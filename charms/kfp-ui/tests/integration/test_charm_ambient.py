# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
from pathlib import Path

import pytest
import tenacity
import yaml
from charmed_kubeflow_chisme.testing import (
    GRAFANA_AGENT_APP,
    ISTIO_INGRESS_K8S_APP,
    ISTIO_INGRESS_ROUTE_ENDPOINT,
    assert_logging,
    assert_path_reachable_through_ingress,
    assert_security_context,
    deploy_and_assert_grafana_agent,
    deploy_and_integrate_service_mesh_charms,
    generate_container_securitycontext_map,
    generate_context_from_charm_spec_list,
    get_pod_names,
    integrate_with_service_mesh,
)
from charms_dependencies import KFP_API, KFP_VIZ, MINIO, MYSQL_K8S
from lightkube import Client
from lightkube.generic_resource import create_namespaced_resource
from pytest_operator.plugin import OpsTest

METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())
CHARM_ROOT = "."
BUNDLE_PATH = Path(__file__).parent / "bundle.yaml.j2"
APP_NAME = METADATA["name"]
HTTP_PATH = "/pipeline"
CONTAINERS_SECURITY_CONTEXT_MAP = generate_container_securitycontext_map(METADATA)
charms_dependencies_list = [KFP_API, KFP_VIZ, MINIO, MYSQL_K8S]
log = logging.getLogger(__name__)

# A second istio-ingress-k8s instance used to verify multiple-ingress support.
SECOND_INGRESS_APP = "istio-ingress-k8s-alt"
INGRESS_CHANNEL = "2/stable"
# Name of the HTTPRoute submitted by kfp-ui (see AmbientIngressRequirerComponent).
INGRESS_ROUTE_NAME = "http-route"
# Gateway listener section for cleartext HTTP on port 80.
HTTP_SECTION_NAME = "http-80"
# Path matched by the kfp-ui HTTPRoute.
INGRESS_ROUTE_PATH = HTTP_PATH
# Gateway API generic resources, resolved at runtime via lightkube.
HTTPROUTE_RESOURCE = create_namespaced_resource(
    "gateway.networking.k8s.io", "v1", "HTTPRoute", "httproutes"
)
GATEWAY_RESOURCE = create_namespaced_resource(
    "gateway.networking.k8s.io", "v1", "Gateway", "gateways"
)
RETRY_120_SECONDS = tenacity.Retrying(
    stop=tenacity.stop_after_delay(120),
    wait=tenacity.wait_fixed(2),
    reraise=True,
)


@pytest.fixture(scope="session")
def lightkube_client() -> Client:
    client = Client(field_manager=APP_NAME)
    return client


@pytest.mark.abort_on_fail
async def test_build_and_deploy_with_relations(ops_test: OpsTest, request: pytest.FixtureRequest):
    image_path = METADATA["resources"]["ml-pipeline-ui"]["upstream-source"]
    resources = {"ml-pipeline-ui": image_path}
    # Keep the option to run the integration tests locally
    # by building the charm and then deploying
    entity_url = (
        await ops_test.build_charm("./")
        if not (entity_url := request.config.getoption("--charm-path"))
        else entity_url
    )

    # Deploy kfp-ui charm
    await ops_test.model.deploy(
        entity_url=entity_url,
        application_name=APP_NAME,
        resources=resources,
        trust=True,
    )

    # Deploy istio ambient charms and add relations
    await deploy_and_integrate_service_mesh_charms(APP_NAME, ops_test.model)

    context = generate_context_from_charm_spec_list(charms_dependencies_list)
    rendered_bundle = ops_test.render_bundle(BUNDLE_PATH, context)
    await ops_test.model.deploy(rendered_bundle, trust=True)
    await ops_test.model.integrate(f"{APP_NAME}:kfp-api", "kfp-api:kfp-api")
    await ops_test.model.integrate(f"{APP_NAME}:object-storage", "minio:object-storage")

    # Integrate dependency charms with the service mesh
    await integrate_with_service_mesh(
        KFP_VIZ.charm, ops_test.model, relate_to_ingress_route_endpoint=False
    )
    await integrate_with_service_mesh(
        KFP_API.charm, ops_test.model, relate_to_ingress_route_endpoint=False
    )

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


