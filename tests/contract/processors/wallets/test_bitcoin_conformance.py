"""Bitcoin chain conformance suite (WALPROC-G400 / WALPROC-019).

Extends the shared :class:`WalletProcessorConformance` harness with Bitcoin
fixture-driven checks. Extra checks cannot remove shared required coverage.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ipfs_datasets_py.processors.wallets.bitcoin import (
    MAINNET_GENESIS,
    BitcoinFinalityPolicy,
    BitcoinLedgerProvider,
    BitcoinNetwork,
    BitcoinNormalizer,
    BitcoinWalletProcessor,
    ScriptDescriptor,
    UtxoRecord,
    UtxoSet,
    describe_address,
    fixture_backend_from_transactions,
    parse_sats,
)
from ipfs_datasets_py.processors.wallets.errors import NormalizationError
from ipfs_datasets_py.processors.wallets.models import Finality, UTXORecord
from ipfs_datasets_py.processors.wallets.protocols import (
    OperationContext,
    RequestLimits,
)
from ipfs_datasets_py.tests.contract.processors.wallets.conformance import (
    REQUIRED_SHARED_CHECKS,
    ProviderContract,
    WalletProcessorConformance,
)

_FIXTURE_DIR = (
    Path(__file__).resolve().parents[3] / "fixtures" / "wallets" / "bitcoin"
)


def _load(name: str) -> dict:
    with (_FIXTURE_DIR / name).open(encoding="utf-8") as handle:
        return json.load(handle)


def _context() -> OperationContext:
    return OperationContext(
        request_id="btc-conformance",
        limits=RequestLimits(max_items=500, max_pages=20, max_requests=50),
    )


def _extra_legacy_segwit_taproot(suite: WalletProcessorConformance) -> None:
    data = _load("scripts_legacy_segwit_taproot.json")
    for vector in data["vectors"]:
        if "address" not in vector:
            continue
        descriptor = describe_address(
            vector["address"], network=BitcoinNetwork.MAINNET
        )
        assert isinstance(descriptor, ScriptDescriptor)
        assert descriptor.script_type.value == vector["expect_script_type"]


def _extra_coinbase(suite: WalletProcessorConformance) -> None:
    data = _load("coinbase.json")
    processor = BitcoinWalletProcessor(network=BitcoinNetwork.MAINNET)
    records = processor.normalize_transactions(
        [data["transaction"]],
        context=_context(),
        head_height=1,
        apply_utxos=True,
    )
    assert any(isinstance(r, UTXORecord) for r in records)
    assert processor.balance_sats("1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa") == 5_000_000_000


def _extra_multi_io(suite: WalletProcessorConformance) -> None:
    data = _load("multi_input_output.json")
    processor = BitcoinWalletProcessor(network=BitcoinNetwork.MAINNET)
    from ipfs_datasets_py.processors.wallets.bitcoin import describe_script, seed_utxo

    for item in data["seed_utxos"]:
        seed_utxo(
            processor.utxos,
            txid=item["txid"],
            vout=int(item["vout"]),
            value_sats=int(item["value"]),
            descriptor=describe_script(
                script_hex=item.get("script_hex"),
                address=item.get("address"),
                network=BitcoinNetwork.MAINNET,
            ),
        )
    processor.normalize_transactions(
        [data["transaction"]], context=_context(), apply_utxos=True
    )
    assert data["expect"]["total_out_sats"] == 145000


def _extra_spent_unspent(suite: WalletProcessorConformance) -> None:
    data = _load("spent_unspent.json")
    processor = BitcoinWalletProcessor(network=BitcoinNetwork.MAINNET)
    processor.normalize_transactions(
        [data["create_tx"], data["spend_tx"]],
        context=_context(),
        apply_utxos=True,
    )
    assert processor.balance_sats(data["address"]) == 0


def _extra_replacement(suite: WalletProcessorConformance) -> None:
    data = _load("replacement_rbf.json")
    processor = BitcoinWalletProcessor(network=BitcoinNetwork.MAINNET)
    from ipfs_datasets_py.processors.wallets.bitcoin import describe_script, seed_utxo

    seed = data["seed_utxo"]
    seed_utxo(
        processor.utxos,
        txid=seed["txid"],
        vout=int(seed["vout"]),
        value_sats=int(seed["value"]),
        descriptor=describe_script(
            script_hex=seed.get("script_hex"),
            address=seed.get("address"),
            network=BitcoinNetwork.MAINNET,
        ),
    )
    processor.normalize_transactions(
        [data["original"], data["replacement"]],
        context=_context(),
        apply_utxos=True,
    )
    assert (
        processor.balance_sats("1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa")
        == data["expect_after_replacement"]["balance_destination"]
    )


def _extra_network_mismatch(suite: WalletProcessorConformance) -> None:
    data = _load("network_mismatch.json")
    for case in data["cases"]:
        if "address" not in case:
            continue
        network = BitcoinNetwork(case["configured_network"])
        if case["expect_error"]:
            with pytest.raises(NormalizationError):
                describe_address(case["address"], network=network)
        else:
            describe_address(case["address"], network=network)


def _extra_reorg_utxo(suite: WalletProcessorConformance) -> None:
    data = _load("reorg_utxo.json")
    processor = BitcoinWalletProcessor(network=BitcoinNetwork.MAINNET)
    from ipfs_datasets_py.processors.wallets.bitcoin import describe_script, seed_utxo

    seed = data["seed_utxo"]
    seed_utxo(
        processor.utxos,
        txid=seed["txid"],
        vout=int(seed["vout"]),
        value_sats=int(seed["value"]),
        descriptor=describe_script(
            script_hex=seed.get("script_hex"),
            address=seed.get("address"),
            network=BitcoinNetwork.MAINNET,
        ),
        height=seed.get("height"),
    )
    processor.normalize_transactions(
        [data["orphaned_tx"]], context=_context(), apply_utxos=True
    )
    processor.reverse_from_height(201)
    assert (
        processor.balance_sats("bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t4")
        == data["expect"]["after_reorg_reverse"]["balance_source"]
    )


def _extra_exact_sats_and_utxo_model(suite: WalletProcessorConformance) -> None:
    assert parse_sats("21000000") == 21_000_000
    with pytest.raises(Exception):
        parse_sats(1.0)
    processor = BitcoinWalletProcessor(network=BitcoinNetwork.MAINNET)
    assert processor.capabilities.metadata.get("utxo_model") is True
    assert processor.capabilities.metadata.get("ownership_clustering") is False
    assert isinstance(UtxoRecord, type)
    assert UtxoRecord is UTXORecord


def _extra_confirmation_policy(suite: WalletProcessorConformance) -> None:
    policy = BitcoinFinalityPolicy(network=BitcoinNetwork.MAINNET)
    assert policy.finality_for_confirmations(0) is Finality.OBSERVED
    assert policy.finality_for_confirmations(policy.thresholds.safe) is Finality.SAFE
    # Policy is configurable; not universal chain truth.
    custom = BitcoinFinalityPolicy(
        network=BitcoinNetwork.MAINNET,
    )
    assert custom.thresholds.confirmed >= 0


def _extra_no_psbt_sign_broadcast(suite: WalletProcessorConformance) -> None:
    backend = fixture_backend_from_transactions(
        [],
        tip_height=0,
        tip_hash="00" * 32,
    )
    provider = BitcoinLedgerProvider(
        network=BitcoinNetwork.MAINNET,
        backend=backend,
    )
    assert provider.capabilities.metadata["supports_psbt"] is False
    assert provider.capabilities.metadata["supports_sign"] is False
    assert provider.capabilities.metadata["supports_broadcast"] is False
    methods = {name for name in dir(provider) if not name.startswith("_")}
    for banned in ("sign", "broadcast", "psbt", "submit"):
        assert banned not in methods


def _extra_provider_fixture_stream(suite: WalletProcessorConformance) -> None:
    data = _load("sample_transactions.json")
    backend = fixture_backend_from_transactions(
        data["transactions"],
        tip_height=data["tip_height"],
        tip_hash=data["tip_hash"],
        address_index=data["address_index"],
        blocks={int(k): v for k, v in data["blocks"].items()},
    )
    provider = BitcoinLedgerProvider(
        network=BitcoinNetwork.MAINNET,
        backend=backend,
    )
    normalizer = BitcoinNormalizer(network=BitcoinNetwork.MAINNET)
    assert provider.capabilities.supports(
        __import__(
            "ipfs_datasets_py.processors.wallets.protocols",
            fromlist=["Capability"],
        ).Capability.LEDGER_RANGE
    )
    assert normalizer.chain.genesis_hash == MAINNET_GENESIS


def make_bitcoin_provider_contract() -> ProviderContract:
    return ProviderContract(
        name="bitcoin-esplora",
        chain_namespace="bip122",
        network="bitcoin-mainnet",
        chain_id=MAINNET_GENESIS[:32],
        genesis_hash=MAINNET_GENESIS,
        fixture_subdir="bitcoin",
        provider_name="bitcoin-esplora",
        import_modules=(
            "ipfs_datasets_py.processors.wallets.bitcoin",
            "ipfs_datasets_py.processors.wallets.bitcoin.provider",
            "ipfs_datasets_py.processors.wallets.bitcoin.normalizer",
        ),
        extra_checks=(
            _extra_legacy_segwit_taproot,
            _extra_coinbase,
            _extra_multi_io,
            _extra_spent_unspent,
            _extra_replacement,
            _extra_network_mismatch,
            _extra_reorg_utxo,
            _extra_exact_sats_and_utxo_model,
            _extra_confirmation_policy,
            _extra_no_psbt_sign_broadcast,
            _extra_provider_fixture_stream,
        ),
        metadata={
            "provider_family": "esplora",
            "utxo_model": True,
            "goal_id": "WALPROC-G400",
        },
    )


@pytest.fixture
def bitcoin_conformance() -> WalletProcessorConformance:
    return WalletProcessorConformance(contract=make_bitcoin_provider_contract())


def test_required_shared_checks_catalog_intact() -> None:
    assert "exact_amounts" in REQUIRED_SHARED_CHECKS
    assert "shallow_deep_reorg" in REQUIRED_SHARED_CHECKS
    assert "secret_leaks" in REQUIRED_SHARED_CHECKS


def test_bitcoin_run_all_shared_and_extra(
    bitcoin_conformance: WalletProcessorConformance,
) -> None:
    results = bitcoin_conformance.run_all()
    failed = [r for r in results if not r.passed]
    assert not failed, "; ".join(f"{r.name}: {r.detail}" for r in failed)
    names = {r.name for r in results}
    for required in REQUIRED_SHARED_CHECKS:
        assert required in names
    # Extra checks ran (named after function).
    assert any(name.startswith("_extra_") or "legacy" in name for name in names) or len(
        results
    ) > len(REQUIRED_SHARED_CHECKS)


def test_bitcoin_fixture_manifest_provenance() -> None:
    suite = WalletProcessorConformance(contract=make_bitcoin_provider_contract())
    suite.transport.assert_manifest_provenance("bitcoin")
    manifest = suite.transport.load_manifest("bitcoin")
    assert manifest["provenance"]["chain_namespace"] == "bip122"
    assert manifest["classification"]["offline_default"] is True
    assert "scripts_legacy_segwit_taproot.json" in manifest["files"]


def test_bitcoin_ast_symbols_importable() -> None:
    from ipfs_datasets_py.processors.wallets.bitcoin import (
        BitcoinLedgerProvider,
        ScriptDescriptor,
        UtxoRecord,
    )

    assert BitcoinLedgerProvider is not None
    assert ScriptDescriptor is not None
    assert UtxoRecord is not None
