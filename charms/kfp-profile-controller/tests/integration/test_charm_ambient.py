# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

import json
import logging
from base64 import b64decode
from copy import deepcopy
from pathlib import Path

import lightkube
import pytest
import tenacity
import yaml
from charmed_kubeflow_chisme.testing import (
    GRAFANA_AGENT_APP,
    assert_logging,
    assert_security_context,
    deploy_and_assert_grafana_agent,
    deploy_and_integrate_service_mesh_charms,
    generate_container_securitycontext_map,
    get_pod_names,
)
from charms_dependencies import (
    ADMISSION_WEBHOOK,
    KUBEFLOW_PROFILES,
    METACONTROLLER_OPERATOR,
    MINIO,
)
from lightkube import ApiError, codecs
from lightkube.generic_resource import (
    GenericNamespacedResource,
    create_global_resource,
    create_namespaced_resource,
)
from lightkube.resources.apps_v1 import Deployment
from lightkube.resources.core_v1 import ConfigMap, Namespace, Secret, Service, ServiceAccount
from pytest_operator.plugin import OpsTest
from tenacity import Retrying, retry, stop_after_delay, wait_exponential, wait_fixed

logger = logging.getLogger(__name__)

METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())
CHARM_NAME = METADATA["name"]
CONTAINERS_SECURITY_CONTEXT_MAP = generate_container_securitycontext_map(METADATA)
CONFIG_NAME_FOR_CUSTOM_IMAGES = "custom_images"
CONFIG_NAME_FOR_DEFAULT_PIPELINE_ROOT = "default_pipeline_root"
CUSTOM_FRONTEND_IMAGE = "gcr.io/ml-pipeline/frontend:latest"
CUSTOM_VISUALISATION_IMAGE = "gcr.io/ml-pipeline/visualization-server:latest"
KFP_LAUNCHER_CONFIGMAP_KEY_FOR_DEFAULT_PIPELINE_ROOT = "defaultPipelineRoot"
KFP_LAUNCHER_CONFIGMAP_NAME = "kfp-launcher"
AMBIENT_AP_NAME = "ml-pipeline-visualizationserver"
SIDECAR_AP_NAME = "ns-owner-access-istio-charmed"

PodDefault = create_namespaced_resource(
    group="kubeflow.org", version="v1alpha1", kind="PodDefault", plural="poddefaults"
)

AuthorizationPolicy = create_namespaced_resource(
    group="security.istio.io",
    version="v1beta1",
    kind="AuthorizationPolicy",
    plural="authorizationpolicies",
)

EXPECTED_SYNC_WEBHOOK_RESOURCES_BY_DEFAULT = [
    (ConfigMap, "metadata-grpc-configmap"),
    (Deployment, "ml-pipeline-visualizationserver"),
    (Service, "ml-pipeline-visualizationserver"),
    (Deployment, "ml-pipeline-ui-artifact"),
    (Service, "ml-pipeline-ui-artifact"),
    (PodDefault, "access-ml-pipeline"),
    (Secret, "mlpipeline-minio-artifact"),
]

RETRY_FOR_ONE_MINUTE = Retrying(
    stop=stop_after_delay(60 * 1),
    wait=wait_fixed(5),
    reraise=True,
)


def wait_for_configmap(client: lightkube.Client, name: str, namespace: str) -> ConfigMap:
    """Waits until a specified configmap is available, to a maximum of 1 minute"""
    for attempt in RETRY_FOR_ONE_MINUTE:
        with attempt:
            return client.get(res=ConfigMap, name=name, namespace=namespace)
    raise TimeoutError(f"ConfigMap {name} in namespace {namespace} not present.")


@pytest.mark.abort_on_fail
async def test_build_and_deploy(ops_test: OpsTest, request: pytest.FixtureRequest):
    # Deploy the admission webhook to apply the PodDefault CRD required by the charm workload
    await ops_test.model.deploy(
        entity_url=ADMISSION_WEBHOOK.charm,
        channel=ADMISSION_WEBHOOK.channel,
        trust=ADMISSION_WEBHOOK.trust,
    )

    # TODO: The webhook charm must be active before the metacontroller is deployed, due to the bug
    # described here: https://github.com/canonical/metacontroller-operator/issues/86
    # Drop this wait_for_idle once the above issue is closed
    await ops_test.model.wait_for_idle(apps=[ADMISSION_WEBHOOK.charm], status="active")

    await ops_test.model.deploy(
        entity_url=METACONTROLLER_OPERATOR.charm,
        channel=METACONTROLLER_OPERATOR.channel,
        trust=METACONTROLLER_OPERATOR.trust,
    )

    # Deploy the charm under test
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
        resources=resources,
        trust=True,
    )

    # Deploy required relations
    await ops_test.model.deploy(
        entity_url=MINIO.charm,
        config=MINIO.config,
        trust=MINIO.trust,
        channel=MINIO.channel,
    )
    await ops_test.model.add_relation(
        f"{CHARM_NAME}:object-storage",
        f"{MINIO.charm}:object-storage",
    )

    # Deploy charms responsible for CRDs creation
    await ops_test.model.deploy(
        entity_url=KUBEFLOW_PROFILES.charm,
        channel=KUBEFLOW_PROFILES.channel,
        trust=KUBEFLOW_PROFILES.trust,
    )

    # The profile controller needs AuthorizationPolicies to create Profiles
    # Wait for everything to deploy
    await deploy_and_integrate_service_mesh_charms(
        CHARM_NAME,
        ops_test.model,
        relate_to_beacon=True,
        relate_to_ingress_gateway_endpoint=False,
        relate_to_ingress_route_endpoint=False,
    )
    await ops_test.model.wait_for_idle(status="active", raise_on_blocked=False, timeout=60 * 10)

    # Deploying grafana-agent-k8s and add all relations
    await deploy_and_assert_grafana_agent(
        ops_test.model, CHARM_NAME, metrics=False, dashboard=False, logging=True
    )


