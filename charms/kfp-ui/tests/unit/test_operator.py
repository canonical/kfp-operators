# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

from base64 import b64decode
from contextlib import nullcontext as does_not_raise
from typing import Optional
from unittest.mock import MagicMock, patch, PropertyMock

import ops
import pytest
import yaml
from oci_image import MissingResourceError
from ops.model import ActiveStatus, BlockedStatus, WaitingStatus
from ops.testing import Harness

from charm import CheckFailedError, KfpUiOperator
from charmed_kubeflow_chisme.components import ComponentGraphItem

# TODO: Tests missing for config_changed and dropped/reloaded relations and relations where this
#  charm provides data to the other application
# TODO: test ingress relation (receive data)
# TODO: test kfp-ui (provide data)

# ops.testing.SIMULATE_CAN_CONNECT = True

MOCK_OBJECT_STORAGE_DATA = {'access-key': 'access-key', 'secret-key': 'secret-key', "service": "service", "namespace": "namespace", "port": 1234, "secure": True,}
MOCK_KFP_API_DATA = {"service-name": "service-name", "service-port": "1234"}


def test_not_leader(harness, mocked_lightkube_client):
    """Test when we are not the leader."""
    harness.begin_with_initial_hooks()
    assert harness.charm.model.unit.status == WaitingStatus("[leadership-gate] Waiting for leadership")


def test_kubernetes_created_method_1(harness, mocked_lightkube_client):
    """Test whether we try to create Kubernetes resources when we have leadership.

    This test is implemented via two methods for mocking to see how they both feel.
    This example is mocked by directly overwriting methods in the ComponentItem/Component instances
    """
    # Arrange
    # Needed because kubernetes component will only apply to k8s if we are the leader
    harness.set_leader(True)
    harness.begin()

    # Need to mock the leadership-gate to be active, and the kubernetes auth component so that it
    # sees the expected resources when calling _get_missing_kubernetes_resources

    harness.charm.leadership_gate_component_item.executed = True
    harness.charm.leadership_gate_component_item.get_status = MagicMock(return_value=ActiveStatus())
    # TODO: This feels too broad.  Is there a better way to test/mock this?
    harness.charm.kubernetes_resources_component_item.component._get_missing_kubernetes_resources = MagicMock(return_value=[])

    # Act
    harness.charm.on.install.emit()

    # Assert
    assert mocked_lightkube_client.apply.call_count == 2
    assert isinstance(harness.charm.kubernetes_resources_component_item.status, ActiveStatus)


def test_kubernetes_created_method_2(harness, mocked_lightkube_client):
    """Test whether we try to create Kubernetes resources when we have leadership.

    This test is implemented via two methods for mocking to see how they both feel.
    This example is mocked by using patch.object to patch the methods temporarily.
    """

    # Arrange
    # Needed because kubernetes component will only apply to k8s if we are the leader
    harness.set_leader(True)
    harness.begin()

    # Need to mock the leadership-gate to be active, and the kubernetes auth component so that it
    # sees the expected resources when calling _get_missing_kubernetes_resources
    harness.charm.leadership_gate_component_item.executed = True
    # In python 3.9, we don't need to nest the with blocks
    with patch.object(harness.charm.leadership_gate_component_item, "get_status", return_value=ActiveStatus()):
        # TODO: This feels too broad.  Is there a better way to test/mock this?
        with patch.object(harness.charm.kubernetes_resources_component_item.component, "_get_missing_kubernetes_resources", return_value=[]):
            # Act
            harness.charm.on.install.emit()

            # Assert
            assert mocked_lightkube_client.apply.call_count == 2
            assert isinstance(harness.charm.kubernetes_resources_component_item.status, ActiveStatus)


def test_object_storage_relation_with_data(harness, mocked_lightkube_client):
    """Test that if Leadership is Active, the object storage relation operates as expected."""
    # Arrange
    harness.begin()

    # Mock:
    # * leadership_gate_component_item to be active and executed
    harness.charm.leadership_gate_component_item.executed = True
    harness.charm.leadership_gate_component_item.get_status = MagicMock(return_value=ActiveStatus())

    # Add relation with data.  This should trigger a charm reconciliation due to relation-changed.
    add_sdi_relation_to_harness(harness, "object-storage", data=MOCK_OBJECT_STORAGE_DATA)

    # Assert
    assert isinstance(harness.charm.object_storage_relation_component.status, ActiveStatus)


