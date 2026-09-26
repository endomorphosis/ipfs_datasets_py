#!/usr/bin/env python3
"""Publish local country-laws-ir releases to justicedao/*."""

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

RELEASES = Path.home() / ".ipfs_datasets" / "country-laws-ir" / "releases"
LOG = Path.home() / ".ipfs_datasets" / "country-laws-ir" / "publish.jsonl"


def _log(event: dict) -> None:
    event = dict(event)
    event.setdefault("ts", datetime.now(timezone.utc).isoformat())
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False, default=str) + "\n")
    print(json.dumps(event, ensure_ascii=False, default=str), flush=True)


def main(argv: list[str] | None = None) -> int:
    from country_laws_ir.catalog import target_repo
    from country_laws_ir.upload import upload_release

    slugs = list(argv[1:] if argv and len(argv) > 1 else [])
    if not slugs:
        slugs = [
            p.name.removeprefix("ipfs_").removesuffix("_laws_ir")
            for p in sorted(RELEASES.glob("ipfs_*_laws_ir"))
            if (p / "manifest.json").is_file()
        ]
    failed = []
    for slug in slugs:
        local = RELEASES / f"ipfs_{slug}_laws_ir"
        repo = target_repo(slug)
        _log({"event": "start", "country": slug, "repo": repo})
        try:
            hub = upload_release(
                local,
                repo,
                commit_message=f"Add country-laws-ir GraphRAG pack for {slug}",
            )
            _log({"event": "uploaded", "country": slug, **hub})
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
