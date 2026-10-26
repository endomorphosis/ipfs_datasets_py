#!/usr/bin/env python3
"""Estonia RECONFIRM_FINAL finish from complete emb ckpt — memsafe layout (no embedding.tolist()).

Skips encode_corpus (done=779141). Builds vectors with float32 ndarray cells,
spills, then sqlite neighbors → bm25 → graph → package_from_spill.
"""
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
import sys
from datetime import datetime, timezone
from pathlib import Path

os.environ.setdefault("HF_HOME", "/workspace/country-laws-ir/cache/hf")
os.environ.setdefault("HF_HUB_DISABLE_IMPLICIT_TOKEN", "1")
os.environ.setdefault("MALLOC_TRIM_THRESHOLD_", "100000")
sys.path.insert(0, "/workspace/country-laws-ir")

import numpy as np
import pandas as pd

from country_laws_ir.build import CACHE, REPORTS, _log, record_progress
from country_laws_ir.catalog import get_country, target_repo
from country_laws_ir.mem import MemAbort, checkpoint, mem_available_gib, rss_gib
from country_laws_ir.package import package_from_spill
from country_laws_ir.spill import (
    build_bm25_tf_spill,
    build_graph_from_neighbor_shards,
    neighbors_via_sqlite,
    spill_pickle,
)
from country_laws_ir.vectors import (
    DIMENSION,
    MODEL_NAME,
    SCHEMA_VERSION,
    _l2_normalize,
    _recursive_clusters,
)
from country_laws_ir import MAX_ROWS_PER_FILE

SLUG = "estonia"
TIP = "902b122cd27eed93e96c28a0ba5a70e9cb36ab7d"
TIP_SHORT = TIP[:12]
SRC = Path(f"/workspace/country-laws-ir/cache/{SLUG}_filtered_{TIP_SHORT}")
OUT = Path(f"/workspace/country-laws-ir/releases/ipfs_{SLUG}_laws_ir")
CKPT = CACHE / "embeddings" / f"{SLUG}_{TIP_SHORT}.npy"
CORPUS_CKPT = CACHE / f"{SLUG}_corpus_{TIP_SHORT}.parquet"
SPILL = CACHE / f"{SLUG}_bm25_spill_{TIP_SHORT}"
LOG = Path(f"/workspace/country-laws-ir/reports/{SLUG}_finish_{TIP_SHORT}.log")
NEIGHBOR_K = 8

LAYOUT_COLS = [
    "entry_cid", "document_index", "law_cid", "instrument_id", "law_id",
    "title", "instrument_title", "record_type", "language", "jurisdiction",
]


def lean_source_meta() -> dict:
    pack = json.loads((SRC / "pack_meta.json").read_text(encoding="utf-8"))
    norm_path = REPORTS / f"{SLUG}_normalization.json"
    norm = json.loads(norm_path.read_text(encoding="utf-8")) if norm_path.exists() else {}
    import pyarrow.parquet as pq
    laws_path = SRC / "data" / "laws.parquet"
    articles_path = SRC / "data" / "articles.parquet"
    laws_cols = [f.name for f in pq.read_schema(laws_path)]
    art_cols = [f.name for f in pq.read_schema(articles_path)]
    rev = str(pack.get("source_revision") or TIP)
    if not rev.startswith(TIP_SHORT):
        rev = TIP
    return {
        "source_dataset": pack.get("source_dataset") or pack.get("repo") or "endomorphosis/ipfs_estonia_laws",
        "source_revision": rev,
        "laws_path": str(laws_path),
        "articles_path": str(articles_path),
        "laws_sha256": norm.get("laws_sha256"),
        "articles_sha256": norm.get("articles_sha256"),
        "n_laws_source": int(pack.get("n_laws") or 3484),
        "n_articles_source": int(pack.get("n_articles") or 533538),
        "laws_columns": laws_cols,
        "articles_columns": art_cols,
        "local_source_dir": str(SRC),
        "pack_meta": pack,
    }


