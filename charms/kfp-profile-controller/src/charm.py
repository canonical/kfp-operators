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
from typing import Dict

import lightkube
import yaml
from charmed_kubeflow_chisme.components import (
    ContainerFileTemplate,
    SdiRelationDataReceiverComponent,
)
from charmed_kubeflow_chisme.components.charm_reconciler import CharmReconciler
from charmed_kubeflow_chisme.components.kubernetes_component import KubernetesComponent
from charmed_kubeflow_chisme.components.leadership_gate_component import LeadershipGateComponent
from charmed_kubeflow_chisme.exceptions import ErrorWithStatus
from charmed_kubeflow_chisme.kubernetes import create_charm_default_labels
from charms.loki_k8s.v1.loki_push_api import LogForwarder
from charms.observability_libs.v1.kubernetes_service_patch import KubernetesServicePatch
from lightkube.generic_resource import create_global_resource
from lightkube.models.core_v1 import ServicePort
from lightkube.resources.core_v1 import Secret
from ops import main
from ops.charm import CharmBase
from ops.model import BlockedStatus

from components.pebble_components import (
    KfpProfileControllerInputs,
    KfpProfileControllerPebbleService,
)

DEFAULT_IMAGES_FILE = "src/default-custom-images.json"
with open(DEFAULT_IMAGES_FILE, "r") as json_file:
    DEFAULT_IMAGES = json.load(json_file)

logger = logging.getLogger(__name__)

DecoratorController = create_global_resource(
    "metacontroller.k8s.io", "v1alpha1", "DecoratorController", "decoratorcontrollers"
)
CONTROLLER_PORT = 1025
K8S_SVC_CONTROLLER_PORT = 80
DISABLE_ISTIO_SIDECAR = "false"
K8S_RESOURCE_FILES = [
    "src/templates/crd_manifests.yaml.j2",
    "src/templates/secrets.yaml.j2",
]
KFP_IMAGES_VERSION = "2.5.0"  # Remember to change this version also in default-custom-images.json
# This service name must be the Service from the mlmd-operator
# FIXME: leaving it hardcoded now, but we should share this
# host and port through relation data
METADATA_GRPC_SERVICE_HOST = "metadata-grpc-service.kubeflow"
METADATA_GRPC_SERVICE_PORT = "8080"
NAMESPACE_LABEL = "pipelines.kubeflow.org/enabled"
SYNC_CODE_FILE = Path("files/upstream/sync.py")


def parse_images_config(config: str) -> Dict:
    """
    Parse a YAML config-defined images list.

    This function takes a YAML-formatted string 'config' containing a list of images
    and returns a dictionary representing the images.

    Args:
        config (str): YAML-formatted string representing a list of images.

    Returns:
        Dict: A list of images.
    """
    if not config:
        return []
    try:
        images = yaml.safe_load(config)
    except yaml.YAMLError as err:
        logger.error(
            f"Charm Blocked due to error parsing the `custom_images` config.  "
            f"Caught error: {str(err)}"
        )
        raise ErrorWithStatus(
            "Error parsing the `custom_images` config - fix `custom_images` to unblock.  "
            "See logs for more details",
            BlockedStatus,
        )
    return images


class KfpProfileControllerOperator(CharmBase):
    """Charm for the Kubeflow Pipelines Profile controller.

    https://github.com/canonical/kfp-operators
    """

    def __init__(self, *args):
        super().__init__(*args)
        try:
            self.images = self.get_images(
                DEFAULT_IMAGES,
                parse_images_config(self.model.config["custom_images"]),
            )
        except ErrorWithStatus as e:
            self.unit.status = e.status
            return
        self.default_pipeline_root = self.model.config["default_pipeline_root"]

        # Storage
        self._container_name = next(iter(self.meta.containers))
        _container_meta = self.meta.containers[self._container_name]
        _storage_name = next(iter(_container_meta.mounts))
        self._hooks_storage_path = Path(_container_meta.mounts[_storage_name].location)

        # expose controller's port
        http_port = ServicePort(K8S_SVC_CONTROLLER_PORT, name="http", targetPort=CONTROLLER_PORT)
        self.service_patcher = KubernetesServicePatch(
            self, [http_port], service_name=f"{self.model.app.name}"
        )

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
                krh_resource_types={Secret, DecoratorController},
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
                    "label": NAMESPACE_LABEL,
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
                name=f"container:{self._container_name}",
                container_name=self._container_name,
                service_name="kfp-profile-controller",
                files_to_push=[
                    ContainerFileTemplate(
                        source_template_path=SYNC_CODE_FILE,
                        destination_path=self._hooks_storage_path / "sync.py",
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
                    KFP_DEFAULT_PIPELINE_ROOT=self.default_pipeline_root,
                    DISABLE_ISTIO_SIDECAR=DISABLE_ISTIO_SIDECAR,
                    CONTROLLER_PORT=CONTROLLER_PORT,
                    METADATA_GRPC_SERVICE_HOST=METADATA_GRPC_SERVICE_HOST,
                    METADATA_GRPC_SERVICE_PORT=METADATA_GRPC_SERVICE_PORT,
                    VISUALIZATION_SERVER_IMAGE=self.images["visualization_server__image"],
                    VISUALIZATION_SERVER_TAG=self.images["visualization_server__version"],
                    FRONTEND_IMAGE=self.images["frontend__image"],
                    FRONTEND_TAG=self.images["frontend__version"],
                ),
            ),
            depends_on=[
                self.leadership_gate,
                self.kubernetes_resources,
                self.object_storage_relation,
            ],
        )

        self.charm_reconciler.install_default_event_handlers()
        self._logging = LogForwarder(charm=self)

    def get_images(
        self, default_images: Dict[str, str], custom_images: Dict[str, str]
    ) -> Dict[str, str]:
        """
        Combine default images with custom images.

        This function takes two dictionaries, 'default_images' and 'custom_images',
        representing the default set of images and the custom set of images respectively.
        It combines the custom images into the default image list, overriding any matching
        image names from the default list with the custom ones.

        Args:
            default_images (Dict[str, str]): A dictionary containing the default image names
                as keys and their corresponding default image URIs as values.
            custom_images (Dict[str, str]): A dictionary containing the custom image names
                as keys and their corresponding custom image URIs as values.

        Returns:
            Dict[str, str]: A dictionary representing the combined images, where image names
            from the custom_images override any matching image names from the default_images.
        """
        images = default_images
        for image_name, custom_image in custom_images.items():
            if custom_image:
                if image_name in images:
                    images[image_name] = custom_image
                else:
                    logger.error(
                        f"Image name `{image_name}` set in `custom_images` config not found in "
                        f"images list: {', '.join(images.keys())}."
                    )
                    raise ErrorWithStatus(
                        "Incorrect image name in `custom_images` config - fix `custom_images` to "
                        "unblock.  See logs for more details",
                        BlockedStatus,
                    )

        # This are special cases comfigmap where they need to be split into image and version
        for image_name in [
            "visualization_server",
            "frontend",
        ]:
            images[f"{image_name}__image"], images[f"{image_name}__version"] = images[
                image_name
            ].rsplit(":", 1)
        return images


if __name__ == "__main__":
    main(KfpProfileControllerOperator)
