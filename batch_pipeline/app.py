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


def main(
    project_name,
    project_id,
    region,
    stage_name: str,
    sagemaker_pipeline_name,
    sagemaker_pipeline_description,
    sagemaker_pipeline_role,
    lambda_header_arn,
    lambda_execution_role,
    artifact_bucket,
    output_dir,
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

    # Get the pipeline execution to get the baseline uri, for passing into
    pipeline_execution_arn = registry.get_pipeline_execution_arn(
        batch_config.model_package_arn
    )
    baseline_uri = registry.get_processing_output(pipeline_execution_arn)
    logger.info(f"Got baseline uri: {baseline_uri}")

    # Create batch pipeline
    pipeline = get_pipeline(
        region=region,
        role=sagemaker_pipeline_role,
        default_bucket=artifact_bucket,
        pipeline_name=sagemaker_pipeline_name,
        baseline_uri=baseline_uri,
        lambda_header_arn=lambda_header_arn,
        lambda_execution_role=lambda_execution_role,
        base_job_prefix=project_id,
    )

    # Create output directory
    if not os.path.exists(output_dir):
        os.mkdir(output_dir)

    # Create the pipeline definition
    logger.info("Creating/updating a SageMaker Pipeline for batch transform")
    pipeline_definition_body = pipeline.definition()
    parsed = json.loads(pipeline_definition_body)
    logger.debug(json.dumps(parsed, indent=2, sort_keys=True))

    # Upload the pipeline to S3 bucket/key and return JSON with key/value for for Cfn Stack parameters.
    # see: https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/aws-resource-sagemaker-pipeline.html
    pipeline_location = upload_pipeline(
        pipeline,
        default_bucket=artifact_bucket,
        base_job_prefix=f"{project_id}/batch",
    )

    # Store parameters as template-config.json used in the next CodePipeline step to create the SageMakerPipelineStack.
    with open(os.path.join(output_dir, "template-config.json"), "w") as f:
        template_configuration = {"Parameters": pipeline_location}
        json.dump(template_configuration, f)

    # Create App and stacks
    app = core.App()

    tags = [
        core.CfnTag(key="sagemaker:project-id", value=project_id),
        core.CfnTag(key="sagemaker:project-name", value=project_name),
    ]

    SageMakerPipelineStack(
        app,
        "drift-batch-pipeline",
        pipeline_name=sagemaker_pipeline_name,
        pipeline_description=sagemaker_pipeline_description,
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
        "--lambda-header-arn",
        default=os.environ.get("LAMBDA_HEADER_ARN"),
    )
    parser.add_argument(
        "--lambda-execution-role",
        default=os.environ.get("LAMBDA_EXECUTION_ROLE_ARN"),
    )
    parser.add_argument(
        "--artifact-bucket",
        default=os.environ.get("ARTIFACT_BUCKET"),
    )
    parser.add_argument("--output-dir", default="dist")
    args = vars(parser.parse_args())
    print("args: {}".format(args))
    main(**args)
