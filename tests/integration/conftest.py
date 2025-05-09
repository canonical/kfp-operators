#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.
"""Conftest for integration tests."""
import subprocess
import time
from pathlib import Path

from helpers.k8s_resources import apply_manifests
from kfp_globals import *

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

    # Remove profile
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


def pytest_addoption(parser: Parser):
    parser.addoption(
        "--bundle",
        default="./tests/integration/bundles/bundle.yaml.j2",
        help="Path to bundle file to use as the template for tests.  This must include all charms"
        "built by this bundle, where the locally built charms will replace those specified. "
        "This is useful for testing this bundle against different external dependencies. "
        "An example file is in ./tests/integration/bundles/bundle.yaml",
    )
    parser.addoption(
        "--no-build",
        action="store_true",
        help="Whether the charms in this repository should be built locally and used"
        "to render the bundle definition template."
        "If set to False, the integration tests will be run against charms in Charmhub.",
    )
    parser.addoption(
        "--charmcraft-clean",
        action="store_true",
        help="Whether to run charmcraft clean and delete lxc instances created by charmcraft."
        "It defaults to False."
    )
    parser.addoption(
        "--charms-path",
        help="Path to directory where charm files are stored.",
    )
