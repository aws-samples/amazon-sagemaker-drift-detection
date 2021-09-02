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

from sagemaker.model_monitor.dataset_format import DatasetFormat
from sagemaker.processing import (
    ProcessingInput,
    ProcessingOutput,
    Processor,
    ScriptProcessor,
)
from sagemaker.s3 import S3Uploader
from sagemaker.workflow.parameters import (
    ParameterInteger,
    ParameterString,
)
from sagemaker.workflow.pipeline import Pipeline
from sagemaker.workflow.steps import (
    ProcessingStep,
    CacheConfig,
)
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
    runtime_client = boto_session.client("sagemaker-runtime")
    return sagemaker.session.Session(
        boto_session=boto_session,
        sagemaker_client=sagemaker_client,
        sagemaker_runtime_client=runtime_client,
        default_bucket=default_bucket,
    )


def get_pipeline(
    region,
    role,
    pipeline_name,
    baseline_uri,
    model_uri,
    default_bucket,
    base_job_prefix,
) -> Pipeline:
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
    input_data_uri = ParameterString(
        name="DataUri",
    )
    input_model_uri = ParameterString(
        name="ModelUri",
        default_value=model_uri,
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
    output_transform_uri = ParameterString(
        name="TransformOutputUri",
        default_value=f"s3://{default_bucket}/{base_job_prefix}/transform/",
    )
    output_monitor_uri = ParameterString(
        name="MonitorOutputUri",
        default_value=f"s3://{default_bucket}/{base_job_prefix}/reporting/",
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

    # Get the default model monitor container
    model_monitor_container_uri = sagemaker.image_uris.retrieve(
        framework="model-monitor",
        region=region,
        version="latest",
    )

    # Create the baseline job using
    dataset_format = DatasetFormat.csv()
    env = {
        "dataset_format": json.dumps(dataset_format),
        "dataset_source": "/opt/ml/processing/input/baseline_dataset_input",
        "output_path": "/opt/ml/processing/output",
        "publish_cloudwatch_metrics": "Disabled",
    }

    monitor_analyzer = Processor(
        image_uri=model_monitor_container_uri,
        role=role,
        instance_count=monitor_instance_count,
        instance_type=monitor_instance_type,
        base_job_name=f"{base_job_prefix}/monitoring",
        sagemaker_session=sagemaker_session,
        max_runtime_in_seconds=1800,
        env=env,
    )

    step_monitor = ProcessingStep(
        name="ModelMonitor",
        processor=monitor_analyzer,
        inputs=[
            ProcessingInput(
                source=step_score.properties.ProcessingOutputConfig.Outputs[
                    "scores"
                ].S3Output.S3Uri,
                destination="/opt/ml/processing/input/baseline_dataset_input",
                input_name="baseline_dataset_input",
            ),
            ProcessingInput(
                source=os.path.join(baseline_uri, "constraints.json"),
                destination="/opt/ml/processing/baseline/constraints",
                input_name="constraints",
            ),
            ProcessingInput(
                source=os.path.join(baseline_uri, "statistics.json"),
                destination="/opt/ml/processing/baseline/stats",
                input_name="baseline",
            ),
        ],
        outputs=[
            ProcessingOutput(
                source="/opt/ml/processing/output",
                destination=output_monitor_uri,
                output_name="monitoring_output",
            ),
        ],
        cache_config=cache_config,
    )

    # pipeline instance
    pipeline = Pipeline(
        name=pipeline_name,
        parameters=[
            input_data_uri,
            input_model_uri,
            transform_instance_count,
            transform_instance_type,
            monitor_instance_count,
            monitor_instance_type,
            output_transform_uri,
            output_monitor_uri,
        ],
        steps=[step_score, step_monitor],
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
