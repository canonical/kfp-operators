#!/usr/bin/env python3
# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

"""Library for sharing Kubernetes Services information.

This library offers a Python API for providing and requesting information about
any Kubernetes Service resource.
The default relation name is `k8s-svc-info` and it's recommended to use that name,
though if changed, you must ensure to pass the correct name when instantiating the
provider and requirer classes, as well as in `metadata.yaml`.

## Getting Started

### Fetching the library with charmcraft

Using charmcraft you can:
```shell
charmcraft fetch-lib charms.mlops_libs.v0.k8s_service_info
```

## Using the library as requirer

### Add relation to metadata.yaml
```yaml
requires:
  k8s-svc-info:
    interface: k8s-service
    limit: 1
```

### Instantiate the KubernetesServiceInfoRequirer class in charm.py

```python
from ops.charm import CharmBase
from charms.mlops_libs.v0.kubernetes_service_info import KubernetesServiceInfoRequirer, KubernetesServiceInfoRelationError

class RequirerCharm(CharmBase):
    def __init__(self, *args):
        self._k8s_svc_info_requirer = KubernetesServiceInfoRequirer(self)
        self.framework.observe(self.on.some_event_emitted, self.some_event_function)

    def some_event_function():
        # use the getter function wherever the info is needed
        try:
            k8s_svc_info_data = self._k8s_svc_info_requirer.get_data()
        except KubernetesServiceInfoRelationError as error:
            "your error handler goes here"
```

## Using the library as provider

### Add relation to metadata.yaml
```yaml
provides:
  k8s-svc-info:
    interface: k8s-service
```

### Instantiate the KubernetesServiceInfoProvider class in charm.py

```python
from ops.charm import CharmBase
from charms.mlops_libs.v0.kubernetes_service_info import KubernetesServiceInfoProvider, KubernetesServiceInfoRelationError

class ProviderCharm(CharmBase):
    def __init__(self, *args, **kwargs):
        ...
        self._k8s_svc_info_provider = KubernetesServiceInfoProvider(self)
        self.observe(self.on.some_event, self._some_event_handler)
    def _some_event_handler(self, ...):
        # This will update the relation data bag with the Service name and port
        try:
            self._k8s_svc_info_provider.send_data(name, port)
        except KubernetesServiceInfoRelationError as error:
            "your error handler goes here"
```

## Relation data

The data shared by this library is:
* name: the name of the Kubernetes Service
  as it appears in the resource metadata, e.g. "metadata-grpc-service".
* port: the port of the Kubernetes Service
"""

import logging
from typing import List, Optional, Union

from ops.charm import CharmBase, RelationEvent
from ops.framework import BoundEvent, EventSource, Object, ObjectEvents
from ops.model import Relation
from pydantic import BaseModel

# The unique Charmhub library identifier, never change it
LIBID = "f5c3f6cc023e40468d6f9a871e8afcd0"

# Increment this major API version when introducing breaking changes
LIBAPI = 0

# Increment this PATCH version before using `charmcraft publish-lib` or reset
# to 0 if you are raising the major API version
LIBPATCH = 1

# Default relation and interface names. If changed, consistency must be kept
# across the provider and requirer.
DEFAULT_RELATION_NAME = "k8s-service-info"
DEFAULT_INTERFACE_NAME = "k8s-service"
REQUIRED_ATTRIBUTES = ["name", "port"]

logger = logging.getLogger(__name__)


class KubernetesServiceInfoRelationError(Exception):
    """Base exception class for any relation error handled by this library."""

    pass


class KubernetesServiceInfoRelationMissingError(KubernetesServiceInfoRelationError):
    """Exception to raise when the relation is missing on either end."""

    def __init__(self):
        self.message = "Missing relation with a k8s service info provider."
        super().__init__(self.message)


class KubernetesServiceInfoRelationDataMissingError(KubernetesServiceInfoRelationError):
    """Exception to raise when there is missing data in the relation data bag."""

    def __init__(self, message):
        self.message = message
        super().__init__(self.message)


