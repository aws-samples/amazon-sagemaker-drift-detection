import boto3
from botocore.config import Config
from botocore.exceptions import ClientError
import json
import os
import logging

CODE_PIPELINE_NAME = os.environ["CODE_PIPELINE_NAME"]
DRIFT_RULE_NAME = os.environ["DRIFT_RULE_NAME"]
SCHEDULE_RULE_NAME = os.environ["SCHEDULE_RULE_NAME"]
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

logger = logging.getLogger()
logger.setLevel(LOG_LEVEL)
config = Config(retries={"max_attempts": 10, "mode": "standard"})
codepipeline = boto3.client("codepipeline", config=config)
cwe = boto3.client("events", config=config)


def update_cloudwatch_rule(rule_name: str, enable: bool):
    try:
        logger.info(f"Update rule: {rule_name}, enable: {enable}")
        if enable:
            response = cwe.enable_rule(Name=rule_name)
        else:
            response = cwe.disable_rule(Name=rule_name)
        logger.debug(response)
    except ClientError as e:
        error_code = e.response["Error"]["Code"]
        error_message = e.response["Error"]["Message"]
        if error_code == "ResourceNotFoundException":
            logger.warning(f"Rule {rule_name} not found")
        else:
            logger.error(error_message)
            raise Exception(error_message)


def update_pipeline_rules(event):
    execution_status = event["detail"]["currentPipelineExecutionStatus"]
    pipeline_execution_arn = event["detail"]["pipelineExecutionArn"]
    stage_name = "Build"
    if execution_status == "Executing":
        logger.info(
            f"Disabling code pipeline: {CODE_PIPELINE_NAME}, stage: {stage_name}"
        )
        response = codepipeline.disable_stage_transition(
            pipelineName=CODE_PIPELINE_NAME,
            stageName=stage_name,
            transitionType="Inbound",
            reason=f"Running SageMaker Pipeline Execution: {pipeline_execution_arn}",
        )
        logger.debug(response)
        for rule_name in [DRIFT_RULE_NAME, SCHEDULE_RULE_NAME]:
            update_cloudwatch_rule(rule_name, enable=False)
        return 200, {"action": "Start"}
    else:
        logger.info(
            f"Enabling code pipeline: {CODE_PIPELINE_NAME}, stage: {stage_name}"
        )
        response = codepipeline.enable_stage_transition(
            pipelineName=CODE_PIPELINE_NAME,
            stageName=stage_name,
            transitionType="Inbound",
        )
        logger.debug(response)
        for rule_name in [DRIFT_RULE_NAME, SCHEDULE_RULE_NAME]:
            update_cloudwatch_rule(rule_name, enable=True)
        return 200, {"action": "Stop", "status": execution_status}


def lambda_handler(event, context):
    try:
        logger.debug(json.dumps(event))
        if (
            event.get("source") == "aws.sagemaker"
            and event.get("detail-type")
            == "SageMaker Model Building Pipeline Execution Status Change"
        ):
            status_code, result = update_pipeline_rules(event)
        else:
            raise Exception("Expect SageMaker Model Package State Change")
        logger.debug(json.dumps(result))
        return {"statusCode": status_code, "body": json.dumps(result)}
    except ClientError as e:
        error_message = e.response["Error"]["Message"]
        logger.error(error_message)
        raise Exception(error_message)
    except Exception as e:
        logger.error(e)
        raise e