@pytest.mark.abort_on_fail
async def test_profile_and_resources_creation(lightkube_client: lightkube.Client, profile: str):
    """Create a profile and validate that corresponding resources were created."""
    profile_name = profile
    validate_profile_resources(lightkube_client, profile_name)


@pytest.mark.abort_on_fail
async def test_ambient_authorization_policy_created(
    lightkube_client: lightkube.Client, profile: str
):
    """Test if the expected Ambient AuthorizationPolicy is created in Profile."""
    logger.info(
        'Checking  if AuthorizationPolicy "%s" exists in Profile "%s"',
        AMBIENT_AP_NAME,
        profile,
    )
    policy = get_authorization_policy(AMBIENT_AP_NAME, profile, lightkube_client)
    assert policy is not None


@pytest.mark.abort_on_fail
async def test_insecure_authorization_policy_is_missing(
    lightkube_client: lightkube.Client, profile: str
):
    """Test if the previous sidecar AuthorizationPolicy is not present in Profile."""
    policy_name = ""
    logger.info(
        'Checking  if AuthorizationPolicy "%s" is not present in Profile "%s"',
        policy_name,
        profile,
    )

    with pytest.raises(ApiError) as excinfo:
        lightkube_client.get(
            AuthorizationPolicy,
            name=policy_name,
            namespace=profile,
        )

    assert excinfo.value.response.status_code == 404


@pytest.mark.abort_on_fail
async def test_kfp_api_principal_changed(
    ops_test: OpsTest, lightkube_client: lightkube.Client, profile: str
):
    """Test that the principal in the AuthorizationPolicy changes on config-change."""
    new_principal = "test"
    await ops_test.model.applications[CHARM_NAME].set_config({"kfp-api-principal": new_principal})
    await ops_test.model.wait_for_idle(apps=[CHARM_NAME], status="active", timeout=600)

    # ensure the AuthorizationPolicy in Profile is updated
    policy = get_authorization_policy(AMBIENT_AP_NAME, profile, lightkube_client)
    assert policy["spec"]["rules"][0]["from"][0]["source"]["principals"][0] == new_principal


@tenacity.retry(
    wait=wait_exponential(multiplier=1, min=1, max=5),
    stop=stop_after_delay(60 * 2),
    reraise=True,
)
def get_authorization_policy(
    name: str, namespace: str, lightkube_client: lightkube.Client
) -> GenericNamespacedResource:
    return lightkube_client.get(
        AuthorizationPolicy,
        name=name,
        namespace=namespace,
    )


@pytest.fixture(scope="session")
def lightkube_client() -> lightkube.Client:
    client = lightkube.Client(field_manager=f"{CHARM_NAME}")
    create_global_resource(group="kubeflow.org", version="v1", kind="Profile", plural="profiles")
    return client


def _safe_load_file_to_text(filename: str):
    """Returns the contents of filename if it is an existing file, else it returns filename."""
    try:
        text = Path(filename).read_text()
    except FileNotFoundError:
        text = filename
    return text


# @pytest.fixture()
@pytest.fixture(scope="session")
def profile(lightkube_client: lightkube.Client):
    """Creates a Profile object in cluster, cleaning it up after tests."""
    profile_file = "./tests/integration/profile.yaml"
    yaml_text = _safe_load_file_to_text(profile_file)
    yaml_rendered = yaml.safe_load(yaml_text)
    profilename = yaml_rendered["metadata"]["name"]

    logger.info("Creating profile: %s", profilename)
    for obj in codecs.load_all_yaml(yaml_text):
        try:
            lightkube_client.apply(obj)
        except lightkube.core.exceptions.ApiError as e:
            raise e

    yield profilename

    delete_all_from_yaml(yaml_text, lightkube_client)


