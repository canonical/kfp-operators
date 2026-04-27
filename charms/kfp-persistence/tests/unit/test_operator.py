# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

from unittest.mock import MagicMock, patch

import pytest
from charmed_kubeflow_chisme.exceptions import GenericCharmRuntimeError
from charmed_kubeflow_chisme.testing import add_sdi_relation_to_harness
from ops.model import ActiveStatus, BlockedStatus, WaitingStatus
from ops.testing import Harness

from charm import KfpPersistenceOperator

MOCK_KFP_API_HTTP_DATA = {"service-name": "service-name", "service-port": "1234"}
MOCK_KFP_API_GRPC_DATA = {"service-name": "service-name", "service-port": "5678"}
OTHER_APP_NAME = "kfp-api-provider"
RELATION_NAME_HTTP = "kfp-api"
RELATION_NAME_GRPC = "kfp-api-grpc"


@pytest.fixture
def harness():
    """Initialize Harness instance."""
    harness = Harness(KfpPersistenceOperator)
    harness.set_can_connect("persistenceagent", True)
    return harness


@pytest.fixture()
def mocked_kubernetes_client(mocker):
    """Mocks the kubernetes client in sa token component."""
    mocked_kubernetes_client = MagicMock()
    mocker.patch("charm.SATokenComponent.kubernetes_client")
    yield mocked_kubernetes_client


def test_log_forwarding(harness: Harness):
    with patch("charm.LogForwarder") as mock_logging:
        harness.begin()
        mock_logging.assert_called_once_with(charm=harness.charm)


def test_not_leader(harness: Harness):
    """Test not a leader scenario."""
    harness.begin_with_initial_hooks()
    assert harness.charm.model.unit.status == WaitingStatus(
        "[leadership-gate] Waiting for leadership"
    )


def test_kfp_api_http_relation_with_data(harness: Harness):
    """Test that if Leadership is Active, the kfp-api HTTP relation operates as expected."""
    # Arrange
    harness.begin()

    # Mock:
    # * leadership_gate_component_item to be active and executed
    harness.charm.leadership_gate.get_status = MagicMock(return_value=ActiveStatus())

    # Add relation with data.  This should trigger a charm reconciliation due to relation-changed.
    add_sdi_relation_to_harness(harness, "kfp-api", data=MOCK_KFP_API_HTTP_DATA)

    # Assert
    assert isinstance(harness.charm.kfp_api_http_relation.status, ActiveStatus)


def test_kfp_api_http_relation_without_data(harness: Harness):
    """Test that the kfp-api HTTP relation goes Blocked if no data is available."""
    # Arrange
    harness.begin()

    # Mock:
    # * leadership_gate_component_item to be active and executed
    harness.charm.leadership_gate.get_status = MagicMock(return_value=ActiveStatus())

    # Add relation with data.  This should trigger a charm reconciliation due to relation-changed.
    add_sdi_relation_to_harness(harness, "kfp-api", data={})

    # Assert
    assert isinstance(harness.charm.kfp_api_http_relation.status, BlockedStatus)


def test_kfp_api_http_relation_without_relation(harness: Harness):
    """Test that the kfp-api HTTP relation goes Blocked if no relation is established."""
    # Arrange
    harness.begin()

    # Mock:
    # * leadership_gate_component_item to be active and executed
    harness.charm.leadership_gate.get_status = MagicMock(return_value=ActiveStatus())

    # Act
    harness.charm.on.install.emit()

    # Assert
    assert isinstance(harness.charm.kfp_api_http_relation.status, BlockedStatus)


def test_kfp_api_grpc_relation_with_data(harness: Harness):
    """Test that the kfp-api GRPC relation operates as expected with data."""
    # Arrange
    harness.begin()

    # Mock:
    # * leadership_gate_component_item to be active and executed
    harness.charm.leadership_gate.get_status = MagicMock(return_value=ActiveStatus())

    # Add relation with data.  This should trigger a charm reconciliation due to relation-changed.
    add_sdi_relation_to_harness(harness, "kfp-api-grpc", data=MOCK_KFP_API_GRPC_DATA)

    # Assert
    assert isinstance(harness.charm.kfp_api_grpc_relation.status, ActiveStatus)


def test_kfp_api_grpc_relation_without_data(harness: Harness):
    """Test that the kfp-api GRPC relation is optional and can be empty."""
    # Arrange
    harness.begin()

    # Mock:
    # * leadership_gate_component_item to be active and executed
    harness.charm.leadership_gate.get_status = MagicMock(return_value=ActiveStatus())

    # Act - GRPC relation is optional, so it should be Active even without data
    harness.charm.on.install.emit()

    # Assert - The GRPC relation has minimum_related_applications=0, so it should be Active
    assert isinstance(harness.charm.kfp_api_grpc_relation.status, ActiveStatus)


