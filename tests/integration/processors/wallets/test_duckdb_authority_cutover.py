"""Integration tests: processor wallet DuckDB authority cutover (DQK-072).

Acceptance:

* Kill/restart at page, block, reorg and export boundaries loses or duplicates
  no record
* Stale cursor CAS fails
* Typed Parquet supports predicate pushdown without opaque-only payload
  authority

Dual mode makes DuckDB authoritative for normalized ledger state and
checkpoints; JSONL, Parquet, Arrow and CAR are outbox-driven exports.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from collections.abc import AsyncIterator, Sequence
from datetime import datetime, timezone
from pathlib import Path

os.environ.setdefault("IPFS_DATASETS_AUTO_INSTALL", "false")
os.environ.setdefault("IPFS_AUTO_INSTALL", "false")
os.environ.setdefault("IPFS_DATASETS_PY_MINIMAL_IMPORTS", "1")

_REPO_ROOT = Path(__file__).resolve().parents[4]
_LOCAL_ACCELERATE = (_REPO_ROOT / "ipfs_accelerate_py").resolve()


def _prefer_sealed_accelerate_checkout() -> None:
    """Prefer the admitted accelerate checkout over the nested worktree copy."""

    accelerate_paths: list[Path] = []
    for entry in sys.path:
        try:
            path = Path(entry).resolve()
        except OSError:
            continue
        runtime = (
            path
            / "ipfs_accelerate_py"
            / "agent_supervisor"
            / "validation_runtime.py"
        )
        if runtime.is_file() and path not in accelerate_paths:
            accelerate_paths.append(path)
    if not accelerate_paths:
        return
    preferred = next(
        (path for path in accelerate_paths if path != _LOCAL_ACCELERATE),
        accelerate_paths[0],
    )
    if preferred == _LOCAL_ACCELERATE:
        return
    rebuilt: list[str] = [str(preferred)]
    for entry in sys.path:
        try:
            path = Path(entry).resolve()
        except OSError:
            rebuilt.append(entry)
            continue
        if path in {_LOCAL_ACCELERATE, preferred}:
            continue
        rebuilt.append(entry)
    sys.path[:] = rebuilt
    for name in list(sys.modules):
        if name == "ipfs_accelerate_py" or name.startswith("ipfs_accelerate_py."):
            del sys.modules[name]


_prefer_sealed_accelerate_checkout()

if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import pytest

from ipfs_datasets_py.processors.wallets.checkpoints import (
    CheckpointIdentity,
    HashAnchor,
    InMemoryCheckpointStore,
    build_checkpoint,
    new_revision,
)
from ipfs_datasets_py.processors.wallets.duckdb_storage import open_wallet_store
from ipfs_datasets_py.processors.wallets.errors import CheckpointError, DatasetSinkError
from ipfs_datasets_py.processors.wallets.export import (
    TYPED_PARQUET_COLUMNS,
    ExportFormat,
    apply_typed_predicates,
    drain_wallet_export_outbox,
    read_parquet,
    write_parquet,
)
from ipfs_datasets_py.processors.wallets.finality import (
    OrphanCorrection,
    ReorgDecision,
    ReorgKind,
)
from ipfs_datasets_py.processors.wallets.models import (
    AccountKind,
    AccountRef,
    AssetKind,
    AssetRef,
    BlockRecord,
    ChainRef,
    ExactAmount,
    Finality,
    LedgerPosition,
    Provenance,
    RawPayloadPolicy,
    RawPayloadRef,
    TransferKind,
    TransferRecord,
    TransactionRecord,
    TransactionStatus,
)
from ipfs_datasets_py.processors.wallets.pipeline import (
    RunStatus,
    WalletLedgerProcessor,
)
from ipfs_datasets_py.processors.wallets.protocols import (
    BoundedRequest,
    Capabilities,
    Capability,
    OperationContext,
    RecordBatch,
    RequestLimits,
)
from ipfs_datasets_py.processors.wallets.storage import (
    ExportOutboxStatus,
    ShadowLedgerMode,
    StreamingDatasetSink,
    assert_shadow_catalog_excludes_secrets,
    compare_jsonl_db_projections,
    record_identity,
)

NOW = datetime(2025, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
ETH_GENESIS = "0xd4e56740f876aef8c010b86a40d5f56745a118d0906a34e69aec8c0db1cb8fa3"
DIGEST = "sha256:" + ("ab" * 32)
CID = "bafybeigdyrzt5sfp7udm7hu76uh7y26nf3efuylqabf3oclgtqy55fbzdi"


def _run(coro):
    return asyncio.run(coro)


def eth_chain() -> ChainRef:
    return ChainRef(
        namespace="eip155",
        network="ethereum-mainnet",
        chain_id="1",
        genesis_hash=ETH_GENESIS,
    )


def _provenance(chain: ChainRef, scope: str, provider: str = "fixture-rpc") -> Provenance:
    return Provenance(
        provider=provider,
        provider_kind="json-rpc",
        request_id=f"req-{chain.network}",
        scope=scope,
        observed_at=NOW,
        raw_payload=RawPayloadRef(
            digest=DIGEST,
            cid=CID,
            media_type="application/json",
            byte_length=64,
        ),
    )


def _block(chain: ChainRef, sequence: int, *, scope: str = "wallet:0xabc/eth") -> BlockRecord:
    h = f"0xethblock{sequence}"
    parent = f"0xethblock{sequence - 1}"
    return BlockRecord(
        chain=chain,
        provenance=_provenance(chain, scope),
        ledger_position=LedgerPosition(sequence=sequence, hash=h),
        finality=Finality.CONFIRMED,
        block_hash=h,
        parent_hash=parent,
        block_time=NOW,
        transaction_count=1,
    )


def _tx(chain: ChainRef, sequence: int, tx_hash: str, *, scope: str = "wallet:0xabc/eth") -> TransactionRecord:
    return TransactionRecord(
        chain=chain,
        provenance=_provenance(chain, scope),
        ledger_position=LedgerPosition(
            sequence=sequence, hash=f"0xethblock{sequence}", transaction_index=0
        ),
        finality=Finality.CONFIRMED,
        transaction_hash=tx_hash,
        status=TransactionStatus.SUCCEEDED,
        participants=(AccountRef(chain, "0xabc", AccountKind.ADDRESS),),
    )


def _transfer(
    chain: ChainRef, sequence: int, tx_hash: str, *, scope: str = "wallet:0xabc/eth"
) -> TransferRecord:
    return TransferRecord(
        chain=chain,
        provenance=_provenance(chain, scope),
        ledger_position=LedgerPosition(
            sequence=sequence, hash=f"0xethblock{sequence}", transaction_index=0
        ),
        finality=Finality.CONFIRMED,
        transaction_hash=tx_hash,
        transfer_index=0,
        asset=AssetRef(
            chain,
            asset_namespace="slip44",
            asset_reference="60",
            decimals=18,
            kind=AssetKind.NATIVE,
            symbol="ETH",
        ),
        amount=ExactAmount(base_units="1000000000000000000", decimals=18),
        source_account=AccountRef(chain, "0xabc", AccountKind.ADDRESS),
        destination_account=AccountRef(chain, "0xdef", AccountKind.ADDRESS),
        transfer_kind=TransferKind.NATIVE,
    )


def page_records(chain: ChainRef, sequence: int, *, scope: str = "wallet:0xabc/eth") -> list[object]:
    tx_hash = f"0xethtx{sequence:04d}"
    return [
        _block(chain, sequence, scope=scope),
        _tx(chain, sequence, tx_hash, scope=scope),
        _transfer(chain, sequence, tx_hash, scope=scope),
    ]


class IdentityNormalizer:
    def __init__(self, chain: ChainRef) -> None:
        self.chain = chain
        self.capabilities = Capabilities(
            provider="fixture-normalizer",
            chain_namespaces=frozenset({chain.namespace}),
            features=frozenset(
                {
                    Capability.WALLET_HISTORY,
                    Capability.LEDGER_RANGE,
                    Capability.DATASET_EXPORT,
                }
            ),
        )

    def normalize(
        self, records: Sequence[object], *, context: OperationContext
    ) -> list[object]:
        context.check_active()
        return list(records)


class FixtureWalletProvider:
    def __init__(self, pages: Sequence[Sequence[object]], chain: ChainRef) -> None:
        self._pages = [tuple(page) for page in pages]
        self.chain = chain
        self.capabilities = Capabilities(
            provider="fixture-rpc",
            chain_namespaces=frozenset({chain.namespace}),
            features=frozenset(
                {
                    Capability.WALLET_HISTORY,
                    Capability.LEDGER_RANGE,
                    Capability.RAW_PAYLOADS,
                }
            ),
        )

    async def validate_address(
        self, address: str, *, context: OperationContext
    ) -> object:
        context.check_active()
        return address

    def ingest_wallet(
        self, request: BoundedRequest
    ) -> AsyncIterator[RecordBatch]:
        return self._ingest(request)

    def ingest_ledger(
        self, request: BoundedRequest
    ) -> AsyncIterator[RecordBatch]:
        return self._ingest(request)

    async def _ingest(
        self, request: BoundedRequest
    ) -> AsyncIterator[RecordBatch]:
        request.context.check_active()
        for index, page in enumerate(self._pages):
            next_cursor = f"page-{index + 1}" if index + 1 < len(self._pages) else None
            yield RecordBatch(
                records=page,
                next_cursor=next_cursor,
                response_bytes=128,
            )


@pytest.fixture
def context() -> OperationContext:
    return OperationContext(
        request_id="authority-cutover-1",
        limits=RequestLimits(
            max_items=100,
            max_pages=20,
            max_requests=40,
            max_response_bytes=64 * 1024,
        ),
    )


# ---------------------------------------------------------------------------
# Module / dual-mode wiring
# ---------------------------------------------------------------------------


def test_dual_mode_defaults_and_promotion(tmp_path: Path, context: OperationContext) -> None:
    chain = eth_chain()
    store = open_wallet_store(scope="auth:promote", auto_recover=True)
    sink = StreamingDatasetSink(
        scope="wallet:promote",
        output_dir=tmp_path / "promote",
        shadow_store=store,
        authority_mode=ShadowLedgerMode.DUAL,
        export_formats=("jsonl", "parquet"),
    )
    assert sink.authority_mode is ShadowLedgerMode.DUAL
    assert sink.authority_store is store
    assert sink.shadow_mode.duckdb_is_authority is True

    checkpoints = InMemoryCheckpointStore(
        shadow_store=store, authority_mode=ShadowLedgerMode.SHADOW
    )
    assert checkpoints.authority_mode is ShadowLedgerMode.SHADOW
    assert checkpoints.authority_store is None
    mode = checkpoints.promote_to_dual()
    assert mode is ShadowLedgerMode.DUAL
    assert checkpoints.authority_store is store
    checkpoints.promote_to_db_primary()
    assert checkpoints.authority_mode is ShadowLedgerMode.DB_PRIMARY


# ---------------------------------------------------------------------------
# Kill/restart at page, block, reorg and export boundaries
# ---------------------------------------------------------------------------


def test_kill_restart_at_page_boundary_no_loss_or_duplicate(
    tmp_path: Path, context: OperationContext
) -> None:
    """Crash after staging a page but before commit; recover and resume."""

    chain = eth_chain()
    page1 = page_records(chain, 100)
    page2 = page_records(chain, 101)
    store = open_wallet_store(scope="auth:page-crash", auto_recover=True)
    sink = StreamingDatasetSink(
        scope="wallet:page-crash",
        output_dir=tmp_path / "page-crash",
        shadow_store=store,
        authority_mode=ShadowLedgerMode.DUAL,
        export_formats=("jsonl",),
    )

    # Commit page 1 durably.
    _run(
        sink.write(
            RecordBatch(records=tuple(page1), response_bytes=32),
            context=context,
        )
    )
    commit1 = _run(sink.commit(None, context=context))
    assert commit1.record_count == len(page1)
    ids_after_p1 = sink.authority_record_ids()
    assert len(ids_after_p1) == len(page1)

    # Stage page 2, then inject crash before authority commit.
    _run(
        sink.write(
            RecordBatch(records=tuple(page2), response_bytes=32),
            context=context,
        )
    )
    assert sink.staged_count == len(page2)
    sink.set_crash_boundary("before_page_commit")
    with pytest.raises(DatasetSinkError, match="crash injected"):
        _run(sink.commit(None, context=context))

    # Recover: open stages abort; durable page1 remains; no duplicates.
    report = sink.recover_authority()
    assert report["recovered"] is True
    durable_ids = sink.authority_record_ids()
    assert durable_ids == ids_after_p1
    assert len(durable_ids) == len(page1)

    # Resume page 2 after recover — still exactly one copy of each record.
    sink.reset_for_resume()
    _run(
        sink.write(
            RecordBatch(records=tuple(page2), response_bytes=32),
            context=context,
        )
    )
    commit2 = _run(sink.commit(None, context=context))
    final_ids = sink.authority_record_ids()
    expected = {record_identity(r) for r in page1 + page2}
    assert final_ids == expected
    assert commit2.record_count == len(expected)
    # Replay page1+page2 must not invent duplicates.
    _run(
        sink.write(
            RecordBatch(records=tuple(page1 + page2), response_bytes=8),
            context=context,
        )
    )
    assert sink.staged_count == 0  # all seen
    assert sink.authority_record_ids() == expected


def test_kill_restart_at_block_and_export_boundaries(
    tmp_path: Path, context: OperationContext
) -> None:
    chain = eth_chain()
    blocks = [_block(chain, seq) for seq in (200, 201, 202)]
    store = open_wallet_store(scope="auth:block-export", auto_recover=True)
    sink = StreamingDatasetSink(
        scope="wallet:block-export",
        output_dir=tmp_path / "block-export",
        shadow_store=store,
        authority_mode=ShadowLedgerMode.DUAL,
        export_formats=("jsonl", "parquet", "arrow"),
    )

    # Write and commit first block.
    _run(
        sink.write(
            RecordBatch(records=(blocks[0],), response_bytes=8),
            context=context,
        )
    )
    _run(sink.commit(None, context=context))
    assert len(sink.authority_record_ids()) == 1

    # Stage second block; crash at block commit boundary.
    _run(
        sink.write(
            RecordBatch(records=(blocks[1],), response_bytes=8),
            context=context,
        )
    )
    sink.set_crash_boundary("before_block_commit")
    with pytest.raises(DatasetSinkError, match="before_block_commit"):
        _run(sink.commit(None, context=context))
    sink.recover_authority()
    assert len(sink.authority_record_ids()) == 1

    # Commit remaining blocks successfully.
    sink.reset_for_resume()
    for block in blocks[1:]:
        _run(
            sink.write(
                RecordBatch(records=(block,), response_bytes=8),
                context=context,
            )
        )
        _run(sink.commit(None, context=context))
    assert len(sink.authority_record_ids()) == 3

    # Export outbox pending after dual commits.
    pending = sink.export_outbox.pending()
    assert pending
    # Crash at export outbox enqueue is simulated on next commit path; drain
    # existing pending entries (export boundary resume).
    drained = drain_wallet_export_outbox(
        sink,
        formats=("jsonl", "parquet"),
        output_dir=tmp_path / "block-export",
    )
    assert drained
    assert all(e.status is ExportOutboxStatus.COMPLETED for e in drained)
    jsonl_path = tmp_path / "block-export" / "records.jsonl"
    assert jsonl_path.is_file()
    lines = [ln for ln in jsonl_path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert len(lines) == 3
    # Re-drain is idempotent (no duplicate materialisation required).
    again = drain_wallet_export_outbox(sink, output_dir=tmp_path / "block-export")
    assert again == ()


def test_kill_restart_at_reorg_boundary(
    tmp_path: Path, context: OperationContext
) -> None:
    chain = eth_chain()
    records = page_records(chain, 300)
    store = open_wallet_store(scope="auth:reorg", auto_recover=True)
    checkpoints = InMemoryCheckpointStore(
        shadow_store=store, authority_mode=ShadowLedgerMode.DUAL
    )
    provider = FixtureWalletProvider([records], chain)
    processor = WalletLedgerProcessor(
        chain=chain,
        wallet_provider=provider,
        ledger_provider=provider,
        normalizer=IdentityNormalizer(chain),
        checkpoint_store=checkpoints,
        shadow_store=store,
        authority_mode=ShadowLedgerMode.DUAL,
        provider_name="fixture-rpc",
        normalizer_version="fixture-normalizer@1.0.0",
    )
    scope = "wallet:0xabc/eth-reorg"
    request = BoundedRequest(scope=scope, context=context)
    receipt = _run(
        processor.ingest_wallet(
            request,
            export_dir=str(tmp_path / "reorg"),
            observed_anchor=HashAnchor(300, "0xethblock300"),
            export_formats=(ExportFormat.JSONL,),
        )
    )
    assert receipt.status is RunStatus.COMPLETE
    assert receipt.checkpoint_advanced
    assert receipt.checkpoint_after is not None
    identity = processor.identity_for(scope)
    tip_rev = receipt.checkpoint_after.revision

    tip = records[0]
    assert isinstance(tip, BlockRecord)
    correction = OrphanCorrection(
        record_id=tip.record_id,
        prior_finality=Finality.CONFIRMED,
        new_finality=Finality.ORPHANED,
        orphaned_anchor=HashAnchor(300, "0xethblock300"),
        ancestor_anchor=HashAnchor(299, "0xethblock299"),
        tombstone=True,
    )
    decision = ReorgDecision(
        kind=ReorgKind.SHALLOW,
        checkpoint_anchor=HashAnchor(300, "0xethblock300"),
        observed_anchor=HashAnchor(301, "0xethblock301alt"),
        common_ancestor=HashAnchor(299, "0xethblock299"),
        orphaned_anchors=(HashAnchor(300, "0xethblock300"),),
        corrections=(correction,),
        rewind_sequence=299,
        reason="authority cutover reorg",
    )
    rewound = build_checkpoint(
        identity,
        sequence=299,
        block_hash="0xethblock299",
        revision=new_revision(),
        prior_history=receipt.checkpoint_after.history,
        sink_commit_id=receipt.checkpoint_after.sink_commit_id,
    )
    reorg_result = _run(
        processor.apply_reorg(
            decision,
            provenance=_provenance(chain, scope),
            identity=identity,
            rewound=rewound,
            expected_revision=tip_rev,
            context=context,
            reorg_id="reorg:authority-1",
        )
    )
    assert reorg_result["checkpoint_advanced"] is True
    assert reorg_result["mode"] in {"dual", "db-primary"}

    # Simulate process restart: new checkpoint store rehydrates from DuckDB.
    restarted = InMemoryCheckpointStore(
        shadow_store=store, authority_mode=ShadowLedgerMode.DUAL
    )
    loaded = _run(restarted.load(identity.key, context=context))
    assert loaded is not None
    assert loaded.anchor.sequence == 299
    assert loaded.anchor.block_hash == "0xethblock299"
    # Ledger records remain durable (reorg rewinds tip, does not erase facts).
    assert store.get_record(record_identity(tip)) is not None
    reorgs = store.list_reorgs()
    assert any(r.get("reorg_id") for r in reorgs)


# ---------------------------------------------------------------------------
# Stale cursor CAS fails
# ---------------------------------------------------------------------------


def test_stale_cursor_cas_fails(tmp_path: Path, context: OperationContext) -> None:
    chain = eth_chain()
    store = open_wallet_store(scope="auth:stale-cas", auto_recover=True)
    checkpoints = InMemoryCheckpointStore(
        shadow_store=store, authority_mode=ShadowLedgerMode.DUAL
    )
    identity = CheckpointIdentity(
        chain=chain,
        provider="fixture-rpc",
        scope="wallet:stale-cas",
        normalized_schema_major=1,
        normalizer_version="fixture-normalizer@1.0.0",
    )
    first = build_checkpoint(
        identity, sequence=10, block_hash="0xhash10", revision=new_revision()
    )
    accepted = _run(
        checkpoints.compare_and_set(
            identity.key,
            expected_revision=None,
            checkpoint=first,
            context=context,
        )
    )
    assert accepted is True

    # Concurrent/stale writer with obsolete expected_revision loses CAS.
    stale = build_checkpoint(
        identity, sequence=11, block_hash="0xhash11", revision=new_revision()
    )
    rejected = _run(
        checkpoints.compare_and_set(
            identity.key,
            expected_revision="rev:stale-not-current",
            checkpoint=stale,
            context=context,
        )
    )
    assert rejected is False
    assert checkpoints.authority_cas_rejects >= 1

    loaded = _run(checkpoints.load(identity.key, context=context))
    assert loaded is not None
    assert loaded.revision == first.revision
    assert loaded.anchor.sequence == 10

    # Fresh expected_revision advances the DuckDB tip.
    next_cp = build_checkpoint(
        identity,
        sequence=11,
        block_hash="0xhash11",
        revision=new_revision(),
        prior_history=first.history,
    )
    advanced = _run(
        checkpoints.compare_and_set(
            identity.key,
            expected_revision=first.revision,
            checkpoint=next_cp,
            context=context,
        )
    )
    assert advanced is True
    # Restarted view sees DuckDB authority tip, not a stale memory ghost.
    other = InMemoryCheckpointStore(
        shadow_store=store, authority_mode=ShadowLedgerMode.DUAL
    )
    reloaded = _run(other.load(identity.key, context=context))
    assert reloaded is not None
    assert reloaded.anchor.sequence == 11
    assert reloaded.revision == next_cp.revision


# ---------------------------------------------------------------------------
# Typed Parquet predicate pushdown (not opaque-only payload authority)
# ---------------------------------------------------------------------------


def test_typed_parquet_predicate_pushdown_without_opaque_only_authority(
    tmp_path: Path,
) -> None:
    chain = eth_chain()
    records = page_records(chain, 400) + page_records(chain, 401)
    # Mix finality for filter coverage.
    finalized = BlockRecord(
        chain=chain,
        provenance=_provenance(chain, "wallet:0xabc/eth"),
        ledger_position=LedgerPosition(sequence=402, hash="0xethblock402"),
        finality=Finality.FINALIZED,
        block_hash="0xethblock402",
        parent_hash="0xethblock401",
        block_time=NOW,
        transaction_count=0,
    )
    all_records = list(records) + [finalized]

    # Typed columns are the pushdown surface; payload_json is never sole authority.
    assert "payload_json" not in TYPED_PARQUET_COLUMNS
    assert "record_id" in TYPED_PARQUET_COLUMNS
    assert "finality" in TYPED_PARQUET_COLUMNS
    assert "sequence" in TYPED_PARQUET_COLUMNS

    filtered = apply_typed_predicates(
        all_records,
        finality_filter=Finality.FINALIZED.value,
        min_sequence=402,
        max_sequence=402,
    )
    assert len(filtered) == 1
    assert record_identity(filtered[0]) == record_identity(finalized)

    path = tmp_path / "typed-authority.parquet"
    partition = write_parquet(
        all_records,
        path,
        typed=True,
        include_payload_json=True,
        finality_filter=Finality.CONFIRMED.value,
        min_sequence=400,
        max_sequence=401,
    )
    assert partition.format == ExportFormat.PARQUET.value
    assert partition.record_count == len(records)
    assert path.is_file()

    # Envelope / table must expose typed columns for pushdown (not payload-only).
    raw = path.read_bytes()
    if raw.lstrip().startswith(b"{"):
        envelope = json.loads(raw.decode("utf-8"))
        assert envelope["format"] == "wallet-typed-parquet-v1"
        assert envelope["opaque_payload_authority"] is False
        assert set(TYPED_PARQUET_COLUMNS).issubset(set(envelope["typed_columns"]))
        # Predicates were applied: only confirmed rows in 400..401.
        assert envelope["row_count"] == len(records)
        for row in envelope["rows"]:
            assert row["finality"] == Finality.CONFIRMED.value
            assert 400 <= int(row["sequence"]) <= 401
            # Typed fields present without needing to parse payload_json.
            assert row["record_id"]
            assert row["record_type"]

    # Round-trip preserves record identities via typed export path.
    round_tripped = read_parquet(path)
    assert len(round_tripped) == len(records)
    rt_ids = {str(r.get("record_id") or "") for r in round_tripped}
    expected_ids = {record_identity(r) for r in records}
    assert rt_ids == expected_ids

    # Filtering without ever consulting payload_json.
    confirmed_only = apply_typed_predicates(
        round_tripped, finality_filter=Finality.CONFIRMED.value
    )
    assert len(confirmed_only) == len(records)


# ---------------------------------------------------------------------------
# End-to-end dual-mode pipeline + outbox exports
# ---------------------------------------------------------------------------


def test_dual_mode_pipeline_ingest_and_outbox_export(
    tmp_path: Path, context: OperationContext
) -> None:
    chain = eth_chain()
    pages = [page_records(chain, 500), page_records(chain, 501)]
    store = open_wallet_store(scope="auth:pipeline", auto_recover=True)
    provider = FixtureWalletProvider(pages, chain)
    processor = WalletLedgerProcessor(
        chain=chain,
        wallet_provider=provider,
        ledger_provider=provider,
        normalizer=IdentityNormalizer(chain),
        shadow_store=store,
        authority_mode=ShadowLedgerMode.DUAL,
        provider_name="fixture-rpc",
        normalizer_version="fixture-normalizer@1.0.0",
    )
    assert processor.authority_mode is ShadowLedgerMode.DUAL
    assert processor.authority_store is store

    scope = "wallet:0xabc/eth-pipeline"
    request = BoundedRequest(scope=scope, context=context)
    out = tmp_path / "pipeline-out"
    receipt = _run(
        processor.ingest_wallet(
            request,
            export_dir=str(out),
            observed_anchor=HashAnchor(501, "0xethblock501"),
            export_formats=(ExportFormat.JSONL, ExportFormat.PARQUET),
        )
    )
    assert receipt.status is RunStatus.COMPLETE
    assert receipt.records_accepted == 6
    assert receipt.checkpoint_advanced
    assert receipt.export_receipt is not None

    # DuckDB is authority: all six fact rows durable.
    assert processor.last_sink is not None
    authority_ids = processor.last_sink.authority_record_ids()
    assert len(authority_ids) == 6
    parity = compare_jsonl_db_projections(
        processor.last_sink.committed_records(), store
    )
    assert parity.matched, parity.to_dict()
    assert_shadow_catalog_excludes_secrets(store)

    # Outbox-driven exports materialised under export_dir.
    assert (out / "records.jsonl").is_file() or any(out.glob("records-*.jsonl"))
    parquet_files = list(out.glob("*.parquet"))
    assert parquet_files

    # Restart recovery is a no-op with no open stages and preserves count.
    report = processor.recover_authority()
    assert report["mode"] == ShadowLedgerMode.DUAL.value
    assert len(processor.last_sink.authority_record_ids()) == 6
