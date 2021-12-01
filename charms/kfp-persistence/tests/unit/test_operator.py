# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

from contextlib import nullcontext as does_not_raise

import pytest
import yaml
from oci_image import MissingResourceError
from ops.model import ActiveStatus, BlockedStatus, WaitingStatus
from ops.testing import Harness

from charm import CheckFailedError, KfpPersistenceOperator

# TODO: Tests missing for dropped/reloaded relations


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


RELATION_NAME = "kfp-api"
OTHER_APP_NAME = "kfp-api-provider"


@pytest.mark.parametrize(
    "relation_data,expected_returned_data,expected_raises,expected_status",
    (
        # No relation established.  Raises CheckFailedError
        (
            None,
            None,
            pytest.raises(CheckFailedError),
            BlockedStatus(f"Missing required relation for {RELATION_NAME}"),
        ),
        (
            # Relation exists but no versions set yet
            {},
            None,
            pytest.raises(CheckFailedError),
            WaitingStatus(
                f"List of {RELATION_NAME} versions not found for apps: {OTHER_APP_NAME}"
            ),
        ),
        (
            # Relation exists with versions, but no data posted yet
            {"_supported_versions": "- v1"},
            None,
            pytest.raises(CheckFailedError),
            WaitingStatus(f"Waiting for {RELATION_NAME} relation data"),
        ),
        (
            # Relation exists with versions and empty data
            {"_supported_versions": "- v1", "data": yaml.dump({})},
            None,
            pytest.raises(CheckFailedError),
            BlockedStatus(f"Found incomplete/incorrect relation data for {RELATION_NAME}."),
        ),
        (
            # Relation exists with versions and invalid (partial) data
            {
                "_supported_versions": "- v1",
                "data": yaml.dump({"service-name": "service-name"}),
            },
            None,
            pytest.raises(CheckFailedError),
            BlockedStatus(
                f"Found incomplete/incorrect relation data for {RELATION_NAME}.  See logs"
            ),
        ),
        (
            # Relation exists with valid data
            {
                "_supported_versions": "- v1",
                "data": yaml.dump({"service-name": "service-name", "service-port": "1928"}),
            },
            {"service-name": "service-name", "service-port": "1928"},
            does_not_raise(),
            None,
        ),
    ),
)
def test_kfp_api_relation(
    harness, relation_data, expected_returned_data, expected_raises, expected_status
):
    harness.set_leader()
    harness.begin()

    relation_name = RELATION_NAME
    other_app = OTHER_APP_NAME
    other_unit = f"{other_app}/0"

    if relation_data is not None:
        rel_id = harness.add_relation(relation_name, other_app)
        harness.add_relation_unit(rel_id, other_unit)
        harness.update_relation_data(rel_id, other_app, relation_data)

    with expected_raises as partial_relation_data:
        interfaces = harness.charm._get_interfaces()
        data = harness.charm._get_kfpapi(interfaces)
    if expected_status is None:
        assert data == expected_returned_data
    else:
        assert partial_relation_data.value.status == expected_status


@pytest.mark.parametrize(
    "relation_name,relation_data,expected_returned_data,expected_raises,expected_status",
    (
        # kfp-api
        # No relation established.  Raises CheckFailedError
        (
            "kfp-api",
            None,
            None,
            pytest.raises(CheckFailedError),
            BlockedStatus("Missing required relation for kfp-api"),
        ),
        (
            # Relation exists but no versions set yet
            "kfp-api",
            {},
            None,
            pytest.raises(CheckFailedError),
            WaitingStatus("List of kfp-api versions not found for apps: other-app"),
        ),
        (
            # Relation exists with versions, but no data posted yet
            "kfp-api",
            {"_supported_versions": "- v1"},
            None,
            pytest.raises(CheckFailedError),
            WaitingStatus("Waiting for kfp-api relation data"),
        ),
        (
            # Relation exists with versions and empty data
            "kfp-api",
            {"_supported_versions": "- v1", "data": yaml.dump({})},
            None,
            pytest.raises(CheckFailedError),
            BlockedStatus("Found incomplete/incorrect relation data for kfp-api."),
        ),
        (
            # Relation exists with versions and invalid (partial) data
            "kfp-api",
            {
                "_supported_versions": "- v1",
                "data": yaml.dump({"service-name": "service-name"}),
            },
            None,
            pytest.raises(CheckFailedError),
            BlockedStatus("Found incomplete/incorrect relation data for kfp-api.  See logs"),
        ),
        (
            # Relation exists with valid data
            "kfp-api",
            {
                "_supported_versions": "- v1",
                "data": yaml.dump(
                    {
                        "service-name": "service-name",
                        "service-port": "1234",
                    }
                ),
            },
            {
                "service-name": "service-name",
                "service-port": "1234",
            },
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
    model_name = "test_model"
    service_port = "8888"
    harness.set_model_name(model_name)
    harness.update_config({"service-port": service_port})

    # Set up required relations
    # Future: convert these to fixtures and share with the tests above
    harness.add_oci_resource(**oci_resource_data)

    # kfp-api relation data
    os_data = {
        "_supported_versions": "- v1",
        "data": yaml.dump(
            {
                "service-name": "some-service.some-namespace",
                "service-port": "1928",
            }
        ),
    }
    os_rel_id = harness.add_relation("kfp-api", "kfp-api-provider")
    harness.add_relation_unit(os_rel_id, "kfp-api-provider/0")
    harness.update_relation_data(os_rel_id, "kfp-api-provider", os_data)

    harness.begin_with_initial_hooks()

    # confirm that we can serialize the pod spec and that the unit is active
    yaml.safe_dump(harness.get_pod_spec())
    assert harness.charm.model.unit.status == ActiveStatus()


@pytest.fixture
def harness():
    return Harness(KfpPersistenceOperator)


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
