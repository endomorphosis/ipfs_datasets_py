"""Shared fixtures for Xaman unit tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ipfs_datasets_py.processors.wallets.protocols import (
    OperationContext,
    RequestLimits,
)
from ipfs_datasets_py.processors.wallets.xrpl.networks import XRPLNetwork

_FIXTURE_DIR = (
    Path(__file__).resolve().parents[4] / "fixtures" / "wallets" / "xaman"
)


@pytest.fixture
def xaman_fixture_dir() -> Path:
    return _FIXTURE_DIR


@pytest.fixture
def load_xaman_fixture(xaman_fixture_dir: Path):
    def _load(name: str) -> dict:
        with (xaman_fixture_dir / name).open(encoding="utf-8") as handle:
            return json.load(handle)

    return _load


@pytest.fixture
def op_context() -> OperationContext:
    return OperationContext(
        request_id="xaman-unit",
        limits=RequestLimits(max_items=100, max_pages=10, max_requests=20),
    )


@pytest.fixture
def testnet() -> XRPLNetwork:
    return XRPLNetwork.TESTNET