def test_object_storage_relation_without_data(harness, mocked_lightkube_client):
    """Test that the object storage relation goes Blocked if no data is available."""
    # Arrange
    harness.begin()

    # Mock:
    # * leadership_gate_component_item to be active and executed
    harness.charm.leadership_gate_component_item.executed = True
    harness.charm.leadership_gate_component_item.get_status = MagicMock(return_value=ActiveStatus())

    # Add relation with data.  This should trigger a charm reconciliation due to relation-changed.
    add_sdi_relation_to_harness(harness, "object-storage", data={})

    # Assert
    assert isinstance(harness.charm.object_storage_relation_component.status, BlockedStatus)


def test_object_storage_relation_without_relation(harness, mocked_lightkube_client):
    """Test that the object storage relation goes Blocked if no relation is established."""
    # Arrange
    harness.begin()

    # Mock:
    # * leadership_gate_component_item to be active and executed
    harness.charm.leadership_gate_component_item.executed = True
    harness.charm.leadership_gate_component_item.get_status = MagicMock(return_value=ActiveStatus())

    # Act
    harness.charm.on.install.emit()

    # Assert
    assert isinstance(harness.charm.object_storage_relation_component.status, BlockedStatus)


def test_kfp_api_relation_with_data(harness, mocked_lightkube_client):
    """Test that if Leadership is Active, the kfp-api relation operates as expected."""
    # Arrange
    harness.begin()

    # Mock:
    # * leadership_gate_component_item to be active and executed
    harness.charm.leadership_gate_component_item.executed = True
    harness.charm.leadership_gate_component_item.get_status = MagicMock(return_value=ActiveStatus())

    # Add relation with data.  This should trigger a charm reconciliation due to relation-changed.
    add_sdi_relation_to_harness(harness, "kfp-api", data=MOCK_KFP_API_DATA)

    # Assert
    assert isinstance(harness.charm.kfp_api_relation_component.status, ActiveStatus)


def test_kfp_api_relation_without_data(harness, mocked_lightkube_client):
    """Test that the kfp-api relation goes Blocked if no data is available."""
    # Arrange
    harness.begin()

    # Mock:
    # * leadership_gate_component_item to be active and executed
    harness.charm.leadership_gate_component_item.executed = True
    harness.charm.leadership_gate_component_item.get_status = MagicMock(return_value=ActiveStatus())

    # Add relation with data.  This should trigger a charm reconciliation due to relation-changed.
    add_sdi_relation_to_harness(harness, "kfp-api", data={})

    # Assert
    assert isinstance(harness.charm.kfp_api_relation_component.status, BlockedStatus)


def test_kfp_api_relation_without_relation(harness, mocked_lightkube_client):
    """Test that the kfp-api relation goes Blocked if no relation is established."""
    # Arrange
    harness.begin()

    # Mock:
    # * leadership_gate_component_item to be active and executed
    harness.charm.leadership_gate_component_item.executed = True
    harness.charm.leadership_gate_component_item.get_status = MagicMock(return_value=ActiveStatus())

    # Act
    harness.charm.on.install.emit()

    # Assert
    assert isinstance(harness.charm.kfp_api_relation_component.status, BlockedStatus)


