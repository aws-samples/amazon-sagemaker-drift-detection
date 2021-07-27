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

# Create the pipeline stack
PipelineStack(app, "drift-pipeline")

# Create the SC stack
ServiceCatalogStack(app, "drift-service-catalog")

app.synth()
