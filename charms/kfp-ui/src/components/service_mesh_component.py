import logging

from charmed_kubeflow_chisme.components import Component
from charmed_kubeflow_chisme.service_mesh import generate_allow_all_authorization_policy
from charms.istio_beacon_k8s.v0.service_mesh import (
    AppPolicy,
    MeshType,
    PolicyResourceManager,
    ServiceMeshConsumer,
)
from lightkube import Client
from ops import ActiveStatus, StatusBase

from charms.istio_ingress_k8s.v0.istio_ingress_route import IstioIngressRouteRequirer, IstioIngressRouteConfig, HTTPRoute, HTTPRouteMatch, HTTPPathMatch, BackendRef, Listener, ProtocolType, URLRewriteFilter, URLRewriteSpec, PathModifier, PathModifierType

logger = logging.getLogger(__name__)


class ServiceMeshComponent(Component):
    """Component to manage service mesh integration for kfp-ui."""

    def __init__(
        self,
        *args,
        service_mesh_relation_name: str = "service-mesh",
        **kwargs,
    ):
        super().__init__(*args, **kwargs)

        self._service_mesh_relation_name = service_mesh_relation_name

        self._mesh = ServiceMeshConsumer(self._charm,
                                         policies=[
                                             AppPolicy(relation="kfp-ui")
                                         ])
        
        self.ingress = IstioIngressRouteRequirer(self, relation_name="istio-ingress-route")
        self._ambient_ingress_setup()

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

    def _ambient_ingress_setup(self):
        """Submit the Ingress configuration for Ambient Mesh, if unit is leader."""
        http_listener = Listener(port=80, protocol=ProtocolType.HTTP)

        config = IstioIngressRouteConfig(
            model=self.model.name,
            listeners=[http_listener],
            http_routes=[
                HTTPRoute(
                    name="http-ingress",
                    listener=http_listener,
                    matches=[HTTPRouteMatch(path=HTTPPathMatch(value="/pipeline"))],
                    backends=[BackendRef(service=self._charm.app.name, port=PORT)],
                )
            ],
        )

        self.ingress.submit_config(config)


    def get_status(self) -> StatusBase:
        return ActiveStatus()

    def _configure_app_leader(self, event):
        """Reconcile the allow-all policy when the app is leader."""
        policies = []

        # create the allow-all policy only when related to ambient
        if self.ambient_mesh_enabled:
            policies.append()

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
