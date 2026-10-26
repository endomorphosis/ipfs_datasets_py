#!/usr/bin/env python3
"""Pakistan provincial law: KP Code (iso:PK-KP) and Sindh Laws (iso:PK-SD), live, robots-allowed.
Usage: collect_pk_prov.py kp|sd. 1 req/s, resumable (done ids in _work), PDFs deleted after text extraction."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import os, sys, re, json, time, html, subprocess, tempfile
import requests
from urllib.parse import urljoin
sys.path.insert(0, (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/pipeline/scrapers/national/us"))
from stage_util import write_part, check_space, utcstamp, now_iso
from robots import allowed, UA
SRC = sys.argv[1]
WORK = f"/workspace/world_law/staging/national/_work/PK/{SRC}"; os.makedirs(WORK, exist_ok=True)
DONE = os.path.join(WORK, "done.json"); PART = 200
S = requests.Session(); S.headers["User-Agent"] = UA
_last = [0.0]
def log(*a): print(time.strftime("%F %T"), *a, flush=True)
def get(url):
    if not allowed(url): log("robots disallow", url); return None
    for i in range(4):
        dt = time.time() - _last[0]
        if dt < 1.1: time.sleep(1.1 - dt)
        _last[0] = time.time()
        try:
            r = S.get(url, timeout=90)
            if r.status_code == 200: return r
            log("HTTP", r.status_code, url)
            if r.status_code in (403, 404, 410): return None
            if r.status_code == 429: time.sleep(60)
        except Exception as e: log("ERR", type(e).__name__, url)
        time.sleep(5 * (i + 1))
    return None
def strip(s): return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s))).strip()
def pdf_text(content):
    if not content.startswith(b"%PDF"): return None
    with tempfile.NamedTemporaryFile(suffix=".pdf", dir=WORK, delete=True) as f:
        f.write(content); f.flush()
        try: return subprocess.run(["pdftotext", "-layout", f.name, "-"], capture_output=True, timeout=180).stdout.decode("utf-8", "replace")
        except Exception: return None
def dtype(cat, title):
    c = (cat or "").lower(); t = (title or "").lower().strip(" .,")
    if re.search(r"\bacts?\b|ordinance|constitution", c): return "statute"
    if re.search(r"rule|regulation|bye-?law|notification|order", c): return "regulation"
    if re.search(r"\b(act|ordinance)\b[^a-z]*(\d{4})?$", t): return "statute"
    return "regulation" if re.search(r"\b(rules?|regulations?|bye-?laws?|notification)\b", t) else "statute"
def iso_date(d):
    for pat, fmt in ((r"(\d{2})-(\d{2})-(\d{4})", "dmy"),):
        m = re.search(pat, d or "")
        if m: return f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
    M = {m: i+1 for i, m in enumerate("jan feb mar apr may jun jul aug sep oct nov dec".split())}
    m = re.search(r"(\d{1,2})-([A-Za-z]{3})-(\d{4})", d or "")
    if m and m.group(2).lower() in M: return f"{m.group(3)}-{M[m.group(2).lower()]:02d}-{int(m.group(1)):02d}"
    m = re.search(r"\b(1[89]\d\d|20\d\d)\b", d or ""); return m.group(1) if m else None
def finish(rec, text):
    if text and len(text.strip()) > 80: rec["text"] = text
    else: rec["content_complete"] = False; rec.setdefault("extra_metadata", {})["note"] = "pdf without text layer (scanned)"
    return rec
# ---- KP ----
def kp_items():
    B = "https://kpcode.kp.gov.pk/homepage/"
    ids = {}
    for page, kind in (("chronological", "search_by_year"), ("rules", "search_by_year_rule")):
        r = get(B + page)
        for y in sorted(set(re.findall(kind + r"/(\d+)", r.text if r else ""))):
            rr = get(f"{B}{kind}/{y}")
            if not rr: continue
            for i, t in re.findall(r'lawDetails/(\d+)"[^>]*>([^<]*)', rr.text): ids.setdefault(i, strip(t))
    log("KP ids", len(ids))
    for i in sorted(ids, key=int): yield i, ids[i]
def kp_rec(i, t):
    url = f"https://kpcode.kp.gov.pk/homepage/lawDetails/{i}"
    r = get(url)
    if not r: return None
    s = r.text
    pdfs = re.findall(r'href="(https://kpcode\.kp\.gov\.pk/uploads/[^"]+\.pdf)"', s, re.I)
    body = strip(re.sub(r"<script.*?</script>|<style.*?</style>", "", s, flags=re.S))
    f = lambda k: (re.search(k + r":\s*(.*?)(?= Main Category:| Specific Category| Year | Promulgation Date:| This site|$)", body) or [None, None])[1]
    cat, year, prom = f("Main Category"), (re.search(r" Year (\d{4})", body) or [None, None])[1], f("Promulgation Date")
    title = t or (re.search(r"Civil law and procedure (.*?) Download", body) or [None, ""])[1]
    rec = {"place_id": "iso:PK-KP", "country_code": "PK", "doc_id": f"kpcode-{i}", "source_platform": "pk_kpcode",
           "source_url": url, "doc_type": dtype(cat, title), "language": "en", "title_native": title,
           "adopted_date": iso_date(prom) or year, "in_force": None, "consolidated": True, "content_format": "pdf_text",
           "retrieved_at": now_iso(), "extra_metadata": {"department": f("Department"), "category": cat, "pdf_url": pdfs[0] if pdfs else None}}
    text = None
    if pdfs:
        p = get(pdfs[0]); text = pdf_text(p.content) if p else None
    return finish(rec, text)
# ---- Sindh ----
def sd_items():
    B = "https://www.sindhlaws.gov.pk/"
    seen = {}
    for pg in ("ACT", "ORDINANCE", "RULE"):
        r = get(f"{B}Chrono.aspx?pg={pg}")
        for x, y in sorted(set(re.findall(r"SindhGazetteDetail\.aspx\?X=([A-Z]+)&(?:amp;)?Year=(\d+)", r.text if r else ""))):
            rr = get(f"{B}SindhGazetteDetail.aspx?X={x}&Year={y}")
            if not rr: continue
            for row in re.findall(r"<tr>(.*?)</tr>", rr.text, re.S):
                m = re.search(r"LawDocument\.aspx\?PubID=([A-Za-z0-9-]+)&(?:amp;)?Lang=EN", row)
                if not m: continue
                tds = re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)
                seen.setdefault(m.group(1), (strip(tds[1]) if len(tds) > 1 else "", strip(tds[-1]) if tds else "", x, strip(tds[0]) if tds else ""))
    log("SD ids", len(seen))
    for k in sorted(seen): yield k, seen[k]
def sd_rec(pid, meta):
    title, date, kind, no = meta
    url = f"https://www.sindhlaws.gov.pk/LawDocument.aspx?PubID={pid}&Lang=EN"
    p = get(f"https://www.sindhlaws.gov.pk/DownloadDocument.aspx?PubID={pid}&Lang=EN")
    rec = {"place_id": "iso:PK-SD", "country_code": "PK", "doc_id": f"sindhlaws-{pid}", "source_platform": "pk_sindhlaws",
           "source_url": url, "doc_type": "regulation" if kind == "RULE" else dtype("", title), "language": "en",
           "title_native": title or pid, "adopted_date": iso_date(date), "in_force": None, "consolidated": False,
           "content_format": "pdf_text", "retrieved_at": now_iso(),
           "extra_metadata": {"kind": kind, "serial_in_year": no, "pub_id": pid}}
    if no and kind != "RULE": rec["number"] = f"Sindh {kind.title()} No. {no}"
    return finish(rec, pdf_text(p.content) if p else None)
def main():
    done = set(json.load(open(DONE))) if os.path.exists(DONE) else set()
    items, mk, pl = (kp_items, kp_rec, "iso:PK-KP") if SRC == "kp" else (sd_items, sd_rec, "iso:PK-SD")
    stamp = utcstamp(); part = 0; buf = []; total = len(done); failed = 0
    def flush():
        nonlocal part, buf
        if not buf: return
        part += 1; path, k = write_part("PK", pl, f"{SRC}-{stamp}p{part:04d}", buf, log)
        if path: done.update(r["doc_id"] for r in buf)
        json.dump(sorted(done), open(DONE + ".tmp", "w")); os.replace(DONE + ".tmp", DONE); buf = []
    for key, meta in items():
        did = f"kpcode-{key}" if SRC == "kp" else f"sindhlaws-{key}"
        if did in done: continue
        check_space()
        try: rec = mk(key, meta)
        except Exception as e: log("fail", key, e); rec = None
        if rec is None: failed += 1; continue
        buf.append(rec); total += 1
        if len(buf) >= PART: flush()
        if total % 50 == 0: log("progress", total, "failed", failed)
    flush()
    log(f"{SRC.upper()} FINISHED docs={len(done)} failed={failed}")
if __name__ == "__main__": main()
