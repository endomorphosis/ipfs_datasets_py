#!/usr/bin/env python3
"""Memory-safe Estonia IR package — stream corpus/BM25/graph; mmap npy for vectors (no vectors.pkl)."""
from __future__ import annotations
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))

import gc
import json
import os
import pickle
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

os.environ.setdefault("HF_HOME", "/workspace/country-laws-ir/cache/hf")
os.environ.setdefault("HF_HUB_DISABLE_IMPLICIT_TOKEN", "1")
os.environ.setdefault("MALLOC_TRIM_THRESHOLD_", "100000")
sys.path.insert(0, "/workspace/country-laws-ir")

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from country_laws_ir import MAX_ROWS_PER_FILE, SCHEMA_VERSION
from country_laws_ir.build import CACHE, REPORTS, _log, record_progress
from country_laws_ir.catalog import get_country, target_repo
from country_laws_ir.cidutil import file_descriptor
from country_laws_ir.mem import mem_available_gib, rss_gib
from country_laws_ir.parquet_io import write_parquet
from country_laws_ir.package import _index_df, _write_readme
from country_laws_ir.vectors import MODEL_NAME, DIMENSION, _l2_normalize

SLUG = "estonia"
TIP = "902b122cd27eed93e96c28a0ba5a70e9cb36ab7d"
TIP_SHORT = TIP[:12]
FLOOR_N = 0  # set from emb meta at runtime (post-norm corpus)
SRC = Path(f"/workspace/country-laws-ir/cache/{SLUG}_filtered_{TIP_SHORT}")
OUT = Path(f"/workspace/country-laws-ir/releases/ipfs_{SLUG}_laws_ir")
CORPUS_CKPT = CACHE / f"{SLUG}_corpus_{TIP_SHORT}.parquet"
EMB_NPY = CACHE / "embeddings" / f"{SLUG}_{TIP_SHORT}.npy"
EMB_JSON = EMB_NPY.with_suffix(".json")
SPILL = CACHE / f"{SLUG}_bm25_spill_{TIP_SHORT}"
GDIR = SPILL / "graph_parts"
LOG = Path(f"/workspace/country-laws-ir/reports/{SLUG}_package_memsafe_{TIP_SHORT}.log")

PEAK_RSS = 0.0


def _track_rss(label: str) -> float:
    global PEAK_RSS
    r = float(rss_gib())
    PEAK_RSS = max(PEAK_RSS, r)
    _log(f"{label} rss={r:.2f}G peak_rss={PEAK_RSS:.2f}G mem={mem_available_gib():.2f}G")
    return r


def lean_source_meta() -> dict:
    pack = json.loads((SRC / "pack_meta.json").read_text(encoding="utf-8"))
    norm_path = REPORTS / f"{SLUG}_normalization.json"
    norm = json.loads(norm_path.read_text(encoding="utf-8")) if norm_path.exists() else {}
    laws_path = SRC / "data" / "laws.parquet"
    articles_path = SRC / "data" / "articles.parquet"
    rev = str(pack.get("source_revision") or TIP)
    if not rev.startswith(TIP_SHORT):
        rev = TIP
    return {
        "source_dataset": pack.get("source_dataset") or "endomorphosis/ipfs_estonia_laws",
        "source_revision": rev,
        "laws_path": str(laws_path),
        "articles_path": str(articles_path),
        "laws_sha256": norm.get("laws_sha256"),
        "articles_sha256": norm.get("articles_sha256"),
        "n_laws_source": int(pack.get("n_laws") or 3484),
        "n_articles_source": int(pack.get("n_articles") or 62308),
        "laws_columns": [f.name for f in pq.read_schema(laws_path)],
        "articles_columns": [f.name for f in pq.read_schema(articles_path)],
        "local_source_dir": str(SRC),
        "pack_meta": pack,
    }


