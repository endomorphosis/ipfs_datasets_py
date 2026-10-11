"""Bounded, resumable source sentence pages with historical archive identities.

The cursor is a physical parquet section offset and zero-based sentence offset.
Prefix sentences are counted again on resume, preserving the historical groups
of 64 valid documents without trusting serialized ordinal state. Only one page
of candidate dictionaries is materialized; the normalized sentence list remains
bounded by the complete section byte limit. Source joins never confer model,
semantic, training or proof authority.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Iterator
import uuid

from . import legacy_span_intake as intake


SCHEMA = "legacy-autoencoder-span-pages/v1"


def _encoded(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=True, separators=(",", ":"),
                      allow_nan=False).encode("utf-8")


def _join_page(index: intake.ProgressIndex, candidates: list[dict[str, Any]], *,
               empty_sections: int = 0) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Join only this bounded page; retain every source occurrence."""
    counts = {"candidate_span_count": len(candidates), "matched_count": 0,
              "duplicate_candidate_count": 0, "unlisted_source_count": 0,
              "source_hash_mismatch_count": 0, "legal_id_mismatch_count": 0,
              "empty_section_count": empty_sections,
              "legacy_citation_fallback_candidate_count": 0}
    if not candidates:
        return candidates, counts
    import pyarrow as pa

    name = "legacy_span_page_" + uuid.uuid4().hex
    index.connection.register(name, pa.table({
        "source_span_id": [row["source_span_id"] for row in candidates]}))
    try:
        expected = {row[0]: row[1:] for row in index.connection.execute(
            f"SELECT p.source_span_id,p.source_sha256,p.legal_id FROM {index.table} p "
            f"JOIN (SELECT DISTINCT source_span_id FROM {name}) c USING(source_span_id)").fetchall()}
        for row in candidates:
            target = expected.get(row["source_span_id"])
            reason = ("unlisted_source" if target is None else
                      "source_hash_mismatch" if target[0] != row["source_sha256"] else
                      "legal_id_mismatch" if target[1] != row["legal_id"] else "matched")
            row["source_join_disposition"] = reason
            counts[reason + "_count"] += 1
            counts["legacy_citation_fallback_candidate_count"] += (
                row["source_text_origin"] == "legacy_citation_fallback")
        # This TEMP flag is hydration bookkeeping only. The caller durably
        # commits the returned candidates and cursor in its own transaction.
        index.connection.execute(
            f"UPDATE {index.table} p SET matched=TRUE WHERE EXISTS "
            f"(SELECT 1 FROM {name} c WHERE c.source_span_id=p.source_span_id) "
            "AND source_span_id IN (SELECT unnest(?))",
            [[row["source_span_id"] for row in candidates
              if row["source_join_disposition"] == "matched"]])
    finally:
        index.connection.unregister(name)
    return candidates, counts


