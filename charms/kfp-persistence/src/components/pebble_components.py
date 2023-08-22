import dataclasses
import logging
from typing import Dict

from charmed_kubeflow_chisme.components.pebble_component import PebbleServiceComponent
from ops import StatusBase, WaitingStatus
from ops.pebble import Layer

logger = logging.getLogger(__name__)


@dataclasses.dataclass
class PesistenceAgentServiceConfig:
    """Defines configuration for PersistenceAgent Service."""

    KFP_API_SERVICE_NAME: str
    NAMESPACE: str


class PersistenceAgentPebbleService(PebbleServiceComponent):
    """Pebble Service for Persistence Agent Container."""

    def __init__(
        self,
        *args,
        environment: Dict[str, str],
        **kwargs,
    ):
        """Initialize component."""
        super().__init__(*args, **kwargs)
        self._environment = environment

    def get_layer(self) -> Layer:
        """Pebble configuration layer for persistenceagent.

        This method is required for subclassing PebbleServiceComponent
        """
        logger.info(f"{self.name}: create layer")

        # retrieve up-to-date service configuration as setup by charm
        try:
            service_config: PesistenceAgentServiceConfig = self._inputs_getter()
        except Exception as err:
            raise ValueError(f"{self.name}: configuration is not provided") from err

        if len(service_config.KFP_API_SERVICE_NAME) == 0 or len(service_config.NAMESPACE) == 0:
            logger.info(f"{self.name}: configuration is not valid")
            return None

        # setup command with parameters provided in configuration
        command = (
            "persistence_agent",
            "--logtostderr=true",
            f"--namespace={service_config.NAMESPACE}",
            "--ttlSecondsAfterWorkflowFinish=86400",
            "--numWorker=2",
            f"--mlPipelineAPIServerName={service_config.KFP_API_SERVICE_NAME}",
        )

        # generate and return layer
        return Layer(
            {
                "services": {
                    self.service_name: {
                        "override": "replace",
                        "summary": "persistenceagent service",
                        "command": " ".join(command),
                        "startup": "enabled",
                        "environment": self._environment,
                    }
                },
                "checks": {
                    "persistenceagent-get": {
                        "override": "replace",
                        "period": "30s",
                        "http": {"url": "http://localhost:8080/metrics"},
                    }
                },
            }
        )

    def get_status(self) -> StatusBase:
        """Return status."""
        # validate configuration availability
        try:
            service_config: PesistenceAgentServiceConfig = self._inputs_getter()
        except Exception as err:
            return WaitingStatus(f"Configuration is not provided: {err}")

        # validate values
        if len(service_config.KFP_API_SERVICE_NAME) == 0 or len(service_config.NAMESPACE) == 0:
            return WaitingStatus("Configuration is not valid")

        return super().get_status()