def test_pebble_services_running(harness, mocked_lightkube_client):
    """Test that if the Kubernetes Component is Active, the pebble services successfully start."""
    # Arrange
    harness.begin()
    harness.set_can_connect("ml-pipeline-ui", True)

    # Mock:
    # * leadership_gate_component_item to be active and executed
    # * kubernetes_resources_component_item to be active and executed
    # * object_storage_relation_component to be active and executed, and have data that can be
    #   returned
    harness.charm.leadership_gate_component_item.executed = True
    harness.charm.leadership_gate_component_item.get_status = MagicMock(return_value=ActiveStatus())
    harness.charm.kubernetes_resources_component_item.executed = True
    harness.charm.kubernetes_resources_component_item.get_status = MagicMock(return_value=ActiveStatus())
    harness.charm.object_storage_relation_component.executed = True
    harness.charm.object_storage_relation_component.component.get_data = MagicMock(return_value=MOCK_OBJECT_STORAGE_DATA)
    harness.charm.kfp_api_relation_component.executed = True
    harness.charm.kfp_api_relation_component.component.get_data = MagicMock(return_value=MOCK_KFP_API_DATA)

    # Act
    harness.charm.on.install.emit()

    # Assert
    container = harness.charm.unit.get_container("ml-pipeline-ui")
    service = container.get_service("ml-pipeline-ui")
    assert service.is_running()
    # Assert the environment variables that are set from inputs are correctly applied
    environment = container.get_plan().services['ml-pipeline-ui'].environment
    assert environment["ALLOW_CUSTOM_VISUALIZATIONS"] == str(harness.charm.config.get("allow-custom-visualizations")).lower()
    assert environment["HIDE_SIDENAV"] == str(harness.charm.config.get("hide-sidenav")).lower()
    # assert environment["minio_secret"] == str({"secret": {"name": f"{harness.charm.app.name}-minio-secret"}})
    assert environment["MINIO_HOST"] == MOCK_OBJECT_STORAGE_DATA["service"]
    assert environment["MINIO_NAMESPACE"] == MOCK_OBJECT_STORAGE_DATA["namespace"]
    assert environment["MINIO_PORT"] == MOCK_OBJECT_STORAGE_DATA["port"]
    assert environment["MINIO_SSL"] == MOCK_OBJECT_STORAGE_DATA["secure"]
    assert environment["ML_PIPELINE_SERVICE_HOST"] == MOCK_KFP_API_DATA["service-name"]
    assert environment["ML_PIPELINE_SERVICE_PORT"] == MOCK_KFP_API_DATA["service-port"]


# def test_image_fetch(harness, oci_resource_data):
#     harness.begin()
#     with pytest.raises(MissingResourceError):
#         harness.charm.image.fetch()
#
#     harness.add_oci_resource(**oci_resource_data)
#     with does_not_raise():
#         harness.charm.image.fetch()


# @pytest.mark.parametrize(
#     "relation_name,relation_data,expected_returned_data,expected_raises,expected_status",
#     (
#         # Object storage
#         (
#             # No relation established.  Raises CheckFailedError
#             "object-storage",
#             None,
#             None,
#             pytest.raises(CheckFailedError),
#             BlockedStatus("Missing required relation for object-storage"),
#         ),
#         (
#             # Relation exists but no versions set yet
#             "object-storage",
#             {},
#             None,
#             pytest.raises(CheckFailedError),
#             WaitingStatus(
#                 "List of <ops.model.Relation object-storage:0> versions not found for apps:"
#                 " other-app"
#             ),
#         ),
#         (
#             # Relation exists with versions, but no data posted yet
#             "object-storage",
#             {"_supported_versions": "- v1"},
#             None,
#             pytest.raises(CheckFailedError),
#             WaitingStatus("Waiting for object-storage relation data"),
#         ),
#         (
#             # Relation exists with versions and empty data
#             "object-storage",
#             {"_supported_versions": "- v1", "data": yaml.dump({})},
#             None,
#             pytest.raises(CheckFailedError),
#             WaitingStatus("Waiting for object-storage relation data"),
#         ),
#         (
#             # Relation exists with versions and invalid (partial) data
#             "object-storage",
#             {
#                 "_supported_versions": "- v1",
#                 "data": yaml.dump({"service-name": "service-name"}),
#             },
#             None,
#             pytest.raises(CheckFailedError),
#             BlockedStatus("Failed to validate data on object-storage:0 from other-app"),
#         ),
#         (
#             # Relation exists with valid data
#             "object-storage",
#             {
#                 "_supported_versions": "- v1",
#                 "data": yaml.dump(
#                     {
#                         "access-key": "access-key",
#                         "namespace": "namespace",
#                         "port": 1234,
#                         "secret-key": "secret-key",
#                         "secure": True,
#                         "service": "service",
#                     }
#                 ),
#             },
#             {
#                 "access-key": "access-key",
#                 "namespace": "namespace",
#                 "port": 1234,
#                 "secret-key": "secret-key",
#                 "secure": True,
#                 "service": "service",
#             },
#             does_not_raise(),
#             None,
#         ),
#         # kfp-api
#         (
#             # No relation established.  Raises CheckFailedError
#             "kfp-api",
#             None,
#             None,
#             pytest.raises(CheckFailedError),
#             BlockedStatus("Missing required relation for kfp-api"),
#         ),
#         (
#             # Relation exists but no versions set yet
#             "kfp-api",
#             {},
#             None,
#             pytest.raises(CheckFailedError),
#             WaitingStatus(
#                 "List of <ops.model.Relation kfp-api:0> versions not found for apps: other-app"
#             ),
#         ),
#         (
#             # Relation exists with versions, but no data posted yet
#             "kfp-api",
#             {"_supported_versions": "- v1"},
#             None,
#             pytest.raises(CheckFailedError),
#             WaitingStatus("Waiting for kfp-api relation data"),
#         ),
#         (
#             # Relation exists with versions and empty data
#             "kfp-api",
#             {"_supported_versions": "- v1", "data": yaml.dump({})},
#             None,
#             pytest.raises(CheckFailedError),
#             WaitingStatus("Waiting for kfp-api relation data"),
#         ),
#         (
#             # Relation exists with versions and invalid (partial) data
#             "kfp-api",
#             {
#                 "_supported_versions": "- v1",
#                 "data": yaml.dump({"service-name": "service-name"}),
#             },
#             None,
#             pytest.raises(CheckFailedError),
#             BlockedStatus("Failed to validate data on kfp-api:0 from other-app"),
#         ),
#         (
#             # Relation exists with valid data
#             "kfp-api",
#             {
#                 "_supported_versions": "- v1",
#                 "data": yaml.dump(
#                     {
#                         "service-name": "service-name",
#                         "service-port": "1234",
#                     }
#                 ),
#             },
#             {
#                 "service-name": "service-name",
#                 "service-port": "1234",
#             },
#             does_not_raise(),
#             None,
#         ),
#     ),
# )
# def test_relations_that_provide_data(
#     harness,
#     relation_name,
#     relation_data,
#     expected_returned_data,
#     expected_raises,
#     expected_status,
# ):
#     harness.set_leader()
#     harness.begin()
#
#     other_app = "other-app"
#     other_unit = f"{other_app}/0"
#
#     if relation_data is not None:
#         rel_id = harness.add_relation(relation_name, other_app)
#         harness.add_relation_unit(rel_id, other_unit)
#         harness.update_relation_data(rel_id, other_app, relation_data)
#
#     with expected_raises as partial_relation_data:
#         interfaces = harness.charm._get_interfaces()
#         data = harness.charm._validate_sdi_interface(interfaces, relation_name)
#     if expected_status is None:
#         assert data == expected_returned_data
#     else:
#         assert partial_relation_data.value.status == expected_status


