#!/usr/bin/env python3
"""Re-check every staged JP doc URL against its host robots.txt with the RFC 9309 matcher."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import sys as _sys; _sys.path.insert(0, (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/pipeline/scrapers/asia_latam/common")); from jsonl_io import open_text, glob_jsonl, locate  # noqa: E402,E702
import glob, json, sys, collections, time
from pathlib import Path
from urllib.parse import urlparse
import requests
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from common.rfc9309 import Robots
from jp_reiki import UA, blocked_reason
urls = collections.defaultdict(list)
for f in glob_jsonl((_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/staging/asia_latam/JP/*.jsonl")):
    for l in open_text(f):
        r = json.loads(l); u = r["source_url"]
        if not blocked_reason(u):
            urls[urlparse(u).scheme + "://" + urlparse(u).netloc].append((u, Path(f).name))
out = {}
for base, lst in urls.items():
    try:
        r = requests.get(base + "/robots.txt", headers={"User-Agent": UA}, timeout=20)
        rb = Robots(disallow_all=True) if r.status_code >= 500 else Robots(allow_all=True) if r.status_code >= 400 or "<html" in r.text[:500].lower() else Robots(r.text)
    except requests.RequestException as e:
        out[base] = {"error": str(e)[:100], "docs": len(lst)}; continue
    bad = [(u, f) for u, f in lst if not rb.can_fetch(UA, u)]
    out[base] = {"docs": len(lst), "disallowed": len(bad), "examples": bad[:3], "files": sorted({f for _, f in bad})}
    time.sleep(1)
Path((_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/staging/asia_latam/_robots_audit_jp.json")).write_text(json.dumps(out, ensure_ascii=False, indent=1))
print("hosts", len(out), "disallowed docs", sum(v.get("disallowed", 0) for v in out.values()), "errors", sum(1 for v in out.values() if "error" in v))
for k, v in out.items():
    if v.get("disallowed") or "error" in v: print(k, v)
