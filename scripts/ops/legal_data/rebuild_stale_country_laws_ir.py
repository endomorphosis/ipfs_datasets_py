#!/usr/bin/env python3
"""Rebuild stale country-laws GraphRAG IR, reusing Hub embeddings by entry_cid."""

from __future__ import annotations

import json
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SCRAPERS = ROOT / "ipfs_datasets_py" / "processors" / "legal_scrapers"
sys.path.insert(0, str(SCRAPERS))
sys.path.insert(0, str(ROOT))

CACHE = Path.home() / ".ipfs_datasets" / "country-laws-ir" / "cache" / "hub-ir"
LOG = Path.home() / ".ipfs_datasets" / "country-laws-ir" / "stale_rebuild.jsonl"


def _log(event: dict) -> None:
    event = dict(event)
    event.setdefault("ts", datetime.now(timezone.utc).isoformat())
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False, default=str) + "\n")
    print(json.dumps(event, ensure_ascii=False, default=str), flush=True)


def fetch_prior(slug: str) -> Path:
    from huggingface_hub import snapshot_download

    from country_laws_ir.auth import operator_token, public_token
    from country_laws_ir.catalog import target_repo

    dest = CACHE / slug
    dest.mkdir(parents=True, exist_ok=True)
    snapshot_download(
        repo_id=target_repo(slug),
        repo_type="dataset",
        local_dir=str(dest),
        allow_patterns=[
            "manifest.json",
            "data/vectors/**",
            "data/corpus/**",
            "indexes/vector_chunks.parquet",
        ],
        token=operator_token() or public_token(),
    )
    return dest


def main(argv: list[str] | None = None) -> int:
    from country_laws_ir.build import build_country

    slugs = list(argv[1:] if argv and len(argv) > 1 else [])
    if not slugs:
        raise SystemExit("usage: rebuild_stale_country_laws_ir.py <slug> [...]")
    failed = []
    for slug in slugs:
        _log({"event": "start", "country": slug})
        try:
            prior = fetch_prior(slug)
            result = build_country(
                slug,
                prior_dir=prior,
                skip_vectors=False,
                mode="auto",
                upload=True,
            )
            incremental = result.get("incremental") or {}
            delta = incremental.get("delta") or {}
            vectors = incremental.get("vectors") or {}
            _log(
                {
                    "event": "skipped" if result.get("skipped") else "rebuilt",
                    "country": slug,
                    "out": result.get("out"),
                    "hub": result.get("hub"),
                    "kind": incremental.get("kind"),
                    "n_added": delta.get("n_added"),
                    "n_removed": delta.get("n_removed"),
                    "n_unchanged": delta.get("n_unchanged"),
                    "vector_status": vectors.get("status"),
                    "counts": result.get("counts"),
                }
            )
        except Exception as exc:
            _log(
                {
                    "event": "failed",
                    "country": slug,
                    "error": str(exc),
                    "traceback": traceback.format_exc(),
                }
            )
            failed.append(slug)
    _log({"event": "batch_done", "n": len(slugs), "failed": failed})
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
