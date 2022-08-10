#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

"""Charm for the Kubeflow Pipelines Visualization Server.

https://github.com/canonical/kfp-operators
"""

import logging

from oci_image import OCIImageResource, OCIImageResourceError
from ops.charm import CharmBase
from ops.main import main
from ops.model import ActiveStatus, BlockedStatus, MaintenanceStatus, WaitingStatus
from serialized_data_interface import NoCompatibleVersions, NoVersionsListed, get_interfaces

log = logging.getLogger()


class KfpVizOperator(CharmBase):
    """Charm for the Kubeflow Pipelines Visualization Server.

    https://github.com/canonical/kfp-operators
    """

    def __init__(self, *args):
        super().__init__(*args)

        self.log = logging.getLogger()
        self.image = OCIImageResource(self, "oci-image")

        self.framework.observe(self.on.install, self._main)
        self.framework.observe(self.on.upgrade_charm, self._main)
        self.framework.observe(self.on.config_changed, self._main)
        self.framework.observe(self.on.leader_elected, self._main)
        self.framework.observe(self.on["kfp-viz"].relation_changed, self._main)

    def _send_viz_info(self, interfaces):
        if interfaces["kfp-viz"]:
            interfaces["kfp-viz"].send_data(
                {
                    "service-name": f"{self.model.app.name}.{self.model.name}",
                    "service-port": self.model.config["http-port"],
                }
            )

    def _main(self, event):
        # Set up all relations/fetch required data
        try:
            self._check_leader()
            interfaces = self._get_interfaces()
            image_details = self.image.fetch()
        except (CheckFailedError, OCIImageResourceError) as check_failed:
            self.model.unit.status = check_failed.status
            self.log.info(str(check_failed.status))
            return

        self._send_viz_info(interfaces)

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


class CheckFailedError(Exception):
    """Raise this exception if one of the checks in main fails."""

    def __init__(self, msg, status_type=None):
        super().__init__()

        self.msg = msg
        self.status_type = status_type
        self.status = status_type(msg)


if __name__ == "__main__":
    main(KfpVizOperator)
