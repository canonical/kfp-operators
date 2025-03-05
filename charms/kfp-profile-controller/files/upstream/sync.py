# Source: manifests/apps/pipeline/upstream/base/installs/multi-user/pipelines-profile-controller/sync.py
# Note for Charmed Kubeflow developers: Because this file is a lightly modified version of an
#   upstream file, we only make changes to it that are functionally required.  As much as possible,
#   we keep the file comparable to upstream so it can easily be diffed.  In particular, keep the
#   formatting as is even though it does not meet our own style configurations.
# Copyright 2020-2021 The Kubeflow Authors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
import base64
import logging

logger = logging.getLogger(__name__)


def main():
    logger.info("User profile sync service alive")
    settings = get_settings_from_env()
    emit_settings_to_logs(settings)
    server = server_factory(**settings)
    logger.info("Serving forever")
    server.serve_forever()


def emit_settings_to_logs(settings):
    """Emits settings to logs, omitting secrets"""
    safe_settings = dict(settings)
    for k in ["MINIO_SECRET_KEY"]:
        if k in safe_settings:
            safe_settings[k] = "REDACTED"
    logger.info(f"Settings = {safe_settings}")


def get_settings_from_env(controller_port=None,
                          visualization_server_image=None, frontend_image=None,
                          visualization_server_tag=None, frontend_tag=None, disable_istio_sidecar=None,
                          minio_access_key=None, minio_secret_key=None, kfp_default_pipeline_root=None,
                          minio_host=None, minio_port=None, minio_namespace=None,
                          metadata_grpc_service_host=None,
                          metadata_grpc_service_port=None):
    """
    Returns a dict of settings from environment variables relevant to the controller

    Environment settings can be overridden by passing them here as arguments.

    Settings are pulled from the all-caps version of the setting name.  The
    following defaults are used if those environment variables are not set
    to enable backwards compatibility with previous versions of this script:
        visualization_server_image: ghcr.io/kubeflow/kfp-visualization-server
        visualization_server_tag: value of KFP_VERSION environment variable
        frontend_image: ghcr.io/kubeflow/kfp-frontend
        frontend_tag: value of KFP_VERSION environment variable
        disable_istio_sidecar: Required (no default)
        minio_access_key: Required (no default)
        minio_secret_key: Required (no default)
        minio_host: minio
        minio_port: 9000
        minio_namespace: kubeflow
        metadata_grpc_service_host: metadata-grpc-service.kubeflow
        metadata_grpc_service_port: 8080
    """
    settings = dict()
    settings["controller_port"] = \
        controller_port or \
        os.environ.get("CONTROLLER_PORT", "8080")

    settings["visualization_server_image"] = \
        visualization_server_image or \
        os.environ.get("VISUALIZATION_SERVER_IMAGE", "ghcr.io/kubeflow/kfp-visualization-server")

    settings["frontend_image"] = \
        frontend_image or \
        os.environ.get("FRONTEND_IMAGE", "ghcr.io/kubeflow/kfp-frontend")

    # Look for specific tags for each image first, falling back to
    # previously used KFP_VERSION environment variable for backwards
    # compatibility
    settings["visualization_server_tag"] = \
        visualization_server_tag or \
        os.environ.get("VISUALIZATION_SERVER_TAG") or \
        os.environ["KFP_VERSION"]

    settings["frontend_tag"] = \
        frontend_tag or \
        os.environ.get("FRONTEND_TAG") or \
        os.environ["KFP_VERSION"]

    settings["disable_istio_sidecar"] = \
        disable_istio_sidecar if disable_istio_sidecar is not None \
            else os.environ.get("DISABLE_ISTIO_SIDECAR") == "true"

    settings["minio_access_key"] = \
        minio_access_key or \
        base64.b64encode(bytes(os.environ.get("MINIO_ACCESS_KEY"), 'utf-8')).decode('utf-8')

    settings["minio_secret_key"] = \
        minio_secret_key or \
        base64.b64encode(bytes(os.environ.get("MINIO_SECRET_KEY"), 'utf-8')).decode('utf-8')

    settings["minio_host"] = \
        minio_host or \
        os.environ.get("MINIO_HOST", "minio")

    settings["minio_port"] = \
        minio_port or \
        os.environ.get("MINIO_PORT", "9000")

    settings["minio_namespace"] = \
        minio_namespace or \
        os.environ.get("MINIO_NAMESPACE", "kubeflow")

    # KFP_DEFAULT_PIPELINE_ROOT is optional
    settings["kfp_default_pipeline_root"] = \
        kfp_default_pipeline_root or \
        os.environ.get("KFP_DEFAULT_PIPELINE_ROOT")

    settings["metadata_grpc_service_host"] = \
        metadata_grpc_service_host or \
        os.environ.get("METADATA_GRPC_SERVICE_HOST", "metadata-grpc-service.kubeflow")

    settings["metadata_grpc_service_port"] = \
        metadata_grpc_service_port or \
        os.environ.get("METADATA_GRPC_SERVICE_PORT", "8080")

    return settings


