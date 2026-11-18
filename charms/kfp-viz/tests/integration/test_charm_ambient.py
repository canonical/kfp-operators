# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
from pathlib import Path

import pytest
import yaml
from charmed_kubeflow_chisme.testing import (
    GRAFANA_AGENT_APP,
    ISTIO_BEACON_K8S_APP,
    ISTIO_INGRESS_K8S_APP,
    ISTIO_K8S_APP,
    assert_logging,
    assert_security_context,
    deploy_and_assert_grafana_agent,
    generate_container_securitycontext_map,
    get_pod_names,
    integrate_with_service_mesh,
)
from lightkube import Client
from pytest_operator.plugin import OpsTest

METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())
CHARM_ROOT = "."
APP_NAME = METADATA["name"]
CONTAINERS_SECURITY_CONTEXT_MAP = generate_container_securitycontext_map(METADATA)
ISTIO_CHANNEL = "1.31/stable"

log = logging.getLogger(__name__)


@pytest.fixture(scope="session")
def lightkube_client() -> Client:
    client = Client(field_manager=APP_NAME)
    return client


async def deploy_istio_charms(ops_test: OpsTest, model_on_mesh: bool = True):
    """Deploy the Istio charms with the Juju CLI; python-libjuju can't deploy Ubuntu 26.04."""
    for charm, options in (
        (ISTIO_K8S_APP, ("--config", "platform=")),
        (ISTIO_INGRESS_K8S_APP, ()),
        (ISTIO_BEACON_K8S_APP, ("--config", f"model-on-mesh={str(model_on_mesh).lower()}")),
    ):
        await ops_test.juju(
            "deploy", charm, "--channel", ISTIO_CHANNEL, "--trust", *options, check=True
        )
        await ops_test.model.wait_for_idle(
            apps=[charm], status="active", raise_on_error=False, timeout=60 * 15
        )


@pytest.mark.abort_on_fail
async def test_build_and_deploy_with_relations(ops_test: OpsTest, request: pytest.FixtureRequest):
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

    await deploy_istio_charms(ops_test)
    await integrate_with_service_mesh(
        APP_NAME, ops_test.model, relate_to_ingress_route_endpoint=False
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
