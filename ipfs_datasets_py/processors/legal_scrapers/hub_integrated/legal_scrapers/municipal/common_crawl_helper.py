#!/usr/bin/env python3
"""Shared Common Crawl helper: S3 cluster.idx -> CDXJ block -> ranged WARC fetch.

Flow (ranged reads only; no live GETs to target sites; no full-file downloads):
  1. cluster.idx   : binary search the ~100 MB sorted cluster.idx on
                     data.commoncrawl.org using HTTP Range reads (~8 KB each, ~15 reads).
  2. CDXJ shards   : read only the matching cdx-NNNNN.gz members (offset/length given
                     by cluster.idx, ~100-300 KB each), gunzip, filter by SURT prefix.
  3. WARC members  : ipfs_datasets_py ``CommonCrawlSearchEngine.fetch_warc_record_ranges_sliced``
                     (coalesced, bounded range reads, exact member split). Falls back to a plain
                     per-member Range GET if the engine is unavailable.

Run with the venv that has ipfs_datasets_py installed:
  /workspace/ipfs_datasets_fresh_venv/bin/python   (run from a cwd that is NOT /workspace,
  because /workspace/ipfs_datasets_py shadows the installed package)

Example:
  import sys; sys.path.insert(0, "{_SCRAPERS.parent}")
  import common_crawl_helper as cc
  hits = cc.find_pointers("joradp.dz", collections=cc.recent_collections(6),
                          status="200", max_records=200)
  recs = cc.fetch_records(hits[:20])            # [{**pointer, 'body': bytes, 'http_status':..}]
  text = cc.extract_text(recs[0]["body"], recs[0].get("mime"))
  cc.save_pointers(hits, "{_SCRAPERS.parent}/cc_pointers/dz_joradp.parquet")

CLI:
  python common_crawl_helper.py pointers joradp.dz --collections 6 --max 200 --out dz.parquet
  python common_crawl_helper.py fetch dz.parquet --limit 20 --outdir dz_raw
"""
from __future__ import annotations
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))

import argparse
import gzip
import io
import json
import logging
import os
import re
import subprocess
import sys
import tempfile
import time
import zlib
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

import requests

log = logging.getLogger("cc_helper")

CC_DATA = "https://data.commoncrawl.org"
CC_COLLINFO = "https://index.commoncrawl.org/collinfo.json"
UA = "legal-corpora-collector/1.0 (research; ranged Common Crawl reads only)"
MIN_MEM_GIB = float(os.environ.get("CC_MIN_MEM_GIB", "3.5"))
MIN_DISK_GIB = float(os.environ.get("CC_MIN_DISK_GIB", "20"))
REQ_DELAY = float(os.environ.get("CC_REQ_DELAY", "0.15"))

_sess: Optional[requests.Session] = None
_size_cache: Dict[str, int] = {}
_last_req = 0.0


# --------------------------------------------------------------------------- resources
def mem_available_gib() -> float:
    for line in open("/proc/meminfo"):
        if line.startswith("MemAvailable:"):
            return int(line.split()[1]) / 1024 / 1024
    return 99.0


def disk_free_gib(path: str = "/workspace") -> float:
    st = os.statvfs(path)
    return st.f_bavail * st.f_frsize / 1024 ** 3


def resource_guard(wait: bool = True, path: str = "/workspace", max_wait_s: int = 1800) -> bool:
    """True when MemAvailable >= 3.5 GiB and free disk >= 20 GiB; else pause (or return False)."""
    t0 = time.time()
    while True:
        m, d = mem_available_gib(), disk_free_gib(path)
        if m >= MIN_MEM_GIB and d >= MIN_DISK_GIB:
            return True
        log.warning("resource guard: mem=%.2f GiB disk=%.1f GiB (need %.1f/%.0f)", m, d, MIN_MEM_GIB, MIN_DISK_GIB)
        if not wait or time.time() - t0 > max_wait_s:
            return False
        time.sleep(20)


# --------------------------------------------------------------------------- http
def _session() -> requests.Session:
    global _sess
    if _sess is None:
        _sess = requests.Session()
        _sess.headers.update({"User-Agent": UA})
    return _sess


