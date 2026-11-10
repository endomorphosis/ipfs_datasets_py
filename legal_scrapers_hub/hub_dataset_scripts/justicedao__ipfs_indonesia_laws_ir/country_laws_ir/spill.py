"""Disk-spill helpers for large country IR builds (SQLite FTS neighbors + BM25 TF).

Design (CoS / DO OOM lesson):
- Embeddings: checkpointed .npy via vectors.encode_corpus (unchanged).
- Neighbors for n >= SQLITE_THRESHOLD (40k): SQLite FTS5 title-only MATCH streaming
  into neighbor_*.pkl shards under cache/<slug>_bm25_spill/ — never hold full
  neighbor matrix in RAM during streaming.
- BM25 TF: stream tokenize → SQLite WITHOUT ROWID → posting parquet parts.
- Package: use package.package_release_sequential / package_from_spill so corpus,
  bm25, graph, vectors are never all resident together; neighbor edges can be
  streamed from shards into graph then spilled as graph.pkl.

Resume-safe: existing FTS DB / neighbor shards / bm25_*.parquet are reused when
row counts match.
"""
from __future__ import annotations

import gc
import json
import math
import pickle
import sqlite3
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

SQLITE_THRESHOLD = 40_000
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


def quote_fts_term(term: str) -> str:
    return '"' + term.replace('"', '""') + '"'


def _idf(n_docs: int, df: int) -> float:
    return math.log((n_docs - df + 0.5) / (df + 0.5) + 1.0)


def sqlite_ready(db_path: Path, expected: int) -> bool:
    if not db_path.is_file():
        return False
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        n = int(conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0])
        conn.close()
        return n == expected
    except Exception:
        return False


def build_sqlite_fts(
    corpus_path: Path,
    db_path: Path,
    expected: int,
    *,
    batch: int = BATCH,
    log: Callable[[str], None] | None = None,
) -> int:
    """Contentless FTS5 over title+body; documents table holds query_text."""
    if db_path.exists():
        db_path.unlink()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    try:
        conn.executescript(
            """
            PRAGMA journal_mode = OFF;
            PRAGMA synchronous = OFF;
            PRAGMA temp_store = MEMORY;
            PRAGMA locking_mode = EXCLUSIVE;
            PRAGMA page_size = 32768;
            CREATE TABLE documents (
                document_index INTEGER PRIMARY KEY,
                entry_cid TEXT NOT NULL UNIQUE,
                title TEXT NOT NULL,
                query_text TEXT NOT NULL
            );
            CREATE VIRTUAL TABLE documents_fts USING fts5(
                title,
                body,
                content='',
                columnsize=1,
                tokenize='unicode61 remove_diacritics 2'
            );
            """
        )
        pf = pq.ParquetFile(corpus_path)
        n = 0
        meta_batch: list[tuple] = []
        fts_batch: list[tuple] = []
        conn.execute("BEGIN")
        for batch_tbl in pf.iter_batches(
            batch_size=batch, columns=["document_index", "entry_cid", "title", "body"]
        ):
            cols = batch_tbl.to_pydict()
            for i in range(len(cols["document_index"])):
                di = int(cols["document_index"][i])
                title = str(cols["title"][i] or "")
                body = str(cols["body"][i] or "")
                cid = str(cols["entry_cid"][i])
                qtext = title.strip() if title.strip() else body[:800]
                meta_batch.append((di, cid, title, qtext))
                fts_batch.append((di + 1, title, body))
                if len(meta_batch) >= batch:
                    conn.executemany(
                        "INSERT INTO documents(document_index, entry_cid, title, query_text) "
                        "VALUES (?,?,?,?)",
                        meta_batch,
                    )
                    conn.executemany(
                        "INSERT INTO documents_fts(rowid, title, body) VALUES (?,?,?)",
                        fts_batch,
                    )
                    n += len(meta_batch)
                    meta_batch.clear()
                    fts_batch.clear()
                    if n % 20_000 == 0:
                        checkpoint(f"fts_insert@{n}", row=n, every_n=20_000, log=log)
                        gc.collect()
        if meta_batch:
            conn.executemany(
                "INSERT INTO documents(document_index, entry_cid, title, query_text) "
                "VALUES (?,?,?,?)",
                meta_batch,
            )
            conn.executemany(
                "INSERT INTO documents_fts(rowid, title, body) VALUES (?,?,?)",
                fts_batch,
            )
            n += len(meta_batch)
        conn.commit()
        conn.execute("INSERT INTO documents_fts(documents_fts) VALUES('optimize')")
        conn.commit()
        conn.execute(
            "CREATE VIRTUAL TABLE documents_vocab USING fts5vocab(documents_fts, 'row')"
        )
        conn.commit()
        got = int(conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0])
        assert got == n == expected, (got, n, expected)
        return n
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
        gc.collect()