def iter_joined_span_pages(index: intake.ProgressIndex, laws_parquet: str, *,
        expected_laws_sha256: str, source_revision: str = intake.SOURCE_REVISION,
        release_id: str = intake.DEFAULT_RELEASE_ID, start_section: int = 0,
        start_span: int = 0, max_page_spans: int = 1024,
        max_page_bytes: int = 4 * 1024 * 1024,
        max_section_bytes: int = 8 * 1024 * 1024,
        max_file_bytes: int = 512 * 1024 * 1024,
        max_row_group_bytes: int = 2 * 1024 * 1024 * 1024) -> Iterator[dict[str, Any]]:
    """Yield complete candidates and the first uncommitted section/span cursor.

    Finished sections advance ``next_section`` and normalize ``next_span=0``.
    Empty metadata sections produce one empty page, consuming no document or
    sentence ordinal. A real-CID blank text preserves the historical citation
    fallback and its ordinals, explicitly marked as synthetic fallback text.
    An individual candidate that cannot fit is refused before its cursor is
    yielded. Page byte limits include serialized candidates and their parents.
    The original queue and source artifact are rechecked before every yield.
    """
    if not isinstance(source_revision, str) or not intake._REVISION.fullmatch(source_revision):
        raise intake.SpanIntakeError("source revision must be a complete commit SHA")
    if not isinstance(release_id, str) or not release_id or len(release_id) > 256:
        raise intake.SpanIntakeError("release_id must be a bounded nonempty string")
    for label, value in (("start_section", start_section), ("start_span", start_span)):
        if type(value) is not int or value < 0:
            raise intake.SpanIntakeError(label + " must be a nonnegative integer")
    for label, value in (("max_page_spans", max_page_spans), ("max_page_bytes", max_page_bytes),
                         ("max_section_bytes", max_section_bytes)):
        intake._positive(value, label)
    identity = intake._file_identity(laws_parquet, expected_laws_sha256, max_bytes=max_file_bytes)
    parquet = intake._parquet(identity["path"], max_rows=2_000_000,
                              max_row_group_bytes=max_row_group_bytes)
    required = {"ipfs_cid", "title_number", "section_number", "text"}
    if not required.issubset(parquet.schema_arrow.names):
        raise intake.SpanIntakeError("source parquet is missing U.S. Code text or identifiers")
    total = parquet.metadata.num_rows
    if start_section > total:
        raise intake.SpanIntakeError("resume section is beyond the source row count")
    if start_section == total and start_span:
        raise intake.SpanIntakeError("completed source cursor requires start_span=0")
    from ...logic.autoformal.constitution_inventory import _sentences
    from ...logic.autoformal.uscode_ingest import SCHEMA as identity_schema, normalize_uscode_hit
    from .uscode_dataset import USCodeParquetRecord

    source_parent = {k: v for k, v in identity.items() if k != "stat_signature"}
    source_parent.update(repository_id=intake.SOURCE_REPOSITORY, revision=source_revision,
                         path_in_repo="uscode_parquet/laws.parquet", release_id=release_id,
                         identity_reconstruction=intake.IDENTITY_RECONSTRUCTION,
                         historical_document_batch_size=intake.HISTORICAL_DOCUMENT_BATCH_SIZE)
    progress_parent = {k: v for k, v in index.progress.items() if k != "stat_signature"}

    def deliver(candidates, section, first_span, next_section, next_span, *, empty_sections=0):
        intake._unchanged(identity)
        intake._unchanged(index.progress)
        candidates, counts = _join_page(index, candidates, empty_sections=empty_sections)
        if len(_encoded(candidates)) > max_page_bytes:
            raise intake.SpanIntakeError("serialized source page exceeds the byte bound")
        intake._unchanged(identity)
        intake._unchanged(index.progress)
        return {"schema": SCHEMA, "candidate_rows": candidates, "counts": counts,
                "section_start": section, "span_start": first_span,
                "next_section": next_section, "next_span": next_span,
                "total_sections": total, "done": next_section == total,
                "source_parent": source_parent, "progress_parent": progress_parent,
                "admitted": False, "formalized": False, "training_executed": False,
                "inference_executed": False, "proof_authority": False}

    columns = sorted(required | ({"normalized_citation", "citation_text"} & set(parquet.schema_arrow.names)))
    valid_documents = group_ordinal = 0
    for section, batch in enumerate(parquet.iter_batches(batch_size=1, columns=columns, use_threads=False)):
        intake._unchanged(identity)
        intake._unchanged(index.progress)
        raw = batch.to_pylist()[0]
        record = USCodeParquetRecord.from_row(raw)
        if not record.ipfs_cid:
            if section >= start_section:
                if section == start_section and start_span:
                    raise intake.SpanIntakeError("empty section cursor requires start_span=0")
                yield deliver([], section, 0, section + 1, 0, empty_sections=1)
            continue
        raw_text = raw.get("text")
        if not isinstance(raw_text, str):
            raise intake.SpanIntakeError("source section text is not a string")
        if len(raw_text.encode("utf-8")) > max_section_bytes:
            raise intake.SpanIntakeError("source section exceeds the complete-text byte bound")
        if len(record.text.encode("utf-8")) > max_section_bytes:
            raise intake.SpanIntakeError("historical fallback text exceeds the complete-text byte bound")
        if not record.text:
            if section >= start_section:
                if section == start_section and start_span:
                    raise intake.SpanIntakeError("empty section cursor requires start_span=0")
                yield deliver([], section, 0, section + 1, 0, empty_sections=1)
            continue
        if valid_documents % intake.HISTORICAL_DOCUMENT_BATCH_SIZE == 0:
            group_ordinal = 0
        historical_group = valid_documents // intake.HISTORICAL_DOCUMENT_BATCH_SIZE
        valid_documents += 1
        document = normalize_uscode_hit({"entry_cid": record.ipfs_cid,
            "legal_id": f"usc:us:{record.title_number}:{record.section_number}",
            "release_id": release_id, "section": record.section_number,
            "text": record.text, "title": record.title_number,
            "canonical_citation": record.citation})
        sentences = _sentences(document["text"]) or [document["text"]]
        first_ordinal = group_ordinal
        group_ordinal += len(sentences)
        if section < start_section:
            continue
        local_start = start_span if section == start_section else 0
        if local_start >= len(sentences):
            raise intake.SpanIntakeError("resume span is beyond the section sentence count")
        raw_present = bool(raw_text.strip())
        origin = "normalized_source_text" if raw_present else "legacy_citation_fallback"
        candidates = []
        page_bytes = 2
        page_start = local_start
        for local_span in range(local_start, len(sentences)):
            text = sentences[local_span]
            source_sha256 = hashlib.sha256(text.encode("utf-8")).hexdigest()
            historical_ordinal = first_ordinal + local_span
            binding = {k: document[k] for k in (
                "canonical_citation", "entry_cid", "legal_id", "release_point", "section", "title")}
            binding.update(unit_id=document["document_id"], ordinal=historical_ordinal,
                           query="ipfs_uscode", release_id=release_id,
                           schema_version=identity_schema, text_sha256=source_sha256)
            digest = hashlib.sha256(json.dumps(binding, sort_keys=True,
                separators=(",", ":"), ensure_ascii=True).encode("utf-8")).hexdigest()
            candidate = {"source_span_id": "uscode-span-" + digest, "text": text,
                "source_sha256": source_sha256, "legal_id": document["legal_id"],
                "title": record.title_number, "section": record.section_number,
                "citation": record.citation, "entry_cid": record.ipfs_cid,
                "source_parent": source_parent, "progress_parent": progress_parent,
                "source_section_offset": section, "source_section_span_ordinal": local_span,
                "source_identity_match": "span_id+source_sha256+legal_id",
                "identity_reconstruction": intake.IDENTITY_RECONSTRUCTION,
                "historical_document_batch_size": intake.HISTORICAL_DOCUMENT_BATCH_SIZE,
                "historical_document_batch_index": historical_group,
                "historical_span_ordinal": historical_ordinal,
                "source_text_origin": origin, "raw_source_text_present": raw_present,
                "admitted": False, "formalized": False, "source_authority_authenticated": False,
                # Longest possible disposition reserves the full serialized
                # size before any join can alter TEMP hydration state.
                "source_join_disposition": "source_hash_mismatch"}
            size = len(_encoded(candidate))
            if size + 2 > max_page_bytes:
                raise intake.SpanIntakeError("individual source candidate exceeds the page byte bound")
            if candidates and (len(candidates) == max_page_spans
                               or page_bytes + 1 + size > max_page_bytes):
                yield deliver(candidates, section, page_start, section, local_span)
                candidates = []
                page_bytes = 2
                page_start = local_span
            page_bytes += size + bool(candidates)
            candidates.append(candidate)
            if len(candidates) == max_page_spans and local_span + 1 < len(sentences):
                yield deliver(candidates, section, page_start, section, local_span + 1)
                candidates = []
                page_bytes = 2
                page_start = local_span + 1
        yield deliver(candidates, section, page_start, section + 1, 0)
    if start_section == total:
        yield deliver([], total, 0, total, 0)
