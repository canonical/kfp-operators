# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

from unittest.mock import MagicMock, patch

import pytest
from charmed_kubeflow_chisme.exceptions import GenericCharmRuntimeError
from charmed_kubeflow_chisme.testing import add_sdi_relation_to_harness
from ops.model import ActiveStatus, BlockedStatus, WaitingStatus
from ops.testing import Harness

from charm import KfpSchedwf


def test_log_forwarding(harness: Harness, mocked_lightkube_client):
    with patch("charm.LogForwarder") as mock_logging:
        harness.begin()
        mock_logging.assert_called_once_with(charm=harness.charm)


def test_not_leader(
    harness: Harness,
    mocked_lightkube_client,
):
    """Test that charm waits for leadership."""
    harness.begin_with_initial_hooks()
    assert harness.charm.model.unit.status == WaitingStatus(
        "[leadership-gate] Waiting for leadership"
    )


def test_kubernetes_component_created(harness: Harness, mocked_lightkube_client):
    """Test that Kubernetes component is created when we have leadership."""
    # Needed because the kubernetes component will only apply to k8s if we are the leader
    harness.set_leader(True)
    harness.begin()

    # Need to mock the leadership-gate to be active, and the kubernetes auth component so that it
    # sees the expected resources when calling _get_missing_kubernetes_resources
    kubernetes_resources = harness.charm.kubernetes_resources
    kubernetes_resources.component._get_missing_kubernetes_resources = MagicMock(return_value=[])

    harness.charm.on.install.emit()

    assert isinstance(harness.charm.kubernetes_resources.status, ActiveStatus)

    # Assert that expected amount of apply calls were made
    # This simulates the Kubernetes resources being created
    assert mocked_lightkube_client.apply.call_count == 1


@patch("charm.SA_TOKEN_FULL_PATH", "tests/unit/data/non-existent-file")
def test_no_sa_token_file(
    harness: Harness, mocked_sa_component_kubernetes_client, mocked_lightkube_client
):
    """Test the unit status when the SA token file is missing."""
    harness.begin()
    harness.set_can_connect("ml-pipeline-scheduledworkflow", True)

    harness.charm.leadership_gate.get_status = MagicMock(return_value=ActiveStatus())
    harness.charm.kubernetes_resources.component.get_status = MagicMock(
        return_value=ActiveStatus()
    )

    # NOTE: without relations, this is necessary for the charm to be installed before
    # "charm.sa_token.get_status()" can be called later on:
    harness.charm.on.install.emit()

    with pytest.raises(GenericCharmRuntimeError) as err:
        harness.charm.sa_token.get_status()

    service_account_name = harness.charm.model.app.name
    assert (
        err.value.msg
        == f"Token file for {service_account_name} ServiceAccount not present in charm."
    )
    # The base charm arbitrarily sets the unit status to BlockedStatus
    # We should fix this in charmed-kubeflow-chisme as it doesn't really
    # show the actual error and can be misleading
    assert isinstance(harness.charm.unit.status, BlockedStatus)
    assert (
        harness.charm.unit.status.message
        == "[sa-token:scheduledworkflow] Failed to compute status.  See logs for details."
    )


def test_custom_app_name_uses_correct_service_account(mocked_lightkube_client):
    """Test that charm uses the correct service account name when deployed with a custom app name."""
    custom_harness = Harness(KfpSchedwf, meta="""
name: target
containers:
  ml-pipeline-scheduledworkflow:
    resource: oci-image
    mounts:
      - storage: kubeflow-secrets
        location: /var/run/secrets/kubeflow/tokens
requires:
  kfp-api-grpc:
    interface: k8s-service
""")
    
    with patch("charm.LogForwarder"), \
         patch("charm.ServiceMeshConsumer"):
        custom_harness.begin()
        
        # Assert that the charm's sa_name attribute matches the custom app name
        assert custom_harness.charm.sa_name == "target"
        
        # Assert that the SATokenComponent was initialized with the correct sa_name
        assert custom_harness.charm.sa_token.component._sa_name == "target"


@patch("charm.SA_TOKEN_FULL_PATH", "tests/unit/data/schedwf-sa-token")
def test_pebble_service_container_running(harness: Harness, mocked_lightkube_client):
    """Test that the pebble service of the charm's kfp-schedwf container is running."""
    harness.set_leader(True)
    harness.begin()
    harness.set_can_connect("ml-pipeline-scheduledworkflow", True)

    harness.charm.kubernetes_resources.get_status = MagicMock(return_value=ActiveStatus())
    harness.charm.sa_token.get_status = MagicMock(return_value=ActiveStatus())

    harness.charm.on.install.emit()

    assert isinstance(harness.charm.unit.status, ActiveStatus)

    container = harness.charm.unit.get_container("ml-pipeline-scheduledworkflow")
    # Assert that sidecar container is up and its service is running
    assert container.get_service("controller").is_running()

    # Assert the environment variables that are set from defaults in the service plan
    environment = container.get_plan().services["controller"].environment
    assert environment["CRON_SCHEDULE_TIMEZONE"] == harness.charm.config.get("timezone")


