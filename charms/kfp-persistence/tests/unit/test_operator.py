# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

from typing import Optional
from unittest.mock import MagicMock

import pytest
import yaml
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


def test_not_leader(
    harness,  # noqa F811
):
    """Test not a leader scenario."""
    harness.begin_with_initial_hooks()
    assert harness.charm.model.unit.status == WaitingStatus(
        "[leadership-gate] Waiting for leadership"
    )


RELATION_NAME = "kfp-api"
OTHER_APP_NAME = "kfp-api-provider"


def test_kfp_api_relation_with_data(harness):
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


def test_kfp_api_relation_without_data(harness):
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


def test_kfp_api_relation_without_relation(harness):
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


def test_pebble_services_running(harness):
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
    harness.charm.kfp_api_relation.component.get_data = MagicMock(return_value=MOCK_KFP_API_DATA)

    # Act
    harness.charm.on.install.emit()

    # Assert
    container = harness.charm.unit.get_container("persistenceagent")
    service = container.get_service("persistenceagent")
    assert service.is_running()

    # Assert the environment variables that are set from inputs are correctly applied
    environment = container.get_plan().services["persistenceagent"].environment
    assert environment["KUBEFLOW_USERID_HEADER"] == "kubeflow-userid"


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


def add_sdi_relation_to_harness(
    harness: Harness, relation_name: str, other_app: str = "other", data: Optional[dict] = None
) -> dict:
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
