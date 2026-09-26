#!/usr/bin/env python3
"""Build country-laws GraphRAG IR for Hub sources that lack a justicedao release."""

from __future__ import annotations

import json
import os
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SCRAPERS = ROOT / "ipfs_datasets_py" / "processors" / "legal_scrapers"
sys.path.insert(0, str(SCRAPERS))
sys.path.insert(0, str(ROOT))

# Prefer no-underscore Hub ids when both spellings exist.
SKIP_DUPLICATE_SLUGS = {
    "dominican_republic",
    "el_salvador",
    "north_korea",
    "papua_new_guinea",
    "san_marino",
    "trinidad_and_tobago",
}
EXCLUDED = {"belgium", "portugal", "lithuania", "ghana"}

# Smallest first; croatia (~30k law-level units) last.
DEFAULT_GAPS = [
    "afghanistan",
    "sudan",
    "libya",
    "iraq",
    "southsudan",
    "northkorea",
    "eritrea",
    "palau",
    "lebanon",
    "papuanewguinea",
    "fiji",
    "fsm",
    "monaco",
    "croatia",
]


def _log(path: Path, event: dict) -> None:
    event = dict(event)
    event.setdefault("ts", datetime.now(timezone.utc).isoformat())
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False, default=str) + "\n")
    print(json.dumps(event, ensure_ascii=False, default=str), flush=True)


def main(argv: list[str] | None = None) -> int:
    from country_laws_ir.build import build_country

    slugs = list(argv[1:] if argv and len(argv) > 1 else DEFAULT_GAPS)
    slugs = [s for s in slugs if s not in SKIP_DUPLICATE_SLUGS and s not in EXCLUDED]
    log_path = Path(
        os.environ.get(
            "COUNTRY_LAWS_IR_GAP_LOG",
            str(Path.home() / ".ipfs_datasets" / "country-laws-ir" / "gap_build.jsonl"),
        )
    )
    results = []
    for slug in slugs:
        _log(log_path, {"event": "start", "country": slug})
        try:
            result = build_country(slug, upload=False, skip_vectors=True, mode="auto")
            row = {
                "event": "skipped" if result.get("skipped") else "built",
                "country": slug,
                "out": result.get("out"),
                "source_revision": result.get("source_revision"),
                "target_hub_id": result.get("target_hub_id"),
                "counts": result.get("counts"),
                "incremental": result.get("incremental"),
            }
            _log(log_path, row)
            results.append(row)
        except Exception as exc:
            _log(
                log_path,
                {
                    "event": "failed",
                    "country": slug,
                    "error": str(exc),
                    "traceback": traceback.format_exc(),
                },
            )
            results.append({"event": "failed", "country": slug, "error": str(exc)})
            continue
    failed = [r for r in results if r.get("event") == "failed"]
    _log(
        log_path,
        {
            "event": "batch_done",
            "n": len(results),
            "built": sum(1 for r in results if r.get("event") == "built"),
            "skipped": sum(1 for r in results if r.get("event") == "skipped"),
            "failed": len(failed),
            "failed_slugs": [r["country"] for r in failed],
        },
    )
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
