#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Charm for the Kubeflow Pipelines Metadata Writer.

https://github.com/canonical/kfp-operators
"""

import logging

import lightkube
from charmed_kubeflow_chisme.components.charm_reconciler import CharmReconciler
from charmed_kubeflow_chisme.components.kubernetes_component import KubernetesComponent
from charmed_kubeflow_chisme.components.leadership_gate_component import LeadershipGateComponent
from charmed_kubeflow_chisme.kubernetes import create_charm_default_labels
from lightkube.resources.core_v1 import ServiceAccount
from lightkube.resources.rbac_authorization_v1 import ClusterRole, ClusterRoleBinding
from ops.charm import CharmBase
from ops.main import main

from components.k8s_service_info_component import K8sServiceInfoComponent
from components.pebble_component import KfpMetadataWriterInputs, KfpMetadataWriterPebbleService

logger = logging.getLogger(__name__)

GRPC_RELATION_NAME = "grpc"
K8S_RESOURCE_FILES = ["src/templates/auth_manifests.yaml.j2"]


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
            component=K8sServiceInfoComponent(
                charm=self,
                relation_name=GRPC_RELATION_NAME,
                refresh_event=self.on[GRPC_RELATION_NAME].relation_changed,
            ),
            depends_on=[self.leadership_gate],
        )

        self.kubernetes_resources = self.charm_reconciler.add(
            component=KubernetesComponent(
                charm=self,
                name="kubernetes:auth",
                resource_templates=K8S_RESOURCE_FILES,
                krh_resource_types={ClusterRole, ClusterRoleBinding, ServiceAccount},
                krh_labels=create_charm_default_labels(
                    self.app.name, self.model.name, scope="auth"
                ),
                context_callable=lambda: {"app_name": self.app.name, "namespace": self._namespace},
                lightkube_client=lightkube.Client(),
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
            depends_on=[self.kubernetes_resources, self.grpc_relation],
        )

        self.charm_reconciler.install_default_event_handlers()


if __name__ == "__main__":
    main(KfpMetadataWriter)