def test_service_mesh_component(harness: Harness):
    """Test that the service mesh component is initialized and returns Active status."""
    # Arrange
    harness.begin()

    # Mock:
    # * leadership_gate_component_item to be active and executed
    harness.charm.leadership_gate.get_status = MagicMock(return_value=ActiveStatus())

    # Act
    harness.charm.on.install.emit()

    # Assert
    assert isinstance(harness.charm.service_mesh.status, ActiveStatus)


def test_no_sa_token_file(harness: Harness, mocked_kubernetes_client):
    """Test the unit status when the SA token file is missing."""
    harness.begin()
    harness.set_can_connect("persistenceagent", True)

    harness.charm.leadership_gate.get_status = MagicMock(return_value=ActiveStatus())
    add_sdi_relation_to_harness(harness, "kfp-api", data=MOCK_KFP_API_HTTP_DATA)
    harness.charm.kfp_api_http_relation.component.get_data = MagicMock(
        return_value=MOCK_KFP_API_HTTP_DATA
    )

    with pytest.raises(GenericCharmRuntimeError) as err:
        harness.charm.sa_token.get_status()

    service_account_name = harness.charm.model.app.name
    assert (
        err.value.msg
        == f"Token file for {service_account_name} ServiceAccount not present in charm."
    )
    # The base charm arbitrarily sets the unit status to BlockedStatus
    # We should fix this in charmed-kubeflow-chisme as it doesn't really
    # show the actual error and can be misleading
    assert isinstance(harness.charm.unit.status, BlockedStatus)
    assert (
        harness.charm.unit.status.message
        == "[sa-token:persistenceagent] Failed to compute status.  See logs for details."
    )


@patch("charm.SA_TOKEN_FULL_PATH", "tests/unit/data/persistenceagent-sa-token")
def test_pebble_services_running(harness: Harness):
    """Test that the pebble services successfully start."""
    # Arrange
    harness.begin()
    harness.set_can_connect("persistenceagent", True)

    # Mock:
    # * leadership_gate_component_item to be active and executed
    # * kfp_api_http_relation_component to be active and executed, and have data that can be
    #   returned
    harness.charm.leadership_gate.get_status = MagicMock(return_value=ActiveStatus())
    harness.charm.sa_token.get_status = MagicMock(return_value=ActiveStatus())
    harness.charm.kfp_api_http_relation.component.get_data = MagicMock(
        return_value=MOCK_KFP_API_HTTP_DATA
    )
    harness.charm.kfp_api_grpc_relation.component.get_data = MagicMock(
        return_value=[MOCK_KFP_API_GRPC_DATA]
    )

    # Act
    harness.charm.on.install.emit()

    # Assert
    container = harness.charm.unit.get_container("persistenceagent")
    service = container.get_service("persistenceagent")
    assert service.is_running()

    # Assert the environment variables that are set from inputs are correctly applied
    environment = container.get_plan().services["persistenceagent"].environment
    assert environment["NAMESPACE"] == ""
    assert environment["MULTIUSER"] == "true"
    assert environment["KUBEFLOW_USERID_HEADER"] == "kubeflow-userid"
    assert environment["KUBEFLOW_USERID_PREFIX"] == ""
    assert environment["LOG_LEVEL"] == harness.charm.config["log-level"]
    assert environment["TTL_SECONDS_AFTER_WORKFLOW_FINISH"] == "86400"
    assert environment["NUM_WORKERS"] == "2"
    assert environment["EXECUTIONTYPE"] == "Workflow"


@pytest.mark.parametrize(
    "relation_data,expected_port",
    [
        ({"service-port": "9999"}, 9999),
        ({}, 8888),
    ],
)
def test_kfp_api_http_port(harness: Harness, relation_data, expected_port):
    """Test that the HTTP port is correctly retrieved from relation or defaults to 8888."""
    harness.begin()

    harness.charm.kfp_api_http_relation.component.get_data = MagicMock(return_value=relation_data)
    assert harness.charm.kfp_api_http_port == expected_port


@pytest.mark.parametrize(
    "relation_data,expected_port",
    [
        ([{"service-port": "7777"}], 7777),
        ({}, 8887),
    ],
)
def test_kfp_api_grpc_port(harness: Harness, relation_data, expected_port):
    """Test that the GRPC port is correctly retrieved from relation or defaults to 8887."""
    harness.begin()

    harness.charm.kfp_api_grpc_relation.component.get_data = MagicMock(return_value=relation_data)
    assert harness.charm.kfp_api_grpc_port == expected_port
