#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Charm for the Kubeflow Scheduled Workflow CRD controller.

https://github.com/canonical/kfp-operators
"""

import logging

from charmed_kubeflow_chisme.components.charm_reconciler import CharmReconciler
from charmed_kubeflow_chisme.components.leadership_gate_component import LeadershipGateComponent
from charmed_kubeflow_chisme.kubernetes import create_charm_default_labels
from charms.loki_k8s.v1.loki_push_api import LogForwarder
from ops import main
from ops.charm import CharmBase

from components.pebble_component import KfpSchedwfPebbleService

logger = logging.getLogger(__name__)

K8S_RESOURCE_FILES = ["src/templates/auth_manifests.yaml.j2", "src/templates/crds.yaml"]


class KfpSchedwf(CharmBase):
    def __init__(self, *args):
        """Charm for the Kubeflow Pipelines Viewer CRD controller."""
        super().__init__(*args)

        self.charm_reconciler = CharmReconciler(self)
        self._namespace = self.model.name

        self.leadership_gate = self.charm_reconciler.add(
            component=LeadershipGateComponent(
                charm=self,
                name="leadership-gate",
            ),
            depends_on=[],
        )

        # The service_name should be consistent with the rock predefined
        # service name to be able to reuse it, do not change it unless
        # it changes in the corresponding Rockcraft project.
        self.pebble_service_container = self.charm_reconciler.add(
            component=KfpSchedwfPebbleService(
                charm=self,
                name="kfp-schedwf-pebble-service",
                container_name="ml-pipeline-scheduledworkflow",
                service_name="controller",
                timezone=self.model.config["timezone"],
                log_level=self.model.config["log-level"],
            ),
            depends_on=[],
        )

        self.charm_reconciler.install_default_event_handlers()
        self._logging = LogForwarder(charm=self)


if __name__ == "__main__":
    main(KfpSchedwf)
