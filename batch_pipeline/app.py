#!/usr/bin/env python3
import argparse
import json
import logging
import os

# Import the pipeline
from pipelines.pipeline import get_pipeline, upload_pipeline

from aws_cdk import core
from infra.batch_config import BatchConfig
from infra.sagemaker_pipeline_stack import SageMakerPipelineStack
from infra.model_registry import ModelRegistry


# Configure the logger
logger = logging.getLogger(__name__)
logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))


registry = ModelRegistry()


def create_pipeline(
    app: core.App,
    project_name: str,
    project_id: str,
    region: str,
    sagemaker_pipeline_role_arn: str,
    event_role_arn: str,
    artifact_bucket: str,
    stage_name: str,
):
    # Get the stage specific deployment config for sagemaker
    with open(f"{stage_name}-config.json", "r") as f:
        j = json.load(f)
        batch_config = BatchConfig(**j)

    # Set the model package group to project name
    package_group_name = project_name
    sagemaker_pipeline_name = f"{project_name}-batch-{stage_name}"
    sagemaker_pipeline_description = f"Batch Pipeline for {stage_name}"

    # If we don't have a specific champion variant defined, get the latest approved
    if batch_config.model_package_version is None:
        logger.info("Selecting latest approved")
        p = registry.get_latest_approved_packages(package_group_name, max_results=1)[0]
        batch_config.model_package_version = p["ModelPackageVersion"]
        batch_config.model_package_arn = p["ModelPackageArn"]
    else:
        # Get the versioned package and update ARN
        logger.info(f"Selecting variant version {batch_config.model_package_version}")
        p = registry.get_versioned_approved_packages(
            package_group_name,
            model_package_versions=[batch_config.model_package_version],
        )[0]
        batch_config.model_package_arn = p["ModelPackageArn"]

    # Set the default input data uri
    data_uri = f"s3://{artifact_bucket}/{project_id}/batch/{stage_name}"

    # set the output transform uri
    transform_uri = f"s3://{artifact_bucket}/{project_id}/transform/{stage_name}"

    # Get the pipeline execution to get the baseline uri
    pipeline_execution_arn = registry.get_pipeline_execution_arn(
        batch_config.model_package_arn
    )
    logger.info(f"Got pipeline exection arn: {pipeline_execution_arn}")
    model_uri = registry.get_model_artifact(pipeline_execution_arn)
    logger.info(f"Got model uri: {model_uri}")

    # If we have drift configuration then get the baseline uri
    baseline_uri = reporting_uri = sagemaker_pipeline_arn = None
    if batch_config.model_monitor_enabled:
        baseline_uri = registry.get_processing_output(pipeline_execution_arn)
        logger.info(f"Got baseline uri: {baseline_uri}")
        pipeline_path = pipeline_execution_arn.split("/", 1)[1]
        reporting_uri = (
            f"s3://{artifact_bucket}/{project_id}/monitoring/{pipeline_path}"
        )
        logger.info(f"Got reporting uri: {reporting_uri}")
        sagemaker_pipeline_arn = registry.get_pipeline_arn(pipeline_execution_arn)
        logger.info(f"Got pipeline arn: {sagemaker_pipeline_arn}")

    # Create batch pipeline
    pipeline = get_pipeline(
        region=region,
        role=sagemaker_pipeline_role_arn,
        pipeline_name=sagemaker_pipeline_name,
        default_bucket=artifact_bucket,
        base_job_prefix=project_id,
        data_uri=data_uri,
        model_uri=model_uri,
        transform_uri=transform_uri,
        baseline_uri=baseline_uri,
        reporting_uri=reporting_uri,
    )

    # Create the pipeline definition
    logger.info("Creating/updating a SageMaker Pipeline for batch transform")
    pipeline_definition_body = pipeline.definition()
    parsed = json.loads(pipeline_definition_body)
    logger.info(json.dumps(parsed, indent=2, sort_keys=True))

    # Upload the pipeline to S3 bucket/key and return JSON with key/value for for Cfn Stack parameters.
    # see: https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/aws-resource-sagemaker-pipeline.html
    logger.info(f"Uploading {stage_name} pipeline to {artifact_bucket}")
    pipeline_definition_key = upload_pipeline(
        pipeline,
        default_bucket=artifact_bucket,
        base_job_prefix=f"{project_id}/batch-{stage_name}",
    )

    tags = [
        core.CfnTag(key="sagemaker:deployment-stage", value=stage_name),
        core.CfnTag(key="sagemaker:project-id", value=project_id),
        core.CfnTag(key="sagemaker:project-name", value=project_name),
    ]

    SageMakerPipelineStack(
        app,
        f"drift-batch-{stage_name}",
        pipeline_name=sagemaker_pipeline_name,
        pipeline_description=sagemaker_pipeline_description,
        pipeline_definition_bucket=artifact_bucket,
        pipeline_definition_key=pipeline_definition_key,
        sagemaker_role_arn=sagemaker_pipeline_role_arn,
        event_role_arn=event_role_arn,
        tags=tags,
        reporting_uri=reporting_uri,
        sagemaker_pipeline_arn=sagemaker_pipeline_arn,
    )


def main(
    project_name: str,
    project_id: str,
    region: str,
    sagemaker_pipeline_role_arn: str,
    event_role_arn: str,
    artifact_bucket: str,
):
    # Create App and stacks
    app = core.App()

    create_pipeline(
        app=app,
        project_name=project_name,
        project_id=project_id,
        region=region,
        sagemaker_pipeline_role_arn=sagemaker_pipeline_role_arn,
        event_role_arn=event_role_arn,
        artifact_bucket=artifact_bucket,
        stage_name="staging",
    )

    create_pipeline(
        app=app,
        project_name=project_name,
        project_id=project_id,
        region=region,
        sagemaker_pipeline_role_arn=sagemaker_pipeline_role_arn,
        event_role_arn=event_role_arn,
        artifact_bucket=artifact_bucket,
        stage_name="prod",
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
        "--sagemaker-pipeline-role-arn",
        default=os.environ.get("SAGEMAKER_PIPELINE_ROLE_ARN"),
    )
    parser.add_argument(
        "--event-role-arn",
        default=os.environ.get("EVENT_ROLE_ARN"),
    )
    parser.add_argument(
        "--artifact-bucket",
        default=os.environ.get("ARTIFACT_BUCKET"),
    )
    args = vars(parser.parse_args())
    logger.info("args: {}".format(args))
    main(**args)
