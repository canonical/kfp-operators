# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
import os
from pathlib import Path

import pytest
import yaml
from charmed_kubeflow_chisme.testing import (
    GRAFANA_AGENT_APP,
    assert_logging,
    deploy_and_assert_grafana_agent,
)
from pytest_operator.plugin import OpsTest
from utils import get_packed_charms

METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())
CHARM_ROOT = "."
APP_NAME = "kfp-viz"

log = logging.getLogger(__name__)


@pytest.fixture
def use_packed_charms() -> str:
    """Return environment variable `USE_PACKED_CHARMS`. If it's not found, return `false`."""
    return os.environ.get("USE_PACKED_CHARMS", "false").replace('"', "")


@pytest.mark.abort_on_fail
async def test_build_and_deploy_with_relations(ops_test: OpsTest, use_packed_charms):
    charm_path = "."
    if use_packed_charms.lower() == "true":
        built_charm_path = await get_packed_charms(charm_path)
    else:
        built_charm_path = await ops_test.build_charm(charm_path)
        log.info(f"Built charm {built_charm_path}")
    image_path = METADATA["resources"]["oci-image"]["upstream-source"]
    resources = {"oci-image": image_path}

    await ops_test.model.deploy(
        entity_url=built_charm_path, application_name=APP_NAME, resources=resources, trust=True
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