def _desc_for_table(
    path: Path,
    relative_dir: str,
    name: str,
    kind: str,
    shard_i: int,
    table: pa.Table,
    key_col: str,
    index_col: str | None = None,
) -> dict:
    n = int(table.num_rows)
    first_key = last_key = ""
    if key_col in table.column_names and n:
        keys = table.column(key_col)
        first_key = str(keys[0].as_py())
        last_key = str(keys[n - 1].as_py())
    start_idx = end_idx = 0
    if index_col and index_col in table.column_names and n:
        idx = table.column(index_col)
        start_idx = int(idx[0].as_py())
        end_idx = int(idx[n - 1].as_py())
    return file_descriptor(
        path,
        f"{relative_dir}/{name}",
        extra={
            "shard_id": shard_i,
            "kind": kind,
            "row_count": n,
            "first_key": first_key,
            "last_key": last_key,
            "start_document_index": start_idx,
            "end_document_index": end_idx,
            "schema_version": SCHEMA_VERSION,
        },
    )


def write_arrow_table(path: Path, table: pa.Table) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(
        table,
        path,
        compression="zstd",
        compression_level=6,
        row_group_size=min(MAX_ROWS_PER_FILE, max(table.num_rows, 1)),
        use_dictionary=True,
    )


def stream_parquet_to_shards(
    src: Path,
    out_dir: Path,
    relative_dir: str,
    kind: str,
    key_col: str,
    index_col: str | None = None,
    batch_size: int = 4096,
    count_record_type: bool = False,
) -> tuple[list[dict], int, int, int]:
    """Stream a parquet file into MAX_ROWS_PER_FILE shards. Never holds full DF."""
    out_dir.mkdir(parents=True, exist_ok=True)
    pf = pq.ParquetFile(src)
    idx_rows: list[dict] = []
    shard_i = 0
    total = 0
    n_laws = 0
    n_articles = 0
    buf: pa.Table | None = None
    for bi, batch in enumerate(pf.iter_batches(batch_size=batch_size)):
        tb = pa.Table.from_batches([batch])
        if count_record_type and "record_type" in tb.column_names:
            rts = tb.column("record_type").to_pylist()
            for r in rts:
                if r == "law":
                    n_laws += 1
                elif r == "article":
                    n_articles += 1
        buf = tb if buf is None else pa.concat_tables([buf, tb])
        while buf.num_rows >= MAX_ROWS_PER_FILE:
            part = buf.slice(0, MAX_ROWS_PER_FILE)
            buf = buf.slice(MAX_ROWS_PER_FILE)
            name = f"part-{shard_i:06d}.parquet"
            path = out_dir / name
            write_arrow_table(path, part)
            idx_rows.append(
                _desc_for_table(path, relative_dir, name, kind, shard_i, part, key_col, index_col)
            )
            total += part.num_rows
            shard_i += 1
            del part
            if shard_i % 50 == 0:
                _track_rss(f"stream {kind} shards={shard_i}")
                gc.collect()
        del tb
        if bi % 200 == 0:
            gc.collect()
    if buf is not None and buf.num_rows:
        part = buf
        name = f"part-{shard_i:06d}.parquet"
        path = out_dir / name
        write_arrow_table(path, part)
        idx_rows.append(
            _desc_for_table(path, relative_dir, name, kind, shard_i, part, key_col, index_col)
        )
        total += part.num_rows
        shard_i += 1
    del buf, pf
    gc.collect()
    return idx_rows, total, n_laws, n_articles


