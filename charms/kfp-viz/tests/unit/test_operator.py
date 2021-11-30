# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

from contextlib import nullcontext as does_not_raise

import pytest
import yaml
from oci_image import MissingResourceError
from ops.model import ActiveStatus, WaitingStatus
from ops.testing import Harness

from charm import KfpVizOperator

# TODO: Tests missing for config_changed and dropped/reloaded relations and relations where this
#  charm provides data to the other application


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


# TODO: kfp-viz (provide data)


def test_install_with_all_inputs(harness, oci_resource_data):
    harness.set_leader()
    http_port = "1234"
    model_name = "test_model"
    harness.set_model_name(model_name)
    harness.update_config({"http-port": http_port})

    kfpviz_relation_name = "kfp-viz"

    harness.set_leader()

    # Set up required relations
    # Future: convert these to fixtures and share with the tests above
    harness.add_oci_resource(**oci_resource_data)

    relation_version_data = {"_supported_versions": "- v1"}

    # example kfp-viz provider relation
    kfpviz_rel_id = harness.add_relation(
        kfpviz_relation_name, f"{kfpviz_relation_name}-subscriber"
    )
    harness.add_relation_unit(kfpviz_rel_id, f"{kfpviz_relation_name}-subscriber/0")
    harness.update_relation_data(
        kfpviz_rel_id, f"{kfpviz_relation_name}-subscriber", relation_version_data
    )

    harness.begin_with_initial_hooks()
    this_app_name = harness.charm.model.app.name

    # Test that we sent expected data to kfp-viz relation
    kfpviz_expected_versions = ["v1"]
    kfpviz_expected_data = {
        "service-name": f"{this_app_name}.{model_name}",
        "service-port": http_port,
    }
    kfpviz_sent_data = harness.get_relation_data(kfpviz_rel_id, this_app_name)
    assert yaml.safe_load(kfpviz_sent_data["_supported_versions"]) == kfpviz_expected_versions
    assert yaml.safe_load(kfpviz_sent_data["data"]) == kfpviz_expected_data

    # confirm that we can serialize the pod spec and that the unit is active
    yaml.safe_dump(harness.get_pod_spec())
    assert harness.charm.model.unit.status == ActiveStatus()


@pytest.fixture
def harness():
    return Harness(KfpVizOperator)


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
