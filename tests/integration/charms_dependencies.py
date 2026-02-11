"""Charms dependencies for tests."""

from charmed_kubeflow_chisme.testing import CharmSpec

ARGO_CONTROLLER = CharmSpec(charm="argo-controller", channel="latest/edge", trust=True)
ENVOY = CharmSpec(charm="envoy", channel="latest/edge", trust=True)
KUBEFLOW_PROFILES = CharmSpec(charm="kubeflow-profiles", channel="latest/edge", trust=True)
KUBEFLOW_ROLES = CharmSpec(charm="kubeflow-roles", channel="latest/edge", trust=True)
METACONTROLLER_OPERATOR = CharmSpec(
    charm="metacontroller-operator", channel="latest/edge", trust=True
)
MINIO = CharmSpec(charm="minio", channel="latest/edge", trust=True)
MLMD = CharmSpec(charm="mlmd", channel="latest/edge", trust=True)
MYSQL_K8S = CharmSpec(
    charm="mysql-k8s", channel="8.0/stable", config={"profile": "testing"}, trust=True
)
ISTIO_GATEWAY = CharmSpec(
    charm="istio-gateway", channel="latest/edge", config={"kind": "ingress"}, trust=True
)
ISTIO_PILOT = CharmSpec(
    charm="istio-pilot",
    channel="latest/edge",
    config={"default-gateway": "kubeflow-gateway"},
    trust=True,
)
# For Charmed Istio to work together with Cilium,
# the `platform` configuration of the istio-k8s charm must be unset
# because by default the platform is set to "microk8s".
ISTIO_K8S = CharmSpec(charm="istio-k8s", channel="2/edge", config={"platform": ""}, trust=True)
ISTIO_INGRESS_K8S = CharmSpec(charm="istio-ingress-k8s", channel="2/edge", trust=True)
ISTIO_BEACON_K8S = CharmSpec(charm="istio-beacon-k8s", channel="2/edge", trust=True)