def _range_get(url: str, start: int, length: int, timeout: float = 45.0, retries: int = 4) -> bytes:
    """Bounded HTTP Range read (the only kind of read this helper does)."""
    global _last_req
    end = start + length - 1
    for attempt in range(retries):
        wait = REQ_DELAY - (time.time() - _last_req)
        if wait > 0:
            time.sleep(wait)
        _last_req = time.time()
        try:
            r = _session().get(url, headers={"Range": f"bytes={start}-{end}"}, timeout=timeout, stream=True)
            if r.status_code == 206:
                data = r.raw.read(length + 1, decode_content=False)
                r.close()
                return data[:length]
            if r.status_code == 416:
                r.close()
                return b""
            if r.status_code == 200:  # server ignored Range: refuse to stream a full object
                r.close()
                raise RuntimeError(f"server ignored Range for {url}")
            r.close()
            if r.status_code in (403, 404):
                raise FileNotFoundError(f"{r.status_code} {url}")
        except FileNotFoundError:
            raise
        except Exception as exc:  # transient
            log.debug("range_get retry %s: %s", attempt, exc)
        time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"range_get failed: {url} {start}+{length}")


def _object_size(url: str) -> int:
    if url not in _size_cache:
        r = _session().head(url, timeout=30, allow_redirects=True)
        r.raise_for_status()
        _size_cache[url] = int(r.headers["content-length"])
    return _size_cache[url]


# --------------------------------------------------------------------------- collections
def list_collections() -> List[str]:
    """Newest-first CC-MAIN-* ids (small JSON metadata read from index.commoncrawl.org)."""
    r = _session().get(CC_COLLINFO, timeout=30)
    r.raise_for_status()
    return [c["id"] for c in r.json() if c["id"].startswith("CC-MAIN-")]


def recent_collections(n: int = 6, offset: int = 0) -> List[str]:
    return list_collections()[offset: offset + n]


def spread_collections(n: int = 8) -> List[str]:
    """n collections spread over the full history (newest first) for broad coverage."""
    allc = list_collections()
    if len(allc) <= n:
        return allc
    step = len(allc) / n
    return [allc[int(i * step)] for i in range(n)]


# --------------------------------------------------------------------------- SURT
def host_to_surt_prefix(domain: str, include_subdomains: bool = True) -> str:
    """'joradp.dz' -> 'dz,joradp' ; matching lines start with 'dz,joradp)' or 'dz,joradp,'."""
    d = domain.strip().lower().strip("/")
    d = re.sub(r"^https?://", "", d).split("/")[0]
    if d.startswith("www."):
        d = d[4:]
    return ",".join(reversed(d.split(".")))


def _line_key(line: bytes) -> bytes:
    return line


def _cluster_url(coll: str) -> str:
    return f"{CC_DATA}/cc-index/collections/{coll}/indexes/cluster.idx"


def _read_line_at(url: str, size: int, pos: int, chunk: int = 4096) -> tuple[int, bytes]:
    """Return (start_offset, line) of the first complete line beginning at/after pos."""
    if pos > 0:
        buf = _range_get(url, max(0, pos - 1), min(chunk, size - pos + 1))
        nl = buf.find(b"\n")
        if nl < 0:
            return size, b""
        start = pos - 1 + nl + 1
        buf = buf[nl + 1:]
    else:
        start = 0
        buf = _range_get(url, 0, min(chunk, size))
    end = buf.find(b"\n")
    while end < 0 and start + len(buf) < size:
        buf += _range_get(url, start + len(buf), chunk)
        end = buf.find(b"\n")
    return start, (buf if end < 0 else buf[:end])


def cluster_blocks(coll: str, surt_prefix: str) -> List[Dict[str, Any]]:
    """Binary-search cluster.idx with Range reads; return cdx blocks that may hold the prefix.

    Each item: {'cdx_file','offset','length','collection'}.
    """
    url = _cluster_url(coll)
    size = _object_size(url)
    p = surt_prefix.encode()
    lo, hi = 0, size  # invariant: key(first line at/after lo) < p  (or lo == 0); answer in [lo, hi]
    while hi - lo > 16384:
        mid = (lo + hi) // 2
        start, line = _read_line_at(url, size, mid)
        if not line or start >= hi:
            hi = mid
            continue
        if line.split(b" ", 1)[0] < p and not line.startswith(p):
            lo = start
        else:
            hi = mid
    # read a window then scan forward until keys pass the prefix
    out: List[Dict[str, Any]] = []
    pos = max(0, lo - 1)
    prev: Optional[bytes] = None
    done = False
    carry = b""
    first = True
    while not done and pos < size:
        buf = carry + _range_get(url, pos, 65536)
        if not buf:
            break
        pos += 65536 if len(buf) - len(carry) == 65536 else len(buf) - len(carry)
        lines = buf.split(b"\n")
        carry = lines.pop() if pos < size else b""
        if first and lo > 0 and lines:
            lines = lines[1:]  # partial first line
        first = False
        for ln in lines:
            if not ln:
                continue
            key = ln.split(b" ", 1)[0]
            parts = ln.split(b"\t")
            if len(parts) < 4:
                continue
            is_match = key.startswith(p) and key[len(p):len(p) + 1] in (b")", b",", b"")
            if key > p and not key.startswith(p):
                # first line past the prefix: previous block may still hold matches; stop after
                if prev is not None:
                    out.append(prev)
                    prev = None
                done = True
                break
            cur = {"cdx_file": parts[1].decode(), "offset": int(parts[2]), "length": int(parts[3]), "collection": coll}
            if is_match or key.startswith(p):
                if prev is not None:
                    out.append(prev)
                    prev = None
                out.append(cur)
            else:  # key < p: remember latest block start (matches begin inside it)
                prev = cur
    if prev is not None and not out:
        out.append(prev)
    seen, uniq = set(), []
    for b in out:
        k = (b["cdx_file"], b["offset"])
        if k not in seen:
            seen.add(k)
            uniq.append(b)
    return uniq


