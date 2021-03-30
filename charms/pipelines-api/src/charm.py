#!/usr/bin/env python3

import json
import logging
from pathlib import Path

from ops.charm import CharmBase
from ops.main import main
from ops.model import ActiveStatus, MaintenanceStatus, Unit

from oci_image import OCIImageResource, OCIImageResourceError


class Operator(CharmBase):
    def __init__(self, *args):
        super().__init__(*args)

        self.log = logging.getLogger()

        if not self.model.unit.is_leader():
            self.log.info("Not a leader, skipping set_pod_spec")
            self.model.unit.status = ActiveStatus()
            return

        self.image = OCIImageResource(self, "oci-image")

        requires = [
            self.on.install,
            self.on.upgrade_charm,
            self.on.config_changed,
            self.on["mysql"].relation_changed,
            self.on["minio"].relation_changed,
            self.on["pipelines-visualization"].relation_changed,
        ]

        for relation in requires:
            self.framework.observe(relation, self.set_pod_spec)

        provides = [
            self.on["pipelines-api"].relation_joined,
            self.on["pipelines-api"].relation_changed,
        ]
        for relation in provides:
            self.framework.observe(relation, self.send_info)

    def send_info(self, event):
        event.relation.data[self.unit]["service"] = self.model.app.name
        event.relation.data[self.unit]["port"] = self.model.config["http-port"]

    def set_pod_spec(self, event):
        try:
            image_details = self.image.fetch()
        except OCIImageResourceError as e:
            self.model.unit.status = e.status
            self.log.info(e)
            return

        config = self.model.config

        try:
            data = next(
                value
                for relation in self.model.relations["pipelines-visualization"]
                for key, value in relation.data.items()
                if isinstance(key, Unit) and not key._is_our_unit
            )
            viz = {"service": data["service"], "port": data["port"]}
        except (StopIteration, KeyError):
            viz = {"service": "unset", "port": "1234"}

        try:
            mysql = next(
                value
                for relation in self.model.relations["mysql"]
                for key, value in relation.data.items()
                if isinstance(key, Unit)
                and not key._is_our_unit
                and value.get("database")
            )
        except StopIteration:
            self.model.unit.status = MaintenanceStatus(
                "Waiting for mysql relation data"
            )
            return

        try:
            data = next(
                value
                for relation in self.model.relations["minio"]
                for key, value in relation.data.items()
                if isinstance(key, Unit) and not key._is_our_unit and value.get("ip")
            )
            minio = {
                "ip": json.loads(data["ip"]),
                "port": json.loads(data["port"]),
                "user": json.loads(data["user"]),
                "password": json.loads(data["password"]),
            }
        except StopIteration:
            self.model.unit.status = MaintenanceStatus(
                "Waiting for minio relation data"
            )
            return

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
                "AccessKey": minio["user"],
                "BucketName": "mlpipeline",
                "Host": minio["ip"],
                "Multipart": {"Disable": "true"},
                "PipelinePath": "pipelines",
                "Port": minio["port"],
                "Region": "",
                "SecretAccessKey": minio["password"],
                "Secure": "false",
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
            "ML_PIPELINE_VISUALIZATIONSERVER_SERVICE_HOST": viz["service"],
            "ML_PIPELINE_VISUALIZATIONSERVER_SERVICE_PORT": viz["port"],
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
