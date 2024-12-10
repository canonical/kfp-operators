# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
from pathlib import Path

import pytest
import yaml
from charmed_kubeflow_chisme.testing import (
    GRAFANA_AGENT_APP,
    assert_alert_rules,
    assert_logging,
    assert_metrics_endpoint,
    deploy_and_assert_grafana_agent,
    get_alert_rules,
)
from pytest_operator.plugin import OpsTest

logger = logging.getLogger(__name__)

APP_NAME = "kfp-api"
METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())

KFP_DB = "kfp-db"
MARIADB_CHANNEL = "latest/edge"
MARIADB_CONFIG = {"database": "mlpipeline"}
MARIADB_CHARM = "charmed-osm-mariadb-k8s"
MARIADB_TRUST = True
KFP_VIZ = "kfp-viz"
KFP_VIZ_CHANNEL = "latest/edge"
KFP_VIZ_TRUST = True
MINIO_CHANNEL = "latest/edge"
MINIO = "minio"
MINIO_TRUST = True
MINIO_CONFIG = {"access-key": "minio", "secret-key": "minio-secret-key"}
MYSQL = "mysql-k8s"
MYSQL_CHANNEL = "8.0/stable"
MYSQL_CONFIG = {"profile": "testing"}
MYSQL_TRUST = True


class TestCharm:
    """Integration test charm"""

    @pytest.mark.abort_on_fail
    async def test_build_and_deploy(self, ops_test: OpsTest):
        """Deploy kfp-api with required charms and relations."""
        image_path = METADATA["resources"]["oci-image"]["upstream-source"]
        resources = {"oci-image": image_path}

        await ops_test.model.deploy(
            entity_url="/tmp/packed-charm-cache-true-.-charms-kfp-api-base-0/charms/kfp-api/kfp-api_ubuntu-20.04-amd64.charm",
            application_name=APP_NAME,
            resources=resources,
            trust=True,
        )

        await ops_test.model.deploy(
            entity_url=MINIO, config=MINIO_CONFIG, channel=MINIO_CHANNEL, trust=MINIO_TRUST
        )
        await ops_test.model.deploy(
            entity_url=KFP_VIZ, channel=KFP_VIZ_CHANNEL, trust=KFP_VIZ_TRUST
        )

        await ops_test.model.add_relation(f"{APP_NAME}:object-storage", f"{MINIO}:object-storage")
        await ops_test.model.add_relation(f"{APP_NAME}:kfp-viz", f"{KFP_VIZ}:kfp-viz")


        await ops_test.model.deploy(
            MYSQL,
            channel=MYSQL_CHANNEL,
            application_name=KFP_DB,
            config=MYSQL_CONFIG,
            trust=MYSQL_TRUST,
        )
        await ops_test.model.relate(f"{APP_NAME}:relational-db", f"{KFP_DB}:database")
        await ops_test.model.wait_for_idle(
            apps=[APP_NAME, KFP_VIZ, KFP_DB, MINIO],
            status="active",
            raise_on_blocked=False,
            raise_on_error=False,
            timeout=90 * 20,
        )

        # Deploying grafana-agent-k8s and add all relations
        await deploy_and_assert_grafana_agent(
            ops_test.model, APP_NAME, metrics=True, dashboard=True, logging=True
        )

    async def test_alert_rules(self, ops_test: OpsTest):
        """Test check charm alert rules and rules defined in relation data bag."""
        app = ops_test.model.applications[APP_NAME]
        alert_rules = get_alert_rules()
        logger.info("found alert_rules: %s", alert_rules)
        await assert_alert_rules(app, alert_rules)

    async def test_metrics_enpoint(self, ops_test: OpsTest):
        """Test metrics_endpoints are defined in relation data bag and their accessibility.

        This function gets all the metrics_endpoints from the relation data bag, checks if
        they are available from the grafana-agent-k8s charm and finally compares them with the
        ones provided to the function.
        """
        app = ops_test.model.applications[APP_NAME]
        await assert_metrics_endpoint(app, metrics_port=8888, metrics_path="/metrics")

    async def test_logging(self, ops_test: OpsTest):
        """Test logging is defined in relation data bag."""
        app = ops_test.model.applications[GRAFANA_AGENT_APP]
        await assert_logging(app)

    async def test_remove_application(self, ops_test: OpsTest):
        """Test that the application can be removed successfully."""
        await ops_test.model.remove_application(app_name=APP_NAME, block_until_done=True)
        assert APP_NAME not in ops_test.model.applications
