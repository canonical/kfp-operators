"""Charms dependencies for tests."""

from charmed_kubeflow_chisme.testing import CharmSpec

KFP_DB = CharmSpec(
    charm="charmed-osm-mariadb-k8s",
    channel="latest/edge",
    config={"database": "mlpipeline"},
    trust=True,
)
KFP_VIZ = CharmSpec(charm="kfp-viz", channel="latest/edge", trust=True)
MINIO = CharmSpec(
    charm="minio",
    channel="latest/edge",
    trust=True,
    config={"access-key": "minio", "secret-key": "minio-secret-key"},
)
MYSQL = CharmSpec(
    charm="mysql-k8s", channel="8.0/stable", config={"profile": "testing"}, trust=True
)
