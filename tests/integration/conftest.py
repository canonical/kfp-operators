#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.
"""Conftest for integration tests."""
import subprocess
import time
from pathlib import Path

from helpers.k8s_resources import apply_manifests

import kfp
import kfp_server_api
import lightkube
import pytest
import yaml
from lightkube import codecs
from lightkube.generic_resource import create_global_resource

from _pytest.config.argparsing import Parser

basedir = Path("./").absolute()

# Variables for configuring the KFP Client
# It is assumed that the ml-pipeline-ui (kfp-ui) service is port-forwarded
KUBEFLOW_LOCAL_HOST = "http://localhost:8080"
KUBEFLOW_PROFILE_NAMESPACE = "kubeflow-user-example-com"
PROFILE_FILE_PATH = f"{basedir}/tests/integration/profile/profile.yaml"
PROFILE_FILE = yaml.safe_load(Path(PROFILE_FILE_PATH).read_text())
KUBEFLOW_USER_NAME = PROFILE_FILE["spec"]["owner"]["name"]

@pytest.fixture(scope="session")
def forward_kfp_ui():
    """Port forward the kfp-ui service."""
    kfp_ui_process = subprocess.Popen(
        ["kubectl", "port-forward", "-n", "kubeflow", "svc/kfp-ui", "8080:3000"]
    )

    # FIXME: find a better way to do this
    # Allow time for the port-forward to happen
    time.sleep(6)

    yield

    kfp_ui_process.terminate()


@pytest.fixture(scope="session")
def apply_profile(lightkube_client):
    """Apply a Profile simulating a user."""
    # Create a Viewer namespaced resource
    profile_class_resource = create_global_resource(
        group="kubeflow.org", version="v1", kind="Profile", plural="profiles"
    )

    # Apply Profile first
    apply_manifests(lightkube_client, PROFILE_FILE_PATH)

    yield

    # Remove namespace
    read_yaml = Path(PROFILE_FILE_PATH).read_text()
    yaml_loaded = codecs.load_all_yaml(read_yaml)
    for obj in yaml_loaded:
        try:
            lightkube_client.delete(
                res=type(obj),
                name=obj.metadata.name,
                namespace=obj.metadata.namespace,
            )
        except lightkube.core.exceptions.ApiError as api_error:
            raise api_error


@pytest.fixture(scope="session")
def kfp_client(apply_profile, forward_kfp_ui) -> kfp.Client:
    """Returns a KFP Client that can talk to the KFP API Server."""
    # Instantiate the KFP Client
    client = kfp.Client(host=KUBEFLOW_LOCAL_HOST, namespace=KUBEFLOW_PROFILE_NAMESPACE)
    client.runs.api_client.default_headers.update({"kubeflow-userid": KUBEFLOW_USER_NAME})
    return client


@pytest.fixture(scope="session")
def lightkube_client() -> lightkube.Client:
    """Returns a lightkube Client that can talk to the K8s API."""
    client = lightkube.Client(field_manager="kfp-operators")
    return client


@pytest.fixture(scope="function")
def upload_and_clean_pipeline(kfp_client: kfp.Client):
    """Upload an arbitrary pipeline and remove after test case execution."""
    pipeline_upload_response = kfp_client.pipeline_uploads.upload_pipeline(
        uploadfile=SAMPLE_PIPELINE, name=SAMPLE_PIPELINE_NAME
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


def pytest_addoption(parser: Parser):
    parser.addoption(
        "--bundle",
        default="./tests/integration/bundles/kfp_latest_edge.yaml.j2",
        help="Path to bundle file to use as the template for tests.  This must include all charms"
             "built by this bundle, where the locally built charms will replace those specified. "
             "This is useful for testing this bundle against different external dependencies. "
             "An example file is in ./tests/integration/data/kfp_latest_edge.yaml",
    )
    parser.addoption(
        "--build",
        default=True,
        help="Whether the charms in this repository should be built locally and used"
             "to render the bundle definition template."
             "If set to False, the integration tests will be run against charms in Charmhub.",
    )
