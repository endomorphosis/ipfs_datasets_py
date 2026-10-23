#!/usr/bin/env python3
"""Rows of this lane already published and verified-pruned from processed/ (state/pruned_manifest.jsonl, bot=states)."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import json, re, collections
c = collections.Counter()
for l in open((_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/state/pruned_manifest.jsonl"), encoding="utf-8"):
    try:
        d = json.loads(l)
    except ValueError:
        continue
    if d.get("bot") != "states":
        continue
    m = re.search(r"iso_([A-Z]{2}-[A-Z0-9]+)\.", d.get("path", ""))
    if m:
        c[m.group(1)] += int(d.get("rows") or 0)
print("  " + "  ".join(f"{k}={v}" for k, v in sorted(c.items())) + f"   total={sum(c.values())}")
