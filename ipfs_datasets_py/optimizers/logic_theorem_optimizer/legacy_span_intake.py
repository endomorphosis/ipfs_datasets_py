"""Recover source text for a pinned span progress ledger without granting authority.

The Hub resume parquet contains identifiers and status, not source sentences.
This module joins those identifiers to sentences regenerated from an independently
verified, local U.S. Code source parquet. It neither downloads nor compiles,
trains, publishes, opens a live catalog, or acknowledges completed model work.
The caller supplies its sole-owner DuckDB connection and durably records each
returned batch before advancing ``next_section``.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Any, Iterator
import uuid


SCHEMA = "legacy-autoencoder-span-intake/v1"
SOURCE_REPOSITORY = "justicedao/ipfs_uscode"
PROGRESS_REPOSITORY = "justicedao/uscode-autoformal-span-cache"
SOURCE_REVISION = "5016b86a273ce5e4ffd066c5ae9f5fe494dd417e"
DEFAULT_RELEASE_ID = "ipfs-uscode-5016b86a"
IDENTITY_RECONSTRUCTION = "historical-64-document-ordinal/v1"
HISTORICAL_DOCUMENT_BATCH_SIZE = 64
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_REVISION = re.compile(r"[0-9a-f]{40}\Z")
_DATASETS = {"ipfs_uscode", SOURCE_REPOSITORY}


class SpanIntakeError(ValueError):
    """An input identity, immutable source, or intake bound was violated."""


@dataclass
class ProgressIndex:
    """Temporary source-identity index in the caller's already-owned connection.

    ``matched`` records source hydration only, never successful inference or an
    imported status. It resets when this index is rebuilt; campaign completion
    and restart acknowledgments belong to the caller's durable queue.
    """

    connection: Any
    table: str
    progress: dict[str, Any]
    stats: dict[str, Any]


def _positive(value: int, label: str) -> int:
    if type(value) is not int or value < 1:
        raise SpanIntakeError(label + " must be a positive integer")
    return value


def _file_identity(path: str | Path, expected_sha256: str, *, max_bytes: int) -> dict[str, Any]:
    if not isinstance(expected_sha256, str) or not _SHA.fullmatch(expected_sha256):
        raise SpanIntakeError("a complete expected file SHA-256 is required")
    original = Path(path)
    resolved = original.resolve(strict=True)
    if not resolved.is_file():
        raise SpanIntakeError("input must resolve to a regular file")
    before = resolved.stat()
    if not 0 < before.st_size <= _positive(max_bytes, "max_bytes"):
        raise SpanIntakeError("input file exceeds the byte bound")
    digest = hashlib.sha256()
    with resolved.open("rb") as stream:
        opened = os.fstat(stream.fileno())
        if _signature(opened) != _signature(before):
            raise SpanIntakeError("input changed before hashing")
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
        after = os.fstat(stream.fileno())
    if (_signature(before) != _signature(after)
            or _signature(before) != _signature(resolved.stat())
            or original.resolve(strict=True) != resolved):
        raise SpanIntakeError("input changed while hashing")
    if digest.hexdigest() != expected_sha256:
        raise SpanIntakeError("input file SHA-256 differs")
    return {"path": str(resolved), "sha256": expected_sha256, "bytes": before.st_size,
            "stat_signature": list(_signature(before))}


def _signature(stat: Any) -> tuple[int, ...]:
    return (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)


def _unchanged(identity: dict[str, Any]) -> None:
    if list(_signature(Path(identity["path"]).stat())) != identity["stat_signature"]:
        raise SpanIntakeError("verified source changed during intake")


def _parquet(path: str, *, max_rows: int, max_row_group_bytes: int):
    import pyarrow.parquet as pq

    parquet = pq.ParquetFile(path)
    if parquet.metadata.num_rows > _positive(max_rows, "max_rows"):
        raise SpanIntakeError("parquet row count exceeds the bound")
    for index in range(parquet.metadata.num_row_groups):
        if parquet.metadata.row_group(index).total_byte_size > _positive(
                max_row_group_bytes, "max_row_group_bytes"):
            raise SpanIntakeError("parquet row-group decoded bytes exceed the bound")
    return parquet


def prepare_progress_index(
    connection: Any,
    progress_parquet: str | Path,
    *,
    expected_sha256: str,
    repository_revision: str,
    max_bytes: int = 256 * 1024 * 1024,
    max_rows: int = 2_000_000,
    max_row_group_bytes: int = 256 * 1024 * 1024,
) -> ProgressIndex:
    """Index only span identities from an immutable, exact-revision ledger.

    The connection must already belong to this caller; no database file is
    opened here. Exact duplicate identities collapse. Conflicting identifiers,
    missing dataset metadata, and unexpected per-span dataset IDs fail closed.
    ``sealed``, ``status``, remote claims, admission, and formalization fields
    never influence eligibility or completion.
    """
    if not isinstance(repository_revision, str) or not _REVISION.fullmatch(repository_revision):
        raise SpanIntakeError("progress repository revision must be a complete commit SHA")
    identity = _file_identity(progress_parquet, expected_sha256, max_bytes=max_bytes)
    parquet = _parquet(identity["path"], max_rows=max_rows, max_row_group_bytes=max_row_group_bytes)
    required = {"record_kind", "dataset_id", "source_span_id", "source_sha256", "legal_id"}
    if not required.issubset(parquet.schema_arrow.names):
        raise SpanIntakeError("progress parquet is missing source-identity columns")
    for field in required:
        import pyarrow as pa
        if not pa.types.is_string(parquet.schema_arrow.field(field).type):
            raise SpanIntakeError("progress source-identity columns must be strings")
    # A materialized temporary table keeps repeated section joins bounded and
    # avoids reparsing the progress parquet for every compiler/GPU batch.
    suffix = uuid.uuid4().hex
    raw_table, table = "legacy_intake_raw_" + suffix, "legacy_intake_spans_" + suffix
    connection.execute(f"CREATE TEMP TABLE {raw_table} AS SELECT record_kind, dataset_id, "
                       "source_span_id, source_sha256, legal_id FROM read_parquet(?)", [identity["path"]])
    try:
        kinds = dict(connection.execute(
            f"SELECT coalesce(record_kind, ''), count(*) FROM {raw_table} GROUP BY 1").fetchall())
        datasets = {row[0] for row in connection.execute(
            f"SELECT DISTINCT dataset_id FROM {raw_table} WHERE record_kind='meta'").fetchall()}
        if not datasets or not datasets.issubset(_DATASETS):
            raise SpanIntakeError("progress metadata is not bound to the U.S. Code dataset")
        invalid = connection.execute(
            f"SELECT count(*) FROM {raw_table} WHERE record_kind='span' AND ("
            "source_span_id IS NULL OR source_span_id='' OR length(source_span_id)>512 OR "
            "source_sha256 IS NULL OR NOT regexp_full_match(source_sha256, '[0-9a-f]{64}') OR "
            "legal_id IS NULL OR legal_id='' OR length(legal_id)>2048 OR "
            "(coalesce(dataset_id,'') NOT IN ('', 'ipfs_uscode', 'justicedao/ipfs_uscode')))").fetchone()[0]
        if invalid:
            raise SpanIntakeError("progress contains invalid or foreign span identities")
        conflict = connection.execute(
            f"SELECT source_span_id FROM {raw_table} WHERE record_kind='span' "
            "GROUP BY source_span_id HAVING count(DISTINCT source_sha256)>1 "
            "OR count(DISTINCT legal_id)>1 LIMIT 1").fetchone()
        if conflict:
            raise SpanIntakeError("conflicting identities under progress source_span_id")
        connection.execute(f"CREATE TEMP TABLE {table} AS SELECT DISTINCT source_span_id, "
                           f"source_sha256, legal_id, FALSE AS matched FROM {raw_table} WHERE record_kind='span'")
        connection.execute(f"CREATE UNIQUE INDEX {table}_id ON {table}(source_span_id)")
        total = connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
        _unchanged(identity)
    except Exception:
        connection.execute(f"DROP TABLE IF EXISTS {table}")
        raise
    finally:
        connection.execute(f"DROP TABLE {raw_table}")
    return ProgressIndex(connection, table,
        {**identity, "repository_id": PROGRESS_REPOSITORY, "revision": repository_revision,
         "path_in_repo": "autoformal/uscode/resume-checkpoint.parquet"},
        {"ledger_row_count": parquet.metadata.num_rows, "record_kind_counts": kinds,
         "span_row_count": kinds.get("span", 0), "unique_span_count": total,
         "duplicate_span_count": kinds.get("span", 0) - total,
         "ignored_nonspan_row_count": parquet.metadata.num_rows - kinds.get("span", 0)})


def progress_coverage(index: ProgressIndex, *, example_limit: int = 16) -> dict[str, Any]:
    """Return source coverage in this index lifetime, never campaign completion."""
    if type(example_limit) is not int or not 0 <= example_limit <= 64:
        raise SpanIntakeError("example_limit must be in 0..64")
    total, matched = index.connection.execute(
        f"SELECT count(*), count(*) FILTER (WHERE matched) FROM {index.table}").fetchone()
    missing = index.connection.execute(
        f"SELECT source_span_id,source_sha256,legal_id FROM {index.table} WHERE NOT matched "
        "ORDER BY source_span_id LIMIT ?", [example_limit]).fetchall()
    return {**index.stats, "matched_source_span_count": matched,
            "unmatched_progress_span_count": total - matched,
            "unmatched_examples": [dict(zip(("source_span_id", "source_sha256", "legal_id"), row)) for row in missing],
            "coverage_scope": "current_index_lifetime_source_hydration_only",
            "admitted": False, "formalized": False}


def iter_joined_section_batches(
    index: ProgressIndex,
    laws_parquet: str | Path,
    *,
    expected_laws_sha256: str,
    source_revision: str = SOURCE_REVISION,
    release_id: str = DEFAULT_RELEASE_ID,
    start_section: int = 0,
    section_batch_size: int = 16,
    max_file_bytes: int = 512 * 1024 * 1024,
    max_row_group_bytes: int = 256 * 1024 * 1024,
    max_section_bytes: int = 8 * 1024 * 1024,
    max_batch_bytes: int = 32 * 1024 * 1024,
    max_batch_spans: int = 8192,
    diagnostic_limit: int = 32,
) -> Iterator[dict[str, Any]]:
    """Yield exact-matched sentences and bounded unmatched diagnostics.

    ``next_section`` is a raw source-parquet row offset. Persist it only in the
    same durable operation that enqueues the returned rows. Replaying a batch
    returns the same identities; queue insertion must be idempotent. A sentence
    is never truncated to match the historical span cache's 32 KiB text limit.
    Such a hash mismatch remains explicitly unmatched. Section and batch limits
    fail before yielding that batch; increasing them requires a larger admitted
    resource budget, not silently dropping source text.

    The pinned progress ledger used 64 valid source documents per inventory
    call. Its span ordinal accumulates inside that historical group, independent
    of this iterator's output batch size. Resume replays source-prefix sentence
    counts to reconstruct the same ordinals; it never borrows IDs from progress.
    """
    if not isinstance(source_revision, str) or not _REVISION.fullmatch(source_revision):
        raise SpanIntakeError("source revision must be a complete commit SHA")
    if not isinstance(release_id, str) or not release_id or len(release_id) > 256:
        raise SpanIntakeError("release_id must be a bounded nonempty string")
    if type(start_section) is not int or start_section < 0:
        raise SpanIntakeError("start_section must be a nonnegative integer")
    if not 1 <= _positive(section_batch_size, "section_batch_size") <= 256:
        raise SpanIntakeError("section_batch_size must be in 1..256")
    if type(diagnostic_limit) is not int or not 0 <= diagnostic_limit <= 128:
        raise SpanIntakeError("diagnostic_limit must be in 0..128")
    for label, bound in (("max_section_bytes", max_section_bytes), ("max_batch_bytes", max_batch_bytes),
                         ("max_batch_spans", max_batch_spans)):
        _positive(bound, label)
    identity = _file_identity(laws_parquet, expected_laws_sha256, max_bytes=max_file_bytes)
    parquet = _parquet(identity["path"], max_rows=2_000_000, max_row_group_bytes=max_row_group_bytes)
    required = {"ipfs_cid", "title_number", "section_number", "text"}
    if not required.issubset(parquet.schema_arrow.names):
        raise SpanIntakeError("source parquet is missing U.S. Code text or identifiers")
    total = parquet.metadata.num_rows
    if start_section > total:
        raise SpanIntakeError("resume section is beyond the source row count")
    from ...logic.autoformal.uscode_ingest import SCHEMA as span_identity_schema, inventory_uscode_documents
    from .uscode_dataset import USCodeParquetRecord
    import pyarrow as pa

    source_parent = {key: value for key, value in identity.items() if key != "stat_signature"}
    source_parent.update(repository_id=SOURCE_REPOSITORY, revision=source_revision,
                         path_in_repo="uscode_parquet/laws.parquet", release_id=release_id,
                         identity_reconstruction=IDENTITY_RECONSTRUCTION,
                         historical_document_batch_size=HISTORICAL_DOCUMENT_BATCH_SIZE)
    progress_parent = {key: value for key, value in index.progress.items() if key != "stat_signature"}
    columns = sorted(required | ({"normalized_citation", "citation_text"} & set(parquet.schema_arrow.names)))
    seen = 0
    valid_documents = 0
    group_span_ordinal = 0
    for arrow_batch in parquet.iter_batches(batch_size=section_batch_size, columns=columns, use_threads=False):
        batch_start = seen
        seen += arrow_batch.num_rows
        _unchanged(identity)
        _unchanged(index.progress)
        candidates: list[dict[str, Any]] = []
        empty_sections = 0
        candidate_bytes = 0
        for local_index, raw in enumerate(arrow_batch.to_pylist()):
            section_offset = batch_start + local_index
            record = USCodeParquetRecord.from_row(raw)
            # Original ingest excludes rows without a source CID. The pinned
            # parquet ends in nine such metadata rows with null text, which
            # must neither fail source validation nor consume identity ordinals.
            if not record.ipfs_cid:
                if section_offset >= start_section:
                    empty_sections += 1
                continue
            raw_text = raw.get("text")
            if not isinstance(raw_text, str):
                raise SpanIntakeError("source section text is not a string")
            if len(raw_text.encode("utf-8")) > max_section_bytes:
                raise SpanIntakeError("source section exceeds the complete-text byte bound")
            if not record.text:
                if section_offset >= start_section:
                    empty_sections += 1
                continue
            if valid_documents % HISTORICAL_DOCUMENT_BATCH_SIZE == 0:
                group_span_ordinal = 0
            historical_group = valid_documents // HISTORICAL_DOCUMENT_BATCH_SIZE
            valid_documents += 1
            document = {"entry_cid": record.ipfs_cid,
                        "legal_id": f"usc:us:{record.title_number}:{record.section_number}",
                        "release_id": release_id, "section": record.section_number,
                        "text": record.text, "title": record.title_number,
                        "canonical_citation": record.citation}
            spans = inventory_uscode_documents([document], query="ipfs_uscode", release_id=release_id)["spans"]
            first_ordinal = group_span_ordinal
            group_span_ordinal += len(spans)
            if section_offset < start_section:
                continue
            for local_span_ordinal, span in enumerate(spans):
                text = span["text"]
                source_sha256 = hashlib.sha256(text.encode("utf-8")).hexdigest()
                historical_ordinal = first_ordinal + local_span_ordinal
                # Reproduce inventory's original identity fields exactly. Only
                # its ordinal is rebased to the verified historical call group.
                span_identity = {key: span[key] for key in (
                    "canonical_citation", "entry_cid", "legal_id", "release_point",
                    "section", "title", "unit_id")}
                span_identity.update(ordinal=historical_ordinal, query="ipfs_uscode",
                                     release_id=release_id, schema_version=span_identity_schema,
                                     text_sha256=source_sha256)
                digest = hashlib.sha256(json.dumps(span_identity, sort_keys=True,
                    separators=(",", ":"), ensure_ascii=True).encode("utf-8")).hexdigest()
                candidate = {"source_span_id": "uscode-span-" + digest, "text": text,
                             "source_sha256": source_sha256,
                             "legal_id": span["legal_id"], "title": record.title_number,
                             "section": record.section_number, "citation": record.citation,
                             "entry_cid": record.ipfs_cid, "source_parent": source_parent,
                             "progress_parent": progress_parent, "source_section_offset": section_offset,
                             "source_identity_match": "span_id+source_sha256+legal_id",
                             "identity_reconstruction": IDENTITY_RECONSTRUCTION,
                             "historical_document_batch_size": HISTORICAL_DOCUMENT_BATCH_SIZE,
                             "historical_document_batch_index": historical_group,
                             "historical_span_ordinal": historical_ordinal,
                             "admitted": False, "formalized": False,
                             "source_authority_authenticated": False}
                candidate_bytes += len(json.dumps(candidate, ensure_ascii=True, separators=(",", ":")).encode())
                candidates.append(candidate)
                if len(candidates) > max_batch_spans or candidate_bytes > max_batch_bytes:
                    raise SpanIntakeError("source batch exceeds the span or byte bound")
        if seen <= start_section:
            continue
        diagnostics: list[dict[str, Any]] = []
        counts = {"candidate_span_count": len(candidates), "matched_count": 0,
                  "duplicate_candidate_count": 0, "unlisted_source_count": 0,
                  "source_hash_mismatch_count": 0, "legal_id_mismatch_count": 0,
                  "empty_section_count": empty_sections}
        rows: list[dict[str, Any]] = []
        if candidates:
            temp_name = "legacy_intake_candidates_" + uuid.uuid4().hex
            index.connection.register(temp_name, pa.table({"source_span_id": [r["source_span_id"] for r in candidates]}))
            try:
                expected = {row[0]: row[1:] for row in index.connection.execute(
                    f"SELECT p.source_span_id,p.source_sha256,p.legal_id FROM {index.table} p "
                    f"JOIN (SELECT DISTINCT source_span_id FROM {temp_name}) c USING(source_span_id)").fetchall()}
            finally:
                index.connection.unregister(temp_name)
            unique: dict[str, dict[str, Any]] = {}
            for row in candidates:
                span_id = row["source_span_id"]
                if span_id in unique:
                    previous = unique[span_id]
                    if (previous["text"], previous["legal_id"]) != (row["text"], row["legal_id"]):
                        raise SpanIntakeError("regenerated source identity collision")
                    counts["duplicate_candidate_count"] += 1
                    continue
                unique[span_id] = row
                source = expected.get(span_id)
                reason = ("unlisted_source" if source is None else
                          "source_hash_mismatch" if source[0] != row["source_sha256"] else
                          "legal_id_mismatch" if source[1] != row["legal_id"] else "")
                if reason:
                    counts[reason + "_count"] += 1
                    if len(diagnostics) < diagnostic_limit:
                        diagnostics.append({"source_span_id": span_id, "source_sha256": row["source_sha256"],
                                            "legal_id": row["legal_id"], "reason": reason,
                                            "expected_source_sha256": source[0] if source else None})
                    continue
                rows.append(row)
            counts["matched_count"] = len(rows)
            if rows:
                index.connection.register(temp_name, pa.table({"source_span_id": [r["source_span_id"] for r in rows]}))
                try:
                    index.connection.execute(f"UPDATE {index.table} SET matched=TRUE WHERE source_span_id IN "
                                             f"(SELECT source_span_id FROM {temp_name})")
                finally:
                    index.connection.unregister(temp_name)
        _unchanged(identity)
        _unchanged(index.progress)
        yield {"schema": SCHEMA, "rows": rows, "counts": counts, "unmatched_examples": diagnostics,
               "section_start": max(batch_start, start_section), "next_section": seen,
               "total_sections": total, "done": seen == total,
               "source_parent": source_parent, "progress_parent": progress_parent,
               "admitted": False, "formalized": False, "training_executed": False}
    if start_section == total:
        yield {"schema": SCHEMA, "rows": [], "counts": {}, "unmatched_examples": [],
               "section_start": total, "next_section": total, "total_sections": total, "done": True,
               "source_parent": source_parent, "progress_parent": progress_parent,
               "admitted": False, "formalized": False, "training_executed": False}
