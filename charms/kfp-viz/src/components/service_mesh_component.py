# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.
from charmed_kubeflow_chisme.components import Component
from charms.istio_beacon_k8s.v0.service_mesh import AppPolicy, ServiceMeshConsumer
from ops import ActiveStatus, StatusBase


class ServiceMeshComponent(Component):
    """Component to manage service mesh integration for kfp-viz."""

    def __init__(
        self,
        *args,
        service_mesh_relation_name: str = "service-mesh",
        provided_relation_name: str = "kfp-viz",
        **kwargs,
    ):
        super().__init__(*args, **kwargs)

        self._service_mesh_relation_name = service_mesh_relation_name
        self._provided_relation_name = provided_relation_name

        self._mesh = ServiceMeshConsumer(
            self._charm, policies=[AppPolicy(relation=self._provided_relation_name, endpoints=[])]
        )

    def get_status(self) -> StatusBase:
        return ActiveStatus()
