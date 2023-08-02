# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.
import dataclasses
from typing import Optional
from unittest.mock import MagicMock

import pytest
import yaml
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


def test_not_leader(harness, mocked_lightkube_client):
    """Test when we are not the leader."""
    harness.begin_with_initial_hooks()
    # Assert that we are not Active, and that the leadership-gate is the cause.
    assert not isinstance(harness.charm.model.unit.status, ActiveStatus)
    assert harness.charm.model.unit.status.message.startswith("[leadership-gate]")


def test_kubernetes_created_method(harness, mocked_lightkube_client):
    """Test whether we try to create Kubernetes resources when we have leadership."""
    # Arrange
    # Needed because kubernetes component will only apply to k8s if we are the leader
    harness.set_leader(True)
    harness.begin()

    # Need to mock the leadership-gate to be active, and the kubernetes auth component so that it
    # sees the expected resources when calling _get_missing_kubernetes_resources

    harness.charm.leadership_gate.get_status = MagicMock(return_value=ActiveStatus())
    # TODO: This feels too broad.  Is there a better way to test/mock this?
    harness.charm.kubernetes_resources.component._get_missing_kubernetes_resources = MagicMock(
        return_value=[]
    )

    # Act
    harness.charm.on.install.emit()

    # Assert
    assert mocked_lightkube_client.apply.call_count == 2
    assert isinstance(harness.charm.kubernetes_resources.status, ActiveStatus)


def test_object_storage_relation_with_data(harness, mocked_lightkube_client):
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


def test_object_storage_relation_without_data(harness, mocked_lightkube_client):
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


def test_object_storage_relation_without_relation(harness, mocked_lightkube_client):
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


def test_kfp_api_relation_with_data(harness, mocked_lightkube_client):
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


def test_kfp_api_relation_without_data(harness, mocked_lightkube_client):
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


def test_kfp_api_relation_without_relation(harness, mocked_lightkube_client):
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


def test_ingress_relation_with_related_app(harness, mocked_lightkube_client):
    """Test that the kfp-api relation sends data to related apps and goes Active."""
    # Arrange
    harness.set_leader(True)  # needed to write to an SDI relation
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
    assert isinstance(harness.charm.ingress_relation.status, ActiveStatus)
    assert_relation_data_send_as_expected(harness, expected_relation_data, relation_ids_to_assert)


def test_kfp_ui_relation_with_related_app(harness, mocked_lightkube_client):
    """Test that the kfp-ui relation sends data to related apps and goes Active."""
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


def assert_relation_data_send_as_expected(harness, expected_relation_data, rel_ids_to_assert):
    """Asserts that we have sent the expected data to the given relations."""
    # Assert on the data we sent out to the other app for each relation.
    for rel_id in rel_ids_to_assert:
        relation_data = harness.get_relation_data(rel_id, harness.model.app)
        assert (
            yaml.safe_load(relation_data["_supported_versions"])
            == expected_relation_data["_supported_versions"]
        )
        assert yaml.safe_load(relation_data["data"]) == expected_relation_data["data"]


def test_pebble_services_running(harness, mocked_lightkube_client):
    """Test that if the Kubernetes Component is Active, the pebble services successfully start."""
    # Arrange
    harness.begin()
    harness.set_can_connect("ml-pipeline-ui", True)

    # Mock:
    # * leadership_gate to have get_status=>Active
    # * kubernetes_resources to have get_status=>Active
    # * object_storage_relation to return mock data, making the item go active
    # * kfp_api_relation to return mock data, making the item go active
    harness.charm.leadership_gate.get_status = MagicMock(return_value=ActiveStatus())
    harness.charm.kubernetes_resources.get_status = MagicMock(return_value=ActiveStatus())
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


@pytest.fixture
def harness() -> Harness:
    harness = Harness(KfpUiOperator)
    return harness


@pytest.fixture()
def mocked_lightkube_client(mocker):
    """Mocks the Lightkube Client in charm.py, returning a mock instead."""
    mocked_lightkube_client = MagicMock()
    mocker.patch("charm.lightkube.Client", return_value=mocked_lightkube_client)
    yield mocked_lightkube_client


# Helpers
def add_data_to_sdi_relation(
    harness: Harness,
    rel_id: int,
    app_name: str,
    data: Optional[dict] = None,
    supported_versions: str = "- v1",
) -> None:
    """Add data to an SDI-backed relation.

    Args:
        harness: the test harness in use
        rel_id: the relation id of the relation to add data to
        app_name: the name of the app who is adding data to the relation, typically the other app
        data: dict of the data to add
        supported_versions: yaml formatted string of SDI supported versions to add to the relation
    """
    if data is None:
        data = {}

    harness.update_relation_data(
        rel_id,
        app_name,
        {"_supported_versions": supported_versions, "data": yaml.dump(data)},
    )


@dataclasses.dataclass
class RelationMetadata:
    other_app: str
    other_unit: str
    rel_id: int
    data: dict


def add_sdi_relation_to_harness(
    harness: Harness, relation_name: str, other_app: str = "other", data: Optional[dict] = None
) -> RelationMetadata:
    """Relates a new app and unit to an sdi-formatted relation.

    Args:
        harness: the Harness to add a relation to
        relation_name: the name of the relation
        other_app: the name of the other app that is relating to our charm
        data: (optional) the data added to this relation

    Returns SdiRelationMetadata with:
    * other (str): The name of the other app
    * other_unit (str): The name of the other unit
    * rel_id (int): The relation id
    * data (dict): The relation data put to the relation
    """
    if data is None:
        data = {}

    other_unit = f"{other_app}/0"
    rel_id = harness.add_relation(relation_name, other_app)

    harness.add_relation_unit(rel_id, other_unit)

    add_data_to_sdi_relation(harness, rel_id, other_app, data)

    return RelationMetadata(
        other_app=other_app,
        other_unit=other_unit,
        rel_id=rel_id,
        data=data,
    )


def render_ingress_data(service, port) -> dict:
    """Returns typical data for the ingress relation."""
    return {
        "prefix": "/pipeline",
        "rewrite": "/pipeline",
        "service": service,
        "port": int(port),
    }


def render_kfp_ui_data(app_name, model_name, port) -> dict:
    """Returns typical data for the kfp-ui relation."""
    return {
        "service-name": f"{app_name}.{model_name}",
        "service-port": str(port),
    }
