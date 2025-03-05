import dataclasses
import logging

from charmed_kubeflow_chisme.components.pebble_component import PebbleServiceComponent
from ops.pebble import Layer

logger = logging.getLogger(__name__)


@dataclasses.dataclass
class MlPipelineUiInputs:
    """Defines the required inputs for MlPipelineUiPebbleService."""

    ALLOW_CUSTOM_VISUALIZATIONS: bool
    ARGO_ARCHIVE_LOGS: bool
    DISABLE_GKE_METADATA: bool
    FRONTEND_SERVER_NAMESPACE: str
    HIDE_SIDENAV: bool
    MINIO_ACCESS_KEY: str
    MINIO_SECRET_KEY: str
    MINIO_HOST: str
    MINIO_NAMESPACE: str
    MINIO_PORT: str
    MINIO_SSL: str
    ML_PIPELINE_SERVICE_HOST: str
    ML_PIPELINE_SERVICE_PORT: str


class MlPipelineUiPebbleService(PebbleServiceComponent):
    def get_layer(self) -> Layer:
        """Pebble configuration layer for ml-pipeline-ui."""
        try:
            inputs: MlPipelineUiInputs = self._inputs_getter()
        except Exception as err:
            raise ValueError("Failed to get inputs for Pebble container.") from err
        layer = Layer(
            {
                "services": {
                    # TODO: should this be an attribute?  Or handled somehow else?
                    self.service_name: {
                        "override": "replace",
                        "summary": "entry point for ml-pipeline-ui",
                        # command should be updated each time we switch from upstream image to rock
                        #  - upsstream: "command": "node dist/server.js ../client/ 3000"
                        #  - rock: "command": "node /server/dist/server.js /client/ 3000"
                        "command": "node /server/dist/server.js /client/ 3000",
                        "startup": "enabled",
                        "user": "_daemon_",  # This is needed only for rocks
                        # TODO: are these still the correct settings?
                        "environment": {
                            "ALLOW_CUSTOM_VISUALIZATIONS": str(
                                inputs.ALLOW_CUSTOM_VISUALIZATIONS
                            ).lower(),
                            "ARGO_ARCHIVE_ARTIFACTORY": "minio",
                            "ARGO_ARCHIVE_BUCKETNAME": "mlpipeline",
                            "ARGO_ARCHIVE_LOGS": inputs.ARGO_ARCHIVE_LOGS,
                            # Must have the same value as the `keyFormat` specified in the
                            # `argo-workflow-controller-configmap` ConfigMap owned by
                            # the `argo-controller` charm.
                            "ARGO_KEYFORMAT": (
                                "artifacts/{{workflow.name}}/"
                                "{{workflow.creationTimestamp.Y}}/"
                                "{{workflow.creationTimestamp.m}}/"
                                "{{workflow.creationTimestamp.d}}/"
                                "{{pod.name}}"
                            ),
                            # TODO: This should come from relation to kfp-profile-controller.
                            #  It is the name/port of the user-specific artifact accessor
                            "ARTIFACTS_SERVICE_PROXY_NAME": "ml-pipeline-ui-artifact",
                            "ARTIFACTS_SERVICE_PROXY_PORT": "80",
                            "ARTIFACTS_SERVICE_PROXY_ENABLED": "true",
                            "AWS_ACCESS_KEY_ID": "",
                            "AWS_SECRET_ACCESS_KEY": "",
                            "DISABLE_GKE_METADATA": inputs.DISABLE_GKE_METADATA,
                            "ENABLE_AUTHZ": "true",
                            "DEPLOYMENT": "KUBEFLOW",
                            "FRONTEND_SERVER_NAMESPACE": inputs.FRONTEND_SERVER_NAMESPACE,
                            "HIDE_SIDENAV": str(inputs.HIDE_SIDENAV).lower(),
                            "HTTP_AUTHORIZATION_DEFAULT_VALUE": "",
                            "HTTP_AUTHORIZATION_KEY": "",
                            "HTTP_BASE_URL": "",
                            "KUBEFLOW_USERID_HEADER": "kubeflow-userid",
                            "KUBEFLOW_USERID_PREFIX": "",
                            "METADATA_ENVOY_SERVICE_SERVICE_HOST": "localhost",
                            "METADATA_ENVOY_SERVICE_SERVICE_PORT": "9090",
                            "MINIO_ACCESS_KEY": f"{inputs.MINIO_ACCESS_KEY}",
                            "MINIO_SECRET_KEY": inputs.MINIO_SECRET_KEY,
                            "MINIO_HOST": inputs.MINIO_HOST,
                            "MINIO_NAMESPACE": inputs.MINIO_NAMESPACE,
                            "MINIO_PORT": inputs.MINIO_PORT,
                            "MINIO_SSL": inputs.MINIO_SSL,
                            "ML_PIPELINE_SERVICE_HOST": inputs.ML_PIPELINE_SERVICE_HOST,
                            "ML_PIPELINE_SERVICE_PORT": inputs.ML_PIPELINE_SERVICE_PORT,
                            "STREAM_LOGS_FROM_SERVER_API": "false",
                            # TODO: Think there's a file here we should copy in.  Workload's logs
                            #  show an error on start for this
                            "VIEWER_TENSORBOARD_POD_TEMPLATE_SPEC_PATH": (
                                "/etc/config/viewer-pod-template.json"
                            ),
                            "VIEWER_TENSORBOARD_TF_IMAGE_NAME": "tensorflow/tensorflow",
                        },
                    }
                },
                # TODO: Checks
                # "checks": {
                #     "kubeflow-profiles-get": {
                #         "override": "replace",
                #         "period": "30s",
                #         "http": {"url": "http://localhost:8080/metrics"},
                #     }
                # },
            }
        )

        logger.debug("computed layer as:")
        logger.debug(layer.to_dict())

        return layer
