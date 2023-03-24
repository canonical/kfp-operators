# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import json
import logging
from pathlib import Path

import pytest
import requests
import yaml
from pytest_operator.plugin import OpsTest
from tenacity import Retrying, stop_after_attempt, stop_after_delay, wait_exponential

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
        trust=True,
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
    prometheus_scrape = "prometheus-scrape-config-k8s"
    scrape_config = {"scrape_interval": "30s"}

    # Deploy and relate prometheus
    await ops_test.model.deploy(prometheus, channel="latest/edge", trust=True)
    await ops_test.model.deploy(grafana, channel="latest/edge", trust=True)
    await ops_test.model.deploy(prometheus_scrape, channel="latest/beta", config=scrape_config)

    await ops_test.model.add_relation(APP_NAME, prometheus_scrape)
    await ops_test.model.add_relation(
        f"{prometheus}:grafana-dashboard", f"{grafana}:grafana-dashboard"
    )
    await ops_test.model.add_relation(
        f"{APP_NAME}:grafana-dashboard", f"{grafana}:grafana-dashboard"
    )
    await ops_test.model.add_relation(
        f"{prometheus}:metrics-endpoint", f"{prometheus_scrape}:metrics-endpoint"
    )

    await ops_test.model.wait_for_idle(status="active", timeout=90 * 20)

    status = await ops_test.model.get_status()
    prometheus_unit_ip = status["applications"][prometheus]["units"][f"{prometheus}/0"]["address"]
    logger.info(f"Prometheus available at http://{prometheus_unit_ip}:9090")

    for attempt in retry_for_5_attempts:
        logger.info(
            f"Testing prometheus deployment (attempt " f"{attempt.retry_state.attempt_number})"
        )
        with attempt:
            r = requests.get(
                f"http://{prometheus_unit_ip}:9090/api/v1/query?"
                f'query=up{{juju_application="{APP_NAME}"}}'
            )
            response = json.loads(r.content.decode("utf-8"))
            response_status = response["status"]
            logger.info(f"Response status is {response_status}")
            assert response_status == "success"

            response_metric = response["data"]["result"][0]["metric"]
            assert response_metric["juju_application"] == APP_NAME
            assert response_metric["juju_model"] == ops_test.model_name


# Helper to retry calling a function over 30 seconds or 5 attempts
retry_for_5_attempts = Retrying(
    stop=(stop_after_attempt(5) | stop_after_delay(30)),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    reraise=True,
)

# TODO: Add test that makes sure the Grafana relation actually works
#  once the template is defined.
