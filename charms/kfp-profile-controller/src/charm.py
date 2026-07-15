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
    RelationCountGateComponent,
    S3RequirerComponent,
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

from components.object_storage_validator import ObjectStorageValidatorComponent
from components.pebble_components import (
    KfpProfileControllerInputs,
    KfpProfileControllerPebbleService,
)
from components.resource_dispatcher_manifests import ResourceDispatcherManifestsComponent
from components.service_mesh_component import ServiceMeshComponent

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
KFP_IMAGES_VERSION = "2.16.0"  # Remember to change this version also in default-custom-images.json
# This service name must be the Service from the mlmd-operator
# FIXME: leaving it hardcoded now, but we should share this
# host and port through relation data
METADATA_GRPC_SERVICE_PORT = "8080"
NAMESPACE_LABEL = "pipelines.kubeflow.org/enabled"
SYNC_CODE_FILE = Path("files/upstream/sync.py")

# resource-dispatcher (kubernetes_manifest) relation endpoints. When related, the
# corresponding resource is created by resource-dispatcher instead of by sync.py.
SECRETS_RELATION_NAME = "secrets"
CONFIGMAPS_RELATION_NAME = "configmaps"

HOOKS_PATH = Path("/var/lib/pebble/default")


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
            # Validate the principal-related config early so the unit goes to BlockedStatus
            # if both `kfp-api-principal` and `kfp_api_service_account_name` are non-empty.
            self._get_kfp_api_principal()
        except ErrorWithStatus as e:
            self.unit.status = e.status
            return
        self.default_pipeline_root = self.model.config["default_pipeline_root"]

        self._container_name = next(iter(self.meta.containers))
        self.metadata_grpc_service_host = f"metadata-grpc-service.{self.model.name}"

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

        self.s3_relations_conflict_detector = self.charm_reconciler.add(
            component=RelationCountGateComponent(
                charm=self,
                name="s3-relations-conflict-detector",
                relation_names=["object-storage", "s3-credentials"],
            ),
            depends_on=[self.leadership_gate],
        )

        self.s3_relation = self.charm_reconciler.add(
            component=S3RequirerComponent(
                charm=self,
                name="relation:s3_credentials",
                relation_name="s3-credentials",
                is_optional=True,
                required_relation_fields=frozenset({"access-key", "secret-key", "endpoint"}),
            ),
            depends_on=[self.leadership_gate, self.s3_relations_conflict_detector],
        )

        self.object_storage_relation = self.charm_reconciler.add(
            component=SdiRelationDataReceiverComponent(
                charm=self,
                name="relation:object_storage",
                relation_name="object-storage",
                # Make this relation optional, since a relation with s3-credentials is
                # also sufficient
                minimum_related_applications=0,
            ),
            depends_on=[self.leadership_gate, self.s3_relations_conflict_detector],
        )

        self.object_storage_validator = self.charm_reconciler.add(
            component=ObjectStorageValidatorComponent(
                charm=self,
                name="object-storage-validator",
                s3_component=self.s3_relation.component,
                object_storage_component=self.object_storage_relation.component,
            ),
            depends_on=[
                self.leadership_gate,
                self.s3_relations_conflict_detector,
                self.s3_relation,
                self.object_storage_relation,
            ],
        )

        self.service_mesh_component = self.charm_reconciler.add(
            component=ServiceMeshComponent(charm=self, name="service-mesh-component"),
            depends_on=[self.leadership_gate],
        )

        self.resource_dispatcher_manifests = self.charm_reconciler.add(
            component=ResourceDispatcherManifestsComponent(
                charm=self,
                name="resource-dispatcher-manifests",
                object_storage_validator=self.object_storage_validator.component,
                default_pipeline_root=self.default_pipeline_root,
                secrets_relation_name=SECRETS_RELATION_NAME,
                configmaps_relation_name=CONFIGMAPS_RELATION_NAME,
            ),
            depends_on=[
                self.leadership_gate,
                self.s3_relations_conflict_detector,
                self.s3_relation,
                self.object_storage_relation,
                self.object_storage_validator,
            ],
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
                context_callable=self._generate_context,
                lightkube_client=lightkube.Client(),
            ),
            depends_on=[
                self.leadership_gate,
                self.s3_relations_conflict_detector,
                self.s3_relation,
                self.object_storage_relation,
                self.object_storage_validator,
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
                        destination_path=HOOKS_PATH / "sync.py",
                    )
                ],
                inputs_getter=self._generate_kfp_profile_controller_inputs,
            ),
            depends_on=[
                self.leadership_gate,
                self.kubernetes_resources,
                self.s3_relations_conflict_detector,
                self.s3_relation,
                self.object_storage_relation,
                self.object_storage_validator,
                self.service_mesh_component,
            ],
        )

        self.charm_reconciler.install_default_event_handlers()
        self._logging = LogForwarder(charm=self)

    def _generate_context(self) -> dict:
        """Generate the context for the secrets-and-compositecontroller Kubernetes resources."""
        object_storage = self.object_storage_validator.component.get_normalized_data()
        return {
            "namespace": self.model.name,
            "sync_webhook_url": f"http://{self.model.app.name}.{self.model.name}/sync",
            "access_key": b64encode(object_storage["access_key"].encode("utf-8")).decode("utf-8"),
            "secret_key": b64encode(object_storage["secret_key"].encode("utf-8")).decode("utf-8"),
            "minio_secret_name": f"{self.model.app.name}-minio-credentials",
            "label": NAMESPACE_LABEL,
        }

    def _generate_kfp_profile_controller_inputs(self) -> KfpProfileControllerInputs:
        """Generate the inputs for the kfp-profile-controller Pebble service."""
        object_storage = self.object_storage_validator.component.get_normalized_data()
        return KfpProfileControllerInputs(
            MINIO_SECRET=json.dumps(
                {"secret": {"name": f"{self.model.app.name}-minio-credentials"}}
            ),
            MINIO_HOST=object_storage["host"],
            MINIO_PORT=str(object_storage["port"]),
            MINIO_NAMESPACE=object_storage["namespace"],
            MINIO_ENDPOINT=object_storage["endpoint"],
            MINIO_ACCESS_KEY=object_storage["access_key"],
            MINIO_SECRET_KEY=object_storage["secret_key"],
            MINIO_SSL="true" if object_storage["secure"] else "false",
            MINIO_REGION=object_storage["region"],
            KFP_VERSION=KFP_IMAGES_VERSION,
            KFP_DEFAULT_PIPELINE_ROOT=self.default_pipeline_root,
            DISABLE_ISTIO_SIDECAR=DISABLE_ISTIO_SIDECAR,
            CONTROLLER_PORT=CONTROLLER_PORT,
            METADATA_GRPC_SERVICE_HOST=self.metadata_grpc_service_host,
            METADATA_GRPC_SERVICE_PORT=METADATA_GRPC_SERVICE_PORT,
            VISUALIZATION_SERVER_IMAGE=self.images["visualization_server__image"],
            VISUALIZATION_SERVER_TAG=self.images["visualization_server__version"],
            FRONTEND_IMAGE=self.images["frontend__image"],
            FRONTEND_TAG=self.images["frontend__version"],
            KFP_API_PRINCIPAL=self._get_kfp_api_principal(),
            AMBIENT_ENABLED=self.service_mesh_component.component.ambient_mesh_enabled,
            HOOKS_PATH=HOOKS_PATH,
            # If the corresponding resource-dispatcher relation exists, the resource is created
            # by resource-dispatcher, so sync.py should not manage (create) it.
            MANAGE_MINIO_SECRET=str(
                self.model.get_relation(SECRETS_RELATION_NAME) is None
            ).lower(),
            MANAGE_KFP_LAUNCHER_CONFIGMAP=str(
                self.model.get_relation(CONFIGMAPS_RELATION_NAME) is None
            ).lower(),
        )

    def _get_kfp_api_principal(self) -> str:
        """Return the KFP API principal to use in the AuthorizationPolicy.

        If the deprecated `kfp-api-principal` config option is set, it is used directly.
        Otherwise, the principal is computed from the `kfp_api_service_account_name` config
        option and the model namespace.

        Raises:
            ErrorWithStatus: if both `kfp-api-principal` and `kfp_api_service_account_name`
                are non-empty.
        """
        kfp_api_principal = self.model.config["kfp-api-principal"]
        kfp_api_service_account_name = self.model.config["kfp_api_service_account_name"]

        if kfp_api_principal:
            if kfp_api_service_account_name:
                raise ErrorWithStatus(
                    "Cannot set both `kfp-api-principal` and `kfp_api_service_account_name`. "
                    "The `kfp-api-principal` option is deprecated; to use it, set "
                    "`kfp_api_service_account_name` to an empty string.",
                    BlockedStatus,
                )
            logger.warning(
                "The `kfp-api-principal` config option is deprecated and will be removed in a "
                "future release. Use `kfp_api_service_account_name` instead."
            )
            return kfp_api_principal

        return f"cluster.local/ns/{self.model.name}/sa/{kfp_api_service_account_name}"

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
