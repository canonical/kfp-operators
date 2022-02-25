# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

from base64 import b64decode
from contextlib import nullcontext as does_not_raise

import pytest
import yaml
from oci_image import MissingResourceError
from ops.model import ActiveStatus, BlockedStatus, WaitingStatus
from ops.testing import Harness

from charm import CheckFailedError, KfpUiOperator

# TODO: Tests missing for config_changed and dropped/reloaded relations and relations where this
#  charm provides data to the other application
# TODO: test ingress relation (receive data)
# TODO: test kfp-ui (provide data)


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
    http_port = "1234"
    model_name = "test_model"
    harness.set_model_name(model_name)
    harness.update_config({"http-port": http_port})

    kfpui_relation_name = "kfp-ui"
    ingress_relation_name = "ingress"

    harness.set_leader()

    # Set up required relations
    # Future: convert these to fixtures and share with the tests above
    harness.add_oci_resource(**oci_resource_data)

    # object storage relation
    os_data = {
        "_supported_versions": "- v1",
        "data": yaml.dump(
            {
                "access-key": "minio-access-key",
                "namespace": "namespace",
                "port": 1234,
                "secret-key": "minio-super-secret-key",
                "secure": True,
                "service": "service",
            }
        ),
    }
    os_rel_id = harness.add_relation("object-storage", "storage-provider")
    harness.add_relation_unit(os_rel_id, "storage-provider/0")
    harness.update_relation_data(os_rel_id, "storage-provider", os_data)

    # kfp-api relation
    kfpapi_data = {
        "_supported_versions": "- v1",
        "data": yaml.dump(
            {
                "service-name": "service-name",
                "service-port": "1234",
            }
        ),
    }
    os_rel_id = harness.add_relation("kfp-api", "kfp-api-provider")
    harness.add_relation_unit(os_rel_id, "kfp-api-provider/0")
    harness.update_relation_data(os_rel_id, "kfp-api-provider", kfpapi_data)

    relation_version_data = {"_supported_versions": "- v1"}

    # example kfp-ui provider relation
    kfpui_rel_id = harness.add_relation(kfpui_relation_name, f"{kfpui_relation_name}-subscriber")
    harness.add_relation_unit(kfpui_rel_id, f"{kfpui_relation_name}-subscriber/0")
    harness.update_relation_data(
        kfpui_rel_id, f"{kfpui_relation_name}-subscriber", relation_version_data
    )

    # example ingress provider relation
    ingress_rel_id = harness.add_relation(
        ingress_relation_name, f"{ingress_relation_name}-subscriber"
    )
    harness.add_relation_unit(ingress_rel_id, f"{ingress_relation_name}-subscriber/0")
    harness.update_relation_data(
        ingress_rel_id, f"{ingress_relation_name}-subscriber", relation_version_data
    )

    harness.begin_with_initial_hooks()
    this_app_name = harness.charm.model.app.name

    # Test that we sent expected data to kfp-api relation
    kfpui_expected_versions = ["v1"]
    kfpui_expected_data = {
        "service-name": f"{this_app_name}.{model_name}",
        "service-port": http_port,
    }
    kfpui_sent_data = harness.get_relation_data(kfpui_rel_id, this_app_name)
    assert yaml.safe_load(kfpui_sent_data["_supported_versions"]) == kfpui_expected_versions
    assert yaml.safe_load(kfpui_sent_data["data"]) == kfpui_expected_data

    # Test that we sent expected data to ingress relation
    ingress_expected_versions = ["v1"]
    ingress_expected_data = {
        "prefix": "/pipeline",
        "rewrite": "/pipeline",
        "service": f"{this_app_name}",
        "port": int(http_port),
    }
    ingress_sent_data = harness.get_relation_data(ingress_rel_id, this_app_name)
    assert yaml.safe_load(ingress_sent_data["_supported_versions"]) == ingress_expected_versions
    assert yaml.safe_load(ingress_sent_data["data"]) == ingress_expected_data

    # confirm that we can serialize the pod spec and that the unit is active
    pod_spec = harness.get_pod_spec()
    yaml.safe_dump(pod_spec)
    assert harness.charm.model.unit.status == ActiveStatus()

    # assert minio secrets are setup correctly
    charm_name = harness.model.app.name
    secrets = pod_spec[0]["kubernetesResources"]["secrets"]
    minio_secrets = [s for s in secrets if s["name"] == f"{charm_name}-minio-secret"][0]
    assert (
        pod_spec[0]["containers"][0]["envConfig"]["minio-secret"]["secret"]["name"]
        == minio_secrets["name"]
    )
    assert (
        b64decode(minio_secrets["data"]["MINIO_ACCESS_KEY"]).decode("utf-8") == "minio-access-key"
    )
    assert (
        b64decode(minio_secrets["data"]["MINIO_SECRET_KEY"]).decode("utf-8")
        == "minio-super-secret-key"
    )


@pytest.fixture
def harness():
    return Harness(KfpUiOperator)


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
