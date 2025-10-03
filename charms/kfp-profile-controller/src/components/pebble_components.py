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
    VISUALIZATION_SERVER_IMAGE: str
    VISUALIZATION_SERVER_TAG: str
    FRONTEND_IMAGE: str
    FRONTEND_TAG: str


class KfpProfileControllerPebbleService(PebbleServiceComponent):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # NOTE: necessary for the (default) Pebble service to be updated on
        # charm configuration changes, as its environment depends on them:
        self._events_to_observe.append(getattr(self._charm.on, "config_changed"))

    def get_layer(self) -> Layer:
        try:
            inputs: KfpProfileControllerInputs = self._inputs_getter()
        except Exception as err:
            raise ValueError(f"{self.name}: inputs are not correctly provided") from err

        if (
            len(inputs.MINIO_SECRET_KEY) == 0
            or len(inputs.MINIO_ACCESS_KEY) == 0
            or len(inputs.MINIO_HOST) == 0
            or len(inputs.MINIO_NAMESPACE) == 0
        ):
            raise ValueError(f"{self.name}: inputs are not correctly provided")

        """Pebble configuration layer for kfp-profile-controller."""
        layer = Layer(
            {
                "services": {
                    self.service_name: {
                        "override": "replace",
                        "summary": "entry point for kfp-profile-controller",
                        "command": "python3 /hooks/sync.py",  # Must be a string
                        "startup": "enabled",
                        "environment": {
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
                            "VISUALIZATION_SERVER_IMAGE": inputs.VISUALIZATION_SERVER_IMAGE,
                            "VISUALIZATION_SERVER_TAG": inputs.VISUALIZATION_SERVER_TAG,
                            "FRONTEND_IMAGE": inputs.FRONTEND_IMAGE,
                            "FRONTEND_TAG": inputs.FRONTEND_TAG,
                        },
                    }
                }
            }
        )

        return layer
