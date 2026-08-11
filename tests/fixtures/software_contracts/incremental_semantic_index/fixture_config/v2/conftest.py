import pytest


@pytest.fixture
def database(prefix: str = "two") -> str:
    return prefix
