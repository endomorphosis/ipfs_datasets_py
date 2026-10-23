#!/usr/bin/env python3
"""Estonia graph+package with streaming edge/node spill (avoid list-of-dicts OOM)."""
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
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

os.environ.setdefault("HF_HOME", "/workspace/country-laws-ir/cache/hf")
os.environ.setdefault("HF_HUB_DISABLE_IMPLICIT_TOKEN", "1")
os.environ.setdefault("MALLOC_TRIM_THRESHOLD_", "100000")
sys.path.insert(0, "/workspace/country-laws-ir")

import pandas as pd

from country_laws_ir.build import CACHE, REPORTS, _log, record_progress
from country_laws_ir.catalog import get_country, target_repo
from country_laws_ir.graph import (
    FACET_FIELDS,
    SCHEMA_VERSION,
    _adjacency,
    _edge,
    _edge_cid,
    _facet_cid,
    _json,
    _props_tuple,
)
from country_laws_ir.mem import MemAbort, checkpoint, mem_available_gib, rss_gib
from country_laws_ir.package import package_from_spill
from country_laws_ir.spill import iter_neighbor_shards, spill_pickle

SLUG = "estonia"
TIP = "902b122cd27eed93e96c28a0ba5a70e9cb36ab7d"
TIP_SHORT = TIP[:12]
SRC = Path(f"/workspace/country-laws-ir/cache/{SLUG}_filtered_{TIP_SHORT}")
OUT = Path(f"/workspace/country-laws-ir/releases/ipfs_{SLUG}_laws_ir")
CORPUS_CKPT = CACHE / f"{SLUG}_corpus_{TIP_SHORT}.parquet"
SPILL = CACHE / f"{SLUG}_bm25_spill_{TIP_SHORT}"
GDIR = SPILL / "graph_parts"
LOG = Path(f"/workspace/country-laws-ir/reports/{SLUG}_stream_graph_{TIP_SHORT}.log")
N = None  # filled from corpus len
FLUSH = 25_000


def lean_source_meta() -> dict:
    pack = json.loads((SRC / "pack_meta.json").read_text(encoding="utf-8"))
    norm_path = REPORTS / f"{SLUG}_normalization.json"
    norm = json.loads(norm_path.read_text(encoding="utf-8")) if norm_path.exists() else {}
    import pyarrow.parquet as pq
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
        "n_articles_source": int(pack.get("n_articles") or 533538),
        "laws_columns": [f.name for f in pq.read_schema(laws_path)],
        "articles_columns": [f.name for f in pq.read_schema(articles_path)],
        "local_source_dir": str(SRC),
        "pack_meta": pack,
    }


def _flush_df(rows: list, path: Path) -> None:
    if not rows:
        return
    pd.DataFrame(rows).to_parquet(path, index=False)
    rows.clear()
    gc.collect()


