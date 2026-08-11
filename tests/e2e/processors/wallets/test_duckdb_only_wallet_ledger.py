"""E2E tests: DuckDB-only processor wallet ledger authority (DQK-073).

Acceptance:

* Ingestion resumes from DuckDB with legacy files absent
* No raw secret-bearing data reaches the publication database
* Quack exposes redacted public ledger analytics only
"""

from __future__ import annotations

import asyncio
import json
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
    build_checkpoint,
    memory_checkpoint_is_authority,
    new_revision,
)
from ipfs_datasets_py.processors.wallets.duckdb_storage import open_wallet_store
from ipfs_datasets_py.processors.wallets.export import (
    drain_wallet_export_outbox,
    import_legacy_jsonl_explicit,
    wallet_ledger_quack_publication,
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
    WALLET_LEDGER_DUCKDB_ONLY_OWNER_TASK,
    WALLET_LEDGER_PUBLICATION_TYPE,
    DirectoryRawPayloadStore,
    ImplicitLegacyLedgerFileError,
    ShadowLedgerMode,
    StreamingDatasetSink,
    WalletLedgerFilesystemGuard,
    assert_shadow_catalog_excludes_secrets,
    duckdb_only_after_promotion,
    get_wallet_ledger_filesystem_guard,
    record_identity,
    reset_wallet_ledger_filesystem_guard,
)

