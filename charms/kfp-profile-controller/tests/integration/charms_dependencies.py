"""Charms dependencies for tests."""

from charmed_kubeflow_chisme.testing import CharmSpec

ADMISSION_WEBHOOK = CharmSpec(charm="admission-webhook", channel="latest/edge", trust=True)
ISTIO_PILOT = CharmSpec(charm="istio-pilot", channel="latest/edge", trust=True)
KUBEFLOW_PROFILES = CharmSpec(charm="kubeflow-profiles", channel="latest/edge", trust=True)
METACONTROLLER_OPERATOR = CharmSpec(
    charm="metacontroller-operator", channel="latest/edge", trust=True
)
MINIO = CharmSpec(
    charm="minio",
    channel="latest/edge",
    trust=True,
    config={"access-key": "minio", "secret-key": "minio-secret-key"},
)
