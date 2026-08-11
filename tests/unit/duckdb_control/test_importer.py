"""Unit tests for the streaming legacy artifact importer (DQK-044).

Acceptance coverage:

* Interrupted imports resume exactly
* Original byte digests and line/record provenance are retained
* Exports are never silently re-imported
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import struct
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
_LOCAL_ACCELERATE = (_REPO_ROOT / "ipfs_accelerate_py").resolve()


def _prefer_sealed_accelerate_checkout() -> None:
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

import pytest

from ipfs_datasets_py.duckdb_control.contracts import (
    EXPORT_RECEIPT_SCHEMA,
    IdempotencyKey,
    SourceDigest,
)
from ipfs_datasets_py.duckdb_control.importer import (
    DEFAULT_BATCH_SIZES,
    IMPORTER_SCHEMA,
    ArtifactImporter,
    ImportError,
    ImportStatus,
    MemoryImportBackend,
    SourceKind,
    batch_size_for,
    detect_source_kind,
    is_export_artifact,
    source_digest_for_path,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write(path: Path, data: str | bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(data, bytes):
        path.write_bytes(data)
    else:
        path.write_text(data, encoding="utf-8")
    return path


def _sha256_file(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _minimal_parquet(path: Path) -> Path:
    """Write a minimal PAR1-framed blob (metadata-only decoder path)."""

    # footer payload can be arbitrary for our metadata-only reader
    footer = b"parquet-footer-placeholder"
    body = b"ROWIDATA"
    with path.open("wb") as handle:
        handle.write(b"PAR1")
        handle.write(body)
        handle.write(footer)
        handle.write(struct.pack("<I", len(footer)))
        handle.write(b"PAR1")
    return path


# ---------------------------------------------------------------------------
# Kind detection / batch sizes / export guard
# ---------------------------------------------------------------------------


def test_detect_source_kind_by_extension() -> None:
    assert detect_source_kind("data/items.jsonl") is SourceKind.JSONL
    assert detect_source_kind("state/tasks.json") is SourceKind.JSON
    assert detect_source_kind("board.taskboard.todo.md") is SourceKind.MARKDOWN_TASKBOARD
    assert detect_source_kind("cache.sqlite") is SourceKind.SQLITE
    assert detect_source_kind("table.parquet") is SourceKind.PARQUET
    assert detect_source_kind("vectors.meta.json") is SourceKind.VECTOR_METADATA
    assert detect_source_kind("dataset_manifest.json") is SourceKind.MANIFEST
    assert detect_source_kind("x.bin", explicit="jsonl") is SourceKind.JSONL


def test_batch_size_defaults_are_positive_and_type_specific() -> None:
    assert batch_size_for(SourceKind.JSONL) == DEFAULT_BATCH_SIZES["jsonl"]
    assert batch_size_for(SourceKind.MARKDOWN_TASKBOARD) == DEFAULT_BATCH_SIZES[
        "markdown_taskboard"
    ]
    assert batch_size_for(SourceKind.JSONL, 3) == 3
    with pytest.raises(ImportError):
        batch_size_for(SourceKind.JSON, 0)


def test_is_export_artifact_path_and_payload() -> None:
    assert is_export_artifact("workspace/exports/report.json") is True
    assert is_export_artifact("data/state/tasks.jsonl") is False
    payload = {
        "schema": EXPORT_RECEIPT_SCHEMA,
        "export_id": "exp-1",
        "non_authoritative": True,
        "renderer_version": "1",
        "snapshot": {"value": "s1"},
    }
    assert is_export_artifact("any/path.json", payload=payload) is True


# ---------------------------------------------------------------------------
# Digests and provenance
# ---------------------------------------------------------------------------


def test_source_digest_matches_exact_bytes(tmp_path: Path) -> None:
    path = _write(tmp_path / "payload.jsonl", b'{"a":1}\n{"b":2}\n')
    digest = source_digest_for_path(path)
    assert digest.digest == _sha256_file(path)
    assert digest.digest == SourceDigest.from_bytes(path.read_bytes()).digest


def test_jsonl_import_retains_line_and_record_provenance(tmp_path: Path) -> None:
    lines = [
        '{"id": "a", "n": 1}',
        "not-json",
        '{"id": "b", "n": 2}',
    ]
    path = _write(tmp_path / "rows.jsonl", "\n".join(lines) + "\n")
    backend = MemoryImportBackend()
    importer = ArtifactImporter(backend)
    receipt = importer.import_path(
        path,
        display_path="rows.jsonl",
        batch_size=10,
        idempotency_key="jsonl-prov-1",
    )
    assert receipt.status == ImportStatus.COMPLETED.value
    assert receipt.accepted_count == 2
    assert receipt.rejected_count == 1
    assert receipt.source_digest == _sha256_file(path)

    records = list(backend.list_records(receipt.job_id))
    assert [r.record_index for r in records] == [0, 2]
    assert records[0].line_number == 1
    assert records[1].line_number == 3
    assert all(r.source_digest == receipt.source_digest for r in records)
    assert all(r.source_path == "rows.jsonl" for r in records)

    rejects = list(backend.list_rejects(receipt.job_id))
    assert len(rejects) == 1
    assert rejects[0].line_number == 2
    assert rejects[0].record_index == 1
    assert rejects[0].source_digest == receipt.source_digest
    assert "not-json" in rejects[0].raw_snippet


def test_json_array_import_preserves_indices(tmp_path: Path) -> None:
    path = _write(
        tmp_path / "arr.json",
        json.dumps([{"i": 0}, {"i": 1}, {"i": 2}], separators=(",", ":")),
    )
    backend = MemoryImportBackend()
    receipt = ArtifactImporter(backend).import_path(
        path,
        display_path="arr.json",
        batch_size=2,
        idempotency_key="json-arr-1",
    )
    assert receipt.accepted_count == 3
    records = list(backend.list_records(receipt.job_id))
    assert [json.loads(r.payload_json)["i"] for r in records] == [0, 1, 2]
    assert [r.record_index for r in records] == [0, 1, 2]


# ---------------------------------------------------------------------------
# Resume exactly
# ---------------------------------------------------------------------------


def test_interrupted_import_resumes_exactly(tmp_path: Path) -> None:
    # 5 records, batch_size=2 → commit after records 0-1, then crash.
    rows = [{"id": i} for i in range(5)]
    path = _write(
        tmp_path / "stream.jsonl",
        "\n".join(json.dumps(r, separators=(",", ":")) for r in rows) + "\n",
    )
    backend = MemoryImportBackend()
    importer = ArtifactImporter(backend)

    with pytest.raises(ImportError, match="simulated interrupt"):
        importer.import_path(
            path,
            display_path="stream.jsonl",
            batch_size=2,
            idempotency_key="resume-exact-1",
            crash_after_batches=1,
        )

    cursor = backend.get_cursor(
        backend.get_job_by_idempotency(key="resume-exact-1", scope="import").job_id  # type: ignore[union-attr]
    )
    assert cursor is not None
    assert cursor.next_record_index == 2
    assert cursor.accepted_count == 2
    assert len(backend.list_records(cursor.job_id)) == 2
    assert backend.get_in_progress() == cursor.job_id

    # resume=False fail-closes
    with pytest.raises(ImportError, match="resume=True"):
        importer.import_path(
            path,
            display_path="stream.jsonl",
            batch_size=2,
            idempotency_key="resume-exact-1",
            resume=False,
        )

    receipt = importer.import_path(
        path,
        display_path="stream.jsonl",
        batch_size=2,
        idempotency_key="resume-exact-1",
        resume=True,
    )
    assert receipt.status == ImportStatus.COMPLETED.value
    assert receipt.resumed is True
    assert receipt.accepted_count == 5
    records = list(backend.list_records(receipt.job_id))
    assert len(records) == 5
    # No duplicates: one row per original record_index.
    assert sorted(r.record_index for r in records) == [0, 1, 2, 3, 4]
    ids = [json.loads(r.payload_json)["id"] for r in records]
    assert ids == [0, 1, 2, 3, 4]
    assert backend.get_in_progress() is None


def test_resume_rejects_source_digest_drift(tmp_path: Path) -> None:
    path = _write(tmp_path / "drift.jsonl", '{"a":1}\n{"b":2}\n{"c":3}\n')
    backend = MemoryImportBackend()
    importer = ArtifactImporter(backend)
    with pytest.raises(ImportError, match="simulated interrupt"):
        importer.import_path(
            path,
            display_path="drift.jsonl",
            batch_size=1,
            idempotency_key="drift-1",
            crash_after_batches=1,
        )
    # Mutate source bytes under the same path.
    path.write_text('{"a":1}\n{"b":2}\n{"c":3}\n{"d":4}\n', encoding="utf-8")
    with pytest.raises(ImportError, match="digest"):
        importer.import_path(
            path,
            display_path="drift.jsonl",
            batch_size=1,
            idempotency_key="drift-1",
            resume=True,
        )


def test_max_batches_partial_then_resume(tmp_path: Path) -> None:
    path = _write(
        tmp_path / "partial.jsonl",
        "\n".join(json.dumps({"n": i}) for i in range(6)) + "\n",
    )
    backend = MemoryImportBackend()
    importer = ArtifactImporter(backend)
    partial = importer.import_path(
        path,
        display_path="partial.jsonl",
        batch_size=2,
        idempotency_key="partial-1",
        max_batches=1,
    )
    assert partial.status == ImportStatus.RUNNING.value
    assert partial.accepted_count == 2
    done = importer.import_path(
        path,
        display_path="partial.jsonl",
        batch_size=2,
        idempotency_key="partial-1",
        resume=True,
    )
    assert done.status == ImportStatus.COMPLETED.value
    assert done.accepted_count == 6
    assert len(backend.list_records(done.job_id)) == 6


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------


def test_idempotent_reimport_does_not_duplicate(tmp_path: Path) -> None:
    path = _write(tmp_path / "once.json", json.dumps([{"x": 1}, {"x": 2}]))
    backend = MemoryImportBackend()
    importer = ArtifactImporter(backend)
    first = importer.import_path(
        path,
        display_path="once.json",
        idempotency_key=IdempotencyKey(key="once-key", scope="import"),
    )
    second = importer.import_path(
        path,
        display_path="once.json",
        idempotency_key=IdempotencyKey(key="once-key", scope="import"),
    )
    assert first.status == ImportStatus.COMPLETED.value
    assert second.status == ImportStatus.SKIPPED_IDEMPOTENT.value
    assert len(backend.list_records(first.job_id)) == 2
    assert second.accepted_count == first.accepted_count


def test_idempotency_key_digest_conflict_fail_closed(tmp_path: Path) -> None:
    path_a = _write(tmp_path / "a.jsonl", '{"v":1}\n')
    path_b = _write(tmp_path / "b.jsonl", '{"v":2}\n')
    backend = MemoryImportBackend()
    importer = ArtifactImporter(backend)
    importer.import_path(
        path_a, display_path="a.jsonl", idempotency_key="same-key"
    )
    with pytest.raises(ImportError, match="idempotency"):
        importer.import_path(
            path_b, display_path="b.jsonl", idempotency_key="same-key"
        )


# ---------------------------------------------------------------------------
# Exports never silently re-imported
# ---------------------------------------------------------------------------


def test_export_path_refused_without_allow_exports(tmp_path: Path) -> None:
    path = _write(tmp_path / "exports" / "report.json", json.dumps({"ok": True}))
    backend = MemoryImportBackend()
    with pytest.raises(ImportError, match="never silently re-imported"):
        ArtifactImporter(backend).import_path(
            path,
            display_path="workspace/exports/report.json",
            idempotency_key="export-1",
        )
    # No records written.
    assert backend.records == {}


def test_export_receipt_payload_refused(tmp_path: Path) -> None:
    payload = {
        "schema": EXPORT_RECEIPT_SCHEMA,
        "export_id": "exp-42",
        "non_authoritative": True,
        "renderer_version": "v1",
        "snapshot": {"value": "snap-1", "store_generation": 0},
        "content": {
            "media_type": "json",
            "content_id": "sha256:" + ("ab" * 32),
            "byte_size": 1,
        },
        "created_at": "2026-01-01T00:00:00Z",
    }
    path = _write(tmp_path / "receipt.json", json.dumps(payload))
    with pytest.raises(ImportError, match="never silently re-imported"):
        ArtifactImporter(MemoryImportBackend()).import_path(
            path,
            display_path="receipt.json",
            idempotency_key="export-receipt-1",
        )


def test_export_allowed_only_with_explicit_flag(tmp_path: Path) -> None:
    path = _write(
        tmp_path / "exports" / "ok.json",
        json.dumps([{"row": 1}, {"row": 2}]),
    )
    backend = MemoryImportBackend()
    receipt = ArtifactImporter(backend).import_path(
        path,
        display_path="workspace/exports/ok.json",
        idempotency_key="export-ok-1",
        allow_exports=True,
    )
    assert receipt.status == ImportStatus.COMPLETED.value
    assert receipt.accepted_count == 2


def test_export_receipt_rows_inside_array_are_rejected(tmp_path: Path) -> None:
    payload = [
        {"id": "ok"},
        {
            "schema": EXPORT_RECEIPT_SCHEMA,
            "export_id": "nested-exp",
            "non_authoritative": True,
            "renderer_version": "v1",
            "snapshot": {"value": "s"},
        },
    ]
    path = _write(tmp_path / "mixed.json", json.dumps(payload))
    backend = MemoryImportBackend()
    receipt = ArtifactImporter(backend).import_path(
        path,
        display_path="mixed.json",
        idempotency_key="mixed-1",
    )
    assert receipt.accepted_count == 1
    assert receipt.rejected_count == 1
    rejects = list(backend.list_rejects(receipt.job_id))
    assert "export" in rejects[0].reason.lower()


# ---------------------------------------------------------------------------
# Type-specific adapters
# ---------------------------------------------------------------------------


def test_markdown_taskboard_import(tmp_path: Path) -> None:
    md = """# Goal Alpha