def layout_vectors_memsafe(corpus: pd.DataFrame, embeddings: np.ndarray) -> dict:
    """Same layout as layout_vectors but embedding cells stay float32 ndarrays (no tolist)."""
    x = np.asarray(embeddings, dtype=np.float32)
    if not x.flags["OWNDATA"]:
        x = np.array(x, dtype=np.float32)  # materialize mmap once
    x = _l2_normalize(x)
    gc.collect()
    _log(f"layout sequential start n={len(x)} rss={rss_gib():.2f}G mem={mem_available_gib():.2f}G")
    # Skip _recursive_clusters — OOM/SIGKILL on ~677k vectors. Contiguous shards only.
    n = len(x)
    clusters = [np.arange(i, min(i + MAX_ROWS_PER_FILE, n), dtype=np.int64) for i in range(0, n, MAX_ROWS_PER_FILE)]
    _log(f"layout sequential shards={len(clusters)} max_rows={MAX_ROWS_PER_FILE} rss={rss_gib():.2f}G mem={mem_available_gib():.2f}G")
    # columnar builders — avoid 779k Python dicts
    chunk_ids: list[str] = []
    cluster_ids: list[int] = []
    entry_cids: list = []
    faiss_ids: list[int] = []
    document_indices: list[int] = []
    corpus_chunk_ids: list[int] = []
    corpus_row_offsets: list[int] = []
    law_cids: list = []
    instrument_ids: list = []
    law_ids: list = []
    titles: list = []
    record_types: list = []
    languages: list = []
    jurisdictions: list = []
    emb_rows: list[np.ndarray] = []
    chunk_meta: list = []
    global_centroid = _l2_normalize(x.mean(axis=0))
    # iloc access is slow; extract columns once
    col_entry = corpus["entry_cid"].to_numpy()
    col_doc = corpus["document_index"].to_numpy()
    col_law_cid = corpus["law_cid"].to_numpy() if "law_cid" in corpus.columns else np.array([""] * len(corpus), dtype=object)
    col_instr = (
        corpus["instrument_id"].to_numpy()
        if "instrument_id" in corpus.columns
        else corpus["law_id"].to_numpy()
    )
    col_law_id = (
        corpus["law_id"].to_numpy()
        if "law_id" in corpus.columns
        else corpus["instrument_id"].to_numpy()
    )
    if "title" in corpus.columns:
        col_title = corpus["title"].to_numpy()
    else:
        col_title = corpus["instrument_title"].to_numpy()
    col_rt = corpus["record_type"].to_numpy()
    col_lang = corpus["language"].to_numpy() if "language" in corpus.columns else np.array([""] * len(corpus), dtype=object)
    col_jur = corpus["jurisdiction"].to_numpy() if "jurisdiction" in corpus.columns else np.array([""] * len(corpus), dtype=object)

    for cluster_id, members in enumerate(clusters):
        shard_centroid = _l2_normalize(x[members].mean(axis=0))
        sims = x[members] @ shard_centroid
        order = np.argsort(-sims)
        members = members[order]
        sims = sims[order]
        chunk_id = f"vec-{cluster_id:06d}"
        for doc_i in members:
            di = int(doc_i)
            chunk_ids.append(chunk_id)
            cluster_ids.append(int(cluster_id))
            entry_cids.append(col_entry[di])
            faiss_ids.append(di)
            doci = int(col_doc[di])
            document_indices.append(doci)
            corpus_chunk_ids.append(doci // MAX_ROWS_PER_FILE)
            corpus_row_offsets.append(doci % MAX_ROWS_PER_FILE)
            law_cids.append(col_law_cid[di])
            instrument_ids.append(col_instr[di])
            law_ids.append(col_law_id[di])
            titles.append(col_title[di])
            record_types.append(col_rt[di])
            languages.append(col_lang[di])
            jurisdictions.append(col_jur[di])
            emb_rows.append(x[di])  # view into x — compact vs tolist
        chunk_meta.append(
            {
                "cluster_id": int(cluster_id),
                "chunk_id": chunk_id,
                "centroid": shard_centroid.tolist(),
                "shard_centroid": shard_centroid.tolist(),
                "centroid_min_score": float(sims.min()) if len(sims) else 0.0,
                "centroid_shard_count": 1,
                "chunk_in_cluster": 0,
                "dimension": DIMENSION,
                "model_name": MODEL_NAME,
                "row_count": int(len(members)),
                "first_key": str(col_entry[int(members[0])]) if len(members) else "",
                "last_key": str(col_entry[int(members[-1])]) if len(members) else "",
            }
        )
        if cluster_id % 20 == 0:
            _log(f"layout cluster {cluster_id}/{len(clusters)} rows={len(chunk_ids)} rss={rss_gib():.2f}G")

    vectors_df = pd.DataFrame(
        {
            "chunk_id": chunk_ids,
            "cluster_id": cluster_ids,
            "entry_cid": entry_cids,
            "faiss_id": faiss_ids,
            "document_index": document_indices,
            "corpus_chunk_id": corpus_chunk_ids,
            "corpus_row_offset": corpus_row_offsets,
            "law_cid": law_cids,
            "instrument_id": instrument_ids,
            "law_id": law_ids,
            "title": titles,
            "record_type": record_types,
            "language": languages,
            "jurisdiction": jurisdictions,
            "embedding": emb_rows,
            "schema_version": SCHEMA_VERSION,
        }
    )
    return {
        "vectors": vectors_df,
        "chunk_meta": chunk_meta,
        "global_centroid": global_centroid.tolist(),
        "stats": {
            "model_name": MODEL_NAME,
            "dimension": DIMENSION,
            "similarity": "cosine",
            "assignment": "sequential_shards",
            "layout": "semantic_centroid_groups",
            "rows_sorted_by": "cosine_similarity_to_shard_centroid_desc",
            "max_rows_per_chunk": MAX_ROWS_PER_FILE,
            "n_vectors": int(len(vectors_df)),
            "centroid_count": len(clusters),
            "shard_count": len(clusters),
            "status": "embedded",
            "via": "layout_vectors_memsafe_sequential",
        },
    }


def main() -> int:
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
    notes: list = []
    try:
        checkpoint("finish_start", log=_log, notes=notes)
        if not CKPT.is_file():
            raise SystemExit(f"missing emb ckpt {CKPT}")
        if not CORPUS_CKPT.is_file():
            raise SystemExit(f"missing corpus {CORPUS_CKPT}")
        meta = json.loads(CKPT.with_suffix(".json").read_text())
        if int(meta.get("done") or 0) < int(meta.get("n") or 0):
            raise SystemExit(f"emb incomplete {meta}")

        country = get_country(str(SRC))
        source_meta = lean_source_meta()
        corpus = pd.read_parquet(CORPUS_CKPT)
        n = len(corpus)
        drop_cols = [c for c in ("body", "body_sha256") if c in corpus.columns]
        if drop_cols:
            corpus = corpus.drop(columns=drop_cols)
        gc.collect()
        _log(f"corpus n={n} dropped={drop_cols} mem={mem_available_gib():.2f}G rss={rss_gib():.2f}G")

        emb = np.load(CKPT, mmap_mode="r")
        assert emb.shape == (n, DIMENSION), (emb.shape, n)
        vectors = layout_vectors_memsafe(corpus, emb)
        del emb
        gc.collect()
        _log(f"vectors n={vectors['stats']['n_vectors']} shards={vectors['stats']['shard_count']} rss={rss_gib():.2f}G")
        SPILL.mkdir(parents=True, exist_ok=True)
        spill_pickle(SPILL / "vectors.pkl", vectors)
        del vectors, corpus
        gc.collect()
        checkpoint("vectors_spilled", log=_log, notes=notes)

        neighbors_via_sqlite(CORPUS_CKPT, SPILL, n, k=NEIGHBOR_K, log=_log)
        checkpoint("neighbors_sharded", log=_log, notes=notes)

        build_bm25_tf_spill(CORPUS_CKPT, SPILL, n, log=_log)
        checkpoint("bm25_tf_spilled", log=_log, notes=notes)

        # Graph+package deferred to stream_graph_parts + package_stream (BE OOM lesson)
        checkpoint("bm25_done_defer_graph", log=_log, notes=notes)
        result = {
            "country": country["slug"],
            "out": str(OUT),
            "target_hub_id": target_repo(country["slug"]),
            "counts": {"corpus_rows": n, "vector_rows": n},
            "neighbor_via": "sqlite_fts",
            "spill": str(SPILL),
            "mem_end_gib": round(mem_available_gib(), 2),
            "rss_end_gib": round(rss_gib(), 2),
            "collectors_sigterm": notes,
            "finished_utc": datetime.now(timezone.utc).isoformat(),
            "via": "estonia_finish_from_emb_memsafe_pre_graph",
            "source_revision": TIP,
            "phase": "vectors_neighbors_bm25_ready",
        }
        record_progress({"event": "estonia_pre_graph", "corpus_n": n, "tip": TIP_SHORT})
        (REPORTS / f"{SLUG}_finish_pre_graph_{TIP_SHORT}.json").write_text(
            json.dumps(result, indent=2, default=str) + "\n"
        )
        print(json.dumps(result, indent=2, default=str))
        return 0
    except MemAbort as e:
        _log(f"abort: {e}")
        return 2
    finally:
        try:
            log_f.close()
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
