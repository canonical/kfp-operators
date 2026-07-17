"""Chisme component that sends a resource to resource-dispatcher for multi-tenancy.

When `kfp-profile-controller` is integrated with `resource-dispatcher` over the
`secrets` and `config-maps` relations, the resources that are otherwise created per
user-namespace by `files/upstream/sync.py` are instead sent to `resource-dispatcher`
so that it can create them in every Profile namespace.

The two relations are independent, so each is handled by its own instance of
`ResourceDispatcherManifestsComponent`:
  * `secrets`     -> the `mlpipeline-minio-artifact` Secret
  * `config-maps` -> the `kfp-launcher` ConfigMap
"""

import logging
from base64 import b64encode
from pathlib import Path

from charmed_kubeflow_chisme.components import Component
from charmed_kubeflow_chisme.exceptions import ErrorWithStatus
from charms.resource_dispatcher.v0.kubernetes_manifests import (
    KubernetesManifest,
    KubernetesManifestRequirerWrapper,
)
from jinja2 import Template
from ops import ActiveStatus, CharmBase, StatusBase

from components.object_storage_validator import ObjectStorageValidatorComponent

logger = logging.getLogger(__name__)

MINIO_SECRET_NAME = "mlpipeline-minio-artifact"
KFP_LAUNCHER_CONFIGMAP_NAME = "kfp-launcher"


class ResourceDispatcherManifestsComponent(Component):
    """Sends a single manifest to resource-dispatcher over one relation.

    Each instance handles exactly one resource-dispatcher relation, rendering and sending
    its manifest only when that relation is present. Instantiate one component per relation
    (e.g. one for `secrets` and one for `config-maps`) to keep the integrations independent.
    """

    def __init__(
        self,
        charm: CharmBase,
        name: str,
        object_storage_validator: ObjectStorageValidatorComponent,
        default_pipeline_root: str,
        relation_name: str,
        template_path: str,
    ):
        """Initialise the component.

        Args:
            charm: the parent charm.
            name: unique component name.
            object_storage_validator: component providing the normalized object storage data.
            default_pipeline_root: the `default_pipeline_root` config value.
            relation_name: name of the resource-dispatcher endpoint this component handles.
            template_path: path to the Jinja template defining the manifest to send.
        """
        super().__init__(charm=charm, name=name)
        self._charm = charm
        self._object_storage_validator = object_storage_validator
        self._default_pipeline_root = default_pipeline_root
        self._relation_name = relation_name
        self._template_path = template_path
        self._wrapper = KubernetesManifestRequirerWrapper(
            charm=self._charm, relation_name=self._relation_name
        )
        # Reconcile (and thus (re)send the manifest) whenever the resource-dispatcher relation
        # changes, so the resource is (re)sent as soon as the relation is established.
        self._events_to_observe.extend(
            [
                self._charm.on[self._relation_name].relation_created,
                self._charm.on[self._relation_name].relation_changed,
                self._charm.on[self._relation_name].relation_broken,
            ]
        )

    def _is_related(self) -> bool:
        """Return whether the relation is established."""
        return self._charm.model.get_relation(self._relation_name) is not None

    def _render_manifest(self, object_storage: dict) -> str:
        """Render the manifest template with the object storage data.

        A single render context is shared across templates; each template uses only the
        values it needs.
        """
        context = {
            "minio_secret_name": MINIO_SECRET_NAME,
            "kfp_launcher_configmap_name": KFP_LAUNCHER_CONFIGMAP_NAME,
            "access_key_b64": b64encode(object_storage["access_key"].encode("utf-8")).decode(
                "utf-8"
            ),
            "secret_key_b64": b64encode(object_storage["secret_key"].encode("utf-8")).decode(
                "utf-8"
            ),
            "endpoint": object_storage["endpoint"],
            "secure": object_storage["secure"],
            "region": object_storage["region"],
            "default_pipeline_root": self._default_pipeline_root,
        }
        template = Template(Path(self._template_path).read_text())
        return template.render(**context)

    def _configure_app_leader(self, event):
        """Render and send the manifest to resource-dispatcher when the relation is present."""
        if not self._is_related():
            # Not integrated with resource-dispatcher; sync.py creates the resource instead.
            return

        object_storage = self._object_storage_validator.get_normalized_data()
        self._wrapper.send_data([KubernetesManifest(self._render_manifest(object_storage))])

    def get_status(self) -> StatusBase:
        """Return the component status.

        The component is Active unless the (already validated) object storage data cannot be
        read while the resource-dispatcher relation is present.
        """
        if not self._is_related():
            return ActiveStatus()
        try:
            self._object_storage_validator.get_normalized_data()
        except ErrorWithStatus as err:
            return err.status
        return ActiveStatus()