def build_graph_streaming(corpus: pd.DataFrame, spill: Path, log=_log) -> dict:
    GDIR.mkdir(parents=True, exist_ok=True)
    # clean old parts
    for p in GDIR.glob("*.parquet"):
        p.unlink()

    nodes: list = []
    edges: list = []
    seen_facets: set[str] = set()
    law_nodes: dict[str, dict] = {}
    entry_by_instrument: dict[str, str] = {}
    node_part = 0
    edge_part = 0

    def flush_nodes():
        nonlocal node_part
        if not nodes:
            return
        _flush_df(nodes, GDIR / f"nodes_{node_part:05d}.parquet")
        node_part += 1

    def flush_edges():
        nonlocal edge_part
        if not edges:
            return
        _flush_df(edges, GDIR / f"edges_{edge_part:05d}.parquet")
        edge_part += 1

    # pass 1: law identity nodes
    for rec in corpus.itertuples(index=False):
        law_cid = str(getattr(rec, "law_cid", "") or "")
        instrument_id = str(getattr(rec, "instrument_id", "") or "")
        if getattr(rec, "record_type", "") == "law" and instrument_id and rec.entry_cid:
            entry_by_instrument.setdefault(instrument_id, rec.entry_cid)
        if not law_cid or law_cid in law_nodes:
            continue
        law_nodes[law_cid] = {
            "node_cid": law_cid,
            "node_type": "law",
            "entry_cid": "",
            "label": getattr(rec, "instrument_title", None) or instrument_id,
            "properties_json": _json(
                {
                    "instrument_id": instrument_id,
                    "instrument_title": str(getattr(rec, "instrument_title", "") or ""),
                    "jurisdiction": str(getattr(rec, "jurisdiction", "") or ""),
                    "language": str(getattr(rec, "language", "") or ""),
                    "law_cid": law_cid,
                }
            ),
            "schema_version": SCHEMA_VERSION,
        }
    nodes.extend(law_nodes.values())
    flush_nodes()
    log(f"law_nodes={len(law_nodes)} rss={rss_gib():.2f}G")

    # pass 2: doc nodes + structural/facet edges
    cid_by_idx = corpus["entry_cid"].tolist()
    for i, rec in enumerate(corpus.itertuples(index=False)):
        node_type = "law_entry" if rec.record_type == "law" else "article"
        title = getattr(rec, "title", None) or getattr(rec, "instrument_title", None) or rec.source_id
        nodes.append(
            {
                "node_cid": rec.entry_cid,
                "node_type": node_type,
                "entry_cid": rec.entry_cid,
                "label": title,
                "properties_json": _props_tuple(rec),
                "schema_version": SCHEMA_VERSION,
            }
        )
        src = rec.entry_cid
        row_map = rec._asdict() if hasattr(rec, "_asdict") else {}
        for kind, edge_type, col in FACET_FIELDS:
            value = str(row_map.get(col) or "").strip()
            if not value:
                continue
            fc = _facet_cid(kind, value)
            if fc not in seen_facets:
                seen_facets.add(fc)
                nodes.append(
                    {
                        "node_cid": fc,
                        "node_type": f"facet_{kind}",
                        "entry_cid": "",
                        "label": f"{kind}:{value}",
                        "properties_json": _json({"kind": kind, "value": value}),
                        "schema_version": SCHEMA_VERSION,
                    }
                )
            edges.append(_edge(src, edge_type, fc, "facet", 1.0, {"facet": kind, "value": value}))
        eli = str(row_map.get("eli") or "").strip()
        if eli:
            fc = _facet_cid("eli", eli)
            if fc not in seen_facets:
                seen_facets.add(fc)
                nodes.append(
                    {
                        "node_cid": fc,
                        "node_type": "facet_eli",
                        "entry_cid": "",
                        "label": f"eli:{eli}",
                        "properties_json": _json({"kind": "eli", "value": eli}),
                        "schema_version": SCHEMA_VERSION,
                    }
                )
            edges.append(_edge(src, "IDENTIFIED_BY_ELI", fc, "identifier", 1.0, {"eli": eli}))
        ident = str(row_map.get("official_identifier") or row_map.get("identifier") or "").strip()
        if ident and ident != eli:
            fc = _facet_cid("identifier", ident)
            if fc not in seen_facets:
                seen_facets.add(fc)
                nodes.append(
                    {
                        "node_cid": fc,
                        "node_type": "facet_identifier",
                        "entry_cid": "",
                        "label": f"identifier:{ident}",
                        "properties_json": _json({"kind": "identifier", "value": ident}),
                        "schema_version": SCHEMA_VERSION,
                    }
                )
            edges.append(_edge(src, "IDENTIFIED_BY", fc, "identifier", 1.0, {"identifier": ident}))
        law_cid = str(row_map.get("law_cid") or "")
        instrument_id = str(row_map.get("instrument_id") or "")
        if rec.record_type == "article":
            parent = entry_by_instrument.get(instrument_id) or law_cid
            if parent and parent != rec.entry_cid:
                edges.append(
                    _edge(
                        rec.entry_cid,
                        "ARTICLE_OF",
                        parent,
                        "structural",
                        1.0,
                        {"instrument_id": instrument_id, "article_number": row_map.get("article_number")},
                    )
                )
        elif law_cid and rec.entry_cid != law_cid:
            edges.append(
                _edge(
                    rec.entry_cid,
                    "HAS_INSTRUMENT",
                    law_cid,
                    "structural",
                    1.0,
                    {"instrument_id": instrument_id},
                )
            )
        if len(nodes) >= FLUSH:
            flush_nodes()
        if len(edges) >= FLUSH:
            flush_edges()
        if i and i % 100_000 == 0:
            log(f"structural @{i} node_parts={node_part} edge_parts={edge_part} rss={rss_gib():.2f}G mem={mem_available_gib():.2f}G")
    flush_nodes()
    flush_edges()
    log(f"structural done node_parts={node_part} edge_parts={edge_part} rss={rss_gib():.2f}G")

    # pass 3: BM25 neighbor edges from shards (no matched_terms — saves RAM)
    seen = 0
    for start_i, part in iter_neighbor_shards(spill):
        for offset, neigh in enumerate(part):
            i = start_i + offset
            if i >= N:
                break
            src = cid_by_idx[i]
            for item in neigh:
                j = int(item[0])
                score = float(item[1])
                tgt = cid_by_idx[j]
                edges.append(
                    _edge(
                        src,
                        "BM25_NEIGHBOR_OF",
                        tgt,
                        "bm25-okapi",
                        score,
                        {"k": 8, "neighbor_index": j},
                        matched_terms=None,
                    )
                )
        seen += len(part)
        del part
        if len(edges) >= FLUSH:
            flush_edges()
        if seen % 100_000 == 0:
            log(f"bm25_edges @{seen} edge_parts={edge_part} rss={rss_gib():.2f}G mem={mem_available_gib():.2f}G")
    flush_edges()
    del cid_by_idx
    gc.collect()
    log(f"bm25_edges done edge_parts={edge_part} rss={rss_gib():.2f}G")

    # KEEP parts on disk only — full edges DF OOMs at ~10M edges (BE lesson)
    node_files = sorted(GDIR.glob("nodes_*.parquet"))
    edge_files = sorted(GDIR.glob("edges_*.parquet"))
    stats = {
        "n_node_parts": len(node_files),
        "n_edge_parts": len(edge_files),
        "via": "estonia_stream_graph_parts_only",
        "adjacency": "deferred_empty_placeholder",
    }
    (GDIR / "parts_stats.json").write_text(json.dumps(stats, indent=2) + "\n")
    log(f"graph_parts ready nodes={len(node_files)} edges={len(edge_files)} rss={rss_gib():.2f}G")
    return {"stats": stats, "parts_only": True}


