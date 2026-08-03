"""UTXO set, coinbase, multi-io, spend, RBF, reorg, and normalizer tests."""

from __future__ import annotations

import asyncio

import pytest

from ipfs_datasets_py.processors.wallets.bitcoin import (
    BitcoinFinalityPolicy,
    BitcoinLedgerProvider,
    BitcoinNetwork,
    BitcoinNormalizer,
    BitcoinWalletProcessor,
    UtxoSet,
    fixture_backend_from_transactions,
    parse_esplora_transaction,
    seed_utxo,
    describe_script,
)
from ipfs_datasets_py.processors.wallets.bitcoin.utxo_set import seed_utxo as seed_utxo_fn
from ipfs_datasets_py.processors.wallets.finality import CanonicalHistory, ReorgKind
from ipfs_datasets_py.processors.wallets.checkpoints import HashAnchor
from ipfs_datasets_py.processors.wallets.models import (
    Finality,
    TransferKind,
    TransferRecord,
    UTXORecord,
)
from ipfs_datasets_py.processors.wallets.protocols import (
    BoundedRequest,
    OperationContext,
    RequestLimits,
)
from ipfs_datasets_py.tests.unit.processors.wallets.bitcoin.conftest import seed_from_mapping


def test_coinbase_fixture(load_fixture, context, processor) -> None:
    data = load_fixture("coinbase.json")
    records = processor.normalize_transactions(
        [data["transaction"]],
        context=context,
        head_height=100,
        apply_utxos=True,
        allow_missing_inputs=True,
    )
    transfers = [r for r in records if isinstance(r, TransferRecord)]
    assert any(t.transfer_kind is TransferKind.REWARD for t in transfers)
    utxos = [r for r in records if isinstance(r, UTXORecord)]
    assert len(utxos) == 1
    assert utxos[0].amount.base_units == "5000000000"
    assert processor.balance_sats("1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa") == 5_000_000_000


def test_multi_input_output(load_fixture, context, processor) -> None:
    data = load_fixture("multi_input_output.json")
    for item in data["seed_utxos"]:
        seed_from_mapping(processor.utxos, item)
    records = processor.normalize_transactions(
        [data["transaction"]],
        context=context,
        head_height=840010,
        apply_utxos=True,
    )
    fee_transfers = [
        r
        for r in records
        if isinstance(r, TransferRecord) and r.transfer_kind is TransferKind.FEE
    ]
    assert len(fee_transfers) == 1
    assert fee_transfers[0].amount.base_units == str(data["expect"]["fee_sats"])
    # UTXO-driven balances: source seeds spent, destinations funded.
    assert processor.balance_sats("bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t4") == 25000
    assert (
        processor.balance_sats(
            "bc1p5cyxnuxmeuwuvkwfem96lqzszd02n6xdcjrs20cac6yqjjwudpxqkedrcr"
        )
        == 120000
    )


def test_spent_unspent(load_fixture, context, processor) -> None:
    data = load_fixture("spent_unspent.json")
    processor.normalize_transactions(
        [data["create_tx"]], context=context, head_height=200, apply_utxos=True
    )
    assert (
        processor.balance_sats(data["address"])
        == data["expect_after_create"]["balance_address"]
    )
    processor.normalize_transactions(
        [data["spend_tx"]], context=context, head_height=200, apply_utxos=True
    )
    assert (
        processor.balance_sats(data["address"])
        == data["expect_after_spend"]["balance_address"]
    )
    spent = processor.utxos.get(data["expect_after_spend"]["spent_outpoint"])
    assert spent is not None and spent.is_spent


def test_replacement_rbf(load_fixture, context, processor) -> None:
    data = load_fixture("replacement_rbf.json")
    seed_from_mapping(processor.utxos, data["seed_utxo"])
    processor.normalize_transactions(
        [data["original"]], context=context, apply_utxos=True
    )
    processor.normalize_transactions(
        [data["replacement"]], context=context, apply_utxos=True
    )
    assert (
        processor.balance_sats("1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa")
        == data["expect_after_replacement"]["balance_destination"]
    )
    # Seed outpoint remains spent by the replacement, not double-spent.
    seed_key = f"{data['seed_utxo']['txid']}:0"
    entry = processor.utxos.get(seed_key)
    assert entry is not None and entry.spent_by == data["replacement"]["txid"]


def test_reorg_reverses_utxo_effects(load_fixture, context, processor) -> None:
    data = load_fixture("reorg_utxo.json")
    seed_from_mapping(processor.utxos, data["seed_utxo"])
    processor.normalize_transactions(
        [data["orphaned_tx"]], context=context, head_height=201, apply_utxos=True
    )
    expect = data["expect"]
    assert (
        processor.balance_sats("bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t4")
        == expect["after_orphan_apply"]["balance_source"]
    )
    assert (
        processor.balance_sats(
            "bc1p5cyxnuxmeuwuvkwfem96lqzszd02n6xdcjrs20cac6yqjjwudpxqkedrcr"
        )
        == expect["after_orphan_apply"]["balance_taproot"]
    )

    reversed_ids = processor.reverse_from_height(201)
    assert data["orphaned_tx"]["txid"] in reversed_ids
    assert (
        processor.balance_sats("bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t4")
        == expect["after_reorg_reverse"]["balance_source"]
    )
    assert (
        processor.balance_sats(
            "bc1p5cyxnuxmeuwuvkwfem96lqzszd02n6xdcjrs20cac6yqjjwudpxqkedrcr"
        )
        == expect["after_reorg_reverse"]["balance_taproot"]
    )

    processor.normalize_transactions(
        [data["replacement_tx"]], context=context, head_height=202, apply_utxos=True
    )
    assert (
        processor.balance_sats("1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa")
        == expect["after_replacement_apply"]["balance_legacy"]
    )


