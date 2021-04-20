#!/usr/bin/env python3

import logging

from ops.charm import CharmBase
from ops.main import main
from ops.model import ActiveStatus, MaintenanceStatus

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
        self.framework.observe(self.on.install, self.set_pod_spec)
        self.framework.observe(self.on.upgrade_charm, self.set_pod_spec)
        self.framework.observe(self.on.config_changed, self.set_pod_spec)

    def set_pod_spec(self, event):
        try:
            image_details = self.image.fetch()
        except OCIImageResourceError as e:
            self.model.unit.status = e.status
            log.info(e)
            return

        self.model.unit.status = MaintenanceStatus("Setting pod spec")
        self.model.pod.set_spec(
            {
                "version": 3,
                "serviceAccount": {
                    "roles": [
                        {
                            "rules": [
                                {
                                    "apiGroups": ["argoproj.io"],
                                    "resources": ["workflows"],
                                    "verbs": ["get", "list", "watch"],
                                },
                                {
                                    "apiGroups": ["kubeflow.org"],
                                    "resources": ["scheduledworkflows"],
                                    "verbs": ["get", "list", "watch"],
                                },
                            ],
                        }
                    ]
                },
                "containers": [
                    {
                        "name": "ml-pipeline-persistenceagent",
                        "imageDetails": image_details,
                        "envConfig": {
                            "NAMESPACE": self.model.name,
                            "TTL_SECONDS_AFTER_WORKFLOW_FINISH": 86400,
                            "NUM_WORKERS": 2,
                        },
                    }
                ],
            },
        )
        self.model.unit.status = ActiveStatus()


if __name__ == "__main__":
    main(Operator)
