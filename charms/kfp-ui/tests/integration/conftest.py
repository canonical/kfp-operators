#!/usr/bin/env python3
# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

from _pytest.config.argparsing import Parser


def pytest_addoption(parser: Parser):
    parser.addoption(
        "--charm-path",
        help="Path to charm file when downloaded as artefact as a result of build_charm.yaml",
    )
