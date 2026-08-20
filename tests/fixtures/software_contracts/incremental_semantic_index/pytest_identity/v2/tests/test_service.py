import pytest

from pkg.service import service

pytestmark = pytest.mark.module_mark


@pytest.mark.timeout(10)
@pytest.mark.usefixtures("shared")
@pytest.mark.parametrize("value, expected", [(1, 1), (2, 2)])
def test_service(database, value, expected) -> None:
    assert service(value) == expected
    assert database == "two"


@pytest.mark.integration
class TestServiceClass:
    pytestmark = pytest.mark.class_mark

    def test_class_method(self, database: str) -> None:
        assert service(1) == 1
        assert database == "two"
