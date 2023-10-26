# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

from unittest.mock import MagicMock, patch

import pytest
from charmed_kubeflow_chisme.exceptions import GenericCharmRuntimeError
from charmed_kubeflow_chisme.testing import add_sdi_relation_to_harness
from ops.model import ActiveStatus, BlockedStatus, WaitingStatus
from ops.testing import Harness

from charm import KfpPersistenceOperator

MOCK_KFP_API_DATA = {"service-name": "service-name", "service-port": "1234"}


@pytest.fixture
def harness():
    """Initialize Harness instance."""
    harness = Harness(KfpPersistenceOperator)
    harness.set_can_connect("persistenceagent", True)
    return harness


@pytest.fixture()
def mocked_lightkube_client(mocker):
    """Mocks the Lightkube Client in charm.py, returning a mock instead."""
    mocked_lightkube_client = MagicMock()
    mocker.patch("charm.lightkube.Client", return_value=mocked_lightkube_client)
    yield mocked_lightkube_client


@pytest.fixture()
def mocked_kubernetes_client(mocker):
    """Mocks the kubernetes client in sa token component."""
    mocked_kubernetes_client = MagicMock()
    mocker.patch("charm.SaTokenComponent.kubernetes_client")
    yield mocked_kubernetes_client


def test_not_leader(harness, mocked_lightkube_client):
    """Test not a leader scenario."""
    harness.begin_with_initial_hooks()
    assert harness.charm.model.unit.status == WaitingStatus(
        "[leadership-gate] Waiting for leadership"
    )


RELATION_NAME = "kfp-api"
OTHER_APP_NAME = "kfp-api-provider"


def test_kfp_api_relation_with_data(harness, mocked_lightkube_client):
    """Test that if Leadership is Active, the kfp-api relation operates as expected."""
    # Arrange
    harness.begin()

    # Mock:
    # * leadership_gate_component_item to be active and executed
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
    # * leadership_gate_component_item to be active and executed
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
    # * leadership_gate_component_item to be active and executed
    harness.charm.leadership_gate.get_status = MagicMock(return_value=ActiveStatus())

    # Act
    harness.charm.on.install.emit()

    # Assert
    assert isinstance(harness.charm.kfp_api_relation.status, BlockedStatus)


def test_no_sa_token_file(harness, mocked_kubernetes_client, mocked_lightkube_client):
    """Test the unit status when the SA token file is missing."""
    harness.begin()
    harness.set_can_connect("persistenceagent", True)

    harness.charm.leadership_gate.get_status = MagicMock(return_value=ActiveStatus())
    harness.charm.kubernetes_resources.component.get_status = MagicMock(
        return_value=ActiveStatus()
    )
    add_sdi_relation_to_harness(harness, "kfp-api", data=MOCK_KFP_API_DATA)
    harness.charm.kfp_api_relation.component.get_data = MagicMock(return_value=MOCK_KFP_API_DATA)

    with pytest.raises(GenericCharmRuntimeError) as err:
        harness.charm.sa_token.get_status()

    assert err.value.msg == "SA token file is not present in charm"
    # The base charm arbitrarily sets the unit status to BlockedStatus
    # We should fix this in charmed-kubeflow-chisme as it doesn't really
    # show the actual error and can be misleading
    assert isinstance(harness.charm.unit.status, BlockedStatus)
    assert (
        harness.charm.unit.status.message
        == "[sa-token:persistenceagent] Failed to compute status.  See logs for details."
    )


@patch("charm.SA_TOKEN_FULL_PATH", "tests/unit/data/persistenceagent-sa-token")
def test_pebble_services_running(harness, mocked_lightkube_client):
    """Test that if the Kubernetes Component is Active, the pebble services successfully start."""
    # Arrange
    harness.begin()
    harness.set_can_connect("persistenceagent", True)

    # Mock:
    # * leadership_gate_component_item to be active and executed
    # * kubernetes_resources_component_item to be active and executed
    # * object_storage_relation_component to be active and executed, and have data that can be
    #   returned
    harness.charm.leadership_gate.get_status = MagicMock(return_value=ActiveStatus())
    harness.charm.sa_token.get_status = MagicMock(return_value=ActiveStatus())
    harness.charm.kfp_api_relation.component.get_data = MagicMock(return_value=MOCK_KFP_API_DATA)

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
    assert environment["TTL_SECONDS_AFTER_WORKFLOW_FINISH"] == "86400"
    assert environment["NUM_WORKERS"] == "2"
