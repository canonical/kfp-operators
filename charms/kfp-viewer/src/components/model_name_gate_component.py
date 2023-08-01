# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.
import logging

from charmed_kubeflow_chisme.components.component import Component
from ops import ActiveStatus, BlockedStatus, CharmBase, StatusBase

logger = logging.getLogger(__name__)


class ModelNameGate(Component):
    """Raises BlockedStatus if the model name is not kubeflow.
    This is because some elements of the viewer are hard coded to use the kubeflow namespace.
    """

    def __init__(self, charm: CharmBase, name: str):
        super().__init__(charm, name)
        self._events_to_observe.append(self._charm.on.upgrade_charm)
        # TODO: Remove below line when LeadershipGateComponent triggers leader events
        self._events_to_observe.append(self._charm.on.leader_elected)

    def ready_for_execution(self) -> bool:
        """Returns True if model name is "kubeflow", else False."""
        return self._charm.model.name == "kubeflow"

    def get_status(self) -> StatusBase:
        if self._charm.model.name != "kubeflow":
            return BlockedStatus("kfp-viewer must be deployed to model named `kubeflow`")

        return ActiveStatus()
