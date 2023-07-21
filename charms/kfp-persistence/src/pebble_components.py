import logging
import dataclasses
from ops.pebble import Layer
from typing import Dict
from charmed_kubeflow_chisme.components.pebble_component import PebbleServiceComponent


logger = logging.getLogger(__name__)

@dataclasses.dataclass
class PesistenceAgentServiceConfig:
    """Defines configuration for PersistenceAgent Service."""
    KFP_API_SERVICE_NAME: str

class PersistenceAgentContainer(PebbleServiceComponent):
    # TODO: Should this be something we subclass to define settings, or should PebbleServiceComponent just have
    #  .add_service, .add_check, etc?
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
        """Pebble configuration layer for kubeflow-profiles.

        This method is required for subclassing PebbleServiceComponent
        """
        logger.info("PersistenceAgentContainer.get_layer executing")

        # retrieve up-to-date service configuration as setup by charm
        service_config: PesistenceAgentServiceConfig = self._get_service_config()

        if len(service_config.KFP_API_SERVICE_NAME) == 0:
            logger.info("kfp-api-service-name is not available.")
            return None

        logger.info(f"PersistenceAgentContainer.get_layer: service name: {service_config.KFP_API_SERVICE_NAME}")

        return Layer({
            "services": {
                # TODO: should this be an attribute?  Or handled somehow else?
                self.service_name: {
                    "override": "replace",
                    "summary": "persistenceagent service",
                    "command": (
                        "persistence_agent",
                        "--logtostderr=true",
                        "--namespace=",
                        "--ttlSecondsAfterWorkflowFinish=86400",
                        "--numWorker=2",
                        f"--mlPipelineAPIServerName={service_config.KFP_API_SERVICE_NAME}",
                    ),
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
        })
