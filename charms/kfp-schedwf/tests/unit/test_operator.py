# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

from unittest.mock import MagicMock, patch

import pytest
from ops.model import ActiveStatus, WaitingStatus
from ops.testing import Harness

from charm import KfpSchedwf


def test_log_forwarding(harness: Harness):
    with patch("charm.LogForwarder") as mock_logging:
        harness.begin()
        mock_logging.assert_called_once_with(charm=harness.charm)


def test_not_leader(harness):
    """Test that charm waits for leadership."""
    harness.begin_with_initial_hooks()
    assert harness.charm.model.unit.status == WaitingStatus(
        "[leadership-gate] Waiting for leadership"
    )


def test_pebble_service_container_running(harness):
    """Test that the pebble service of the charm's kfp-viewer container is running."""
    harness.set_leader(True)
    harness.begin()
    harness.set_can_connect("ml-pipeline-scheduledworkflow", True)

    harness.charm.on.install.emit()

    assert isinstance(harness.charm.unit.status, ActiveStatus)

    container = harness.charm.unit.get_container("ml-pipeline-scheduledworkflow")
    # Assert that sidecar container is up and its service is running
    assert container.get_service("controller").is_running()

    # Assert the environment variables that are set from defaults in the service plan
    environment = container.get_plan().services["controller"].environment
    assert environment["CRON_SCHEDULE_TIMEZONE"] == harness.charm.config.get("timezone")


def test_pebble_service_is_replanned_on_config_changed(harness):
    """Test that the pebble service of the charm's kfp-viewer container is running."""
    harness.set_leader(True)
    harness.begin()
    harness.set_can_connect("ml-pipeline-scheduledworkflow", True)

    harness.charm.on.install.emit()

    assert isinstance(harness.charm.unit.status, ActiveStatus)

    container = harness.charm.unit.get_container("ml-pipeline-scheduledworkflow")
    # Assert that sidecar container is up and its service is running
    assert container.get_service("controller").is_running()

    # Assert the environment variables that are set from defaults
    environment = container.get_plan().services["controller"].environment
    assert environment["CRON_SCHEDULE_TIMEZONE"] == harness.charm.config.get("timezone")
    assert environment["LOG_LEVEL"] == harness.charm.config.get("log-level")


def test_install_before_pebble_service_container(harness):
    """Test that charm waits when install event happens before pebble-service-container is ready."""
    harness.set_leader(True)
    harness.begin()

    harness.charm.on.install.emit()

    # Assert charm is waiting on PebbleComponent
    assert harness.charm.model.unit.status == WaitingStatus(
        "[kfp-schedwf-pebble-service] Waiting for Pebble to be ready."
    )


@pytest.fixture
def harness():
    return Harness(KfpSchedwf)
