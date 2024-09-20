# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.
"""Utils functions for integration tests. Should be moved to chisme."""

import os
import pathlib
import subprocess
import typing


async def get_packed_charms(
    charm_path: typing.Union[str, os.PathLike], bases_index: int = None
) -> pathlib.Path:
    """Simplified version of https://github.com/canonical/data-platform-workflows/blob/06f252ea079edfd055cee236ede28c237467f9b0/python/pytest_plugins/pytest_operator_cache/pytest_operator_cache/_plugin.py#L22."""  # noqa: E501
    charm_path = pathlib.Path(charm_path)
    # namespace-node-affinity_ubuntu-20.04-amd64.charm
    # <metadata-name>_<base>-<architecture>.charm
    architecture = subprocess.run(
        ["dpkg", "--print-architecture"],
        capture_output=True,
        check=True,
        encoding="utf-8",
    ).stdout.strip()
    assert architecture in ("amd64", "arm64")
    packed_charms = list(charm_path.glob(f"*-{architecture}.charm"))
    if len(packed_charms) == 1:
        # python-libjuju's model.deploy(), juju deploy, and juju bundle files expect local charms
        # to begin with `./` or `/` to distinguish them from Charmhub charms.
        # Therefore, we need to return an absolute path—a relative `pathlib.Path` does not start
        # with `./` when cast to a str.
        # (python-libjuju model.deploy() expects a str but will cast any input to a str as a
        # workaround for pytest-operator's non-compliant `build_charm` return type of
        # `pathlib.Path`.)
        return packed_charms[0].resolve(strict=True)
    elif len(packed_charms) > 1:
        message = f"More than one matching .charm file found at {charm_path=} for {architecture=}: {packed_charms}."  # noqa: E501
        if bases_index is None:
            message += " Specify `bases_index`"
        raise ValueError(message)
    else:
        raise ValueError(
            f"Unable to find .charm file for {architecture=} and {bases_index=} at {charm_path=}"
        )
