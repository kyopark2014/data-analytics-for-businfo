#!/usr/bin/env python3
"""
AWS Infrastructure Installer using boto3
This script creates AWS infrastructure resources defined in cdk/lib/cdk-stack.ts.
CDK deploy is replaced by this boto3 installer (see ref/installer.py for the pattern).

Also provisions async Jobs API (API Gateway + DynamoDB + Lambda worker)
→ AgentCore Harness (PUBLIC, memory disabled) for bus schedule analytics.
"""

import argparse
import io
import json
import logging
import mimetypes
import os
import re
import subprocess
import sys
import time
import uuid
import zipfile
from datetime import datetime
from typing import Dict, List, Optional

import boto3
from botocore.exceptions import ClientError

# Configuration
project_name = "businfo"
region = "us-west-2"
DEFAULT_MODEL_ID = "global.anthropic.claude-sonnet-4-6"

# CreateHarness harnessName: Pattern [a-zA-Z][a-zA-Z0-9_]{0,39} — no hyphens.
_HARNESS_NAME_API_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]{0,39}$")

bucket_name_prefix = "businfo"
bucket_name = ""
stream_name = "businfo-stream"
table_name = "dynamodb-businfo"
jobs_table_name = "dynamodb-businfo-jobs"
glue_database_name = "businfo"
crawler_name = "translate-parquet-crawler"
crawler_role_name = "crawler-role-businfo"
translation_role_name = "businfo-translation-role"
firehose_name = "businfo-delivery-stream"
event_rule_name = "rule-businfo"

lambda_kinesis_name = "lambda-kinesis-businfo"
lambda_firehose_name = "lambda-firehose-businfo"
lambda_businfo_name = "lambda-businfo"
lambda_harness_name = "lambda-harness-businfo"
api_harness_name = "api-harness-businfo"
code_interpreter_name = "businfo_code"

lambda_kinesis_role_name = "lambda-kinesis-businfo-role"
lambda_firehose_role_name = "lambda-firehose-businfo-role"
lambda_businfo_role_name = "lambda-businfo-role"
lambda_harness_role_name = "lambda-harness-businfo-role"
lambda_runtime = "nodejs20.x"
lambda_python_runtime = "python3.12"

script_dir = os.path.dirname(os.path.abspath(__file__))
lambda_base_dir = script_dir

sts_client = boto3.client("sts", region_name=region)
account_id = sts_client.get_caller_identity()["Account"]

s3_client = boto3.client("s3", region_name=region)
iam_client = boto3.client("iam", region_name=region)
kinesis_client = boto3.client("kinesis", region_name=region)
dynamodb_client = boto3.client("dynamodb", region_name=region)
lambda_client = boto3.client("lambda", region_name=region)
events_client = boto3.client("events", region_name=region)
glue_client = boto3.client("glue", region_name=region)
firehose_client = boto3.client("firehose", region_name=region)
apigatewayv2_client = boto3.client("apigatewayv2", region_name=region)
cloudfront_client = boto3.client("cloudfront", region_name="us-east-1")
agentcore_control_client = boto3.client(
    "bedrock-agentcore-control",
    region_name=region,
)

WEB_S3_PREFIX = "web"
HTML_DIR = os.path.join(script_dir, "html")
SKILLS_DIR = os.path.join(script_dir, "skills")
SKILLS_S3_PREFIX = "skills"
DEFAULT_HARNESS_SKILLS = ["businfo"]


def setup_logging(log_level=logging.INFO):
    """Setup logging configuration."""
    log_format = "%(asctime)s - %(levelname)s - %(message)s"
    date_format = "%Y-%m-%d %H:%M:%S"

    logging.basicConfig(
        level=log_level,
        format=log_format,
        datefmt=date_format,
        handlers=[logging.StreamHandler()],
    )

    return logging.getLogger(__name__)


logger = setup_logging()


def wait_for_iam_role(role_name: str, max_wait: int = 30, propagation_delay: int = 10):
    """Wait until IAM role is available and propagated for Lambda."""
    waited = 0
    while waited < max_wait:
        try:
            iam_client.get_role(RoleName=role_name)
            break
        except ClientError:
            time.sleep(2)
            waited += 2
    else:
        logger.warning(f"IAM role {role_name} may not exist yet")
        return

    if propagation_delay:
        logger.debug(
            f"Waiting {propagation_delay}s for IAM role propagation: {role_name}"
        )
        time.sleep(propagation_delay)


def create_iam_role(
    role_name: str,
    assume_role_policy: Dict,
    description: str = "",
    managed_policies: Optional[List[str]] = None,
) -> str:
    """Create IAM role."""
    logger.debug(f"Creating IAM role: {role_name}")

    try:
        response = iam_client.create_role(
            RoleName=role_name,
            AssumeRolePolicyDocument=json.dumps(assume_role_policy),
            Description=description or f"Role for {role_name}",
        )
        role_arn = response["Role"]["Arn"]
        logger.debug(f"Role created: {role_arn}")

        if managed_policies:
            for policy_arn in managed_policies:
                iam_client.attach_role_policy(
                    RoleName=role_name,
                    PolicyArn=policy_arn,
                )

        wait_for_iam_role(role_name)
        logger.info(f"✓ IAM role created: {role_name}")
        return role_arn

    except ClientError as e:
        if e.response["Error"]["Code"] == "EntityAlreadyExists":
            logger.warning(f"IAM role already exists: {role_name}")
            response = iam_client.get_role(RoleName=role_name)
            role_arn = response["Role"]["Arn"]

            iam_client.update_assume_role_policy(
                RoleName=role_name,
                PolicyDocument=json.dumps(assume_role_policy),
            )

            if managed_policies:
                attached = iam_client.list_attached_role_policies(RoleName=role_name)
                current = {p["PolicyArn"] for p in attached["AttachedPolicies"]}
                for policy_arn in managed_policies:
                    if policy_arn not in current:
                        iam_client.attach_role_policy(
                            RoleName=role_name,
                            PolicyArn=policy_arn,
                        )

            wait_for_iam_role(role_name)
            return role_arn
        logger.error(f"Failed to create IAM role {role_name}: {e}")
        raise


def attach_inline_policy(role_name: str, policy_name: str, policy_document: Dict):
    """Attach or update inline policy to IAM role."""
    logger.debug(f"Attaching inline policy {policy_name} to {role_name}")
    iam_client.put_role_policy(
        RoleName=role_name,
        PolicyName=policy_name,
        PolicyDocument=json.dumps(policy_document),
    )


def resolve_bucket_name(acct_id: str, aws_region: str) -> str:
    """Build a globally unique S3 bucket name for this account and region."""
    return f"{bucket_name_prefix}-{acct_id}-{aws_region}".lower()


def load_bucket_name_from_config() -> Optional[str]:
    """Load bucket name from config.json if available."""
    config_path = os.path.join(script_dir, "config.json")
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            content = f.read().strip()
            if not content:
                return None
            data = json.loads(content)
            return data.get("bucketName")
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None


def verify_s3_bucket_access(target_bucket: Optional[str] = None) -> bool:
    """Verify that the S3 bucket exists and is accessible."""
    target_bucket = target_bucket or bucket_name
    try:
        s3_client.head_bucket(Bucket=target_bucket)
        return True
    except ClientError as e:
        error_code = e.response["Error"]["Code"]
        if error_code in ("404", "NoSuchBucket", "NotFound"):
            return False
        raise


def configure_s3_bucket(target_bucket: Optional[str] = None):
    target_bucket = target_bucket or bucket_name
    """Apply standard bucket configuration."""
    s3_client.put_public_access_block(
        Bucket=target_bucket,
        PublicAccessBlockConfiguration={
            "BlockPublicAcls": True,
            "IgnorePublicAcls": True,
            "BlockPublicPolicy": True,
            "RestrictPublicBuckets": True,
        },
    )
    s3_client.put_bucket_versioning(
        Bucket=target_bucket,
        VersioningConfiguration={"Status": "Suspended"},
    )


def create_s3_bucket() -> Dict[str, str]:
    """Create S3 bucket."""
    logger.info(f"[1/11] Creating S3 bucket: {bucket_name}")

    if verify_s3_bucket_access():
        logger.warning(f"S3 bucket already exists: {bucket_name}")
        try:
            configure_s3_bucket()
        except ClientError as e:
            logger.debug(f"Bucket configuration skipped or already applied: {e}")
    else:
        try:
            if region == "us-east-1":
                s3_client.create_bucket(Bucket=bucket_name)
            else:
                s3_client.create_bucket(
                    Bucket=bucket_name,
                    CreateBucketConfiguration={"LocationConstraint": region},
                )
            configure_s3_bucket()
            logger.info(f"✓ S3 bucket created: {bucket_name}")

        except ClientError as e:
            error_code = e.response["Error"]["Code"]
            if error_code == "BucketAlreadyOwnedByYou":
                if not verify_s3_bucket_access():
                    raise RuntimeError(
                        f"S3 bucket '{bucket_name}' is owned by this account but is not "
                        f"accessible in region '{region}'."
                    ) from e
                logger.warning(f"S3 bucket already exists: {bucket_name}")
                try:
                    configure_s3_bucket()
                except ClientError as config_error:
                    logger.debug(
                        f"Bucket configuration skipped or already applied: {config_error}"
                    )
            elif error_code == "BucketAlreadyExists":
                raise RuntimeError(
                    f"S3 bucket name '{bucket_name}' is already taken by another AWS account. "
                    "Use a globally unique bucket name."
                ) from e
            else:
                logger.error(f"Failed to create S3 bucket: {e}")
                raise

    if not verify_s3_bucket_access():
        raise RuntimeError(
            f"S3 bucket '{bucket_name}' is not accessible. "
            f"Verify the bucket exists in region '{region}' and your credentials have access."
        )

    bucket_arn = f"arn:aws:s3:::{bucket_name}"
    return {
        "bucket_name": bucket_name,
        "bucket_arn": bucket_arn,
        "s3_path": f"s3://{bucket_name}",
    }


def create_kinesis_stream() -> str:
    """Create Kinesis data stream."""
    logger.info(f"[2/11] Creating Kinesis stream: {stream_name}")

    try:
        response = kinesis_client.create_stream(
            StreamName=stream_name,
            StreamModeDetails={"StreamMode": "ON_DEMAND"},
        )
        logger.debug(f"Stream creation response: {response}")

        logger.info("Waiting for Kinesis stream to become active...")
        for _ in range(30):
            desc = kinesis_client.describe_stream(StreamName=stream_name)
            status = desc["StreamDescription"]["StreamStatus"]
            if status == "ACTIVE":
                break
            time.sleep(2)
        else:
            raise TimeoutError(f"Kinesis stream {stream_name} did not become ACTIVE in time")

        stream_arn = desc["StreamDescription"]["StreamARN"]
        logger.info(f"✓ Kinesis stream created: {stream_arn}")
        return stream_arn

    except ClientError as e:
        if e.response["Error"]["Code"] == "ResourceInUseException":
            logger.warning(f"Kinesis stream already exists: {stream_name}")
            desc = kinesis_client.describe_stream(StreamName=stream_name)
            return desc["StreamDescription"]["StreamARN"]
        logger.error(f"Failed to create Kinesis stream: {e}")
        raise


def wait_for_dynamodb_table_active():
    """Wait until DynamoDB table becomes ACTIVE."""
    logger.info("Waiting for DynamoDB table to become active...")
    waiter = dynamodb_client.get_waiter("table_exists")
    waiter.wait(TableName=table_name)
    for _ in range(30):
        response = dynamodb_client.describe_table(TableName=table_name)
        if response["Table"]["TableStatus"] == "ACTIVE":
            return response["Table"]["TableArn"]
        time.sleep(2)
    raise TimeoutError(f"DynamoDB table {table_name} did not become ACTIVE in time")


