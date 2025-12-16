# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

import json
from copy import deepcopy
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml
from charmed_kubeflow_chisme.testing import add_sdi_relation_to_harness
from ops.model import ActiveStatus, BlockedStatus
from ops.testing import Harness

from charm import (
    CONTROLLER_PORT,
    DISABLE_ISTIO_SIDECAR,
    KFP_IMAGES_VERSION,
    METADATA_GRPC_SERVICE_HOST,
    METADATA_GRPC_SERVICE_PORT,
    KfpProfileControllerOperator,
)

CONFIG_NAME_FOR_CUSTOM_IMAGES = "custom_images"
CONFIG_NAME_FOR_DEFAULT_PIPELINE_ROOT = "default_pipeline_root"

# Load the custom images from the JSON
CUSTOM_IMAGES_PATH = Path("./src/default-custom-images.json")
with CUSTOM_IMAGES_PATH.open() as f:
    custom_images = json.load(f)

KFP_DEFAULT_PIPELINE_ROOT = ""

MOCK_OBJECT_STORAGE_DATA = {
    "access-key": "access-key",
    "secret-key": "secret-key",
    "service": "service",
    "namespace": "namespace",
    "port": 1234,
    "secure": True,
}

EXPECTED_ENVIRONMENT_BY_DEFAULT = {
    "CONTROLLER_PORT": CONTROLLER_PORT,
    "DISABLE_ISTIO_SIDECAR": DISABLE_ISTIO_SIDECAR,
    "KFP_DEFAULT_PIPELINE_ROOT": KFP_DEFAULT_PIPELINE_ROOT,
    "KFP_VERSION": KFP_IMAGES_VERSION,
    "METADATA_GRPC_SERVICE_HOST": METADATA_GRPC_SERVICE_HOST,
    "METADATA_GRPC_SERVICE_PORT": METADATA_GRPC_SERVICE_PORT,
    "MINIO_ACCESS_KEY": MOCK_OBJECT_STORAGE_DATA["access-key"],
    "MINIO_HOST": MOCK_OBJECT_STORAGE_DATA["service"],
    "MINIO_NAMESPACE": MOCK_OBJECT_STORAGE_DATA["namespace"],
    "MINIO_PORT": MOCK_OBJECT_STORAGE_DATA["port"],
    "MINIO_SECRET_KEY": MOCK_OBJECT_STORAGE_DATA["secret-key"],
    # Using custom image and tag from the JSON file
    "FRONTEND_IMAGE": custom_images["frontend"].split(":")[0],
    "FRONTEND_TAG": custom_images["frontend"].split(":")[1],
    "VISUALIZATION_SERVER_IMAGE": custom_images["visualization_server"].split(":")[0],
    "VISUALIZATION_SERVER_TAG": custom_images["visualization_server"].split(":")[1],
}


@pytest.fixture
def harness() -> Harness:
    harness = Harness(KfpProfileControllerOperator)
    return harness


@pytest.fixture()
def mocked_lightkube_client(mocker):
    """Mocks the Lightkube Client in charm.py, returning a mock instead."""
    mocked_lightkube_client = MagicMock()
    mocker.patch("charm.lightkube.Client", return_value=mocked_lightkube_client)
    yield mocked_lightkube_client


@pytest.fixture()
def mocked_kubernetes_service_patch(mocker):
    """Mocks the KubernetesServicePatch for the charm."""
    mocked_kubernetes_service_patch = mocker.patch(
        "charm.KubernetesServicePatch", lambda x, y, service_name: None
    )
    yield mocked_kubernetes_service_patch


def test_log_forwarding(
    harness: Harness, mocked_lightkube_client, mocked_kubernetes_service_patch
):
    with patch("charm.LogForwarder") as mock_logging:
        harness.begin()
        mock_logging.assert_called_once_with(charm=harness.charm)


def test_not_leader(harness: Harness, mocked_lightkube_client, mocked_kubernetes_service_patch):
    """Test when we are not the leader."""
    harness.begin_with_initial_hooks()
    # Assert that we are not Active, and that the leadership-gate is the cause.
    assert not isinstance(harness.charm.model.unit.status, ActiveStatus)
    assert harness.charm.model.unit.status.message.startswith("[leadership-gate]")


def test_object_storage_relation_with_data(
    harness: Harness, mocked_lightkube_client, mocked_kubernetes_service_patch
):
    """Test that if Leadership is Active, the object storage relation operates as expected.

    Note: See test_relation_components.py for an alternative way of unit testing Components without
          mocking the regular charm.
    """
    # Arrange
    harness.begin()

    # Mock:
    # * leadership_gate to be active and executed
    harness.charm.leadership_gate.get_status = MagicMock(return_value=ActiveStatus())

    # Add relation with data.  This should trigger a charm reconciliation due to relation-changed.
    add_sdi_relation_to_harness(harness, "object-storage", data=MOCK_OBJECT_STORAGE_DATA)

    # Assert
    assert isinstance(harness.charm.object_storage_relation.status, ActiveStatus)


