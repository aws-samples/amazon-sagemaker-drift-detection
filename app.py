#!/usr/bin/env python3

import logging

import aws_cdk as cdk

from infra.service_catalog_stack import ServiceCatalogStack

# Configure the logger
logger = logging.getLogger(__name__)
logging.basicConfig(level="INFO")

# Create App and stacks
app = cdk.App()

# Attempts to retrieve custom bucket name and object key prefix for deployable assets.
artifact_bucket = app.node.try_get_context("drift:ArtifactBucket")
artifact_bucket_prefix = app.node.try_get_context("drift:ArtifactBucketPrefix")



# Create the SC stack
synth = cdk.DefaultStackSynthesizer(
    file_assets_bucket_name=artifact_bucket,
    generate_bootstrap_version_rule=False,
    bucket_prefix=artifact_bucket_prefix,
)

ServiceCatalogStack(app, "drift-service-catalog", synthesizer=synth)

app.synth()
