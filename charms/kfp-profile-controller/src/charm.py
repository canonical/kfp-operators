#!/usr/bin/env python3

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
        else:
            self.model.unit.status = ActiveStatus()

        change_events = [
            self.on.install,
            self.on.upgrade_charm,
            self.on.config_changed,
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

    # def send_info(self, event):
    #     if self.interfaces["kfp-api"]:
    #         self.interfaces["kfp-api"].send_data(
    #             {
    #                 "service-name": self.model.app.name,
    #                 "service-port": self.model.config["http-port"],
    #             }
    #         )

    def set_pod_spec(self, event):
        try:
            image_details = self.image.fetch()
        except OCIImageResourceError as e:
            self.model.unit.status = e.status
            self.log.info(e)
            return

        config = self.model.config

        if not ((os := self.interfaces["object-storage"]) and os.get_data()):
            self.model.unit.status = WaitingStatus(
                "Waiting for object-storage relation data"
            )
            return
        os = list(os.get_data().values())[0]

        deployment_env = {
            "MINIO_ACCESS_KEY": os["access-key"],
            "MINIO_SECRET_KEY": os["secret-key"],
            # "KFP_VERSION": ___,  # optional
            "KFP_DEFAULT_PIPELINE_ROOT": "",
            "DISABLE_ISTIO_SIDECAR": "false",
        }

        self.model.unit.status = MaintenanceStatus("Setting pod spec")
        self.model.pod.set_spec(
            {
                "version": 3,
                "containers": [
                    {
                        # TODO: annotations: sidecar.istio.io/inject: "false"
                        # TODO: labels?
                        "name": "kubeflow-pipelines-profile-controller",
                        "command": "python",
                        "args": ["/hooks/s.py"],
                        "imageDetails": image_details,
                        "ports": [
                            {
                                "name": "http",
                                # TODO: Upstream maps kubeflow maps 80->8080.  This this is fine?
                                "containerPort": int(config["http-port"]),
                                "protocol": "TCP"
                            },
                        ],
                        "envConfig": deployment_env,
                        "volumeConfig": [
                            {
                                "name": "kubeflow-pipelines-profile-controller-code",
                                "mountPath": "/hooks",
                                "files": [
                                    {
                                        "key": "sync.py",
                                        "path": "sync.py",
                                    }
                                ],
                            }
                        ],
                    }
                ],
            },
            k8s_resources={
                "kubernetesResources": {
                    "customResources": {
                        "ompositecontrollers.metacontroller.k8s.io": {
                            "apiVersion": "metacontroller.k8s.io/v1alpha1",
                            "kind": "CompositeController",
                            "metadata": {
                                "name": "kubeflow-pipelines-profile-controller",
                                # "labels": {}, # TODO: Include labels?  think they might be defined at metadata indentation
                            },
                            "spec": {
                                "childResources": [
                                    {
                                        "apiVersion": "v1",
                                        "resource": "secrets",
                                        "updateStrategy": {
                                            "method": "OnDelete"
                                        },
                                    },
                                    {
                                        "apiVersion": "v1",
                                        "resource": "configmaps",
                                        "updateStrategy": {
                                            "method": "OnDelete"
                                        }
                                    },
                                    {
                                        "apiVersion": "apps/v1",
                                        "resource": "deployments",
                                        "updateStrategy": {
                                            "method": "InPlace"
                                        }
                                    },
                                    {
                                        "apiVersion": "v1",
                                        "resource": "services",
                                        "updateStrategy": {
                                            "method": "InPlace"
                                        }
                                    },
                                    {
                                        "apiVersion": "networking.istio.io/v1alpha3",
                                        "resource": "destinationrules",
                                        "updateStrategy": {
                                            "method": "InPlace"
                                        }
                                    },
                                    {
                                        "apiVersion": "security.istio.io/v1beta1",
                                        "resource": "authorizationpolicies",
                                        "updateStrategy": {
                                            "method": "InPlace"
                                        }
                                    },
                                ],
                                "generateSelector": "true",
                                "hooks": {
                                    "sync": {
                                        "webhook": {
                                            "url": "http://kubeflow-pipelines-profile-controller/sync"  # This needs to match the service juju makes for us
                                        }
                                    }
                                },
                                "parentResource": {
                                    "apiVersion": "v1",
                                    "resource": "namespaces",
                                },
                                "resyncPeriodSeconds": 10,
                            }
                        }
                    },
                    "configMaps": {
                        "kubeflow-pipelines-profile-controller-code": {
                            "sync.py": Path("files/upstream/sync.py"),
                        },
                    },

                }
            },
        )
        self.model.unit.status = ActiveStatus()


if __name__ == "__main__":
    main(Operator)
