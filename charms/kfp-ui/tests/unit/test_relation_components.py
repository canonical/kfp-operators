"""This is an alternative approach to testing the Relation Components.

Instead of testing them within the main charm, this uses smaller tester charms in a more unit-test
like style.  This could be extended to the other relation Component unit tests as well.

Pros:
* no need to mock the rest of the charm - in this style, the rest of the charm does not exist.
  This is helpful especially for testing something that relies on another component - effectively
  we can mock away that dependency and just pass data directly.  This might be more readable
* as other parts of the charm change, these tests won't need to.  For example, normally if we added
  a Component in our charm ahead of these Relation Components, we'd have to refactor the tests to
  add another mock.  But in this style, we don't.

Cons:
* there's duplication here between the mock charms below and the real Charm's __init__.  That
  is extra work and could go out of sync.
  * that duplication could get large, say if we mocked the MlPipelineUiPebbleService this way.
"""

from pathlib import Path
from typing import Optional

import pytest
import yaml
from charmed_kubeflow_chisme.components import CharmReconciler, SdiRelationDataReceiverComponent
from ops.charm import CharmBase
from ops.model import ActiveStatus, BlockedStatus
from ops.testing import Harness

MOCK_OBJECT_STORAGE_DATA = {
    "access-key": "access-key",
    "secret-key": "secret-key",
    "service": "service",
    "namespace": "namespace",
    "port": 1234,
    "secure": True,
}
MOCK_KFP_API_DATA = {"service-name": "service-name", "service-port": "1234"}


def test_object_storage_relation_with_data(harness_for_object_storage_relation):
    """Test that if Leadership is Active, the object storage relation operates as expected."""
    # Arrange
    harness = harness_for_object_storage_relation
    harness.begin()

    # Add relation with data.  This should trigger a charm reconciliation due to relation-changed.
    add_sdi_relation_to_harness(harness, "object-storage", data=MOCK_OBJECT_STORAGE_DATA)

    # Assert
    assert isinstance(harness.charm.object_storage_relation_component.status, ActiveStatus)


def test_object_storage_relation_without_data(harness_for_object_storage_relation):
    """Test that the object storage relation goes Blocked if no data is available."""
    # Arrange
    harness = harness_for_object_storage_relation
    harness.begin()

    # Add relation with data.  This should trigger a charm reconciliation due to relation-changed.
    add_sdi_relation_to_harness(harness, "object-storage", data={})

    # Assert
    assert isinstance(harness.charm.object_storage_relation_component.status, BlockedStatus)


def test_object_storage_relation_without_relation(harness_for_object_storage_relation):
    """Test that the object storage relation goes Blocked if no relation is established."""
    # Arrange
    harness = harness_for_object_storage_relation
    harness.begin()

    # Act
    harness.charm.on.install.emit()

    # Assert
    assert isinstance(harness.charm.object_storage_relation_component.status, BlockedStatus)


def test_kfp_api_relation_with_data(harness_for_kfp_api_relation):
    """Test that if Leadership is Active, the kfp-api relation operates as expected."""
    # Arrange
    harness = harness_for_kfp_api_relation
    harness.begin()

    # Add relation with data.  This should trigger a charm reconciliation due to relation-changed.
    add_sdi_relation_to_harness(harness, "kfp-api", data=MOCK_KFP_API_DATA)

    # Assert
    assert isinstance(harness.charm.kfp_api_relation_component.status, ActiveStatus)


def test_kfp_api_relation_without_data(harness_for_kfp_api_relation):
    """Test that the kfp-api relation goes Blocked if no data is available."""
    # Arrange
    harness = harness_for_kfp_api_relation
    harness.begin()

    # Add relation with data.  This should trigger a charm reconciliation due to relation-changed.
    add_sdi_relation_to_harness(harness, "kfp-api", data={})

    # Assert
    assert isinstance(harness.charm.kfp_api_relation_component.status, BlockedStatus)


def test_kfp_api_relation_without_relation(harness_for_kfp_api_relation):
    """Test that the kfp-api relation goes Blocked if no relation is established."""
    # Arrange
    harness = harness_for_kfp_api_relation
    harness.begin()

    # Act
    harness.charm.on.install.emit()

    # Assert
    assert isinstance(harness.charm.kfp_api_relation_component.status, BlockedStatus)


class MockCharmForObjectStorageRelation(CharmBase):
    def __init__(self, *args):
        super().__init__(*args)
        self.charm_executor = CharmReconciler(self)

        self.object_storage_relation_component = self.charm_executor.add(
            component=SdiRelationDataReceiverComponent(
                charm=self,
                name="relation:object_storage",
                relation_name="object-storage",
            ),
        )

        self.charm_executor.install_default_event_handlers()


@pytest.fixture
def harness_for_object_storage_relation() -> Harness:
    # Must specify meta because Harness by default introspects the path to metadata.yaml from
    # the root path of the Charm class, which here will be in /tests/... not where metadata.yaml
    # actually is.
    harness = Harness(MockCharmForObjectStorageRelation, meta=Path("./metadata.yaml").read_text())
    return harness


class MockCharmForKfpApiRelation(CharmBase):
    def __init__(self, *args):
        super().__init__(*args)
        self.charm_executor = CharmReconciler(self)

        self.kfp_api_relation_component = self.charm_executor.add(
            component=SdiRelationDataReceiverComponent(
                charm=self,
                name="relation:kfp-api",
                relation_name="kfp-api",
            ),
        )

        self.charm_executor.install_default_event_handlers()


@pytest.fixture
def harness_for_kfp_api_relation() -> Harness:
    # Must specify meta because Harness by default introspects the path to metadata.yaml from
    # the root path of the Charm class, which here will be in /tests/... not where metadata.yaml
    # actually is.
    harness = Harness(MockCharmForKfpApiRelation, meta=Path("./metadata.yaml").read_text())
    return harness


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
