#!/usr/bin/env python3

import logging

from aws_cdk import core
from infra.pipeline_stack import BatchPipelineStack, DeployPipelineStack
from infra.service_catalog_stack import ServiceCatalogStack

# Configure the logger
logger = logging.getLogger(__name__)
logging.basicConfig(level="INFO")

# Create App and stacks
app = core.App()

# Attempts to retrive custom bucket name and object key prefix for deployable assets.
artifact_bucket = app.node.try_get_context("drift:ArtifactBucket")
artifact_bucket_prefix = app.node.try_get_context("drift:ArtifactBucketPrefix")

# Create the batch pipeline stack
BatchPipelineStack(
    app,
    "drift-batch-pipeline",
    synthesizer=core.DefaultStackSynthesizer(
        file_assets_bucket_name=artifact_bucket,
        bucket_prefix=artifact_bucket_prefix,
        generate_bootstrap_version_rule=False,
    ),
)

# Create the real-time deploy stack
DeployPipelineStack(
    app,
    "drift-deploy-pipeline",
    synthesizer=core.DefaultStackSynthesizer(
        file_assets_bucket_name=artifact_bucket,
        bucket_prefix=artifact_bucket_prefix,
        generate_bootstrap_version_rule=False,
    ),
)

# Create the SC stack
synth = core.DefaultStackSynthesizer(
    file_assets_bucket_name=artifact_bucket,
    generate_bootstrap_version_rule=False,
    bucket_prefix=artifact_bucket_prefix,
)

ServiceCatalogStack(app, "drift-service-catalog", synthesizer=synth)

app.synth()
