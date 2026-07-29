"""Normalizer, delivered_amount, outcomes, marker pagination, continuity."""

from __future__ import annotations

import asyncio

import pytest

from ipfs_datasets_py.processors.wallets.errors import ProviderError
from ipfs_datasets_py.processors.wallets.models import (
    Finality,
    TransactionRecord,
    TransactionStatus,
    TransferKind,
    TransferRecord,
)
from ipfs_datasets_py.processors.wallets.protocols import (
    BoundedRequest,
    OperationContext,
    RequestLimits,
)
from ipfs_datasets_py.processors.wallets.xrpl import (
    MemoPrivacyPolicy,
    TxOutcome,
    XRPLFinalityPolicy,
    XRPLLedgerProvider,
    XRPLNetwork,
    XRPLNormalizer,
    XRPLWalletProcessor,
    delivered_amount,
    fixture_backend_from_account_tx,
    parse_account_tx_entry,
)


def test_partial_payment_delivered_amount(load_fixture, context, processor) -> None:
    data = load_fixture("partial_payment_delivered_amount.json")
    entry = data["entry"]
    native = parse_account_tx_entry(entry, network=XRPLNetwork.MAINNET)
    assert native.partial_payment is True
    assert native.amount is not None
    assert native.amount.value == data["expect"]["requested_drops"]
    assert native.delivered_amount is not None
    assert native.delivered_amount.value == data["expect"]["delivered_drops"]

    # Helper matches meta.delivered_amount.
    resolved = delivered_amount(entry["tx"], entry["meta"])
    assert resolved is not None
    assert resolved.value == data["expect"]["delivered_drops"]

    records = processor.normalize_transactions([entry], context=context)
    transfers = [
        r
        for r in records
        if isinstance(r, TransferRecord) and r.transfer_kind is TransferKind.NATIVE
    ]
    assert len(transfers) == 1
    assert transfers[0].amount.base_units == data["expect"]["transfer_base_units"]
    # Must not use requested Amount.
    assert transfers[0].amount.base_units != data["expect"]["requested_drops"]


def test_issued_currency_identity(load_fixture, context, processor) -> None:
    data = load_fixture("issued_currency_trustline.json")
    records = processor.normalize_transactions([data["entry"]], context=context)
    token_transfers = [
        r
        for r in records
        if isinstance(r, TransferRecord) and r.transfer_kind is TransferKind.TOKEN
    ]
    assert len(token_transfers) == 1
    asset = token_transfers[0].asset
    assert asset.asset_namespace == data["expect"]["asset_namespace"]
    assert data["expect"]["currency"] in asset.asset_reference
    assert data["expect"]["issuer"] in asset.asset_reference


def test_destination_tag_and_memos(load_fixture, context) -> None:
    data = load_fixture("destination_tag_and_memos.json")
    native = parse_account_tx_entry(data["entry"], network=XRPLNetwork.MAINNET)
    assert native.destination_tag == data["expect"]["destination_tag"]
    assert native.source_tag == data["expect"]["source_tag"]
    assert len(native.memos) == data["expect"]["memo_count"]
    assert native.memos[0].memo_type is not None
    assert native.memos[0].memo_data is not None

    redacted = parse_account_tx_entry(
        data["entry"],
        network=XRPLNetwork.MAINNET,
        privacy=MemoPrivacyPolicy(redact_memo_data=True),
    )
    assert redacted.memos[0].data_redacted is True
    assert redacted.memos[0].memo_data is None
    assert redacted.memos[0].memo_type is not None


def test_outcomes_remain_distinct(load_fixture, context, processor) -> None:
    data = load_fixture("outcomes_validated_failed_unknown.json")
    policy = XRPLFinalityPolicy(network=XRPLNetwork.MAINNET)
    seen_outcomes: set[str] = set()
    for case in data["cases"]:
        native = parse_account_tx_entry(case["entry"], network=XRPLNetwork.MAINNET)
        assert native.outcome.value == case["expect_outcome"]
        seen_outcomes.add(native.outcome.value)
        assert policy.finality_for_transaction(native).value == case["expect_finality"]
        records = processor.normalize_transactions([case["entry"]], context=context)
        txs = [r for r in records if isinstance(r, TransactionRecord)]
        assert len(txs) == 1
        assert txs[0].status.value == case["expect_status"]
        assert txs[0].finality.value == case["expect_finality"]
    # Distinct classes present.
    assert TxOutcome.VALIDATED_SUCCESS.value in seen_outcomes
    assert TxOutcome.VALIDATED_FAILED.value in seen_outcomes
    assert TxOutcome.UNVALIDATED.value in seen_outcomes
    assert TxOutcome.UNKNOWN.value in seen_outcomes


