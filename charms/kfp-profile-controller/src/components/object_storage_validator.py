"""Chisme component to validate and normalize object-storage relation data."""

import logging
from typing import Tuple
from urllib.parse import urlparse

from charmed_kubeflow_chisme.components import (
    Component,
    S3RequirerComponent,
    SdiRelationDataReceiverComponent,
)
from charmed_kubeflow_chisme.exceptions import ErrorWithStatus
from ops import ActiveStatus, BlockedStatus, CharmBase, StatusBase

logger = logging.getLogger(__name__)


class ObjectStorageValidatorComponent(Component):
    """Component that validates and normalizes data from the active object-storage relation.

    The charm can receive object storage credentials from either the `object-storage`
    relation or the `s3-credentials` relation.

    This component:
      * selects the active storage relation,
      * validates the data published by the chosen relation,
      * exposes a unified ``get_normalized_data()`` dict for downstream consumers
        (e.g. ``KubernetesComponent`` context callables and ``PebbleServiceComponent``
        inputs getters),
    """

    def __init__(
        self,
        charm: CharmBase,
        name: str,
        s3_component: S3RequirerComponent,
        object_storage_component: SdiRelationDataReceiverComponent,
        s3_relation_name: str = "s3-credentials",
    ):
        """Initialise the component.

        Args:
            charm: the parent charm.
            name: unique component name.
            s3_component: the `S3RequirerComponent` wrapping the `s3-credentials` relation.
            object_storage_component: the `SdiRelationDataReceiverComponent` wrapping the
                `object-storage` relation.
            s3_relation_name: name of the s3 relation endpoint, used to detect which
                relation is active. Defaults to "s3-credentials".
        """
        super().__init__(charm=charm, name=name)
        self._s3_component = s3_component
        self._object_storage_component = object_storage_component
        self._s3_relation_name = s3_relation_name

    @property
    def _active_storage_component(self) -> Component:
        """Return the active storage component (S3 or object-storage).

        Exactly one of the `s3-credentials` or `object-storage` relations is expected
        at a time (enforced by the s3-relations-conflict-detector).
        """
        if self._charm.model.get_relation(self._s3_relation_name):
            return self._s3_component
        return self._object_storage_component

    @staticmethod
    def _parse_s3_endpoint(endpoint: str) -> Tuple[str, int, bool]:
        """Parse an s3 endpoint into a (host, port, secure) tuple.

        The endpoint may be a full URL (e.g. "https://s3.example.com:443") or a bare
        "host[:port]". The MinIO-style sync.py expects the host, port and TLS flag as
        separate values, so the URL scheme (when present) determines the default port and
        whether TLS is used.
        """
        parsed_endpoint = urlparse(endpoint if "://" in endpoint else f"//{endpoint}")
        if parsed_endpoint.scheme:
            secure = parsed_endpoint.scheme == "https"
            port = parsed_endpoint.port or (443 if secure else 80)
        else:
            port = parsed_endpoint.port or 80
            secure = port == 443
        return parsed_endpoint.hostname, port, secure

    def get_normalized_data(self) -> dict:
        """Return normalized object storage connection data from the active storage relation.

        Supports both the `object-storage` and `s3` interfaces, returning a common dict
        with keys: `access_key`, `secret_key`, `host`, `namespace`, `port`,
        `secure`, `region`, `endpoint`.

        Raises:
            ErrorWithStatus(BlockedStatus): if the active relation is missing data
                (no related app, no published databag, missing required fields, or a
                malformed s3 endpoint).
        """
        active_storage_component = self._active_storage_component
        if isinstance(active_storage_component, S3RequirerComponent):
            # get_data() returns a list of dicts; exactly one S3 relation is expected.
            # If empty, the provider hasn't populated the databag yet.
            data_list = active_storage_component.get_data()
            if not data_list:
                raise ErrorWithStatus("Missing s3-credentials relation data", BlockedStatus)
            data = data_list[0]
            required_fields = ("access-key", "secret-key", "endpoint")
            missing = [f for f in required_fields if not data.get(f)]
            if missing:
                raise ErrorWithStatus(
                    "Incomplete s3-credentials relation data, missing fields: "
                    f"{', '.join(missing)}",
                    BlockedStatus,
                )
            host, port, secure = self._parse_s3_endpoint(data["endpoint"])
            if not host:
                raise ErrorWithStatus(
                    f"Invalid s3 endpoint: {data['endpoint']!r}",
                    BlockedStatus,
                )
            return {
                "access_key": data["access-key"],
                "secret_key": data["secret-key"],
                # The s3 interface has no namespace concept. An empty namespace makes
                # sync.py build a `host:port` endpoint (without a `.namespace` suffix).
                "host": host,
                "namespace": "",
                "port": str(port),
                "secure": secure,
                "region": data.get("region", ""),
                # The s3 interface has no namespace concept, so the endpoint is just host:port.
                "endpoint": f"{host}:{port}",
            }
        else:
            # active_storage_component = SdiRelationDataReceiverComponent here
            data = active_storage_component.get_data()
            # With minimum_related_applications=0 and maximum=1, SdiRelationDataReceiverComponent
            # returns {} when no related app is present, otherwise a list of dicts. Extract the
            # first (and expected-only) entry.
            if isinstance(data, list):
                data = data[0] if data else {}
            if not data:
                raise ErrorWithStatus("Missing object-storage relation data", BlockedStatus)

            required_fields = (
                "access-key",
                "secret-key",
                "service",
                "namespace",
                "secure",
                "port",
            )
            missing = [f for f in required_fields if not data.get(f)]
            if missing:
                raise ErrorWithStatus(
                    "Incomplete object-storage relation data, missing fields: "
                    f"{', '.join(missing)}",
                    BlockedStatus,
                )

            return {
                "access_key": data["access-key"],
                "secret_key": data["secret-key"],
                "host": data["service"],
                "namespace": data["namespace"],
                "port": str(data["port"]),
                "secure": data["secure"],
                "region": "",
                # The object-storage interface uses a `host.namespace:port` endpoint.
                "endpoint": f"{data['service']}.{data['namespace']}:{data['port']}",
            }

    def get_status(self) -> StatusBase:
        """Return the validation status for the active storage relation.

        Returns `ActiveStatus` when the active relation's data parses cleanly into the
        normalized form, otherwise returns `BlockedStatus`.
        """
        try:
            self.get_normalized_data()
        except ErrorWithStatus as err:
            return err.status
        return ActiveStatus()
