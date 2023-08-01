#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Charm for the data persistence application of Kubeflow Pipelines.

https://github.com/canonical/kfp-operators/
"""

import logging

from charmed_kubeflow_chisme.components.charm_reconciler import CharmReconciler
from charmed_kubeflow_chisme.components.leadership_gate_component import LeadershipGateComponent
from ops.charm import CharmBase
from ops.main import main

from components.pebble_components import (
    PebbleServicePersistenceAgentContainer,
    PesistenceAgentServiceConfig,
)
from components.relation_components import SdiRelation

log = logging.getLogger()


class KfpPersistenceOperator(CharmBase):
    """Charm for the data persistence application of Kubeflow Pipelines."""

    def __init__(self, *args, **kwargs):
        """Initialize charm and setup the container."""
        super().__init__(*args, **kwargs)

        # Charm logic
        self.charm_executor = CharmReconciler(self)

        # Components
        self.leadership_gate = self.charm_executor.add(
            component=LeadershipGateComponent(charm=self, name="leadership-gate"), depends_on=[]
        )

        self.kfp_api_relation = self.charm_executor.add(
            component=SdiRelation(charm=self, name="relation:kfp-api", relation_name="kfp-api"),
            depends_on=[self.leadership_gate],
        )

        self.persistenceagent_container = self.charm_executor.add(
            component=PebbleServicePersistenceAgentContainer(
                charm=self,
                name="container:persistenceagent",
                container_name="persistenceagent",
                service_name="persistenceagent",
                files_to_push=[],
                environment={
                    "KUBEFLOW_USERID_HEADER": "kubeflow-userid",
                    "KUBEFLOW_USERID_PREFIX": "",
                    # Upstream defines this in the configmap persistenceagent-config-*
                    "MULTIUSER": "true",
                },
                # provide function to pebble with which it can get service configuration from
                # relation
                inputs_getter=lambda: PesistenceAgentServiceConfig(
                    KFP_API_SERVICE_NAME=self.kfp_api_relation.component.get_data()[
                        "service-name"
                    ],
                    NAMESPACE=str(self.model.name),
                ),
            ),
            depends_on=[self.leadership_gate, self.kfp_api_relation],
        )

        self.charm_executor.install_default_event_handlers()

    def get_all_status(self):
        """Convenience function for getting a list of all statuses for this charm's executor.

        This is more for debugging.  Having an action would be useful to summarise this too on a
        running charm.
        """
        return self.charm_executor.component_graph.status_prioritiser.all()


class CheckFailedError(Exception):
    """Raise this exception if one of the checks in main fails."""

    def __init__(self, msg, status_type=None):
        super().__init__()

        self.msg = msg
        self.status_type = status_type
        self.status = status_type(msg)


if __name__ == "__main__":
    main(KfpPersistenceOperator)
