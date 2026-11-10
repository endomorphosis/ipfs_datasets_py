#!/usr/bin/env python3
"""Reusable mem-spill IR build template for TN / BE / FR / PL (and large DO next runs).

Copy and set SLUG / TIP / SRC / paths. For n >= 40k:
  embeddings → cache/embeddings/<slug>.npy (checkpointed)
  neighbors  → SQLite FTS5 stream → cache/<slug>_bm25_spill/neighbors_*.pkl
  BM25 TF    → cache/<slug>_bm25_spill/bm25_{documents,postings}.parquet
  graph      → streamed from neighbor shards (no full neighbor list)
  package    → package_from_spill (sequential; never hold all artifacts)

Env:
  IR_MEM_WARN_GIB=3.5   shed collectors
  IR_MEM_ABORT_GIB=2.5  abort if still low after shed
  IR_RSS_ABORT_GIB=12.0 abort-to-disk if process RSS exceeds
  IR_MEM_LOG_EVERY=5000

Do NOT use stock bm25_neighbors for ≥40k (DO OOM ~13.6G RSS).
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

from country_laws_ir.build import CACHE, REPORTS, _log, record_progress
from country_laws_ir.catalog import get_country, target_repo
from country_laws_ir.mem import MemAbort, checkpoint, mem_available_gib, rss_gib, shed_collectors
from country_laws_ir.normalize import build_corpus, load_source
from country_laws_ir.package import package_from_spill
from country_laws_ir.spill import (
    SQLITE_THRESHOLD,
    build_bm25_tf_spill,
    build_graph_from_neighbor_shards,
    neighbors_via_sqlite,
    spill_dir_for,
    spill_pickle,
)
from country_laws_ir.vectors import encode_corpus, embeddings_available, layout_vectors

# --- configure per country ---
SLUG = "belgium"  # tunisia | belgium | france | poland | ...
TIP = "REPLACE_FULL_TIP_SHA"
TIP_SHORT = TIP[:12]
SRC = Path(f"/workspace/country-laws-ir/cache/{SLUG}_filtered_{TIP_SHORT}")
OUT = Path(f"/workspace/country-laws-ir/releases/ipfs_{SLUG}_laws_ir")
CKPT = CACHE / "embeddings" / f"{SLUG}.npy"
CORPUS_CKPT = CACHE / f"{SLUG}_corpus_{TIP_SHORT}.parquet"
SPILL = spill_dir_for(SLUG, CACHE)  # cache/<slug>_bm25_spill/
LOG = Path(f"/workspace/country-laws-ir/reports/{SLUG}_build_{TIP_SHORT}.log")
NEIGHBOR_K = 8


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
        checkpoint("start", log=_log, notes=notes)
        if not embeddings_available():
            raise SystemExit("torch/ST unavailable — refusing stub vectors")
        if not SRC.is_dir():
            raise SystemExit(f"missing filtered pack {SRC}")

        country = get_country(str(SRC))
        laws, articles, source_meta = load_source(str(SRC), CACHE)
        if not (source_meta.get("source_revision") or "").startswith(TIP_SHORT):
            source_meta["source_revision"] = TIP
        corpus, norm_report = build_corpus(laws, articles, source_meta)
        del laws, articles
        gc.collect()
        CORPUS_CKPT.parent.mkdir(parents=True, exist_ok=True)
        corpus.to_parquet(CORPUS_CKPT, index=False)
        (REPORTS / f"{SLUG}_normalization.json").write_text(
            json.dumps(norm_report, indent=2, ensure_ascii=False) + "\n"
        )
        n = len(corpus)
        _log(f"corpus n={n} spill={SPILL} mem={mem_available_gib():.2f}G")
        if n < SQLITE_THRESHOLD:
            _log(f"WARN n={n} < {SQLITE_THRESHOLD}; template still uses sqlite path")

        CKPT.parent.mkdir(parents=True, exist_ok=True)
        emb = encode_corpus(corpus, device="cpu", checkpoint_path=str(CKPT))
        assert emb.shape[0] == n
        vectors = layout_vectors(corpus, emb)
        del emb
        SPILL.mkdir(parents=True, exist_ok=True)
        spill_pickle(SPILL / "vectors.pkl", vectors)
        del vectors, corpus
        gc.collect()
        checkpoint("vectors_spilled", log=_log, notes=notes)

        neighbors_via_sqlite(CORPUS_CKPT, SPILL, n, k=NEIGHBOR_K, log=_log)
        checkpoint("neighbors_sharded", log=_log, notes=notes)

        build_bm25_tf_spill(CORPUS_CKPT, SPILL, n, log=_log)
        checkpoint("bm25_tf_spilled", log=_log, notes=notes)

        import pandas as pd

        corpus = pd.read_parquet(CORPUS_CKPT)
        graph = build_graph_from_neighbor_shards(corpus, SPILL, log=_log)
        spill_pickle(SPILL / "graph.pkl", graph)
        del graph, corpus
        gc.collect()
        checkpoint("graph_spilled", log=_log, notes=notes)

        country = get_country(str(SRC))
        norm_report = json.loads((REPORTS / f"{SLUG}_normalization.json").read_text())
        manifest = package_from_spill(
            OUT, SPILL, CORPUS_CKPT, source_meta, country,
            Path("/workspace/country-laws-ir"),
            normalization_report=norm_report, expected_rows=n,
        )
        result = {
            "country": country["slug"],
            "out": str(OUT),
            "target_hub_id": target_repo(country["slug"]),
            "counts": manifest.get("counts"),
            "neighbor_via": "sqlite_fts",
            "spill": str(SPILL),
            "mem_end_gib": round(mem_available_gib(), 2),
            "rss_end_gib": round(rss_gib(), 2),
            "collectors_sigterm": notes,
            "finished_utc": datetime.now(timezone.utc).isoformat(),
            "via": "spill_build_template",
        }
        record_progress({"event": "built_local", **{k: result[k] for k in result if k != "counts"}})
        (REPORTS / f"{SLUG}_build_{TIP_SHORT}_result.json").write_text(
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
