# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
from pathlib import Path

import pytest
import yaml
from pytest_operator.plugin import OpsTest

logger = logging.getLogger(__name__)

APP_NAME = "kfp-persistence"
METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())

KFP_API = "kfp-api"
KFP_API_CHANNEL = "2.0/stable"
KFP_API_TRUST = True
KFP_DB = "kfp-db"
KFP_DB_CHANNEL = "8.0/stable"
KFP_DB_CONFIG = {"profile": "testing"}
KFP_DB_ENTITY = "mysql-k8s"
KFP_DB_TRUST = True
KFP_VIZ = "kfp-viz"
KFP_VIZ_CHANNEL = "2.0/stable"
KFP_VIZ_TRUST = True
MINIO_CHANNEL = "ckf-1.8/stable"
MINIO = "minio"
MINIO_TRUST = True
MINIO_CONFIG = {"access-key": "minio", "secret-key": "minio-secret-key"}


class TestCharm:
    """Integration test charm"""

    @pytest.mark.abort_on_fail
    async def test_build_and_deploy(self, ops_test: OpsTest):
        """Deploy kfp-persistence with required charms and relations."""
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
            entity_url=KFP_DB_ENTITY,
            application_name=KFP_DB,
            config=KFP_DB_CONFIG,
            channel=KFP_DB_CHANNEL,
            trust=KFP_DB_TRUST,
        )

        await ops_test.model.deploy(
            entity_url=MINIO, config=MINIO_CONFIG, channel=MINIO_CHANNEL, trust=MINIO_TRUST
        )
        await ops_test.model.deploy(
            entity_url=KFP_VIZ, channel=KFP_VIZ_CHANNEL, trust=KFP_VIZ_TRUST
        )

        # deploy kfp-api which needs to be related to this charm
        await ops_test.model.deploy(
            entity_url=KFP_API, channel=KFP_API_CHANNEL, trust=KFP_API_TRUST
        )

        await ops_test.model.add_relation(f"{KFP_API}:relational-db", f"{KFP_DB}:database")
        await ops_test.model.add_relation(f"{KFP_API}:object-storage", f"{MINIO}:object-storage")
        await ops_test.model.add_relation(f"{KFP_API}:kfp-viz", f"{KFP_VIZ}:kfp-viz")

        await ops_test.model.wait_for_idle(
            apps=[KFP_API, KFP_DB],
            status="active",
            raise_on_blocked=False,
            raise_on_error=False,
            timeout=90 * 30,
            idle_period=30,
        )

        await ops_test.model.add_relation(f"{APP_NAME}:kfp-api", f"{KFP_API}:kfp-api")

        await ops_test.model.wait_for_idle(
            apps=[APP_NAME],
            status="active",
            raise_on_blocked=False,
            raise_on_error=False,
            timeout=60 * 10,
            idle_period=30,
        )
