import logging

import aws_cdk as cdk
from aws_cdk import aws_applicationautoscaling as applicationautoscaling
from aws_cdk import aws_cloudwatch as cloudwatch
from aws_cdk import aws_events as events
from aws_cdk import aws_sagemaker as sagemaker
from constructs import Construct

from infra.endpoint_lineage import get_pipeline_arn
from infra.sagemaker_pipelines_event_target import add_sagemaker_pipeline_target
from infra.sagemaker_service_catalog_roles_construct import SageMakerSCRoles

logger = logging.getLogger(__name__)


class SageMakerStack(cdk.Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        sagemaker_execution_role: str,
        deployment_config: object,
        endpoint_name: str,
        baseline_uri: str,
        data_capture_uri: str,
        reporting_uri: str,
        tags: list,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # Select the variant config and name - needs to be same for updating Endpoint
        # or Autoscaling deregister fails
        # see: https://docs.aws.amazon.com/sagemaker/latest/dg/endpoint-scaling.html
        variant_config = deployment_config.variant_config
        variant_name = variant_config.variant_name or "LatestApproved"

        # Do not use a custom named resource for models as these get replaced
        model = sagemaker.CfnModel(
            self,
            variant_name,
            execution_role_arn=sagemaker_execution_role,
            primary_container=sagemaker.CfnModel.ContainerDefinitionProperty(
                model_package_name=variant_config.model_package_arn,
            ),
        )

        # Create the production variant
        model_variant = sagemaker.CfnEndpointConfig.ProductionVariantProperty(
            initial_instance_count=variant_config.instance_count,
            initial_variant_weight=variant_config.initial_variant_weight,
            instance_type=variant_config.instance_type,
            model_name=model.attr_model_name,
            variant_name=variant_name,
        )

        endpoint_config = sagemaker.CfnEndpointConfig(
            self,
            "EndpointConfig",
            production_variants=[model_variant],
        )

        # Enable data capture for scheduling
        if deployment_config.schedule_config is not None:
            endpoint_config.data_capture_config = sagemaker.CfnEndpointConfig.DataCaptureConfigProperty(
                enable_capture=True,
                destination_s3_uri=data_capture_uri,
                initial_sampling_percentage=deployment_config.schedule_config.data_capture_sampling_percentage,
                capture_options=[
                    sagemaker.CfnEndpointConfig.CaptureOptionProperty(
                        capture_mode="Input"
                    ),
                    sagemaker.CfnEndpointConfig.CaptureOptionProperty(
                        capture_mode="Output"
                    ),
                ],
                capture_content_type_header=sagemaker.CfnEndpointConfig.CaptureContentTypeHeaderProperty(
                    csv_content_types=["text/csv"],
                    json_content_types=["application/json"],
                ),
            )

        endpoint = sagemaker.CfnEndpoint(
            self,
            "Endpoint",
            endpoint_config_name=endpoint_config.attr_endpoint_config_name,
            endpoint_name=endpoint_name,
            tags=tags,
        )

        if deployment_config.schedule_config is not None:
            mapping = self.get_model_monitor_mapping()
            # Set schedule name to endpoint name
            schedule_name = f"{endpoint_name}-threshold"
            monitoring_schedule = sagemaker.CfnMonitoringSchedule(
                self,
                "MonitoringSchedule",
                monitoring_schedule_name=schedule_name,
                endpoint_name=endpoint_name,
                monitoring_schedule_config=sagemaker.CfnMonitoringSchedule.MonitoringScheduleConfigProperty(
                    monitoring_job_definition=sagemaker.CfnMonitoringSchedule.MonitoringJobDefinitionProperty(
                        baseline_config=sagemaker.CfnMonitoringSchedule.BaselineConfigProperty(
                            constraints_resource=sagemaker.CfnMonitoringSchedule.ConstraintsResourceProperty(
                                s3_uri=f"{baseline_uri}/constraints.json",
                            ),
                            statistics_resource=sagemaker.CfnMonitoringSchedule.StatisticsResourceProperty(
                                s3_uri=f"{baseline_uri}/statistics.json",
                            ),
                        ),
                        monitoring_app_specification=sagemaker.CfnMonitoringSchedule.MonitoringAppSpecificationProperty(
                            image_uri=mapping.find_in_map(self.region, "ImageUri")
                        ),
                        monitoring_inputs=[
                            sagemaker.CfnMonitoringSchedule.MonitoringInputProperty(
                                endpoint_input=sagemaker.CfnMonitoringSchedule.EndpointInputProperty(
                                    endpoint_name=endpoint_name,
                                    local_path="/opt/ml/processing/endpointdata",
                                )
                            )
                        ],
                        monitoring_output_config=sagemaker.CfnMonitoringSchedule.MonitoringOutputConfigProperty(
                            monitoring_outputs=[
                                sagemaker.CfnMonitoringSchedule.MonitoringOutputProperty(
                                    s3_output=sagemaker.CfnMonitoringSchedule.S3OutputProperty(
                                        local_path="/opt/ml/processing/localpath",
                                        s3_uri=reporting_uri,
                                    ),
                                )
                            ],
                        ),
                        monitoring_resources=sagemaker.CfnMonitoringSchedule.MonitoringResourcesProperty(
                            cluster_config=sagemaker.CfnMonitoringSchedule.ClusterConfigProperty(
                                instance_count=1,
                                instance_type="ml.m5.xlarge",
                                volume_size_in_gb=30,
                            )
                        ),
                        role_arn=sagemaker_execution_role,
                        stopping_condition=sagemaker.CfnMonitoringSchedule.StoppingConditionProperty(
                            max_runtime_in_seconds=1800
                        ),
                    ),
                    schedule_config=sagemaker.CfnMonitoringSchedule.ScheduleConfigProperty(
                        schedule_expression=deployment_config.schedule_config.schedule_expression,
                    ),
                ),
                tags=tags,
            )
            monitoring_schedule.add_dependency(endpoint)

            drift_alarm = cloudwatch.CfnAlarm(
                self,
                "DriftAlarm",
                alarm_name=f"{endpoint_name}-threshold",
                alarm_description="Schedule Drift Threshold",
                metric_name=deployment_config.schedule_config.metric_name,
                threshold=deployment_config.schedule_config.metric_threshold,
                namespace="aws/sagemaker/Endpoints/data-metrics",
                comparison_operator=deployment_config.schedule_config.comparison_operator,
                dimensions=[
                    cloudwatch.CfnAlarm.DimensionProperty(
                        name="Endpoint", value=endpoint.attr_endpoint_name
                    ),
                    cloudwatch.CfnAlarm.DimensionProperty(
                        name="MonitoringSchedule", value=schedule_name
                    ),
                ],
                evaluation_periods=deployment_config.schedule_config.evaluation_periods,
                period=deployment_config.schedule_config.period,
                datapoints_to_alarm=deployment_config.schedule_config.datapoints_to_alarm,
                statistic=deployment_config.schedule_config.statistic,
            )
            drift_alarm.add_dependency(monitoring_schedule)

            ### add rule to run build pipeline
            # Run the pipeline if data drift is detected
            drift_rule_name = f"sagemaker-{endpoint_name}-drift-{construct_id}"
            drift_rule = events.Rule(
                self,
                "DriftRule",
                enabled=True,
                description="Rule to start SM pipeline when drift has been detected.",
                rule_name=drift_rule_name,
                event_pattern=events.EventPattern(
                    source=["aws.cloudwatch"],
                    detail_type=["CloudWatch Alarm State Change"],
                    detail={
                        "alarmName": [
                            drift_alarm.alarm_name,
                        ],
                        "state": {"value": ["ALARM"]},
                    },
                ),
            )

            sm_roles = SageMakerSCRoles(self, "SmRoles", mutable=False)
            event_role = sm_roles.events_role
            execution_role = sm_roles.execution_role
            pipeline_arn = get_pipeline_arn(
                endpoint_name=endpoint.attr_endpoint_name,
                sagemaker_execution_role=execution_role.role_arn,
            )
            add_sagemaker_pipeline_target(
                drift_rule,
                event_role=event_role,
                sagemaker_pipeline_arn=pipeline_arn,
            )

        if deployment_config.auto_scaling is not None:
            resource_id = f"endpoint/{endpoint_name}/variant/{variant_name}"

            scalable_target = applicationautoscaling.CfnScalableTarget(
                self,
                "AutoScaling",
                min_capacity=deployment_config.auto_scaling.min_capacity,
                max_capacity=deployment_config.auto_scaling.max_capacity,
                resource_id=resource_id,
                role_arn=sagemaker_execution_role,
                scalable_dimension="sagemaker:variant:DesiredInstanceCount",
                service_namespace="sagemaker",
            )
            scalable_target.add_dependency(endpoint)

            scaling_policy = applicationautoscaling.CfnScalingPolicy(
                self,
                "AutoScalingPolicy",
                policy_name="SageMakerVariantInvocationsPerInstance",
                policy_type="TargetTrackingScaling",
                resource_id=resource_id,
                scalable_dimension="sagemaker:variant:DesiredInstanceCount",
                service_namespace="sagemaker",  # Note: This is different to scaling above
                target_tracking_scaling_policy_configuration=applicationautoscaling.CfnScalingPolicy.TargetTrackingScalingPolicyConfigurationProperty(
                    target_value=deployment_config.auto_scaling.target_value,
                    scale_in_cooldown=deployment_config.auto_scaling.scale_in_cooldown,
                    scale_out_cooldown=deployment_config.auto_scaling.scale_out_cooldown,
                    predefined_metric_specification=applicationautoscaling.CfnScalingPolicy.PredefinedMetricSpecificationProperty(
                        predefined_metric_type="SageMakerVariantInvocationsPerInstance"
                    ),
                ),
            )
            scaling_policy.add_dependency(scalable_target)

            # TODO: Add cloud watch alarm

    def get_model_monitor_mapping(self):
        region_to_account = {
            "af-south-1": "875698925577",
            "ap-east-1": "001633400207",
            "ap-northeast-1": "574779866223",
            "ap-northeast-2": "709848358524",
            "ap-south-1": "126357580389",
            "ap-southeast-1": "245545462676",
            "ap-southeast-2": "563025443158",
            "ca-central-1": "536280801234",
            "cn-north-1": "453000072557",
            "cn-northwest-1": "453252182341",
            "eu-central-1": "048819808253",
            "eu-north-1": "895015795356",
            "eu-south-1": "933208885752",
            "eu-west-1": "468650794304",
            "eu-west-2": "749857270468",
            "eu-west-3": "680080141114",
            "me-south-1": "607024016150",
            "sa-east-1": "539772159869",
            "us-east-1": "156813124566",
            "us-east-2": "777275614652",
            "us-west-1": "890145073186",
            "us-west-2": "159807026194",
        }
        mapping = cdk.CfnMapping(self, "ModelAnalyzerMap")
        container = "sagemaker-model-monitor-analyzer:latest"
        for region in region_to_account:
            mapping.set_value(
                region,
                "ImageUri",
                f"{region_to_account[region]}.dkr.ecr.{region}.amazonaws.com/{container}",
            )
        return mapping