# def test_install_with_all_inputs(harness, oci_resource_data):
#     harness.set_leader()
#     http_port = "1234"
#     model_name = "test_model"
#     harness.set_model_name(model_name)
#     harness.update_config({"http-port": http_port})
#
#     kfpui_relation_name = "kfp-ui"
#     ingress_relation_name = "ingress"
#
#     harness.set_leader()
#
#     # Set up required relations
#     # Future: convert these to fixtures and share with the tests above
#     harness.add_oci_resource(**oci_resource_data)
#
#     # object storage relation
#     os_data = {
#         "_supported_versions": "- v1",
#         "data": yaml.dump(
#             {
#                 "access-key": "minio-access-key",
#                 "namespace": "namespace",
#                 "port": 1234,
#                 "secret-key": "minio-super-secret-key",
#                 "secure": True,
#                 "service": "service",
#             }
#         ),
#     }
#     os_rel_id = harness.add_relation("object-storage", "storage-provider")
#     harness.add_relation_unit(os_rel_id, "storage-provider/0")
#     harness.update_relation_data(os_rel_id, "storage-provider", os_data)
#
#     # kfp-api relation
#     kfpapi_data = {
#         "_supported_versions": "- v1",
#         "data": yaml.dump(
#             {
#                 "service-name": "service-name",
#                 "service-port": "1234",
#             }
#         ),
#     }
#     os_rel_id = harness.add_relation("kfp-api", "kfp-api-provider")
#     harness.add_relation_unit(os_rel_id, "kfp-api-provider/0")
#     harness.update_relation_data(os_rel_id, "kfp-api-provider", kfpapi_data)
#
#     relation_version_data = {"_supported_versions": "- v1"}
#
#     # example kfp-ui provider relation
#     kfpui_rel_id = harness.add_relation(kfpui_relation_name, f"{kfpui_relation_name}-subscriber")
#     harness.add_relation_unit(kfpui_rel_id, f"{kfpui_relation_name}-subscriber/0")
#     harness.update_relation_data(
#         kfpui_rel_id, f"{kfpui_relation_name}-subscriber", relation_version_data
#     )
#
#     # example ingress provider relation
#     ingress_rel_id = harness.add_relation(
#         ingress_relation_name, f"{ingress_relation_name}-subscriber"
#     )
#     harness.add_relation_unit(ingress_rel_id, f"{ingress_relation_name}-subscriber/0")
#     harness.update_relation_data(
#         ingress_rel_id, f"{ingress_relation_name}-subscriber", relation_version_data
#     )
#
#     harness.begin_with_initial_hooks()
#     this_app_name = harness.charm.model.app.name
#
#     # Test that we sent expected data to kfp-api relation
#     kfpui_expected_versions = ["v1"]
#     kfpui_expected_data = {
#         "service-name": f"{this_app_name}.{model_name}",
#         "service-port": http_port,
#     }
#     kfpui_sent_data = harness.get_relation_data(kfpui_rel_id, this_app_name)
#     assert yaml.safe_load(kfpui_sent_data["_supported_versions"]) == kfpui_expected_versions
#     assert yaml.safe_load(kfpui_sent_data["data"]) == kfpui_expected_data
#
#     # Test that we sent expected data to ingress relation
#     ingress_expected_versions = ["v1"]
#     ingress_expected_data = {
#         "prefix": "/pipeline",
#         "rewrite": "/pipeline",
#         "service": f"{this_app_name}",
#         "port": int(http_port),
#     }
#     ingress_sent_data = harness.get_relation_data(ingress_rel_id, this_app_name)
#     assert yaml.safe_load(ingress_sent_data["_supported_versions"]) == ingress_expected_versions
#     assert yaml.safe_load(ingress_sent_data["data"]) == ingress_expected_data
#
#     # confirm that we can serialize the pod spec and that the unit is active
#     pod_spec = harness.get_pod_spec()
#     yaml.safe_dump(pod_spec)
#     assert harness.charm.model.unit.status == ActiveStatus()
#
#     # assert minio secrets are setup correctly
#     charm_name = harness.model.app.name
#     secrets = pod_spec[0]["kubernetesResources"]["secrets"]
#     minio_secrets = [s for s in secrets if s["name"] == f"{charm_name}-minio-secret"][0]
#     assert (
#         pod_spec[0]["containers"][0]["envConfig"]["minio-secret"]["secret"]["name"]
#         == minio_secrets["name"]
#     )
#     assert (
#         b64decode(minio_secrets["data"]["MINIO_ACCESS_KEY"]).decode("utf-8") == "minio-access-key"
#     )
#     assert (
#         b64decode(minio_secrets["data"]["MINIO_SECRET_KEY"]).decode("utf-8")
#         == "minio-super-secret-key"
#     )


