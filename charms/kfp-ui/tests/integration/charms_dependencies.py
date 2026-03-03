"""Charms dependencies for tests."""

from charmed_kubeflow_chisme.testing import CharmSpec

KFP_API = CharmSpec(charm="kfp-api", channel="latest/edge/pr-865", trust=True)
KFP_VIZ = CharmSpec(charm="kfp-viz", channel="latest/edge/pr-865", trust=True)
MINIO = CharmSpec(
    charm="minio",
    channel="latest/edge",
    trust=True,
    config={"access-key": "minio", "secret-key": "minio-secret-key"},
)
MYSQL_K8S = CharmSpec(
    charm="mysql-k8s", channel="8.0/stable", trust=True, config={"profile": "testing"}
)
