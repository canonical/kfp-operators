#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.
import logging
import pytest
import time
from pathlib import Path, PosixPath

from helpers.localize_bundle import localize_bundle_application, get_resources_from_charm_file
from helpers.bundle_mgmt import render_bundle, deploy_bundle
from helpers.auth_session import get_istio_auth_session

import aiohttp
import kfp
import kfp_server_api
import lightkube
import yaml
from lightkube import codecs
from lightkube.generic_resource import create_namespaced_resource
from pytest_operator.plugin import OpsTest

GENERIC_BUNDLE_CHARMS = [
    "kfp-api",
    "kfp-persistence",
    "kfp-schedwf",
    "kfp-ui",
    "kfp-viewer",
    "kfp-viz",
]

basedir = Path("./").absolute()
CHARM_PATH_TEMPLATE = "{basedir}/charms/{charm}/"

# Configuration for auth session
KUBEFLOW_HOST = "http://10.64.140.43.nip.io"
DEX_STATIC_USERNAME = "admin"
DEX_STATIC_PASSWORD = "admin"

# Variables for uploading/creating pipelines/experiments/runs
SAMPLE_PIPELINE = f"{basedir}/tests/integration/pipelines/sample_pipeline.yaml"
SAMPLE_PIPELINE_NAME = "sample-pipeline-2"

# Variables for creating a viewer
SAMPLE_VIEWER = f"{basedir}/tests/integration/viewer/mnist.yaml"

log = logging.getLogger(__name__)


@pytest.fixture(scope="function")
def auth_session() -> dict:
    """Returns the session cookies needed for Authentication."""
    # Authenticate with Dex using static password and username
    # It is assumed that these tests run in a Microk8s environment where
    # Metallb is enabled with an arbitrary IP range 10.64.140.43-10.64.140.49
    # and the istio-operators are deployed in the cluster and configured to use the LB
    # provided by Metallb.
    return get_istio_auth_session(
        url=f"{KUBEFLOW_HOST}/dex", username=DEX_STATIC_USERNAME, password=DEX_STATIC_PASSWORD
    )


@pytest.fixture(scope="function")
def kfp_client(auth_session) -> kfp.Client:
    """Returns a KFP Client that can talk to the KFP API Server."""
    # Get session cookies
    session_cookies = auth_session["session_cookie"]

    # Instantiate the KFP Client
    client = kfp.Client(host=f"{KUBEFLOW_HOST}/pipeline", cookies=session_cookies)
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

    yield upload_and_clean_pipeline

    kfp_client.delete_pipeline(pipeline_id=pipeline_upload_response.id)


@pytest.fixture(scope="function")
def create_and_clean_experiment(kfp_client: kfp.Client):
    """Create an experiment and remove after test case execution."""
    experiment_response = kfp_client.create_experiment(name="test-experiment", namespace="default")

    yield experiment_response

    kfp_client.delete_experiment(experiment_id=experiment_response.id)


# TODO: Abstract the build and deploy method into conftest
@pytest.mark.abort_on_fail
async def test_build_and_deploy(ops_test: OpsTest, request):
    """Build and deploy kfp-operators charms."""
    # Immediately raise an error if the model name is not kubeflow
    if ops_test.model_name != "kubeflow":
        raise ValueError("kfp must be deployed to namespace kubeflow")

    # Get/load template bundle from command line args
    bundlefile_path = Path(request.config.getoption("bundle"))
    basedir = Path("./").absolute()

    # Build the charms we need to build
    charms_to_build = {
        charm: Path(CHARM_PATH_TEMPLATE.format(basedir=str(basedir), charm=charm))
        for charm in GENERIC_BUNDLE_CHARMS
    }
    log.info(f"Building charms for: {charms_to_build}")
    built_charms = await ops_test.build_charms(*charms_to_build.values())
    log.info(f"Built charms: {built_charms}")

    context = {}
    for charm, charm_file in built_charms.items():
        charm_resources = get_resources_from_charm_file(charm_file)
        context.update([(f"{charm.replace('-', '_')}_resources", charm_resources)])
        context.update([(f"{charm.replace('-', '_')}", charm_file)])

    # Render kfp-operators bundle file with locally built charms and their resources
    local_build = request.config.getoption("build")
    rendered_bundle = render_bundle(
        ops_test, bundle_path=bundlefile_path, context=context, local_build=local_build
    )

    # Deploy the kfp-operators bundle from the rendered bundle file
    await deploy_bundle(ops_test, bundle_path=rendered_bundle, trust=True)

    # Wait for everything to be up.  Note, at time of writing these charms would naturally go
    # into blocked during deploy while waiting for each other to satisfy relations, so we don't
    # raise_on_blocked.
    await ops_test.model.wait_for_idle(
        status="active",
        raise_on_blocked=False,  # These apps block while waiting for each other to deploy/relate
        raise_on_error=True,
        timeout=1800,
    )


