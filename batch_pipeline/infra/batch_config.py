class BatchConfig:
    def __init__(
        self,
        stage_name: str,
        instance_count: int = 1,
        instance_type: str = "ml.t2.medium",
        model_package_version: str = None,
        model_package_arn: str = None,
        model_monitor_enabled: bool = False,
    ):
        self.stage_name = stage_name
        self.instance_count = instance_count
        self.instance_type = instance_type
        self.model_package_version = model_package_version
        self.model_package_arn = model_package_arn
        self.model_monitor_enabled = model_monitor_enabled
