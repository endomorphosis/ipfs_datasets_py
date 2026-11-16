"""Disk-backed BM25 layout for corpora that do not fit in the in-memory builder.

The parquet schema, IDF, and shard rules are the shared HF GraphRAG builder.
Posting tuples are sorted on disk so a multi-million-row corpus does not keep
every (term, document) pair in RAM.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
import subprocess
from collections import Counter
from pathlib import Path
from typing import Any, Callable

import numpy as np

from ipfs_datasets_py.logic.ir_core.canonical import canonical_json_bytes
from ipfs_datasets_py.retrieval.hf_graphrag.bm25 import (
    BM25LayoutConfig,
    BM25LayoutSummary,
    BM25_DOCUMENT_SCHEMA_VERSION,
    BM25_POSTING_SCHEMA_VERSION,
    DEFAULT_BM25_TOKENIZER_ID,
    _document_schema,
    _file_descriptor,
    _fts5_idf,
    _meta_row,
    _posting_schema,
    _write_meta_indexes,
    _write_parquet,
    tokenize_bm25_text,
    validate_bm25_layout,
)

Log = Callable[[str], None] | None
_POSTING_BATCH = 2_000_000
_MERGE_WIDTH = 100


def _say(log: Log, message: str) -> None:
    if log is not None:
        log(message)


def _chunks_marker(work_dir: Path) -> Path:
    return work_dir / "CHUNKS_DONE.json"


def chunks_ready(work_dir: Path, fingerprint: str) -> bool:
    marker = _chunks_marker(work_dir)
    if not marker.is_file():
        return False
    try:
        payload = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    if payload.get("fingerprint") != fingerprint:
        return False
    n_chunks = int(payload.get("n_chunks") or 0)
    found = sorted(work_dir.glob("chunk-*.sorted"))
    if len(found) != n_chunks or n_chunks <= 0:
        return False
    if not (work_dir / "lengths.npy").is_file():
        return False
    if not (work_dir / "document_meta.json").is_file():
        return False
    return True


def _flush_posting_batch(batch: list[tuple[str, int, int, int]], work_dir: Path, chunk_id: int) -> None:
    raw = work_dir / f"chunk-{chunk_id:05d}.tsv"
    sorted_path = work_dir / f"chunk-{chunk_id:05d}.sorted"
    with raw.open("w", encoding="utf-8") as handle:
        for term, doc, title_tf, body_tf in batch:
            handle.write(f"{term}\t{doc}\t{title_tf}\t{body_tf}\n")
    env = dict(os.environ)
    env["LC_ALL"] = "C"
    subprocess.run(
        ["sort", "-S", "1G", "-t", "\t", "-k1,1", "-k2,2n", "-o", str(sorted_path), str(raw)],
        check=True,
        env=env,
    )
    raw.unlink()


def _write_document_shard(
    rows: list[dict[str, Any]],
    layout_dir: Path,
    shard_id: int,
    config: BM25LayoutConfig,
) -> dict[str, Any]:
    import pyarrow as pa

    destination = layout_dir / "data" / "bm25" / "documents"
    path = destination / f"part-{shard_id:06d}.parquet"
    table = pa.Table.from_pylist(rows, schema=_document_schema(pa, config))
    _write_parquet(path, table, config)
    descriptor = _file_descriptor(path, root=layout_dir, row_count=table.num_rows)
    start = int(rows[0]["document_index"])
    return _meta_row(
        descriptor,
        shard_id=shard_id,
        first_key=str(rows[0]["entry_cid"]),
        last_key=str(rows[-1]["entry_cid"]),
        start_document_index=start,
        end_document_index=start + len(rows) - 1,
        kind="bm25_documents",
    )


def _document_record(row: dict[str, Any], document_index: int) -> tuple[dict[str, Any], int, Counter, Counter]:
    title = str(row["title"])
    body = str(row["body"])
    title_tokens = tokenize_bm25_text(title)
    body_tokens = tokenize_bm25_text(body)
    title_tf = Counter(title_tokens)
    body_tf = Counter(body_tokens)
    title_length = len(title_tokens)
    body_length = len(body_tokens)
    document_length = title_length + body_length
    if document_length <= 0:
        raise RuntimeError(f"document has no searchable tokens: {row.get('entry_cid')}")
    record = {
        "authority": "non_authoritative",
        "body_length": body_length,
        "body_sha256": hashlib.sha256(body.encode("utf-8")).hexdigest(),
        "document_index": int(document_index),
        "document_length": document_length,
        "entry_cid": str(row["entry_cid"]),
        "record_type": str(row["record_type"]),
        "schema_version": BM25_DOCUMENT_SCHEMA_VERSION,
        "title": title,
        "title_length": title_length,
        "token_input_sha256": hashlib.sha256(
            canonical_json_bytes(
                {
                    "body": body,
                    "title": title,
                    "tokenizer": DEFAULT_BM25_TOKENIZER_ID,
                }
            )
        ).hexdigest(),
    }
    return record, document_length, title_tf, body_tf


def _write_chunks(
    rows: list[dict[str, Any]],
    layout_dir: Path,
    work_dir: Path,
    config: BM25LayoutConfig,
    fingerprint: str,
    log: Log,
) -> tuple[np.ndarray, list[dict[str, Any]], int]:
    if layout_dir.exists():
        shutil.rmtree(layout_dir)
    if work_dir.exists():
        shutil.rmtree(work_dir)
    layout_dir.mkdir(parents=True, exist_ok=True)
    work_dir.mkdir(parents=True, exist_ok=True)
    lengths = np.zeros(1_048_576, dtype=np.int32)
    document_meta: list[dict[str, Any]] = []
    pending_docs: list[dict[str, Any]] = []
    posting_batch: list[tuple[str, int, int, int]] = []
    chunk_id = 0
    seen: set[str] = set()
    n_docs = 0
    for document_index, row in enumerate(rows):
        if document_index >= len(lengths):
            grown = np.zeros(len(lengths) * 2, dtype=np.int32)
            grown[: len(lengths)] = lengths
            lengths = grown
        n_docs = document_index + 1
        cid = str(row.get("entry_cid") or "")
        if cid in seen:
            raise RuntimeError(f"duplicate BM25 entry CID: {cid}")
        seen.add(cid)
        record, document_length, title_tf, body_tf = _document_record(row, document_index)
        lengths[document_index] = document_length
        pending_docs.append(record)
        if len(pending_docs) == config.max_rows_per_shard:
            document_meta.append(
                _write_document_shard(pending_docs, layout_dir, len(document_meta), config)
            )
            pending_docs = []
        for term in title_tf.keys() | body_tf.keys():
            posting_batch.append(
                (term, document_index, int(title_tf[term]), int(body_tf[term]))
            )
        if len(posting_batch) >= _POSTING_BATCH:
            _flush_posting_batch(posting_batch, work_dir, chunk_id)
            posting_batch = []
            chunk_id += 1
        if log and document_index and document_index % 50_000 == 0:
            _say(log, f"bm25 scanned docs={document_index} chunks={chunk_id}")
    if pending_docs:
        document_meta.append(
            _write_document_shard(pending_docs, layout_dir, len(document_meta), config)
        )
    if posting_batch:
        _flush_posting_batch(posting_batch, work_dir, chunk_id)
        chunk_id += 1
    if not document_meta or chunk_id <= 0:
        raise RuntimeError("BM25 spill produced no documents or postings")
    lengths = lengths[:n_docs]
    np.save(work_dir / "lengths.npy", lengths)
    (work_dir / "document_meta.json").write_text(
        json.dumps(document_meta) + "\n",
        encoding="utf-8",
    )
    _chunks_marker(work_dir).write_text(
        json.dumps(
            {
                "fingerprint": fingerprint,
                "n_docs": n_docs,
                "n_chunks": chunk_id,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    _say(log, f"bm25 chunks ready docs={n_docs} chunks={chunk_id} document_shards={len(document_meta)}")
    return lengths, document_meta, n_docs


def _load_chunks(work_dir: Path) -> tuple[np.ndarray, list[dict[str, Any]], int]:
    payload = json.loads(_chunks_marker(work_dir).read_text(encoding="utf-8"))
    lengths = np.load(work_dir / "lengths.npy")
    document_meta = json.loads((work_dir / "document_meta.json").read_text(encoding="utf-8"))
    return lengths, document_meta, int(payload["n_docs"])


def _merge_inputs(paths: list[Path], work_dir: Path) -> subprocess.Popen[str]:
    env = dict(os.environ)
    env["LC_ALL"] = "C"
    files = list(paths)
    round_id = 0
    while len(files) > _MERGE_WIDTH:
        merged: list[Path] = []
        for offset in range(0, len(files), _MERGE_WIDTH):
            group = files[offset : offset + _MERGE_WIDTH]
            dest = work_dir / f"merge-r{round_id}-{offset:05d}.sorted"
            subprocess.run(
                ["sort", "-m", "-S", "1G", "-t", "\t", "-k1,1", "-k2,2n", "-o", str(dest), *map(str, group)],
                check=True,
                env=env,
            )
            merged.append(dest)
        files = merged
        round_id += 1
    error_path = work_dir / "sort-merge.err"
    error_handle = error_path.open("w", encoding="utf-8")
    return subprocess.Popen(
        ["sort", "-m", "-S", "1G", "-t", "\t", "-k1,1", "-k2,2n", *map(str, files)],
        stdout=subprocess.PIPE,
        stderr=error_handle,
        env=env,
        text=True,
    )


def _rows_for_term(
    term: str,
    values: list[tuple[int, int, int]],
    document_count: int,
    lengths: np.ndarray,
    config: BM25LayoutConfig,
) -> list[dict[str, Any]]:
    document_frequency = len(values)
    corpus_frequency = sum(title_tf + body_tf for _, title_tf, body_tf in values)
    chunk_count = math.ceil(document_frequency / config.postings_per_row)
    if chunk_count > config.max_rows_per_shard:
        raise RuntimeError(f"one term exceeds the Parquet row limit: {term!r}")
    idf = _fts5_idf(document_count, document_frequency)
    rows: list[dict[str, Any]] = []
    for chunk_index, start in enumerate(range(0, document_frequency, config.postings_per_row)):
        selected = values[start : start + config.postings_per_row]
        document_indices = [item[0] for item in selected]
        rows.append(
            {
                "body_frequencies": [item[2] for item in selected],
                "corpus_frequency": corpus_frequency,
                "document_frequency": document_frequency,
                "document_indices": document_indices,
                "document_lengths": [int(lengths[index]) for index in document_indices],
                "idf": idf,
                "posting_chunk_count": chunk_count,
                "posting_chunk_index": chunk_index,
                "schema_version": BM25_POSTING_SCHEMA_VERSION,
                "term": term,
                "title_frequencies": [item[1] for item in selected],
            }
        )
    return rows


def _write_posting_shard(
    rows: list[dict[str, Any]],
    layout_dir: Path,
    shard_id: int,
    config: BM25LayoutConfig,
) -> dict[str, Any]:
    import pyarrow as pa

    terms = tuple(dict.fromkeys(str(row["term"]) for row in rows))
    posting_count = sum(len(row["document_indices"]) for row in rows)
    token_instances = sum(sum(row["title_frequencies"]) + sum(row["body_frequencies"]) for row in rows)
    table = pa.Table.from_pylist(rows, schema=_posting_schema(pa, config))
    table = table.replace_schema_metadata(
        {
            **dict(table.schema.metadata or {}),
            b"first_term": terms[0].encode("utf-8"),
            b"last_term": terms[-1].encode("utf-8"),
            b"posting_count": str(posting_count).encode("ascii"),
            b"term_count": str(len(terms)).encode("ascii"),
            b"token_instance_count": str(token_instances).encode("ascii"),
        }
    )
    path = layout_dir / "data" / "bm25" / "postings" / f"part-{shard_id:06d}.parquet"
    _write_parquet(path, table, config)
    descriptor = _file_descriptor(path, root=layout_dir, row_count=table.num_rows)
    return _meta_row(
        descriptor,
        shard_id=shard_id,
        first_key=terms[0],
        last_key=terms[-1],
        start_document_index=-1,
        end_document_index=-1,
        kind="bm25_postings",
        posting_count=posting_count,
        term_count=len(terms),
        token_instance_count=token_instances,
    )


def _merge_postings(
    layout_dir: Path,
    work_dir: Path,
    lengths: np.ndarray,
    document_count: int,
    config: BM25LayoutConfig,
    log: Log,
) -> tuple[list[dict[str, Any]], dict[str, int | float]]:
    postings_dir = layout_dir / "data" / "bm25" / "postings"
    if postings_dir.exists():
        shutil.rmtree(postings_dir)
    indexes = layout_dir / "indexes"
    if indexes.exists():
        shutil.rmtree(indexes)
    files = sorted(work_dir.glob("chunk-*.sorted"))
    proc = _merge_inputs(files, work_dir)
    assert proc.stdout is not None
    pending: list[dict[str, Any]] = []
    pending_terms = 0
    posting_meta: list[dict[str, Any]] = []
    term_count = 0
    total_postings = 0
    total_instances = 0
    current: str | None = None
    bucket: list[tuple[int, int, int]] = []

    def flush_pending() -> None:
        nonlocal pending, pending_terms
        if not pending:
            return
        posting_meta.append(_write_posting_shard(pending, layout_dir, len(posting_meta), config))
        pending = []
        pending_terms = 0

    def push_group(group: list[dict[str, Any]]) -> None:
        nonlocal pending, pending_terms, term_count, total_postings, total_instances
        if pending and (
            pending_terms >= config.terms_per_shard
            or len(pending) + len(group) > config.max_rows_per_shard
        ):
            flush_pending()
        pending.extend(group)
        pending_terms += 1
        term_count += 1
        total_postings += sum(len(row["document_indices"]) for row in group)
        total_instances += sum(sum(row["title_frequencies"]) + sum(row["body_frequencies"]) for row in group)

    def flush_term() -> None:
        nonlocal current, bucket
        if current is None:
            return
        push_group(_rows_for_term(current, bucket, document_count, lengths, config))
        if log and term_count and term_count % 200_000 == 0:
            _say(log, f"bm25 terms={term_count} posting_shards={len(posting_meta)}")
        current = None
        bucket = []

    for line in proc.stdout:
        term, doc_s, title_s, body_s = line.rstrip("\n").split("\t")
        if term != current:
            flush_term()
            current = term
        bucket.append((int(doc_s), int(title_s), int(body_s)))
    flush_term()
    flush_pending()
    proc.stdout.close()
    code = proc.wait()
    if code != 0:
        raise RuntimeError(f"BM25 sort merge failed exit={code}")
    if not posting_meta:
        raise RuntimeError("BM25 spill produced no posting shards")
    _say(
        log,
        f"bm25 postings terms={term_count} shards={len(posting_meta)} instances={total_instances}",
    )
    return posting_meta, {
        "posting_count": total_postings,
        "posting_row_count": sum(int(row["row_count"]) for row in posting_meta),
        "term_count": term_count,
        "token_instance_count": total_instances,
    }


def spill_bm25_layout(
    rows: list[dict[str, Any]] | None,
    layout_dir: Path,
    *,
    work_dir: Path,
    fingerprint: str,
    log: Log = None,
) -> BM25LayoutSummary:
    """Write a validated BM25 layout. A finished chunk pass is merged, not retokenized."""
    layout_dir = Path(layout_dir)
    work_dir = Path(work_dir)
    documents = layout_dir / "data" / "bm25" / "documents"
    if chunks_ready(work_dir, fingerprint) and any(documents.glob("part-*.parquet")):
        lengths, document_meta, n_docs = _load_chunks(work_dir)
        _say(log, f"reused bm25 chunks {work_dir} docs={n_docs}")
    else:
        if rows is None or (isinstance(rows, list) and not rows):
            raise RuntimeError("BM25 spill requires corpus rows")
        import gc

        # An iterator does not know its length yet. The summary config below
        # is rebuilt from the counted document total.
        width = len(rows) if isinstance(rows, list) else 2_000_000_000
        config = BM25LayoutConfig(max_documents=max(width, 1))
        lengths, document_meta, n_docs = _write_chunks(
            rows, layout_dir, work_dir, config, fingerprint, log
        )
        if isinstance(rows, list):
            rows.clear()
        gc.collect()
    config = BM25LayoutConfig(max_documents=max(n_docs, 1))
    posting_meta, stats = _merge_postings(layout_dir, work_dir, lengths, n_docs, config, log)
    document_index, keyword_index = _write_meta_indexes(
        layout_dir, document_meta, posting_meta, config
    )
    average = float(np.asarray(lengths, dtype=np.float64).sum()) / float(n_docs)
    summary = BM25LayoutSummary(
        output_dir=str(layout_dir),
        document_count=n_docs,
        document_shard_count=len(document_meta),
        posting_count=int(stats["posting_count"]),
        posting_row_count=int(stats["posting_row_count"]),
        posting_shard_count=len(posting_meta),
        term_count=int(stats["term_count"]),
        token_instance_count=int(stats["token_instance_count"]),
        average_document_length=average,
        document_index=document_index,
        keyword_index=keyword_index,
        config=config,
    )
    validated = validate_bm25_layout(layout_dir, config=config)
    if validated.counts != summary.counts or not math.isclose(
        validated.average_document_length,
        summary.average_document_length,
        rel_tol=0.0,
        abs_tol=1e-12,
    ):
        raise RuntimeError("spilled BM25 layout failed validation against its own summary")
    _say(log, f"bm25 validated docs={n_docs} terms={summary.term_count}")
    return validated
