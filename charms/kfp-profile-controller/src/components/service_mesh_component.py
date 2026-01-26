import logging

from charmed_kubeflow_chisme.components import Component
from charmed_kubeflow_chisme.service_mesh import generate_allow_all_authorization_policy
from charms.istio_beacon_k8s.v0.service_mesh import (
    MeshType,
    PolicyResourceManager,
    ServiceMeshConsumer,
)
from lightkube import Client
from ops import ActiveStatus, StatusBase

logger = logging.getLogger(__name__)


class ServiceMeshComponent(Component):
    """Component to manage service mesh integration for kfp-profile-controller."""

    def __init__(
        self,
        *args,
        service_mesh_relation_name: str = "service-mesh",
        **kwargs,
    ):
        super().__init__(*args, **kwargs)

        self._service_mesh_relation_name = service_mesh_relation_name

        self._mesh = ServiceMeshConsumer(self._charm)

        # trigger reconciliation logic to update AuthorizationPolicies when
        # the charm gets related to beacon
        self._events_to_observe = [
            self._charm.on[self._service_mesh_relation_name].relation_changed,
            self._charm.on[self._service_mesh_relation_name].relation_broken,
        ]

        self._policy_resource_manager = PolicyResourceManager(
            charm=self._charm,
            lightkube_client=Client(
                field_manager=f"{self._charm.app.name}-{self._charm.model.name}"
            ),
            labels={
                "app.kubernetes.io/instance": f"{self._charm.app.name}-{self._charm.model.name}",
                "kubernetes-resource-handler-scope": f"{self._charm.app.name}-allow-all",
            },
            logger=logger,
        )

        # Allow allow policy needed to allow Metacontroller to talk to the server
        self._allow_all_policy = generate_allow_all_authorization_policy(
            app_name=self._charm.app.name,
            namespace=self._charm.model.name,
        )

    def get_status(self) -> StatusBase:
        return ActiveStatus()

    def _configure_app_leader(self, event):
        """Reconcile the allow-all policy when the app is leader."""
        policies = []

        # create the allow-all policy only when related to ambient
        if self.ambient_mesh_enabled:
            logger.info("Integrated with ambient mesh, will create allow-all policy")
            policies.append(self._allow_all_policy)

        self._policy_resource_manager.reconcile(
            policies=[], mesh_type=MeshType.istio, raw_policies=policies
        )

    def remove(self, event):
        """Remove all policies on charm removal."""
        self._policy_resource_manager.reconcile(
            policies=[], mesh_type=MeshType.istio, raw_policies=[]
        )

    @property
    def ambient_mesh_enabled(self) -> bool:
        """Whether the charm is integrated with ambient mesh.

        It will look if the relation to istio-beacon-k8s is setup.
        """
        if self._charm.model.get_relation(self._service_mesh_relation_name):
            return True

        return False
