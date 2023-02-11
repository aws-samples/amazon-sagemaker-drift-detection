import aws_cdk as cdk
import aws_cdk.aws_iam as iam
from constructs import Construct


class SageMakerSCRoles(Construct):
    def __init__(
        self, scope: Construct, construct_id: str, mutable: bool = True, **kwargs
    ):
        super().__init__(scope, construct_id, **kwargs)

        self.execution_role = iam.Role.from_role_arn(
            self,
            "SMModelDeploymentRole",
            role_arn=format_role(
                role_name="AmazonSageMakerServiceCatalogProductsExecutionRole"
            ),
            mutable=mutable,
        )

        self.events_role = iam.Role.from_role_arn(
            self,
            "SMEventsRole",
            role_arn=format_role(
                role_name="AmazonSageMakerServiceCatalogProductsEventsRole"
            ),
            mutable=mutable,
        )

        self.code_build_role = iam.Role.from_role_arn(
            self,
            "SMCodeBuildRole",
            role_arn=format_role(
                role_name="AmazonSageMakerServiceCatalogProductsCodeBuildRole"
            ),
            mutable=mutable,
        )

        self.code_pipeline_role = iam.Role.from_role_arn(
            self,
            "SMCodePipelineRole",
            role_arn=format_role(
                role_name="AmazonSageMakerServiceCatalogProductsCodePipelineRole"
            ),
            mutable=mutable,
        )

        self.lambda_role = iam.Role.from_role_arn(
            self,
            "SMLambdaRole",
            role_arn=format_role(
                role_name="AmazonSageMakerServiceCatalogProductsLambdaRole"
            ),
            mutable=mutable,
        )

        self.api_gw_role = iam.Role.from_role_arn(
            self,
            "SMApiGatewayRole",
            role_arn=format_role(
                role_name="AmazonSageMakerServiceCatalogProductsApiGatewayRole"
            ),
            mutable=mutable,
        )

        self.firehose_role = iam.Role.from_role_arn(
            self,
            "SMFirehoseRole",
            role_arn=format_role(
                role_name="AmazonSageMakerServiceCatalogProductsFirehoseRole"
            ),
            mutable=mutable,
        )

        self.glue_role = iam.Role.from_role_arn(
            self,
            "SMGlueRole",
            role_arn=format_role(
                role_name="AmazonSageMakerServiceCatalogProductsGlueRole"
            ),
            mutable=mutable,
        )

        self.cloudformation_role = iam.Role.from_role_arn(
            self,
            "SMCloudformationRole",
            role_arn=format_role(
                role_name="AmazonSageMakerServiceCatalogProductsCloudformationRole"
            ),
            mutable=mutable,
        )


def format_role(role_name: str):
    return f"arn:aws:iam::{cdk.Aws.ACCOUNT_ID}:role/service-role/{role_name}"
