import dataclasses
import logging
from typing import Dict

from charmed_kubeflow_chisme.components.pebble_component import PebbleServiceComponent
from ops.pebble import Layer

logger = logging.getLogger(__name__)


@dataclasses.dataclass
class PesistenceAgentServiceConfig:
    """Defines configuration for PersistenceAgent Service."""

    KFP_API_SERVICE_NAME: str
    NAMESPACE: str


class PersistenceAgentContainer(PebbleServiceComponent):
    # TODO: Should this be something we subclass to define settings, or should
    # PebbleServiceComponent just have .add_service, .add_check, etc?
    def __init__(
        self,
        *args,
        environment: Dict[str, str],
        service_config_getter,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self._get_service_config = service_config_getter
        self._environment = environment

    def get_layer(self) -> Layer:
        """Pebble configuration layer for persistenceagent.

        This method is required for subclassing PebbleServiceComponent
        """
        logger.info("PersistenceAgentContainer: create layer")

        # retrieve up-to-date service configuration as setup by charm
        service_config: PesistenceAgentServiceConfig = self._get_service_config()

        if len(service_config.KFP_API_SERVICE_NAME) == 0 or len(service_config.NAMESPACE) == 0:
            logger.info("PersistenceAgentContainer: configuration is not available")
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