def main() -> int:

    LOG.parent.mkdir(parents=True, exist_ok=True)
    log_f = LOG.open("w", encoding="utf-8")

    class Tee:
        def write(self, d):
            sys.__stdout__.write(d); sys.__stdout__.flush()
            log_f.write(d); log_f.flush()
        def flush(self):
            sys.__stdout__.flush(); log_f.flush()

    sys.stdout = Tee(); sys.stderr = Tee()
    notes: list = []
    try:
        for req in (
            SPILL / "vectors.pkl",
            SPILL / "bm25_documents.parquet",
            SPILL / "bm25_postings.parquet",
            SPILL / "bm25_stats.pkl",
            CORPUS_CKPT,
        ):
            if not Path(req).exists():
                raise SystemExit(f"missing {req}")
        checkpoint("stream_graph_start", log=_log, notes=notes)
        _log(f"start mem={mem_available_gib():.2f}G")

        if not list(GDIR.glob("edges_*.parquet")):
            corpus = pd.read_parquet(CORPUS_CKPT)
            global N
            N = len(corpus)
            assert N > 0
            drop = [c for c in ("body", "body_sha256") if c in corpus.columns]
            if drop:
                corpus = corpus.drop(columns=drop)
            gc.collect()
            _log(f"corpus lean n={len(corpus)} rss={rss_gib():.2f}G")
            graph = build_graph_streaming(corpus, SPILL, log=_log)
            del corpus
            gc.collect()
            del graph
            gc.collect()
            checkpoint("graph_parts_ready", log=_log, notes=notes)
        else:
            _log("graph_parts present — skip build")
            import pyarrow.parquet as pq
            N = len(pq.read_metadata(CORPUS_CKPT).num_rows) if False else int(__import__("pandas").read_parquet(CORPUS_CKPT, columns=["entry_cid"]).shape[0])

        result = {
            "country": "estonia",
            "spill": str(SPILL),
            "graph_parts": str(GDIR),
            "n": N,
            "graph_stats": (graph.get("stats") if "graph" in dir() else None),
            "mem_end_gib": round(mem_available_gib(), 2),
            "rss_end_gib": round(rss_gib(), 2),
            "finished_utc": datetime.now(timezone.utc).isoformat(),
            "via": "estonia_stream_graph_parts_only",
            "source_revision": TIP,
            "phase": "graph_parts_ready",
        }
        # fix graph stats from last build
        try:
            result["graph_stats"] = json.loads((GDIR / "parts_stats.json").read_text())
        except Exception:
            pass
        (REPORTS / f"{SLUG}_graph_parts_{TIP_SHORT}.json").write_text(
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
