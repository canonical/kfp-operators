#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.
"""Helpers for handling K8s resources."""
from pathlib import Path

import lightkube
from lightkube import codecs


def apply_manifests(lightkube_client: lightkube.Client, yaml_file_path: str):
    """Apply resources using manifest files and returns the applied object.

    Args:
        lightkube_client (lightkube.Client): an instance of lightkube.Client to
            use for applying resources.
        yaml_file_path (str): the resource yaml file.

    Returns:
        A namespaced or global lightkube resource (obj).
    """
    read_yaml = Path(yaml_file_path).read_text()
    yaml_loaded = codecs.load_all_yaml(read_yaml)
    for obj in yaml_loaded:
        try:
            lightkube_client.apply(
                obj=obj,
                name=obj.metadata.name,
            )
        except lightkube.core.exceptions.ApiError as api_error:
            raise api_error
    return obj