def delete_all_from_yaml(yaml_file: str, lightkube_client: lightkube.Client = None):
    """Deletes all k8s resources listed in a YAML file via lightkube.

    Args:
        yaml_file (str or Path): Either a string filename or a string of valid YAML.  Will attempt
                                 to open a filename at this path, failing back to interpreting the
                                 string directly as YAML.
        lightkube_client: Instantiated lightkube client or None
    """
    yaml_text = _safe_load_file_to_text(yaml_file)

    if lightkube_client is None:
        lightkube_client = lightkube.Client()

    for obj in codecs.load_all_yaml(yaml_text):
        lightkube_client.delete(type(obj), obj.metadata.name)


@retry(
    wait=wait_exponential(multiplier=1, min=1, max=10),
    stop=stop_after_delay(30),
    reraise=True,
)
def validate_profile_resources(
    client: lightkube.Client,
    profile_name: str,
):
    """Tests if the resources associated with Profile were created.

    Validates that a namespace for a Profile was created, has the expected label,
    and that a default-editor service account was created.
    Retries multiple times using tenacity to allow time for profile-controller to create the
    namespace
    """
    namespace = client.get(Namespace, profile_name)
    namespace_name = namespace.metadata.name

    service_account = client.get(ServiceAccount, "default-editor", namespace=namespace_name)
    assert service_account

    expected_label = "pipelines.kubeflow.org/enabled"
    expected_label_value = "true"
    assert expected_label in namespace.metadata.labels
    assert expected_label_value == namespace.metadata.labels[expected_label]


@retry(
    wait=wait_exponential(multiplier=1, min=1, max=10),
    stop=stop_after_delay(30),
    reraise=True,
)
def validate_profile_deployments_with_custom_images(
    lightkube_client: lightkube.Client,
    profile_name: str,
    frontend_image: str,
    visualisation_image: str,
):
    """Tests if profile's deployment have correct images"""
    # Get deployments
    pipeline_ui_deployment = lightkube_client.get(
        Deployment, name="ml-pipeline-ui-artifact", namespace=profile_name
    )
    visualization_server_deployment = lightkube_client.get(
        Deployment, name="ml-pipeline-visualizationserver", namespace=profile_name
    )

    # Assert images
    assert pipeline_ui_deployment.spec.template.spec.containers[0].image == frontend_image
    assert (
        visualization_server_deployment.spec.template.spec.containers[0].image
        == visualisation_image
    )


async def test_model_resources(ops_test: OpsTest):
    """Tests if the resources associated with secret's namespace were created.

    Verifies that the secret was created, decoded secret-key matches the minio config value,
    and that the pods are running.
    """
    minio_config = await ops_test.model.applications[MINIO.charm].get_config()

    await assert_minio_secret(
        access_key=minio_config["access-key"]["value"],
        secret_key=minio_config["secret-key"]["value"],
        ops_test=ops_test,
    )


async def assert_minio_secret(access_key: str, secret_key: str, ops_test: OpsTest):
    lightkube_client = lightkube.Client()
    secret = lightkube_client.get(
        Secret, f"{CHARM_NAME}-minio-credentials", namespace=ops_test.model_name
    )
    assert b64decode(secret.data["MINIO_ACCESS_KEY"]).decode("utf-8") == access_key
    assert b64decode(secret.data["MINIO_SECRET_KEY"]).decode("utf-8") == secret_key
    return lightkube_client


async def test_minio_config_changed(ops_test: OpsTest):
    """Tests if the kfp-profile controller unit updates its secrets if minio credentials change."""
    minio_access_key = "new-access-key"
    minio_secret_key = "new-secret-key"
    await ops_test.model.applications["minio"].set_config(
        {"access-key": minio_access_key, "secret-key": minio_secret_key}
    )
    await ops_test.model.wait_for_idle(
        apps=[MINIO.charm, CHARM_NAME], status="active", timeout=600
    )

    await assert_minio_secret(minio_access_key, minio_secret_key, ops_test)

    assert ops_test.model.applications[CHARM_NAME].units[0].workload_status == "active"


async def test_sync_webhook_before_config_changes(
    lightkube_client: lightkube.Client, profile: str
):
    """Test that the sync webhook deploys the desired resources."""
    desired_resources = deepcopy(EXPECTED_SYNC_WEBHOOK_RESOURCES_BY_DEFAULT)

    for resource, name in desired_resources:
        lightkube_client.get(resource, name=name, namespace=profile)


async def test_default_config_for_deafult_pipeline_root(
    lightkube_client: lightkube.Client, profile: str
):
    """Test that the default config for the default pipeline root is applied as intended."""
    with pytest.raises(lightkube.ApiError):
        lightkube_client.get(res=ConfigMap, name=KFP_LAUNCHER_CONFIGMAP_NAME, namespace=profile)


