# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

from unittest.mock import MagicMock

import pytest
from charmed_kubeflow_chisme.testing import add_sdi_relation_to_harness
from ops.model import ActiveStatus, BlockedStatus
from ops.testing import Harness

from charm import KfpProfileControllerOperator

MOCK_OBJECT_STORAGE_DATA = {
    "access-key": "access-key",
    "secret-key": "secret-key",
    "service": "service",
    "namespace": "namespace",
    "port": 1234,
    "secure": True,
}

EXPECTED_ENVIRONMENT = {
    "CONTROLLER_PORT": 80,
    "DISABLE_ISTIO_SIDECAR": "false",
    "KFP_DEFAULT_PIPELINE_ROOT": "",
    "KFP_VERSION": "2.0.2",
    "METADATA_GRPC_SERVICE_HOST": "mlmd.kubeflow",
    "METADATA_GRPC_SERVICE_PORT": "8080",
    "MINIO_ACCESS_KEY": "access-key",
    "MINIO_HOST": "service",
    "MINIO_NAMESPACE": "namespace",
    "MINIO_PORT": 1234,
    "MINIO_SECRET_KEY": "secret-key",
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


def test_not_leader(harness, mocked_lightkube_client, mocked_kubernetes_service_patch):
    """Test when we are not the leader."""
    harness.begin_with_initial_hooks()
    # Assert that we are not Active, and that the leadership-gate is the cause.
    assert not isinstance(harness.charm.model.unit.status, ActiveStatus)
    assert harness.charm.model.unit.status.message.startswith("[leadership-gate]")


def test_object_storage_relation_with_data(
    harness, mocked_lightkube_client, mocked_kubernetes_service_patch
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
    harness, mocked_lightkube_client, mocked_kubernetes_service_patch
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
    harness, mocked_lightkube_client, mocked_kubernetes_service_patch
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
    harness, mocked_lightkube_client, mocked_kubernetes_service_patch
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


def test_pebble_services_running(
    harness, mocked_lightkube_client, mocked_kubernetes_service_patch
):
    """Test that if the Kubernetes Component is Active, the pebble services successfully start."""
    # Arrange
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
    assert environment == EXPECTED_ENVIRONMENT
