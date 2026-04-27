# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
from pathlib import Path

import pytest
import yaml
from charmed_kubeflow_chisme.testing import (
    GRAFANA_AGENT_APP,
    assert_alert_rules,
    assert_logging,
    assert_metrics_endpoint,
    assert_security_context,
    deploy_and_assert_grafana_agent,
    generate_container_securitycontext_map,
    get_alert_rules,
    get_pod_names,
)
from charms_dependencies import KFP_DB, KFP_VIZ, MINIO
from lightkube import Client
from pytest_operator.plugin import OpsTest

logger = logging.getLogger(__name__)

METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())
APP_NAME = METADATA["name"]
CONTAINERS_SECURITY_CONTEXT_MAP = generate_container_securitycontext_map(METADATA)
KFP_DB_APPLICATION_NAME = "kfp-db"


@pytest.fixture(scope="session")
def lightkube_client() -> Client:
    client = Client(field_manager=APP_NAME)
    return client


@pytest.mark.abort_on_fail
async def test_build_and_deploy(ops_test: OpsTest, request: pytest.FixtureRequest):
    """Deploy kfp-api with required charms and relations."""

    image_path = METADATA["resources"]["oci-image"]["upstream-source"]
    resources = {"oci-image": image_path}
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

    # FIXME: we should probably stop deploying mariadb as:
    # 1) The team has accepted and started using mysql-k8s more extensively
    # 2) The repository level integration tests use mysql-k8s only
    await ops_test.model.deploy(
        entity_url=KFP_DB.charm,
        application_name=KFP_DB_APPLICATION_NAME,
        config=KFP_DB.config,
        channel=KFP_DB.channel,
        trust=KFP_DB.trust,
    )
    await ops_test.model.deploy(
        entity_url=MINIO.charm, config=MINIO.config, channel=MINIO.channel, trust=MINIO.trust
    )
    await ops_test.model.deploy(
        entity_url=KFP_VIZ.charm, channel=KFP_VIZ.channel, trust=KFP_VIZ.trust
    )

    # FIXME: This assertion belongs to unit tests
    # test no database relation, charm should be in blocked state
    # assert ops_test.model.applications[APP_NAME].units[0].workload_status == "blocked"

    await ops_test.model.add_relation(f"{APP_NAME}:mysql", f"{KFP_DB_APPLICATION_NAME}:mysql")
    await ops_test.model.add_relation(
        f"{APP_NAME}:object-storage", f"{MINIO.charm}:object-storage"
    )
    await ops_test.model.add_relation(f"{APP_NAME}:kfp-viz", f"{KFP_VIZ.charm}:kfp-viz")

    await ops_test.model.wait_for_idle(
        apps=[APP_NAME, KFP_VIZ.charm, KFP_DB_APPLICATION_NAME, MINIO.charm],
        status="active",
        raise_on_blocked=False,
        raise_on_error=False,
        timeout=90 * 20,
    )

    # Deploying grafana-agent-k8s and add all relations
    await deploy_and_assert_grafana_agent(
        ops_test.model, APP_NAME, metrics=True, dashboard=True, logging=True
    )


async def test_alert_rules(ops_test: OpsTest):
    """Test check charm alert rules and rules defined in relation data bag."""
    app = ops_test.model.applications[APP_NAME]
    alert_rules = get_alert_rules()
    logger.info("found alert_rules: %s", alert_rules)
    await assert_alert_rules(app, alert_rules)


async def test_metrics_endpoint(ops_test: OpsTest):
    """Test metrics_endpoints are defined in relation data bag and their accessibility.

    This function gets all the metrics_endpoints from the relation data bag, checks if
    they are available from the grafana-agent-k8s charm and finally compares them with the
    ones provided to the function.
    """
    app = ops_test.model.applications[APP_NAME]
    await assert_metrics_endpoint(app, metrics_port=8888, metrics_path="/metrics")


async def test_logging(ops_test: OpsTest):
    """Test logging is defined in relation data bag."""
    app = ops_test.model.applications[GRAFANA_AGENT_APP]
    await assert_logging(app)


@pytest.mark.parametrize("container_name", list(CONTAINERS_SECURITY_CONTEXT_MAP.keys()))
async def test_container_security_context(
    ops_test: OpsTest,
    lightkube_client: Client,
    container_name: str,
):
    """Test container security context is correctly set.

    Verify that container spec defines the security context with correct
    user ID and group ID.
    """
    pod_name = get_pod_names(ops_test.model.name, APP_NAME)[0]
    assert_security_context(
        lightkube_client,
        pod_name,
        container_name,
        CONTAINERS_SECURITY_CONTEXT_MAP,
        ops_test.model.name,
    )


async def test_remove_application(ops_test: OpsTest):
    """Test that the application can be removed successfully."""
    await ops_test.model.remove_application(app_name=APP_NAME, block_until_done=True)
    assert APP_NAME not in ops_test.model.applications
