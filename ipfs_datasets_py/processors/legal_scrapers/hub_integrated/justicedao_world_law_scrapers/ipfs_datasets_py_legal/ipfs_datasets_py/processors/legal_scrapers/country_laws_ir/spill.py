"""Disk-spill helpers for large country IR builds (DuckDB + parquet).

Design (CoS / DO OOM lesson):
- Embeddings: checkpointed .npy via vectors.encode_corpus (unchanged).
- Neighbors for n >= DUCKDB_THRESHOLD (40k): DuckDB FTS over corpus parquet,
  streamed into neighbor_*.parquet shards — never hold the full neighbor
  matrix in RAM.
- BM25 TF: stream tokenize → DuckDB → posting parquet parts.
- Package: sequential parquet write so corpus, bm25, graph, vectors are never
  all resident together.

No SQLite. Intermediate and published artifacts are parquet / DuckDB.
"""
from __future__ import annotations

import gc
import json
import math
import pickle
from collections import defaultdict
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from . import SCHEMA_VERSION
from .bm25 import (
    B,
    BODY_WEIGHT,
    K1,
    POSTING_ROWS_PER_RECORD,
    TERMS_PER_SHARD,
    TITLE_WEIGHT,
)
from .graph import _adjacency, _edge, build_graph
from .mem import MemAbort, checkpoint, log_mem
from .tokenize import tokenize

DUCKDB_THRESHOLD = 40_000
SQLITE_THRESHOLD = DUCKDB_THRESHOLD  # backward-compatible alias; not SQLite
BATCH = 256
NEIGHBOR_SHARD = 5_000
NEIGHBOR_K = 8
DF_CAP = 1500
MAX_QTERMS = 8
TITLE_W = TITLE_WEIGHT
BODY_W = BODY_WEIGHT


def spill_dir_for(slug: str, cache: Path) -> Path:
    return Path(cache) / f"{slug}_bm25_spill"


def spill_pickle(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("wb") as f:
        pickle.dump(obj, f, protocol=pickle.HIGHEST_PROTOCOL)
    tmp.replace(path)


def load_pickle(path: Path) -> Any:
    with path.open("rb") as f:
        return pickle.load(f)


def _idf(n_docs: int, df: int) -> float:
    return math.log((n_docs - df + 0.5) / (df + 0.5) + 1.0)


def _require_duckdb():
    try:
        import duckdb  # type: ignore
    except ImportError as exc:
        raise RuntimeError("duckdb is required for sparse GraphRAG spill (no sqlite)") from exc
    return duckdb


def duckdb_ready(db_path: Path, expected: int) -> bool:
    if not db_path.is_file():
        return False
    duckdb = _require_duckdb()
    try:
        conn = duckdb.connect(str(db_path), read_only=True)
        n = int(conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0])
        conn.close()
        return n == expected
    except Exception:
        return False


def build_sqlite_fts(*args, **kwargs):  # pragma: no cover - removed
    raise RuntimeError("SQLite FTS is removed; use DuckDB parquet neighbors")


def neighbors_via_duckdb(
    corpus_path: Path,
    spill: Path,
    n_docs: int,
    *,
    k: int = NEIGHBOR_K,
    resume: bool = True,
    log: Callable[[str], None] | None = None,
) -> list[Path]:
    """DuckDB FTS over corpus parquet → neighbor_*.parquet shards. No SQLite."""
    from .duckdb_store import build_fts_index, stream_neighbors_to_parquet

    spill = Path(spill)
    spill.mkdir(parents=True, exist_ok=True)
    db_path = spill / "neighbors.duckdb"
    if not duckdb_ready(db_path, n_docs):
        if db_path.exists():
            db_path.unlink()
        if log:
            log(f"building duckdb fts n={n_docs} -> {db_path}")
        build_fts_index(corpus_path, db_path, n_docs, log=log)
    else:
        if log:
            log(f"reusing duckdb fts n={n_docs} path={db_path}")
    return stream_neighbors_to_parquet(
        db_path, spill, n_docs, k=k, resume=resume, log=log
    )