def load_df_map(conn: sqlite3.Connection, df_cap: int = DF_CAP) -> dict[str, int]:
    df_map: dict[str, int] = {}
    for term, doc in conn.execute(
        "SELECT term, doc FROM documents_vocab WHERE doc <= ?", (df_cap,)
    ):
        df_map[str(term)] = int(doc)
    return df_map


def select_query_terms(query_text: str, df_map: dict[str, int]) -> list[str]:
    toks = tokenize(query_text)[:24]
    seen: set[str] = set()
    cands: list[tuple[int, str]] = []
    for t in toks:
        if t in seen or len(t) < 2:
            continue
        seen.add(t)
        if t not in df_map:
            continue
        cands.append((df_map[t], t))
    cands.sort()
    return [t for _, t in cands[:MAX_QTERMS]]


def stream_neighbors_to_shards(
    db_path: Path,
    spill: Path,
    n_docs: int,
    *,
    k: int = NEIGHBOR_K,
    shard: int = NEIGHBOR_SHARD,
    batch: int = BATCH,
    df_cap: int = DF_CAP,
    resume: bool = True,
    log: Callable[[str], None] | None = None,
) -> list[Path]:
    """Stream FTS5 title-only neighbors into neighbor_START_END.pkl shards.

    Does not assemble the full neighbor list. Resume skips shards already on disk
    whose end index is covered (contiguous from 0).
    """
    spill.mkdir(parents=True, exist_ok=True)
    existing = sorted(spill.glob("neighbors_*.pkl"))
    buf_start = 0
    shard_paths: list[Path] = []
    if resume and existing:
        # Contiguous cover from 0
        covered = 0
        for sp in existing:
            parts = sp.stem.split("_")
            # neighbors_000000_005000
            try:
                start_i, end_i = int(parts[1]), int(parts[2])
            except (IndexError, ValueError):
                continue
            if start_i != covered:
                break
            shard_paths.append(sp)
            covered = end_i
        buf_start = covered
        if buf_start >= n_docs:
            if log:
                log(f"neighbors resume complete {buf_start}/{n_docs}")
            return shard_paths
        if log:
            log(f"neighbors resume from {buf_start}/{n_docs} shards={len(shard_paths)}")
        # Drop non-contiguous leftover shards beyond covered
        for sp in existing:
            if sp not in shard_paths:
                sp.unlink(missing_ok=True)
    else:
        for sp in existing:
            sp.unlink(missing_ok=True)

    conn_rw = sqlite3.connect(str(db_path))
    row = conn_rw.execute(
        "SELECT name FROM sqlite_master WHERE name='documents_vocab'"
    ).fetchone()
    if row is None:
        conn_rw.execute(
            "CREATE VIRTUAL TABLE documents_vocab USING fts5vocab(documents_fts, 'row')"
        )
        conn_rw.commit()
    df_map = load_df_map(conn_rw, df_cap)
    conn_rw.close()
    spill_pickle(spill / "df_map_meta.pkl", {"n_rare": len(df_map), "df_cap": df_cap})
    if log:
        log(f"vocab rare_terms={len(df_map)} df_cap={df_cap}")

    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    buf: list = []
    done = buf_start
    score_sql = f"-bm25(documents_fts, {TITLE_W}, {BODY_W})"
    last_idx = buf_start - 1
    try:
        while True:
            rows = conn.execute(
                "SELECT document_index, entry_cid, query_text FROM documents "
                "WHERE document_index > ? ORDER BY document_index LIMIT ?",
                (last_idx, batch),
            ).fetchall()
            if not rows:
                break
            for row in rows:
                di = int(row["document_index"])
                terms = select_query_terms(str(row["query_text"]), df_map)
                if not terms:
                    neigh: list = []
                else:
                    expr = " OR ".join("title : " + quote_fts_term(t) for t in terms)
                    sql = (
                        "SELECT d.document_index, " + score_sql + " AS score "
                        "FROM documents_fts "
                        "JOIN documents AS d ON d.document_index = documents_fts.rowid - 1 "
                        "WHERE documents_fts MATCH ? AND d.document_index != ? "
                        "ORDER BY score DESC, d.document_index LIMIT ?"
                    )
                    hits = conn.execute(sql, (expr, di, k)).fetchall()
                    neigh = [
                        (int(h["document_index"]), max(0.0, float(h["score"])), list(terms)[:4])
                        for h in hits
                    ]
                while buf_start + len(buf) < di:
                    buf.append([])
                buf.append(neigh)
                last_idx = di
                done += 1
                if len(buf) >= shard:
                    end = buf_start + len(buf)
                    sp = spill / f"neighbors_{buf_start:06d}_{end:06d}.pkl"
                    spill_pickle(sp, buf)
                    shard_paths.append(sp)
                    checkpoint(
                        f"neighbors_shard_{buf_start}_{end}",
                        log=log,
                    )
                    buf_start = end
                    buf = []
                    gc.collect()
                if done % 5_000 == 0:
                    checkpoint(f"neighbors_stream", row=done, every_n=5_000, log=log)
        if buf:
            end = buf_start + len(buf)
            sp = spill / f"neighbors_{buf_start:06d}_{end:06d}.pkl"
            spill_pickle(sp, buf)
            shard_paths.append(sp)
            if log:
                log(f"neighbors shard final {buf_start}:{end}/{n_docs}")
        if log:
            log(f"bm25 neighbors streamed done={done} n_docs={n_docs} shards={len(shard_paths)}")
        return shard_paths
    finally:
        conn.close()
        del df_map
        gc.collect()