def enable_dynamodb_kinesis_streaming(stream_arn: str):
    """Enable Kinesis streaming destination on DynamoDB table."""
    try:
        response = dynamodb_client.describe_kinesis_streaming_destination(
            TableName=table_name
        )
        for dest in response.get("KinesisDataStreamDestinations", []):
            if dest.get("StreamArn") == stream_arn and dest.get("DestinationStatus") in (
                "ACTIVE",
                "ENABLING",
            ):
                logger.warning("DynamoDB Kinesis streaming destination already enabled")
                return
    except ClientError as e:
        if e.response["Error"]["Code"] not in (
            "ResourceNotFoundException",
            "ValidationException",
        ):
            raise

    try:
        dynamodb_client.enable_kinesis_streaming_destination(
            TableName=table_name,
            StreamArn=stream_arn,
        )
        logger.info(f"✓ DynamoDB Kinesis streaming enabled: {stream_arn}")
    except ClientError as e:
        if e.response["Error"]["Code"] in (
            "ResourceInUseException",
            "ValidationException",
        ):
            logger.warning("DynamoDB Kinesis streaming destination already enabled")
            return
        raise


def create_dynamodb_table(stream_arn: str) -> str:
    """Create DynamoDB table with Kinesis streaming."""
    logger.info(f"[3/11] Creating DynamoDB table: {table_name}")

    try:
        dynamodb_client.create_table(
            TableName=table_name,
            KeySchema=[
                {"AttributeName": "RouteId", "KeyType": "HASH"},
                {"AttributeName": "Timestamp", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "RouteId", "AttributeType": "S"},
                {"AttributeName": "Timestamp", "AttributeType": "S"},
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        table_arn = wait_for_dynamodb_table_active()
        logger.info(f"✓ DynamoDB table created: {table_arn}")

    except ClientError as e:
        if e.response["Error"]["Code"] == "ResourceInUseException":
            logger.warning(f"DynamoDB table already exists: {table_name}")
            table_arn = wait_for_dynamodb_table_active()
        else:
            logger.error(f"Failed to create DynamoDB table: {e}")
            raise

    enable_dynamodb_kinesis_streaming(stream_arn)
    return table_arn


def ensure_lambda_dependencies(source_dir: str, packages: List[str]):
    """Install missing npm packages required by Lambda source code."""
    node_modules = os.path.join(source_dir, "node_modules")
    missing = [
        pkg for pkg in packages
        if not os.path.isdir(os.path.join(node_modules, pkg))
    ]
    if not missing:
        return

    logger.info(f"Installing missing Lambda dependencies: {', '.join(missing)}")
    subprocess.run(
        ["npm", "install", "--no-save", *missing],
        cwd=source_dir,
        check=True,
    )


def package_lambda(
    source_dir: str,
    include_node_modules: bool = False,
    pip_packages: Optional[List[str]] = None,
) -> bytes:
    """Package Lambda function source into a zip archive."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        if include_node_modules:
            for root, dirs, files in os.walk(source_dir):
                dirs[:] = [d for d in dirs if not d.startswith(".")]
                for filename in files:
                    if filename.startswith("."):
                        continue
                    filepath = os.path.join(root, filename)
                    arcname = os.path.relpath(filepath, source_dir)
                    zf.write(filepath, arcname)
        else:
            py_handler = os.path.join(source_dir, "lambda_function.py")
            index_path = os.path.join(source_dir, "index.js")
            if os.path.isfile(py_handler):
                for filename in sorted(os.listdir(source_dir)):
                    if not filename.endswith(".py"):
                        continue
                    filepath = os.path.join(source_dir, filename)
                    if os.path.isfile(filepath):
                        zf.write(filepath, filename)
            elif os.path.isfile(index_path):
                zf.write(index_path, "index.js")
            else:
                raise FileNotFoundError(
                    f"No lambda_function.py or index.js in {source_dir}"
                )

        if pip_packages:
            import tempfile

            with tempfile.TemporaryDirectory(prefix="lambda-pip-") as tmp:
                logger.info(
                    f"  Bundling pip packages for Lambda: {', '.join(pip_packages)}"
                )
                subprocess.run(
                    [
                        sys.executable,
                        "-m",
                        "pip",
                        "install",
                        "--quiet",
                        "--upgrade",
                        "--target",
                        tmp,
                        *pip_packages,
                    ],
                    check=True,
                )
                for root, dirs, files in os.walk(tmp):
                    dirs[:] = [
                        d
                        for d in dirs
                        if d not in {"__pycache__", "*.dist-info"}
                        and not d.endswith(".dist-info")
                    ]
                    for filename in files:
                        if filename.endswith((".pyc", ".pyo")):
                            continue
                        filepath = os.path.join(root, filename)
                        arcname = os.path.relpath(filepath, tmp)
                        if "__pycache__" in arcname.split(os.sep):
                            continue
                        zf.write(filepath, arcname.replace(os.sep, "/"))

    buffer.seek(0)
    return buffer.read()


def harness_name_for_api(name: str) -> str:
    """Map projectName to CreateHarness harnessName (hyphens → underscores)."""
    normalized = (name or "").replace("-", "_")
    if not _HARNESS_NAME_API_RE.fullmatch(normalized):
        logger.error(
            "CreateHarness harnessName must match [a-zA-Z][a-zA-Z0-9_]{0,39} "
            f"(after '-'→'_'): got {normalized!r} from projectName={name!r}"
        )
        sys.exit(1)
    return normalized


def get_max_output_tokens(model_id: str = "") -> int:
    """Return max output tokens per Amazon Bedrock Anthropic Claude model cards."""
    mid = model_id.lower()
    if "claude-opus-4-7" in mid or "claude-opus-4-6" in mid:
        return 128000
    if "claude-opus-4-5" in mid:
        return 64000
    if "claude-opus-4" in mid or "claude-4-opus" in mid:
        return 128000
    if "claude-sonnet-4" in mid or "claude-4-sonnet" in mid or "claude-haiku-4" in mid:
        return 64000
    return 8192


BASE_SYSTEM_PROMPT = (
    "당신은 버스 정류장 도착·지연 데이터를 분석하는 분석 에이전트입니다.\n"
    "한국어로 답변하세요.\n"
    "모르는 내용은 추측하지 말고 모른다고 말하세요.\n"
    "\n"
    "## 데이터\n"
    f"- Glue Data Catalog 데이터베이스: `{glue_database_name}`\n"
    "- 원본 데이터는 S3(businfo 버킷)에 저장되어 있으며 Amazon Athena로 조회합니다.\n"
    "- 센터필드 정류장 버스 도착 예상시간·지연 패턴 분석에 집중하세요.\n"
    "\n"
    "## Skills (businfo)\n"
    "- 버스 도착·잔여좌석·노선/차량 조회는 반드시 **businfo** skill CLI를 사용하세요.\n"
    "- code 인터프리터에는 skill 파일이 미리 마운트되지 않을 수 있습니다. 실행 전 S3에서 동기화하세요:\n"
    f"  `aws s3 sync s3://businfo-{account_id}-{region}/skills/businfo/ /tmp/businfo/`\n"
    "- 이후: `python /tmp/businfo/scripts/query_businfo.py recent|plate|route|summary ...`\n"
    "- ad-hoc Athena SQL을 새로 짜지 마세요.\n"
    "\n"
    "## 도구\n"
    "- code 인터프리터로 skill 스크립트 동기화·실행·집계를 수행하세요.\n"
    "- 필요 시 aws_knowledge로 AWS 서비스 문서를 참고하세요.\n"
    "- 결과는 수치와 근거를 포함한 짧은 요약으로 제시하세요.\n"
)


def create_lambda_execution_role(role_name: str, extra_policies: Optional[List[Dict]] = None) -> str:
    """Create Lambda execution IAM role."""
    assume_role_policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Principal": {"Service": "lambda.amazonaws.com"},
                "Action": "sts:AssumeRole",
            }
        ],
    }

    role_arn = create_iam_role(
        role_name,
        assume_role_policy,
        managed_policies=[
            "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
        ],
    )

    if extra_policies:
        for policy in extra_policies:
            attach_inline_policy(role_name, policy["name"], policy["document"])

    return role_arn


def lambda_function_exists(function_name: str) -> bool:
    """Check whether a Lambda function already exists."""
    try:
        lambda_client.get_function(FunctionName=function_name)
        return True
    except ClientError as e:
        if e.response["Error"]["Code"] == "ResourceNotFoundException":
            return False
        raise


def wait_for_lambda_function_ready(function_name: str):
    """Wait until Lambda function update completes."""
    logger.debug(f"Waiting for Lambda function update: {function_name}")
    waiter = lambda_client.get_waiter("function_updated")
    waiter.wait(FunctionName=function_name)


def update_lambda_function_configuration(
    function_name: str,
    role_arn: str,
    handler: str,
    runtime: str,
    description: str,
    timeout: int,
    memory_size: int = 128,
    environment: Optional[Dict[str, str]] = None,
    max_retries: int = 6,
):
    """Update Lambda configuration with retry while function update is in progress."""
    update_kwargs = {
        "FunctionName": function_name,
        "Role": role_arn,
        "Handler": handler,
        "Runtime": runtime,
        "Description": description,
        "Timeout": timeout,
        "MemorySize": memory_size,
    }
    if environment:
        update_kwargs["Environment"] = {"Variables": environment}

    for attempt in range(max_retries):
        try:
            lambda_client.update_function_configuration(**update_kwargs)
            return
        except ClientError as e:
            error_code = e.response["Error"]["Code"]
            error_message = e.response["Error"].get("Message", "")
            if (
                error_code == "ResourceConflictException"
                and "update is in progress" in error_message
                and attempt < max_retries - 1
            ):
                wait_time = 5 * (attempt + 1)
                logger.warning(
                    f"Lambda update in progress for {function_name}, "
                    f"retrying configuration update in {wait_time}s "
                    f"({attempt + 1}/{max_retries})"
                )
                time.sleep(wait_time)
                wait_for_lambda_function_ready(function_name)
                continue
            raise


def deploy_lambda_function(
    function_name: str,
    role_arn: str,
    source_dir: str,
    description: str,
    handler: str = "index.handler",
    runtime: str = lambda_runtime,
    timeout: int = 3,
    memory_size: int = 128,
    environment: Optional[Dict[str, str]] = None,
    include_node_modules: bool = False,
    pip_packages: Optional[List[str]] = None,
) -> str:
    """Create or update Lambda function."""
    logger.info(f"Deploying Lambda function: {function_name}")

    zip_bytes = package_lambda(
        source_dir,
        include_node_modules=include_node_modules,
        pip_packages=pip_packages,
    )
    function_exists = lambda_function_exists(function_name)

    if not function_exists:
        create_kwargs = {
            "FunctionName": function_name,
            "Runtime": runtime,
            "Role": role_arn,
            "Handler": handler,
            "Code": {"ZipFile": zip_bytes},
            "Description": description,
            "Timeout": timeout,
            "MemorySize": memory_size,
        }
        if environment:
            create_kwargs["Environment"] = {"Variables": environment}

        max_retries = 6
        for attempt in range(max_retries):
            try:
                response = lambda_client.create_function(**create_kwargs)
                function_arn = response["FunctionArn"]
                logger.info(f"✓ Lambda function created: {function_arn}")
                return function_arn

            except ClientError as e:
                error_code = e.response["Error"]["Code"]
                error_message = e.response["Error"].get("Message", "")

                if (
                    error_code == "ResourceConflictException"
                    and "already exist" in error_message.lower()
                ):
                    function_exists = True
                    break

                if (
                    error_code == "InvalidParameterValueException"
                    and "cannot be assumed by Lambda" in error_message
                    and attempt < max_retries - 1
                ):
                    wait_time = 5 * (attempt + 1)
                    logger.warning(
                        f"IAM role not yet assumable by Lambda, retrying in {wait_time}s "
                        f"({attempt + 1}/{max_retries})"
                    )
                    time.sleep(wait_time)
                    continue

                logger.error(f"Failed to deploy Lambda function {function_name}: {e}")
                raise
        else:
            raise RuntimeError(f"Failed to deploy Lambda function {function_name}")

    logger.warning(f"Lambda function already exists, updating: {function_name}")
    lambda_client.update_function_code(
        FunctionName=function_name,
        ZipFile=zip_bytes,
    )
    wait_for_lambda_function_ready(function_name)
    update_lambda_function_configuration(
        function_name=function_name,
        role_arn=role_arn,
        handler=handler,
        runtime=runtime,
        description=description,
        timeout=timeout,
        memory_size=memory_size,
        environment=environment,
    )
    wait_for_lambda_function_ready(function_name)

    response = lambda_client.get_function(FunctionName=function_name)
    function_arn = response["Configuration"]["FunctionArn"]
    logger.info(f"✓ Lambda function updated: {function_arn}")
    return function_arn


def create_lambda_kinesis(stream_arn: str) -> str:
    """Create Lambda function for Kinesis stream processing."""
    logger.info(f"[4/11] Creating Lambda: {lambda_kinesis_name}")

    kinesis_policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Action": [
                    "kinesis:DescribeStreamSummary",
                    "kinesis:GetRecords",
                    "kinesis:GetShardIterator",
                    "kinesis:ListShards",
                    "kinesis:SubscribeToShard",
                    "kinesis:DescribeStream",
                    "kinesis:ListStreams",
                ],
                "Resource": stream_arn,
            }
        ],
    }

    role_arn = create_lambda_execution_role(
        lambda_kinesis_role_name,
        extra_policies=[{"name": "kinesis-read-policy", "document": kinesis_policy}],
    )

    source_dir = os.path.join(lambda_base_dir, "lambda-kinesis-stream")
    return deploy_lambda_function(
        function_name=lambda_kinesis_name,
        role_arn=role_arn,
        source_dir=source_dir,
        description="get eventinfo from kinesis data stream",
        timeout=3,
    )


def create_lambda_firehose() -> str:
    """Create Lambda function for Firehose data transformation."""
    logger.info(f"[5/11] Creating Lambda: {lambda_firehose_name}")

    role_arn = create_lambda_execution_role(lambda_firehose_role_name)

    source_dir = os.path.join(lambda_base_dir, "lambda-kinesis-firehose")
    return deploy_lambda_function(
        function_name=lambda_firehose_name,
        role_arn=role_arn,
        source_dir=source_dir,
        description="update event sources",
        timeout=3,
    )


def create_lambda_businfo(table_arn: str) -> str:
    """Create Lambda function for bus info collection."""
    logger.info(f"[6/11] Creating Lambda: {lambda_businfo_name}")

    dynamodb_policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Action": [
                    "dynamodb:BatchGetItem",
                    "dynamodb:GetRecords",
                    "dynamodb:GetShardIterator",
                    "dynamodb:Query",
                    "dynamodb:GetItem",
                    "dynamodb:Scan",
                    "dynamodb:ConditionCheckItem",
                    "dynamodb:BatchWriteItem",
                    "dynamodb:PutItem",
                    "dynamodb:UpdateItem",
                    "dynamodb:DeleteItem",
                    "dynamodb:DescribeTable",
                ],
                "Resource": table_arn,
            }
        ],
    }

    role_arn = create_lambda_execution_role(
        lambda_businfo_role_name,
        extra_policies=[{"name": "dynamodb-access-policy", "document": dynamodb_policy}],
    )

    source_dir = os.path.join(lambda_base_dir, "lambda-businfo")
    ensure_lambda_dependencies(source_dir, ["aws-sdk"])
    return deploy_lambda_function(
        function_name=lambda_businfo_name,
        role_arn=role_arn,
        source_dir=source_dir,
        description="Lambda for businfo",
        timeout=10,
        environment={"tableName": table_name},
        include_node_modules=True,
    )


def create_kinesis_event_source(function_arn: str, stream_arn: str):
    """Connect Lambda to Kinesis stream."""
    logger.info(f"[7/11] Creating Kinesis event source mapping")

    try:
        mappings = lambda_client.list_event_source_mappings(
            FunctionName=function_arn,
        )
        for mapping in mappings.get("EventSourceMappings", []):
            if mapping.get("EventSourceArn") == stream_arn:
                logger.warning("Kinesis event source mapping already exists")
                return mapping["UUID"]

        response = lambda_client.create_event_source_mapping(
            EventSourceArn=stream_arn,
            FunctionName=function_arn,
            StartingPosition="TRIM_HORIZON",
            BatchSize=100,
        )
        logger.info(f"✓ Kinesis event source mapping created: {response['UUID']}")
        return response["UUID"]

    except ClientError as e:
        logger.error(f"Failed to create Kinesis event source mapping: {e}")
        raise


def create_eventbridge_rule(function_arn: str) -> str:
    """Create EventBridge rule to trigger Lambda on schedule."""
    logger.info(f"[8/11] Creating EventBridge rule: {event_rule_name}")

    rule_arn = f"arn:aws:events:{region}:{account_id}:rule/{event_rule_name}"

    try:
        events_client.put_rule(
            Name=event_rule_name,
            ScheduleExpression="rate(1 minute)",
            State="ENABLED",
            Description="Schedule a Lambda to save arrival time of buses",
        )

        events_client.put_targets(
            Rule=event_rule_name,
            Targets=[{"Id": "Target0", "Arn": function_arn}],
        )

        try:
            lambda_client.add_permission(
                FunctionName=lambda_businfo_name,
                StatementId=f"eventbridge-{event_rule_name}",
                Action="lambda:InvokeFunction",
                Principal="events.amazonaws.com",
                SourceArn=rule_arn,
            )
        except ClientError as e:
            if e.response["Error"]["Code"] != "ResourceConflictException":
                raise

        logger.info(f"✓ EventBridge rule created: {rule_arn}")
        return rule_arn

    except ClientError as e:
        logger.error(f"Failed to create EventBridge rule: {e}")
        raise


def create_crawler_role(bucket_arn: str) -> str:
    """Create IAM role for Glue crawler."""
    logger.info(f"[9/11] Creating Glue crawler role: {crawler_role_name}")

    assume_role_policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Principal": {"Service": "glue.amazonaws.com"},
                "Action": "sts:AssumeRole",
            }
        ],
    }

    role_arn = create_iam_role(
        crawler_role_name,
        assume_role_policy,
        description="Role for parquet translation",
        managed_policies=[
            "arn:aws:iam::aws:policy/service-role/AWSGlueServiceRole"
        ],
    )

    s3_policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Action": [
                    "s3:AbortMultipartUpload",
                    "s3:GetBucketLocation",
                    "s3:GetObject",
                    "s3:ListBucket",
                    "s3:ListBucketMultipartUploads",
                    "s3:PutObject",
                ],
                "Resource": [bucket_arn, f"{bucket_arn}/*"],
            }
        ],
    }
    attach_inline_policy(crawler_role_name, "crawler-s3-policy", s3_policy)

    return role_arn


def ensure_s3_prefix(prefix: str, target_bucket: Optional[str] = None):
    target_bucket = target_bucket or bucket_name
    """Create S3 prefix placeholder required by Glue crawler validation."""
    if not verify_s3_bucket_access(target_bucket):
        raise RuntimeError(
            f"S3 bucket '{target_bucket}' is not accessible in region '{region}'. "
            "Cannot create prefix placeholder for Glue crawler."
        )

    key = prefix if prefix.endswith("/") else f"{prefix}/"
    logger.info(f"Ensuring S3 prefix exists: s3://{target_bucket}/{key}")
    s3_client.put_object(Bucket=target_bucket, Key=key, Body=b"")


def create_glue_database():
    """Create Glue database."""
    logger.info(f"Creating Glue database: {glue_database_name}")

    try:
        glue_client.create_database(
            DatabaseInput={"Name": glue_database_name}
        )
        logger.info(f"✓ Glue database created: {glue_database_name}")

    except ClientError as e:
        if e.response["Error"]["Code"] == "AlreadyExistsException":
            logger.warning(f"Glue database already exists: {glue_database_name}")
        else:
            logger.error(f"Failed to create Glue database: {e}")
            raise


def create_glue_crawler(
    crawler_role_arn: str, s3_path: str, target_bucket: Optional[str] = None
):
    target_bucket = target_bucket or bucket_name
    """Create Glue crawler."""
    logger.info(f"Creating Glue crawler: {crawler_name}")

    ensure_s3_prefix("businfo", target_bucket=target_bucket)

    try:
        glue_client.create_crawler(
            Name=crawler_name,
            Role=crawler_role_arn,
            DatabaseName=glue_database_name,
            Targets={"S3Targets": [{"Path": f"{s3_path}/businfo"}]},
            SchemaChangePolicy={"DeleteBehavior": "DELETE_FROM_DATABASE"},
        )
        logger.info(f"✓ Glue crawler created: {crawler_name}")

    except ClientError as e:
        if e.response["Error"]["Code"] == "AlreadyExistsException":
            logger.warning(f"Glue crawler already exists: {crawler_name}")
            glue_client.update_crawler(
                Name=crawler_name,
                Role=crawler_role_arn,
                DatabaseName=glue_database_name,
                Targets={"S3Targets": [{"Path": f"{s3_path}/businfo"}]},
                SchemaChangePolicy={"DeleteBehavior": "DELETE_FROM_DATABASE"},
            )
            logger.info(f"✓ Glue crawler updated: {crawler_name}")
        else:
            logger.error(f"Failed to create Glue crawler: {e}")
            raise


def create_translation_role(bucket_arn: str, lambda_firehose_arn: str) -> str:
    """Create IAM role for Kinesis Firehose."""
    logger.info(f"[10/11] Creating Firehose translation role: {translation_role_name}")

    assume_role_policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Principal": {"Service": "firehose.amazonaws.com"},
                "Action": "sts:AssumeRole",
            }
        ],
    }

    role_arn = create_iam_role(
        translation_role_name,
        assume_role_policy,
        description="TraslationRole",
        managed_policies=[
            "arn:aws:iam::aws:policy/AWSLambdaExecute",
            "arn:aws:iam::aws:policy/service-role/AWSLambdaKinesisExecutionRole",
            "arn:aws:iam::aws:policy/service-role/AWSGlueServiceRole",
        ],
    )

    inline_policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Action": [
                    "s3:AbortMultipartUpload",
                    "s3:GetBucketLocation",
                    "s3:GetObject",
                    "s3:ListBucket",
                    "s3:ListBucketMultipartUploads",
                    "s3:PutObject",
                ],
                "Resource": [bucket_arn, f"{bucket_arn}/*"],
            },
            {
                "Effect": "Allow",
                "Action": [
                    "lambda:InvokeFunction",
                    "lambda:GetFunctionConfiguration",
                ],
                "Resource": [lambda_firehose_arn, f"{lambda_firehose_arn}:*"],
            },
            {
                "Effect": "Allow",
                "Action": [
                    "glue:GetTable",
                    "glue:GetTableVersion",
                    "glue:GetTableVersions",
                ],
                "Resource": "*",
            },
        ],
    }
    attach_inline_policy(translation_role_name, "translation-policy", inline_policy)

    return role_arn


def create_firehose_delivery_stream(
    stream_arn: str,
    bucket_arn: str,
    translation_role_arn: str,
    lambda_firehose_arn: str,
) -> str:
    """Create Kinesis Firehose delivery stream."""
    logger.info(f"[11/11] Creating Firehose delivery stream: {firehose_name}")

    config = {
        "RoleARN": translation_role_arn,
        "BucketARN": bucket_arn,
        "Prefix": "businfo/",
        "ErrorOutputPrefix": "eror/",
        "BufferingHints": {
            "SizeInMBs": 128,
            "IntervalInSeconds": 60,
        },
        "CompressionFormat": "UNCOMPRESSED",
        "EncryptionConfiguration": {"NoEncryptionConfig": "NoEncryption"},
        "ProcessingConfiguration": {
            "Enabled": True,
            "Processors": [
                {
                    "Type": "Lambda",
                    "Parameters": [
                        {
                            "ParameterName": "LambdaArn",
                            "ParameterValue": lambda_firehose_arn,
                        }
                    ],
                }
            ],
        },
        "DataFormatConversionConfiguration": {
            "Enabled": False,
            "SchemaConfiguration": {
                "RoleARN": translation_role_arn,
                "DatabaseName": glue_database_name,
                "TableName": "businfo",
            },
        },
    }

    try:
        response = firehose_client.create_delivery_stream(
            DeliveryStreamName=firehose_name,
            DeliveryStreamType="KinesisStreamAsSource",
            KinesisStreamSourceConfiguration={
                "KinesisStreamARN": stream_arn,
                "RoleARN": translation_role_arn,
            },
            ExtendedS3DestinationConfiguration=config,
        )
        delivery_stream_arn = response["DeliveryStreamARN"]
        logger.info(f"✓ Firehose delivery stream created: {delivery_stream_arn}")
        return delivery_stream_arn

    except ClientError as e:
        if e.response["Error"]["Code"] == "ResourceInUseException":
            logger.warning(f"Firehose delivery stream already exists: {firehose_name}")
            response = firehose_client.describe_delivery_stream(
                DeliveryStreamName=firehose_name
            )
            return response["DeliveryStreamDescription"]["DeliveryStreamARN"]
        logger.error(f"Failed to create Firehose delivery stream: {e}")
        raise


def create_harness_execution_role(s3_bucket: str) -> str:
    """Create IAM execution role for Bedrock AgentCore harness (PUBLIC, no memory)."""
    logger.info("Creating Harness execution IAM role")
    role_name = f"role-harness-for-{project_name}-{region}"
    if len(role_name) > 64:
        logger.error(
            f"IAM RoleName exceeds 64 characters ({len(role_name)}): {role_name!r}"
        )
        sys.exit(1)

    assume_role_policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "AllowAgentCoreAssumeHarness",
                "Effect": "Allow",
                "Principal": {"Service": "bedrock-agentcore.amazonaws.com"},
                "Action": "sts:AssumeRole",
            }
        ],
    }

    # Track whether role was newly created for propagation wait
    role_created = False
    try:
        iam_client.get_role(RoleName=role_name)
    except ClientError as e:
        if e.response["Error"]["Code"] == "NoSuchEntity":
            role_created = True
        else:
            raise

    role_arn = create_iam_role(
        role_name,
        assume_role_policy,
        description="Execution role for Bedrock AgentCore harness (businfo analytics)",
    )

    harness_execution_policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "BedrockModelInvocation",
                "Effect": "Allow",
                "Action": [
                    "bedrock:InvokeModel",
                    "bedrock:InvokeModelWithResponseStream",
                    "bedrock:GetInferenceProfile",
                    "bedrock:GetFoundationModel",
                ],
                "Resource": [
                    "arn:aws:bedrock:*::foundation-model/*",
                    f"arn:aws:bedrock:{region}:{account_id}:inference-profile/*",
                ],
            },
            {
                "Sid": "AgentCoreAccess",
                "Effect": "Allow",
                "Action": ["bedrock-agentcore:*"],
                "Resource": ["*"],
            },
            {
                "Sid": "CloudWatchLogsAgentCore",
                "Effect": "Allow",
                "Action": [
                    "logs:CreateLogGroup",
                    "logs:CreateLogStream",
                    "logs:PutLogEvents",
                    "logs:DescribeLogStreams",
                ],
                "Resource": [
                    f"arn:aws:logs:{region}:{account_id}:log-group:/aws/bedrock-agentcore/*",
                ],
            },
            {
                "Sid": "EcrManagedImagePull",
                "Effect": "Allow",
                "Action": [
                    "ecr:BatchGetImage",
                    "ecr:GetDownloadUrlForLayer",
                    "ecr:BatchCheckLayerAvailability",
                ],
                "Resource": [f"arn:aws:ecr:{region}:*:repository/harness-*"],
            },
            {
                "Sid": "EcrManagedImageToken",
                "Effect": "Allow",
                "Action": ["ecr:GetAuthorizationToken"],
                "Resource": ["*"],
            },
            {
                "Sid": "BusinfoS3Read",
                "Effect": "Allow",
                "Action": ["s3:ListBucket", "s3:GetBucketLocation"],
                "Resource": [f"arn:aws:s3:::{s3_bucket}"],
            },
            {
                "Sid": "BusinfoS3GetObject",
                "Effect": "Allow",
                "Action": ["s3:GetObject"],
                "Resource": [f"arn:aws:s3:::{s3_bucket}/*"],
            },
            {
                "Sid": "AthenaQuery",
                "Effect": "Allow",
                "Action": [
                    "athena:StartQueryExecution",
                    "athena:GetQueryExecution",
                    "athena:GetQueryResults",
                    "athena:StopQueryExecution",
                    "athena:GetWorkGroup",
                    "athena:ListWorkGroups",
                ],
                "Resource": ["*"],
            },
            {
                "Sid": "GlueCatalogReadWritePartition",
                "Effect": "Allow",
                "Action": [
                    "glue:GetDatabase",
                    "glue:GetDatabases",
                    "glue:GetTable",
                    "glue:GetTables",
                    "glue:GetPartition",
                    "glue:GetPartitions",
                    "glue:BatchGetPartition",
                    "glue:CreatePartition",
                    "glue:BatchCreatePartition",
                    "glue:UpdatePartition",
                    "glue:BatchUpdatePartition",
                ],
                "Resource": ["*"],
            },
            {
                "Sid": "AthenaResultsS3",
                "Effect": "Allow",
                "Action": [
                    "s3:GetBucketLocation",
                    "s3:ListBucket",
                    "s3:GetObject",
                    "s3:PutObject",
                    "s3:AbortMultipartUpload",
                ],
                "Resource": [
                    f"arn:aws:s3:::aws-athena-query-results-{account_id}-{region}",
                    f"arn:aws:s3:::aws-athena-query-results-{account_id}-{region}/*",
                ],
            },
            {
                "Sid": "SkillsS3Read",
                "Effect": "Allow",
                "Action": ["s3:ListBucket"],
                "Resource": [f"arn:aws:s3:::{s3_bucket}"],
                "Condition": {
                    "StringLike": {"s3:prefix": [f"{SKILLS_S3_PREFIX}/*"]}
                },
            },
            {
                "Sid": "SkillsS3GetObject",
                "Effect": "Allow",
                "Action": ["s3:GetObject"],
                "Resource": [f"arn:aws:s3:::{s3_bucket}/{SKILLS_S3_PREFIX}/*"],
            },
        ],
    }

    attach_inline_policy(
        role_name,
        f"harness-exec-inline-for-{project_name}",
        harness_execution_policy,
    )
    if role_created:
        wait_seconds = 20
        logger.info(
            f"  Waiting {wait_seconds}s for IAM role/policy propagation "
            "before CreateHarness..."
        )
        time.sleep(wait_seconds)
    logger.info(f"✓ Harness execution role ready: {role_arn}")
    return role_arn


def _paginate_list_harnesses() -> List[Dict]:
    items: List[Dict] = []
    token = None
    while True:
        kw: Dict = {"maxResults": 50}
        if token:
            kw["nextToken"] = token
        resp = agentcore_control_client.list_harnesses(**kw)
        items.extend(resp.get("harnesses") or [])
        token = resp.get("nextToken")
        if not token:
            break
    return items


def find_harness_by_api_name(harness_api_name: str) -> Optional[Dict]:
    for h in _paginate_list_harnesses():
        if h.get("harnessName") == harness_api_name:
            return h
    return None


def wait_for_harness_ready(harness_id: str, timeout_seconds: int = 300) -> str:
    """Poll until harness reaches READY; return harness ARN."""
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        res = agentcore_control_client.get_harness(harnessId=harness_id)
        h = res["harness"]
        status = h["status"]
        if status == "READY":
            harness_arn = h["arn"]
            logger.info(f"✓ Harness ready: {harness_arn}")
            return harness_arn
        if status in (
            "FAILED",
            "CREATE_FAILED",
            "UPDATE_FAILED",
            "DELETING",
            "DELETE_UNSUCCESSFUL",
            "DELETE_FAILED",
        ):
            reason = h.get("failureReason") or h.get("statusReason") or ""
            raise RuntimeError(
                f"Harness {harness_id} entered terminal status: {status}"
                + (f" — {reason}" if reason else "")
            )
        logger.info(f"  Waiting for harness ({harness_id}) status: {status}")
        time.sleep(5)
    raise TimeoutError(
        f"Harness {harness_id} did not reach READY within {timeout_seconds}s"
    )


def update_harness_safe(harness_id: str, *, timeout_seconds: int = 600, **kwargs) -> None:
    """UpdateHarness only when READY; retry on ConflictException."""
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        remaining = max(30, int(deadline - time.time()))
        wait_for_harness_ready(harness_id, timeout_seconds=remaining)
        try:
            agentcore_control_client.update_harness(harnessId=harness_id, **kwargs)
            return
        except ClientError as e:
            code = (e.response.get("Error") or {}).get("Code", "")
            msg = (e.response.get("Error") or {}).get("Message", "")
            if code != "ConflictException" and "while it is UPDATING" not in msg:
                raise
            logger.warning(
                "  UpdateHarness ConflictException; waiting and retrying..."
            )
            time.sleep(8)
    raise TimeoutError(
        f"Timed out updating harness {harness_id} within {timeout_seconds}s"
    )


def _default_harness_tools(code_interpreter_arn: str = "") -> List[Dict]:
    code_config: Dict = {"agentCoreCodeInterpreter": {}}
    if code_interpreter_arn:
        code_config = {
            "agentCoreCodeInterpreter": {
                "codeInterpreterArn": code_interpreter_arn,
            }
        }
    return [
        {
            "type": "remote_mcp",
            "name": "aws_knowledge",
            "config": {
                "remoteMcp": {
                    "url": "https://knowledge-mcp.global.api.aws",
                }
            },
        },
        {
            "type": "agentcore_code_interpreter",
            "name": "code",
            "config": code_config,
        },
    ]


def _paginate_list_code_interpreters() -> List[Dict]:
    items: List[Dict] = []
    token = None
    while True:
        kw: Dict = {"maxResults": 50}
        if token:
            kw["nextToken"] = token
        resp = agentcore_control_client.list_code_interpreters(**kw)
        items.extend(resp.get("codeInterpreterSummaries") or [])
        token = resp.get("nextToken")
        if not token:
            break
    return items


def wait_for_code_interpreter_ready(
    code_interpreter_id: str,
    timeout_seconds: int = 300,
) -> str:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        detail = agentcore_control_client.get_code_interpreter(
            codeInterpreterId=code_interpreter_id
        )
        status = detail.get("status")
        if status == "READY":
            arn = detail["codeInterpreterArn"]
            logger.info(f"✓ Code Interpreter ready: {arn}")
            return arn
        if status in ("FAILED", "DELETE_FAILED", "DELETED"):
            reason = detail.get("failureReason") or ""
            raise RuntimeError(
                f"Code Interpreter {code_interpreter_id} status={status}"
                + (f" — {reason}" if reason else "")
            )
        logger.info(
            f"  Waiting for Code Interpreter ({code_interpreter_id}) status: {status}"
        )
        time.sleep(5)
    raise TimeoutError(
        f"Code Interpreter {code_interpreter_id} not READY within {timeout_seconds}s"
    )


def create_or_get_code_interpreter(execution_role_arn: str) -> Dict[str, str]:
    """Custom Code Interpreter with IAM role (Athena/S3 access for businfo skill)."""
    logger.info(f"Creating Code Interpreter: {code_interpreter_name}")
    existing_id = ""
    for item in _paginate_list_code_interpreters():
        if item.get("name") == code_interpreter_name:
            existing_id = item.get("codeInterpreterId") or ""
            break

    if existing_id:
        logger.info(
            f"  Code Interpreter {code_interpreter_name!r} exists "
            f"(id={existing_id}); reusing"
        )
        arn = wait_for_code_interpreter_ready(existing_id)
        # Keep execution role in sync when possible (no Update API on some accounts)
        detail = agentcore_control_client.get_code_interpreter(
            codeInterpreterId=existing_id
        )
        current_role = detail.get("executionRoleArn") or ""
        if current_role and current_role != execution_role_arn:
            logger.warning(
                f"  Code Interpreter role differs "
                f"(current={current_role}, desired={execution_role_arn}); "
                "recreate manually if Athena access fails"
            )
        return {
            "code_interpreter_id": existing_id,
            "code_interpreter_arn": arn,
            "code_interpreter_name": code_interpreter_name,
        }

    response = agentcore_control_client.create_code_interpreter(
        name=code_interpreter_name,
        description="Businfo Athena/S3 code interpreter for AgentCore Harness",
        executionRoleArn=execution_role_arn,
        networkConfiguration={"networkMode": "PUBLIC"},
        clientToken=str(uuid.uuid4()),
        tags={"Project": project_name, "Env": "dev"},
    )
    code_interpreter_id = response["codeInterpreterId"]
    logger.info(f"  ✓ Code Interpreter created: {code_interpreter_id}")
    arn = wait_for_code_interpreter_ready(code_interpreter_id)
    return {
        "code_interpreter_id": code_interpreter_id,
        "code_interpreter_arn": arn,
        "code_interpreter_name": code_interpreter_name,
    }


def _public_harness_environment() -> Dict:
    return {
        "agentCoreRuntimeEnvironment": {
            "lifecycleConfiguration": {
                "idleRuntimeSessionTimeout": 600,
                "maxLifetime": 14400,
            },
            "networkConfiguration": {"networkMode": "PUBLIC"},
        }
    }


def ensure_harness_memory_disabled(harness_id: str) -> None:
    """Ensure harness has memory explicitly disabled (stateless)."""
    h = agentcore_control_client.get_harness(harnessId=harness_id)["harness"]
    memory = h.get("memory") or {}
    if isinstance(memory, dict) and "disabled" in memory:
        logger.info("  Harness memory already disabled")
        return
    logger.info(f"  Disabling harness memory (harnessId={harness_id})")
    update_harness_safe(
        harness_id,
        memory={"optionalValue": {"disabled": {}}},
    )


def ensure_harness_environment_public(harness_id: str) -> None:
    desired = _public_harness_environment()
    h = agentcore_control_client.get_harness(harnessId=harness_id)["harness"]
    current_rt = (h.get("environment") or {}).get("agentCoreRuntimeEnvironment") or {}
    current_mode = (current_rt.get("networkConfiguration") or {}).get("networkMode")
    if current_mode == "PUBLIC":
        logger.info("  Harness environment already PUBLIC")
        return
    logger.info(f"  Updating harness networkMode {current_mode!r} -> PUBLIC")
    update_harness_safe(harness_id, environment=desired)


def ensure_harness_system_prompt(harness_id: str) -> None:
    desired = [{"text": BASE_SYSTEM_PROMPT}]
    h = agentcore_control_client.get_harness(harnessId=harness_id)["harness"]
    current = h.get("systemPrompt") or []
    if current == desired:
        logger.info("  Harness systemPrompt already up to date")
        return
    logger.info(f"  Updating harness systemPrompt (harnessId={harness_id})")
    update_harness_safe(harness_id, systemPrompt=desired)


def ensure_harness_model(harness_id: str, model_id: str = DEFAULT_MODEL_ID) -> None:
    """Keep CreateHarness modelId in sync on re-install."""
    desired_max = get_max_output_tokens(model_id)
    h = agentcore_control_client.get_harness(harnessId=harness_id)["harness"]
    current = ((h.get("model") or {}).get("bedrockModelConfig") or {})
    if current.get("modelId") == model_id and current.get("maxTokens") == desired_max:
        logger.info(f"  Harness model already {model_id}")
        return
    logger.info(
        f"  Updating harness model: {current.get('modelId')!r} -> {model_id!r}"
    )
    update_harness_safe(
        harness_id,
        model={
            "bedrockModelConfig": {
                "modelId": model_id,
                "maxTokens": desired_max,
            }
        },
    )


def ensure_harness_tools(harness_id: str, code_interpreter_arn: str = "") -> None:
    desired = _default_harness_tools(code_interpreter_arn)
    h = agentcore_control_client.get_harness(harnessId=harness_id)["harness"]
    current = h.get("tools") or []
    current_by_name = {
        t.get("name"): t for t in current if isinstance(t, dict) and t.get("name")
    }
    needs_update = False
    for tool in desired:
        existing = current_by_name.get(tool["name"])
        if existing != tool:
            needs_update = True
            break
    if not needs_update and {t["name"] for t in desired}.issubset(current_by_name):
        logger.info("  Harness tools already up to date")
        return
    merged = dict(current_by_name)
    for tool in desired:
        merged[tool["name"]] = tool
    logger.info("  Updating harness tools (custom code interpreter)")
    update_harness_safe(harness_id, tools=list(merged.values()))


def ensure_harness_skills(harness_id: str, s3_bucket: str) -> None:
    """Attach default S3 skills (businfo) on the harness configuration."""
    desired = build_default_harness_skills(s3_bucket)
    h = agentcore_control_client.get_harness(harnessId=harness_id)["harness"]
    current = h.get("skills") or []
    desired_uris = {
        ((s.get("s3") or {}).get("uri") or "").rstrip("/")
        for s in desired
        if isinstance(s, dict)
    }
    current_uris = {
        ((s.get("s3") or {}).get("uri") or "").rstrip("/")
        for s in current
        if isinstance(s, dict)
    }
    if desired_uris and desired_uris.issubset(current_uris):
        logger.info("  Harness skills already include businfo S3 skill")
        return
    logger.info(
        f"  Updating harness skills → {', '.join(sorted(desired_uris)) or '(none)'}"
    )
    update_harness_safe(harness_id, skills=desired)


def create_or_get_harness(
    execution_role_arn: str,
    s3_bucket: str,
    code_interpreter_arn: str = "",
) -> Dict[str, str]:
    """Create AgentCore Harness (PUBLIC, memory disabled) or reuse by name."""
    logger.info("Creating AgentCore Harness (PUBLIC, memory disabled)")

    harness_api_name = harness_name_for_api(project_name)
    logger.info(
        f"  harnessName: {harness_api_name} (from projectName={project_name!r})"
    )

    model_id = DEFAULT_MODEL_ID
    system_prompt = [{"text": BASE_SYSTEM_PROMPT}]
    environment = _public_harness_environment()
    tools = _default_harness_tools(code_interpreter_arn)
    skills = build_default_harness_skills(s3_bucket)

    existing = find_harness_by_api_name(harness_api_name)
    if existing:
        harness_id = existing["harnessId"]
        try:
            status = agentcore_control_client.get_harness(harnessId=harness_id)[
                "harness"
            ].get("status")
        except ClientError:
            status = None
        if status in ("CREATE_FAILED", "UPDATE_FAILED", "FAILED", "DELETE_FAILED"):
            reason = ""
            try:
                reason = (
                    agentcore_control_client.get_harness(harnessId=harness_id)[
                        "harness"
                    ].get("failureReason")
                    or ""
                )
            except ClientError:
                pass
            logger.warning(
                f"Harness {harness_api_name!r} is {status} "
                f"(harnessId={harness_id}); deleting to recreate."
                + (f" reason={reason!r}" if reason else "")
            )
            try:
                agentcore_control_client.delete_harness(
                    harnessId=harness_id,
                    clientToken=str(uuid.uuid4()),
                )
            except ClientError as e:
                if e.response.get("Error", {}).get("Code") != "ResourceNotFoundException":
                    raise
            deadline = time.time() + 600
            while time.time() < deadline:
                try:
                    agentcore_control_client.get_harness(harnessId=harness_id)
                    time.sleep(5)
                except ClientError as e:
                    if (
                        e.response.get("Error", {}).get("Code")
                        == "ResourceNotFoundException"
                    ):
                        break
                    raise
            else:
                raise TimeoutError(f"Timed out deleting failed harness {harness_id}")
            existing = None
        else:
            logger.warning(
                f"Harness {harness_api_name!r} already exists "
                f"(harnessId={harness_id}); skipping CreateHarness."
            )

    if not existing:
        try:
            response = agentcore_control_client.create_harness(
                harnessName=harness_api_name,
                executionRoleArn=execution_role_arn,
                model={
                    "bedrockModelConfig": {
                        "modelId": model_id,
                        "maxTokens": get_max_output_tokens(model_id),
                    }
                },
                systemPrompt=system_prompt,
                tools=tools,
                skills=skills,
                memory={"disabled": {}},
                truncation={
                    "strategy": "sliding_window",
                    "config": {"slidingWindow": {"messagesCount": 50}},
                },
                maxIterations=20,
                maxTokens=50000,
                timeoutSeconds=300,
                environment=environment,
                environmentVariables={
                    "LOG_LEVEL": "info",
                    "GLUE_DATABASE": glue_database_name,
                    "S3_BUCKET": s3_bucket,
                },
                tags={"Project": project_name, "Env": "dev"},
            )
            harness_id = response["harness"]["harnessId"]
            logger.info(f"  ✓ Harness created: {harness_id}")
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") != "ConflictException":
                raise
            rerun = find_harness_by_api_name(harness_api_name)
            if not rerun:
                raise
            harness_id = rerun["harnessId"]
            logger.info(
                f"CreateHarness conflict; using existing harnessId={harness_id}"
            )

    ensure_harness_memory_disabled(harness_id)
    ensure_harness_environment_public(harness_id)
    ensure_harness_model(harness_id, DEFAULT_MODEL_ID)
    ensure_harness_system_prompt(harness_id)
    ensure_harness_tools(harness_id, code_interpreter_arn)
    ensure_harness_skills(harness_id, s3_bucket)
    harness_arn = wait_for_harness_ready(harness_id)
    return {
        "harness_id": harness_id,
        "harness_arn": harness_arn,
        "harness_name": harness_api_name,
    }


def _should_skip_skill_path(rel_path: str) -> bool:
    parts = rel_path.replace("\\", "/").split("/")
    if any(p in {"__pycache__", ".git", "node_modules", ".DS_Store"} for p in parts):
        return True
    basename = parts[-1] if parts else ""
    return basename.endswith((".pyc", ".pyo", ".DS_Store"))


def _local_skill_names() -> set:
    if not os.path.isdir(SKILLS_DIR):
        return set()
    return {
        name
        for name in os.listdir(SKILLS_DIR)
        if os.path.isdir(os.path.join(SKILLS_DIR, name))
        and not name.startswith(".")
        and name not in {"__pycache__", "node_modules"}
    }


def _prune_removed_skills_from_s3(s3_bucket_name: str) -> int:
    """Delete S3 skill prefixes that no longer exist under local skills/."""
    local_names = _local_skill_names()
    prefix = f"{SKILLS_S3_PREFIX}/"
    removed = 0
    try:
        paginator = s3_client.get_paginator("list_objects_v2")
        remote_names: set = set()
        for page in paginator.paginate(
            Bucket=s3_bucket_name, Prefix=prefix, Delimiter="/"
        ):
            for cp in page.get("CommonPrefixes") or []:
                p = (cp.get("Prefix") or "").rstrip("/")
                name = p.split("/")[-1] if p else ""
                if name:
                    remote_names.add(name)
        for name in sorted(remote_names - local_names):
            orphan_prefix = f"{prefix}{name}/"
            logger.info(
                f"  pruning removed skill from S3: "
                f"s3://{s3_bucket_name}/{orphan_prefix}"
            )
            for page in paginator.paginate(
                Bucket=s3_bucket_name, Prefix=orphan_prefix
            ):
                objs = page.get("Contents") or []
                if not objs:
                    continue
                s3_client.delete_objects(
                    Bucket=s3_bucket_name,
                    Delete={
                        "Objects": [{"Key": o["Key"]} for o in objs],
                        "Quiet": True,
                    },
                )
                removed += len(objs)
    except ClientError as e:
        logger.warning(f"  skill prune skipped: {e}")
        return removed
    if removed:
        logger.info(f"✓ Pruned {removed} stale skill object(s) from S3")
    return removed


def upload_skills_to_s3(s3_bucket_name: str) -> int:
    """Upload skills/ to s3://{bucket}/skills/ for InvokeHarness S3 skill attach."""
    logger.info(f"Uploading skills to s3://{s3_bucket_name}/{SKILLS_S3_PREFIX}/")
    if not os.path.isdir(SKILLS_DIR):
        logger.warning(f"Skills directory not found: {SKILLS_DIR}; skipping upload")
        return 0

    uploaded = 0
    failed = 0
    for root, dirs, files in os.walk(SKILLS_DIR):
        dirs[:] = [d for d in dirs if d not in {"__pycache__", ".git", "node_modules"}]
        for filename in files:
            local_path = os.path.join(root, filename)
            rel_path = os.path.relpath(local_path, SKILLS_DIR)
            if _should_skip_skill_path(rel_path):
                continue
            s3_key = f"{SKILLS_S3_PREFIX}/{rel_path.replace(os.sep, '/')}"
            content_type, _ = mimetypes.guess_type(local_path)
            upload_kwargs = {}
            if content_type:
                upload_kwargs["ExtraArgs"] = {"ContentType": content_type}
            try:
                s3_client.upload_file(
                    local_path,
                    s3_bucket_name,
                    s3_key,
                    **upload_kwargs,
                )
                uploaded += 1
                logger.debug(f"  uploaded: s3://{s3_bucket_name}/{s3_key}")
            except ClientError as e:
                failed += 1
                logger.error(f"  failed: {rel_path}: {e}")

    if failed:
        raise RuntimeError(
            f"Skills upload incomplete: {uploaded} ok, {failed} failed "
            f"(from {SKILLS_DIR})"
        )

    _prune_removed_skills_from_s3(s3_bucket_name)
    logger.info(
        f"✓ Uploaded {uploaded} skill file(s) to "
        f"s3://{s3_bucket_name}/{SKILLS_S3_PREFIX}/"
    )
    return uploaded


def build_default_harness_skills(s3_bucket_name: str) -> List[Dict]:
    """InvokeHarness skills payload for DEFAULT_HARNESS_SKILLS."""
    return [
        {"s3": {"uri": f"s3://{s3_bucket_name}/{SKILLS_S3_PREFIX}/{name}/"}}
        for name in DEFAULT_HARNESS_SKILLS
    ]


def create_jobs_table() -> Dict[str, str]:
    """Create DynamoDB table for async Harness job status/results (TTL 24h)."""
    logger.info(f"Creating jobs DynamoDB table: {jobs_table_name}")
    try:
        dynamodb_client.create_table(
            TableName=jobs_table_name,
            KeySchema=[{"AttributeName": "jobId", "KeyType": "HASH"}],
            AttributeDefinitions=[
                {"AttributeName": "jobId", "AttributeType": "S"},
            ],
            BillingMode="PAY_PER_REQUEST",
            Tags=[
                {"Key": "Project", "Value": project_name},
                {"Key": "Purpose", "Value": "harness-async-jobs"},
            ],
        )
    except ClientError as e:
        if e.response["Error"]["Code"] != "ResourceInUseException":
            raise
        logger.warning(f"Jobs table already exists: {jobs_table_name}")

    waiter = dynamodb_client.get_waiter("table_exists")
    waiter.wait(TableName=jobs_table_name)
    for _ in range(30):
        desc = dynamodb_client.describe_table(TableName=jobs_table_name)
        if desc["Table"]["TableStatus"] == "ACTIVE":
            break
        time.sleep(2)
    else:
        raise TimeoutError(f"Jobs table {jobs_table_name} did not become ACTIVE")

    try:
        dynamodb_client.update_time_to_live(
            TableName=jobs_table_name,
            TimeToLiveSpecification={"Enabled": True, "AttributeName": "ttl"},
        )
        logger.info("✓ Jobs table TTL enabled on attribute 'ttl'")
    except ClientError as e:
        # Already enabled / in progress is fine
        code = e.response["Error"]["Code"]
        if code not in (
            "ValidationException",
            "ResourceInUseException",
        ):
            logger.warning(f"Could not enable TTL on {jobs_table_name}: {e}")

    table_arn = dynamodb_client.describe_table(TableName=jobs_table_name)["Table"][
        "TableArn"
    ]
    logger.info(f"✓ Jobs table ready: {table_arn}")
    return {"jobsTableName": jobs_table_name, "jobsTableArn": table_arn}


def create_lambda_harness(
    harness_arn: str, s3_bucket: str, jobs_table: str
) -> str:
    """Deploy Lambda: API jobs API + async worker → InvokeHarness."""
    logger.info(f"Creating Lambda: {lambda_harness_name}")

    jobs_table_arn = (
        f"arn:aws:dynamodb:{region}:{account_id}:table/{jobs_table}"
    )
    lambda_arn = (
        f"arn:aws:lambda:{region}:{account_id}:function:{lambda_harness_name}"
    )

    invoke_policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "InvokeHarness",
                "Effect": "Allow",
                "Action": [
                    "bedrock-agentcore:InvokeHarness",
                    "bedrock-agentcore:InvokeAgentRuntime",
                    "bedrock-agentcore:InvokeAgentRuntimeForUser",
                ],
                "Resource": ["*"],
            },
            {
                "Sid": "JobsTable",
                "Effect": "Allow",
                "Action": [
                    "dynamodb:GetItem",
                    "dynamodb:PutItem",
                    "dynamodb:UpdateItem",
                    "dynamodb:DeleteItem",
                    "dynamodb:DescribeTable",
                ],
                "Resource": [jobs_table_arn],
            },
            {
                "Sid": "SelfAsyncInvoke",
                "Effect": "Allow",
                "Action": ["lambda:InvokeFunction"],
                "Resource": [lambda_arn],
            },
        ],
    }

    role_arn = create_lambda_execution_role(
        lambda_harness_role_name,
        extra_policies=[
            {"name": "invoke-harness-policy", "document": invoke_policy}
        ],
    )

    source_dir = os.path.join(lambda_base_dir, "lambda-harness")
    return deploy_lambda_function(
        function_name=lambda_harness_name,
        role_arn=role_arn,
        source_dir=source_dir,
        description="Async jobs API + worker proxy to AgentCore Harness",
        handler="lambda_function.handler",
        runtime=lambda_python_runtime,
        timeout=300,
        memory_size=512,
        # Runtime boto3 is too old for InvokeHarness skills.s3; bundle a recent SDK.
        pip_packages=["boto3>=1.40.0"],
        environment={
            "HARNESS_ARN": harness_arn,
            "BEDROCK_REGION": region,
            "DEFAULT_MODEL_ID": DEFAULT_MODEL_ID,
            "S3_BUCKET": s3_bucket,
            "SKILLS_S3_PREFIX": SKILLS_S3_PREFIX,
            "DEFAULT_SKILLS": ",".join(DEFAULT_HARNESS_SKILLS),
            "JOBS_TABLE": jobs_table,
            "JOB_TTL_SECONDS": str(24 * 3600),
        },
    )


