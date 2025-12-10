#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Charm for the Kubeflow Scheduled Workflow CRD controller.

https://github.com/canonical/kfp-operators
"""

import logging
from pathlib import Path

import lightkube
from charmed_kubeflow_chisme.components.charm_reconciler import CharmReconciler
from charmed_kubeflow_chisme.components.kubernetes_component import KubernetesComponent
from charmed_kubeflow_chisme.components.leadership_gate_component import LeadershipGateComponent
from charmed_kubeflow_chisme.components.pebble_component import ContainerFileTemplate
from charmed_kubeflow_chisme.components.sa_token_component import SATokenComponent
from charmed_kubeflow_chisme.kubernetes import create_charm_default_labels
from charms.loki_k8s.v1.loki_push_api import LogForwarder
from lightkube.resources.apiextensions_v1 import CustomResourceDefinition
from ops import main
from ops.charm import CharmBase

from components.pebble_component import KfpSchedwfPebbleService

logger = logging.getLogger(__name__)

K8S_RESOURCE_FILES = ["src/templates/crds.yaml"]
SA_NAME = "kfp-schedwf"
SA_TOKEN_PATH = "src/"
SA_TOKEN_FILENAME = "scheduledworkflow-sa-token"
SA_TOKEN_FULL_PATH = str(Path(SA_TOKEN_PATH, SA_TOKEN_FILENAME))
SA_TOKEN_DESTINATION_PATH = f"/var/run/secrets/kubeflow/tokens/{SA_TOKEN_FILENAME}"


class KfpSchedwf(CharmBase):
    def __init__(self, *args):
        """Charm for the Kubeflow Pipelines Viewer CRD controller."""
        super().__init__(*args)

        self.charm_reconciler = CharmReconciler(self)

        self.leadership_gate = self.charm_reconciler.add(
            component=LeadershipGateComponent(
                charm=self,
                name="leadership-gate",
            ),
            depends_on=[],
        )

        self.kubernetes_resources = self.charm_reconciler.add(
            component=KubernetesComponent(
                charm=self,
                name="kubernetes:crds",
                resource_templates=K8S_RESOURCE_FILES,
                krh_resource_types={CustomResourceDefinition},
                krh_labels=create_charm_default_labels(
                    self.app.name, self.model.name, scope="crds"
                ),
                context_callable=lambda: {
                    "app_name": self.app.name,
                    "namespace": self.model.name,
                    "sa_name": SA_NAME,
                },
                lightkube_client=lightkube.Client(),
            ),
            depends_on=[self.leadership_gate],
        )

        # creating a serviceAccountToken injected via a mounted projected volume:
        self.sa_token = self.charm_reconciler.add(
            component=SATokenComponent(
                charm=self,
                name="sa-token:scheduledworkflow",
                audiences=["pipelines.kubeflow.org"],
                sa_name=SA_NAME,
                sa_namespace=self.model.name,
                filename=SA_TOKEN_FILENAME,
                path=SA_TOKEN_PATH,
                expiration=4294967296,
            ),
            depends_on=[self.leadership_gate, self.kubernetes_resources],
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
                files_to_push=[
                    ContainerFileTemplate(
                        source_template_path=SA_TOKEN_FULL_PATH,
                        destination_path=SA_TOKEN_DESTINATION_PATH,
                    )
                ],
                timezone=self.model.config["timezone"],
                log_level=self.model.config["log-level"],
            ),
            depends_on=[
                self.kubernetes_resources,
                self.sa_token,
            ],
        )

        self.charm_reconciler.install_default_event_handlers()
        self._logging = LogForwarder(charm=self)


if __name__ == "__main__":
    main(KfpSchedwf)
