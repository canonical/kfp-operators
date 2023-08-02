#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Charm for the Kubeflow Pipelines Viewer CRD controller.

https://github.com/canonical/kfp-operators
"""

import logging

import lightkube
from charmed_kubeflow_chisme.components.charm_reconciler import CharmReconciler
from charmed_kubeflow_chisme.components.kubernetes_component import KubernetesComponent
from charmed_kubeflow_chisme.components.leadership_gate_component import LeadershipGateComponent
from charmed_kubeflow_chisme.kubernetes import create_charm_default_labels
from lightkube.resources.apiextensions_v1 import CustomResourceDefinition
from lightkube.resources.core_v1 import ServiceAccount
from lightkube.resources.rbac_authorization_v1 import Role, RoleBinding
from ops.charm import CharmBase
from ops.main import main

from components.model_name_gate_component import ModelNameGate
from components.pebble_component import PebbleServiceContainerComponent

logger = logging.getLogger(__name__)

K8S_RESOURCE_FILES = ["src/templates/auth_manifests.yaml.j2", "src/templates/crds.yaml.j2"]


class KfpViewer(CharmBase):
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

        self.model_name_gate = self.charm_reconciler.add(
            component=ModelNameGate(
                charm=self,
                name="model-name-gate",
            ),
            depends_on=[self.leadership_gate],
        )

        self.kubernetes_resources = self.charm_reconciler.add(
            component=KubernetesComponent(
                charm=self,
                name="kubernetes:auth-and-crds",
                resource_templates=K8S_RESOURCE_FILES,
                krh_resource_types={CustomResourceDefinition, Role, RoleBinding, ServiceAccount},
                krh_labels=create_charm_default_labels(
                    self.app.name, self.model.name, scope="auth-and-crds"
                ),
                context_callable=lambda: {"app_name": self.app.name, "namespace": self._namespace},
                lightkube_client=lightkube.Client(),
            ),
            depends_on=[self.leadership_gate],
        )

        self.pebble_service_container = self.charm_reconciler.add(
            component=PebbleServiceContainerComponent(
                charm=self,
                name="pebble-service-container",
                container_name="kfp-viewer",
                service_name="controller",
                environment={
                    "MAX_NUM_VIEWERS": self.model.config["max-num-viewers"],
                    "MINIO_NAMESPACE": self._namespace,
                },
            ),
            depends_on=[self.kubernetes_resources],
        )

        self.charm_reconciler.install_default_event_handlers()


if __name__ == "__main__":
    main(KfpViewer)
