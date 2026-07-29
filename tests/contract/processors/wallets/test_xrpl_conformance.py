"""XRPL chain conformance suite (WALPROC-G200 / WALPROC-017).

Extends the shared :class:`WalletProcessorConformance` harness with XRPL
fixture-driven checks. Extra checks cannot remove shared required coverage.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from ipfs_datasets_py.processors.wallets.models import (
    Finality,
    TransferKind,
    TransferRecord,
    TransactionRecord,
)
from ipfs_datasets_py.processors.wallets.protocols import (
    BoundedRequest,
    OperationContext,
    RequestLimits,
)
from ipfs_datasets_py.processors.wallets.xrpl import (
    MAINNET_GENESIS,
    MemoPrivacyPolicy,
    XRPLFinalityPolicy,
    XRPLLedgerProvider,
    XRPLNetwork,
    XRPLNormalizer,
    XRPLWalletProcessor,
    delivered_amount,
    fixture_backend_from_account_tx,
    parse_account_tx_entry,
)
from ipfs_datasets_py.tests.contract.processors.wallets.conformance import (
    REQUIRED_SHARED_CHECKS,
    ProviderContract,
    WalletProcessorConformance,
)

_FIXTURE_DIR = Path(__file__).resolve().parents[3] / "fixtures" / "wallets" / "xrpl"


def _load(name: str) -> dict:
    with (_FIXTURE_DIR / name).open(encoding="utf-8") as handle:
        return json.load(handle)


def _context() -> OperationContext:
    return OperationContext(
        request_id="xrpl-conformance",
        limits=RequestLimits(max_items=500, max_pages=20, max_requests=50),
    )


def _extra_marker_pagination(suite: WalletProcessorConformance) -> None:
    data = _load("account_tx_marker_pages.json")
    backend = fixture_backend_from_account_tx(
        data["pages"],
        account=data["account"],
        ledger_head=data["ledger_head"],
    )
    provider = XRPLLedgerProvider(
        network=XRPLNetwork.MAINNET, backend=backend, page_size=2
    )
    request = BoundedRequest(scope=data["account"], context=_context())

    async def _collect():
        hashes: list[str] = []
        async for batch in provider.ingest_wallet(request):
            for rec in batch.records:
                hashes.append(rec.hash)
        return hashes

    hashes = asyncio.run(_collect())
    assert len(hashes) == len(set(hashes))
    assert hashes == [h.upper() for h in data["expect"]["hashes_in_order"]]


def _extra_delivered_amount(suite: WalletProcessorConformance) -> None:
    data = _load("partial_payment_delivered_amount.json")
    entry = data["entry"]
    resolved = delivered_amount(entry["tx"], entry["meta"])
    assert resolved is not None
    assert resolved.value == data["expect"]["delivered_drops"]
    processor = XRPLWalletProcessor(network=XRPLNetwork.MAINNET)
    records = processor.normalize_transactions([entry], context=_context())
    transfers = [
        r
        for r in records
        if isinstance(r, TransferRecord) and r.transfer_kind is TransferKind.NATIVE
    ]
    assert transfers[0].amount.base_units == data["expect"]["transfer_base_units"]


def _extra_issued_asset_identity(suite: WalletProcessorConformance) -> None:
    data = _load("issued_currency_trustline.json")
    processor = XRPLWalletProcessor(network=XRPLNetwork.MAINNET)
    records = processor.normalize_transactions([data["entry"]], context=_context())
    token = [
        r
        for r in records
        if isinstance(r, TransferRecord) and r.transfer_kind is TransferKind.TOKEN
    ]
    assert len(token) == 1
    assert data["expect"]["issuer"] in token[0].asset.asset_reference
    assert data["expect"]["currency"] in token[0].asset.asset_reference


def _extra_tags_memos_privacy(suite: WalletProcessorConformance) -> None:
    data = _load("destination_tag_and_memos.json")
    native = parse_account_tx_entry(data["entry"], network=XRPLNetwork.MAINNET)
    assert native.destination_tag == data["expect"]["destination_tag"]
    assert len(native.memos) == 1
    redacted = parse_account_tx_entry(
        data["entry"],
        network=XRPLNetwork.MAINNET,
        privacy=MemoPrivacyPolicy(redact_memo_data=True),
    )
    assert redacted.memos[0].data_redacted is True
    assert redacted.memos[0].memo_type is not None


def _extra_outcomes_distinct(suite: WalletProcessorConformance) -> None:
    data = _load("outcomes_validated_failed_unknown.json")
    policy = XRPLFinalityPolicy(network=XRPLNetwork.MAINNET)
    outcomes = set()
    for case in data["cases"]:
        native = parse_account_tx_entry(case["entry"], network=XRPLNetwork.MAINNET)
        outcomes.add(native.outcome.value)
        assert policy.finality_for_transaction(native).value == case["expect_finality"]
    assert outcomes >= {
        "validated_success",
        "validated_failed",
        "unvalidated",
        "unknown",
    }


def _extra_validated_only_final(suite: WalletProcessorConformance) -> None:
    data = _load("outcomes_validated_failed_unknown.json")
    policy = XRPLFinalityPolicy(network=XRPLNetwork.MAINNET)
    for case in data["cases"]:
        native = parse_account_tx_entry(case["entry"], network=XRPLNetwork.MAINNET)
        finality = policy.finality_for_transaction(native)
        if case["id"] == "validated_success":
            assert finality is Finality.FINALIZED
        else:
            assert finality is not Finality.FINALIZED


def _extra_ledger_continuity(suite: WalletProcessorConformance) -> None:
    data = _load("ledger_hash_continuity.json")
    ledgers = {int(k): v for k, v in data["ledgers"].items()}
    backend = fixture_backend_from_account_tx(
        [],
        account="rhzFipyh5UsycxUjaPzR1RkTJZp9VybKAz",
        ledgers=ledgers,
    )
    provider = XRPLLedgerProvider(network=XRPLNetwork.MAINNET, backend=backend)
    request = BoundedRequest(
        scope="ledger-range",
        context=_context(),
        start_position=data["start_index"],
        end_position=data["end_index"],
    )

    async def _collect():
        total = 0
        async for batch in provider.ingest_ledger(request):
            total += len(batch.records)
        return total

    assert asyncio.run(_collect()) == data["expect"]["tx_count"]


def _extra_no_sign_submit_xaman(suite: WalletProcessorConformance) -> None:
    backend = fixture_backend_from_account_tx(
        [],
        account="rhzFipyh5UsycxUjaPzR1RkTJZp9VybKAz",
        ledger_head={
            "ledger": {
                "ledger_index": 1,
                "ledger_hash": "00" * 32,
                "parent_hash": "11" * 32,
            },
            "validated": True,
        },
    )
    provider = XRPLLedgerProvider(network=XRPLNetwork.MAINNET, backend=backend)
    assert provider.capabilities.metadata["supports_sign"] is False
    assert provider.capabilities.metadata["supports_submit"] is False
    assert provider.capabilities.metadata["xaman_payloads"] is False
    methods = {name for name in dir(provider) if not name.startswith("_")}
    for banned in ("sign", "submit", "broadcast", "xaman"):
        assert banned not in methods


def _extra_normalizer_ast_symbols(suite: WalletProcessorConformance) -> None:
    normalizer = XRPLNormalizer(network=XRPLNetwork.MAINNET)
    assert normalizer.chain.genesis_hash == MAINNET_GENESIS
    assert callable(delivered_amount)
    assert XRPLLedgerProvider is not None


def make_xrpl_provider_contract() -> ProviderContract:
    return ProviderContract(
        name="xrpl-json-rpc",
        chain_namespace="xrpl",
        network="xrpl-mainnet",
        chain_id="0",
        genesis_hash=MAINNET_GENESIS,
        fixture_subdir="xrpl",
        provider_name="xrpl-json-rpc",
        import_modules=(
            "ipfs_datasets_py.processors.wallets.xrpl",
            "ipfs_datasets_py.processors.wallets.xrpl.provider",
            "ipfs_datasets_py.processors.wallets.xrpl.normalizer",
        ),
        extra_checks=(
            _extra_marker_pagination,
            _extra_delivered_amount,
            _extra_issued_asset_identity,
            _extra_tags_memos_privacy,
            _extra_outcomes_distinct,
            _extra_validated_only_final,
            _extra_ledger_continuity,
            _extra_no_sign_submit_xaman,
            _extra_normalizer_ast_symbols,
        ),
        metadata={
            "provider_family": "xrpl-json-rpc",
            "goal_id": "WALPROC-G200",
            "xaman_payloads": False,
        },
    )


@pytest.fixture
def xrpl_conformance() -> WalletProcessorConformance:
    return WalletProcessorConformance(contract=make_xrpl_provider_contract())


def test_required_shared_checks_catalog_intact() -> None:
    assert "exact_amounts" in REQUIRED_SHARED_CHECKS
    assert "shallow_deep_reorg" in REQUIRED_SHARED_CHECKS
    assert "secret_leaks" in REQUIRED_SHARED_CHECKS


def test_xrpl_run_all_shared_and_extra(
    xrpl_conformance: WalletProcessorConformance,
) -> None:
    results = xrpl_conformance.run_all()
    failed = [r for r in results if not r.passed]
    assert not failed, "; ".join(f"{r.name}: {r.detail}" for r in failed)
    names = {r.name for r in results}
    for required in REQUIRED_SHARED_CHECKS:
        assert required in names
    assert len(results) > len(REQUIRED_SHARED_CHECKS)


def test_xrpl_fixture_manifest_provenance() -> None:
    suite = WalletProcessorConformance(contract=make_xrpl_provider_contract())
    suite.transport.assert_manifest_provenance("xrpl")
    manifest = suite.transport.load_manifest("xrpl")
    assert manifest["provenance"]["chain_namespace"] == "xrpl"
    assert manifest["classification"]["offline_default"] is True
    assert manifest["provenance"].get("xaman_payloads") is False
    assert "partial_payment_delivered_amount.json" in manifest["files"]


def test_xrpl_ast_symbols_importable() -> None:
    from ipfs_datasets_py.processors.wallets.xrpl import (
        XRPLLedgerProvider,
        XRPLNormalizer,
        delivered_amount,
    )

    assert XRPLLedgerProvider is not None
    assert XRPLNormalizer is not None
    assert callable(delivered_amount)
