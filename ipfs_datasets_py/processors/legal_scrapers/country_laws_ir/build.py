"""End-to-end build: normalize → BM25 → graph → vectors → package (no upload by default)."""

from __future__ import annotations

import os

import json

import pandas as pd
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .bm25 import bm25_neighbors, build_index
from .mem import MemAbort, checkpoint, log_mem
from .spill import (
    SQLITE_THRESHOLD,
    build_bm25_tf_spill,
    build_graph_from_neighbor_shards,
    neighbors_via_sqlite,
    should_use_sqlite,
    spill_dir_for,
    spill_pickle,
)
from .package import package_from_spill, package_release
from .catalog import get_country, indexable_countries, target_repo
from .graph import build_graph
from .normalize import build_corpus, load_source
from .auth import configure_hf
from .vectors import encode_corpus, embeddings_available, layout_stub_vectors, layout_vectors

ROOT = Path(os.environ.get("COUNTRY_LAWS_IR_ROOT", str(Path.home() / ".ipfs_datasets" / "country-laws-ir")))
CACHE = ROOT / "cache"
RELEASES = ROOT / "releases"
REPORTS = ROOT / "reports"
PROGRESS = ROOT / "progress.jsonl"


def _log(msg: str) -> None:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    print(f"[{ts}] {msg}", flush=True)


def record_progress(event: dict[str, Any]) -> None:
    event = dict(event)
    event.setdefault("ts", datetime.now(timezone.utc).isoformat())
    with PROGRESS.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")


