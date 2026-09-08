"""End-to-end build: normalize → BM25 → graph → vectors → package (no upload by default)."""

from __future__ import annotations

import json
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .bm25 import bm25_neighbors, build_index
from .catalog import get_country, indexable_countries, target_repo
from .graph import build_graph
from .normalize import build_corpus, load_source
from .package import package_release
from .auth import configure_hf
from .vectors import encode_corpus, embeddings_available, layout_stub_vectors, layout_vectors

ROOT = Path("/workspace/country-laws-ir")
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
    _log(f"build start {repo} -> {out} (upload={upload})")
    configure_hf()
    CACHE.mkdir(parents=True, exist_ok=True)
    REPORTS.mkdir(parents=True, exist_ok=True)
    laws, articles, source_meta = load_source(repo, CACHE)
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

    bm25 = build_index(corpus)
    _log(f"bm25 terms={bm25['stats']['n_terms']} postings={bm25['stats']['n_postings']}")
    _log(f"bm25 neighbors start n={len(corpus)} k={neighbor_k}")
    neighbors = bm25_neighbors(bm25, k=neighbor_k)
    _log("bm25 neighbors done")
    graph = build_graph(corpus, neighbors)
    _log(f"graph nodes={graph['stats']['n_nodes']} edges={graph['stats']['n_edges']}")

    vector_blocker = None
    if skip_vectors:
        vectors = layout_stub_vectors(corpus, reason="skip_vectors flag")
        vector_blocker = "skip_vectors"
    elif embeddings_available():
        try:
            ckpt = CACHE / "embeddings" / f"{country['slug']}.npy"
            _log(f"vectors encode start n={len(corpus)} checkpoint={ckpt}")
            embeddings = encode_corpus(corpus, device=device, checkpoint_path=str(ckpt))
            vectors = layout_vectors(corpus, embeddings)
            _log(f"vectors n={vectors['stats']['n_vectors']} shards={vectors['stats']['shard_count']}")
        except Exception as exc:
            vector_blocker = f"embedding_failed: {exc}"
            _log(f"vector embedding failed; writing stub ({exc})")
            vectors = layout_stub_vectors(corpus, reason=vector_blocker)
    else:
        vector_blocker = "sentence-transformers/torch unavailable"
        _log(f"vectors stub: {vector_blocker}")
        vectors = layout_stub_vectors(corpus, reason=vector_blocker)

    code_root = Path(__file__).resolve().parent.parent
    manifest = package_release(
        out,
        corpus,
        bm25,
        graph,
        vectors,
        source_meta,
        country,
        code_root,
        normalization_report=norm_report,
    )
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
