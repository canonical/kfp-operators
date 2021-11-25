# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

from contextlib import nullcontext as does_not_raise
import pytest
import yaml

from oci_image import MissingResourceError
from ops.model import ActiveStatus, BlockedStatus, WaitingStatus
from ops.testing import Harness

from charm import KfpApiOperator, CheckFailed


def test_not_leader(harness):
    harness.begin_with_initial_hooks()
    assert harness.charm.model.unit.status == WaitingStatus("Waiting for leadership")


def test_image_fetch(harness, oci_resource_data):
    harness.begin()
    with pytest.raises(MissingResourceError):
        harness.charm.image.fetch()

    harness.add_oci_resource(**oci_resource_data)
    with does_not_raise():
        harness.charm.image.fetch()

    # harness.begin_with_initial_hooks()
    # assert harness.charm.model.unit.status == BlockedStatus(
    #     "Missing resource: oci-image"
    # )


# Tests to do:
# * things happen when we have required
# * subscriber relations are optional, but they provide the expected data
# * config_changed actually changes something?
# Test when SOMETHING raises CheckFailed that it hits the status properly.  Or, check it for everything (parameterize somehow?)


@pytest.mark.parametrize(
    "relation_data,expected_returned_data,expected_raises,expected_status",
    (
        (
            # No relation established.  Raises CheckFailed
            None,
            None,
            pytest.raises(CheckFailed),
            BlockedStatus("Missing required relation for mysql"),
        ),
        (
            # Relation exists but no data posted yet
            {},
            None,
            pytest.raises(CheckFailed),
            WaitingStatus("Waiting for mysql relation data"),
        ),
        (
            # Relation exists with only partial data
            {"database": "database"},
            None,
            pytest.raises(CheckFailed),
            BlockedStatus("Received incomplete data from mysql relation.  See logs"),
        ),
        (
            # Relation complete
            {
                "database": "database",
                "host": "host",
                "root_password": "root_password",
                "port": "port",
            },
            {
                "database": "database",
                "host": "host",
                "root_password": "root_password",
                "port": "port",
            },
            does_not_raise(),
            None,
        ),
    ),
)
def test_mysql_relation(
    harness, relation_data, expected_returned_data, expected_raises, expected_status
):
    harness.begin()

    mysql_app = "mysql_app"
    mysql_unit = f"{mysql_app}/0"

    rel_id = harness.add_relation("mysql", mysql_app)
    harness.add_relation_unit(rel_id, mysql_unit)

    # Test complete relation
    data = {
        "database": "database",
        "host": "host",
        "root_password": "root_password",
        "port": "port",
    }
    harness.update_relation_data(rel_id, mysql_unit, data)
    with does_not_raise():
        harness.charm._get_mysql()


def test_mysql_relation_too_many_relations(harness):
    harness.begin()

    mysql_app = "mysql_app"
    mysql_unit = f"{mysql_app}/0"

    rel_id = harness.add_relation("mysql", mysql_app)
    harness.add_relation_unit(rel_id, mysql_unit)
    rel_id_2 = harness.add_relation("mysql", "extra_sql")
    harness.add_relation_unit(rel_id_2, "extra_sql/0")

    with pytest.raises(CheckFailed) as too_many_relations:
        harness.charm._get_mysql()
    assert too_many_relations.value.status == BlockedStatus("Too many mysql relations")


def test_kfp_viz_relation_missing(harness):
    harness.set_leader()
    harness.begin()

    default_viz_data = {"service-name": "unset", "service-port": "1234"}

    # Could mock this away, but looked complicated
    interfaces = harness.charm._get_interfaces()
    assert harness.charm._get_viz(interfaces) == default_viz_data