@patch("charm.SA_TOKEN_FULL_PATH", "tests/unit/data/schedwf-sa-token")
def test_pebble_service_is_replanned_on_config_changed(harness: Harness, mocked_lightkube_client):
    """Test that the pebble service of the charm's kfp-schedwf container is running."""
    harness.set_leader(True)
    harness.begin()
    harness.set_can_connect("ml-pipeline-scheduledworkflow", True)

    harness.charm.kubernetes_resources.get_status = MagicMock(return_value=ActiveStatus())
    harness.charm.sa_token.get_status = MagicMock(return_value=ActiveStatus())

    harness.charm.on.install.emit()

    assert isinstance(harness.charm.unit.status, ActiveStatus)

    container = harness.charm.unit.get_container("ml-pipeline-scheduledworkflow")
    # Assert that sidecar container is up and its service is running
    assert container.get_service("controller").is_running()

    # Assert the environment variables that are set from defaults
    environment = container.get_plan().services["controller"].environment
    assert environment["CRON_SCHEDULE_TIMEZONE"] == harness.charm.config.get("timezone")
    assert environment["LOG_LEVEL"] == harness.charm.config.get("log-level")


@patch("charm.SA_TOKEN_FULL_PATH", "tests/unit/data/schedwf-sa-token")
def test_install_before_pebble_service_container(harness: Harness, mocked_lightkube_client):
    """Test that charm waits when install event happens before pebble-service-container is ready."""
    harness.set_leader(True)
    harness.begin()

    harness.charm.kubernetes_resources.get_status = MagicMock(return_value=ActiveStatus())
    harness.charm.sa_token.get_status = MagicMock(return_value=ActiveStatus())

    harness.charm.on.install.emit()

    # Assert charm is waiting on PebbleComponent
    assert harness.charm.model.unit.status == WaitingStatus(
        "[kfp-schedwf-pebble-service] Waiting for Pebble to be ready."
    )


@patch("charm.SA_TOKEN_FULL_PATH", "tests/unit/data/schedwf-sa-token")
def test_kfp_api_relation_updates_pebble_service(harness: Harness, mocked_lightkube_client):
    """Test that kfp-api relation updates the pebble service command with custom service-name."""
    # Setup harness
    harness.set_leader(True)
    harness.begin()
    harness.set_can_connect("ml-pipeline-scheduledworkflow", True)

    # Mock components to return ActiveStatus
    harness.charm.kubernetes_resources.get_status = MagicMock(return_value=ActiveStatus())
    harness.charm.sa_token.get_status = MagicMock(return_value=ActiveStatus())

    # Emit install event
    harness.charm.on.install.emit()

    # Test 1: Verify charm status is active
    assert isinstance(harness.charm.unit.status, ActiveStatus)

    # Test 2: Verify pebble service is running
    container = harness.charm.unit.get_container("ml-pipeline-scheduledworkflow")
    assert container.get_service("controller").is_running()

    # Test 3: Verify default command parameter
    plan = container.get_plan()
    command = plan.services["controller"].command
    assert "--mlPipelineAPIServerName=ml-pipeline" in command
    assert "--mlPipelineServiceGRPCPort=8887" in command

    # Test 4: Add SDI relation for kfp-api-grpc with custom service-name
    custom_kfp_api_data = {"service-name": "custom-ml-pipeline", "service-port": "1234"}
    add_sdi_relation_to_harness(harness, "kfp-api-grpc", data=custom_kfp_api_data)

    # Test 5: Verify updated command parameter
    updated_plan = container.get_plan()
    updated_command = updated_plan.services["controller"].command
    assert "--mlPipelineAPIServerName=custom-ml-pipeline" in updated_command
    assert "--mlPipelineServiceGRPCPort=1234" in updated_command


@pytest.fixture
def harness():
    return Harness(KfpSchedwf)


@pytest.fixture()
def mocked_lightkube_client(mocker):
    """Mocks the Lightkube Client in charm.py, returning a mock instead."""
    mocked_lightkube_client = MagicMock()
    mocker.patch("charm.lightkube.Client", return_value=mocked_lightkube_client)
    yield mocked_lightkube_client


@pytest.fixture()
def mocked_sa_component_kubernetes_client(mocker):
    """Mocks the kubernetes client in sa token component."""
    mocked_kubernetes_client = MagicMock()
    mocker.patch("charm.SATokenComponent.kubernetes_client")
    yield mocked_kubernetes_client
