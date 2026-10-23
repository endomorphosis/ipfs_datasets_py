"""Polite HTTP for the ph lane: per-host robots (RFC 9309 via asia_latam/common), per-host delay."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import os, sys, time, threading, requests, urllib3
from urllib.parse import urlparse
sys.path.insert(0, (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + '/pipeline/scrapers/asia_latam/common'))
from rfc9309 import Robots
urllib3.disable_warnings()
UA = "JusticeDAO-WorldLaw/1.0 (+https://github.com/endomorphosis/ipfs_datasets_py; municipal law research crawler; polite)"
DELAY = 1.5
_rob, _last, _lock, _retry = {}, {}, threading.Lock(), {}
S = requests.Session(); S.headers['User-Agent'] = UA
a = requests.adapters.HTTPAdapter(pool_connections=50, pool_maxsize=50); S.mount('http://', a); S.mount('https://', a)

def _wait(host):
    with _lock:
        t = _last.get(host, 0); now = time.time(); w = max(0, t + DELAY - now); _last[host] = now + w
    if w: time.sleep(w)

def robots(url):
    p = urlparse(url); key = (p.scheme, p.netloc)
    if key in _rob: return _rob[key]
    _wait(p.netloc)
    try:
        r = S.get(f"{p.scheme}://{p.netloc}/robots.txt", timeout=15, verify=False)
        if r.status_code >= 500: rb, pol = Robots(disallow_all=True), 'robots_unreachable'
        elif r.status_code >= 400 or 'html' in r.headers.get('content-type', '') : rb, pol = Robots(allow_all=True), 'robots_404_allow_rfc9309'
        else: rb, pol = Robots(r.text), 'robots_allowed_rfc9309'
    except Exception:
        rb, pol = Robots(disallow_all=True), 'robots_unreachable'
        if not _retry.get(key):  # one retry for transient errors
            _retry[key] = 1; time.sleep(5); return robots(url)
    _rob[key] = (rb, pol); return rb, pol

def variants(url):
    p = urlparse(url); h = p.netloc; path = p.path or '/'
    hs = [h] + ([h[4:]] if h.startswith('www.') else ['www.' + h])
    return [f"{sc}://{x}{path}" for sc in ('https', 'http') for x in hs]

def resolve_base(url):
    """First working scheme/host variant: returns (response, policy) of homepage or (None, reason)."""
    last = 'error:unreachable'
    for v in variants(url):
        p = urlparse(v)
        if (p.scheme, p.netloc) in _rob and _rob[(p.scheme, p.netloc)][1] == 'robots_unreachable': continue
        r, pol = get(v, timeout=20)
        if r is not None: return r, pol
        last = pol
    return None, last

def get(url, timeout=30, **kw):
    """Returns (response|None, policy|reason). Never fetches robots-disallowed URLs."""
    rb, pol = robots(url)
    if not rb.can_fetch(UA, url):
        return None, ('robots_unreachable' if pol == 'robots_unreachable' else 'robots_disallowed')
    _wait(urlparse(url).netloc)
    try:
        return S.get(url, timeout=timeout * float(os.environ.get('NET_TIMEOUT_MULT', '1')), verify=False, **kw), pol
    except Exception as e:
        return None, 'error:' + type(e).__name__
