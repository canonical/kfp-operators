#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.
"""Functional tests for kfp-operators with the KFP SDK v1."""
import logging
import time
from pathlib import Path

from helpers.bundle_mgmt import render_bundle, deploy_bundle
from helpers.k8s_resources import apply_manifests, fetch_response
from helpers.localize_bundle import update_charm_context
from helpers.charmcraft import charmcraft_clean
from kfp_globals import (
    CHARM_PATH_TEMPLATE,
    KFP_CHARMS,
    KUBEFLOW_PROFILE_NAMESPACE,
    SAMPLE_PIPELINE,
    SAMPLE_PIPELINE_NAME,
    SAMPLE_VIEWER,
)

import sh
import kfp
import lightkube
import pytest
import tenacity
from lightkube import codecs
from lightkube.generic_resource import create_namespaced_resource
from lightkube.resources.apps_v1 import Deployment
from pytest_operator.plugin import OpsTest


KFP_SDK_VERSION = "v1"
log = logging.getLogger(__name__)


# ---- KFP SDK V1 fixtures
@pytest.fixture(scope="function")
def upload_and_clean_pipeline_v1(kfp_client: kfp.Client):
    """Upload an arbitrary pipeline and remove after test case execution."""
    pipeline_upload_response = kfp_client.pipeline_uploads.upload_pipeline(
        uploadfile=SAMPLE_PIPELINE[KFP_SDK_VERSION], name=SAMPLE_PIPELINE_NAME
    )
    # The newer pipelines backend requires the deletion of the pipelines versions
    # before we can actually remove the pipeline. This variable extracts the pipeline
    # version id that can be used to remove it later in the test exectution.
    pipeline_version_id = (
        kfp_client.list_pipeline_versions(pipeline_upload_response.id).versions[0].id
    )

    yield pipeline_upload_response

    kfp_client.delete_pipeline_version(pipeline_version_id)
    kfp_client.delete_pipeline(pipeline_id=pipeline_upload_response.id)


@pytest.fixture(scope="function")
def create_and_clean_experiment_v1(kfp_client: kfp.Client):
    """Create an experiment and remove after test case execution."""
    experiment_response = kfp_client.create_experiment(
        name="test-experiment", namespace=KUBEFLOW_PROFILE_NAMESPACE
    )

    yield experiment_response

    kfp_client.delete_experiment(experiment_id=experiment_response.id)


@pytest.mark.abort_on_fail
async def test_build_and_deploy(ops_test: OpsTest, request, lightkube_client):
    """Build and deploy kfp-operators charms."""
    charmcraft_clean_flag = True if request.config.getoption("--charmcraft-clean") else False

    # Immediately raise an error if the model name is not kubeflow
    if ops_test.model_name != "kubeflow":
        raise ValueError("kfp must be deployed to namespace kubeflow")

    # Get/load template bundle from command line args
    bundlefile_path = Path(request.config.getoption("bundle"))
    basedir = Path("./").absolute()

    context = {}

    # Find charms in the expected path if `--charms-path` is passed
    if charms_path := request.config.getoption("--charms-path"):
        for charm in KFP_CHARMS:
            # NOTE: The full path for the charm is hardcoded here. It relies on the downloaded
            # artifacts having the format below and existing in the exact path under `charms_path`.
            cached_charm = f"{charms_path}/{charm}/{charm}_ubuntu@20.04-amd64.charm"
            update_charm_context(context, charm, cached_charm)
    # Otherwise build the charms with ops_test
    else:
        charms_to_build = {
            charm: Path(CHARM_PATH_TEMPLATE.format(basedir=str(basedir), charm=charm))
            for charm in KFP_CHARMS
        }
        log.info(f"Building charms for: {charms_to_build}")
        
        # Build charms sequentially
        for charm_name, charm_path in charms_to_build.items():
            log.info(f" Building charm {charm_name}")
            built_charm = await ops_test.build_charm(charm_path)
            update_charm_context(context, charm_name, built_charm)

        if charmcraft_clean_flag == True:
            charmcraft_clean(charms_to_build)

    # Render kfp-operators bundle file with locally built charms and their resources
    rendered_bundle = render_bundle(
        ops_test, bundle_path=bundlefile_path, context=context
    )

    # Deploy the kfp-operators bundle from the rendered bundle file
    await deploy_bundle(ops_test, bundle_path=rendered_bundle, trust=True)

    # Use `juju wait-for` instead of `wait_for_idle()`
    # due to https://github.com/canonical/kfp-operators/issues/601
    # and https://github.com/juju/python-libjuju/issues/1204
    # Also check status of the unit instead of application due to
    # https://github.com/juju/juju/issues/18625
    log.info("Waiting on model applications to be active")
    sh.juju("wait-for","model","kubeflow", query="forEach(units, unit => unit.workload-status == 'active')", timeout="30m")

