import boto3
from botocore.config import Config
from botocore.exceptions import ClientError
import json
import os
import logging

# Get environment variables
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

# Configure logging
logger = logging.getLogger()
logger.setLevel(LOG_LEVEL)


config = Config(retries={"max_attempts": 10, "mode": "standard"})
codepipeline = boto3.client("codepipeline", config=config)
sm_client = boto3.client("sagemaker")


def check_pipeline(job_id, pipeline_name, pipeline_execution_arn=None):
    try:
        if pipeline_execution_arn is None:
            logger.info(
                f"Starting SageMaker Pipeline: {pipeline_name} for job: {job_id}"
            )
            response = sm_client.start_pipeline_execution(
                PipelineName=pipeline_name,
                PipelineExecutionDisplayName=f"codepipeline-{job_id}",
                PipelineParameters=[
                    {"Name": "InputSource", "Value": "CodePipeline"},
                ],
                PipelineExecutionDescription="SageMaker Drift Detection Pipeline",
                ClientRequestToken=job_id,
            )
            logger.debug(response)
            pipeline_execution_arn = response["PipelineExecutionArn"]
            logger.info(f"SageMaker Pipeline arn: {pipeline_execution_arn} started")
        else:
            logger.info(
                f"Checking SageMaker Pipeline: {pipeline_execution_arn} for job: {job_id}"
            )
            response = sm_client.describe_pipeline_execution(
                PipelineExecutionArn=pipeline_execution_arn
            )
            logger.debug(response)
            pipeline_execution_status = response["PipelineExecutionStatus"]
            logger.info(
                f"SageMaker Pipeline arn: {pipeline_execution_arn} {pipeline_execution_status}"
            )
            if pipeline_execution_status in ["Failed", "Stopped"]:
                # Set to failure if Failed or Stopped
                result = {
                    "type": "JobFailed",
                    "message": f"Pipeline Status is {pipeline_execution_status}",
                    "externalExecutionId": pipeline_execution_arn,
                }
                codepipeline.put_job_failure_result(jobId=job_id, failureDetails=result)
                return 400, result
            elif pipeline_execution_status in ["Executing", "Succeeded"]:
                # Set to success if Executing or Succeeded
                result = {
                    "Status": pipeline_execution_status,
                    "PipelineExecutionArn": pipeline_execution_arn,
                }
                codepipeline.put_job_success_result(
                    jobId=job_id, outputVariables=result
                )
                return 200, result
        # Update status to pending passing continuation token
        logger.info(f"Continuing code pipeline job: {job_id}")
        codepipeline.put_job_success_result(
            jobId=job_id,
            continuationToken=pipeline_execution_arn,
        )
        return 202, {"PipelineExecutionArn": pipeline_execution_arn}
    except ClientError as e:
        logger.error(e)
        # Get boto3 specific error message
        error_code = e.response["Error"]["Code"]
        error_message = e.response["Error"]["Message"]
        result = {
            "type": "JobFailed",
            "message": error_message,
        }
        logger.error(error_message)
        if error_code != "InvalidJobStateException":
            codepipeline.put_job_failure_result(jobId=job_id, failureDetails=result)
        return 500, result
    except Exception as e:
        logger.error(e)
        raise e


def lambda_handler(event, context):
    logger.debug(json.dumps(event))

    # Get the code pipeline job id and data
    job_id = event["CodePipeline.job"]["id"]
    job_data = event["CodePipeline.job"]["data"]
    # Get the pipeline name from the user parameters
    user_parameters = job_data["actionConfiguration"]["configuration"]["UserParameters"]
    pipeline_name = json.loads(user_parameters)["PipelineName"]
    # Check if we have a continuation token
    if "continuationToken" in job_data:
        pipeline_execution_arn = job_data["continuationToken"]
    else:
        pipeline_execution_arn = None

    # Return the status to check the pipeline
    status_code, result = check_pipeline(job_id, pipeline_name, pipeline_execution_arn)

    # Log result succesful result and return
    logger.debug(json.dumps(result))
    return {"statusCode": status_code, "body": json.dumps(result)}
