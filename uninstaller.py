#!/usr/bin/env python3
"""
AWS Infrastructure Uninstaller using boto3
This script deletes all AWS infrastructure resources created by installer.py.
See ref/uninstaller.py for the pattern.
"""

import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
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

script_dir = os.path.dirname(os.path.abspath(__file__))

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
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[logging.StreamHandler()],
    )
    return logging.getLogger(__name__)


logger = setup_logging()


def resolve_bucket_name(acct_id: str, aws_region: str) -> str:
    """Build the default S3 bucket name for this account and region."""
    return f"{bucket_name_prefix}-{acct_id}-{aws_region}".lower()


def load_config() -> Dict:
    """Load deployment configuration from config.json."""
    config_path = os.path.join(script_dir, "config.json")
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            content = f.read().strip()
            if content:
                return json.loads(content)
    except (FileNotFoundError, json.JSONDecodeError, OSError) as e:
        logger.debug(f"Could not load config.json: {e}")
    return {}


def apply_config_overrides(config: Dict):
    """Apply resource names from config.json when available."""
    global bucket_name, stream_name, table_name, firehose_name, event_rule_name
    global lambda_kinesis_name, lambda_firehose_name, lambda_businfo_name
    global crawler_name, glue_database_name, crawler_role_name, translation_role_name
    global lambda_kinesis_role_name, lambda_firehose_role_name, lambda_businfo_role_name

    bucket_name = config.get("bucketName") or bucket_name
    stream_name = config.get("streamName") or stream_name
    table_name = config.get("tableName") or table_name
    firehose_name = config.get("firehoseName") or firehose_name
    event_rule_name = config.get("eventRuleName") or event_rule_name
    lambda_kinesis_name = config.get("lambdaKinesisName") or lambda_kinesis_name
    lambda_firehose_name = config.get("lambdaFirehoseName") or lambda_firehose_name
    lambda_businfo_name = config.get("lambdaBusinfoName") or lambda_businfo_name
    crawler_name = config.get("crawlerName") or crawler_name
    glue_database_name = config.get("glueDatabaseName") or glue_database_name


def update_config_json(deletion_summary: Dict):
    """Update config.json after infrastructure deletion."""
    config_path = os.path.join(script_dir, "config.json")
    config_data = load_config()

    resource_keys = [
        "bucketName",
        "s3Arn",
        "s3Path",
        "streamName",
        "streamArn",
        "tableName",
        "tableArn",
        "lambdaKinesisName",
        "lambdaKinesisArn",
        "lambdaFirehoseName",
        "lambdaFirehoseArn",
        "lambdaBusinfoName",
        "lambdaBusinfoArn",
        "eventRuleName",
        "eventRuleArn",
        "crawlerRoleArn",
        "crawlerName",
        "glueDatabaseName",
        "translationRoleArn",
        "firehoseName",
        "firehoseArn",
    ]
    for key in resource_keys:
        config_data.pop(key, None)

    config_data.update(
        {
            "projectName": project_name,
            "accountId": account_id,
            "region": region,
            "deploymentStatus": "uninstalled",
            "uninstalledAt": datetime.now(timezone.utc).isoformat(),
            "deletionSummary": deletion_summary,
        }
    )

    try:
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(config_data, f, indent=2, ensure_ascii=False)
            f.write("\n")
        logger.info(f"✓ Updated {config_path}")
    except Exception as e:
        logger.warning(f"Could not update {config_path}: {e}")


def delete_firehose_delivery_stream() -> bool:
    """Delete Kinesis Data Firehose delivery stream."""
    logger.info(f"[1/11] Deleting Firehose delivery stream: {firehose_name}")

    try:
        firehose_client.delete_delivery_stream(
            DeliveryStreamName=firehose_name,
            AllowForceDelete=True,
        )
        logger.info(f"✓ Firehose delivery stream deleted: {firehose_name}")
        return True
    except ClientError as e:
        if e.response["Error"]["Code"] == "ResourceNotFoundException":
            logger.warning(f"Firehose delivery stream not found: {firehose_name}")
            return False
        logger.error(f"Failed to delete Firehose delivery stream: {e}")
        raise


