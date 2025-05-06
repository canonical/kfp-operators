"""Charms dependencies for tests."""
from charmed_kubeflow_chisme.testing import CharmSpec

CHARMS = {
    "argo-controller": CharmSpec(
        charm="argo-controller",
        channel="latest/edge",
        trust=True
    ),
    "metacontroller-operator": CharmSpec(
        charm="metacontroller-operator",
        channel="latest/edge",
        trust=True
    ),
    "minio": CharmSpec(
        charm="minio",
        channel="latest/edge",
        trust=False
    ),
    "mlmd": CharmSpec(
        charm="mlmd",
        channel="latest/edge",
        trust=True
    ),
    "envoy": CharmSpec(
        charm="envoy",
        channel="latest/edge",
        trust=True
    ),
    "kubeflow-profiles": CharmSpec(
        charm="kubeflow-profiles",
        channel="latest/edge",
        trust=True
    ),
    "istio-gateway": CharmSpec(
        charm="istio-gateway",
        channel="latest/edge",
        config={"kind": "ingress"},
        trust=True
    ),
    "istio-pilot": CharmSpec(
        charm="istio-pilot",
        channel="latest/edge",
        config={"default-gateway": "kubeflow-gateway"},
        trust=True
    ),
    "mysql-k8s": CharmSpec(
        charm="mysql-k8s",
        channel="8.0/stable",
        config={"profile": "testing"},
        trust=True
    ),
    "kubeflow-roles": CharmSpec(
        charm="kubeflow-roles",
        channel="latest/edge",
        trust=True
    )
}
