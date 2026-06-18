import logging

from charmed_kubeflow_chisme.components import Component
from ops import ActiveStatus, BlockedStatus, StatusBase

logger = logging.getLogger(__name__)


class IstioRelationsConflictDetectorComponent(Component):
    """Component to detect conflicting Istio relations."""

    def __init__(
        self,
        *args,
        sidecar_relation_name: str = "ingress",
        ambient_relation_name: str = "istio-ingress-route",
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.sidecar_relation_name = sidecar_relation_name
        self.ambient_relation_name = ambient_relation_name

    def get_status(self) -> StatusBase:
        """Check that both ambient and sidecar relations are not present simultaneously.

        Each endpoint may hold any number of relations, so this inspects the full list
        of relations on each endpoint rather than assuming at most one.
        """
        ambient_relations = self._charm.model.relations[self.ambient_relation_name]
        sidecar_relations = self._charm.model.relations[self.sidecar_relation_name]

        if ambient_relations and sidecar_relations:
            logger.error(
                f"Both '{self.ambient_relation_name}' and '{self.sidecar_relation_name}' "
                "relations are present, remove one to unblock."
            )
            return BlockedStatus(
                f"Cannot have both '{self.ambient_relation_name}' and "
                f"'{self.sidecar_relation_name}' relations at the same time."
            )
        return ActiveStatus()