def test_balances_are_utxo_not_account_debits(context, processor) -> None:
    # No implicit account ledger: empty set is zero without debits.
    assert processor.balance_sats() == 0
    assert processor.utxos.balances_by_address() == {}


def test_no_ownership_clustering_metadata(context, processor, load_fixture) -> None:
    data = load_fixture("coinbase.json")
    records = processor.normalize_transactions(
        [data["transaction"]], context=context, apply_utxos=False
    )
    # Transaction-level extension explicitly refuses clustering; UTXO rows
    # carry script metadata only.
    from ipfs_datasets_py.processors.wallets.models import TransactionRecord

    tx_records = [r for r in records if isinstance(r, TransactionRecord)]
    assert tx_records
    bitcoin_ext = tx_records[0].extensions["bitcoin"]
    assert bitcoin_ext.data.get("ownership_clustering") is False
    assert processor.capabilities.metadata.get("ownership_clustering") is False


def test_confirmation_threshold_is_policy() -> None:
    strict = BitcoinFinalityPolicy(
        network=BitcoinNetwork.MAINNET,
    )
    loose = BitcoinFinalityPolicy(
        network=BitcoinNetwork.MAINNET,
    )
    # Defaults differ by design from "universal truth"; operator can change.
    assert strict.thresholds.safe == 6
    assert strict.finality_for_confirmations(0) is Finality.OBSERVED
    assert strict.finality_for_confirmations(1) is Finality.CONFIRMED
    assert strict.finality_for_confirmations(6) is Finality.SAFE
    assert strict.finality_for_confirmations(100) is Finality.FINALIZED
    assert loose.thresholds.finalized is not None


def test_finality_reorg_classification(load_fixture, context) -> None:
    data = load_fixture("reorg_utxo.json")
    policy = BitcoinFinalityPolicy(network=BitcoinNetwork.MAINNET, max_reorg_depth=10)
    from ipfs_datasets_py.processors.wallets.checkpoints import (
        CheckpointIdentity,
        build_checkpoint,
    )
    from ipfs_datasets_py.processors.wallets.bitcoin import chain_ref_for

    chain = chain_ref_for(BitcoinNetwork.MAINNET)
    local_pairs = [(item["sequence"], item["hash"]) for item in data["local_history"]]
    remote = CanonicalHistory.from_pairs(
        [(item["sequence"], item["hash"]) for item in data["remote_history"]]
    )
    identity = CheckpointIdentity(
        chain=chain,
        provider="bitcoin-test",
        scope="reorg",
        normalized_schema_major=1,
        normalizer_version="test",
    )
    tip = data["local_history"][-1]
    prior = tuple(HashAnchor(seq, h) for seq, h in local_pairs[:-1])
    checkpoint = build_checkpoint(
        identity=identity,
        sequence=tip["sequence"],
        block_hash=tip["hash"],
        prior_history=prior,
    )
    observed = HashAnchor(
        data["remote_history"][-1]["sequence"],
        data["remote_history"][-1]["hash"],
    )
    decision = policy.evaluate_reorg(
        checkpoint,
        observed_anchor=observed,
        context=context,
        remote_history=remote,
    )
    assert decision.kind is ReorgKind.SHALLOW
    assert decision.common_ancestor is not None
    assert decision.common_ancestor.sequence == 200


def test_provider_wallet_ingest(load_fixture, context) -> None:
    data = load_fixture("sample_transactions.json")
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
    processor = BitcoinWalletProcessor(
        network=BitcoinNetwork.MAINNET,
        provider=provider,
    )

    async def _run():
        request = BoundedRequest(
            scope="bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t4",
            context=context,
        )
        batches = []
        async for batch in processor.ingest_wallet(request):
            batches.append(batch)
        return batches

    batches = asyncio.run(_run())
    assert batches
    assert any(batch.records for batch in batches)
    # Change output remains; payment moved to taproot.
    assert processor.balance_sats("bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t4") == 5000


def test_provider_rejects_network_mismatch_address(load_fixture) -> None:
    data = load_fixture("sample_transactions.json")
    backend = fixture_backend_from_transactions(
        data["transactions"],
        tip_height=data["tip_height"],
        tip_hash=data["tip_hash"],
    )
    provider = BitcoinLedgerProvider(
        network=BitcoinNetwork.MAINNET,
        backend=backend,
    )
    ctx = OperationContext(request_id="mm", limits=RequestLimits())

    async def _run():
        with pytest.raises(Exception):
            await provider.validate_address(
                "tb1qw508d6qejxtdg4y5r3zarvary0c5xw7kxpjzsx",
                context=ctx,
            )

    asyncio.run(_run())


def test_normalizer_projects_utxo_records(load_fixture, context) -> None:
    data = load_fixture("multi_input_output.json")
    normalizer = BitcoinNormalizer(network=BitcoinNetwork.MAINNET)
    records = normalizer.normalize(
        [data["transaction"]],
        context=context,
        head_height=840010,
    )
    utxos = [r for r in records if isinstance(r, UTXORecord)]
    assert len(utxos) >= 2
    for utxo in utxos:
        assert utxo.amount.decimals == 8
        assert not utxo.amount.base_units.startswith("-")


def test_parse_esplora_transaction_roundtrip(load_fixture) -> None:
    data = load_fixture("coinbase.json")
    tx = parse_esplora_transaction(data["transaction"], network=BitcoinNetwork.MAINNET)
    assert tx.is_coinbase
    assert tx.outputs[0].value_sats == 5_000_000_000
