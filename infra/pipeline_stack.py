from aws_cdk import (
    core,
    aws_iam as iam,
    aws_s3 as s3,
)

from infra.build_pipeline_construct import BuildPipelineConstruct
from infra.batch_pipeline_construct import BatchPipelineConstruct
from infra.deploy_pipeline_construct import DeployPipelineConstruct


class PipelineStack(core.Stack):
    def __init__(
        self,
        scope: core.Construct,
        construct_id: str,
        build_pipeline: bool,
        batch_pipeline: bool,
        deply_pipeline: bool,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # Define required parmeters
        project_name = core.CfnParameter(
            self,
            "SageMakerProjectName",
            type="String",
            description="The name of the SageMaker project.",
            min_length=1,
            max_length=32,
        )
        project_id = core.CfnParameter(
            self,
            "SageMakerProjectId",
            type="String",
            min_length=1,
            max_length=16,
            description="Service generated Id of the project.",
        )

        # Get drift-pipeline parameters
        seed_bucket = self.resolve_ssm_parameter("CodeCommitSeedBucket")
        seed_build_key = self.resolve_ssm_parameter("CodeCommitBuildKey")
        seed_batch_key = self.resolve_ssm_parameter("CodeCommitBatchKey")
        seed_deploy_key = self.resolve_ssm_parameter("CodeCommitDeployKey")

        # Create the s3 artifact (name must be < 63 chars)
        artifact_bucket_name = (
            f"sagemaker-project-{project_id.value_as_string}-{self.region}"
        )
        s3_artifact = s3.Bucket(
            self,
            "S3Artifact",
            bucket_name=artifact_bucket_name,
            removal_policy=core.RemovalPolicy.DESTROY,
        )

        core.CfnOutput(self, "ArtifactBucket", value=s3_artifact.bucket_name)

        # Get the service catalog role for all permssions (if None CDK will create new roles)
        # CodeBuild and CodePipeline resources need to start with "sagemaker-" to be within default policy
        products_use_role_name = self.node.try_get_context("drift:ProductsUseRoleName")
        if products_use_role_name:
            service_catalog_role = iam.Role.from_role_arn(
                self,
                "ProductsUseRole",
                f"arn:{self.partition}:iam::{self.account}:role/{products_use_role_name}",
            )
            # Use the service catalog role for all roles
            sagemaker_execution_role = service_catalog_role
            code_pipeline_role = service_catalog_role
            code_build_role = service_catalog_role
            cloudformation_role = service_catalog_role
            lambda_role = service_catalog_role
            event_role = service_catalog_role
        else:
            # Create unique scope roles per service, so that permissions can be added in build/deploy stacks
            sagemaker_execution_role = iam.Role(
                self,
                "SageMakerExecutionRole",
                assumed_by=iam.ServicePrincipal("sagemaker.amazonaws.com"),
                path="/service-role/",
            )
            code_pipeline_role = iam.Role(
                self,
                "CodePipelineRole",
                assumed_by=iam.ServicePrincipal("codepipeline.amazonaws.com"),
                path="/service-role/",
            )
            code_build_role = iam.Role(
                self,
                "CodeBuildRole",
                assumed_by=iam.ServicePrincipal("codebuild.amazonaws.com"),
                path="/service-role/",
            )
            cloudformation_role = iam.Role(
                self,
                "CloudFormationRole",
                assumed_by=iam.ServicePrincipal("cloudformation.amazonaws.com"),
                path="/service-role/",
            )
            lambda_role = iam.Role(
                self,
                "LambdaRole",
                assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
                path="/service-role/",
            )
            event_role = iam.Role(
                self,
                "EventRole",
                assumed_by=iam.ServicePrincipal("events.amazonaws.com"),
                path="/service-role/",
            )

            # Add cloudformation to allow creating CW rules for re-training, and passing event role
            cloudformation_role.add_to_policy(
                iam.PolicyStatement(
                    actions=[
                        "events:DeleteRule",
                        "events:DescribeRule",
                        "events:PutRule",
                        "events:PutTargets",
                        "events:RemoveTargets",
                    ],
                    resources=["arn:aws:events:*:*:rule/sagemaker-*"],
                )
            )
            cloudformation_role.add_to_policy(
                iam.PolicyStatement(
                    actions=[
                        "iam:PassRole",
                    ],
                    resources=[event_role.role_arn],
                )
            )

            # Add cloudwatch logs
            logs_policy = iam.PolicyStatement(
                actions=[
                    "logs:CreateLogGroup",
                    "logs:CreateLogStream",
                    "logs:PutLogEvents",
                ],
                resources=["*"],
            )
            lambda_role.add_to_policy(logs_policy)

            # Create a policy statement for SM and ECR pull
            sagemaker_policy = iam.Policy(
                self,
                "SageMakerPolicy",
                document=iam.PolicyDocument(
                    statements=[
                        logs_policy,
                        iam.PolicyStatement(
                            actions=["sagemaker:*"],
                            not_resources=[
                                "arn:aws:sagemaker:*:*:domain/*",
                                "arn:aws:sagemaker:*:*:user-profile/*",
                                "arn:aws:sagemaker:*:*:app/*",
                                "arn:aws:sagemaker:*:*:flow-definition/*",
                            ],
                        ),
                        iam.PolicyStatement(
                            actions=[
                                "ecr:BatchCheckLayerAvailability",
                                "ecr:BatchGetImage",
                                "ecr:Describe*",
                                "ecr:GetAuthorizationToken",
                                "ecr:GetDownloadUrlForLayer",
                            ],
                            resources=["*"],
                        ),
                        iam.PolicyStatement(
                            actions=[
                                "cloudwatch:PutMetricData",
                            ],
                            resources=["*"],
                        ),
                        iam.PolicyStatement(
                            actions=[
                                "s3:AbortMultipartUpload",
                                "s3:DeleteObject",
                                "s3:GetBucket*",
                                "s3:GetObject*",
                                "s3:List*",
                                "s3:PutObject*",
                            ],
                            resources=[
                                s3_artifact.bucket_arn,
                                f"{s3_artifact.bucket_arn}/*",
                            ],
                        ),
                        iam.PolicyStatement(
                            actions=["iam:PassRole"],
                            resources=[sagemaker_execution_role.role_arn],
                        ),
                    ]
                ),
            )
            # # SageMaker needs to manage pipelines, model package groups
            sagemaker_policy.attach_to_role(sagemaker_execution_role)
            # Code build needs to query model package groups and artifacts
            sagemaker_policy.attach_to_role(code_build_role)
            # CloudFormation creates models and endpoints
            sagemaker_policy.attach_to_role(cloudformation_role)
            # Lambda needs to describe SM and put metrics
            sagemaker_policy.attach_to_role(lambda_role)

        # Define an environment object to pass to build
        env = core.Environment(account=self.account, region=self.region)

        # Define the repository name and branch
        branch_name = "main"

        if build_pipeline:
            # Require a schedule parameter (must be cron, otherwise will trigger every time rate is enabled/disabled)
            # https://docs.aws.amazon.com/AmazonCloudWatch/latest/events/ScheduledEvents.html
            retrain_schedule = core.CfnParameter(
                self,
                "RetrainSchedule",
                type="String",
                description="The expression to retrain schedule.  Defaults to first day of the month.",
                default="cron(0 12 1 * ? *)",  # 1st of the month at 12am
                min_length=1,
            )
            BuildPipelineConstruct(
                self,
                "build",
                env=env,
                sagemaker_execution_role=sagemaker_execution_role,
                code_pipeline_role=code_pipeline_role,
                code_build_role=code_build_role,
                cloudformation_role=cloudformation_role,
                event_role=event_role,
                lambda_role=lambda_role,
                s3_artifact=s3_artifact,
                branch_name=branch_name,
                project_id=project_id.value_as_string,
                project_name=project_name.value_as_string,
                seed_bucket=seed_bucket,
                seed_key=seed_build_key,
                retrain_schedule=retrain_schedule.value_as_string,
            )

        if batch_pipeline:
            batch_schedule = core.CfnParameter(
                self,
                "BatchSchedule",
                type="String",
                description="The expression to batch schedule.  Defaults to every day.",
                default="cron(0 12 * * ? *)",  # Every day at 12am
                min_length=1,
            )
            BatchPipelineConstruct(
                self,
                "batch",
                env=env,
                sagemaker_execution_role=sagemaker_execution_role,
                code_pipeline_role=code_pipeline_role,
                code_build_role=code_build_role,
                cloudformation_role=cloudformation_role,
                event_role=event_role,
                lambda_role=lambda_role,
                s3_artifact=s3_artifact,
                branch_name=branch_name,
                project_id=project_id.value_as_string,
                project_name=project_name.value_as_string,
                seed_bucket=seed_bucket,
                seed_key=seed_batch_key,
                batch_schedule=batch_schedule.value_as_string,
            )

        if deply_pipeline:
            DeployPipelineConstruct(
                self,
                "deploy",
                sagemaker_execution_role=sagemaker_execution_role,
                code_pipeline_role=code_pipeline_role,
                code_build_role=code_build_role,
                cloudformation_role=cloudformation_role,
                event_role=event_role,
                s3_artifact=s3_artifact,
                branch_name=branch_name,
                project_id=project_id.value_as_string,
                project_name=project_name.value_as_string,
                seed_bucket=seed_bucket,
                seed_key=seed_deploy_key,
            )

    def resolve_ssm_parameter(self, key: str):
        parameter_name = self.node.try_get_context(f"drift:{key}")
        return core.CfnDynamicReference(
            core.CfnDynamicReferenceService.SSM, parameter_name
        ).to_string()


class BatchPipelineStack(PipelineStack):
    """Creates a Pipeline for batch deployment"""

    def __init__(
        self,
        scope: core.Construct,
        construct_id: str,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, True, True, False, **kwargs)


class DeployPipelineStack(PipelineStack):
    """Creates a Pipelinfe for real-time deployment"""

    def __init__(
        self,
        scope: core.Construct,
        construct_id: str,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, True, False, True, **kwargs)