class KubernetesServiceInfoUpdatedEvent(RelationEvent):
    """Indicates the Kubernetes Service Info data was updated."""


class KubernetesServiceInfoEvents(ObjectEvents):
    """Events for the Kubernetes Service Info library."""

    updated = EventSource(KubernetesServiceInfoUpdatedEvent)


class KubernetesServiceInfoObject(BaseModel):
    """Representation of a Kubernetes Service info object.

    Args:
        name: The name of the Service
        port: The port of the Service
    """

    name: str
    port: str


class KubernetesServiceInfoRequirer(Object):
    """Implement the Requirer end of the Kubernetes Service Info relation.

    Observes the relation events and get data of a related application.

    This library emits:
    * KubernetesServiceInfoUpdatedEvent: when data received on the relation is updated.

    Args:
        charm (CharmBase): the provider application
        refresh_event: (list, optional): list of BoundEvents that this manager should handle.
                       Use this to update the data sent on this relation on demand.
        relation_name (str, optional): the name of the relation

    Attributes:
        charm (CharmBase): variable for storing the requirer application
        relation_name (str): variable for storing the name of the relation
    """

    on = KubernetesServiceInfoEvents()

    def __init__(
        self,
        charm: CharmBase,
        refresh_event: Optional[Union[BoundEvent, List[BoundEvent]]] = None,
        relation_name: Optional[str] = DEFAULT_RELATION_NAME,
    ):
        super().__init__(charm, relation_name)
        self._charm = charm
        self._relation_name = relation_name
        self._requirer_wrapper = KubernetesServiceInfoRequirerWrapper(
            self._charm, self._relation_name
        )

        self.framework.observe(
            self._charm.on[self._relation_name].relation_changed, self._on_relation_changed
        )

        self.framework.observe(
            self._charm.on[self._relation_name].relation_broken, self._on_relation_broken
        )

        if refresh_event:
            if not isinstance(refresh_event, (tuple, list)):
                refresh_event = [refresh_event]
            for evt in refresh_event:
                self.framework.observe(evt, self._on_relation_changed)

    def get_data(self) -> KubernetesServiceInfoObject:
        """Return a KubernetesServiceInfoObject."""
        return self._requirer_wrapper.get_data()

    def _on_relation_changed(self, event: BoundEvent) -> None:
        """Handle relation-changed event for this relation."""
        self.on.updated.emit(event.relation)

    def _on_relation_broken(self, event: BoundEvent) -> None:
        """Handle relation-broken event for this relation."""
        self.on.updated.emit(event.relation)


class KubernetesServiceInfoRequirerWrapper(Object):
    """Wrapper for the relation data getting logic.

    Args:
        charm (CharmBase): the requirer application
        relation_name (str, optional): the name of the relation

    Attributes:
        relation_name (str): variable for storing the name of the relation
    """

    def __init__(self, charm, relation_name: Optional[str] = DEFAULT_RELATION_NAME):
        super().__init__(charm, relation_name)
        self.relation_name = relation_name

    @staticmethod
    def _validate_relation(relation: Relation) -> None:
        """Series of checks for the relation and relation data.

        Args:
            relation (Relation): the relation object to run the checks on

        Raises:
            KubernetesServiceInfoRelationDataMissingError if data is missing or incomplete
            KubernetesServiceInfoRelationMissingError: if there is no related application
        """
        # Raise if there is no related application
        if not relation:
            raise KubernetesServiceInfoRelationMissingError()

        # Extract remote app information from relation
        remote_app = relation.app
        # Get relation data from remote app
        relation_data = relation.data[remote_app]

        # Raise if there is no data found in the relation data bag
        if not relation_data:
            raise KubernetesServiceInfoRelationDataMissingError(
                f"No data found in relation {relation.name} data bag."
            )

        # Check if the relation data contains the expected attributes
        missing_attributes = [
            attribute for attribute in REQUIRED_ATTRIBUTES if attribute not in relation_data
        ]
        if missing_attributes:
            raise KubernetesServiceInfoRelationDataMissingError(
                f"Missing attributes: {missing_attributes} in relation {relation.name}"
            )

    def get_data(self) -> KubernetesServiceInfoObject:
        """Return a KubernetesServiceInfoObject containing Kubernetes Service information.

        Raises:
            KubernetesServiceInfoRelationDataMissingError: if data is missing entirely or some attributes
            KubernetesServiceInfoRelationMissingError: if there is no related application
            ops.model.TooManyRelatedAppsError: if there is more than one related application
        """
        # Validate relation data
        # Raises TooManyRelatedAppsError if related to more than one app
        relation = self.model.get_relation(self.relation_name)

        self._validate_relation(relation=relation)

        # Get relation data from remote app
        relation_data = relation.data[relation.app]

        return KubernetesServiceInfoObject(name=relation_data["name"], port=relation_data["port"])


