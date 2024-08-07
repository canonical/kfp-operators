#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Charm for the data persistence application of Kubeflow Pipelines.

https://github.com/canonical/kfp-operators/
"""

import logging
from pathlib import Path

import lightkube
from charmed_kubeflow_chisme.components.charm_reconciler import CharmReconciler
from charmed_kubeflow_chisme.components.kubernetes_component import KubernetesComponent
from charmed_kubeflow_chisme.components.leadership_gate_component import LeadershipGateComponent
from charmed_kubeflow_chisme.components.pebble_component import ContainerFileTemplate
from charmed_kubeflow_chisme.components.serialised_data_interface_components import (
    SdiRelationDataReceiverComponent,
)
from charmed_kubeflow_chisme.kubernetes import create_charm_default_labels
from charms.loki_k8s.v1.loki_push_api import LogForwarder
from lightkube.resources.core_v1 import ServiceAccount
from lightkube.resources.rbac_authorization_v1 import ClusterRole, ClusterRoleBinding
from ops import CharmBase, main

from components.pebble_components import (
    PersistenceAgentPebbleService,
    PesistenceAgentServiceConfig,
)
from components.sa_token_component import SaTokenComponent

log = logging.getLogger()

K8S_RESOURCE_FILES = ["src/templates/auth_manifests.yaml.j2"]
SA_NAME = "ml-pipeline-persistenceagent"
SA_TOKEN_PATH = "src/"
SA_TOKEN_FILENAME = "persistenceagent-sa-token"
SA_TOKEN_FULL_PATH = str(Path(SA_TOKEN_PATH, SA_TOKEN_FILENAME))
SA_TOKEN_DESTINATION_PATH = f"/var/run/secrets/kubeflow/tokens/{SA_TOKEN_FILENAME}"


class KfpPersistenceOperator(CharmBase):
    """Charm for the data persistence application of Kubeflow Pipelines."""

    def __init__(self, *args, **kwargs):
        """Initialize charm and setup the container."""
        super().__init__(*args, **kwargs)

        # Charm logic
        self.charm_reconciler = CharmReconciler(self)

        # Components
        self.leadership_gate = self.charm_reconciler.add(
            component=LeadershipGateComponent(charm=self, name="leadership-gate"), depends_on=[]
        )

        self.kfp_api_relation = self.charm_reconciler.add(
            component=SdiRelationDataReceiverComponent(
                charm=self, name="relation:kfp-api", relation_name="kfp-api"
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
                context_callable=lambda: {
                    "app_name": self.app.name,
                    "namespace": self.model.name,
                    "sa_name": SA_NAME,
                },
                lightkube_client=lightkube.Client(),
            ),
            depends_on=[self.leadership_gate],
        )

        self.sa_token = self.charm_reconciler.add(
            component=SaTokenComponent(
                charm=self,
                name="sa-token:persistenceagent",
                audiences=["pipelines.kubeflow.org"],
                sa_name=SA_NAME,
                sa_namespace=self.model.name,
                filename=SA_TOKEN_FILENAME,
                path=SA_TOKEN_PATH,
                expiration=4294967296,
            ),
            depends_on=[self.leadership_gate, self.kubernetes_resources],
        )
        self.persistenceagent_container = self.charm_reconciler.add(
            component=PersistenceAgentPebbleService(
                charm=self,
                name="container:persistenceagent",
                container_name="persistenceagent",
                service_name="persistenceagent",
                files_to_push=[
                    ContainerFileTemplate(
                        source_template_path=SA_TOKEN_FULL_PATH,
                        destination_path=SA_TOKEN_DESTINATION_PATH,
                    )
                ],
                environment={
                    "KUBEFLOW_USERID_HEADER": "kubeflow-userid",
                    "KUBEFLOW_USERID_PREFIX": "",
                    "LOG_LEVEL": self.model.config["log-level"],
                    # Upstream defines this in the configmap persistenceagent-config-*
                    "MULTIUSER": "true",
                    "NAMESPACE": "",
                    "TTL_SECONDS_AFTER_WORKFLOW_FINISH": "86400",
                    "NUM_WORKERS": "2",
                    "EXECUTIONTYPE": "Workflow",
                },
                # provide function to pebble with which it can get service configuration from
                # relation
                inputs_getter=lambda: PesistenceAgentServiceConfig(
                    KFP_API_SERVICE_NAME=self.kfp_api_relation.component.get_data()[
                        "service-name"
                    ],
                ),
            ),
            depends_on=[
                self.leadership_gate,
                self.kfp_api_relation,
                self.kubernetes_resources,
                self.sa_token,
            ],
        )

        self.charm_reconciler.install_default_event_handlers()
        self._logging = LogForwarder(charm=self)


class CheckFailedError(Exception):
    """Raise this exception if one of the checks in main fails."""

    def __init__(self, msg, status_type=None):
        super().__init__()

        self.msg = msg
        self.status_type = status_type
        self.status = status_type(msg)


if __name__ == "__main__":
    main(KfpPersistenceOperator)
