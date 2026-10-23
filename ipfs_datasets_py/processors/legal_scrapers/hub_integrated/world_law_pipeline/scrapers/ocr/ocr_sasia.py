#!/usr/bin/env python3
"""OCR lane for the South Asia & Russia queue (reuses ocr_afme.py fetch/OCR helpers; ocr_ro.py design).
Input : staging/sasia_ru/_ocr/ocr_queue.jsonl + _ocr/ru_gosweb_notext.jsonl (read-only; deduped by doc_id)
Output: staging/ocr/<CC>/<place_key>.ocr<TS>p<NNNN>.jsonl   State: _state/sasia_done.txt   Logs: _logs/sasia_*
Order : RU gosweb (rus) -> Tatarstan CC (rus+tat, ranged WARC GET) -> IN (pdftotext check first; Kerala mal+eng)
Tatarstan place_key: queue has null; keyed by issuing body (tt_issuer.py): settlement acts -> that settlement's wd:Q (sasia_ru lane
  Wikidata/OKTMO-92 map), genuine Republic acts -> iso:RU-TA; unresolved (e.g. district bodies not in the place codes) are HELD
  (logged to _logs/sasia_held.jsonl, not staged).
"""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import argparse, gzip, hashlib, json, os, re, subprocess, sys, tempfile, threading, time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ocr_mem as M
sys.path.insert(0, (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/ocr")); sys.path.insert(0, (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/pipeline"))
import ocr_afme as A
import tt_issuer as TI
from schema import place_key, validate_file, validate_record

