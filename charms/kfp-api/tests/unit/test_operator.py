# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

from contextlib import nullcontext as does_not_raise
from unittest.mock import MagicMock, patch

import pytest
import yaml
from charmed_kubeflow_chisme.kubernetes import KubernetesResourceHandler
from ops.model import ActiveStatus, BlockedStatus, MaintenanceStatus, WaitingStatus
from ops.testing import Harness

from charm import KFP_API_SERVICE_NAME, ErrorWithStatus, KfpApiOperator

KFP_API_CONTAINER_NAME = "apiserver"


@pytest.fixture()
def mocked_resource_handler(mocker):
    """Yields a mocked resource handler with a mocked Lightkube Client."""
    mocked_resource_handler = MagicMock()
    mocked_resource_handler_factory = mocker.patch("charm.KubernetesResourceHandler")

    def return_krh_with_mocked_lightkube(*args, **kwargs):
        kwargs["lightkube_client"] = MagicMock()
        return KubernetesResourceHandler(*args, **kwargs)

    mocked_resource_handler_factory.side_effect = return_krh_with_mocked_lightkube
    yield mocked_resource_handler


@pytest.fixture()
def mocked_kubernetes_service_patcher(mocker):
    mocked_service_patcher = mocker.patch("charm.KubernetesServicePatch")
    mocked_service_patcher.return_value = lambda x, y: None
    yield mocked_service_patcher


@pytest.fixture(scope="function")
def harness() -> Harness:
    """Create and return Harness for testing."""
    harness = Harness(KfpApiOperator)

    # setup container networking simulation
    harness.set_can_connect(KFP_API_CONTAINER_NAME, True)

    # Set required model name
    harness.set_model_name("kubeflow")

    return harness


