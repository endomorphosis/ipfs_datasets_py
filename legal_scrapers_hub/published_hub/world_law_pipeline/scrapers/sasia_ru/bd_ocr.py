"""BD Gazette OCR pass (2026-11-04): OCRs the PDFs queued by bd_gazette.py in _bd/bg_ocr_pending.jsonl (Bijoy/SutonnyMJ
text layers are unusable). Rasterizes with pdftoppm (300 dpi gray; pymupdf fallback if installed), runs tesseract
-l ben+eng (tessdata_fast ben in staging/sasia_ru/_tessdata), keeps the qid mapping from the pending entry and stages
schema-valid rows to staging/sasia_ru/BD/ exactly like bd_gazette.stage(). extra_metadata.text_method='ocr_tesseract'.
Resumable via _bd/bg_ocr_done.txt. Guards: tree RSS < 450 MB (pauses), /workspace free >= 10 GB (stops).
--pending _bd/bg_ocr_rematched.jsonl --include-suspect: re-matched entries (bd_rematch.py) whose qid is the upazila/municipality.
Usage: bd_ocr.py [--limit N] [--workers 2] [--stage] [--max-pages 40]"""
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import sys, os, re, json, time, shutil, argparse, subprocess, tempfile
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor
for k in ('http_proxy','https_proxy','HTTP_PROXY','HTTPS_PROXY','ALL_PROXY','all_proxy'): os.environ.pop(k, None)
os.environ['ARCHIVE_LANE'] = 'sasia_ru'
os.environ['TESSDATA_PREFIX'] = (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + '/staging/sasia_ru/_tessdata')
os.environ['OMP_THREAD_LIMIT'] = '1'
sys.path.insert(0, (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/pipeline")); sys.path.insert(0, (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/pipeline/scrapers/sasia_ru"))
from schema import validate_record
import pandas as pd
from bd_gazette import stage, doc_type, bn_ratio, BN_DIG, MON, BASE, D, free_gb
MEM_MB = 450
SUSPECT = re.compile(r"পৌরসভা|সিটি\s*কর্পোরেশন|ইউনিয়ন|উপজেলা")
def tree_rss_mb():
    me = os.getpid(); kids = {me}; tot = 0
    for p in os.listdir('/proc'):
        if not p.isdigit(): continue
        try:
            st = open(f'/proc/{p}/stat').read().rsplit(')', 1)[1].split()
            if int(p) == me or int(st[1]) in kids or int(st[3]) == os.getpgrp(): kids.add(int(p)); tot += int(st[21]) * 4096
        except Exception: pass
    return tot / 1e6
def mem_wait():
    while tree_rss_mb() > MEM_MB: time.sleep(5)
def ocr(pdfp, maxp):
    with tempfile.TemporaryDirectory(dir=D) as d:
        r = subprocess.run(["pdftoppm", "-r", "300", "-gray", "-l", str(maxp), "-png", pdfp, os.path.join(d, "pg")], capture_output=True, timeout=1200)
        ims = sorted(x for x in os.listdir(d) if x.startswith("pg"))
        if not ims:
            try:
                import fitz
                for i, pg in enumerate(fitz.open(pdfp)):
                    if i >= maxp: break
                    pg.get_pixmap(dpi=300, colorspace=fitz.csGRAY).save(os.path.join(d, f"pg-{i+1:04d}.png"))
                ims = sorted(x for x in os.listdir(d) if x.startswith("pg"))
            except ImportError: pass
        out = []
        for im in ims:
            mem_wait()
            out.append(subprocess.run(["tesseract", os.path.join(d, im), "-", "-l", "ben+eng", "--psm", "3"], capture_output=True, text=True, timeout=600).stdout)
            os.unlink(os.path.join(d, im))
        n = int(re.search(r"Pages:\s+(\d+)", subprocess.run(["pdfinfo", pdfp], capture_output=True, text=True).stdout or "Pages: 0").group(1))
        return "\n\f".join(out), len(ims), n
