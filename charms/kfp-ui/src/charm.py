#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Charm for the Kubeflow Pipelines UI.

https://github.com/canonical/kfp-operators
"""

import logging
from pathlib import Path

import yaml
from charmed_kubeflow_chisme.components import (
    CharmReconciler,
    ContainerFileTemplate,
    LeadershipGateComponent,
    SdiRelationBroadcasterComponent,
    SdiRelationDataReceiverComponent,
)
from charms.kubeflow_dashboard.v0.kubeflow_dashboard_links import (
    DashboardLink,
    KubeflowDashboardLinksRequirer,
)
from charms.loki_k8s.v1.loki_push_api import LogForwarder
from charms.observability_libs.v1.kubernetes_service_patch import KubernetesServicePatch
from lightkube.models.core_v1 import ServicePort
from ops import CharmBase, main

from components.pebble_components import MlPipelineUiInputs, MlPipelineUiPebbleService

logger = logging.getLogger(__name__)

TEMPLATES_PATH = Path("src/templates")
SERVICE_CONFIG_PATH = Path("src/service-config.yaml")

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
        text="Artifacts",
        link="/pipeline/#/artifacts",
        type="item",
        icon="editor:bubble-chart",
        location="menu",
    ),
    DashboardLink(
        text="Executions",
        link="/pipeline/#/executions",
        type="item",
        icon="av:play-arrow",
        location="menu",
    ),
    DashboardLink(
        text="Upload a Pipeline",
        desc="Kubeflow Pipelines",
        link="/pipeline/#/pipelines",
        location="quick",
    ),
    DashboardLink(
        text="View Pipeline Runs",
        desc="Pipelines",
        link="/pipeline/#/runs",
        location="quick",
    ),
    DashboardLink(
        text="Kubeflow Pipelines Documentation",
        link="https://www.kubeflow.org/docs/components/pipelines/",
        desc="Documentation for Kubeflow Pipelines",
        location="documentation",
    ),
]


class KfpUiOperator(CharmBase):
    """Charm for the Kubeflow Pipelines UI.

    https://github.com/canonical/kfp-operators
    """

    def __init__(self, *args):
        super().__init__(*args)

        # Load user and command from service config file
        with open(SERVICE_CONFIG_PATH, "r") as file:
            service_config = yaml.safe_load(file)
        self.user = service_config.get("user", "")
        self.command = service_config.get("command", "")

        # add links in kubeflow-dashboard sidebar
        self.kubeflow_dashboard_sidebar = KubeflowDashboardLinksRequirer(
            charm=self,
            relation_name="dashboard-links",
            dashboard_links=DASHBOARD_LINKS,
        )

        # expose dashboard's port
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
                    ARGO_ARCHIVE_LOGS=self.model.config["argo-archive-logs"],
                    DISABLE_GKE_METADATA=self.model.config["disable-gke-metadata"],
                    FRONTEND_SERVER_NAMESPACE=self.model.name,
                    HIDE_SIDENAV=self.model.config["hide-sidenav"],
                    MINIO_ACCESS_KEY=self.object_storage_relation.component.get_data()[
                        "access-key"
                    ],
                    MINIO_SECRET_KEY=self.object_storage_relation.component.get_data()[
                        "secret-key"
                    ],
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
                    USER=self.user,
                    COMMAND=self.command,
                ),
            ),
            depends_on=[
                self.leadership_gate,
                self.object_storage_relation,
                self.kfp_api_relation,
            ],
        )

        self.charm_reconciler.install_default_event_handlers()
        self._logging = LogForwarder(charm=self)


if __name__ == "__main__":
    main(KfpUiOperator)