def test_marker_pagination_no_gaps_or_duplicates(load_fixture) -> None:
    data = load_fixture("account_tx_marker_pages.json")
    account = data["account"]
    backend = fixture_backend_from_account_tx(
        data["pages"],
        account=account,
        ledger_head=data["ledger_head"],
    )
    provider = XRPLLedgerProvider(
        network=XRPLNetwork.MAINNET,
        backend=backend,
        page_size=2,
    )
    context = OperationContext(
        request_id="marker-test",
        limits=RequestLimits(max_items=100, max_pages=10, max_requests=20),
    )
    request = BoundedRequest(scope=account, context=context)

    async def _collect():
        hashes: list[str] = []
        pages = 0
        async for batch in provider.ingest_wallet(request):
            pages += 1
            for rec in batch.records:
                hashes.append(rec.hash)
        return pages, hashes

    pages, hashes = asyncio.run(_collect())
    assert pages == data["expect"]["page_count"]
    assert len(hashes) == data["expect"]["total_transactions"]
    assert len(set(hashes)) == len(hashes)
    assert hashes == [h.upper() for h in data["expect"]["hashes_in_order"]]


def test_ledger_hash_continuity(load_fixture) -> None:
    data = load_fixture("ledger_hash_continuity.json")
    ledgers = {int(k): v for k, v in data["ledgers"].items()}
    backend = fixture_backend_from_account_tx(
        [],
        account="rhzFipyh5UsycxUjaPzR1RkTJZp9VybKAz",
        ledgers=ledgers,
    )
    provider = XRPLLedgerProvider(network=XRPLNetwork.MAINNET, backend=backend)
    context = OperationContext(
        request_id="continuity-test",
        limits=RequestLimits(max_items=100, max_pages=10, max_requests=20),
    )
    request = BoundedRequest(
        scope="ledger-range",
        context=context,
        start_position=data["start_index"],
        end_position=data["end_index"],
    )

    async def _collect():
        total = 0
        async for batch in provider.ingest_ledger(request):
            total += len(batch.records)
        return total

    assert asyncio.run(_collect()) == data["expect"]["tx_count"]

    # Broken parent_hash must fail closed.
    broken = dict(ledgers)
    broken[data["end_index"]] = data["broken_ledger"]
    bad_backend = fixture_backend_from_account_tx(
        [],
        account="rhzFipyh5UsycxUjaPzR1RkTJZp9VybKAz",
        ledgers=broken,
    )
    bad_provider = XRPLLedgerProvider(network=XRPLNetwork.MAINNET, backend=bad_backend)

    async def _broken():
        async for _ in bad_provider.ingest_ledger(request):
            pass

    with pytest.raises(ProviderError, match="continuity"):
        asyncio.run(_broken())


def test_only_validated_is_final(load_fixture) -> None:
    data = load_fixture("outcomes_validated_failed_unknown.json")
    policy = XRPLFinalityPolicy(network=XRPLNetwork.MAINNET)
    for case in data["cases"]:
        native = parse_account_tx_entry(case["entry"], network=XRPLNetwork.MAINNET)
        finality = policy.finality_for_transaction(native)
        if case["expect_outcome"] == "validated_success":
            assert finality is Finality.FINALIZED
        else:
            assert finality is not Finality.FINALIZED


def test_processor_ingest_wallet_normalizes(load_fixture) -> None:
    data = load_fixture("account_tx_marker_pages.json")
    backend = fixture_backend_from_account_tx(
        data["pages"],
        account=data["account"],
        ledger_head=data["ledger_head"],
    )
    provider = XRPLLedgerProvider(network=XRPLNetwork.MAINNET, backend=backend)
    processor = XRPLWalletProcessor(network=XRPLNetwork.MAINNET, provider=provider)
    context = OperationContext(
        request_id="proc-ingest",
        limits=RequestLimits(max_items=100, max_pages=10, max_requests=20),
    )
    request = BoundedRequest(scope=data["account"], context=context)

    async def _run():
        count = 0
        async for batch in processor.ingest_wallet(request):
            for rec in batch.records:
                if isinstance(rec, TransactionRecord):
                    count += 1
                    assert rec.finality is Finality.FINALIZED
        return count

    assert asyncio.run(_run()) == 3


def test_normalizer_capabilities_exclude_xaman() -> None:
    normalizer = XRPLNormalizer(network=XRPLNetwork.MAINNET)
    assert normalizer.capabilities.metadata.get("xaman_payloads") is False
    assert normalizer.capabilities.metadata.get("supports_sign") is False
