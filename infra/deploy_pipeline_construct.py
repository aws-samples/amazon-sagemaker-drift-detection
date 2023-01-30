import aws_cdk as cdk
from aws_cdk import aws_codebuild as codebuild
from aws_cdk import aws_codecommit as codecommit
from aws_cdk import aws_codepipeline as codepipeline
from aws_cdk import aws_codepipeline_actions as codepipeline_actions
from aws_cdk import aws_events as events
from aws_cdk import aws_events_targets as targets
from aws_cdk import aws_iam as iam
from aws_cdk import aws_s3 as s3
from constructs import Construct


class DeployPipelineConstruct(Construct):
    """
    Deploy pipeline construct
    """

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        sagemaker_execution_role: iam.Role,
        code_pipeline_role: iam.Role,
        code_build_role: iam.Role,
        cloudformation_role: iam.Role,
        event_role: iam.Role,
        s3_artifact: s3.Bucket,
        branch_name: str,
        project_name: str,
        project_id: str,
        seed_bucket: str,
        seed_key: str,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        code_pipeline_role = iam.Role.from_role_arn(
            self, "CodePipelineRole", code_pipeline_role.role_arn, mutable=False
        )
        code_build_role = iam.Role.from_role_arn(
            self, "CodeBuildRole", code_build_role.role_arn, mutable=False
        )

        # Create source repo from seed bucket/key
        repo = codecommit.CfnRepository(
            self,
            "CodeRepo",
            repository_name="sagemaker-{}-{}".format(project_name, construct_id),
            repository_description=f"Amazon SageMaker Drift {construct_id} pipeline",
            code=codecommit.CfnRepository.CodeProperty(
                s3=codecommit.CfnRepository.S3Property(
                    bucket=seed_bucket,
                    key=seed_key,
                    object_version=None,
                ),
                branch_name=branch_name,
            ),
            tags=[
                cdk.CfnTag(key="sagemaker:project-id", value=project_id),
                cdk.CfnTag(key="sagemaker:project-name", value=project_name),
            ],
        )

        # Reference the newly created repository
        code = codecommit.Repository.from_repository_name(
            self, "ImportedRepo", repo.attr_name
        )

        cdk_build = codebuild.PipelineProject(
            self,
            "CdkBuild",
            project_name=f"sagemaker-{project_name}-{construct_id}",
            role=code_build_role,
            environment=codebuild.BuildEnvironment(
                build_image=codebuild.LinuxBuildImage.AMAZON_LINUX_2_4,
                environment_variables={
                    "SAGEMAKER_PROJECT_NAME": codebuild.BuildEnvironmentVariable(
                        value=project_name
                    ),
                    "SAGEMAKER_PROJECT_ID": codebuild.BuildEnvironmentVariable(
                        value=project_id
                    ),
                    "SAGEMAKER_EXECUTION_ROLE_ARN": codebuild.BuildEnvironmentVariable(
                        value=sagemaker_execution_role.role_arn,
                    ),
                    "ARTIFACT_BUCKET": codebuild.BuildEnvironmentVariable(
                        value=s3_artifact.bucket_name
                    ),
                },
            ),
        )

        source_output = codepipeline.Artifact()
        cdk_build_output = codepipeline.Artifact()

        code_pipeline = codepipeline.Pipeline(
            self,
            "Pipeline",
            role=code_pipeline_role,
            artifact_bucket=s3_artifact,
            pipeline_name=f"sagemaker-{project_name}-{construct_id}",
        )

        source_stage = code_pipeline.add_stage(
            stage_name="Source",
            actions=[
                codepipeline_actions.CodeCommitSourceAction(
                    action_name="CodeCommit_Source",
                    repository=code,
                    trigger=codepipeline_actions.CodeCommitTrigger.NONE,  # Created below
                    event_role=event_role,
                    output=source_output,
                    branch=branch_name,
                    role=code_pipeline_role,
                )
            ],
        )

        build_stage = code_pipeline.add_stage(
            stage_name="Build",
            actions=[
                codepipeline_actions.CodeBuildAction(
                    action_name="Build_CDK_Template",
                    project=cdk_build,
                    input=source_output,
                    outputs=[
                        cdk_build_output,
                    ],
                    role=code_pipeline_role,
                ),
            ],
        )

        staging_stack_name = f"sagemaker-{project_name}-{construct_id}-staging"
        staging_deploy_stage = code_pipeline.add_stage(
            stage_name="DeployStaging",
            actions=[
                codepipeline_actions.CloudFormationCreateUpdateStackAction(
                    action_name="Deploy_CFN_Staging",
                    run_order=1,
                    template_path=cdk_build_output.at_path(
                        "drift-deploy-staging.template.json"
                    ),
                    stack_name=staging_stack_name,
                    admin_permissions=False,
                    deployment_role=cloudformation_role,
                    role=code_pipeline_role,
                    replace_on_failure=True,
                ),
                codepipeline_actions.ManualApprovalAction(
                    action_name="Approve_Staging",
                    run_order=2,
                    additional_information="Approving deployment for production",
                    role=code_pipeline_role,
                ),
            ],
        )
        production_deploy_stage = code_pipeline.add_stage(
            stage_name="DeployProd",
            actions=[
                codepipeline_actions.CloudFormationCreateUpdateStackAction(
                    action_name="Deploy_CFN_Prod",
                    run_order=1,
                    template_path=cdk_build_output.at_path(
                        "drift-deploy-prod.template.json"
                    ),
                    stack_name=f"sagemaker-{project_name}-{construct_id}-prod",
                    admin_permissions=False,
                    deployment_role=cloudformation_role,
                    role=code_pipeline_role,
                    replace_on_failure=True,
                ),
                codepipeline_actions.CloudFormationDeleteStackAction(
                    stack_name=staging_stack_name,
                    admin_permissions=False,
                    deployment_role=cloudformation_role,
                    role=code_pipeline_role,
                ),
            ],
        )

        events.Rule(
            self,
            "ModelRegistryRule",
            rule_name=f"sagemaker-{project_name}-modelregistry-{construct_id}",
            description="Rule to trigger a deployment when SageMaker Model registry is updated with a new model package.",
            event_pattern=events.EventPattern(
                source=["aws.sagemaker"],
                detail_type=["SageMaker Model Package State Change"],
                detail={
                    "ModelPackageGroupName": [
                        project_name,
                    ],
                    "ModelApprovalStatus": [
                        "Approved",
                        "Rejected",
                    ],
                },
            ),
            targets=[
                targets.CodePipeline(pipeline=code_pipeline, event_role=event_role)
            ],
        )

        events.Rule(
            self,
            "CodeCommitRule",
            rule_name=f"sagemaker-{project_name}-codecommit-{construct_id}",
            description="Rule to trigger a deployment when configuration is updated in CodeCommit.",
            event_pattern=events.EventPattern(
                source=["aws.codecommit"],
                detail_type=["CodeCommit Repository State Change"],
                detail={
                    "event": ["referenceCreated", "referenceUpdated"],
                    "referenceType": ["branch"],
                    "referenceName": [branch_name],
                },
                resources=[code.repository_arn],
            ),
            targets=[
                targets.CodePipeline(pipeline=code_pipeline, event_role=event_role)
            ],
        )
