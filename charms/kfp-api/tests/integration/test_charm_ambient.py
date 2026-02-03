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
    deploy_and_integrate_service_mesh_charms,
    generate_container_securitycontext_map,
    get_alert_rules,
    get_pod_names,
    integrate_with_service_mesh,
)
from charms_dependencies import KFP_SCHEDWF, KFP_VIZ, MINIO, MYSQL
from lightkube import Client
from lightkube_extensions.types import AuthorizationPolicy
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

    # Deploy service mesh charms and add all relations
    await deploy_and_integrate_service_mesh_charms(
        APP_NAME, ops_test.model, relate_to_ingress_route_endpoint=False, model_on_mesh=False
    )

    await ops_test.model.deploy(
        entity_url=MYSQL.charm,
        application_name=KFP_DB_APPLICATION_NAME,
        config=MYSQL.config,
        channel=MYSQL.channel,
        trust=MYSQL.trust,
    )
    await ops_test.model.deploy(
        entity_url=MINIO.charm, config=MINIO.config, channel=MINIO.channel, trust=MINIO.trust
    )
    await ops_test.model.deploy(
        entity_url=KFP_VIZ.charm, channel=KFP_VIZ.channel, trust=KFP_VIZ.trust
    )

    await ops_test.model.deploy(
        entity_url=KFP_SCHEDWF.charm, channel=KFP_SCHEDWF.channel, trust=KFP_SCHEDWF.trust
    )

    await ops_test.model.add_relation(
        f"{APP_NAME}:relational-db", f"{KFP_DB_APPLICATION_NAME}:database"
    )
    await ops_test.model.add_relation(
        f"{APP_NAME}:object-storage", f"{MINIO.charm}:object-storage"
    )
    await ops_test.model.add_relation(f"{APP_NAME}:kfp-viz", f"{KFP_VIZ.charm}:kfp-viz")

    await ops_test.model.add_relation(
        f"{APP_NAME}:kfp-api-grpc", f"{KFP_SCHEDWF.charm}:kfp-api-grpc"
    )

    await integrate_with_service_mesh(
        KFP_VIZ.charm, ops_test.model, relate_to_ingress_route_endpoint=False
    )

    await integrate_with_service_mesh(
        KFP_SCHEDWF.charm, ops_test.model, relate_to_ingress_route_endpoint=False
    )

    await ops_test.model.wait_for_idle(
        status="active",
        raise_on_blocked=False,
        raise_on_error=False,
        timeout=90 * 20,
    )

    # Deploying grafana-agent-k8s and add all relations
    await deploy_and_assert_grafana_agent(
        ops_test.model, APP_NAME, metrics=True, dashboard=True, logging=True
    )

    await ops_test.model.wait_for_idle(
        apps=[APP_NAME],
        status="active",
        raise_on_blocked=False,
        raise_on_error=False,
        timeout=90 * 20,
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
    # Set model-on-mesh to true temporarily to include grafana-agent-k8s in the service mesh
    # and be able to access the metrics endpoint since it can't relate to be beacon.
    # NOTE: This is a workaround until we replace grafana-agent-k8s with otel-collector-k8s
    # See https://github.com/canonical/charmed-kubeflow-chisme/issues/182.
    await ops_test.model.applications["istio-beacon-k8s"].set_config({"model-on-mesh": "true"})
    await ops_test.model.wait_for_idle(
        apps=["istio-beacon-k8s"],
        raise_on_blocked=False,
        raise_on_error=False,
        timeout=90 * 20,
    )
    app = ops_test.model.applications[APP_NAME]
    await assert_metrics_endpoint(app, metrics_port=8888, metrics_path="/metrics")
    await ops_test.model.applications["istio-beacon-k8s"].set_config({"model-on-mesh": "false"})


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


async def test_authorization_policy_waypoint_accepted(ops_test: OpsTest, lightkube_client: Client):
    """Test that the authorization policy has WaypointAccepted status and reason condition."""
    namespace = ops_test.model.name
    policy_name = f"{APP_NAME}-allow-without-kubeflow-header"

    # Retrieve the authorization policy
    policy = lightkube_client.get(AuthorizationPolicy, name=policy_name, namespace=namespace)

    # Verify the policy has the expected status conditions
    assert policy.status is not None, "Authorization policy status is missing"
    conditions = policy.status.get("conditions", [])
    assert len(conditions) > 0, "No status conditions found"

    # Find the WaypointAccepted condition
    waypoint_condition = None
    for condition in conditions:
        if condition.get("type") == "WaypointAccepted":
            waypoint_condition = condition
            break

    assert waypoint_condition is not None, "WaypointAccepted condition not found"
    assert waypoint_condition.get("status") == "True", "WaypointAccepted status is not True"
    assert waypoint_condition.get("reason") == "Accepted", "Reason is not 'Accepted'"


async def test_remove_application(ops_test: OpsTest):
    """Test that the application can be removed successfully."""
    await ops_test.model.remove_application(app_name=APP_NAME, block_until_done=True)
    assert APP_NAME not in ops_test.model.applications
