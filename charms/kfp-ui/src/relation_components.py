import logging
from typing import Optional, List, Callable, Any, Union

from jsonschema import ValidationError
from ops import CharmBase, StatusBase, WaitingStatus, BlockedStatus, ActiveStatus

from charmed_kubeflow_chisme.components import Component
from serialized_data_interface import SerializedDataInterface, get_interface, NoVersionsListed, NoCompatibleVersions
from serialized_data_interface.errors import UnversionedRelation

from charmed_kubeflow_chisme.exceptions import ErrorWithStatus

logger = logging.getLogger(__name__)


class SdiRelationGetterComponent(Component):
    """Wraps an SDI-backed relation that receives data."""
    def __init__(self, charm: CharmBase, name: str, relation_name, *args, inputs_getter: Optional[Callable[[], Any]] = None, minimum_related_applications: Optional[int] = 1,  maximum_related_applications: Optional[int] = 1, **kwargs):
        """TODO: Docstring"""
        super().__init__(charm, name, *args, inputs_getter=inputs_getter, **kwargs)
        self._relation_name = relation_name
        self._minimum_related_applications = minimum_related_applications
        self._maximum_related_applications = maximum_related_applications
        # TODO: handle relation-broken
        self._events_to_observe = [self._charm.on[self._relation_name].relation_changed]

    def get_data(self) -> Union[List[dict], dict]:
        """Validates and returns the data stored in this relation.

        Validation asserts that there is data for exactly one related app.

        Raises ErrorWithStatus if data can not be returned.
        """
        try:
            interface = self.get_interface()
        # TODO: These messages should be tested and cleaned up
        except (NoVersionsListed, UnversionedRelation) as err:
            raise ErrorWithStatus(str(err), WaitingStatus) from err
        except NoCompatibleVersions as err:
            raise ErrorWithStatus(str(err), BlockedStatus) from err
        except Exception as err:
            raise ErrorWithStatus(f"Caught unknown error: '{str(err)}'", BlockedStatus) from err

        if interface is None:
            msg = f"Missing required data from 1 application on relation {self._relation_name}"
            raise ErrorWithStatus(str(msg), BlockedStatus)

        try:
            # TODO: This might be multiple values (one for each related app).  This is returning a
            #  list
            unpacked_data = list(interface.get_data().values())
        except ValidationError as val_error:
            # Validation in .get_data() ensures if data is populated, it matches the schema and is
            # not incomplete
            msg = f"Got ValidationError when interpreting data on relation {self._relation_name}: {val_error}"
            raise ErrorWithStatus(msg, BlockedStatus) from val_error

        self.validate_data(unpacked_data)

        # If relation supports exactly 1 relation, return just that relation's data.  Else, return
        # as a list.
        if self._minimum_related_applications == self._maximum_related_applications:
            return unpacked_data[0]
        else:
            return unpacked_data

    def get_interface(self) -> Optional[SerializedDataInterface]:
        """Returns the SerializedDataInterface object for this interface."""
        return get_interface(self._charm, self._relation_name)

    def get_status(self) -> StatusBase:
        """Returns the status of this relation.

        Use this in the charm to inspect the state of the relation and its data.

        Will return:
            * BlockedStatus: if we have no compatible versions on the relation, or no related
                             app
            * WaitingStatus: if we have not yet received a version from the opposite relation
            * ActiveStatus: if:
                * nothing is related to us (as there is no work to do)
                * we have one or more relations, and we have sent data to all of them
        """
        logging.info("in ObjectStorageRequirerComponent.is_ready")

        try:
            # If we successfully get data
            self.get_data()
        except ErrorWithStatus as err:
            return err.status

        return ActiveStatus()

    def validate_data(self, data: List[dict]):
        """Validates the data for this relation, raising if it does not meet requirements."""
        if self._minimum_related_applications == self._maximum_related_applications:
            error_msg = f"Expected data from exactly {self._minimum_related_applications} related applications - " \
                        f"got {len(data)}."
        else:
            error_msg = (
                f"Expected data from {self._minimum_related_applications}-{self._maximum_related_applications} "
                f"related applications - got {len(data)}."
            )

        if len(data) > self._maximum_related_applications:
            raise ErrorWithStatus(str(error_msg), BlockedStatus)

        if len(data) == 0:
            raise ErrorWithStatus(str(error_msg), BlockedStatus)


