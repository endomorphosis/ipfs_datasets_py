"""Tests for World Chain composition and WLD assets (WALPROC-G120)."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pytest

from ipfs_datasets_py.processors.wallets.models import AssetRef, Finality
from ipfs_datasets_py.processors.wallets.worldcoin.assets import (
    WLD_WORLD_CHAIN_MAINNET_ADDRESS,
    WorldChainAssetError,
    asset_manifests_for_chain,
    build_sepolia_wld_manifest,
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
    EthereumWalletProcessor,
    WorldChainConfigError,
    WorldChainFinalityLabel,
    WorldChainProcessor,
    classify_world_chain_finality,
    get_world_chain_network,
    validate_world_chain_identity,
    world_chain_processor_for_chain_id,
)


# Reviewed Sepolia fixture contract — not the mainnet WLD address.
_SEPOLIA_WLD_FIXTURE = "0x1111111111111111111111111111111111111111"


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
    assert mainnet.genesis_hash == WORLD_CHAIN_MAINNET_GENESIS_HASH.lower()
    assert sepolia.genesis_hash == WORLD_CHAIN_SEPOLIA_GENESIS_HASH.lower()

    validate_world_chain_identity(
        chain_id=480,
        genesis_hash=WORLD_CHAIN_MAINNET_GENESIS_HASH,
        network="mainnet",
    )
    validate_world_chain_identity(
        chain_id=4801,
        genesis_hash=WORLD_CHAIN_SEPOLIA_GENESIS_HASH,
        network="sepolia",
    )
    with pytest.raises(WorldChainConfigError, match="genesis_hash"):
        validate_world_chain_identity(chain_id=480, genesis_hash="0x" + "00" * 32)
    with pytest.raises(WorldChainConfigError, match="unsupported"):
        get_world_chain_network(1)
    with pytest.raises(WorldChainConfigError, match="network name"):
        validate_world_chain_identity(
            chain_id=480,
            genesis_hash=WORLD_CHAIN_MAINNET_GENESIS_HASH,
            network="sepolia",
        )


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
    assert isinstance(asset, AssetRef)
    assert asset.symbol == "WLD"
    assert asset.decimals == 18
    assert normalize_evm_address(WLD_WORLD_CHAIN_MAINNET_ADDRESS) in asset.asset_reference
    assert asset.chain.chain_ref_id == chain.chain_ref_id

    # Different chain identity cannot share the same asset_id when contracts differ.
    sepolia_asset = wld_asset(
        WORLD_CHAIN_SEPOLIA.to_chain_ref(),
        contract_address=_SEPOLIA_WLD_FIXTURE,
    )
    assert sepolia_asset.asset_id != asset.asset_id

    # Mainnet WLD must never be silently bound to Sepolia.
    with pytest.raises(WorldChainAssetError, match="mainnet WLD"):
        wld_asset(
            WORLD_CHAIN_SEPOLIA.to_chain_ref(),
            contract_address=WLD_WORLD_CHAIN_MAINNET_ADDRESS,
        )
    with pytest.raises(WorldChainAssetError, match="required outside"):
        wld_asset(WORLD_CHAIN_SEPOLIA.to_chain_ref())


def test_asset_manifests_include_mainnet_wld_only_by_default() -> None:
    mainnet = asset_manifests_for_chain(WORLD_CHAIN_MAINNET.to_chain_ref())
    assert set(mainnet) >= {"native_eth", "weth", "wld"}
    assert mainnet["wld"].asset.symbol == "WLD"

    sepolia = asset_manifests_for_chain(WORLD_CHAIN_SEPOLIA.to_chain_ref())
    assert "wld" not in sepolia
    assert set(sepolia) == {"native_eth", "weth"}

    sepolia_with_wld = asset_manifests_for_chain(
        WORLD_CHAIN_SEPOLIA.to_chain_ref(),
        sepolia_wld_contract=_SEPOLIA_WLD_FIXTURE,
    )
    assert "wld" in sepolia_with_wld
    manifest = build_sepolia_wld_manifest(
        WORLD_CHAIN_SEPOLIA.to_chain_ref(),
        contract_address=_SEPOLIA_WLD_FIXTURE,
    )
    assert manifest.label == "wld_sepolia"


def test_world_chain_processor_reuses_ethereum_parsing() -> None:
    eth = _FakeEthereumProcessor()
    assert isinstance(eth, EthereumWalletProcessor)
    processor = WorldChainProcessor(network=WORLD_CHAIN_MAINNET, ethereum=eth)

    tx = processor.normalize_transaction({"hash": "0x1", "value": "10"})
    receipt = processor.normalize_receipt({"transactionHash": "0x1", "status": "0x1"})

    assert eth.tx_calls == 1
    assert eth.receipt_calls == 1
    assert tx["parsed_by"] == "ethereum"
    assert receipt["parsed_by"] == "ethereum"
    assert tx["chain"]["chain_id"] == "480"
    assert tx["world_chain"]["settlement_layer"] == "ethereum-mainnet"
    assert tx["world_chain"]["composes"] == "ethereum"
    assert receipt["world_chain"]["settlement_layer"] == "ethereum-mainnet"


def test_finality_labels_are_distinct_and_depth_is_not_finality() -> None:
    included = classify_world_chain_finality(block_tag="latest")
    operational = classify_world_chain_finality(confirmations=3)
    safe = classify_world_chain_finality(block_tag="safe")
    finalized = classify_world_chain_finality(block_tag="finalized")
    l1 = classify_world_chain_finality(block_tag="finalized", l1_settled=True)
    unknown_tag = classify_world_chain_finality(block_tag="custom-unknown")
    shallow = classify_world_chain_finality(confirmations=0, min_operational_confirmations=2)

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
    assert l1.portable is Finality.FINALIZED
    assert unknown_tag.label is WorldChainFinalityLabel.INCLUDED
    assert shallow.label is WorldChainFinalityLabel.INCLUDED

    # Block depth alone must never be marketed as finality.
    for assessment in (included, operational, shallow, unknown_tag):
        payload = assessment.to_dict()
        assert payload["block_depth_alone_is_not_finality"] is True
        assert assessment.label not in {
            WorldChainFinalityLabel.SAFE,
            WorldChainFinalityLabel.FINALIZED,
            WorldChainFinalityLabel.L1_SETTLED,
        }

    with pytest.raises(WorldChainConfigError, match="confirmations"):
        classify_world_chain_finality(confirmations=-1)


def test_siwe_bootstrap_placeholder_is_not_promoted() -> None:
    assert SIWE_BOOTSTRAP_SUPPORTED is False
    processor = world_chain_processor_for_chain_id(480, _FakeEthereumProcessor())
    caps = processor.capabilities()
    assert caps["siwe_bootstrap_supported"] is False
    assert "siwe" not in caps["assets"]  # type: ignore[operator]
    assert WORLD_CHAIN_MAINNET.to_dict()["siwe_bootstrap_supported"] is False
    assert "siwe" not in processor.normalize_transaction({})["world_chain"]


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

    sepolia_bound = WorldChainProcessor(
        network=WORLD_CHAIN_SEPOLIA,
        ethereum=_FakeEthereumProcessor(),
        sepolia_wld_contract=_SEPOLIA_WLD_FIXTURE,
    )
    sepolia_wld = sepolia_bound.bind_wld_asset()
    assert sepolia_wld.symbol == "WLD"
    assert normalize_evm_address(_SEPOLIA_WLD_FIXTURE) in sepolia_wld.asset_reference
    assert sepolia_bound.wld is not None


def test_processor_requires_ethereum_protocol() -> None:
    with pytest.raises(WorldChainConfigError, match="ethereum"):
        WorldChainProcessor(network=WORLD_CHAIN_MAINNET, ethereum=object())  # type: ignore[arg-type]


def test_world_chain_composes_ethereum_evm_network() -> None:
    """Composition hand-off reuses ethereum EvmNetwork without duplicating EVM code."""

    kwargs = WORLD_CHAIN_MAINNET.to_evm_network_kwargs()
    assert kwargs["chain_id"] == 480
    assert kwargs["genesis_hash"] == WORLD_CHAIN_MAINNET_GENESIS_HASH.lower()
    assert kwargs["native_symbol"] == "ETH"

    evm = WORLD_CHAIN_MAINNET.to_evm_network()
    assert evm.chain_id == 480
    assert evm.to_chain_ref().chain_ref_id == WORLD_CHAIN_MAINNET.to_chain_ref().chain_ref_id

    sepolia_evm = WORLD_CHAIN_SEPOLIA.to_evm_network()
    assert sepolia_evm.chain_id == 4801
    assert sepolia_evm.to_chain_ref().genesis_hash == WORLD_CHAIN_SEPOLIA_GENESIS_HASH.lower()