- [ ] First task
- [x] Done task

## Section B

- [ ] Nested work
"""
    path = _write(tmp_path / "plan.taskboard.todo.md", md)
    backend = MemoryImportBackend()
    receipt = ArtifactImporter(backend).import_path(
        path,
        display_path="plan.taskboard.todo.md",
        idempotency_key="md-1",
        batch_size=2,
    )
    assert receipt.source_kind == SourceKind.MARKDOWN_TASKBOARD.value
    assert receipt.accepted_count == 3
    records = list(backend.list_records(receipt.job_id))
    bodies = [json.loads(r.payload_json) for r in records]
    assert bodies[0]["text"] == "First task"
    assert bodies[0]["done"] is False
    assert bodies[1]["done"] is True
    assert bodies[2]["section"] == ["Goal Alpha", "Section B"]
    # Line provenance points at original markdown lines.
    assert records[0].line_number == 3
    assert records[1].line_number == 4
    assert records[2].line_number == 8


def test_sqlite_import_with_row_provenance(tmp_path: Path) -> None:
    db_path = tmp_path / "legacy.sqlite"
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("CREATE TABLE items (name TEXT, value INTEGER)")
        conn.executemany(
            "INSERT INTO items(name, value) VALUES (?, ?)",
            [("alpha", 1), ("beta", 2), ("gamma", 3)],
        )
        conn.commit()
    finally:
        conn.close()

    backend = MemoryImportBackend()
    receipt = ArtifactImporter(backend).import_path(
        db_path,
        display_path="legacy.sqlite",
        idempotency_key="sqlite-1",
        batch_size=2,
    )
    assert receipt.source_kind == SourceKind.SQLITE.value
    assert receipt.accepted_count == 3
    assert receipt.source_digest == _sha256_file(db_path)
    records = list(backend.list_records(receipt.job_id))
    assert all(r.table_name == "items" for r in records)
    names = [json.loads(r.payload_json)["name"] for r in records]
    assert names == ["alpha", "beta", "gamma"]
    assert all(r.source_digest == receipt.source_digest for r in records)


def test_manifest_import_expands_files(tmp_path: Path) -> None:
    manifest = {
        "name": "bundle",
        "files": [
            {"path": "a.parquet", "cid": "Qm" + ("a" * 44)},
            {"path": "b.parquet", "cid": "Qm" + ("b" * 44)},
        ],
    }
    # Use a name that detects as manifest.
    path = _write(tmp_path / "bundle_manifest.json", json.dumps(manifest))
    backend = MemoryImportBackend()
    receipt = ArtifactImporter(backend).import_path(
        path,
        display_path="bundle_manifest.json",
        idempotency_key="manifest-1",
    )
    assert receipt.source_kind == SourceKind.MANIFEST.value
    assert receipt.accepted_count == 2
    records = list(backend.list_records(receipt.job_id))
    assert json.loads(records[0].payload_json)["path"] == "a.parquet"


def test_vector_metadata_import(tmp_path: Path) -> None:
    meta = {
        "collection": "docs",
        "entries": [
            {"chunk_id": "c1", "dim": 3, "model": "test-emb"},
            {"chunk_id": "c2", "dim": 3, "model": "test-emb"},
        ],
    }
    path = _write(tmp_path / "docs.meta.json", json.dumps(meta))
    backend = MemoryImportBackend()
    receipt = ArtifactImporter(backend).import_path(
        path,
        display_path="docs.meta.json",
        idempotency_key="vec-1",
    )
    assert receipt.source_kind == SourceKind.VECTOR_METADATA.value
    assert receipt.accepted_count == 2


def test_parquet_metadata_only_import(tmp_path: Path) -> None:
    path = _minimal_parquet(tmp_path / "shard.parquet")
    backend = MemoryImportBackend()
    receipt = ArtifactImporter(backend).import_path(
        path,
        display_path="shard.parquet",
        idempotency_key="pq-1",
    )
    assert receipt.source_kind == SourceKind.PARQUET.value
    assert receipt.accepted_count == 1
    assert receipt.source_digest == _sha256_file(path)
    payload = json.loads(backend.list_records(receipt.job_id)[0].payload_json)
    assert payload["kind"] == "parquet_source"
    assert payload["footer_digest"].startswith("sha256:")


# ---------------------------------------------------------------------------
# Bounded batches and schema identity
# ---------------------------------------------------------------------------


def test_type_specific_batching_commits_cursors(tmp_path: Path) -> None:
    path = _write(
        tmp_path / "batched.jsonl",
        "\n".join(json.dumps({"i": i}) for i in range(5)) + "\n",
    )
    backend = MemoryImportBackend()
    commits: list[int] = []

    def on_commit(cursor, job) -> None:  # type: ignore[no-untyped-def]
        commits.append(cursor.next_record_index)

    receipt = ArtifactImporter(backend).import_path(
        path,
        display_path="batched.jsonl",
        batch_size=2,
        idempotency_key="batch-1",
        on_batch_commit=on_commit,
    )
    assert receipt.status == ImportStatus.COMPLETED.value
    # Batches of 2: after 2, after 4, then final remainder (5).
    assert commits[0] == 2
    assert commits[1] == 4
    assert receipt.accepted_count == 5


def test_importer_schema_constant() -> None:
    assert IMPORTER_SCHEMA.startswith("ipfs_datasets_py/duckdb-control-importer@")
    assert ArtifactImporter.SCHEMA == IMPORTER_SCHEMA


def test_empty_jsonl_completes_with_zero_records(tmp_path: Path) -> None:
    path = _write(tmp_path / "empty.jsonl", "")
    receipt = ArtifactImporter(MemoryImportBackend()).import_path(
        path,
        display_path="empty.jsonl",
        idempotency_key="empty-1",
    )
    assert receipt.status == ImportStatus.COMPLETED.value
    assert receipt.accepted_count == 0
    assert receipt.total_records == 0