def _read_cdx_block(coll: str, blk: Dict[str, Any]) -> List[bytes]:
    url = f"{CC_DATA}/cc-index/collections/{coll}/indexes/{blk['cdx_file']}"
    raw = _range_get(url, blk["offset"], blk["length"])
    try:
        data = zlib.decompressobj(16 + zlib.MAX_WBITS).decompress(raw)
    except Exception:
        data = gzip.decompress(raw)
    return data.split(b"\n")


# --------------------------------------------------------------------------- pointer search
def find_pointers(
    domain: str,
    collections: Optional[Sequence[str]] = None,
    *,
    status: Optional[str] = "200",
    mime_regex: Optional[str] = None,
    url_regex: Optional[str] = None,
    max_records: int = 500,
    max_blocks_per_collection: int = 12,
    include_subdomains: bool = True,
    path_prefix: Optional[str] = None,
    dedupe_url: bool = True,
) -> List[Dict[str, Any]]:
    """cluster.idx -> CDXJ lookup for a domain (or domain + path_prefix). Returns pointer dicts.

    Pointer keys: url, timestamp, collection, filename, offset, length, status, mime, digest, languages.
    """
    base = host_to_surt_prefix(domain)
    mime_re = re.compile(mime_regex, re.I) if mime_regex else None
    url_re = re.compile(url_regex, re.I) if url_regex else None
    results: List[Dict[str, Any]] = []
    seen_url: set = set()
    for coll in collections or recent_collections(4):
        if len(results) >= max_records:
            break
        if not resource_guard(wait=True):
            log.error("resource guard breached; stopping")
            break
        try:
            blocks = cluster_blocks(coll, base)
        except Exception as exc:
            log.warning("cluster lookup failed %s %s: %s", coll, domain, exc)
            continue
        for blk in blocks[:max_blocks_per_collection]:
            try:
                lines = _read_cdx_block(coll, blk)
            except Exception as exc:
                log.warning("cdx block failed %s: %s", blk, exc)
                continue
            pb = base.encode()
            for ln in lines:
                if not ln.startswith(pb):
                    continue
                rest = ln[len(pb):len(pb) + 1]
                if rest not in (b")", b","):
                    continue
                if not include_subdomains and rest == b",":
                    continue
                try:
                    surt, ts, js = ln.decode("utf-8", "replace").split(" ", 2)
                    j = json.loads(js)
                except Exception:
                    continue
                if status and str(j.get("status")) != str(status):
                    continue
                u = j.get("url", "")
                if path_prefix and not re.sub(r"^https?://[^/]+", "", u).startswith(path_prefix):
                    continue
                if mime_re and not mime_re.search(j.get("mime-detected") or j.get("mime") or ""):
                    continue
                if url_re and not url_re.search(u):
                    continue
                if dedupe_url and u in seen_url:
                    continue
                seen_url.add(u)
                results.append({
                    "url": u, "timestamp": ts, "collection": coll,
                    "filename": j.get("filename"), "offset": int(j.get("offset", 0)),
                    "length": int(j.get("length", 0)), "status": str(j.get("status")),
                    "mime": j.get("mime-detected") or j.get("mime"), "digest": j.get("digest"),
                    "languages": j.get("languages"),
                })
                if len(results) >= max_records:
                    break
            if len(results) >= max_records:
                break
    return results


# --------------------------------------------------------------------------- WARC fetch
_engine = None