class TestCharm:
    """Test class for KfamApiOperator."""

    @patch("charm.KubernetesServicePatch", lambda x, y: None)
    @patch("charm.KfpApiOperator.k8s_resource_handler")
    def test_log_forwarding(self, k8s_resource_handler: MagicMock, harness: Harness):
        with patch("charm.LogForwarder") as mock_logging:
            harness.begin()
            mock_logging.assert_called_once_with(charm=harness.charm)

    @patch("charm.KubernetesServicePatch", lambda x, y: None)
    @patch("charm.KfpApiOperator.k8s_resource_handler")
    def test_not_leader(self, k8s_resource_handler: MagicMock, harness: Harness):
        harness.begin_with_initial_hooks()
        harness.container_pebble_ready(KFP_API_CONTAINER_NAME)
        assert harness.charm.model.unit.status == WaitingStatus("Waiting for leadership")

    @patch("charm.KubernetesServicePatch", lambda x, y: None)
    @patch("charm.KfpApiOperator.k8s_resource_handler")
    def test_check_model_name_failure(self, k8s_resource_handler: MagicMock, harness: Harness):
        """Tests that the charm blocks if model name is not 'kubeflow'."""
        harness.set_model_name("not-kubeflow")
        harness.begin_with_initial_hooks()
        assert isinstance(harness.charm.model.unit.status, BlockedStatus)
        assert harness.charm.model.unit.status.message.startswith("kfp-api must be deployed to")

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
    @patch("charm.KubernetesServicePatch", lambda x, y: None)
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
        harness.container_pebble_ready(KFP_API_CONTAINER_NAME)

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
            harness.charm._get_db_data()

    @patch("charm.KubernetesServicePatch", lambda x, y: None)
    def test_mysql_relation_too_many_relations(self, harness: Harness):
        harness.set_leader(True)
        harness.begin()
        harness.container_pebble_ready(KFP_API_CONTAINER_NAME)

        mysql_app = "mysql_app"
        mysql_unit = f"{mysql_app}/0"

        rel_id = harness.add_relation("mysql", mysql_app)
        harness.add_relation_unit(rel_id, mysql_unit)
        rel_id_2 = harness.add_relation("mysql", "extra_sql")
        with pytest.raises(ErrorWithStatus) as too_many_relations:
            harness.add_relation_unit(rel_id_2, "extra_sql/0")
        assert too_many_relations.value.status == BlockedStatus(
            "Too many mysql relations. Relation mysql is deprecated."
        )

    @patch("charm.KubernetesServicePatch", lambda x, y: None)
    def test_kfp_viz_relation_missing(self, harness: Harness):
        harness.set_leader(True)
        harness.begin()
        harness.container_pebble_ready(KFP_API_CONTAINER_NAME)

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
                WaitingStatus(
                    "List of <ops.model.Relation object-storage:0> "
                    "versions not found for apps: other-app"
                ),
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
                WaitingStatus("Waiting for object-storage relation data"),
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
                BlockedStatus("Failed to validate data on object-storage:0 from other-app"),
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
                WaitingStatus(
                    "List of <ops.model.Relation kfp-viz:0> "
                    "versions not found for apps: other-app"
                ),
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
                WaitingStatus("Waiting for kfp-viz relation data"),
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
                BlockedStatus("Failed to validate data on kfp-viz:0 from other-app"),
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
    @patch("charm.KubernetesServicePatch", lambda x, y: None)
    def test_relations_that_provide_data(
        self,
        relation_name,
        relation_data,
        expected_returned_data,
        expected_raises,
        expected_status,
        harness: Harness,
        mocked_resource_handler,
    ):
        harness.set_leader(True)
        harness.begin()
        harness.container_pebble_ready(KFP_API_CONTAINER_NAME)

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

    @patch("charm.KubernetesServicePatch", lambda x, y: None)
    @patch("charm.KfpApiOperator.k8s_resource_handler")
    def test_install_with_all_inputs_and_pebble(
        self,
        k8s_resource_handler: MagicMock,
        harness: Harness,
    ):
        """Test complete installation with all required relations and verify pebble layer."""
        harness.set_leader(True)
        model_name = "kubeflow"
        service_port = "8888"
        harness.set_model_name(model_name)
        harness.update_config({"http-port": service_port})

        # Set up required relations
        (
            mysql_data,
            objectstorage_data,
            kfp_viz_data,
            kfpapi_rel_id,
        ) = self.setup_required_relations(harness)

        harness.begin_with_initial_hooks()
        harness.container_pebble_ready(KFP_API_CONTAINER_NAME)
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
        assert harness.charm.container.get_service("apiserver").is_running()
        pebble_plan = harness.get_container_pebble_plan(KFP_API_CONTAINER_NAME)
        assert pebble_plan
        assert pebble_plan.services
        pebble_plan_info = pebble_plan.to_dict()
        pebble_exec_command = pebble_plan_info["services"][KFP_API_SERVICE_NAME]["command"]
        exec_command = (
            # TODO: Remove 'sleep' as soon as a fix for
            # https://github.com/canonical/pebble/issues/240 is provided
            "sleep 1.1 && "
            "/bin/apiserver "
            "--config=/config "
            "--sampleconfig=/config/sample_config.json "
            "-logtostderr=true "
            f"--logLevel={harness.charm.config['log-level']}"
        )
        assert pebble_exec_command == f"bash -c '{exec_command}'"

        expected_env = {
            "AUTO_UPDATE_PIPELINE_DEFAULT_VERSION": harness.charm.config[
                "auto-update-default-version"
            ],
            "KFP_API_SERVICE_NAME": KFP_API_SERVICE_NAME,
            "KUBEFLOW_USERID_HEADER": "kubeflow-userid",
            "KUBEFLOW_USERID_PREFIX": "",
            "POD_NAMESPACE": harness.charm.model.name,
            "OBJECTSTORECONFIG_SECURE": "false",
            "OBJECTSTORECONFIG_BUCKETNAME": harness.charm.config["object-store-bucket-name"],
            "DBCONFIG_CONMAXLIFETIME": "120s",
            "DB_DRIVER_NAME": "mysql",
            "DBCONFIG_MYSQLCONFIG_USER": "root",
            "DBCONFIG_MYSQLCONFIG_PASSWORD": mysql_data["root_password"],
            "DBCONFIG_MYSQLCONFIG_DBNAME": mysql_data["database"],
            "DBCONFIG_MYSQLCONFIG_HOST": mysql_data["host"],
            "DBCONFIG_MYSQLCONFIG_PORT": mysql_data["port"],
            "OBJECTSTORECONFIG_ACCESSKEY": objectstorage_data["access-key"],
            "OBJECTSTORECONFIG_SECRETACCESSKEY": objectstorage_data["secret-key"],
            "DEFAULTPIPELINERUNNERSERVICEACCOUNT": "default-editor",
            "MULTIUSER": "true",
            "VISUALIZATIONSERVICE_NAME": kfp_viz_data["service-name"],
            "VISUALIZATIONSERVICE_PORT": kfp_viz_data["service-port"],
            "LOG_LEVEL": harness.charm.config["log-level"],
            "ML_PIPELINE_VISUALIZATIONSERVER_SERVICE_HOST": kfp_viz_data["service-name"],
            "ML_PIPELINE_VISUALIZATIONSERVER_SERVICE_PORT": kfp_viz_data["service-port"],
            "PIPELINE_LOG_LEVEL": "1",
            "PUBLISH_LOGS": "true",
            "CACHE_IMAGE": harness.charm.config["cache-image"],
            "V2_DRIVER_IMAGE": harness.charm.config["driver-image"],
            "V2_LAUNCHER_IMAGE": harness.charm.config["launcher-image"],
            "ARCHIVE_CONFIG_LOG_FILE_NAME": harness.charm.config["log-archive-filename"],
            "ARCHIVE_CONFIG_LOG_PATH_PREFIX": harness.charm.config["log-archive-prefix"],
            # OBJECTSTORECONFIG_HOST and _PORT currently have no effect due to
            # https://github.com/kubeflow/pipelines/issues/9689, described more in
            # https://github.com/canonical/minio-operator/pull/151
            # They're included here so that when the upstream issue is fixed we don't break
            "OBJECTSTORECONFIG_HOST": (
                f"{objectstorage_data['service']}.{objectstorage_data['namespace']}"
            ),
            "OBJECTSTORECONFIG_PORT": str(objectstorage_data["port"]),
            "OBJECTSTORECONFIG_REGION": "",
        }
        test_env = pebble_plan_info["services"][KFP_API_SERVICE_NAME]["environment"]

        assert test_env == expected_env
        assert model_name == test_env["POD_NAMESPACE"]

    @patch("charm.KubernetesServicePatch", lambda x, y: None)
    @patch("charm.KfpApiOperator.k8s_resource_handler")
    def test_launcher_driver_images_config(
        self,
        k8s_resource_handler: MagicMock,
        harness: Harness,
    ):
        """Test complete installation with all required relations and verify pebble layer."""
        harness.set_leader(True)
        model_name = "kubeflow"
        service_port = "8888"
        harness.set_model_name(model_name)
        harness.update_config({"http-port": service_port})
        harness.update_config({"launcher-image": "fake-launcher-image"})
        harness.update_config({"driver-image": "fake-driver-image"})

        # Set up required relations
        self.setup_required_relations(harness)

        harness.begin_with_initial_hooks()
        harness.container_pebble_ready(KFP_API_CONTAINER_NAME)

        # test Pebble
        pebble_plan = harness.get_container_pebble_plan(KFP_API_CONTAINER_NAME)
        pebble_plan_info = pebble_plan.to_dict()
        test_env = pebble_plan_info["services"][KFP_API_SERVICE_NAME]["environment"]

        assert test_env["V2_LAUNCHER_IMAGE"] == "fake-launcher-image"
        assert test_env["V2_DRIVER_IMAGE"] == "fake-driver-image"
        assert model_name == test_env["POD_NAMESPACE"]

    @patch("charm.KubernetesServicePatch", lambda x, y: None)
    @patch("charm.KfpApiOperator._apply_k8s_resources")
    @patch("charm.KfpApiOperator._check_status")
    @patch("charm.KfpApiOperator._generate_environment")
    def test_update_status(
        self,
        _apply_k8s_resources: MagicMock,
        _check_status: MagicMock,
        _generate_environment: MagicMock,
        harness: Harness,
    ):
        """Test update status handler."""
        harness.set_leader(True)
        harness.begin_with_initial_hooks()
        harness.container_pebble_ready(KFP_API_CONTAINER_NAME)

        # test successful update status
        _apply_k8s_resources.reset_mock()
        harness.charm.on.update_status.emit()
        # this will enforce the design in which main event handler is executed in update-status
        _apply_k8s_resources.assert_called()
        # check status should be called
        _check_status.assert_called()

    def _get_relation_db_only_side_effect_func(self, relation):
        """Returns relational-db relation with some data."""
        if relation == "mysql":
            return None
        if relation == "relational-db":
            return {"some-data": True}

    def test_relational_db_relation_no_data(
        self,
        mocked_resource_handler,
        mocked_kubernetes_service_patcher,
        harness: Harness,
    ):
        """Test that error is raised when relational-db has empty data."""
        database = MagicMock()
        fetch_relation_data = MagicMock()
        # setup empty data for library function to return
        fetch_relation_data.return_value = {}
        database.fetch_relation_data = fetch_relation_data
        harness.model.get_relation = MagicMock(
            side_effect=self._get_relation_db_only_side_effect_func
        )
        harness.begin()
        harness.charm.database = database
        with pytest.raises(ErrorWithStatus) as err:
            harness.charm._get_db_data()
        assert err.value.status_type(WaitingStatus)
        assert "Waiting for relational-db data" in str(err)

    def test_relational_db_relation_missing_attributes(
        self,
        mocked_resource_handler,
        mocked_kubernetes_service_patcher,
        harness: Harness,
    ):
        """Test that error is raised when relational-db has missing attributes data."""
        database = MagicMock()
        fetch_relation_data = MagicMock()
        # setup empty data for library function to return
        fetch_relation_data.return_value = {"test-db-data": {"password": "password1"}}
        database.fetch_relation_data = fetch_relation_data
        harness.model.get_relation = MagicMock(
            side_effect=self._get_relation_db_only_side_effect_func
        )
        harness.begin()
        harness.charm.database = database
        with pytest.raises(ErrorWithStatus) as err:
            harness.charm._get_db_data()
        assert err.value.status_type(WaitingStatus)
        assert "Incorrect/incomplete data found in relation relational-db. See logs" in str(err)

    def test_relational_db_relation_bad_data(
        self,
        mocked_resource_handler,
        mocked_kubernetes_service_patcher,
        harness: Harness,
    ):
        """Test that error is raised when relational-db has bad data."""
        database = MagicMock()
        fetch_relation_data = MagicMock()
        # setup bad data for library function to return
        fetch_relation_data.return_value = {"test-db-data": {"bad": "data"}}
        database.fetch_relation_data = fetch_relation_data
        harness.model.get_relation = MagicMock(
            side_effect=self._get_relation_db_only_side_effect_func
        )
        harness.begin()
        harness.charm.database = database
        with pytest.raises(ErrorWithStatus) as err:
            harness.charm._get_db_data()
        assert err.value.status_type(WaitingStatus)
        assert "Incorrect/incomplete data found in relation relational-db. See logs" in str(err)

    def test_relational_db_relation_with_data(
        self,
        mocked_resource_handler,
        mocked_kubernetes_service_patcher,
        harness: Harness,
    ):
        """Test that correct data is returned when data is in relational-db relation."""
        database = MagicMock()
        fetch_relation_data = MagicMock()
        fetch_relation_data.return_value = {
            "test-db-data": {
                "endpoints": "host:1234",
                "username": "username",
                "password": "password",
            }
        }
        database.fetch_relation_data = fetch_relation_data
        harness.model.get_relation = MagicMock(
            side_effect=self._get_relation_db_only_side_effect_func
        )
        harness.begin()
        harness.charm.database = database
        res = harness.charm._get_db_data()
        for key, val in res.items():
            assert key, val in {
                "db_name": "mlpipeline",
                "db_password": "password",
                "db_username": "username",
                "db_host": "host",
                "db_port": "1234",
            }

    def test_relational_db_relation_broken(
        self,
        mocked_resource_handler,
        mocked_kubernetes_service_patcher,
        harness: Harness,
    ):
        """Test that a relation broken event is properly handled."""
        # Arrange
        database = MagicMock()
        fetch_relation_data = MagicMock(side_effect=KeyError())
        database.fetch_relation_data = fetch_relation_data
        harness.model.get_relation = MagicMock(
            side_effect=self._get_relation_db_only_side_effect_func
        )

        rel_name = "relational-db"
        rel_id = harness.add_relation(rel_name, "relational-db-provider")

        harness.begin()

        # Mock the object storage data access to keep it from blocking the charm
        # Cannot mock by adding a relation to the harness because harness.model.get_relation is
        # mocked above to be specific to the db relation.  This test's mocks could use a refactor.
        objectstorage_data = {
            "access-key": "access-key",
            "namespace": "namespace",
            "port": 1234,
            "secret-key": "secret-key",
            "secure": True,
            "service": "service",
        }
        harness.charm._get_object_storage = MagicMock(return_value=objectstorage_data)
        harness.set_leader(True)

        # Act and Assert
        harness.container_pebble_ready(KFP_API_CONTAINER_NAME)

        assert harness.model.unit.status == WaitingStatus("Waiting for relational-db data")

        harness.charm.database = database
        del harness.model.get_relation

        harness._emit_relation_broken(rel_name, rel_id, "kfp-api")

        assert harness.model.unit.status == BlockedStatus(
            "Please add required database relation: eg. relational-db"
        )

        harness.charm.on.remove.emit()
        assert harness.model.unit.status == MaintenanceStatus("K8S resources removed")

    def test_minio_service_rendered_as_expected(
        self,
        mocker,
        mocked_kubernetes_service_patcher,
        harness: Harness,
    ):
        # Arrange

        # object storage relation
        objectstorage_data = {
            "access-key": "access-key",
            "namespace": "namespace",
            "port": 1234,
            "secret-key": "secret-key",
            "secure": True,
            "service": "service",
        }
        objectstorage_data_dict = {
            "_supported_versions": "- v1",
            "data": yaml.dump(objectstorage_data),
        }
        objectstorage_rel_id = harness.add_relation("object-storage", "storage-provider")
        harness.add_relation_unit(objectstorage_rel_id, "storage-provider/0")
        harness.update_relation_data(
            objectstorage_rel_id, "storage-provider", objectstorage_data_dict
        )

        harness.set_leader(True)
        model_name = "kubeflow"
        harness.set_model_name(model_name)
        harness.begin()

        # Mock the KubernetesResourceHandler to always have a mocked Lightkube Client
        mocked_resource_handler_factory = mocker.patch("charm.KubernetesResourceHandler")

        def return_krh_with_mocked_lightkube(*args, **kwargs):
            kwargs["lightkube_client"] = MagicMock()
            return KubernetesResourceHandler(*args, **kwargs)

        mocked_resource_handler_factory.side_effect = return_krh_with_mocked_lightkube

        # Act
        krh = harness.charm.k8s_resource_handler
        manifests = krh.render_manifests()

        # Assert that manifests include a Service(name='minio-service'), and that it has the
        # expected configuration data from object-storage
        minio_service = next(
            (m for m in manifests if m.kind == "Service" and m.metadata.name == "minio-service"),
            None,
        )
        assert minio_service.metadata.namespace == harness.charm.model.name
        assert (
            minio_service.spec.externalName
            == f"{objectstorage_data['service']}.{objectstorage_data['namespace']}"
            f".svc.cluster.local"
        )
        assert len(minio_service.spec.ports) == 1
        assert minio_service.spec.ports[0].targetPort == objectstorage_data["port"]

    def setup_required_relations(self, harness: Harness):
        kfpapi_relation_name = "kfp-api"

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
        objectstorage_data = {
            "access-key": "access-key",
            "namespace": "namespace",
            "port": 1234,
            "secret-key": "secret-key",
            "secure": True,
            "service": "service",
        }
        objectstorage_data_dict = {
            "_supported_versions": "- v1",
            "data": yaml.dump(objectstorage_data),
        }
        objectstorage_rel_id = harness.add_relation("object-storage", "storage-provider")
        harness.add_relation_unit(objectstorage_rel_id, "storage-provider/0")
        harness.update_relation_data(
            objectstorage_rel_id, "storage-provider", objectstorage_data_dict
        )

        # kfp-viz relation
        kfp_viz_data = {
            "service-name": "viz-service",
            "service-port": "1234",
        }
        kfp_viz_data_dict = {"_supported_versions": "- v1", "data": yaml.dump(kfp_viz_data)}
        kfp_viz_id = harness.add_relation("kfp-viz", "kfp-viz")
        harness.add_relation_unit(kfp_viz_id, "kfp-viz/0")
        harness.update_relation_data(kfp_viz_id, "kfp-viz", kfp_viz_data_dict)

        # example kfp-api provider relation
        kfpapi_data = {
            "_supported_versions": "- v1",
        }
        kfpapi_rel_id = harness.add_relation(kfpapi_relation_name, "kfp-api-subscriber")
        harness.add_relation_unit(kfpapi_rel_id, "kfp-api-subscriber/0")
        harness.update_relation_data(kfpapi_rel_id, "kfp-api-subscriber", kfpapi_data)

        return mysql_data, objectstorage_data, kfp_viz_data, kfpapi_rel_id