def iter_neighbor_shards(spill: Path) -> Iterator[tuple[int, list]]:
    """Yield (start_index, shard_list) from parquet neighbor shards."""
    from .duckdb_store import iter_neighbor_parquet_shards

    parquet = list(Path(spill).glob("neighbors_*.parquet"))
    if parquet:
        yield from iter_neighbor_parquet_shards(spill)
        return
    # Legacy pickle shards (pre-DuckDB). Do not create new ones.
    paths = sorted(Path(spill).glob("neighbors_*.pkl"))
    for sp in paths:
        parts = sp.stem.split("_")
        start_i = int(parts[1])
        yield start_i, load_pickle(sp)


def assemble_neighbors_streaming(spill: Path, n_docs: int) -> list:
    """Assemble only when unavoidable; prefer build_graph_from_neighbor_shards."""
    neighbors: list = []
    for start_i, part in iter_neighbor_shards(spill):
        while len(neighbors) < start_i:
            neighbors.append([])
        neighbors.extend(part)
        del part
        gc.collect()
    while len(neighbors) < n_docs:
        neighbors.append([])
    if len(neighbors) > n_docs:
        neighbors = neighbors[:n_docs]
    return neighbors


def neighbors_via_sqlite(*args, **kwargs):
    """Removed. Sparse GraphRAG neighbors are DuckDB/parquet only."""
    return neighbors_via_duckdb(*args, **kwargs)