@pytest.fixture
def harness() -> Harness:
    harness = Harness(KfpUiOperator)
    # harness.set_can_connect("ml-pipeline-ui")
    return harness


# @pytest.fixture
# def oci_resource_data():
#     return {
#         "resource_name": "oci-image",
#         "contents": {
#             "registrypath": "ci-test",
#             "username": "",
#             "password": "",
#         },
#     }


@pytest.fixture()
def mocked_lightkube_client(mocker):
    """Mocks the Lightkube Client in charm.py, returning a mock instead."""
    mocked_lightkube_client = MagicMock()
    mocked_lightkube_client_class = mocker.patch("charm.lightkube.Client", return_value=mocked_lightkube_client)
    yield mocked_lightkube_client


# Helpers
def add_data_to_sdi_relation(
        harness: Harness,
        rel_id: int,
        other: str,
        data: Optional[dict] = None,
        supported_versions: str = "- v1",
) -> None:
    """Add data to an SDI-backed relation."""
    if data is None:
        data = {}

    harness.update_relation_data(
        rel_id,
        other,
        {"_supported_versions": supported_versions, "data": yaml.dump(data)},
    )


def add_sdi_relation_to_harness(harness: Harness, relation_name: str, other_app: str = "other", data: Optional[dict] = None) -> dict:
    """Relates a new app and unit to an sdi-formatted relation.

    Args:
        harness: the Harness to add a relation to
        relation_name: the name of the relation
        other_app: the name of the other app that is relating to our charm
        data: (optional) the data added to this relation

    Returns dict of:
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

    return {
        "other_app": other_app,
        "other_unit": other_unit,
        "rel_id": rel_id,
        "data": data,
    }