# ---- KFP API Server focused test cases
async def test_upload_pipeline(kfp_client):
    """Upload a pipeline from a YAML file and assert its presence."""
    # Upload a pipeline and get the server response
    pipeline_name = f"test-pipeline-sdk-{KFP_SDK_VERSION}"
    pipeline_upload_response = kfp_client.pipeline_uploads.upload_pipeline(
        uploadfile=SAMPLE_PIPELINE[KFP_SDK_VERSION],
        name=pipeline_name,
    )
    # Upload a pipeline and get its ID
    uploaded_pipeline_id = pipeline_upload_response.id

    # Get pipeline id by name, default='sample-pipeline'
    server_pipeline_id = kfp_client.get_pipeline_id(name=pipeline_name)
    assert uploaded_pipeline_id == server_pipeline_id


async def test_create_and_monitor_run(kfp_client, create_and_clean_experiment_v1):
    """Create a run and monitor it to completion."""
    # Create a run, save response in variable for easy manipulation
    # Create an experiment for this run
    experiment_response = create_and_clean_experiment_v1

    # Create a run from a pipeline file (SAMPLE_PIPELINE) and an experiment (create_experiment).
    # This call uses the 'default' kubeflow service account to be able to edit Workflows
    create_run_response = kfp_client.create_run_from_pipeline_package(
        pipeline_file=SAMPLE_PIPELINE[KFP_SDK_VERSION],
        arguments={},
        run_name=f"test-run-sdk-{KFP_SDK_VERSION}",
        experiment_name=experiment_response.name,
        namespace=KUBEFLOW_PROFILE_NAMESPACE,
    )

    # FIXME: waiting_for_run_completion timeouts on GitHub runners
    # Related issue: https://github.com/canonical/kfp-operators/issues/244
    # Monitor the run to completion, the pipeline should not be executed in
    # more than 300 seconds as it is a very simple operation
    # monitor_response = kfp_client.wait_for_run_completion(create_run_response.run_id, timeout=600)

    # assert monitor_response.run.status == "Succeeded"

    # At least get the run and extract some data while the previous check
    # works properly on the GitHub runners
    test_run = kfp_client.get_run(create_run_response.run_id).run
    assert test_run is not None


# ---- ScheduledWorfklows and Argo focused test case
async def test_create_and_monitor_recurring_run(
    kfp_client, upload_and_clean_pipeline_v1, create_and_clean_experiment_v1
):
    """Create a recurring run and monitor it to completion."""

    # Upload a pipeline from file
    pipeline_response = upload_and_clean_pipeline_v1

    # Create an experiment for this run
    experiment_response = create_and_clean_experiment_v1

    # Create a recurring run from a pipeline (upload_pipeline_from_file) and an experiment (create_experiment)
    # This call uses the 'default' kubeflow service account to be able to edit ScheduledWorkflows
    # This ScheduledWorkflow (Recurring Run) will run once every two seconds
    create_recurring_run_response = kfp_client.create_recurring_run(
        experiment_id=experiment_response.id,
        job_name=f"recurring-job-{KFP_SDK_VERSION}",
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
    time.sleep(20)

    first_run = kfp_client.list_runs(experiment_id=experiment_response.id,
                                          namespace=KUBEFLOW_PROFILE_NAMESPACE).runs[0]

    # Assert that a run has been created from the recurring job
    assert "recurring-job" in first_run.name

    # Monitor the run to completion, the pipeline should not be executed in
    # more than 300 seconds as it is a very simple operation
    monitor_response = kfp_client.wait_for_run_completion(first_run.id, timeout=300).run
    assert monitor_response.status == "Succeeded"

    # FIXME: disabling the job does not work at the moment, it seems like
    # the status of the recurring run is never updated and is causing the
    # following assertion to fail
    # Related issue: https://github.com/canonical/kfp-operators/issues/244
    # Disable the job after few runs
    kfp_client.disable_job(recurring_job.id)

    # Assert the job is disabled
    # assert recurring_job.enabled is False