async def assert_ui_is_accessible(ops_test: OpsTest):
    """Verify that UI is accessible through the ingress gateway."""
    await assert_path_reachable_through_ingress(
        http_path=HTTP_PATH,
        namespace=ops_test.model.name,
        expected_content_type="text/html",
        expected_response_text="Kubeflow Pipelines",
    )


@pytest.mark.abort_on_fail
async def test_ui_is_accessible(ops_test: OpsTest):
    """Verify that UI is accessible through the ingress gateway before the second ingress."""
    await assert_ui_is_accessible(ops_test)


@pytest.mark.abort_on_fail
async def test_deploy_and_relate_second_ingress(ops_test: OpsTest):
    """Deploy a second istio-ingress-k8s and relate it to kfp-ui.

    kfp-ui must accept more than one istio-ingress-route relation without
    erroring, so it should remain active after the second ingress is related.
    """
    await ops_test.model.deploy(
        ISTIO_INGRESS_K8S_APP,
        application_name=SECOND_INGRESS_APP,
        channel=INGRESS_CHANNEL,
        trust=True,
    )
    await ops_test.model.wait_for_idle(
        [SECOND_INGRESS_APP],
        raise_on_blocked=False,
        raise_on_error=False,
        wait_for_active=True,
        timeout=60 * 15,
    )

    await ops_test.model.integrate(
        f"{SECOND_INGRESS_APP}:{ISTIO_INGRESS_ROUTE_ENDPOINT}",
        f"{APP_NAME}:{ISTIO_INGRESS_ROUTE_ENDPOINT}",
    )
    await ops_test.model.wait_for_idle(
        [APP_NAME, SECOND_INGRESS_APP],
        status="active",
        raise_on_blocked=False,
        raise_on_error=False,
        timeout=60 * 10,
        idle_period=30,
    )

    assert ops_test.model.applications[APP_NAME].units[0].workload_status == "active"


async def test_httproute_attached_to_second_gateway(ops_test: OpsTest, lightkube_client: Client):
    """Verify the HTTPRoute for the second ingress is created and bound to its Gateway.

    The istio-ingress-k8s charm names each route
    ``{source_app}-{route_name}-httproute-{section}-{ingress_app}`` and binds it to a
    Gateway named after the ingress application via ``parentRefs``. We assert that the
    route created for the second ingress is attached to the *second* Gateway (not the
    first) and routes the kfp-ui path to the kfp-ui backend.
    """
    namespace = ops_test.model.name

    expected_route_name = (
        f"{APP_NAME}-{INGRESS_ROUTE_NAME}-httproute-{HTTP_SECTION_NAME}-{SECOND_INGRESS_APP}"
    )

    # The second Gateway should exist, named after the second ingress application.
    lightkube_client.get(GATEWAY_RESOURCE, name=SECOND_INGRESS_APP, namespace=namespace)

    # Retry to give the ingress charm time to reconcile the HTTPRoute resources.
    httproute = None
    for attempt in RETRY_120_SECONDS:
        with attempt:
            httproute = lightkube_client.get(
                HTTPROUTE_RESOURCE, name=expected_route_name, namespace=namespace
            )

    parent_refs = httproute.spec["parentRefs"]
    assert len(parent_refs) == 1
    # The route must be attached to the SECOND gateway, not the first.
    assert parent_refs[0]["name"] == SECOND_INGRESS_APP
    assert parent_refs[0]["sectionName"] == HTTP_SECTION_NAME

    # And it must route the kfp-ui path to the kfp-ui backend.
    rule = httproute.spec["rules"][0]
    assert rule["matches"][0]["path"]["value"] == INGRESS_ROUTE_PATH
    assert rule["backendRefs"][0]["name"] == APP_NAME


@pytest.mark.abort_on_fail
async def test_ui_is_accessible_after_second_ingress(ops_test: OpsTest):
    """Verify that UI is still accessible through the ingress gateway after the second ingress."""
    await assert_ui_is_accessible(ops_test)