def create_lambda_function_url(function_name: str) -> str:
    """Create or reuse IAM-auth Function URL for long-running invokes."""
    logger.info(f"Creating Lambda Function URL: {function_name}")
    try:
        existing = lambda_client.get_function_url_config(FunctionName=function_name)
        url = existing["FunctionUrl"]
        auth = existing.get("AuthType")
        if auth != "AWS_IAM":
            lambda_client.update_function_url_config(
                FunctionName=function_name,
                AuthType="AWS_IAM",
            )
        logger.info(f"✓ Function URL ready: {url}")
        return url
    except ClientError as e:
        if e.response["Error"]["Code"] != "ResourceNotFoundException":
            raise

    response = lambda_client.create_function_url_config(
        FunctionName=function_name,
        AuthType="AWS_IAM",
        Cors={
            "AllowOrigins": ["*"],
            "AllowMethods": ["GET", "POST"],
            "AllowHeaders": ["content-type", "authorization"],
            "MaxAge": 300,
        },
    )
    url = response["FunctionUrl"]
    logger.info(f"✓ Function URL created: {url}")
    return url


def _find_http_api_by_name(api_name: str) -> Optional[Dict]:
    paginator = apigatewayv2_client.get_paginator("get_apis")
    for page in paginator.paginate():
        for api in page.get("Items", []):
            if api.get("Name") == api_name:
                return api
    return None


