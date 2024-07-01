# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.
import logging

from charmed_kubeflow_chisme.components.pebble_component import PebbleServiceComponent
from ops.pebble import Layer

logger = logging.getLogger(__name__)


class KfpSchedwfPebbleService(PebbleServiceComponent):
    def __init__(
        self,
        *args,
        timezone: str,
<<<<<<< HEAD
        namespace: str,
=======
        log_level: str,
>>>>>>> 915111a (Remove the namespace field in the pebble class)
        **kwargs,
    ):
        """Pebble service container component in order to configure Pebble layer"""
        super().__init__(*args, **kwargs)
<<<<<<< HEAD
        self.environment = {"CRON_SCHEDULE_TIMEZONE": timezone}
=======
        self.environment = {
            "CRON_SCHEDULE_TIMEZONE": timezone,
            "LOG_LEVEL": log_level,
            "NAMESPACE": "",
        }
<<<<<<< HEAD
>>>>>>> b94f628 (Change namespace in kfp-schedwf)
        self.namespace = namespace
=======
>>>>>>> 915111a (Remove the namespace field in the pebble class)

    def get_layer(self) -> Layer:
        """Defines and returns Pebble layer configuration

        This method is required for subclassing PebbleServiceContainer
        """
        logger.info("PebbleServiceComponent.get_layer executing")
        # NOTE: to check exactly how we are supposed to re-use rocks' predefined
        # pebble services, this could work, but I have to check if there are no
        # other edge cases were the layer is defined somewhere else and it is
        # merged wrongly.
        # Just merge with the rock pre-defined pebble service
        return Layer(
            {
                "summary": "kfp-schedwf layer",
                "description": "Pebble config layer for kfp-schedwf",
                "services": {
                    self.service_name: {
                        "override": "replace",
                        "summary": "scheduled workflow controller service",
                        "startup": "enabled",
                        "command": "/bin/controller --logtostderr=true"
                        ' --namespace=""',
                        "environment": self.environment,
                    }
                },
            }
        )
