#!/usr/bin/env python3
"""Build a dedicated Oregon Administrative Rules dataset.

Outputs a focused dataset derived from the Oregon state scraper's
"Oregon Administrative Rules" code path.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any, Dict, List


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _bootstrap_pythonpath() -> None:
    root = _repo_root()
    root_str = str(root)
    if root_str not in sys.path:
        sys.path.insert(0, root_str)


async def _scrape_oar() -> List[Dict[str, Any]]:
    _bootstrap_pythonpath()
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.oregon import OregonScraper

    scraper = OregonScraper("OR", "Oregon")
    seed_url = "https://secure.sos.state.or.us/oard/displayChapterRules.action?selectedChapter=137"
    statutes = await scraper.scrape_code("Oregon Administrative Rules", seed_url)
    return [item.to_dict() for item in statutes]


def _write_json(records: List[Dict[str, Any]], output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / "oregon_administrative_rules.json"
    payload = {
        "dataset": "oregon_administrative_rules",
        "state": "OR",
        "record_count": len(records),
        "records": records,
    }
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return out_path


def _write_jsonl(records: List[Dict[str, Any]], output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / "oregon_administrative_rules.jsonl"
    with out_path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    return out_path


def _write_parquet(records: List[Dict[str, Any]], output_dir: Path) -> Path | None:
    try:
        import pyarrow as pa  # type: ignore
        import pyarrow.parquet as pq  # type: ignore
    except Exception:
        return None

    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / "oregon_administrative_rules.parquet"
    table = pa.Table.from_pylist(records)
    pq.write_table(table, out_path)
    return out_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Build Oregon Administrative Rules dataset")
    parser.add_argument(
        "--output-dir",
        default=str(_repo_root() / "data" / "state_administrative_rules" / "OR" / "parsed"),
        help="Directory where dataset files will be written",
    )
    args = parser.parse_args()

    output_dir = Path(args.output_dir).expanduser().resolve()

    records = asyncio.run(_scrape_oar())
    json_path = _write_json(records, output_dir)
    jsonl_path = _write_jsonl(records, output_dir)
    parquet_path = _write_parquet(records, output_dir)

    result = {
        "status": "success",
        "record_count": len(records),
        "json": str(json_path),
        "jsonl": str(jsonl_path),
        "parquet": str(parquet_path) if parquet_path else None,
        "note": None if parquet_path else "pyarrow unavailable; skipped parquet",
    }
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
