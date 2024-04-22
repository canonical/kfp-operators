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

import kfp
import lightkube
import pytest
import tenacity
from lightkube import codecs
from lightkube.generic_resource import create_namespaced_resource
from lightkube.resources.apps_v1 import Deployment
from pytest_operator.plugin import OpsTest

KFP_SDK_VERSION = "v2"
log = logging.getLogger(__name__)


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
