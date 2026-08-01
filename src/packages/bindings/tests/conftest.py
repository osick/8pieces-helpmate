import pytest


def pytest_configure(config):
    config.addinivalue_line("markers", "slow: needs --run-slow to execute")


def pytest_addoption(parser):
    parser.addoption("--run-slow", action="store_true", default=False)


def pytest_collection_modifyitems(config, items):
    if config.getoption("--run-slow"):
        return
    skip = pytest.mark.skip(reason="needs --run-slow")
    for item in items:
        if "slow" in item.keywords:
            item.add_marker(skip)