async def test_first_change_to_config_for_deafult_pipeline_root(
    ops_test: OpsTest, lightkube_client: lightkube.Client, profile: str
):
    """Test that a first config change for the default pipeline root results in a ConfigMap."""
    updated_deafult_pipeline_root = "minio://whatever-minio-bucket/whatever/minio/path"

    await ops_test.model.applications[CHARM_NAME].set_config(
        {CONFIG_NAME_FOR_DEFAULT_PIPELINE_ROOT: updated_deafult_pipeline_root}
    )
    await ops_test.model.wait_for_idle(
        apps=[CHARM_NAME], status="active", raise_on_blocked=True, timeout=300
    )

    kfp_launcher_configmap = wait_for_configmap(
        lightkube_client, KFP_LAUNCHER_CONFIGMAP_NAME, profile
    )
    assert (
        kfp_launcher_configmap.data[KFP_LAUNCHER_CONFIGMAP_KEY_FOR_DEFAULT_PIPELINE_ROOT]
        == updated_deafult_pipeline_root
    )


async def test_yet_another_change_to_config_for_deafult_pipeline_root(
    ops_test: OpsTest, lightkube_client: lightkube.Client, profile: str
):
    """Test that another config change for the default pipeline root updates the ConfigMap."""
    updated_deafult_pipeline_root = "s3://whatever-s3-bucket/whatever/s3/path"

    await ops_test.model.applications[CHARM_NAME].set_config(
        {CONFIG_NAME_FOR_DEFAULT_PIPELINE_ROOT: updated_deafult_pipeline_root}
    )
    await ops_test.model.wait_for_idle(
        apps=[CHARM_NAME], status="active", raise_on_blocked=True, timeout=300
    )

    # NOTE: simulating the necessary manual deletion of the old ConfigMap by the user:
    # https://github.com/kubeflow/manifests/blob/v1.10.1/apps/pipeline/upstream/base/installs/generic/pipeline-install-config.yaml#L40-L42  # noqa: E501 # fmt: skip
    lightkube_client.delete(res=ConfigMap, name=KFP_LAUNCHER_CONFIGMAP_NAME, namespace=profile)
    await ops_test.model.wait_for_idle(
        apps=[CHARM_NAME], status="active", raise_on_blocked=True, timeout=300
    )

    kfp_launcher_configmap = wait_for_configmap(
        lightkube_client, KFP_LAUNCHER_CONFIGMAP_NAME, profile
    )
    assert (
        kfp_launcher_configmap.data[KFP_LAUNCHER_CONFIGMAP_KEY_FOR_DEFAULT_PIPELINE_ROOT]
        == updated_deafult_pipeline_root
    )


async def test_sync_webhook_after_config_changes(lightkube_client: lightkube.Client, profile: str):
    """Test that the sync webhook deploys the desired resources."""
    desired_resources = deepcopy(EXPECTED_SYNC_WEBHOOK_RESOURCES_BY_DEFAULT)
    desired_resources.append((ConfigMap, "kfp-launcher"))

    for resource, name in desired_resources:
        lightkube_client.get(resource, name=name, namespace=profile)


async def test_change_custom_images(
    ops_test: OpsTest, lightkube_client: lightkube.Client, profile: str
):
    """Tests that updating images deployed to user Namespaces works as expected."""
    custom_images = {
        "visualization_server": CUSTOM_VISUALISATION_IMAGE,
        "frontend": CUSTOM_FRONTEND_IMAGE,
    }
    await ops_test.model.applications[CHARM_NAME].set_config(
        {CONFIG_NAME_FOR_CUSTOM_IMAGES: json.dumps(custom_images)}
    )

    await ops_test.model.wait_for_idle(
        apps=[CHARM_NAME], status="active", raise_on_blocked=True, timeout=300
    )

    validate_profile_deployments_with_custom_images(
        lightkube_client, profile, CUSTOM_FRONTEND_IMAGE, CUSTOM_VISUALISATION_IMAGE
    )


async def test_logging(ops_test: OpsTest):
    """Test logging is defined in relation data bag."""
    app = ops_test.model.applications[GRAFANA_AGENT_APP]
    await assert_logging(app)


@pytest.mark.parametrize("container_name", list(CONTAINERS_SECURITY_CONTEXT_MAP.keys()))
async def test_container_security_context(
    ops_test: OpsTest,
    lightkube_client: lightkube.Client,
    container_name: str,
):
    """Test container security context is correctly set.

    Verify that container spec defines the security context with correct
    user ID and group ID.
    """
    pod_name = get_pod_names(ops_test.model.name, CHARM_NAME)[0]
    assert_security_context(
        lightkube_client,
        pod_name,
        container_name,
        CONTAINERS_SECURITY_CONTEXT_MAP,
        ops_test.model.name,
    )
