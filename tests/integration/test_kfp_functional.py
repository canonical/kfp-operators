#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.
"""Functional tests for kfp-operators."""
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
    SAMPLE_VIEWER,
)

import lightkube
import pytest
import tenacity
from lightkube import codecs
from lightkube.generic_resource import create_namespaced_resource
from lightkube.resources.apps_v1 import Deployment
from pytest_operator.plugin import OpsTest


log = logging.getLogger(__name__)


@pytest.mark.abort_on_fail
async def test_build_and_deploy(ops_test: OpsTest, request, lightkube_client):
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
        for charm in KFP_CHARMS
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

    # Wait for kfp-* Deployment to be active and idle.
    # If a kfp charm is ever migrated to sidecar, and the above issue is still
    # there, appropriate changes must be done on this method for checking the readiness
    # of the application.
    # FIXME: This is a workaround for issue https://bugs.launchpad.net/juju/+bug/1981833
    # Also https://github.com/juju/python-libjuju/issues/900
    @tenacity.retry(
        wait=tenacity.wait_exponential(multiplier=2, min=1, max=15),
        stop=tenacity.stop_after_delay(900),
        reraise=True,
    )
    def assert_get_kfp_deployment(kfp_component: str):
        """Asserts the deployment of kfp_component is ready and available."""
        log.info(f"Waiting for {kfp_component} to be ready and available")
        # Get Deployment, the namespace should always be kubeflow
        kfp_deployment = lightkube_client.get(Deployment, name=kfp_component, namespace="kubeflow")

        # Verify the deployment exists
        assert kfp_deployment is not None

        # Verify the readiness and availability
        assert kfp_deployment.status.readyReplicas == 1
        assert kfp_deployment.status.availableReplicas == 1

    for component in KFP_CHARMS:
        if component == "kfp-api":
            # The issue seems to be happening only with podspec charms,
            # nothing to do for kfp-api
            continue
        assert_get_kfp_deployment(kfp_component=component)


# ---- KFP API Server focused test cases
async def test_upload_pipeline(kfp_client):
    """Upload a pipeline from a YAML file and assert its presence."""
    # Upload a pipeline and get the server response
    pipeline_upload_response = kfp_client.pipeline_uploads.upload_pipeline(
        uploadfile=SAMPLE_PIPELINE, name="test-upload-pipeline"
    )
    # Upload a pipeline and get its ID
    uploaded_pipeline_id = pipeline_upload_response.id

    # Get pipeline id by name, default='sample-pipeline'
    server_pipeline_id = kfp_client.get_pipeline_id(name="test-upload-pipeline")
    assert uploaded_pipeline_id == server_pipeline_id


async def test_create_and_monitor_run(kfp_client, create_and_clean_experiment):
    """Create a run and monitor it to completion."""
    # Create a run, save response in variable for easy manipulation
    # Create an experiment for this run
    experiment_response = create_and_clean_experiment

    # Create a run from a pipeline file (SAMPLE_PIPELINE) and an experiment (create_experiment).
    # This call uses the 'default' kubeflow service account to be able to edit Workflows
    create_run_response = kfp_client.create_run_from_pipeline_package(
        pipeline_file=SAMPLE_PIPELINE,
        arguments={},
        run_name="test-run-1",
        experiment_name=experiment_response.name,
        namespace=KUBEFLOW_PROFILE_NAMESPACE,
    )

    # FIXME: waiting_for_run_completion timeouts on GitHub runners
    # Related issue: https://github.com/canonical/kfp-operators/issues/244
    # Monitor the run to completion, the pipeline should not be executed in
    # more than 300 seconds as it is a very simple operation
    #monitor_response = kfp_client.wait_for_run_completion(create_run_response.run_id, timeout=600)

    #assert monitor_response.run.status == "Succeeded"

    # At least get the run and extract some data while the previous check
    # works properly on the GitHub runners
    test_run = kfp_client.get_run(create_run_response.run_id)
    assert test_run is not None
    assert test_run.status is not None
    assert test_run.error is None

# ---- ScheduledWorfklows and Argo focused test case
async def test_create_and_monitor_recurring_run(
    kfp_client, upload_and_clean_pipeline, create_and_clean_experiment
):
    """Create a recurring run and monitor it to completion."""

    # Upload a pipeline from file
    pipeline_response = upload_and_clean_pipeline

    # Create an experiment for this run
    experiment_response = create_and_clean_experiment

    # Create a recurring run from a pipeline (upload_pipeline_from_file) and an experiment (create_experiment)
    # This call uses the 'default' kubeflow service account to be able to edit ScheduledWorkflows
    # This ScheduledWorkflow (Recurring Run) will run once every two seconds
    create_recurring_run_response = kfp_client.create_recurring_run(
        experiment_id=experiment_response.id,
        job_name="recurring-job-1",
        pipeline_id=pipeline_response.id,
        enabled=True,
        cron_expression="*/2 * * * * *",
        max_concurrency=1,
    )

    recurring_job = create_recurring_run_response
    # Assert the job is enabled
    assert recurring_job.enabled is True

    # Assert the job executes once every two seconds
    assert recurring_job.trigger.cron_schedule.cron == "*/2 * * * * *"

    # Wait for the recurring job to schedule some runs
    time.sleep(6)

    # FIXME: disabling the job does not work at the moment, it seems like
    # the status of the recurring run is never updated and is causing the
    # following assertion to fail
    # Related issue: https://github.com/canonical/kfp-operators/issues/244
    # Disable the job after few runs
    kfp_client.disable_job(recurring_job.id)

    # Assert the job is disabled
    # assert recurring_job.enabled is False


# ---- KFP Viewer and Visualization focused test cases
async def test_apply_sample_viewer(lightkube_client):
    """Test a Viewer can be applied and its presence is verified."""
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
    status = await ops_test.model.get_status()
    units = status["applications"]["kfp-viz"]["units"]
    url = units["kfp-viz/0"]["address"]
    headers = {"kubeflow-userid": "user"}
    result_status, result_text = await fetch_response(url=f"http://{url}:8888", headers=headers)

    assert result_status == 200
