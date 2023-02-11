import aws_cdk as cdk
import aws_cdk.aws_s3 as s3
import aws_cdk.aws_servicecatalog as sc
import aws_cdk.aws_lambda as lambda_
from constructs import Construct

from infra.batch_pipeline_construct import BatchPipelineConstruct
from infra.build_pipeline_construct import BuildPipelineConstruct
from infra.deploy_pipeline_construct import DeployPipelineConstruct
from infra.sagemaker_service_catalog_roles_construct import SageMakerSCRoles


class PipelineProductStack(sc.ProductStack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        build_pipeline: bool,
        batch_pipeline: bool,
        deploy_pipeline: bool,
        seed_bucket: s3.Bucket,
        sm_roles: SageMakerSCRoles,
        lowercase_lambda: lambda_.Function = None,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # Define required parameters
        project_name = cdk.CfnParameter(
            self,
            "SageMakerProjectName",
            type="String",
            description="The name of the SageMaker project.",
            allowed_pattern="^[a-zA-Z0-9](-*[a-zA-Z0-9]){0,31}",
        )
        project_id = cdk.CfnParameter(
            self,
            "SageMakerProjectId",
            type="String",
            min_length=1,
            max_length=20,
            description="Service generated Id of the project.",
            allowed_pattern="^[a-zA-Z0-9](-*[a-zA-Z0-9])*",
        )

        # Create the s3 artifact (name must be < 63 chars)
        artifact_bucket_name = (
            f"sagemaker-project-{project_id.value_as_string}-{self.region}"
        )
        s3_artifact = s3.Bucket(
            self,
            "S3Artifact",
            bucket_name=artifact_bucket_name,
            removal_policy=cdk.RemovalPolicy.DESTROY,
        )

        cdk.CfnOutput(self, "ArtifactBucket", value=s3_artifact.bucket_name)

        execution_role = sm_roles.execution_role
        code_pipeline_role = sm_roles.code_pipeline_role
        code_build_role = sm_roles.code_build_role
        cloudformation_role = sm_roles.cloudformation_role
        lambda_role = sm_roles.lambda_role
        event_role = sm_roles.events_role

        # Define an environment object to pass to build
        env = cdk.Environment(account=self.account, region=self.region)

        # Define the repository name and branch
        branch_name = "main"

        if build_pipeline:
            # Require a schedule parameter (must be cron, otherwise will trigger every
            # time rate is enabled/disabled)
            # https://docs.aws.amazon.com/AmazonCloudWatch/latest/events/ScheduledEvents.html
            retrain_schedule = cdk.CfnParameter(
                self,
                "RetrainSchedule",
                type="String",
                description="The expression to retrain schedule.  Defaults to first "
                "day of the month.",
                default="cron(0 12 1 * ? *)",  # 1st of the month at 12am
                min_length=1,
            )
            BuildPipelineConstruct(
                self,
                "build",
                env=env,
                sagemaker_execution_role=execution_role,
                code_pipeline_role=code_pipeline_role,
                code_build_role=code_build_role,
                cloudformation_role=cloudformation_role,
                event_role=event_role,
                lambda_role=lambda_role,
                s3_artifact=s3_artifact,
                branch_name=branch_name,
                project_id=project_id.value_as_string,
                project_name=project_name.value_as_string,
                seed_bucket=seed_bucket.bucket_name,
                seed_key="build_pipeline.zip",
                retrain_schedule=retrain_schedule.value_as_string,
                lowercase_lambda=lowercase_lambda,
            )

        if batch_pipeline:
            batch_schedule = cdk.CfnParameter(
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
                sagemaker_execution_role=execution_role,
                code_pipeline_role=code_pipeline_role,
                code_build_role=code_build_role,
                cloudformation_role=cloudformation_role,
                event_role=event_role,
                lambda_role=lambda_role,
                s3_artifact=s3_artifact,
                branch_name=branch_name,
                project_id=project_id.value_as_string,
                project_name=project_name.value_as_string,
                seed_bucket=seed_bucket.bucket_name,
                seed_key="batch_pipeline.zip",
                batch_schedule=batch_schedule.value_as_string,
            )

        if deploy_pipeline:
            DeployPipelineConstruct(
                self,
                "deploy",
                sagemaker_execution_role=execution_role,
                code_pipeline_role=code_pipeline_role,
                code_build_role=code_build_role,
                cloudformation_role=cloudformation_role,
                event_role=event_role,
                s3_artifact=s3_artifact,
                branch_name=branch_name,
                project_id=project_id.value_as_string,
                project_name=project_name.value_as_string,
                seed_bucket=seed_bucket.bucket_name,
                seed_key="deployment_pipeline.zip",
            )


class BatchPipelineStack(PipelineProductStack):
    """Creates a Pipeline for real-time deployment"""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, True, True, False, **kwargs)


class DeployPipelineStack(PipelineProductStack):
    """Creates a Pipeline for real-time deployment"""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, True, False, True, **kwargs)
