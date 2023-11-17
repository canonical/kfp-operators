#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.
"""Conftest for integration tests."""
import subprocess
import time
from pathlib import Path

from ..kfp_globals import *

import kfp
import kfp_server_api
import lightkube
import pytest
import yaml
from lightkube import codecs
from lightkube.generic_resource import create_global_resource

from _pytest.config.argparsing import Parser

@pytest.fixture(scope="function")
def upload_and_clean_pipeline(kfp_client: kfp.Client):
    """Upload an arbitrary pipeline and remove after test case execution."""
    pipeline_upload_response = kfp_client.pipeline_uploads.upload_pipeline(
        uploadfile=SAMPLE_PIPELINE["v1"], name=SAMPLE_PIPELINE_NAME
    )

    yield pipeline_upload_response

    kfp_client.delete_pipeline(pipeline_id=pipeline_upload_response.id)


@pytest.fixture(scope="function")
def create_and_clean_experiment(kfp_client: kfp.Client):
    """Create an experiment and remove after test case execution."""
    experiment_response = kfp_client.create_experiment(
        name="test-experiment", namespace=KUBEFLOW_PROFILE_NAMESPACE
    )

    yield experiment_response

    kfp_client.delete_experiment(experiment_id=experiment_response.id)
