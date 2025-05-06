"""Charms dependencies for tests."""

from charmed_kubeflow_chisme.testing import CharmSpec

CHARMS = {"mlmd": CharmSpec(charm="mlmd", channel="latest/edge", trust=True)}
