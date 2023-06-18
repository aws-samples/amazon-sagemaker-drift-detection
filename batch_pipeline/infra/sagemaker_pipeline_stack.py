import logging

import aws_cdk as cdk
from aws_cdk import aws_cloudwatch as cloudwatch
from aws_cdk import aws_sagemaker as sagemaker
from constructs import Construct
from pipelines.pipeline import get_pipeline


from infra.batch_config import DriftConfig, BatchConfig

logger = logging.getLogger(__name__)

# Create a SageMaker Pipeline resource with a given pipeline_definition
# see: https://docs.aws.amazon.com/cdk/api/latest/python/aws_cdk.aws_sagemaker/CfnPipeline.html


class SageMakerPipelineStack(cdk.Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        pipeline_name: str,
        pipeline_description: str,
        sagemaker_role_arn: str,
        default_bucket: str,
        tags: list,
        batch_config: BatchConfig,
        drift_config: DriftConfig,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # Do not use a custom named resource for models as these get replaced
        model = sagemaker.CfnModel(
            self,
            "Model",
            execution_role_arn=sagemaker_role_arn,
            primary_container=sagemaker.CfnModel.ContainerDefinitionProperty(
                model_package_name=batch_config.model_package_arn,
            ),
            model_name=f"{batch_config.model_package_arn.split('/', 1)[1].replace('/', '-')}-{batch_config.stage_name}",
        )

        pipeline_definition = get_pipeline(
            role=sagemaker_role_arn,
            pipeline_name=pipeline_name,
            default_bucket=default_bucket,
            model_package_arn=batch_config.model_package_arn,
            default_model_name=model.model_name,
        ).definition()

        print(model.model_name)

        sagemaker.CfnPipeline(
            self,
            "Pipeline",
            pipeline_name=pipeline_name,
            pipeline_description=pipeline_description,
            pipeline_definition={"PipelineDefinitionBody": pipeline_definition},
            role_arn=sagemaker_role_arn,
            tags=tags,
        )

        if drift_config is not None:
            # Create a CW alarm (which will be picked up by build pipeline)
            alarm_name = f"sagemaker-{pipeline_name}-threshold"

            drift_metric = cloudwatch.Metric(
                metric_name=drift_config.metric_name,
                namespace="aws/sagemaker/ModelBuildingPipeline/data-metrics",
                dimensions_map={"PipelineName": pipeline_name},
                statistic=cloudwatch.Stats.AVERAGE,
                period=cdk.Duration.minutes(drift_config.period),
            )

            cloudwatch.Alarm(
                self,
                "DriftAlarm",
                alarm_name=alarm_name,
                alarm_description="Batch Drift Threshold",
                metric=drift_metric,
                comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
                threshold=drift_config.metric_threshold,
                evaluation_periods=drift_config.evaluation_periods,
                datapoints_to_alarm=drift_config.datapoints_to_alarm,
            )