def test_object_storage_relation_without_data(
    harness: Harness, mocked_lightkube_client, mocked_kubernetes_service_patch
):
    """Test that the object storage relation goes Blocked if no data is available."""
    # Arrange
    harness.begin()

    # Mock:
    # * leadership_gate to be active and executed
    harness.charm.leadership_gate.get_status = MagicMock(return_value=ActiveStatus())

    # Add relation with data.  This should trigger a charm reconciliation due to relation-changed.
    add_sdi_relation_to_harness(harness, "object-storage", data={})

    # Assert
    assert isinstance(harness.charm.object_storage_relation.status, BlockedStatus)


def test_object_storage_relation_without_relation(
    harness: Harness, mocked_lightkube_client, mocked_kubernetes_service_patch
):
    """Test that the object storage relation goes Blocked if no relation is established."""
    # Arrange
    harness.begin()

    # Mock:
    # * leadership_gate to be active and executed
    harness.charm.leadership_gate.get_status = MagicMock(return_value=ActiveStatus())

    # Act
    harness.charm.on.install.emit()

    # Assert
    assert isinstance(harness.charm.object_storage_relation.status, BlockedStatus)


def test_kubernetes_created_method(
    harness: Harness, mocked_lightkube_client, mocked_kubernetes_service_patch
):
    """Test whether we try to create Kubernetes resources when we have leadership."""
    # Arrange
    # Needed because kubernetes component will only apply to k8s if we are the leader
    harness.set_leader(True)
    harness.begin()

    # Need to mock the leadership-gate to be active, and the kubernetes auth component so that it
    # sees the expected resources when calling _get_missing_kubernetes_resources

    harness.charm.leadership_gate.get_status = MagicMock(return_value=ActiveStatus())

    # Add relation with data.  This should trigger a charm reconciliation due to relation-changed.
    add_sdi_relation_to_harness(harness, "object-storage", data=MOCK_OBJECT_STORAGE_DATA)

    harness.charm.kubernetes_resources.component._get_missing_kubernetes_resources = MagicMock(
        return_value=[]
    )

    # Act
    harness.charm.on.install.emit()

    # Assert
    assert mocked_lightkube_client.apply.call_count == 4
    assert isinstance(harness.charm.kubernetes_resources.status, ActiveStatus)


@pytest.mark.parametrize("do_update_config_for_default_pipeline_root", (False, True))
def test_pebble_services_running(
    do_update_config_for_default_pipeline_root: bool,
    harness: Harness,
    mocked_lightkube_client,
    mocked_kubernetes_service_patch,
):
    """Test that if the Kubernetes Component is Active, the pebble services successfully start."""
    # Arrange
    expected_environment = deepcopy(EXPECTED_ENVIRONMENT_BY_DEFAULT)
    if do_update_config_for_default_pipeline_root:
        updated_default_pipeline_root = "s3://whatever-s3-bucket/whatever/s3/path"
        harness.update_config(
            {CONFIG_NAME_FOR_DEFAULT_PIPELINE_ROOT: updated_default_pipeline_root}
        )
        expected_environment["KFP_DEFAULT_PIPELINE_ROOT"] = updated_default_pipeline_root
    harness.begin()
    harness.set_can_connect("kfp-profile-controller", True)

    # Mock:
    # * leadership_gate to have get_status=>Active
    # * object_storage_relation to return mock data, making the item go active
    # * kubernetes_resources to have get_status=>Active
    harness.charm.leadership_gate.get_status = MagicMock(return_value=ActiveStatus())
    harness.charm.object_storage_relation.component.get_data = MagicMock(
        return_value=MOCK_OBJECT_STORAGE_DATA
    )
    harness.charm.kubernetes_resources.get_status = MagicMock(return_value=ActiveStatus())

    # Act
    harness.charm.on.install.emit()

    # Assert
    container = harness.charm.unit.get_container("kfp-profile-controller")
    service = container.get_service("kfp-profile-controller")
    assert service.is_running()
    # Assert the environment variables that are set from inputs are correctly applied
    environment = container.get_plan().services["kfp-profile-controller"].environment
    assert environment == expected_environment


def test_custom_images_config_with_incorrect_config(
    harness: Harness, mocked_lightkube_client, mocked_kubernetes_service_patch
):
    """Asserts that the unit goes to blocked on corrupted config input."""
    harness.update_config({CONFIG_NAME_FOR_CUSTOM_IMAGES: "{"})
    harness.begin()

    assert isinstance(harness.model.unit.status, BlockedStatus)
    assert harness.charm.model.unit.status.message.startswith("Error parsing")


def test_custom_images_config_with_incorrect_images_names(
    harness: Harness, mocked_lightkube_client, mocked_kubernetes_service_patch
):
    """Asserts that the unit goes to blocked on incorrect images names in the config input."""
    harness.update_config(
        {CONFIG_NAME_FOR_CUSTOM_IMAGES: yaml.dump({"name1": "image1", "name2": "image2"})}
    )
    harness.begin()

    assert isinstance(harness.model.unit.status, BlockedStatus)
    assert harness.charm.model.unit.status.message.startswith("Incorrect image name")
