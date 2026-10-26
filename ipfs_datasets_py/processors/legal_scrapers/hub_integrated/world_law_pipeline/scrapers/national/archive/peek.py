#!/usr/bin/env python3
"""Debug: dump the cached/archived body for the first N done candidates of a target. peek.py TARGET [N]"""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import gzip, json, os, sys
sys.path.insert(0, (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/pipeline")); sys.path.insert(0, (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/pipeline/scrapers/national/archive"))
from archive import ArchiveFetcher
from archive.core import Capture
t = sys.argv[1]; n = int(sys.argv[2]) if len(sys.argv) > 2 else 2
W = f"/workspace/world_law/staging/national/_archive_work/{t}"
done = {l.split("\t")[0]: l.split("\t")[1] for l in open(f"{W}/done.tsv")}
fx = ArchiveFetcher(cc_crawls=1)
k = 0
_cp = f"{W}/candidates.jsonl.gz" if os.path.exists(f"{W}/candidates.jsonl.gz") else f"{W}/candidates.jsonl"
for l in (gzip.open(_cp, "rt", encoding="utf-8") if _cp.endswith(".gz") else open(_cp)):
    r = json.loads(l)
    if r["key"] in done and k < n:
        k += 1
        doc = fx.fetch_best([Capture(**c) for c in r["caps"]])
        p = f"/tmp/peek_{t}_{k}.html"
        open(p, "wb").write(doc.body if doc else b"")
        print(r["key"], done[r["key"]], doc.original_url if doc else None, len(doc.body) if doc else 0, p)
