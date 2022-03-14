# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
from pathlib import Path

import pytest
import yaml
from pytest_operator.plugin import OpsTest


logger = logging.getLogger(__name__)

APP_NAME = "kfp-api"
METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())

MINIO_CONFIG = {"access-key": "minio", "secret-key": "minio-secret-key"}
KFP_DB_CONFIG = {"database": "mlpipeline"}


@pytest.mark.abort_on_fail
async def test_build_and_deploy(ops_test: OpsTest):
    """Deploy kfp-api with required charms and relations."""
    built_charm_path = await ops_test.build_charm("./")
    logger.info(f"Built charm {built_charm_path}")

    image_path = METADATA["resources"]["oci-image"]["upstream-source"]
    resources = {"oci-image": image_path}

    await ops_test.model.deploy(
        entity_url=built_charm_path,
        application_name=APP_NAME,
        resources=resources,
    )

    # juju config kfp-db database=mlpipeline
    await ops_test.model.deploy(entity_url="charmed-osm-mariadb-k8s", application_name="kfp-db", config=KFP_DB_CONFIG)
    await ops_test.model.add_relation(
        f"{APP_NAME}:mysql",
        "kfp-db:mysql",
    )

    await ops_test.model.deploy(entity_url="minio", config=MINIO_CONFIG)
    await ops_test.model.add_relation(
        f"{APP_NAME}:object-storage",
        "minio:object-storage",
    )

    await ops_test.model.deploy(entity_url="kfp-viz")
    await ops_test.model.add_relation(
        f"{APP_NAME}:kfp-viz",
        "kfp-viz:kfp-viz",
    )

    await ops_test.model.wait_for_idle(status="active", timeout=60 * 10)


async def test_integrate_with_prometheus_and_grafana(ops_test: OpsTest):
    """Deploy prometheus, grafana and required relations."""
    await ops_test.model.deploy("prometheus-k8s", channel="latest/beta")
    await ops_test.model.deploy("grafana-k8s", channel="latest/beta")
    await ops_test.model.add_relation("prometheus-k8s", "grafana-k8s")
    await ops_test.model.add_relation(APP_NAME, "grafana-k8s")
    await ops_test.model.add_relation("prometheus-k8s", APP_NAME)

    await ops_test.model.wait_for_idle(status="active", timeout=60 * 10)

    status = await ops_test.model.get_status()
    prometheus_unit_ip = status["applications"]["prometheus-k8s"]["units"]["prometheus-k8s/0"]["address"]
    assert prometheus_unit_ip