def build_graph_from_neighbor_shards(
    corpus: pd.DataFrame,
    spill: Path,
    *,
    log: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Build graph without holding the full neighbor list.

    Structural edges first (neighbors=[]), then stream BM25_NEIGHBOR_OF from shards
    and recompute adjacency once.
    """
    n = len(corpus)
    # Structural + facets only
    graph = build_graph(corpus, [[] for _ in range(n)])
    cid_by_idx = corpus["entry_cid"].tolist()
    extra_edges: list[dict[str, Any]] = []
    seen = 0
    for start_i, part in iter_neighbor_shards(spill):
        for offset, neigh in enumerate(part):
            i = start_i + offset
            if i >= n:
                break
            src = cid_by_idx[i]
            for item in neigh:
                if len(item) == 3:
                    j, score, terms = item
                else:
                    j, score = item[0], item[1]
                    terms = []
                tgt = cid_by_idx[int(j)]
                extra_edges.append(
                    _edge(
                        src,
                        "BM25_NEIGHBOR_OF",
                        tgt,
                        "bm25-okapi",
                        float(score),
                        {"k": 8, "neighbor_index": int(j)},
                        matched_terms=list(terms),
                    )
                )
        seen += len(part)
        del part
        if len(extra_edges) >= 50_000:
            # Flush into edges df incrementally
            add = pd.DataFrame(extra_edges)
            graph["edges"] = pd.concat([graph["edges"], add], ignore_index=True)
            extra_edges.clear()
            del add
            gc.collect()
            checkpoint(f"graph_neighbor_edges@{seen}", row=seen, every_n=50_000, log=log)
    if extra_edges:
        add = pd.DataFrame(extra_edges)
        graph["edges"] = pd.concat([graph["edges"], add], ignore_index=True)
        del add, extra_edges
        gc.collect()

    edges_df = graph["edges"]
    if not edges_df.empty:
        edges_df = edges_df.drop_duplicates("edge_cid").reset_index(drop=True)
        edges_df = edges_df.sort_values(
            ["edge_type", "source_cid", "target_cid"]
        ).reset_index(drop=True)
    graph["edges"] = edges_df
    node_type = {r["node_cid"]: r["node_type"] for r in graph["nodes"].to_dict("records")}
    incoming, outgoing = _adjacency(edges_df, node_type)
    graph["incoming"] = incoming
    graph["outgoing"] = outgoing
    graph["stats"] = {
        "n_nodes": int(len(graph["nodes"])),
        "n_edges": int(len(edges_df)),
        "n_doc_nodes": int(
            graph["nodes"]["node_type"].isin(["law_entry", "article", "law"]).sum()
        ),
        "n_facet_nodes": int(
            graph["nodes"]["node_type"].astype(str).str.startswith("facet_").sum()
        ),
        "edge_types": sorted(edges_df["edge_type"].unique().tolist())
        if not edges_df.empty
        else [],
    }
    if log:
        log(
            f"graph from shards nodes={graph['stats']['n_nodes']} "
            f"edges={graph['stats']['n_edges']}"
        )
    return graph


def build_bm25_tf_spill(
    corpus_path: Path,
    spill: Path,
    n_docs: int,
    *,
    batch: int = 512,
    log: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Stream tokenize corpus → DuckDB TF → bm25_documents/postings parquet + stats.

    Resume: if bm25_documents.parquet + bm25_postings.parquet + bm25_stats.json exist
    with matching n_docs, reuse.
    """
    spill.mkdir(parents=True, exist_ok=True)
    docs_path = spill / "bm25_documents.parquet"
    post_path = spill / "bm25_postings.parquet"
    stats_json = spill / "bm25_stats.json"
    stats_path = spill / "bm25_stats.pkl"
    if docs_path.is_file() and post_path.is_file():
        stats = None
        if stats_json.is_file():
            stats = json.loads(stats_json.read_text(encoding="utf-8"))
        elif stats_path.is_file():
            stats = load_pickle(stats_path)
        if stats is not None and int(stats.get("n_docs", -1)) == n_docs:
            if log:
                log(f"reusing bm25 spill n_docs={n_docs}")
            return {"stats": stats, "documents": docs_path, "postings": post_path}

    duckdb = _require_duckdb()
    bm25_db = spill / "bm25_tf.duckdb"
    if bm25_db.exists():
        bm25_db.unlink()
    conn = duckdb.connect(str(bm25_db))
    conn.execute(
        "CREATE TABLE tf (term VARCHAR NOT NULL, doc INTEGER NOT NULL, "
        "ttf INTEGER NOT NULL, btf INTEGER NOT NULL)"
    )
    title_len = np.zeros(n_docs, dtype=np.int32)
    body_len = np.zeros(n_docs, dtype=np.int32)
    meta_path = spill / "doc_meta_rows.parquet"
    meta_path.unlink(missing_ok=True)
    meta_buf: list[dict] = []
    pf = pq.ParquetFile(corpus_path)
    schema_names = set(pf.schema_arrow.names)
    cols = [
        c
        for c in [
            "document_index",
            "entry_cid",
            "law_cid",
            "instrument_id",
            "law_id",
            "source_id",
            "title",
            "instrument_title",
            "article_number",
            "article_title",
            "record_type",
            "language",
            "jurisdiction",
            "body",
        ]
        if c in schema_names
    ]
    processed = 0
    batch_rows: list[tuple] = []
    for batch_tbl in pf.iter_batches(batch_size=batch, columns=cols):
        d = batch_tbl.to_pydict()
        m = len(d["document_index"])
        for i in range(m):
            di = int(d["document_index"][i])
            title = str((d.get("title") or [""])[i] or "")
            body = str((d.get("body") or [""])[i] or "")
            tt = tokenize(title)
            bt = tokenize(body)
            title_len[di] = len(tt)
            body_len[di] = len(bt)
            tf_t: dict[str, int] = defaultdict(int)
            tf_b: dict[str, int] = defaultdict(int)
            for tok in tt:
                tf_t[tok] += 1
            for tok in bt:
                tf_b[tok] += 1
            for tok in set(tf_t) | set(tf_b):
                batch_rows.append((tok, di, int(tf_t.get(tok, 0)), int(tf_b.get(tok, 0))))
            law_id = str((d.get("law_id") or d.get("instrument_id") or [""])[i] or "")
            instrument_id = str(
                (d.get("instrument_id") or d.get("law_id") or [""])[i] or ""
            )
            meta_buf.append(
                {
                    "entry_cid": str(d["entry_cid"][i]),
                    "document_index": di,
                    "law_cid": str((d.get("law_cid") or [""])[i] or ""),
                    "instrument_id": instrument_id,
                    "law_id": law_id,
                    "source_id": str(d["source_id"][i]),
                    "title": title,
                    "instrument_title": str(
                        (d.get("instrument_title") or [""])[i] or ""
                    ),
                    "article_number": str((d.get("article_number") or [""])[i] or ""),
                    "article_title": str((d.get("article_title") or [""])[i] or ""),
                    "record_type": str(d["record_type"][i]),
                    "language": str((d.get("language") or [""])[i] or ""),
                    "jurisdiction": str((d.get("jurisdiction") or [""])[i] or ""),
                }
            )
            if len(batch_rows) >= 20_000:
                conn.executemany("INSERT INTO tf VALUES (?, ?, ?, ?)", batch_rows)
                batch_rows.clear()
        processed += m
        if len(meta_buf) >= 20_000:
            dfm = pd.DataFrame(meta_buf)
            if meta_path.exists():
                old = pd.read_parquet(meta_path)
                dfm = pd.concat([old, dfm], ignore_index=True)
                del old
            dfm.to_parquet(meta_path, index=False)
            del dfm
            meta_buf.clear()
            gc.collect()
        if processed % 20_000 == 0:
            checkpoint(f"bm25_tf_tokenize", row=processed, every_n=20_000, log=log)
            gc.collect()
    if batch_rows:
        conn.executemany("INSERT INTO tf VALUES (?, ?, ?, ?)", batch_rows)
        batch_rows.clear()
    if meta_buf:
        dfm = pd.DataFrame(meta_buf)
        if meta_path.exists():
            old = pd.read_parquet(meta_path)
            dfm = pd.concat([old, dfm], ignore_index=True)
            del old
        dfm.to_parquet(meta_path, index=False)
        del dfm
        meta_buf.clear()
    if log:
        log("bm25 tf spilled to duckdb; writing documents")

    doc_len = (title_len * TITLE_WEIGHT + body_len * BODY_WEIGHT).astype(np.float64)
    avgdl = float(doc_len.mean()) if n_docs else 0.0
    meta_df = pd.read_parquet(meta_path).sort_values("document_index").reset_index(drop=True)
    assert len(meta_df) == n_docs
    meta_df["title_length"] = title_len[meta_df["document_index"].to_numpy()]
    meta_df["body_length"] = body_len[meta_df["document_index"].to_numpy()]
    meta_df["document_length"] = np.round(
        doc_len[meta_df["document_index"].to_numpy()]
    ).astype(int)
    meta_df["schema_version"] = SCHEMA_VERSION
    meta_df.to_parquet(docs_path, index=False)
    del meta_df
    gc.collect()
    meta_path.unlink(missing_ok=True)

    posting_rows: list[dict] = []
    n_postings = 0
    n_terms = 0
    part_i = 0
    cur_term = None
    cur_items: list = []

    def flush_term(term: str, items: list) -> None:
        nonlocal n_postings, n_terms, part_i, posting_rows
        if not items:
            return
        n_terms += 1
        dfreq = len(items)
        cfreq = sum(int(ttf) + int(btf) for _, ttf, btf in items)
        idf = _idf(n_docs, dfreq)
        chunks = [
            items[i : i + POSTING_ROWS_PER_RECORD]
            for i in range(0, max(len(items), 1), POSTING_ROWS_PER_RECORD)
        ]
        n_chunks = len(chunks)
        for cidx, chunk in enumerate(chunks):
            posting_rows.append(
                {
                    "term": term,
                    "document_indices": [int(d) for d, _, _ in chunk],
                    "title_frequencies": [int(ttf) for _, ttf, _ in chunk],
                    "body_frequencies": [int(btf) for _, _, btf in chunk],
                    "tfs": [
                        TITLE_WEIGHT * int(ttf) + BODY_WEIGHT * int(btf)
                        for _, ttf, btf in chunk
                    ],
                    "lengths": [int(round(doc_len[int(d)])) for d, _, _ in chunk],
                    "document_lengths": [
                        int(round(doc_len[int(d)])) for d, _, _ in chunk
                    ],
                    "document_frequency": int(dfreq),
                    "corpus_frequency": int(cfreq),
                    "idf": float(idf),
                    "posting_chunk_index": int(cidx),
                    "posting_chunk_count": int(n_chunks),
                    "schema_version": SCHEMA_VERSION,
                }
            )
        n_postings += dfreq
        if len(posting_rows) >= 8_000:
            pd.DataFrame(posting_rows).to_parquet(
                spill / f"postings_part_{part_i:08d}.parquet", index=False
            )
            posting_rows.clear()
            part_i += 1
            gc.collect()

    for term, doc, ttf, btf in conn.execute(
        "SELECT term, doc, ttf, btf FROM tf ORDER BY term, doc"
    ).fetchall():
        term = str(term)
        if cur_term is None:
            cur_term = term
        if term != cur_term:
            flush_term(cur_term, cur_items)
            cur_items = []
            cur_term = term
            if n_terms and n_terms % 50_000 == 0:
                checkpoint(f"bm25_postings_terms", row=n_terms, every_n=50_000, log=log)
        cur_items.append((int(doc), int(ttf), int(btf)))
    if cur_term is not None:
        flush_term(cur_term, cur_items)
    if posting_rows:
        pd.DataFrame(posting_rows).to_parquet(
            spill / f"postings_part_{part_i:08d}.parquet", index=False
        )
        posting_rows.clear()
    conn.close()
    gc.collect()

    parts = sorted(spill.glob("postings_part_*.parquet"))
    frames: list[pd.DataFrame] = []
    for i, part in enumerate(parts):
        frames.append(pd.read_parquet(part))
        if len(frames) >= 8:
            frames = [pd.concat(frames, ignore_index=True)]
            gc.collect()
        if i and i % 20 == 0:
            checkpoint(f"concat_postings", row=i, every_n=20, log=log)
    postings = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    del frames
    for part in parts:
        part.unlink()
    postings.to_parquet(post_path, index=False)
    out_rows = len(postings)
    del postings
    gc.collect()
    stats = {
        "k1": K1,
        "b": B,
        "title_weight": TITLE_WEIGHT,
        "body_weight": BODY_WEIGHT,
        "average_document_length": avgdl,
        "tokenizer": "fts5-unicode61-remove-diacritics-2-python/v1",
        "max_query_terms": 64,
        "posting_rows_per_record": POSTING_ROWS_PER_RECORD,
        "terms_per_shard": TERMS_PER_SHARD,
        "n_docs": n_docs,
        "n_terms": int(n_terms),
        "n_posting_rows": int(out_rows),
        "n_postings": int(n_postings),
    }
    stats_json.write_text(json.dumps(stats, indent=2) + "\n", encoding="utf-8")
    try:
        bm25_db.unlink()
    except Exception:
        pass
    if log:
        log(f"bm25 spill done terms={n_terms} posting_rows={out_rows}")
    return {"stats": stats, "documents": docs_path, "postings": post_path}


def should_use_spill(n_docs: int, threshold: int = DUCKDB_THRESHOLD) -> bool:
    return n_docs >= threshold


def should_use_sqlite(n_docs: int, threshold: int = DUCKDB_THRESHOLD) -> bool:
    """Alias: large-corpus path is DuckDB/parquet, not SQLite."""
    return should_use_spill(n_docs, threshold)
