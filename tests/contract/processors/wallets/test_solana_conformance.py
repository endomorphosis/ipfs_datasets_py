"""Solana shared and chain-native conformance (WALPROC-G500/WALPROC-020)."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from ipfs_datasets_py.processors.wallets.errors import ProviderError
from ipfs_datasets_py.processors.wallets.models import (
    ContractEventRecord,
    Finality,
    TokenAccountRecord,
    TransactionRecord,
    TransactionStatus,
    TransferRecord,
)
from ipfs_datasets_py.processors.wallets.protocols import (
    BoundedRequest,
    OperationContext,
    RequestLimits,
)
from ipfs_datasets_py.processors.wallets.solana import (
    SOLANA_MAINNET,
    SOLANA_MAINNET_GENESIS_HASH,
    MissingSolanaSlotError,
    SolanaLedgerProvider,
    SolanaNormalizer,
)
from ipfs_datasets_py.tests.contract.processors.wallets.conformance import (
    REQUIRED_SHARED_CHECKS,
    FixtureTransport,
    ProviderContract,
    WalletProcessorConformance,
)


FIXTURE_DIR = (
    Path(__file__).resolve().parents[3] / "fixtures" / "wallets" / "solana"
)
SESSION = json.loads((FIXTURE_DIR / "rpc_session.json").read_text(encoding="utf-8"))


class _FixtureRpc:
    async def json_rpc(
        self,
        url: str,
        method: str,
        params: Mapping[str, object] | Sequence[object],
        *,
        context: OperationContext,
        request_id: int | str = 1,
        headers: Mapping[str, str] | None = None,
    ) -> object:
        del url, request_id, headers
        context.check_active()
        arguments = tuple(params)
        if method == "getGenesisHash":
            return SESSION["network"]["genesis_hash"]
        if method == "getSlot":
            return SESSION["slots"][arguments[0]["commitment"]]
        if method == "getBlock":
            return SESSION["blocks"].get(str(arguments[0]))
        if method == "getTransaction":
            return SESSION["transactions"].get(str(arguments[0]))
        if method == "getBalance":
            return {"context": {"slot": 100}, "value": 18446744073709551615}
        if method == "getSignaturesForAddress":
            before = arguments[1].get("before")
            if before is None:
                return SESSION["signature_pages"]["first"]
            if before == SESSION["signatures"]["failed_legacy"]:
                return SESSION["signature_pages"]["after_failed"]
            return []
        raise ProviderError(f"fixture has no response for {method}")


def _context(request_id: str = "solana-conformance") -> OperationContext:
    return OperationContext(
        request_id,
        limits=RequestLimits(
            max_items=100,
            max_pages=10,
            max_requests=30,
            max_response_bytes=2_000_000,
        ),
    )


def _extra_fixture_ingestion_and_normalization(
    _suite: WalletProcessorConformance,
) -> None:
    provider = SolanaLedgerProvider(
        _FixtureRpc(),
        endpoint="https://fixture.invalid",
        network=SOLANA_MAINNET,
    )

    async def collect() -> tuple[object, ...]:
        request = BoundedRequest(
            scope=SESSION["addresses"]["alice"],
            context=_context(),
            options={"page_size": 2, "commitment": "finalized"},
        )
        return tuple(
            bundle
            for batch in [batch async for batch in provider.ingest_wallet(request)]
            for bundle in batch.records
        )

    bundles = asyncio.run(collect())
    assert len(bundles) == 2
    normalizer = SolanaNormalizer(
        SOLANA_MAINNET,
        clock=lambda: datetime(2026, 7, 29, tzinfo=timezone.utc),
    )
    records = normalizer.normalize(bundles, context=_context("normalize"))
    transactions = [
        item for item in records if isinstance(item, TransactionRecord)
    ]
    assert {item.status for item in transactions} == {
        TransactionStatus.SUCCEEDED,
        TransactionStatus.FAILED,
    }
    assert all(item.finality is Finality.FINALIZED for item in transactions)
    transfers = [item for item in records if isinstance(item, TransferRecord)]
    assert {item.amount.base_units for item in transfers} >= {
        "18446744073709551615",
        "900719925474099312345",
    }
    events = [item for item in records if isinstance(item, ContractEventRecord)]
    assert any(
        item.extensions["solana"].data["inner_index"] == 0 for item in events
    )
    assert any(isinstance(item, TokenAccountRecord) for item in records)
    assert all(callable(getattr(item, "to_dict", None)) for item in records)


def _extra_finalized_checkpoint_and_skipped_slot(
    _suite: WalletProcessorConformance,
) -> None:
    provider = SolanaLedgerProvider(
        _FixtureRpc(), endpoint="https://fixture.invalid"
    )
    checkpoint = asyncio.run(
        provider.finalized_checkpoint(
            "wallet:fixture", context=_context("checkpoint")
        )
    )
    assert checkpoint.anchor.sequence == SESSION["slots"]["finalized"]
    assert checkpoint.anchor.block_hash == SESSION["blocks"]["100"]["blockhash"]

    async def skipped() -> None:
        request = BoundedRequest(
            scope="ledger",
            context=_context("skipped"),
            start_position=SESSION["slots"]["skipped"],
            end_position=SESSION["slots"]["skipped"],
        )
        async for _ in provider.ingest_ledger(request):
            raise AssertionError("skipped slot must not yield")

    with pytest.raises(MissingSolanaSlotError):
        asyncio.run(skipped())


def _extra_read_only_and_optional_nft_projection(
    _suite: WalletProcessorConformance,
) -> None:
    provider = SolanaLedgerProvider(
        _FixtureRpc(), endpoint="https://fixture.invalid"
    )
    assert provider.capabilities.metadata["read_only"] is True
    assert provider.capabilities.metadata["nft_enrichment"] == "optional_projection"
    assert provider.capabilities.metadata["supports_sign"] is False
    for forbidden in ("sign", "submit", "broadcast", "send_transaction"):
        assert not hasattr(provider, forbidden)


def make_solana_provider_contract() -> ProviderContract:
    return ProviderContract(
        name="solana-json-rpc",
        chain_namespace="solana",
        network="solana-mainnet-beta",
        chain_id="mainnet-beta",
        genesis_hash=SOLANA_MAINNET_GENESIS_HASH,
        fixture_subdir="solana",
        provider_name="solana-json-rpc",
        import_modules=(
            "ipfs_datasets_py.processors.wallets.solana",
            "ipfs_datasets_py.processors.wallets.solana.models",
            "ipfs_datasets_py.processors.wallets.solana.provider",
            "ipfs_datasets_py.processors.wallets.solana.normalizer",
            "ipfs_datasets_py.processors.wallets.solana.finality",
        ),
        extra_checks=(
            _extra_fixture_ingestion_and_normalization,
            _extra_finalized_checkpoint_and_skipped_slot,
            _extra_read_only_and_optional_nft_projection,
        ),
        metadata={
            "goal_id": "WALPROC-G500",
            "read_only": True,
            "nft_enrichment": "optional_projection",
        },
    )


@pytest.fixture
def solana_conformance() -> WalletProcessorConformance:
    return WalletProcessorConformance(contract=make_solana_provider_contract())


def test_solana_runs_every_shared_and_chain_native_check(
    solana_conformance: WalletProcessorConformance,
) -> None:
    results = solana_conformance.run_all()
    assert all(item.passed for item in results)
    names = {item.name for item in results}
    assert REQUIRED_SHARED_CHECKS <= names
    assert len(results) == len(REQUIRED_SHARED_CHECKS) + 3


def test_solana_fixture_manifest_is_active_and_complete() -> None:
    transport = FixtureTransport()
    transport.assert_manifest_provenance("solana")
    manifest = transport.load_manifest("solana")
    assert manifest["goal_id"] == "WALPROC-G500"
    assert manifest["task_id"] == "WALPROC-020"
    assert manifest["classification"]["status"] == "active"
    assert {
        "signature_pagination_no_gaps_or_duplicates",
        "legacy_and_versioned_transactions",
        "address_lookup_tables",
        "failed_transaction_visibility",
        "outer_and_inner_instruction_coordinates",
        "exact_lamport_and_spl_amounts",
        "processed_confirmed_finalized_distinction",
        "skipped_slot_fail_closed",
        "finalized_slot_blockhash_checkpoint",
        "read_only_surface",
        "optional_nft_projection",
    } <= set(manifest["coverage"])
    for filename in manifest["files"]:
        assert (FIXTURE_DIR / filename).is_file()


def test_solana_ast_evidence_symbols_are_importable() -> None:
    from ipfs_datasets_py.processors.wallets.solana import (
        SolanaLedgerProvider,
        SolanaNormalizer,
        TokenAccountRecord,
    )

    assert SolanaLedgerProvider is not None
    assert SolanaNormalizer is not None
    assert TokenAccountRecord is not None