NOW = datetime(2025, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
ETH_GENESIS = "0xd4e56740f876aef8c010b86a40d5f56745a118d0906a34e69aec8c0db1cb8fa3"
DIGEST = "sha256:" + ("ab" * 32)
CID = "bafybeigdyrzt5sfp7udm7hu76uh7y26nf3efuylqabf3oclgtqy55fbzdi"
SECRET_MARKER = "super-secret-raw-payload-body-never-publish"


def _run(coro):
    return asyncio.run(coro)


def eth_chain() -> ChainRef:
    return ChainRef(
        namespace="eip155",
        network="ethereum-mainnet",
        chain_id="1",
        genesis_hash=ETH_GENESIS,
    )


def _provenance(chain: ChainRef, scope: str) -> Provenance:
    return Provenance(
        provider="fixture-rpc",
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


def _block(chain: ChainRef, sequence: int, *, scope: str) -> BlockRecord:
    h = f"0xethblock{sequence}"
    return BlockRecord(
        chain=chain,
        provenance=_provenance(chain, scope),
        ledger_position=LedgerPosition(sequence=sequence, hash=h),
        finality=Finality.CONFIRMED,
        block_hash=h,
        parent_hash=f"0xethblock{sequence - 1}",
        block_time=NOW,
        transaction_count=1,
    )


def _tx(chain: ChainRef, sequence: int, tx_hash: str, *, scope: str) -> TransactionRecord:
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
    chain: ChainRef, sequence: int, tx_hash: str, *, scope: str
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


def page_records(chain: ChainRef, sequence: int, *, scope: str) -> list[object]:
    tx_hash = f"0xethtx{sequence:04d}"
    return [
        _block(chain, sequence, scope=scope),
        _tx(chain, sequence, tx_hash, scope=scope),
        _transfer(chain, sequence, tx_hash, scope=scope),
    ]


def _legacy_files(root: Path) -> list[Path]:
    if not root.exists():
        return []
    guarded = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        name = path.name
        if (
            name == "records.jsonl"
            or (name.startswith("records-") and name.endswith(".jsonl"))
            or name.endswith(".meta.json")
            or name in {"export-manifest.json", "export-partitions.json", "content.digest"}
        ):
            guarded.append(path)
    return sorted(guarded)


@pytest.fixture(autouse=True)
def _reset_guards():
    reset_wallet_ledger_filesystem_guard()
    yield
    reset_wallet_ledger_filesystem_guard()


@pytest.fixture
def context() -> OperationContext:
    return OperationContext(
        request_id="duckdb-only-ledger-1",
        limits=RequestLimits(
            max_items=100,
            max_pages=20,
            max_requests=40,
            max_response_bytes=64 * 1024,
        ),
    )


# ---------------------------------------------------------------------------
# Constants / guard classification
# ---------------------------------------------------------------------------


def test_owner_task_and_publication_constants() -> None:
    assert WALLET_LEDGER_DUCKDB_ONLY_OWNER_TASK == "DQK-073"
    assert WALLET_LEDGER_PUBLICATION_TYPE == "wallet_ledger_quack_publication_v1"
    assert duckdb_only_after_promotion(ShadowLedgerMode.DB_PRIMARY) is True
    assert duckdb_only_after_promotion(ShadowLedgerMode.DUAL) is False
    assert memory_checkpoint_is_authority(ShadowLedgerMode.DB_PRIMARY) is False
    assert memory_checkpoint_is_authority(ShadowLedgerMode.SHADOW) is True


def test_filesystem_guard_classifies_legacy_ledger_paths(tmp_path: Path) -> None:
    guard = WalletLedgerFilesystemGuard(allow_legacy_files=False)
    assert guard.classify_path(tmp_path / "records.jsonl") == "records_jsonl"
    assert guard.classify_path(tmp_path / "records-000.jsonl") == "records_jsonl"
    assert guard.classify_path(tmp_path / "sha256_ab.meta.json") == "meta_json"
    assert guard.classify_path(tmp_path / "export-manifest.json") == "export_manifest_json"
    assert guard.classify_path(tmp_path / "export-partitions.json") == "export_partitions_json"
    assert guard.classify_path(tmp_path / "content.digest") == "content_digest"
    assert guard.classify_path(tmp_path / "index.faiss") is None

    with pytest.raises(ImplicitLegacyLedgerFileError) as excinfo:
        guard.assert_allowed(tmp_path / "records.jsonl", kind="records_jsonl")
    assert excinfo.value.kind == "records_jsonl"
    assert "implicit" in str(excinfo.value).lower()


# ---------------------------------------------------------------------------
# Acceptance: ingestion resumes from DuckDB with legacy files absent
# ---------------------------------------------------------------------------


def test_ingest_and_resume_without_legacy_files(
    tmp_path: Path, context: OperationContext
) -> None:
    chain = eth_chain()
    scope = "wallet:0xabc/eth-duckdb-only"
    out = tmp_path / "ledger-out"
    store = open_wallet_store(scope="duckdb-only:resume", auto_recover=True)
    sink = StreamingDatasetSink(
        scope=scope,
        output_dir=out,
        shadow_store=store,
        authority_mode=ShadowLedgerMode.DB_PRIMARY,
        export_formats=("jsonl", "parquet"),
        allow_legacy_files=False,
    )
    assert sink.duckdb_only is True
    assert sink.allow_legacy_files is False
    assert sink.authority_store is store

    page1 = page_records(chain, 100, scope=scope)
    page2 = page_records(chain, 101, scope=scope)

    _run(
        sink.write(
            RecordBatch(records=tuple(page1), response_bytes=32),
            context=context,
        )
    )
    commit1 = _run(sink.commit(None, context=context))
    assert commit1.record_count == len(page1)
    # Implicit legacy files must not materialize on commit under db-primary.
    assert _legacy_files(out) == []
    assert not (out / "records.jsonl").exists()
    assert not (out / "export-manifest.json").exists()

    ids_after_p1 = sink.authority_record_ids()
    assert len(ids_after_p1) == len(page1)

    # Simulate process restart: empty memory projection, no legacy files.
    sink.clear_memory_projection = None  # type: ignore[attr-defined]
    restarted = StreamingDatasetSink(
        scope=scope,
        output_dir=out,
        shadow_store=store,
        authority_mode=ShadowLedgerMode.DB_PRIMARY,
        export_formats=("jsonl",),
        allow_legacy_files=False,
    )
    report = restarted.recover_authority()
    assert report["recovered"] is True or report.get("rehydrated") is True
    assert restarted.authority_record_ids() == ids_after_p1
    assert _legacy_files(out) == []

    # Resume page 2 from DuckDB authority only.
    restarted.reset_for_resume()
    _run(
        restarted.write(
            RecordBatch(records=tuple(page2), response_bytes=32),
            context=context,
        )
    )
    commit2 = _run(restarted.commit(None, context=context))
    expected = {record_identity(r) for r in page1 + page2}
    assert restarted.authority_record_ids() == expected
    assert commit2.record_count == len(expected)
    assert _legacy_files(out) == []

    # Replaying page1+page2 must not invent duplicates.
    _run(
        restarted.write(
            RecordBatch(records=tuple(page1 + page2), response_bytes=8),
            context=context,
        )
    )
    assert restarted.staged_count == 0
    assert restarted.authority_record_ids() == expected


def test_checkpoint_resume_from_duckdb_not_memory(
    tmp_path: Path, context: OperationContext
) -> None:
    chain = eth_chain()
    store = open_wallet_store(scope="duckdb-only:checkpoint", auto_recover=True)
    checkpoints = InMemoryCheckpointStore(
        shadow_store=store, authority_mode=ShadowLedgerMode.DB_PRIMARY
    )
    assert checkpoints.memory_is_authority is False
    assert checkpoints.duckdb_only is True

    identity = CheckpointIdentity(
        chain=chain,
        provider="fixture-rpc",
        scope="wallet:duckdb-only-cp",
        normalized_schema_major=1,
        normalizer_version="fixture-normalizer@1.0.0",
    )
    first = build_checkpoint(
        identity,
        sequence=42,
        block_hash="0xhash42",
        revision=new_revision(),
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

    # Drop memory projection — resume must rehydrate from DuckDB only.
    checkpoints.clear_memory_projection()
    assert identity.key not in checkpoints.keys()

    peer = InMemoryCheckpointStore(
        shadow_store=store, authority_mode=ShadowLedgerMode.DB_PRIMARY
    )
    peer.clear_memory_projection()
    loaded = _run(peer.load(identity.key, context=context))
    assert loaded is not None
    assert loaded.anchor.sequence == 42
    assert loaded.anchor.block_hash == "0xhash42"
    assert loaded.revision == first.revision
    assert peer.memory_is_authority is False

    # Memory-only ghost must not win over an empty DuckDB tip for a new scope.
    ghost_identity = CheckpointIdentity(
        chain=chain,
        provider="fixture-rpc",
        scope="wallet:ghost-scope",
        normalized_schema_major=1,
        normalizer_version="fixture-normalizer@1.0.0",
    )
    # Inject a memory-only entry without CAS to DuckDB (simulates stale local state).
    peer._entries[ghost_identity.key] = build_checkpoint(  # noqa: SLF001
        ghost_identity,
        sequence=99,
        block_hash="0xghost",
        revision=new_revision(),
    )
    ghost_load = _run(peer.load(ghost_identity.key, context=context))
    assert ghost_load is None
    assert ghost_identity.key not in peer.keys()


def test_raw_payload_meta_json_not_authority(tmp_path: Path, context: OperationContext) -> None:
    """Encrypted/CID raw-object refs remain; .meta.json is optional non-authority."""

    store = DirectoryRawPayloadStore(
        tmp_path / "raw",
        policy=RawPayloadPolicy.REFERENCED,
        write_meta=False,
    )
    body = SECRET_MARKER.encode("utf-8")
    put = _run(
        store.put(
            body,
            media_type="application/json",
            cid=CID,
            context=context,
        )
    )
    assert put.digest.startswith("sha256:")
    assert put.cid == CID
    # No .meta.json sidecar under write_meta=False (DQK-073).
    assert list(store.root.glob("*.meta.json")) == []
    assert list(store.root.glob("*.bin"))

    got = _run(store.get(put.digest, context=context))
    assert got is not None
    assert got.body == body
    assert got.media_type == "application/json"
    assert got.cid == CID
    # to_ref is digest/CID only — safe for DuckDB encrypted_object_refs.
    ref = put.to_ref()
    assert ref.digest == put.digest
    assert ref.cid == CID
    assert not hasattr(ref, "body") or getattr(ref, "body", None) in (None, b"", "")


# ---------------------------------------------------------------------------
# Acceptance: no raw secret-bearing data in publication database
# ---------------------------------------------------------------------------


def test_no_raw_secrets_reach_publication_database(
    tmp_path: Path, context: OperationContext
) -> None:
    chain = eth_chain()
    scope = "wallet:0xabc/eth-secrets"
    store = open_wallet_store(scope="duckdb-only:secrets", auto_recover=True)
    sink = StreamingDatasetSink(
        scope=scope,
        output_dir=tmp_path / "sec-out",
        shadow_store=store,
        authority_mode=ShadowLedgerMode.DB_PRIMARY,
        allow_legacy_files=False,
    )
    records = page_records(chain, 200, scope=scope)
    _run(
        sink.write(
            RecordBatch(records=tuple(records), response_bytes=16),
            context=context,
        )
    )
    _run(sink.commit(None, context=context))

    # Store encrypted/CID raw-object reference only (never body bytes).
    ref = RawPayloadRef(
        digest=DIGEST,
        cid=CID,
        media_type="application/json",
        byte_length=len(SECRET_MARKER),
    )
    store.put_encrypted_object_ref(
        ref,
        chain=chain,
        provenance=_provenance(chain, scope),
        finality=Finality.CONFIRMED,
        related_record_id=record_identity(records[0]),
    )

    assert_shadow_catalog_excludes_secrets(store)
    for table in store.catalog_tables():
        for row in store.list_records(table):
            text = json.dumps(dict(row), default=str)
            assert SECRET_MARKER not in text
            assert "private_key" not in text.casefold()
            for value in row.values():
                assert not isinstance(value, (bytes, bytearray, memoryview))


# ---------------------------------------------------------------------------
# Acceptance: Quack exposes redacted public ledger analytics only
# ---------------------------------------------------------------------------


def test_quack_exposes_redacted_public_ledger_analytics_only(
    tmp_path: Path, context: OperationContext
) -> None:
    chain = eth_chain()
    scope = "wallet:0xabc/eth-quack"
    store = open_wallet_store(scope="duckdb-only:quack", auto_recover=True)
    sink = StreamingDatasetSink(
        scope=scope,
        output_dir=tmp_path / "quack-out",
        shadow_store=store,
        authority_mode=ShadowLedgerMode.DB_PRIMARY,
        allow_legacy_files=False,
    )
    records = page_records(chain, 300, scope=scope) + page_records(
        chain, 301, scope=scope
    )
    _run(
        sink.write(
            RecordBatch(records=tuple(records), response_bytes=16),
            context=context,
        )
    )
    _run(sink.commit(None, context=context))
    store.put_encrypted_object_ref(
        RawPayloadRef(
            digest=DIGEST,
            cid=CID,
            media_type="application/json",
            byte_length=64,
        ),
        chain=chain,
        provenance=_provenance(chain, scope),
        finality=Finality.CONFIRMED,
    )

    document = sink.quack_publication_document()
    assert document["publication_type"] == WALLET_LEDGER_PUBLICATION_TYPE
    assert document["owner_task"] == WALLET_LEDGER_DUCKDB_ONLY_OWNER_TASK
    assert document["authority"] == "duckdb"
    assert document["wallet_raw_excluded"] is True
    assert document["secrets_excluded"] is True
    assert document["raw_payload_bodies_excluded"] is True
    assert document["legacy_file_authority"] is False
    assert document["records_jsonl_authority"] is False
    assert document["meta_json_authority"] is False
    assert document["json_manifest_authority"] is False
    assert document["in_memory_checkpoint_authority"] is False

    analytics = document["redacted_public_ledger_analytics"]
    assert analytics["record_count"] == 6
    assert analytics["secrets_excluded"] is True
    assert analytics["raw_payload_bodies_excluded"] is True
    assert analytics["legacy_files_authority"] is False
    assert analytics["encrypted_object_ref_count"] >= 1
    for ref in analytics["encrypted_object_refs"]:
        assert "digest" in ref or "cid" in ref
        assert "body" not in ref
        assert "ciphertext" not in ref
        assert "plaintext" not in ref

    doc_text = json.dumps(document, default=str)
    assert SECRET_MARKER not in doc_text
    assert "private_key" not in doc_text.casefold()
    assert "mnemonic" not in doc_text.casefold()

    # Helper entrypoint mirrors sink document.
    via_helper = wallet_ledger_quack_publication(sink)
    assert via_helper["publication_type"] == WALLET_LEDGER_PUBLICATION_TYPE
    assert via_helper["redacted_public_ledger_analytics"]["record_count"] == 6


# ---------------------------------------------------------------------------
# Explicit import/export remain available (compatibility only)
# ---------------------------------------------------------------------------


def test_explicit_export_and_import_compatibility(
    tmp_path: Path, context: OperationContext
) -> None:
    chain = eth_chain()
    scope = "wallet:0xabc/eth-export"
    out = tmp_path / "export-out"
    store = open_wallet_store(scope="duckdb-only:export", auto_recover=True)
    sink = StreamingDatasetSink(
        scope=scope,
        output_dir=out,
        shadow_store=store,
        authority_mode=ShadowLedgerMode.DB_PRIMARY,
        export_formats=("jsonl",),
        allow_legacy_files=False,
    )
    records = page_records(chain, 400, scope=scope)
    _run(
        sink.write(
            RecordBatch(records=tuple(records), response_bytes=8),
            context=context,
        )
    )
    _run(sink.commit(None, context=context))
    assert not (out / "records.jsonl").exists()

    # Implicit write still blocked.
    with pytest.raises(ImplicitLegacyLedgerFileError):
        sink.assert_legacy_file_write_allowed(out / "records.jsonl", kind="records_jsonl")

    # Explicit outbox drain materialises export artifacts under permit.
    pending = sink.export_outbox.pending()
    assert pending
    drained = sink.drain_export_outbox(output_dir=out)
    assert drained
    assert (out / "records.jsonl").is_file()

    # Explicit one-time import reads the export artifact (not authority).
    imported = import_legacy_jsonl_explicit(out / "records.jsonl", sink=sink)
    assert len(imported) == len(records)
    imported_ids = {str(r.get("record_id") or "") for r in imported}
    expected_ids = {record_identity(r) for r in records}
    assert imported_ids == expected_ids

    # After explicit export, implicit writes remain blocked without a permit.
    with pytest.raises(ImplicitLegacyLedgerFileError):
        get_wallet_ledger_filesystem_guard().assert_allowed(
            out / "records-implicit.jsonl",
            kind="records_jsonl",
            operation="write",
        )


def test_read_jsonl_records_never_re_admits_files_under_db_primary(
    tmp_path: Path, context: OperationContext
) -> None:
    chain = eth_chain()
    scope = "wallet:0xabc/eth-no-readback"
    out = tmp_path / "no-readback"
    store = open_wallet_store(scope="duckdb-only:no-readback", auto_recover=True)
    sink = StreamingDatasetSink(
        scope=scope,
        output_dir=out,
        shadow_store=store,
        authority_mode=ShadowLedgerMode.DB_PRIMARY,
        allow_legacy_files=False,
    )
    records = page_records(chain, 500, scope=scope)
    _run(
        sink.write(
            RecordBatch(records=tuple(records), response_bytes=8),
            context=context,
        )
    )
    _run(sink.commit(None, context=context))

    # Plant a hostile records.jsonl that must not become authority.
    out.mkdir(parents=True, exist_ok=True)
    hostile = {
        "record_id": "hostile-should-not-load",
        "record_type": "block",
        "finality": "confirmed",
        "secret": SECRET_MARKER,
    }
    (out / "records.jsonl").write_text(
        json.dumps(hostile) + "\n", encoding="utf-8"
    )

    # read_jsonl_records must rehydrate from DuckDB, ignoring the hostile file.
    rows = sink.read_jsonl_records()
    row_ids = {str(r.get("record_id") or "") for r in rows}
    assert "hostile-should-not-load" not in row_ids
    assert record_identity(records[0]) in row_ids
    text = json.dumps(list(rows), default=str)
    assert SECRET_MARKER not in text


def test_promote_to_db_primary_blocks_legacy_files(
    tmp_path: Path, context: OperationContext
) -> None:
    chain = eth_chain()
    scope = "wallet:0xabc/eth-promote"
    out = tmp_path / "promote"
    store = open_wallet_store(scope="duckdb-only:promote", auto_recover=True)
    sink = StreamingDatasetSink(
        scope=scope,
        output_dir=out,
        shadow_store=store,
        authority_mode=ShadowLedgerMode.DUAL,
        export_formats=("jsonl",),
    )
    assert sink.duckdb_only is False
    mode = sink.promote_to_db_primary()
    assert mode is ShadowLedgerMode.DB_PRIMARY
    assert sink.duckdb_only is True
    assert sink.allow_legacy_files is False

    records = page_records(chain, 600, scope=scope)
    _run(
        sink.write(
            RecordBatch(records=tuple(records), response_bytes=4),
            context=context,
        )
    )
    _run(sink.commit(None, context=context))
    assert not (out / "records.jsonl").exists()
    with pytest.raises(ImplicitLegacyLedgerFileError):
        sink.filesystem_guard.assert_allowed(out / "records.jsonl")
