"""Wrapper around copied shared/collect_dk.py (repo file unchanged).
Finding 2026-10-10: retsinformation ELI docs that fail with empty_text are Status=Historic (mostly Lovtidende A
1880-1999) whose /xml holds only <Meta> (no body). /rawhtml, /json and the page are a JS-app shell, and /pdf answers
404 "Can not generate PDF for document". So the text isn't published, and the extra fallback calls are wasted.
Changes: (1) ids already logged empty_text in failures.jsonl are skipped (no request);
(2) /xml is fetched FIRST; if it is metadata-only (no element after </Meta>), the id is logged as
'historic_metadata_only' (with Status) and no further requests are made; otherwise the original fetch_one runs,
reusing the cached /xml response; (3) 2 workers instead of 4."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import sys, json, re, threading, concurrent.futures as cf, functools
sys.path.insert(0, (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/pipeline/scrapers/national/shared"))
import collect_dk as C
FAIL = C.ROOT / C.CC / "failures.jsonl"
known = set()
if FAIL.exists():
    for l in open(FAIL, encoding="utf-8"):
        try:
            o = json.loads(l)
            if o.get("reason") in ("empty_text", "historic_metadata_only"): known.add(o["identifier"])
        except Exception: pass
_cache = threading.local()
_orig_get = C.http_get
def http_get(url, *a, **kw):
    c = getattr(_cache, "xml", None)
    if c and c[0] == url: return c[1]
    return _orig_get(url, *a, **kw)
C.http_get = http_get
_orig_fetch = C.fetch_one
def fetch_one(loc, done):
    loc = loc.replace("http://", "https://")
    ident = loc.split("/eli/", 1)[-1].strip("/")
    if C.slug_id(C.CC, ident) in done: return "skip"
    if ident in known: return "fail"
    xml_url = loc.rstrip("/") + "/xml"
    r = _orig_get(xml_url, ua=C.UA, sleep=0.3)
    body = r.text if r.status_code == 200 else ""
    tail = body.split("</Meta>", 1)[1] if "</Meta>" in body else None
    if tail is not None and not re.search(r"<(?!/Dokument)[A-Za-z]", tail):
        st = re.search(r"<Status>([^<]*)", body)
        C.log_failure(C.CC, {"identifier": ident, "source_url": loc, "status": "failed",
                             "reason": "historic_metadata_only", "doc_status": st.group(1) if st else None})
        return "fail"
    _cache.xml = (xml_url, r)
    try: return _orig_fetch(loc, done)
    finally: _cache.xml = None
C.fetch_one = fetch_one
class _TPE2(cf.ThreadPoolExecutor):
    def __init__(self, max_workers=None, **k): super().__init__(max_workers=2, **k)
cf.ThreadPoolExecutor = _TPE2
C.log.info("dk wrapper: %d known metadata-only ids will be skipped", len(known))
if __name__ == "__main__":
    C.main()
