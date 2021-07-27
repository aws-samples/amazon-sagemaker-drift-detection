from aws_cdk import (
    core,
    aws_codebuild as codebuild,
    aws_codecommit as codecommit,
    aws_codepipeline as codepipeline,
    aws_codepipeline_actions as codepipeline_actions,
    aws_events as events,
    aws_events_targets as targets,
    aws_iam as iam,
    aws_s3 as s3,
)


class DeployPipelineConstruct(core.Construct):
    """
    Deploy pipeline construct
    """

    def __init__(
        self,
        scope: core.Construct,
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

        # Add permissions to allow adding auto scaling for production deployment
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

        # Define AWS CodeBuild spec to run node.js and python
        # https://docs.aws.amazon.com/codebuild/latest/userguide/available-runtimes.html
        cdk_build = codebuild.PipelineProject(
            self,
            "CdkBuild",
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
                        "files": ["*.template.json"],
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
            pipeline_name="sagemaker-{}-{}".format(project_name, construct_id),
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
                            action_name="Build_CDK_Template",
                            project=cdk_build,
                            input=source_output,
                            outputs=[
                                cdk_build_output,
                            ],
                            role=code_pipeline_role,
                        ),
                    ],
                ),
                codepipeline.StageProps(
                    stage_name="DeployStaging",
                    actions=[
                        codepipeline_actions.CloudFormationCreateUpdateStackAction(
                            action_name="Deploy_CFN_Staging",
                            run_order=1,
                            template_path=cdk_build_output.at_path(
                                "drift-deploy-staging.template.json"
                            ),
                            stack_name="sagemaker-{}-{}-staging".format(
                                project_name, construct_id
                            ),
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
                ),
                codepipeline.StageProps(
                    stage_name="DeployProd",
                    actions=[
                        codepipeline_actions.CloudFormationCreateUpdateStackAction(
                            action_name="Deploy_CFN_Prod",
                            run_order=1,
                            template_path=cdk_build_output.at_path(
                                "drift-deploy-prod.template.json"
                            ),
                            stack_name="sagemaker-{}-{}-prod".format(
                                project_name, construct_id
                            ),
                            admin_permissions=False,
                            deployment_role=cloudformation_role,
                            role=code_pipeline_role,
                            replace_on_failure=True,
                        ),
                    ],
                ),
            ],
        )

        # Allow event role to start code pipeline
        event_role.add_to_policy(
            iam.PolicyStatement(
                actions=["codepipeline:StartPipelineExecution"],
                resources=[code_pipeline.pipeline_arn],
            )
        )

        # Add deploy role to target the code pipeline when model package is approved
        events.Rule(
            self,
            "ModelRegistryRule",
            rule_name="sagemaker-{}-modelregistry-{}".format(
                project_name, construct_id
            ),
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
            rule_name="sagemaker-{}-codecommit-{}".format(project_name, construct_id),
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
