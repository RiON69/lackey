import os

import pytest


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers", "desktop: drives the real mouse/keyboard; run manually with the owner's consent"
    )


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Desktop tests run only when selected explicitly (-m desktop) or LACKEY_DESKTOP_TESTS=1."""
    if "desktop" in (config.getoption("-m") or "") or os.environ.get("LACKEY_DESKTOP_TESTS") == "1":
        return
    skip = pytest.mark.skip(reason="desktop test: run with -m desktop and the owner's consent")
    for item in items:
        if "desktop" in item.keywords:
            item.add_marker(skip)
