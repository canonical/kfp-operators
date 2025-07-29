# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

from unittest.mock import MagicMock, patch

import pytest
from ops.model import ActiveStatus, BlockedStatus, WaitingStatus
from ops.testing import Harness

from charm import GRPC_RELATION_NAME, KfpMetadataWriter

MOCK_GRPC_DATA = {"name": "service-name", "port": "1234"}


def test_log_forwarding(harness: Harness):
    with patch("charm.LogForwarder") as mock_logging:
        harness.begin()
        mock_logging.assert_called_once_with(charm=harness.charm, relation_name="logging")


def test_not_leader(harness):
    """Test that charm waits for leadership."""
    harness.begin_with_initial_hooks()
    assert harness.charm.model.unit.status == WaitingStatus(
        "[leadership-gate] Waiting for leadership"
    )


def test_grpc_relation_with_data(harness):
    """Test that if Leadership is Active, the grpc relation operates as expected."""
    # Arrange
    harness.begin()

    # Mock:
    # * leadership_gate to be active and executed
    harness.charm.leadership_gate.get_status = MagicMock(return_value=ActiveStatus())

    # Add relation with data.  This should trigger a charm reconciliation due to relation-changed.
    harness.add_relation(
        relation_name=GRPC_RELATION_NAME, remote_app="other-app", app_data=MOCK_GRPC_DATA
    )

    # Assert
    assert harness.charm.grpc_relation.component.get_service_info().name == MOCK_GRPC_DATA["name"]
    assert harness.charm.grpc_relation.component.get_service_info().port == MOCK_GRPC_DATA["port"]


def test_grpc_relation_with_empty_data(harness):
    """Test the grpc relation component returns WaitingStatus when data is missing."""
    # Arrange
    harness.begin()

    # Mock:
    # * leadership_gate to be active and executed
    harness.charm.leadership_gate.get_status = MagicMock(return_value=ActiveStatus())

    harness.charm.on.install.emit()

    # Add relation without data.
    harness.add_relation(relation_name=GRPC_RELATION_NAME, remote_app="other-app", app_data={})

    assert isinstance(harness.charm.grpc_relation.get_status(), WaitingStatus)


def test_grpc_relation_with_missing_data(harness):
    """Test the grpc relation component returns WaitingStatus when data is incomplete."""
    # Arrange
    harness.begin()

    # Mock:
    # * leadership_gate to be active and executed
    harness.charm.leadership_gate.get_status = MagicMock(return_value=ActiveStatus())

    harness.charm.on.install.emit()

    # Add relation without data.
    harness.add_relation(
        relation_name=GRPC_RELATION_NAME, remote_app="other-app", app_data={"name": "some-name"}
    )

    assert isinstance(harness.charm.grpc_relation.component.get_status(), WaitingStatus)


def test_grpc_relation_without_relation(harness):
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
    assert (
        harness.charm.grpc_relation.status.message
        == "Missing relation with a k8s service info provider. Please add the missing relation."
    )


def test_pebble_service_container_running(harness):
    """Test that the pebble service of the charm's kfp-metadata-writer container is running."""
    harness.set_leader(True)
    harness.begin()
    harness.set_can_connect("kfp-metadata-writer", True)

    harness.charm.on.install.emit()

    harness.add_relation(
        relation_name=GRPC_RELATION_NAME, remote_app="other-app", app_data=MOCK_GRPC_DATA
    )

    assert isinstance(harness.charm.unit.status, ActiveStatus)

    container = harness.charm.unit.get_container("kfp-metadata-writer")
    # Assert that sidecar container is up and its service is running
    assert container.get_service("kfp-metadata-writer").is_running()

    # Assert the environment variables that are set from defaults in the service plan
    environment = container.get_plan().services["kfp-metadata-writer"].environment
    assert environment["NAMESPACE_TO_WATCH"] == ""
    assert (
        environment["METADATA_GRPC_SERVICE_SERVICE_HOST"]
        == harness.charm.grpc_relation.component.get_service_info().name
    )
    assert (
        environment["METADATA_GRPC_SERVICE_SERVICE_PORT"]
        == harness.charm.grpc_relation.component.get_service_info().port
    )


def test_install_before_pebble_service_container(harness):
    """Test that charm waits when install event happens before pebble-service-container is ready."""
    harness.set_leader(True)
    harness.begin()

    harness.add_relation(
        relation_name=GRPC_RELATION_NAME, remote_app="other-app", app_data=MOCK_GRPC_DATA
    )

    harness.charm.on.install.emit()

    # Assert charm is waiting on PebbleComponent
    assert harness.charm.model.unit.status == WaitingStatus(
        "[kfp-metadata-writer-pebble-service] Waiting for Pebble to be ready."
    )


@pytest.fixture
def harness():
    return Harness(KfpMetadataWriter)
