# Copyright 2023 Canonical Ltd.
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

        # test no database relation, charm should be in blocked state
        assert ops_test.model.applications[APP_NAME].units[0].workload_status == "blocked"

        await ops_test.model.add_relation(f"{APP_NAME}:mysql", "kfp-db:mysql")
        await ops_test.model.add_relation(f"{APP_NAME}:object-storage", "minio:object-storage")
        await ops_test.model.add_relation(f"{APP_NAME}:kfp-viz", "kfp-viz:kfp-viz")

        await ops_test.model.wait_for_idle(
            apps=[APP_NAME, "kfp-viz", "kfp-db", "minio"],
            status="active",
            raise_on_blocked=False,
            raise_on_error=False,
            timeout=60 * 10,
            idle_period=120,
        )

    @pytest.mark.abort_on_fail
    async def test_relational_db_relation_with_mysql_relation(self, ops_test: OpsTest):
        """Test failure of addition of relational-db relation with mysql relation present."""
        # Deploy mysql-k8s charm
        await ops_test.model.deploy(
            "mysql-k8s",
            channel="8.0/edge",
            series="jammy",
            constraints="mem=600M",
            trust=True,
        )
        await ops_test.model.wait_for_idle(
            apps=["mysql-k8s"],
            status="active",
            raise_on_blocked=True,
            timeout=60 * 10,
            idle_period=60,
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
