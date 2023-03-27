# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

from contextlib import nullcontext as does_not_raise

import ops
import pytest
import yaml
from oci_image import MissingResourceError
from ops.model import ActiveStatus, BlockedStatus, TooManyRelatedAppsError, WaitingStatus
from ops.testing import Harness

from charm import CheckFailedError, KfpApiOperator

# TODO: Tests missing for config_changed and dropped/reloaded relations

ops.testing.SIMULATE_CAN_CONNECT = True


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


@pytest.mark.parametrize(
    "relation_data,expected_returned_data,expected_raises,expected_status",
    (
        (
            # No relation established.  Raises CheckFailedError
            None,
            None,
            pytest.raises(CheckFailedError),
            BlockedStatus("Missing required relation for mysql"),
        ),
        (
            # Relation exists but no data posted yet
            {},
            None,
            pytest.raises(CheckFailedError),
            WaitingStatus("Waiting for mysql relation data"),
        ),
        (
            # Relation exists with only partial data
            {"database": "database"},
            None,
            pytest.raises(CheckFailedError),
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

    with pytest.raises(TooManyRelatedAppsError):
        harness.charm._get_mysql()


def test_kfp_viz_relation_missing(harness):
    harness.set_leader()
    harness.begin()

    default_viz_data = {"service-name": "unset", "service-port": "1234"}

    # Could mock this away, but looked complicated
    interfaces = harness.charm._get_interfaces()
    assert harness.charm._get_viz(interfaces) == default_viz_data


@pytest.mark.parametrize(
    "relation_name,relation_data,expected_returned_data,expected_raises,expected_status",
    (
        # Object storage
        # No relation established.  Raises CheckFailedError
        (
            "object-storage",
            None,
            None,
            pytest.raises(CheckFailedError),
            BlockedStatus("Missing required relation for object-storage"),
        ),
        (
            # Relation exists but no versions set yet
            "object-storage",
            {},
            None,
            pytest.raises(CheckFailedError),
            WaitingStatus("List of object-storage versions not found for apps: other-app"),
        ),
        (
            # Relation exists with versions, but no data posted yet
            "object-storage",
            {"_supported_versions": "- v1"},
            None,
            pytest.raises(CheckFailedError),
            WaitingStatus("Waiting for object-storage relation data"),
        ),
        (
            # Relation exists with versions and empty data
            "object-storage",
            {"_supported_versions": "- v1", "data": yaml.dump({})},
            None,
            pytest.raises(CheckFailedError),
            BlockedStatus("Found incomplete/incorrect relation data for object-storage."),
        ),
        (
            # Relation exists with versions and invalid (partial) data
            "object-storage",
            {
                "_supported_versions": "- v1",
                "data": yaml.dump({"service-name": "service-name"}),
            },
            None,
            pytest.raises(CheckFailedError),
            BlockedStatus(
                "Found incomplete/incorrect relation data for object-storage.  See logs"
            ),
        ),
        (
            # Relation exists with valid data
            "object-storage",
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
        # kfp-viz
        # No relation established.  Raises CheckFailedError
        (
            "kfp-viz",
            None,
            None,
            pytest.raises(CheckFailedError),
            BlockedStatus("Missing required relation for kfp-viz"),
        ),
        (
            # Relation exists but no versions set yet
            "kfp-viz",
            {},
            None,
            pytest.raises(CheckFailedError),
            WaitingStatus("List of kfp-viz versions not found for apps: other-app"),
        ),
        (
            # Relation exists with versions, but no data posted yet
            "kfp-viz",
            {"_supported_versions": "- v1"},
            None,
            pytest.raises(CheckFailedError),
            WaitingStatus("Waiting for kfp-viz relation data"),
        ),
        (
            # Relation exists with versions and empty data
            "kfp-viz",
            {"_supported_versions": "- v1", "data": yaml.dump({})},
            None,
            pytest.raises(CheckFailedError),
            BlockedStatus("Found incomplete/incorrect relation data for kfp-viz."),
        ),
        (
            # Relation exists with versions and invalid (partial) data
            "kfp-viz",
            {
                "_supported_versions": "- v1",
                "data": yaml.dump({"service-name": "service-name"}),
            },
            None,
            pytest.raises(CheckFailedError),
            BlockedStatus("Found incomplete/incorrect relation data for kfp-viz.  See logs"),
        ),
        (
            # Relation exists with valid data
            "kfp-viz",
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
def test_relations_that_provide_data(
    harness,
    relation_name,
    relation_data,
    expected_returned_data,
    expected_raises,
    expected_status,
):
    harness.set_leader()
    harness.begin()

    other_app = "other-app"
    other_unit = f"{other_app}/0"

    if relation_data is not None:
        rel_id = harness.add_relation(relation_name, other_app)
        harness.add_relation_unit(rel_id, other_unit)
        harness.update_relation_data(rel_id, other_app, relation_data)

    with expected_raises as partial_relation_data:
        interfaces = harness.charm._get_interfaces()
        data = harness.charm._validate_sdi_interface(interfaces, relation_name)
    if expected_status is None:
        assert data == expected_returned_data
    else:
        assert partial_relation_data.value.status == expected_status


def test_install_with_all_inputs(harness, oci_resource_data):
    harness.set_leader()
    kfpapi_relation_name = "kfp-api"
    model_name = "test_model"
    service_port = "8888"
    harness.set_model_name(model_name)
    harness.update_config({"http-port": service_port})

    # Set up required relations
    # Future: convert these to fixtures and share with the tests above
    harness.add_oci_resource(**oci_resource_data)

    # mysql relation
    mysql_data = {
        "database": "database",
        "host": "host",
        "root_password": "root_password",
        "port": "port",
    }
    mysql_rel_id = harness.add_relation("mysql", "mysql-provider")
    harness.add_relation_unit(mysql_rel_id, "mysql-provider/0")
    harness.update_relation_data(mysql_rel_id, "mysql-provider/0", mysql_data)

    # object storage relation
    os_data = {
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
    }
    os_rel_id = harness.add_relation("object-storage", "storage-provider")
    harness.add_relation_unit(os_rel_id, "storage-provider/0")
    harness.update_relation_data(os_rel_id, "storage-provider", os_data)

    # example kfp-api provider relation
    kfpapi_data = {
        "_supported_versions": "- v1",
    }
    kfpapi_rel_id = harness.add_relation(kfpapi_relation_name, "kfp-api-subscriber")
    harness.add_relation_unit(kfpapi_rel_id, "kfp-api-subscriber/0")
    harness.update_relation_data(kfpapi_rel_id, "kfp-api-subscriber", kfpapi_data)

    harness.begin_with_initial_hooks()
    this_app_name = harness.charm.model.app.name

    # Test that we sent data to anyone subscribing to us
    kfpapi_expected_versions = ["v1"]
    kfpapi_expected_data = {
        "service-name": f"{this_app_name}.{model_name}",
        "service-port": service_port,
    }
    kfpapi_sent_data = harness.get_relation_data(kfpapi_rel_id, "kfp-api")
    assert yaml.safe_load(kfpapi_sent_data["_supported_versions"]) == kfpapi_expected_versions
    assert yaml.safe_load(kfpapi_sent_data["data"]) == kfpapi_expected_data

    # confirm that we can serialize the pod spec and that the unit is active
    yaml.safe_dump(harness.get_pod_spec())
    assert harness.charm.model.unit.status == ActiveStatus()


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
