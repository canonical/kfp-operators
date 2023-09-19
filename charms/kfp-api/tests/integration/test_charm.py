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


class TestCharm:
    """Integration test charm"""

    @pytest.mark.abort_on_fail
    async def test_build_and_deploy(self, ops_test: OpsTest):
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

        # FIXME: we should probably stop deploying mariadb as:
        # 1) The team has acceped and started using mysql-k8s more extensively
        # 2) The repository level integration tests use mysql-k8s only
        await ops_test.model.deploy(
            entity_url="charmed-osm-mariadb-k8s",
            application_name="kfp-db",
            config=KFP_DB_CONFIG,
            channel="latest/stable",
            trust=True,
        )
        await ops_test.model.deploy(
            entity_url="minio", config=MINIO_CONFIG, channel="ckf-1.7/stable", trust=True
        )
        await ops_test.model.deploy(entity_url="kfp-viz", channel="2.0/stable", trust=True)

        # FIXME: This assertion belongs to unit tests
        # test no database relation, charm should be in blocked state
        # assert ops_test.model.applications[APP_NAME].units[0].workload_status == "blocked"

        await ops_test.model.add_relation(f"{APP_NAME}:mysql", "kfp-db:mysql")
        await ops_test.model.add_relation(f"{APP_NAME}:object-storage", "minio:object-storage")
        await ops_test.model.add_relation(f"{APP_NAME}:kfp-viz", "kfp-viz:kfp-viz")

        await ops_test.model.wait_for_idle(
            apps=[APP_NAME, "kfp-viz", "kfp-db", "minio"],
            status="active",
            raise_on_blocked=False,
            raise_on_error=False,
            timeout=90 * 30,
        )

    # FIXME: this test case belongs in unit tests as it is asserting the status of the
    # unit under a certain condition, we don't actually need the presence of any deployed
    # charm to test this.
    @pytest.mark.abort_on_fail
    async def test_relational_db_relation_with_mysql_relation(self, ops_test: OpsTest):
        """Test failure of addition of relational-db relation with mysql relation present."""
        # deploy mysql-k8s charm
        await ops_test.model.deploy(
            "mysql-k8s",
            channel="8.0/edge",
            config={"profile": "testing"},
            trust=True,
        )
        await ops_test.model.wait_for_idle(
            apps=["mysql-k8s"],
            status="active",
            raise_on_blocked=True,
            timeout=90 * 20,
            idle_period=20,
        )

        # add relational-db relation which should put charm into blocked state,
        # because at this point mysql relation is already established
        await ops_test.model.relate(f"{APP_NAME}:relational-db", "mysql-k8s:database")

        # verify that charm goes into blocked state
        await ops_test.model.wait_for_idle(
            apps=[APP_NAME],
            status="blocked",
            raise_on_blocked=False,
            raise_on_error=True,
            timeout=60 * 10,
            idle_period=10,
        )
        assert ops_test.model.applications[APP_NAME].units[0].workload_status == "blocked"

        # remove just added relational-db relation
        await ops_test.juju("remove-relation", f"{APP_NAME}:relational-db", "mysql-k8s:database")

    # FIXME: this test case belongs in unit tests as it is asserting the status of the
    # unit under a certain condition, we don't actually need the presence of any deployed
    # charm to test this.
    @pytest.mark.abort_on_fail
    async def test_relational_db_relation_with_mysql_k8s(self, ops_test: OpsTest):
        """Test no relation and relation with mysql-k8s charm."""

        # verify that charm is active state
        await ops_test.model.wait_for_idle(
            apps=[APP_NAME],
            status="active",
            raise_on_blocked=False,
            raise_on_error=True,
            timeout=60 * 10,
        )
        assert ops_test.model.applications[APP_NAME].units[0].workload_status == "active"

        # remove existing mysql relation which should put charm into blocked state,
        # because there will be no database relations
        await ops_test.juju("remove-relation", f"{APP_NAME}:mysql", "kfp-db:mysql")

        # verify that charm goes into blocked state
        await ops_test.model.wait_for_idle(
            apps=[APP_NAME],
            status="blocked",
            raise_on_blocked=False,
            raise_on_error=True,
            timeout=60 * 10,
        )
        assert ops_test.model.applications[APP_NAME].units[0].workload_status == "blocked"

        # add relational-db relation which should put charm into active state
        await ops_test.model.relate(f"{APP_NAME}:relational-db", "mysql-k8s:database")

        # verify that charm goes into active state
        await ops_test.model.wait_for_idle(
            apps=[APP_NAME],
            status="active",
            raise_on_blocked=False,
            raise_on_error=True,
            timeout=60 * 10,
        )
        assert ops_test.model.applications[APP_NAME].units[0].workload_status == "active"

    # FIXME: this test case belongs in unit tests as it is asserting the status of the
    # unit under a certain condition, we don't actually need the presence of any deployed
    # charm to test this.
    @pytest.mark.abort_on_fail
    async def test_msql_relation_with_relational_db_relation(self, ops_test: OpsTest):
        """Test failure of addition of mysql relation with relation-db relation present."""

        # add mysql relation which should put charm into blocked state,
        # because at this point relational-db relation is already established
        await ops_test.model.relate(f"{APP_NAME}:mysql", "kfp-db:mysql")

        # verify that charm goes into blocked state
        await ops_test.model.wait_for_idle(
            apps=[APP_NAME],
            status="blocked",
            raise_on_blocked=False,
            raise_on_error=True,
            timeout=60 * 10,
        )
        assert ops_test.model.applications[APP_NAME].units[0].workload_status == "blocked"

    async def test_prometheus_grafana_integration(self, ops_test: OpsTest):
        """Deploy prometheus, grafana and required relations, then test the metrics."""
        prometheus = "prometheus-k8s"
        grafana = "grafana-k8s"
        prometheus_scrape = "prometheus-scrape-config-k8s"
        scrape_config = {"scrape_interval": "30s"}

        # Deploy and relate prometheus
        await ops_test.model.deploy(prometheus, channel="latest/stable", trust=True)
        await ops_test.model.deploy(grafana, channel="latest/stable", trust=True)
        await ops_test.model.deploy(
            prometheus_scrape, channel="latest/stable", config=scrape_config, trust=True
        )

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

        # prometheus-k8s needs a significant amount of time to deploy in GH runners,
        # please make sure the timeout stays above or equal to 90*20
        await ops_test.model.wait_for_idle(
            apps=["grafana-k8s", "prometheus-k8s", "prometheus-scrape-config-k8s"],
            status="active",
            raise_on_blocked=False,
            raise_on_error=False,
            timeout=90 * 20,
            idle_period=20,
        )

        status = await ops_test.model.get_status()
        prometheus_unit_ip = status["applications"][prometheus]["units"][f"{prometheus}/0"][
            "address"
        ]
        logger.info(f"Prometheus available at http://{prometheus_unit_ip}:9090")

        for attempt in self.retry_for_5_attempts:
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
