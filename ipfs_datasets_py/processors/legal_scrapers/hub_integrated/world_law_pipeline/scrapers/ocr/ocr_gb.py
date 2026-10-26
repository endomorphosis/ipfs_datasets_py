#!/usr/bin/env python3
"""(ocr_gb.py: GB byelaws variant of ocr_ro.py; state gb_done.txt, logs gb_*)
OCR lane for Romania council_docs (romol) PDFs that had no text layer.
Input : /workspace/world_law/staging/eu/_state/council_ro/notext_urls.jsonl (read-only; append-only by EU bot)
Output: /workspace/world_law/staging/ocr/RO/<place_key>.ocr<YYYYMMDDTHHMMSSZ>p<NNNN>.jsonl (tmp -> validate -> rename)
Rows mirror council_docs.py row_for() (same place_key / doc_id = romol:<sha1(url)[:20]>), text from tesseract -l ron+eng.
Usage: python3 ocr_ro.py [--limit N] [--workers W] [--dpi 300] [--flush-docs 100] [--max-pages 60]
"""
from __future__ import annotations
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import argparse, csv, hashlib, json, os, re, resource, subprocess, sys, tempfile, threading, time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse
import requests

sys.path.insert(0, (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/pipeline"))
from schema import place_key, validate_file, validate_record  # noqa: E402

INP = Path((_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/staging/eu/_state/council_gb/notext_urls.jsonl"))
CAND = Path((_wl_os.environ.get("GLOBAL_MUNICIPALITIES_ROOT", "/workspace/global_municipalities") + "/global_municipalities_candidate.csv"))
CACHE = Path((_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/ocr/_cache_gb"))
OUT = Path((_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/staging/ocr"))
STATE, LOGS = OUT / "_state", OUT / "_logs"
UA = "world-municipal-law-research/1.0 (OCR lane; open-data reuse; ~1 req/s per host)"
MAX_PDF = 40 * 1024 * 1024
LANG = "eng"
RIGHTS = ("official publication of the council (UK: OGL/Crown or council copyright; "
          "RO: acte normative, Legea 8/1996 art. 9 exempt from copyright)")

def utcnow(): return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
def utctag(): return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

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

LINKED = {}
def download(url, site, depth=0, cache_as=None):
    p = cache_as or CACHE / (hashlib.sha1(url.encode()).hexdigest() + ".pdf")
    if p.exists() and p.stat().st_size > 0:
        return p
    err = None
    for a in range(4):
        LIM.wait(site)
        try:
            r = sess().get(url, timeout=(15, 90), stream=True)
            if r.status_code in (429, 500, 502, 503, 504):
                err = f"http {r.status_code}"; r.close(); time.sleep(5 * 2 ** a); continue
            r.raise_for_status()
            tmp = p.with_suffix(".part"); n = 0
            with tmp.open("wb") as f:
                for ch in r.iter_content(256 * 1024):
                    n += len(ch)
                    if n > MAX_PDF: raise RuntimeError("too large")
                    f.write(ch)
            if open(tmp, "rb").read(4) != b"%PDF":
                body = tmp.read_bytes(); tmp.unlink()
                if depth == 0 and (b"<html" in body[:4096].lower() or b"<!doctype" in body[:4096].lower()):
                    from urllib.parse import urljoin
                    links = [urljoin(r.url, h) for h in re.findall(rb'href=["\']([^"\']+\.pdf(?:\?[^"\']*)?)["\']', body, re.I) for h in [h.decode("utf-8", "replace")]]
                    links = list(dict.fromkeys(links))
                    pick = [l for l in links if re.search(r"bye-?\s?laws?|byelaw", l, re.I)] or links
                    if not pick: raise RuntimeError("html_no_pdf")
                    LINKED[url] = pick[0]
                    return download(pick[0], urlparse(pick[0]).hostname or site, depth=1, cache_as=p)
                raise RuntimeError("not a PDF")
            os.rename(tmp, p); return p
        except (requests.ConnectionError, requests.Timeout) as e:
            err = str(e)[:150]; time.sleep(3 * 2 ** a)
    raise RuntimeError(f"download failed: {err}")

def tess_version():
    return subprocess.run(["tesseract", "--version"], capture_output=True, text=True).stdout.split()[1]

def ocr_pdf(pdf, dpi, max_pages):
    env = dict(os.environ, OMP_THREAD_LIMIT="1")
    pages, texts = [], []
    with tempfile.TemporaryDirectory(dir="/tmp") as td:
        subprocess.run(["pdftoppm", "-r", str(dpi), "-gray", "-png", "-l", str(max_pages), str(pdf), f"{td}/p"],
                       check=True, capture_output=True, timeout=900)
        for img in sorted(Path(td).glob("p-*.png")):
            base = str(img)[:-4]
            subprocess.run(["tesseract", str(img), base, "-l", LANG, "--psm", "3", "txt", "tsv"],
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
            img.unlink()
    return texts, pages

def load_cand():
    out = {}
    for r in csv.DictReader(CAND.open(encoding="utf-8")):
        if r["country_code"] == "GB": out[r["place_id"]] = r
    return out

NUM_HEAD = re.compile(r"^\W{0,3}(?:HOT[AĂ]R[AÂ]REA?|HCL|DISPOZI[TŢȚ]IA?|DECIZIA?|ORDINUL?|REGULAMENTUL?|PROCES[\s-]*VERBAL(?:UL)?)\b"
                      r"[^\n]{0,40}?\b(?:nr|num[aă]rul)\.?\s*[:.]?\s*(\d{1,5}(?:\s*[/.\-]\s*(?:19|20)\d\d)?)", re.I | re.M)
NUM_TITLE = re.compile(r"(?:\b(?:HCL|hot[aă]r[aâ]rea?|dispozi[tţț]ia?|decizia?)\b[^0-9\n]{0,20}?(?:nr\.?\s*)?|\bnr\.?\s*)(\d{1,5}(?:\s*[/.\-]\s*(?:19|20)\d\d)?)", re.I | re.M)

def fname_title(u):
    from urllib.parse import unquote
    n = unquote(u.rsplit("/", 1)[-1].split("?")[0])
    n = re.sub(r"\.(pdf|docx?)$", "", n, flags=re.I)
    n = re.sub(r"[_\-]+", " ", n).strip()
    n = re.sub(r"^\d{1,4}[.\s]+(?=\D)", "", n).strip()          # leading listing index "259. "
    n = re.sub(r"(\d{1,2}) (\d{1,2}) ((?:19|20)\d\d)", r"\1.\2.\3", n)
    n = re.sub(r"\s+", " ", n)
    return (n[:1].upper() + n[1:]) if n else ""

def heading_line(text):
    for ln in text.splitlines()[:15]:
        ln = ln.strip()
        if NUM_HEAD.search(ln) or re.match(r"^(HOT[AĂ]R[AÂ]RE|DISPOZI|PROCES|REGULAMENT|DECIZI)", ln, re.I):
            return re.sub(r"\s+", " ", ln)[:300]
    return None

def norm_num(x): return re.sub(r"\s*([/.\-])\s*", r"\1", x).strip() if x else None

GB_NUM = re.compile(r"\b(?:Byelaws?|Bye-laws?|Order|Regulations?)\b[^\n]{0,60}?\bNo\.?\s*(\d{1,4})\b|\bS\.?I\.?\s+((?:19|20)\d\d/\d{1,5})\b", re.I)
def doc_number(text, title, url):
    for s_ in ("\n".join(text.splitlines()[:15]), title or ""):
        m = GB_NUM.search(s_)
        if m: return m.group(1) or m.group(2)
    return None
def _ro_doc_number(text, title, url):
    head = "\n".join(text.splitlines()[:15])
    m = NUM_HEAD.search(head)
    if m: return norm_num(m.group(1))
    for s in (title or "", fname_title(url)):
        m = NUM_TITLE.search(s)
        if m: return norm_num(m.group(1))
    return None

def doc_title(e, text):
    t = re.sub(r"\s*\(?\b(?:PDF|pdf)\b[^)]*?(?:KB|MB)\)?.*$|\s*Opens? (?:in )?new window.*$", "", (e.get("title") or "")).strip()
    if t and not re.fullmatch(r"(?i)(download|descarc[aă]|pdf|vezi|click.*|aici|\d+)", t):
        t = re.sub(r"[\s\u2013\-]+$", "", re.sub(r"^\d{1,4}\.\s+", "", t))[:300]
        return t[:1].upper() + t[1:]
    return fname_title(e["source_url"]) or heading_line(text) or e["source_url"].rsplit("/", 1)[-1]

def row_for(e, cand, text, meta):
    r = cand.get(e["place_id"], {})
    u, title = e["source_url"], (e.get("title") or "")
    num = doc_number(text, title, u)
    yr = re.search(r"\b(19[5-9]\d|20[0-3]\d)\b", title) or re.search(r"\b(19[5-9]\d|20[0-3]\d)\b", text[:1500])
    key = e.get("doc_key") or ("doc:" + hashlib.sha1(u.encode()).hexdigest()[:20])
    lvl = r.get("admin_level") or "municipality"
    return {
        "place_id": e["place_id"], "country_code": "GB", "doc_id": f"ukbyelaw:{key[4:] if key.startswith('doc:') else key}",
        "source_platform": "council_site_gb", "source_url": u, "doc_type": "ordinance",
        "language": "en", "title_native": doc_title(e, text), "number": num,
        "adopted_date": None, "published_date": None, "effective_date": None, "in_force": None,
        "consolidated": False, "content_format": "pdf_text", "text": text, "retrieved_at": utcnow(),
        "place_name": r.get("place_name") or e.get("place_name"), "qid": r.get("qid") or None,
        "iso_3166_2": r.get("iso_3166_2") or None, "admin_level": lvl, "level": lvl,
        "platform": "official_council_website", "platform_place_id": None, "place_match": "candidate_source_url",
        "year_hint": yr.group(1) if yr else None, "source_official": True, "rights": RIGHTS,
        "extra_metadata": meta,
    }

def free_gib():
    for ln in open("/proc/meminfo"):
        if ln.startswith("MemAvailable:"): return int(ln.split()[1]) / 1048576
    return 0.0

def free_disk_gb(): 
    st = os.statvfs("/workspace"); return st.f_bavail * st.f_frsize / 1e9

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default=str(INP)); ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--workers", type=int, default=2); ap.add_argument("--max-workers", type=int, default=2)
    ap.add_argument("--dpi", type=int, default=300)
    ap.add_argument("--flush-docs", type=int, default=100); ap.add_argument("--max-pages", type=int, default=60)
    ap.add_argument("--min-chars", type=int, default=200); ap.add_argument("--min-conf", type=float, default=0.5)
    ap.add_argument("--follow", action="store_true", help="keep polling the append-only input for new rows")
    ap.add_argument("--poll", type=int, default=120); ap.add_argument("--chunk", type=int, default=48)
    ap.add_argument("--min-disk-gb", type=float, default=10); ap.add_argument("--ram-up-gib", type=float, default=3)
    ap.add_argument("--keep-pdf", action="store_true")
    a = ap.parse_args(); a.workers = min(a.workers, 2); a.max_workers = min(a.max_workers, 2)
    for d in (CACHE, OUT / "GB", STATE, LOGS): d.mkdir(parents=True, exist_ok=True)
    donef = STATE / "gb_done.txt"
    done = set(donef.read_text().split()) if donef.exists() else set()
    cand, ver = load_cand(), tess_version()
    run = utctag()
    logf = open(LOGS / f"gb_run_{run}.jsonl", "a", encoding="utf-8")
    skipf = open(LOGS / "gb_skipped.jsonl", "a", encoding="utf-8")
    evf = open(LOGS / f"gb_events_{run}.log", "a", encoding="utf-8")
    def ev(msg): evf.write(f"{utcnow()} {msg}\n"); evf.flush()
    buf = []; stats = defaultdict(float); confs = []; seen = set(); pos = [0]
    t0 = time.time(); taken = [0]; last_ts = ['']

    def new_entries():
        out = []
        with open(a.input, encoding="utf-8") as f:
            f.seek(pos[0])
            while True:
                ln = f.readline()
                if not ln or not ln.endswith("\n"): break      # partial last line: re-read next poll
                pos[0] = f.tell()
                try: e = json.loads(ln)
                except ValueError: continue
                u = e.get("source_url")
                if not u or u in seen or not e.get("place_id"): continue
                seen.add(u)
                if hashlib.sha1(u.encode()).hexdigest()[:20] in done: continue
                out.append(e)
        return out

    def one(e):
        u = e["source_url"]; site = e.get("site") or urlparse(u).hostname or ""
        h = hashlib.sha1(u.encode()).hexdigest()
        oc = CACHE / f"{h}.ocr.json"          # OCR result cache (text + per-page conf) so rows can be re-derived
        if oc.exists():
            c = json.loads(oc.read_text()); texts, pc, sha, secs = c["texts"], c["page_conf"], c["sha256"], c["secs"]
        else:
            pdf = download(u, site); t = time.time()
            texts, pc = ocr_pdf(pdf, a.dpi, a.max_pages); secs = round(time.time() - t, 1)
            sha = hashlib.sha256(pdf.read_bytes()).hexdigest()
            oc.write_text(json.dumps({"url": u, "texts": texts, "page_conf": pc, "sha256": sha, "secs": secs, "dpi": a.dpi,
                                      "engine_version": ver}, ensure_ascii=False))
        text = "\n\f\n".join(texts).strip()
        mean = round(sum(pc) / len(pc), 4) if pc else 0.0
        meta = {"text_source": "ocr", "ocr_engine": "tesseract", "ocr_engine_version": ver, "ocr_lang": LANG,
                "ocr_confidence_mean": mean, "ocr_pages": len(pc),
                "ocr_low_conf_pages": sum(1 for c in pc if c < a.min_conf),
                "ocr_low_conf_page_list": [i + 1 for i, c in enumerate(pc) if c < a.min_conf],
                "ocr_dpi": a.dpi, "source_pdf_sha256": sha, "source_pdf_url": LINKED.get(u, u), "ocr_seconds": secs}
        return e, text, meta

    def prune(dids_urls):
        if a.keep_pdf: return
        for u in dids_urls:
            p = CACHE / (hashlib.sha1(u.encode()).hexdigest() + ".pdf")
            try: p.unlink()
            except FileNotFoundError: pass

    def flush():
        nonlocal buf
        if not buf: return
        by = defaultdict(list)
        for row, did in buf: by[row["place_id"]].append((row, did))
        ts = utctag()
        while ts <= last_ts[0]:                 # unique batch ts per flush (same-second flushes would overwrite)
            time.sleep(0.3); ts = utctag()
        last_ts[0] = ts
        for i, (pid, rs) in enumerate(by.items(), 1):
            pk = place_key(pid)
            fn = OUT / "GB" / f"{pk}.ocr{ts}p{i:04d}.jsonl"
            if fn.exists(): raise RuntimeError(f"refusing to overwrite {fn}")
            tmp = fn.with_name("." + fn.name[:-len(".jsonl")] + ".tmp.jsonl")  # dot-prefixed: ignored by uploader
            with tmp.open("w", encoding="utf-8") as f:
                for row, _ in rs: f.write(json.dumps(row, ensure_ascii=False) + "\n")
                f.flush(); os.fsync(f.fileno())
            v = validate_file(tmp, expect_place_key=pk)
            if not v["ok"]:
                os.rename(tmp, LOGS / ("gb_" + fn.name + ".invalid")); ev(f"INVALID {fn.name} {v['errors'][:2]} {v.get('file_errors')}"); continue
            os.rename(tmp, fn)
        with donef.open("a") as f:
            for _, did in buf: f.write(did + "\n"); done.add(did)
        prune([r["source_url"] for r, _ in buf])
        ev(f"flushed {len(buf)} docs ts={ts}")
        buf = []

    def handle(e, res, exc):
        u = e["source_url"]; did = hashlib.sha1(u.encode()).hexdigest()[:20]
        if exc is not None:
            rsn = "html_no_pdf" if "html_no_pdf" in str(exc) else "error"; stats[rsn] += 1
            skipf.write(json.dumps({"ts": utcnow(), "source_url": u, "place_id": e.get("place_id"), "reason": rsn, "detail": str(exc)[:200]}) + "\n"); skipf.flush()
            return
        e, text, meta = res
        stats["docs"] += 1; stats["pages"] += meta["ocr_pages"]; confs.append(meta["ocr_confidence_mean"])
        logf.write(json.dumps({"ts": utcnow(), "source_url": u, "pages": meta["ocr_pages"], "conf": meta["ocr_confidence_mean"], "chars": len(text), "secs": meta["ocr_seconds"]}) + "\n"); logf.flush()
        reason = "near_empty" if len(re.sub(r"\s", "", text)) < a.min_chars else ("low_conf" if meta["ocr_confidence_mean"] < a.min_conf else None)
        if reason:
            stats["skipped"] += 1
            skipf.write(json.dumps({"ts": utcnow(), "source_url": u, "place_id": e.get("place_id"), "reason": reason, "conf": meta["ocr_confidence_mean"], "chars": len(text), "pages": meta["ocr_pages"]}) + "\n"); skipf.flush()
            with donef.open("a") as f: f.write(did + "\n")
            done.add(did); prune([u]); return
        row = row_for(e, cand, text, meta)
        err = validate_record(row)
        if err:
            stats["invalid"] += 1; skipf.write(json.dumps({"source_url": u, "reason": "invalid", "detail": err}) + "\n"); return
        buf.append((row, did)); stats["written"] += 1
        if len(buf) >= a.flush_docs:
            try: flush()
            except Exception as fe:  # noqa
                ev(f"FLUSH ERROR {fe!r}")

    def summary():
        el = time.time() - t0
        summ = {"run": run, "taken": taken[0], "elapsed_s": round(el, 1), **stats,
                "mean_conf": round(sum(confs) / len(confs), 4) if confs else None,
                "docs_per_hour": round(stats["docs"] / el * 3600, 1) if el else 0,
                "pages_per_hour": round(stats["pages"] / el * 3600, 1) if el else 0,
                "max_child_rss_mb": round(resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss / 1024, 1),
                "self_rss_mb": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1)}
        (LOGS / f"gb_summary_{run}.json").write_text(json.dumps(summ, indent=1)); return summ

    pending = []; nw = a.workers
    ex = ThreadPoolExecutor(a.max_workers)
    while True:
        if not pending or len(pending) < nw * 4:
            pending += new_entries()
        if a.limit:
            pending = pending[:max(0, a.limit - taken[0])]
        if not pending:
            if not a.follow: break
            flush(); summary(); time.sleep(a.poll); continue
        while free_disk_gb() < a.min_disk_gb:
            ev(f"PAUSE: free disk {free_disk_gb():.1f} GB < {a.min_disk_gb}"); flush(); time.sleep(300)
        ram = free_gib()
        nw = min(a.max_workers, nw + 1) if ram > a.ram_up_gib and nw < a.max_workers and stats["docs"] >= 20 else nw
        if ram < 1.5 and nw > a.workers: nw -= 1
        chunk, pending = pending[:nw * 4], pending[nw * 4:]
        taken[0] += len(chunk)
        ev(f"chunk {len(chunk)} workers={nw} free_ram={ram:.1f}GiB disk={free_disk_gb():.1f}GB pending={len(pending)}")
        # bounded concurrency = nw
        sem = threading.Semaphore(nw)
        def job(e):
            with sem: return one(e)
        futs = {ex.submit(job, e): e for e in chunk}
        for fu in as_completed(futs):
            try: res, exc = fu.result(), None
            except Exception as x:  # noqa
                res, exc = None, x
            handle(futs[fu], res, exc)
        summary()
        if a.limit and taken[0] >= a.limit and not a.follow: break
    flush()
    print(json.dumps(summary()))

if __name__ == "__main__":
    main()
