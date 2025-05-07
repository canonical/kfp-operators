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
    generate_context_from_charm_spec_list,
)
from charms_dependencies import KFP_API, KFP_VIZ, MINIO, MYSQL_K8S
from pytest_operator.plugin import OpsTest

METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())
CHARM_ROOT = "."
BUNDLE_PATH = Path(__file__).parent / "bundle.yaml.j2"
APP_NAME = METADATA["name"]
charms_dependencies_list = [KFP_API, KFP_VIZ, MINIO, MYSQL_K8S]
log = logging.getLogger(__name__)


@pytest.mark.abort_on_fail
async def test_build_and_deploy_with_relations(ops_test: OpsTest, request):
    image_path = METADATA["resources"]["ml-pipeline-ui"]["upstream-source"]
    resources = {"ml-pipeline-ui": image_path}
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
    context = generate_context_from_charm_spec_list(charms_dependencies_list)
    rendered_bundle = ops_test.render_bundle(BUNDLE_PATH, context)
    await ops_test.model.deploy(rendered_bundle, trust=True)
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
