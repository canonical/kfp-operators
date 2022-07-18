#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

"""Charm for the Kubeflow Pipelines Profile Controller.

https://github.com/canonical/kfp-operators/
"""

import logging
from base64 import b64encode
from pathlib import Path

from jsonschema import ValidationError
from oci_image import OCIImageResource, OCIImageResourceError
from ops.charm import CharmBase
from ops.main import main
from ops.model import ActiveStatus, BlockedStatus, MaintenanceStatus, WaitingStatus
from serialized_data_interface import (
    NoCompatibleVersions,
    NoVersionsListed,
    SerializedDataInterface,
    get_interfaces,
)

# This must be hard-coded to port 80 because the metacontroller webhook that talks to this port
# only communicates over port 80.  Upstream uses the service to map 80->8080 but we cannot via
# podspec.
CONTROLLER_PORT = 80

# TODO: This sets the version of the images deployed to each namespace (value comes from the
#  upstream configMap pipeline-install-config's appVersion entry).  Normal pattern would
#  set this in metadata but this is different here.  Should this be exposed differently?
KFP_IMAGES_VERSION = "1.7.0-rc.3"

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

        self.framework.observe(self.on.install, self._set_pod_spec)
        self.framework.observe(self.on.upgrade_charm, self._set_pod_spec)
        self.framework.observe(self.on.config_changed, self._set_pod_spec)
        self.framework.observe(self.on["object-storage"].relation_changed, self._set_pod_spec)
        self.framework.observe(self.on.leader_elected, self._set_pod_spec)

    def _set_pod_spec(self, event):
        try:
            self._check_leader()
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
            self.log.error(val_error)
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


class CheckFailedError(Exception):
    """Raise this exception if one of the checks in main fails."""

    def __init__(self, msg, status_type=None):
        super().__init__()

        self.msg = msg
        self.status_type = status_type
        self.status = status_type(msg)


if __name__ == "__main__":
    main(KfpProfileControllerOperator)