def write_parts_sharded(
    part_files: list[Path],
    out_dir: Path,
    relative_dir: str,
    kind: str,
    key_col: str,
    track_node_types: bool = False,
) -> tuple[list[dict], int, int, int]:
    """Read each part, re-shard to MAX_ROWS_PER_FILE. Optionally count node types."""
    out_dir.mkdir(parents=True, exist_ok=True)
    idx_rows: list[dict] = []
    shard_i = 0
    total = 0
    n_doc_nodes = 0
    n_facet_nodes = 0
    buf: pd.DataFrame | None = None
    for fi, f in enumerate(part_files):
        df = pd.read_parquet(f)
        if track_node_types and "node_type" in df.columns:
            nt = df["node_type"].astype(str)
            n_doc_nodes += int(nt.isin(["law_entry", "article", "law"]).sum())
            n_facet_nodes += int(nt.str.startswith("facet_").sum())
        if buf is None:
            buf = df
        else:
            buf = pd.concat([buf, df], ignore_index=True)
        del df
        while len(buf) >= MAX_ROWS_PER_FILE:
            part = buf.iloc[:MAX_ROWS_PER_FILE].copy()
            buf = buf.iloc[MAX_ROWS_PER_FILE:].reset_index(drop=True)
            name = f"part-{shard_i:06d}.parquet"
            path = out_dir / name
            write_parquet(path, part)
            keys = part[key_col].astype(str) if key_col in part.columns and not part.empty else None
            desc = file_descriptor(
                path,
                f"{relative_dir}/{name}",
                extra={
                    "shard_id": shard_i,
                    "kind": kind,
                    "row_count": int(len(part)),
                    "first_key": keys.iloc[0] if keys is not None else "",
                    "last_key": keys.iloc[-1] if keys is not None else "",
                    "schema_version": SCHEMA_VERSION,
                },
            )
            idx_rows.append(desc)
            total += len(part)
            shard_i += 1
            del part
        if fi % 40 == 0:
            _track_rss(f"write {kind} parts @{fi+1}/{len(part_files)} shards={shard_i}")
            gc.collect()
    if buf is not None and len(buf):
        part = buf
        name = f"part-{shard_i:06d}.parquet"
        path = out_dir / name
        write_parquet(path, part)
        keys = part[key_col].astype(str) if key_col in part.columns and not part.empty else None
        desc = file_descriptor(
            path,
            f"{relative_dir}/{name}",
            extra={
                "shard_id": shard_i,
                "kind": kind,
                "row_count": int(len(part)),
                "first_key": keys.iloc[0] if keys is not None else "",
                "last_key": keys.iloc[-1] if keys is not None else "",
                "schema_version": SCHEMA_VERSION,
            },
        )
        idx_rows.append(desc)
        total += len(part)
        shard_i += 1
    del buf
    gc.collect()
    return idx_rows, total, n_doc_nodes, n_facet_nodes