@pytest.mark.parametrize(
    "relation_data,expected_returned_data,expected_raises,expected_status",
    (
        # No relation established.  Returns default value
        (
            None,
            {"service-name": "unset", "service-port": "1234"},
            does_not_raise(),
            None,
        ),
        (
            # Relation exists but no versions set yet
            {},
            None,
            pytest.raises(CheckFailed),
            WaitingStatus("List of kfp-viz versions not found for apps: kfp-viz"),
        ),
        (
            # Relation exists with versions, but no data posted yet
            {"_supported_versions": "- v1"},
            None,
            pytest.raises(CheckFailed),
            WaitingStatus("Waiting for kfp-viz relation data"),
        ),
        (
            # Relation exists with versions and empty data
            {"_supported_versions": "- v1", "data": yaml.dump({})},
            None,
            pytest.raises(CheckFailed),
            BlockedStatus("Found incomplete/incorrect relation data for kfp-viz."),
        ),
        (
            # Relation exists with versions and invalid (partial) data
            {
                "_supported_versions": "- v1",
                "data": yaml.dump({"service-name": "service-name"}),
            },
            None,
            pytest.raises(CheckFailed),
            BlockedStatus(
                "Found incomplete/incorrect relation data for kfp-viz.  See logs"
            ),
        ),
        (
            # Relation exists with valid data
            {
                "_supported_versions": "- v1",
                "data": yaml.dump({"service-name": "set", "service-port": "9876"}),
            },
            {"service-name": "set", "service-port": "9876"},
            does_not_raise(),
            None,
        ),
    ),
)
def test_kfp_viz_relation(
    harness, relation_data, expected_returned_data, expected_raises, expected_status
):
    harness.set_leader()
    harness.begin()

    viz_app = "kfp-viz"
    viz_unit = f"{viz_app}/0"

    if relation_data is not None:
        rel_id = harness.add_relation("kfp-viz", viz_app)
        harness.add_relation_unit(rel_id, viz_unit)
        harness.update_relation_data(rel_id, viz_app, relation_data)

    with expected_raises as partial_relation_data:
        interfaces = harness.charm._get_interfaces()
        viz = harness.charm._get_viz(interfaces)
    if expected_status is None:
        assert viz == expected_returned_data
    else:
        assert partial_relation_data.value.status == expected_status


@pytest.mark.parametrize(
    "relation_data,expected_returned_data,expected_raises,expected_status",
    (
        # No relation established.  Raises CheckFailed
        (
            None,
            None,
            pytest.raises(CheckFailed),
            BlockedStatus("Missing required relation for object-storage"),
        ),
        (
            # Relation exists but no versions set yet
            {},
            None,
            pytest.raises(CheckFailed),
            WaitingStatus("List of object-storage versions not found for apps: minio"),
        ),
        (
            # Relation exists with versions, but no data posted yet
            {"_supported_versions": "- v1"},
            None,
            pytest.raises(CheckFailed),
            WaitingStatus("Waiting for object-storage relation data"),
        ),
        (
            # Relation exists with versions and empty data
            {"_supported_versions": "- v1", "data": yaml.dump({})},
            None,
            pytest.raises(CheckFailed),
            BlockedStatus(
                "Found incomplete/incorrect relation data for object-storage."
            ),
        ),
        (
            # Relation exists with versions and invalid (partial) data
            {
                "_supported_versions": "- v1",
                "data": yaml.dump({"service-name": "service-name"}),
            },
            None,
            pytest.raises(CheckFailed),
            BlockedStatus(
                "Found incomplete/incorrect relation data for object-storage.  See logs"
            ),
        ),
        (
            # Relation exists with valid data
            {
                "_supported_versions": "- v1",
                "data": yaml.dump(
                    {
                        "access-key": "access-key",
                        "namespace": "namespace",
                        "port": 1234,
                        "secret-key": "secret-key",
                        "secure": True,
                        "service": "service",
                    }
                ),
            },
            {
                "access-key": "access-key",
                "namespace": "namespace",
                "port": 1234,
                "secret-key": "secret-key",
                "secure": True,
                "service": "service",
            },
            does_not_raise(),
            None,
        ),
    ),
)
def test_object_storage_relation(
    harness, relation_data, expected_returned_data, expected_raises, expected_status
):
    harness.set_leader()
    harness.begin()

    relation_name = "object-storage"
    other_app = "minio"
    other_unit = f"{other_app}/0"

    if relation_data is not None:
        rel_id = harness.add_relation(relation_name, other_app)
        harness.add_relation_unit(rel_id, other_unit)
        harness.update_relation_data(rel_id, other_app, relation_data)

    with expected_raises as partial_relation_data:
        interfaces = harness.charm._get_interfaces()
        data = harness.charm._get_object_storage(interfaces)
    if expected_status is None:
        assert data == expected_returned_data
    else:
        assert partial_relation_data.value.status == expected_status


@pytest.fixture
def harness():
    return Harness(KfpApiOperator)


@pytest.fixture
def oci_resource_data():
    return {
        "resource_name": "oci-image",
        "contents": {
            "registrypath": "ci-test",
            "username": "",
            "password": "",
        },
    }
