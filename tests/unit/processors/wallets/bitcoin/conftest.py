"""Shared fixtures for Bitcoin unit tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ipfs_datasets_py.processors.wallets.bitcoin import (
    BitcoinNetwork,
    BitcoinWalletProcessor,
    UtxoSet,
    describe_script,
    seed_utxo,
)
from ipfs_datasets_py.processors.wallets.protocols import OperationContext, RequestLimits

FIXTURE_ROOT = (
    Path(__file__).resolve().parents[4] / "fixtures" / "wallets" / "bitcoin"
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
        request_id="btc-unit-1",
        limits=RequestLimits(max_items=1000, max_pages=20, max_requests=50),
    )


@pytest.fixture
def processor() -> BitcoinWalletProcessor:
    return BitcoinWalletProcessor(network=BitcoinNetwork.MAINNET)


def seed_from_mapping(utxos: UtxoSet, item: dict) -> None:
    descriptor = describe_script(
        script_hex=item.get("script_hex"),
        address=item.get("address"),
        network=BitcoinNetwork.MAINNET,
    )
    seed_utxo(
        utxos,
        txid=item["txid"],
        vout=int(item["vout"]),
        value_sats=int(item["value"]),
        descriptor=descriptor,
        height=item.get("height"),
    )
