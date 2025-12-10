# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.
import logging

from charmed_kubeflow_chisme.components.pebble_component import PebbleServiceComponent
from ops.pebble import Layer

logger = logging.getLogger(__name__)


class KfpViewerPebbleService(PebbleServiceComponent):
    def __init__(
        self,
        *args,
        max_num_viewers: str,
        **kwargs,
    ):
        """Pebble service container component in order to configure Pebble layer"""
        super().__init__(*args, **kwargs)
        self.max_num_viewers = max_num_viewers
        self.namespace = ""
        self.environment = {
            "MAX_NUM_VIEWERS": max_num_viewers,
            "NAMESPACE": self.namespace,
        }

    def get_layer(self) -> Layer:
        """Defines and returns Pebble layer configuration

        This method is required for subclassing PebbleServiceContainer
        """
        logger.info("PebbleServiceComponent.get_layer executing")

        layer_dict = {
            "summary": "kfp-viewer layer",
            "description": "Pebble config layer for kfp-viewer",
            "services": {
                self.service_name: {
                    "override": "replace",
                    "summary": "Entry point for kfp-viewer image",
                    "command": (
                        "/bin/controller"
                        " -logtostderr=true"
                        f" -max_num_viewers={self.max_num_viewers}"
                        f" --namespace={self.namespace}"
                    ),
                    "startup": "enabled",
                    "environment": self.environment,
                }
            },
        }

        return Layer(layer_dict)
