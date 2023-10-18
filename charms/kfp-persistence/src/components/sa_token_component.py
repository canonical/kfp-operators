#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Component for generating the kfp-persistence sa token."""

import logging
from pathlib import Path
from typing import List

import kubernetes
from charmed_kubeflow_chisme.components.component import Component
from charmed_kubeflow_chisme.exceptions import GenericCharmRuntimeError
from kubernetes.client import AuthenticationV1TokenRequest, CoreV1Api, V1TokenRequestSpec
from kubernetes.client.rest import ApiException
from kubernetes.config import ConfigException
from ops import ActiveStatus, StatusBase

logger = logging.getLogger(__name__)


class SaTokenComponent(Component):
    """Create a token of a ServiceAccount for the persistence controller."""

    def __init__(
        self,
        *args,
        audiences: List[str],
        sa_name: str,
        sa_namespace: str,
        path: str,
        filename: str,
        expiration: int,
        **kwargs,
    ):
        """Instantiate the SaTokenComponent.

        Args:
            audiences (List[str]): list of audiences for the SA token
            expiration (int): token expiration time in seconds
            filename (str): filename to save a token file
            path (str): path to save a token file
            sa_name (str): ServiceAccount name
            sa_namespace (str): ServiceAccount namespace
        """
        super().__init__(*args, **kwargs)
        self._audiences = audiences
        self._expiration = expiration
        self._filename = filename
        self._sa_name = sa_name
        self._sa_namespace = sa_namespace
        self._path = path

    @property
    def kubernetes_client(self) -> CoreV1Api:
        """Load cluster configuration and return a CoreV1 Kubernetes client."""
        try:
            kubernetes.config.load_incluster_config()
        except ConfigException:
            kubernetes.config.load_kube_config()

        api_client = kubernetes.client.ApiClient()
        core_v1_api = kubernetes.client.CoreV1Api(api_client)
        return core_v1_api

    def _create_sa_token(self) -> AuthenticationV1TokenRequest:
        """Return a TokenRequest."""
        # The TokenRequest should always have the audience pointing to pipelines.kubeflow.org
        # and an large expiration time to avoid having to re-generate the token and push it
        # again to the workload container.
        spec = V1TokenRequestSpec(audiences=self._audiences, expiration_seconds=self._expiration)
        body = kubernetes.client.AuthenticationV1TokenRequest(spec=spec)
        try:
            api_response = self.kubernetes_client.create_namespaced_service_account_token(
                name=self._sa_name, namespace=self._sa_namespace, body=body
            )
        except ApiException as e:
            logger.error("Error creating the sa token.")
            raise e
        return api_response

    def _generate_and_save_token(self, path: str, filename: str) -> None:
        """Save the sa token in path in the charm container.

        Args:
            path (str): a path to store the token file
            filename (str): a filename for the token file
        """
        if not Path(path).is_dir():
            logger.error("Path does not exist, cannot proceed saving the sa token file.")
            raise RuntimeError("Path does not exist, cannot proceed saving the sa token file.")
        if Path(path, filename).is_file():
            logger.info("Token file already exists, nothing else to do.")
        api_response = self._create_sa_token()
        token = api_response.status.token
        with open(Path(path, filename), "w") as token_file:
            token_file.write(token)

    def _configure_app_leader(self, event) -> None:
        """Generate and save the SA token file.

        Raises:
            GenericCharmRuntimeError if the file could not be created.
        """
        try:
            self._generate_and_save_token(self._path, self._filename)
        except (RuntimeError, ApiException) as e:
            raise GenericCharmRuntimeError("Failed to create and save sa token") from e

    def get_status(self) -> StatusBase:
        """Return ActiveStatus if the SA token file is present.

        Raises:
            GenericCharmRuntimeError if the file is not present in the charm.
        """
        if not Path(self._path, self._filename).is_file():
            raise GenericCharmRuntimeError("SA token file is not present in charm")
        return ActiveStatus
