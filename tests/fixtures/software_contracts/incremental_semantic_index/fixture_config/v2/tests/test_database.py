import pytest


@pytest.mark.integration
def test_database(database: str) -> None:
    assert database == "two"
