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

APP_NAME = "kfp-persistence"
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

        # deploy kfp-api which needs to be related to this charm
        await ops_test.model.deploy(entity_url="kfp-api", channel="2.0/stable", trust=True)

        await ops_test.model.add_relation(f"kfp-api:mysql", "kfp-db:mysql")
        await ops_test.model.add_relation(f"kfp-api:object-storage", "minio:object-storage")
        await ops_test.model.add_relation(f"kfp-api:kfp-viz", "kfp-viz:kfp-viz")

        await ops_test.model.wait_for_idle(
            apps=["kfp-api", "kfp-db"],
            status="active",
            raise_on_blocked=False,
            raise_on_error=False,
            timeout=60 * 10,
            idle_period=30,
        )

        await ops_test.model.add_relation(f"{APP_NAME}:kfp-api", "kfp-api:kfp-api")

        await ops_test.model.wait_for_idle(
            apps=[APP_NAME],
            status="active",
            raise_on_blocked=False,
            raise_on_error=False,
            timeout=60 * 10,
            idle_period=30,
        )