"""Shared fixtures for Worldcoin pure protocol unit tests."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

# Allow test modules to import local helpers regardless of pytest import mode.
_WORLDCOIN_TEST_DIR = Path(__file__).resolve().parent
if str(_WORLDCOIN_TEST_DIR) not in sys.path:
    sys.path.insert(0, str(_WORLDCOIN_TEST_DIR))

FIXTURES_DIR = (
    Path(__file__).resolve().parents[4] / "fixtures" / "wallets" / "worldcoin"
)


@pytest.fixture
def fixtures_dir() -> Path:
    return FIXTURES_DIR


@pytest.fixture
def golden_vectors(fixtures_dir: Path) -> dict[str, Any]:
    return json.loads((fixtures_dir / "golden_vectors.json").read_text(encoding="utf-8"))
