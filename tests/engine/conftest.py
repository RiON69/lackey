import pytest


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers", "desktop: drives the real mouse/keyboard; run manually with the owner's consent"
    )
