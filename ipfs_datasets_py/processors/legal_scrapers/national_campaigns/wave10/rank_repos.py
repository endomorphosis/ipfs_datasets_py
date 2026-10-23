#!/usr/bin/env python3
"""Wave 10 step 1 (v2): rank all endomorphosis ipfs_* datasets by live row count.

- Repo list + file lists: HF hub API via urllib + surrogate (wave-9 transport),
  retry/backoff per call.
- Row counts: parquet FOOTER reads via HTTP Range requests (works for any
  repo size; no full downloads). Falls back to full download for odd files.
- 6 worker threads; checkpoint to ../stats/ranking.json after every repo.
"""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import io, json, os, re, sys, threading, time, urllib.request, urllib.error
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, "/opt/hatch/skills/skill-creator/bin")
os.environ["no_proxy"] = "localhost,127.0.0.1"
os.environ["NO_PROXY"] = "localhost,127.0.0.1"
from dynamic_credentials import add_surrogate_to_request

WAVE10 = os.path.expanduser("~/workspace/goals/global-law-scraping-coverage/hidden_files/wave10")
HOST = "huggingface.co"
CONNECTOR = "custom.huggingface"
OUT = os.path.join(WAVE10, "stats", "ranking.json")
LIST_CACHE = os.path.join(WAVE10, "stats", "dataset_list.json")
LOCK = threading.Lock()

def raw_get(url, timeout=60, attempts=5, headers=None):
    last = None
    for i in range(attempts):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "legal-data-research/1.0", **(headers or {})})
            add_surrogate_to_request(req, CONNECTOR, allowed_hosts=[HOST])
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read(), {k.lower(): v for k, v in resp.headers.items()}
        except urllib.error.HTTPError as e:
            if e.code in (404, 416):
                return None, {}
            last = e
        except Exception as e:
            last = e
        time.sleep(2 * (i + 1))
    raise last

def get_json(url, **kw):
    blob, _ = raw_get(url, **kw)
    return None if blob is None else json.loads(blob)

class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None

def resolve_signed(url, attempts=5):
    """Resolve an HF resolve/main URL to its signed CDN URL (302), no body."""
    opener = urllib.request.build_opener(_NoRedirect)
    last = None
    for i in range(attempts):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "legal-data-research/1.0"})
            add_surrogate_to_request(req, CONNECTOR, allowed_hosts=[HOST])
            resp = opener.open(req, timeout=60)
            return url  # no redirect (small file served directly)
        except urllib.error.HTTPError as e:
            if e.code in (301, 302, 303, 307, 308) and e.headers.get("Location"):
                return e.headers["Location"]
            if e.code == 404:
                return None
            last = e
        except Exception as e:
            last = e
        time.sleep(2 * (i + 1))
    raise last

def range_get(url, start, end, attempts=5):
    """Ranged GET against a (possibly signed CDN) URL; no surrogate off-host."""
    last = None
    for i in range(attempts):
        try:
            req = urllib.request.Request(url, headers={"Range": f"bytes={start}-{end}",
                                                       "User-Agent": "legal-data-research/1.0"})
            with urllib.request.urlopen(req, timeout=60) as resp:
                return resp.read(), {k.lower(): v for k, v in resp.headers.items()}
        except urllib.error.HTTPError as e:
            if e.code in (404, 416):
                return None, {}
            last = e
        except Exception as e:
            last = e
        time.sleep(2 * (i + 1))
    raise last

