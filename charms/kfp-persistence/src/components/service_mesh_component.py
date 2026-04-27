# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.
from charmed_kubeflow_chisme.components import Component
from charms.istio_beacon_k8s.v0.service_mesh import ServiceMeshConsumer
from ops import ActiveStatus, StatusBase


class ServiceMeshComponent(Component):
    """Component to manage service mesh integration for kfp-persistence."""

    def __init__(
        self,
        *args,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)

        self._mesh = ServiceMeshConsumer(self._charm)

    def get_status(self) -> StatusBase:
        return ActiveStatus()
