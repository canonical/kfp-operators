#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.
"""Conftest for integration tests."""
import logging
import subprocess
import time
from pathlib import Path

import jubilant
import kfp
import lightkube
import pytest
import yaml
from _pytest.config.argparsing import Parser
from helpers.k8s_resources import apply_manifests
from lightkube import codecs
from lightkube.generic_resource import create_global_resource

basedir = Path("./").absolute()

# Variables for configuring the KFP Client
# It is assumed that the ml-pipeline-ui (kfp-ui) service is port-forwarded
KUBEFLOW_LOCAL_HOST = "http://localhost:8080"
KUBEFLOW_PROFILE_NAMESPACE = "kubeflow-user-example-com"
PROFILE_FILE_PATH = f"{basedir}/tests/integration/profile/profile.yaml"
PROFILE_FILE = yaml.safe_load(Path(PROFILE_FILE_PATH).read_text())
KUBEFLOW_USER_NAME = PROFILE_FILE["spec"]["owner"]["name"]

WAIT_TIMEOUT = 20 * 60

log = logging.getLogger(__name__)


def pytest_configure(config):
    # Custom markers
    config.addinivalue_line("markers", "deploy: mark test as a deployment test")
    config.addinivalue_line(
        "markers", "abort_on_fail: abort the entire test session if this test fails"
    )


def pytest_collection_modifyitems(config, items):
    if config.getoption("--no-deploy"):
        skip_deploy = pytest.mark.skip(reason="skipped because --no-deploy was passed")
        for item in items:
            # If the test has the @pytest.mark.deploy marker, skip it
            if "deploy" in item.keywords:
                item.add_marker(skip_deploy)


@pytest.hookimpl(tryfirst=True, hookwrapper=True)
def pytest_runtest_makereport(item, call):
    # Yield control to allow the test to run and generate a report
    outcome = yield
    report = outcome.get_result()

    # If the test failed during execution
    if report.when == "call" and report.failed:
        # Check if the test function had the custom marker
        if item.get_closest_marker("abort_on_fail"):
            log.warning(f"\n[ABORT] Test '{item.name}' failed. Aborting session.")
            # Gracefully stop the session
            item.session.shouldstop = True


@pytest.fixture(scope="module")
def juju(request: pytest.FixtureRequest):
    keep_models = bool(request.config.getoption("--keep-models"))
    model_name = request.config.getoption("--model")

    def print_debug_log(juju_instance: jubilant.Juju):
        if request.session.testsfailed:
            print(f"[DEBUG] Fetching debug log for model: {juju_instance.model}")
            log = juju_instance.debug_log(limit=1000)
            print(log, end="")

    if model_name:
        juju_instance = jubilant.Juju(model=model_name)
        juju_instance.wait_timeout = WAIT_TIMEOUT
        try:
            yield juju_instance
        finally:
            print_debug_log(juju_instance)
    else:
        with jubilant.temp_model(keep=keep_models) as juju_instance:
            juju_instance.wait_timeout = WAIT_TIMEOUT
            try:
                yield juju_instance
            finally:
                print_debug_log(juju_instance)


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
    create_global_resource(group="kubeflow.org", version="v1", kind="Profile", plural="profiles")

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
        "--keep-models",
        action="store_true",
        default=False,
        help="keep temporarily-created models",
    )
    parser.addoption(
        "--model",
        action="store",
        help="Juju model to use; if not provided, a new model "
        "will be created for each test which requires one",
    )
    parser.addoption(
        "--no-deploy",
        action="store_true",
        default=False,
        help="Don't deploy any charms before testing",
    )
    parser.addoption(
        "--bundle",
        default="./tests/integration/bundles/bundle.yaml.j2",
        help="Path to bundle file to use as the template for tests.  This must include all charms"
        "built by this bundle, where the locally built charms will replace those specified. "
        "This is useful for testing this bundle against different external dependencies. "
        "An example file is in ./tests/integration/bundles/bundle.yaml.j2",
    )
    parser.addoption(
        "--charms-path",
        help="Path to directory where charm files are stored.",
    )
