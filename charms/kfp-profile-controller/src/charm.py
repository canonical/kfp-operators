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
CONTROLLER_PORT = 80

# TODO: Istio destinationrule/auth manually disabled in sync.py.  Need a better solution for this.
# TODO: If we start this without a relation to the object-storage, it sits in Active status.
#  Does it ever have warning about missing relation?


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

    def set_pod_spec(self, event):
        try:
            image_details = self.image.fetch()
        except OCIImageResourceError as e:
            self.model.unit.status = e.status
            self.log.info(e)
            return

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
            "MINIO_HOST": os["service"],
            "MINIO_PORT": os["port"],
            "MINIO_NAMESPACE": os["namespace"],
            # TODO: This sets the version of the images used in each namespace, coming from the
            #  upstream configMap pipeline-install-config's appVersion entry.  Normally we'd expect
            #  to set this in metadata but is different in this charm - should we have this
            #  exposed better somewhere?
            "KFP_VERSION": "1.7.0-rc.3",
            "KFP_DEFAULT_PIPELINE_ROOT": "",
            "DISABLE_ISTIO_SIDECAR": "false",
            "CONTROLLER_PORT": CONTROLLER_PORT,
            "METADATA_GRPC_SERVICE_HOST": "mlmd.kubeflow",  # TODO: Set using relation
            "METADATA_GRPC_SERVICE_PORT": "8080",  # TODO: Set using relation to kfp-api or mlmd
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
                                "containerPort": CONTROLLER_PORT,
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
                        # Define the metacontroller that manages the deployments for each user
                        "compositecontrollers.metacontroller.k8s.io": [
                            {
                                "apiVersion": "metacontroller.k8s.io/v1alpha1",
                                "kind": "CompositeController",
                                "metadata": {
                                    "name": "kubeflow-pipelines-profile-controller",
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
                                        # TODO: This only works if istio is available.  Disabled
                                        #  for now and add back when istio checked as dependency
                                        # {
                                        #     "apiVersion": "networking.istio.io/v1alpha3",
                                        #     "resource": "destinationrules",
                                        #     "updateStrategy": {"method": "InPlace"},
                                        # },
                                        # {
                                        #     "apiVersion": "security.istio.io/v1beta1",
                                        #     "resource": "authorizationpolicies",
                                        #     "updateStrategy": {"method": "InPlace"},
                                        # },
                                    ],
                                    "generateSelector": True,
                                    "hooks": {
                                        "sync": {
                                            "webhook": {
                                                "url": f"http://"
                                                f"{self.model.app.name}.{self.model.name}/sync"
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


# TODO: Restore the readiness probes?


if __name__ == "__main__":
    main(Operator)
