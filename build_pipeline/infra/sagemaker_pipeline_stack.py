import logging

import aws_cdk as cdk
from aws_cdk import aws_sagemaker as sagemaker
from constructs import Construct

logger = logging.getLogger(__name__)

# Create a SageMaker Pipeline resource with a given pipeline_definition
# see: https://docs.aws.amazon.com/cdk/api/latest/python/aws_cdk.aws_sagemaker/CfnPipeline.html


class SageMakerPipelineStack(cdk.Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        model_package_group_name: str,
        pipeline_name: str,
        pipeline_description: str,
        pipeline_definition: dict,
        role_arn: str,
        tags: list,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)


        sagemaker.CfnModelPackageGroup(
            self,
            "ModelPackageGroup",
            model_package_group_name=model_package_group_name,
            model_package_group_description=pipeline_description,
            tags=tags,
        )

        sagemaker.CfnPipeline(
            self,
            "Pipeline",
            pipeline_name=pipeline_name,
            pipeline_description=pipeline_description,
            pipeline_definition = {"PipelineDefinitionBody": pipeline_definition},
            role_arn=role_arn,
            tags=tags,
        )