class RangeFile:
    """Minimal seekable file-like over HTTP Range GETs (for parquet footers)."""
    def __init__(self, signed_url):
        self.url = signed_url
        self.pos = 0
        blob, hdrs = range_get(self.url, 0, 0)
        cr = hdrs.get("content-range", "")
        m = re.search(r"/(\d+)$", cr)
        if not m:
            raise RuntimeError(f"no Content-Range for {self.url[:80]}: {list(hdrs)}")
        self.size = int(m.group(1))
        self._cache = {}
    def seek(self, offset, whence=0):
        if whence == 0: self.pos = offset
        elif whence == 1: self.pos += offset
        else: self.pos = self.size + offset
        return self.pos
    def tell(self):
        return self.pos
    def read(self, n=-1):
        if n is None or n < 0: n = self.size - self.pos
        if n == 0: return b""
        key = (self.pos, n)
        if key not in self._cache:
            end = self.pos + n - 1
            blob, _ = range_get(self.url, self.pos, end)
            if blob is None: raise RuntimeError("range read failed")
            self._cache[key] = blob
        data = self._cache[key]
        self.pos += len(data)
        return data
    def readable(self): return True
    def seekable(self): return True
    def writable(self): return False
    @property
    def closed(self): return getattr(self, "_closed", False)
    def close(self): self._closed = True
    def flush(self): pass
    def __enter__(self): return self
    def __exit__(self, *a): self.close()

def footer_rows(repo, path):
    import pyarrow.parquet as pq
    url = f"https://{HOST}/datasets/endomorphosis/{repo}/resolve/main/{path}"
    signed = resolve_signed(url)
    if signed is None:
        raise RuntimeError("resolve 404")
    rf = RangeFile(signed)
    md = pq.ParquetFile(rf).metadata
    return md.num_rows, rf.size

def process(repo):
    rec = {"repo": repo}
    info = get_json(f"https://{HOST}/api/datasets/endomorphosis/{repo}")
    files = [s["rfilename"] for s in (info or {}).get("siblings", [])]
    parquets = [f for f in files if f.endswith(".parquet")]
    rec["files"] = files
    rec["parquets"] = parquets
    rec["layout"] = ("data/laws.parquet" if "data/laws.parquet" in parquets
                     else ("other-parquet" if parquets else "no-parquet"))
    per, sizes = {}, {}
    try:
        # headline count needs only data/laws.parquet; footer the rest only
        # when the layout is nonstandard (no data/laws.parquet).
        targets = ["data/laws.parquet"] if "data/laws.parquet" in parquets else parquets
        for pf in targets:
            per[pf], sizes[pf] = footer_rows(repo, pf)
        rec["rows_per_file"] = per
        rec["bytes_per_file"] = sizes
        rec["rows_source"] = "parquet-footer-range"
        if "data/laws.parquet" in per:
            rec["rows"] = per["data/laws.parquet"]
        elif per:
            rec["rows"] = sum(per.values())
            rec["rows_note"] = "sum of nonstandard parquets (no data/laws.parquet)"
        else:
            rec["rows"] = 0
            rec["rows_note"] = "no parquet files"
    except Exception as e:
        rec["error"] = f"{type(e).__name__}: {e}"[:200]
    return rec

def main():
    ids = json.load(open(LIST_CACHE))
    repos = [i.split("/", 1)[1] for i in ids if i.startswith("endomorphosis/ipfs_")]
    print(f"{len(repos)} ipfs_* datasets", flush=True)
    results = []
    if os.path.isfile(OUT):
        results = json.load(open(OUT))
    have = {r["repo"]: r for r in results if r.get("rows") is not None}
    todo = [r for r in repos if r not in have]
    print(f"{len(have)} cached, {len(todo)} to fetch", flush=True)
    results = list(have.values())
    def work(repo):
        try:
            rec = process(repo)
        except Exception as e:
            rec = {"repo": repo, "error": f"{type(e).__name__}: {e}"[:200]}
        with LOCK:
            results.append(rec)
            json.dump(results, open(OUT, "w"), indent=1)
        print(repo, rec.get("rows"), rec.get("layout"), rec.get("error", "")[:70], flush=True)
    with ThreadPoolExecutor(max_workers=12) as ex:
        list(ex.map(work, todo))
    print("wrote", OUT)

if __name__ == "__main__":
    main()
