"""Charms dependencies for tests."""

from charmed_kubeflow_chisme.testing import CharmSpec

CHARMS = {
    "kfp-api": CharmSpec(charm="kfp-api", channel="latest/edge", trust=True),
    "mysql-k8s": CharmSpec(
        charm="mysql-k8s", channel="8.0/stable", config={"profile": "testing"}, trust=True
    ),
    "kfp-viz": CharmSpec(charm="kfp-viz", channel="latest/edge", trust=True),
    "minio": CharmSpec(
        charm="minio",
        channel="latest/edge",
        trust=True,
        config={"access-key": "minio", "secret-key": "minio-secret-key"},
    ),
}
