#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

"""Charm for the Kubeflow Pipelines Scheduled Workflow Controller.

https://github.com/canonical/kfp-operators/
"""

import logging
from pathlib import Path

import yaml
from oci_image import OCIImageResource, OCIImageResourceError
from ops.charm import CharmBase
from ops.main import main
from ops.model import ActiveStatus, MaintenanceStatus, WaitingStatus

log = logging.getLogger()


class KfpSchedwf(CharmBase):
    """Charm for the Kubeflow Pipelines Scheduled Workflow Controller.

    https://github.com/canonical/kfp-operators/
    """

    def __init__(self, *args):
        super().__init__(*args)

        self.log = logging.getLogger()
        self.image = OCIImageResource(self, "oci-image")

        self.framework.observe(self.on.install, self._main)
        self.framework.observe(self.on.upgrade_charm, self._main)
        self.framework.observe(self.on.config_changed, self._main)

    def _main(self, event):
        try:
            self._check_leader()
            image_details = self.image.fetch()
        except (CheckFailedError, OCIImageResourceError) as check_failed:
            self.model.unit.status = check_failed.status
            self.log.info(str(check_failed.status))
            return

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
                                    "resources": ["scheduledworkflows", "scheduledworkflows/finalizers"],
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
                                    "apiGroups": [""],
                                    "resources": ["events"],
                                    "verbs": ["create", "patch"],
                                },
                            ],
                        }
                    ]
                },
                "containers": [
                    {
                        "name": "ml-pipeline-scheduledworkflow",
                        "imageDetails": image_details,
                        "envConfig": {
                            "NAMESPACE": "",
                            "CRON_SCHEDULE_TIMEZONE": self.model.config["timezone"],
                        },
                    }
                ],
            },
            k8s_resources={
                "kubernetesResources": {
                    "customResourceDefinitions": [
                        {"name": crd["metadata"]["name"], "spec": crd["spec"]}
                        for crd in yaml.safe_load_all(Path("src/crds.yaml").read_text())
                    ],
                }
            },
        )
        self.model.unit.status = ActiveStatus()

    def _check_leader(self):
        if not self.unit.is_leader():
            # We can't do anything useful when not the leader, so do nothing.
            raise CheckFailedError("Waiting for leadership", WaitingStatus)


class CheckFailedError(Exception):
    """Raise this exception if one of the checks in main fails."""

    def __init__(self, msg, status_type=None):
        super().__init__()

        self.msg = msg
        self.status_type = status_type
        self.status = status_type(msg)


if __name__ == "__main__":
    main(KfpSchedwf)
