class DriftConfig:
    def __init__(
        self,
        metric_name: str,
        metric_threshold: float,
        comparison_operator: str = "GreaterThanThreshold",
        period: int = 60,
        evaluation_periods: int = 1,
        datapoints_to_alarm: int = 1,
        statistic: str = "Average",
    ):
        self.metric_name = metric_name
        self.metric_threshold = metric_threshold
        self.comparison_operator = comparison_operator
        self.period = period
        self.datapoints_to_alarm = datapoints_to_alarm
        self.evaluation_periods = evaluation_periods
        self.statistic = statistic


class BatchConfig:
    def __init__(
        self,
        stage_name: str,
        instance_count: int = 1,
        instance_type: str = "ml.t2.medium",
        model_package_version: str = None,
        model_package_arn: str = None,
        drift_config: DriftConfig = None,
    ):
        self.stage_name = stage_name
        self.instance_count = instance_count
        self.instance_type = instance_type
        self.model_package_version = model_package_version
        self.model_package_arn = model_package_arn
        if type(drift_config) is dict:
            self.drift_config = DriftConfig(**drift_config)
        else:
            self.drift_config = None