class KubernetesServiceInfoProvider(Object):
    """Implement the Provider end of the Kubernetes Service Info relation.

    Observes relation events to send data to related applications.

    Args:
        charm (CharmBase): the provider application
        name (str): the name of the Kubernetes Service the provider knows about
        port (str): the port number of the Kubernetes Service the provider knows about
        refresh_event: (list, optional): list of BoundEvents that this manager should handle.  Use this to update
                       the data sent on this relation on demand.
        relation_name (str, optional): the name of the relation

    Attributes:
        charm (CharmBase): variable for storing the provider application
        relation_name (str): variable for storing the name of the relation
    """

    def __init__(
        self,
        charm: CharmBase,
        name: str,
        port: str,
        refresh_event: Optional[Union[BoundEvent, List[BoundEvent]]] = None,
        relation_name: Optional[str] = DEFAULT_RELATION_NAME,
    ):
        super().__init__(charm, relation_name)
        self.charm = charm
        self.relation_name = relation_name
        self._provider_wrapper = KubernetesServiceInfoProviderWrapper(
            self.charm, self.relation_name
        )
        self._svc_name = name
        self._svc_port = port

        self.framework.observe(self.charm.on.leader_elected, self._send_data)

        self.framework.observe(self.charm.on[self.relation_name].relation_created, self._send_data)

        if refresh_event:
            if not isinstance(refresh_event, (tuple, list)):
                refresh_event = [refresh_event]
            for evt in refresh_event:
                self.framework.observe(evt, self._send_data)

    def _send_data(self, _) -> None:
        """Serve as an event handler for sending the Kubernetes Service information."""
        self._provider_wrapper.send_data(self._svc_name, self._svc_port)


class KubernetesServiceInfoProviderWrapper(Object):
    """Wrapper for the relation data sending logic.

    Args:
        charm (CharmBase): the provider application
        relation_name (str, optional): the name of the relation

    Attributes:
        charm (CharmBase): variable for storing the provider application
        relation_name (str): variable for storing the name of the relation
    """

    def __init__(self, charm: CharmBase, relation_name: Optional[str] = DEFAULT_RELATION_NAME):
        super().__init__(charm, relation_name)
        self.charm = charm
        self.relation_name = relation_name

    def send_data(
        self,
        name: str,
        port: str,
    ) -> None:
        """Update the relation data bag with data from a Kubernetes Service.

        This method will complete successfully even if there are no related applications.

        Args:
            name (str): the name of the Kubernetes Service the provider knows about
            port (str): the port number of the Kubernetes Service the provider knows about
        """
        # Validate unit is leader to send data; otherwise return
        if not self.charm.model.unit.is_leader():
            logger.info(
                "KubernetesServiceInfoProvider handled send_data event when it is not the leader."
                "Skipping event - no data sent."
            )
        # Update the relation data bag with a Kubernetes Service information
        relations = self.charm.model.relations[self.relation_name]

        # Update relation data
        for relation in relations:
            relation.data[self.charm.app].update(
                {
                    "name": name,
                    "port": port,
                }
            )