def build_country(
    source: str,
    out: Path | None = None,
    upload: bool = False,
    device: str = "cpu",
    neighbor_k: int = 8,
    skip_vectors: bool = False,
) -> dict[str, Any]:
    country = get_country(source)
    if not country.get("indexable", True):
        raise RuntimeError(f"{country['repo']} is excluded: {country.get('skip_reason')}")
    repo = country["repo"]
    out = Path(out) if out else RELEASES / f"ipfs_{country['slug']}_laws_ir"
    local_dir = country.get("local_source_dir") or (
        str(Path(source).resolve())
        if Path(source).is_dir()
        and (
            (Path(source) / "data" / "laws.parquet").is_file()
            or (Path(source) / "laws.parquet").is_file()
        )
        else None
    )
    _log(f"build start {repo} -> {out} (upload={upload}) local={local_dir}")
    configure_hf()
    CACHE.mkdir(parents=True, exist_ok=True)
    REPORTS.mkdir(parents=True, exist_ok=True)
    laws, articles, source_meta = load_source(local_dir or repo, CACHE)
    _log(
        f"source loaded laws={source_meta['n_laws_source']} "
        f"articles={source_meta['n_articles_source']} rev={source_meta['source_revision']}"
    )
    corpus, norm_report = build_corpus(laws, articles, source_meta)
    report_path = REPORTS / f"{country['slug']}_normalization.json"
    report_path.write_text(json.dumps(norm_report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (REPORTS / "normalization.json").write_text(
        json.dumps(norm_report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    _log(
        f"normalized docs={len(corpus)} unit={norm_report['unit']} "
        f"dropped={norm_report['n_dropped_total']} report={report_path}"
    )
    if corpus.empty:
        raise RuntimeError("Normalized corpus is empty; refusing to package")

    import gc

    n_docs = len(corpus)
    spill = spill_dir_for(country["slug"], CACHE)
    spill.mkdir(parents=True, exist_ok=True)
    corpus_ckpt = CACHE / f"{country['slug']}_corpus.parquet"
    corpus.to_parquet(corpus_ckpt, index=False)
    checkpoint("after_normalize", log=_log)

    vector_blocker = None
    if skip_vectors:
        vectors = layout_stub_vectors(corpus, reason="skip_vectors flag")
        vector_blocker = "skip_vectors"
        spill_pickle(spill / "vectors.pkl", vectors)
        del vectors
        gc.collect()
    elif embeddings_available():
        try:
            ckpt = CACHE / "embeddings" / f"{country['slug']}.npy"
            _log(f"vectors encode start n={n_docs} checkpoint={ckpt}")
            embeddings = encode_corpus(corpus, device=device, checkpoint_path=str(ckpt))
            vectors = layout_vectors(corpus, embeddings)
            _log(f"vectors n={vectors['stats']['n_vectors']} shards={vectors['stats']['shard_count']}")
            spill_pickle(spill / "vectors.pkl", vectors)
            del embeddings, vectors
            gc.collect()
            checkpoint("vectors_spilled", log=_log)
        except Exception as exc:
            vector_blocker = f"embedding_failed: {exc}"
            _log(f"vector embedding failed; writing stub ({exc})")
            vectors = layout_stub_vectors(corpus, reason=vector_blocker)
            spill_pickle(spill / "vectors.pkl", vectors)
            del vectors
            gc.collect()
    else:
        vector_blocker = "sentence-transformers/torch unavailable"
        _log(f"vectors stub: {vector_blocker}")
        vectors = layout_stub_vectors(corpus, reason=vector_blocker)
        spill_pickle(spill / "vectors.pkl", vectors)
        del vectors
        gc.collect()

    use_sqlite = should_use_sqlite(n_docs)
    neighbor_via = "stock"
    if use_sqlite:
        _log(f"sqlite neighbors path n={n_docs} (>= {SQLITE_THRESHOLD}) spill={spill}")
        # Free corpus body for neighbor stream — reload later for graph
        del corpus
        gc.collect()
        neighbors_via_sqlite(corpus_ckpt, spill, n_docs, k=neighbor_k, log=_log)
        neighbor_via = "sqlite_fts"
        bm25_info = build_bm25_tf_spill(corpus_ckpt, spill, n_docs, log=_log)
        corpus = pd.read_parquet(corpus_ckpt)
        graph = build_graph_from_neighbor_shards(corpus, spill, log=_log)
        spill_pickle(spill / "graph.pkl", graph)
        del graph, corpus
        gc.collect()
        checkpoint("graph_spilled", log=_log)
        code_root = Path(__file__).resolve().parent.parent
        manifest = package_from_spill(
            out, spill, corpus_ckpt, source_meta, country, code_root,
            normalization_report=norm_report, expected_rows=n_docs,
        )
        _log(f"packaged sequential via={neighbor_via} {out}")
    else:
        bm25 = build_index(corpus)
        _log(f"bm25 terms={bm25['stats']['n_terms']} postings={bm25['stats']['n_postings']}")
        _log(f"bm25 neighbors start n={n_docs} k={neighbor_k}")
        neighbors = bm25_neighbors(bm25, k=neighbor_k)
        _log("bm25 neighbors done")
        graph = build_graph(corpus, neighbors)
        del neighbors
        gc.collect()
        _log(f"graph nodes={graph['stats']['n_nodes']} edges={graph['stats']['n_edges']}")
        with open(spill / "vectors.pkl", "rb") as _vf:
            import pickle as _pickle
            vectors = _pickle.load(_vf)
        code_root = Path(__file__).resolve().parent.parent
        manifest = package_release(
            out, corpus, bm25, graph, vectors, source_meta, country, code_root,
            normalization_report=norm_report,
        )
        del corpus, bm25, graph, vectors
        gc.collect()
    _log(f"packaged {out}")
    result = {
        "country": country["slug"],
        "source": repo,
        "source_revision": source_meta["source_revision"],
        "out": str(out),
        "target_hub_id": target_repo(country["slug"]),
        "counts": manifest["counts"],
        "normalization": norm_report,
        "vector_blocker": vector_blocker,
        "neighbor_via": neighbor_via,
        "schema_version": manifest["schema_version"],
    }
    if upload:
        from .upload import upload_release

        hub = upload_release(out, target_repo(country["slug"]))
        result["hub"] = hub
        _log(f"uploaded {hub['url']} rev={hub['revision']}")
        record_progress({"event": "uploaded", **result})
    else:
        record_progress({"event": "built_local", **{k: v for k, v in result.items() if k != "normalization"}})
    return result


def batch(
    slugs: list[str] | None = None,
    upload: bool = False,
    skip_done: bool = True,
) -> list[dict[str, Any]]:
    done = set()
    if skip_done and PROGRESS.exists():
        for line in PROGRESS.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            rec = json.loads(line)
            if rec.get("event") in {"uploaded", "built_local"} and rec.get("country"):
                done.add(rec["country"])
    targets = slugs or [c["slug"] for c in indexable_countries()]
    if "malta" in targets:
        targets = ["malta"] + [s for s in targets if s != "malta"]
    results = []
    for slug in targets:
        if skip_done and slug in done:
            _log(f"skip already done {slug}")
            continue
        try:
            results.append(build_country(slug, upload=upload))
        except Exception as exc:
            _log(f"FAILED {slug}: {exc}")
            record_progress(
                {
                    "event": "failed",
                    "country": slug,
                    "error": str(exc),
                    "traceback": traceback.format_exc(),
                }
            )
            continue
    return results
