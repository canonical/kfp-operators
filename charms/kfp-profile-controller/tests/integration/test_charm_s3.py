# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
from copy import deepcopy
from pathlib import Path

import lightkube
import pytest
import yaml
from charmed_kubeflow_chisme.testing import (
    GRAFANA_AGENT_APP,
    assert_logging,
    assert_security_context,
    deploy_and_assert_grafana_agent,
    generate_container_securitycontext_map,
    get_pod_names,
)
from charmed_kubeflow_chisme.testing.s3_integration import deploy_and_assert_s3_integrator
from charms_dependencies import (
    ADMISSION_WEBHOOK,
    ISTIO_PILOT,
    KUBEFLOW_PROFILES,
    METACONTROLLER_OPERATOR,
    S3_INTEGRATOR,
)
from lightkube import codecs
from lightkube.generic_resource import create_global_resource, create_namespaced_resource
from lightkube.resources.apps_v1 import Deployment
from lightkube.resources.core_v1 import ConfigMap, Namespace, Secret, Service, ServiceAccount
from pytest_operator.plugin import OpsTest
from tenacity import retry, stop_after_delay, wait_exponential

logger = logging.getLogger(__name__)

METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())
CHARM_NAME = METADATA["name"]
CONTAINERS_SECURITY_CONTEXT_MAP = generate_container_securitycontext_map(METADATA)

PodDefault = create_namespaced_resource(
    group="kubeflow.org", version="v1alpha1", kind="PodDefault", plural="poddefaults"
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

    # Deploy s3-integrator and provide it with S3 credentials, then relate it as the
    # object storage backend (instead of minio)
    await deploy_and_assert_s3_integrator(ops_test.model, s3_integrator=S3_INTEGRATOR)
    await ops_test.model.add_relation(
        f"{CHARM_NAME}:s3-credentials",
        f"{S3_INTEGRATOR.charm}:s3-credentials",
    )

    # Deploy charms responsible for CRDs creation
    await ops_test.model.deploy(
        entity_url=KUBEFLOW_PROFILES.charm,
        channel=KUBEFLOW_PROFILES.channel,
        trust=KUBEFLOW_PROFILES.trust,
    )

    # The profile controller needs AuthorizationPolicies to create Profiles
    # Deploy istio-pilot to provide the k8s cluster with this CRD
    await ops_test.model.deploy(
        entity_url=ISTIO_PILOT.charm,
        channel=ISTIO_PILOT.channel,
        trust=ISTIO_PILOT.trust,
    )
    # Wait for everything to deploy
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


@pytest.fixture(scope="session")
def profile(lightkube_client: lightkube.Client):
    """Creates a Profile object in cluster, cleaning it up after tests."""
    profile_file = "./tests/integration/profile.yaml"
    yaml_text = _safe_load_file_to_text(profile_file)
    yaml_rendered = yaml.safe_load(yaml_text)
    profilename = yaml_rendered["metadata"]["name"]

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


async def test_sync_webhook_resources(lightkube_client: lightkube.Client, profile: str):
    """Test that the sync webhook deploys the desired resources when backed by s3."""
    desired_resources = deepcopy(EXPECTED_SYNC_WEBHOOK_RESOURCES_BY_DEFAULT)

    for resource, name in desired_resources:
        lightkube_client.get(resource, name=name, namespace=profile)


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
