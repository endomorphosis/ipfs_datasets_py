#!/usr/bin/env python3
"""Build local country-laws IR releases and smoke-query BM25. No Hub upload."""
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
from country_laws_ir.query import Release

PT = ZoneInfo("America/Los_Angeles")
REPORT = ROOT / "reports" / "wave_results.jsonl"
QUERIES = {
    "estonia": "constitution",
    "singapore": "constitution",
    "israel": "constitution",
    "kuwait": "constitution",
    "uae": "federal law companies",
    "egypt": "constitution",
    "hungary": "alkotmany constitution",
    "thailand": "constitution",
    "ireland": "constitution",
    "luxembourg": "constitution",
    "netherlands": "grondwet constitution",
    "germany": "grundgesetz verfassung",
}


def now_pt() -> str:
    return datetime.now(PT).strftime("%Y-%m-%d %H:%M PT")


def record(event: dict) -> None:
    event = dict(event)
    event.setdefault("ts_utc", datetime.now(timezone.utc).isoformat())
    event.setdefault("ts_pt", now_pt())
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    with REPORT.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False, default=str) + "\n")
    print(json.dumps(event, ensure_ascii=False, default=str)[:2000], flush=True)


def smoke_bm25(out: Path, slug: str, top_k: int = 3) -> dict:
    q = QUERIES.get(slug, "constitution")
    rel = Release(out)
    hits = rel.bm25(q, top_k=top_k)
    titles = []
    for h in hits:
        titles.append(
            {
                "title": h.get("title") or h.get("instrument_title") or "",
                "score": h.get("score"),
                "record_type": h.get("record_type"),
                "entry_cid": h.get("entry_cid"),
            }
        )
    return {"query": q, "top": titles}


def build_one(slug: str) -> dict:
    out = ROOT / "releases" / f"ipfs_{slug}_laws_ir"
    print(f"\n===== BUILD {slug} -> {out} @ {now_pt()} =====", flush=True)
    result = build_country(slug, out=out, upload=False, device="cpu")
    try:
        smoke = smoke_bm25(out, slug)
    except Exception as exc:
        smoke = {"error": str(exc), "traceback": traceback.format_exc()}
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
        },
        "vector_blocker": result.get("vector_blocker"),
        "schema_version": result.get("schema_version"),
        "source_revision": result.get("source_revision"),
        "bm25_smoke": smoke,
    }
    record(payload)
    return payload


def main(argv: list[str]) -> int:
    slugs = argv or [
        "estonia",
        "singapore",
        "israel",
        "kuwait",
        "uae",
        "egypt",
        "hungary",
        "thailand",
    ]
    for slug in slugs:
        try:
            build_one(slug)
        except Exception as exc:
            record(
                {
                    "event": "wave_failed",
                    "country": slug,
                    "error": str(exc),
                    "traceback": traceback.format_exc(),
                }
            )
            print(f"FAILED {slug}: {exc}", flush=True)
            continue
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