def create_api_gateway(lambda_arn: str) -> Dict[str, str]:
    """Create HTTP API with POST /invoke and GET /health → Lambda proxy."""
    logger.info(f"Creating API Gateway HTTP API: {api_harness_name}")

    existing = _find_http_api_by_name(api_harness_name)
    if existing:
        api_id = existing["ApiId"]
        api_endpoint = existing["ApiEndpoint"]
        logger.warning(f"HTTP API already exists: {api_harness_name} ({api_id})")
    else:
        created = apigatewayv2_client.create_api(
            Name=api_harness_name,
            ProtocolType="HTTP",
            Description="Businfo analytics Harness invoke API",
            CorsConfiguration={
                "AllowOrigins": ["*"],
                "AllowMethods": ["GET", "POST", "OPTIONS"],
                "AllowHeaders": ["content-type", "authorization"],
                "MaxAge": 300,
            },
            Tags={"Project": project_name},
        )
        api_id = created["ApiId"]
        api_endpoint = created["ApiEndpoint"]
        logger.info(f"✓ HTTP API created: {api_id}")

    # Integration
    integrations = apigatewayv2_client.get_integrations(ApiId=api_id).get("Items") or []
    integration_id = None
    for integ in integrations:
        if integ.get("IntegrationUri") == lambda_arn:
            integration_id = integ["IntegrationId"]
            break
    if not integration_id and integrations:
        # Reuse first AWS_PROXY integration if present
        for integ in integrations:
            if integ.get("IntegrationType") == "AWS_PROXY":
                integration_id = integ["IntegrationId"]
                apigatewayv2_client.update_integration(
                    ApiId=api_id,
                    IntegrationId=integration_id,
                    IntegrationUri=lambda_arn,
                    PayloadFormatVersion="2.0",
                    TimeoutInMillis=30000,
                )
                break
    if not integration_id:
        integ = apigatewayv2_client.create_integration(
            ApiId=api_id,
            IntegrationType="AWS_PROXY",
            IntegrationUri=lambda_arn,
            PayloadFormatVersion="2.0",
            TimeoutInMillis=30000,
        )
        integration_id = integ["IntegrationId"]
        logger.info(f"✓ Integration created: {integration_id}")

    existing_routes = {
        r["RouteKey"]: r["RouteId"]
        for r in (apigatewayv2_client.get_routes(ApiId=api_id).get("Items") or [])
    }
    for route_key in (
        "POST /jobs",
        "GET /jobs/{jobId}",
        "OPTIONS /jobs",
        "OPTIONS /jobs/{jobId}",
        "POST /invoke",
        "GET /health",
        "OPTIONS /invoke",
    ):
        if route_key in existing_routes:
            continue
        try:
            apigatewayv2_client.create_route(
                ApiId=api_id,
                RouteKey=route_key,
                Target=f"integrations/{integration_id}",
            )
            logger.info(f"  Route created: {route_key}")
        except ClientError as e:
            if e.response["Error"]["Code"] != "ConflictException":
                raise

    try:
        apigatewayv2_client.create_stage(
            ApiId=api_id,
            StageName="$default",
            AutoDeploy=True,
        )
        logger.info("✓ Stage $default created")
    except ClientError as e:
        if e.response["Error"]["Code"] not in (
            "ConflictException",
            "BadRequestException",
        ):
            raise

    # Permission for API Gateway to invoke Lambda
    source_arn = (
        f"arn:aws:execute-api:{region}:{account_id}:{api_id}/*/*"
    )
    try:
        lambda_client.add_permission(
            FunctionName=lambda_harness_name,
            StatementId=f"apigw-{api_harness_name}",
            Action="lambda:InvokeFunction",
            Principal="apigateway.amazonaws.com",
            SourceArn=source_arn,
        )
    except ClientError as e:
        if e.response["Error"]["Code"] != "ResourceConflictException":
            raise

    jobs_url = f"{api_endpoint}/jobs"
    invoke_url = f"{api_endpoint}/invoke"
    health_url = f"{api_endpoint}/health"
    logger.info(f"✓ API Gateway ready: jobs={jobs_url} invoke={invoke_url}")
    logger.info(
        "  Web uses async POST /jobs + GET /jobs/{jobId} (avoids API GW ~29s limit). "
        "POST /invoke remains for short sync smoke tests."
    )
    return {
        "api_id": api_id,
        "api_endpoint": api_endpoint,
        "api_jobs_url": jobs_url,
        "api_invoke_url": invoke_url,
        "api_health_url": health_url,
    }


