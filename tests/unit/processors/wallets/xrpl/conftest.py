"""Shared fixtures for XRPL unit tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ipfs_datasets_py.processors.wallets.protocols import OperationContext, RequestLimits
from ipfs_datasets_py.processors.wallets.xrpl import XRPLNetwork, XRPLWalletProcessor

FIXTURE_ROOT = (
    Path(__file__).resolve().parents[4] / "fixtures" / "wallets" / "xrpl"
)


@pytest.fixture
def fixture_root() -> Path:
    return FIXTURE_ROOT


@pytest.fixture
def load_fixture(fixture_root: Path):
    def _load(name: str):
        with (fixture_root / name).open(encoding="utf-8") as handle:
            return json.load(handle)

    return _load


@pytest.fixture
def context() -> OperationContext:
    return OperationContext(
        request_id="xrpl-unit-1",
        limits=RequestLimits(max_items=1000, max_pages=20, max_requests=50),
    )


@pytest.fixture
def processor() -> XRPLWalletProcessor:
    return XRPLWalletProcessor(network=XRPLNetwork.MAINNET)
