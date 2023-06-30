import logging
import pytest
from pathlib import Path, PosixPath
import shlex
import yaml

from pytest_operator.plugin import OpsTest
from helpers.localize_bundle import localize_bundle_application

BUNDLE_CHARMS = [
    "kfp-api",
    "kfp-persistence",
    "kfp-profile-controller",
    "kfp-schedwf",
    "kfp-ui",
    "kfp-viewer",
    "kfp-viz",
]

CHARM_PATH_TEMPLATE = "{basedir}/charms/{charm}/"

log = logging.getLogger(__name__)


async def test_build_and_deploy(ops_test: OpsTest, request):
    if ops_test.model_name != "kubeflow":
        raise ValueError("kfp must be deployed to namespace kubeflow")

    # Get/load template bundle from command line args
    bundlefile = Path(request.config.getoption("bundle"))
    basedir = Path("./").absolute()
    bundle = yaml.safe_load(bundlefile.read_text())

    # Build the charms we need to build
    charms_to_build = {
        charm: Path(f"./charms/{charm}")
        for charm in BUNDLE_CHARMS
    }
    log.info(f"Building charms for: {charms_to_build}")
    built_charms = await ops_test.build_charms(*charms_to_build.values())
    log.info(f"Built charms: {built_charms}")

    # Edit the bundle, splicing our locally built charms into it
    for charm, path in built_charms.items():
        bundle = localize_bundle_application(bundle, application=charm, charm_file=path)

    # Deploy the bundle
    # TODO This should be easier... but it isn't.  Can either use the `juju bundle` integration, or
    #      shell out to juju (like k8s charms do).  For now, I'm doing the latter
    #      Observability has a function in their CI that is similar.  Use that?
    bundle_dst_file = write_bundle_file(bundle, Path("./bundle.yaml"))

    rendered_bundle = Path(bundle_dst_file).read_text()
    log.info(f"BUNDLE: {rendered_bundle}")

    model = ops_test.model_full_name
    # TODO: Figure out when we need --trust rather than blanket-applying it
    cmd = f"juju deploy -m {model} --trust ./{bundle_dst_file}"
    log.info(f"Deploying bundle to {model} using cmd '{cmd}'")
    rc, stdout, stderr = await ops_test.run(*shlex.split(cmd))
    if rc != 0:
        raise RuntimeError(f"Failed to deploy bundle.  Got stdout:\n{stderr}\nand stderr:\n{stderr}")

    # Wait for everything to be up.  Note, at time of writing these charms would naturally go
    # into blocked during deploy while waiting for each other to satisfy relations, so we don't
    # raise_on_blocked.
    await ops_test.model.wait_for_idle(
        status="active",
        raise_on_blocked=False,  # These apps block while waiting for each other to deploy/relate
        raise_on_error=True,
        timeout=1800,
    )


def write_bundle_file(bundle: dict, path: Path):
    """Writes the bundle to a temporary file and returns the path."""
    bundle_dst_file = path
    bundle_dst_dir = bundle_dst_file.parent
    bundle_dst_dir.mkdir(exist_ok=True, parents=True)
    bundle_dst_file.write_text(yaml.dump(bundle))
    return bundle_dst_file
