import os
import json
import re
import subprocess
import sys
import logging
from datetime import datetime

def install(package):
    subprocess.check_call([sys.executable, "-m", "pip", "install", package])

install('boto3')
import boto3

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logger = logging.getLogger()
logger.setLevel(LOG_LEVEL)
region = os.environ.get('Region', 'NoAWSRegionFound')
pipeline_name = os.environ.get('PipelineName', 'NoPipelineNameFound')

cloudwatch = boto3.client("cloudwatch", region)


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

        
def postprocess_handler():
    violations_file = "/opt/ml/processing/output/constraint_violations.json"
    if os.path.isfile(violations_file):
        f = open(violations_file)
        violations = json.load(f)
        metrics = list(get_baseline_drift(violations))
        
        put_cloudwatch_metric(pipeline_name, metrics)
        logger.info("Violation detected and added to cloudwatch")
    else: 
        logger.info("No constraint_violations file found. All good!")
