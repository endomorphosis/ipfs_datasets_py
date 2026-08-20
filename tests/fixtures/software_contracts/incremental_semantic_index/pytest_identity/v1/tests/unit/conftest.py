import pytest


@pytest.fixture
def shared() -> str:
    return "unit-shared"
