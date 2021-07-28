from aws_cdk import (
    core,
    aws_iam as iam,
    aws_s3_assets as s3_assets,
    aws_servicecatalog as servicecatalog,
    aws_ssm as ssm,
)

from infra.generate_sc_template import generate_template
from infra.pipeline_stack import PipelineStack


# Create a Portfolio and Product
# see: https://docs.aws.amazon.com/cdk/api/latest/python/aws_cdk.aws_servicecatalog.html
class ServiceCatalogStack(core.Stack):
    def __init__(
        self,
        scope: core.Construct,
        construct_id: str,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        execution_role_arn = core.CfnParameter(
            self,
            "ExecutionRoleArn",
            type="String",
            description="The SageMaker Studio execution role",
            min_length=1,
            allowed_pattern="^arn:aws[a-z\-]*:iam::\d{12}:role/?[a-zA-Z_0-9+=,.@\-_/]+$",
        )

        portfolio_name = core.CfnParameter(
            self,
            "PortfolioName",
            type="String",
            description="The name of the portfolio",
            default="SageMaker Organization Templates",
            min_length=1,
        )

        portfolio_owner = core.CfnParameter(
            self,
            "PortfolioOwner",
            type="String",
            description="The owner of the portfolio",
            default="administrator",
            min_length=1,
            max_length=50,
        )

        product_version = core.CfnParameter(
            self,
            "ProductVersion",
            type="String",
            description="The product version to deploy",
            default="1.0",
            min_length=1,
        )

        portfolio = servicecatalog.Portfolio(
            self,
            "Portfolio",
            display_name=portfolio_name.value_as_string,
            provider_name=portfolio_owner.value_as_string,
            description="Organization templates for Drift Detection pipeline",
        )

        drift_pipeline_template = generate_template(
            stack=PipelineStack, stack_name="drift-pipeline", strip_policies=True
        )

        product = servicecatalog.CloudFormationProduct(
            self,
            "Product",
            owner=portfolio_owner.value_as_string,
            product_name="Amazon Sagemaker Drift Detection Pipeline",
            product_versions=[
                servicecatalog.CloudFormationProductVersion(
                    cloud_formation_template=servicecatalog.CloudFormationTemplate.from_asset(
                        drift_pipeline_template
                    ),
                    product_version_name=product_version.value_as_string,
                )
            ],
            description="Amazon SageMaker Project for a build and deployment pipeline that triggers on drift or schedule",
        )
        core.Tags.of(product).add(key="sagemaker:studio-visibility", value="true")

        portfolio.add_product(product)

        # Get the service catalog role for all permssions (if None CDK will create new roles)
        # CodeBuild and CodePipeline resources need to start with "sagemaker-" to be within default policy
        products_use_role_name = self.node.try_get_context("drift:ProductsUseRoleName")
        if products_use_role_name:
            products_use_role = iam.Role.from_role_arn(
                self,
                "ProductsUseRole",
                f"arn:{self.partition}:iam::{self.account}:role/{products_use_role_name}",
            )

            # Allow assuming role on self, as the CDK CodePipeline requires this
            # see: https://github.com/aws/aws-cdk/issues/5941
            products_use_role.add_to_principal_policy(
                iam.PolicyStatement(
                    actions=["sts:AssumeRole"],
                    resources=[products_use_role.role_arn],
                )
            )

            # Add permissions to allow adding auto scaling for production deployment
            products_use_role.add_to_principal_policy(
                iam.PolicyStatement(
                    actions=[
                        "application-autoscaling:DeregisterScalableTarget",
                        "application-autoscaling:DeleteScalingPolicy",
                        "application-autoscaling:DescribeScalingPolicies",
                        "application-autoscaling:PutScalingPolicy",
                        "application-autoscaling:DescribeScalingPolicies",
                        "application-autoscaling:RegisterScalableTarget",
                        "application-autoscaling:DescribeScalableTargets",
                        "iam:CreateServiceLinkedRole",
                        "cloudwatch:DeleteAlarms",
                        "cloudwatch:DescribeAlarms",
                        "cloudwatch:PutMetricAlarm",
                        "codepipeline:PutJobSuccessResult",
                        "codepipeline:PutJobFailureResult",
                    ],
                    resources=["*"],
                )
            )

            # Add permissions to enable/disable sagemaker pipeline stages
            products_use_role.add_to_principal_policy(
                iam.PolicyStatement(
                    actions=[
                        "codepipeline:EnableStageTransition",
                        "codepipeline:DisableStageTransition",
                    ],
                    resources=[
                        f"arn:aws:codepipeline:{self.region}:{self.account}:sagemaker-*"
                    ],
                )
            )

            # Add permissions to enable/disable sagemaker rules
            products_use_role.add_to_principal_policy(
                iam.PolicyStatement(
                    actions=[
                        "events:EnableRule",
                        "events:DisableRule",
                    ],
                    resources=[
                        f"arn:aws:events:{self.region}:{self.account}:rule/sagemaker-*"
                    ],
                )
            )

            products_use_role.add_to_principal_policy(
                iam.PolicyStatement(
                    actions=["iam:CreateServiceLinkedRole"],
                    resources=[
                        f"arn:aws:iam::{self.account}:role/aws-service-role/sagemaker.application-autoscaling.amazonaws.com/AWSServiceRoleForApplicationAutoScaling_SageMakerEndpoint"
                    ],
                    conditions={
                        "StringLike": {
                            "iam:AWSServiceName": "sagemaker.application-autoscaling.amazonaws.com"
                        }
                    },
                )
            )

        # Create the launch role
        products_launch_role_name = self.node.try_get_context(
            "drift:ProductsLaunchRoleName"
        )
        products_launch_role = iam.Role.from_role_arn(
            self,
            "LaunchRole",
            role_arn=f"arn:{self.partition}:iam::{self.account}:role/{products_launch_role_name}",
        )

        portfolio.give_access_to_role(
            iam.Role.from_role_arn(
                self, "execution_role_arn", role_arn=execution_role_arn.value_as_string
            )
        )

        servicecatalog.CfnLaunchRoleConstraint(
            self,
            "LaunchRoleConstraint",
            portfolio_id=portfolio.portfolio_id,
            product_id=product.product_id,
            role_arn=products_launch_role.role_arn,
            description=f"Launch as {products_launch_role.role_arn}",
        )

        # Create the build and deployment asset as an output to pass to pipeline stack
        build_asset = s3_assets.Asset(self, "BuildAsset", path="./build_pipeline")
        deploy_asset = s3_assets.Asset(
            self, "DeployAsset", path="./deployment_pipeline"
        )
        lambda_asset = s3_assets.Asset(self, "LambdaAsset", path="./lambda/build")

        build_asset.grant_read(grantee=products_launch_role)
        deploy_asset.grant_read(grantee=products_launch_role)
        lambda_asset.grant_read(grantee=products_launch_role)

        # Output the deployment bucket and key, for input into pipeline stack
        self.export_ssm(
            "CodeCommitSeedBucket", build_asset.s3_bucket_name, products_launch_role
        )
        self.export_ssm(
            "CodeCommitBuildKey", build_asset.s3_object_key, products_launch_role
        )
        self.export_ssm(
            "CodeCommitDeployKey", deploy_asset.s3_object_key, products_launch_role
        )
        self.export_ssm("LambdaKey", lambda_asset.s3_object_key, products_launch_role)

    def export_ssm(self, key: str, value: str, launch_role: iam.Role):
        parameter_name = self.node.try_get_context(f"drift:{key}")
        param = ssm.StringParameter(
            self, key, parameter_name=parameter_name, string_value=value
        )
        param.grant_read(launch_role)
