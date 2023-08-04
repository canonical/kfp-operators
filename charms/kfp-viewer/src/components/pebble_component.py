# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.
import logging
from typing import Dict

from charmed_kubeflow_chisme.components.pebble_component import PebbleServiceComponent
from ops.pebble import Layer

logger = logging.getLogger(__name__)


class PebbleServiceContainerComponent(PebbleServiceComponent):
    def __init__(
        self,
        *args,
        environment: Dict[str, str],
        **kwargs,
    ):
        """Pebble service container component in order to configure Pebble layer"""
        super().__init__(*args, **kwargs)
        self.environment = environment

    def get_layer(self) -> Layer:
        """Defines and returns Pebble layer configuration

        This method is required for subclassing PebbleServiceContainer
        """
        logger.info("PebbleServiceComponent.get_layer executing")
        return Layer(
            {
                "summary": "kfp-viewer layer",
                "description": "Pebble config layer for kfp-viewer",
                "services": {
                    self.service_name: {
                        "override": "replace",
                        "summary": "Entry point for kfp-viewer image",
                        "command": (
                            "/bin/controller"
                            " -logtostderr=true"
                            f" -max_num_viewers={self.environment['MAX_NUM_VIEWERS']}"
                            f" --namespace={self.environment['MINIO_NAMESPACE']}"
                        ),
                        "startup": "enabled",
                        "environment": self.environment,
                    }
                },
            }
        )
