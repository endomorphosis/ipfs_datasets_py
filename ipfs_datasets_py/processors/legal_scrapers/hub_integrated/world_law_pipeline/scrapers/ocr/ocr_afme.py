#!/usr/bin/env python3
"""OCR lane for the Africa & Middle East (afme) queue. Design mirrors ocr_ro.py; separate state/logs.
Input : /workspace/world_law/out/afme/_ocr_queue.jsonl (read-only)
Output: /workspace/world_law/staging/ocr/<CC>/<place_key>.ocr<YYYYMMDDTHHMMSSZ>p<NNNN>.jsonl (.<name>.tmp.jsonl -> validate -> rename)
State : staging/ocr/_state/afme_done.txt   Logs: staging/ocr/_logs/afme_*
Usage: python3 ocr_afme.py [--limit N] [--countries KE,TR] [--workers 2] [--probe]
"""
from __future__ import annotations
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import argparse, glob, gzip, hashlib, json, os, re, resource, subprocess, sys, tempfile, threading, time
from collections import defaultdict, Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ocr_mem as M
from urllib.parse import urlparse, quote
import requests

sys.path.insert(0, (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/pipeline"))
from schema import place_key, validate_file, validate_record  # noqa: E402

QUEUE = Path((_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/out/afme/_ocr_queue.jsonl"))
SRC = Path((_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/out/afme"))
CACHE = Path((_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/ocr/_cache_afme"))
OUT = Path((_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/staging/ocr"))
STATE, LOGS = OUT / "_state", OUT / "_logs"
UA = "world-municipal-law-research/1.0 (OCR lane; open-data reuse; ~1 req/s per host)"
MAX_PDF = 40 * 1024 * 1024
ORDER = ["KE", "TR", "IR", "ZA", "TZ", "ZM", "UG", "MW"]
LANGS = {"TR": "tur+eng", "IR": "fas+eng", "KE": "eng+swa", "TZ": "eng+swa", "UG": "eng+swa"}  # others: eng
CF_PLATFORMS = {"lii_tanzlii", "lii_zambialii", "lii_lawlibrary", "lii_ulii", "lii_malawilii"}

def utcnow(): return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
def utctag(): return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
def did_of(e): return hashlib.sha1(f"{e['place_id']}|{e['doc_id']}".encode()).hexdigest()[:20]

class Skip(Exception):
    def __init__(self, reason, detail=""): super().__init__(detail); self.reason, self.detail = reason, detail

class SiteLimiter:
    def __init__(self, gap=1.0): self.gap, self.next, self.lk = gap, defaultdict(float), threading.Lock()
    def wait(self, site):
        with self.lk:
            t = max(time.time(), self.next[site]); self.next[site] = t + self.gap
        time.sleep(max(0, t - time.time()))
LIM = SiteLimiter()
_tls = threading.local()
def sess():
    if not hasattr(_tls, "s"):
        _tls.s = requests.Session(); _tls.s.headers["User-Agent"] = UA
    return _tls.s

def is_cf(r, head=b""):
    return (r.headers.get("cf-mitigated") == "challenge" or
            (r.status_code in (403, 503) and "cloudflare" in r.headers.get("server", "").lower()) or
            b"Just a moment" in head or b"challenge-platform" in head)

def get(url, peek=False, rng=None):
    """Polite GET with retries. Returns (status, headers, bytes or first 2KB if peek). Raises Skip('blocked_cf')."""
    site = urlparse(url).hostname or ""; err = None
    for a in range(4):
        LIM.wait(site)
        try:
            h = {"Range": rng} if rng else {}
            r = sess().get(url, timeout=(15, 90), stream=True, headers=h, allow_redirects=True)
            first = next(r.iter_content(2048), b"") if r.status_code < 400 or r.status_code in (403, 503) else b""
            if is_cf(r, first): r.close(); raise Skip("blocked_cf", f"cloudflare challenge {r.status_code} {url}")
            if r.status_code in (429, 500, 502, 503, 504):
                err = f"http {r.status_code}"; r.close(); time.sleep(5 * 2 ** a); continue
            if r.status_code >= 400: r.close(); return r.status_code, r.headers, b""
            if peek: r.close(); return r.status_code, r.headers, first
            buf = bytearray(first)
            for ch in r.iter_content(256 * 1024):
                buf += ch
                if len(buf) > MAX_PDF: r.close(); raise Skip("error", "too large")
            return r.status_code, r.headers, bytes(buf)
        except (requests.ConnectionError, requests.Timeout) as x:
            err = str(x)[:150]; time.sleep(3 * 2 ** a)
    raise Skip("error", f"fetch failed: {err}")

def wayback_lookup(url):
    st, _, body = get("https://archive.org/wayback/available?url=" + quote(url, safe=""))
    if st != 200: return None
    try: s = json.loads(body).get("archived_snapshots", {}).get("closest")
    except ValueError: return None
    if s and s.get("available") and str(s.get("status", "200")).startswith("2"):
        return s["timestamp"], f"https://web.archive.org/web/{s['timestamp']}id_/{url}"
    return None

def cc_record(m):
    a = (m.get("extra_metadata") or {}).get("archive") or {}
    off, ln = int(a["warc_offset"]), int(a["warc_length"])
    st, _, raw = get(m["archive_url"], rng=f"bytes={off}-{off + ln - 1}")
    if st not in (200, 206): raise Skip("error", f"cc http {st}")
    rec = gzip.decompress(raw)
    _, _, rest = rec.partition(b"\r\n\r\n")             # WARC headers
    hh, _, body = rest.partition(b"\r\n\r\n")           # HTTP headers
    if b"chunked" in hh.lower():
        out, b = bytearray(), body
        while b:
            l, _, b = b.partition(b"\r\n")
            n = int(l.split(b";")[0] or b"0", 16)
            if n == 0: break
            out += b[:n]; b = b[n + 2:]
        body = bytes(out)
    return body.rstrip(b"\r\n")

def candidates(e, m):
    """Ordered (kind, url) fetch plan; never tries to solve a challenge."""
    pol = e["source_policy"]; pols = pol if isinstance(pol, list) else [pol]
    u = e["source_url"]; orig = m.get("original_url")
    if "archived_commoncrawl" in pols and m.get("archive_url"): return [("cc", m["archive_url"])]
    if "archived_wayback" in pols and m.get("archive_url"):
        au = re.sub(r"/web/(\d+)/", r"/web/\1id_/", m["archive_url"]); return [("wayback", au)]
    if e["source_platform"] in CF_PLATFORMS:
        pdf = u.rstrip("/") + "/source.pdf"
        return [("live", pdf), ("wayback_lookup", pdf), ("wayback_lookup", u.rstrip("/") + "/source")]
    if e["country_code"] == "KE": return [("live", (orig or u.rstrip("/") + "/source"))]
    return [("live", u)]

def fetch_pdf(e, m, peek=False):
    """Returns (bytes, fetch_info). Raises Skip(html|blocked_cf|not_pdf|error)."""
    cf, last = False, None
    for kind, url in candidates(e, m):
        try:
            if kind == "cc":
                b = cc_record(m); info = {"via": "commoncrawl", "url": m["archive_url"]}
            elif kind == "wayback_lookup":
                w = wayback_lookup(url)
                if not w: last = Skip("blocked_cf" if cf else "error", "no wayback capture"); continue
                st, h, b = get(w[1], peek=peek)
                if st != 200: last = Skip("error", f"wayback http {st}"); continue
                info = {"via": "wayback", "url": w[1].replace("id_/", "/"), "timestamp": w[0], "original": url}
            else:
                st, h, b = get(url, peek=peek)
                if st != 200: last = Skip("error", f"http {st}"); continue
                info = {"via": kind, "url": url}
                if kind == "wayback": info["timestamp"] = re.search(r"/web/(\d+)", url).group(1)
        except Skip as s:
            if s.reason == "blocked_cf": cf = True; last = s; continue
            raise
        if b[:5] == b"%PDF-" or b.lstrip()[:5] == b"%PDF-":
            return b, info
        head = b[:2048].lower()
        last = Skip("html" if (b"<html" in head or b"<!doctype" in head) else "not_pdf", f"{info['url']} ct={(locals().get('h') or {}).get('content-type','')}")
    if cf and (last is None or last.reason != "html"): raise Skip("blocked_cf", "cloudflare challenge; no direct or archived PDF")
    raise last or Skip("error", "no candidate")

def tess_version():
    return subprocess.run(["tesseract", "--version"], capture_output=True, text=True).stdout.split()[1]

def ocr_pdf(pdf, dpi, max_pages, lang):
    env = dict(M.TESS_ENV, OMP_THREAD_LIMIT="1")
    pages, texts = [], []
    with tempfile.TemporaryDirectory(dir="/tmp") as td:
        for img in M.render_pages(pdf, dpi, max_pages, td):  # one page per pdftoppm call, memory-capped
            base = str(img)[:-4]
            subprocess.run(["tesseract", str(img), base, "-l", lang, "--psm", "3", "txt", "tsv"],
                           check=True, capture_output=True, env=env, timeout=600)
            confs = []
            for ln in open(base + ".tsv", encoding="utf-8", errors="replace").read().splitlines()[1:]:
                c = ln.split("\t")
                if len(c) >= 12 and c[0] == "5" and c[11].strip():
                    try:
                        v = float(c[10])
                        if v >= 0: confs.append(v)
                    except ValueError: pass
            pages.append(sum(confs) / len(confs) / 100 if confs else 0.0)
            texts.append(open(base + ".txt", encoding="utf-8", errors="replace").read().strip())
            for x in (img, Path(base + ".tsv"), Path(base + ".txt")): x.unlink(missing_ok=True)
    return texts, pages

# number: only from the doc's own heading (first 15 lines) or its title
NUM_PATS = {
    "TR": [re.compile(r"\b(?:karar\s*(?:no|numaras[ıi]|say[ıi]s[ıi])|say[ıi])\s*[:.]?\s*(\d{1,5}(?:\s*/\s*\d{1,5})?)", re.I)],
    "IR": [re.compile(r"(?:شماره)\s*[:：]?\s*([0-9۰-۹/\-]{1,15})")],
    "_": [re.compile(r"\b(?:Act|By-?laws?|Notice|Ordinance)\s+No\.?\s*(\d{1,5}\s+of\s+(?:19|20)\d\d)\b", re.I),
          re.compile(r"\bNo\.\s*(\d{1,5}\s+of\s+(?:19|20)\d\d)\b", re.I),
          re.compile(r"\(\s*[^()\n]{0,60}?\bActs?,?\s+No\.?\s*(\d{1,4})\s*\)", re.I),     # "(Kajiado County Acts No. 1)"
          re.compile(r"\bAct\s+No\.?\s*(\d{1,4})\b", re.I),
          re.compile(r"\b(?:G\.?N\.?|Government Notice)\s+No\.?\s*(\d{1,5})\b", re.I)],
}
def doc_number(cc, text, title):
    pats = NUM_PATS.get(cc, NUM_PATS["_"])
    for s in ("\n".join(text.splitlines()[:15]), title or ""):
        for p in pats:
            m = p.search(s)
            if m and re.sub(r"\D", "", m.group(1)).strip("0"): return re.sub(r"\s+", " ", re.sub(r"\s*/\s*", "/", m.group(1))).strip()
    return None

def load_mirror(keys):
    idx = {}
    for f in sorted(glob.glob(str(SRC / "*" / "[!_]*.jsonl"))):
        for ln in open(f, encoding="utf-8"):
            try: r = json.loads(ln)
            except ValueError: continue
            k = (r.get("place_id"), r.get("doc_id"))
            if k in keys and k not in idx:
                r.pop("text", None); r.pop("html", None); idx[k] = r
    return idx

def row_for(e, m, text, meta, info):
    r = dict(m)                                   # mirror source-lane field values
    for k in ("place_id", "country_code", "doc_id", "source_url", "source_platform", "source_policy", "content_format", "title_native"):
        r[k] = e[k]                               # queue row metadata wins
    em = dict(r.get("extra_metadata") or {}); em.pop("note", None); em.update(meta)
    if info["via"] == "wayback" and not r.get("archive_source"):
        r.update(archive_source="wayback", archive_crawl_id="wayback", archive_timestamp=info["timestamp"],
                 archive_url=info["url"], original_url=info.get("original") or e["source_url"])
    r.update(text=text, number=doc_number(e["country_code"], text, e.get("title_native")),
             content_complete=True, retrieved_at=utcnow(), extra_metadata=em)
    r.setdefault("doc_type", "decision"); r.setdefault("consolidated", False)
    if not r.get("title_native"): r["title_native"] = e["source_url"].rstrip("/").rsplit("/", 1)[-1]
    return r

def free_disk_gb():
    st = os.statvfs("/workspace"); return st.f_bavail * st.f_frsize / 1e9

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0); ap.add_argument("--countries", default=""); ap.add_argument("--per-cc", type=int, default=0)
    ap.add_argument("--workers", type=int, default=2); ap.add_argument("--dpi", type=int, default=300)
    ap.add_argument("--flush-docs", type=int, default=100); ap.add_argument("--max-pages", type=int, default=60)
    ap.add_argument("--min-chars", type=int, default=200); ap.add_argument("--min-conf", type=float, default=0.5)
    ap.add_argument("--probe", action="store_true", help="only check reachability of every row (no OCR, no output)")
    a = ap.parse_args()
    a.workers = min(a.workers, 2)                 # hard cap: don't starve the RO run
    for d in (CACHE, STATE, LOGS): d.mkdir(parents=True, exist_ok=True)
    rows = [json.loads(l) for l in QUEUE.open(encoding="utf-8")]
    keys = {(e["place_id"], e["doc_id"]) for e in rows}
    mirror = load_mirror(keys); ver = tess_version(); run = utctag()
    seen, uniq = set(), []
    for e in sorted(rows, key=lambda e: ORDER.index(e["country_code"]) if e["country_code"] in ORDER else 99):
        k = (e["place_id"], e["doc_id"])
        if k in seen: continue                    # 206 queue rows repeat a (place, doc_id) under a www/non-www URL
        seen.add(k); uniq.append(e)
    if a.countries: uniq = [e for e in uniq if e["country_code"] in a.countries.split(",")]

    if a.probe:
        res = Counter(); pf = open(LOGS / f"afme_probe_{run}.jsonl", "a", encoding="utf-8"); lk = threading.Lock()
        def pr(e):
            try: _, info = fetch_pdf(e, mirror.get((e["place_id"], e["doc_id"]), {}), peek=True); out = ("reachable", info["via"])
            except Skip as s: out = (s.reason, s.detail[:150])
            with lk:
                res[(e["country_code"], out[0])] += 1
                pf.write(json.dumps({"place_id": e["place_id"], "doc_id": e["doc_id"], "cc": e["country_code"], "result": out[0], "detail": out[1]}, ensure_ascii=False) + "\n"); pf.flush()
        with ThreadPoolExecutor(a.workers) as ex: list(ex.map(pr, uniq))
        summ = {"run": run, "rows": len(rows), "unique": len(uniq), "by": {f"{k[0]}:{k[1]}": v for k, v in sorted(res.items())}}
        (LOGS / f"afme_probe_summary_{run}.json").write_text(json.dumps(summ, indent=1)); print(json.dumps(summ)); return

    donef = STATE / "afme_done.txt"
    done = set(donef.read_text().split()) if donef.exists() else set()
    todo = [e for e in uniq if did_of(e) not in done]
    if a.per_cc:
        cnt = Counter(); t2 = []
        for e in todo:
            if cnt[e["country_code"]] < a.per_cc: t2.append(e); cnt[e["country_code"]] += 1
        todo = t2
    if a.limit: todo = todo[:a.limit]
    logf = open(LOGS / f"afme_run_{run}.jsonl", "a", encoding="utf-8")
    skipf = open(LOGS / "afme_skipped.jsonl", "a", encoding="utf-8")
    evf = open(LOGS / f"afme_events_{run}.log", "a", encoding="utf-8")
    lk = threading.Lock()
    def ev(msg): evf.write(f"{utcnow()} {msg}\n"); evf.flush()
    buf, stats, confs, last_ts, files = [], Counter(), [], [""], []
    t0 = time.time()

    def mark_done(did):
        with donef.open("a") as f: f.write(did + "\n")
        done.add(did)

    def skip(e, reason, **kw):
        stats["skip_" + reason] += 1
        skipf.write(json.dumps({"ts": utcnow(), "run": run, "country_code": e["country_code"], "place_id": e["place_id"], "doc_id": e["doc_id"],
                                "source_url": e["source_url"], "reason": reason, **kw}, ensure_ascii=False) + "\n"); skipf.flush()

    def flush():
        nonlocal buf
        if not buf: return
        by = defaultdict(list)
        for row, did in buf: by[(row["country_code"], row["place_id"])].append((row, did))
        ts = utctag()
        while ts <= last_ts[0]: time.sleep(0.3); ts = utctag()
        last_ts[0] = ts
        for i, ((cc, pid), rs) in enumerate(sorted(by.items()), 1):
            pk = place_key(pid); (OUT / cc).mkdir(exist_ok=True)
            fn = OUT / cc / f"{pk}.ocr{ts}p{i:04d}.jsonl"
            if fn.exists(): raise RuntimeError(f"refusing to overwrite {fn}")
            tmp = fn.with_name("." + fn.name[:-len(".jsonl")] + ".tmp.jsonl")
            with tmp.open("w", encoding="utf-8") as f:
                for row, _ in rs: f.write(json.dumps(row, ensure_ascii=False) + "\n")
                f.flush(); os.fsync(f.fileno())
            v = validate_file(tmp, expect_place_key=pk)
            if not v["ok"]:
                os.rename(tmp, LOGS / ("afme_" + fn.name + ".invalid")); ev(f"INVALID {fn.name} {v['errors'][:2]} {v.get('file_errors')}"); continue
            os.rename(tmp, fn); files.append(str(fn))
            for _, did in rs: mark_done(did)
        ev(f"flushed {len(buf)} docs ts={ts}"); buf = []

    def one(e):
        m = mirror.get((e["place_id"], e["doc_id"]), {}); cc = e["country_code"]; lang = LANGS.get(cc, "eng")
        did = did_of(e); oc = CACHE / f"{did}.ocr.json"
        if oc.exists():
            c = json.loads(oc.read_text()); texts, pc, sha, secs, info = c["texts"], c["page_conf"], c["sha256"], c["secs"], c["fetch"]
        else:
            b, info = fetch_pdf(e, m)
            pdf = CACHE / f"{did}.pdf"; pdf.write_bytes(b); sha = hashlib.sha256(b).hexdigest()
            t = time.time()
            try: texts, pc = ocr_pdf(pdf, a.dpi, a.max_pages, lang)
            finally: pdf.unlink(missing_ok=True)
            secs = round(time.time() - t, 1)
            oc.write_text(json.dumps({"key": [e["place_id"], e["doc_id"]], "texts": texts, "page_conf": pc, "sha256": sha, "secs": secs,
                                      "fetch": info, "lang": lang, "dpi": a.dpi, "engine_version": ver}, ensure_ascii=False))
        text = "\n\f\n".join(texts).strip()
        mean = round(sum(pc) / len(pc), 4) if pc else 0.0
        meta = {"text_source": "ocr", "ocr_engine": "tesseract", "ocr_engine_version": ver, "ocr_lang": lang,
                "ocr_confidence_mean": mean, "ocr_pages": len(pc),
                "ocr_low_conf_pages": sum(1 for c in pc if c < a.min_conf),
                "ocr_low_conf_page_list": [i + 1 for i, c in enumerate(pc) if c < a.min_conf],
                "ocr_dpi": a.dpi, "ocr_max_pages": a.max_pages, "source_pdf_sha256": sha, "source_pdf_url": info["url"],
                "ocr_fetch_via": info["via"], "ocr_seconds": secs}
        return m, text, meta, info

    def job(e):
        M.mem_gate(ev)
        did = did_of(e)
        try: m, text, meta, info = one(e)
        except Skip as s:
            with lk:
                skip(e, s.reason, detail=s.detail[:200])
                if s.reason in ("html", "blocked_cf", "not_pdf"): mark_done(did)
            return
        except Exception as x:  # noqa
            with lk: skip(e, "error", detail=repr(x)[:200])
            return
        with lk:
            stats["docs"] += 1; stats["pages"] += meta["ocr_pages"]; confs.append(meta["ocr_confidence_mean"])
            logf.write(json.dumps({"ts": utcnow(), "cc": e["country_code"], "doc_id": e["doc_id"], "pages": meta["ocr_pages"],
                                   "conf": meta["ocr_confidence_mean"], "chars": len(text), "secs": meta["ocr_seconds"], "via": info["via"]}, ensure_ascii=False) + "\n"); logf.flush()
            reason = "near_empty" if len(re.sub(r"\s", "", text)) < a.min_chars else ("low_conf" if meta["ocr_confidence_mean"] < a.min_conf else None)
            if reason:
                skip(e, reason, conf=meta["ocr_confidence_mean"], chars=len(text), pages=meta["ocr_pages"]); mark_done(did); return
            row = row_for(e, m, text, meta, info)
            err = validate_record(row)
            if err: skip(e, "invalid", detail=str(err)[:200]); return
            buf.append((row, did)); stats["written"] += 1
            if len(buf) >= a.flush_docs:
                try: flush()
                except Exception as fe: ev(f"FLUSH ERROR {fe!r}")  # noqa

    ev(f"start todo={len(todo)} workers={a.workers} disk={free_disk_gb():.1f}GB")
    with ThreadPoolExecutor(a.workers) as ex: list(ex.map(job, todo))
    flush()
    el = time.time() - t0
    summ = {"run": run, "taken": len(todo), "elapsed_s": round(el, 1), **stats,
            "mean_conf": round(sum(confs) / len(confs), 4) if confs else None,
            "docs_per_hour": round(stats["docs"] / el * 3600, 1) if el else 0,
            "written_per_hour": round(stats["written"] / el * 3600, 1) if el else 0,
            "pages_per_hour": round(stats["pages"] / el * 3600, 1) if el else 0,
            "max_child_rss_mb": round(resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss / 1024, 1), "files": files}
    (LOGS / f"afme_summary_{run}.json").write_text(json.dumps(summ, indent=1)); print(json.dumps(summ))

if __name__ == "__main__":
    main()
