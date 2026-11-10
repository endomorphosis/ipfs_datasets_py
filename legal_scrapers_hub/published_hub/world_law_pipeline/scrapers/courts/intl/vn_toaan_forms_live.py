"""VN: TANDTC (toaan.gov.vn) 'Biểu mẫu tố tụng' procedural forms fetched LIVE from the official site (reachable again 2026-11-02).
Civil (linhVuc=45, NQ 01/2017/NQ-HĐTP annex), criminal (46, NQ 05/2017), administrative (47, NQ 02/2017). Statistics templates (104-110) not used.
Paginates listing pages politely (2 s), downloads only documents whose source_url / sha256 are not already in data/vn/vn_forms.jsonl. Append-only.
Usage: vn_toaan_forms_live.py [--dry]"""
import json, re, html, datetime, hashlib, os, sys, time, subprocess, shutil
ROOT = "/workspace/world_courts"; UA = "world_courts/0.1 (open court-data research; github.com/endomorphosis)"
OUT = f"{ROOT}/data/vn/vn_forms.jsonl"; FD = f"{ROOT}/forms/vn"; os.makedirs(FD, exist_ok=True)
now = datetime.datetime.now(datetime.timezone.utc).isoformat(); B = "https://www.toaan.gov.vn/webcenter/portal/tatc/"; dry = "--dry" in sys.argv
LV = {"45": "to-tung-dan-su", "46": "to-tung-hinh-su", "47": "to-tung-hanh-chinh"}
NQ = {"45": "NQ 01/2017/NQ-HĐTP (civil procedure forms)", "46": "NQ 05/2017/NQ-HĐTP (criminal procedure forms)", "47": "NQ 02/2017/NQ-HĐTP (administrative procedure forms)"}
POL = "robots_none|toaan.gov.vn serves no robots.txt (HTML page instead); official TANDTC portal, no restrictive terms found; fetched live 2 s/request"
CK = "/tmp/vn_toaan_cookies.txt"  # session cookie needed for ADF pagination
def get(u):
    r = subprocess.run(["curl", "-sk", "-L", "-m", "120", "-c", CK, "-b", CK, "-A", UA, u], capture_output=True); time.sleep(2); return r.stdout
docs = {}
for lv in LV:
    get(f"{B}bieu-mau-to-tung?linhVuc={lv}"); miss = 0
    for p in range(80):
        t = get(f"{B}bieu-mau-to-tung?selectedPage={p}&docType=BieuMau&linhVuc={lv}").decode("utf-8", "replace")
        new = 0
        for m in re.finditer(r'chi-tiet-bieu-mau\?dDocName=(\w+)"[^>]*>(.*?)</a>', t, re.S):
            if m.group(1) not in docs:
                docs[m.group(1)] = (re.sub(r"\s+", " ", html.unescape(re.sub("<[^>]+>", "", m.group(2)))).strip(), lv, f"{B}bieu-mau-to-tung?selectedPage={p}&docType=BieuMau&linhVuc={lv}"); new += 1
        miss = 0 if new else miss + 1
        if miss >= 3: break
    print("lv", lv, "pages", p, "docs total", len(docs), flush=True)
WBC = "/tmp/vn_forms_docs.json"  # titles listed earlier from Wayback snapshots (vn_toaan_forms_wb.py); fetched live here
if os.path.exists(WBC):
    for k, v in json.load(open(WBC)).items(): docs.setdefault(k, (v[0], v[1], v[2]))
json.dump(docs, open(f"{ROOT}/state/run_20261102_06/vn_live_docs.json", "w"), ensure_ascii=False)
old = [json.loads(l) for l in open(OUT)]; shas = {r["pdf_sha256"] for r in old}; srcs = {r["source_url"] for r in old}
# the official listing repeats the same form many times (re-uploads by different units); keep one row per (normalised title, format)
def tkey(t, ext): return (re.sub(r"[\s:.\-–]+", "", t.lower()), ext)
tkeys = {tkey(r["title"], r["file_format"]) for r in old}
EXT = {b"%PDF": "pdf", b"\xd0\xcf\x11\xe0": "doc", b"PK\x03\x04": "docx"}; n = dup = bad = 0
for did, (title, lv, lu) in docs.items():
    src = f"https://www.toaan.gov.vn/webcenter/ShowProperty?nodeId=/UCMServer/{did}"
    if src in srcs: continue
    if shutil.disk_usage("/workspace").free < 20 * 2**30: raise SystemExit("disk < 20 GB, pausing downloads")
    b = get(src); ext = next((e for k, e in EXT.items() if b.startswith(k)), None)
    if not ext: bad += 1; print("not a document", did); continue
    sha = hashlib.sha256(b).hexdigest()
    if sha in shas or tkey(title, ext) in tkeys: dup += 1; continue
    tkeys.add(tkey(title, ext))
    fn = re.match(r"^M[ẫâ]u(?: số)?\s*([0-9]+[a-zđA-Z]?\s*-?\s*[A-Z]{2,3})", title)
    row = {"form_id": f"vn-{sha[:16]}", "court_id": None, "jurisdiction": "VN", "form_number": fn.group(1).replace(" ", "") if fn else None,
           "title": title, "category": LV[lv], "language": "vi", "revision_date": None, "file_format": ext, "pdf_path": f"forms/vn/{sha}.{ext}",
           "pdf_sha256": sha, "file_bytes": len(b), "source_url": src, "index_url": lu, "legal_basis": NQ[lv],
           "license": "Official court form (Vietnam: legal normative documents & official forms not protected by copyright, Law on IP art. 15)",
           "site_policy": POL, "source_kind": "official", "retrieved_at": now}
    print("new", did, title[:70])
    if not dry:
        open(f"{FD}/{sha}.{ext}", "wb").write(b)
        with open(OUT, "a") as f: f.write(json.dumps(row, ensure_ascii=False) + "\n")
    shas.add(sha); srcs.add(src); n += 1
print("added", n, "dup_sha", dup, "bad", bad)
