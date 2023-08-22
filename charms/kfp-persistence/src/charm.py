#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Charm for the data persistence application of Kubeflow Pipelines.

https://github.com/canonical/kfp-operators/
"""

import logging

from charmed_kubeflow_chisme.components.charm_reconciler import CharmReconciler
from charmed_kubeflow_chisme.components.leadership_gate_component import LeadershipGateComponent
from charmed_kubeflow_chisme.components.serialised_data_interface_components import (
    SdiRelationDataReceiverComponent,
)
from ops import CharmBase, main

from components.pebble_components import (
    PersistenceAgentPebbleService,
    PesistenceAgentServiceConfig,
)

log = logging.getLogger()


class KfpPersistenceOperator(CharmBase):
    """Charm for the data persistence application of Kubeflow Pipelines."""

    def __init__(self, *args, **kwargs):
        """Initialize charm and setup the container."""
        super().__init__(*args, **kwargs)

        # Charm logic
        self.charm_reconciler = CharmReconciler(self)

        # Components
        self.leadership_gate = self.charm_reconciler.add(
            component=LeadershipGateComponent(charm=self, name="leadership-gate"), depends_on=[]
        )

        self.kfp_api_relation = self.charm_reconciler.add(
            component=SdiRelationDataReceiverComponent(
                charm=self, name="relation:kfp-api", relation_name="kfp-api"
            ),
            depends_on=[self.leadership_gate],
        )

        self.persistenceagent_container = self.charm_reconciler.add(
            component=PersistenceAgentPebbleService(
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

        self.charm_reconciler.install_default_event_handlers()


class CheckFailedError(Exception):
    """Raise this exception if one of the checks in main fails."""

    def __init__(self, msg, status_type=None):
        super().__init__()

        self.msg = msg
        self.status_type = status_type
        self.status = status_type(msg)


if __name__ == "__main__":
    main(KfpPersistenceOperator)
