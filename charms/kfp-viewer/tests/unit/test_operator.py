# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

from unittest.mock import MagicMock, patch

import ops
import pytest
from ops.model import ActiveStatus, BlockedStatus, WaitingStatus
from ops.testing import Harness

from charm import KfpViewer

ops.testing.SIMULATE_CAN_CONNECT = True


def test_log_forwarding(harness: Harness, mocked_lightkube_client):
    with patch("charm.LogForwarder") as mock_logging:
        harness.begin()
        mock_logging.assert_called_once_with(charm=harness.charm)


def test_not_leader(
    harness,
    mocked_lightkube_client,
):
    """Test that charm waits for leadership."""
    harness.begin_with_initial_hooks()
    assert harness.charm.model.unit.status == WaitingStatus(
        "[leadership-gate] Waiting for leadership"
    )


def test_wrong_model(harness, mocked_lightkube_client):
    """Test that charm blocks when it is not deployed to a model named `kubeflow`."""
    harness.set_leader(True)
    harness.set_model_name("wrong-name")
    harness.begin_with_initial_hooks()
    assert harness.charm.model.unit.status == BlockedStatus(
        "[model-name-gate] Charm must be deployed to model named kubeflow"
    )


def test_kubernetes_component_created(harness, mocked_lightkube_client):
    """Test that Kubernetes component is created when we have leadership."""
    harness.set_leader(True)
    harness.set_model_name("kubeflow")
    harness.begin()

    # Mock get_missing_kubernetes_resources to always return an empty list.
    kubernetes_resources = harness.charm.kubernetes_resources
    kubernetes_resources.component._get_missing_kubernetes_resources = MagicMock(return_value=[])

    harness.charm.on.install.emit()

    assert isinstance(harness.charm.kubernetes_resources.status, ActiveStatus)

    # Assert that expected amount of Kubernetes resources were created
    assert mocked_lightkube_client.apply.call_count == 1


def test_pebble_service_container_running(harness, mocked_lightkube_client):
    """Test that the pebble service of the charm's kfp-viewer container is running."""
    harness.set_leader(True)
    harness.set_model_name("kubeflow")
    harness.begin()
    harness.set_can_connect("kfp-viewer", True)

    harness.charm.kubernetes_resources.get_status = MagicMock(return_value=ActiveStatus())

    harness.charm.on.install.emit()

    assert isinstance(harness.charm.unit.status, ActiveStatus)

    container = harness.charm.unit.get_container("kfp-viewer")
    # Assert that sidecar container is up and its service is running
    assert container.get_service("controller").is_running()

    # Assert the environment variables that are set from inputs are correctly applied
    environment = container.get_plan().services["controller"].environment
    assert environment["MAX_NUM_VIEWERS"] == str(harness.charm.config.get("max-num-viewers"))
    assert environment["NAMESPACE"] == ""


def test_install_before_pebble_service_container(harness, mocked_lightkube_client):
    """Test that charm waits when install event happens before pebble-service-container is ready."""
    harness.set_leader(True)
    harness.set_model_name("kubeflow")
    harness.begin()

    harness.charm.kubernetes_resources.get_status = MagicMock(return_value=ActiveStatus())

    harness.charm.on.install.emit()

    # but charm is waiting on PebbleComponent
    assert harness.charm.model.unit.status == WaitingStatus(
        "[kfp-viewer-pebble-service] Waiting for Pebble to be ready."
    )


@pytest.fixture
def harness():
    return Harness(KfpViewer)


@pytest.fixture()
def mocked_lightkube_client(mocker):
    """Mocks the Lightkube Client in charm.py, returning a mock instead."""
    mocked_lightkube_client = MagicMock()
    mocker.patch("charm.lightkube.Client", return_value=mocked_lightkube_client)
    yield mocked_lightkube_client
