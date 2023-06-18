#!/usr/bin/env python3
import argparse
import json
import logging
import os

import aws_cdk as cdk

from infra.deployment_config import DeploymentConfig, VariantConfig
from infra.model_registry import ModelRegistry
from infra.sagemaker_stack import SageMakerStack

# Configure the logger
logger = logging.getLogger(__name__)
logging.basicConfig(level="INFO")

registry = ModelRegistry()


def create_endpoint(
    app: cdk.App,
    project_name: str,
    project_id: str,
    sagemaker_execution_role: str,
    artifact_bucket: str,
    stage_name: str,
):

    # Define variables for passing down to stacks
    endpoint_name = f"{project_name}-{stage_name}"
    if len(endpoint_name) > 63:
        raise Exception(
            f"SageMaker endpoint: {endpoint_name} must be less than 64 characters"
        )
    logger.info(f"Create endpoint: {endpoint_name}")

    # Define the deployment tags
    tags = [
        cdk.CfnTag(key="sagemaker:deployment-stage", value=stage_name),
        cdk.CfnTag(key="sagemaker:project-id", value=project_id),
        cdk.CfnTag(key="sagemaker:project-name", value=project_name),
    ]

    # Get the stage specific deployment config for sagemaker
    with open(f"{stage_name}-config.json", "r") as f:
        j = json.load(f)
        deployment_config = DeploymentConfig(**j)

    # Set the model package group to project name
    package_group_name = project_name

    # If we don't have a specific champion variant defined, get the latest approved
    if deployment_config.variant_config.model_package_version is None:
        logger.info("Selecting latest approved")
        p = registry.get_latest_approved_packages(package_group_name, max_results=1)[0]
        deployment_config.variant_config = VariantConfig(
            model_package_version=p["ModelPackageVersion"],
            model_package_arn=p["ModelPackageArn"],
            initial_variant_weight=1,
            instance_count=deployment_config.instance_count,
            instance_type=deployment_config.instance_type,
            variant_name=deployment_config.variant_config.variant_name
            or f"{package_group_name}-LatestApproved",
        )
    else:
        # Get the versioned package and update ARN
        version = deployment_config.variant_config.model_package_version
        logger.info(f"Selecting variant version {version}")
        p = registry.get_versioned_approved_packages(
            package_group_name,
            model_package_versions=[version],
        )[0]
        deployment_config.variant_config.model_package_arn = p["ModelPackageArn"]

    baseline_uri = registry.get_data_check_baseline_uri(p["ModelPackageArn"])
    logger.info(f"Got baseline uri: {baseline_uri}")

    data_capture_uri = f"s3://{artifact_bucket}/monitoring/datacapture"
    logger.info(f"Got data capture uri: {data_capture_uri}")

    reporting_uri = f"s3://{artifact_bucket}/monitoring/reports"
    logger.info(f"Got reporting uri: {reporting_uri}")

    stack_synthesizer = cdk.DefaultStackSynthesizer(
        file_assets_bucket_name=artifact_bucket,
        bucket_prefix="deploy-pipeline-cdk-assets/",
        generate_bootstrap_version_rule=False,
    )

    return SageMakerStack(
        app,
        f"drift-deploy-{stage_name}",
        sagemaker_execution_role=sagemaker_execution_role,
        deployment_config=deployment_config,
        endpoint_name=endpoint_name,
        baseline_uri=baseline_uri,
        data_capture_uri=data_capture_uri,
        reporting_uri=reporting_uri,
        tags=tags,
        synthesizer=stack_synthesizer,
    )


def main(
    project_name: str,
    project_id: str,
    sagemaker_execution_role: str,
    artifact_bucket: str,
):

    # Create App and stacks
    app = cdk.App()

    # Create two different stages for staging and prod
    create_endpoint(
        app,
        project_name=project_name,
        project_id=project_id,
        sagemaker_execution_role=sagemaker_execution_role,
        artifact_bucket=artifact_bucket,
        stage_name="staging",
    )
    create_endpoint(
        app,
        project_name=project_name,
        project_id=project_id,
        sagemaker_execution_role=sagemaker_execution_role,
        artifact_bucket=artifact_bucket,
        stage_name="prod",
    )

    app.synth()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Load parameters")
    parser.add_argument(
        "--project-name",
        default=os.environ.get("SAGEMAKER_PROJECT_NAME"),
    )
    parser.add_argument("--project-id", default=os.environ.get("SAGEMAKER_PROJECT_ID"))
    parser.add_argument(
        "--sagemaker-execution-role",
        default=os.environ.get("SAGEMAKER_EXECUTION_ROLE_ARN"),
    )
    parser.add_argument(
        "--artifact-bucket",
        default=os.environ.get("ARTIFACT_BUCKET"),
    )
    args = vars(parser.parse_args())
    logger.info("args: {}".format(args))
    main(**args)
