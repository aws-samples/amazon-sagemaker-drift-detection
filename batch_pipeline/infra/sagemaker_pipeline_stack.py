from aws_cdk import (
    core,
    aws_sagemaker as sagemaker,
    aws_events as events,
    aws_iam as iam,
)

import logging
import os
from urllib.parse import urlparse

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
        event_role_arn: str,
        tags: list,
        reporting_uri: str = None,
        sagemaker_pipeline_arn: str = None,
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

        if reporting_uri is not None and sagemaker_pipeline_arn is not None:
            # Get the monitor bucket and key prefix
            url_parsed = urlparse(reporting_uri)
            bucket_name, key_prefix = url_parsed.netloc, url_parsed.path.lstrip("/")
            key_prefix = os.path.join(key_prefix, "constraint_violations.json")

            # Get event bridge rule that triggers when the constraints file appears in that bucket
            # see: https://docs.aws.amazon.com/codepipeline/latest/userguide/create-cloudtrail-S3-source-cfn.html
            constraint_rule = events.CfnRule(
                self,
                "ConstraintViolationRule",
                name=f"sagemaker-{pipeline_name}-constraint-violation",
                description="Rule to trigger re-training on monitor constraint violation",
                event_pattern=events.EventPattern(
                    source=["aws.s3"],
                    detail_type=["AWS API Call via CloudTrail"],
                    detail={
                        "eventSource": ["s3.amazonaws.com"],
                        "eventName": ["PutObject"],
                        "requestParameters": {
                            "bucketName": [bucket_name],
                            "key": [key_prefix],
                        },
                    },
                ),
            )

            # Add the sagemaker build pipeline as a target
            event_role = iam.Role.from_role_arn(self, "EventRole", event_role_arn)
            self.add_sagemaker_pipeline_target(
                constraint_rule, event_role, sagemaker_pipeline_arn
            )

    def add_sagemaker_pipeline_target(
        self,
        rule: events.CfnRule,
        event_role: iam.Role,
        sagemaker_pipeline_arn: str,
    ) -> None:
        """Use events.CfnRule instead of events.Rule to accommodate
        [custom target](https://github.com/aws/aws-cdk/issues/14887)

        Args:
            rule (events.IRule): The event rule to add Target
            event_role (iam.Role): The event role
            sagemaker_pipeline_arn (str): The SageMaker Pipeline ARN
        """
        sagemaker_pipeline_target = {
            "Arn": sagemaker_pipeline_arn,
            "Id": "Target0",
            "RoleArn": event_role.role_arn,
            "SageMakerPipelineParameters": {
                "PipelineParameterList": [{"Name": "InputSource", "Value": rule.name}]
            },
        }
        rule.add_property_override("Targets", [sagemaker_pipeline_target])
