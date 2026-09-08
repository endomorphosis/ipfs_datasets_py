"""End-to-end build: normalize → BM25 → graph → vectors → v3 package → optional upload."""

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
from .vectors import encode_corpus, layout_vectors

ROOT = Path("/workspace/country-laws-ir")
CACHE = ROOT / "cache"
RELEASES = ROOT / "releases"
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
    upload: bool = True,
    device: str = "cpu",
    neighbor_k: int = 8,
) -> dict[str, Any]:
    country = get_country(source)
    if not country.get("indexable", True):
        raise RuntimeError(f"{country['repo']} is excluded: {country.get('skip_reason')}")
    repo = country["repo"]
    out = Path(out) if out else RELEASES / f"ipfs_{country['slug']}_laws-ir"
    _log(f"build start {repo} -> {out}")
    configure_hf()
    CACHE.mkdir(parents=True, exist_ok=True)
    laws, articles, source_meta = load_source(repo, CACHE)
    _log(f"source loaded laws={source_meta['n_laws_source']} articles={source_meta['n_articles_source']} rev={source_meta['source_revision']}")
    corpus = build_corpus(laws, articles, source_meta)
    n_dropped = int(getattr(corpus, "attrs", {}).get("n_duplicate_cid_dropped", 0) or 0)
    _log(
        f"normalized docs={len(corpus)} unique_cids={corpus['entry_cid'].nunique()} "
        f"dropped_duplicate_cid={n_dropped}"
    )
    bm25 = build_index(corpus)
    _log(f"bm25 terms={bm25['stats']['n_terms']} postings={bm25['stats']['n_postings']}")
    _log(f"bm25 neighbors start n={len(corpus)} k={neighbor_k}")
    neighbors = bm25_neighbors(bm25, k=neighbor_k)
    _log("bm25 neighbors done")
    graph = build_graph(corpus, neighbors)
    _log(f"graph nodes={graph['stats']['n_nodes']} edges={graph['stats']['n_edges']}")
    embeddings = encode_corpus(corpus, device=device)
    vectors = layout_vectors(corpus, embeddings)
    _log(f"vectors n={vectors['stats']['n_vectors']} shards={vectors['stats']['shard_count']}")
    code_root = Path(__file__).resolve().parent.parent
    manifest = package_release(out, corpus, bm25, graph, vectors, source_meta, country, code_root)
    _log(f"packaged {out}")
    result = {
        "country": country["slug"],
        "source": repo,
        "source_revision": source_meta["source_revision"],
        "out": str(out),
        "counts": {**manifest["counts"], "n_duplicate_cid_dropped": n_dropped},
        "schema_mapping": manifest["schema_mapping"],
    }
    if upload:
        from .upload import upload_release

        hub = upload_release(out, target_repo(country["slug"]))
        result["hub"] = hub
        _log(f"uploaded {hub['url']} rev={hub['revision']}")
        record_progress({"event": "uploaded", **result, "hub": hub})
    else:
        record_progress({"event": "built_local", **result})
    return result


def batch(
    slugs: list[str] | None = None,
    upload: bool = True,
    skip_done: bool = True,
) -> list[dict[str, Any]]:
    done = set()
    if skip_done and PROGRESS.exists():
        for line in PROGRESS.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            rec = json.loads(line)
            if rec.get("event") == "uploaded" and rec.get("country"):
                done.add(rec["country"])
    targets = slugs or [c["slug"] for c in indexable_countries()]
    # Malta first, then remaining in catalog order
    if "malta" in targets:
        targets = ["malta"] + [s for s in targets if s != "malta"]
    results = []
    for slug in targets:
        if skip_done and slug in done:
            _log(f"skip already uploaded {slug}")
            continue
        try:
            result = build_country(slug, upload=upload)
            results.append(result)
            # Keep Malta local as the pilot; drop other release dirs after a successful Hub push.
            if upload and slug != "malta":
                outp = Path(result["out"])
                if outp.exists() and outp.resolve().is_relative_to(RELEASES.resolve()):
                    import shutil
                    shutil.rmtree(outp)
                    _log(f"cleaned local release {outp}")
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
