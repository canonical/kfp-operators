# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
from pathlib import Path

import pytest
import yaml
from charmed_kubeflow_chisme.testing import (
    GRAFANA_AGENT_APP,
    assert_logging,
    deploy_and_assert_grafana_agent,
)
from charms_dependencies import KFP_API, KFP_DB, KFP_VIZ, MINIO
from pytest_operator.plugin import OpsTest

logger = logging.getLogger(__name__)

METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())
APP_NAME = METADATA["name"]
KFP_DB_APPLICATION_NAME = "kfp-db"


class TestCharm:
    """Integration test charm"""

    @pytest.mark.abort_on_fail
    async def test_build_and_deploy(self, ops_test: OpsTest, request):
        """Deploy kfp-persistence with required charms and relations."""
        image_path = METADATA["resources"]["oci-image"]["upstream-source"]
        resources = {"oci-image": image_path}
        # Keep the option to run the integration tests locally
        # by building the charm and then deploying
        entity_url = (
            await ops_test.build_charm("./")
            if not (entity_url := request.config.getoption("--charm-path"))
            else entity_url
        )

        await ops_test.model.deploy(
            entity_url=entity_url,
            application_name=APP_NAME,
            resources=resources,
            trust=True,
        )

        await ops_test.model.deploy(
            entity_url=KFP_DB.charm,
            application_name=KFP_DB_APPLICATION_NAME,
            config=KFP_DB.config,
            channel=KFP_DB.channel,
            trust=KFP_DB.trust,
        )

        await ops_test.model.deploy(
            entity_url=MINIO.charm, config=MINIO.config, channel=MINIO.channel, trust=MINIO.trust
        )
        await ops_test.model.deploy(
            entity_url=KFP_VIZ.charm, channel=KFP_VIZ.channel, trust=KFP_VIZ.trust
        )

        # deploy kfp-api which needs to be related to this charm
        await ops_test.model.deploy(
            entity_url=KFP_API.charm, channel=KFP_API.channel, trust=KFP_API.trust
        )

        await ops_test.model.integrate(
            f"{KFP_API.charm}:relational-db", f"{KFP_DB_APPLICATION_NAME}:database"
        )
        await ops_test.model.integrate(
            f"{KFP_API.charm}:object-storage", f"{MINIO.charm}:object-storage"
        )
        await ops_test.model.integrate(f"{KFP_API.charm}:kfp-viz", f"{KFP_VIZ.charm}:kfp-viz")

        await ops_test.model.wait_for_idle(
            apps=[KFP_API.charm, KFP_DB_APPLICATION_NAME],
            status="active",
            raise_on_blocked=False,
            raise_on_error=False,
            timeout=90 * 30,
            idle_period=30,
        )

        await ops_test.model.integrate(f"{APP_NAME}:kfp-api", f"{KFP_API.charm}:kfp-api")

        await ops_test.model.wait_for_idle(
            apps=[APP_NAME],
            status="active",
            raise_on_blocked=False,
            raise_on_error=False,
            timeout=60 * 10,
            idle_period=30,
        )
        # Deploying grafana-agent-k8s and add all relations
        await deploy_and_assert_grafana_agent(
            ops_test.model, APP_NAME, metrics=False, dashboard=False, logging=True
        )


async def test_logging(ops_test):
    """Test logging is defined in relation data bag."""
    app = ops_test.model.applications[GRAFANA_AGENT_APP]
    await assert_logging(app)
