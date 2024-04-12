#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

"""Charm for the Kubeflow Pipelines Profile Controller.

https://github.com/canonical/kfp-operators/
"""

import json
import logging
from base64 import b64encode
from pathlib import Path
from typing import Dict

import yaml
from jsonschema import ValidationError
from oci_image import OCIImageResource, OCIImageResourceError
from ops.charm import CharmBase
from ops.main import main
from ops.model import ActiveStatus, BlockedStatus, MaintenanceStatus, WaitingStatus
from serialized_data_interface.errors import (
    NoCompatibleVersions,
    NoVersionsListed,
    RelationDataError,
)
from serialized_data_interface.sdi import SerializedDataInterface, get_interfaces

DEFAULT_IMAGES_FILE = "src/default-custom-images.json"
with open(DEFAULT_IMAGES_FILE, "r") as json_file:
    DEFAULT_IMAGES = json.load(json_file)

# This must be hard-coded to port 80 because the metacontroller webhook that talks to this port
# only communicates over port 80.  Upstream uses the service to map 80->8080 but we cannot via
# podspec.
CONTROLLER_PORT = 80

# TODO: This sets the version of the images deployed to each namespace (value comes from the
#  upstream configMap pipeline-install-config's appVersion entry).  Normal pattern would
#  set this in metadata but this is different here.  Should this be exposed differently?
KFP_IMAGES_VERSION = (
    "2.0.0-alpha.7"  # Remember to change this version also in default-custom-images.json
)

# Note: Istio destinationrule/auth have been manually disabled in sync.py.  Need a better
# solution for this in future

# TODO: Restore the readiness probes?


