"""Example workflow pipeline script for NYC Taxi pipeline.
                                               . -RegisterModel
                                              .
    Process-> Train -> Evaluate -> Condition .
             .                                .
              -> Baseline                      . -(stop)

Implements a get_pipeline(**kwargs) method.
"""
import os

# from sagemaker.model import ModelPackage
from sagemaker.model_monitor.dataset_format import DatasetFormat
from sagemaker.s3 import S3Uploader
from sagemaker.transformer import Transformer
from sagemaker.utils import name_from_base
from sagemaker.workflow.check_job_config import CheckJobConfig
from sagemaker.workflow.execution_variables import ExecutionVariables
from sagemaker.workflow.functions import Join

# from sagemaker.workflow.model_step import ModelStep
from sagemaker.workflow.monitor_batch_transform_step import MonitorBatchTransformStep
from sagemaker.workflow.parameters import (
    ParameterBoolean,
    ParameterInteger,
    ParameterString,
)
from sagemaker.workflow.pipeline import Pipeline
from sagemaker.workflow.pipeline_context import PipelineSession
from sagemaker.workflow.quality_check_step import DataQualityCheckConfig
from sagemaker.workflow.steps import CacheConfig

BASE_DIR = os.path.dirname(os.path.realpath(__file__))


def get_pipeline(
    role: str,
    pipeline_name: str,
    default_bucket: str,
    model_package_arn: str,
    data_uri: str = None,
    default_model_name: str = None,
) -> Pipeline:
    """Gets a SageMaker ML Pipeline instance."""
    sagemaker_session = PipelineSession()

    # Parameters
    input_data_uri = ParameterString(
        name="DataInputUri",
        default_value=data_uri,
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
    stop_if_check_fails = ParameterBoolean(name="StopIfCheckFails", default_value=False)
    model_name = ParameterString(name="ModelName", default_value=default_model_name)

    parameters = [
        model_name,
        input_data_uri,
        transform_instance_count,
        transform_instance_type,
        monitor_instance_count,
        monitor_instance_type,
        stop_if_check_fails,
    ]

    output_common_path = [
        "s3:/",
        default_bucket,
        "batch-transform-runs",
        Join(
            on="-",
            values=[
                ExecutionVariables.START_DATETIME,
                ExecutionVariables.PIPELINE_EXECUTION_ID,
            ],
        ),
    ]

    model_package_group_name = model_package_arn.split("/", -1)[-2]

    # Cache configuration (Unable to pass parameter for expire_after value)
    cache_config = CacheConfig(enable_caching=True, expire_after="PT1H")

    # Data Quality Check configuration
    check_job_config = CheckJobConfig(
        role=role,
        instance_count=monitor_instance_count,
        instance_type=monitor_instance_type,
    )
    data_quality_config = DataQualityCheckConfig(
        baseline_dataset=input_data_uri,
        dataset_format=DatasetFormat.csv(header=False),
        output_s3_uri=Join(
            on="/",
            values=output_common_path + ["dataqualitycheck"],
        ),
        post_analytics_processor_script="pipelines/postprocess_monitor_script.py"
    )

    # Transform Step arguments
    transformer = Transformer(
        model_name=model_name,
        instance_count=transform_instance_count,
        instance_type=transform_instance_type,
        accept="text/csv",
        assemble_with="Line",
        output_path=Join(
            on="/",
            values=output_common_path + ["transformed"],
        ),
        sagemaker_session=sagemaker_session,
    )

    transform_arg = transformer.transform(
        input_data_uri,
        content_type="text/csv",
        split_type="Line",
        # exclude the ground truth (first column) from the validation set
        # when doing inference.
        input_filter="$[1:]",
    )

    transform_and_monitor_step = MonitorBatchTransformStep(
        name="MonitorDataQuality",
        transform_step_args=transform_arg,
        monitor_configuration=data_quality_config,
        check_job_configuration=check_job_config,
        monitor_before_transform=True,
        fail_on_violation=stop_if_check_fails,
    )
    transform_and_monitor_step.steps[
        1
    ].model_package_group_name = model_package_group_name
    for step in transform_and_monitor_step.steps:
        step.cache_config = cache_config

    return Pipeline(
        name=pipeline_name,
        parameters=parameters,
        steps=[
            transform_and_monitor_step,
        ],
        sagemaker_session=sagemaker_session,
    )


def upload_pipeline(pipeline: Pipeline, default_bucket, base_job_prefix) -> str:
    # Get the pipeline definition
    pipeline_definition_body = pipeline.definition()
    # Upload the pipeline to a unique location in s3 based on git commit and timestamp
    pipeline_key = f"{name_from_base(base_job_prefix)}/pipeline.json"
    S3Uploader.upload_string_as_file_body(
        pipeline_definition_body, f"s3://{default_bucket}/{pipeline_key}"
    )
    return pipeline_key
