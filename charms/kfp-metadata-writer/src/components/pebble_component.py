# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.
import dataclasses
import logging

from charmed_kubeflow_chisme.components.pebble_component import PebbleServiceComponent
from ops.pebble import Layer

logger = logging.getLogger(__name__)


@dataclasses.dataclass
class KfpMetadataWriterInputs:
    """Defines the required inputs for KfpMetadataWriterInputs."""

    METADATA_GRPC_SERVICE_SERVICE_HOST: str
    METADATA_GRPC_SERVICE_SERVICE_PORT: str


class KfpMetadataWriterPebbleService(PebbleServiceComponent):
    def __init__(
        self,
        *args,
        namespace_to_watch: str = "",
        **kwargs,
    ):
        """Pebble service container component in order to configure Pebble layer

        Args:
            namespace_to_watch (str): The namespace in which the metadata-writer workload
            will look for pods. Matching upstream manifests, this defaults to "" in order
            for the component to look for pods in all namespaces.
        """
        self.namespace_to_watch = namespace_to_watch
        super().__init__(*args, **kwargs)

    def get_layer(self) -> Layer:
        """Defines and returns Pebble layer configuration

        This method is required for subclassing PebbleServiceContainer
        """
        logger.info("PebbleServiceComponent.get_layer executing")

        try:
            inputs: KfpMetadataWriterInputs = self._inputs_getter()
        except Exception as err:
            raise ValueError("Failed to get inputs for Pebble container.") from err

        environment = {
            "NAMESPACE_TO_WATCH": self.namespace_to_watch,
            "METADATA_GRPC_SERVICE_SERVICE_HOST": inputs.METADATA_GRPC_SERVICE_SERVICE_HOST,
            "METADATA_GRPC_SERVICE_SERVICE_PORT": inputs.METADATA_GRPC_SERVICE_SERVICE_PORT,
        }

        layer_dict = {
            "summary": "kfp-metadata-writer layer",
            "description": "Pebble config layer for kfp-metadata-writer",
            "services": {
                self.service_name: {
                    "override": "replace",
                    "summary": "Entry point for kfp-metadata-writer oci-image",
                    "command": "python3 -u /kfp/metadata_writer/metadata_writer.py",
                    "startup": "enabled",
                    "environment": environment,
                }
            },
        }

        return Layer(layer_dict)
