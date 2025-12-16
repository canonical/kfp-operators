#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Charm for the Kubeflow Pipelines Visualization Server.

https://github.com/canonical/kfp-operators
"""

import logging

from charmed_kubeflow_chisme.components import (
    CharmReconciler,
    LeadershipGateComponent,
    SdiRelationBroadcasterComponent,
)
from charms.loki_k8s.v1.loki_push_api import LogForwarder
from charms.observability_libs.v1.kubernetes_service_patch import KubernetesServicePatch
from lightkube.models.core_v1 import ServicePort
from ops import main
from ops.charm import CharmBase

from components.pebble_components import KfpVizPebbleService

logger = logging.getLogger()


class KfpVizOperator(CharmBase):
    """Charm for the Kubeflow Pipelines Visualization Server.

    https://github.com/canonical/kfp-operators
    """

    def __init__(self, *args):
        super().__init__(*args)

        http_port = ServicePort(int(self.model.config["http-port"]), name="http")
        self.service_patcher = KubernetesServicePatch(
            self, [http_port], service_name=f"{self.model.app.name}"
        )

        # Charm logic
        self.charm_reconciler = CharmReconciler(self)

        self.leadership_gate = self.charm_reconciler.add(
            component=LeadershipGateComponent(
                charm=self,
                name="leadership-gate",
            ),
            depends_on=[],
        )

        self.kfp_viz_relation = self.charm_reconciler.add(
            SdiRelationBroadcasterComponent(
                charm=self,
                name="relation:kfp-viz",
                relation_name="kfp-viz",
                data_to_send={
                    "service-name": f"{self.model.app.name}.{self.model.name}",
                    "service-port": self.model.config["http-port"],
                },
            ),
            depends_on=[self.leadership_gate],
        )

        # The service_name should be consistent with the rock predefined
        # service name to be able to reuse it, do not change it unless
        # it changes in the corresponding Rockcraft project.
        self.ml_pipeline_visualizationserver_container = self.charm_reconciler.add(
            component=KfpVizPebbleService(
                charm=self,
                name="kfp-viz-pebble-service",
                container_name="ml-pipeline-visualizationserver",
                service_name="vis-server",
            )
        )

        self.charm_reconciler.install_default_event_handlers()
        self._logging = LogForwarder(charm=self)


if __name__ == "__main__":
    main(KfpVizOperator)