def deploy_harness_stack(s3_bucket: Optional[str] = None) -> Dict[str, str]:
    """Provision Harness + jobs table + Lambda + API Gateway + Function URL."""
    target_bucket = s3_bucket or bucket_name or resolve_bucket_name(account_id, region)
    upload_skills_to_s3(target_bucket)
    jobs_info = create_jobs_table()
    execution_role_arn = create_harness_execution_role(target_bucket)
    code_info = create_or_get_code_interpreter(execution_role_arn)
    harness_info = create_or_get_harness(
        execution_role_arn,
        target_bucket,
        code_interpreter_arn=code_info["code_interpreter_arn"],
    )
    lambda_arn = create_lambda_harness(
        harness_info["harness_arn"],
        target_bucket,
        jobs_info["jobsTableName"],
    )
    function_url = create_lambda_function_url(lambda_harness_name)
    api_info = create_api_gateway(lambda_arn)
    skill_uris = [
        item["s3"]["uri"] for item in build_default_harness_skills(target_bucket)
    ]
    return {
        "HARNESS_ARN": harness_info["harness_arn"],
        "HARNESS_ID": harness_info["harness_id"],
        "harnessName": harness_info["harness_name"],
        "harnessExecutionRole": execution_role_arn,
        "codeInterpreterId": code_info["code_interpreter_id"],
        "codeInterpreterArn": code_info["code_interpreter_arn"],
        "codeInterpreterName": code_info["code_interpreter_name"],
        "lambdaHarnessName": lambda_harness_name,
        "lambdaHarnessArn": lambda_arn,
        "jobsTableName": jobs_info["jobsTableName"],
        "jobsTableArn": jobs_info["jobsTableArn"],
        "apiGatewayId": api_info["api_id"],
        "apiJobsUrl": api_info["api_jobs_url"],
        "apiGatewayUrl": api_info["api_jobs_url"],
        "apiGatewayInvokeUrl": api_info["api_invoke_url"],
        "apiGatewayHealthUrl": api_info["api_health_url"],
        "lambdaFunctionUrl": function_url,
        "skillsS3Prefix": f"s3://{target_bucket}/{SKILLS_S3_PREFIX}/",
        "defaultSkills": ",".join(DEFAULT_HARNESS_SKILLS),
        "defaultSkillUris": skill_uris,
    }


