from pathlib import Path
from zipfile import ZipFile

import aws_cdk as cdk

from aws_cdk import aws_iam as iam
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_s3 as s3
from aws_cdk import aws_s3_deployment as s3d
from aws_cdk import aws_servicecatalog as servicecatalog
from constructs import Construct

from infra.pipeline_product_stack import BatchPipelineStack, DeployPipelineStack
from infra.sagemaker_service_catalog_roles_construct import SageMakerSCRoles


# Create a Portfolio and Product
# see: https://docs.aws.amazon.com/cdk/api/latest/python/aws_cdk.aws_servicecatalog.html
class ServiceCatalogStack(cdk.Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        sm_user_execution_role_arn = cdk.CfnParameter(
            self,
            "SageMakerUserExecutionRoleArn",
            type="String",
            description="The SageMaker Studio User execution role",
            min_length=1,
            allowed_pattern="^arn:aws[a-z\\-]*:iam::\\d{12}:role/?[a-zA-Z_0-9+=,.@\\-_/]+$",
        )

        portfolio_name = cdk.CfnParameter(
            self,
            "PortfolioName",
            type="String",
            description="The name of the portfolio",
            default="SageMaker Organization Templates",
            min_length=1,
        )

        portfolio_owner = cdk.CfnParameter(
            self,
            "PortfolioOwner",
            type="String",
            description="The owner of the portfolio",
            default="administrator",
            min_length=1,
            max_length=50,
        )

        product_version = cdk.CfnParameter(
            self,
            "ProductVersion",
            type="String",
            description="The product version to deploy",
            default="1.0",
            min_length=1,
        )

        if seed_bucket_name := self.node.try_get_context("SeedBucketName"):
            seed_bucket = s3.Bucket(
                self,
                "SeedBucket",
                bucket_name=seed_bucket_name,
            )
        else:
            seed_bucket = s3.Bucket(
                self,
                "SeedBucket",
                bucket_name=f"sagemaker-drift-detection-template-seed-{self.account}",
                removal_policy=cdk.RemovalPolicy.DESTROY,
                auto_delete_objects=True,
            )

        path_list = ["build_pipeline", "batch_pipeline", "deployment_pipeline"]

        # Create the compressed code seed for the code commit repositories
        temp_path = Path("cdk.out/compressed_repos")
        temp_path.mkdir(exist_ok=True, parents=True)
        [create_zip((temp_path / f"{k}.zip").as_posix(), Path(k)) for k in path_list]

        # deploys the code seeds in the designated seed bucket
        build_asset = s3d.BucketDeployment(
            self,
            "BuildAsset",
            destination_bucket=seed_bucket,
            sources=[s3d.Source.asset(temp_path.as_posix())],
        )

        # Lambda powering the custom resource to convert names to lower case at
        # deploy time
        with open("lambda/lowercase_name.py", encoding="utf8") as fp:
            lambda_lowercase_code = fp.read()

        lowercase_lambda = lambda_.Function(
            self,
            "LowerCaseLambda",
            function_name="sagemaker-lowercase-names",
            description="Returns the lowercase version of a string",
            code=lambda_.Code.from_inline(lambda_lowercase_code),
            handler="index.lambda_handler",
            runtime=lambda_.Runtime.PYTHON_3_8,
            timeout=cdk.Duration.seconds(3),
            memory_size=128,
        )

        # Check for custom launch roles, otherwise fall back to default
        # role created with SageMaker Studio
        if (
            products_launch_role_name := self.node.try_get_context(
                "drift:ProductsLaunchRoleName"
            )
        ) is None:
            products_launch_role_name = (
                "service-role/AmazonSageMakerServiceCatalogProductsLaunchRole"
            )

        products_launch_role = iam.Role.from_role_arn(
            self,
            "LaunchRole",
            role_arn=self.format_arn(
                region="",
                service="iam",
                resource="role",
                resource_name=products_launch_role_name,
            ),
        )

        sm_user_execution_role = iam.Role.from_role_arn(
            self,
            "ExecutionRole",
            role_arn=sm_user_execution_role_arn.value_as_string,
        )

        sm_roles = SageMakerSCRoles(self, "SageMakerSCRoles", mutable=True)
        # Add endpoint autoscaling policies to CloudFormation role
        cloudformation_role = sm_roles.cloudformation_role
        cloudformation_role.add_to_principal_policy(
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
                ],
                resources=["*"],
            )
        )
        cloudformation_role.add_to_principal_policy(
            iam.PolicyStatement(
                actions=[
                    "events:DescribeRule",
                    "events:PutRule",
                    "events:DeleteRule",
                    "events:PutTargets",
                    "events:RemoveTargets",
                    "events:ListTargetsByRule",
                    "events:ListRuleNamesByTarget",
                ],
                resources=[
                    "*",
                    self.format_arn(
                        resource="rule", service="events", resource_name="sagemaker*"
                    ),
                ],
            )
        )

        cloudformation_role.add_to_principal_policy(
            iam.PolicyStatement(
                actions=[
                    "iam:PassRole",
                ],
                resources=[
                    "*",
                    self.format_arn(
                        resource="role",
                        service="iam",
                        resource_name="service-role/AmazonSageMakerServiceCatalogProductsEventsRole",
                        region="",
                        account="*",
                    ),
                ],
            )
        )

        # Add permissions to start SM pipelines to the Event Role
        event_role = sm_roles.events_role
        event_role.add_to_principal_policy(
            iam.PolicyStatement(
                actions=[
                    "sagemaker:DescribePipelineExecution",
                    "sagemaker:StartPipelineExecution",
                ],
                resources=[
                    self.format_arn(
                        resource="pipeline",
                        service="sagemaker",
                        resource_name="",
                        arn_format=cdk.ArnFormat.NO_RESOURCE_NAME,
                    ),
                    self.format_arn(
                        resource="pipeline", service="sagemaker", resource_name="*"
                    ),
                ],
            )
        )

        product_roles = SageMakerSCRoles(self, "ScProductRoles", mutable=False)
        if (
            execution_role_arn := self.node.try_get_context("drift:execution_role")
        ) is not None:
            product_roles.execution_role = iam.Role.from_role_arn(
                self,
                "execution_role",
                role_arn=execution_role_arn,
                mutable=False,
            )

        if (
            code_pipeline_role_arn := self.node.try_get_context(
                "drift:code_pipeline_role"
            )
        ) is not None:
            product_roles.code_pipeline_role = iam.Role.from_role_arn(
                self,
                "code_pipeline_role",
                role_arn=code_pipeline_role_arn,
                mutable=False,
            )

        if (
            code_build_role_arn := self.node.try_get_context("drift:code_build_role")
        ) is not None:
            product_roles.code_build_role = iam.Role.from_role_arn(
                self,
                "code_build_role",
                role_arn=code_build_role_arn,
                mutable=False,
            )

        if (
            cloudformation_role_arn := self.node.try_get_context(
                "drift:cloudformation_role"
            )
        ) is not None:
            product_roles.code_build_role = iam.Role.from_role_arn(
                self,
                "code_build_role",
                role_arn=cloudformation_role_arn,
                mutable=False,
            )

        if (
            lambda_role_arn := self.node.try_get_context("drift:lambda_role")
        ) is not None:
            product_roles.lambda_role = iam.Role.from_role_arn(
                self,
                "lambda_role",
                role_arn=lambda_role_arn,
                mutable=False,
            )

        if (
            event_role_arn := self.node.try_get_context("drift:event_role")
        ) is not None:
            product_roles.event_role = iam.Role.from_role_arn(
                self,
                "event_role",
                role_arn=event_role_arn,
                mutable=False,
            )

        # Create the Service Catalog portfolio and the products
        portfolio = servicecatalog.Portfolio(
            self,
            "Portfolio",
            display_name=portfolio_name.value_as_string,
            provider_name=portfolio_owner.value_as_string,
            description="Organization templates for drift detection pipelines",
        )
        portfolio.give_access_to_role(sm_user_execution_role)

        batch_product = servicecatalog.CloudFormationProduct(
            self,
            "BatchProduct",
            owner=portfolio_owner.value_as_string,
            product_name="Amazon SageMaker drift detection template for batch scoring",
            product_versions=[
                servicecatalog.CloudFormationProductVersion(
                    cloud_formation_template=servicecatalog.CloudFormationTemplate.from_product_stack(
                        BatchPipelineStack(
                            self,
                            "BuildDeploy",
                            seed_bucket=build_asset.deployed_bucket,
                            lowercase_lambda=lowercase_lambda,
                            sm_roles=product_roles,
                        )
                    ),
                    product_version_name=product_version.value_as_string,
                )
            ],
            description="This template includes a model building pipeline "
            "that includes a workflow to pre-process, train, evaluate and register"
            " a model as well as create a baseline for model monitoring. "
            "The batch pipeline creates a staging and production workflow to"
            " perform scoring, and model monitor to output metrics "
            "to automate re-training on drift detection.",
        )
        portfolio.add_product(batch_product)

        # Attach the product to the SageMaker Studio as Project template
        cdk.Tags.of(batch_product).add(key="sagemaker:studio-visibility", value="true")
        portfolio.set_launch_role(
            product=batch_product, launch_role=products_launch_role
        )

        deploy_product = servicecatalog.CloudFormationProduct(
            self,
            "DeployProduct",
            owner=portfolio_owner.value_as_string,
            product_name=(
                "Amazon SageMaker drift detection template for real-time deployment"
            ),
            product_versions=[
                servicecatalog.CloudFormationProductVersion(
                    cloud_formation_template=servicecatalog.CloudFormationTemplate.from_product_stack(
                        DeployPipelineStack(
                            self,
                            "DeployPipeline",
                            seed_bucket=build_asset.deployed_bucket,
                            lowercase_lambda=lowercase_lambda,
                            sm_roles=product_roles,
                        )
                    ),
                    product_version_name=product_version.value_as_string,
                )
            ],
            description="This template includes a model building pipeline that "
            "includes a workflow to pre-process, train, evaluate and register a "
            "model as well as create a baseline for model monitoring. "
            "The deploy pipeline creates a staging and production endpoint, "
            "and schedules model monitor to output metrics "
            "to automate re-training on drift detection.",
        )
        cdk.Tags.of(deploy_product).add(key="sagemaker:studio-visibility", value="true")
        portfolio.add_product(deploy_product)
        portfolio.set_launch_role(
            product=deploy_product, launch_role=products_launch_role
        )


def create_zip(zipfile_name: str, local_path: Path):
    """
    Create a zip archive with the content of `local_path`

    :param zipfile_name: The name of the zip archive
    :param local_path: The path to the directory to zip
    """
    with ZipFile(zipfile_name, mode="w") as archive:
        [
            archive.write(k, arcname=f"{k.relative_to(local_path)}")
            for k in local_path.glob("**/*.*")
            if not f"{k.relative_to(local_path)}".startswith(("cdk.out", "."))
            if "__pycache__" not in f"{k.relative_to(local_path)}"
            if not f"{k.relative_to(local_path)}".endswith(".zip")
        ]
        if (gitignore_path := local_path / ".gitignore").exists():
            archive.write(gitignore_path, arcname=".gitignore")

    zip_size = Path(zipfile_name).stat().st_size / 10**6
    return zip_size
