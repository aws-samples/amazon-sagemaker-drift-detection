import logging
import os

import aws_cdk as cdk
import boto3
import sagemaker
from sagemaker.lineage.artifact import Artifact, ModelArtifact
from sagemaker.lineage.context import Context, EndpointContext

logger = logging.getLogger(__name__)

region = os.getenv("AWS_REGION")
boto_session = boto3.Session(region_name=region)
sagemaker_session = sagemaker.Session(
    boto_session=boto_session,
)


def get_pipeline_arn_from_endpoint(endpoint_name: str):
    logger.info(f"Endpoint: {endpoint_name}")
    endpoint_arn = f"arn:aws:sagemaker:{cdk.Aws.REGION}:{cdk.Aws.ACCOUNT_ID}:endpoint/{endpoint_name}"

    contexts = Context.list(
        source_uri=endpoint_arn,
        sagemaker_session=sagemaker_session,
    )
    context_name = list(contexts)[0].context_name
    endpoint_context = EndpointContext.load(context_name=context_name)
    pipeline_arn = endpoint_context.pipeline_execution_arn().split("/execution")[0]

    logger.info(f"It was created by an execution of SageMaker Pipeline {pipeline_arn}")

    return pipeline_arn


def get_pipeline_arn_from_model(model_package_arn: str):
    logger.info(f"Model version ARN: {model_package_arn}")
    model_artifact_summary = list(Artifact.list(source_uri=model_package_arn))[0]
    model_artifact = ModelArtifact.load(
        artifact_arn=model_artifact_summary.artifact_arn
    )

    pipeline_arn = model_artifact.pipeline_execution_arn().split("/execution")[0]

    logger.info(f"It was created by an execution of SageMaker Pipeline {pipeline_arn}")

    return pipeline_arn