def get_engine():
    """ipfs_datasets_py CommonCrawlSearchEngine (local mode) or None if unavailable."""
    global _engine
    if _engine is None:
        try:
            from ipfs_datasets_py.processors.web_archiving.common_crawl_integration import CommonCrawlSearchEngine
            eng = CommonCrawlSearchEngine(mode="local")
            _engine = eng if getattr(eng, "_available", False) else False
        except Exception as exc:  # pragma: no cover
            log.warning("CommonCrawlSearchEngine unavailable (%s); using plain Range fallback", exc)
            _engine = False
    return _engine or None


def parse_warc_member(member: bytes) -> Dict[str, Any]:
    """gunzip one WARC response member -> {'warc_headers','http_status','http_headers','body'}."""
    try:
        raw = zlib.decompressobj(16 + zlib.MAX_WBITS).decompress(member)
    except Exception:
        raw = member
    hdr_end = raw.find(b"\r\n\r\n")
    warc_hdr = raw[:hdr_end].decode("utf-8", "replace") if hdr_end >= 0 else ""
    rest = raw[hdr_end + 4:] if hdr_end >= 0 else raw
    h_end = rest.find(b"\r\n\r\n")
    http_hdr = rest[:h_end].decode("utf-8", "replace") if h_end >= 0 else ""
    body = rest[h_end + 4:] if h_end >= 0 else b""
    m = re.match(r"HTTP/\S+\s+(\d+)", http_hdr)
    headers = {}
    for ln in http_hdr.split("\r\n")[1:]:
        if ":" in ln:
            k, v = ln.split(":", 1)
            headers[k.strip().lower()] = v.strip()
    if headers.get("transfer-encoding", "").lower() == "chunked":
        body = _dechunk(body)
    enc = headers.get("content-encoding", "").lower()
    try:
        if enc == "gzip":
            body = gzip.decompress(body)
        elif enc == "deflate":
            body = zlib.decompress(body)
    except Exception:
        pass
    return {"warc_headers": warc_hdr, "http_status": int(m.group(1)) if m else None,
            "http_headers": headers, "body": body}


def _dechunk(b: bytes) -> bytes:
    out, i = b"", 0
    try:
        while True:
            j = b.index(b"\r\n", i)
            n = int(b[i:j].split(b";")[0], 16)
            if n == 0:
                break
            out += b[j + 2:j + 2 + n]
            i = j + 2 + n + 2
    except Exception:
        return b
    return out


def fetch_records(pointers: Sequence[Dict[str, Any]], *, max_slice_bytes: int = 8_000_000,
                  max_gap_bytes: int = 128_000, timeout_s: float = 60.0) -> List[Dict[str, Any]]:
    """Ranged WARC fetch for pointers (grouped by WARC file). Returns pointer dicts + parsed body.

    Uses CommonCrawlSearchEngine.fetch_warc_record_ranges_sliced when available.
    Failed pointers get an 'error' key and no body.
    """
    out: List[Dict[str, Any]] = []
    by_file: Dict[str, List[Dict[str, Any]]] = {}
    for p in pointers:
        by_file.setdefault(p["filename"], []).append(p)
    eng = get_engine()
    for fn, ps in by_file.items():
        if not resource_guard(wait=True):
            for p in ps:
                out.append({**p, "error": "resource_guard"})
            continue
        ranges = [(int(p["offset"]), int(p["length"])) for p in ps]
        try:
            if eng is not None:
                try:
                    data, errs = eng.fetch_warc_record_ranges_sliced(
                        fn, ranges, timeout_s=timeout_s, max_slice_bytes=max_slice_bytes,
                        max_gap_bytes=max_gap_bytes, max_workers=1)
                except TypeError as te:
                    # version skew: engine wrapper passes stats_out but the bundled ccindex.api
                    # (ipfs_datasets_py_fresh) predates it -> call the same slicer directly.
                    if "stats_out" not in str(te):
                        raise
                    data, errs = eng.api.fetch_warc_record_ranges_sliced(
                        warc_filename=fn, ranges=ranges, timeout_s=timeout_s,
                        max_slice_bytes=max_slice_bytes, max_gap_bytes=max_gap_bytes, max_workers=1)
            else:
                data, errs = {}, {}
                for off, ln in ranges:
                    try:
                        data[(off, ln)] = _range_get(f"{CC_DATA}/{fn}", off, ln, timeout=timeout_s)
                    except Exception as exc:
                        errs[(off, ln)] = str(exc)
        except Exception as exc:
            data, errs = {}, {r: f"{type(exc).__name__}: {exc}" for r in ranges}
        for p in ps:
            key = (int(p["offset"]), int(p["length"]))
            if key in data:
                try:
                    out.append({**p, **parse_warc_member(data[key])})
                except Exception as exc:
                    out.append({**p, "error": f"parse: {exc}"})
            else:
                out.append({**p, "error": errs.get(key, "missing")})
    return out