Q = Path((_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/staging/sasia_ru/_ocr"))
OUT, STATE, LOGS = A.OUT, A.STATE, A.LOGS
CACHE = Path((_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/ocr/_cache_sasia"))
TT_PID = "iso:RU-TA"
def rank(e):
    s = e["source"]; return 0 if s == "ru_gosweb" else 1 if s == "pravo_tatarstan_cc" else 2

def lang_of(e):
    if e["source"] == "pravo_tatarstan_cc": return "rus+tat"
    if e.get("country") == "RU": return "rus"
    if e["source"] == "in_lsgkerala": return "mal+eng"
    return "eng+hin" if "hi" in (e.get("language") or "") else "eng"

TESSDATA_BEST = "/usr/share/tesseract-ocr/5/tessdata_best"     # tessdata_best mal + eng (Kerala); others use the default (fast) dir
INDIC = re.compile(r"Mlym|Deva|Taml|Telu|Knda|Beng|Gujr|Guru|Orya")
def is_indic(e): return bool(INDIC.search(e.get("script") or ""))
def ocr_pdf(pdf, max_pages, lang, best=False):
    if not best: return A.ocr_pdf(pdf, 300, max_pages, lang)
    env = dict(M.TESS_ENV, OMP_THREAD_LIMIT="1"); pages, texts = [], []
    with tempfile.TemporaryDirectory(dir="/tmp") as td:
        for img in M.render_pages(pdf, 300, max_pages, td):  # one page per pdftoppm call, memory-capped
            base = str(img)[:-4]
            subprocess.run(["tesseract", "--tessdata-dir", TESSDATA_BEST, str(img), base, "-l", lang, "--psm", "3", "txt", "tsv"],
                           check=True, capture_output=True, env=env, timeout=900)
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
    return texts, pages

MONTHS = {m: i for i, m in enumerate(["JANUARY","FEBRUARY","MARCH","APRIL","MAY","JUNE","JULY","AUGUST","SEPTEMBER","OCTOBER","NOVEMBER","DECEMBER"], 1)}
def _roman(x): return x.upper().replace("1", "I").replace("L", "I")
def egazette_meta(text):
    """-> (title_native or None, number or None) from the Gazette of India header."""
    head = text[:4000]
    part = re.search(r"PART\s*([IVXl1]{1,4})\s*\W{1,3}\s*Sec(?:tion|\.)?\s*(\d)(?:\s*\W{1,3}\s*Sub-?\s*section\s*\(([ivx]+)\))?", head, re.I)
    dt = re.search(r"NEW DELHI,\s*[A-Z]+DAY,\s*([A-Z]+)\s+(\d{1,2}),\s*((?:19|20)\d\d)", head, re.I)
    num = subj = None
    m = re.search(r"^\W{0,3}([S58]\.\s?[O0]\.|G\.\s?S\.\s?R\.)\s*(\d{1,5})\s*\(E\)\s*\.?\s*[\-—–]+\s*(.+)$", text[:12000], re.M)
    if m:
        kind = "S.O." if re.match(r"[S58]", m.group(1)) else "G.S.R."
        num = f"{kind} {m.group(2)}(E)"; subj = re.sub(r"\s*[:;,]?\s*[—\-–]*\s*$", "", m.group(3)).strip()
    if not num:
        h = re.search(r"(का\.आ\.|सा\.का\.नि\.)\s*(\d{1,5})\s*\(अ\)", text[:12000])
        if h: num = f"{'S.O.' if h.group(1) == 'का.आ.' else 'G.S.R.'} {h.group(2)}(E)"
    title = None
    if part and dt and subj and dt.group(1).upper() in MONTHS:
        sec = part.group(2) + (f"({part.group(3).lower()})" if part.group(3) else "")
        date = f"{dt.group(3)}-{MONTHS[dt.group(1).upper()]:02d}-{int(dt.group(2)):02d}"
        title = f"Gazette of India Extraordinary, Part {_roman(part.group(1))} Sec {sec}, {date}: {subj}"[:400]
    return title, num

def fetch(e):
    ar = e.get("archive_ref")
    if e["source"] == "pravo_tatarstan_cc" or (ar and e["source"] == "egazette_in"):
        m = {"archive_url": "https://data.commoncrawl.org/" + ar["warc_filename"], "extra_metadata": {"archive": ar}}
        b = A.cc_record(m); info = {"via": "commoncrawl", "url": m["archive_url"]}
    else:
        st, h, b = A.get(e["source_url"]); info = {"via": "live", "url": e["source_url"]}
        if st != 200: raise A.Skip("error", f"http {st}")
    if b.lstrip()[:5] != b"%PDF-":
        raise A.Skip("html" if b"<html" in b[:4096].lower() else "not_pdf", info["url"])
    return b, info

NUM = re.compile(r"(?:ПОСТАНОВЛЕНИЕ|РЕШЕНИЕ|РАСПОРЯЖЕНИЕ|ПРИКАЗ|КАРАР|БОЕРЫК)?[^\n]{0,80}?№\s*([0-9]{1,5}[0-9А-Яа-я\-/]*)", re.I)
def clean_num(x):
    x = (x or "").strip().strip("\"'”“«».,:;_ ")
    if not x or not re.search(r"[1-9]", x) or not re.fullmatch(r"[0-9]{1,6}(?:[-/][0-9А-Яа-яA-Za-z]{1,6})*[А-Яа-я]{0,3}(?:-[А-Яа-я]{1,4})?", x): return None
    return x
def number(e, text):
    m = re.search(r"(?:года|г\.)\s*№[\s_]*([0-9][0-9А-Яа-я\-/]*)", "\n".join(text.splitlines()[:15]))   # "… 2025 года № 97"
    if m and clean_num(m.group(1)): return clean_num(m.group(1))
    for s in ("\n".join(text.splitlines()[:15]), e.get("title") or ""):
        for m in re.finditer(r"№[\s_]*([0-9][0-9А-Яа-я\-/]*)", s):
            n = clean_num(m.group(1))
            if n: return n
    return clean_num(e.get("number"))

def tt_title(text):
    """Subject line of a Tatarstan act ("О …"/"Об …"), joined across wrapped lines, from the first 25 lines."""
    ls = [l.strip() for l in text.splitlines()[:60] if l.strip()][:40]
    for i, l in enumerate(ls):
        if re.match(r"^Об?\s+[а-яА-Я]", l):
            out = [l]
            for n in ls[i + 1:i + 5]:
                if re.match(r"^\d+\.|^(ПОСТАНОВЛЯ|РЕШИЛ|постановляю|решил)", n) or re.match(r"^(В соответствии|Руководствуясь|На основании|В целях|Рассмотрев)", n): break
                out.append(n)
            return re.sub(r"\s+", " ", " ".join(out)).strip(" -")[:300]
    return None

def row_for(e, text, meta, info):
    cc = e.get("country_code") or e["country"]
    if e["source"] == "ru_gosweb":
        host = e["doc_id"].split(":")[1]
        r = {"place_id": e["place_id"], "country_code": "RU", "doc_id": e["doc_id"], "source_platform": "ru_gosweb",
             "source_url": e.get("doc_page_url") or e["source_url"], "file_url": e["source_url"], "doc_type": "regulation",
             "language": "ru", "title_native": e.get("title") or e["source_url"].rsplit("/", 1)[-1], "adopted_date": e.get("adopted_date"),
             "in_force": None, "consolidated": False, "content_format": "pdf_text", "source_policy": "robots_allowed_rfc9309",
             "source_official": True, "qid": e["place_id"].split(":")[1], "admin_level": "municipality",
             "platform": "ru_gosweb", "platform_place_id": host}
    elif e["source"] == "pravo_tatarstan_cc":
        ar = e["archive_ref"]; pid, why = TI.issuer(text)
        if pid is None: raise A.Skip("held_issuer", why)
        tt_place = {"place_name": "Республика Татарстан", "qid": "Q5481", "admin_level": "adm1", "platform_place_id": "RU-TA"} if pid == TT_PID else \
                   {"place_name": why.split(":", 1)[1], "qid": pid[3:], "admin_level": "municipality", "platform_place_id": None}
        r = {"place_id": pid, "country_code": "RU", "doc_id": e["doc_id"], "source_platform": "pravo_tatarstan_cc",
             "source_url": e["source_url"], "doc_type": "regulation", "language": "ru",
             "title_native": e.get("title") or tt_title(text) or (text.strip().splitlines() or [e["source_url"].rsplit("/", 1)[-1]])[0][:300],
             "in_force": None, "consolidated": False, "content_format": "pdf_text",
             "archive_source": "commoncrawl", "archive_crawl_id": ar["archive_crawl_id"], "archive_timestamp": ar["archive_timestamp"],
             "archive_url": info["url"], "original_url": e["source_url"], "source_policy": "archived_commoncrawl",
             "source_official": True, "iso_3166_2": "RU-TA", "platform": "pravo_tatarstan", **tt_place}
        meta = dict(meta, issuer_match=why)
        meta = dict(meta, archive={k: ar[k] for k in ("warc_filename", "warc_offset", "warc_length")})
    else:
        pid = e["place_key"] if ":" in e["place_key"] else ("iso:" + e["place_key"] if len(e["place_key"]) == 2 else e["place_key"].replace("_", ":", 1))
        egt, egn = egazette_meta(text) if e["source"] == "egazette_in" else (None, None)
        r = {"place_id": pid, "country_code": "IN", "doc_id": e["doc_id"], "source_platform": e["source"], "source_url": e["source_url"],
             "doc_type": "gazette_act" if e["source"] == "egazette_in" else "regulation", "language": (e.get("language") or "en").split("/")[0],
             "title_native": egt if e["source"] == "egazette_in" else (e.get("title") or e["source_url"].rsplit("/", 1)[-1]), "in_force": None, "consolidated": False,
             "content_format": "pdf_text", "source_official": True}
    if e["source"] == "egazette_in":
        r.update(number=egn, text=text, content_complete=True, retrieved_at=A.utcnow(), extra_metadata=meta)
        if not r["title_native"]: r.pop("title_native")       # header not parseable -> null title (number kept as title fallback)
        return r
    r.update(number=number(e, text), text=text, content_complete=True, retrieved_at=A.utcnow(), extra_metadata=meta)
    return r

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-source", type=int, default=0); ap.add_argument("--sources", default="")
    ap.add_argument("--workers", type=int, default=2); ap.add_argument("--min-conf", type=float, default=0.5)
    ap.add_argument("--min-chars", type=int, default=200); ap.add_argument("--max-pages", type=int, default=60)
    ap.add_argument("--follow", action="store_true"); ap.add_argument("--poll", type=int, default=300); ap.add_argument("--chunk", type=int, default=20)
    a = ap.parse_args(); a.workers = min(a.workers, 2)
    CACHE.mkdir(parents=True, exist_ok=True)
    ap2 = a
    held = set(); heldf = open(LOGS / "sasia_held.jsonl", "a", encoding="utf-8")
    def load():
      rows, seen = [], set()
      for f in ("ocr_queue.jsonl", "ru_gosweb_notext.jsonl"):
        for ln in open(Q / f, encoding="utf-8"):
            if not ln.endswith("\n"): continue
            try: e = json.loads(ln)
            except ValueError: continue
            if e["doc_id"] in seen: continue
            seen.add(e["doc_id"]); e.setdefault("country", e.get("country_code")); rows.append(e)
      rows.sort(key=rank); return rows
    rows = load()
    donef = STATE / "sasia_done.txt"; done = set(donef.read_text().split()) if donef.exists() else set()
    did = lambda e: hashlib.sha1(e["doc_id"].encode()).hexdigest()[:20]
    todo = [e for e in rows if did(e) not in done and (not a.sources or e["source"] in a.sources.split(","))]
    if a.per_source:
        c = Counter(); t = []
        for e in todo:
            if c[e["source"]] < a.per_source: t.append(e); c[e["source"]] += 1
        todo = t
    ver = A.tess_version(); run = A.utctag(); lk = threading.Lock()
    logf = open(LOGS / f"sasia_run_{run}.jsonl", "a"); skipf = open(LOGS / "sasia_skipped.jsonl", "a"); evf = open(LOGS / f"sasia_events_{run}.log", "a")
    stats, confs, buf, files = Counter(), [], [], []; t0 = time.time()
    def mark(d):
        with donef.open("a") as f: f.write(d + "\n")
    def skip(e, reason, **kw):
        stats["skip_" + reason] += 1
        skipf.write(json.dumps({"ts": A.utcnow(), "run": run, "doc_id": e["doc_id"], "source": e["source"], "source_url": e["source_url"], "reason": reason, **kw}, ensure_ascii=False) + "\n"); skipf.flush()
    def job(e):
        M.mem_gate(lambda m: (evf.write(f"{A.utcnow()} {m}\n"), evf.flush()))
        d = did(e); lang = lang_of(e)
        oc = CACHE / f"{d}.ocr.json"
        try:
          if oc.exists():
            c = json.loads(oc.read_text()); texts, pc, secs, info, sha = c["texts"], c["page_conf"], c["secs"], c["fetch"], c["sha256"]
          else:
            b, info = fetch(e); sha = hashlib.sha256(b).hexdigest()
            with tempfile.TemporaryDirectory() as td:
                pdf = Path(td) / "x.pdf"; pdf.write_bytes(b)
                if e["source"].startswith("egazette") or e["source"] == "in_lsgkerala":
                    tl = subprocess.run(["pdftotext", "-l", "5", str(pdf), "-"], capture_output=True, text=True).stdout
                    if len(re.sub(r"\s", "", tl)) >= a.min_chars:
                        with lk: skip(e, "has_text", chars=len(tl)); mark(d)
                        return
                t = time.time(); texts, pc = ocr_pdf(pdf, a.max_pages, lang, best=(e["source"] == "in_lsgkerala")); secs = round(time.time() - t, 1)
            oc.write_text(json.dumps({"doc_id": e["doc_id"], "texts": texts, "page_conf": pc, "secs": secs, "fetch": info, "sha256": sha, "lang": lang}, ensure_ascii=False))
        except A.Skip as s:
            with lk:
                skip(e, s.reason, detail=s.detail[:200])
                if s.reason in ("html", "not_pdf", "blocked_cf"): mark(d)
            return
        except Exception as x:
            with lk: skip(e, "error", detail=repr(x)[:200])
            return
        text = "\n\f\n".join(texts).strip(); mean = round(sum(pc) / len(pc), 4) if pc else 0.0
        meta = {"text_source": "ocr", "ocr_engine": "tesseract", "ocr_engine_version": ver, "ocr_lang": lang, "ocr_model": "tessdata_best" if e["source"] == "in_lsgkerala" else "tessdata_fast", "ocr_confidence_mean": mean,
                "ocr_pages": len(pc), "ocr_low_conf_pages": sum(1 for c in pc if c < a.min_conf),
                "ocr_low_conf_page_list": [i + 1 for i, c in enumerate(pc) if c < a.min_conf], "ocr_dpi": 300,
                "source_pdf_sha256": sha, "source_pdf_url": e["source_url"], "ocr_fetch_via": info["via"], "ocr_seconds": secs}
        with lk:
            stats["docs"] += 1; stats["pages"] += len(pc); confs.append(mean)
            logf.write(json.dumps({"ts": A.utcnow(), "doc_id": e["doc_id"], "pages": len(pc), "conf": mean, "chars": len(text), "secs": secs}) + "\n"); logf.flush()
            reason = "near_empty" if len(re.sub(r"\s", "", text)) < a.min_chars else "low_conf" if mean < a.min_conf else \
                     "low_conf_indic" if is_indic(e) and mean < 0.6 else None
            if reason: skip(e, reason, conf=mean, pages=len(pc)); mark(d); return
            try: r = row_for(e, text, meta, info)
            except A.Skip as s:
                stats["held_issuer"] += 1; held.add(d)
                heldf.write(json.dumps({"ts": A.utcnow(), "doc_id": e["doc_id"], "source_url": e["source_url"], "reason": s.detail,
                                        "head": " / ".join([l for l in text.splitlines() if l.strip()][:6])[:300]}, ensure_ascii=False) + "\n"); heldf.flush()
                return
            err = validate_record(r)
            if err: skip(e, "invalid", detail=str(err)[:200]); return
            buf.append((r, d)); stats["written"] += 1
    tried = set(); last_ts = [""]
    def flush():
        nonlocal buf
        if not buf: return
        by = defaultdict(list)
        for r, d in buf: by[(r["country_code"], r["place_id"])].append((r, d))
        ts = A.utctag()
        while ts <= last_ts[0]: time.sleep(0.3); ts = A.utctag()
        last_ts[0] = ts
        for i, ((cc, pid), rs) in enumerate(sorted(by.items()), 1):
            pk = place_key(pid); (OUT / cc).mkdir(exist_ok=True)
            fn = OUT / cc / f"{pk}.ocr{ts}p{i:04d}.jsonl"
            if fn.exists(): raise RuntimeError(f"refusing to overwrite {fn}")
            tmp = fn.with_name("." + fn.name[:-6] + ".tmp.jsonl")
            with tmp.open("w", encoding="utf-8") as f:
                for r, _ in rs: f.write(json.dumps(r, ensure_ascii=False) + "\n")
                f.flush(); os.fsync(f.fileno())
            v = validate_file(tmp, expect_place_key=pk)
            if not v["ok"]: os.rename(tmp, LOGS / ("sasia_" + fn.name + ".invalid")); evf.write(f"INVALID {fn.name} {v['errors'][:2]}\n"); continue
            os.rename(tmp, fn); files.append(str(fn))
            for _, d in rs: mark(d); done.add(d)
        evf.write(f"{A.utcnow()} flushed {len(buf)} docs ts={ts}\n"); evf.flush(); buf = []
    def summary():
        el = time.time() - t0
        s = {"run": run, "taken": len(tried), "elapsed_s": round(el, 1), **stats, "mean_conf": round(sum(confs) / len(confs), 4) if confs else None,
             "docs_per_hour": round(stats["docs"] / el * 3600, 1) if el else 0, "files": files}
        (LOGS / f"sasia_summary_{run}.json").write_text(json.dumps(s, indent=1, ensure_ascii=False)); return s
    while True:
        while todo:
            chunk, todo = todo[:a.chunk], todo[a.chunk:]
            for e in chunk: tried.add(did(e))
            evf.write(f"{A.utcnow()} chunk {len(chunk)} pending={len(todo)}\n"); evf.flush()
            with ThreadPoolExecutor(a.workers) as ex: list(ex.map(job, chunk))
            flush(); summary()
        if not a.follow: break
        time.sleep(a.poll)
        todo = [e for e in load() if did(e) not in done and did(e) not in tried and (not a.sources or e["source"] in a.sources.split(","))]
    print(json.dumps(summary(), ensure_ascii=False))

if __name__ == "__main__":
    main()
