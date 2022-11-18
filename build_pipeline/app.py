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
        # Name of the ECR repository for Docker image assets
        # image_assets_repository_name="cdk-${Qualifier}-container-assets-${AWS::AccountId}-${AWS::Region}",
        # ARN of the role assumed by the CLI and Pipeline to deploy here
        deploy_role_arn="arn:aws:iam::570358149193:role/service-role/AmazonSageMakerServiceCatalogProductsCodePipelineRole",
        deploy_role_external_id="",
        # ARN of the role used for file asset publishing (assumed from the deploy role)
        file_asset_publishing_role_arn="arn:aws:iam::570358149193:role/service-role/AmazonSageMakerServiceCatalogProductsCodeBuildRole",
        file_asset_publishing_external_id="",
        # ARN of the role used for Docker asset publishing (assumed from the deploy role)
        image_asset_publishing_role_arn="arn:aws:iam::570358149193:role/service-role/AmazonSageMakerServiceCatalogProductsCodeBuildRole",
        image_asset_publishing_external_id="",
        # ARN of the role passed to CloudFormation to execute the deployments
        cloud_formation_execution_role="arn:aws:iam::570358149193:role/service-role/AmazonSageMakerServiceCatalogProductsCloudformationRole",
        # ARN of the role used to look up context information in an environment
        lookup_role_arn="arn:aws:iam::570358149193:role/service-role/AmazonSageMakerServiceCatalogProductsCodeBuildRole",
        lookup_role_external_id="",
        # Name of the SSM parameter which describes the bootstrap stack version number
        # bootstrap_stack_version_ssm_parameter="/cdk-bootstrap/${Qualifier}/version",
        # Add a rule to every template which verifies the required bootstrap stack version
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
    args = vars(parser.parse_args())
    logger.info("args: {}".format(args))
    main(**args)