class KfpProfileControllerOperator(CharmBase):
    """Charm for the Kubeflow Pipelines Profile Controller.

    https://github.com/canonical/kfp-operators/
    """

    def __init__(self, *args):
        super().__init__(*args)

        self.log = logging.getLogger()

        self.image = OCIImageResource(self, "oci-image")
        self.images = {}

        self.framework.observe(self.on.install, self._set_pod_spec)
        self.framework.observe(self.on.upgrade_charm, self._set_pod_spec)
        self.framework.observe(self.on.config_changed, self._set_pod_spec)
        self.framework.observe(self.on["object-storage"].relation_changed, self._set_pod_spec)
        self.framework.observe(self.on.leader_elected, self._set_pod_spec)

    def _set_pod_spec(self, event):
        try:
            self._check_leader()
            self.images = self.get_images(
                DEFAULT_IMAGES,
                self.parse_images_config(self.model.config["custom_images"]),
            )
            interfaces = self._get_interfaces()
            os = self._get_object_storage(interfaces)
            image_details = self.image.fetch()
        except (CheckFailedError, OCIImageResourceError) as check_failed:
            self.model.unit.status = check_failed.status
            self.log.info(str(check_failed.status))
            return

        logging.info("Found all required relations - proceeding to setting pod spec")
        self.model.unit.status = MaintenanceStatus("Setting pod spec")

        deployment_env = {
            "minio-secret": {"secret": {"name": f"{self.model.app.name}-minio-credentials"}},
            "MINIO_HOST": os["service"],
            "MINIO_PORT": os["port"],
            "MINIO_NAMESPACE": os["namespace"],
            "KFP_VERSION": KFP_IMAGES_VERSION,
            "KFP_DEFAULT_PIPELINE_ROOT": "",
            "DISABLE_ISTIO_SIDECAR": "false",
            "CONTROLLER_PORT": CONTROLLER_PORT,
            "METADATA_GRPC_SERVICE_HOST": "mlmd.kubeflow",  # TODO: Set using relation
            "METADATA_GRPC_SERVICE_PORT": "8080",  # TODO: Set using relation to kfp-api or mlmd
            "VISUALIZATION_SERVER_IMAGE": self.images["visualization_server__image"],
            "VISUALIZATION_SERVER_TAG": self.images["visualization_server__version"],
            "FRONTEND_IMAGE": self.images["frontend__image"],
            "FRONTEND_TAG": self.images["frontend__version"],
        }

        self.model.pod.set_spec(
            {
                "version": 3,
                "containers": [
                    {
                        # TODO: If istio is enabled, may need annotation here of
                        #  sidecar.istio.io/inject: "false" like upstream uses
                        "name": "kubeflow-pipelines-profile-controller",
                        "command": ["python"],
                        "args": ["/hooks/sync.py"],
                        "imageDetails": image_details,
                        "ports": [
                            {
                                "name": "http",
                                "containerPort": CONTROLLER_PORT,
                                "protocol": "TCP",
                            },
                        ],
                        "envConfig": deployment_env,
                        "volumeConfig": [
                            {
                                "name": "kubeflow-pipelines-profile-controller-code",
                                "mountPath": "/hooks",
                                "configMap": {
                                    "name": "kubeflow-pipelines-profile-controller-code",
                                    "files": [
                                        {
                                            "key": "sync.py",
                                            "path": "sync.py",
                                        },
                                    ],
                                },
                            },
                        ],
                    },
                ],
            },
            k8s_resources={
                "kubernetesResources": {
                    "customResources": {
                        # Define the metacontroller that manages the deployments for each user
                        "compositecontrollers.metacontroller.k8s.io": [
                            {
                                "apiVersion": "metacontroller.k8s.io/v1alpha1",
                                "kind": "CompositeController",
                                "metadata": {
                                    "name": "kubeflow-pipelines-profile-controller",
                                },
                                "spec": {
                                    "childResources": [
                                        {
                                            "apiVersion": "v1",
                                            "resource": "secrets",
                                            # TODO: Push this change upstream
                                            "updateStrategy": {"method": "InPlace"},
                                        },
                                        {
                                            "apiVersion": "v1",
                                            "resource": "configmaps",
                                            "updateStrategy": {"method": "OnDelete"},
                                        },
                                        {
                                            "apiVersion": "apps/v1",
                                            "resource": "deployments",
                                            "updateStrategy": {"method": "InPlace"},
                                        },
                                        {
                                            "apiVersion": "v1",
                                            "resource": "services",
                                            "updateStrategy": {"method": "InPlace"},
                                        },
                                        # Added from
                                        # https://github.com/kubeflow/pipelines/pull/6629/files to
                                        # fix
                                        # https://github.com/canonical/bundle-kubeflow/issues/423.
                                        # This was not yet in upstream and if they go with
                                        # something different we should consider syncing with
                                        # upstream
                                        {
                                            "apiVersion": "kubeflow.org/v1alpha1",
                                            "resource": "poddefaults",
                                            "updateStrategy": {"method": "InPlace"},
                                        },
                                        # TODO: This only works if istio is available.  Disabled
                                        #  for now and add back when istio checked as dependency
                                        # {
                                        #     "apiVersion": "networking.istio.io/v1alpha3",
                                        #     "resource": "destinationrules",
                                        #     "updateStrategy": {"method": "InPlace"},
                                        # },
                                        # {
                                        #     "apiVersion": "security.istio.io/v1beta1",
                                        #     "resource": "authorizationpolicies",
                                        #     "updateStrategy": {"method": "InPlace"},
                                        # },
                                    ],
                                    "generateSelector": True,
                                    "hooks": {
                                        "sync": {
                                            "webhook": {
                                                "url": f"http://"
                                                f"{self.model.app.name}.{self.model.name}/sync"
                                            }
                                        }
                                    },
                                    "parentResource": {
                                        "apiVersion": "v1",
                                        "resource": "namespaces",
                                    },
                                    "resyncPeriodSeconds": 3600,
                                },
                            }
                        ]
                    },
                    "secrets": [
                        {
                            "name": f"{self.model.app.name}-minio-credentials",
                            "type": "Opaque",
                            "data": {
                                k: b64encode(v.encode("utf-8")).decode("utf-8")
                                for k, v in {
                                    "MINIO_ACCESS_KEY": os["access-key"],
                                    "MINIO_SECRET_KEY": os["secret-key"],
                                }.items()
                            },
                        }
                    ],
                },
                "configMaps": {
                    "kubeflow-pipelines-profile-controller-code": {
                        "sync.py": Path("files/upstream/sync.py").read_text(),
                    },
                },
            },
        )
        self.model.unit.status = ActiveStatus()

    def _get_interfaces(self):
        # Remove this abstraction when SDI adds .status attribute to NoVersionsListed,
        # NoCompatibleVersionsListed:
        # https://github.com/canonical/serialized-data-interface/issues/26
        try:
            interfaces = get_interfaces(self)
        except NoVersionsListed as err:
            raise CheckFailedError(str(err), WaitingStatus)
        except NoCompatibleVersions as err:
            raise CheckFailedError(str(err), BlockedStatus)
        except RelationDataError as err:
            raise CheckFailedError(str(err), BlockedStatus)
        return interfaces

    def _get_object_storage(self, interfaces):
        relation_name = "object-storage"
        return self._validate_sdi_interface(interfaces, relation_name)

    def _validate_sdi_interface(self, interfaces: dict, relation_name: str, default_return=None):
        """Validates data received from SerializedDataInterface, returning the data if valid.

        Optionally can return a default_return value when no relation is established
        Raises:
            CheckFailed(..., Blocked) when no relation established (unless default_return set)
            CheckFailed(..., Blocked) if interface is not using SDI
            CheckFailed(..., Blocked) if data in interface fails schema check
            CheckFailed(..., Waiting) if we have a relation established but no data passed
        Params:
            interfaces:
        Returns:
              (dict) interface data
        """
        # If nothing is related to this relation, return a default value or raise an error
        if relation_name not in interfaces or interfaces[relation_name] is None:
            if default_return is not None:
                return default_return
            else:
                raise CheckFailedError(
                    f"Missing required relation for {relation_name}", BlockedStatus
                )

        relations = interfaces[relation_name]
        if not isinstance(relations, SerializedDataInterface):
            raise CheckFailedError(
                f"Unexpected error with {relation_name} relation data - data not as expected",
                BlockedStatus,
            )

        # Get and validate data from the relation
        try:
            # relations is a dict of {(ops.model.Relation, ops.model.Application): data}
            unpacked_relation_data = relations.get_data()
        except ValidationError as val_error:
            # Validation in .get_data() ensures if data is populated, it matches the schema and is
            # not incomplete
            self.log.exception(val_error)
            raise CheckFailedError(
                f"Found incomplete/incorrect relation data for {relation_name}.  See logs",
                BlockedStatus,
            )

        # Check if we have an established relation with no data exchanged
        if len(unpacked_relation_data) == 0:
            raise CheckFailedError(f"Waiting for {relation_name} relation data", WaitingStatus)

        # Unpack data (we care only about the first element)
        data_dict = list(unpacked_relation_data.values())[0]

        # Catch if empty data dict is received (JSONSchema ValidationError above does not raise
        # when this happens)
        # Remove once addressed in:
        # https://github.com/canonical/serialized-data-interface/issues/28
        if len(data_dict) == 0:
            raise CheckFailedError(
                f"Found incomplete/incorrect relation data for {relation_name}.",
                BlockedStatus,
            )

        return data_dict

    def _check_leader(self):
        if not self.unit.is_leader():
            # We can't do anything useful when not the leader, so do nothing.
            raise CheckFailedError("Waiting for leadership", WaitingStatus)

    def parse_images_config(self, config: str) -> Dict:
        """
        Parse a YAML config-defined images list.

        This function takes a YAML-formatted string 'config' containing a list of images
        and returns a dictionary representing the images.

        Args:
            config (str): YAML-formatted string representing a list of images.

        Returns:
            Dict: A list of images.
        """
        error_message = (
            f"Cannot parse a config-defined images list from config '{config}' - this"
            "config input will be ignored."
        )
        if not config:
            return []
        try:
            images = yaml.safe_load(config)
        except yaml.YAMLError as err:
            self.log.warning(
                f"{error_message}  Got error: {err}, while parsing the custom_image config."
            )
            raise err
        return images

    def get_images(
        self, default_images: Dict[str, str], custom_images: Dict[str, str]
    ) -> Dict[str, str]:
        """
        Combine default images with custom images.

        This function takes two dictionaries, 'default_images' and 'custom_images',
        representing the default set of images and the custom set of images respectively.
        It combines the custom images into the default image list, overriding any matching
        image names from the default list with the custom ones.

        Args:
            default_images (Dict[str, str]): A dictionary containing the default image names
                as keys and their corresponding default image URIs as values.
            custom_images (Dict[str, str]): A dictionary containing the custom image names
                as keys and their corresponding custom image URIs as values.

        Returns:
            Dict[str, str]: A dictionary representing the combined images, where image names
            from the custom_images override any matching image names from the default_images.
        """
        images = default_images
        for image_name, custom_image in custom_images.items():
            if custom_image:
                if image_name in images:
                    images[image_name] = custom_image
                else:
                    self.log.warning(f"image_name {image_name} not in image list, ignoring.")

        # This are special cases comfigmap where they need to be split into image and version
        for image_name in [
            "visualization_server",
            "frontend",
        ]:
            images[f"{image_name}__image"], images[f"{image_name}__version"] = images[
                image_name
            ].rsplit(":", 1)
        return images


class CheckFailedError(Exception):
    """Raise this exception if one of the checks in main fails."""

    def __init__(self, msg, status_type=None):
        super().__init__()

        self.msg = msg
        self.status_type = status_type
        self.status = status_type(msg)


if __name__ == "__main__":
    main(KfpProfileControllerOperator)
