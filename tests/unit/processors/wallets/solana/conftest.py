from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest


FIXTURE_DIR = (
    Path(__file__).resolve().parents[4] / "fixtures" / "wallets" / "solana"
)


@pytest.fixture(scope="session")
def rpc_session() -> dict[str, Any]:
    return json.loads((FIXTURE_DIR / "rpc_session.json").read_text(encoding="utf-8"))
