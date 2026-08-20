"""E2E: DuckDB-only processor wallet ledger after legacy file removal (DQK-073).

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
    WALLET_CHECKPOINT_ONLY_OWNER_TASK,
    build_checkpoint,
    new_revision,
)
from ipfs_datasets_py.processors.wallets.duckdb_storage import open_wallet_store
from ipfs_datasets_py.processors.wallets.errors import CheckpointError, DatasetSinkError
from ipfs_datasets_py.processors.wallets.export import (
    ExportFormat,
    NAMED_LEDGER_EXPORT_COMMANDS,
    PUBLIC_LEDGER_QUACK_TABLE,
    WalletDatasetExporter,
    drain_wallet_export_outbox,
    publish_redacted_public_ledger_analytics,
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
    BoundedRequest,
    Capabilities,
    Capability,
    OperationContext,
    RecordBatch,
    RequestLimits,
)
from ipfs_datasets_py.processors.wallets.storage import (
    DirectoryRawPayloadStore,
    ImplicitLegacyLedgerWriteError,
    LEGACY_WALLET_LEDGER_FILENAMES,
    LedgerFilesystemGuard,
    ShadowLedgerMode,
    StreamingDatasetSink,
    WALLET_LEDGER_ONLY_DEFAULT_MODE,
    WALLET_LEDGER_ONLY_OWNER_TASK,
    assert_legacy_wallet_ledger_files_absent,
    assert_publication_excludes_secrets,
    assert_shadow_catalog_excludes_secrets,
    build_redacted_public_ledger_analytics,
    legacy_wallet_ledger_files_present,
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


@pytest.fixture
def context() -> OperationContext:
    return OperationContext(
        request_id="dqk-073-e2e-1",
        limits=RequestLimits(
            max_items=100,
            max_pages=20,
            max_requests=40,
            max_response_bytes=64 * 1024,
        ),
    )


# ---------------------------------------------------------------------------
# Pins / surface
# ---------------------------------------------------------------------------


def test_dqk073_owner_and_named_export_pins() -> None:
    assert WALLET_LEDGER_ONLY_OWNER_TASK == "DQK-073"
    assert WALLET_CHECKPOINT_ONLY_OWNER_TASK == "DQK-073"
    assert WALLET_LEDGER_ONLY_DEFAULT_MODE == "db-primary"
    assert "export_ledger_jsonl" in NAMED_LEDGER_EXPORT_COMMANDS
    assert "drain_export_outbox" in NAMED_LEDGER_EXPORT_COMMANDS
    assert "records.jsonl" in LEGACY_WALLET_LEDGER_FILENAMES
    assert "export-manifest.json" in LEGACY_WALLET_LEDGER_FILENAMES
    assert PUBLIC_LEDGER_QUACK_TABLE == "public_ledger_analytics"
    assert ShadowLedgerMode.EXPORT_ONLY.blocks_implicit_legacy_files is True
    assert ShadowLedgerMode.DB_PRIMARY.memory_is_authority is False
    assert ShadowLedgerMode.EXPORT_ONLY.duckdb_is_authority is True


# ---------------------------------------------------------------------------
# Ingestion resumes from DuckDB with legacy files absent
# ---------------------------------------------------------------------------


def test_ingest_resume_from_duckdb_with_legacy_files_absent(
    tmp_path: Path, context: OperationContext
) -> None:
    """Commit + crash + rehydrate works with no records.jsonl / meta / manifest."""

    chain = eth_chain()
    page1 = page_records(chain, 100)
    page2 = page_records(chain, 101)
    store = open_wallet_store(scope="dqk073:resume", auto_recover=True)
    out = tmp_path / "ledger-out"
    out.mkdir()

    # Prove legacy operational files start absent.
    assert_legacy_wallet_ledger_files_absent(out)
    assert legacy_wallet_ledger_files_present(out) == ()

    sink = StreamingDatasetSink(
        scope="wallet:0xabc/eth-resume",
        output_dir=out,
        shadow_store=store,
        authority_mode=ShadowLedgerMode.EXPORT_ONLY,
        # No implicit formats — DuckDB only until an explicit drain.
        export_formats=(),
    )
    assert sink.authority_mode is ShadowLedgerMode.EXPORT_ONLY
    assert sink.memory_is_authority is False
    assert sink.owner_task_id == WALLET_LEDGER_ONLY_OWNER_TASK

    checkpoints = InMemoryCheckpointStore(
        shadow_store=store, authority_mode=ShadowLedgerMode.EXPORT_ONLY
    )
    assert checkpoints.memory_is_authority is False
    assert checkpoints.owner_task_id == WALLET_CHECKPOINT_ONLY_OWNER_TASK

    identity = CheckpointIdentity(
        chain=chain,
        provider="fixture-rpc",
        scope="wallet:0xabc/eth-resume",
        normalized_schema_major=1,
        normalizer_version="fixture-normalizer@1.0.0",
    )

    # Commit page 1 to DuckDB authority.
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

    tip = build_checkpoint(
        identity,
        sequence=100,
        block_hash="0xethblock100",
        revision=new_revision(),
        sink_commit_id=commit1.commit_id,
    )
    accepted = _run(
        checkpoints.compare_and_set(
            identity.key,
            expected_revision=None,
            checkpoint=tip,
            context=context,
        )
    )
    assert accepted is True

    # No legacy files after durable commit (export-only never implies JSONL).
    assert_legacy_wallet_ledger_files_absent(out)
    assert not (out / "records.jsonl").exists()
    assert not (out / "export-manifest.json").exists()
    assert list(out.rglob("*.meta.json")) == []

    # Stage page 2, crash before authority commit, recover from DuckDB only.
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

    # Fresh process view: empty memory projection, load tip from DuckDB.
    restarted_cp = InMemoryCheckpointStore(
        shadow_store=store, authority_mode=ShadowLedgerMode.EXPORT_ONLY
    )
    loaded = _run(restarted_cp.load(identity.key, context=context))
    assert loaded is not None
    assert loaded.anchor.sequence == 100
    assert loaded.revision == tip.revision

    # Clear memory ghosts and rehydrate ledger rows exclusively from DuckDB.
    restarted_sink = StreamingDatasetSink(
        scope="wallet:0xabc/eth-resume",
        output_dir=out,
        shadow_store=store,
        authority_mode=ShadowLedgerMode.DB_PRIMARY,
        export_formats=(),
    )
    rehydrated = restarted_sink.rehydrate_from_authority()
    assert rehydrated == len(page1)
    assert restarted_sink.authority_record_ids() == ids_after_p1
    assert_legacy_wallet_ledger_files_absent(out)

    # Resume page 2 after recover.
    restarted_sink.reset_for_resume()
    _run(
        restarted_sink.write(
            RecordBatch(records=tuple(page2), response_bytes=32),
            context=context,
        )
    )
    commit2 = _run(restarted_sink.commit(None, context=context))
    expected = {record_identity(r) for r in page1 + page2}
    assert restarted_sink.authority_record_ids() == expected
    assert commit2.record_count == len(expected)

    # Implicit records.jsonl flush is blocked under DuckDB-only modes.
    with pytest.raises(ImplicitLegacyLedgerWriteError):
        restarted_sink._flush_committed_jsonl("sha256:" + ("00" * 32))
    assert not (out / "records.jsonl").exists()

    # Reject treating legacy files as operational authority.
    with pytest.raises(DatasetSinkError, match="DQK-073"):
        restarted_sink.reject_legacy_file_authority(artifact="records.jsonl")


def test_in_memory_checkpoint_not_authority_without_duckdb() -> None:
    with pytest.raises(CheckpointError, match="DQK-073"):
        InMemoryCheckpointStore(authority_mode=ShadowLedgerMode.EXPORT_ONLY)
    with pytest.raises(CheckpointError, match="DQK-073"):
        InMemoryCheckpointStore(authority_mode=ShadowLedgerMode.DB_PRIMARY)


def test_raw_payload_refs_without_meta_json(
    tmp_path: Path, context: OperationContext
) -> None:
    """Encrypted/CID raw-object identity does not require .meta.json authority."""

    root = tmp_path / "raw"
    store = DirectoryRawPayloadStore(
        root,
        write_meta_json=False,
        policy=RawPayloadPolicy.REFERENCED,
        encryptor=None,
    )
    body = b'{"public":"ledger-payload"}'
    stored = _run(
        store.put(body, media_type="application/json", cid=CID, context=context)
    )
    assert stored.digest.startswith("sha256:")
    assert stored.cid == CID
    assert list(root.glob("*.meta.json")) == []
    assert list(root.glob("*.bin"))

    loaded = _run(store.get(stored.digest, context=context))
    assert loaded is not None
    assert loaded.body == body
    assert loaded.media_type == "application/json"
    assert loaded.cid == CID

    # DuckDB authority stores only the ref — never body bytes.
    wallet = open_wallet_store(scope="dqk073:raw-ref", auto_recover=True)
    chain = eth_chain()
    ref_row = wallet.put_encrypted_object_ref(
        stored.to_ref(),
        chain=chain,
        provenance=_provenance(chain, "wallet:raw"),
        finality=Finality.CONFIRMED,
    )
    assert "body" not in ref_row
    assert "raw_payload" not in ref_row
    assert ref_row.get("digest") == stored.digest or "digest" in str(ref_row)
    assert_shadow_catalog_excludes_secrets(wallet)


# ---------------------------------------------------------------------------
# Filesystem guard + explicit exports only
# ---------------------------------------------------------------------------


def test_filesystem_guard_blocks_implicit_legacy_writes(tmp_path: Path) -> None:
    guard = LedgerFilesystemGuard(tmp_path)
    for name in (
        "records.jsonl",
        "export-manifest.json",
        "export-partitions.json",
        "content.digest",
        "sha256_ab.bin.meta.json",
    ):
        with pytest.raises(ImplicitLegacyLedgerWriteError) as excinfo:
            guard.assert_write_allowed(tmp_path / name, kind="legacy")
        assert "implicit" in str(excinfo.value).lower()

    # Explicit export permit allows materialisation.
    target = tmp_path / "records.jsonl"
    with guard.permit_export():
        guard.assert_write_allowed(target, kind="records_jsonl")
        target.write_text("{}\n", encoding="utf-8")
    assert target.is_file()


def test_explicit_export_materialises_files_only_when_named(
    tmp_path: Path, context: OperationContext
) -> None:
    chain = eth_chain()
    records = page_records(chain, 200)
    store = open_wallet_store(scope="dqk073:export", auto_recover=True)
    out = tmp_path / "export-out"
    sink = StreamingDatasetSink(
        scope="wallet:export",
        output_dir=out,
        shadow_store=store,
        authority_mode=ShadowLedgerMode.DB_PRIMARY,
        export_formats=("jsonl",),
    )
    _run(
        sink.write(
            RecordBatch(records=tuple(records), response_bytes=16),
            context=context,
        )
    )
    _run(sink.commit(None, context=context))
    # Pending outbox exists but files are still absent until named drain.
    assert sink.export_outbox.pending()
    assert_legacy_wallet_ledger_files_absent(out)

    drained = sink.drain_export_outbox(formats=("jsonl",), output_dir=out)
    assert drained
    assert "drain_export_outbox" in sink.named_export_invocations()
    assert (out / "records.jsonl").is_file()

    # Exporter with explicit_export_only + persist_manifest writes guarded files.
    export_dir = tmp_path / "named-export"
    exporter = WalletDatasetExporter(
        chain=chain,
        output_dir=export_dir,
        formats=(ExportFormat.JSONL,),
        explicit_export_only=True,
        persist_manifest=True,
    )
    receipt = _run(
        exporter.export_records(
            records,
            context=context,
            scope="wallet:export",
        )
    )
    assert receipt.complete
    assert (export_dir / "export-manifest.json").is_file()
    assert "export_ledger_manifest" in exporter.named_export_invocations()
    # Manifest is non-authoritative.
    manifest = json.loads((export_dir / "export-partitions.json").read_text())
    assert manifest.get("authoritative") is False
    assert manifest.get("owner_task_id") == WALLET_LEDGER_ONLY_OWNER_TASK


# ---------------------------------------------------------------------------
# No secrets in publication; Quack redacted analytics only
# ---------------------------------------------------------------------------


def test_no_raw_secrets_reach_publication_and_quack_analytics_only(
    tmp_path: Path, context: OperationContext
) -> None:
    chain = eth_chain()
    records = page_records(chain, 300) + page_records(chain, 301)
    store = open_wallet_store(scope="dqk073:pub", auto_recover=True)
    sink = StreamingDatasetSink(
        scope="wallet:pub",
        shadow_store=store,
        authority_mode=ShadowLedgerMode.EXPORT_ONLY,
        export_formats=(),
    )
    _run(
        sink.write(
            RecordBatch(records=tuple(records), response_bytes=24),
            context=context,
        )
    )
    _run(sink.commit(None, context=context))

    # Authority catalog has no secret-bearing columns / raw bytes.
    assert_shadow_catalog_excludes_secrets(store)

    # Register a raw ref only (CID/digest) — never body bytes.
    block = records[0]
    assert isinstance(block, BlockRecord)
    store.put_encrypted_object_ref(
        RawPayloadRef(
            digest=DIGEST,
            cid=CID,
            media_type="application/json",
            byte_length=64,
        ),
        chain=chain,
        provenance=_provenance(chain, "wallet:pub"),
        finality=Finality.CONFIRMED,
        related_record_id=block.record_id,
    )
    assert_shadow_catalog_excludes_secrets(store)

    document = dict(
        build_redacted_public_ledger_analytics(store, scope="wallet:pub")
    )
    assert document["owner_task_id"] == WALLET_LEDGER_ONLY_OWNER_TASK
    assert document["operational_authority"] == "duckdb"
    assert document["sensitive_raw_excluded"] is True
    assert document["payload_body_excluded"] is True
    assert document["legacy_file_authority"] is False
    assert document["quack_surface"] == "redacted_public_ledger_analytics"
    assert document["total_records"] >= len(records)
    assert document["aggregates"]
    assert_publication_excludes_secrets(document)

    # Structural: no secret keys/values on the publication surface.
    doc_text = json.dumps(document)
    for needle in (
        "private_key",
        "mnemonic",
        "password",
        "api_key",
        "payload_bytes",
        "ciphertext",
        "BEGIN PRIVATE KEY",
    ):
        assert needle not in doc_text

    # Quack materialisation path (hermetic publication plane when available).
    pub = publish_redacted_public_ledger_analytics(
        store, scope="wallet:pub", publication_plane=None
    )
    assert pub["ok"] is True
    assert pub["quack_surface"] == "redacted_public_ledger_analytics"
    assert pub["table_name"] == PUBLIC_LEDGER_QUACK_TABLE
    assert pub["authority_catalogs_attached"] is False
    assert_publication_excludes_secrets(pub)

    try:
        from ipfs_datasets_py.duckdb_control.publication import PublicationPlane
    except Exception:
        pytest.skip("publication plane not importable in this environment")

    plane = PublicationPlane(
        str(tmp_path / "publication.duckdb"),
        clock=lambda: NOW,
        clock_ms=lambda: int(NOW.timestamp() * 1000),
    )
    try:
        materialized = publish_redacted_public_ledger_analytics(
            store,
            scope="wallet:pub",
            publication_plane=plane,
        )
        assert materialized["materialized"] is True
        assert materialized["authority_catalogs_attached"] is False
        assert_publication_excludes_secrets(materialized)
        if hasattr(plane, "assert_sensitive_surfaces_absent"):
            plane.assert_sensitive_surfaces_absent()
    finally:
        close = getattr(plane, "close", None)
        if callable(close):
            close()


def test_checkpoint_cas_resume_stale_fails_under_export_only(
    context: OperationContext,
) -> None:
    chain = eth_chain()
    store = open_wallet_store(scope="dqk073:cas", auto_recover=True)
    checkpoints = InMemoryCheckpointStore(
        shadow_store=store, authority_mode=ShadowLedgerMode.EXPORT_ONLY
    )
    identity = CheckpointIdentity(
        chain=chain,
        provider="fixture-rpc",
        scope="wallet:cas",
        normalized_schema_major=1,
        normalizer_version="fixture-normalizer@1.0.0",
    )
    first = build_checkpoint(
        identity, sequence=10, block_hash="0xhash10", revision=new_revision()
    )
    assert _run(
        checkpoints.compare_and_set(
            identity.key,
            expected_revision=None,
            checkpoint=first,
            context=context,
        )
    )
    stale = build_checkpoint(
        identity, sequence=11, block_hash="0xhash11", revision=new_revision()
    )
    assert (
        _run(
            checkpoints.compare_and_set(
                identity.key,
                expected_revision="rev:stale",
                checkpoint=stale,
                context=context,
            )
        )
        is False
    )
    # Drop memory projection; DuckDB tip remains.
    checkpoints.clear_memory_projection()
    reloaded = _run(checkpoints.load(identity.key, context=context))
    assert reloaded is not None
    assert reloaded.revision == first.revision
    assert reloaded.anchor.sequence == 10
