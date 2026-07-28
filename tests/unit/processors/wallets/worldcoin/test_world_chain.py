"""Tests for World Chain composition and WLD assets (WALPROC-G120)."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pytest

from ipfs_datasets_py.processors.wallets.models import Finality
from ipfs_datasets_py.processors.wallets.worldcoin.assets import (
    WLD_WORLD_CHAIN_MAINNET_ADDRESS,
    normalize_evm_address,
    wld_asset,
)
from ipfs_datasets_py.processors.wallets.worldcoin.world_chain import (
    SIWE_BOOTSTRAP_SUPPORTED,
    WORLD_CHAIN_MAINNET,
    WORLD_CHAIN_MAINNET_CHAIN_ID,
    WORLD_CHAIN_MAINNET_GENESIS_HASH,
    WORLD_CHAIN_SEPOLIA,
    WORLD_CHAIN_SEPOLIA_CHAIN_ID,
    WORLD_CHAIN_SEPOLIA_GENESIS_HASH,
    WorldChainConfigError,
    WorldChainFinalityLabel,
    WorldChainProcessor,
    classify_world_chain_finality,
    get_world_chain_network,
    validate_world_chain_identity,
    world_chain_processor_for_chain_id,
)


class _FakeEthereumProcessor:
    """Minimal Ethereum composition double — proves parsing is reused."""

    def __init__(self) -> None:
        self.tx_calls = 0
        self.receipt_calls = 0

    def normalize_transaction(self, raw: Mapping[str, Any]) -> Mapping[str, Any]:
        self.tx_calls += 1
        return {
            "hash": raw.get("hash", "0xabc"),
            "from": raw.get("from", "0xfrom"),
            "to": raw.get("to", "0xto"),
            "value": raw.get("value", "0"),
            "status": "succeeded",
            "parsed_by": "ethereum",
        }

    def normalize_receipt(self, raw: Mapping[str, Any]) -> Mapping[str, Any]:
        self.receipt_calls += 1
        return {
            "transaction_hash": raw.get("transactionHash", "0xabc"),
            "status": raw.get("status", "0x1"),
            "parsed_by": "ethereum",
        }


def test_world_chain_network_ids_and_genesis_are_validated() -> None:
    mainnet = get_world_chain_network(480)
    sepolia = get_world_chain_network("4801")
    assert mainnet.chain_id == WORLD_CHAIN_MAINNET_CHAIN_ID
    assert sepolia.chain_id == WORLD_CHAIN_SEPOLIA_CHAIN_ID
    assert mainnet.genesis_hash == WORLD_CHAIN_MAINNET_GENESIS_HASH
    assert sepolia.genesis_hash == WORLD_CHAIN_SEPOLIA_GENESIS_HASH

    validate_world_chain_identity(
        chain_id=480,
        genesis_hash=WORLD_CHAIN_MAINNET_GENESIS_HASH,
        network="mainnet",
    )
    with pytest.raises(WorldChainConfigError, match="genesis_hash"):
        validate_world_chain_identity(chain_id=480, genesis_hash="0x" + "00" * 32)
    with pytest.raises(WorldChainConfigError, match="unsupported"):
        get_world_chain_network(1)


def test_chain_ref_includes_namespace_network_and_genesis() -> None:
    ref = WORLD_CHAIN_MAINNET.to_chain_ref()
    assert ref.namespace == "eip155"
    assert ref.network == "mainnet"
    assert ref.chain_id == "480"
    assert ref.genesis_hash == WORLD_CHAIN_MAINNET_GENESIS_HASH.lower()

    other = WORLD_CHAIN_SEPOLIA.to_chain_ref()
    assert ref.chain_ref_id != other.chain_ref_id


def test_wld_asset_is_network_and_contract_bound() -> None:
    chain = WORLD_CHAIN_MAINNET.to_chain_ref()
    asset = wld_asset(chain)
    assert asset.symbol == "WLD"
    assert asset.decimals == 18
    assert normalize_evm_address(WLD_WORLD_CHAIN_MAINNET_ADDRESS) in asset.asset_reference
    assert asset.chain.chain_ref_id == chain.chain_ref_id

    # Different chain identity cannot share the same asset_id.
    sepolia_asset = wld_asset(WORLD_CHAIN_SEPOLIA.to_chain_ref(), contract_address=WLD_WORLD_CHAIN_MAINNET_ADDRESS)
    assert sepolia_asset.asset_id != asset.asset_id


def test_world_chain_processor_reuses_ethereum_parsing() -> None:
    eth = _FakeEthereumProcessor()
    processor = WorldChainProcessor(network=WORLD_CHAIN_MAINNET, ethereum=eth)

    tx = processor.normalize_transaction({"hash": "0x1", "value": "10"})
    receipt = processor.normalize_receipt({"transactionHash": "0x1", "status": "0x1"})

    assert eth.tx_calls == 1
    assert eth.receipt_calls == 1
    assert tx["parsed_by"] == "ethereum"
    assert receipt["parsed_by"] == "ethereum"
    assert tx["chain"]["chain_id"] == "480"
    assert tx["world_chain"]["settlement_layer"] == "ethereum-mainnet"


def test_finality_labels_are_distinct_and_depth_is_not_finality() -> None:
    included = classify_world_chain_finality(block_tag="latest")
    operational = classify_world_chain_finality(confirmations=3)
    safe = classify_world_chain_finality(block_tag="safe")
    finalized = classify_world_chain_finality(block_tag="finalized")
    l1 = classify_world_chain_finality(block_tag="finalized", l1_settled=True)

    assert included.label is WorldChainFinalityLabel.INCLUDED
    assert included.portable is Finality.OBSERVED
    assert operational.label is WorldChainFinalityLabel.OPERATIONALLY_CONFIRMED
    assert operational.portable is Finality.CONFIRMED
    assert safe.label is WorldChainFinalityLabel.SAFE
    assert safe.portable is Finality.SAFE
    assert finalized.label is WorldChainFinalityLabel.FINALIZED
    assert finalized.portable is Finality.FINALIZED
    assert l1.label is WorldChainFinalityLabel.L1_SETTLED
    assert l1.l1_settled is True

    # Block depth alone must never be marketed as finality.
    for assessment in (included, operational):
        assert assessment.to_dict()["block_depth_alone_is_not_finality"] is True
        assert assessment.label not in {
            WorldChainFinalityLabel.FINALIZED,
            WorldChainFinalityLabel.L1_SETTLED,
        }


def test_siwe_bootstrap_placeholder_is_not_promoted() -> None:
    assert SIWE_BOOTSTRAP_SUPPORTED is False
    processor = world_chain_processor_for_chain_id(480, _FakeEthereumProcessor())
    caps = processor.capabilities()
    assert caps["siwe_bootstrap_supported"] is False
    assert "siwe" not in caps["assets"]  # type: ignore[operator]
    assert WORLD_CHAIN_MAINNET.to_dict()["siwe_bootstrap_supported"] is False


def test_processor_rejects_wrong_provider_identity_and_binds_wld() -> None:
    processor = WorldChainProcessor(network=WORLD_CHAIN_MAINNET, ethereum=_FakeEthereumProcessor())
    processor.validate_provider_identity(chain_id=480, genesis_hash=WORLD_CHAIN_MAINNET_GENESIS_HASH)
    with pytest.raises(WorldChainConfigError):
        processor.validate_provider_identity(chain_id=480, genesis_hash=WORLD_CHAIN_SEPOLIA_GENESIS_HASH)

    wld = processor.bind_wld_asset()
    assert wld.symbol == "WLD"
    assert processor.wld is not None
    assert processor.wld.asset_id == wld.asset_id

    sepolia = WorldChainProcessor(network=WORLD_CHAIN_SEPOLIA, ethereum=_FakeEthereumProcessor())
    with pytest.raises(WorldChainConfigError, match="chain_id 480"):
        sepolia.bind_wld_asset()


def test_processor_requires_ethereum_protocol() -> None:
    with pytest.raises(WorldChainConfigError, match="ethereum"):
        WorldChainProcessor(network=WORLD_CHAIN_MAINNET, ethereum=object())  # type: ignore[arg-type]
