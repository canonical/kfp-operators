# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

from unittest.mock import MagicMock, patch

import pytest
import yaml
from charmed_kubeflow_chisme.testing import add_sdi_relation_to_harness
from ops.model import ActiveStatus, WaitingStatus
from ops.testing import Harness

from charm import KfpVizOperator

# TODO: Tests missing for dropped/reloaded relations


def test_log_forwarding(harness: Harness, mocked_kubernetes_service_patch):
    with patch("charm.LogForwarder") as mock_logging:
        harness.begin()
        mock_logging.assert_called_once_with(charm=harness.charm)


def test_not_leader(harness: Harness, mocked_kubernetes_service_patch):
    """Test when we are not the leader."""
    harness.begin_with_initial_hooks()
    # Assert that we are not Active, and that the leadership-gate is the cause.
    assert not isinstance(harness.charm.model.unit.status, ActiveStatus)
    assert harness.charm.model.unit.status.message.startswith("[leadership-gate]")


def test_pebble_service_container_running(harness: Harness, mocked_kubernetes_service_patch):
    """Test that the pebble service of the charm's kfp-visualization
    container is running on install."""
    # Arrange
    harness.set_leader(True)
    harness.begin()
    harness.set_can_connect("ml-pipeline-visualizationserver", True)

    # Mock:
    # * leadership_gate to have get_status=>Active
    harness.charm.leadership_gate.get_status = MagicMock(return_value=ActiveStatus())

    # Act
    harness.charm.on.install.emit()

    assert isinstance(harness.charm.unit.status, ActiveStatus)

    # Assert
    container = harness.charm.unit.get_container("ml-pipeline-visualizationserver")
    # Assert that sidecar container is up and its service is running
    assert container.get_service("vis-server").is_running()


def test_pebble_service_is_replanned_on_config_changed(
    harness: Harness, mocked_kubernetes_service_patch
):
    """Test that the pebble service of the charm's kfp-visualization
    container is running on config_changed."""
    # Arrange
    harness.set_leader(True)
    harness.begin()
    harness.set_can_connect("ml-pipeline-visualizationserver", True)

    # Mock:
    # * leadership_gate to have get_status=>Active
    harness.charm.leadership_gate.get_status = MagicMock(return_value=ActiveStatus())

    # Act
    harness.charm.on.config_changed.emit()

    assert isinstance(harness.charm.unit.status, ActiveStatus)

    container = harness.charm.unit.get_container("ml-pipeline-visualizationserver")
    # Assert that sidecar container is up and its service is running
    assert container.get_service("vis-server").is_running()


def test_kfp_viz_relation_with_related_app(harness: Harness, mocked_kubernetes_service_patch):
    """Test that the kfp-viz relation sends data to related apps and goes Active."""
    # Arrange
    harness.set_leader(True)  # needed to write to an SDI relation
    model = "model"
    harness.set_model_name(model)
    harness.begin()

    # Mock:
    # * leadership_gate to be active and executed
    harness.charm.leadership_gate.get_status = MagicMock(return_value=ActiveStatus())

    expected_relation_data = {
        "_supported_versions": ["v1"],
        "data": render_kfp_viz_data(
            app_name=harness.model.app.name,
            model_name=model,
            port=harness.model.config["http-port"],
        ),
    }

    # Act
    # Add one relation with data.  This should trigger a charm reconciliation due to
    # relation-changed.
    relation_metadata = add_sdi_relation_to_harness(harness, "kfp-viz", other_app="o1", data={})
    relation_ids_to_assert = [relation_metadata.rel_id]

    # Assert
    assert isinstance(harness.charm.kfp_viz_relation.status, ActiveStatus)
    assert_relation_data_send_as_expected(harness, expected_relation_data, relation_ids_to_assert)


def test_install_before_pebble_service_container(harness, mocked_kubernetes_service_patch):
    """Test that charm waits when install event happens before pebble-service-container is ready."""
    # Arrange
    harness.set_leader(True)
    harness.begin()

    # Mock:
    # * leadership_gate to be active and executed
    harness.charm.leadership_gate.get_status = MagicMock(return_value=ActiveStatus())

    # Act
    harness.charm.on.install.emit()

    # Assert charm is waiting on PebbleComponent
    assert harness.charm.model.unit.status == WaitingStatus(
        "[kfp-viz-pebble-service] Waiting for Pebble to be ready."
    )


@pytest.fixture
def harness():
    return Harness(KfpVizOperator)


@pytest.fixture()
def mocked_kubernetes_service_patch(mocker):
    """Mocks the KubernetesServicePatch for the charm."""
    mocked_kubernetes_service_patch = mocker.patch(
        "charm.KubernetesServicePatch", lambda x, y, service_name: None
    )
    yield mocked_kubernetes_service_patch


def render_kfp_viz_data(app_name, model_name, port) -> dict:
    """Returns typical data for the kfp-viz relation."""
    return {
        "service-name": f"{app_name}.{model_name}",
        "service-port": str(port),
    }


def assert_relation_data_send_as_expected(
    harness_object: Harness, expected_relation_data: dict, rel_ids_to_assert: list
):
    """Asserts that we have sent the expected data to the given relations."""
    # Assert on the data we sent out to the other app for each relation.
    for rel_id in rel_ids_to_assert:
        relation_data = harness_object.get_relation_data(rel_id, harness_object.model.app)
        assert (
            yaml.safe_load(relation_data["_supported_versions"])
            == expected_relation_data["_supported_versions"]
        )
        assert yaml.safe_load(relation_data["data"]) == expected_relation_data["data"]
