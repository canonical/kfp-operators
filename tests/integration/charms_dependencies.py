"""Charms dependencies for tests."""

from charmed_kubeflow_chisme.testing import CharmSpec

ARGO_CONTROLLER = CharmSpec(charm="argo-controller", channel="3.4/stable", trust=True)
ENVOY = CharmSpec(charm="envoy", channel="2.4/stable", trust=True)
KUBEFLOW_PROFILES = CharmSpec(charm="kubeflow-profiles", channel="1.10/stable", trust=True)
KUBEFLOW_ROLES = CharmSpec(charm="kubeflow-roles", channel="1.10/stable", trust=True)
METACONTROLLER_OPERATOR = CharmSpec(
    charm="metacontroller-operator", channel="4.11/stable", trust=True
)
MINIO = CharmSpec(charm="minio", channel="ckf-1.10/stable", trust=False)
MLMD = CharmSpec(charm="mlmd", channel="ckf-1.10/stable", trust=True)
MYSQL_K8S = CharmSpec(
    charm="mysql-k8s", channel="8.0/stable", config={"profile": "testing"}, trust=True
)
ISTIO_GATEWAY = CharmSpec(
    charm="istio-gateway", channel="1.24/stable", config={"kind": "ingress"}, trust=True
)
ISTIO_PILOT = CharmSpec(
    charm="istio-pilot",
    channel="1.24/stable",
    config={"default-gateway": "kubeflow-gateway"},
    trust=True,
)
