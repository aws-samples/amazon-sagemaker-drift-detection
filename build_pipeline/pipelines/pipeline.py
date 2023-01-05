"""Example workflow pipeline script for NYC Taxi pipeline.
                                               . -RegisterModel
                                              .
    Process-> Train -> Evaluate -> Condition .
             .                                .
              -> Baseline                      . -(stop)

Implements a get_pipeline(**kwargs) method.
"""
import json
import os

import boto3
import sagemaker
import sagemaker.session
from sagemaker.debugger import Rule, rule_configs
from sagemaker.drift_check_baselines import DriftCheckBaselines
from sagemaker.estimator import Estimator
from sagemaker.inputs import TrainingInput
from sagemaker.model_metrics import MetricsSource, ModelMetrics
from sagemaker.model_monitor.dataset_format import DatasetFormat
from sagemaker.processing import (
    ProcessingInput,
    ProcessingOutput,
    Processor,
    ScriptProcessor,
)
from sagemaker.s3 import S3Uploader
from sagemaker.sklearn.processing import SKLearnProcessor
from sagemaker.utils import name_from_base
from sagemaker.workflow.check_job_config import CheckJobConfig
from sagemaker.workflow.condition_step import ConditionStep, JsonGet
from sagemaker.workflow.conditions import ConditionLessThanOrEqualTo
from sagemaker.workflow.execution_variables import ExecutionVariables
from sagemaker.workflow.functions import Join
from sagemaker.workflow.parameters import ParameterInteger, ParameterString
from sagemaker.workflow.pipeline import Pipeline
from sagemaker.workflow.pipeline_context import PipelineSession
from sagemaker.workflow.properties import PropertyFile
from sagemaker.workflow.quality_check_step import (
    DataQualityCheckConfig,
    ModelQualityCheckConfig,
    QualityCheckStep,
)
from sagemaker.workflow.step_collections import RegisterModel
from sagemaker.workflow.steps import CacheConfig, ProcessingStep, TrainingStep

BASE_DIR = os.path.dirname(os.path.realpath(__file__))


def get_session(region, default_bucket):
    """Gets the sagemaker session based on the region.
    Args:
        region: the aws region to start the session
        default_bucket: the bucket to use for storing the artifacts
    Returns:
        `sagemaker.session.Session instance
    """

    boto_session = boto3.Session(region_name=region)

    sagemaker_client = boto_session.client("sagemaker")
    return PipelineSession(
        boto_session=boto_session,
        sagemaker_client=sagemaker_client,
        default_bucket=default_bucket,     
    )


