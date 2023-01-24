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

from sagemaker.inputs import CreateModelInput
from sagemaker.model import Model
from sagemaker.model_monitor.dataset_format import DatasetFormat
from sagemaker.processing import (
    ProcessingInput,
    ProcessingOutput,
    Processor,
    ScriptProcessor,
)
from sagemaker.s3 import S3Uploader
from sagemaker.workflow.lambda_step import (
    LambdaStep,
    LambdaOutput,
    LambdaOutputTypeEnum,
)
from sagemaker.lambda_helper import Lambda
from sagemaker.workflow.parameters import (
    ParameterInteger,
    ParameterString,
)
from sagemaker.workflow.pipeline import Pipeline
from sagemaker.workflow.pipeline_context import PipelineSession
from sagemaker.workflow.steps import (
    CreateModelStep,
    ProcessingStep,
    CacheConfig,
)
from sagemaker.workflow.quality_check_step import (
    DataQualityCheckConfig,
    ModelQualityCheckConfig,
    QualityCheckStep,
)
from sagemaker.drift_check_baselines import DriftCheckBaselines
from sagemaker.workflow.check_job_config import CheckJobConfig
from sagemaker.workflow.step_collections import RegisterModel
from sagemaker.workflow.functions import Join
from sagemaker.workflow.execution_variables import ExecutionVariables
from sagemaker.utils import name_from_base


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
    region: str,
    role: str,
    pipeline_name: str,
    default_bucket: str,
    base_job_prefix: str,
    evaluate_drift_function_arn: str,
    data_uri: str,
    model_uri: str,
    transform_uri: str,
    baseline_uri: str = None,
) -> Pipeline:
    """Gets a SageMaker ML Pipeline instance working with on nyc taxi data.
    Args:
        region: AWS region to create and run the pipeline.
        role: IAM role to create and run steps and pipeline.
        pipeline_name: the bucket to use for storing the artifacts
        default_bucket: the bucket to use for storing the artifacts
        base_job_prefix: the prefix to include after the bucket
        data_uri: the input data location
        model_uri: the input model location
        transform_uri: the output transform uri location
        baseline_uri: optional input baseline uri for drift detection
    Returns:
        an instance of a pipeline
    """
    sagemaker_session = get_session(region, default_bucket)

    # parameters for pipeline execution
    input_data_uri = ParameterString(
        name="DataInputUri",
        default_value=data_uri,
    )
    input_model_uri = ParameterString(
        name="ModelInputUri",
        default_value=model_uri,
    )
    output_transform_uri = ParameterString(
        name="TransformOutputUri",
        default_value=transform_uri,
    )
    transform_instance_count = ParameterInteger(
        name="TransformInstanceCount", default_value=1
    )
    transform_instance_type = ParameterString(
        name="TransformInstanceType", default_value="ml.m5.xlarge"
    )
    monitor_instance_count = ParameterInteger(
        name="MonitorInstanceCount", default_value=1
    )
    monitor_instance_type = ParameterString(
        name="MonitorInstanceType", default_value="ml.m5.xlarge"
    )

    # Create cache configuration (Unable to pass parameter for expire_after value)
    cache_config = CacheConfig(enable_caching=True, expire_after="PT1H")

    # Create the Model step
    image_uri_inference = sagemaker.image_uris.retrieve(
        framework="xgboost",
        region=region,
        version="1.2-2",
        py_version="py3",
        instance_type=transform_instance_type,
    )

    model = Model(
        image_uri=image_uri_inference,
        model_data=input_model_uri,
        sagemaker_session=sagemaker_session,
        role=role,
    )

    inputs_model = CreateModelInput(instance_type=transform_instance_type)

    step_create_model = CreateModelStep(
        name="CreateModel", model=model, inputs=inputs_model
    )

    # processing step for evaluation
    script_eval = ScriptProcessor(
        image_uri=image_uri_inference,
        command=["python3"],
        instance_count=transform_instance_count,
        instance_type=transform_instance_type,
        base_job_name=f"{base_job_prefix}/script-score",
        sagemaker_session=sagemaker_session,
        role=role,
    )

    step_score = ProcessingStep(
        name="ScoreModel",
        processor=script_eval,
        inputs=[
            ProcessingInput(
                source=input_model_uri,
                destination="/opt/ml/processing/model",
            ),
            ProcessingInput(
                source=input_data_uri,
                destination="/opt/ml/processing/input",
            ),
        ],
        outputs=[
            ProcessingOutput(output_name="scores", source="/opt/ml/processing/output"),
        ],
        code=os.path.join(BASE_DIR, "score.py"),
        cache_config=cache_config,
    )
    step_score.add_depends_on([step_create_model])

    steps = [step_create_model, step_score]

    if baseline_uri is not None:        
        check_job_config = CheckJobConfig(
            role=role,
            instance_count=monitor_instance_count,
            instance_type=monitor_instance_type,
            sagemaker_session=sagemaker_session,
            base_job_name=f"{base_job_prefix}/monitoring",
            env = {
                "PipelineName": pipeline_name,
                "Region": region,
            }
        )

        data_quality_check_config = DataQualityCheckConfig(
            baseline_dataset=step_score.properties.ProcessingOutputConfig.Outputs["scores"].S3Output.S3Uri,
            dataset_format=DatasetFormat.csv(header=True),
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
            post_analytics_processor_script='pipelines/postprocess_monitor_script.py',
        )

        step_monitor = QualityCheckStep(
            name="ModelMonitor",
            skip_check=False,
            register_new_baseline=False,
            quality_check_config=data_quality_check_config,
            check_job_config=check_job_config,
            supplied_baseline_statistics=os.path.join(baseline_uri, "statistics.json"),
            supplied_baseline_constraints=os.path.join(baseline_uri, "constraints.json"),
            cache_config=cache_config,
        )

        steps += [step_monitor]

    # pipeline instance
    pipeline = Pipeline(
        name=pipeline_name,
        parameters=[
            input_data_uri,
            input_model_uri,
            output_transform_uri,
            transform_instance_count,
            transform_instance_type,
            monitor_instance_count,
            monitor_instance_type,
        ],
        steps=steps,
        sagemaker_session=sagemaker_session,
    )

    return pipeline


def upload_pipeline(pipeline: Pipeline, default_bucket, base_job_prefix) -> str:
    # Get the pipeline definition
    pipeline_definition_body = pipeline.definition()
    # Upload the pipeline to a unique location in s3 based on git commit and timestamp
    pipeline_key = f"{name_from_base(base_job_prefix)}/pipeline.json"
    S3Uploader.upload_string_as_file_body(
        pipeline_definition_body, f"s3://{default_bucket}/{pipeline_key}"
    )
    return pipeline_key