def server_factory(visualization_server_image,
                   visualization_server_tag, frontend_image, frontend_tag,
                   disable_istio_sidecar, minio_access_key,
                   minio_secret_key, minio_host, minio_namespace, minio_port,
                   metadata_grpc_service_host, metadata_grpc_service_port,
                   kfp_default_pipeline_root=None, url="", controller_port=8080):
    """
    Returns an HTTPServer populated with Handler with customized settings
    """
    class Controller(BaseHTTPRequestHandler):
        def sync(self, parent, attachments):
            logger.info("Got new request")

            # parent is a namespace
            namespace = parent.get("metadata", {}).get("name")

            pipeline_enabled = parent.get("metadata", {}).get(
                "labels", {}).get("pipelines.kubeflow.org/enabled")

            if pipeline_enabled != "true":
                logger.info(f"Namespace not in scope, no action taken (metadata.labels.pipelines.kubeflow.org/enabled = {pipeline_enabled}, must be 'true')")
                return {"status": {}, "attachments": []}

            desired_configmap_count = 1
            desired_resources = []
            if kfp_default_pipeline_root:
                desired_configmap_count = 2
                desired_resources += [{
                    "apiVersion": "v1",
                    "kind": "ConfigMap",
                    "metadata": {
                        "name": "kfp-launcher",
                        "namespace": namespace,
                    },
                    "data": {
                        "defaultPipelineRoot": kfp_default_pipeline_root,
                    },
                }]


            # Compute status based on observed state.
            desired_status = {
                "kubeflow-pipelines-ready":
                    len(attachments["Secret.v1"]) == 1 and
                    len(attachments["ConfigMap.v1"]) == desired_configmap_count and
                    len(attachments["Deployment.apps/v1"]) == 2 and
                    len(attachments["Service.v1"]) == 2 and
                    # TODO CANONICAL: This only works if istio is available.  Disabled for now
                    # len(attachments["DestinationRule.networking.istio.io/v1alpha3"]) == 1 and
                    # len(attachments["AuthorizationPolicy.security.istio.io/v1beta1"]) == 1 and
                    "True" or "False"
            }

            # Generate the desired attachment object(s).
            desired_resources += [
                {
                    "apiVersion": "v1",
                    "kind": "ConfigMap",
                    "metadata": {
                        "name": "metadata-grpc-configmap",
                        "namespace": namespace,
                    },
                    "data": {
                        "METADATA_GRPC_SERVICE_HOST": metadata_grpc_service_host,
                        "METADATA_GRPC_SERVICE_PORT": metadata_grpc_service_port,
                    },
                },
                # Visualization server related manifests below
                {
                    "apiVersion": "apps/v1",
                    "kind": "Deployment",
                    "metadata": {
                        "labels": {
                            "app": "ml-pipeline-visualizationserver"
                        },
                        "name": "ml-pipeline-visualizationserver",
                        "namespace": namespace,
                    },
                    "spec": {
                        "selector": {
                            "matchLabels": {
                                "app": "ml-pipeline-visualizationserver"
                            },
                        },
                        "template": {
                            "metadata": {
                                "labels": {
                                    "app": "ml-pipeline-visualizationserver"
                                },
                                "annotations": disable_istio_sidecar and {
                                    "sidecar.istio.io/inject": "false"
                                } or {},
                            },
                            "spec": {
                                "containers": [{
                                    "image": f"{visualization_server_image}:{visualization_server_tag}",
                                    "imagePullPolicy":
                                        "IfNotPresent",
                                    "name":
                                        "ml-pipeline-visualizationserver",
                                    "ports": [{
                                        "containerPort": 8888
                                    }],
                                    "resources": {
                                        "requests": {
                                            "cpu": "50m",
                                            "memory": "200Mi"
                                        },
                                        "limits": {
                                            "cpu": "500m",
                                            "memory": "1Gi"
                                        },
                                    }
                                }],
                                "serviceAccountName":
                                    "default-editor",
                            },
                        },
                    },
                },
                # TODO CANONICAL: This only works if istio is available.  Disabled for now
                # {
                #     "apiVersion": "networking.istio.io/v1alpha3",
                #     "kind": "DestinationRule",
                #     "metadata": {
                #         "name": "ml-pipeline-visualizationserver",
                #         "namespace": namespace,
                #     },
                #     "spec": {
                #         "host": "ml-pipeline-visualizationserver",
                #         "trafficPolicy": {
                #             "tls": {
                #                 "mode": "ISTIO_MUTUAL"
                #             }
                #         }
                #     }
                # },
                # {
                #     "apiVersion": "security.istio.io/v1beta1",
                #     "kind": "AuthorizationPolicy",
                #     "metadata": {
                #         "name": "ml-pipeline-visualizationserver",
                #         "namespace": namespace,
                #     },
                #     "spec": {
                #         "selector": {
                #             "matchLabels": {
                #                 "app": "ml-pipeline-visualizationserver"
                #             }
                #         },
                #         "rules": [{
                #             "from": [{
                #                 "source": {
                #                     "principals": ["cluster.local/ns/kubeflow/sa/ml-pipeline"]
                #                 }
                #             }]
                #         }]
                #     }
                # },
                {
                    "apiVersion": "v1",
                    "kind": "Service",
                    "metadata": {
                        "name": "ml-pipeline-visualizationserver",
                        "namespace": namespace,
                    },
                    "spec": {
                        "ports": [{
                            "name": "http",
                            "port": 8888,
                            "protocol": "TCP",
                            "targetPort": 8888,
                        }],
                        "selector": {
                            "app": "ml-pipeline-visualizationserver",
                        },
                    },
                },
                # Artifact fetcher related resources below.
                {
                    "apiVersion": "apps/v1",
                    "kind": "Deployment",
                    "metadata": {
                        "labels": {
                            "app": "ml-pipeline-ui-artifact"
                        },
                        "name": "ml-pipeline-ui-artifact",
                        "namespace": namespace,
                    },
                    "spec": {
                        "selector": {
                            "matchLabels": {
                                "app": "ml-pipeline-ui-artifact"
                            }
                        },
                        "template": {
                            "metadata": {
                                "labels": {
                                    "app": "ml-pipeline-ui-artifact"
                                },
                                "annotations": disable_istio_sidecar and {
                                    "sidecar.istio.io/inject": "false"
                                } or {},
                            },
                            "spec": {
                                "containers": [{
                                    "name":
                                        "ml-pipeline-ui-artifact",
                                    "image": f"{frontend_image}:{frontend_tag}",
                                    "imagePullPolicy":
                                        "IfNotPresent",
                                    "ports": [{
                                        "containerPort": 3000
                                    }],
                                    "env": [
                                        {'name': "MINIO_PORT", 'value': minio_port},
                                        {'name': "MINIO_HOST", 'value': minio_host},
                                        {'name': "MINIO_NAMESPACE", 'value': minio_namespace},
                                        {
                                            "name": "MINIO_ACCESS_KEY",
                                            "valueFrom": {
                                                "secretKeyRef": {
                                                    "key": "accesskey",
                                                    "name": "mlpipeline-minio-artifact"
                                                }
                                            }
                                        },
                                        {
                                            "name": "MINIO_SECRET_KEY",
                                            "valueFrom": {
                                                "secretKeyRef": {
                                                    "key": "secretkey",
                                                    "name": "mlpipeline-minio-artifact"
                                                }
                                            }
                                        }
                                    ],
                                    "resources": {
                                        "requests": {
                                            "cpu": "10m",
                                            "memory": "70Mi"
                                        },
                                        "limits": {
                                            "cpu": "100m",
                                            "memory": "500Mi"
                                        },
                                    }
                                }],
                                "serviceAccountName":
                                    "default-editor"
                            }
                        }
                    }
                },
                # Added from https://github.com/kubeflow/pipelines/pull/6629 to fix
                # https://github.com/canonical/bundle-kubeflow/issues/423.  This was not yet in
                # upstream and if they go with something different we should consider syncing with
                # upstream.
                # Adds "Allow access to Kubeflow Pipelines" button in Notebook spawner UI
                {
                    "apiVersion": "kubeflow.org/v1alpha1",
                    "kind": "PodDefault",
                    "metadata": {
                        "name": "access-ml-pipeline",
                        "namespace": namespace
                    },
                    "spec": {
                        "desc": "Allow access to Kubeflow Pipelines",
                        "selector": {
                            "matchLabels": {
                                "access-ml-pipeline": "true"
                            }
                        },
                        "volumes": [
                            {
                                "name": "volume-kf-pipeline-token",
                                "projected": {
                                    "sources": [
                                        {
                                            "serviceAccountToken": {
                                                "path": "token",
                                                "expirationSeconds": 7200,
                                                "audience": "pipelines.kubeflow.org"
                                            }
                                        }
                                    ]
                                }
                            }
                        ],
                        "volumeMounts": [
                            {
                                "mountPath": "/var/run/secrets/kubeflow/pipelines",
                                "name": "volume-kf-pipeline-token",
                                "readOnly": True
                            }
                        ],
                        "env": [
                            {
                                "name": "KF_PIPELINES_SA_TOKEN_PATH",
                                "value": "/var/run/secrets/kubeflow/pipelines/token"
                            }
                        ]
                    }
                },
                {
                    "apiVersion": "v1",
                    "kind": "Service",
                    "metadata": {
                        "name": "ml-pipeline-ui-artifact",
                        "namespace": namespace,
                        "labels": {
                            "app": "ml-pipeline-ui-artifact"
                        }
                    },
                    "spec": {
                        "ports": [{
                            "name":
                                "http",  # name is required to let istio understand request protocol
                            "port": 80,
                            "protocol": "TCP",
                            "targetPort": 3000
                        }],
                        "selector": {
                            "app": "ml-pipeline-ui-artifact"
                        }
                    }
                },
                # This AuthorizationPolicy was added from https://github.com/canonical/kfp-operators/pull/356
                # to fix https://github.com/canonical/notebook-operators/issues/311
                # and https://github.com/canonical/kfp-operators/issues/355.
                # Remove when istio sidecars are implemented.
                {
                    "apiVersion": "security.istio.io/v1beta1",
                    "kind": "AuthorizationPolicy",
                    "metadata": {"name": "ns-owner-access-istio-charmed", "namespace": namespace},
                    "spec": {
                        "rules": [
                            {
                                "when": [
                                    {"key": "request.headers[kubeflow-userid]", "values": ["*"]}
                                ]
                            },
                            {
                                "to": [
                                    {"operation": {"methods": ["GET"], "paths": ["*/api/kernels"]}}
                                ]
                            },
                        ]
                    },
                },
            ]
            print('Received request:\n', json.dumps(parent, indent=2, sort_keys=True))
            print('Desired resources except secrets:\n', json.dumps(desired_resources, indent=2, sort_keys=True))
            # Moved after the print argument because this is sensitive data.
            desired_resources.append({
                "apiVersion": "v1",
                "kind": "Secret",
                "metadata": {
                    "name": "mlpipeline-minio-artifact",
                    "namespace": namespace,
                },
                "data": {
                    "accesskey": minio_access_key,
                    "secretkey": minio_secret_key,
                },
            })

            return {"status": desired_status, "attachments": desired_resources}

        def do_POST(self):
            # Serve the sync() function as a JSON webhook.
            observed = json.loads(
                self.rfile.read(int(self.headers.get("content-length"))))
            logger.info(f"Request is  {observed}")
            desired = self.sync(observed["object"], observed["attachments"])

            self.send_response(200)
            self.send_header("Content-type", "application/json")
            self.end_headers()
            self.wfile.write(bytes(json.dumps(desired), 'utf-8'))

    return HTTPServer((url, int(controller_port)), Controller)


if __name__ == "__main__":
    main()
