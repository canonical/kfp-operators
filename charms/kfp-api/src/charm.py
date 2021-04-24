#!/usr/bin/env python3

import json
import logging
from pathlib import Path

from ops.charm import CharmBase
from ops.main import main
from ops.model import (
    ActiveStatus,
    BlockedStatus,
    MaintenanceStatus,
    WaitingStatus,
)

from oci_image import OCIImageResource, OCIImageResourceError
from serialized_data_interface import (
    NoCompatibleVersions,
    NoVersionsListed,
    get_interfaces,
)


class Operator(CharmBase):
    def __init__(self, *args):
        super().__init__(*args)

        self.log = logging.getLogger()

        if not self.model.unit.is_leader():
            self.log.info("Not a leader, skipping set_pod_spec")
            self.model.unit.status = ActiveStatus()
            return

        self.image = OCIImageResource(self, "oci-image")

        try:
            self.interfaces = get_interfaces(self)
        except NoVersionsListed as err:
            self.model.unit.status = WaitingStatus(str(err))
            return
        except NoCompatibleVersions as err:
            self.model.unit.status = BlockedStatus(str(err))
            return

        change_events = [
            self.on.install,
            self.on.upgrade_charm,
            self.on.config_changed,
            self.on["mysql"].relation_changed,
        ]

        for event in change_events:
            self.framework.observe(event, self.set_pod_spec)

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
                    "service-name": self.model.app.name,
                    "service-port": self.model.config["http-port"],
                }
            )

    def set_pod_spec(self, event):
        try:
            image_details = self.image.fetch()
        except OCIImageResourceError as e:
            self.model.unit.status = e.status
            self.log.info(e)
            return

        config = self.model.config

        mysql = self.model.relations["mysql"]

        if len(mysql) > 1:
            self.model.unit.status = BlockedStatus("Too many mysql relations")
            return

        try:
            mysql = mysql[0]
            unit = list(mysql.units)[0]
            mysql = mysql.data[unit]
            mysql["database"]
        except (IndexError, KeyError):
            self.model.unit.status = MaintenanceStatus(
                "Waiting for mysql relation data"
            )
            return

        if (viz := self.interfaces["kfp-viz"]) and viz.get_data():
            viz = list(viz.get_data().values())[0]
        else:
            viz = {"service-name": "unset", "service-port": "1234"}

        if not ((os := self.interfaces["object-storage"]) and os.get_data()):
            self.model.unit.status = WaitingStatus(
                "Waiting for object-storage relation data"
            )
            return

        os = list(os.get_data().values())[0]

        config_json = {
            "DBConfig": {
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
                "Host": os["service"],
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
            "CacheEnabled": str(config["cache-enabled"]).lower(),
            "DefaultPipelineRunnerServiceAccount": config["runner-sa"],
            "InitConnectionTimeout": config["init-connection-timeout"],
            "ML_PIPELINE_VISUALIZATIONSERVER_SERVICE_HOST": viz["service-name"],
            "ML_PIPELINE_VISUALIZATIONSERVER_SERVICE_PORT": viz["service-port"],
        }

        healthz = f"http://localhost:{config['http-port']}/apis/v1beta1/healthz"

        self.model.unit.status = MaintenanceStatus("Setting pod spec")
        self.model.pod.set_spec(
            {
                "version": 3,
                "serviceAccount": {
                    "roles": [
                        {
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
                                "selector": {"juju-app": self.model.app.name},
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
                    "serviceAccounts": [
                        {
                            "name": "pipeline-runner",
                            "roles": [
                                {
                                    "name": "pipeline-runner",
                                    "rules": [
                                        {
                                            "apiGroups": [""],
                                            "resources": ["secrets"],
                                            "verbs": ["get"],
                                        },
                                        {
                                            "apiGroups": [""],
                                            "resources": ["configmaps"],
                                            "verbs": ["get", "watch", "list"],
                                        },
                                        {
                                            "apiGroups": [""],
                                            "resources": [
                                                "persistentvolumes",
                                                "persistentvolumeclaims",
                                            ],
                                            "verbs": ["*"],
                                        },
                                        {
                                            "apiGroups": ["snapshot.storage.k8s.io"],
                                            "resources": ["volumesnapshots"],
                                            "verbs": ["create", "delete", "get"],
                                        },
                                        {
                                            "apiGroups": ["argoproj.io"],
                                            "resources": ["workflows"],
                                            "verbs": [
                                                "get",
                                                "list",
                                                "watch",
                                                "update",
                                                "patch",
                                            ],
                                        },
                                        {
                                            "apiGroups": [""],
                                            "resources": [
                                                "pods",
                                                "pods/exec",
                                                "pods/log",
                                                "services",
                                            ],
                                            "verbs": ["*"],
                                        },
                                        {
                                            "apiGroups": ["", "apps", "extensions"],
                                            "resources": ["deployments", "replicasets"],
                                            "verbs": ["*"],
                                        },
                                        {
                                            "apiGroups": ["kubeflow.org"],
                                            "resources": ["*"],
                                            "verbs": ["*"],
                                        },
                                        {
                                            "apiGroups": ["batch"],
                                            "resources": ["jobs"],
                                            "verbs": ["*"],
                                        },
                                        {
                                            "apiGroups": ["machinelearning.seldon.io"],
                                            "resources": ["seldondeployments"],
                                            "verbs": ["*"],
                                        },
                                    ],
                                }
                            ],
                        }
                    ],
                }
            },
        )
        self.model.unit.status = ActiveStatus()


if __name__ == "__main__":
    main(Operator)
