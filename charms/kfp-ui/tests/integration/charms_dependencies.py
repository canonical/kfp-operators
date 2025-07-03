"""Charms dependencies for tests."""

from charmed_kubeflow_chisme.testing import CharmSpec

KFP_API = CharmSpec(charm="kfp-api", channel="2.4/stable", trust=True)
KFP_VIZ = CharmSpec(charm="kfp-viz", channel="2.4/stable", trust=True)
MINIO = CharmSpec(
    charm="minio",
    channel="ckf-1.10/stable",
    trust=True,
    config={"access-key": "minio", "secret-key": "minio-secret-key"},
)
MYSQL_K8S = CharmSpec(
    charm="mysql-k8s", channel="8.0/stable", trust=True, config={"profile": "testing"}
)