def delete_glue_crawler() -> bool:
    """Delete Glue crawler."""
    logger.info(f"[2/11] Deleting Glue crawler: {crawler_name}")

    try:
        try:
            glue_client.stop_crawler(Name=crawler_name)
            logger.debug("Stopped Glue crawler before deletion")
            time.sleep(5)
        except ClientError as e:
            if e.response["Error"]["Code"] not in (
                "EntityNotFoundException",
                "CrawlerNotRunningException",
            ):
                logger.debug(f"Could not stop crawler: {e}")

        glue_client.delete_crawler(Name=crawler_name)
        logger.info(f"✓ Glue crawler deleted: {crawler_name}")
        return True
    except ClientError as e:
        if e.response["Error"]["Code"] == "EntityNotFoundException":
            logger.warning(f"Glue crawler not found: {crawler_name}")
            return False
        logger.error(f"Failed to delete Glue crawler: {e}")
        raise


def delete_glue_database() -> bool:
    """Delete Glue database and its tables."""
    logger.info(f"[3/11] Deleting Glue database: {glue_database_name}")

    try:
        tables = glue_client.get_tables(DatabaseName=glue_database_name)
        for table in tables.get("TableList", []):
            table_name_value = table["Name"]
            glue_client.delete_table(
                DatabaseName=glue_database_name,
                Name=table_name_value,
            )
            logger.info(f"  ✓ Deleted Glue table: {table_name_value}")

        glue_client.delete_database(Name=glue_database_name)
        logger.info(f"✓ Glue database deleted: {glue_database_name}")
        return True
    except ClientError as e:
        if e.response["Error"]["Code"] == "EntityNotFoundException":
            logger.warning(f"Glue database not found: {glue_database_name}")
            return False
        logger.error(f"Failed to delete Glue database: {e}")
        raise


def delete_eventbridge_rule() -> bool:
    """Delete EventBridge rule and Lambda invoke permission."""
    logger.info(f"[4/11] Deleting EventBridge rule: {event_rule_name}")

    deleted = False
    try:
        try:
            events_client.remove_targets(Rule=event_rule_name, Ids=["Target0"])
        except ClientError as e:
            if e.response["Error"]["Code"] != "ResourceNotFoundException":
                logger.debug(f"Could not remove EventBridge targets: {e}")

        events_client.delete_rule(Name=event_rule_name)
        logger.info(f"✓ EventBridge rule deleted: {event_rule_name}")
        deleted = True
    except ClientError as e:
        if e.response["Error"]["Code"] == "ResourceNotFoundException":
            logger.warning(f"EventBridge rule not found: {event_rule_name}")
        else:
            logger.error(f"Failed to delete EventBridge rule: {e}")
            raise

    try:
        lambda_client.remove_permission(
            FunctionName=lambda_businfo_name,
            StatementId=f"eventbridge-{event_rule_name}",
        )
        logger.info("✓ Removed EventBridge invoke permission from Lambda")
    except ClientError as e:
        if e.response["Error"]["Code"] != "ResourceNotFoundException":
            logger.debug(f"Could not remove Lambda permission: {e}")

    return deleted


def delete_lambda_event_source_mappings() -> int:
    """Delete Lambda event source mappings for project Lambdas."""
    logger.info("[5/11] Deleting Lambda event source mappings")

    deleted_count = 0
    function_names = [lambda_kinesis_name, lambda_firehose_name, lambda_businfo_name]

    for function_name in function_names:
        try:
            mappings = lambda_client.list_event_source_mappings(
                FunctionName=function_name
            )
            for mapping in mappings.get("EventSourceMappings", []):
                uuid = mapping["UUID"]
                lambda_client.delete_event_source_mapping(UUID=uuid)
                logger.info(
                    f"  ✓ Deleted event source mapping {uuid} for {function_name}"
                )
                deleted_count += 1
        except ClientError as e:
            if e.response["Error"]["Code"] != "ResourceNotFoundException":
                logger.warning(
                    f"  Could not delete event source mappings for {function_name}: {e}"
                )

    logger.info(f"✓ Lambda event source mappings deleted: {deleted_count}")
    return deleted_count


def delete_lambda_function(function_name: str) -> bool:
    """Delete a single Lambda function."""
    try:
        lambda_client.delete_function(FunctionName=function_name)
        logger.info(f"  ✓ Deleted Lambda function: {function_name}")
        return True
    except ClientError as e:
        if e.response["Error"]["Code"] == "ResourceNotFoundException":
            logger.warning(f"  Lambda function not found: {function_name}")
            return False
        raise


def delete_lambda_functions() -> int:
    """Delete all project Lambda functions."""
    logger.info("[6/11] Deleting Lambda functions")

    deleted_count = 0
    for function_name in [
        lambda_kinesis_name,
        lambda_firehose_name,
        lambda_businfo_name,
    ]:
        if delete_lambda_function(function_name):
            deleted_count += 1

    logger.info(f"✓ Lambda functions deleted: {deleted_count}")
    return deleted_count