def get_pipeline(
    region,
    role,
    pipeline_name,
    model_package_group_name,
    default_bucket,
    base_job_prefix,
):
    """Gets a SageMaker ML Pipeline instance working with on nyc taxi data.
    Args:
        region: AWS region to create and run the pipeline.
        role: IAM role to create and run steps and pipeline.
        default_bucket: the bucket to use for storing the artifacts
        pipeline_name: the bucket to use for storing the artifacts
        model_package_group_name: the model package group name
        base_job_prefix: the prefix to include after the bucket
    Returns:
        an instance of a pipeline
    """
    sagemaker_session = get_session(region, default_bucket)

    # parameters for pipeline execution
    input_source = ParameterString(
        name="InputSource",
        default_value="Studio",
    )
    input_data = ParameterString(
        name="InputDataUrl",
        default_value=f"s3://{default_bucket}/{base_job_prefix}/input/data",
    )
    input_zones = ParameterString(
        name="InputZonesUrl",
        default_value=f"s3://{default_bucket}/{base_job_prefix}/input/zones/taxi_zones.zip",
    )
    processing_instance_count = ParameterInteger(
        name="ProcessingInstanceCount", default_value=1
    )
    processing_instance_type = ParameterString(
        name="ProcessingInstanceType", default_value="ml.m5.xlarge"
    )
    baseline_instance_type = ParameterString(
        name="BaselineInstanceType", default_value="ml.m5.xlarge"
    )
    training_instance_type = ParameterString(
        name="TrainingInstanceType", default_value="ml.m5.xlarge"
    )
    model_approval_status = ParameterString(
        name="ModelApprovalStatus", default_value="PendingManualApproval"
    )
    model_output = ParameterString(
        name="ModelOutputUrl",
        default_value=f"s3://{default_bucket}/{base_job_prefix}/model",
    )
    baseline_output = ParameterString(
        name="OutputBaselineUrl",
        default_value=f"s3://{default_bucket}/{base_job_prefix}/baseline/",
    )

    # Create cache configuration (Unable to pass parameter for expire_after value)
    cache_config = CacheConfig(enable_caching=False, expire_after="PT1H")

    # processing step for feature engineering
    sklearn_processor = SKLearnProcessor(
        framework_version="0.23-1",
        instance_type=processing_instance_type,
        instance_count=processing_instance_count,
        base_job_name=f"{base_job_prefix}/sklearn-preprocess",
        sagemaker_session=sagemaker_session,
        role=role,
    )
    step_process = ProcessingStep(
        name="PreprocessData",
        processor=sklearn_processor,
        inputs=[
            ProcessingInput(
                source=input_data,
                destination="/opt/ml/processing/input/data",
                s3_data_distribution_type="ShardedByS3Key",
            ),
            ProcessingInput(
                source=input_zones,
                destination="/opt/ml/processing/input/zones",
                s3_data_distribution_type="FullyReplicated",
            ),
        ],
        outputs=[
            ProcessingOutput(output_name="train", source="/opt/ml/processing/train"),
            ProcessingOutput(
                output_name="validation", source="/opt/ml/processing/validation"
            ),
            ProcessingOutput(output_name="test", source="/opt/ml/processing/test"),
            ProcessingOutput(
                output_name="baseline", source="/opt/ml/processing/baseline"
            ),
        ],
        code=os.path.join(BASE_DIR, "preprocess.py"),
        cache_config=cache_config,
    )

    check_job_config = CheckJobConfig(
        role=role,
        instance_count=1,
        instance_type=baseline_instance_type,
        sagemaker_session=sagemaker_session,
    )

    data_quality_check_config = DataQualityCheckConfig(
        baseline_dataset=step_process.properties.ProcessingOutputConfig.Outputs[
            "baseline"
        ].S3Output.S3Uri,
        dataset_format=DatasetFormat.csv(),
        output_s3_uri=Join(
            on="/",
            values=[
                "s3:/",
                default_bucket,
                base_job_prefix,
                ExecutionVariables.PIPELINE_EXECUTION_ID,
                "dataqualitycheckstep",
            ],
        ),
    )

    step_baseline = QualityCheckStep(
        name="DataQualityBaselineJob",
        skip_check=True,
        register_new_baseline=True,
        quality_check_config=data_quality_check_config,
        check_job_config=check_job_config,
        model_package_group_name=model_package_group_name,
        cache_config=cache_config,
    )

    # Define the XGBoost training report rules
    # see: https://docs.aws.amazon.com/sagemaker/latest/dg/debugger-training-xgboost-report.html
    rules = [Rule.sagemaker(rule_configs.create_xgboost_report())]

    # training step for generating model artifacts
    image_uri = sagemaker.image_uris.retrieve(
        framework="xgboost",
        region=region,
        version="1.2-2",
        py_version="py3",
        instance_type=training_instance_type,
    )
    xgb_train = Estimator(
        image_uri=image_uri,
        instance_type=training_instance_type,
        instance_count=1,
        output_path=model_output,
        base_job_name=f"{base_job_prefix}/train",
        sagemaker_session=sagemaker_session,
        role=role,
        disable_profiler=False,  # Profile processing job
        rules=rules,  # Report processing job
    )

    # Set some hyper parameters
    # https://docs.aws.amazon.com/sagemaker/latest/dg/xgboost_hyperparameters.html
    xgb_train.set_hyperparameters(
        objective="reg:squarederror",
        num_round=100,
        early_stopping_rounds=10,
        max_depth=9,
        eta=0.2,
        gamma=4,
        min_child_weight=300,
        subsample=0.8,
    )
    step_train = TrainingStep(
        name="TrainModel",
        estimator=xgb_train,
        inputs={
            "train": TrainingInput(
                s3_data=step_process.properties.ProcessingOutputConfig.Outputs[
                    "train"
                ].S3Output.S3Uri,
                content_type="text/csv",
            ),
            "validation": TrainingInput(
                s3_data=step_process.properties.ProcessingOutputConfig.Outputs[
                    "validation"
                ].S3Output.S3Uri,
                content_type="text/csv",
            ),
        },
        cache_config=cache_config,
    )

    # processing step for evaluation
    script_eval = ScriptProcessor(
        image_uri=image_uri,
        command=["python3"],
        instance_type=processing_instance_type,
        instance_count=1,
        base_job_name=f"{base_job_prefix}/script-eval",
        sagemaker_session=sagemaker_session,
        role=role,
    )
    evaluation_report = PropertyFile(
        name="EvaluationReport",
        output_name="evaluation",
        path="evaluation.json",
    )
    step_eval = ProcessingStep(
        name="EvaluateModel",
        processor=script_eval,
        inputs=[
            ProcessingInput(
                source=step_train.properties.ModelArtifacts.S3ModelArtifacts,
                destination="/opt/ml/processing/model",
            ),
            ProcessingInput(
                source=step_process.properties.ProcessingOutputConfig.Outputs[
                    "test"
                ].S3Output.S3Uri,
                destination="/opt/ml/processing/test",
            ),
        ],
        outputs=[
            ProcessingOutput(
                output_name="evaluation", source="/opt/ml/processing/evaluation"
            ),
        ],
        code=os.path.join(BASE_DIR, "evaluate.py"),
        property_files=[evaluation_report],
        cache_config=cache_config,
    )

    # register model step that will be conditionally executed
    model_metrics = ModelMetrics(
        model_statistics=MetricsSource(
            s3_uri="{}/evaluation.json".format(
                step_eval.arguments["ProcessingOutputConfig"]["Outputs"][0]["S3Output"][
                    "S3Uri"
                ]
            ),
            content_type="application/json",
        ),
        model_data_statistics=MetricsSource(
            s3_uri=step_baseline.properties.CalculatedBaselineStatistics,
            content_type="application/json",
        ),
        model_data_constraints=MetricsSource(
            s3_uri=step_baseline.properties.CalculatedBaselineConstraints,
            content_type="application/json",
        ),
    )

    drift_check_baselines = DriftCheckBaselines(
        model_data_statistics=MetricsSource(
            s3_uri=step_baseline.properties.BaselineUsedForDriftCheckStatistics,
            content_type="application/json",
        ),
        model_data_constraints=MetricsSource(
            s3_uri=step_baseline.properties.BaselineUsedForDriftCheckConstraints,
            content_type="application/json",
        ),
    )

    step_register = RegisterModel(
        name="RegisterModel",
        estimator=xgb_train,
        model_data=step_train.properties.ModelArtifacts.S3ModelArtifacts,
        content_types=["text/csv"],
        response_types=["text/csv"],
        inference_instances=["ml.t2.medium", "ml.t2.large", "ml.m5.large"],
        transform_instances=["ml.m5.large"],
        model_package_group_name=model_package_group_name,
        approval_status=model_approval_status,
        model_metrics=model_metrics,
        drift_check_baselines=drift_check_baselines,
    )

    # condition step for evaluating model quality and branching execution
    cond_lte = ConditionLessThanOrEqualTo(
        left=JsonGet(
            step=step_eval,
            property_file=evaluation_report,
            json_path="regression_metrics.rmse.value",
        ),
        right=7.0,
    )
    step_cond = ConditionStep(
        name="CheckEvaluation",
        conditions=[cond_lte],
        if_steps=[step_register],
        else_steps=[],
    )

    # pipeline instance
    pipeline = Pipeline(
        name=pipeline_name,
        parameters=[
            input_source,
            input_data,
            input_zones,
            processing_instance_type,
            processing_instance_count,
            baseline_instance_type,
            training_instance_type,
            model_approval_status,
            model_output,
            baseline_output,
        ],
        steps=[step_process, step_baseline, step_train, step_eval, step_cond],
        sagemaker_session=sagemaker_session,
    )

    return pipeline


def upload_pipeline(pipeline: Pipeline, default_bucket, base_job_prefix):
    # Get the pipeline definition
    pipeline_definition_body = pipeline.definition()
    # Upload the pipeline to a unique location in s3 based on git commit and timestamp
    pipeline_name = name_from_base(f"{base_job_prefix}/pipeline")
    S3Uploader.upload_string_as_file_body(
        pipeline_definition_body, f"s3://{default_bucket}/{pipeline_name}.json"
    )
    # Return JSON with parameters used in Cfn Stack creation as template-configuration.json
    return {
        "PipelineDefinitionBucket": default_bucket,
        "PipelineDefinitionKey": f"{pipeline_name}.json",
    }
