# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

import dataclasses
import logging

from charmed_kubeflow_chisme.components.pebble_component import PebbleServiceComponent
from ops.pebble import Layer

logger = logging.getLogger(__name__)


@dataclasses.dataclass
class KfpVizInputs:
    """Defines the required inputs for KfpVizInputs."""

    USER: str


class KfpVizPebbleService(PebbleServiceComponent):
    def get_layer(self) -> Layer:
        """Pebble configuration layer for ml-pipeline-visualizationserver."""

        try:
            inputs: KfpVizInputs = self._inputs_getter()
        except Exception as err:
            raise ValueError("Failed to get inputs for Pebble container.") from err

        layer_dict = {
            "services": {
                self.service_name: {
                    "override": "replace",
                    "summary": "entry point for ml-pipeline-visualizationserver",
                    "command": "python3 server.py",  # Must be a string
                    "startup": "enabled",
                    "on-check-failure": {"kfp-viz-up": "restart"},
                }
            },
            "checks": {
                "kfp-viz-up": {
                    "override": "replace",
                    "period": "5m",
                    "timeout": "60s",
                    "threshold": 3,
                    "http": {"url": f"http://localhost:{self._charm.model.config['http-port']}"},
                }
            },
        }

        # Change the value of user in `service-config.yaml`:
        # - upstream: Leave string empty
        # - rock: _daemon_
        if inputs.USER:
            layer_dict["services"][self.service_name]["user"] = inputs.USER
        layer = Layer(layer_dict)

        return layer
