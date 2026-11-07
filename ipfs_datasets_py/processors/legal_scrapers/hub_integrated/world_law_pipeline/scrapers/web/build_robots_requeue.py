#!/usr/bin/env python3
"""Build robots requeue lists (2026-11-01 IGNORE_ROBOTS policy): places whose latest outcome was robots-blocked,
had robots-blocked docs/seeds, or were skipped for Crawl-delay > 30 s. Writes staging/web/_requeue/lists/<lane>.jsonl."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_WORLD = _ipfs_Path(_ipfs_os.environ.get("WORLD_LAW_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "world_law")))
_TESSDATA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_TESSDATA", str(_ipfs_Path.home() / ".ipfs_datasets" / "tessdata")))
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import json, collections
from pathlib import Path
WEB = Path((_wl_os.environ.get("WORLD_LAW_ROOT", str(_WORLD)) + "/staging/web")); OUT = WEB / "_requeue" / "lists"
ROB = {"robots_disallowed", "docs_robots_disallowed", "robots_disallowed_partial", "crawl_delay_too_long"}


def is_robot(r):
    ev = r.get("events") or {}
    return r.get("status") in ROB or ev.get("err_robots_disallowed", 0) > 0 or ev.get("err_crawl_delay_too_long", 0) > 0


summary = {}
for lane in ("IT", "DE", "FR", "CA", "_missing"):
    last = {}
    for l in (WEB / lane / "_state" / "place_results.jsonl").open(encoding="utf-8"):
        try:
            r = json.loads(l)
        except ValueError:
            continue
        last[r["place_id"]] = r
    rows = {pid: {"place_id": pid, "status": r.get("status"), "src": "place_results"} for pid, r in last.items() if is_robot(r)}
    if lane == "_missing":
        for l in (WEB / lane / "_state" / "archive_queue.jsonl").open():
            r = json.loads(l)
            if "robots" in (r.get("status") or ""):
                rows.setdefault(r["place_id"], {"place_id": r["place_id"], "status": r["status"], "src": "archive_queue"})
    OUT.mkdir(parents=True, exist_ok=True)
    with (OUT / f"{lane}.jsonl").open("w") as fh:
        for v in rows.values():
            fh.write(json.dumps(v) + "\n")
    summary[lane] = {"total": len(rows), "by_status": dict(collections.Counter(v["status"] for v in rows.values()))}
print(json.dumps(summary, indent=1))
(OUT / "summary.json").write_text(json.dumps(summary, indent=1))
