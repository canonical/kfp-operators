import dataclasses
import logging

from charmed_kubeflow_chisme.components.pebble_component import PebbleServiceComponent
from ops.pebble import Layer

logger = logging.getLogger(__name__)


@dataclasses.dataclass
class KfpProfileControllerInputs:
    """Defines the required inputs for KfpProfileControllerPebbleService."""

    MINIO_SECRET: str
    MINIO_HOST: str
    MINIO_NAMESPACE: str
    MINIO_PORT: str
    MINIO_ACCESS_KEY: str
    MINIO_SECRET_KEY: str
    KFP_VERSION: str
    KFP_DEFAULT_PIPELINE_ROOT: str
    DISABLE_ISTIO_SIDECAR: str
    CONTROLLER_PORT: int
    METADATA_GRPC_SERVICE_HOST: str
    METADATA_GRPC_SERVICE_PORT: str


class KfpProfileControllerPebbleService(PebbleServiceComponent):
    def get_layer(self) -> Layer:
        """Pebble configuration layer for kfp-profile-controller."""
        # TODO: Make this built-in, use the service/container names
        logger.info("MlPipelineUiPebbleService.get_layer executing")
        inputs: KfpProfileControllerInputs = self._inputs_getter()
        layer = Layer(
            {
                "services": {
                    # TODO: should this be an attribute?  Or handled somehow else?
                    self.service_name: {
                        "override": "replace",
                        "summary": "entry point for kfp-profile-controller",
                        "command": "python /hooks/sync.py",  # Must be a string
                        "startup": "enabled",
                        "environment": {
                            "minio-secret": inputs.MINIO_SECRET,
                            "MINIO_HOST": inputs.MINIO_HOST,
                            "MINIO_PORT": inputs.MINIO_PORT,
                            "MINIO_NAMESPACE": inputs.MINIO_NAMESPACE,
                            "MINIO_ACCESS_KEY": f"{inputs.MINIO_ACCESS_KEY}",
                            "MINIO_SECRET_KEY": inputs.MINIO_SECRET_KEY,
                            "KFP_VERSION": inputs.KFP_VERSION,
                            "KFP_DEFAULT_PIPELINE_ROOT": inputs.KFP_DEFAULT_PIPELINE_ROOT,
                            "DISABLE_ISTIO_SIDECAR": inputs.DISABLE_ISTIO_SIDECAR,
                            "CONTROLLER_PORT": inputs.CONTROLLER_PORT,
                            "METADATA_GRPC_SERVICE_HOST": inputs.METADATA_GRPC_SERVICE_HOST,
                            "METADATA_GRPC_SERVICE_PORT": inputs.METADATA_GRPC_SERVICE_PORT,
                        },
                    }
                }
            }
        )

        logger.debug("Computed layer as:")
        logger.debug(layer.to_dict())

        return layer
