#!/usr/bin/env python3
# Copyright 2024 Ubuntu
# See LICENSE file for licensing details.

from typing import List, Optional, Union

from charmed_kubeflow_chisme.components.component import Component
from charms.mlops_libs.v0.k8s_service_info import (
    KubernetesServiceInfoObject,
    KubernetesServiceInfoRelationDataMissingError,
    KubernetesServiceInfoRelationMissingError,
    KubernetesServiceInfoRequirer,
)
from ops import ActiveStatus, BlockedStatus, CharmBase, StatusBase
from ops.framework import BoundEvent


class K8sServiceInfoComponent(Component):
    """A Component that wraps the requirer side of the k8s_service_info charm library.

    Args:
        charm(CharmBase): the requirer charm
        relation_name(str, Optional): name of the relation that uses the k8s-service interface
    """

    def __init__(
        self,
        charm: CharmBase,
        relation_name: Optional[str] = "k8s-service-info",
        refresh_event: Optional[Union[BoundEvent, List[BoundEvent]]] = None,
    ):
        super().__init__(charm, relation_name)
        self.relation_name = relation_name
        self.charm = charm
        self.refresh_event = refresh_event

        self._k8s_service_info_requirer = KubernetesServiceInfoRequirer(
            charm=self.charm, relation_name=self.relation_name, refresh_event=self.refresh_event
        )

        self._events_to_observe = [self._k8s_service_info_requirer.on.updated]

    def get_service_info(self) -> KubernetesServiceInfoObject:
        """Wrap the get_data method and return a KubernetesServiceInfoObject."""
        return self._k8s_service_info_requirer.get_data()

    def get_status(self) -> StatusBase:
        """Return this component's status based on the presence of the relation and its data."""
        try:
            self.get_service_info()
        except KubernetesServiceInfoRelationMissingError as rel_error:
            return BlockedStatus(f"{rel_error.message} Please add the missing relation.")
        except KubernetesServiceInfoRelationDataMissingError as data_error:
            # Nothing can be done, just re-raise
            raise data_error
        return ActiveStatus()
