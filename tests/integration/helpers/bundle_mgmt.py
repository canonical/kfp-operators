# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

import asyncio
import logging
from pathlib import Path

from pytest_operator.plugin import OpsTest

logger = logging.getLogger(__name__)


def render_bundle(ops_test: OpsTest, bundle_path: Path, context: dict) -> Path:
    """Render a templated bundle and return its file path.

    Args:
        bundle_path (Path): Path to bundle file.
        context (dict): Context mapping to render the bundle file.
    """
    # Render the bundle and get its path
    # The pytest-operator will save it in `self.tmp_path / "bundles"`
    logger.debug(f"Rendering the bundle in {bundle_path} with context {context}")
    logger.debug(f"Saving in {ops_test.tmp_path}")
    rendered_bundle_path = ops_test.render_bundle(bundle_path, context=context)
    logger.debug(f"Rendered bundle saved in {rendered_bundle_path}")
    return rendered_bundle_path


async def deploy_bundle(ops_test: OpsTest, bundle_path: Path, trust: bool) -> None:
    """Deploy a bundle from file using juju CLI.

    Args:
        bundle_path (Path): Path to bundle file.
        trust (bool): Whether to deploy with trust.
    """
    # Deploy the bundle
    run_args = ["juju", "deploy", "-m", ops_test.model_full_name, f"{bundle_path}"]
    if trust:
        run_args.append("--trust")
    retcode, stdout, stderr = await ops_test.run(*run_args)
    logger.info(stdout)
    assert retcode == 0, f"Deploy failed: {(stderr or stdout).strip()}"
