#!/usr/bin/env python3

import logging

from aws_cdk import core
from infra.pipeline_stack import PipelineStack
from infra.service_catalog_stack import ServiceCatalogStack

# Configure the logger
logger = logging.getLogger(__name__)
logging.basicConfig(level="INFO")

# Create App and stacks
app = core.App()

artifact_bucket = app.node.try_get_context("ArtifactBucket")

# Create the pipeline stack
synth = core.DefaultStackSynthesizer()
if artifact_bucket is not None:
    synth = core.DefaultStackSynthesizer(
        file_assets_bucket_name=artifact_bucket,
        generate_bootstrap_version_rule=False,
    )
PipelineStack(app, "drift-pipeline", synthesizer=synth)

# Create the SC stack
synth = core.DefaultStackSynthesizer()
if artifact_bucket is not None:
    synth = core.DefaultStackSynthesizer(
        file_assets_bucket_name=artifact_bucket,
        generate_bootstrap_version_rule=False,
    )

ServiceCatalogStack(app, "drift-service-catalog", synthesizer=synth)

app.synth()
