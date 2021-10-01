import boto3
from datetime import datetime
import logging
import os
import re
import json
from urllib.parse import urlparse

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

logger = logging.getLogger()
logger.setLevel(LOG_LEVEL)
sm_client = boto3.client("sagemaker")
s3_client = boto3.client("s3")
cloudwatch = boto3.client("cloudwatch")


def get_processing_job(processing_job_name):
    response = sm_client.describe_processing_job(ProcessingJobName=processing_job_name)
    status = response["ProcessingJobStatus"]
    exit_message = response["ExitMessage"]
    s3_result_uri = response["ProcessingOutputConfig"]["Outputs"][0]["S3Output"][
        "S3Uri"
    ]
    url_parsed = urlparse(s3_result_uri)
    result_bucket, result_path = url_parsed.netloc, url_parsed.path.lstrip("/")
    return status, exit_message, result_bucket, result_path


def get_s3_results_json(bucket_name, key_prefix, filename):
    s3_object = s3_client.get_object(
        Bucket=bucket_name,
        Key=os.path.join(key_prefix, filename),
    )
    return json.loads(s3_object["Body"].read())


def get_baseline_drift(feature):
    if "violations" in feature:
        for violation in feature["violations"]:
            if violation["constraint_check_type"] == "baseline_drift_check":
                desc = violation["description"]
                matches = re.search("distance: (.+) exceeds threshold: (.+)", desc)
                if matches:
                    yield {
                        "metric_name": f'feature_baseline_drift_{violation["feature_name"]}',
                        "metric_value": float(matches.group(1)),
                        "metric_threshold": float(matches.group(2)),
                    }


def put_cloudwatch_metric(pipeline_name: str, metrics: list):
    for m in metrics:
        logger.info(f'Putting metric: {m["metric_name"]} value: {m["metric_value"]}')
        response = cloudwatch.put_metric_data(
            Namespace="aws/sagemaker/ModelBuildingPipeline/data-metrics",
            MetricData=[
                {
                    "MetricName": m["metric_name"],
                    "Dimensions": [{"Name": "PipelineName", "Value": pipeline_name}],
                    "Timestamp": datetime.now(),
                    "Value": m["metric_value"],
                    "Unit": "None",
                },
            ],
        )
        logger.debug(response)


def lambda_handler(event, context):
    if "ProcessingJobName" in event:
        job_name = event["ProcessingJobName"]
    else:
        raise KeyError("ProcessingJobName  not found in event")
    if "PipelineName" in event:
        pipeline_name = event["PipelineName"]
    else:
        raise KeyError("PipelineName  not found in event")
    try:
        # Parse the result uri
        status, exit_message, result_bucket, result_path = get_processing_job(job_name)
        logger.info(f"Processing job: {job_name} has status: {status}")
        metrics = None
        status_code = 200
        if status == "Completed":
            try:
                violations = get_s3_results_json(
                    result_bucket, result_path, "constraint_violations.json"
                )
                status_code = 400
                status = "CompletedWithViolations"
                metrics = list(get_baseline_drift(violations))
                put_cloudwatch_metric(pipeline_name, metrics)
            except:
                logger.info("No violations")
        return {
            "statusCode": status_code,
            "body": json.dumps(
                {
                    "ProcessingJobStatus": status,
                    "ExitMessage": exit_message,
                    "Metrics": metrics,
                }
            ),
        }
    except Exception as e:
        logger.error(e)
        return {"statusCode": 500, "error": str(e)}