# ---- KFP API Server focused test cases
#async def test_upload_pipeline(kfp_client):
#    """Upload a pipeline from a YAML file and assert its presence."""
#    # Upload a pipeline and get the server response
#    pipeline_upload_response = kfp_client.pipeline_uploads.upload_pipeline(
#        uploadfile=SAMPLE_PIPELINE, name="test-upload-pipeline"
#    )
#    # Upload a pipeline and get its ID
#    uploaded_pipeline_id = pipeline_upload_response.id
#
#    # Get pipeline id by name, default='sample-pipeline'
#    server_pipeline_id = kfp_client.get_pipeline_id(name="test-upload-pipeline")
#    assert uploaded_pipeline_id == server_pipeline_id
#
#
#async def test_create_and_monitor_run(kfp_client, create_and_clean_experiment):
#    """Create a run and monitor it to completion."""
#    # Create a run, save response in variable for easy manipulation
#    # Create an experiment for this run
#    experiment_response = create_and_clean_experiment
#
#    # Create a run from a pipeline file (SAMPLE_PIPELINE) and an experiment (create_experiment).
#    # This call uses the 'default' kubeflow service account to be able to edit Workflows
#    create_run_response = kfp_client.create_run_from_pipeline_package(
#        pipeline_file=SAMPLE_PIPELINE,
#        arguments={},
#        run_name="test-run-1",
#        experiment_name=experiment_response.name,
#        namespace="default",
#        service_account="default",
#    )
#
#    # FIXME: wait for completion does not work at the moment, it seems like
#    # the status of the run is never updated and is causing this to timeout
#    # Monitor the run to completion, the pipeline should not be executed in
#    # more than 60 seconds as it is a very simple operation
#    # monitor_response = kfp_client.wait_for_run_completion(run_response.run_id, timeout=60)
#
#    # assert monitor_response.success is True
#
#
## ---- ScheduledWorfklows and Argo focused test case
#async def test_create_and_monitor_recurring_run(kfp_client, upload_and_clean_pipeline, create_and_clean_experiment):
#    """Create a recurring run and monitor it to completion."""
#
#    # Upload a pipeline from file
#    pipeline_response = upload_and_clean_pipeline
#
#    # Create an experiment for this run
#    experiment_response = create_and_clean_experiment
#
#    # Create a recurring run from a pipeline (upload_pipeline_from_file) and an experiment (create_experiment)
#    # This call uses the 'default' kubeflow service account to be able to edit ScheduledWorkflows
#    # This ScheduledWorkflow (Recurring Run) will run once every two seconds
#    create_recurring_run_response = kfp_client.create_recurring_run(
#        experiment_id=experiment_response.id,
#        job_name="recurring-job-1",
#        pipeline_id=pipeline_response.id,
#        enabled=True,
#        cron_expression="*/2 * * * * *",
#        max_concurrency=1,
#        service_account="default",
#    )
#
#    recurring_job = create_recurring_run_response
#    # Assert the job is enabled
#    assert recurring_job.enabled is True
#
#    # Assert the job executes once every two seconds
#    assert recurring_job.trigger.cron_schedule.cron == "*/2 * * * * *"
#
#    # Wait for the recurring job to schedule some runs
#    time.sleep(6)
#
#    # FIXME: disabling the job does not work at the moment, it seems like
#    # the status of the recurring run is never updated and is causing the
#    # following assertion to fail
#    # Disable the job after few runs
#    kfp_client.disable_job(recurring_job.id)
#
#    # Assert the job is disabled
#    # assert recurring_job.enabled is False
#
#
## ---- KFP Viewer and Visualization focused test cases
#async def test_apply_sample_viewer(lightkube_client):
#    """Test a Viewer can be applied and its presence is verified."""
#    viewer_object, viewer_object_class = apply_viewer(lightkube_client)
#
#    viewer = lightkube_client.get(
#        res=viewer_object_class,
#        name=viewer_object.metadata.name,
#        namespace=viewer_object.metadata.namespace,
#    )
#    assert viewer is not None
#
#
#async def test_viz_server_healthcheck(ops_test: OpsTest):
#    """Run a healthcheck on the server endpoint."""
#    status = await ops_test.model.get_status()
#    units = status["applications"]["kfp-viz"]["units"]
#    url = units["kfp-viz/0"]["address"]
#    headers = {"kubeflow-userid": "user"}
#    result_status, result_text = await fetch_response(url=f"http://{url}:8888", headers=headers)
#
#    assert result_status == 200
#
#
## ---- Helpers
#async def fetch_response(url, headers, cookies: dict = None):
#    """Fetch provided URL and return pair - status and text (int, string)."""
#    result_status = 0
#    result_text = ""
#    async with aiohttp.ClientSession() as session:
#        async with session.get(url=url, headers=headers, cookies=cookies) as response:
#            result_status = response.status
#            result_text = await response.text()
#    return result_status, str(result_text)
#
#async def post_request(url, headers, data: str, cookies: dict = None):
#    """Make an HTTP POST request"."""
#    result_status = 0
#    result_text = ""
#    async with aiohttp.ClientSession() as session:
#        async with session.post(url=url, data=data, headers=headers, cookies=cookies) as response:
#            result_status = response.status
#            result_text = await response.text()
#    return result_status, str(result_text)
#
#def apply_viewer(lightkube_client: lightkube.Client):
#    """Apply a sample Viewer and remove it after test case execution.
#
#        Args:
#            lightkube_client (lightkube.Client): the lightkube Client that talks to the K8s API.
#        Returns:
#            A Viewer object and its class.
#    """
#    # Create a Viewer namespaced resource
#    viewer_class_resource = create_namespaced_resource(
#        group="kubeflow.org", version="v1beta1", kind="Viewer", plural="viewers"
#    )
#
#    # Apply viewer
#    viewer_yaml = Path(SAMPLE_VIEWER).read_text()
#    viewer_yaml_loaded = codecs.load_all_yaml(viewer_yaml)
#    for viewer_obj in viewer_yaml_loaded:
#        try:
#            lightkube_client.apply(
#                obj=viewer_obj,
#                name=viewer_obj.metadata.name,
#                namespace=viewer_obj.metadata.namespace,
#            )
#        except lightkube.core.exceptions.ApiError as e:
#            raise e
#    return viewer_obj, viewer_class_resource
