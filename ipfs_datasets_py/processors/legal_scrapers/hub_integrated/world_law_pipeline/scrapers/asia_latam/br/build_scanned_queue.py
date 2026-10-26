#!/usr/bin/env python3
"""One-off backfill of common/scanned_pdfs.MANIFEST with SAPL rows that have no text layer (text_source=ementa,
content_complete=false, a texto_integral PDF URL): local staging/asia_latam/BR/*.jsonl, then the published Hub parquets
endomorphosis/world_municipal_law/world_law/data/BR/<place_key>_html.parquet for every SAPL place_key in
state/ledger.jsonl. Hub reads use HTTP range requests on the footer + only the needed column chunks
(doc_id, content_complete, source_policy, extra_metadata), pinned to one commit, >= 2 s between HTTP requests.
Resumable: _state/scanned_queue_hub_done.txt (place_keys finished).   build_scanned_queue.py [--local-only] [--limit N]
"""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import argparse, ast, glob, io, json, logging, sys, time
from pathlib import Path
import requests, pyarrow.parquet as pq
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "common"))
import scanned_pdfs as Q  # noqa: E402

WL = Path(_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law")); STAGE = WL / "staging/asia_latam"
DONE = STAGE / "_state/scanned_queue_hub_done.txt"
REPO = "endomorphosis/world_municipal_law"
UA = "world-municipal-law-research/1.0 (asia_latam scanned-PDF queue; ~1 req/2s)"
GAP = 2.0
COLS = ["doc_id", "content_complete", "source_policy", "extra_metadata"]
log = logging.getLogger("scanq")
S = requests.Session(); S.headers["User-Agent"] = UA
_last = [0.0]; NREQ = [0]


def get(url, **kw):
    w = _last[0] + GAP - time.time()
    if w > 0: time.sleep(w)
    for i in range(4):
        try:
            r = S.get(url, timeout=60, **kw); _last[0] = time.time(); NREQ[0] += 1
            if r.status_code in (429, 500, 502, 503, 504):
                time.sleep(30 * (i + 1)); continue
            return r
        except requests.RequestException as e:
            _last[0] = time.time(); log.warning("req error %s", e); time.sleep(30 * (i + 1))
    raise RuntimeError("gave up " + url)


def pdf_of(v):
    if isinstance(v, str):
        try: v = ast.literal_eval(v) if v.startswith("[") else [v]
        except (ValueError, SyntaxError): v = [v]
    return next((u for u in (v or []) if isinstance(u, str) and u.startswith("http")), None)


def local_rows():
    out = []
    for f in sorted(glob.glob(str(STAGE / "BR/*.sapl-*.jsonl"))):
        pk = Path(f).name.split(".")[0]
        for ln in open(f, encoding="utf-8"):
            try: r = json.loads(ln)
            except ValueError: continue
            if r.get("source_platform") != "br_sapl" or r.get("content_complete") is not False: continue
            if r.get("text_source") != "ementa": continue
            u = pdf_of(r.get("pdf_urls"))
            if u: out.append(Q.record(r["doc_id"], pk, "BR", u, r.get("source_policy")))
    return out


class Ranged(io.RawIOBase):
    """Read-only file over HTTP ranges with an explicit cache; pyarrow only gets bytes we prefetched."""
    def __init__(self, url, size): self.url, self.size, self.pos, self.chunks = url, size, 0, []
    def fetch(self, a, b):  # [a, b)
        r = get(self.url, headers={"Range": f"bytes={a}-{b-1}"})
        if r.status_code != 206: raise RuntimeError(f"range {r.status_code}")
        self.chunks.append((a, r.content))
    def readable(self): return True
    def seekable(self): return True
    def tell(self): return self.pos
    def seek(self, o, wh=0):
        self.pos = o if wh == 0 else (self.pos + o if wh == 1 else self.size + o); return self.pos
    def readinto(self, b):
        n = min(len(b), self.size - self.pos)
        for a, d in self.chunks:
            if a <= self.pos and self.pos + n <= a + len(d):
                b[:n] = d[self.pos - a:self.pos - a + n]; self.pos += n; return n
        raise RuntimeError(f"uncached read {self.pos}+{n}")


def hub_place(pk, rev):
    url = f"https://huggingface.co/datasets/{REPO}/resolve/{rev}/world_law/data/BR/{pk}_html.parquet"
    r = get(url, allow_redirects=False)
    if r.status_code == 404: return None
    if r.status_code != 302: raise RuntimeError(f"resolve {r.status_code}")
    size = int(r.headers["x-linked-size"]); cdn = r.headers["location"]
    f = Ranged(cdn, size)
    tail = min(size, 512 * 1024); f.fetch(size - tail, size)
    md = pq.read_metadata(f)
    names = [md.schema.column(i).name for i in range(md.num_columns)]
    spans = []
    for g in range(md.num_row_groups):
        rg = md.row_group(g)
        for c in COLS:
            cc = rg.column(names.index(c))
            a = cc.dictionary_page_offset if cc.has_dictionary_page and cc.dictionary_page_offset else cc.data_page_offset
            spans.append((a, a + cc.total_compressed_size))
    spans.sort(); merged = []
    for a, b in spans:  # coalesce spans closer than 256 KB
        if merged and a - merged[-1][1] < 256 * 1024: merged[-1][1] = max(merged[-1][1], b)
        else: merged.append([a, b])
    for a, b in merged:
        if not (a >= size - tail): f.fetch(a, min(b, size - tail) if b > size - tail else b)
    try:
        t = pq.ParquetFile(f).read(columns=COLS).to_pylist()
    except RuntimeError as e:          # a chunk outside the planned spans (e.g. page index): fetch the whole file once
        if "uncached" not in str(e) or size > 64 * 1024 * 1024: raise
        f.chunks = []; f.fetch(0, size); f.pos = 0
        t = pq.ParquetFile(f).read(columns=COLS).to_pylist()
    out = []
    for r in t:
        if not str(r["doc_id"]).startswith("sapl-") or r["content_complete"] is not False: continue
        em = json.loads(r["extra_metadata"] or "{}")
        if em.get("text_source") != "ementa": continue
        u = pdf_of(em.get("pdf_urls"))
        if u: out.append(Q.record(r["doc_id"], pk, "BR", u, r["source_policy"]))
    return out, len(t)


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--local-only", action="store_true"); ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    n = Q.append(local_rows()); log.info("local: appended %d", n)
    if a.local_only: return
    pks = sorted({json.loads(l)["rel"].split("/")[-1].split(".")[0] for l in open(WL / "state/ledger.jsonl")
                  if '"asia_latam"' in l and ".sapl-" in l})
    done = set(DONE.read_text().split()) if DONE.exists() else set()
    r = get(f"https://huggingface.co/api/datasets/{REPO}/revision/main", params={"expand[]": "sha"})
    rev = r.json()["sha"]; log.info("hub rev %s, %d SAPL place_keys, %d done", rev, len(pks), len(done))
    todo = [p for p in pks if p not in done][: a.limit or None]
    tot = 0
    for i, pk in enumerate(todo, 1):
        try:
            res = hub_place(pk, rev)
        except Exception as e:  # noqa: BLE001
            log.warning("%s failed: %s", pk, e); continue
        if res is None: log.warning("%s: 404 on hub", pk); rows = []; nr = 0
        else: rows, nr = res
        w = Q.append(rows); tot += w
        with open(DONE, "a") as d: d.write(pk + "\n")
        log.info("[%d/%d] %s rows=%d noText=%d appended=%d reqs=%d", i, len(todo), pk, nr, len(rows), w, NREQ[0])
    log.info("hub: appended %d total, %d HTTP requests", tot, NREQ[0])


if __name__ == "__main__":
    main()
