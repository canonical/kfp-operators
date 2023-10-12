# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

from unittest.mock import MagicMock

import pytest
from charmed_kubeflow_chisme.testing import add_sdi_relation_to_harness
from ops.model import ActiveStatus, BlockedStatus, WaitingStatus
from ops.testing import Harness

from charm import KfpMetadataWriter

MOCK_GRPC_DATA = {"service": "service-name", "port": "1234"}


def test_not_leader(
    harness,
    mocked_lightkube_client,
):
    """Test that charm waits for leadership."""
    harness.begin_with_initial_hooks()
    assert harness.charm.model.unit.status == WaitingStatus(
        "[leadership-gate] Waiting for leadership"
    )


def test_kubernetes_component_created(harness, mocked_lightkube_client):
    """Test that Kubernetes component is created when we have leadership."""
    # Needed because the kubernetes component will only apply to k8s if we are the leader
    harness.set_leader(True)
    harness.begin()

    # Need to mock the leadership-gate to be active, and the kubernetes auth component so that it
    # sees the expected resources when calling _get_missing_kubernetes_resources
    kubernetes_resources = harness.charm.kubernetes_resources
    kubernetes_resources.component._get_missing_kubernetes_resources = MagicMock(return_value=[])

    harness.charm.on.install.emit()

    assert isinstance(harness.charm.kubernetes_resources.status, ActiveStatus)

    # Assert that expected amount of apply calls were made
    # This simulates the Kubernetes resources being created
    assert mocked_lightkube_client.apply.call_count == 3


def test_grpc_relation_with_data(harness, mocked_lightkube_client):
    """Test that if Leadership is Active, the grpc relation operates as expected."""
    # Arrange
    harness.begin()

    # Mock:
    # * leadership_gate to be active and executed
    harness.charm.leadership_gate.get_status = MagicMock(return_value=ActiveStatus())

    # Add relation with data.  This should trigger a charm reconciliation due to relation-changed.
    add_sdi_relation_to_harness(harness, "grpc", data=MOCK_GRPC_DATA)

    # Assert
    assert isinstance(harness.charm.grpc_relation.status, ActiveStatus)


def test_grpc_relation_without_data(harness, mocked_lightkube_client):
    """Test that the grpc relation goes Blocked if no data is available."""
    # Arrange
    harness.begin()

    # Mock:
    # * leadership_gate to be active and executed
    harness.charm.leadership_gate.get_status = MagicMock(return_value=ActiveStatus())

    # Add relation with data.  This should trigger a charm reconciliation due to relation-changed.
    add_sdi_relation_to_harness(harness, "grpc", data={})

    # Assert
    assert isinstance(harness.charm.grpc_relation.status, BlockedStatus)


def test_grpc_relation_without_relation(harness, mocked_lightkube_client):
    """Test that the grpc relation goes Blocked if no relation is established."""
    # Arrange
    harness.begin()

    # Mock:
    # * leadership_gate to be active and executed
    harness.charm.leadership_gate.get_status = MagicMock(return_value=ActiveStatus())

    # Act
    harness.charm.on.install.emit()

    # Assert
    assert isinstance(harness.charm.grpc_relation.status, BlockedStatus)


def test_pebble_service_container_running(harness, mocked_lightkube_client):
    """Test that the pebble service of the charm's kfp-metadata-writer container is running."""
    harness.set_leader(True)
    harness.begin()
    harness.set_can_connect("kfp-metadata-writer", True)

    harness.charm.kubernetes_resources.get_status = MagicMock(return_value=ActiveStatus())
    add_sdi_relation_to_harness(harness, "grpc", data=MOCK_GRPC_DATA)

    harness.charm.on.install.emit()

    assert isinstance(harness.charm.unit.status, ActiveStatus)

    container = harness.charm.unit.get_container("kfp-metadata-writer")
    # Assert that sidecar container is up and its service is running
    assert container.get_service("kfp-metadata-writer").is_running()

    # Assert the environment variables that are set from defaults in the service plan
    environment = container.get_plan().services["kfp-metadata-writer"].environment
    assert environment["NAMESPACE_TO_WATCH"] == ""
    assert (
        environment["METADATA_GRPC_SERVICE_SERVICE_HOST"]
        == harness.charm.grpc_relation.component.get_data()["service"]
    )
    assert (
        environment["METADATA_GRPC_SERVICE_SERVICE_PORT"]
        == harness.charm.grpc_relation.component.get_data()["port"]
    )


def test_pebble_service_is_replanned_on_config_changed(harness, mocked_lightkube_client):
    """Test that the pebble service of the charm's kfp-metadata-writer container
    is running on config_changed"""
    harness.set_leader(True)
    harness.begin()
    harness.set_can_connect("kfp-metadata-writer", True)

    harness.charm.kubernetes_resources.get_status = MagicMock(return_value=ActiveStatus())
    add_sdi_relation_to_harness(harness, "grpc", data=MOCK_GRPC_DATA)

    harness.charm.on.config_changed.emit()

    assert isinstance(harness.charm.unit.status, ActiveStatus)

    container = harness.charm.unit.get_container("kfp-metadata-writer")
    # Assert that sidecar container is up and its service is running
    assert container.get_service("kfp-metadata-writer").is_running()

    # Assert the environment variables that are set from defaults in the service plan
    environment = container.get_plan().services["kfp-metadata-writer"].environment
    assert environment["NAMESPACE_TO_WATCH"] == ""
    assert (
        environment["METADATA_GRPC_SERVICE_SERVICE_HOST"]
        == harness.charm.grpc_relation.component.get_data()["service"]
    )
    assert (
        environment["METADATA_GRPC_SERVICE_SERVICE_PORT"]
        == harness.charm.grpc_relation.component.get_data()["port"]
    )


def test_install_before_pebble_service_container(harness, mocked_lightkube_client):
    """Test that charm waits when install event happens before pebble-service-container is ready."""
    harness.set_leader(True)
    harness.begin()

    harness.charm.kubernetes_resources.get_status = MagicMock(return_value=ActiveStatus())
    add_sdi_relation_to_harness(harness, "grpc", data=MOCK_GRPC_DATA)

    harness.charm.on.install.emit()

    # Assert charm is waiting on PebbleComponent
    assert harness.charm.model.unit.status == WaitingStatus(
        "[kfp-metadata-writer-pebble-service] Waiting for Pebble to be ready."
    )


@pytest.fixture
def harness():
    return Harness(KfpMetadataWriter)


@pytest.fixture()
def mocked_lightkube_client(mocker):
    """Mocks the Lightkube Client in charm.py, returning a mock instead."""
    mocked_lightkube_client = MagicMock()
    mocker.patch("charm.lightkube.Client", return_value=mocked_lightkube_client)
    yield mocked_lightkube_client
