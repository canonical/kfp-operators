# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.
from unittest.mock import MagicMock, patch

import pytest
import yaml
from charmed_kubeflow_chisme.testing import add_sdi_relation_to_harness
from ops.model import ActiveStatus, BlockedStatus
from ops.testing import Harness

from charm import KfpUiOperator

MOCK_OBJECT_STORAGE_DATA = {
    "access-key": "access-key",
    "secret-key": "secret-key",
    "service": "service",
    "namespace": "namespace",
    "port": 1234,
    "secure": True,
}
MOCK_KFP_API_DATA = {"service-name": "service-name", "service-port": "1234"}


def test_log_forwarding(
    harness: Harness,
    mocked_kubernetes_service_patch,
):
    """Test LogForwarder initialization."""
    with patch("charm.LogForwarder") as mock_logging:
        harness.begin()
        mock_logging.assert_called_once_with(charm=harness.charm)


def test_not_leader(
    harness: Harness,
    mocked_kubernetes_service_patch,
):
    """Test when we are not the leader."""
    harness.set_leader(False)
    harness.begin_with_initial_hooks()
    # Assert that we are not Active, and that the leadership-gate is the cause.
    assert not isinstance(harness.charm.model.unit.status, ActiveStatus)
    assert harness.charm.model.unit.status.message.startswith("[leadership-gate]")


def test_object_storage_relation_with_data(harness: Harness, mocked_kubernetes_service_patch):
    """Test that if Leadership is Active, the object storage relation operates as expected."""
    # Arrange
    harness.begin()

    # Mock:
    # * leadership_gate to be active and executed
    harness.charm.leadership_gate.get_status = MagicMock(return_value=ActiveStatus())

    # Add relation with data.  This should trigger a charm reconciliation due to relation-changed.
    add_sdi_relation_to_harness(harness, "object-storage", data=MOCK_OBJECT_STORAGE_DATA)

    # Assert
    assert isinstance(harness.charm.object_storage_relation.status, ActiveStatus)


def test_object_storage_relation_without_data(harness: Harness, mocked_kubernetes_service_patch):
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
    harness: Harness,
    mocked_kubernetes_service_patch,
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


def test_kfp_api_relation_with_data(harness: Harness, mocked_kubernetes_service_patch):
    """Test that if Leadership is Active, the kfp-api relation operates as expected."""
    # Arrange
    harness.begin()

    # Mock:
    # * leadership_gate to be active and executed
    harness.charm.leadership_gate.get_status = MagicMock(return_value=ActiveStatus())

    # Add relation with data.  This should trigger a charm reconciliation due to relation-changed.
    add_sdi_relation_to_harness(harness, "kfp-api", data=MOCK_KFP_API_DATA)

    # Assert
    assert isinstance(harness.charm.kfp_api_relation.status, ActiveStatus)


def test_kfp_api_relation_without_data(harness: Harness, mocked_kubernetes_service_patch):
    """Test that the kfp-api relation goes Blocked if no data is available."""
    # Arrange
    harness.begin()

    # Mock:
    # * leadership_gate to be active and executed
    harness.charm.leadership_gate.get_status = MagicMock(return_value=ActiveStatus())

    # Add relation with data.  This should trigger a charm reconciliation due to relation-changed.
    add_sdi_relation_to_harness(harness, "kfp-api", data={})

    # Assert
    assert isinstance(harness.charm.kfp_api_relation.status, BlockedStatus)


def test_kfp_api_relation_without_relation(harness: Harness, mocked_kubernetes_service_patch):
    """Test that the kfp-api relation goes Blocked if no relation is established."""
    # Arrange
    harness.begin()

    # Mock:
    # * leadership_gate to be active and executed
    harness.charm.leadership_gate.get_status = MagicMock(return_value=ActiveStatus())

    # Act
    harness.charm.on.install.emit()

    # Assert
    assert isinstance(harness.charm.kfp_api_relation.status, BlockedStatus)


def test_ambient_ingress_component_get_status(
    harness: Harness,
    mocked_kubernetes_service_patch,
):
    """Test that ambient ingress component get_status always returns ActiveStatus."""
    # Arrange
    harness.begin()

    # Act
    status = harness.charm.ambient_ingress_relation.component.get_status()

    # Assert
    assert isinstance(status, ActiveStatus)


