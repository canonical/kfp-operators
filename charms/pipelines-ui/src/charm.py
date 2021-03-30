#!/usr/bin/env python3

import json
import logging

from ops.charm import CharmBase
from ops.main import main
from ops.model import ActiveStatus, MaintenanceStatus, Unit

from oci_image import OCIImageResource, OCIImageResourceError

log = logging.getLogger()


class Operator(CharmBase):
    def __init__(self, *args):
        super().__init__(*args)

        if not self.model.unit.is_leader():
            log.info("Not a leader, skipping set_pod_spec")
            self.model.unit.status = ActiveStatus()
            return

        self.image = OCIImageResource(self, "oci-image")

        relations = [
            self.on.install,
            self.on.upgrade_charm,
            self.on.config_changed,
            self.on["minio"].relation_changed,
            self.on["pipelines-api"].relation_changed,
        ]

        for relation in relations:
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
            log.info(e)
            return

        config = self.model.config

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

        try:
            data = next(
                value
                for relation in self.model.relations["pipelines-api"]
                for key, value in relation.data.items()
                if isinstance(key, Unit)
                and not key._is_our_unit
                and value.get("service")
            )
            api = {
                "service": data["service"],
                "port": data["port"],
            }
        except StopIteration:
            self.model.unit.status = MaintenanceStatus("Waiting for api relation data")
            return

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
                                    "verbs": ["get"],
                                },
                                {
                                    "apiGroups": [""],
                                    "resources": ["events"],
                                    "verbs": ["list"],
                                },
                                {
                                    "apiGroups": [""],
                                    "resources": ["secrets"],
                                    "verbs": ["get", "list"],
                                },
                                {
                                    "apiGroups": ["kubeflow.org"],
                                    "resources": ["viewers"],
                                    "verbs": [
                                        "create",
                                        "get",
                                        "list",
                                        "watch",
                                        "delete",
                                    ],
                                },
                                {
                                    "apiGroups": ["argoproj.io"],
                                    "resources": ["workflows"],
                                    "verbs": ["get", "list"],
                                },
                            ],
                        }
                    ]
                },
                "containers": [
                    {
                        "name": "ml-pipeline-ui",
                        "imageDetails": image_details,
                        "ports": [
                            {
                                "name": "http",
                                "containerPort": int(config["http-port"]),
                            },
                        ],
                        "envConfig": {
                            "ALLOW_CUSTOM_VISUALIZATIONS": str(
                                config["allow-custom-visualizations"]
                            ).lower(),
                            "ARGO_ARCHIVE_ARTIFACTORY": "minio",
                            "ARGO_ARCHIVE_BUCKETNAME": "mlpipeline",
                            "ARGO_ARCHIVE_LOGS": "false",
                            "ARGO_ARCHIVE_PREFIX": "logs",
                            "AWS_ACCESS_KEY_ID": "",
                            "AWS_SECRET_ACCESS_KEY": "",
                            "DEPLOYMENT": "KUBEFLOW",
                            "DISABLE_GKE_METADATA": "false",
                            "ENABLE_AUTHZ": "false",
                            "HIDE_SIDENAV": "",
                            "HTTP_AUTHORIZATION_DEFAULT_VALUE": "",
                            "HTTP_AUTHORIZATION_KEY": "",
                            "HTTP_BASE_URL": "",
                            "KUBEFLOW_USERID_HEADER": "kubeflow-userid",
                            "KUBEFLOW_USERID_PREFIX": "",
                            "METADATA_ENVOY_SERVICE_SERVICE_HOST": "localhost",
                            "METADATA_ENVOY_SERVICE_SERVICE_PORT": "9090",
                            "MINIO_ACCESS_KEY": minio["user"],
                            "MINIO_HOST": minio["ip"],
                            "MINIO_NAMESPACE": self.model.name,
                            "MINIO_PORT": minio["port"],
                            "MINIO_SECRET_KEY": minio["password"],
                            "MINIO_SSL": "false",
                            "ML_PIPELINE_SERVICE_HOST": api["service"],
                            "ML_PIPELINE_SERVICE_PORT": api["port"],
                            "STREAM_LOGS_FROM_SERVER_API": "false",
                            "VIEWER_TENSORBOARD_POD_TEMPLATE_SPEC_PATH": "/etc/config/viewer-pod-template.json",
                            "VIEWER_TENSORBOARD_TF_IMAGE_NAME": "tensorflow/tensorflow",
                        },
                        "volumeConfig": [
                            {
                                "name": "config",
                                "mountPath": "/config",
                                "files": [
                                    {
                                        "path": "config.json",
                                        "content": json.dumps(
                                            {
                                                "spec": {
                                                    "serviceAccountName": "kubeflow-pipelines-viewer"
                                                }
                                            }
                                        ),
                                    },
                                ],
                            },
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
        )
        self.model.unit.status = ActiveStatus()


if __name__ == "__main__":
    main(Operator)
