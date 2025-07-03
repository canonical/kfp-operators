# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
from pathlib import Path

import pytest
import yaml
from charmed_kubeflow_chisme.testing import (
    GRAFANA_AGENT_APP,
    assert_logging,
    deploy_and_assert_grafana_agent,
)
from pytest_operator.plugin import OpsTest

METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())
CHARM_ROOT = "."
APP_NAME = METADATA["name"]

log = logging.getLogger(__name__)


@pytest.mark.abort_on_fail
async def test_build_and_deploy_with_relations(ops_test: OpsTest, request):
    image_path = METADATA["resources"]["kfp-viewer-image"]["upstream-source"]
    resources = {"kfp-viewer-image": image_path}
    # Keep the option to run the integration tests locally
    # by building the charm and then deploying
    entity_url = (
        await ops_test.build_charm("./")
        if not (entity_url := request.config.getoption("--charm-path"))
        else entity_url
    )

    await ops_test.model.deploy(
        entity_url=entity_url,
        application_name=APP_NAME,
        resources=resources,
        trust=True,
    )

    await ops_test.model.wait_for_idle(
        apps=[APP_NAME],
        status="active",
        raise_on_blocked=False,
        raise_on_error=False,
        timeout=10 * 60,
    )

    # Deploying grafana-agent-k8s and add all relations
    await deploy_and_assert_grafana_agent(
        ops_test.model, APP_NAME, metrics=False, logging=True, dashboard=False
    )


async def test_logging(ops_test):
    """Test logging is defined in relation data bag."""
    app = ops_test.model.applications[GRAFANA_AGENT_APP]
    await assert_logging(app)
