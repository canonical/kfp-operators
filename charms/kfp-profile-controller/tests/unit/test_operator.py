# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

from base64 import b64decode
from contextlib import nullcontext as does_not_raise

import pytest
import yaml
from oci_image import MissingResourceError
from ops.model import ActiveStatus, BlockedStatus, WaitingStatus
from ops.testing import Harness

from charm import CheckFailedError, KfpProfileControllerOperator

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

    harness.begin_with_initial_hooks()

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

    pod_spec = harness.get_pod_spec()
    pod_spec_secrets = pod_spec[1]["kubernetesResources"]["secrets"]
    pod_spec_secret_key = pod_spec_secrets[0]["data"]["MINIO_SECRET_KEY"]

    assert b64decode(pod_spec_secret_key).decode("utf-8") == "secret-key"

    # confirm that we can serialize the pod spec and that the unit is active
    yaml.safe_dump(harness.get_pod_spec())
    assert harness.charm.model.unit.status == ActiveStatus()


@pytest.fixture
def harness():
    return Harness(KfpProfileControllerOperator)


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
