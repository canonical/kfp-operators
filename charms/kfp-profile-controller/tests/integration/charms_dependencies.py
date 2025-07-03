"""Charms dependencies for tests."""

from charmed_kubeflow_chisme.testing import CharmSpec

ADMISSION_WEBHOOK = CharmSpec(charm="admission-webhook", channel="1.10/stable", trust=True)
ISTIO_PILOT = CharmSpec(charm="istio-pilot", channel="1.24/stable", trust=True)
KUBEFLOW_PROFILES = CharmSpec(charm="kubeflow-profiles", channel="1.10/stable", trust=True)
METACONTROLLER_OPERATOR = CharmSpec(
    charm="metacontroller-operator", channel="4.11/stable", trust=True
)
MINIO = CharmSpec(
    charm="minio",
    channel="ckf-1.10/stable",
    trust=True,
    config={"access-key": "minio", "secret-key": "minio-secret-key"},
)
