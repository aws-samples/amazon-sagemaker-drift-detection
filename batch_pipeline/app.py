#!/usr/bin/env python3
import argparse
import json
import logging
import os

import aws_cdk as cdk

from infra.batch_config import BatchConfig
from infra.model_registry import ModelRegistry
from infra.sagemaker_pipeline_stack import SageMakerPipelineStack

# Configure the logger
logger = logging.getLogger(__name__)
logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))


registry = ModelRegistry()


def create_pipeline(
    app: cdk.App,
    project_name: str,
    project_id: str,
    sagemaker_pipeline_role_arn: str,
    artifact_bucket: str,
    stage_name: str,
):
    # Get the stage specific deployment config for sagemaker
    with open(f"{stage_name}-config.json", "r") as f:
        j = json.load(f)
        batch_config = BatchConfig(**j)

    # Set the model package group to project name
    package_group_name = project_name

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

    # Set the sagemaker pipeline name and description with model version
    sagemaker_pipeline_name = f"{project_name}-batch-{stage_name}"
    sagemaker_pipeline_description = (
        f"Batch Pipeline for {stage_name} model version:"
        f"{batch_config.model_package_version}"
    )

    tags = [
        cdk.CfnTag(key="sagemaker:deployment-stage", value=stage_name),
        cdk.CfnTag(key="sagemaker:project-id", value=project_id),
        cdk.CfnTag(key="sagemaker:project-name", value=project_name),
    ]

    SageMakerPipelineStack(
        app,
        f"drift-batch-{stage_name}",
        pipeline_name=sagemaker_pipeline_name,
        pipeline_description=sagemaker_pipeline_description,
        sagemaker_role_arn=sagemaker_pipeline_role_arn,
        default_bucket=artifact_bucket,
        tags=tags,
        batch_config=batch_config,
        drift_config=batch_config.drift_config,
    )


def main(
    project_name: str,
    project_id: str,
    region: str,
    sagemaker_pipeline_role_arn: str,
    artifact_bucket: str,
    # evaluate_drift_function_arn: str,
):
    # Create App and stacks
    app = cdk.App()

    create_pipeline(
        app=app,
        project_name=project_name,
        project_id=project_id,
        sagemaker_pipeline_role_arn=sagemaker_pipeline_role_arn,
        artifact_bucket=artifact_bucket,
        stage_name="staging",
    )

    create_pipeline(
        app=app,
        project_name=project_name,
        project_id=project_id,
        sagemaker_pipeline_role_arn=sagemaker_pipeline_role_arn,
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
    # parser.add_argument(
    #     "--evaluate-drift-function-arn",
    #     default=os.environ.get("EVALUATE_DRIFT_FUNCTION_ARN"),
    # )
    parser.add_argument(
        "--artifact-bucket",
        default=os.environ.get("ARTIFACT_BUCKET"),
    )
    args = vars(parser.parse_args())
    logger.info("args: {}".format(args))
    main(**args)
