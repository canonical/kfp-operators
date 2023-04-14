# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

from contextlib import nullcontext as does_not_raise
from unittest.mock import MagicMock, patch

import pytest
import yaml
from ops.model import ActiveStatus, BlockedStatus, WaitingStatus
from ops.testing import Harness

from charm import ErrorWithStatus, KfpApiOperator

# TODO: Tests missing for config_changed and dropped/reloaded relations


@pytest.fixture(scope="function")
def harness() -> Harness:
    """Create and return Harness for testing."""
    harness = Harness(KfpApiOperator)

    # setup container networking simulation
    harness.set_can_connect("ml-pipeline-api-server", True)

    return harness


class TestCharm:
    """Test class for KfamApiOperator."""

    @patch("charm.KubernetesServicePatch", lambda x, y, service_name: None)
    @patch("charm.KfpApiOperator.k8s_resource_handler")
    def test_not_leader(self, k8s_resource_handler: MagicMock, harness: Harness):
        harness.begin_with_initial_hooks()
        harness.container_pebble_ready("ml-pipeline-api-server")
        assert harness.charm.model.unit.status == WaitingStatus("Waiting for leadership")

    @pytest.mark.parametrize(
        "relation_data,expected_returned_data,expected_raises,expected_status",
        (
            (
                # No relation established.  Raises ErrorWithStatus
                None,
                None,
                pytest.raises(ErrorWithStatus),
                BlockedStatus("Please add required relation relation mysql"),
            ),
            (
                # Relation exists but no data posted yet
                {},
                None,
                pytest.raises(ErrorWithStatus),
                WaitingStatus("Waiting for mysql relation data"),
            ),
            (
                # Relation exists with only partial data
                {"database": "database"},
                None,
                pytest.raises(ErrorWithStatus),
                BlockedStatus("Received incomplete data from mysql relation. See logs"),
            ),
            (
                # Relation complete
                {
                    "database": "database",
                    "host": "host",
                    "root_password": "root_password",
                    "port": "port",
                },
                {
                    "database": "database",
                    "host": "host",
                    "root_password": "root_password",
                    "port": "port",
                },
                does_not_raise(),
                None,
            ),
        ),
    )
    @patch("charm.KubernetesServicePatch", lambda x, y, service_name: None)
    def test_mysql_relation(
        self,
        relation_data,
        expected_returned_data,
        expected_raises,
        expected_status,
        harness: Harness,
    ):
        harness.set_leader(True)
        harness.begin()
        harness.container_pebble_ready("ml-pipeline-api-server")

        mysql_app = "mysql_app"
        mysql_unit = f"{mysql_app}/0"

        rel_id = harness.add_relation("mysql", mysql_app)
        harness.add_relation_unit(rel_id, mysql_unit)

        # Test complete relation
        data = {
            "database": "database",
            "host": "host",
            "root_password": "root_password",
            "port": "port",
        }
        harness.update_relation_data(rel_id, mysql_unit, data)
        with does_not_raise():
            harness.charm._get_mysql()

    @patch("charm.KubernetesServicePatch", lambda x, y, service_name: None)
    def test_mysql_relation_too_many_relations(self, harness: Harness):
        harness.set_leader(True)
        harness.begin()
        harness.container_pebble_ready("ml-pipeline-api-server")

        mysql_app = "mysql_app"
        mysql_unit = f"{mysql_app}/0"

        rel_id = harness.add_relation("mysql", mysql_app)
        harness.add_relation_unit(rel_id, mysql_unit)
        rel_id_2 = harness.add_relation("mysql", "extra_sql")
        harness.add_relation_unit(rel_id_2, "extra_sql/0")

        with pytest.raises(ErrorWithStatus) as too_many_relations:
            harness.charm._get_mysql()
        assert too_many_relations.value.status == BlockedStatus("Too many mysql relations")

    @patch("charm.KubernetesServicePatch", lambda x, y, service_name: None)
    def test_kfp_viz_relation_missing(self, harness: Harness):
        harness.set_leader(True)
        harness.begin()
        harness.container_pebble_ready("ml-pipeline-api-server")

        # check for correct error message when retrieving missing relation data
        interfaces = harness.charm._get_interfaces()

        with pytest.raises(ErrorWithStatus) as missing_relation:
            harness.charm._get_viz(interfaces)
        assert missing_relation.value.status == BlockedStatus(
            "Please add required relation kfp-viz"
        )

    @pytest.mark.parametrize(
        "relation_name,relation_data,expected_returned_data,expected_raises,expected_status",
        (
            # Object storage
            # No relation established.  Raises ErrorWithStatus
            (
                "object-storage",
                None,
                None,
                pytest.raises(ErrorWithStatus),
                BlockedStatus("Please add required relation object-storage"),
            ),
            (
                # Relation exists but no versions set yet
                "object-storage",
                {},
                None,
                pytest.raises(ErrorWithStatus),
                WaitingStatus("List of object-storage versions not found for apps: other-app"),
            ),
            (
                # Relation exists with versions, but no data posted yet
                "object-storage",
                {"_supported_versions": "- v1"},
                None,
                pytest.raises(ErrorWithStatus),
                WaitingStatus("Waiting for object-storage relation data"),
            ),
            (
                # Relation exists with versions and empty data
                "object-storage",
                {"_supported_versions": "- v1", "data": yaml.dump({})},
                None,
                pytest.raises(ErrorWithStatus),
                BlockedStatus("Found empty relation data for object-storage"),
            ),
            (
                # Relation exists with versions and invalid (partial) data
                "object-storage",
                {
                    "_supported_versions": "- v1",
                    "data": yaml.dump({"service-name": "service-name"}),
                },
                None,
                pytest.raises(ErrorWithStatus),
                BlockedStatus(
                    "Found incomplete/incorrect relation data for object-storage. See logs"
                ),
            ),
            (
                # Relation exists with valid data
                "object-storage",
                {
                    "_supported_versions": "- v1",
                    "data": yaml.dump(
                        {
                            "access-key": "access-key",
                            "namespace": "namespace",
                            "port": 1234,
                            "secret-key": "secret-key",
                            "secure": True,
                            "service": "service",
                        }
                    ),
                },
                {
                    "access-key": "access-key",
                    "namespace": "namespace",
                    "port": 1234,
                    "secret-key": "secret-key",
                    "secure": True,
                    "service": "service",
                },
                does_not_raise(),
                None,
            ),
            # kfp-viz
            # No relation established.  Raises ErrorWithStatus
            (
                "kfp-viz",
                None,
                None,
                pytest.raises(ErrorWithStatus),
                BlockedStatus("Please add required relation kfp-viz"),
            ),
            (
                # Relation exists but no versions set yet
                "kfp-viz",
                {},
                None,
                pytest.raises(ErrorWithStatus),
                WaitingStatus("List of kfp-viz versions not found for apps: other-app"),
            ),
            (
                # Relation exists with versions, but no data posted yet
                "kfp-viz",
                {"_supported_versions": "- v1"},
                None,
                pytest.raises(ErrorWithStatus),
                WaitingStatus("Waiting for kfp-viz relation data"),
            ),
            (
                # Relation exists with versions and empty data
                "kfp-viz",
                {"_supported_versions": "- v1", "data": yaml.dump({})},
                None,
                pytest.raises(ErrorWithStatus),
                BlockedStatus("Found empty relation data for kfp-viz"),
            ),
            (
                # Relation exists with versions and invalid (partial) data
                "kfp-viz",
                {
                    "_supported_versions": "- v1",
                    "data": yaml.dump({"service-name": "service-name"}),
                },
                None,
                pytest.raises(ErrorWithStatus),
                BlockedStatus("Found incomplete/incorrect relation data for kfp-viz. See logs"),
            ),
            (
                # Relation exists with valid data
                "kfp-viz",
                {
                    "_supported_versions": "- v1",
                    "data": yaml.dump({"service-name": "set", "service-port": "9876"}),
                },
                {"service-name": "set", "service-port": "9876"},
                does_not_raise(),
                None,
            ),
        ),
    )
    @patch("charm.KubernetesServicePatch", lambda x, y, service_name: None)
    def test_relations_that_provide_data(
        self,
        relation_name,
        relation_data,
        expected_returned_data,
        expected_raises,
        expected_status,
        harness: Harness,
    ):
        harness.set_leader(True)
        harness.begin()
        harness.container_pebble_ready("ml-pipeline-api-server")

        other_app = "other-app"
        other_unit = f"{other_app}/0"

        if relation_data is not None:
            rel_id = harness.add_relation(relation_name, other_app)
            harness.add_relation_unit(rel_id, other_unit)
            harness.update_relation_data(rel_id, other_app, relation_data)

        with expected_raises as partial_relation_data:
            interfaces = harness.charm._get_interfaces()
            data = harness.charm._validate_sdi_interface(interfaces, relation_name)
        if expected_status is None:
            assert data == expected_returned_data
        else:
            assert partial_relation_data.value.status == expected_status

    @patch("charm.KubernetesServicePatch", lambda x, y, service_name: None)
    @patch("charm.KfpApiOperator.k8s_resource_handler")
    def test_install_with_all_inputs_and_pebble(
        self,
        k8s_resource_handler: MagicMock,
        harness: Harness,
    ):
        """Test complete installation with all required relations and verify pebble layer."""
        harness.set_leader(True)
        kfpapi_relation_name = "kfp-api"
        model_name = "test_model"
        service_port = "8888"
        harness.set_model_name(model_name)
        harness.update_config({"http-port": service_port})

        # Set up required relations

        # mysql relation
        mysql_data = {
            "database": "database",
            "host": "host",
            "root_password": "root_password",
            "port": "port",
        }
        mysql_rel_id = harness.add_relation("mysql", "mysql-provider")
        harness.add_relation_unit(mysql_rel_id, "mysql-provider/0")
        harness.update_relation_data(mysql_rel_id, "mysql-provider/0", mysql_data)

        # object storage relation
        os_data = {
            "_supported_versions": "- v1",
            "data": yaml.dump(
                {
                    "access-key": "access-key",
                    "namespace": "namespace",
                    "port": 1234,
                    "secret-key": "secret-key",
                    "secure": True,
                    "service": "service",
                }
            ),
        }
        os_rel_id = harness.add_relation("object-storage", "storage-provider")
        harness.add_relation_unit(os_rel_id, "storage-provider/0")
        harness.update_relation_data(os_rel_id, "storage-provider", os_data)

        # kfp-viz relation
        kfp_viz_data = {
            "_supported_versions": "- v1",
            "data": yaml.dump({"service-name": "unset", "service-port": "1234"}),
        }
        kfp_viz_id = harness.add_relation("kfp-viz", "kfp-viz")
        harness.add_relation_unit(kfp_viz_id, "kfp-viz/0")
        harness.update_relation_data(kfp_viz_id, "kfp-viz", kfp_viz_data)

        # example kfp-api provider relation
        kfpapi_data = {
            "_supported_versions": "- v1",
        }
        kfpapi_rel_id = harness.add_relation(kfpapi_relation_name, "kfp-api-subscriber")
        harness.add_relation_unit(kfpapi_rel_id, "kfp-api-subscriber/0")
        harness.update_relation_data(kfpapi_rel_id, "kfp-api-subscriber", kfpapi_data)

        harness.begin_with_initial_hooks()
        harness.container_pebble_ready("ml-pipeline-api-server")
        this_app_name = harness.charm.model.app.name

        # Test that we sent data to anyone subscribing to us
        kfpapi_expected_versions = ["v1"]
        kfpapi_expected_data = {
            "service-name": f"{this_app_name}.{model_name}",
            "service-port": service_port,
        }
        kfpapi_sent_data = harness.get_relation_data(kfpapi_rel_id, "kfp-api")
        assert yaml.safe_load(kfpapi_sent_data["_supported_versions"]) == kfpapi_expected_versions
        assert yaml.safe_load(kfpapi_sent_data["data"]) == kfpapi_expected_data

        # confirm that we can serialize the pod spec and that the unit is active
        assert harness.charm.model.unit.status == ActiveStatus()

        # test K8S resources were applied
        k8s_resource_handler.apply.assert_called()

        # test Pebble
        assert harness.charm.container.get_service("ml-pipeline-api-server").is_running()
        pebble_plan = harness.get_container_pebble_plan("ml-pipeline-api-server")
        assert pebble_plan
        assert pebble_plan.services
        pebble_plan_info = pebble_plan.to_dict()
        assert pebble_plan_info["services"]["ml-pipeline-api-server"]["command"] == (
            "/bin/apiserver "
            "--config=/config "
            "--sampleconfig=/config/sample_config.json "
            "-logtostderr=true "
        )
        test_env = pebble_plan_info["services"]["ml-pipeline-api-server"]["environment"]
        # there should be 1 environment variable
        assert 1 == len(test_env)
        assert "test_model" == test_env["POD_NAMESPACE"]
