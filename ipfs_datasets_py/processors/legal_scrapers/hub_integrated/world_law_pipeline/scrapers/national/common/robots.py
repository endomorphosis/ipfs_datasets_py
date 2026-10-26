"""Robots gate for national collectors: RFC 9309 matcher from asia_latam/common/rfc9309.py.
Unreachable robots.txt or 5xx => disallow-all. 4xx (404 etc.) => allow-all (RFC 9309 §2.3.1.3).
"""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import sys, time, json
from urllib.parse import urlparse
import requests
sys.path.insert(0, (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/pipeline/scrapers/asia_latam/common"))
from rfc9309 import Robots  # noqa

UA = "legal-corpora-collector/1.0 (research archive of official national gazettes; polite; no commercial scraping)"
_cache = {}

def robots_for(url, timeout=20):
    p = urlparse(url); base = f"{p.scheme}://{p.netloc}"
    if base in _cache: return _cache[base]
    info = {"base": base}
    try:
        r = requests.get(base + "/robots.txt", headers={"User-Agent": UA}, timeout=timeout, allow_redirects=True)
        info["status"] = r.status_code
        if r.status_code >= 500: rb = Robots(disallow_all=True); info["rule"] = "5xx=>disallow-all"
        elif r.status_code >= 400: rb = Robots(allow_all=True); info["rule"] = "4xx=>allow-all"
        else:
            txt = r.text
            if "<html" in txt[:500].lower(): rb = Robots(allow_all=True); info["rule"] = "html-not-robots=>allow-all"
            else: rb = Robots(txt); info["rule"] = "parsed"
    except Exception as e:
        rb = Robots(disallow_all=True); info["status"] = None; info["rule"] = f"unreachable=>disallow-all ({type(e).__name__})"
    _cache[base] = (rb, info)
    return rb, info

def allowed(url, ua=UA):
    rb, info = robots_for(url)
    return rb.can_fetch(ua, url) and rb.can_fetch("*", url) if True else False

def crawl_delay(url, ua=UA):
    rb, _ = robots_for(url)
    return rb.crawl_delay(ua)

if __name__ == "__main__":
    for u in sys.argv[1:]:
        rb, info = robots_for(u)
        print(json.dumps({"url": u, "allowed_ua": rb.can_fetch(UA, u), "allowed_star": rb.can_fetch("*", u), "delay": rb.crawl_delay(UA), **info}))
