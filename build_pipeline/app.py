#!/usr/bin/env python3
import argparse
import logging
import os

import aws_cdk as cdk

from infra.sagemaker_pipeline_stack import SageMakerPipelineStack
from pipelines.pipeline import get_pipeline

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
    commit_id=None,
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
        commit_id=commit_id,
    )

    # Create the pipeline definition
    logger.info("Creating/updating a SageMaker Pipeline")
    pipeline_definition_body = pipeline.definition()

    # Create App and stacks
    app = cdk.App()

    tags = [
        cdk.CfnTag(key="sagemaker:project-id", value=project_id),
        cdk.CfnTag(key="sagemaker:project-name", value=project_name),
    ]

    stack_synthesizer = cdk.DefaultStackSynthesizer(
        # Name of the S3 bucket for file assets
        file_assets_bucket_name=artifact_bucket,
        bucket_prefix="build-pipeline-cdk-assets/",
        generate_bootstrap_version_rule=False,
    )

    SageMakerPipelineStack(
        app,
        "drift-sagemaker-pipeline",
        model_package_group_name=model_package_group_name,
        pipeline_name=sagemaker_pipeline_name,
        pipeline_description=sagemaker_pipeline_description,
        pipeline_definition=pipeline_definition_body,
        role_arn=sagemaker_pipeline_role,
        tags=tags,
        synthesizer=stack_synthesizer,
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
    parser.add_argument(
        "--commit-id",
        default=os.environ.get("COMMIT_ID"),
    )
    args = vars(parser.parse_args())
    logger.info("args: {}".format(args))
    main(**args)
