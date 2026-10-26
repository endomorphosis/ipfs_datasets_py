#!/usr/bin/env python3
"""OCR lane for Romania council_docs (romol) PDFs that had no text layer.
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

INP = Path((_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/staging/eu/_state/council_ro/notext_urls.jsonl"))
CAND = Path((_wl_os.environ.get("GLOBAL_MUNICIPALITIES_ROOT", "/workspace/global_municipalities") + "/global_municipalities_candidate.csv"))
CACHE = Path((_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/ocr/_cache"))
OUT = Path((_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/staging/ocr"))
STATE, LOGS = OUT / "_state", OUT / "_logs"
UA = "world-municipal-law-research/1.0 (OCR lane; open-data reuse; ~1 req/s per host)"
MAX_PDF = 40 * 1024 * 1024
LANG = "ron+eng"
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

def download(url, site):
    p = CACHE / (hashlib.sha1(url.encode()).hexdigest() + ".pdf")
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
                tmp.unlink(); raise RuntimeError("not a PDF")
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
        if r["country_code"] == "RO": out[r["place_id"]] = r
    return out

def row_for(e, cand, text, meta):
    r = cand.get(e["place_id"], {})
    u, title = e["source_url"], (e.get("title") or "")
    num = None
    m = re.search(r"(?:HCL|hot[aă]r[aâ]rea?|nr\.?)\s*(?:nr\.?)?\s*(\d{1,4})\s*[/.\-]\s*((?:19|20)\d\d)", title + " " + text[:400], re.I)
    if m: num = f"{m.group(1)}/{m.group(2)}"
    yr = re.search(r"\b(19[5-9]\d|20[0-3]\d)\b", title) or re.search(r"\b(19[5-9]\d|20[0-3]\d)\b", text[:1500])
    key = e.get("doc_key") or ("doc:" + hashlib.sha1(u.encode()).hexdigest()[:20])
    lvl = r.get("admin_level") or "municipality"
    return {
        "place_id": e["place_id"], "country_code": "RO", "doc_id": f"romol:{key[4:] if key.startswith('doc:') else key}",
        "source_platform": "council_site_ro", "source_url": u, "doc_type": "decision",
        "language": "ro", "title_native": title or u.rsplit("/", 1)[-1], "number": num,
        "adopted_date": None, "published_date": None, "effective_date": None, "in_force": None,
        "consolidated": False, "content_format": "pdf_text", "text": text, "retrieved_at": utcnow(),
        "place_name": r.get("place_name") or e.get("place_name"), "qid": r.get("qid") or None,
        "iso_3166_2": r.get("iso_3166_2") or None, "admin_level": lvl, "level": lvl,
        "platform": "official_council_website", "platform_place_id": None, "place_match": "candidate_source_url",
        "year_hint": yr.group(1) if yr else None, "source_official": True, "rights": RIGHTS,
        "extra_metadata": meta,
    }

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default=str(INP)); ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--workers", type=int, default=4); ap.add_argument("--dpi", type=int, default=300)
    ap.add_argument("--flush-docs", type=int, default=100); ap.add_argument("--max-pages", type=int, default=60)
    ap.add_argument("--min-chars", type=int, default=200); ap.add_argument("--min-conf", type=float, default=0.5)
    a = ap.parse_args()
    for d in (CACHE, OUT / "RO", STATE, LOGS): d.mkdir(parents=True, exist_ok=True)
    donef = STATE / "done.txt"
    done = set(donef.read_text().split()) if donef.exists() else set()
    ents, seen = [], set()
    for ln in open(a.input, encoding="utf-8"):
        try: e = json.loads(ln)
        except ValueError: continue
        u = e.get("source_url")
        if not u or u in seen or not e.get("place_id"): continue
        seen.add(u)
        did = hashlib.sha1(u.encode()).hexdigest()[:20]
        if did in done: continue
        ents.append(e)
        if a.limit and len(ents) >= a.limit: break
    cand, ver = load_cand(), tess_version()
    run = utctag()
    logf = open(LOGS / f"run_{run}.jsonl", "a", encoding="utf-8")
    skipf = open(LOGS / "skipped.jsonl", "a", encoding="utf-8")
    lk = threading.Lock(); buf = []; stats = defaultdict(float); confs = []
    t0 = time.time()

    def one(e):
        u = e["source_url"]; site = e.get("site") or urlparse(u).hostname or ""
        pdf = download(u, site)
        t = time.time()
        texts, pc = ocr_pdf(pdf, a.dpi, a.max_pages)
        text = "\n\f\n".join(texts).strip()
        mean = round(sum(pc) / len(pc), 4) if pc else 0.0
        meta = {"text_source": "ocr", "ocr_engine": "tesseract", "ocr_engine_version": ver, "ocr_lang": LANG,
                "ocr_confidence_mean": mean, "ocr_pages": len(pc),
                "ocr_low_conf_pages": [i + 1 for i, c in enumerate(pc) if c < a.min_conf],
                "ocr_dpi": a.dpi, "source_pdf_sha256": hashlib.sha256(pdf.read_bytes()).hexdigest(),
                "source_pdf_url": u, "ocr_seconds": round(time.time() - t, 1)}
        return e, text, meta

    def flush():
        nonlocal buf
        by = defaultdict(list)
        for row, did in buf: by[row["place_id"]].append((row, did))
        ts = utctag()
        for i, (pid, rs) in enumerate(by.items(), 1):
            pk = place_key(pid)
            fn = OUT / "RO" / f"{pk}.ocr{ts}p{i:04d}.jsonl"
            tmp = fn.with_name("." + fn.name[:-len(".jsonl")] + ".tmp.jsonl")  # dot-prefixed: ignored by uploader
            with tmp.open("w", encoding="utf-8") as f:
                for row, _ in rs: f.write(json.dumps(row, ensure_ascii=False) + "\n")
                f.flush(); os.fsync(f.fileno())
            v = validate_file(tmp, expect_place_key=pk)
            if not v["ok"]:
                os.rename(tmp, LOGS / (fn.name + ".invalid")); print("INVALID", fn.name, v["errors"][:2], v.get("file_errors")); continue
            os.rename(tmp, fn)
        with donef.open("a") as f:
            for _, did in buf: f.write(did + "\n")
        buf = []

    with ThreadPoolExecutor(a.workers) as ex:
        futs = {ex.submit(one, e): e for e in ents}
        for fu in as_completed(futs):
            e = futs[fu]; u = e["source_url"]; did = hashlib.sha1(u.encode()).hexdigest()[:20]
            with lk:
                try:
                    e, text, meta = fu.result()
                except Exception as ex_:  # noqa
                    stats["errors"] += 1
                    skipf.write(json.dumps({"ts": utcnow(), "source_url": u, "place_id": e.get("place_id"), "reason": "error", "detail": str(ex_)[:200]}) + "\n"); skipf.flush()
                    continue
                stats["docs"] += 1; stats["pages"] += meta["ocr_pages"]; confs.append(meta["ocr_confidence_mean"])
                logf.write(json.dumps({"ts": utcnow(), "source_url": u, "pages": meta["ocr_pages"], "conf": meta["ocr_confidence_mean"], "chars": len(text), "secs": meta["ocr_seconds"]}) + "\n"); logf.flush()
                reason = "near_empty" if len(re.sub(r"\s", "", text)) < a.min_chars else ("low_conf" if meta["ocr_confidence_mean"] < a.min_conf else None)
                if reason:
                    stats["skipped"] += 1
                    skipf.write(json.dumps({"ts": utcnow(), "source_url": u, "place_id": e.get("place_id"), "reason": reason, "conf": meta["ocr_confidence_mean"], "chars": len(text), "pages": meta["ocr_pages"]}) + "\n"); skipf.flush()
                    with donef.open("a") as f: f.write(did + "\n")
                    continue
                row = row_for(e, cand, text, meta)
                err = validate_record(row)
                if err:
                    stats["invalid"] += 1; skipf.write(json.dumps({"source_url": u, "reason": "invalid", "detail": err}) + "\n"); continue
                buf.append((row, did)); stats["written"] += 1
                if len(buf) >= a.flush_docs:
                    try: flush()
                    except Exception as fe:  # noqa
                        print("FLUSH ERROR", repr(fe), flush=True)
    with lk:
        if buf: flush()
    el = time.time() - t0
    rss = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss / 1024
    summ = {"run": run, "input_entries": len(ents), "elapsed_s": round(el, 1), **stats,
            "mean_conf": round(sum(confs) / len(confs), 4) if confs else None,
            "docs_per_hour": round(stats["docs"] / el * 3600, 1) if el else 0,
            "pages_per_hour": round(stats["pages"] / el * 3600, 1) if el else 0,
            "max_child_rss_mb": round(rss, 1), "self_rss_mb": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1),
            "workers": a.workers}
    (LOGS / f"summary_{run}.json").write_text(json.dumps(summ, indent=1))
    print(json.dumps(summ))

if __name__ == "__main__":
    main()
