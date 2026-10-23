"""Probe reachability + robots (RFC 9309) for candidate source URLs. Read-only, one GET each."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import sys, json, requests
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/pipeline/scrapers/national/common"))
from robots import robots_for, UA
def one(u):
    rb, info = robots_for(u)
    d = {"url": u, "robots": info.get("status"), "rule": info.get("rule"), "allowed": rb.can_fetch(UA, u) and rb.can_fetch("*", u), "delay": rb.crawl_delay(UA)}
    try:
        r = requests.get(u, headers={"User-Agent": UA}, timeout=25)
        t = r.text[:3000].lower()
        d.update(get=r.status_code, bytes=len(r.content), ctype=r.headers.get("content-type", "")[:40],
                 challenge=any(k in t for k in ("captcha", "cf-chl", "challenge", "just a moment", "access denied", "tspd", "incapsula")))
    except Exception as e:
        d.update(get=None, err=f"{type(e).__name__}: {str(e)[:90]}")
    return d
urls = sys.argv[1:]
with ThreadPoolExecutor(8) as ex:
    for d in ex.map(one, urls): print(json.dumps(d, ensure_ascii=False))
