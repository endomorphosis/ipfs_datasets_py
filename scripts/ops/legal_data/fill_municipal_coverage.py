#!/usr/bin/env python3
"""Fill mapped countries that still have no municipal rows.

Asks Wikidata for places inside each missing country whose class name is a
district, parish, municipality, village, town, or the same kind of word.
The class is not downloaded worldwide.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


def _bootstrap_pythonpath() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    repo_root_str = str(repo_root)
    if repo_root_str not in sys.path:
        sys.path.insert(0, repo_root_str)


_bootstrap_pythonpath()

from ipfs_datasets_py.processors.legal_scrapers.municipal.seed_harvest import seed_root  # noqa: E402
from ipfs_datasets_py.processors.legal_scrapers.municipal.traverse import (  # noqa: E402
    coverage_query,
    country_qids,
    rows_from_coverage_bindings,
)
from ipfs_datasets_py.processors.legal_scrapers.municipal.world_seed import (  # noqa: E402
    _write_jsonl,
    finalize_world,
    parts_root,
    sparql,
)


def missing_isos(dest: Path) -> list[str]:
    mapping_path = Path(__file__).resolve().parents[3] / "ipfs_datasets_py/processors/legal_scrapers/regions/mapping.py"
    spec = importlib.util.spec_from_file_location("region_mapping", mapping_path)
    mapping = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mapping)
    counts: dict[str, int] = {}
    summary_path = dest / "world_summary.json"
    if summary_path.is_file():
        counts = json.loads(summary_path.read_text(encoding="utf-8")).get("by_country") or {}
    return sorted(iso for iso in mapping.COUNTRY_TO_REGION if iso != "EU" and int(counts.get(iso) or 0) == 0)


# Country-specific classes whose items are not linked with P17 to that country.
EXPLICIT_CLASSES: tuple[tuple[str, str, str], ...] = (
    ("HK", "Q50256", "district"),
    ("AI", "Q16678127", "district"),
    ("TC", "Q2487479", "district"),
    ("IN", "Q6958514", "municipality"),
)


def explicit_query(class_qid: str) -> str:
    return f"""
SELECT ?item ?en ?site ?gnis ?geonames ?pop WHERE {{
  ?item wdt:P31 wd:{class_qid} .
  FILTER NOT EXISTS {{ ?item wdt:P576 ?dissolved }}
  OPTIONAL {{ ?item rdfs:label ?en FILTER(LANG(?en) = "en") }}
  OPTIONAL {{ ?item wdt:P856 ?site }}
  OPTIONAL {{ ?item wdt:P590 ?gnis }}
  OPTIONAL {{ ?item wdt:P1566 ?geonames }}
  OPTIONAL {{ ?item wdt:P1082 ?pop }}
}}
LIMIT 2000
"""


def fill_explicit(dest: Path, part_dir: Path) -> dict[str, int]:
    written: dict[str, int] = {}
    for iso, class_qid, level in EXPLICIT_CLASSES:
        try:
            bindings = sparql(explicit_query(class_qid), attempts=2, timeout=70.0)
        except Exception as exc:
            print(f"FAIL explicit {iso} {class_qid} {type(exc).__name__}: {exc}", flush=True)
            continue
        for binding in bindings:
            binding.setdefault("class", {"value": f"http://www.wikidata.org/entity/{class_qid}"})
            binding.setdefault("classLabel", {"value": level})
        rows = rows_from_coverage_bindings(bindings, iso)
        for row in rows:
            row["admin_level"] = level
            row["wikidata_class"] = class_qid
        path = part_dir / f"coverage_{iso}_{class_qid}.jsonl"
        count = _write_jsonl(path, rows)
        written[f"{iso}:{class_qid}"] = count
        print(f"EXPLICIT {iso} {class_qid} {level} rows={count}", flush=True)
    return written


def fill_missing(dest: Path, isos: list[str] | None = None) -> dict[str, int]:
    targets = isos or missing_isos(dest)
    print(f"missing countries {len(targets)} {' '.join(targets)}", flush=True)
    qids = country_qids(targets)
    part_dir = parts_root()
    part_dir.mkdir(parents=True, exist_ok=True)
    written = fill_explicit(dest, part_dir)
    for index, iso in enumerate(targets, start=1):
        country = qids.get(iso)
        if not country:
            print(f"NOQID {index}/{len(targets)} {iso}", flush=True)
            continue
        try:
            bindings = sparql(coverage_query(country), attempts=2, timeout=70.0)
        except Exception as exc:
            print(f"FAIL {index}/{len(targets)} {iso} {type(exc).__name__}: {exc}", flush=True)
            continue
        rows = rows_from_coverage_bindings(bindings, iso)
        path = part_dir / f"coverage_{iso}.jsonl"
        count = _write_jsonl(path, rows)
        written[iso] = count
        print(f"OK {index}/{len(targets)} {iso} rows={count}", flush=True)
    if any(written.values()):
        summary = finalize_world(dest, part_dir)
        print(json.dumps({"countries": summary.get("countries"), "rows": summary.get("rows"), "added": written}, indent=2))
    else:
        print(json.dumps({"added": written}, indent=2))
    return written


def main() -> int:
    fill_missing(seed_root(), [iso.upper() for iso in sys.argv[1:]] or None)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
