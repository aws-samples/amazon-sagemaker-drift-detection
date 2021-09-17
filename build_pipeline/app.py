#!/usr/bin/env python3
import argparse
import json
import logging
import os

# Import the pipeline
from pipelines.pipeline import get_pipeline, upload_pipeline

from aws_cdk import core
from infra.sagemaker_pipeline_stack import SageMakerPipelineStack

# Configure the logger
logger = logging.getLogger(__name__)
logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))


def main(
    project_name,
    project_id,
    region,
    sagemaker_pipeline_name,
    sagemaker_pipeline_description,
    sagemaker_pipeline_role,
    artifact_bucket,
):
    # Use project_name for pipeline and model package group name
    model_package_group_name = project_name
    pipeline = get_pipeline(
        region=region,
        role=sagemaker_pipeline_role,
        default_bucket=artifact_bucket,
        model_package_group_name=model_package_group_name,
        pipeline_name=sagemaker_pipeline_name,
        base_job_prefix=project_id,
    )

    # Create the pipeline definition
    logger.info("Creating/updating a SageMaker Pipeline")
    pipeline_definition_body = pipeline.definition()
    parsed = json.loads(pipeline_definition_body)
    logger.debug(json.dumps(parsed, indent=2, sort_keys=True))

    # Upload the pipeline to S3 bucket and return the target key
    # see: https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/aws-resource-sagemaker-pipeline.html
    pipeline_definition_key = upload_pipeline(
        pipeline,
        default_bucket=artifact_bucket,
        base_job_prefix=f"{project_id}/build",
    )

    # Create App and stacks
    app = core.App()

    tags = [
        core.CfnTag(key="sagemaker:project-id", value=project_id),
        core.CfnTag(key="sagemaker:project-name", value=project_name),
    ]

    SageMakerPipelineStack(
        app,
        "drift-sagemaker-pipeline",
        model_package_group_name=model_package_group_name,
        pipeline_name=sagemaker_pipeline_name,
        pipeline_description=sagemaker_pipeline_description,
        pipeline_definition_bucket=artifact_bucket,
        pipeline_definition_key=pipeline_definition_key,
        role_arn=sagemaker_pipeline_role,
        tags=tags,
    )

    app.synth()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Load parameters")
    parser.add_argument("--region", default=os.environ.get("AWS_REGION"))
    parser.add_argument(
        "--project-name",
        default=os.environ.get("SAGEMAKER_PROJECT_NAME"),
    )
    parser.add_argument("--project-id", default=os.environ.get("SAGEMAKER_PROJECT_ID"))
    parser.add_argument(
        "--sagemaker-pipeline-name",
        default=os.environ.get("SAGEMAKER_PIPELINE_NAME"),
    )
    parser.add_argument(
        "--sagemaker-pipeline-description",
        default=os.environ.get("SAGEMAKER_PIPELINE_DESCRIPTION"),
    )
    parser.add_argument(
        "--sagemaker-pipeline-role",
        default=os.environ.get("SAGEMAKER_PIPELINE_ROLE_ARN"),
    )
    parser.add_argument(
        "--artifact-bucket",
        default=os.environ.get("ARTIFACT_BUCKET"),
    )
    args = vars(parser.parse_args())
    logger.info("args: {}".format(args))
    main(**args)
