#!/usr/bin/env python3
"""OCR lane for the Philippines (PH) queue (reuses ocr_afme.py fetch/OCR helpers; ocr_sasia.py design).
Input : staging/ph/_state/ocr_queue.jsonl (read-only, re-read each pass, deduped by doc_id)
Output: staging/ocr/PH/<place_key>.ocr<TS>p<NNNN>.jsonl  State: _state/ph_done.txt  Logs: _logs/ph_*
Google Drive rows -> uc?export=download&id=<id> (+ confirm-token page). HTML / permission wall -> skip gdrive_noaccess. Never logs in.
"""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import argparse, glob, hashlib, html as H, json, math, os, re, subprocess, sys, tempfile, threading, time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ocr_mem as M
from urllib.parse import urljoin, urlencode, urlparse, parse_qs
sys.path.insert(0, (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/ocr")); sys.path.insert(0, (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/pipeline"))
import ocr_afme as A
from schema import place_key, validate_file, validate_record

PH = Path((_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/staging/ph")); QUEUE = PH / "_state/ocr_queue.jsonl"
OUT, STATE, LOGS = A.OUT, A.STATE, A.LOGS
CACHE = Path((_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/ocr/_cache_ph")); DPI = 200; DEFAULT_LANG = "eng+fil+ceb"
OK_LANGS = {"eng", "fil", "ceb"}

def lang_of(e):
    ls = [l for l in re.split(r"[+,\s]+", e.get("langs") or "") if l in OK_LANGS]
    return "+".join(ls) if ls else DEFAULT_LANG

def gdrive_id(url):
    m = re.search(r"/(?:file/d|document/d|uc)/([A-Za-z0-9_-]{10,})", url) or re.search(r"[?&]id=([A-Za-z0-9_-]{10,})", url)
    return m.group(1) if m else None

def fetch(e):
    if e.get("source_kind") != "gdrive":
        st, h, b = A.get(e["source_url"])
        if st != 200: raise A.Skip("error", f"http {st}")
        if b.lstrip()[:5] != b"%PDF-": raise A.Skip("html" if b"<html" in b[:4096].lower() else "not_pdf", e["source_url"])
        return b, {"via": "live", "url": e["source_url"]}
    gid = gdrive_id(e["source_url"])
    if not gid: raise A.Skip("gdrive_noaccess", "no file id (folder/other link): " + e["source_url"])
    url = "https://drive.google.com/uc?" + urlencode({"export": "download", "id": gid})
    st, h, b = A.get(url)
    if st == 200 and b.lstrip()[:5] != b"%PDF-" and b"<html" in b[:4096].lower():
        # large-file virus-scan interstitial: a form (download-form) with hidden inputs incl. confirm/uuid
        s = b.decode("utf-8", "replace")
        fm = re.search(r'<form[^>]+id="download-form"[^>]+action="([^"]+)"(.*?)</form>', s, re.S)
        if fm:
            q = dict(re.findall(r'<input[^>]+type="hidden"[^>]+name="([^"]+)"[^>]+value="([^"]*)"', fm.group(2)))
            url = H.unescape(fm.group(1)) + "?" + urlencode(q)
        else:
            m = re.search(r'href="(/uc\?export=download[^"]*confirm=[^"]+)"', s) or re.search(r'confirm=([0-9A-Za-z_-]+)', s)
            if not m: raise A.Skip("gdrive_noaccess", "html/permission wall " + url)
            url = urljoin("https://drive.google.com", H.unescape(m.group(1))) if m.group(0).startswith("href") else url + "&confirm=" + m.group(1)
        st, h, b = A.get(url)
    if st != 200 or b.lstrip()[:5] != b"%PDF-":
        if st in (200, 401, 403, 404) and (st != 200 or b"<html" in b[:4096].lower()):
            raise A.Skip("gdrive_noaccess", f"http {st} html/permission wall {url}")
        raise A.Skip("not_pdf" if st == 200 else "error", f"http {st} {url}")
    return b, {"via": "gdrive_uc", "url": url}

NUMRE = re.compile(r"\b(ORDINANCE|RESOLUTION|EXECUTIVE ORDER|KAUTUSAN|KAPASIYAHAN|RESOLUSYON|ORDINANSA)\s*(?:NO|BLG|NUMERO|NUM)\s*[.:]?\s*([0-9][0-9A-Za-z\-/,. ]{0,24}?)(?=\s*(?:$|[,;(]|series|serye|s\.|\b[A-Z]{3,}))", re.I | re.M)
def number(text):
    head = "\n".join(text.splitlines()[:15])
    for m in NUMRE.finditer(head):
        kind = m.group(1).title(); n = m.group(2).strip(" .,-")
        sep = "Blg." if kind in ("Kautusan", "Kapasiyahan", "Resolusyon", "Ordinansa") else "No."
        if re.search(r"\d", n): return f"{kind} {sep} {n}"
    return None

def _numkey(n): return re.sub(r"[^0-9A-Za-z]", "", re.sub(r"(?i)\b(?:s|series|serye)\b.*$", "", n)).lstrip("0").lower()
TITLE_NUM = re.compile(r"\b(?:No|Blg)\s*\.?\s*([0-9][0-9A-Za-z\-/]{0,15})", re.I)
def number_conflict(num, title):
    if not num or not title: return None
    m = TITLE_NUM.search(title)
    if not m: return None
    hn = re.split(r"(?:No\.|Blg\.)\s*", num)[-1]
    tn = m.group(1).strip(".-/")
    a, b = _numkey(hn), _numkey(tn)
    if a == b or a.startswith(b) or b.startswith(a): return None
    return f"title says No. {tn}"

ISO_CODES = None
def iso_for(qid):
    """ISO 3166-2 code for a QID from pipeline/codes/place_codes.parquet (code_system iso_3166_2 / Wikidata P300)."""
    global ISO_CODES
    if ISO_CODES is None:
        ISO_CODES = {}
        try:
            import pyarrow.parquet as pq
            t = pq.read_table((_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/pipeline/codes/place_codes.parquet"), columns=["place_id", "code_system", "code", "wikidata_property", "is_current"])
            for r in t.to_pylist():
                if (r["wikidata_property"] == "P300" or "3166" in (r["code_system"] or "")) and r["code"] and r["is_current"] is not False:
                    ISO_CODES.setdefault(r["place_id"], r["code"])
        except Exception as x: print("place_codes load failed:", x, file=sys.stderr)
    return ISO_CODES.get("wd:" + qid if qid and not qid.startswith("wd:") else qid)

def lane_index(ids):
    """doc_id -> newest existing PH-lane row (metadata source)."""
    idx = {}
    for f in sorted(glob.glob(str(PH / "PH/*.jsonl"))) + sorted(glob.glob(str(PH / "_test/PH/*.jsonl"))):
        for ln in open(f, encoding="utf-8"):
            try: r = json.loads(ln)
            except ValueError: continue
            if r.get("doc_id") in ids and (r["doc_id"] not in idx or "/_test/" in idx[r["doc_id"]][1]): idx[r["doc_id"]] = (r, f)
    return idx

DROP = {"text", "html", "html_title", "text_note", "content_complete", "retrieved_at", "pdf", "number", "title_native", "extra_metadata"}
def clean(v): return None if isinstance(v, float) and math.isnan(v) else v

def row_for(e, base, text, meta):
    r = {k: clean(v) for k, v in base.items() if k not in DROP}
    r = {k: v for k, v in r.items() if v is not None}
    r.update(place_id=e["place_key"], doc_id=e["doc_id"], country_code="PH", source_url=e["source_url"], content_format="pdf_text",
             title_native=e.get("title") or e["source_url"].rsplit("/", 1)[-1], number=number(text), text=text, content_complete=True,
             retrieved_at=A.utcnow(), extra_metadata=dict(base.get("extra_metadata") or {}, **meta))
    if not r.get("iso_3166_2"):
        r.pop("iso_3166_2", None); c = iso_for(r.get("qid") or e["place_key"])
        r["iso_3166_2"] = c          # null only when place_codes has no code
    if "source_policy" in base: r["source_policy"] = base["source_policy"]    # unchanged (robots_unreachable -> held by pipeline)
    nc = number_conflict(r["number"], r["title_native"])
    if nc: r["extra_metadata"]["number_conflict"] = nc
    r.setdefault("consolidated", False); r.setdefault("language", "en"); r.setdefault("source_platform", "ph_lgu"); r.setdefault("doc_type", "ordinance")
    return r

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit-pdf", type=int, default=0); ap.add_argument("--limit-gdrive", type=int, default=0)
    ap.add_argument("--workers", type=int, default=2); ap.add_argument("--min-conf", type=float, default=0.5)
    ap.add_argument("--min-chars", type=int, default=200); ap.add_argument("--max-pages", type=int, default=60)
    ap.add_argument("--follow", action="store_true"); ap.add_argument("--poll", type=int, default=300); ap.add_argument("--chunk", type=int, default=20)
    ap.add_argument("--restage-cached", action="store_true", help="re-emit docs that have cached OCR text, ignoring done state (no fetch/OCR)")
    ap.add_argument("--fetch-gdrive", action="store_true", help="actually try Drive downloads (default: skip fast as gdrive_noaccess)")
    a = ap.parse_args(); a.workers = min(a.workers, 2); CACHE.mkdir(parents=True, exist_ok=True)
    def load():
        rows, seen = [], set()
        for ln in open(QUEUE, encoding="utf-8"):
            if not ln.endswith("\n"): continue
            try: e = json.loads(ln)
            except ValueError: continue
            if e.get("doc_id") and e["doc_id"] not in seen: seen.add(e["doc_id"]); rows.append(e)
        return rows
    donef = STATE / "ph_done.txt"; done = set(donef.read_text().split()) if donef.exists() else set()
    did = lambda e: hashlib.sha1(e["doc_id"].encode()).hexdigest()[:20]
    def pick(rows, tried=()):
        if a.restage_cached: return [e for e in rows if (CACHE / f"{did(e)}.ocr.json").exists() and did(e) not in tried]
        t = [e for e in rows if did(e) not in done and did(e) not in tried]
        if a.limit_pdf or a.limit_gdrive:   # interleaved test batch
            p = [e for e in t if e.get("source_kind") != "gdrive"][:a.limit_pdf]; g = [e for e in t if e.get("source_kind") == "gdrive"][:a.limit_gdrive]
            t = [x for pair in zip(p, g) for x in pair] + p[len(g):] + g[len(p):]
        return t
    rows = load(); todo = pick(rows); idx = lane_index({e["doc_id"] for e in rows})
    ver = A.tess_version(); run = A.utctag(); lk = threading.Lock()
    logf = open(LOGS / f"ph_run_{run}.jsonl", "a"); skipf = open(LOGS / "ph_skipped.jsonl", "a"); evf = open(LOGS / f"ph_events_{run}.log", "a")
    stats, confs, buf, files = Counter(), [], [], []; t0 = time.time()
    def mark(d):
        with donef.open("a") as f: f.write(d + "\n")
        done.add(d)
    def skip(e, reason, **kw):
        stats["skip_" + reason] += 1
        skipf.write(json.dumps({"ts": A.utcnow(), "run": run, "doc_id": e["doc_id"], "source_kind": e.get("source_kind"), "source_url": e["source_url"], "reason": reason, **kw}, ensure_ascii=False) + "\n"); skipf.flush()
    def job(e):
        M.mem_gate(lambda m: (evf.write(f"{A.utcnow()} {m}\n"), evf.flush()))
        d = did(e); lang = lang_of(e); oc = CACHE / f"{d}.ocr.json"
        with lk: stats["try_" + e.get("source_kind", "pdf")] += 1
        try:
            if e.get("source_kind") == "gdrive" and not a.fetch_gdrive and not oc.exists():
                raise A.Skip("gdrive_noaccess", "skipped without fetch: Drive links hit Google sign-in wall (test batch 0/10)")
            if oc.exists():
                c = json.loads(oc.read_text()); texts, pc, secs, info, sha = c["texts"], c["page_conf"], c["secs"], c["fetch"], c["sha256"]
            else:
                b, info = fetch(e); sha = hashlib.sha256(b).hexdigest()
                with tempfile.TemporaryDirectory() as td:
                    pdf = Path(td) / "x.pdf"; pdf.write_bytes(b); del b
                    t = time.time(); texts, pc = A.ocr_pdf(pdf, DPI, a.max_pages, lang); secs = round(time.time() - t, 1)
                oc.write_text(json.dumps({"doc_id": e["doc_id"], "texts": texts, "page_conf": pc, "secs": secs, "fetch": info, "sha256": sha, "lang": lang}, ensure_ascii=False))
        except A.Skip as s:
            with lk:
                skip(e, s.reason, detail=s.detail[:200])
                if s.reason in ("html", "not_pdf", "blocked_cf", "gdrive_noaccess"): mark(d)
            return
        except Exception as x:
            with lk: skip(e, "error", detail=repr(x)[:200])
            return
        if e.get("source_kind") == "gdrive":
            with lk: stats["gdrive_ok"] += 1
        text = "\n\f\n".join(texts).strip(); mean = round(sum(pc) / len(pc), 4) if pc else 0.0
        meta = {"text_source": "ocr", "ocr_engine": "tesseract", "ocr_engine_version": ver, "ocr_lang": lang, "ocr_model": "tessdata_fast",
                "ocr_confidence_mean": mean, "ocr_pages": len(pc), "ocr_low_conf_pages": sum(1 for c in pc if c < a.min_conf),
                "ocr_low_conf_page_list": [i + 1 for i, c in enumerate(pc) if c < a.min_conf], "ocr_dpi": DPI, "ocr_max_pages": a.max_pages,
                "source_pdf_sha256": sha, "source_pdf_url": info["url"], "ocr_fetch_via": info["via"], "ocr_seconds": secs}
        with lk:
            stats["docs"] += 1; stats["pages"] += len(pc); confs.append(mean)
            logf.write(json.dumps({"ts": A.utcnow(), "doc_id": e["doc_id"], "kind": e.get("source_kind"), "pages": len(pc), "conf": mean, "chars": len(text), "secs": secs}) + "\n"); logf.flush()
            reason = "near_empty" if len(re.sub(r"\s", "", text)) < a.min_chars else "low_conf" if mean < a.min_conf else None
            if reason: skip(e, reason, conf=mean, pages=len(pc)); mark(d); return
            if e["doc_id"] not in idx: skip(e, "no_lane_row"); return
            r = row_for(e, idx[e["doc_id"]][0], text, meta)
            err = validate_record(r)
            if err: skip(e, "invalid", detail=str(err)[:200]); return
            buf.append((r, d)); stats["written"] += 1
    tried = set(); last_ts = [""]
    def flush():
        nonlocal buf
        if not buf: return
        by = defaultdict(list)
        for r, d in buf: by[r["place_id"]].append((r, d))
        ts = A.utctag()
        while ts <= last_ts[0]: time.sleep(0.3); ts = A.utctag()
        last_ts[0] = ts; (OUT / "PH").mkdir(exist_ok=True)
        for i, (pid, rs) in enumerate(sorted(by.items()), 1):
            pk = place_key(pid); fn = OUT / "PH" / f"{pk}.ocr{ts}p{i:04d}.jsonl"
            if fn.exists(): raise RuntimeError(f"refusing to overwrite {fn}")
            tmp = fn.with_name("." + fn.name[:-6] + ".tmp.jsonl")
            with tmp.open("w", encoding="utf-8") as f:
                for r, _ in rs: f.write(json.dumps(r, ensure_ascii=False) + "\n")
                f.flush(); os.fsync(f.fileno())
            v = validate_file(tmp, expect_place_key=pk)
            if not v["ok"]: os.rename(tmp, LOGS / ("ph_" + fn.name + ".invalid")); evf.write(f"INVALID {fn.name} {v['errors'][:2]}\n"); continue
            os.rename(tmp, fn); files.append(str(fn))
            for _, d in rs: mark(d)
        evf.write(f"{A.utcnow()} flushed {len(buf)} docs ts={ts}\n"); evf.flush(); buf = []
    def summary():
        el = time.time() - t0; ga = stats["try_gdrive"]
        s = {"run": run, "taken": len(tried), "elapsed_s": round(el, 1), **stats, "mean_conf": round(sum(confs) / len(confs), 4) if confs else None,
             "docs_per_hour": round(stats["docs"] / el * 3600, 1) if el else 0, "gdrive_access_rate": round(stats["gdrive_ok"] / ga, 3) if ga else None, "files": files}
        (LOGS / f"ph_summary_{run}.json").write_text(json.dumps(s, indent=1, ensure_ascii=False)); return s
    while True:
        while todo:
            chunk, todo = todo[:a.chunk], todo[a.chunk:]
            for e in chunk: tried.add(did(e))
            evf.write(f"{A.utcnow()} chunk {len(chunk)} pending={len(todo)}\n"); evf.flush()
            with ThreadPoolExecutor(a.workers) as ex: list(ex.map(job, chunk))
            flush(); summary()
        if not a.follow or a.restage_cached: break
        time.sleep(a.poll); rows = load(); idx = lane_index({e["doc_id"] for e in rows}); todo = pick(rows, tried)
    print(json.dumps(summary(), ensure_ascii=False))

if __name__ == "__main__":
    main()
