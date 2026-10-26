"""National lane: route every web.archive.org / archive.org / commoncrawl request through the box-wide
limiter (/workspace/world_law/pipeline/archive/ratelimit.py). Auto-loaded via PYTHONPATH=<this dir>.
Patches requests (HTTPAdapter.send, i.e. every hop incl. redirects) and urllib (OpenerDirector.open).
Bodies are read inside the slot. 429/5xx/timeouts/network errors -> req.fail() (backoff of that family only).
Lane: every request is tagged lane 'national' for the limiter's per-lane fair sharing.
Timeouts: Wayback (10, 20) s, Common Crawl (10, 30) s (ratelimit.TIMEOUTS); a caller's larger timeout is capped.
Common Crawl is optional for the collectors: if its slot is not free within CC_MAX_WAIT s (CC backoff/queue),
the request fails fast with a ConnectionError instead of stalling the worker (so it can fall back to Wayback).
Wayback breaker (ratelimit v4): while it is open, Wayback requests fail fast with ConnectionError/URLError
("wayback skipped: wayback breaker open ...") instead of hitting web.archive.org; use Common Crawl.
If the limiter cannot be imported, archive requests raise instead of bypassing it."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import contextlib, io, os, sys
from urllib.parse import urlparse


def _kind(e):
    """'timeout' or 'neterr' (both SOFT in ratelimit; status None was ambiguous in the audit log)."""
    n = type(e).__name__.lower() + " " + str(e).lower()[:200]
    if "ssl" in n or "tls" in n: return "ssl"      # counts toward the Wayback breaker like neterr
    return "timeout" if ("timeout" in n or "timed out" in n) else "neterr"

def _family(url):
    h = (urlparse(url).hostname or "").lower()
    if h == "web.archive.org" or h == "archive.org" or h.endswith(".archive.org"): return "wayback"
    if h == "index.commoncrawl.org": return "cc_index"
    if h.endswith("commoncrawl.org"): return "cc_data"
    return None

try:
    sys.path.insert(0, (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/pipeline"))
    from archive import ratelimit as _rl
    _RL_ERR = None
except Exception as e:  # pragma: no cover
    _rl, _RL_ERR = None, e
finally:
    if sys.path and sys.path[0] == (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/pipeline"): sys.path.pop(0)

LANE = "national"
os.environ.setdefault("ARCHIVE_LANE", LANE)
CC_MAX_WAIT = 30.0

def _slot(fam):
    if _rl is None: raise RuntimeError(f"box-wide ratelimit unavailable ({_RL_ERR}); refusing archive request")
    return _rl.slot(fam, lane=LANE, max_wait=CC_MAX_WAIT if fam.startswith("cc_") else None)

def _cap_timeout(fam, timeout):
    ct, rt = _rl.TIMEOUTS[fam] if _rl is not None else (10, 20)
    if timeout is None: return (ct, rt)
    if isinstance(timeout, (tuple, list)):
        c, r = (list(timeout) + [None, None])[:2]
        return (min(c or ct, ct), min(r or rt, rt))
    try: return (min(float(timeout), ct), min(float(timeout), rt))
    except (TypeError, ValueError): return (ct, rt)


def _tag(url): return ("national:" + url)[:300]

def _status_ok(req, code):
    if code == 429 or (code and code >= 500): req.fail(code)
    else: req.ok(code)

try:
    import requests.adapters as _ra
    _orig_send = _ra.HTTPAdapter.send
    def _send(self, request, stream=False, timeout=None, **kw):
        fam = _family(request.url)
        if not fam: return _orig_send(self, request, stream=stream, timeout=timeout, **kw)
        timeout = _cap_timeout(fam, timeout)
        try: cm = _slot(fam); req = cm.__enter__()
        except Exception as e:
            if _rl is not None and isinstance(e, _rl.SlotBusy):
                import requests.exceptions as _rex
                raise _rex.ConnectionError(f"{fam} skipped: {e}", request=request)
            raise
        with contextlib.ExitStack() as _es:
            _es.push(cm)
            req.tag = _tag(request.url)
            try:
                r = _orig_send(self, request, stream=stream, timeout=timeout, **kw)
                if stream: r.content  # read body inside the slot
            except Exception as _e:
                req.fail(_kind(_e)); raise
            ra = r.headers.get("Retry-After")
            if r.status_code == 429 or r.status_code >= 500:
                try: req.fail(r.status_code, float(ra) if ra else None)
                except ValueError: req.fail(r.status_code)
            else: req.ok(r.status_code)
            return r
    _ra.HTTPAdapter.send = _send
except ImportError:
    pass

import urllib.request as _ur, urllib.response as _uresp, urllib.error as _ue
_orig_open = _ur.OpenerDirector.open
def _open(self, fullurl, data=None, timeout=None, *a, **kw):
    url = fullurl if isinstance(fullurl, str) else fullurl.full_url
    fam = _family(url)
    if not fam:
        return _orig_open(self, fullurl, data, *((timeout,) if timeout is not None else ()), *a, **kw)
    ct, rt = _cap_timeout(fam, timeout)
    timeout = ct + rt
    try: cm = _slot(fam); req = cm.__enter__()
    except Exception as e:
        if _rl is not None and isinstance(e, _rl.SlotBusy):
            raise _ue.URLError(f"{fam} skipped: {e}")
        raise
    with contextlib.ExitStack() as _es:
        _es.push(cm)
        req.tag = _tag(url)
        try:
            resp = _orig_open(self, fullurl, data, timeout, *a, **kw)
            body = resp.read(); code = getattr(resp, "status", None) or resp.getcode()
            out = _uresp.addinfourl(io.BytesIO(body), resp.headers, resp.geturl(), code)
            resp.close(); _status_ok(req, code); return out
        except _ue.HTTPError as e:
            _status_ok(req, e.code); raise
        except Exception as _e:
            req.fail(_kind(_e)); raise
_ur.OpenerDirector.open = _open
os.environ.setdefault("NATIONAL_RLHOOK", "1")
