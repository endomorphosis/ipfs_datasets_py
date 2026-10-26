#!/usr/bin/env python3
"""Recon helper (states lane): polite GET(s) via common.PoliteSession (robots, >=2 s/host). Saves bodies to data/recon/.
usage: recon_get.py URL [URL ...]   -> prints status, content-type, size, robots policy, first chars of text"""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import hashlib, re, sys
sys.path.insert(0, (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/pipeline/scrapers/states"))
from common import PoliteSession, check_guards
s = PoliteSession()
for u in sys.argv[1:]:
    check_guards()
    try:
        r, pol = s.get(u)
    except Exception as e:
        print("##", u, "ERR", e, flush=True); continue
    fn = (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/pipeline/scrapers/states/data/recon/") + re.sub(r"[^A-Za-z0-9._-]+", "_", u)[:150] + "_" + hashlib.md5(u.encode()).hexdigest()[:6]
    open(fn, "wb").write(r.content)
    t = r.content[:600].decode("utf-8", "replace").replace("\n", " ")
    print("##", u, r.status_code, r.headers.get("content-type"), len(r.content), pol, "->", fn, "\n  ", t[:400], flush=True)
