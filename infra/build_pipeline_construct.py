from aws_cdk import (
    core,
    aws_codebuild as codebuild,
    aws_codecommit as codecommit,
    aws_codepipeline as codepipeline,
    aws_codepipeline_actions as codepipeline_actions,
    aws_events as events,
    aws_events_targets as targets,
    aws_iam as iam,
    aws_lambda as lambda_,
    aws_s3 as s3,
)


class BuildPipelineConstruct(core.Construct):
    """
    Build pipeline construct
    """

    def __init__(
        self,
        scope: core.Construct,
        construct_id: str,
        env: core.Environment,
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
        retrain_schedule: str,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

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
                core.CfnTag(key="sagemaker:project-id", value=project_id),
                core.CfnTag(key="sagemaker:project-name", value=project_name),
            ],
        )

        # Reference the newly created repository
        code = codecommit.Repository.from_repository_name(
            self, "ImportedRepo", repo.attr_name
        )

        # Define resource names
        pipeline_name = f"{project_name}-pipeline"
        pipeline_description = "SageMaker Drift Detection Pipeline"
        sagemaker_pipeline_arn = (
            f"arn:aws:sagemaker:{env.region}:{env.account}:pipeline/{pipeline_name}"
        )
        code_pipeline_name = f"sagemaker-{project_name}-{construct_id}"
        drift_rule_name = f"sagemaker-{project_name}-drift-{construct_id}"
        schedule_rule_name = f"sagemaker-{project_name}-schedule-{construct_id}"

        # It seems the code build job requires  permissions to CreateBucket, despite the fact this exists
        code_build_role.add_to_policy(
            iam.PolicyStatement(
                actions=["s3:CreateBucket"],
                resources=[s3_artifact.bucket_arn],
            )
        )

        # Define AWS CodeBuild spec to run node.js and python
        # https://docs.aws.amazon.com/codebuild/latest/userguide/available-runtimes.html
        pipeline_build = codebuild.PipelineProject(
            self,
            "PipelineBuild",
            project_name="sagemaker-{}-{}".format(project_name, construct_id),
            role=code_build_role,
            build_spec=codebuild.BuildSpec.from_object(
                dict(
                    version="0.2",
                    phases=dict(
                        install={
                            "runtime-versions": {
                                "nodejs": "12",
                                "python": "3.8",
                            },
                            "commands": [
                                "npm install aws-cdk",
                                "npm update",
                                "python -m pip install -r requirements.txt",
                            ],
                        },
                        build=dict(
                            commands=[
                                "npx cdk synth -o dist --path-metadata false",
                            ]
                        ),
                    ),
                    artifacts={
                        "base-directory": "dist",
                        "files": [
                            "pipeline.json",
                            "*.template.json",
                        ],
                    },
                )
            ),
            environment=codebuild.BuildEnvironment(
                build_image=codebuild.LinuxBuildImage.AMAZON_LINUX_2_3,
                environment_variables={
                    "SAGEMAKER_PROJECT_NAME": codebuild.BuildEnvironmentVariable(
                        value=project_name
                    ),
                    "SAGEMAKER_PROJECT_ID": codebuild.BuildEnvironmentVariable(
                        value=project_id
                    ),
                    "AWS_REGION": codebuild.BuildEnvironmentVariable(value=env.region),
                    "SAGEMAKER_PIPELINE_NAME": codebuild.BuildEnvironmentVariable(
                        value=pipeline_name,
                    ),
                    "SAGEMAKER_PIPELINE_DESCRIPTION": codebuild.BuildEnvironmentVariable(
                        value=pipeline_description,
                    ),
                    "SAGEMAKER_PIPELINE_ROLE_ARN": codebuild.BuildEnvironmentVariable(
                        value=sagemaker_execution_role.role_arn,
                    ),
                    "ARTIFACT_BUCKET": codebuild.BuildEnvironmentVariable(
                        value=s3_artifact.bucket_name
                    ),
                },
            ),
        )

        # Load the start pipeline code
        with open("lambda/build/lambda_start_pipeline.py", encoding="utf8") as fp:
            lambda_start_pipeline_code = fp.read()

        lambda_start_pipeline = lambda_.Function(
            self,
            "StartPipelineFunction",
            function_name=f"sagemaker-{project_name}-start-pipeline",
            code=lambda_.Code.from_inline(lambda_start_pipeline_code),
            role=lambda_role,
            handler="index.lambda_handler",
            runtime=lambda_.Runtime.PYTHON_3_8,
            timeout=core.Duration.seconds(3),
            memory_size=128,
            environment={
                "LOG_LEVEL": "INFO",
                "PIPELINE_NAME": pipeline_name,
            },
        )

        # Add permissions to start pipeline for lambda and event role
        start_pipeline_policy = iam.PolicyStatement(
            actions=[
                "sagemaker:DescribePipelineExecution",
                "sagemaker:StartPipelineExecution",
            ],
            resources=[sagemaker_pipeline_arn, f"{sagemaker_pipeline_arn}/*"],
        )
        lambda_start_pipeline.add_to_role_policy(start_pipeline_policy)

        source_output = codepipeline.Artifact()
        pipeline_build_output = codepipeline.Artifact()

        code_pipeline = codepipeline.Pipeline(
            self,
            "Pipeline",
            role=code_pipeline_role,
            artifact_bucket=s3_artifact,
            pipeline_name=code_pipeline_name,
            stages=[
                codepipeline.StageProps(
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
                ),
                codepipeline.StageProps(
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
                        ),
                    ],
                ),
                codepipeline.StageProps(
                    stage_name="Pipeline",
                    actions=[
                        codepipeline_actions.CloudFormationCreateUpdateStackAction(
                            action_name="Create_CFN_Pipeline",
                            run_order=1,
                            template_path=pipeline_build_output.at_path(
                                "drift-sagemaker-pipeline.template.json"
                            ),
                            stack_name="sagemaker-{}-pipeline".format(project_name),
                            admin_permissions=False,
                            deployment_role=cloudformation_role,
                            replace_on_failure=True,
                            role=code_pipeline_role,
                        ),
                        codepipeline_actions.LambdaInvokeAction(
                            lambda_=lambda_start_pipeline,
                            action_name="Start_Pipeline",
                            user_parameters={"PipelineName": pipeline_name},
                            run_order=2,
                            role=code_pipeline_role,
                        ),
                    ],
                ),
            ],
        )

        # Allow event role to start pipeline and code pipeline
        event_role.add_to_policy(start_pipeline_policy)
        event_role.add_to_policy(
            iam.PolicyStatement(
                actions=["codepipeline:StartPipelineExecution"],
                resources=[code_pipeline.pipeline_arn],
            )
        )

        # TODO: Add Fix to ensure `detail_type` emits as `detail-type` in CFN
        drift_rule = events.CfnRule(
            self,
            "DriftRule",
            description="Rule to start SM pipeline when drift has been detected.",
            name=drift_rule_name,
            state="ENABLED",
            event_pattern={
                "source": ["aws.cloudwatch"],
                "detail-type": ["CloudWatch Alarm State Change"],
                "detail": {
                    "alarmName": [
                        f"sagemaker-{project_name}-staging-threshold",
                        f"sagemaker-{project_name}-prod-threshold",
                    ],
                    "state": {"value": ["ALARM"]},
                },
            },
        )

        self.add_sagemaker_pipeline_target(
            drift_rule, event_role, sagemaker_pipeline_arn
        )

        schedule_rule = events.CfnRule(
            self,
            "ScheduleRule",
            description="Rule to retrain SM pipeline on a schedule.",
            name=schedule_rule_name,
            state="ENABLED",
            schedule_expression=retrain_schedule,
        )
        self.add_sagemaker_pipeline_target(
            schedule_rule, event_role, sagemaker_pipeline_arn
        )

        # Load the lambda pipeline change code
        with open("lambda/build/lambda_pipeline_change.py", encoding="utf8") as fp:
            lambda_pipeline_change_code = fp.read()

        lambda_pipeline_change = lambda_.Function(
            self,
            "PipelineChangeFunction",
            function_name=f"sagemaker-{project_name}-pipeline-change",
            code=lambda_.Code.from_inline(lambda_pipeline_change_code),
            role=lambda_role,
            handler="index.lambda_handler",
            runtime=lambda_.Runtime.PYTHON_3_8,
            timeout=core.Duration.seconds(3),
            memory_size=128,
            environment={
                "LOG_LEVEL": "INFO",
                "CODE_PIPELINE_NAME": code_pipeline_name,
                "DRIFT_RULE_NAME": drift_rule_name,
                "SCHEDULE_RULE_NAME": schedule_rule_name,
            },
        )

        # Add permissions to put job status (if we want to call this directly within CodePipeline)
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
            description="Rule to enable/disable SM pipeline triggers when a SageMaker Model Building Pipeline is in progress.",
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
            targets=[targets.LambdaFunction(lambda_pipeline_change)],
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
