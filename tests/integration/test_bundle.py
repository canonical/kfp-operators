import logging
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
    # for each local charm, build it (in parallel?) and update the bundle to use that
    # TODO: Optionally override some local charms, pulling them instead?  And maybe that accepts a
    #       path (to an already built charm) or channel (so we can use a published branch)
    #       This would be good for CI, where we could build in parallel across many jobs then test
    #       in one spot

    # TODO: Should I make a generic "build charm if not already built" function that accepts a
    #       bundle? it will basically just be `juju bundle`...

    # TODO: Separate kfp charms and other dependencies into bundle and overlay, that way they can
    #       be deployed in separate tests.  But do we need extra tooling to let us "deploy" a
    #       overlay after the fact?  Can't just `juju deploy` it, can we?
    #       Yeah actually, you'd deploy the dependencies first, then you could deploy this bundle's
    #       charms as an overlay.  Ideally you'd build this bundle's charms first though, so you
    #       can fail before.  If you're really worried about speed, you build, deploy these without
    #       relations to dependencies, then deploy dependencies, then wire these up
    #
    # TODO: Update bundle first

    if ops_test.model_name != "kubeflow":
        raise ValueError("kfp must be deployed to namespace kubeflow")

    bundlefile = Path(request.config.getoption("bundle"))

    basedir = Path("./").absolute()

    # Load template bundle
    bundle = yaml.safe_load(bundlefile.read_text())

    # Build the charms we need to build
    charms_to_build = {
        charm: Path(CHARM_PATH_TEMPLATE.format(basedir=str(basedir), charm=charm))
        for charm in BUNDLE_CHARMS
    }
    log.info(f"Building charms for: {charms_to_build}")
    # Mock out build_charms during iterations
    built_charms = await ops_test.build_charms(*charms_to_build.values())
    # FIXME: debug code
    # built_charms = {
    #     'kfp-api': PosixPath('/home/scribs/code/canonical/kfp-operators/kf-16-release/charms/kfp-api/kfp-api_ubuntu-20.04-amd64.charm'),
    #     # 'kfp-viewer': PosixPath('/home/scribs/code/canonical/kfp-operators/kf-16-release/charms/kfp-viewer/kfp-viewer_ubuntu-20.04-amd64.charm'),
    #     # 'kfp-viz': PosixPath('/home/scribs/code/canonical/kfp-operators/kf-16-release/charms/kfp-viz/kfp-viz_ubuntu-20.04-amd64.charm')
    # }
    log.info(f"Built charms: {built_charms}")

    # Edit the bundle, localizing the charms we've built
    for charm, path in built_charms.items():
        bundle = localize_bundle_application(
            bundle, application=charm, charm_file=path
        )

    # Deploy the bundle
    # This should be easier... but it isn't.  Can either use the `juju bundle` integration, or
    # shell out to juju (like k8s charms do).  For now, I'm doing the latter
    bundles_dst_dir = ops_test.tmp_path / "bundles"
    bundles_dst_dir.mkdir(exist_ok=True)
    bundle_dst_file = bundles_dst_dir / "bundle.yaml"
    bundle_dst_file.write_text(yaml.dump(bundle))

    model = ops_test.model_full_name
    # TODO: Figure out when we need --trust rather than blanket-applying it
    cmd = f"juju deploy -m {model} --trust {bundle_dst_file}"
    log.info(f"Deploying bundle to {model} using cmd '{cmd}'")
    rc, stdout, stderr = await ops_test.run(*shlex.split(cmd))

    # Wait for everything to be up.  Note, at time of writing these charms would naturally go
    # into blocked during deploy while waiting for each other to satisfy relations.
    await ops_test.model.wait_for_idle(
        status="active",
        raise_on_blocked=False,  # These apps block while waiting for each other to deploy/relate
        raise_on_error=True,
        timeout=1200,
    )
