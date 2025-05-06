"""Charms dependencies for tests."""

from charmed_kubeflow_chisme.testing import CharmSpec

CHARMS = {
    "admission-webhook": CharmSpec(charm="admission-webhook", channel="latest/edge", trust=True),
    "istio-pilot": CharmSpec(charm="istio-pilot", channel="latest/edge", trust=True),
    "metacontroller-operator": CharmSpec(
        charm="metacontroller-operator", channel="latest/edge", trust=True
    ),
    "minio": CharmSpec(
        charm="minio",
        channel="latest/edge",
        trust=True,
        config={"access-key": "minio", "secret-key": "minio-secret-key"},
    ),
    "kubeflow-profiles": CharmSpec(charm="kubeflow-profiles", channel="latest/edge", trust=True),
}
