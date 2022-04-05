# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
from base64 import b64decode
from pathlib import Path

import lightkube
import pytest
import yaml
from lightkube import codecs
from lightkube.generic_resource import create_global_resource
from lightkube.resources.core_v1 import Namespace, Pod, Secret, ServiceAccount
from pytest_operator.plugin import OpsTest
from tenacity import retry, stop_after_delay, wait_exponential

logger = logging.getLogger(__name__)

APP_NAME = "kfp-profile-controller"
METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())

MINIO_CONFIG = {"access-key": "minio", "secret-key": "minio-secret-key"}


@pytest.mark.abort_on_fail
async def test_build_and_deploy(ops_test: OpsTest):
    built_charm_path = await ops_test.build_charm("./")
    logger.info(f"Built charm {built_charm_path}")

    image_path = METADATA["resources"]["oci-image"]["upstream-source"]
    resources = {"oci-image": image_path}

    await ops_test.model.deploy(
        entity_url=built_charm_path,
        application_name=APP_NAME,
        resources=resources,
    )

    # Deploy required relations
    await ops_test.model.deploy(entity_url="minio", config=MINIO_CONFIG)
    await ops_test.model.add_relation(
        f"{APP_NAME}:object-storage",
        "minio:object-storage",
    )

    # Deploy charms responsible for CRDs creation
    await ops_test.model.deploy(
        entity_url="kubeflow-profiles",
        trust=True,
    )
    await ops_test.model.deploy(
        entity_url="metacontroller-operator",
        trust=True,
    )

    # Maybe: await ops_test.model.wait_for_idle(raise_on_error=False, raise_on_blocked=True) ?
    await ops_test.model.wait_for_idle(status="active", timeout=60 * 10)


@pytest.mark.abort_on_fail
async def test_profile_and_resources_creation(lightkube_client, profile):
    """Create a profile and validate that corresponding resources were created."""
    profile_name = profile
    validate_profile_resources(lightkube_client, profile_name)


@pytest.fixture(scope="session")
def lightkube_client() -> lightkube.Client:
    client = lightkube.Client(field_manager=f"{APP_NAME}")
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
def profile(lightkube_client):
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


def test_model_resources(ops_test: OpsTest):
    """Tests if the resources associated with secret's namespace were created.

    Verifies that the secret was created, decoded secret-key matches the minio config value,
    and that the pods are running.
    """
    lightkube_client = lightkube.Client()
    secret = lightkube_client.get(
        Secret, f"{APP_NAME}-minio-credentials", namespace=ops_test.model_name
    )
    assert b64decode(secret.data["MINIO_SECRET_KEY"]).decode("utf-8") == MINIO_CONFIG["secret-key"]

    pod_status = lightkube_client.get(Pod, f"{APP_NAME}-operator-0", namespace=ops_test.model_name)
    assert pod_status.status.phase == "Running"


async def test_minio_config_changed(ops_test: OpsTest):
    """Tests if the kfp-profile controller unit turns active after minio config change."""
    await ops_test.model.applications["minio"].set_config(
        {"access-key": "new-access-key", "secret-key": "new-secret-key"}
    )
    await ops_test.model.wait_for_idle(status="active", timeout=600)

    assert ops_test.model.applications[APP_NAME].units[0].workload_status == "active"