def test_ambient_ingress_configure_app_leader_success(
    harness: Harness,
    mocked_kubernetes_service_patch,
):
    """Test that _configure_app_leader submits config when ingress is ready."""
    # Arrange
    harness.begin()

    # Add the relation first
    harness.add_relation("istio-ingress-route", "istio-ingress")

    # Mock methods on the actual ingress instance
    ingress = harness.charm.ambient_ingress_relation.component.ingress
    ingress.is_ready = MagicMock(return_value=True)
    ingress.submit_config = MagicMock()

    # Act - Trigger install event which calls the component through the charm reconciler
    harness.charm.on.install.emit()

    # Assert
    ingress.submit_config.assert_called_once()


def test_ambient_ingress_configure_app_leader_not_ready(
    harness: Harness,
    mocked_kubernetes_service_patch,
):
    """Test that _configure_app_leader skips submission when ingress is not ready."""
    # Arrange
    harness.begin()

    # Add the relation first
    harness.add_relation("istio-ingress-route", "istio-ingress")

    # Mock methods on the actual ingress instance
    ingress = harness.charm.ambient_ingress_relation.component.ingress
    ingress.is_ready = MagicMock(return_value=False)
    ingress.submit_config = MagicMock()

    # Act - Trigger install event which calls the component through the charm reconciler
    harness.charm.on.install.emit()

    # Assert
    ingress.submit_config.assert_not_called()


def test_ambient_ingress_configure_app_leader_generic_error(
    harness: Harness,
    mocked_kubernetes_service_patch,
):
    """Test that _configure_app_leader raises GenericCharmRuntimeError on other exceptions."""
    from charmed_kubeflow_chisme.exceptions import GenericCharmRuntimeError

    # Arrange
    harness.begin()

    # Mock methods on the actual ingress instance
    ingress = harness.charm.ambient_ingress_relation.component.ingress
    ingress.is_ready = MagicMock(return_value=True)
    ingress.submit_config = MagicMock(side_effect=Exception("Test error"))

    # Act & Assert - Call the method directly to test exception handling
    with pytest.raises(GenericCharmRuntimeError) as exc_info:
        harness.charm.ambient_ingress_relation.component._configure_app_leader(None)

    assert "Failed to submit ingress config" in str(exc_info.value)
    assert "Test error" in str(exc_info.value)


def test_ingress_relation_with_related_app(harness: Harness, mocked_kubernetes_service_patch):
    """Test that the kfp-api relation sends data to related apps and goes Active."""
    # Arrange
    harness.begin()

    # Mock:
    # * leadership_gate to be active and executed
    harness.charm.leadership_gate.get_status = MagicMock(return_value=ActiveStatus())

    expected_relation_data = {
        "_supported_versions": ["v1"],
        "data": render_ingress_data(
            service=harness.model.app.name, port=harness.model.config["http-port"]
        ),
    }

    # Act
    # Add one relation with data.  This should trigger a charm reconciliation due to
    # relation-changed.
    relation_metadata = add_sdi_relation_to_harness(harness, "ingress", other_app="o1", data={})
    relation_ids_to_assert = [relation_metadata.rel_id]

    # Assert
    assert isinstance(harness.charm.sidecar_ingress_relation.status, ActiveStatus)
    assert_relation_data_send_as_expected(harness, expected_relation_data, relation_ids_to_assert)


def test_kfp_ui_relation_with_related_app(harness: Harness, mocked_kubernetes_service_patch):
    """Test that the kfp-ui relation sends data to related apps and goes Active."""
    # Arrange
    model = "model"
    harness.set_model_name(model)
    harness.begin()

    # Mock:
    # * leadership_gate to be active and executed
    harness.charm.leadership_gate.get_status = MagicMock(return_value=ActiveStatus())

    expected_relation_data = {
        "_supported_versions": ["v1"],
        "data": render_kfp_ui_data(
            app_name=harness.model.app.name,
            model_name=model,
            port=harness.model.config["http-port"],
        ),
    }

    # Act
    # Add one relation with data.  This should trigger a charm reconciliation due to
    # relation-changed.
    relation_metadata = add_sdi_relation_to_harness(harness, "kfp-ui", other_app="o1", data={})
    relation_ids_to_assert = [relation_metadata.rel_id]

    # Assert
    assert isinstance(harness.charm.kfp_ui_relation.status, ActiveStatus)
    assert_relation_data_send_as_expected(harness, expected_relation_data, relation_ids_to_assert)


def assert_relation_data_send_as_expected(
    harness: Harness, expected_relation_data: dict, rel_ids_to_assert: list
):
    """Asserts that we have sent the expected data to the given relations."""
    # Assert on the data we sent out to the other app for each relation.
    for rel_id in rel_ids_to_assert:
        relation_data = harness.get_relation_data(rel_id, harness.model.app)
        assert (
            yaml.safe_load(relation_data["_supported_versions"])
            == expected_relation_data["_supported_versions"]
        )
        assert yaml.safe_load(relation_data["data"]) == expected_relation_data["data"]


