from _pytest.config.argparsing import Parser


def pytest_addoption(parser: Parser):
    parser.addoption(
        "--bundle",
        default="./tests/integration/data/kfp_latest_edge.yaml.j2",
        help="Path to bundle file to use as the template for tests.  This must include all charms"
             "built by this bundle, where the locally built charms will replace those specified. "
             "This is useful for testing this bundle against different external dependencies. "
             "An example file is in ./tests/integration/data/kfp_latest_edge.yaml",
    )
