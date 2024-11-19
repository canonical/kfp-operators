#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.
"""Functional tests for kfp-operators with the KFP SDK v2."""
import logging
import time
from pathlib import Path

from helpers.bundle_mgmt import render_bundle, deploy_bundle
from helpers.k8s_resources import apply_manifests, fetch_response
from helpers.localize_bundle import get_resources_from_charm_file
from kfp_globals import (
    CHARM_PATH_TEMPLATE,
    KFP_CHARMS,
    KUBEFLOW_PROFILE_NAMESPACE,
    SAMPLE_PIPELINE,
    SAMPLE_PIPELINE_NAME,
    SAMPLE_VIEWER,
)

import json
import kfp
import lightkube
import pytest
import sh
import tenacity
from lightkube import codecs
from lightkube.generic_resource import create_namespaced_resource
from lightkube.resources.apps_v1 import Deployment
from pytest_operator.plugin import OpsTest
import jq

KFP_SDK_VERSION = "v2"
log = logging.getLogger(__name__)


# ---- KFP SDK V2 fixtures
@pytest.fixture(scope="function")
def upload_and_clean_pipeline_v2(kfp_client: kfp.Client):
    """Upload an arbitrary v2 pipeline and remove after test case execution."""
    pipeline_upload_response = kfp_client.pipeline_uploads.upload_pipeline(
        uploadfile=SAMPLE_PIPELINE[KFP_SDK_VERSION], name=SAMPLE_PIPELINE_NAME
    )
    # The newer pipelines backend requires the deletion of the pipelines versions
    # before we can actually remove the pipeline. This variable extracts the pipeline
    # version id that can be used to remove it later in the test exectution.
    pipeline_version_id = (
        kfp_client.list_pipeline_versions(pipeline_upload_response.pipeline_id)
        .pipeline_versions[0]
        .pipeline_version_id
    )

    yield pipeline_upload_response, pipeline_version_id

    kfp_client.delete_pipeline_version(pipeline_upload_response.pipeline_id, pipeline_version_id)
    kfp_client.delete_pipeline(pipeline_upload_response.pipeline_id)


@pytest.fixture(scope="function")
def create_and_clean_experiment_v2(kfp_client: kfp.Client):
    """Create an experiment and remove after test case execution."""
    experiment_response = kfp_client.create_experiment(
        name="test-experiment", namespace=KUBEFLOW_PROFILE_NAMESPACE
    )

    yield experiment_response

    kfp_client.delete_experiment(experiment_id=experiment_response.experiment_id)


@pytest.mark.abort_on_fail
async def test_build_and_deploy(ops_test: OpsTest, request, lightkube_client):
    """Build and deploy kfp-operators charms."""
    no_build = request.config.getoption("no_build")

    # Immediately raise an error if the model name is not kubeflow
    if ops_test.model_name != "kubeflow":
        raise ValueError("kfp must be deployed to namespace kubeflow")

    # Get/load template bundle from command line args
    bundlefile_path = Path(request.config.getoption("bundle"))
    basedir = Path("./").absolute()

    # Build the charms we need to build only if --no-build is not set
    context = {}
    if not no_build:
        charms_to_build = {
            charm: Path(CHARM_PATH_TEMPLATE.format(basedir=str(basedir), charm=charm))
            for charm in KFP_CHARMS
        }
        log.info(f"Building charms for: {charms_to_build}")
        built_charms = await ops_test.build_charms(*charms_to_build.values())
        log.info(f"Built charms: {built_charms}")

        for charm, charm_file in built_charms.items():
            charm_resources = get_resources_from_charm_file(charm_file)
            context.update([(f"{charm.replace('-', '_')}_resources", charm_resources)])
            context.update([(f"{charm.replace('-', '_')}", charm_file)])

    # Render kfp-operators bundle file with locally built charms and their resources
    rendered_bundle = render_bundle(
        ops_test, bundle_path=bundlefile_path, context=context, no_build=no_build
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
        timeout=3600,
        idle_period=30,
    )
    juju_status = sh.juju.status(format="json", no_color=True, model="kubeflow")
    print("###########################")
    print("juju_status:")
    print(juju_status)
    status = await ops_test.model.get_status()
    print("###########################")
    print("ops_test.model.get_status()")
    print(status)

    # Delete lxc instances once deployment is succesful
    # Based on https://discourse.charmhub.io/t/how-to-quickly-clean-unused-lxd-instances-from-charmcraft-pack/15975
    lxc_instances = sh.lxc.list(project="charmcraft", format="json")
    lxc_instances_charmcraft = jq.compile('.[] | select(.name | startswith("charmcraft-")) | .name').input_text(lxc_instances).all()
    for instance in lxc_instances_charmcraft:
        print(f"Deleting {instance}")
        sh.lxc.delete(instance, project="charmcraft")


# ---- KFP API Server focused test cases
async def test_upload_pipeline(kfp_client):
    """Upload a pipeline from a YAML file and assert its presence."""
    df = sh.df("-h")
    print("df -h before test_upload_pipeline")
    print(df)
    # Upload a pipeline and get the server response
    pipeline_name = f"test-pipeline-sdk-{KFP_SDK_VERSION}"
    pipeline_upload_response = kfp_client.pipeline_uploads.upload_pipeline(
        uploadfile=SAMPLE_PIPELINE[KFP_SDK_VERSION],
        name=pipeline_name,
    )
    # Upload a pipeline and get its ID
    uploaded_pipeline_id = pipeline_upload_response.pipeline_id

    # Get pipeline id by name, default='sample-pipeline'
    server_pipeline_id = kfp_client.get_pipeline_id(name=pipeline_name)
    assert uploaded_pipeline_id == server_pipeline_id


