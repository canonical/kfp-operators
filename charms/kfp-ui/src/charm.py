#!/usr/bin/env python3

import json
import logging

from oci_image import OCIImageResource, OCIImageResourceError
from ops.charm import CharmBase
from ops.main import main
from ops.model import ActiveStatus, BlockedStatus, MaintenanceStatus, WaitingStatus
from serialized_data_interface import (
    NoCompatibleVersions,
    NoVersionsListed,
    get_interfaces,
)

log = logging.getLogger()


class Operator(CharmBase):
    def __init__(self, *args):
        super().__init__(*args)

        if not self.model.unit.is_leader():
            log.info("Not a leader, skipping set_pod_spec")
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
        else:
            self.model.unit.status = ActiveStatus()

        self.framework.observe(self.on.install, self.set_pod_spec)
        self.framework.observe(self.on.upgrade_charm, self.set_pod_spec)
        self.framework.observe(self.on.config_changed, self.set_pod_spec)

        for relation in self.interfaces.keys():
            self.framework.observe(
                self.on[relation].relation_changed,
                self.set_pod_spec,
            )
            self.framework.observe(
                self.on[relation].relation_changed,
                self.send_info,
            )
            self.framework.observe(
                self.on[relation].relation_changed,
                self.configure_ingress,
            )

    def configure_ingress(self, event):
        if self.interfaces["ingress"]:
            self.interfaces["ingress"].send_data(
                {
                    "prefix": "/pipeline",
                    "rewrite": "/pipeline",
                    "service": self.model.app.name,
                    "port": int(self.model.config["http-port"]),
                }
            )

    def send_info(self, event):
        if self.interfaces["kfp-ui"]:
            self.interfaces["kfp-ui"].send_data(
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
            log.info(e)
            return

        config = self.model.config

        if not ((os := self.interfaces["object-storage"]) and os.get_data()):
            self.model.unit.status = WaitingStatus(
                "Waiting for object-storage relation data"
            )
            return
        os = list(os.get_data().values())[0]

        if not ((api := self.interfaces["kfp-api"]) and api.get_data()):
            self.model.unit.status = WaitingStatus("Waiting for api relation data")
            return
        api = list(api.get_data().values())[0]

        healthz = f"http://localhost:{config['http-port']}/apis/v1beta1/healthz"

        env = {
            "ALLOW_CUSTOM_VISUALIZATIONS": str(
                config["allow-custom-visualizations"]
            ).lower(),
            "ARGO_ARCHIVE_ARTIFACTORY": "minio",
            "ARGO_ARCHIVE_BUCKETNAME": "mlpipeline",
            "ARGO_ARCHIVE_LOGS": "false",
            "ARGO_ARCHIVE_PREFIX": "logs",
            "AWS_ACCESS_KEY_ID": "",
            "AWS_SECRET_ACCESS_KEY": "",
            "DISABLE_GKE_METADATA": "false",
            "ENABLE_AUTHZ": "false",
            "DEPLOYMENT": "KUBEFLOW",
            "HIDE_SIDENAV": str(config["hide-sidenav"]).lower(),
            "HTTP_AUTHORIZATION_DEFAULT_VALUE": "",
            "HTTP_AUTHORIZATION_KEY": "",
            "HTTP_BASE_URL": "",
            "METADATA_ENVOY_SERVICE_SERVICE_HOST": "localhost",
            "METADATA_ENVOY_SERVICE_SERVICE_PORT": "9090",
            "MINIO_ACCESS_KEY": os["access-key"],
            "MINIO_HOST": os["service"],
            "MINIO_NAMESPACE": os["namespace"],
            "MINIO_PORT": os["port"],
            "MINIO_SECRET_KEY": os["secret-key"],
            "MINIO_SSL": os["secure"],
            "ML_PIPELINE_SERVICE_HOST": api["service-name"],
            "ML_PIPELINE_SERVICE_PORT": api["service-port"],
            "STREAM_LOGS_FROM_SERVER_API": "false",
            "VIEWER_TENSORBOARD_POD_TEMPLATE_SPEC_PATH": "/etc/config/viewer-pod-template.json",
            "VIEWER_TENSORBOARD_TF_IMAGE_NAME": "tensorflow/tensorflow",
        }

        config_json = json.dumps(
            {"spec": {"serviceAccountName": "kubeflow-pipelines-viewer"}}
        )

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
                        "envConfig": env,
                        "volumeConfig": [
                            {
                                "name": "config",
                                "mountPath": "/config",
                                "files": [
                                    {
                                        "path": "config.json",
                                        "content": config_json,
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
