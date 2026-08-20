import pytest


@pytest.mark.slow
def test_database(database: str) -> None:
    assert database == "one"
