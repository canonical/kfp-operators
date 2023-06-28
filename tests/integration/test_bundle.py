import logging
from pathlib import Path, PosixPath
import shlex
import yaml

from pytest_operator.plugin import OpsTest
from helpers.localize_bundle import localize_bundle_application, get_resources_from_charm_file
from helpers.bundle_mgmt import render_bundle, deploy_bundle

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
    bundlefile_path = Path(request.config.getoption("bundle"))
    basedir = Path("./").absolute()

    # Build the charms we need to build
    charms_to_build = {
        charm: Path(CHARM_PATH_TEMPLATE.format(basedir=str(basedir), charm=charm))
        for charm in BUNDLE_CHARMS
    }
    log.info(f"Building charms for: {charms_to_build}")
    built_charms = await ops_test.build_charms(*charms_to_build.values())
    log.info(f"Built charms: {built_charms}")

    context = {}
    for charm, charm_file in built_charms.items():
       charm_resources = get_resources_from_charm_file(charm_file)
       context.update([(f"{charm.replace('-', '_')}_resources", charm_resources)])
       context.update([(f"{charm.replace('-', '_')}", charm_file)])

    # Render kfp-operators bundle file with locally built charms and their resources
    rendered_bundle = render_bundle(ops_test, bundle_path=bundlefile_path, context=context, local_build=True)

    # Deploy the kfp-operators bundle from the rendered bundle file
    await deploy_bundle(ops_test, bundle_path=rendered_bundle, trust=True)

    # Wait for everything to be up.  Note, at time of writing these charms would naturally go
    # into blocked during deploy while waiting for each other to satisfy relations, so we don't
    # raise_on_blocked.
    await ops_test.model.wait_for_idle(
        status="active",
        raise_on_blocked=False,  # These apps block while waiting for each other to deploy/relate
        raise_on_error=True,
        timeout=1800,
    )
