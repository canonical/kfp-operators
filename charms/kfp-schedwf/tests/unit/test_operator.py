# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

from unittest.mock import MagicMock, patch

import pytest
from charmed_kubeflow_chisme.exceptions import GenericCharmRuntimeError
from ops.model import ActiveStatus, BlockedStatus, WaitingStatus
from ops.testing import Harness

from charm import KfpSchedwf

SERVICE_ACCOUNT_NAME = "kfp-schedwf"


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
    assert mocked_lightkube_client.apply.call_count == 1


@patch("charm.SA_TOKEN_FULL_PATH", "tests/unit/data/non-existent-file")
def test_no_sa_token_file(harness, mocked_sa_component_kubernetes_client, mocked_lightkube_client):
    """Test the unit status when the SA token file is missing."""
    harness.begin()
    harness.set_can_connect("ml-pipeline-scheduledworkflow", True)

    harness.charm.leadership_gate.get_status = MagicMock(return_value=ActiveStatus())
    harness.charm.kubernetes_resources.component.get_status = MagicMock(
        return_value=ActiveStatus()
    )

    # NOTE: without relations, this is necessary for the charm to be installed before
    # "charm.sa_token.get_status()" can be called later on:
    harness.charm.on.install.emit()

    with pytest.raises(GenericCharmRuntimeError) as err:
        harness.charm.sa_token.get_status()

    assert (
        err.value.msg
        == f"Token file for {SERVICE_ACCOUNT_NAME} ServiceAccount not present in charm."
    )
    # The base charm arbitrarily sets the unit status to BlockedStatus
    # We should fix this in charmed-kubeflow-chisme as it doesn't really
    # show the actual error and can be misleading
    assert isinstance(harness.charm.unit.status, BlockedStatus)
    assert (
        harness.charm.unit.status.message
        == "[sa-token:scheduledworkflow] Failed to compute status.  See logs for details."
    )


@patch("charm.SA_TOKEN_FULL_PATH", "tests/unit/data/schedwf-sa-token")
def test_pebble_service_container_running(harness, mocked_lightkube_client):
    """Test that the pebble service of the charm's kfp-schedwf container is running."""
    harness.set_leader(True)
    harness.begin()
    harness.set_can_connect("ml-pipeline-scheduledworkflow", True)

    harness.charm.kubernetes_resources.get_status = MagicMock(return_value=ActiveStatus())
    harness.charm.sa_token.get_status = MagicMock(return_value=ActiveStatus())

    harness.charm.on.install.emit()

    assert isinstance(harness.charm.unit.status, ActiveStatus)

    container = harness.charm.unit.get_container("ml-pipeline-scheduledworkflow")
    # Assert that sidecar container is up and its service is running
    assert container.get_service("controller").is_running()

    # Assert the environment variables that are set from defaults in the service plan
    environment = container.get_plan().services["controller"].environment
    assert environment["CRON_SCHEDULE_TIMEZONE"] == harness.charm.config.get("timezone")


@patch("charm.SA_TOKEN_FULL_PATH", "tests/unit/data/schedwf-sa-token")
def test_pebble_service_is_replanned_on_config_changed(harness, mocked_lightkube_client):
    """Test that the pebble service of the charm's kfp-schedwf container is running."""
    harness.set_leader(True)
    harness.begin()
    harness.set_can_connect("ml-pipeline-scheduledworkflow", True)

    harness.charm.kubernetes_resources.get_status = MagicMock(return_value=ActiveStatus())
    harness.charm.sa_token.get_status = MagicMock(return_value=ActiveStatus())

    harness.charm.on.install.emit()

    assert isinstance(harness.charm.unit.status, ActiveStatus)

    container = harness.charm.unit.get_container("ml-pipeline-scheduledworkflow")
    # Assert that sidecar container is up and its service is running
    assert container.get_service("controller").is_running()

    # Assert the environment variables that are set from defaults
    environment = container.get_plan().services["controller"].environment
    assert environment["CRON_SCHEDULE_TIMEZONE"] == harness.charm.config.get("timezone")
    assert environment["LOG_LEVEL"] == harness.charm.config.get("log-level")


@patch("charm.SA_TOKEN_FULL_PATH", "tests/unit/data/schedwf-sa-token")
def test_install_before_pebble_service_container(harness, mocked_lightkube_client):
    """Test that charm waits when install event happens before pebble-service-container is ready."""
    harness.set_leader(True)
    harness.begin()

    harness.charm.kubernetes_resources.get_status = MagicMock(return_value=ActiveStatus())
    harness.charm.sa_token.get_status = MagicMock(return_value=ActiveStatus())

    harness.charm.on.install.emit()

    # Assert charm is waiting on PebbleComponent
    assert harness.charm.model.unit.status == WaitingStatus(
        "[kfp-schedwf-pebble-service] Waiting for Pebble to be ready."
    )


@pytest.fixture
def harness():
    return Harness(KfpSchedwf)


@pytest.fixture()
def mocked_lightkube_client(mocker):
    """Mocks the Lightkube Client in charm.py, returning a mock instead."""
    mocked_lightkube_client = MagicMock()
    mocker.patch("charm.lightkube.Client", return_value=mocked_lightkube_client)
    yield mocked_lightkube_client


@pytest.fixture()
def mocked_sa_component_kubernetes_client(mocker):
    """Mocks the kubernetes client in sa token component."""
    mocked_kubernetes_client = MagicMock()
    mocker.patch("charm.SATokenComponent.kubernetes_client")
    yield mocked_kubernetes_client