def _cloudfront_comment() -> str:
    return f"CloudFront-S3-for-{project_name}"


def _oai_comment() -> str:
    return f"OAI for {project_name} web"


def load_config_json() -> Dict:
    config_path = os.path.join(script_dir, "config.json")
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            content = f.read().strip()
            if content:
                return json.loads(content)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        pass
    return {}


def discover_web_resources() -> Dict[str, str]:
    """Look up existing businfo S3 + CloudFront (by comment) and return config keys."""
    logger.info("Discovering S3 / CloudFront for web hosting")
    cfg = load_config_json()
    found: Dict[str, str] = {}

    target_bucket = (
        cfg.get("bucketName")
        or bucket_name
        or resolve_bucket_name(account_id, region)
    )
    if verify_s3_bucket_access(target_bucket):
        found["bucketName"] = target_bucket
        found["s3Arn"] = f"arn:aws:s3:::{target_bucket}"
        found["s3Path"] = f"s3://{target_bucket}"
        logger.info(f"  ✓ S3 bucket: {target_bucket}")
    else:
        logger.warning(f"  S3 bucket not accessible: {target_bucket}")

    comment = _cloudfront_comment()
    try:
        marker = None
        while True:
            kwargs: Dict = {}
            if marker:
                kwargs["Marker"] = marker
            resp = cloudfront_client.list_distributions(**kwargs)
            dist_list = resp.get("DistributionList") or {}
            for dist in dist_list.get("Items") or []:
                if comment in (dist.get("Comment") or ""):
                    found["cloudfrontId"] = dist["Id"]
                    found["cloudfrontDomain"] = dist["DomainName"]
                    found["cloudfrontUrl"] = f"https://{dist['DomainName']}"
                    logger.info(
                        f"  ✓ CloudFront: {dist['DomainName']} ({dist['Id']})"
                    )
                    break
            if found.get("cloudfrontId"):
                break
            if not dist_list.get("IsTruncated"):
                break
            marker = dist_list.get("NextMarker")
    except ClientError as e:
        logger.warning(f"  Could not list CloudFront distributions: {e}")

    if not found.get("cloudfrontId"):
        logger.info(f"  CloudFront with comment {comment!r} not found yet")
    return found


