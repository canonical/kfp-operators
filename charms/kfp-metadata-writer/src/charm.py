#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Charm for the Kubeflow Pipelines Metadata Writer.

https://github.com/canonical/kfp-operators
"""

import logging

from charmed_kubeflow_chisme.components.charm_reconciler import CharmReconciler
from charmed_kubeflow_chisme.components.leadership_gate_component import LeadershipGateComponent
from charms.loki_k8s.v1.loki_push_api import LogForwarder
from ops import main
from ops.charm import CharmBase

from components.k8s_service_info_requirer_component import K8sServiceInfoRequirerComponent
from components.pebble_component import KfpMetadataWriterInputs, KfpMetadataWriterPebbleService

logger = logging.getLogger(__name__)

GRPC_RELATION_NAME = "grpc"
LOGGING_RELATION_NAME = "logging"


class KfpMetadataWriter(CharmBase):
    def __init__(self, *args):
        """Charm for the Kubeflow Pipelines Metadata Writer."""
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

        self.grpc_relation = self.charm_reconciler.add(
            component=K8sServiceInfoRequirerComponent(
                charm=self,
                relation_name=GRPC_RELATION_NAME,
            ),
            depends_on=[self.leadership_gate],
        )

        self.pebble_service_container = self.charm_reconciler.add(
            component=KfpMetadataWriterPebbleService(
                charm=self,
                name="kfp-metadata-writer-pebble-service",
                container_name="kfp-metadata-writer",
                service_name="kfp-metadata-writer",
                namespace_to_watch="",
                inputs_getter=lambda: KfpMetadataWriterInputs(
                    METADATA_GRPC_SERVICE_SERVICE_HOST=self.grpc_relation.component.get_service_info().name,  # noqa
                    METADATA_GRPC_SERVICE_SERVICE_PORT=self.grpc_relation.component.get_service_info().port,  # noqa
                ),
            ),
            depends_on=[self.grpc_relation],
        )

        self.charm_reconciler.install_default_event_handlers()
        self._logging = LogForwarder(charm=self, relation_name=LOGGING_RELATION_NAME)


if __name__ == "__main__":
    main(KfpMetadataWriter)
