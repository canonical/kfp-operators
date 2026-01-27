# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.
import dataclasses
import logging

from charmed_kubeflow_chisme.components.pebble_component import PebbleServiceComponent
from ops.pebble import Layer

logger = logging.getLogger(__name__)


@dataclasses.dataclass
class KfpSchedwfPebbleServiceComponentInputs:
    """Defines the required inputs for the Pebble Component."""

    KFP_API_SERVICE: str
    KFP_API_GRPC_PORT: int


class KfpSchedwfPebbleService(PebbleServiceComponent):
    def __init__(
        self,
        *args,
        timezone: str,
        log_level: str,
        **kwargs,
    ):
        """Pebble service container component in order to configure Pebble layer"""
        super().__init__(*args, **kwargs)
        self.environment = {
            "CRON_SCHEDULE_TIMEZONE": timezone,
            "LOG_LEVEL": log_level,
            "NAMESPACE:": "",
        }
        self.log_level = log_level

    def get_layer(self) -> Layer:
        """Defines and returns Pebble layer configuration

        This method is required for subclassing PebbleServiceContainer
        """
        logger.info("PebbleServiceComponent.get_layer executing")

        try:
            inputs: KfpSchedwfPebbleServiceComponentInputs = self._inputs_getter()
        except Exception as err:
            raise ValueError(f"{self.name}: inputs are not correctly provided") from err

        # NOTE: to check exactly how we are supposed to reuse rocks' predefined
        # pebble services, this could work, but I have to check if there are no
        # other edge cases were the layer is defined somewhere else and it is
        # merged wrongly.
        # Just merge with the rock pre-defined pebble service
        layer_dict = {
            "summary": "kfp-schedwf layer",
            "description": "Pebble config layer for kfp-schedwf",
            "services": {
                self.service_name: {
                    "override": "replace",
                    "summary": "scheduled workflow controller service",
                    "startup": "enabled",
                    "command": "/bin/controller --logtostderr=true "
                    '--namespace="" '
                    f"--logLevel={self.log_level} "
                    f"--mlPipelineAPIServerName={inputs.KFP_API_SERVICE} "
                    f"--mlPipelineServiceGRPCPort={inputs.KFP_API_GRPC_PORT}",
                    "environment": self.environment,
                }
            },
        }

        return Layer(layer_dict)
