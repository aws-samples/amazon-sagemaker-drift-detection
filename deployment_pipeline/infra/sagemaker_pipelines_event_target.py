import aws_cdk as cdk
from aws_cdk import aws_events as events
from aws_cdk import aws_iam as iam


def add_sagemaker_pipeline_target(
    rule: events.Rule,
    event_role: iam.Role,
    sagemaker_pipeline_arn: str,
    pipeline_parameters: dict = None,
    target_id: str = None,
) -> None:
    """
    [custom target](https://github.com/aws/aws-cdk/issues/14887)

    Args:
        rule (events.Rule): The event rule to add Target
        event_role (iam.Role): The event role
        sagemaker_pipeline_arn (str): The SageMaker Pipeline ARN
        pipeline_parameters (dict): dictionary with the pipeline parameters
    """
    if target_id is None:
        target_id = cdk.Fn.split(
            delimiter="/",
            source=sagemaker_pipeline_arn,
            assumed_length=2,
        )[1]

    sagemaker_pipeline_target = {
        "Arn": sagemaker_pipeline_arn,
        "Id": target_id,
        "RoleArn": event_role.role_arn,
    }
    if pipeline_parameters is not None:
        parameters_list = [
            {"Name": k, "Value": o} for k, o in pipeline_parameters.items()
        ]

        sagemaker_pipeline_target = {
            **sagemaker_pipeline_target,
            "SageMakerPipelineParameters": {"PipelineParameterList": parameters_list},
        }

    child = rule.node.default_child
    child.add_property_override("Targets", [sagemaker_pipeline_target])
