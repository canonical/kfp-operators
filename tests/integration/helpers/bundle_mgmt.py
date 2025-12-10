# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
import tempfile
from pathlib import Path

import jinja2

logger = logging.getLogger(__name__)


def render_bundle(bundle_path: Path, context: dict) -> Path:
    """Render a templated bundle and return its file path.

    Args:
        bundle_path (Path): Path to bundle file.
        context (dict): Context mapping to render the bundle file.
    """
    # Render the bundle and get its path
    logger.debug(f"Rendering the bundle in {bundle_path} with context {context}")

    tmp_dir = tempfile.mkdtemp()
    tmp_path = Path(tmp_dir)
    logger.debug(f"Saving in {tmp_dir}")

    # Render the bundle
    bundle_path = Path(bundle_path)
    bundle_text = bundle_path.read_text()
    bundle_name = bundle_path.stem
    rendered = jinja2.Template(bundle_text).render(**context)

    rendered_bundle_path = tmp_path / bundle_name
    rendered_bundle_path.write_text(rendered)
    logger.debug(f"Rendered bundle saved in {rendered_bundle_path}")
    return rendered_bundle_path
