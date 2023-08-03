#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Charm for the Kubeflow Pipelines Profile Controller.

https://github.com/canonical/kfp-operators
"""

import json
import logging
from base64 import b64encode
from pathlib import Path

import lightkube
from charmed_kubeflow_chisme.components import (
    ContainerFileTemplate,
    SdiRelationDataReceiverComponent,
)
from charmed_kubeflow_chisme.components.charm_reconciler import CharmReconciler
from charmed_kubeflow_chisme.components.kubernetes_component import KubernetesComponent
from charmed_kubeflow_chisme.components.leadership_gate_component import LeadershipGateComponent
from charmed_kubeflow_chisme.kubernetes import create_charm_default_labels
from lightkube.generic_resource import create_global_resource
from lightkube.resources.core_v1 import Secret
from ops.charm import CharmBase
from ops.main import main

from components.pebble_components import (
    KfpProfileControllerInputs,
    KfpProfileControllerPebbleService,
)

logger = logging.getLogger(__name__)

CompositeController = create_global_resource(
    "metacontroller.k8s.io", "v1alpha1", "CompositeController", "compositecontrollers"
)
CONTROLLER_PORT = 80
DISABLE_ISTIO_SIDECAR = "false"
K8S_RESOURCE_FILES = [
    "src/templates/crd_manifests.yaml.j2",
    "src/templates/secrets.yaml.j2",
]
KFP_DEFAULT_PIPELINE_ROOT = ""
KFP_IMAGES_VERSION = "2.0.0-alpha.7"
METADATA_GRPC_SERVICE_HOST = "mlmd.kubeflow"
METADATA_GRPC_SERVICE_PORT = "8080"
SYNC_CODE_FILE = Path("files/upstream/sync.py")
SYNC_CODE_DESTINATION_PATH = "/hooks/sync.py"


class KfpProfileControllerOperator(CharmBase):
    """Charm for the Kubeflow Pipelines Profile controller.

    https://github.com/canonical/kfp-operators
    """

    def __init__(self, *args):
        super().__init__(*args)

        self.charm_reconciler = CharmReconciler(self)

        self.leadership_gate = self.charm_reconciler.add(
            component=LeadershipGateComponent(
                charm=self,
                name="leadership-gate",
            ),
            depends_on=[],
        )

        self.object_storage_relation = self.charm_reconciler.add(
            component=SdiRelationDataReceiverComponent(
                charm=self,
                name="relation:object_storage",
                relation_name="object-storage",
            ),
            depends_on=[self.leadership_gate],
        )

        self.kubernetes_resources = self.charm_reconciler.add(
            component=KubernetesComponent(
                charm=self,
                name="kubernetes:secrets-and-compositecontroller",
                resource_templates=K8S_RESOURCE_FILES,
                krh_resource_types={Secret, CompositeController},
                krh_labels=create_charm_default_labels(
                    self.app.name,
                    self.model.name,
                    scope="secrets-and-compositecontroller",
                ),
                context_callable=lambda: {
                    "namespace": self.model.name,
                    "sync_webhook_url": f"http://{self.model.app.name}.{self.model.name}/sync",
                    "access_key": b64encode(
                        self.object_storage_relation.component.get_data()["access-key"].encode(
                            "utf-8"
                        )
                    ).decode("utf-8"),
                    "secret_key": b64encode(
                        self.object_storage_relation.component.get_data()["secret-key"].encode(
                            "utf-8"
                        )
                    ).decode("utf-8"),
                    "minio_secret_name": f"{self.model.app.name}-minio-credentials",
                },
                lightkube_client=lightkube.Client(),
            ),
            depends_on=[
                self.leadership_gate,
                self.object_storage_relation,
            ],
        )

        self.profile_controller_container = self.charm_reconciler.add(
            component=KfpProfileControllerPebbleService(
                charm=self,
                name="container:kfp-profile-controller",
                container_name="kfp-profile-controller",
                service_name="kfp-profile-controller",
                files_to_push=[
                    ContainerFileTemplate(
                        source_template_path=SYNC_CODE_FILE,
                        destination_path=SYNC_CODE_DESTINATION_PATH,
                    )
                ],
                inputs_getter=lambda: KfpProfileControllerInputs(
                    MINIO_SECRET=json.dumps(
                        {"secret": {"name": f"{self.model.app.name}-minio-credentials"}}
                    ),
                    MINIO_HOST=self.object_storage_relation.component.get_data()["service"],
                    MINIO_PORT=self.object_storage_relation.component.get_data()["port"],
                    MINIO_NAMESPACE=self.object_storage_relation.component.get_data()["namespace"],
                    MINIO_ACCESS_KEY=self.object_storage_relation.component.get_data()[
                        "access-key"
                    ],
                    MINIO_SECRET_KEY=self.object_storage_relation.component.get_data()[
                        "secret-key"
                    ],
                    KFP_VERSION=KFP_IMAGES_VERSION,
                    KFP_DEFAULT_PIPELINE_ROOT="",
                    DISABLE_ISTIO_SIDECAR=DISABLE_ISTIO_SIDECAR,
                    CONTROLLER_PORT=CONTROLLER_PORT,
                    METADATA_GRPC_SERVICE_HOST=METADATA_GRPC_SERVICE_HOST,
                    METADATA_GRPC_SERVICE_PORT=METADATA_GRPC_SERVICE_PORT,
                ),
            ),
            depends_on=[
                self.leadership_gate,
                self.kubernetes_resources,
                self.object_storage_relation,
            ],
        )

        self.charm_reconciler.install_default_event_handlers()


if __name__ == "__main__":
    main(KfpProfileControllerOperator)
