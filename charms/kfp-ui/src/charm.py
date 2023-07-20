#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Charm for the Kubeflow Pipelines UI.

https://github.com/canonical/kfp-operators
"""

import json
import logging
from base64 import b64encode
from pathlib import Path

import lightkube
from charmed_kubeflow_chisme.kubernetes import create_charm_default_labels
from charmed_kubeflow_chisme.components import CharmReconciler, KubernetesComponent, ContainerFileTemplate, LeadershipGateComponent
from charms.kubeflow_dashboard.v0.kubeflow_dashboard_links import (
    DashboardLink,
    KubeflowDashboardLinksRequirer,
)
from jsonschema import ValidationError
from lightkube.resources.rbac_authorization_v1 import ClusterRole, ClusterRoleBinding
from oci_image import OCIImageResource, OCIImageResourceError
from ops.charm import CharmBase
from ops.main import main
from ops.model import ActiveStatus, BlockedStatus, MaintenanceStatus, WaitingStatus
from pebble_components import MlPipelineUiInputs, MlPipelineUiPebbleService
from serialized_data_interface.errors import (
    NoCompatibleVersions,
    NoVersionsListed,
    RelationDataError,
)
from serialized_data_interface.sdi import SerializedDataInterface, get_interfaces

from relation_components import SdiRelationGetterComponent

TEMPLATES_PATH = Path("src/templates")
K8S_RESOURCE_FILES = [TEMPLATES_PATH / "auth_manifests.yaml.j2"]

CONFIG_JSON_TEMPLATE_FILE = TEMPLATES_PATH / "config.json"
CONFIG_JSON_DESTINATION_PATH = "/config/config.json"
VIEWER_POD_TEMPLATE_FILE = TEMPLATES_PATH / "viewer-pod-template.json"
VIEWER_JSON_DESTINATION_PATH = "/etc/config/viewer-pod-template.json"


class KfpUiOperator(CharmBase):
    """Charm for the Kubeflow Pipelines UI.

    https://github.com/canonical/kfp-operators
    """

    def __init__(self, *args):
        super().__init__(*args)

        self.log = logging.getLogger()
        self.image = OCIImageResource(self, "oci-image")

        # self.framework.observe(self.on.install, self._main)
        # self.framework.observe(self.on.upgrade_charm, self._main)
        # self.framework.observe(self.on.config_changed, self._main)
        # self.framework.observe(self.on["object-storage"].relation_changed, self._main)
        # self.framework.observe(self.on["kfp-api"].relation_changed, self._main)
        # self.framework.observe(self.on["ingress"].relation_changed, self._main)
        # self.framework.observe(self.on["kfp-ui"].relation_changed, self._main)
        # self.framework.observe(self.on.leader_elected, self._main)

        # add links in kubeflow-dashboard sidebar
        self.kubeflow_dashboard_sidebar = KubeflowDashboardLinksRequirer(
            charm=self,
            relation_name="dashboard-links",
            dashboard_links=[
                DashboardLink(
                    text="Experiments (KFP)",
                    link="/pipeline/#/experiments",
                    type="item",
                    icon="done-all",
                    location="menu",
                ),
                DashboardLink(
                    text="Pipelines",
                    link="/pipeline/#/pipelines",
                    type="item",
                    icon="kubeflow:pipeline-centered",
                    location="menu",
                ),
                DashboardLink(
                    text="Runs",
                    link="/pipeline/#/runs",
                    type="item",
                    icon="maps:directions-run",
                    location="menu",
                ),
                DashboardLink(
                    text="Recurring Runs",
                    link="/pipeline/#/recurringruns",
                    type="item",
                    icon="device:access-alarm",
                    location="menu",
                ),
                DashboardLink(
                    text="Upload a pipeline",
                    desc="Pipelines",
                    link="/pipeline/",
                    location="quick",
                ),
                DashboardLink(
                    text="View all pipeline runs",
                    desc="Pipelines",
                    link="/pipeline/#/runs",
                    location="quick",
                ),
            ],
        )

        # Charm logic
        self.charm_executor = CharmReconciler(self)

        self.leadership_gate_component_item = self.charm_executor.add(
            component=LeadershipGateComponent(
                charm=self,
                name="leadership-gate",
            ),
            depends_on=[]
        )

        self.kubernetes_resources_component_item = self.charm_executor.add(
            component=KubernetesComponent(
                charm=self,
                name="kubernetes:auth",
                resource_templates=K8S_RESOURCE_FILES,
                krh_resource_types={ClusterRole, ClusterRoleBinding},
                krh_labels=create_charm_default_labels(self.app.name, self.model.name, scope="auth-and-crds"),
                context_callable=lambda: {"app_name": self.app.name, "namespace": self.model.name},
                lightkube_client=lightkube.Client(),  # TODO: Make this easier to test on
            ),
            depends_on=[self.leadership_gate_component_item]
        )

        self.object_storage_relation_component = self.charm_executor.add(
            component=SdiRelationGetterComponent(
                charm=self,
                name="relation:object_storage",
                relation_name="object-storage",
            ),
            depends_on=[self.leadership_gate_component_item]
        )

        self.kfp_api_relation_component = self.charm_executor.add(
            component=SdiRelationGetterComponent(
                charm=self,
                name="relation:kfp-api",
                relation_name="kfp-api",
            ),
            depends_on=[self.leadership_gate_component_item]
        )

        self.ml_pipeline_ui_container = self.charm_executor.add(
            component=MlPipelineUiPebbleService(
                charm=self,
                name="container:ml-pipeline-ui",  # This feels a bit redundant, but will read
                container_name="ml-pipeline-ui",  # well in the statuses.  Thoughts?
                service_name="ml-pipeline-ui",
                files_to_push=[
                    ContainerFileTemplate(
                        source_template_path=CONFIG_JSON_TEMPLATE_FILE,
                        destination_path=CONFIG_JSON_DESTINATION_PATH,
                    ),
                    ContainerFileTemplate(
                        source_template_path=VIEWER_POD_TEMPLATE_FILE,
                        destination_path=VIEWER_JSON_DESTINATION_PATH,
                    )
                ],
                inputs_getter=lambda: MlPipelineUiInputs(
                    ALLOW_CUSTOM_VISUALIZATIONS=self.model.config["allow-custom-visualizations"],
                    HIDE_SIDENAV=self.model.config["hide-sidenav"],
                    # minio_secret={"secret": {"name": f"{self.app.name}-minio-secret"}},  # TODO: Is this required?
                    MINIO_HOST=self.object_storage_relation_component.component.get_data()["service"],  # os["service"],
                    MINIO_NAMESPACE=self.object_storage_relation_component.component.get_data()["namespace"],  # os["namespace"],
                    MINIO_PORT=self.object_storage_relation_component.component.get_data()["port"],  # os["port"],
                    MINIO_SSL=self.object_storage_relation_component.component.get_data()["secure"],  # os["secure"],
                    ML_PIPELINE_SERVICE_HOST=self.kfp_api_relation_component.component.get_data()["service-name"],  # kfp_api["service-name"],
                    ML_PIPELINE_SERVICE_PORT=self.kfp_api_relation_component.component.get_data()["service-port"],  # kfp_api["service-port"],
                ),
            ),
            # TODO: add relations
            depends_on=[self.leadership_gate_component_item, self.kubernetes_resources_component_item, self.object_storage_relation_component],
        )
        # TODO: Add object-storage relation
        # TODO: Add kfp-api relation
        # TODO: Add kfp-ui relation (send_ui_info)
        # TODO: Add ingress send_ingress_info (ingress)

        self.charm_executor.install(self)


    # def _main(self, event):
    #     try:
    #         self._check_leader()
    #         interfaces = self._get_interfaces()
    #         image_details = self.image.fetch()
    #         os = self._validate_sdi_interface(interfaces, "object-storage")
    #         kfp_api = self._validate_sdi_interface(interfaces, "kfp-api")
    #     except (CheckFailedError, OCIImageResourceError) as check_failed:
    #         self.model.unit.status = check_failed.status
    #         self.log.info(str(check_failed.status))
    #         return
    #
    #     self._send_ui_info(interfaces)
    #     self._send_ingress_info(interfaces)

        # config = self.model.config

        # healthz = f"http://localhost:{config['http-port']}/apis/v1beta1/healthz"
        # charm_name = self.model.app.name
        # env = {
        #     "ALLOW_CUSTOM_VISUALIZATIONS": str(config["allow-custom-visualizations"]).lower(),
        #     "ARGO_ARCHIVE_ARTIFACTORY": "minio",
        #     "ARGO_ARCHIVE_BUCKETNAME": "mlpipeline",
        #     "ARGO_ARCHIVE_LOGS": "false",
        #     "ARGO_ARCHIVE_PREFIX": "logs",
        #     # TODO: This should come from relation to kfp-profile-controller.  It is the name/port
        #     #  of the user-specific artifact accessor
        #     "ARTIFACTS_SERVICE_PROXY_NAME": "ml-pipeline-ui-artifact",
        #     "ARTIFACTS_SERVICE_PROXY_PORT": "80",
        #     "ARTIFACTS_SERVICE_PROXY_ENABLED": "true",
        #     "AWS_ACCESS_KEY_ID": "",
        #     "AWS_SECRET_ACCESS_KEY": "",
        #     "DISABLE_GKE_METADATA": "false",
        #     "ENABLE_AUTHZ": "true",
        #     "DEPLOYMENT": "KUBEFLOW",
        #     "HIDE_SIDENAV": str(config["hide-sidenav"]).lower(),
        #     "HTTP_AUTHORIZATION_DEFAULT_VALUE": "",
        #     "HTTP_AUTHORIZATION_KEY": "",
        #     "HTTP_BASE_URL": "",
        #     "KUBEFLOW_USERID_HEADER": "kubeflow-userid",
        #     "KUBEFLOW_USERID_PREFIX": "",
        #     "METADATA_ENVOY_SERVICE_SERVICE_HOST": "localhost",
        #     "METADATA_ENVOY_SERVICE_SERVICE_PORT": "9090",
        #     "minio-secret": {"secret": {"name": f"{charm_name}-minio-secret"}},
        #     "MINIO_HOST": os["service"],
        #     "MINIO_NAMESPACE": os["namespace"],
        #     "MINIO_PORT": os["port"],
        #     "MINIO_SSL": os["secure"],
        #     "ML_PIPELINE_SERVICE_HOST": kfp_api["service-name"],
        #     "ML_PIPELINE_SERVICE_PORT": kfp_api["service-port"],
        #     "STREAM_LOGS_FROM_SERVER_API": "false",
        #     # TODO: Think there's a file here we should copy in.  Workload's logs show an error on
        #     #  start for this
        #     "VIEWER_TENSORBOARD_POD_TEMPLATE_SPEC_PATH": "/etc/config/viewer-pod-template.json",
        #     "VIEWER_TENSORBOARD_TF_IMAGE_NAME": "tensorflow/tensorflow",
        # }

        # TODO: Not sure if this gets used.  I don't see it in regular pipeline manifests
        # config_json = json.dumps({"spec": {"serviceAccountName": "kubeflow-pipelines-viewer"}})
        #
        # viewer_pod_template = json.dumps({"spec": {"serviceAccountName": "default-editor"}})

        # self.model.unit.status = MaintenanceStatus("Setting pod spec")
        # self.model.pod.set_spec(
        #     {
        #         "version": 3,
        #         "serviceAccount": {
        #             "roles": [
        #                 {
        #                     "global": True,
        #                     "rules": [
        #                         {
        #                             "apiGroups": [""],
        #                             "resources": ["pods", "pods/log"],
        #                             "verbs": ["get"],
        #                         },
        #                         {
        #                             "apiGroups": [""],
        #                             "resources": ["events"],
        #                             "verbs": ["list"],
        #                         },
        #                         {
        #                             "apiGroups": [""],
        #                             "resources": ["secrets"],
        #                             "verbs": ["get", "list"],
        #                         },
        #                         {
        #                             "apiGroups": ["kubeflow.org"],
        #                             "resources": ["viewers"],
        #                             "verbs": [
        #                                 "create",
        #                                 "get",
        #                                 "list",
        #                                 "watch",
        #                                 "delete",
        #                             ],
        #                         },
        #                         {
        #                             "apiGroups": ["argoproj.io"],
        #                             "resources": ["workflows"],
        #                             "verbs": ["get", "list"],
        #                         },
        #                     ],
        #                 }
        #             ]
        #         },
        #         "containers": [
        #             {
        #                 "name": "ml-pipeline-ui",
        #                 "imageDetails": image_details,
        #                 "ports": [
        #                     {
        #                         "name": "http",
        #                         "containerPort": int(config["http-port"]),
        #                     },
        #                 ],
        #                 "envConfig": env,
        #                 "volumeConfig": [
        #                     {
        #                         "name": "config",
        #                         "mountPath": "/config",
        #                         "files": [
        #                             {
        #                                 "path": "config.json",
        #                                 "content": config_json,
        #                             },
        #                         ],
        #                     },
        #                     {
        #                         "name": "viewer-pod-template",
        #                         "mountPath": "/etc/config",
        #                         "files": [
        #                             {
        #                                 "path": "viewer-pod-template.json",
        #                                 "content": viewer_pod_template,
        #                             },
        #                         ],
        #                     },
        #                 ],
                        # "kubernetes": {
                        #     "readinessProbe": {
                        #         "exec": {"command": ["wget", "-q", "-S", "-O", "-", healthz]},
                        #         "initialDelaySeconds": 3,
                        #         "periodSeconds": 5,
                        #         "timeoutSeconds": 2,
                        #     },
                        #     "livenessProbe": {
                        #         "exec": {"command": ["wget", "-q", "-S", "-O", "-", healthz]},
                        #         "initialDelaySeconds": 3,
                        #         "periodSeconds": 5,
                        #         "timeoutSeconds": 2,
                        #     },
        #                 },
        #             }
        #         ],
        #     },
        # )
        # self.model.unit.status = ActiveStatus()

    # def _send_ui_info(self, interfaces):
    #     if interfaces["kfp-ui"]:
    #         interfaces["kfp-ui"].send_data(
    #             {
    #                 "service-name": f"{self.model.app.name}.{self.model.name}",
    #                 "service-port": self.model.config["http-port"],
    #             }
    #         )
    #
    # def _send_ingress_info(self, interfaces):
    #     if interfaces["ingress"]:
    #         interfaces["ingress"].send_data(
    #             {
    #                 "prefix": "/pipeline",
    #                 "rewrite": "/pipeline",
    #                 "service": self.model.app.name,  # TODO: Should this be name.namespace?
    #                 "port": int(self.model.config["http-port"]),
    #             }
    #         )

    def _check_leader(self):
        if not self.unit.is_leader():
            # We can't do anything useful when not the leader, so do nothing.
            raise CheckFailedError("Waiting for leadership", WaitingStatus)

    # def _get_interfaces(self):
    #     # Remove this abstraction when SDI adds .status attribute to NoVersionsListed,
    #     # NoCompatibleVersionsListed:
    #     # https://github.com/canonical/serialized-data-interface/issues/26
    #     try:
    #         interfaces = get_interfaces(self)
    #     except NoVersionsListed as err:
    #         raise CheckFailedError(str(err), WaitingStatus)
    #     except NoCompatibleVersions as err:
    #         raise CheckFailedError(str(err), BlockedStatus)
    #     except RelationDataError as err:
    #         raise CheckFailedError(str(err), BlockedStatus)
    #     return interfaces

    # def _validate_sdi_interface(self, interfaces: dict, relation_name: str, default_return=None):
    #     """Validates data received from SerializedDataInterface, returning the data if valid.
    #
    #     Optionally can return a default_return value when no relation is established
    #     Raises:
    #         CheckFailed(..., Blocked) when no relation established (unless default_return set)
    #         CheckFailed(..., Blocked) if interface is not using SDI
    #         CheckFailed(..., Blocked) if data in interface fails schema check
    #         CheckFailed(..., Waiting) if we have a relation established but no data passed
    #     Params:
    #         interfaces:
    #     Returns:
    #           (dict) interface data
    #     """
    #     # If nothing is related to this relation, return a default value or raise an error
    #     if relation_name not in interfaces or interfaces[relation_name] is None:
    #         if default_return is not None:
    #             return default_return
    #         else:
    #             raise CheckFailedError(
    #                 f"Missing required relation for {relation_name}", BlockedStatus
    #             )
    #
    #     relations = interfaces[relation_name]
    #     if not isinstance(relations, SerializedDataInterface):
    #         raise CheckFailedError(
    #             f"Unexpected error with {relation_name} relation data - data not as expected",
    #             BlockedStatus,
    #         )
    #
    #     # Get and validate data from the relation
    #     try:
    #         # relations is a dict of {(ops.model.Relation, ops.model.Application): data}
    #         unpacked_relation_data = relations.get_data()
    #     except ValidationError as val_error:
    #         # Validation in .get_data() ensures if data is populated, it matches the schema and is
    #         # not incomplete
    #         self.log.exception(val_error)
    #         raise CheckFailedError(
    #             f"Found incomplete/incorrect relation data for {relation_name}.  See logs",
    #             BlockedStatus,
    #         )
    #
    #     # Check if we have an established relation with no data exchanged
    #     if len(unpacked_relation_data) == 0:
    #         raise CheckFailedError(f"Waiting for {relation_name} relation data", WaitingStatus)
    #
    #     # Unpack data (we care only about the first element)
    #     data_dict = list(unpacked_relation_data.values())[0]
    #
    #     # Catch if empty data dict is received (JSONSchema ValidationError above does not raise
    #     # when this happens)
    #     # Remove once addressed in:
    #     # https://github.com/canonical/serialized-data-interface/issues/28
    #     if len(data_dict) == 0:
    #         raise CheckFailedError(
    #             f"Found incomplete/incorrect relation data for {relation_name}.",
    #             BlockedStatus,
    #         )
    #
    #     return data_dict


class CheckFailedError(Exception):
    """Raise this exception if one of the checks in main fails."""

    def __init__(self, msg, status_type=None):
        super().__init__()

        self.msg = msg
        self.status_type = status_type
        self.status = status_type(msg)


if __name__ == "__main__":
    main(KfpUiOperator)