def delete_dynamodb_table(config: Dict) -> bool:
    """Disable Kinesis streaming and delete DynamoDB table."""
    logger.info(f"[7/11] Deleting DynamoDB table: {table_name}")

    stream_arn = config.get("streamArn")
    if stream_arn:
        try:
            dynamodb_client.disable_kinesis_streaming_destination(
                TableName=table_name,
                StreamArn=stream_arn,
            )
            logger.info("✓ Disabled DynamoDB Kinesis streaming destination")
        except ClientError as e:
            if e.response["Error"]["Code"] not in (
                "ResourceNotFoundException",
                "ValidationException",
            ):
                logger.debug(f"Could not disable Kinesis streaming: {e}")

    try:
        dynamodb_client.delete_table(TableName=table_name)
        logger.info(f"✓ DynamoDB table deleted: {table_name}")
        return True
    except ClientError as e:
        if e.response["Error"]["Code"] == "ResourceNotFoundException":
            logger.warning(f"DynamoDB table not found: {table_name}")
            return False
        logger.error(f"Failed to delete DynamoDB table: {e}")
        raise


def delete_kinesis_stream() -> bool:
    """Delete Kinesis data stream."""
    logger.info(f"[8/11] Deleting Kinesis stream: {stream_name}")

    try:
        kinesis_client.delete_stream(StreamName=stream_name, EnforceConsumerDeletion=True)
        logger.info(f"✓ Kinesis stream deleted: {stream_name}")
        return True
    except ClientError as e:
        if e.response["Error"]["Code"] == "ResourceNotFoundException":
            logger.warning(f"Kinesis stream not found: {stream_name}")
            return False
        logger.error(f"Failed to delete Kinesis stream: {e}")
        raise


def delete_iam_role(role_name: str) -> bool:
    """Delete IAM role and attached policies."""
    try:
        attached_policies = iam_client.list_attached_role_policies(RoleName=role_name)
        for policy in attached_policies.get("AttachedPolicies", []):
            iam_client.detach_role_policy(
                RoleName=role_name,
                PolicyArn=policy["PolicyArn"],
            )

        inline_policies = iam_client.list_role_policies(RoleName=role_name)
        for policy_name in inline_policies.get("PolicyNames", []):
            iam_client.delete_role_policy(
                RoleName=role_name,
                PolicyName=policy_name,
            )

        iam_client.delete_role(RoleName=role_name)
        logger.info(f"  ✓ Deleted IAM role: {role_name}")
        return True
    except ClientError as e:
        if e.response["Error"]["Code"] == "NoSuchEntity":
            logger.warning(f"  IAM role not found: {role_name}")
            return False
        logger.warning(f"  Could not delete IAM role {role_name}: {e}")
        return False


def delete_iam_roles() -> int:
    """Delete all IAM roles created by installer.py."""
    logger.info("[9/11] Deleting IAM roles")

    role_names = [
        translation_role_name,
        crawler_role_name,
        lambda_businfo_role_name,
        lambda_firehose_role_name,
        lambda_kinesis_role_name,
    ]

    deleted_count = 0
    for role_name in role_names:
        if delete_iam_role(role_name):
            deleted_count += 1

    logger.info(f"✓ IAM roles deleted: {deleted_count}")
    return deleted_count


def empty_s3_bucket(target_bucket: str):
    """Delete all objects and versions from an S3 bucket."""
    try:
        paginator = s3_client.get_paginator("list_object_versions")
        delete_keys: List[Dict[str, str]] = []

        for page in paginator.paginate(Bucket=target_bucket):
            for version in page.get("Versions", []):
                delete_keys.append(
                    {
                        "Key": version["Key"],
                        "VersionId": version["VersionId"],
                    }
                )
            for marker in page.get("DeleteMarkers", []):
                delete_keys.append(
                    {
                        "Key": marker["Key"],
                        "VersionId": marker["VersionId"],
                    }
                )

        if delete_keys:
            for i in range(0, len(delete_keys), 1000):
                batch = delete_keys[i : i + 1000]
                s3_client.delete_objects(
                    Bucket=target_bucket,
                    Delete={"Objects": batch},
                )
            logger.info(
                f"  ✓ Deleted {len(delete_keys)} objects/versions from {target_bucket}"
            )

        paginator = s3_client.get_paginator("list_objects_v2")
        object_keys = []
        for page in paginator.paginate(Bucket=target_bucket):
            for obj in page.get("Contents", []):
                object_keys.append({"Key": obj["Key"]})

        if object_keys:
            for i in range(0, len(object_keys), 1000):
                batch = object_keys[i : i + 1000]
                s3_client.delete_objects(
                    Bucket=target_bucket,
                    Delete={"Objects": batch},
                )
            logger.info(
                f"  ✓ Deleted {len(object_keys)} objects from {target_bucket}"
            )
    except ClientError as e:
        if e.response["Error"]["Code"] != "NoSuchBucket":
            raise


