from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

from ._helpers import FixtureJsonRpc


FIXTURE_DIR = (
    Path(__file__).resolve().parents[4] / "fixtures" / "wallets" / "ethereum"
)


@pytest.fixture(scope="session")
def rpc_session() -> dict[str, Any]:
    return json.loads((FIXTURE_DIR / "rpc_session.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def reorg_fixture() -> dict[str, Any]:
    return json.loads((FIXTURE_DIR / "reorg.json").read_text(encoding="utf-8"))


@pytest.fixture
def fixture_rpc(rpc_session: Mapping[str, Any]) -> FixtureJsonRpc:
    return FixtureJsonRpc(rpc_session)
