#!/usr/bin/env python3
"""Fill seed population from Wikidata P1082 and sort each country file.

Rows that already have a population are left as they are. Places Wikidata
does not know a population for stay blank and sort last.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path


def _bootstrap_pythonpath() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    repo_root_str = str(repo_root)
    if repo_root_str not in sys.path:
        sys.path.insert(0, repo_root_str)


_bootstrap_pythonpath()

from ipfs_datasets_py.processors.legal_scrapers.municipal.population import (  # noqa: E402
    apply_population,
    choose_population,
    sort_municipalities_first,
)
from ipfs_datasets_py.processors.legal_scrapers.municipal.seed_harvest import seed_root  # noqa: E402
from ipfs_datasets_py.processors.legal_scrapers.municipal.world_seed import (  # noqa: E402
    _cell,
    _qid,
    parts_root,
    sparql,
)

BATCH = 80
SKIP_PARTS = {"code_hosts", "code_docs"}


def seed_files(dest: Path) -> list[Path]:
    files = []
    for path in sorted(dest.rglob("*.jsonl")):
        if any(part in SKIP_PARTS for part in path.parts):
            continue
        if path.name in {"us_gnis_crosswalk.jsonl", "traverse_journal.jsonl"}:
            continue
        files.append(path)
    return files


def part_files(root: Path) -> list[Path]:
    if not root.is_dir():
        return []
    return sorted(path for path in root.glob("*.jsonl") if path.name != "progress.json")


def load_cache(path: Path) -> dict[str, str]:
    found: dict[str, str] = {}
    if not path.is_file():
        return found
    for line in path.open(encoding="utf-8"):
        if not line.strip():
            continue
        row = json.loads(line)
        found[str(row.get("qid") or "")] = str(row.get("population") or "")
    return found


def qids_missing(paths: list[Path], cache: dict[str, str]) -> list[str]:
    needed: set[str] = set()
    for path in paths:
        for line in path.open(encoding="utf-8"):
            if not line.strip():
                continue
            row = json.loads(line)
            qid = str(row.get("qid") or "")
            if not qid or qid in cache:
                continue
            if str(row.get("population") or "").strip():
                cache[qid] = str(row["population"]).strip()
                continue
            needed.add(qid)
    return sorted(needed)


def population_query(qids: list[str]) -> str:
    values = " ".join(f"wd:{qid}" for qid in qids)
    return f"""
SELECT ?item ?pop WHERE {{
  VALUES ?item {{ {values} }}
  ?item wdt:P1082 ?pop .
}}
"""


def _fetch_batch(batch: list[str], cache: dict[str, str], handle, *, delay: float, seen: list[int]) -> None:
    if not batch:
        return
    try:
        bindings = sparql(population_query(batch), attempts=3, timeout=60.0)
    except Exception as exc:
        if len(batch) > 10:
            print(f"SPLIT {len(batch)} {type(exc).__name__}", flush=True)
            _fetch_batch(batch[: len(batch) // 2], cache, handle, delay=delay, seen=seen)
            _fetch_batch(batch[len(batch) // 2 :], cache, handle, delay=delay, seen=seen)
            return
        print(f"FAIL {batch[0]} {type(exc).__name__}", flush=True)
        bindings = []
    grouped: dict[str, list[str]] = {qid: [] for qid in batch}
    for binding in bindings:
        qid = _qid(_cell(binding, "item"))
        pop = _cell(binding, "pop")
        if qid in grouped and pop:
            grouped[qid].append(pop)
    filled = 0
    for qid, values in grouped.items():
        chosen = choose_population(values)
        cache[qid] = chosen
        if chosen:
            filled += 1
        handle.write(json.dumps({"qid": qid, "population": chosen}) + "\n")
    handle.flush()
    seen[0] += len(batch)
    print(f"batch {seen[0]} size {len(batch)} with_population {filled}", flush=True)
    if delay:
        time.sleep(delay)


def fetch_populations(qids: list[str], cache_path: Path, *, delay: float) -> dict[str, str]:
    cache = load_cache(cache_path)
    pending = [qid for qid in qids if qid not in cache]
    print(f"population lookup {len(pending)} cached {len(cache)}", flush=True)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    seen = [0]
    with cache_path.open("a", encoding="utf-8") as handle:
        for start in range(0, len(pending), BATCH):
            _fetch_batch(pending[start : start + BATCH], cache, handle, delay=delay, seen=seen)
    return cache


def rewrite(path: Path, populations: dict[str, str], *, sort: bool) -> tuple[int, int]:
    rows = []
    filled = 0
    for line in path.open(encoding="utf-8"):
        if not line.strip():
            continue
        updated = apply_population(json.loads(line), populations)
        if str(updated.get("population") or "").strip():
            filled += 1
        rows.append(updated)
    if sort:
        rows = sort_municipalities_first(rows)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    temporary.replace(path)
    return len(rows), filled


def main() -> int:
    dest = seed_root()
    files = seed_files(dest)
    parts = part_files(parts_root())
    cache_path = parts_root() / "population.jsonl"
    cache = load_cache(cache_path)
    needed = qids_missing(files + parts, cache)
    # qids_missing mutates cache with populations already on rows; persist those too
    known = load_cache(cache_path)
    with cache_path.open("a", encoding="utf-8") as handle:
        for qid, population in cache.items():
            if qid not in known:
                handle.write(json.dumps({"qid": qid, "population": population}) + "\n")
    populations = fetch_populations(needed, cache_path, delay=0.2)
    populations.update(cache)
    seed_rows = seed_filled = 0
    for path in files:
        count, filled = rewrite(path, populations, sort=True)
        seed_rows += count
        seed_filled += filled
    for path in parts:
        rewrite(path, populations, sort=False)
    print(json.dumps({"seed_rows": seed_rows, "with_population": seed_filled, "files": len(files)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
