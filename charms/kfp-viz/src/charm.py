#!/usr/bin/env python3

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

        self.image = OCIImageResource(self, "oci-image")
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

    def send_info(self, event):
        if self.interfaces["kfp-viz"]:
            self.interfaces["kfp-viz"].send_data(
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

        port = self.model.config["http-port"]
        self.model.unit.status = MaintenanceStatus("Setting pod spec")
        self.model.pod.set_spec(
            {
                "version": 3,
                "containers": [
                    {
                        "name": "ml-pipeline-visualizationserver",
                        "imageDetails": image_details,
                        "ports": [
                            {
                                "name": "http",
                                "containerPort": int(port),
                            },
                        ],
                        "kubernetes": {
                            "readinessProbe": {
                                "exec": {
                                    "command": [
                                        "wget",
                                        "-q",
                                        "-S",
                                        "-O",
                                        "-",
                                        f"http://localhost:{port}/",
                                    ]
                                },
                                "initialDelaySeconds": 3,
                                "periodSeconds": 5,
                                "timeoutSeconds": 2,
                            },
                            "livenessProbe": {
                                "exec": {
                                    "command": [
                                        "wget",
                                        "-q",
                                        "-S",
                                        "-O",
                                        "-",
                                        f"http://localhost:{port}/",
                                    ]
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
