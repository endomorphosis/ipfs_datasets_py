"""E2E: DuckDB-only processor wallet ledger after file authority removal (DQK-073).

Acceptance:

* Ingestion resumes from DuckDB with legacy files absent
* No raw secret-bearing data reaches the publication database
* Quack exposes redacted public ledger analytics only
"""

from __future__ import annotations

import asyncio
import os
import sys
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
    assert_legacy_checkpoint_files_absent,
    build_checkpoint,
    new_revision,
)
from ipfs_datasets_py.processors.wallets.duckdb_storage import open_wallet_store
from ipfs_datasets_py.processors.wallets.errors import DatasetSinkError
from ipfs_datasets_py.processors.wallets.export import (
    ExportFormat,
    drain_wallet_export_outbox,
    project_quack_public_ledger_publication,
    project_redacted_public_ledger_analytics,
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
from ipfs_datasets_py.processors.wallets.protocols import (
    OperationContext,
    RecordBatch,
    RequestLimits,
)
from ipfs_datasets_py.processors.wallets.storage import (
    LEGACY_AUTHORITY_FILENAMES,
    ShadowLedgerMode,
    StreamingDatasetSink,
    assert_legacy_authority_files_absent,
    assert_publication_database_excludes_secrets,
    assert_shadow_catalog_excludes_secrets,
    find_legacy_authority_files,
    project_publication_ledger,
    project_public_ledger_analytics,
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


def _tx(
    chain: ChainRef, sequence: int, tx_hash: str, *, scope: str = "wallet:0xabc/eth"
) -> TransactionRecord:
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


def page_records(chain: ChainRef, sequence: int) -> list:
    tx_hash = f"0xethtx{sequence:04d}"
    return [
        _block(chain, sequence),
        _tx(chain, sequence, tx_hash),
        _transfer(chain, sequence, tx_hash),
    ]


@pytest.fixture
def context() -> OperationContext:
    return OperationContext(
        request_id="dqk-073-e2e",
        limits=RequestLimits(
            max_items=100,
            max_pages=20,
            max_requests=40,
            max_response_bytes=64 * 1024,
        ),
    )


# ---------------------------------------------------------------------------
# Ingestion resumes from DuckDB with legacy files absent
# ---------------------------------------------------------------------------


def test_ingestion_resumes_from_duckdb_with_legacy_files_absent(
    tmp_path: Path, context: OperationContext
) -> None:
    """db-primary ingest + kill/resume never requires records.jsonl / meta / manifest."""

    chain = eth_chain()
    page1 = page_records(chain, 100)
    page2 = page_records(chain, 101)
    work = tmp_path / "ledger-work"
    work.mkdir()
    store = open_wallet_store(scope="dqk073:resume", auto_recover=True)

    sink = StreamingDatasetSink(
        scope="wallet:dqk073-resume",
        output_dir=work,
        shadow_store=store,
        authority_mode=ShadowLedgerMode.DB_PRIMARY,
        # No export_formats → no implicit outbox materialisation (DQK-073).
        export_formats=(),
        raw_payload_policy=RawPayloadPolicy.OMITTED,
    )
    assert sink.authority_mode is ShadowLedgerMode.DB_PRIMARY
    assert sink.rejects_legacy_file_authority is True
    assert sink.authority_store is store

    checkpoints = InMemoryCheckpointStore(
        shadow_store=store,
        authority_mode=ShadowLedgerMode.DB_PRIMARY,
    )
    assert checkpoints.authority_mode is ShadowLedgerMode.DB_PRIMARY
    assert checkpoints.memory_is_authority is False
    assert checkpoints.authority_store is store

    identity = CheckpointIdentity(
        chain=chain,
        provider="fixture-rpc",
        scope="wallet:dqk073-resume",
        normalized_schema_major=1,
        normalizer_version="fixture-normalizer@1.0.0",
    )

    # Commit page 1 durably to DuckDB only.
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

    rev1 = new_revision()
    cp1 = build_checkpoint(
        identity,
        sequence=100,
        block_hash="0xethblock100",
        revision=rev1,
        sink_commit_id=commit1.commit_id,
    )
    accepted = _run(
        checkpoints.compare_and_set(
            identity.key,
            expected_revision=None,
            checkpoint=cp1,
            context=context,
        )
    )
    assert accepted is True

    # Legacy authority files must remain absent after durable commit.
    assert_legacy_authority_files_absent(work)
    assert_legacy_checkpoint_files_absent(work)
    assert find_legacy_authority_files(work) == ()
    assert not (work / "records.jsonl").exists()
    assert list(work.glob("*.meta.json")) == []
    assert not (work / "export-manifest.json").exists()

    # Inject crash before second commit; recover from DuckDB without files.
    _run(
        sink.write(
            RecordBatch(records=tuple(page2), response_bytes=32),
            context=context,
        )
    )
    sink.set_crash_boundary("before_page_commit")
    with pytest.raises(DatasetSinkError, match="crash injected"):
        _run(sink.commit(None, context=context))

    report = sink.recover_authority()
    assert report["recovered"] is True
    assert sink.authority_record_ids() == ids_after_p1

    # Fresh process-style resume: new sink + checkpoint store on same DuckDB.
    sink2 = StreamingDatasetSink(
        scope="wallet:dqk073-resume",
        output_dir=work,
        shadow_store=store,
        authority_mode=ShadowLedgerMode.DB_PRIMARY,
        export_formats=(),
    )
    sink2.recover_authority()
    assert sink2.authority_record_ids() == ids_after_p1

    checkpoints2 = InMemoryCheckpointStore(
        shadow_store=store,
        authority_mode=ShadowLedgerMode.DB_PRIMARY,
    )
    loaded = _run(checkpoints2.load(identity.key, context=context))
    assert loaded is not None
    assert loaded.anchor.sequence == 100
    assert loaded.anchor.block_hash == "0xethblock100"
    # Memory is a projection only — DuckDB tip is authority.
    assert checkpoints2.memory_is_authority is False

    # Resume page 2 after recover.
    sink2.reset_for_resume()
    _run(
        sink2.write(
            RecordBatch(records=tuple(page2), response_bytes=32),
            context=context,
        )
    )
    commit2 = _run(sink2.commit(None, context=context))
    expected = {record_identity(r) for r in page1 + page2}
    assert sink2.authority_record_ids() == expected
    assert commit2.record_count == len(expected)

    rev2 = new_revision()
    cp2 = build_checkpoint(
        identity,
        sequence=101,
        block_hash="0xethblock101",
        revision=rev2,
        sink_commit_id=commit2.commit_id,
        prior_history=loaded.history,
    )
    accepted2 = _run(
        checkpoints2.compare_and_set(
            identity.key,
            expected_revision=loaded.revision,
            checkpoint=cp2,
            context=context,
        )
    )
    assert accepted2 is True

    # Still no legacy authority files after full resume.
    assert_legacy_authority_files_absent(work)
    assert_legacy_checkpoint_files_absent(work)
    for name in LEGACY_AUTHORITY_FILENAMES:
        assert not (work / name).exists(), name


def test_db_primary_does_not_enqueue_implicit_jsonl_outbox(
    tmp_path: Path, context: OperationContext
) -> None:
    """Without explicit export_formats, db-primary never schedules file writes."""

    chain = eth_chain()
    work = tmp_path / "no-outbox"
    work.mkdir()
    store = open_wallet_store(scope="dqk073:no-outbox", auto_recover=True)
    sink = StreamingDatasetSink(
        scope="wallet:no-outbox",
        output_dir=work,
        shadow_store=store,
        authority_mode=ShadowLedgerMode.DB_PRIMARY,
        export_formats=(),
    )
    _run(
        sink.write(
            RecordBatch(records=tuple(page_records(chain, 200)), response_bytes=8),
            context=context,
        )
    )
    _run(sink.commit(None, context=context))
    assert sink.export_outbox.pending() == ()
    assert_legacy_authority_files_absent(work)


def test_explicit_export_outbox_does_not_write_classic_names_under_db_primary(
    tmp_path: Path, context: OperationContext
) -> None:
    """Explicit drain still works; classic records.jsonl suppressed by default."""

    chain = eth_chain()
    work = tmp_path / "explicit-export"
    work.mkdir()
    store = open_wallet_store(scope="dqk073:export", auto_recover=True)
    sink = StreamingDatasetSink(
        scope="wallet:export",
        output_dir=work,
        shadow_store=store,
        authority_mode=ShadowLedgerMode.DB_PRIMARY,
        export_formats=("jsonl", "parquet"),
    )
    records = page_records(chain, 300)
    _run(
        sink.write(
            RecordBatch(records=tuple(records), response_bytes=8),
            context=context,
        )
    )
    _run(sink.commit(None, context=context))
    assert sink.export_outbox.pending()
    drained = drain_wallet_export_outbox(sink, output_dir=work)
    assert drained
    # Numbered explicit export partitions are allowed.
    assert any(work.glob("records-*.jsonl"))
    assert any(work.glob("records-*.parquet"))
    # Classic authority names remain absent unless write_legacy_names=True.
    assert not (work / "records.jsonl").exists()
    assert not (work / "content.digest").exists()


# ---------------------------------------------------------------------------
# No raw secret-bearing data reaches the publication database
# ---------------------------------------------------------------------------


def test_publication_database_excludes_raw_secret_bearing_data(
    tmp_path: Path, context: OperationContext
) -> None:
    chain = eth_chain()
    store = open_wallet_store(scope="dqk073:secrets", auto_recover=True)
    sink = StreamingDatasetSink(
        scope="wallet:secrets",
        shadow_store=store,
        authority_mode=ShadowLedgerMode.DB_PRIMARY,
        export_formats=(),
    )
    records = page_records(chain, 400)
    _run(
        sink.write(
            RecordBatch(records=tuple(records), response_bytes=16),
            context=context,
        )
    )
    _run(sink.commit(None, context=context))

    # Catalog (private authority DB surface) has only public data + CID refs.
    assert_shadow_catalog_excludes_secrets(store)

    # Encrypted object refs are digest/CID only — never bodies.
    ref_rows = list(store.list_records("encrypted_object_refs"))
    assert ref_rows, "expected encrypted/CID raw-object references"
    for row in ref_rows:
        assert row.get("digest") or row.get("cid")
        assert "body" not in row
        assert "payload_bytes" not in row
        assert "raw_payload" not in row
        assert not isinstance(row.get("digest"), (bytes, bytearray))

    publication = project_publication_ledger(store, scope="wallet:secrets")
    assert_publication_database_excludes_secrets(publication)
    assert publication["redacted"] is True
    assert publication["analytics"]["raw_secret_bearing_data"] is False

    # Injecting a secret into a forged publication must fail closed.
    forged = dict(publication)
    forged["private_key"] = "0xdeadbeef" * 4
    with pytest.raises(DatasetSinkError, match="secret-bearing"):
        assert_publication_database_excludes_secrets(forged)

    forged_bytes = {"analytics": publication["analytics"], "payload_bytes": b"secret"}
    with pytest.raises(DatasetSinkError, match="raw bytes|secret-bearing"):
        assert_publication_database_excludes_secrets(forged_bytes)


# ---------------------------------------------------------------------------
# Quack exposes redacted public ledger analytics only
# ---------------------------------------------------------------------------


def test_quack_exposes_redacted_public_ledger_analytics_only(
    tmp_path: Path, context: OperationContext
) -> None:
    chain = eth_chain()
    store = open_wallet_store(scope="dqk073:quack", auto_recover=True)
    sink = StreamingDatasetSink(
        scope="wallet:quack",
        shadow_store=store,
        authority_mode=ShadowLedgerMode.DB_PRIMARY,
        export_formats=(),
    )
    pages = page_records(chain, 500) + page_records(chain, 501)
    _run(
        sink.write(
            RecordBatch(records=tuple(pages), response_bytes=16),
            context=context,
        )
    )
    _run(sink.commit(None, context=context))

    analytics = project_redacted_public_ledger_analytics(
        store, scope="wallet:quack"
    )
    assert analytics["redacted"] is True
    assert analytics["publication_type"] == "wallet_public_ledger_analytics_v1"
    assert analytics["record_count"] == len(pages)
    assert analytics["counts_by_table"]
    assert analytics["min_sequence"] == 500
    assert analytics["max_sequence"] == 501
    assert analytics["raw_secret_bearing_data"] is False
    assert analytics["opaque_payload_authority"] is False
    # Content refs are digest/CID only.
    for ref in analytics["content_refs"]:
        assert ref.get("digest") or ref.get("cid")
        assert "body" not in ref

    publication = project_quack_public_ledger_publication(
        store, scope="wallet:quack"
    )
    assert publication["publication_type"] == "wallet_quack_ledger_publication_v1"
    assert publication["redacted"] is True
    assert "public_ledger_analytics" in publication["allowed_surfaces"]
    assert "records.jsonl" in publication["forbidden_surfaces"]
    assert ".meta.json" in publication["forbidden_surfaces"]
    assert "export-manifest.json" in publication["forbidden_surfaces"]
    assert "in_memory_checkpoint_authority" in publication["forbidden_surfaces"]
    assert "raw_secret_bearing_data" in publication["forbidden_surfaces"]
    assert_publication_database_excludes_secrets(publication)

    # Storage-level analytics helper agrees with export-facing projection.
    direct = project_public_ledger_analytics(store, scope="wallet:quack")
    assert direct["record_count"] == analytics["record_count"]
    assert direct["counts_by_finality"] == analytics["counts_by_finality"]


def test_promote_to_db_primary_removes_memory_and_file_authority(
    tmp_path: Path, context: OperationContext
) -> None:
    chain = eth_chain()
    work = tmp_path / "promote"
    work.mkdir()
    store = open_wallet_store(scope="dqk073:promote", auto_recover=True)
    sink = StreamingDatasetSink(
        scope="wallet:promote",
        output_dir=work,
        shadow_store=store,
        authority_mode=ShadowLedgerMode.DUAL,
        export_formats=("jsonl",),
    )
    checkpoints = InMemoryCheckpointStore(
        shadow_store=store,
        authority_mode=ShadowLedgerMode.DUAL,
    )
    assert checkpoints.memory_is_authority is False  # dual already DuckDB authority

    _run(
        sink.write(
            RecordBatch(records=tuple(page_records(chain, 600)), response_bytes=8),
            context=context,
        )
    )
    _run(sink.commit(None, context=context))

    mode = sink.promote_to_db_primary()
    assert mode is ShadowLedgerMode.DB_PRIMARY
    assert sink.rejects_legacy_file_authority is True
    cp_mode = checkpoints.promote_to_db_primary()
    assert cp_mode is ShadowLedgerMode.DB_PRIMARY
    assert checkpoints.memory_is_authority is False

    # After promotion, further commits on the same sink without export formats
    # leave no classic authority files on disk.
    # Clear dual-era export formats so no implicit outbox is scheduled.
    sink._export_formats = ()
    _run(
        sink.write(
            RecordBatch(records=tuple(page_records(chain, 601)), response_bytes=8),
            context=context,
        )
    )
    _run(sink.commit(None, context=context))
    # Prior dual commits may still have pending outbox entries; the db-primary
    # commit with empty export_formats must not add new ones for classic names.
    # Classic authority files remain undrained / absent.
    assert not (work / "records.jsonl").exists()
    assert not (work / "export-manifest.json").exists()
    assert not (work / "content.digest").exists()
    assert list(work.glob("*.meta.json")) == []


def test_db_primary_stale_checkpoint_cas_fails_closed(
    context: OperationContext,
) -> None:
    chain = eth_chain()
    store = open_wallet_store(scope="dqk073:cas", auto_recover=True)
    checkpoints = InMemoryCheckpointStore(
        shadow_store=store,
        authority_mode=ShadowLedgerMode.DB_PRIMARY,
    )
    identity = CheckpointIdentity(
        chain=chain,
        provider="fixture-rpc",
        scope="wallet:cas",
        normalized_schema_major=1,
        normalizer_version="fixture@1",
    )
    rev1 = new_revision()
    cp1 = build_checkpoint(
        identity,
        sequence=1,
        block_hash="0xhash1",
        revision=rev1,
    )
    assert _run(
        checkpoints.compare_and_set(
            identity.key,
            expected_revision=None,
            checkpoint=cp1,
            context=context,
        )
    )
    stale = build_checkpoint(
        identity,
        sequence=2,
        block_hash="0xhash2",
        revision=new_revision(),
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
    tip = _run(checkpoints.load(identity.key, context=context))
    assert tip is not None
    assert tip.revision == rev1
    assert tip.anchor.sequence == 1
