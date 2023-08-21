import logging

from charmed_kubeflow_chisme.components.pebble_component import PebbleServiceComponent
from ops.pebble import Layer

logger = logging.getLogger(__name__)


class KfpVizPebbleService(PebbleServiceComponent):
    def get_layer(self) -> Layer:
        """Pebble configuration layer for ml-pipeline-visualizationserver."""
        layer = Layer(
            {
                "services": {
                    self.service_name: {
                        "override": "replace",
                        "summary": "entry point for ml-pipeline-visualizationserver",
                        "command": "python3.6 server.py",  # Must be a string
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
                        "http": {
                            "url": f"http://localhost:{self.charm.model.config['http-port']}"
                        },
                    }
                },
            }
        )

        return layer
