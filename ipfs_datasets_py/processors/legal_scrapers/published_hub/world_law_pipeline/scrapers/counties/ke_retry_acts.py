"""Retry specific failed Kenya county Acts live (same record shape as ke_kenyalaw.py; robots '*' Allow /, Crawl-delay 5 honoured).
Acts still failing are written to an archive_retry.py config (archive_policy=archived_live_fetch_failed, source.pdf URLs).
Usage: ke_retry_acts.py <county code e.g. 001> <act path> [<act path> ...]"""
import re, sys, json, time, datetime, urllib.request, subprocess, html as H
from pathlib import Path
sys.path.insert(0, "/workspace/world_law/pipeline")
from archive import StagedWriter
HERE = Path(__file__).parent
RAW = Path("/workspace/world_law/staging/counties/_raw/ke_kenyalaw"); RAW.mkdir(parents=True, exist_ok=True)
UA = "Mozilla/5.0 (world_law county lane)"; B = "https://new.kenyalaw.org"
def getb(u, tries=3):
    for k in range(tries):
        time.sleep(5 * (k + 1))
        try: return urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": UA}), timeout=180).read()
        except Exception as ex:
            if k == tries - 1: raise
            print("  retry", k + 1, u, ex, flush=True)
def get(u): return getb(u).decode("utf-8", "replace")
c, acts = sys.argv[1], sys.argv[2:]
pid = f"iso:KE-{int(c):02d}"; now = datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
w = StagedWriter("/workspace/world_law/staging/counties", "KE", pid, batch_prefix="kenyalaw-retry", chunk=500)
idx = get(f"{B}/legislation/ke-{c}/"); name = re.search(r"<h1[^>]*>\s*([^<]+)", idx); name = H.unescape(name.group(1).strip()) if name else pid
order = list(dict.fromkeys(re.findall(rf'href="(/akn/ke-{c}/act/[^"]+)"', idx)))
failed = []
for a in acts:
    try:
        s = get(B + a)
        t = re.search(r"<title>\s*([^<]+)", s); t = H.unescape(t.group(1).strip()) if t else a
        m = re.search(r'(<div class="document-content__inner">.*?)<div class="[^"]*document-(?:enrichments|sidebar)', s, re.S) or re.search(r'(<la-akoma-ntoso.*?</la-akoma-ntoso>)', s, re.S)
        body = m.group(1) if m else ""
        if len(re.sub("<[^>]+>", "", body).strip()) < 100: body = ""
        mm = re.match(rf"/akn/ke-{c}/act/(\d{{4}})/([^/]+)/eng@([\d-]+)", a)
        rec = {"place_id": pid, "country_code": "KE", "doc_id": a.split("/eng@")[0], "doc_order": order.index(a) if a in order else None,
               "source_platform": "ke_kenyalaw_county", "source_url": B + a, "doc_type": "statute", "language": "en",
               "title_native": t.split("|")[0].strip(), "number": f"Act No. {mm.group(2)} of {mm.group(1)}" if mm else None,
               "effective_date": mm.group(3) if mm else None, "consolidated": True, "content_format": "html", "retrieved_at": now,
               "source_policy": ["robots_allowed_rfc9309", "content_signal_ai_train_no"], "source_official": True,
               "source_org": "National Council for Law Reporting (Kenya Law)", "pdf_url": B + a + "/source.pdf",
               "place_name": name, "iso_3166_2": f"KE-{int(c):02d}", "admin_level": "county", "platform": "ke_kenyalaw_county", "platform_place_id": f"ke-{c}"}
        if body: rec["html"] = '<div class="chunk-content">' + body + "</div>"
        else:
            p = RAW / (a.split("/eng@")[0].strip("/").replace("/", "_") + ".pdf"); p.write_bytes(getb(B + a + "/source.pdf"))
            txt = subprocess.run(["pdftotext", "-layout", str(p), "-"], capture_output=True, text=True).stdout
            rec.update(content_format="pdf_text", raw_path=str(p))
            if len(txt.strip()) >= 200: rec["text"] = txt
            elif p.read_bytes().find(b"%PDF-", 0, 1024) < 0: print("SKIP_NOTPDF", a, flush=True); continue  # 2026-10-21 followup
            else: rec.update(content_complete=False, scanned_pdf=True)
        e = w.add(rec); print("INVALID " + e if e else "OK", rec["content_format"], a, flush=True)
        if e: failed.append(a)
    except Exception as ex: print("FAIL", a, ex, flush=True); failed.append(a)
print("written:", w.flush(), "ok", len(acts) - len(failed), "fail", len(failed), flush=True)
if failed:
    cfgp = HERE / f"ke_retry_ke-{c}_archive.json"
    json.dump(dict(country_code="KE", place_id=pid, place_name=name, iso_3166_2=f"KE-{int(c):02d}", admin_level="county", language="en", doc_type="statute",
                   platform="ke_kenyalaw_county", source_org="National Council for Law Reporting (Kenya Law)", archive_policy="archived_live_fetch_failed",
                   urls=[B + a + "/source.pdf" for a in failed]), open(cfgp, "w"), ensure_ascii=False, indent=1)
    print("ARCHIVE_CFG", cfgp, flush=True)
