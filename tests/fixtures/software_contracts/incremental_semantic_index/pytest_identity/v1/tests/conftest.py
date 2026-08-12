import pytest


@pytest.fixture
def shared() -> str:
    return "tests-shared"


@pytest.fixture
def database() -> str:
    return "one"
