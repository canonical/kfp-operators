# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.
import logging

from charmed_kubeflow_chisme.components.component import Component
from ops import ActiveStatus, BlockedStatus, StatusBase

logger = logging.getLogger(__name__)


class ModelNameGateComponent(Component):
    """Raises BlockedStatus if the model name is not kubeflow.
    This is because some elements of the viewer are hard coded to use the kubeflow namespace.
    """

    def ready_for_execution(self) -> bool:
        """Returns True if charm is deployed to model named "kubeflow", else False."""
        return self._charm.model.name == "kubeflow"

    def get_status(self) -> StatusBase:
        """Returns True if charm is deployed to model named "kubeflow", else False."""
        if self._charm.model.name != "kubeflow":
            return BlockedStatus("kfp-viewer must be deployed to model named `kubeflow`")

        return ActiveStatus()
