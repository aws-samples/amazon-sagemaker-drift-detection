from aws_cdk import (
    core,
    aws_sagemaker as sagemaker,
)

import logging

logger = logging.getLogger(__name__)

# Create a SageMaker Pipeline resource with a given pipeline_definition
# see: https://docs.aws.amazon.com/cdk/api/latest/python/aws_cdk.aws_sagemaker/CfnPipeline.html


class SageMakerPipelineStack(core.Stack):
    def __init__(
        self,
        scope: core.Construct,
        construct_id: str,
        pipeline_name: str,
        pipeline_description: str,
        role_arn: str,
        tags: list,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        definition_bucket = core.CfnParameter(
            self,
            "PipelineDefinitionBucket",
            type="String",
            description="The s3 bucket for pipeline definition",
            min_length=1,
        )
        definition_key = core.CfnParameter(
            self,
            "PipelineDefinitionKey",
            type="String",
            description="The s3 key for pipeline definition",
            min_length=1,
        )

        sagemaker.CfnPipeline(
            self,
            "Pipeline",
            pipeline_name=pipeline_name,
            pipeline_description=pipeline_description,
            pipeline_definition={
                "PipelineDefinitionS3Location": {
                    "Bucket": definition_bucket.value_as_string,
                    "Key": definition_key.value_as_string,
                }
            },
            role_arn=role_arn,
            tags=tags,
        )
