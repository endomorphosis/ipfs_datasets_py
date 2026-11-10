"""Kenya county legislation from new.kenyalaw.org (/legislation/ke-NNN/ -> /akn/ke-NNN/act/...).
robots: '*' allowed for /akn/ke-NNN/act, Crawl-delay 5; Content-Signal ai-train=no, ai-input=no (both tagged; rows staged before 2026-10-21 lack ai_input_no).
Usage: ke_kenyalaw.py <county codes comma> <max acts per county>"""
import re, sys, time, datetime, urllib.request, subprocess, html as H
from pathlib import Path
sys.path.insert(0, "/workspace/world_law/pipeline")
from archive import StagedWriter
sys.path.insert(0, "/workspace/world_law/pipeline/scrapers/counties"); from county_pdfstage import text_of, ScanStager; from schema import validate_record  # 2026-10-21: no _raw
ss = ScanStager()
UA = "Mozilla/5.0 (world_law county lane)"
import shutil
def disk_ok():
    free = shutil.disk_usage("/workspace").free / 1e9
    if free < 45: print("STOP: free disk %.1f GB < 45" % free, flush=True); return False
    return True
B = "https://new.kenyalaw.org"
def getb(u):
    time.sleep(5)
    return urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": UA}), timeout=120).read()
def get(u): return getb(u).decode("utf-8", "replace")
codes, cap = sys.argv[1].split(","), int(sys.argv[2])
now = datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
for c in codes:
    if not disk_ok(): break
    pid = f"iso:KE-{int(c):02d}"; w = StagedWriter("/workspace/world_law/staging/counties", "KE", pid, batch_prefix="kenyalaw", chunk=500)
    idx = get(f"{B}/legislation/ke-{c}/"); name = re.search(r"<h1[^>]*>\s*([^<]+)", idx); name = H.unescape(name.group(1).strip()) if name else pid
    acts = list(dict.fromkeys(re.findall(rf'href="(/akn/ke-{c}/act/[^"]+)"', idx)))[:cap]; ok = fail = 0
    for i, a in enumerate(acts):
        try:
            s = get(B + a)
            t = re.search(r"<title>\s*([^<]+)", s); t = H.unescape(t.group(1).strip()) if t else a
            m = re.search(r'(<div class="document-content__inner">.*?)<div class="[^"]*document-(?:enrichments|sidebar)', s, re.S) or re.search(r'(<la-akoma-ntoso.*?</la-akoma-ntoso>)', s, re.S)
            body = m.group(1) if m else ""
            if len(re.sub("<[^>]+>", "", body).strip()) < 100: body = ""
            mm = re.match(rf"/akn/ke-{c}/act/(\d{{4}})/([^/]+)/eng@([\d-]+)", a)
            rec = {"place_id": pid, "country_code": "KE", "doc_id": a.split("/eng@")[0], "doc_order": i,
                   "source_platform": "ke_kenyalaw_county", "source_url": B + a, "doc_type": "statute", "language": "en",
                   "title_native": t.split("|")[0].strip(), "number": f"Act No. {mm.group(2)} of {mm.group(1)}" if mm else None,
                   "effective_date": mm.group(3) if mm else None, "consolidated": True, "content_format": "html", "retrieved_at": now,
                   "source_policy": ["robots_allowed_rfc9309", "content_signal_ai_train_no", "content_signal_ai_input_no"], "source_official": True,
                   "source_org": "National Council for Law Reporting (Kenya Law)", "pdf_url": B + a + "/source.pdf",
                   "place_name": name, "iso_3166_2": f"KE-{int(c):02d}", "admin_level": "county", "platform": "ke_kenyalaw_county", "platform_place_id": f"ke-{c}"}
            if body: rec["html"] = '<div class="chunk-content">' + body + "</div>"
            else:
                data = getb(B + a + "/source.pdf"); txt = text_of(data)
                if data.find(b"%PDF-", 0, 1024) < 0: print("SKIP_NOTPDF", a); continue  # 2026-10-21 followup: never scanned_pdf for non-PDF
                rec.update(content_format="pdf_text")
                if len(txt.strip()) >= 200: rec["text"] = txt
                else:
                    rec.update(content_complete=False, scanned_pdf=True)
                    if not validate_record(rec): rec["pdf_path"] = ss.add(data, rec, now)
            e = w.add(rec); ok += not e; fail += bool(e)
            if e: print("INVALID", a, e)
        except Exception as ex: print("FAIL", a, ex); fail += 1
    print(c, name, "acts_listed", len(acts), "ok", ok, "fail", fail, w.flush(), "scan_batch", ss.flush(), flush=True)
