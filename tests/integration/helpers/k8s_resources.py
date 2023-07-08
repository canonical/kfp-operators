#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.
"""Helpers for handling K8s resources."""
from pathlib import Path
from typing import Tuple

import aiohttp
import lightkube
from lightkube import codecs

async def fetch_response(url: str, headers: dict) -> Tuple[int, str]:
    """Fetch provided URL and return pair - status and text (int, string).

        Args:
            url (str): the url to send the GET request
            headers (dict): a header that will be added to the request.

        Returns:
            A tuple with the response of the request and the text.
    """
    result_status = 0
    result_text = ""
    async with aiohttp.ClientSession() as session:
        async with session.get(url=url, headers=headers) as response:
            result_status = response.status
            result_text = await response.text()
    return result_status, str(result_text)


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
