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
BUNDLE = Path(__file__).parent / "bundle.yaml"
APP_NAME = "kfp-ui"

log = logging.getLogger(__name__)


@pytest.mark.abort_on_fail
async def test_build_and_deploy_with_relations(ops_test: OpsTest):
    image_path = METADATA["resources"]["ml-pipeline-ui"]["upstream-source"]
    resources = {"ml-pipeline-ui": image_path}

    await ops_test.model.deploy(
        entity_url="/tmp/charms/kfp-ui/kfp-ui_ubuntu-20.04-amd64.charm", application_name=APP_NAME, resources=resources, trust=True
    )
    await ops_test.model.deploy(BUNDLE, trust=True)
    await ops_test.model.integrate(f"{APP_NAME}:kfp-api", "kfp-api:kfp-api")
    await ops_test.model.integrate(f"{APP_NAME}:object-storage", "minio:object-storage")

    await ops_test.model.wait_for_idle(
        status="active",
        raise_on_blocked=False,
        raise_on_error=False,
        timeout=60 * 10,
    )

    # Deploying grafana-agent-k8s and add all relations
    await deploy_and_assert_grafana_agent(
        ops_test.model, APP_NAME, metrics=False, logging=True, dashboard=False
    )


async def test_logging(ops_test):
    """Test logging is defined in relation data bag."""
    app = ops_test.model.applications[GRAFANA_AGENT_APP]
    await assert_logging(app)