def _ensure_cloudfront_oai() -> str:
    oai_cmt = _oai_comment()
    try:
        oai_list = cloudfront_client.list_cloud_front_origin_access_identities(
            MaxItems="100"
        )
        items = (oai_list.get("CloudFrontOriginAccessIdentityList") or {}).get(
            "Items"
        ) or []
        for oai in items:
            if oai_cmt in (oai.get("Comment") or ""):
                logger.info(f"  Using existing OAI: {oai['Id']}")
                return oai["Id"]
    except ClientError as e:
        logger.debug(f"list OAI: {e}")

    oai_response = cloudfront_client.create_cloud_front_origin_access_identity(
        CloudFrontOriginAccessIdentityConfig={
            "CallerReference": f"{project_name}-web-oai-{int(time.time())}",
            "Comment": oai_cmt,
        }
    )
    oai_id = oai_response["CloudFrontOriginAccessIdentity"]["Id"]
    logger.info(f"  Created OAI: {oai_id}")
    return oai_id


def _merge_s3_cloudfront_bucket_policy(s3_bucket_name: str, oai_id: str) -> None:
    """Allow CloudFront OAI GetObject without wiping unrelated statements."""
    oai = cloudfront_client.get_cloud_front_origin_access_identity(Id=oai_id)
    canonical_user = oai["CloudFrontOriginAccessIdentity"]["S3CanonicalUserId"]
    cf_statement = {
        "Sid": "AllowCloudFrontWebAccess",
        "Effect": "Allow",
        "Principal": {"CanonicalUser": canonical_user},
        "Action": "s3:GetObject",
        "Resource": f"arn:aws:s3:::{s3_bucket_name}/{WEB_S3_PREFIX}/*",
    }
    policy: Dict = {"Version": "2012-10-17", "Statement": []}
    try:
        existing = s3_client.get_bucket_policy(Bucket=s3_bucket_name)
        policy = json.loads(existing["Policy"])
    except ClientError as e:
        if e.response["Error"]["Code"] not in ("NoSuchBucketPolicy", "NoSuchBucket"):
            raise

    statements = policy.get("Statement") or []
    if isinstance(statements, dict):
        statements = [statements]
    statements = [
        s
        for s in statements
        if not (isinstance(s, dict) and s.get("Sid") == "AllowCloudFrontWebAccess")
    ]
    statements.append(cf_statement)
    policy["Statement"] = statements
    s3_client.put_bucket_policy(Bucket=s3_bucket_name, Policy=json.dumps(policy))
    logger.info("  Updated S3 bucket policy for CloudFront web access")


def create_cloudfront_distribution(s3_bucket_name: str) -> Dict[str, str]:
    """Create or reuse CloudFront distribution for html/ static site on S3."""
    logger.info("Creating CloudFront distribution (S3 web)")
    discovered = discover_web_resources()
    if discovered.get("cloudfrontId") and discovered.get("cloudfrontDomain"):
        return {
            "id": discovered["cloudfrontId"],
            "domain": discovered["cloudfrontDomain"],
        }

    oai_id = _ensure_cloudfront_oai()
    time.sleep(5)
    _merge_s3_cloudfront_bucket_policy(s3_bucket_name, oai_id)

    origin_id = f"s3-{project_name}-web"
    distribution_config = {
        "CallerReference": f"{project_name}-web-{int(time.time())}",
        "Comment": _cloudfront_comment(),
        "DefaultRootObject": "index.html",
        "DefaultCacheBehavior": {
            "TargetOriginId": origin_id,
            "ViewerProtocolPolicy": "redirect-to-https",
            "AllowedMethods": {
                "Quantity": 2,
                "Items": ["GET", "HEAD"],
                "CachedMethods": {"Quantity": 2, "Items": ["GET", "HEAD"]},
            },
            "CachePolicyId": "658327ea-f89d-4fab-a63d-7e88639e58f6",
            "Compress": True,
        },
        "Origins": {
            "Quantity": 1,
            "Items": [
                {
                    "Id": origin_id,
                    "DomainName": f"{s3_bucket_name}.s3.{region}.amazonaws.com",
                    "OriginPath": f"/{WEB_S3_PREFIX}",
                    "S3OriginConfig": {
                        "OriginAccessIdentity": (
                            f"origin-access-identity/cloudfront/{oai_id}"
                        )
                    },
                }
            ],
        },
        "Enabled": True,
        "PriceClass": "PriceClass_200",
    }

    response = cloudfront_client.create_distribution(
        DistributionConfig=distribution_config
    )
    distribution_id = response["Distribution"]["Id"]
    distribution_domain = response["Distribution"]["DomainName"]
    logger.info(f"✓ CloudFront created: {distribution_domain}")
    return {"id": distribution_id, "domain": distribution_domain}


def _derive_api_base(url: str) -> str:
    """Strip trailing /jobs or /invoke to get API endpoint base."""
    u = (url or "").rstrip("/")
    if u.endswith("/jobs"):
        return u[: -len("/jobs")]
    if u.endswith("/invoke"):
        return u[: -len("/invoke")]
    return u


def write_html_config_js(
    api_gateway_url: str,
    api_gateway_health_url: str = "",
    api_jobs_url: str = "",
) -> str:
    """Write html/config.js from deployment config for the static site."""
    os.makedirs(HTML_DIR, exist_ok=True)
    path = os.path.join(HTML_DIR, "config.js")
    prior = load_config_json()
    jobs = (api_jobs_url or prior.get("apiJobsUrl") or api_gateway_url or "").rstrip(
        "/"
    )
    # Prefer /jobs for the demo web; accept legacy /invoke and rewrite.
    if jobs.endswith("/invoke"):
        jobs = jobs[: -len("/invoke")] + "/jobs"
    if jobs and not jobs.endswith("/jobs"):
        base = _derive_api_base(jobs)
        jobs = f"{base}/jobs" if base else jobs
    health = (api_gateway_health_url or prior.get("apiGatewayHealthUrl") or "").rstrip(
        "/"
    )
    if not health and jobs:
        health = f"{_derive_api_base(jobs)}/health"
    content = (
        "// Generated by installer.py — do not edit by hand for deploy.\n"
        "window.APP_CONFIG = {\n"
        f"  apiJobsUrl: {json.dumps(jobs)},\n"
        f"  apiGatewayUrl: {json.dumps(jobs)},\n"
        f"  apiGatewayHealthUrl: {json.dumps(health)},\n"
        f"  projectName: {json.dumps(project_name)},\n"
        '  companyName: "센터교통정보",\n'
        "};\n"
    )
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    logger.info(f"✓ Wrote {path}")
    return path


def upload_web_to_s3(
    s3_bucket_name: str,
    api_gateway_url: str,
    api_gateway_health_url: str = "",
    api_jobs_url: str = "",
) -> int:
    """Upload html/ assets (including images/) to s3://{bucket}/web/."""
    logger.info(f"Uploading html/ → s3://{s3_bucket_name}/{WEB_S3_PREFIX}/")
    if not os.path.isdir(HTML_DIR):
        raise FileNotFoundError(f"Missing HTML directory: {HTML_DIR}")

    write_html_config_js(api_gateway_url, api_gateway_health_url, api_jobs_url)
    uploaded = 0
    skip_names = {"generate_images.py", "manifest.json"}
    for root, dirs, files in os.walk(HTML_DIR):
        dirs[:] = [d for d in dirs if not d.startswith(".") and d != "__pycache__"]
        for filename in sorted(files):
            if filename.startswith(".") or filename in skip_names:
                continue
            if filename.endswith(".py"):
                continue
            filepath = os.path.join(root, filename)
            rel = os.path.relpath(filepath, HTML_DIR).replace(os.sep, "/")
            key = f"{WEB_S3_PREFIX}/{rel}"
            content_type, _ = mimetypes.guess_type(filename)
            if filename.endswith(".js"):
                content_type = "application/javascript"
            elif filename.endswith(".css"):
                content_type = "text/css"
            elif filename.endswith(".html"):
                content_type = "text/html; charset=utf-8"
            elif filename.endswith(".png"):
                content_type = "image/png"
            elif filename.endswith(".jpg") or filename.endswith(".jpeg"):
                content_type = "image/jpeg"
            elif filename.endswith(".webp"):
                content_type = "image/webp"
            extra = {"ContentType": content_type or "application/octet-stream"}
            if filename in ("config.js", "index.html", "app.js") or rel.endswith(
                "hero.png"
            ):
                extra["CacheControl"] = "no-cache, max-age=0"
            else:
                extra["CacheControl"] = "public, max-age=300"
            s3_client.upload_file(
                filepath,
                s3_bucket_name,
                key,
                ExtraArgs=extra,
            )
            uploaded += 1
            logger.info(f"  ↑ {key}")
    logger.info(f"✓ Uploaded {uploaded} files")
    return uploaded


