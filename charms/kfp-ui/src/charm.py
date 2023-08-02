#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Charm for the Kubeflow Pipelines UI.

https://github.com/canonical/kfp-operators
"""

import logging
from pathlib import Path

import lightkube
from charmed_kubeflow_chisme.components import (
    CharmReconciler,
    ContainerFileTemplate,
    KubernetesComponent,
    LeadershipGateComponent,
    SdiRelationBroadcasterComponent,
    SdiRelationDataReceiverComponent,
)
from charmed_kubeflow_chisme.kubernetes import create_charm_default_labels
from charms.kubeflow_dashboard.v0.kubeflow_dashboard_links import (
    DashboardLink,
    KubeflowDashboardLinksRequirer,
)
from lightkube.resources.rbac_authorization_v1 import ClusterRole, ClusterRoleBinding
from ops import BoundEvent, CharmBase, main

from components.pebble_components import MlPipelineUiInputs, MlPipelineUiPebbleService

logger = logging.getLogger(__name__)

TEMPLATES_PATH = Path("src/templates")
K8S_RESOURCE_FILES = [TEMPLATES_PATH / "auth_manifests.yaml.j2"]

CONFIG_JSON_TEMPLATE_FILE = TEMPLATES_PATH / "config.json"
CONFIG_JSON_DESTINATION_PATH = "/config/config.json"
VIEWER_POD_TEMPLATE_FILE = TEMPLATES_PATH / "viewer-pod-template.json"
VIEWER_JSON_DESTINATION_PATH = "/etc/config/viewer-pod-template.json"

DASHBOARD_LINKS = [
    DashboardLink(
        text="Experiments (KFP)",
        link="/pipeline/#/experiments",
        type="item",
        icon="done-all",
        location="menu",
    ),
    DashboardLink(
        text="Pipelines",
        link="/pipeline/#/pipelines",
        type="item",
        icon="kubeflow:pipeline-centered",
        location="menu",
    ),
    DashboardLink(
        text="Runs",
        link="/pipeline/#/runs",
        type="item",
        icon="maps:directions-run",
        location="menu",
    ),
    DashboardLink(
        text="Recurring Runs",
        link="/pipeline/#/recurringruns",
        type="item",
        icon="device:access-alarm",
        location="menu",
    ),
    DashboardLink(
        text="Upload a pipeline",
        desc="Pipelines",
        link="/pipeline/",
        location="quick",
    ),
    DashboardLink(
        text="View all pipeline runs",
        desc="Pipelines",
        link="/pipeline/#/runs",
        location="quick",
    ),
]


class KfpUiOperator(CharmBase):
    """Charm for the Kubeflow Pipelines UI.

    https://github.com/canonical/kfp-operators
    """

    def __init__(self, *args):
        super().__init__(*args)

        # add links in kubeflow-dashboard sidebar
        self.kubeflow_dashboard_sidebar = KubeflowDashboardLinksRequirer(
            charm=self,
            relation_name="dashboard-links",
            dashboard_links=DASHBOARD_LINKS,
        )

        # Handle charm upgrade
        self.framework.observe(self.on.upgrade_charm, self.upgrade_charm)

        # Charm logic
        self.charm_reconciler = CharmReconciler(self)

        self.leadership_gate = self.charm_reconciler.add(
            component=LeadershipGateComponent(
                charm=self,
                name="leadership-gate",
            ),
            depends_on=[],
        )

        self.ingress_relation = self.charm_reconciler.add(
            SdiRelationBroadcasterComponent(
                charm=self,
                name="relation:ingress",
                relation_name="ingress",
                data_to_send={
                    "prefix": "/pipeline",
                    "rewrite": "/pipeline",
                    "service": self.model.app.name,
                    "port": int(self.model.config["http-port"]),
                },
            ),
            depends_on=[self.leadership_gate],
        )

        self.kfp_ui_relation = self.charm_reconciler.add(
            SdiRelationBroadcasterComponent(
                charm=self,
                name="relation:kfp-ui",
                relation_name="kfp-ui",
                data_to_send={
                    "service-name": f"{self.model.app.name}.{self.model.name}",
                    "service-port": self.model.config["http-port"],
                },
            ),
            depends_on=[self.leadership_gate],
        )

        self.kubernetes_resources = self.charm_reconciler.add(
            component=KubernetesComponent(
                charm=self,
                name="kubernetes:auth",
                resource_templates=K8S_RESOURCE_FILES,
                krh_resource_types={ClusterRole, ClusterRoleBinding},
                krh_labels=create_charm_default_labels(
                    self.app.name, self.model.name, scope="auth-and-crds"
                ),
                context_callable=lambda: {"app_name": self.app.name, "namespace": self.model.name},
                lightkube_client=lightkube.Client(),  # TODO: Make this easier to test on
            ),
            depends_on=[self.leadership_gate],
        )

        self.object_storage_relation = self.charm_reconciler.add(
            component=SdiRelationDataReceiverComponent(
                charm=self,
                name="relation:object_storage",
                relation_name="object-storage",
            ),
            depends_on=[self.leadership_gate],
        )

        self.kfp_api_relation = self.charm_reconciler.add(
            component=SdiRelationDataReceiverComponent(
                charm=self,
                name="relation:kfp-api",
                relation_name="kfp-api",
            ),
            depends_on=[self.leadership_gate],
        )

        self.ml_pipeline_ui_container = self.charm_reconciler.add(
            component=MlPipelineUiPebbleService(
                charm=self,
                name="container:ml-pipeline-ui",  # This feels a bit redundant, but will read
                container_name="ml-pipeline-ui",  # well in the statuses.  Thoughts?
                service_name="ml-pipeline-ui",
                files_to_push=[
                    ContainerFileTemplate(
                        source_template_path=CONFIG_JSON_TEMPLATE_FILE,
                        destination_path=CONFIG_JSON_DESTINATION_PATH,
                    ),
                    ContainerFileTemplate(
                        source_template_path=VIEWER_POD_TEMPLATE_FILE,
                        destination_path=VIEWER_JSON_DESTINATION_PATH,
                    ),
                ],
                inputs_getter=lambda: MlPipelineUiInputs(
                    ALLOW_CUSTOM_VISUALIZATIONS=self.model.config["allow-custom-visualizations"],
                    HIDE_SIDENAV=self.model.config["hide-sidenav"],
                    MINIO_HOST=self.object_storage_relation.component.get_data()["service"],
                    MINIO_NAMESPACE=self.object_storage_relation.component.get_data()["namespace"],
                    MINIO_PORT=self.object_storage_relation.component.get_data()["port"],
                    MINIO_SSL=self.object_storage_relation.component.get_data()["secure"],
                    ML_PIPELINE_SERVICE_HOST=self.kfp_api_relation.component.get_data()[
                        "service-name"
                    ],
                    ML_PIPELINE_SERVICE_PORT=self.kfp_api_relation.component.get_data()[
                        "service-port"
                    ],
                ),
            ),
            depends_on=[
                self.leadership_gate,
                self.kubernetes_resources,
                self.object_storage_relation,
                self.kfp_api_relation,
            ],
        )

        self.charm_reconciler.install_default_event_handlers()

    def upgrade_charm(self, _: BoundEvent):
        """Handler for an upgrade-charm event.

        This handler should do anything required for upgrade that is not already covered by a
        regular Component in self.charm_reconciler.
        """
        logger.info("Handling the upgrade-charm event.")
        logger.info("No action needed for upgrade.  Continuing.")


if __name__ == "__main__":
    main(KfpUiOperator)