def write_vectors_from_mmap(
    corpus_path: Path,
    npy_path: Path,
    out_dir: Path,
    indexes_dir: Path,
    n: int,
) -> tuple[list[dict], dict, int]:
    """Write vector shards from mmap .npy + streamed corpus meta. Never load vectors.pkl."""
    out_dir.mkdir(parents=True, exist_ok=True)
    emb = np.load(str(npy_path), mmap_mode="r")
    assert emb.shape == (n, DIMENSION), (emb.shape, n, DIMENSION)

    meta_cols = [
        "entry_cid",
        "document_index",
        "law_cid",
        "instrument_id",
        "law_id",
        "title",
        "record_type",
        "language",
        "jurisdiction",
    ]
    pf = pq.ParquetFile(corpus_path)
    # Stream meta in MAX_ROWS batches aligned with file/document_index order
    meta_batches: list[dict[str, list]] = []
    # Actually process on the fly without storing all meta
    vec_idx: list[dict] = []
    chunk_meta: list[dict] = []
    sum_vec = np.zeros(DIMENSION, dtype=np.float64)
    n_done = 0
    shard_i = 0
    buf_cols: dict[str, list] = {c: [] for c in meta_cols}
    buf_n = 0

    def flush_shard(cols: dict[str, list], start_row: int) -> None:
        nonlocal shard_i, n_done, sum_vec
        m = len(cols["entry_cid"])
        if m == 0:
            return
        end_row = start_row + m
        x = np.asarray(emb[start_row:end_row], dtype=np.float32)
        x = _l2_normalize(x)
        sum_vec += x.astype(np.float64).sum(axis=0)
        shard_centroid = _l2_normalize(x.mean(axis=0).astype(np.float32))
        sims = x @ shard_centroid
        order = np.argsort(-sims)
        x = x[order]
        # reorder meta
        ordered = {c: [cols[c][i] for i in order] for c in meta_cols}
        faiss_ids = (np.arange(start_row, end_row, dtype=np.int64)[order]).tolist()
        doc_idx = ordered["document_index"]
        chunk_id = f"vec-{shard_i:06d}"
        part = pd.DataFrame(
            {
                "chunk_id": [chunk_id] * m,
                "cluster_id": [shard_i] * m,
                "entry_cid": ordered["entry_cid"],
                "faiss_id": faiss_ids,
                "document_index": doc_idx,
                "corpus_chunk_id": [int(d) // MAX_ROWS_PER_FILE for d in doc_idx],
                "corpus_row_offset": [int(d) % MAX_ROWS_PER_FILE for d in doc_idx],
                "law_cid": ordered["law_cid"],
                "instrument_id": ordered["instrument_id"],
                "law_id": ordered["law_id"],
                "title": ordered["title"],
                "record_type": ordered["record_type"],
                "language": ordered["language"],
                "jurisdiction": ordered["jurisdiction"],
                "embedding": [x[i].tolist() for i in range(m)],
                "schema_version": SCHEMA_VERSION,
            }
        )
        name = f"part-{shard_i:06d}.parquet"
        path = out_dir / name
        write_parquet(path, part)
        keys = part["entry_cid"].astype(str)
        desc = file_descriptor(
            path,
            f"data/vectors/{name}",
            extra={
                "shard_id": shard_i,
                "kind": "vectors",
                "row_count": int(m),
                "first_key": keys.iloc[0],
                "last_key": keys.iloc[-1],
                "schema_version": SCHEMA_VERSION,
                "centroid": shard_centroid.tolist(),
                "shard_centroid": shard_centroid.tolist(),
                "centroid_min_score": float(sims.min()) if len(sims) else 0.0,
                "centroid_shard_count": 1,
                "chunk_in_cluster": 0,
                "cluster_id": shard_i,
                "dimension": DIMENSION,
                "model_name": MODEL_NAME,
            },
        )
        vec_idx.append(desc)
        chunk_meta.append(
            {
                "cluster_id": shard_i,
                "chunk_id": chunk_id,
                "centroid": shard_centroid.tolist(),
                "shard_centroid": shard_centroid.tolist(),
                "centroid_min_score": float(sims.min()) if len(sims) else 0.0,
                "centroid_shard_count": 1,
                "chunk_in_cluster": 0,
                "dimension": DIMENSION,
                "model_name": MODEL_NAME,
                "row_count": m,
                "first_key": keys.iloc[0],
                "last_key": keys.iloc[-1],
            }
        )
        n_done += m
        shard_i += 1
        del part, x, ordered
        if shard_i % 20 == 0:
            _track_rss(f"vectors shard @{shard_i} n_done={n_done}")
            gc.collect()

    row_cursor = 0  # absolute row in corpus/emb aligned with flush start
    shard_start = 0
    for batch in pf.iter_batches(batch_size=MAX_ROWS_PER_FILE, columns=meta_cols):
        tb = pa.Table.from_batches([batch])
        for c in meta_cols:
            buf_cols[c].extend(tb.column(c).to_pylist())
        buf_n += tb.num_rows
        while buf_n >= MAX_ROWS_PER_FILE:
            take = {c: buf_cols[c][:MAX_ROWS_PER_FILE] for c in meta_cols}
            for c in meta_cols:
                buf_cols[c] = buf_cols[c][MAX_ROWS_PER_FILE:]
            buf_n -= MAX_ROWS_PER_FILE
            flush_shard(take, shard_start)
            shard_start += MAX_ROWS_PER_FILE
        del tb
    if buf_n:
        flush_shard(buf_cols, shard_start)
        shard_start += buf_n

    assert n_done == n, (n_done, n)
    global_centroid = _l2_normalize((sum_vec / max(n, 1)).astype(np.float32)).tolist()
    write_parquet(indexes_dir / "vector_chunks.parquet", _index_df(vec_idx))
    vstats = {
        "model_name": MODEL_NAME,
        "dimension": DIMENSION,
        "similarity": "cosine",
        "assignment": "sequential_shards",
        "layout": "semantic_centroid_groups",
        "rows_sorted_by": "cosine_similarity_to_shard_centroid_desc",
        "max_rows_per_chunk": MAX_ROWS_PER_FILE,
        "n_vectors": int(n_done),
        "centroid_count": len(chunk_meta),
        "shard_count": len(chunk_meta),
        "status": "embedded",
        "via": "mmap_npy_stream_package_memsafe",
        "global_centroid": global_centroid,
    }
    del emb, pf, buf_cols
    gc.collect()
    return vec_idx, vstats, n_done


def main() -> int:
    global PEAK_RSS
    LOG.parent.mkdir(parents=True, exist_ok=True)
    log_f = LOG.open("w", encoding="utf-8")

    class Tee:
        def write(self, d):
            sys.__stdout__.write(d)
            sys.__stdout__.flush()
            log_f.write(d)
            log_f.flush()

        def flush(self):
            sys.__stdout__.flush()
            log_f.flush()

    sys.stdout = Tee()
    sys.stderr = Tee()
    try:
        node_files = sorted(GDIR.glob("nodes_*.parquet"))
        edge_files = sorted(GDIR.glob("edges_*.parquet"))
        if not node_files or not edge_files:
            raise SystemExit(f"missing graph_parts nodes={len(node_files)} edges={len(edge_files)}")
        for req in (
            SPILL / "bm25_documents.parquet",
            SPILL / "bm25_postings.parquet",
            SPILL / "bm25_stats.pkl",
            CORPUS_CKPT,
            EMB_NPY,
            EMB_JSON,
        ):
            if not Path(req).exists():
                raise SystemExit(f"missing {req}")

        emb_meta = json.loads(EMB_JSON.read_text())
        global FLOOR_N
        FLOOR_N = int(emb_meta.get("n") or 0)
        if FLOOR_N <= 0 or int(emb_meta.get("done") or 0) != FLOOR_N:
            raise SystemExit(f"emb meta mismatch {emb_meta}")
        _log(f"FLOOR_N from emb meta = {FLOOR_N}")

        # Idempotent: wipe partial release
        if OUT.exists():
            _log(f"wiping OUT {OUT}")
            shutil.rmtree(OUT)
        OUT.mkdir(parents=True)
        indexes_dir = OUT / "indexes"
        indexes_dir.mkdir()
        _track_rss(f"package_memsafe start nodes={len(node_files)} edges={len(edge_files)}")

        # --- corpus (stream) ---
        corpus_idx, N, n_laws, n_articles = stream_parquet_to_shards(
            CORPUS_CKPT,
            OUT / "data" / "corpus",
            "data/corpus",
            kind="corpus",
            key_col="entry_cid",
            index_col="document_index",
            batch_size=4096,
            count_record_type=True,
        )
        write_parquet(indexes_dir / "corpus_chunks.parquet", _index_df(corpus_idx))
        if N != FLOOR_N:
            raise SystemExit(f"corpus_rows {N} != floor {FLOOR_N}")
        gc.collect()
        _track_rss(f"corpus done n={N} laws={n_laws} articles={n_articles}")

        # --- bm25 documents ---
        with (SPILL / "bm25_stats.pkl").open("rb") as f:
            bm25_stats = pickle.load(f)
        bm25_doc_idx, n_bm25_docs, _, _ = stream_parquet_to_shards(
            SPILL / "bm25_documents.parquet",
            OUT / "data" / "bm25" / "documents",
            "data/bm25/documents",
            kind="bm25_documents",
            key_col="entry_cid",
            index_col="document_index",
            batch_size=4096,
        )
        write_parquet(indexes_dir / "bm25_document_chunks.parquet", _index_df(bm25_doc_idx))
        gc.collect()
        _track_rss(f"bm25 docs done n={n_bm25_docs}")

        # --- bm25 postings (arrow stream — pandas inflate kills) ---
        posting_idx, n_posting_rows, _, _ = stream_parquet_to_shards(
            SPILL / "bm25_postings.parquet",
            OUT / "data" / "bm25" / "postings",
            "data/bm25/postings",
            kind="bm25_postings",
            key_col="term",
            batch_size=1024,
        )
        write_parquet(indexes_dir / "bm25_keyword_shards.parquet", _index_df(posting_idx))
        gc.collect()
        _track_rss(f"bm25 postings done n={n_posting_rows}")

        # --- graph nodes (parts already unique — no concat-all) ---
        node_idx, n_nodes, n_doc_nodes, n_facet_nodes = write_parts_sharded(
            node_files,
            OUT / "data" / "graph" / "nodes",
            "data/graph/nodes",
            kind="graph_nodes",
            key_col="node_cid",
            track_node_types=True,
        )
        write_parquet(indexes_dir / "graph_node_chunks.parquet", _index_df(node_idx))
        gc.collect()
        _track_rss(f"graph nodes done n={n_nodes} doc={n_doc_nodes} facet={n_facet_nodes}")

        # --- graph edges ---
        edge_idx, n_edges, _, _ = write_parts_sharded(
            edge_files,
            OUT / "data" / "graph" / "edges",
            "data/graph/edges",
            kind="graph_edges",
            key_col="edge_cid",
        )
        write_parquet(indexes_dir / "graph_edge_chunks.parquet", _index_df(edge_idx))
        gc.collect()
        _track_rss(f"graph edges done n={n_edges} shards={len(edge_idx)}")

        # empty adjacency placeholders
        empty_adj = pd.DataFrame(columns=["node_cid", "page_index", "direction"])
        # write empty placeholder shards via write_parquet directly
        for direction, rel in (
            ("incoming", "data/graph/adjacency/incoming"),
            ("outgoing", "data/graph/adjacency/outgoing"),
        ):
            d = OUT / rel
            d.mkdir(parents=True, exist_ok=True)
            # zero-row placeholder file so indexes are non-empty descriptors
            name = "part-000000.parquet"
            path = d / name
            write_parquet(path, empty_adj)
            desc = file_descriptor(
                path,
                f"{rel}/{name}",
                extra={
                    "shard_id": 0,
                    "kind": f"graph_{direction}_adjacency",
                    "row_count": 0,
                    "first_key": "",
                    "last_key": "",
                    "schema_version": SCHEMA_VERSION,
                    "direction": direction,
                    "adjacency_count": 0,
                    "node_count": 0,
                    "first_page_index": 0,
                    "last_page_index": 0,
                },
            )
            write_parquet(
                indexes_dir / f"graph_{direction}_adjacency.parquet",
                _index_df([desc]),
            )
        edge_types = [
            "ARTICLE_OF",
            "BM25_NEIGHBOR_OF",
            "HAS_INSTRUMENT",
            "HAS_JURISDICTION",
            "HAS_LANGUAGE",
            "HAS_SOURCE",
            "HAS_STATUS",
            "IDENTIFIED_BY",
            "IDENTIFIED_BY_ELI",
        ]
        gc.collect()
        _track_rss("graph adj empty placeholders")

        # --- vectors from mmap npy (skip vectors.pkl) ---
        _vec_idx, vstats, n_vectors = write_vectors_from_mmap(
            CORPUS_CKPT, EMB_NPY, OUT / "data" / "vectors", indexes_dir, N
        )
        if n_vectors != FLOOR_N:
            raise SystemExit(f"vector_rows {n_vectors} != floor {FLOOR_N}")
        gc.collect()
        _track_rss(f"vectors done n={n_vectors}")

        # --- bundle code + manifest ---
        country = get_country(str(SRC))
        source_meta = lean_source_meta()
        norm_report = {}
        npth = REPORTS / f"{SLUG}_normalization.json"
        if npth.exists():
            norm_report = json.loads(npth.read_text())
        code_root = Path("/workspace/country-laws-ir")
        pkg_src = code_root / "country_laws_ir"
        dest_pkg = OUT / "country_laws_ir"
        shutil.copytree(
            pkg_src,
            dest_pkg,
            dirs_exist_ok=True,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".venv"),
        )
        scripts_dir = OUT / "scripts"
        scripts_dir.mkdir(exist_ok=True)
        for name in (
            "build_country_laws_ir.py",
            "normalize_country_laws.py",
            "query_country_laws_hf.py",
            "query_country_laws_ir.py",
            "generate_country_laws_ir.py",
        ):
            src = code_root / "scripts" / name
            if src.exists():
                shutil.copy2(src, scripts_dir / name)
        hub_id = target_repo(country["slug"])
        gstats = {
            "n_nodes": n_nodes,
            "n_edges": n_edges,
            "n_doc_nodes": n_doc_nodes,
            "n_facet_nodes": n_facet_nodes,
            "edge_types": edge_types,
            "adjacency": "empty_placeholder_oom_avoidance",
        }
        counts = {
            "corpus_rows": N,
            "laws": n_laws,
            "articles": n_articles,
            "bm25_documents": n_bm25_docs,
            "bm25_posting_rows": n_posting_rows,
            "graph_nodes": n_nodes,
            "graph_edges": n_edges,
            "vector_rows": n_vectors,
            "graph_incoming_adjacency_rows": 0,
            "graph_outgoing_adjacency_rows": 0,
        }
        manifest = {
            "schema_version": SCHEMA_VERSION,
            "dataset_revision": TIP,
            "country": country,
            "source": source_meta,
            "counts": counts,
            "bm25": bm25_stats,
            "graph": gstats,
            "vector": vstats,
            "normalization": norm_report,
            "neighbor_via": "sqlite_fts",
            "built_utc": datetime.now(timezone.utc).isoformat(),
            "via": "estonia_package_memsafe_mmap_npy",
            "peak_rss_gib": round(PEAK_RSS, 2),
        }
        (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2, default=str) + "\n")
        try:
            _write_readme(OUT, country, source_meta, counts, bm25_stats, gstats, vstats, hub_id)
        except Exception as e:
            _log(f"readme warn: {e}")
            (OUT / "README.md").write_text(f"# {hub_id}\n\nEstonia laws IR release.\n")
        _track_rss(f"packaged {OUT} counts={counts}")

        result = {
            "country": country["slug"],
            "out": str(OUT),
            "target_hub_id": hub_id,
            "counts": counts,
            "neighbor_via": "sqlite_fts",
            "spill": str(SPILL),
            "mem_end_gib": round(mem_available_gib(), 2),
            "rss_end_gib": round(rss_gib(), 2),
            "peak_rss_gib": round(PEAK_RSS, 2),
            "finished_utc": datetime.now(timezone.utc).isoformat(),
            "via": "estonia_package_memsafe_mmap_npy",
            "source_revision": TIP,
            "graph_adjacency": "empty_placeholder",
            "vectors_source": str(EMB_NPY),
            "vectors_pkl_loaded": False,
        }
        record_progress({"event": "built_local", **{k: result[k] for k in result if k != "counts"}})
        (REPORTS / f"{SLUG}_build_{TIP_SHORT}_result.json").write_text(
            json.dumps(result, indent=2, default=str) + "\n"
        )
        print(json.dumps(result, indent=2, default=str))
        return 0
    finally:
        try:
            log_f.close()
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
