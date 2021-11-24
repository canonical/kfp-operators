# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
from pathlib import Path

import yaml

from pytest_operator.plugin import OpsTest

logger = logging.getLogger(__name__)

APP_NAME = "kfp-profile-controller"
METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())

MINIO_CONFIG = {"access-key": "minio", "secret-key": "minio-secret-key"}


async def test_build_and_deploy(ops_test: OpsTest):
    built_charm_path = await ops_test.build_charm("./")
    logger.info(f"Built charm {built_charm_path}")

    image_path = METADATA["resources"]["oci-image"]["upstream-source"]
    resources = {"oci-image": image_path}

    await ops_test.model.deploy(
        entity_url=built_charm_path,
        application_name=APP_NAME,
        resources=resources,
    )

    # Deploy required relations
    await ops_test.model.deploy(entity_url="minio", config=MINIO_CONFIG)
    await ops_test.model.add_relation(
        f"{APP_NAME}:object-storage",
        "minio:object-storage",
    )

    # TODO: Need a better test for checking everything is ok
    # Maybe: await ops_test.model.wait_for_idle(raise_on_error=False, raise_on_blocked=True) ?
    await ops_test.model.wait_for_idle(timeout=60 * 10)


# TODO: Real testing requires:
#  * kubeflow-profile controller, or something that will make namespaces/service accounts in a
#    similar fashion (some resources deployed to each namespace by kfp-profile-controller use the
#    `default-editor` service account, which is created by the main kubeflow-profile controller)
#  * This charm deploying successfully is not a full test of function.  We need to create a new
#    tracked namespace (namespace that has label pipelines.kubeflow.org/enabled=true) and ensure all
#    expected resources are deployed and come up successfully (eg: if service account is not found,
#    deployments will exist but pods will never be "ready")