def test_pebble_services_running(harness: Harness, mocked_kubernetes_service_patch):
    """Test that the pebble services successfully start."""
    # Arrange
    harness.begin()
    harness.set_can_connect("ml-pipeline-ui", True)

    # Mock:
    # * leadership_gate to have get_status=>Active
    # * object_storage_relation to return mock data, making the item go active
    # * kfp_api_relation to return mock data, making the item go active
    harness.charm.leadership_gate.get_status = MagicMock(return_value=ActiveStatus())
    harness.charm.object_storage_relation.component.get_data = MagicMock(
        return_value=MOCK_OBJECT_STORAGE_DATA
    )
    harness.charm.kfp_api_relation.component.get_data = MagicMock(return_value=MOCK_KFP_API_DATA)

    # Act
    harness.charm.on.install.emit()

    # Assert
    container = harness.charm.unit.get_container("ml-pipeline-ui")
    service = container.get_service("ml-pipeline-ui")
    assert service.is_running()
    # Assert the environment variables that are set from inputs are correctly applied
    environment = container.get_plan().services["ml-pipeline-ui"].environment
    assert (
        environment["ALLOW_CUSTOM_VISUALIZATIONS"]
        == str(harness.charm.config.get("allow-custom-visualizations")).lower()
    )
    assert environment["HIDE_SIDENAV"] == str(harness.charm.config.get("hide-sidenav")).lower()
    assert environment["MINIO_HOST"] == MOCK_OBJECT_STORAGE_DATA["service"]
    assert environment["MINIO_NAMESPACE"] == MOCK_OBJECT_STORAGE_DATA["namespace"]
    assert environment["MINIO_PORT"] == MOCK_OBJECT_STORAGE_DATA["port"]
    assert environment["MINIO_SSL"] == MOCK_OBJECT_STORAGE_DATA["secure"]
    assert environment["ML_PIPELINE_SERVICE_HOST"] == MOCK_KFP_API_DATA["service-name"]
    assert environment["ML_PIPELINE_SERVICE_PORT"] == MOCK_KFP_API_DATA["service-port"]


@pytest.mark.parametrize(
    "add_ambient,add_sidecar",
    [
        (False, False),  # no relations
        (True, False),  # only ambient
        (False, True),  # only sidecar
    ],
)
def test_istio_relations_conflict_detector_active(
    harness: Harness,
    mocked_kubernetes_service_patch,
    add_ambient,
    add_sidecar,
):
    """Test conflict detector returns ActiveStatus when no conflict exists."""
    harness.begin()
    if add_ambient:
        harness.add_relation("istio-ingress-route", "istio-ingress")
    if add_sidecar:
        harness.add_relation("ingress", "istio-pilot")
    status = harness.charm.istio_relations_conflict_detector.component.get_status()
    assert isinstance(status, ActiveStatus)


def test_istio_relations_conflict_detector_both_relations(
    harness: Harness,
    mocked_kubernetes_service_patch,
):
    """Test conflict detector when both relations are present - should be blocked."""
    # Arrange
    harness.begin()

    # Act - Add both relations
    harness.add_relation("istio-ingress-route", "istio-ingress")
    harness.add_relation("ingress", "istio-pilot")

    # Assert
    status = harness.charm.istio_relations_conflict_detector.component.get_status()
    assert isinstance(status, BlockedStatus)
    assert "Cannot have both" in status.message
    assert "istio-ingress-route" in status.message
    assert "ingress" in status.message


@pytest.fixture
def harness() -> Harness:
    """Returns a Harness for the KfpUiOperator charm."""
    harness = Harness(KfpUiOperator)

    # set model name to avoid validation errors
    harness.set_model_name("kubeflow")

    # set leader by default
    harness.set_leader(True)

    yield harness

    harness.cleanup()


@pytest.fixture()
def mocked_kubernetes_service_patch(mocker):
    """Mocks the KubernetesServicePatch for the charm."""
    mocked_kubernetes_service_patch = mocker.patch(
        "charm.KubernetesServicePatch", lambda x, y, service_name: None
    )
    yield mocked_kubernetes_service_patch


def render_ingress_data(service: str, port: str) -> dict:
    """Returns typical data for the ingress relation."""
    return {
        "prefix": "/pipeline",
        "rewrite": "/pipeline",
        "service": service,
        "port": int(port),
    }


def render_kfp_ui_data(app_name: str, model_name: str, port: int) -> dict:
    """Returns typical data for the kfp-ui relation."""
    return {
        "service-name": f"{app_name}.{model_name}",
        "service-port": str(port),
    }
