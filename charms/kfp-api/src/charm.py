#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

"""Charm the Kubeflow Pipelines API.

https://github.com/canonical/kfp-operators/
"""

import json
import logging
from pathlib import Path

from charms.grafana_k8s.v0.grafana_dashboard import GrafanaDashboardProvider
from charms.prometheus_k8s.v0.prometheus_scrape import MetricsEndpointProvider
from jsonschema import ValidationError
from oci_image import OCIImageResource, OCIImageResourceError
from ops.charm import CharmBase
from ops.main import main
from ops.model import ActiveStatus, BlockedStatus, MaintenanceStatus, WaitingStatus
from serialized_data_interface import (
    NoCompatibleVersions,
    NoVersionsListed,
    SerializedDataInterface,
    get_interfaces,
)

METRICS_PATH = "/metrics"


class KfpApiOperator(CharmBase):
    """Charm the Kubeflow Pipelines API.

    https://github.com/canonical/kfp-operators/
    """

    def __init__(self, *args):
        super().__init__(*args)

        self.log = logging.getLogger()
        self.image = OCIImageResource(self, "oci-image")

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

        change_events = [
            self.on.install,
            self.on.upgrade_charm,
            self.on.config_changed,
            self.on["mysql"].relation_changed,
            self.on["object-storage"].relation_changed,
            self.on["kfp-viz"].relation_changed,
            self.on["kfp-api"].relation_changed,
        ]
        for event in change_events:
            self.framework.observe(event, self._main)

    def _send_info(self, interfaces):
        if interfaces["kfp-api"]:
            interfaces["kfp-api"].send_data(
                {
                    "service-name": f"{self.model.app.name}.{self.model.name}",
                    "service-port": self.model.config["http-port"],
                }
            )

    def _main(self, event):
        # Set up all relations/fetch required data
        try:
            self._check_leader()
            mysql = self._get_mysql()
            interfaces = self._get_interfaces()
            image_details = self.image.fetch()
            os = self._get_object_storage(interfaces)
            viz = self._get_viz(interfaces)
        except (CheckFailedError, OCIImageResourceError) as check_failed:
            self.model.unit.status = check_failed.status
            self.log.info(str(check_failed.status))
            return

        self._send_info(interfaces)

        config, config_json = self._generate_config(mysql, os, viz)

        healthz = f"http://localhost:{config['http-port']}/apis/v1beta1/healthz"

        self.model.unit.status = MaintenanceStatus("Setting pod spec")
        self.model.pod.set_spec(
            {
                "version": 3,
                "serviceAccount": {
                    "roles": [
                        {
                            "global": True,
                            "rules": [
                                {
                                    "apiGroups": [""],
                                    "resources": ["pods", "pods/log"],
                                    "verbs": ["get", "list", "delete"],
                                },
                                {
                                    "apiGroups": ["argoproj.io"],
                                    "resources": ["workflows"],
                                    "verbs": [
                                        "create",
                                        "get",
                                        "list",
                                        "watch",
                                        "update",
                                        "patch",
                                        "delete",
                                    ],
                                },
                                {
                                    "apiGroups": ["kubeflow.org"],
                                    "resources": ["scheduledworkflows"],
                                    "verbs": [
                                        "create",
                                        "get",
                                        "list",
                                        "update",
                                        "patch",
                                        "delete",
                                    ],
                                },
                                {
                                    "apiGroups": ["authorization.k8s.io"],
                                    "resources": ["subjectaccessreviews"],
                                    "verbs": ["create"],
                                },
                                {
                                    "apiGroups": ["authentication.k8s.io"],
                                    "resources": ["tokenreviews"],
                                    "verbs": ["create"],
                                },
                            ],
                        }
                    ]
                },
                "containers": [
                    {
                        "name": "ml-pipeline-api-server",
                        "imageDetails": image_details,
                        "ports": [
                            {
                                "name": "http",
                                "containerPort": int(config["http-port"]),
                            },
                            {
                                "name": "grpc",
                                "containerPort": int(config["grpc-port"]),
                            },
                        ],
                        "envConfig": {
                            "POD_NAMESPACE": self.model.name,
                        },
                        "volumeConfig": [
                            {
                                "name": "config",
                                "mountPath": "/config",
                                "files": [
                                    {
                                        "path": "config.json",
                                        "content": json.dumps(config_json),
                                    },
                                    {
                                        "path": "sample_config.json",
                                        "content": Path("src/sample_config.json").read_text(),
                                    },
                                ],
                            }
                        ],
                        "kubernetes": {
                            "readinessProbe": {
                                "exec": {"command": ["wget", "-q", "-S", "-O", "-", healthz]},
                                "initialDelaySeconds": 3,
                                "periodSeconds": 5,
                                "timeoutSeconds": 2,
                            },
                            "livenessProbe": {
                                "exec": {"command": ["wget", "-q", "-S", "-O", "-", healthz]},
                                "initialDelaySeconds": 3,
                                "periodSeconds": 5,
                                "timeoutSeconds": 2,
                            },
                            "startupProbe": {
                                "exec": {"command": ["wget", "-q", "-S", "-O", "-", healthz]},
                                "failureThreshold": 12,
                            },
                        },
                    }
                ],
            },
            k8s_resources={
                "kubernetesResources": {
                    "services": [
                        {
                            "name": config["k8s-service-name"],
                            "spec": {
                                "selector": {"app.kubernetes.io/name": self.model.app.name},
                                "ports": [
                                    {
                                        "name": "grpc",
                                        "port": int(config["grpc-port"]),
                                        "protocol": "TCP",
                                        "targetPort": int(config["grpc-port"]),
                                    },
                                    {
                                        "name": "http",
                                        "port": int(config["http-port"]),
                                        "protocol": "TCP",
                                        "targetPort": int(config["http-port"]),
                                    },
                                ],
                            },
                        },
                    ],
                }
            },
        )
        self.model.unit.status = ActiveStatus()

    def _generate_config(self, mysql, os, viz):
        config = self.model.config
        config_json = {
            "DBConfig": {
                "ConMaxLifeTime": "120s",
                "DBName": mysql["database"],
                "DriverName": "mysql",
                "GroupConcatMaxLen": "4194304",
                "Host": mysql["host"],
                "Password": mysql["root_password"],
                "Port": mysql["port"],
                "User": "root",
            },
            "ObjectStoreConfig": {
                "AccessKey": os["access-key"],
                "BucketName": "mlpipeline",
                "Host": f"{os['service']}.{os['namespace']}",
                "Multipart": {"Disable": "true"},
                "PipelinePath": "pipelines",
                "Port": os["port"],
                "Region": "",
                "SecretAccessKey": os["secret-key"],
                "Secure": str(os["secure"]).lower(),
            },
            "ARCHIVE_CONFIG_LOG_FILE_NAME": config["log-archive-filename"],
            "ARCHIVE_CONFIG_LOG_PATH_PREFIX": config["log-archive-prefix"],
            "AUTO_UPDATE_PIPELINE_DEFAULT_VERSION": config["auto-update-default-version"],
            "CACHE_IMAGE": config["cache-image"],
            "CACHE_NODE_RESTRICTIONS": "false",
            "CacheEnabled": str(config["cache-enabled"]).lower(),
            "DefaultPipelineRunnerServiceAccount": config["runner-sa"],
            "InitConnectionTimeout": config["init-connection-timeout"],
            "KUBEFLOW_USERID_HEADER": "kubeflow-userid",
            "KUBEFLOW_USERID_PREFIX": "",
            "MULTIUSER": "true",
            "ML_PIPELINE_VISUALIZATIONSERVER_SERVICE_HOST": viz["service-name"],
            "ML_PIPELINE_VISUALIZATIONSERVER_SERVICE_PORT": viz["service-port"],
        }
        return config, config_json

    def _check_leader(self):
        if not self.unit.is_leader():
            # We can't do anything useful when not the leader, so do nothing.
            raise CheckFailedError("Waiting for leadership", WaitingStatus)

    def _get_interfaces(self):
        # Remove this abstraction when SDI adds .status attribute to NoVersionsListed,
        # NoCompatibleVersionsListed:
        # https://github.com/canonical/serialized-data-interface/issues/26
        try:
            interfaces = get_interfaces(self)
        except NoVersionsListed as err:
            raise CheckFailedError(str(err), WaitingStatus)
        except NoCompatibleVersions as err:
            raise CheckFailedError(str(err), BlockedStatus)
        return interfaces

    def _get_mysql(self):
        mysql = self.model.relations["mysql"]
        if len(mysql) == 0:
            raise CheckFailedError("Missing required relation for mysql", BlockedStatus)
        elif len(mysql) > 1:
            raise CheckFailedError("Too many mysql relations", BlockedStatus)

        try:
            mysql = mysql[0]
            unit = list(mysql.units)[0]
            mysql = mysql.data[unit]
        except Exception as e:
            self.log.error(
                f"Encountered the following exception when parsing mysql relation: " f"{str(e)}"
            )
            raise CheckFailedError(
                "Unexpected error when parsing mysql relation.  See logs", BlockedStatus
            )

        expected_attributes = ["database", "host", "root_password", "port"]

        missing_attributes = [
            attribute for attribute in expected_attributes if attribute not in mysql
        ]

        if len(missing_attributes) == len(expected_attributes):
            raise CheckFailedError("Waiting for mysql relation data", WaitingStatus)
        elif len(missing_attributes) > 0:
            self.log.error(
                f"mysql relation data missing expected attributes '{missing_attributes}'"
            )
            raise CheckFailedError(
                "Received incomplete data from mysql relation.  See logs", BlockedStatus
            )
        return mysql

    def _get_object_storage(self, interfaces):
        relation_name = "object-storage"
        return self._validate_sdi_interface(interfaces, relation_name)

    def _get_viz(self, interfaces):
        relation_name = "kfp-viz"
        default_viz_data = {"service-name": "unset", "service-port": "1234"}
        return self._validate_sdi_interface(
            interfaces, relation_name, default_return=default_viz_data
        )

    def _validate_sdi_interface(self, interfaces: dict, relation_name: str, default_return=None):
        """Validates data received from SerializedDataInterface, returning the data if valid.

        Optionally can return a default_return value when no relation is established

        Raises:
            CheckFailed(..., Blocked) when no relation established (unless default_return set)
            CheckFailed(..., Blocked) if interface is not using SDI
            CheckFailed(..., Blocked) if data in interface fails schema check
            CheckFailed(..., Waiting) if we have a relation established but no data passed

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
                raise CheckFailedError(
                    f"Missing required relation for {relation_name}", BlockedStatus
                )

        relations = interfaces[relation_name]
        if not isinstance(relations, SerializedDataInterface):
            raise CheckFailedError(
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
            self.log.error(val_error)
            raise CheckFailedError(
                f"Found incomplete/incorrect relation data for {relation_name}.  See logs",
                BlockedStatus,
            )

        # Check if we have an established relation with no data exchanged
        if len(unpacked_relation_data) == 0:
            raise CheckFailedError(f"Waiting for {relation_name} relation data", WaitingStatus)

        # Unpack data (we care only about the first element)
        data_dict = list(unpacked_relation_data.values())[0]

        # Catch if empty data dict is received (JSONSchema ValidationError above does not raise
        # when this happens)
        # Remove once addressed in:
        # https://github.com/canonical/serialized-data-interface/issues/28
        if len(data_dict) == 0:
            raise CheckFailedError(
                f"Found incomplete/incorrect relation data for {relation_name}.",
                BlockedStatus,
            )

        return data_dict


class CheckFailedError(Exception):
    """Raise this exception if one of the checks in main fails."""

    def __init__(self, msg, status_type=None):
        super().__init__()

        self.msg = msg
        self.status_type = status_type
        self.status = status_type(msg)


if __name__ == "__main__":
    main(KfpApiOperator)
