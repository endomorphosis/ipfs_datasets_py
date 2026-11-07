"""NP: Supreme Court of Nepal (supremecourt.gov.np, official; live again 2026-11-02) - 'सेवाग्राहीले अदालतमा पेस गर्ने निवेदनका ढाँचाहरु'
(templates of applications parties file in court) for the Supreme Court (supform), High Courts (acform), District Courts (dcform),
Foreign Employment Tribunal (baideshikform), and the judgment-execution (tahsil) templates of the Directorate of Judgment Execution (faisalatemp).
One row per distinct form per page: Word (.docx/.doc) preferred; PDF only when no Word version with the same title exists on that page.
Polite 2 s/request, honest UA, dedupe by sha256 / source_url, append-only. Usage: np_sc_nibedan_forms.py [--dry]"""
import json, re, html, os, sys, time, hashlib, datetime, shutil, subprocess, urllib.parse
ROOT = "/workspace/world_courts"; UA = "world_courts/0.1 (open court-data research; github.com/endomorphosis)"; B = "https://supremecourt.gov.np/web/"
OUT = f"{ROOT}/data/np/np_forms.jsonl"; FD = f"{ROOT}/forms/np"; os.makedirs(FD, exist_ok=True); dry = "--dry" in sys.argv
now = datetime.datetime.now(datetime.timezone.utc).isoformat()
POL = "robots_none|supremecourt.gov.np/robots.txt returns no rules (no restrictions); official Supreme Court of Nepal website, no terms of use stated"
PAGES = {"supform": ("np-supreme-court", "supreme-court-applications", "Supreme Court"),
         "acform": (None, "high-court-applications", "High Courts (उच्च अदालत)"),
         "dcform": (None, "district-court-applications", "District Courts (जिल्ला अदालत)"),
         "baideshikform": (None, "foreign-employment-tribunal-applications", "Foreign Employment Tribunal (वैदेशिक रोजगार न्यायाधिकरण)"),
         "faisalatemp": (None, "judgment-execution-templates", "Directorate of Judgment Execution templates used by court tahsil sections")}
EXT = {b"%PDF": "pdf", b"\xd0\xcf\x11\xe0": "doc", b"PK\x03\x04": "docx"}
def get(u, out=None):
    a = ["curl", "-sk", "-L", "-g", "-m", "180", "-A", UA] + (["-o", out] if out else []) + [u]
    r = subprocess.run(a, capture_output=True); time.sleep(2); return r.stdout
old = [json.loads(l) for l in open(OUT)] if os.path.exists(OUT) else []; shas = {r["pdf_sha256"] for r in old}; srcs = {r["source_url"] for r in old}
n = 0; skipped = []
for pg, (cid, cat, desc) in PAGES.items():
    t = get(B + pg).decode("utf-8", "replace"); s = t[t.find('class="entry"'):t.find("col-md-4 sidebar")]
    sec = None; links = []
    for m in re.finditer(r'<a[^>]*href="([^"]+)"[^>]*>(.*?)</a>', s, re.S):
        u, txt = m.group(1).strip(), re.sub(r"\s+", " ", html.unescape(re.sub("<[^>]+>", "", m.group(2)))).strip()
        if u.startswith("#"): continue
        if not re.search(r"\.(docx?|pdf)$", u, re.I): continue
        u = urllib.parse.urljoin(B + pg, u); u = re.sub(r"/web/index\.php/\.\./", "/web/", u)
        sub = "faujdari" if "/faujdari/" in u else "dewani" if "/dewani/" in u else None
        links.append((u, txt, sub))
    word_titles = {(x[1], x[2]) for x in links if re.search(r"\.docx?$", x[0], re.I)}
    for u, title, sub in links:
        if u.lower().endswith(".pdf") and (title, sub) in word_titles: continue
        if u in srcs: continue
        if shutil.disk_usage("/workspace").free < 20 * 2**30: raise SystemExit("disk < 20 GB, pausing downloads")
        b = get(urllib.parse.quote(u, safe=":/%")); ext = next((e for k, e in EXT.items() if b.startswith(k)), None)
        if not ext: skipped.append((u, len(b))); continue
        sha = hashlib.sha256(b).hexdigest()
        if sha in shas: continue
        fn = re.search(r"फाराम न\s*([०-९0-9]+)", urllib.parse.unquote(u)) or re.search(r"/(\d{1,3}) [^/]+$", urllib.parse.unquote(u))
        row = {"form_id": f"np-{sha[:16]}", "court_id": cid, "jurisdiction": "NP", "form_number": fn.group(1) if fn else None, "title": title,
               "category": cat + (f"/{sub}" if sub else ""), "language": "ne", "revision_date": None, "file_format": ext, "pdf_path": f"forms/np/{sha}.{ext}",
               "pdf_sha256": sha, "file_bytes": len(b), "source_url": u, "index_url": B + pg, "source_kind": "official", "site_policy": POL,
               "license": "Supreme Court of Nepal official application templates; government work, no licence stated",
               "description": f"Application/notice template for {desc}" + (f" ({'criminal' if sub == 'faujdari' else 'civil'})" if sub else ""), "retrieved_at": now}
        if not dry:
            open(f"{FD}/{sha}.{ext}", "wb").write(b)
            with open(OUT, "a") as f: f.write(json.dumps(row, ensure_ascii=False) + "\n")
        shas.add(sha); srcs.add(u); n += 1
    print(pg, "links", len(links), "total new so far", n, flush=True)
print("added", n, "skipped", len(skipped), skipped[:5])
