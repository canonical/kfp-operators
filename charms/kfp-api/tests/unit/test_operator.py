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
# * required relations missing block things
#   * object-storage
#   * optional kfp-viz
# * things happen when we have required
# * subscriber relations are optional, but they provide the expected data
# * where else can I look for tests?  notebook?  minio?
# * config_changed actually changes something?
# Test when SOMETHING raises CheckFailed that it hits the status properly.  Or, check it for everything (parameterize somehow?)

def test_mysql_relation(harness):
    harness.begin()

    # Test no relation
    with pytest.raises(CheckFailed) as no_relation:
        harness.charm._get_mysql()
    assert no_relation.value.status == BlockedStatus("Missing required relation for mysql")

    mysql_app = "mysql_app"
    mysql_unit = f"{mysql_app}/0"

    # Test relation with missing data
    rel_id = harness.add_relation("mysql", mysql_app)
    harness.add_relation_unit(rel_id, mysql_unit)
    with pytest.raises(CheckFailed) as no_relation_data:
        harness.charm._get_mysql()
    assert no_relation_data.value.status == WaitingStatus("Waiting for mysql relation data")

    # Test with partial data
    data = {"database": "database"}
    harness.update_relation_data(
        rel_id,
        mysql_unit,
        data
    )
    with pytest.raises(CheckFailed) as partial_relation_data:
        harness.charm._get_mysql()
    assert partial_relation_data.value.status == BlockedStatus("Received incomplete data from mysql relation.  See logs")

    # Test complete relation
    data = {
        "database": "database",
        "host": "host",
        "root_password": "root_password",
        "port": "port",
    }
    harness.update_relation_data(
        rel_id,
        mysql_unit,
        data
    )
    with does_not_raise():
        harness.charm._get_mysql()

    # Test too many relations
    rel_id_2 = harness.add_relation("mysql", "extra_sql")
    harness.add_relation_unit(rel_id_2, "extra_sql/0")
    with pytest.raises(CheckFailed) as too_many_relations:
        harness.charm._get_mysql()
    assert too_many_relations.value.status == BlockedStatus("Too many mysql relations")


def test_kfp_viz_relation(harness):
    harness.set_leader()  # Required for SDI relations
    harness.begin()

    viz_app = "kfp-viz"
    viz_unit = f"{viz_app}/0"
    default_viz_data = {"service-name": "unset", "service-port": "1234"}

    # Test no relation, returning default data
    # TODO: Mock this away?
    interfaces = harness.charm._get_interfaces()
    assert harness.charm._get_viz(interfaces) == default_viz_data

    # Test relation with no version data
    rel_id = harness.add_relation("kfp-viz", viz_app)
    harness.add_relation_unit(rel_id, viz_unit)
    with pytest.raises(CheckFailed) as no_version:
        interfaces = harness.charm._get_interfaces()
    assert no_version.value.status == WaitingStatus("List of kfp-viz versions not found for apps: kfp-viz")

    # Test with relation, version, and no data
    harness.update_relation_data(
        rel_id,
        viz_app,
        {"_supported_versions": '- v1'}
    )
    interfaces = harness.charm._get_interfaces()
    with pytest.raises(CheckFailed) as no_relation_data:
        harness.charm._get_viz(interfaces)
    assert no_relation_data.value.status == WaitingStatus("Waiting for kfp-viz relation data")

    # Test with partial data (empty)
    packaged_data = {"data": yaml.dump({})}
    harness.update_relation_data(
        rel_id,
        viz_app,
        packaged_data
    )
    with pytest.raises(CheckFailed) as partial_relation_data:
        harness.charm._get_viz(interfaces)
    assert partial_relation_data.value.status == WaitingStatus("Waiting for kfp-viz relation data")

    # Test with partial data
    packaged_data = {"data": yaml.dump({"service-name": "service-name"})}
    harness.update_relation_data(
        rel_id,
        viz_app,
        packaged_data
    )
    with pytest.raises(CheckFailed) as partial_relation_data:
        harness.charm._get_viz(interfaces)
    assert partial_relation_data.value.status == BlockedStatus("Found incomplete/incorrect relation data for 'kfp-viz'.  See logs")

    # Test complete relation
    data = {"service-name": "set", "service-port": "9876"}
    packaged_data = {"data": yaml.dump(data)}
    harness.update_relation_data(
        rel_id,
        viz_app,
        packaged_data
    )
    with does_not_raise():
        viz = harness.charm._get_viz(interfaces)
    assert viz == data


def test_too_many_mysql_relation(harness):
    assert False


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