def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--limit", type=int, default=0); ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--stage", action="store_true"); ap.add_argument("--max-pages", type=int, default=40); ap.add_argument("--include-suspect", action="store_true"); ap.add_argument("--pending", default=f"{D}/bg_ocr_pending.jsonl"); a = ap.parse_args()
    c = pd.read_csv((_wl_os.environ.get("GLOBAL_MUNICIPALITIES_ROOT", "/workspace/global_municipalities") + '/global_municipalities_candidate.csv'), low_memory=False, usecols=['qid','place_name','admin_level','country_code'])
    PL = {q: (n, l) for q, n, l, cc in c[c.country_code == 'BD'][['qid','place_name','admin_level','country_code']].itertuples(index=False)}; del c
    donef = f"{D}/bg_ocr_done.txt"; done = set(open(donef).read().split()) if os.path.exists(donef) else set()
    todo = [json.loads(l) for l in open(a.pending)]
    todo = [x for x in todo if os.path.basename(x["pdf"])[:-4] not in done]
    if a.limit: todo = todo[:a.limit]
    # 2026-11-04: place_name from Wikidata English label (candidate CSV has bad labels, e.g. Q3349044 'Rony'); cached in _bd/wd_bd_en.jsonl
    import requests
    cf = f"{D}/wd_bd_en.jsonl"; en = {json.loads(l)["qid"]: json.loads(l)["en"] for l in open(cf)} if os.path.exists(cf) else {}
    need = sorted({x["qid"] for x in todo} - set(en))
    with open(cf, "a") as fo:
        for i in range(0, len(need), 50):
            for t in range(8):
                j = requests.get("https://www.wikidata.org/w/api.php", params=dict(action="wbgetentities", ids="|".join(need[i:i+50]), props="labels", languages="en", format="json"), headers={"User-Agent": "Mozilla/5.0 (compatible; WorldLawMunicipalResearch/1.0)"}, timeout=60).json()
                if "error" not in j: break
                time.sleep(10)
            for q, e in j.get("entities", {}).items():
                en[q] = e.get("labels", {}).get("en", {}).get("value"); fo.write(json.dumps({"qid": q, "en": en[q]}, ensure_ascii=False) + "\n")
    bn = {json.loads(l)["qid"]: (json.loads(l)["bn"] or [None])[0] for l in open(f"{D}/wd_bd_bn.jsonl")}
    def nm(q, n):  # an English label without a body-type word (e.g. Q3349044 'Rony') is distrusted -> Bengali label
        e = en.get(q)
        if e and re.search(r"Upazila|Upazilla|Municipality|Pourashava|Paurashava|Pourashava|District|Union|City Corporation|Thana|Sadar", str(e or "")): return e
        return bn.get(q) or e or n
    PL = {q: (nm(q, n), l) for q, (n, l) in PL.items()}
    print(json.dumps({"todo": len(todo), "done_before": len(done), "start": datetime.now().isoformat(timespec="seconds")}), flush=True)
    fd = open(donef, "a"); st = {"staged": 0, "n": 0, "skip": 0}
    def one(x):
        key = os.path.basename(x["pdf"])[:-4]
        if free_gb() < 10: return key, "disk_low", None
        if not os.path.exists(x["pdf_path"]): return key, "missing_pdf", None
        if x["qid"] not in PL: return key, "qid_not_in_candidates", None
        # Suspect mapping: qid is a district but the title is about a sub-district body ("X জেলার Y পৌরসভা") -> held, not done.
        if not a.include_suspect and PL[x["qid"]][1] == "district" and SUSPECT.search(x["title"]): return key, "held_suspect_district_map", None
        try: text, np_, ntot = ocr(x["pdf_path"], a.max_pages)
        except Exception as e: return key, f"ocr_error:{type(e).__name__}", None
        if len(text.strip()) < 200 or bn_ratio(text) < 0.3: return key, f"low_text(len={len(text.strip())},bn={bn_ratio(text):.2f})", None
        q = x["qid"]; nm, lvl = PL.get(q, (None, None))
        if nm is None: return key, "qid_not_in_candidates", None
        dm = re.match(r"(\d{2})-(\w{3})-(\d{4})", x["date"]); gid = x["gid"]
        num = re.search(r"(?:নং|S\.?\s*R\.?\s*O\.?[^০-৯0-9]*)\s*([০-৯0-9][^\s।,]*)", x["title"])
        rec = {"place_id": "wd:" + q, "country_code": "BD", "doc_id": f"bdgazette:{gid}:{key}", "source_platform": "bd_gazette",
               "source_url": f"{BASE}/bgpress/index.php/document/get_extraordinary/{gid}", "doc_type": doc_type(x["title"]), "language": "bn",
               "title_native": x["title"][:1000], "number": num.group(1).translate(BN_DIG) if num else None, "adopted_date": None,
               "published_date": f"{dm.group(3)}-{MON.get(dm.group(2), 1):02d}-{dm.group(1)}" if dm else None, "in_force": None,
               "consolidated": False, "content_format": "pdf_text", "text": text, "retrieved_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
               "source_policy": "robots_not_consulted", "source_official": True, "source_org": "Bangladesh Government Press (DPP)", "file_url": x["pdf"],
               "place_name": nm, "qid": q, "admin_level": lvl, "platform": "bd_gazette", "platform_place_id": str(gid),
               "extra_metadata": {"ministry": x["ministry"], "gazette_pages": x["pages"], "text_method": "ocr_tesseract",
                                  "ocr_note": "Text produced by Tesseract 5.5 OCR (ben+eng, tessdata_fast, 300 dpi); PDF text layer was Bijoy/SutonnyMJ legacy-encoded. Expect OCR errors.",
                                  "ocr_pages": np_, "pdf_pages": ntot, "ocr_truncated": np_ < ntot, **({"place_rematch": {"old_qid": x["old_qid"], "method": x["rematch"]}} if x.get("old_qid") else {})}}
        err = validate_record(rec)
        if err: return key, f"invalid:{str(err)[:200]}", None
        if not a.stage: return key, "ok_nostage", None
        return key, "staged" if (out := stage([rec], "wd:" + q)) else "rejected", out
    with ThreadPoolExecutor(max(1, min(2, a.workers))) as ex:
        for key, status, out in ex.map(one, todo):
            st["n"] += 1
            if status == "disk_low": print(json.dumps({"stop": "disk_low", "free_gb": round(free_gb(), 1)}), flush=True); os._exit(3)
            st["staged"] += status == "staged"
            if status in ("staged", "missing_pdf", "qid_not_in_candidates") or status.startswith(("low_text", "invalid")): fd.write(key + "\n"); fd.flush()
            print(json.dumps({"key": key, "status": status, "out": out, "rss_mb": round(tree_rss_mb()), **st, "ts": datetime.now().isoformat(timespec="seconds")}), flush=True)
    print(json.dumps({"end": datetime.now().isoformat(timespec="seconds"), **st}), flush=True)
if __name__ == "__main__": main()
