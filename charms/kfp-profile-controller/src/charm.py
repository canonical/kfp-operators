#!/usr/bin/env python3

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


# This must be hard-coded to port 80 because the metacontroller webhook that talks to this port only
# communicates over port 80.  Upstream uses the service to map 80->8080 but we cannot via podspec.
CONTAINER_PORT = 80


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
            # self.framework.observe(
                # self.on[relation].relation_changed,
                # self.send_info,
            # )

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

        # TODO: this didn't seem to work.  if deployed before object storage is up, still goes
        #  to active state
        if not ((os := self.interfaces["object-storage"]) and os.get_data()):
            self.model.unit.status = WaitingStatus(
                "Waiting for object-storage relation data"
            )
            return

        logging.info("Found all required relations - proceeding to setting pod spec")
        self.model.unit.status = MaintenanceStatus("Setting pod spec")
        os = list(os.get_data().values())[0]

        deployment_env = {
            "MINIO_ACCESS_KEY": os["access-key"],
            "MINIO_SECRET_KEY": os["secret-key"],
            # TODO: This sets the version of the images used in each namespace, coming from the
            #  configMap pipeline-install-config's appVersion entry.  Should this be a config option?  It'll be updated whenever we update the charm
            "KFP_VERSION": "1.7.0-rc.3",
            "KFP_DEFAULT_PIPELINE_ROOT": "",
            "DISABLE_ISTIO_SIDECAR": "false",
            "CONTAINER_PORT": CONTAINER_PORT,
        }

        self.model.pod.set_spec(
            {
                "version": 3,
                "containers": [
                    {
                        # TODO: annotations: sidecar.istio.io/inject: "false"
                        # TODO: labels?
                        "name": "kubeflow-pipelines-profile-controller",
                        "command": ["python"],
                        "args": ["/hooks/sync.py"],
                        "imageDetails": image_details,
                        "ports": [
                            {
                                "name": "http",
                                "containerPort": CONTAINER_PORT,
                                "protocol": "TCP",
                            },
                        ],
                        "envConfig": deployment_env,
                        "volumeConfig": [
                            {
                                "name": "kubeflow-pipelines-profile-controller-code",
                                "mountPath": "/hooks",
                                "configMap": {
                                    "name": "kubeflow-pipelines-profile-controller-code",
                                    "files": [
                                        {
                                            "key": "sync.py",
                                            "path": "sync.py",
                                        },
                                    ],
                                },
                            },
                        ],
                    },
                ],
            },
            k8s_resources={
                "kubernetesResources": {
                    "customResources": {
                        "compositecontrollers.metacontroller.k8s.io": [
                            {
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
                                            "updateStrategy": {"method": "OnDelete"},
                                        },
                                        {
                                            "apiVersion": "v1",
                                            "resource": "configmaps",
                                            "updateStrategy": {"method": "OnDelete"},
                                        },
                                        {
                                            "apiVersion": "apps/v1",
                                            "resource": "deployments",
                                            "updateStrategy": {"method": "InPlace"},
                                        },
                                        {
                                            "apiVersion": "v1",
                                            "resource": "services",
                                            "updateStrategy": {"method": "InPlace"},
                                        },
                                        {
                                            "apiVersion": "networking.istio.io/v1alpha3",
                                            "resource": "destinationrules",
                                            "updateStrategy": {"method": "InPlace"},
                                        },
                                        {
                                            "apiVersion": "security.istio.io/v1beta1",
                                            "resource": "authorizationpolicies",
                                            "updateStrategy": {"method": "InPlace"},
                                        },
                                    ],
                                    "generateSelector": True,
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
                                },
                            }
                        ]
                    },
                },
                "configMaps": {
                    "kubeflow-pipelines-profile-controller-code": {
                        "sync.py": Path("files/upstream/sync.py").read_text(),
                    },
                },
            },
        )
        self.model.unit.status = ActiveStatus()


if __name__ == "__main__":
    main(Operator)
