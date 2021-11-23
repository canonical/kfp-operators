#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

import json
import logging
from pathlib import Path

from oci_image import OCIImageResource, OCIImageResourceError
from ops.charm import CharmBase
from ops.main import main
from ops.model import ActiveStatus, BlockedStatus, MaintenanceStatus, WaitingStatus
from serialized_data_interface import (
    NoCompatibleVersions,
    NoVersionsListed,
    get_interfaces,
)


class Operator(CharmBase):
    def __init__(self, *args):
        super().__init__(*args)

        self.log = logging.getLogger()

        self.image = OCIImageResource(self, "oci-image")

        change_events = [
            self.on.install,
            self.on.upgrade_charm,
            self.on.config_changed,
            self.on["mysql"].relation_changed,
        ]

        for event in change_events:
            self.framework.observe(event, self.set_pod_spec)

        # TODO: Think this through.  Are these relations we react to, provide data to, or both?
        #  Handle them appropriately based on that
        for relation in self.interfaces.keys():
            self.framework.observe(
                self.on[relation].relation_changed,
                self.set_pod_spec,
            )
            self.framework.observe(
                self.on[relation].relation_changed,
                self.send_info,
            )

    def send_info(self, event):
        if self.interfaces["kfp-api"]:
            self.interfaces["kfp-api"].send_data(
                {
                    "service-name": f"{self.model.app.name}.{self.model.name}",
                    "service-port": self.model.config["http-port"],
                }
            )

    def set_pod_spec(self, event):
        try:
            self._check_leader()
            interfaces = self._get_interfaces()
            image_details = self.image.fetch()
            mysql = self._get_mysql()
            os = self._get_object_storage(interfaces)
            viz = self._get_viz(interfaces)
        except (CheckFailed, OCIImageResourceError) as check_failed:
            self.model.unit.status = check_failed.status
            self.log.info(str(check_failed.status))
            return

        config, config_json = self.generate_config(mysql, os, viz)

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
                                        "content": Path(
                                            "src/sample_config.json"
                                        ).read_text(),
                                    },
                                ],
                            }
                        ],
                        "kubernetes": {
                            "readinessProbe": {
                                "exec": {
                                    "command": ["wget", "-q", "-S", "-O", "-", healthz]
                                },
                                "initialDelaySeconds": 3,
                                "periodSeconds": 5,
                                "timeoutSeconds": 2,
                            },
                            "livenessProbe": {
                                "exec": {
                                    "command": ["wget", "-q", "-S", "-O", "-", healthz]
                                },
                                "initialDelaySeconds": 3,
                                "periodSeconds": 5,
                                "timeoutSeconds": 2,
                            },
                        },
                    }
                ],
            },
            k8s_resources={
                "kubernetesResources": {
                    "services": [
                        {
                            "name": "ml-pipeline",
                            "spec": {
                                "selector": {
                                    "app.kubernetes.io/name": self.model.app.name
                                },
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
                        }
                    ],
                }
            },
        )
        self.model.unit.status = ActiveStatus()

    def generate_config(self, mysql, os, viz):
        config = self.model.config
        config_json = {
            "DBConfig": {
                "ConMaxLifeTimeSec": "120",
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
            "AUTO_UPDATE_PIPELINE_DEFAULT_VERSION": config[
                "auto-update-default-version"
            ],
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
            raise CheckFailed("Waiting for leadership", WaitingStatus)

    def _get_interfaces(self):
        # Remove this abstraction when SDI adds .status attribute to NoVersionsListed,
        # NoCompatibleVersionsListed:
        # https://github.com/canonical/serialized-data-interface/issues/26
        try:
            interfaces = get_interfaces(self)
        except NoVersionsListed as err:
            raise CheckFailed(err, WaitingStatus)
        except NoCompatibleVersions as err:
            raise CheckFailed(err, BlockedStatus)
        return interfaces

    def _get_mysql(self):
        mysql = self.model.relations["mysql"]
        if len(mysql) > 1:
            raise CheckFailed("Too many mysql relations", BlockedStatus)

        try:
            mysql = mysql[0]
            unit = list(mysql.units)[0]
            mysql = mysql.data[unit]
            _ = mysql["database"]
        except (IndexError, KeyError):
            raise CheckFailed("Waiting for mysql relation data", MaintenanceStatus)

        return mysql

    def _get_object_storage(self, interfaces):
        try:
            os = interfaces["object-storage"]
            os.get_data()
            os = list(os.get_data().values())[0]
            return os
        except Exception as e:
            raise CheckFailed("Waiting for object-storage relation data", WaitingStatus)

    def _get_viz(self, interfaces):
        try:
            viz = interfaces["kfp-viz"]
            viz.get_data()
        except:
            viz = {"service-name": "unset", "service-port": "1234"}
        return viz


class CheckFailed(Exception):
    """ Raise this exception if one of the checks in main fails. """

    def __init__(self, msg, status_type=None):
        super().__init__()

        self.msg = msg
        self.status_type = status_type
        self.status = status_type(msg)


if __name__ == "__main__":
    main(Operator)
