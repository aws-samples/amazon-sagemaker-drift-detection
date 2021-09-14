class InstanceConfig:
    def __init__(self, instance_count: int = 1, instance_type: str = "ml.t2.medium"):
        self.instance_count = instance_count
        self.instance_type = instance_type


class VariantConfig(InstanceConfig):
    def __init__(
        self,
        model_package_version: str,
        initial_variant_weight: float = 1.0,
        variant_name: str = None,
        instance_count: int = 1,
        instance_type: str = "ml.t2.medium",
        model_package_arn: str = None,
    ):
        self.model_package_version = model_package_version
        self.initial_variant_weight = initial_variant_weight
        self.variant_name = variant_name
        self.model_package_arn = model_package_arn
        super().__init__(instance_count, instance_type)


class AutoScalingConfig:
    def __init__(
        self,
        min_capacity: int = 1,
        max_capacity: int = 1,
        target_value: float = 750,
        scale_in_cooldown=60,
        scale_out_cooldown=60,
    ):
        self.min_capacity = min_capacity
        self.max_capacity = max_capacity
        self.target_value = target_value
        self.scale_in_cooldown = scale_in_cooldown
        self.scale_out_cooldown = scale_out_cooldown


# TODO: Rename this to DriftConfig and move schedule expression out
class ScheduleConfig:
    def __init__(
        self,
        schedule_expression: str,
        metric_name: str,
        metric_threshold: float,
        comparison_operator: str = "GreaterThanThreshold",
        period: int = 60,
        evaluation_periods: int = 1,
        datapoints_to_alarm: int = 1,
        statistic: str = "Average",
        data_capture_sampling_percentage: float = 100,
    ):
        self.schedule_expression = schedule_expression
        self.metric_name = metric_name
        self.metric_threshold = metric_threshold
        self.comparison_operator = comparison_operator
        self.period = period
        self.datapoints_to_alarm = datapoints_to_alarm
        self.evaluation_periods = evaluation_periods
        self.statistic = statistic
        self.data_capture_sampling_percentage = data_capture_sampling_percentage


class DeploymentConfig(InstanceConfig):
    def __init__(
        self,
        stage_name: str,
        variant_config: dict = None,
        instance_count: int = 1,
        instance_type: str = "ml.t2.medium",
        auto_scaling: AutoScalingConfig = None,
        schedule_config: ScheduleConfig = None,
    ):
        self.stage_name = stage_name
        if type(variant_config) is dict:
            self.variant_config = VariantConfig(
                **{
                    "instance_count": instance_count,
                    "instance_type": instance_type,
                    **variant_config,
                }
            )
        else:
            self.variant_config = None
        if type(auto_scaling) is dict:
            self.auto_scaling = AutoScalingConfig(**auto_scaling)
        else:
            self.auto_scaling = None
        if type(schedule_config) is dict:
            self.schedule_config = ScheduleConfig(**schedule_config)
        else:
            self.schedule_config = None
        super().__init__(instance_count, instance_type)