def delete_s3_bucket() -> bool:
    """Delete S3 bucket and all objects."""
    logger.info(f"[10/11] Deleting S3 bucket: {bucket_name}")

    if not bucket_name:
        logger.warning("S3 bucket name is empty, skipping bucket deletion")
        return False

    try:
        empty_s3_bucket(bucket_name)
        s3_client.delete_bucket(Bucket=bucket_name)
        logger.info(f"✓ S3 bucket deleted: {bucket_name}")
        return True
    except ClientError as e:
        if e.response["Error"]["Code"] == "NoSuchBucket":
            logger.warning(f"S3 bucket not found: {bucket_name}")
            return False
        logger.error(f"Failed to delete S3 bucket: {e}")
        raise


def main():
    """Main cleanup function."""
    global region, sts_client, account_id, bucket_name
    global s3_client, iam_client, kinesis_client, dynamodb_client
    global lambda_client, events_client, glue_client, firehose_client

    parser = argparse.ArgumentParser(
        description="AWS Infrastructure Uninstaller for Bus Schedule Analytics"
    )
    parser.add_argument(
        "--region",
        default=region,
        help=f"AWS region (default: {region})",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Skip confirmation prompt and proceed with deletion",
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
    s3_client = boto3.client("s3", region_name=region)
    iam_client = boto3.client("iam", region_name=region)
    kinesis_client = boto3.client("kinesis", region_name=region)
    dynamodb_client = boto3.client("dynamodb", region_name=region)
    lambda_client = boto3.client("lambda", region_name=region)
    events_client = boto3.client("events", region_name=region)
    glue_client = boto3.client("glue", region_name=region)
    firehose_client = boto3.client("firehose", region_name=region)

    config = load_config()
    bucket_name = config.get("bucketName") or resolve_bucket_name(account_id, region)
    apply_config_overrides(config)

    logger.info("=" * 60)
    logger.info("Starting AWS Infrastructure Cleanup")
    logger.info("=" * 60)
    logger.info(f"Project: {project_name}")
    logger.info(f"Region: {region}")
    logger.info(f"Account ID: {account_id}")
    logger.info(f"Bucket Name: {bucket_name}")
    logger.info("=" * 60)

    if not args.yes:
        print("\n" + "=" * 60)
        print("WARNING: This will delete all resources created by installer.py")
        print("=" * 60)
        response = input("\nAre you sure you want to continue? (yes/no): ")
        if response.lower() != "yes":
            print("Uninstallation cancelled.")
            sys.exit(0)

    start_time = time.time()
    deletion_summary = {}

    try:
        deletion_summary["firehose"] = delete_firehose_delivery_stream()
        deletion_summary["glueCrawler"] = delete_glue_crawler()
        deletion_summary["glueDatabase"] = delete_glue_database()
        deletion_summary["eventRule"] = delete_eventbridge_rule()
        deletion_summary["lambdaEventSourceMappings"] = (
            delete_lambda_event_source_mappings()
        )
        deletion_summary["lambdaFunctions"] = delete_lambda_functions()
        deletion_summary["dynamodbTable"] = delete_dynamodb_table(config)
        deletion_summary["kinesisStream"] = delete_kinesis_stream()
        deletion_summary["iamRoles"] = delete_iam_roles()
        deletion_summary["s3Bucket"] = delete_s3_bucket()

        elapsed_time = time.time() - start_time
        logger.info("")
        logger.info("=" * 60)
        logger.info("Infrastructure Cleanup Completed Successfully!")
        logger.info("=" * 60)
        logger.info(f"Total cleanup time: {elapsed_time / 60:.2f} minutes")
        logger.info("=" * 60)

        update_config_json(deletion_summary)

    except Exception as e:
        elapsed_time = time.time() - start_time
        logger.error("")
        logger.error("=" * 60)
        logger.error("Cleanup Failed!")
        logger.error("=" * 60)
        logger.error(f"Error: {e}")
        logger.error(f"Cleanup time before failure: {elapsed_time / 60:.2f} minutes")
        logger.error("=" * 60)
        import traceback

        logger.error(traceback.format_exc())
        raise


if __name__ == "__main__":
    main()
