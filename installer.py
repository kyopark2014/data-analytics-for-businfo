#!/usr/bin/env python3
"""
AWS Infrastructure Installer using boto3
This script creates AWS infrastructure resources defined in cdk/lib/cdk-stack.ts.
CDK deploy is replaced by this boto3 installer (see ref/installer.py for the pattern).
"""

import argparse
import io
import json
import logging
import os
import subprocess
import time
import zipfile
from datetime import datetime
from typing import Dict, List, Optional

import boto3
from botocore.exceptions import ClientError

# Configuration
project_name = "businfo"
region = "us-west-2"

bucket_name_prefix = "businfo"
bucket_name = ""
stream_name = "businfo-stream"
table_name = "dynamodb-businfo"
glue_database_name = "businfo"
crawler_name = "translate-parquet-crawler"
crawler_role_name = "crawler-role-businfo"
translation_role_name = "businfo-translation-role"
firehose_name = "businfo-delivery-stream"
event_rule_name = "rule-businfo"

lambda_kinesis_name = "lambda-kinesis-businfo"
lambda_firehose_name = "lambda-firehose-businfo"
lambda_businfo_name = "lambda-businfo"

lambda_kinesis_role_name = "lambda-kinesis-businfo-role"
lambda_firehose_role_name = "lambda-firehose-businfo-role"
lambda_businfo_role_name = "lambda-businfo-role"
lambda_runtime = "nodejs20.x"

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


def package_lambda(source_dir: str, include_node_modules: bool = False) -> bytes:
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
            index_path = os.path.join(source_dir, "index.js")
            zf.write(index_path, "index.js")

    buffer.seek(0)
    return buffer.read()


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
    environment: Optional[Dict[str, str]] = None,
    include_node_modules: bool = False,
) -> str:
    """Create or update Lambda function."""
    logger.info(f"Deploying Lambda function: {function_name}")

    zip_bytes = package_lambda(source_dir, include_node_modules=include_node_modules)
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


def update_config_json(resource_info: Dict[str, str]):
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
    args = parser.parse_args()

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

    logger.info("=" * 60)
    logger.info("Starting AWS Infrastructure Deployment")
    logger.info("=" * 60)
    logger.info(f"Project: {project_name}")
    logger.info(f"Region: {region}")
    logger.info(f"Account ID: {account_id}")
    logger.info(f"Bucket Name: {bucket_name}")
    logger.info("=" * 60)

    start_time = time.time()

    try:
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

        elapsed_time = time.time() - start_time
        logger.info("")
        logger.info("=" * 60)
        logger.info("Infrastructure Deployment Completed Successfully!")
        logger.info("=" * 60)
        logger.info("Summary:")
        logger.info(f"  S3 Bucket: {s3_info['bucket_name']}")
        logger.info(f"  S3 ARN: {s3_info['bucket_arn']}")
        logger.info(f"  S3 Path: {s3_info['s3_path']}")
        logger.info(f"  Kinesis Stream ARN: {stream_arn}")
        logger.info(f"  DynamoDB Table: {table_name}")
        logger.info(f"  Lambda Kinesis ARN: {lambda_kinesis_arn}")
        logger.info(f"  Lambda Firehose ARN: {lambda_firehose_arn}")
        logger.info(f"  Lambda BusInfo ARN: {lambda_businfo_arn}")
        logger.info(f"  EventBridge Rule ARN: {rule_arn}")
        logger.info(f"  Crawler Role ARN: {crawler_role_arn}")
        logger.info(f"  Translation Role ARN: {translation_role_arn}")
        logger.info(f"  Firehose ARN: {firehose_arn}")
        logger.info("")
        logger.info(f"Total deployment time: {elapsed_time / 60:.2f} minutes")
        logger.info("=" * 60)

        update_config_json(
            {
                "projectName": project_name,
                "accountId": account_id,
                "region": region,
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
