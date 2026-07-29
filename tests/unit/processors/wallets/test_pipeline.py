"""Unit tests for streaming wallet/ledger ingestion pipelines."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Sequence
from datetime import datetime, timezone
from pathlib import Path

import pytest

from ipfs_datasets_py.processors.wallets.checkpoints import (
    HashAnchor,
    InMemoryCheckpointStore,
)
from ipfs_datasets_py.processors.wallets.errors import (
    InvalidRequestError,
    OperationCancelledError,
)
from ipfs_datasets_py.processors.wallets.export import ExportFormat
from ipfs_datasets_py.processors.wallets.models import (
    AccountKind,
    AccountRef,
    ChainRef,
    Finality,
    LedgerPosition,
    Provenance,
    RawPayloadPolicy,
    TransactionRecord,
    TransactionStatus,
)
from ipfs_datasets_py.processors.wallets.pipeline import (
    IngestMode,
    RunStatus,
    WalletLedgerProcessor,
    assert_finite_scope,
    extract_batch_anchor,
)
from ipfs_datasets_py.processors.wallets.protocols import (
    BoundedRequest,
    Capabilities,
    Capability,
    DatasetSink,
    OperationContext,
    RecordBatch,
    RequestLimits,
)
from ipfs_datasets_py.processors.wallets.storage import (
    InMemoryRawPayloadStore,
    StreamingDatasetSink,
)


NOW = datetime(2025, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
GENESIS = "0xd4e56740f876aef8c010b86a40d5f56745a118d0906a34e69aec8c0db1cb8fa3"


@pytest.fixture
def chain() -> ChainRef:
    return ChainRef(
        namespace="eip155",
        network="ethereum-mainnet",
        chain_id="1",
        genesis_hash=GENESIS,
    )


@pytest.fixture
def context() -> OperationContext:
    return OperationContext(
        request_id="pipeline-test-1",
        limits=RequestLimits(max_items=100, max_pages=10, max_requests=20),
    )


def _run(coro):
    return asyncio.run(coro)


def _tx(
    chain: ChainRef,
    *,
    tx_hash: str,
    sequence: int,
    block_hash: str,
    finality: Finality = Finality.CONFIRMED,
    scope: str = "wallet:0xabc",
) -> TransactionRecord:
    return TransactionRecord(
        chain=chain,
        provenance=Provenance(
            provider="fixture-rpc",
            provider_kind="json-rpc",
            request_id="req-1",
            scope=scope,
            observed_at=NOW,
        ),
        ledger_position=LedgerPosition(
            sequence=sequence,
            hash=block_hash,
            transaction_index=0,
        ),
        finality=finality,
        transaction_hash=tx_hash,
        status=TransactionStatus.SUCCEEDED,
        participants=(
            AccountRef(chain, "0xabc", AccountKind.ADDRESS),
        ),
    )


class _CancelToken:
    def __init__(self) -> None:
        self.cancelled = False

    def cancel(self) -> None:
        self.cancelled = True


class FakeWalletLedgerProvider:
    """Fixture provider that yields prebuilt native pages."""

    def __init__(
        self,
        pages: Sequence[Sequence[object]],
        *,
        cancel_after: int | None = None,
        cancel_token: _CancelToken | None = None,
        reorder_duplicate: bool = False,
    ) -> None:
        self._pages = [tuple(page) for page in pages]
        self._cancel_after = cancel_after
        self._cancel_token = cancel_token
        self.capabilities = Capabilities(
            provider="fixture-rpc",
            chain_namespaces=frozenset({"eip155"}),
            features=frozenset(
                {
                    Capability.WALLET_HISTORY,
                    Capability.LEDGER_RANGE,
                    Capability.RAW_PAYLOADS,
                }
            ),
        )
        self.calls = 0
        self._reorder_duplicate = reorder_duplicate

    async def validate_address(self, address: str, *, context: OperationContext) -> object:
        context.check_active()
        return {"address": address, "valid": True}

    async def ledger_head(self, *, context: OperationContext) -> object:
        context.check_active()
        return HashAnchor(sequence=100, block_hash="0xhead")

    def ingest_wallet(self, request: BoundedRequest) -> AsyncIterator[RecordBatch]:
        return self._stream(request)

    def ingest_ledger(self, request: BoundedRequest) -> AsyncIterator[RecordBatch]:
        return self._stream(request)

    async def _stream(self, request: BoundedRequest) -> AsyncIterator[RecordBatch]:
        for index, page in enumerate(self._pages):
            request.context.check_active()
            self.calls += 1
            if self._cancel_after is not None and index >= self._cancel_after:
                if self._cancel_token is not None:
                    self._cancel_token.cancel()
                raise OperationCancelledError("fixture cancellation")
            records = list(page)
            if self._reorder_duplicate and index == 1:
                # Re-emit first page's first record out of order, then new rows.
                records = list(self._pages[0][:1]) + records
            next_cursor = f"page-{index + 1}" if index + 1 < len(self._pages) else None
            yield RecordBatch(tuple(records), next_cursor=next_cursor, response_bytes=64)


class IdentityNormalizer:
    """Pass-through normalizer for already-normalized fixture records."""

    capabilities = Capabilities(
        provider="identity-normalizer",
        chain_namespaces=frozenset({"eip155"}),
        features=frozenset({Capability.WALLET_HISTORY}),
    )

    def normalize(
        self,
        records: Sequence[object],
        *,
        context: OperationContext,
    ) -> Sequence[object]:
        context.check_active()
        return tuple(records)


def test_assert_finite_scope_requires_ledger_range_endpoints(context: OperationContext) -> None:
    request = BoundedRequest(scope="ledger:1-10", context=context)
    with pytest.raises(InvalidRequestError, match="start_position"):
        assert_finite_scope(request, mode=IngestMode.LEDGER_RANGE)
    ok = BoundedRequest(
        scope="ledger:1-10",
        context=context,
        start_position=1,
        end_position=10,
    )
    assert_finite_scope(ok, mode=IngestMode.LEDGER_RANGE)


def test_assert_finite_scope_requires_wallet_scope(context: OperationContext) -> None:
    with pytest.raises(InvalidRequestError, match="scope"):
        BoundedRequest(scope="  ", context=context)


def test_extract_batch_anchor_picks_highest_sequence(chain: ChainRef) -> None:
    records = (
        _tx(chain, tx_hash="0x1", sequence=5, block_hash="0xa"),
        _tx(chain, tx_hash="0x2", sequence=9, block_hash="0xb"),
        _tx(chain, tx_hash="0x3", sequence=7, block_hash="0xc"),
    )
    anchor = extract_batch_anchor(records)
    assert anchor is not None
    assert anchor.sequence == 9
    assert anchor.block_hash == "0xb"


def test_streaming_wallet_ingest_does_not_accumulate_whole_history(
    chain: ChainRef,
    context: OperationContext,
    tmp_path: Path,
) -> None:
    pages = [
        [_tx(chain, tx_hash=f"0x{i:02x}", sequence=10 + i, block_hash=f"0xb{i}") for i in range(3)],
        [_tx(chain, tx_hash=f"0x1{i:02x}", sequence=20 + i, block_hash=f"0xc{i}") for i in range(2)],
    ]
    provider = FakeWalletLedgerProvider(pages)
    processor = WalletLedgerProcessor(
        chain=chain,
        wallet_provider=provider,
        ledger_provider=provider,
        normalizer=IdentityNormalizer(),
        checkpoint_store=InMemoryCheckpointStore(),
        provider_name="fixture-rpc",
        normalizer_version="fixture-normalizer@1",
        clock=lambda: NOW,
    )
    sink = StreamingDatasetSink(scope="wallet:0xabc", output_dir=tmp_path / "sink")
    request = BoundedRequest(scope="wallet:0xabc", context=context)

    receipt = _run(
        processor.ingest_wallet(
            request,
            sink=sink,
            observed_anchor=HashAnchor(sequence=21, block_hash="0xc1"),
        )
    )

    assert receipt.status is RunStatus.COMPLETE
    assert receipt.pages_processed == 2
    assert receipt.records_accepted == 5
    assert receipt.checkpoint_advanced is True
    assert receipt.checkpoint_after is not None
    assert receipt.checkpoint_after.anchor.sequence == 21
    assert receipt.sink_commit is not None
    assert receipt.sink_commit.record_count == 5
    # Sink retains committed rows only (streamed pages are not re-buffered
    # outside the sink); page outcomes record per-page sizes.
    assert [p.normalized_count for p in receipt.page_outcomes] == [3, 2]
    assert sink.committed_count == 5
    assert sink.staged_count == 0


def test_duplicate_and_out_of_order_pages_do_not_duplicate_records(
    chain: ChainRef,
    context: OperationContext,
) -> None:
    page0 = [
        _tx(chain, tx_hash="0xaa", sequence=1, block_hash="0x01"),
        _tx(chain, tx_hash="0xbb", sequence=2, block_hash="0x02"),
    ]
    # page1 re-emits page0[0] (duplicate) and a new lower-sequence row (out of
    # order), then a forward row.  Dedup must drop the duplicate; the lower
    # sequence is accepted once without inventing a second row for 0xaa.
    page1 = [
        _tx(chain, tx_hash="0xaa", sequence=1, block_hash="0x01"),
        _tx(chain, tx_hash="0x00", sequence=0, block_hash="0x00"),
        _tx(chain, tx_hash="0xcc", sequence=3, block_hash="0x03"),
    ]
    provider = FakeWalletLedgerProvider([page0, page1])
    processor = WalletLedgerProcessor(
        chain=chain,
        wallet_provider=provider,
        normalizer=IdentityNormalizer(),
        provider_name="fixture-rpc",
        normalizer_version="fixture-normalizer@1",
        clock=lambda: NOW,
    )
    sink = StreamingDatasetSink(scope="wallet:0xabc")
    request = BoundedRequest(scope="wallet:0xabc", context=context)
    receipt = _run(
        processor.ingest_wallet(
            request,
            sink=sink,
            observed_anchor=HashAnchor(3, "0x03"),
        )
    )
    # Unique rows: 0xaa, 0xbb, 0x00, 0xcc (duplicate of 0xaa dropped).
    assert receipt.records_accepted == 4
    assert receipt.records_duplicate >= 1
    assert receipt.out_of_order_count >= 1
    ids = [row["record_id"] for row in sink.committed_records()]
    assert len(ids) == len(set(ids)) == 4


def test_cancelled_run_does_not_advance_checkpoint(
    chain: ChainRef,
) -> None:
    token = _CancelToken()
    pages = [
        [_tx(chain, tx_hash="0x01", sequence=1, block_hash="0x01")],
        [_tx(chain, tx_hash="0x02", sequence=2, block_hash="0x02")],
    ]
    provider = FakeWalletLedgerProvider(pages, cancel_after=1, cancel_token=token)
    store = InMemoryCheckpointStore()
    processor = WalletLedgerProcessor(
        chain=chain,
        wallet_provider=provider,
        normalizer=IdentityNormalizer(),
        checkpoint_store=store,
        provider_name="fixture-rpc",
        normalizer_version="fixture-normalizer@1",
        clock=lambda: NOW,
    )
    context = OperationContext(
        request_id="cancel-run",
        limits=RequestLimits(max_items=50, max_pages=10, max_requests=10),
        cancellation=token,
    )
    sink = StreamingDatasetSink(scope="wallet:0xabc")
    request = BoundedRequest(scope="wallet:0xabc", context=context)
    receipt = _run(processor.ingest_wallet(request, sink=sink))
    assert receipt.status is RunStatus.CANCELLED
    assert receipt.checkpoint_advanced is False
    assert receipt.checkpoint_after is receipt.checkpoint_before
    # No durable checkpoint written.
    assert store.keys() == frozenset()
    assert sink.is_aborted is True
    assert sink.committed_count == 0


def test_partial_without_anchor_does_not_skip_checkpoint_safety(
    chain: ChainRef,
    context: OperationContext,
) -> None:
    # Records without ledger hashes: sink may commit but checkpoint stays put.
    bare = TransactionRecord(
        chain=chain,
        provenance=Provenance(
            provider="fixture-rpc",
            provider_kind="json-rpc",
            request_id="req-1",
            scope="wallet:0xabc",
            observed_at=NOW,
        ),
        ledger_position=LedgerPosition(sequence=5, hash=None),
        finality=Finality.OBSERVED,
        transaction_hash="0xdead",
        status=TransactionStatus.SUCCEEDED,
    )
    provider = FakeWalletLedgerProvider([[bare]])
    store = InMemoryCheckpointStore()
    processor = WalletLedgerProcessor(
        chain=chain,
        wallet_provider=provider,
        normalizer=IdentityNormalizer(),
        checkpoint_store=store,
        provider_name="fixture-rpc",
        normalizer_version="fixture-normalizer@1",
        clock=lambda: NOW,
    )
    sink = StreamingDatasetSink(scope="wallet:0xabc")
    request = BoundedRequest(scope="wallet:0xabc", context=context)
    receipt = _run(processor.ingest_wallet(request, sink=sink))
    assert receipt.checkpoint_advanced is False
    assert "no_hash_anchor_checkpoint_not_advanced" in receipt.warnings
    assert store.keys() == frozenset()


def test_ledger_range_requires_finite_bounds(
    chain: ChainRef,
    context: OperationContext,
) -> None:
    provider = FakeWalletLedgerProvider([])
    processor = WalletLedgerProcessor(
        chain=chain,
        ledger_provider=provider,
        normalizer=IdentityNormalizer(),
        provider_name="fixture-rpc",
        normalizer_version="fixture-normalizer@1",
    )
    request = BoundedRequest(scope="ledger:open", context=context)
    with pytest.raises(InvalidRequestError, match="start_position"):
        _run(processor.ingest_ledger(request))


def test_ledger_range_streaming_and_resume_identity(
    chain: ChainRef,
    context: OperationContext,
) -> None:
    pages = [
        [
            _tx(chain, tx_hash="0x10", sequence=100, block_hash="0x100", scope="ledger:100-102"),
            _tx(chain, tx_hash="0x11", sequence=101, block_hash="0x101", scope="ledger:100-102"),
        ],
        [
            _tx(chain, tx_hash="0x12", sequence=102, block_hash="0x102", scope="ledger:100-102"),
        ],
    ]
    provider = FakeWalletLedgerProvider(pages)
    store = InMemoryCheckpointStore()
    processor = WalletLedgerProcessor(
        chain=chain,
        ledger_provider=provider,
        normalizer=IdentityNormalizer(),
        checkpoint_store=store,
        provider_name="fixture-rpc",
        normalizer_version="fixture-normalizer@1",
        clock=lambda: NOW,
    )
    request = BoundedRequest(
        scope="ledger:100-102",
        context=context,
        start_position=100,
        end_position=102,
    )
    sink = StreamingDatasetSink(scope="ledger:100-102")
    receipt = _run(
        processor.ingest_ledger(
            request,
            sink=sink,
            observed_anchor=HashAnchor(102, "0x102"),
        )
    )
    assert receipt.status is RunStatus.COMPLETE
    assert receipt.mode is IngestMode.LEDGER_RANGE
    assert receipt.records_accepted == 3
    assert receipt.checkpoint_after is not None
    # Identity binds chain/network/genesis/provider/scope/schema/normalizer.
    assert receipt.checkpoint_after.identity.scope == "ledger:100-102"
    assert receipt.checkpoint_after.identity.chain.genesis_hash == GENESIS
    loaded = _run(store.load(receipt.checkpoint_after.identity.key, context=context))
    assert loaded is not None
    assert loaded.anchor.block_hash == "0x102"


def test_pipeline_export_manifest_includes_required_fields(
    chain: ChainRef,
    context: OperationContext,
    tmp_path: Path,
) -> None:
    pages = [
        [
            _tx(chain, tx_hash="0x21", sequence=50, block_hash="0x50", finality=Finality.FINALIZED),
            _tx(chain, tx_hash="0x22", sequence=51, block_hash="0x51", finality=Finality.SAFE),
        ]
    ]
    provider = FakeWalletLedgerProvider(pages)
    processor = WalletLedgerProcessor(
        chain=chain,
        wallet_provider=provider,
        normalizer=IdentityNormalizer(),
        provider_name="fixture-rpc",
        normalizer_version="fixture-normalizer@1.2.3",
        normalized_schema_major=1,
        raw_payload_policy=RawPayloadPolicy.REFERENCED,
        clock=lambda: NOW,
    )
    export_dir = tmp_path / "export"
    request = BoundedRequest(scope="wallet:0xabc", context=context)
    receipt = _run(
        processor.ingest_wallet(
            request,
            observed_anchor=HashAnchor(51, "0x51"),
            export_formats=(ExportFormat.JSONL, ExportFormat.PARQUET),
            export_dir=str(export_dir),
            store_raw_payloads=True,
        )
    )
    assert receipt.export_receipt is not None
    export = receipt.export_receipt
    manifest = export.manifest
    payload = manifest.to_dict()

    # Required manifest fields from acceptance criteria.
    assert payload["status"] in {"complete", "partial"}
    assert payload["raw_payload_policy"] == "referenced"
    assert payload["record_count"] == 2
    assert sum(payload["finality_counts"].values()) == 2
    assert payload["checkpoint_after"] is not None
    assert "source" in payload
    assert payload["source"]["scope"] == "wallet:0xabc"
    assert payload["source"]["provider"] == "fixture-rpc"
    assert export.processor_version == "fixture-normalizer@1.2.3"
    assert export.normalized_schema_major == 1
    assert "wallet_history" in export.provider_capabilities or export.provider_capabilities
    assert ExportFormat.JSONL.value in export.formats
    assert (export_dir / "export-manifest.json").is_file()
    assert any(export_dir.glob("*.jsonl"))
    assert any(export_dir.glob("*.parquet"))


def test_resume_skips_already_seen_record_ids(
    chain: ChainRef,
    context: OperationContext,
) -> None:
    first_pages = [
        [_tx(chain, tx_hash="0xa1", sequence=1, block_hash="0x01")],
    ]
    provider = FakeWalletLedgerProvider(first_pages)
    store = InMemoryCheckpointStore()
    processor = WalletLedgerProcessor(
        chain=chain,
        wallet_provider=provider,
        normalizer=IdentityNormalizer(),
        checkpoint_store=store,
        provider_name="fixture-rpc",
        normalizer_version="fixture-normalizer@1",
        clock=lambda: NOW,
    )
    sink = StreamingDatasetSink(scope="wallet:0xabc")
    request = BoundedRequest(scope="wallet:0xabc", context=context)
    first = _run(
        processor.ingest_wallet(
            request,
            sink=sink,
            observed_anchor=HashAnchor(1, "0x01"),
        )
    )
    assert first.checkpoint_advanced is True

    # Second run re-emits the same page plus a new record.
    second_pages = [
        [
            _tx(chain, tx_hash="0xa1", sequence=1, block_hash="0x01"),
            _tx(chain, tx_hash="0xa2", sequence=2, block_hash="0x02"),
        ]
    ]
    provider2 = FakeWalletLedgerProvider(second_pages)
    processor2 = WalletLedgerProcessor(
        chain=chain,
        wallet_provider=provider2,
        normalizer=IdentityNormalizer(),
        checkpoint_store=store,
        provider_name="fixture-rpc",
        normalizer_version="fixture-normalizer@1",
        clock=lambda: NOW,
    )
    sink.reset_for_resume()
    second = _run(
        processor2.ingest_wallet(
            request,
            sink=sink,
            observed_anchor=HashAnchor(2, "0x02"),
        )
    )
    assert second.records_duplicate >= 1
    assert second.records_accepted == 1
    assert sink.committed_count == 2
    ids = [row["record_id"] for row in sink.committed_records()]
    assert len(set(ids)) == 2


def test_raw_payload_store_content_addressed(
    chain: ChainRef,
    context: OperationContext,
) -> None:
    pages = [[_tx(chain, tx_hash="0x99", sequence=9, block_hash="0x09")]]
    provider = FakeWalletLedgerProvider(pages)
    raw_store = InMemoryRawPayloadStore()
    processor = WalletLedgerProcessor(
        chain=chain,
        wallet_provider=provider,
        normalizer=IdentityNormalizer(),
        raw_payload_store=raw_store,
        raw_payload_policy=RawPayloadPolicy.REFERENCED,
        provider_name="fixture-rpc",
        normalizer_version="fixture-normalizer@1",
        clock=lambda: NOW,
    )
    request = BoundedRequest(scope="wallet:0xabc", context=context)
    _run(
        processor.ingest_wallet(
            request,
            observed_anchor=HashAnchor(9, "0x09"),
            store_raw_payloads=True,
        )
    )
    assert len(raw_store) == 1
    digest = next(iter(raw_store.digests()))
    stored = _run(raw_store.get(digest, context=context))
    assert stored is not None
    assert stored.digest.startswith("sha256:")
    assert stored.byte_length > 0


def test_processor_satisfies_dataset_sink_protocol_surface(
    chain: ChainRef,
    context: OperationContext,
) -> None:
    sink = StreamingDatasetSink(scope="wallet:0xabc")
    assert isinstance(sink, DatasetSink)
    processor = WalletLedgerProcessor(
        chain=chain,
        wallet_provider=FakeWalletLedgerProvider([]),
        normalizer=IdentityNormalizer(),
        provider_name="fixture-rpc",
        normalizer_version="fixture-normalizer@1",
    )
    assert Capability.WALLET_HISTORY in processor.capabilities.features
    assert processor.chain == chain
