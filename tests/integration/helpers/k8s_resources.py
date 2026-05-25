#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.
"""Helpers for handling K8s resources."""
from pathlib import Path
from typing import Optional

import jinja2
import lightkube
from lightkube import codecs


def apply_manifests(
    lightkube_client: lightkube.Client,
    yaml_template_path: str,
    context: Optional[dict] = None,
):
    """Apply resources using manifest files and returns the applied object.

    Args:
        lightkube_client (lightkube.Client): an instance of lightkube.Client to
            use for applying resources.
        yaml_template_path (str): path to a YAML Jinja2 template file.
        context (Optional[dict]): a dictionary of variables to render the
            yaml file as a Jinja2 template. If None, the file is used as-is.

    Returns:
        A namespaced or global lightkube resource (obj).
    """
    read_yaml = Path(yaml_template_path).read_text()
    compiled_yaml = jinja2.Template(read_yaml).render(**context)
    yaml_loaded = codecs.load_all_yaml(compiled_yaml)
    for obj in yaml_loaded:
        try:
            lightkube_client.apply(
                obj=obj,
                name=obj.metadata.name,
            )
        except lightkube.core.exceptions.ApiError as api_error:
            raise api_error
    return obj