def invalidate_cloudfront(distribution_id: str) -> None:
    if not distribution_id:
        return
    try:
        cloudfront_client.create_invalidation(
            DistributionId=distribution_id,
            InvalidationBatch={
                "Paths": {"Quantity": 1, "Items": ["/*"]},
                "CallerReference": f"{project_name}-web-{int(time.time())}",
            },
        )
        logger.info(f"✓ CloudFront invalidation submitted: {distribution_id}")
    except ClientError as e:
        logger.warning(f"CloudFront invalidation skipped: {e}")


def deploy_web_stack(
    s3_bucket_name: str,
    api_gateway_url: str = "",
    api_gateway_health_url: str = "",
    api_jobs_url: str = "",
) -> Dict[str, str]:
    """Ensure CloudFront + upload html/ and return config fields."""
    discovered = discover_web_resources()
    target_bucket = s3_bucket_name or discovered.get("bucketName") or bucket_name
    if not target_bucket:
        raise RuntimeError("S3 bucket name is required for web deploy")

    prior = load_config_json()
    jobs = (
        api_jobs_url
        or prior.get("apiJobsUrl")
        or api_gateway_url
        or prior.get("apiGatewayUrl")
        or ""
    )
    health = (
        api_gateway_health_url
        or prior.get("apiGatewayHealthUrl")
        or ""
    )

    cf = create_cloudfront_distribution(target_bucket)
    upload_web_to_s3(target_bucket, jobs, health, api_jobs_url=jobs)
    invalidate_cloudfront(cf["id"])

    return {
        "bucketName": target_bucket,
        "s3Arn": f"arn:aws:s3:::{target_bucket}",
        "s3Path": f"s3://{target_bucket}",
        "webS3Prefix": WEB_S3_PREFIX,
        "cloudfrontId": cf["id"],
        "cloudfrontDomain": cf["domain"],
        "cloudfrontUrl": f"https://{cf['domain']}",
        "websiteUrl": f"https://{cf['domain']}",
    }


def update_config_json(resource_info: Dict):
    """Update config.json with deployed resource information."""
    config_path = os.path.join(script_dir, "config.json")
    config_data = {}

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            content = f.read().strip()
            if content:
                config_data = json.loads(content)
    except FileNotFoundError:
        logger.info(f"Creating new {config_path}")
    except json.JSONDecodeError as e:
        logger.warning(f"Could not parse existing {config_path}: {e}")
    except Exception as e:
        logger.warning(f"Could not read existing {config_path}: {e}")

    config_data.update(resource_info)

    try:
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(config_data, f, indent=2, ensure_ascii=False)
            f.write("\n")
        logger.info(f"✓ Updated {config_path}")
    except Exception as e:
        logger.warning(f"Could not update {config_path}: {e}")


def main():
    """Main deployment function."""
    global region, sts_client, account_id, bucket_name
    global s3_client, iam_client, kinesis_client, dynamodb_client
    global lambda_client, events_client, glue_client, firehose_client
    global apigatewayv2_client, agentcore_control_client, cloudfront_client

    parser = argparse.ArgumentParser(
        description="AWS Infrastructure Installer for Bus Schedule Analytics"
    )
    parser.add_argument(
        "--region",
        default=region,
        help=f"AWS region (default: {region})",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging",
    )
    parser.add_argument(
        "--harness-only",
        action="store_true",
        help="Skip businfo pipeline; provision Harness + API Gateway + Lambda only",
    )
    parser.add_argument(
        "--skip-harness",
        action="store_true",
        help="Provision businfo pipeline only; skip Harness/API Gateway",
    )
    parser.add_argument(
        "--web-only",
        action="store_true",
        help="Discover/create CloudFront + upload html/ only (uses config.json API URL)",
    )
    parser.add_argument(
        "--skip-web",
        action="store_true",
        help="Skip CloudFront / static web upload",
    )
    args = parser.parse_args()

    if args.harness_only and args.skip_harness:
        parser.error("--harness-only and --skip-harness are mutually exclusive")

    if args.debug:
        logger.setLevel(logging.DEBUG)

    region = args.region
    sts_client = boto3.client("sts", region_name=region)
    account_id = sts_client.get_caller_identity()["Account"]
    bucket_name = load_bucket_name_from_config() or resolve_bucket_name(
        account_id, region
    )
    s3_client = boto3.client("s3", region_name=region)
    iam_client = boto3.client("iam", region_name=region)
    kinesis_client = boto3.client("kinesis", region_name=region)
    dynamodb_client = boto3.client("dynamodb", region_name=region)
    lambda_client = boto3.client("lambda", region_name=region)
    events_client = boto3.client("events", region_name=region)
    glue_client = boto3.client("glue", region_name=region)
    firehose_client = boto3.client("firehose", region_name=region)
    apigatewayv2_client = boto3.client("apigatewayv2", region_name=region)
    cloudfront_client = boto3.client("cloudfront", region_name="us-east-1")
    agentcore_control_client = boto3.client(
        "bedrock-agentcore-control",
        region_name=region,
    )

    logger.info("=" * 60)
    logger.info("Starting AWS Infrastructure Deployment")
    logger.info("=" * 60)
    logger.info(f"Project: {project_name}")
    logger.info(f"Region: {region}")
    logger.info(f"Account ID: {account_id}")
    logger.info(f"Bucket Name: {bucket_name}")
    logger.info(f"Harness only: {args.harness_only}")
    logger.info(f"Skip harness: {args.skip_harness}")
    logger.info(f"Web only: {args.web_only}")
    logger.info(f"Skip web: {args.skip_web}")
    logger.info("=" * 60)

    start_time = time.time()
    config_payload: Dict = {
        "projectName": project_name,
        "accountId": account_id,
        "region": region,
    }

    try:
        if args.web_only:
            existing = load_config_json()
            config_payload.update(existing)
            discovered = discover_web_resources()
            config_payload.update(discovered)
            target_bucket = (
                discovered.get("bucketName")
                or existing.get("bucketName")
                or bucket_name
            )
            api_url = existing.get("apiGatewayUrl") or ""
            web_config = deploy_web_stack(target_bucket, api_url)
            config_payload.update(web_config)
            update_config_json(config_payload)
            elapsed_time = time.time() - start_time
            logger.info("")
            logger.info("=" * 60)
            logger.info("Web deployment completed")
            logger.info(f"  Website: {web_config.get('websiteUrl')}")
            logger.info(f"  S3: s3://{target_bucket}/{WEB_S3_PREFIX}/")
            logger.info(f"  API: {api_url or '(missing apiGatewayUrl in config.json)'}")
            logger.info(f"Total time: {elapsed_time / 60:.2f} minutes")
            logger.info("=" * 60)
            return

        if not args.harness_only:
            s3_info = create_s3_bucket()
            stream_arn = create_kinesis_stream()
            table_arn = create_dynamodb_table(stream_arn)

            lambda_kinesis_arn = create_lambda_kinesis(stream_arn)
            lambda_firehose_arn = create_lambda_firehose()
            lambda_businfo_arn = create_lambda_businfo(table_arn)

            create_kinesis_event_source(lambda_kinesis_arn, stream_arn)
            rule_arn = create_eventbridge_rule(lambda_businfo_arn)

            crawler_role_arn = create_crawler_role(s3_info["bucket_arn"])
            create_glue_database()
            create_glue_crawler(
                crawler_role_arn,
                s3_info["s3_path"],
                target_bucket=s3_info["bucket_name"],
            )

            translation_role_arn = create_translation_role(
                s3_info["bucket_arn"], lambda_firehose_arn
            )
            firehose_arn = create_firehose_delivery_stream(
                stream_arn,
                s3_info["bucket_arn"],
                translation_role_arn,
                lambda_firehose_arn,
            )

            config_payload.update(
                {
                    "bucketName": s3_info["bucket_name"],
                    "s3Arn": s3_info["bucket_arn"],
                    "s3Path": s3_info["s3_path"],
                    "streamName": stream_name,
                    "streamArn": stream_arn,
                    "tableName": table_name,
                    "tableArn": table_arn,
                    "lambdaKinesisName": lambda_kinesis_name,
                    "lambdaKinesisArn": lambda_kinesis_arn,
                    "lambdaFirehoseName": lambda_firehose_name,
                    "lambdaFirehoseArn": lambda_firehose_arn,
                    "lambdaBusinfoName": lambda_businfo_name,
                    "lambdaBusinfoArn": lambda_businfo_arn,
                    "eventRuleName": event_rule_name,
                    "eventRuleArn": rule_arn,
                    "crawlerRoleArn": crawler_role_arn,
                    "crawlerName": crawler_name,
                    "glueDatabaseName": glue_database_name,
                    "translationRoleArn": translation_role_arn,
                    "firehoseName": firehose_name,
                    "firehoseArn": firehose_arn,
                }
            )
        else:
            logger.warning("Skipping businfo pipeline (--harness-only)")
            s3_info = {
                "bucket_name": bucket_name,
                "bucket_arn": f"arn:aws:s3:::{bucket_name}",
                "s3_path": f"s3://{bucket_name}",
            }
            config_payload["bucketName"] = bucket_name

        harness_config: Dict[str, str] = {}
        if not args.skip_harness:
            harness_config = deploy_harness_stack(s3_info["bucket_name"])
            config_payload.update(harness_config)
        else:
            logger.warning("Skipping Harness / API Gateway (--skip-harness)")

        web_config: Dict[str, str] = {}
        if not args.skip_web:
            prior_cfg = load_config_json()
            jobs_url = (
                config_payload.get("apiJobsUrl")
                or prior_cfg.get("apiJobsUrl")
                or config_payload.get("apiGatewayUrl")
                or prior_cfg.get("apiGatewayUrl")
                or ""
            )
            health_url = (
                config_payload.get("apiGatewayHealthUrl")
                or prior_cfg.get("apiGatewayHealthUrl")
                or ""
            )
            web_config = deploy_web_stack(
                s3_info["bucket_name"],
                api_gateway_url=jobs_url,
                api_gateway_health_url=health_url,
                api_jobs_url=jobs_url,
            )
            config_payload.update(web_config)
        else:
            logger.warning("Skipping CloudFront / web upload (--skip-web)")

        elapsed_time = time.time() - start_time
        logger.info("")
        logger.info("=" * 60)
        logger.info("Infrastructure Deployment Completed Successfully!")
        logger.info("=" * 60)
        if not args.harness_only:
            logger.info(f"  S3 Bucket: {config_payload.get('bucketName')}")
            logger.info(f"  Kinesis Stream ARN: {config_payload.get('streamArn')}")
            logger.info(f"  DynamoDB Table: {config_payload.get('tableName')}")
            logger.info(f"  Firehose ARN: {config_payload.get('firehoseArn')}")
        if harness_config:
            logger.info(f"  Harness ARN: {harness_config.get('HARNESS_ARN')}")
            logger.info(f"  Harness ID: {harness_config.get('HARNESS_ID')}")
            logger.info(
                f"  Lambda Harness ARN: {harness_config.get('lambdaHarnessArn')}"
            )
            logger.info(f"  API Jobs URL: {harness_config.get('apiJobsUrl')}")
            logger.info(
                f"  API Invoke URL (sync/short): "
                f"{harness_config.get('apiGatewayInvokeUrl')}"
            )
            logger.info(f"  Jobs table: {harness_config.get('jobsTableName')}")
            logger.info(
                f"  Lambda Function URL: {harness_config.get('lambdaFunctionUrl')}"
            )
            logger.info(
                "  Tip: Web uses async POST /jobs + poll GET /jobs/{jobId} "
                "(avoids API GW ~29s limit)"
            )
        if web_config:
            logger.info(f"  Website URL: {web_config.get('websiteUrl')}")
            logger.info(
                f"  Web S3: s3://{web_config.get('bucketName')}/{WEB_S3_PREFIX}/"
            )
        logger.info("")
        logger.info(f"Total deployment time: {elapsed_time / 60:.2f} minutes")
        logger.info("=" * 60)

        update_config_json(config_payload)

    except Exception as e:
        elapsed_time = time.time() - start_time
        logger.error("")
        logger.error("=" * 60)
        logger.error("Deployment Failed!")
        logger.error("=" * 60)
        logger.error(f"Error: {e}")
        logger.error(f"Deployment time before failure: {elapsed_time / 60:.2f} minutes")
        logger.error("=" * 60)
        import traceback

        logger.error(traceback.format_exc())
        raise


if __name__ == "__main__":
    main()