# --------------------------------------------------------------------------- text extraction
def extract_text(body: bytes, mime: Optional[str] = None, *, max_chars: int = 2_000_000) -> str:
    """HTML or PDF bytes -> plain text (pdftotext for PDF, bs4 for HTML). Operates on bytes already fetched."""
    if not body:
        return ""
    m = (mime or "").lower()
    if "pdf" in m or body[:5] == b"%PDF-":
        with tempfile.NamedTemporaryFile(suffix=".pdf") as f:
            f.write(body)
            f.flush()
            try:
                r = subprocess.run(["pdftotext", "-layout", f.name, "-"], capture_output=True, timeout=120)
                return r.stdout.decode("utf-8", "replace")[:max_chars]
            except Exception:
                return ""
    from bs4 import BeautifulSoup
    for enc in ("utf-8", "windows-1256", "windows-1252", "latin-1"):
        try:
            html = body.decode(enc)
            break
        except Exception:
            html = None
    if html is None:
        html = body.decode("utf-8", "replace")
    soup = BeautifulSoup(html, "html.parser")
    for t in soup(["script", "style", "noscript", "nav", "header", "footer"]):
        t.decompose()
    txt = soup.get_text("\n")
    txt = re.sub(r"[ \t\r\f\v]+", " ", txt)
    txt = re.sub(r"\n\s*\n+", "\n\n", txt).strip()
    return txt[:max_chars]


def clean_text(txt: str) -> str:
    """NFKC-normalise (fixes Arabic presentation-form glyphs from PDFs), drop bidi controls, tidy blank lines."""
    import unicodedata
    txt = unicodedata.normalize("NFKC", txt)
    txt = re.sub("[\u200e\u200f\u202a-\u202e\u2066-\u2069\ufeff\x0c]", "", txt)
    txt = re.sub(r"[ \t]+\n", "\n", txt)
    txt = re.sub(r"\n{3,}", "\n\n", txt)
    return txt.strip()


# --------------------------------------------------------------------------- persistence
def save_pointers(pointers: Sequence[Dict[str, Any]], path: str) -> str:
    import pyarrow as pa
    import pyarrow.parquet as pq
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    rows = [{k: (json.dumps(v) if isinstance(v, (list, dict)) else v) for k, v in p.items() if k != "body"} for p in pointers]
    pq.write_table(pa.Table.from_pylist(rows), path)
    return path


def load_pointers(path: str) -> List[Dict[str, Any]]:
    import pyarrow.parquet as pq
    return pq.read_table(path).to_pylist()


# --------------------------------------------------------------------------- CLI
def _main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("pointers")
    a.add_argument("domain")
    a.add_argument("--collections", type=int, default=4)
    a.add_argument("--spread", action="store_true", help="spread collections over history instead of newest N")
    a.add_argument("--max", type=int, default=200)
    a.add_argument("--status", default="200")
    a.add_argument("--mime")
    a.add_argument("--url-regex")
    a.add_argument("--out", required=True)
    b = sub.add_parser("fetch")
    b.add_argument("pointers")
    b.add_argument("--limit", type=int, default=20)
    b.add_argument("--outdir", required=True)
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    if args.cmd == "pointers":
        colls = spread_collections(args.collections) if args.spread else recent_collections(args.collections)
        ps = find_pointers(args.domain, colls, status=args.status, mime_regex=args.mime,
                           url_regex=args.url_regex, max_records=args.max)
        save_pointers(ps, args.out)
        print(f"{len(ps)} pointers -> {args.out}")
    else:
        ps = load_pointers(args.pointers)[: args.limit]
        recs = fetch_records(ps)
        od = Path(args.outdir)
        od.mkdir(parents=True, exist_ok=True)
        ok = 0
        for i, r in enumerate(recs):
            if r.get("body"):
                ok += 1
                (od / f"{i:05d}.bin").write_bytes(r["body"])
                (od / f"{i:05d}.json").write_text(json.dumps({k: v for k, v in r.items() if k not in ("body",)}, default=str))
        print(f"fetched {ok}/{len(recs)} -> {od}")
    return 0


if __name__ == "__main__":
    sys.exit(_main())
