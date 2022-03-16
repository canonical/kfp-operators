# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import json
import logging
from pathlib import Path

import pytest
import requests
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

    await ops_test.model.deploy(
        entity_url="charmed-osm-mariadb-k8s", application_name="kfp-db", config=KFP_DB_CONFIG
    )
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


async def test_prometheus_grafana_integration(ops_test: OpsTest):
    """Deploy prometheus, grafana and required relations, then test the metrics."""
    prometheus = "prometheus-k8s"
    grafana = "grafana-k8s"

    await ops_test.model.deploy(prometheus, channel="latest/beta")
    await ops_test.model.deploy(grafana, channel="latest/beta")
    await ops_test.model.add_relation(prometheus, grafana)
    await ops_test.model.add_relation(APP_NAME, grafana)
    await ops_test.model.add_relation(prometheus, APP_NAME)

    await ops_test.model.wait_for_idle(status="active", timeout=60 * 10)

    status = await ops_test.model.get_status()
    prometheus_unit_ip = status["applications"][prometheus]["units"][f"{prometheus}/0"]["address"]
    logger.info(f"Prometheus available at http://{prometheus_unit_ip}:9090")

    r = requests.get(
        f'http://{prometheus_unit_ip}:9090/api/v1/query?query=up{{juju_application="{APP_NAME}"}}'
    )
    response = json.loads(r.content.decode("utf-8"))
    response_status = response["status"]
    logger.info(f"Response status is {response_status}")

    response_metric = response["data"]["result"][0]["metric"]
    assert response_metric["juju_application"] == APP_NAME
    assert response_metric["juju_model"] == ops_test.model_name
