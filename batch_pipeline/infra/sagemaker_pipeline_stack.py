from aws_cdk import (
    core,
    aws_cloudwatch as cloudwatch,
    aws_events as events,
    aws_iam as iam,
    aws_sagemaker as sagemaker,
)

import logging
import os
from urllib.parse import urlparse
from batch_config import DriftConfig

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
        pipeline_definition_bucket: str,
        pipeline_definition_key: str,
        sagemaker_role_arn: str,
        tags: list,
        drift_config: DriftConfig,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        sagemaker.CfnPipeline(
            self,
            "Pipeline",
            pipeline_name=pipeline_name,
            pipeline_description=pipeline_description,
            pipeline_definition={
                "PipelineDefinitionS3Location": {
                    "Bucket": pipeline_definition_bucket,
                    "Key": pipeline_definition_key,
                }
            },
            role_arn=sagemaker_role_arn,
            tags=tags,
        )

        if drift_config is not None:
            # Create a CW alarm (which will be picked up by build pipeline)
            alarm_name = f"sagemaker-{pipeline_name}-threshold"
            cloudwatch.CfnAlarm(
                self,
                "DriftAlarm",
                alarm_name=alarm_name,
                alarm_description=f"Batch Drift Threshold",
                metric_name=drift_config.metric_name,
                threshold=drift_config.metric_threshold,
                namespace="aws/sagemaker/ModelBuildingPipeline/data-metrics",
                comparison_operator=drift_config.comparison_operator,
                dimensions=[
                    cloudwatch.CfnAlarm.DimensionProperty(
                        name="PipelineName", value=pipeline_name
                    ),
                ],
                evaluation_periods=drift_config.evaluation_periods,
                period=drift_config.period,
                datapoints_to_alarm=drift_config.datapoints_to_alarm,
                statistic=drift_config.statistic,
            )