async def test_create_and_monitor_run(kfp_client, create_and_clean_experiment_v2):
    """Create a run and monitor it to completion."""
    df = sh.df("-h")
    print("df -h before test_create_and_monitor_run")
    print(df)
    # Create a run, save response in variable for easy manipulation
    # Create an experiment for this run
    experiment_response = create_and_clean_experiment_v2

    # Create a run from a pipeline file (SAMPLE_PIPELINE) and an experiment (create_experiment).
    # This call uses the 'default' kubeflow service account to be able to edit Workflows
    create_run_response = kfp_client.create_run_from_pipeline_package(
        pipeline_file=SAMPLE_PIPELINE[KFP_SDK_VERSION],
        arguments={},
        run_name=f"test-run-sdk-{KFP_SDK_VERSION}",
        experiment_name=experiment_response.display_name,
        namespace=KUBEFLOW_PROFILE_NAMESPACE,
    )

    # Monitor the run to completion, the pipeline should not be executed in
    # more than 300 seconds as it is a very simple operation
    monitor_response = kfp_client.wait_for_run_completion(create_run_response.run_id, timeout=600)

    assert monitor_response.state == "SUCCEEDED"


# ---- ScheduledWorfklows and Argo focused test case
async def test_create_and_monitor_recurring_run(
    kfp_client, upload_and_clean_pipeline_v2, create_and_clean_experiment_v2
):
    """Create a recurring run and monitor it to completion."""
    df = sh.df("-h")
    print("df -h before test_create_and_monitor_recurring_run")
    print(df)
    # Upload a pipeline from file
    pipeline_response, pipeline_version_id = upload_and_clean_pipeline_v2

    # Create an experiment for this run
    experiment_response = create_and_clean_experiment_v2

    # Create a recurring run from a pipeline (upload_pipeline_from_file) and an experiment (create_experiment)
    # This call uses the 'default' kubeflow service account to be able to edit ScheduledWorkflows
    # This ScheduledWorkflow (Recurring Run) will run once every two seconds
    create_recurring_run_response = kfp_client.create_recurring_run(
        experiment_id=experiment_response.experiment_id,
        job_name=f"recurring-job-{KFP_SDK_VERSION}",
        pipeline_id=pipeline_response.pipeline_id,
        version_id=pipeline_version_id,
        enabled=True,
        cron_expression="*/2 * * * * *",
        max_concurrency=1,
    )

    recurring_job = create_recurring_run_response

    # Assert the job is enabled
    assert recurring_job.status == "ENABLED"

    # Assert the job executes once every two seconds
    assert recurring_job.trigger.cron_schedule.cron == "*/2 * * * * *"

    # Wait for the recurring job to schedule some runs
    time.sleep(20)

    first_run = kfp_client.list_runs(experiment_id=experiment_response.experiment_id,
                                          namespace=KUBEFLOW_PROFILE_NAMESPACE).runs[0]

    # Assert that a run has been created from the recurring job
    assert first_run.recurring_run_id == recurring_job.recurring_run_id

    # Monitor the run to completion, the pipeline should not be executed in
    # more than 300 seconds as it is a very simple operation
    monitor_response = kfp_client.wait_for_run_completion(first_run.run_id, timeout=600)
    df = sh.df("-h")
    print("df -h before test_create_and_monitor_recurring_run ASSERT")
    print(df)
    assert monitor_response.state == "SUCCEEDED"

    # FIXME: disabling the job does not work at the moment, it seems like
    # the status of the recurring run is never updated and is causing the
    # following assertion to fail
    # Related issue: https://github.com/canonical/kfp-operators/issues/244
    # Disable the job after few runs

    kfp_client.disable_recurring_run(recurring_job.recurring_run_id)

    # Assert the job is disabled
    # assert recurring_job.status is "DISABLED"


# ---- KFP Viewer and Visualization focused test cases
async def test_apply_sample_viewer(lightkube_client):
    """Test a Viewer can be applied and its presence is verified."""
    df = sh.df("-h")
    print("df -h before test_apply_sample_viewer")
    print(df)
    # Create a Viewer namespaced resource
    viewer_class_resource = create_namespaced_resource(
        group="kubeflow.org", version="v1beta1", kind="Viewer", plural="viewers"
    )

    # Apply viewer
    viewer_object = apply_manifests(lightkube_client, yaml_file_path=SAMPLE_VIEWER)

    viewer = lightkube_client.get(
        res=viewer_class_resource,
        name=viewer_object.metadata.name,
        namespace=viewer_object.metadata.namespace,
    )
    assert viewer is not None


async def test_viz_server_healthcheck(ops_test: OpsTest):
    """Run a healthcheck on the server endpoint."""
    df = sh.df("-h")
    print("df -h before test_viz_server_healthcheck")
    print(df)
    # This is a workaround for canonical/kfp-operators#549
    # Leave model=kubeflow as this test case
    # should always be executed on that model
    juju_status = sh.juju.status(format="json", no_color=True, model="kubeflow")
    kfp_viz_unit = json.loads(juju_status)["applications"]["kfp-viz"]["units"]["kfp-viz/0"]
    url = kfp_viz_unit["address"]

    headers = {"kubeflow-userid": "user"}
    result_status, result_text = await fetch_response(url=f"http://{url}:8888", headers=headers)

    assert result_status == 200
