#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Charm the Kubeflow Pipelines API.

https://github.com/canonical/kfp-operators/
"""

import logging
from pathlib import Path

from charmed_kubeflow_chisme.exceptions import ErrorWithStatus, GenericCharmRuntimeError
from charmed_kubeflow_chisme.kubernetes import (
    KubernetesResourceHandler,
    create_charm_default_labels,
)
from charmed_kubeflow_chisme.pebble import update_layer
from charms.data_platform_libs.v0.data_interfaces import DatabaseRequires
from charms.grafana_k8s.v0.grafana_dashboard import GrafanaDashboardProvider
from charms.loki_k8s.v1.loki_push_api import LogForwarder
from charms.observability_libs.v1.kubernetes_service_patch import KubernetesServicePatch
from charms.prometheus_k8s.v0.prometheus_scrape import MetricsEndpointProvider
from jsonschema import ValidationError
from lightkube import ApiError
from lightkube.generic_resource import load_in_cluster_generic_resources
from lightkube.models.core_v1 import ServicePort
from lightkube.resources.core_v1 import Service, ServiceAccount
from lightkube.resources.rbac_authorization_v1 import ClusterRole, ClusterRoleBinding
from ops import main
from ops.charm import CharmBase
from ops.model import ActiveStatus, BlockedStatus, MaintenanceStatus, ModelError, WaitingStatus
from ops.pebble import CheckStatus, Layer
from serialized_data_interface import (
    NoCompatibleVersions,
    NoVersionsListed,
    SerializedDataInterface,
    get_interfaces,
)
from serialized_data_interface.errors import RelationDataError

CONFIG_DIR = Path("/config")
SAMPLE_CONFIG = CONFIG_DIR / "sample_config.json"
METRICS_PATH = "/metrics"
PROBE_PATH = "/apis/v1beta1/healthz"

K8S_RESOURCE_FILES = [
    "src/templates/auth_manifests.yaml.j2",
    "src/templates/ml-pipeline-service.yaml.j2",
    "src/templates/minio-service.yaml.j2",
]
MYSQL_WARNING = "Relation mysql is deprecated."
UNBLOCK_MESSAGE = "Remove deprecated mysql relation to unblock."
KFP_API_SERVICE_NAME = "apiserver"


class KfpApiOperator(CharmBase):
    """Charm the Kubeflow Pipelines API."""

    def __init__(self, *args):
        super().__init__(*args)

        # retrieve configuration and base settings
        self.logger = logging.getLogger(__name__)
        self._namespace = self.model.name
        self._lightkube_field_manager = "lightkube"
        self._name = self.model.app.name
        self._grcp_port = self.model.config["grpc-port"]
        self._http_port = self.model.config["http-port"]
        self._exec_command = (
            # TODO: Remove 'sleep' as soon as a fix for
            # https://github.com/canonical/pebble/issues/240 is provided
            "sleep 1.1 && "
            "/bin/apiserver "
            f"--config={CONFIG_DIR} "
            f"--sampleconfig={SAMPLE_CONFIG} "
            "-logtostderr=true "
            f"--logLevel={self.model.config['log-level']}"
        )
        self._container_name = "apiserver"
        self._database_name = "mlpipeline"
        self._container = self.unit.get_container(self._container_name)

        self._k8s_resource_handler = None

        grpc_port = ServicePort(int(self._grcp_port), name="grpc-port")
        http_port = ServicePort(int(self._http_port), name="http-port")
        self.service_patcher = KubernetesServicePatch(
            self,
            [grpc_port, http_port],
        )

        # setup events to be handled by main event handler
        self.framework.observe(self.on.leader_elected, self._on_event)
        self.framework.observe(self.on.config_changed, self._on_event)
        self.framework.observe(self.on.apiserver_pebble_ready, self._on_event)
        change_events = [
            self.on["object-storage"].relation_changed,
            self.on["kfp-viz"].relation_changed,
            self.on["kfp-api"].relation_changed,
        ]
        for event in change_events:
            self.framework.observe(event, self._on_event)

        # setup events to be handled by specific event handlers
        self.framework.observe(self.on.install, self._on_install)
        self.framework.observe(self.on.upgrade_charm, self._on_upgrade)
        self.framework.observe(self.on.remove, self._on_remove)
        self.framework.observe(self.on.update_status, self._on_update_status)
        self.framework.observe(self.on["mysql"].relation_joined, self._on_mysql_relation)
        self.framework.observe(self.on["mysql"].relation_changed, self._on_mysql_relation)
        self.framework.observe(self.on["mysql"].relation_departed, self._on_mysql_relation_remove)
        self.framework.observe(self.on["mysql"].relation_broken, self._on_mysql_relation_remove)
        self.framework.observe(
            self.on["relational-db"].relation_joined, self._on_relational_db_relation
        )
        self.framework.observe(
            self.on["relational-db"].relation_changed, self._on_relational_db_relation
        )
        self.framework.observe(
            self.on["relational-db"].relation_departed, self._on_relational_db_relation_remove
        )
        self.framework.observe(
            self.on["relational-db"].relation_broken, self._on_relational_db_relation_remove
        )

        # setup relational database interface and observers
        self.database = DatabaseRequires(
            self, relation_name="relational-db", database_name=self._database_name
        )
        self.framework.observe(self.database.on.database_created, self._on_relational_db_relation)
        self.framework.observe(self.database.on.endpoints_changed, self._on_relational_db_relation)

        self.prometheus_provider = MetricsEndpointProvider(
            charm=self,
            relation_name="metrics-endpoint",
            jobs=[
                {
                    "metrics_path": METRICS_PATH,
                    "static_configs": [{"targets": ["*:{}".format(self.config["http-port"])]}],
                }
            ],
        )

        self.dashboard_provider = GrafanaDashboardProvider(self)

        self._logging = LogForwarder(charm=self)

    @property
    def _charm_default_kubernetes_labels(self):
        """Return default labels for Kubernetes resources."""
        return create_charm_default_labels(
            application_name=self.model.app.name,
            model_name=self.model.name,
            scope="all-resources",
        )

    @property
    def container(self):
        """Return container."""
        return self._container

    @property
    def _context(self):
        """Return the context used for generating kubernetes resources."""
        interfaces = self._get_interfaces()
        object_storage = self._get_object_storage(interfaces)

        minio_url = f"{object_storage['service']}.{object_storage['namespace']}.svc.cluster.local"

        context = {
            "app_name": self._name,
            "namespace": self._namespace,
            "service": self._name,
            "grpc_port": self._grcp_port,
            "http_port": self._http_port,
            # Must include .svc.cluster.local for DNS resolution
            "minio_url": minio_url,
            "minio_port": str(object_storage["port"]),
        }
        return context

    @property
    def k8s_resource_handler(self):
        """Update K8S with K8S resources."""
        if not self._k8s_resource_handler:
            self._k8s_resource_handler = KubernetesResourceHandler(
                field_manager=self._lightkube_field_manager,
                template_files=K8S_RESOURCE_FILES,
                context=self._context,
                logger=self.logger,
                labels=self._charm_default_kubernetes_labels,
                resource_types={Service, ServiceAccount, ClusterRole, ClusterRoleBinding},
            )
        load_in_cluster_generic_resources(self._k8s_resource_handler.lightkube_client)
        return self._k8s_resource_handler

    @k8s_resource_handler.setter
    def k8s_resource_handler(self, handler: KubernetesResourceHandler):
        self._k8s_resource_handler = handler

    @property
    def service_environment(self):
        """Return environment variables based on model configuration."""
        return self._generate_environment()

    @property
    def _kfp_api_layer(self) -> Layer:
        """Create and return Pebble framework layer."""
        # The service name should be the same as the one
        # defined in the Rockcraft project: apiserver
        layer_config = {
            "summary": "kfp-api layer",
            "description": "Pebble config layer for kfp-api",
            "services": {
                KFP_API_SERVICE_NAME: {
                    "override": "replace",
                    "summary": "ML Pipeline API Server",
                    "command": f"bash -c '{self._exec_command}'",
                    "startup": "enabled",
                    "environment": self.service_environment,
                    "on-check-failure": {"kfp-api-up": "restart"},
                }
            },
            "checks": {
                "kfp-api-up": {
                    "override": "replace",
                    "period": "5m",
                    "timeout": "60s",
                    "threshold": 3,
                    "http": {"url": f"http://localhost:{self.config['http-port']}{PROBE_PATH}"},
                }
            },
        }

        return Layer(layer_config)

    def _generate_environment(self) -> dict:
        """Generate environment based on supplied data.

        Configuration is generated based on:
        - Supplied interfaces.
        - Database data: from MySQL relation data or from data platform library.
        - Model configuration.

        Return:
            env_vars(dict): a dictionary of environment variables for the api server.
        """

        try:
            interfaces = self._get_interfaces()
            db_data = self._get_db_data()
            object_storage = self._get_object_storage(interfaces)
            viz_data = self._get_viz(interfaces)
        except ErrorWithStatus as error:
            self.logger.error("Failed to generate container configuration.")
            raise error

        env_vars = {
            # Configurations that are also defined in the upstream manifests
            "AUTO_UPDATE_PIPELINE_DEFAULT_VERSION": self.model.config[
                "auto-update-default-version"
            ],
            "KFP_API_SERVICE_NAME": KFP_API_SERVICE_NAME,
            "KUBEFLOW_USERID_HEADER": "kubeflow-userid",
            "KUBEFLOW_USERID_PREFIX": "",
            "POD_NAMESPACE": self.model.name,
            "OBJECTSTORECONFIG_SECURE": "false",
            "OBJECTSTORECONFIG_BUCKETNAME": self.model.config["object-store-bucket-name"],
            "DBCONFIG_CONMAXLIFETIME": "120s",
            "DB_DRIVER_NAME": "mysql",
            "DBCONFIG_MYSQLCONFIG_USER": db_data["db_username"],
            "DBCONFIG_MYSQLCONFIG_PASSWORD": db_data["db_password"],
            "DBCONFIG_MYSQLCONFIG_DBNAME": db_data["db_name"],
            "DBCONFIG_MYSQLCONFIG_HOST": db_data["db_host"],
            "DBCONFIG_MYSQLCONFIG_PORT": db_data["db_port"],
            "OBJECTSTORECONFIG_ACCESSKEY": object_storage["access-key"],
            "OBJECTSTORECONFIG_SECRETACCESSKEY": object_storage["secret-key"],
            "DEFAULTPIPELINERUNNERSERVICEACCOUNT": "default-editor",
            "MULTIUSER": "true",
            "VISUALIZATIONSERVICE_NAME": viz_data["service-name"],
            "VISUALIZATIONSERVICE_PORT": viz_data["service-port"],
            "LOG_LEVEL": self.model.config["log-level"],
            "ML_PIPELINE_VISUALIZATIONSERVER_SERVICE_HOST": viz_data["service-name"],
            "ML_PIPELINE_VISUALIZATIONSERVER_SERVICE_PORT": viz_data["service-port"],
            "PIPELINE_LOG_LEVEL": "1",
            "PUBLISH_LOGS": "true",
            "CACHE_IMAGE": self.model.config["cache-image"],
            "V2_DRIVER_IMAGE": self.model.config["driver-image"],
            "V2_LAUNCHER_IMAGE": self.model.config["launcher-image"],
            # Configurations charmed-kubeflow adds to those of upstream
            "ARCHIVE_CONFIG_LOG_FILE_NAME": self.model.config["log-archive-filename"],
            "ARCHIVE_CONFIG_LOG_PATH_PREFIX": self.model.config["log-archive-prefix"],
            # OBJECTSTORECONFIG_HOST and _PORT set the object storage configurations,
            # taking precedence over configuration in the config.json or
            # MINIO_SERVICE_SERVICE_* environment variables.
            # NOTE: While OBJECTSTORECONFIG_HOST and _PORT control the object store
            # that the apiserver connects to, other parts of kfp currently cannot use
            # object stores with arbitrary names.  See
            # https://github.com/kubeflow/pipelines/issues/9689 and
            # https://github.com/canonical/minio-operator/pull/151 for more details.
            "OBJECTSTORECONFIG_HOST": f"{object_storage['service']}.{object_storage['namespace']}",
            "OBJECTSTORECONFIG_PORT": str(object_storage["port"]),
            "OBJECTSTORECONFIG_REGION": "",
        }

        return env_vars

    def _check_model_name(self):
        if self.model.name != "kubeflow":
            # Remove when this bug is resolved:
            # https://github.com/canonical/kfp-operators/issues/389
            raise ErrorWithStatus(
                "kfp-api must be deployed to model named `kubeflow` due to"
                " https://github.com/canonical/kfp-operators/issues/389",
                BlockedStatus,
            )

    def _check_status(self):
        """Check status of workload and set status accordingly."""
        self._check_leader()
        container = self.unit.get_container(self._container_name)
        if container:
            try:
                # verify if container is alive/up
                check = container.get_check("kfp-api-up")
            except ModelError as error:
                raise GenericCharmRuntimeError(
                    "Failed to run health check on workload container"
                ) from error

            if check.status == CheckStatus.DOWN:
                self.logger.error(
                    f"Container {self._container_name} failed health check. It will be restarted."
                )
                raise ErrorWithStatus("Workload failed health check", MaintenanceStatus)
            self.model.unit.status = ActiveStatus()

    def _send_info(self, interfaces):
        if interfaces["kfp-api"]:
            interfaces["kfp-api"].send_data(
                {
                    "service-name": f"{self.model.app.name}.{self.model.name}",
                    "service-port": self.model.config["http-port"],
                }
            )

    def _get_interfaces(self):
        # Remove this abstraction when SDI adds .status attribute to NoVersionsListed,
        # NoCompatibleVersionsListed:
        # https://github.com/canonical/serialized-data-interface/issues/26
        try:
            interfaces = get_interfaces(self)
        except NoVersionsListed as err:
            raise ErrorWithStatus((err), WaitingStatus)
        except NoCompatibleVersions as err:
            raise ErrorWithStatus(str(err), BlockedStatus)
        except RelationDataError as err:
            raise ErrorWithStatus(str(err), BlockedStatus)
        return interfaces

    def _validate_sdi_interface(self, interfaces: dict, relation_name: str, default_return=None):
        """Validates data received from SerializedDataInterface, returning the data if valid.

        Optionally can return a default_return value when no relation is established

        Raises:
            ErrorWithStatus(..., Blocked) when no relation established (unless default_return set)
            ErrorWithStatus(..., Blocked) if interface is not using SDI
            ErrorWithStatus(..., Blocked) if data in interface fails schema check
            ErrorWithStatus(..., Waiting) if we have a relation established but no data passed

        Params:
            interfaces:

        Returns:
              (dict) interface data
        """
        # If nothing is related to this relation, return a default value or raise an error
        if relation_name not in interfaces or interfaces[relation_name] is None:
            if default_return is not None:
                return default_return
            else:
                raise ErrorWithStatus(
                    f"Please add required relation {relation_name}", BlockedStatus
                )

        relations = interfaces[relation_name]
        if not isinstance(relations, SerializedDataInterface):
            raise ErrorWithStatus(
                f"Unexpected error with {relation_name} relation data - data not as expected",
                BlockedStatus,
            )

        # Get and validate data from the relation
        try:
            # relations is a dict of {(ops.model.Relation, ops.model.Application): data}
            unpacked_relation_data = relations.get_data()
        except ValidationError as val_error:
            # Validation in .get_data() ensures if data is populated, it matches the schema and is
            # not incomplete
            self.logger.error(val_error)
            raise ErrorWithStatus(
                f"Found incomplete/incorrect relation data for {relation_name}. See logs",
                BlockedStatus,
            )

        # Check if we have an established relation with no data exchanged
        if len(unpacked_relation_data) == 0:
            raise ErrorWithStatus(f"Waiting for {relation_name} relation data", WaitingStatus)

        # Unpack data (we care only about the first element)
        data_dict = list(unpacked_relation_data.values())[0]

        # Catch if empty data dict is received (JSONSchema ValidationError above does not raise
        # when this happens)
        # Remove once addressed in:
        # https://github.com/canonical/serialized-data-interface/issues/28
        if len(data_dict) == 0:
            raise ErrorWithStatus(
                f"Found empty relation data for {relation_name}",
                BlockedStatus,
            )

        return data_dict

    def _get_object_storage(self, interfaces):
        """Retrieve object-storage relation data."""
        relation_name = "object-storage"
        return self._validate_sdi_interface(interfaces, relation_name)

    def _get_viz(self, interfaces):
        """Retrieve kfp-viz relation data, return default, if empty."""
        relation_name = "kfp-viz"
        return self._validate_sdi_interface(interfaces, relation_name)

    def _check_leader(self):
        """Check if this unit is a leader."""
        if not self.unit.is_leader():
            self.logger.warning("Not a leader, skipping setup")
            raise ErrorWithStatus("Waiting for leadership", WaitingStatus)

    def _get_db_relation(self, relation_name):
        """Retrieves relation with supplied relation name, if it is established.

        Returns relation, if it is established, and raises error otherwise."""

        try:
            # retrieve relation data
            relation = self.model.get_relation(relation_name)
        except KeyError:
            # relation was not found
            relation = None
        if not relation:
            # relation is not established, raise an error
            raise GenericCharmRuntimeError(
                f"Database relation {relation_name} is not established or empty"
            )

        return relation

    def _get_mysql_data(self) -> dict:
        """Check mysql relation, retrieve and return data, if available."""
        db_data = {}
        relation_data = {}
        relation = self._get_db_relation("mysql")

        # retrieve database data from relation
        try:
            unit = next(iter(relation.units))
            relation_data = relation.data[unit]
            # retrieve database data from relation data
            # this also validates the expected data by means of KeyError exception
            db_data["db_name"] = relation_data["database"]
            db_data["db_password"] = relation_data["root_password"]
            db_data["db_username"] = "root"
            db_data["db_host"] = relation_data["host"]
            db_data["db_port"] = relation_data["port"]
        except (IndexError, StopIteration, KeyError) as err:
            # failed to retrieve database configuration
            if not relation_data:
                raise GenericCharmRuntimeError(
                    "Database relation mysql is not established or empty"
                )
            self.logger.error(f"Missing attribute {err} in mysql relation data")
            # incorrect/incomplete data can be found in mysql relation which can be resolved:
            # use WaitingStatus
            raise ErrorWithStatus(
                "Incorrect/incomplete data found in relation mysql. See logs", WaitingStatus
            )

        return db_data

    def _get_relational_db_data(self) -> dict:
        """Check relational-db relation, retrieve and return data, if available."""
        db_data = {}
        relation_data = {}

        self._get_db_relation("relational-db")

        # retrieve database data from library
        try:
            # if called in response to a '*-relation-broken' event, this will raise an exception
            relation_data = self.database.fetch_relation_data()
        except KeyError:
            self.logger.error("Failed to retrieve relation data from library")
            raise GenericCharmRuntimeError(
                "Failed to retrieve relational-db data. This is to be expected if executed in"
                " response to a '*-relation-broken' event"
            )
        # parse data in relation
        # this also validates expected data by means of KeyError exception
        for val in relation_data.values():
            if not val:
                continue
            try:
                db_data["db_name"] = self._database_name
                db_data["db_password"] = val["password"]
                db_data["db_username"] = val["username"]
                host, port = val["endpoints"].split(":")
                db_data["db_host"] = host
                db_data["db_port"] = port
            except KeyError as err:
                self.logger.error(f"Missing attribute {err} in relational-db relation data")
                # incorrect/incomplete data can be found in mysql relation which can be
                # resolved: use WaitingStatus
                raise ErrorWithStatus(
                    "Incorrect/incomplete data found in relation relational-db. See logs",
                    WaitingStatus,
                )
        # report if there was no data populated
        if not db_data:
            self.logger.info("Found empty relation data for relational-db relation.")
            raise ErrorWithStatus("Waiting for relational-db data", WaitingStatus)

        return db_data

    def _get_db_data(self) -> dict:
        """Check for MySQL relations -  mysql or relational-db - and retrieve data.

        Only one database relation can be established at a time.
        """
        db_data = {}
        try:
            db_data = self._get_mysql_data()
        except ErrorWithStatus as err:
            # mysql relation is established, but data could not be retrieved
            raise err
        except GenericCharmRuntimeError:
            # mysql relation is not established, proceed to check for relational-db relation
            try:
                db_data = self._get_relational_db_data()
            except ErrorWithStatus as err:
                # relation-db relation is established, but data could not be retrieved
                raise err
            except GenericCharmRuntimeError:
                # mysql and relational-db relations are not established, raise error
                raise ErrorWithStatus(
                    "Please add required database relation: eg. relational-db", BlockedStatus
                )

        return db_data

    def _check_and_report_k8s_conflict(self, error):
        """Return True if error status code is 409 (conflict), False otherwise."""
        if error.status.code == 409:
            self.logger.warning(f"Encountered a conflict: {error}")
            return True
        return False

    def _apply_k8s_resources(self, force_conflicts: bool = False) -> None:
        """Apply K8S resources.

        Args:
            force_conflicts (bool): *(optional)* Will "force" apply requests causing conflicting
                                    fields to change ownership to the field manager used in this
                                    charm.
                                    NOTE: This will only be used if initial regular apply() fails.
        """
        self.unit.status = MaintenanceStatus("Creating K8S resources")
        try:
            self.k8s_resource_handler.apply()
        except ApiError as error:
            if self._check_and_report_k8s_conflict(error) and force_conflicts:
                # conflict detected when applying K8S resources
                # re-apply K8S resources with forced conflict resolution
                self.unit.status = MaintenanceStatus("Force applying K8S resources")
                self.logger.warning("Apply K8S resources with forced changes against conflicts")
                self.k8s_resource_handler.apply(force=force_conflicts)
            else:
                raise GenericCharmRuntimeError("K8S resources creation failed") from error
        self.model.unit.status = MaintenanceStatus("K8S resources created")

    def _on_install(self, event):
        """Installation only tasks."""
        try:
            # deploy K8S resources early to speed up deployment
            self._apply_k8s_resources()
        except ErrorWithStatus as err:
            self.model.unit.status = err.status
            self.logger.error(f"Failed to handle {event} with error: {err}")
            return

    def _on_upgrade(self, _):
        """Perform upgrade steps."""
        # force conflict resolution in K8S resources update
        self._on_event(_, force_conflicts=True)

    def _on_remove(self, _):
        """Remove all resources."""
        self.unit.status = MaintenanceStatus("Removing K8S resources")
        # Define the KubernetesResourceHandler manually because the object storage conflict in
        # `self._context` is not available anymore, and all we need is the labels/resource_types
        # to delete the resources anyway
        k8s_resource_handler = KubernetesResourceHandler(
            field_manager=self._lightkube_field_manager,
            template_files=[],
            context={},
            logger=self.logger,
            labels=self._charm_default_kubernetes_labels,
            resource_types={Service, ServiceAccount, ClusterRole, ClusterRoleBinding},
        )
        load_in_cluster_generic_resources(k8s_resource_handler.lightkube_client)
        k8s_resource_handler.delete()

        self.unit.status = MaintenanceStatus("K8S resources removed")

    def _on_update_status(self, _):
        """Update status actions."""
        try:
            self._on_event(_)
        except ErrorWithStatus:
            return

        if isinstance(self.model.unit.status, WaitingStatus) or isinstance(
            self.model.unit.status, BlockedStatus
        ):
            # do not check status in case of Waiting and Blocked states
            return

        try:
            self._check_status()
        except ErrorWithStatus as err:
            self.model.unit.status = err.status
            self.logger.error(f"Failed update status with error: {err}")
            return

        self.model.unit.status = ActiveStatus()

    def _on_mysql_relation(self, event):
        """Check for existing database relations and process mysql relation if needed."""
        # check for too many mysql relations
        mysql = self.model.relations["mysql"]
        if len(mysql) > 1:
            raise ErrorWithStatus(f"Too many mysql relations. {MYSQL_WARNING}", BlockedStatus)

        # check for relational-db relation
        # relying on KeyError to ensure that relational-db relation is not present
        try:
            relation = self.model.get_relation("relational-db")
            if relation:
                self.logger.warning(
                    "Up-to-date database relation relational-db is already established."
                )
                self.logger.error(f"{MYSQL_WARNING} {UNBLOCK_MESSAGE}")
                self.model.unit.status = BlockedStatus(f"{UNBLOCK_MESSAGE} See logs")
                return
        except KeyError:
            pass
        # relational-db relation was not found, proceed with warnings
        self.logger.warning(MYSQL_WARNING)
        self.model.unit.status = MaintenanceStatus(f"Adding mysql relation. {MYSQL_WARNING}")
        self._on_event(event)

    def _on_mysql_relation_remove(self, event):
        """Process removal of mysql relation."""
        self.model.unit.status = MaintenanceStatus(f"Removing mysql relation. {MYSQL_WARNING}")
        self._on_event(event)

    def _on_relational_db_relation(self, event):
        """Check for existing database relations and process relational-db relation if needed."""
        # relying on KeyError to ensure that mysql relation is not present
        try:
            relation = self.model.get_relation("mysql")
            if relation:
                self.logger.warning(
                    "Failed to create relational-db relation due to existing mysql relation."
                )
                self.logger.error(f"{MYSQL_WARNING} {UNBLOCK_MESSAGE}")
                self.model.unit.status = BlockedStatus(f"{UNBLOCK_MESSAGE} See logs")
                return
        except KeyError:
            pass
        # mysql relation was not found, proceed
        self.model.unit.status = MaintenanceStatus("Adding relational-db relation")
        self._on_event(event)

    def _on_relational_db_relation_remove(self, event):
        """Process removal of relational-db relation."""
        self.model.unit.status = MaintenanceStatus("Removing relational-db relation")
        self._on_event(event)

    def _on_event(self, event, force_conflicts: bool = False) -> None:
        # Set up all relations/fetch required data
        try:
            self._check_model_name()
            self._check_leader()
            self._apply_k8s_resources(force_conflicts=force_conflicts)
            update_layer(self._container_name, self._container, self._kfp_api_layer, self.logger)
            self._send_info(self._get_interfaces())
        except ErrorWithStatus as err:
            self.model.unit.status = err.status
            self.logger.error(f"Failed to handle {event} with error: {err}")
            return

        self.model.unit.status = ActiveStatus()


if __name__ == "__main__":
    main(KfpApiOperator)
