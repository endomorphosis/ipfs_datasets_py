"""Sweep step 2 (Hub, read-only): read column subsets of every data parquet in world_municipal_law / world_national_law.
Pacing: one HTTP request per ~2 s (global), backoff on 429/5xx (Retry-After honoured).\nv2 (2026-10-17 09:5x PT): exactly one GET per file (whole object streamed to /tmp, columns read locally); municipal files that\nsweep_hubskip.py proves have no incomplete docs (local metadata snapshot + unchanged sha) are not fetched at all. Per file: footer via suffix range,
then only the byte ranges of doc_id/place_id/country_code/source_url/original_url/archive_url/content_format/content_complete/
source_policy/pdf_ref; the text column chunk is read only for row groups that hold PDF-like rows without pdf_ref and with
content_complete != True, and only if it is <= 4 MB compressed (else text length = unknown).
Checkpoint: sweep_work/hub_done.txt (repo|path|sha). Output: sweep_work/hub_rows.jsonl (candidates, one per row, appended).
Also appends queue rows straight into the sweep input (append-only, de-duplicated) after the exclusion checks."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import io, json, os, re, sys, time, signal
from pathlib import Path
import requests
sys.path.insert(0, (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/ocr"))
import sweep_common as S
from huggingface_hub import HfApi, hf_hub_url
from huggingface_hub.utils import build_hf_headers
import pyarrow.parquet as pq

REPOS = ["endomorphosis/world_municipal_law", "endomorphosis/world_national_law"]
GAP = 2.0; last = [0.0]; nreq = [0]
STOP = [False]
signal.signal(signal.SIGTERM, lambda *a: STOP.__setitem__(0, True))
LOG = open(S.WORK / "hub.log", "a")
def log(m): LOG.write(time.strftime("%Y-%m-%dT%H:%M:%S ") + m + "\n"); LOG.flush()
def pace():
    d = last[0] + GAP - time.time()
    if d > 0: time.sleep(d)
    last[0] = time.time(); nreq[0] += 1
HDR = build_hf_headers(); SESS = requests.Session()

def get(url, rng):
    for a in range(8):
        pace()
        try: r = SESS.get(url, headers={**HDR, "Range": rng}, timeout=(20, 120), allow_redirects=True)
        except requests.RequestException as x:
            time.sleep(min(600, 10 * 2 ** a)); continue
        if r.status_code in (200, 206): return r.content
        if r.status_code == 429 or r.status_code >= 500:
            ra = r.headers.get("Retry-After", ""); w = int(ra) if ra.isdigit() else 30 * 2 ** a
            log(f"backoff {r.status_code} {min(w, 900)}s"); time.sleep(min(w, 900)); continue
        raise RuntimeError(f"http {r.status_code}")
    raise RuntimeError("retries exhausted")

class RF(io.RawIOBase):
    """Sparse read-only file over HTTP ranges; serves pyarrow from prefetched segments, fetches on miss."""
    def __init__(self, url, size): self.url, self.size, self.pos, self.seg = url, size, 0, []
    def readable(self): return True
    def seekable(self): return True
    def seek(self, o, wh=0):
        self.pos = o if wh == 0 else (self.pos + o if wh == 1 else self.size + o); return self.pos
    def tell(self): return self.pos
    def fetch(self, a, b):
        b = min(b, self.size)
        if a >= b: return
        self.seg.append((a, get(self.url, f"bytes={a}-{b - 1}")))
    def _have(self, a, b):
        for s, d in self.seg:
            if s <= a and b <= s + len(d): return d[a - s:b - s]
        return None
    def read(self, n=-1):
        if n < 0: n = self.size - self.pos
        a, b = self.pos, min(self.pos + n, self.size)
        d = self._have(a, b)
        if d is None: self.fetch(a, max(b, a + 65536)); d = self._have(a, b)
        self.pos = b; return d
    def readinto(self, buf):
        d = self.read(len(buf)); buf[:len(d)] = d; return len(d)

META = ["doc_id", "place_id", "country_code", "source_url", "original_url", "archive_url", "content_format", "content_complete",
        "source_policy", "pdf_ref"]

def ranges(md, gi, cols):
    rg = md.row_group(gi); out = []
    for j in range(rg.num_columns):
        c = rg.column(j)
        if c.path_in_schema in cols:
            st = c.dictionary_page_offset if c.has_dictionary_page and c.dictionary_page_offset else c.data_page_offset
            out.append((st, st + c.total_compressed_size, c.path_in_schema, c.total_compressed_size))
    return out

def coalesce(rs, gap=262144):
    rs = sorted(rs); out = []
    for a, b in rs:
        if out and a - out[-1][1] <= gap: out[-1][1] = max(out[-1][1], b)
        else: out.append([a, b])
    return out

TMP = Path("/tmp/sweep_hub_cur.parquet")
def fetch_whole(url, size):
    """ONE paced GET of the whole object, streamed to a temp file (no Range => no per-chunk requests). Backoff on 429/5xx."""
    for a in range(8):
        pace()
        try:
            with SESS.get(url, headers=HDR, timeout=(20, 300), stream=True, allow_redirects=True) as r:
                if r.status_code == 200:
                    n = 0
                    with open(TMP, "wb") as f:
                        for ch in r.iter_content(1 << 20): f.write(ch); n += len(ch)
                    with open(TMP, "rb") as f:
                        head = f.read(4); f.seek(-4, 2); tail = f.read(4)
                    if head != b"PAR1" or tail != b"PAR1": raise RuntimeError(f"incomplete parquet {n}/{size}")
                    if n != size: log(f"note size changed since listing {n}/{size} {url[-80:]}")   # newer revision: read it as-is
                    return TMP
                if r.status_code == 429 or r.status_code >= 500:
                    ra = r.headers.get("Retry-After", ""); w = int(ra) if ra.isdigit() else 30 * 2 ** a
                    log(f"backoff {r.status_code} {min(w, 900)}s"); time.sleep(min(w, 900)); continue
                raise RuntimeError(f"http {r.status_code}")
        except (requests.RequestException, RuntimeError) as x:
            if isinstance(x, RuntimeError) and str(x).startswith("http "): raise
            log(f"retry {a} {repr(x)[:120]}"); time.sleep(min(600, 10 * 2 ** a))
    raise RuntimeError("retries exhausted")

def scan_file(repo, path, size):
    import pyarrow.compute as pc
    fn = fetch_whole(hf_hub_url(repo, path, repo_type="dataset"), size)
    pf = pq.ParquetFile(fn); names = set(pf.schema_arrow.names)
    cols = [c for c in META if c in names]
    if not {"doc_id", "place_id", "source_url"} <= set(cols): return []
    out = []
    for g in range(pf.metadata.num_row_groups):
        # content_complete stats: a row group whose content_complete is all True cannot hold candidates (text not read)
        rows = pf.read_row_group(g, columns=cols).to_pylist()
        hit = [i for i, r in enumerate(rows) if r.get("doc_id") and not r.get("pdf_ref") and r.get("content_complete") is not True and S.pdf_url(r)]
        if not hit: continue
        tl = pc.utf8_length(pf.read_row_group(g, columns=["text"]).column("text")).to_pylist() if "text" in names else [0] * len(rows)
        for i in hit:
            r = rows[i]; n = tl[i] or 0; why = S.classify(r, n)
            if why:
                out.append(dict(doc_id=r["doc_id"], place_id=r["place_id"], country_code=r.get("country_code"), source_url=r.get("source_url"),
                                pdf_url=S.pdf_url(r), archive_url=r.get("archive_url"), original_url=r.get("original_url"),
                                source_policy=r.get("source_policy"), content_complete=r.get("content_complete"), text_len=n, why=why,
                                hub=f"{repo}:{path}"))
    del pf
    return out

def listing(api, repo):
    cache = S.WORK / f"tree_{repo.split('/')[1]}.jsonl"
    if cache.exists(): return [json.loads(l) for l in open(cache)]
    out = []
    pace(); n = 0
    for e in api.list_repo_tree(repo, repo_type="dataset", path_in_repo="world_law/data", recursive=True):
        n += 1
        if n % 1000 == 0: pace()                          # the tree API pages ~1000 entries per request
        if getattr(e, "size", None) is not None and e.path.endswith(".parquet"):
            out.append({"path": e.path, "size": e.size, "sha": (e.lfs.sha256 if getattr(e, "lfs", None) else e.blob_id)})
    log(f"listing {repo}: entries={n} parquet={len(out)}")
    with open(cache, "w") as w:
        for o in out: w.write(json.dumps(o) + "\n")
    return out

def main():
    os.nice(10); api = HfApi()
    done = set(l.strip() for l in open(S.WORK / "hub_done.txt")) if (S.WORK / "hub_done.txt").exists() else set()
    todo = []
    for repo in REPOS:
        for e in listing(api, repo): todo.append((repo, e))
    # order: PH first (city retry), then smallest countries/files first so coverage grows fast
    todo.sort(key=lambda t: (t[1]["path"].split("/")[2] != "PH", t[0] != REPOS[1], t[1]["size"]))
    todo = [t for t in todo if f"{t[0]}|{t[1]['path']}|{t[1]['sha']}" not in done]
    skip = set()
    if (S.WORK / "hub_skip.jsonl").exists():
        for l in open(S.WORK / "hub_skip.jsonl"):
            r = json.loads(l)
            if r["repo"] == REPOS[0]: skip.add((r["repo"], r["path"], r["sha"]))
    n0 = len(todo); todo = [t for t in todo if (t[0], t[1]["path"], t[1]["sha"]) not in skip]
    log(f"offline skip (metadata content_incomplete=0, sha unchanged): {n0 - len(todo)} files; 1 request per remaining file")
    log(f"start todo={len(todo)} done={len(done)}")
    dn = open(S.WORK / "hub_done.txt", "a"); hr = open(S.WORK / "hub_rows.jsonl", "a"); t0 = time.time()
    for i, (repo, e) in enumerate(todo):
        if STOP[0]: break
        try: rows = scan_file(repo, e["path"], e["size"])
        except Exception as x:
            log(f"error {repo}:{e['path']} {repr(x)[:200]}"); continue
        for r in rows: hr.write(json.dumps(r, ensure_ascii=False) + "\n")
        hr.flush(); dn.write(f"{repo}|{e['path']}|{e['sha']}\n"); dn.flush()
        if i % 100 == 0 or i == len(todo) - 1:
            el = time.time() - t0
            log(f"progress {i}/{len(todo)} req={nreq[0]} rate={i / max(el, 1) * 3600:.0f} files/h eta_h={(len(todo) - i) / max(i, 1) * el / 3600:.1f}")
    TMP.unlink(missing_ok=True); log("exit stop=%s files=%d req=%d" % (STOP[0], i + 1 if todo else 0, nreq[0]))

if __name__ == "__main__": main()
