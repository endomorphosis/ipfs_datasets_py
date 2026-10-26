#!/usr/bin/env python3
"""Build remaining indexable country-laws IR releases in size order. No Hub upload."""
from __future__ import annotations
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))

import json
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path("/workspace/country-laws-ir")
sys.path.insert(0, str(ROOT))

from country_laws_ir.build import build_country
from country_laws_ir.catalog import indexable_countries
from country_laws_ir.query import Release

PT = ZoneInfo("America/Los_Angeles")
REPORT = ROOT / "reports" / "wave_results.jsonl"
SIZES = ROOT / "reports" / "corpus_sizes.jsonl"
SKIP = {"malta", "belgium", "portugal", "lithuania", "bulgaria", "cyprus", "italy", "romania", "slovenia", "iceland", "morocco", "thailand", "kuwait", "hungary", "uae", "egypt", "germany", "estonia", "singapore", "ireland", "israel", "bangladesh", "nigeria", "saudiarabia", "pakistan", "southafrica", "greece", "philippines", "kenya", "malaysia", "czechia", "sweden", "switzerland", "slovakia", "netherlands", "qatar", "austria", "chile", "china", "vietnam", "latvia"}


def now_pt() -> str:
    return datetime.now(PT).strftime("%Y-%m-%d %H:%M PT")


def record(event: dict) -> None:
    event = dict(event)
    event.setdefault("ts_utc", datetime.now(timezone.utc).isoformat())
    event.setdefault("ts_pt", now_pt())
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    with REPORT.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False, default=str) + "\n")
    print(json.dumps({k: event[k] for k in event if k != "traceback"}, ensure_ascii=False, default=str)[:2500], flush=True)


def completed_ok() -> set[str]:
    done = set()
    if not REPORT.exists():
        return done
    for line in REPORT.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        rec = json.loads(line)
        if rec.get("event") != "wave_built":
            continue
        slug = rec.get("country")
        counts = rec.get("counts") or {}
        blocker = rec.get("vector_blocker")
        # require real vectors
        if blocker:
            continue
        if int(counts.get("vector_rows") or 0) <= 0:
            continue
        # estonia thin build is not ok
        if slug == "estonia" and int(counts.get("corpus_rows") or 0) < 100:
            continue
        out = Path(rec.get("out") or "")
        if out.is_dir() and (out / "manifest.json").exists():
            # confirm vector status embedded
            try:
                man = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
                if (man.get("vector") or {}).get("status") != "embedded":
                    continue
            except Exception:
                continue
            done.add(slug)
    return done


def smoke_bm25(out: Path, slug: str, top_k: int = 3) -> dict:
    rel = Release(out)
    # try a few queries until we get hits
    candidates = [
        "constitution",
        "grundgesetz",
        "grondwet",
        "company",
        "article",
        "law",
        "act",
        "1",
    ]
    # peek frequent terms
    try:
        import pandas as pd

        posts = pd.concat(
            [pd.read_parquet(p) for p in sorted((out / "data/bm25/postings").glob("*.parquet"))],
            ignore_index=True,
        )
        longish = [
            t
            for t in posts.sort_values("corpus_frequency", ascending=False)["term"].tolist()
            if isinstance(t, str) and len(t) >= 4
        ][:8]
        candidates = longish + candidates
    except Exception:
        pass
    for q in candidates:
        hits = rel.bm25(str(q), top_k=top_k)
        if hits:
            return {
                "query": str(q),
                "top": [
                    {
                        "title": h.get("title") or "",
                        "score": h.get("score"),
                        "record_type": h.get("record_type"),
                        "entry_cid": h.get("entry_cid"),
                    }
                    for h in hits
                ],
            }
    return {"query": candidates[0] if candidates else "", "top": []}


def size_order(slugs: list[str]) -> list[str]:
    est = {}
    if SIZES.exists():
        for line in SIZES.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            rec = json.loads(line)
            if "est_n" in rec and "slug" in rec:
                est[rec["slug"]] = int(rec["est_n"])
    return sorted(slugs, key=lambda s: (est.get(s, 10**12), s))


def build_one(slug: str) -> dict:
    out = ROOT / "releases" / f"ipfs_{slug}_laws_ir"
    # wipe stale thin estonia / stub vectors
    print(f"\n===== BUILD {slug} -> {out} @ {now_pt()} =====", flush=True)
    result = build_country(slug, out=out, upload=False, device="cpu", skip_vectors=False)
    if result.get("vector_blocker"):
        raise RuntimeError(f"vector_blocker={result['vector_blocker']}")
    smoke = smoke_bm25(out, slug)
    payload = {
        "event": "wave_built",
        "country": slug,
        "out": str(out),
        "counts": result.get("counts"),
        "normalization": {
            "unit": result.get("normalization", {}).get("unit"),
            "n_out": result.get("normalization", {}).get("n_out"),
            "n_laws_in": result.get("normalization", {}).get("n_laws_in"),
            "n_articles_in": result.get("normalization", {}).get("n_articles_in"),
            "drops": result.get("normalization", {}).get("drops"),
            "quality_flags": result.get("normalization", {}).get("quality_flags"),
            "schema_surprises": result.get("normalization", {}).get("schema_surprises"),
            "sparse_article_fallback": result.get("normalization", {}).get("sparse_article_fallback"),
            "article_law_coverage": result.get("normalization", {}).get("article_law_coverage"),
        },
        "vector_blocker": result.get("vector_blocker"),
        "schema_version": result.get("schema_version"),
        "source_revision": result.get("source_revision"),
        "bm25_smoke": smoke,
    }
    record(payload)
    return payload


def main(argv: list[str]) -> int:
    force = set()
    args = []
    for a in argv:
        if a == "--force-estonia":
            force.add("estonia")
        else:
            args.append(a)
    done = completed_ok()
    if "estonia" in force:
        done.discard("estonia")
    if args:
        targets = [s for s in args if s not in SKIP]
    else:
        targets = [c["slug"] for c in indexable_countries() if c["slug"] not in SKIP and c["slug"] not in done]
        targets = size_order(targets)
    print(f"queue ({len(targets)}): {targets}", flush=True)
    for slug in targets:
        if slug in done and slug not in force:
            print(f"skip done {slug}", flush=True)
            continue
        try:
            # remove stale embedding checkpoint if rebuilding estonia after thin run
            if slug == "estonia":
                ck = ROOT / "cache" / "embeddings" / "estonia.npy"
                meta = ROOT / "cache" / "embeddings" / "estonia.json"
                for p in (ck, meta):
                    if p.exists():
                        p.unlink()
                        print(f"removed stale {p}", flush=True)
            build_one(slug)
            done.add(slug)
        except Exception as exc:
            record({"event": "wave_failed", "country": slug, "error": str(exc), "traceback": traceback.format_exc()})
            print(f"FAILED {slug}: {exc}", flush=True)
            continue
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
