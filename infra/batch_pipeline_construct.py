import aws_cdk as cdk
from aws_cdk import aws_codebuild as codebuild
from aws_cdk import aws_codecommit as codecommit
from aws_cdk import aws_codepipeline as codepipeline
from aws_cdk import aws_codepipeline_actions as codepipeline_actions
from aws_cdk import aws_events as events
from aws_cdk import aws_events_targets as targets
from aws_cdk import aws_iam as iam
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_s3 as s3
from aws_cdk.aws_codebuild import BuildEnvironmentVariable
from constructs import Construct

from infra.sagemaker_pipelines_event_target import add_sagemaker_pipeline_target


class BatchPipelineConstruct(Construct):
    """
    Batch pipeline construct
    """

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        env: cdk.Environment,
        sagemaker_execution_role: iam.Role,
        code_pipeline_role: iam.Role,
        code_build_role: iam.Role,
        cloudformation_role: iam.Role,
        event_role: iam.Role,
        lambda_role: iam.Role,
        s3_artifact: s3.Bucket,
        branch_name: str,
        project_name: str,
        project_id: str,
        seed_bucket: str,
        seed_key: str,
        batch_schedule: str,
        lowercase_lambda: lambda_.Function = None,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # Create source repo from seed bucket/key
        repo = codecommit.CfnRepository(
            self,
            "CodeRepo",
            repository_name=f"sagemaker-{project_name}-{construct_id}",
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

        # Define resource names
        pipeline_name = f"{project_name}-{construct_id}"

        # Use a custom resource to format the pipeline name
        pipeline_name_lowercase = cdk.CustomResource(
            self,
            "CrPipelineNameLowercase",
            service_token=lowercase_lambda.function_arn,
            properties=dict(InputString=pipeline_name),
        )
        pipeline_description = "SageMaker Drift Detection Batch Pipeline"
        sagemaker_pipeline_arn = cdk.Fn.join(
            delimiter="/",
            list_of_values=[
                f"arn:aws:sagemaker:{env.region}:{env.account}:pipeline",
                pipeline_name_lowercase.get_att_string("OutputString"),
            ],
        )
        code_pipeline_name = f"sagemaker-{project_name}-{construct_id}"
        schedule_rule_name = f"sagemaker-{project_name}-schedule-{construct_id}"

        # Define AWS CodeBuild spec to run node.js and python
        # https://docs.aws.amazon.com/codebuild/latest/userguide/available-runtimes.html
        pipeline_build = codebuild.PipelineProject(
            self,
            "PipelineBuild",
            project_name=f"sagemaker-{project_name}-{construct_id}",
            role=code_build_role,
            environment=codebuild.BuildEnvironment(
                build_image=codebuild.LinuxBuildImage.AMAZON_LINUX_2_4,
                environment_variables={
                    "SAGEMAKER_PROJECT_NAME": BuildEnvironmentVariable(
                        value=project_name
                    ),
                    "SAGEMAKER_PROJECT_ID": BuildEnvironmentVariable(value=project_id),
                    "AWS_REGION": BuildEnvironmentVariable(value=env.region),
                    "SAGEMAKER_PIPELINE_NAME": BuildEnvironmentVariable(
                        value=pipeline_name,
                    ),
                    "SAGEMAKER_PIPELINE_DESCRIPTION": BuildEnvironmentVariable(
                        value=pipeline_description,
                    ),
                    "SAGEMAKER_PIPELINE_ROLE_ARN": BuildEnvironmentVariable(
                        value=sagemaker_execution_role.role_arn,
                    ),
                    "ARTIFACT_BUCKET": BuildEnvironmentVariable(
                        value=s3_artifact.bucket_name
                    ),
                },
            ),
        )

        source_output = codepipeline.Artifact()
        pipeline_build_output = codepipeline.Artifact()

        code_pipeline = codepipeline.Pipeline(
            self,
            "Pipeline",
            role=code_pipeline_role,
            artifact_bucket=s3_artifact,
            pipeline_name=code_pipeline_name,
        )

        source_action = codepipeline_actions.CodeCommitSourceAction(
            action_name="CodeCommit_Source",
            repository=code,
            # Created rule below to give it a custom name
            trigger=codepipeline_actions.CodeCommitTrigger.NONE,
            event_role=event_role,
            output=source_output,
            branch=branch_name,
            role=code_pipeline_role,
        )
        _ = code_pipeline.add_stage(
            stage_name="Source",
            actions=[source_action],
        )

        _ = code_pipeline.add_stage(
            stage_name="Build",
            actions=[
                codepipeline_actions.CodeBuildAction(
                    run_order=1,
                    action_name="Build_Pipeline",
                    project=pipeline_build,
                    input=source_output,
                    outputs=[
                        pipeline_build_output,
                    ],
                    role=code_pipeline_role,
                    environment_variables={
                        "COMMIT_ID": BuildEnvironmentVariable(
                            value=source_action.variables.commit_id,
                        ),
                    },
                ),
            ],
        )
        _ = code_pipeline.add_stage(
            stage_name="BatchStaging",
            actions=[
                codepipeline_actions.CloudFormationCreateUpdateStackAction(
                    action_name="Batch_CFN_Staging",
                    run_order=1,
                    template_path=pipeline_build_output.at_path(
                        "drift-batch-staging.template.json"
                    ),
                    stack_name=f"sagemaker-{project_name}-batch-staging",
                    admin_permissions=False,
                    deployment_role=cloudformation_role,
                    replace_on_failure=True,
                    role=code_pipeline_role,
                ),
                codepipeline_actions.ManualApprovalAction(
                    action_name="Approve_Staging",
                    run_order=2,
                    additional_information="Approving deployment for production",
                    role=code_pipeline_role,
                ),
            ],
        )
        _ = code_pipeline.add_stage(
            stage_name="BatchProd",
            actions=[
                codepipeline_actions.CloudFormationCreateUpdateStackAction(
                    action_name="Batch_CFN_Prod",
                    run_order=1,
                    template_path=pipeline_build_output.at_path(
                        "drift-batch-prod.template.json"
                    ),
                    stack_name=f"sagemaker-{project_name}-batch-prod",
                    admin_permissions=False,
                    deployment_role=cloudformation_role,
                    role=code_pipeline_role,
                    replace_on_failure=True,
                ),
            ],
        )

        schedule_rule = events.Rule(
            self,
            "ScheduleRule",
            enabled=True,
            description="Rule to run batch SM pipeline on a schedule.",
            rule_name=schedule_rule_name,
            schedule=events.Schedule.expression(batch_schedule),
        )

        add_sagemaker_pipeline_target(
            schedule_rule,
            event_role=event_role,
            sagemaker_pipeline_arn=sagemaker_pipeline_arn,
        )

        # Load the lambda pipeline change code
        with open("lambda/build/lambda_pipeline_change.py", encoding="utf8") as fp:
            lambda_pipeline_change_code = fp.read()

        lambda_pipeline_change = lambda_.Function(
            self,
            "PipelineChangeFunction",
            function_name=f"sagemaker-{project_name}-batch-change",
            code=lambda_.Code.from_inline(lambda_pipeline_change_code),
            role=lambda_role,
            handler="index.lambda_handler",
            runtime=lambda_.Runtime.PYTHON_3_8,
            timeout=cdk.Duration.seconds(3),
            memory_size=128,
            environment={
                "LOG_LEVEL": "INFO",
                "CODE_PIPELINE_NAME": code_pipeline_name,
                "DRIFT_RULE_NAME": "",
                "SCHEDULE_RULE_NAME": schedule_rule_name,
            },
        )

        # Add permissions to put job status (if we want to call this directly
        # within CodePipeline)
        # see: https://docs.aws.amazon.com/codepipeline/latest/userguide/approvals-iam-permissions.html
        lambda_pipeline_change.add_to_role_policy(
            iam.PolicyStatement(
                actions=[
                    "codepipeline:EnableStageTransition",
                    "codepipeline:DisableStageTransition",
                ],
                resources=["arn:aws:codepipeline:*:*:sagemaker-*"],
            )
        )

        lambda_pipeline_change.add_to_role_policy(
            iam.PolicyStatement(
                actions=[
                    "events:EnableRule",
                    "events:DisableRule",
                ],
                resources=["arn:aws:events:*:*:rule/sagemaker-*"],
            )
        )

        # Rule to enable/disable rules when start/stop of sagemaker pipeline
        events.Rule(
            self,
            "SagemakerPipelineRule",
            rule_name=f"sagemaker-{project_name}-sagemakerpipeline-{construct_id}",
            description="Rule to enable/disable SM pipeline triggers when a "
            "SageMaker Batch Pipeline is in progress.",
            event_pattern=events.EventPattern(
                source=["aws.sagemaker"],
                detail_type=[
                    "SageMaker Model Building Pipeline Execution Status Change"
                ],
                detail={
                    "currentPipelineExecutionStatus": [
                        "Executing",
                        "Stopped",
                        "Succeeded",
                        "Failed",
                    ],  # Start/Finish
                },
                resources=[sagemaker_pipeline_arn],
            ),
            targets=[targets.LambdaFunction(handler=lambda_pipeline_change)],
        )

        # Add deploy role to target the code pipeline when model package is approved
        events.Rule(
            self,
            "ModelRegistryRule",
            rule_name="sagemaker-{}-modelregistry-{}".format(
                project_name, construct_id
            ),
            description="Rule to trigger a deployment when SageMaker Model "
            "Registry is updated with a new model package.",
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
            description="Rule to trigger a build when code is updated in CodeCommit.",
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
                targets.CodePipeline(
                    pipeline=code_pipeline,
                    event_role=event_role,
                )
            ],
        )