def iter_neighbor_shards(spill: Path) -> Iterator[tuple[int, list]]:
    """Yield (start_index, shard_list) without loading all shards."""
    paths = sorted(spill.glob("neighbors_*.pkl"))
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


def neighbors_via_sqlite(
    corpus_path: Path,
    spill: Path,
    n_docs: int,
    *,
    k: int = NEIGHBOR_K,
    resume: bool = True,
    log: Callable[[str], None] | None = None,
) -> list[Path]:
    """Ensure FTS DB + neighbor shards; return shard paths (not full list)."""
    spill.mkdir(parents=True, exist_ok=True)
    db_path = spill / "fts.sqlite"
    if not sqlite_ready(db_path, n_docs):
        if db_path.exists():
            db_path.unlink()
        if log:
            log(f"building sqlite fts n={n_docs} -> {db_path}")
        build_sqlite_fts(corpus_path, db_path, n_docs, log=log)
    else:
        if log:
            log(f"reusing sqlite fts n={n_docs} path={db_path}")
    return stream_neighbors_to_shards(
        db_path, spill, n_docs, k=k, resume=resume, log=log
    )


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
    """Stream tokenize corpus → SQLite TF → bm25_documents/postings parquet + stats.

    Resume: if bm25_documents.parquet + bm25_postings.parquet + bm25_stats.pkl exist
    with matching n_docs, reuse.
    """
    spill.mkdir(parents=True, exist_ok=True)
    docs_path = spill / "bm25_documents.parquet"
    post_path = spill / "bm25_postings.parquet"
    stats_path = spill / "bm25_stats.pkl"
    if docs_path.is_file() and post_path.is_file() and stats_path.is_file():
        stats = load_pickle(stats_path)
        if int(stats.get("n_docs", -1)) == n_docs:
            if log:
                log(f"reusing bm25 spill n_docs={n_docs}")
            return {"stats": stats, "documents": docs_path, "postings": post_path}

    bm25_sql = spill / "bm25_tf.sqlite"
    if bm25_sql.exists():
        bm25_sql.unlink()
    conn = sqlite3.connect(str(bm25_sql))
    conn.execute("PRAGMA journal_mode=OFF")
    conn.execute("PRAGMA synchronous=OFF")
    conn.execute("PRAGMA temp_store=MEMORY")
    conn.execute("PRAGMA locking_mode=EXCLUSIVE")
    conn.execute(
        "CREATE TABLE tf (term TEXT NOT NULL, doc INTEGER NOT NULL, "
        "ttf INTEGER NOT NULL, btf INTEGER NOT NULL, PRIMARY KEY(term, doc)) WITHOUT ROWID"
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
    conn.execute("BEGIN")
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
                conn.executemany(
                    "INSERT OR REPLACE INTO tf VALUES (?,?,?,?)", batch_rows
                )
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
        conn.executemany("INSERT OR REPLACE INTO tf VALUES (?,?,?,?)", batch_rows)
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
    conn.commit()
    if log:
        log("bm25 tf spilled; writing documents")

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
    ):
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
    spill_pickle(stats_path, stats)
    try:
        bm25_sql.unlink()
    except Exception:
        pass
    if log:
        log(f"bm25 spill done terms={n_terms} posting_rows={out_rows}")
    return {"stats": stats, "documents": docs_path, "postings": post_path}


def should_use_sqlite(n_docs: int, threshold: int = SQLITE_THRESHOLD) -> bool:
    return n_docs >= threshold
