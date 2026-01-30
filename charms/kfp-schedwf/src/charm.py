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
from charmed_kubeflow_chisme.components.serialised_data_interface_components import (
    SdiRelationDataReceiverComponent,
)
from charmed_kubeflow_chisme.kubernetes import create_charm_default_labels
from charms.istio_beacon_k8s.v0.service_mesh import ServiceMeshConsumer
from charms.loki_k8s.v1.loki_push_api import LogForwarder
from lightkube.resources.apiextensions_v1 import CustomResourceDefinition
from ops import main
from ops.charm import CharmBase

from components.pebble_component import (
    KfpSchedwfPebbleService,
    KfpSchedwfPebbleServiceComponentInputs,
)

logger = logging.getLogger(__name__)

K8S_RESOURCE_FILES = ["src/templates/crds.yaml"]
SA_TOKEN_PATH = "src/"
SA_TOKEN_FILENAME = "scheduledworkflow-sa-token"
SA_TOKEN_FULL_PATH = str(Path(SA_TOKEN_PATH, SA_TOKEN_FILENAME))
SECRETS_PATH = Path("/var/run/secrets/kubeflow/tokens")


class KfpSchedwf(CharmBase):
    def __init__(self, *args):
        """Charm for the Kubeflow Pipelines Viewer CRD controller."""
        super().__init__(*args)

        self._container_name = next(iter(self.meta.containers))

        self.charm_reconciler = CharmReconciler(self)

        self.sa_name = self.app.name

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
                    "sa_name": self.sa_name,
                },
                lightkube_client=lightkube.Client(),
            ),
            depends_on=[self.leadership_gate],
        )

        self.mesh = ServiceMeshConsumer(self)
        self.kfp_api_relation = self.charm_reconciler.add(
            component=SdiRelationDataReceiverComponent(
                charm=self,
                name="relation:kfp-api-grpc",
                relation_name="kfp-api-grpc",
                minimum_related_applications=0,
                maximum_related_applications=1,
            ),
            depends_on=[self.leadership_gate],
        )

        # creating a serviceAccountToken injected via a mounted projected volume:
        self.sa_token = self.charm_reconciler.add(
            component=SATokenComponent(
                charm=self,
                name="sa-token:scheduledworkflow",
                audiences=["pipelines.kubeflow.org"],
                sa_name=self.sa_name,
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
                container_name=self._container_name,
                service_name="controller",
                inputs_getter=lambda: KfpSchedwfPebbleServiceComponentInputs(
                    KFP_API_SERVICE=self.kfp_api_service_name,
                    KFP_API_GRPC_PORT=self.kfp_api_service_port,
                ),
                files_to_push=[
                    ContainerFileTemplate(
                        source_template_path=SA_TOKEN_FULL_PATH,
                        destination_path=SECRETS_PATH / SA_TOKEN_FILENAME,
                    )
                ],
                timezone=self.model.config["timezone"],
                log_level=self.model.config["log-level"],
            ),
            depends_on=[
                self.kubernetes_resources,
                self.kfp_api_relation,
                self.sa_token,
            ],
        )

        self.charm_reconciler.install_default_event_handlers()
        self._logging = LogForwarder(charm=self)

    @property
    def kfp_api_service_name(self) -> str:
        """
        Return the KFP API service name.

        Will first try to load data from the (sdi) kfp-api-grpc relation, of k8s_service interface.
        If it's not established then it will use the hardcoded value "ml-pipeline".
        """
        kfp_api_data = self.kfp_api_relation.component.get_data()
        if kfp_api_data:
            return kfp_api_data[0]["service-name"]

        return "ml-pipeline"

    @property
    def kfp_api_service_port(self) -> int:
        """
        Return the KFP API service port.

        Will first try to load data from the (sdi) kfp-api-grpc relation, of k8s_service interface.
        If it's not established then it will use the hardcoded value 8887.
        """
        kfp_api_data = self.kfp_api_relation.component.get_data()
        if kfp_api_data:
            return int(kfp_api_data[0]["service-port"])

        return 8887


if __name__ == "__main__":
    main(KfpSchedwf)