class IngressRelationComponent(Component):
    def __init__(self, charm: CharmBase, name: str, relation_name, *args, inputs_getter: Optional[Callable[[], Any]] = None, **kwargs):
        super().__init__(charm, name, *args, inputs_getter=inputs_getter, **kwargs)
        self._relation_name = relation_name
        self._events_to_observe = [self._charm.on[self._relation_name].relation_created, self._charm.on[self._relation_name].relation_changed]

        # TODO: validation: assert exactly one relation?  share that with the above class?

    def _configure_app(self, event):
        """Send data to all related applications."""
        interface = self.get_interface()
        if interface is None:
            return

        interface.send_data(
            data={
                "prefix": "/pipeline",
                "rewrite": "/pipeline",
                "service": self._charm.model.app.name,  # TODO: Should this be name.namespace?
                "port": int(self._charm.model.config["http-port"]),
            }
        )

    def get_interface(self) -> Optional[SerializedDataInterface]:
        """Returns the SerializedDataInterface object for this interface."""
        try:
            interface = get_interface(self._charm, self._relation_name)
        # TODO: These messages should be tested and cleaned up
        except (NoVersionsListed, UnversionedRelation) as err:
            raise ErrorWithStatus(str(err), WaitingStatus) from err
        except NoCompatibleVersions as err:
            raise ErrorWithStatus(str(err), BlockedStatus) from err
        except Exception as err:
            raise ErrorWithStatus(f"Caught unknown error: '{str(err)}'", BlockedStatus) from err

        return interface

    def get_status(self) -> StatusBase:
        """Returns the status of this relation.

        Use this in the charm to inspect the state of the relation and its data.

        Will return:
            * BlockedStatus: if we have no compatible versions on the relation
            * WaitingStatus: if we have not yet received a version from the opposite relation
            * ActiveStatus: if:
                * nothing is related to us (as there is no work to do)
                * we have one or more relations, and we have sent data to all of them
        """
        required_attributes = ["prefix", "rewrite", "service", "port"]
        unknown_error_message = (
            f"Caught unknown exception while checking readiness of {self._relation_name}: "
        )

        try:
            interface = self.get_interface()
        # TODO: These messages should be tested and cleaned up
        except ErrorWithStatus as err:
            return err.status

        if interface is None:
            # Nothing is related to us, so we have nothing to send out.  Relation is Active
            return ActiveStatus()

        try:
            # TODO: Handle this differently when you know the syntax is correct
            # We check whether we've sent, on our application side of the relation, the required
            # attributes
            interface_data_dict = interface.get_data()
            this_apps_interface_data = interface_data_dict[(self.model.get_relation(self._relation_name), self._charm.app)]

            missing_attributes = []
            # TODO: This could validate the data sent, not just confirm there is something sent.
            #  Would that be too much?
            for attribute in required_attributes:
                if not (attribute in this_apps_interface_data and this_apps_interface_data[attribute] is not None and this_apps_interface_data[attribute] != ""):
                    missing_attributes.append(attribute)

            if missing_attributes:
                msg = f"Relation is missing attributes {missing_attributes} that we send out." \
                      f"  This likely is a transient error but if it persists, there could be" \
                      f" something wrong."

                return WaitingStatus(msg)

            return ActiveStatus()
        except Exception as err:
            logging.info(unknown_error_message)
            return BlockedStatus(str(unknown_error_message + str(err)))
