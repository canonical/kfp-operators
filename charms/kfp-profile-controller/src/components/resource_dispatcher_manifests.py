"""Chisme component that sends resources to resource-dispatcher for multi-tenancy.

When `kfp-profile-controller` is integrated with `resource-dispatcher` over the
`secrets` and `config-maps` relations, the resources that are otherwise created per
user-namespace by `files/upstream/sync.py` are instead sent to `resource-dispatcher`
so that it can create them in every Profile namespace.

The two relations are independent:
  * `secrets`    -> the `mlpipeline-minio-artifact` Secret
  * `config-maps` -> handles the `kfp-launcher` ConfigMap

Manifests are sent without a `metadata.namespace` so that `resource-dispatcher` treats
them as global manifests and applies them to every Profile namespace.
"""

import logging
from base64 import b64encode

import yaml
from charmed_kubeflow_chisme.components import Component
from charmed_kubeflow_chisme.exceptions import ErrorWithStatus
from charms.resource_dispatcher.v0.kubernetes_manifests import (
    KubernetesManifest,
    KubernetesManifestRequirerWrapper,
)
from ops import ActiveStatus, CharmBase, StatusBase

from components.object_storage_validator import ObjectStorageValidatorComponent

logger = logging.getLogger(__name__)

MINIO_SECRET_NAME = "mlpipeline-minio-artifact"
KFP_LAUNCHER_CONFIGMAP_NAME = "kfp-launcher"


class ResourceDispatcherManifestsComponent(Component):
    """Sends the minio Secret and kfp-launcher ConfigMap to resource-dispatcher.

    This component renders and sends the manifests only for the relations that are present,
    keeping the `secrets` and `configmaps` integrations independent.
    """

    def __init__(
        self,
        charm: CharmBase,
        name: str,
        object_storage_validator: ObjectStorageValidatorComponent,
        default_pipeline_root: str,
        secrets_relation_name: str = "secrets",
        configmaps_relation_name: str = "config-maps",
    ):
        """Initialise the component.

        Args:
            charm: the parent charm.
            name: unique component name.
            object_storage_validator: component providing the normalized object storage data.
            default_pipeline_root: the `default_pipeline_root` config value.
            secrets_relation_name: name of the secrets endpoint.
            configmaps_relation_name: name of the configmaps endpoint.
        """
        super().__init__(charm=charm, name=name)
        self._charm = charm
        self._object_storage_validator = object_storage_validator
        self._default_pipeline_root = default_pipeline_root
        self._secrets_relation_name = secrets_relation_name
        self._configmaps_relation_name = configmaps_relation_name
        self._secrets_wrapper = KubernetesManifestRequirerWrapper(
            charm=self._charm, relation_name=self._secrets_relation_name
        )
        self._configmaps_wrapper = KubernetesManifestRequirerWrapper(
            charm=self._charm, relation_name=self._configmaps_relation_name
        )
        # Reconcile (and thus (re)send manifests) whenever either resource-dispatcher relation
        # changes, so the resources are (re)sent as soon as the relation is established.
        for relation_name in (self._secrets_relation_name, self._configmaps_relation_name):
            self._events_to_observe.extend(
                [
                    self._charm.on[relation_name].relation_created,
                    self._charm.on[relation_name].relation_changed,
                    self._charm.on[relation_name].relation_broken,
                ]
            )

    def _is_related(self, relation_name: str) -> bool:
        """Return whether the given relation is established."""
        return self._charm.model.get_relation(relation_name) is not None

    def _minio_secret_manifest(self, object_storage: dict) -> str:
        """Return the mlpipeline-minio-artifact Secret manifest (without a namespace)."""
        manifest = {
            "apiVersion": "v1",
            "kind": "Secret",
            "metadata": {
                "name": MINIO_SECRET_NAME,
            },
            "data": {
                "accesskey": b64encode(object_storage["access_key"].encode("utf-8")).decode(
                    "utf-8"
                ),
                "secretkey": b64encode(object_storage["secret_key"].encode("utf-8")).decode(
                    "utf-8"
                ),
            },
        }
        return yaml.safe_dump(manifest)

    def _kfp_launcher_configmap_manifest(self, object_storage: dict) -> str:
        """Return the kfp-launcher ConfigMap manifest (without a namespace).

        This mirrors the `providers` configuration built in `files/upstream/sync.py` so
        that resource-dispatcher creates the same ConfigMap it would otherwise create.
        """
        providers_yaml = (
            "minio:\n"
            "  default:\n"
            f"    endpoint: {object_storage['endpoint']}\n"
            f"    disableSSL: {'false' if object_storage['secure'] else 'true'}\n"
            f"    region: {object_storage['region']}\n"
            "    forcePathStyle: true\n"
            "    credentials:\n"
            "      fromEnv: false\n"
            "      secretRef:\n"
            f"        secretName: {MINIO_SECRET_NAME}\n"
            "        accessKeyKey: accesskey\n"
            "        secretKeyKey: secretkey"
        )
        configmap_data = {"providers": providers_yaml}
        if self._default_pipeline_root:
            configmap_data["defaultPipelineRoot"] = self._default_pipeline_root

        manifest = {
            "apiVersion": "v1",
            "kind": "ConfigMap",
            "metadata": {
                "name": KFP_LAUNCHER_CONFIGMAP_NAME,
            },
            "data": configmap_data,
        }
        return yaml.safe_dump(manifest)

    def _configure_app_leader(self, event):
        """Render and send manifests to resource-dispatcher for the related endpoints."""
        secrets_related = self._is_related(self._secrets_relation_name)
        configmaps_related = self._is_related(self._configmaps_relation_name)

        if not secrets_related and not configmaps_related:
            # Not integrated with resource-dispatcher; sync.py creates the resources instead.
            return

        object_storage = self._object_storage_validator.get_normalized_data()

        if secrets_related:
            self._secrets_wrapper.send_data(
                [KubernetesManifest(self._minio_secret_manifest(object_storage))]
            )
        if configmaps_related:
            self._configmaps_wrapper.send_data(
                [KubernetesManifest(self._kfp_launcher_configmap_manifest(object_storage))]
            )

    def get_status(self) -> StatusBase:
        """Return the component status.

        The component is Active unless the (already validated) object storage data cannot be
        read while a resource-dispatcher relation is present.
        """
        if not self._is_related(self._secrets_relation_name) and not self._is_related(
            self._configmaps_relation_name
        ):
            return ActiveStatus()
        try:
            self._object_storage_validator.get_normalized_data()
        except ErrorWithStatus as err:
            return err.status
        return ActiveStatus()
