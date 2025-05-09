"""Charms dependencies for tests."""

from charmed_kubeflow_chisme.testing import CharmSpec

MLMD = CharmSpec(charm="mlmd", channel="latest/edge", trust=True)
