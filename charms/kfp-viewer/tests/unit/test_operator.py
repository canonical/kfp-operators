# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

from contextlib import nullcontext as does_not_raise

import ops
import pytest
import yaml
from oci_image import MissingResourceError
from ops.model import ActiveStatus, BlockedStatus, WaitingStatus
from ops.testing import Harness

from charm import KfpViewer

ops.testing.SIMULATE_CAN_CONNECT = True


def test_not_leader(harness):
    harness.begin_with_initial_hooks()
    assert harness.charm.model.unit.status == WaitingStatus("Waiting for leadership")


def test_wrong_model(harness):
    harness.set_leader()
    harness.set_model_name("wrong-name")
    harness.begin_with_initial_hooks()
    assert harness.charm.model.unit.status == BlockedStatus(
        "kfp-viewer must be deployed to model named `kubeflow`"
    )


def test_image_fetch(harness, oci_resource_data):
    harness.begin()
    with pytest.raises(MissingResourceError):
        harness.charm.image.fetch()

    harness.add_oci_resource(**oci_resource_data)
    with does_not_raise():
        harness.charm.image.fetch()


def test_install_with_all_inputs(harness, oci_resource_data):
    harness.set_leader()
    harness.set_model_name("kubeflow")
    harness.add_oci_resource(**oci_resource_data)

    harness.begin_with_initial_hooks()

    # confirm that we can serialize the pod spec and that the unit is active
    yaml.safe_dump(harness.get_pod_spec())
    assert harness.charm.model.unit.status == ActiveStatus()


@pytest.fixture
def harness():
    return Harness(KfpViewer)


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
