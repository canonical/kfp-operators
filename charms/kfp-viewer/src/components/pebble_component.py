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
        super().__init__(*args, **kwargs)
        self.environment = environment
        self.max_num_viewers = environment["MAX_NUM_VIEWERS"]
        self.namespace = environment["MINIO_NAMESPACE"]

    def get_layer(self) -> Layer:
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
                            f" -max_num_viewers={self.max_num_viewers}"
                            f" --namespace={self.namespace}"
                        ),
                        "startup": "enabled",
                        "environment": self.environment,
                    }
                },
            }
        )
