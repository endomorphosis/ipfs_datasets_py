import pytest


@pytest.fixture
def shared() -> str:
    return "tests-shared"


@pytest.fixture
def database() -> str:
    # Fixture body edit: return value and construction change.
    prefix = "two"
    return prefix
