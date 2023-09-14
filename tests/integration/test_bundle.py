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
    if ops_test.model_name != "kubeflow":
        raise ValueError("kfp must be deployed to namespace kubeflow")

    # Get/load template bundle from command line args
    bundlefile = Path(request.config.getoption("bundle"))
    basedir = Path("./").absolute()
    bundle = yaml.safe_load(bundlefile.read_text())

    # Build the charms we need to build
    charms_to_build = {
        charm: Path(CHARM_PATH_TEMPLATE.format(basedir=str(basedir), charm=charm))
        for charm in BUNDLE_CHARMS
    }
    log.info(f"Building charms for: {charms_to_build}")
    built_charms = await ops_test.build_charms(*charms_to_build.values())
    log.info(f"Built charms: {built_charms}")

    # Edit the bundle, splicing our locally built charms into it
    #for charm, path in built_charms.items():
    #    bundle = localize_bundle_application(bundle, application=charm, charm_file=path)

    # Deploy the bundle
    # TODO This should be easier... but it isn't.  Can either use the `juju bundle` integration, or
    #      shell out to juju (like k8s charms do).  For now, I'm doing the latter
    #      Observability has a function in their CI that is similar.  Use that?
    bundle_dst_file = write_bundle_file(bundle, ops_test.tmp_path / "bundles" / "bundle.yaml")

    model = ops_test.model_full_name
    # TODO: Figure out when we need --trust rather than blanket-applying it
    cmd = f"juju deploy -m {model} --trust {bundle_dst_file}"
    log.info(f"Deploying bundle to {model} using cmd '{cmd}'")
    rc, stdout, stderr = await ops_test.run(*shlex.split(cmd))
    if rc != 0:
        raise RuntimeError(f"Failed to deploy bundle.  Got stdout:\n{stderr}\nand stderr:\n{stderr}")

    # deploy all KFP charms that were built locally
    for charm, path in built_charms.items():
        metadata_file = Path(f"./charms/{charm}/metadata.yaml")
        metadata = yaml.safe_load(metadata_file.read_text())
        image_path = metadata["resources"]["oci-image"]["upstream-source"]
        resources = {"oci-image": image_path}
        await ops_test.model.deploy(charm, resources=resources, trust=True)

    # deploy argo-controller, minio separately, because those are PodSpec
    # charms and cannot be deployed as part of a bundle
    # for details refer to https://github.com/canonical/bundle-kubeflow/issues/693
    await ops_test.model.deploy("argo-controller", channel="3.3/stable", trust=True)
    await ops_test.model.deploy("minio", channel="ckf-1.7/stable", trust=True)
    await ops_test.model.deploy(
            "charmed-osm-mariadb-k8s", application_name="kfp-db", channel="latest/stable", trust=True
    )

    # add relations
    await ops_test.model.relate("kfp-api", "kfp-db")
    await ops_test.model.relate("kfp-api:kfp-api", "kfp-persistence:kfp-api")
    await ops_test.model.relate("kfp-api:kfp-api", "kfp-ui:kfp-api")
    await ops_test.model.relate("kfp-api:kfp-viz", "kfp-viz:kfp-viz")
    await ops_test.model.relate("kfp-api:object-storage", "minio:object-storage")
    await ops_test.model.relate("istio-pilot:ingress", "kfp-ui:ingress")
    await ops_test.model.relate("kfp-api", "minio")
    await ops_test.model.relate("kfp-profile-controller", "minio")
    await ops_test.model.relate("kfp-ui", "minio")
    await ops_test.model.relate("argo-controller", "minio")

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
