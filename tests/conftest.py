from _pytest.config.argparsing import Parser

import json
import os
import logging
from pathlib import Path

import pytest
from pytest_operator.plugin import OpsTest
log = logging.getLogger(__name__)

@pytest.fixture
def ops_test(ops_test: OpsTest) -> OpsTest:
    if os.environ.get("CI") == "true":
        # Running in GitHub Actions; skip build step
        # (GitHub Actions uses a separate, cached build step)
        packed_charms = json.loads(os.environ["CI_PACKED_CHARMS"])

        async def build_charm(charm_path, bases_index: int = None) -> Path:
            for charm in packed_charms:
                if Path(charm_path) == Path(charm["directory_path"]):
                    if bases_index is None or bases_index == charm["bases_index"]:
                        file_path = Path(charm["file_path"].strip("local:"))
                        return file_path
            raise ValueError(f"Unable to find .charm file for {bases_index=} at {charm_path=}")

        ops_test.build_charm = build_charm

    return ops_test


def pytest_addoption(parser: Parser):
    parser.addoption(
        "--bundle",
        default="./tests/integration/data/kfp_against_latest_edge.yaml",
        help="Path to bundle file to use as the template for tests.  This must include all charms"
             "built by this bundle, where the locally built charms will replace those specified. "
             "This is useful for testing this bundle against different external dependencies. "
             "An example file is in ./tests/integration/data/kfp_against_latest_edge.yaml",
    )
