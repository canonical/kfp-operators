# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.
from unittest.mock import MagicMock, patch

import pytest
import yaml
from charmed_kubeflow_chisme.testing import add_sdi_relation_to_harness
from charms.istio_ingress_k8s.v0.istio_ingress_route import (
    HTTPPathMatchType,
    IstioIngressRouteConfig,
    ProtocolType,
)
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
MOCK_S3_DATA = {
    "access-key": "s3-access-key",
    "secret-key": "s3-secret-key",
    "endpoint": "https://s3.example.com:443",
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
    """Test that the object storage relation is Active when a relation exists but has no data.

    The object-storage relation has minimum_related_applications=0, making it optional (a
    relation with s3-credentials is an alternative), so even an empty relation does not block
    the component.
    """
    # Arrange
    harness.begin()

    # Mock:
    # * leadership_gate to be active and executed
    harness.charm.leadership_gate.get_status = MagicMock(return_value=ActiveStatus())

    # Add relation with data.  This should trigger a charm reconciliation due to relation-changed.
    add_sdi_relation_to_harness(harness, "object-storage", data={})

    # Assert
    assert isinstance(harness.charm.object_storage_relation.status, ActiveStatus)


def test_object_storage_relation_without_relation(
    harness: Harness,
    mocked_kubernetes_service_patch,
):
    """Test that the object storage relation is Active when no relation is established.

    The object-storage relation has minimum_related_applications=0, making it optional (a
    relation with s3-credentials is an alternative). The s3-relations-conflict-detector is
    mocked Active here to isolate this component.
    """
    # Arrange
    harness.begin()

    # Mock:
    # * leadership_gate to be active and executed
    # * s3_relations_conflict_detector to be active
    harness.charm.leadership_gate.get_status = MagicMock(return_value=ActiveStatus())
    harness.charm.s3_relations_conflict_detector.get_status = MagicMock(
        return_value=ActiveStatus()
    )

    # Act
    harness.charm.on.install.emit()

    # Assert
    assert isinstance(harness.charm.object_storage_relation.status, ActiveStatus)


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


def test_pebble_services_running_object_storage(harness: Harness, mocked_kubernetes_service_patch):
    """Test that the pebble services successfully start with an object-storage."""
    # Arrange
    harness.begin()
    harness.set_can_connect("ml-pipeline-ui", True)

    # Mock:
    # * leadership_gate to have get_status=>Active
    # * s3_relations_conflict_detector to be active
    # * object_storage_relation to return mock data, making the item go active
    # * kfp_api_relation to return mock data, making the item go active
    harness.charm.leadership_gate.get_status = MagicMock(return_value=ActiveStatus())
    harness.charm.s3_relations_conflict_detector.get_status = MagicMock(
        return_value=ActiveStatus()
    )
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


def test_pebble_services_running_s3(harness: Harness, mocked_kubernetes_service_patch):
    """Test that the pebble services start with an s3-credentials relation.

    The MINIO_* frontend env is derived from the s3 endpoint, with the URL scheme stripped
    into a separate MINIO_SSL flag and an empty MINIO_NAMESPACE.
    """
    # Arrange
    harness.begin()
    harness.set_can_connect("ml-pipeline-ui", True)

    # Mock:
    # * leadership_gate to have get_status=>Active
    # * s3_relations_conflict_detector to be active
    # * s3_relation to return mock data, making the item go active
    # * kfp_api_relation to return mock data, making the item go active
    harness.charm.leadership_gate.get_status = MagicMock(return_value=ActiveStatus())
    harness.charm.s3_relations_conflict_detector.get_status = MagicMock(
        return_value=ActiveStatus()
    )
    harness.charm.s3_relation.get_status = MagicMock(return_value=ActiveStatus())
    harness.charm.s3_relation.component.get_data = MagicMock(return_value=[MOCK_S3_DATA])
    harness.charm.kfp_api_relation.component.get_data = MagicMock(return_value=MOCK_KFP_API_DATA)

    harness.add_relation("s3-credentials", "s3-provider")

    # Act
    harness.charm.on.install.emit()

    # Assert
    container = harness.charm.unit.get_container("ml-pipeline-ui")
    service = container.get_service("ml-pipeline-ui")
    assert service.is_running()
    environment = container.get_plan().services["ml-pipeline-ui"].environment
    assert environment["MINIO_HOST"] == "s3.example.com"
    assert environment["MINIO_NAMESPACE"] == ""
    assert environment["MINIO_PORT"] == 443
    assert environment["MINIO_SSL"] is True
    assert environment["ML_PIPELINE_SERVICE_HOST"] == MOCK_KFP_API_DATA["service-name"]
    assert environment["ML_PIPELINE_SERVICE_PORT"] == MOCK_KFP_API_DATA["service-port"]


@pytest.mark.parametrize(
    "add_s3_credentials, add_object_storage, expected_status",
    [
        pytest.param(False, False, BlockedStatus, id="no-relation"),
        pytest.param(True, False, ActiveStatus, id="s3-credentials-only"),
        pytest.param(False, True, ActiveStatus, id="object-storage-only"),
        pytest.param(True, True, BlockedStatus, id="both-relations"),
    ],
)
def test_s3_relations_conflict_detector_status(
    harness: Harness,
    mocked_kubernetes_service_patch,
    add_s3_credentials,
    add_object_storage,
    expected_status,
):
    """Test the conflict detector blocks unless exactly one storage relation is set.

    Exactly one of object-storage or s3-credentials must be present at a time:
    - none active  → Blocked
    - one active   → Active
    - both active  → Blocked
    """
    harness.begin()

    if add_s3_credentials:
        harness.add_relation("s3-credentials", "s3-provider")
    if add_object_storage:
        harness.add_relation("object-storage", "object-storage-provider")

    status = harness.charm.s3_relations_conflict_detector.component.get_status()
    assert isinstance(status, expected_status)


@pytest.mark.parametrize(
    "endpoint,expected",
    [
        # full URLs: scheme decides the TLS flag and default port
        ("http://10.0.0.1", ("10.0.0.1", 80, False)),
        ("https://s3.example.com", ("s3.example.com", 443, True)),
        ("http://10.0.0.1:9000", ("10.0.0.1", 9000, False)),
        ("https://s3.example.com:443", ("s3.example.com", 443, True)),
        # bare host[:port]: defaults to non-TLS
        ("10.0.0.1", ("10.0.0.1", 80, False)),
        ("minio.example:9000", ("minio.example", 9000, False)),
    ],
)
def test_parse_s3_endpoint(endpoint, expected):
    """Test that an s3 endpoint is split into (host, port, secure)."""
    assert KfpUiOperator._parse_s3_endpoint(endpoint) == expected


@pytest.mark.parametrize(
    "s3_data",
    [
        pytest.param([], id="empty-list"),
        pytest.param([{"access-key": "k"}], id="missing-fields"),
    ],
)
def test_get_object_storage_data_waits_when_s3_data_not_ready(
    harness: Harness,
    mocked_kubernetes_service_patch,
    s3_data,
):
    """Test that an empty/partial s3-credentials databag causes the unit to be blocked."""
    # Arrange
    harness.begin()
    harness.set_can_connect("ml-pipeline-ui", True)

    harness.charm.leadership_gate.get_status = MagicMock(return_value=ActiveStatus())
    harness.charm.s3_relations_conflict_detector.get_status = MagicMock(
        return_value=ActiveStatus()
    )
    harness.charm.s3_relation.get_status = MagicMock(return_value=ActiveStatus())
    harness.charm.s3_relation.component.get_data = MagicMock(return_value=s3_data)
    harness.charm.kfp_api_relation.component.get_data = MagicMock(return_value=MOCK_KFP_API_DATA)
    # An actual s3-credentials relation must exist so the active storage component is the s3 one
    harness.add_relation("s3-credentials", "s3-provider")

    # Act
    harness.charm.on.install.emit()

    # Assert
    assert isinstance(harness.charm.model.unit.status, BlockedStatus)


@pytest.mark.parametrize(
    "endpoint",
    [
        pytest.param("://", id="scheme-only"),
        pytest.param("http://", id="http-no-host"),
    ],
)
def test_get_object_storage_data_blocks_when_s3_endpoint_invalid(
    harness: Harness,
    mocked_kubernetes_service_patch,
    endpoint,
):
    """Test that a wrong s3 endpoint causes the unit to go to BlockedStatus.

    All required fields are present but the endpoint cannot be parsed to a valid host,
    so the error should propagate and the unit should end up in BlockedStatus.
    """
    # Arrange
    harness.begin()
    harness.set_can_connect("ml-pipeline-ui", True)

    harness.charm.leadership_gate.get_status = MagicMock(return_value=ActiveStatus())
    harness.charm.s3_relations_conflict_detector.get_status = MagicMock(
        return_value=ActiveStatus()
    )
    harness.charm.s3_relation.get_status = MagicMock(return_value=ActiveStatus())
    harness.charm.s3_relation.component.get_data = MagicMock(
        return_value=[{**MOCK_S3_DATA, "endpoint": endpoint}]
    )
    harness.charm.kfp_api_relation.component.get_data = MagicMock(return_value=MOCK_KFP_API_DATA)
    # An actual s3-credentials relation must exist so the active storage component is the s3 one
    harness.add_relation("s3-credentials", "s3-provider")

    # Act
    harness.charm.on.install.emit()

    # Assert
    assert isinstance(harness.charm.model.unit.status, BlockedStatus)


def test_get_object_storage_data_waits_when_object_storage_data_not_ready(
    harness: Harness,
    mocked_kubernetes_service_patch,
):
    """Test that an empty object-storage databag causes the unit to be blocked."""
    # Arrange
    harness.begin()
    harness.set_can_connect("ml-pipeline-ui", True)

    harness.charm.leadership_gate.get_status = MagicMock(return_value=ActiveStatus())
    harness.charm.s3_relations_conflict_detector.get_status = MagicMock(
        return_value=ActiveStatus()
    )
    harness.charm.object_storage_relation.component.get_data = MagicMock(return_value={})
    harness.charm.kfp_api_relation.component.get_data = MagicMock(return_value=MOCK_KFP_API_DATA)

    # Act
    harness.charm.on.install.emit()

    # Assert
    assert isinstance(harness.charm.model.unit.status, BlockedStatus)


def test_storage_relation_data_not_ready_blocks_unit_status(
    harness: Harness,
    mocked_kubernetes_service_patch,
):
    """Test that an s3-credentials relation with no data sets the unit to BlockedStatus."""
    # Arrange
    harness.begin()
    # leadership-gate must be Active so the storage components are reached during reconcile
    harness.charm.leadership_gate.get_status = MagicMock(return_value=ActiveStatus())
    # The relation exists, but the provider hasn't populated the databag yet
    harness.add_relation("s3-credentials", "s3-provider")

    # Act
    harness.charm.on.install.emit()

    # Assert
    assert harness.charm.model.unit.status == BlockedStatus(
        "[relation:s3_credentials] Relation 's3-credentials' is present but required data "
        "is not yet available."
    )


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


def test_istio_relations_conflict_detector_multiple_ambient_relations(
    harness: Harness,
    mocked_kubernetes_service_patch,
):
    """Test conflict detector handles multiple istio-ingress-route relations without erroring."""
    # Arrange
    harness.begin()

    # Act - Add more than one relation on the ambient ingress endpoint
    harness.add_relation("istio-ingress-route", "istio-ingress")
    harness.add_relation("istio-ingress-route", "istio-ingress-2")

    # Assert - inspecting the full list of relations per endpoint must not raise
    status = harness.charm.istio_relations_conflict_detector.component.get_status()
    assert isinstance(status, ActiveStatus)


def test_each_istio_ingress_route_relation_receives_config(
    harness: Harness,
    mocked_kubernetes_service_patch,
):
    """Test that an HTTPRoute config is submitted to every istio-ingress-route relation."""
    # Arrange
    harness.begin()

    rel_id_1 = harness.add_relation("istio-ingress-route", "istio-ingress")
    rel_id_2 = harness.add_relation("istio-ingress-route", "istio-ingress-2")

    # Use the real submit_config so we can inspect the databags; only force readiness.
    ingress = harness.charm.ambient_ingress_relation.component.ingress
    ingress.is_ready = MagicMock(return_value=True)

    # Act - reconcile the charm so the component submits its config.
    harness.charm.on.install.emit()

    # Assert
    # Each relation's application databag should contain a valid config that
    # defines the kfp-ui HTTPRoute, proving the lib handles every ingress.
    for rel_id in (rel_id_1, rel_id_2):
        app_data = harness.get_relation_data(rel_id, harness.charm.app.name)
        assert "config" in app_data

        config = IstioIngressRouteConfig.model_validate_json(app_data["config"])
        assert len(config.http_routes) == 1
        http_route = config.http_routes[0]
        assert http_route.matches[0].path.type == HTTPPathMatchType.PathPrefix
        assert http_route.matches[0].path.value == "/pipeline"
        assert http_route.backends[0].service == harness.charm.app.name
        assert http_route.backends[0].port == int(harness.charm.model.config["http-port"])
        # The route's parent (the Gateway listener referenced under parentRefs in
        # the HTTPRouteSpec) should be the expected HTTP listener.
        assert http_route.listener.name == "http-80"


@pytest.mark.parametrize("tls_enabled, expected_port", [(False, 80), (True, 443)])
def test_ambient_ingress_listener_port(
    harness: Harness,
    mocked_kubernetes_service_patch,
    tls_enabled,
    expected_port,
):
    """Test that the ambient ingress listener uses the correct port based on TLS setting."""
    harness.begin()
    component = harness.charm.ambient_ingress_relation.component
    component.ingress = MagicMock()
    component.ingress.tls_enabled = tls_enabled

    config = component._get_ingress_config()
    assert len(config.listeners) == 1
    assert config.listeners[0].port == expected_port
    assert config.listeners[0].protocol == ProtocolType.HTTP


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
