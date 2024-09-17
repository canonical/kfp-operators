# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
import os
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
from utils import get_packed_charms

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

    @pytest.fixture
    def use_packed_charms() -> str:
        """Return environment variable `USE_PACKED_CHARMS`. If it's not found, return `false`."""
        return os.environ.get("USE_PACKED_CHARMS", "false").replace('"', "")

    @pytest.mark.abort_on_fail
    async def test_build_and_deploy(self, ops_test: OpsTest, use_packed_charms):
        """Deploy kfp-api with required charms and relations."""
        charm_path = "."
        if use_packed_charms.lower() == "true":
            built_charm_path = await get_packed_charms(charm_path)
        else:
            built_charm_path = await ops_test.build_charm(charm_path)
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
            entity_url=MARIADB_CHARM,
            application_name=KFP_DB,
            config=MARIADB_CONFIG,
            channel=MARIADB_CHANNEL,
            trust=MARIADB_TRUST,
        )
        await ops_test.model.deploy(
            entity_url=MINIO, config=MINIO_CONFIG, channel=MINIO_CHANNEL, trust=MINIO_TRUST
        )
        await ops_test.model.deploy(
            entity_url=KFP_VIZ, channel=KFP_VIZ_CHANNEL, trust=KFP_VIZ_TRUST
        )

        # FIXME: This assertion belongs to unit tests
        # test no database relation, charm should be in blocked state
        # assert ops_test.model.applications[APP_NAME].units[0].workload_status == "blocked"

        await ops_test.model.add_relation(f"{APP_NAME}:mysql", f"{KFP_DB}:mysql")
        await ops_test.model.add_relation(f"{APP_NAME}:object-storage", f"{MINIO}:object-storage")
        await ops_test.model.add_relation(f"{APP_NAME}:kfp-viz", f"{KFP_VIZ}:kfp-viz")

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

    # FIXME: this test case belongs in unit tests as it is asserting the status of the
    # unit under a certain condition, we don't actually need the presence of any deployed
    # charm to test this.
    @pytest.mark.abort_on_fail
    async def test_relational_db_relation_with_mysql_relation(self, ops_test: OpsTest):
        """Test failure of addition of relational-db relation with mysql relation present."""
        # deploy mysql-k8s charm
        await ops_test.model.deploy(
            MYSQL,
            channel=MYSQL_CHANNEL,
            config=MYSQL_CONFIG,
            trust=MYSQL_TRUST,
        )
        await ops_test.model.wait_for_idle(
            apps=[MYSQL],
            status="active",
            raise_on_blocked=True,
            timeout=90 * 30,
            idle_period=20,
        )

        # add relational-db relation which should put charm into blocked state,
        # because at this point mysql relation is already established
        await ops_test.model.relate(f"{APP_NAME}:relational-db", f"{MYSQL}:database")

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
        await ops_test.juju("remove-relation", f"{APP_NAME}:relational-db", f"{MYSQL}:database")

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
        await ops_test.juju("remove-relation", f"{APP_NAME}:mysql", f"{KFP_DB}:mysql")

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
        await ops_test.model.relate(f"{APP_NAME}:relational-db", f"{MYSQL}:database")

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
        await ops_test.model.relate(f"{APP_NAME}:mysql", f"{KFP_DB}:mysql")

        # verify that charm goes into blocked state
        await ops_test.model.wait_for_idle(
            apps=[APP_NAME],
            status="blocked",
            raise_on_blocked=False,
            raise_on_error=True,
            timeout=60 * 10,
        )
        assert ops_test.model.applications[APP_NAME].units[0].workload_status == "blocked"

        # remove redundant relation
        await ops_test.juju("remove-relation", f"{APP_NAME}:mysql", f"{KFP_DB}:mysql")

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
