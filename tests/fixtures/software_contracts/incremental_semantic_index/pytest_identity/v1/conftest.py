import pytest

pytestmark = pytest.mark.repo_wide


@pytest.fixture
def shared() -> str:
    return "root-shared"


@pytest.fixture(autouse=True)
def audit_log() -> list[str]:
    return []
