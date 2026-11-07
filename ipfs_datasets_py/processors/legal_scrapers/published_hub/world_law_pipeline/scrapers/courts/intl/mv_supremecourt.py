"""MV: Supreme Court of the Maldives (www.supremecourt.mv; robots.txt allows all but /admin,/api/admin,/auth).
1) judges: /justices (Chief Justice + Justices; English name, Dhivehi name, official title only).
2) forms: /services/forms (SC-xx court forms, DOCX downloads, versioned) -> forms/mv/<sha>.docx.
3) rules: /rules/regulations (paginated list of Supreme Court regulations/rules with number + status) -> one document-level row per
   regulation PDF (rules/raw/mv/<sha>.pdf; text mostly Dhivehi/Thaana, pdftotext output kept when it yields text)."""
import json, re, sys, os, hashlib, datetime, time, subprocess, shutil, requests, unicodedata, urllib.parse
from bs4 import BeautifulSoup as B
ROOT = "/workspace/world_courts"; H = {"User-Agent": "Mozilla/5.0 (world_courts research; public court data)"}; BASE = "https://www.supremecourt.mv"
now = datetime.datetime.now(datetime.UTC).isoformat(); dry = "--dry" in sys.argv
POL = "robots_allowed|supremecourt.mv: no licence stated"; LIC = "Supreme Court of the Maldives official publication; no licence stated"
def slug(s): return re.sub(r"[^a-z0-9]+", "-", unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()).strip("-")
def rjl(p): return [json.loads(l) for l in open(p)] if os.path.exists(p) else []
def get(u):
    r = requests.get(u, headers=H, timeout=120); time.sleep(3); r.raise_for_status(); return r
def app(p, rows):
    if dry or not rows: return
    with open(p, "a") as f:
        for x in rows: f.write(json.dumps(x, ensure_ascii=False) + "\n")
def fetch(u, d, ext):
    if shutil.disk_usage("/workspace").free < 20 * 2**30: raise SystemExit("disk < 20 GB, pausing")
    c = get(u).content; sha = hashlib.sha256(c).hexdigest(); os.makedirs(d, exist_ok=True); p = f"{d}/{sha}.{ext}"
    if not os.path.exists(p): open(p, "wb").write(c)
    return p, sha, len(c)
THA = re.compile(r"[\u0780-\u07BF]")
# ---- judges
U = f"{BASE}/justices"; r = get(U); sha = hashlib.sha256(r.content).hexdigest(); s = B(r.text, "html.parser")
for x in s(["script", "style"]): x.decompose()
T = [t for t in s.get_text("\n", strip=True).split("\n") if t.strip()]
OUTJ = f"{ROOT}/data/mv/mv_judges.jsonl"; have = {o["judge_id"] for o in rjl(OUTJ)}; jr = []
for i, t in enumerate(T):
    if t in ("Chief Justice of the Maldives", "Justice of Supreme Court of the Maldives") and i + 3 < len(T):
        tdv = T[i+1] if THA.search(T[i+1]) else None; en = T[i+2]; dv = T[i+3] if THA.search(T[i+3]) else None
        if THA.search(en) or len(en) < 4: continue
        jid = f"mv-{slug(en)}"
        if jid in have: continue
        have.add(jid)
        jr.append({"judge_id": jid, "court_id": "mv-supreme-court", "name": en, "name_local": dv, "title": t, "title_local": tdv,
            "position_type": "chief" if t.startswith("Chief") else "associate", "term_start": None, "term_end": None, "status": "sitting",
            "jurisdiction": "MV", "roster_url": U, "source_url": U, "source_kind": "official", "site_policy": POL, "retrieved_at": now,
            "needs_review": False, "extraction": "supremecourt.mv /justices page (names + official titles only)",
            "license": "official public information; no licence stated", "source_sha256": sha})
app(OUTJ, jr); print("judges added", len(jr), [x["name"] for x in jr])
# ---- forms
U = f"{BASE}/services/forms"; html = get(U).text; s = B(html, "html.parser")
links = {}
for a in s.find_all("a", href=True):
    m = re.search(r"/files/forms/([A-Z]{2,3}-\d+[A-Z]?)/[^\"\\]+\.(docx?|pdf)", a["href"])
    if m: links.setdefault(m.group(1), urllib.parse.urljoin(BASE, m.group(0)))
for x in s(["script", "style"]): x.decompose()
T = [t for t in s.get_text("\n", strip=True).split("\n") if t.strip()]
OUTF = f"{ROOT}/data/mv/mv_forms.jsonl"; old = rjl(OUTF); osha = {o["pdf_sha256"] for o in old}; ofid = {o["form_id"] for o in old}; fr = []
for i, t in enumerate(T):
    if not re.match(r"^[A-Z]{2,3}-\d+[A-Z]?$", t) or t not in links: continue
    ver = T[i+2] if T[i+1] == "v" else None; en = T[i+3] if ver else T[i+1]; dv = T[i+4] if ver and THA.search(T[i+4]) else None
    fid = f"mv-sc-{t.lower()}"
    if fid in ofid: continue
    u = links[t]; ext = u.rsplit(".", 1)[-1].lower()
    try: p, sh, n = fetch(u, f"{ROOT}/forms/mv", ext)
    except Exception as e: print("fail", u, str(e)[:60]); continue
    if sh in osha: continue
    osha.add(sh); ofid.add(fid)
    fr.append({"form_id": fid, "court_id": "mv-supreme-court", "jurisdiction": "MV", "form_number": t, "title": en, "title_local": dv,
        "category": "supreme-court-forms", "language": "dv", "languages": ["dv", "en"], "version": ver, "revision_date": None, "file_format": ext,
        "pdf_path": os.path.relpath(p, ROOT), "pdf_sha256": sh, "file_bytes": n, "source_url": u, "index_url": U, "source_kind": "official",
        "site_policy": POL, "retrieved_at": now, "license": LIC})
app(OUTF, fr); print("forms added", len(fr))
# ---- regulations (document-level)
OUTR = f"{ROOT}/data/mv/mv_rules.jsonl"; oldr = rjl(OUTR); orid = {o["rule_id"] for o in oldr}; rsha = {o.get("pdf_sha256") for o in oldr}; rr = []
for pg in range(1, 15):
    U = f"{BASE}/rules/regulations" + (f"?page={pg}" if pg > 1 else ""); s = B(get(U).text, "html.parser")
    L = [a for a in s.find_all("a", href=True) if a["href"].lower().endswith(".pdf") and a.get_text(strip=True)]
    if not L: break
    for a in L:
        parts = [x.strip() for x in a.get_text("|", strip=True).split("|") if x.strip()]
        en = next((x for x in parts if not THA.search(x)), parts[0]); dv = next((x for x in parts if THA.search(x)), None)
        pv = [x.strip() for x in a.find_all_previous(string=True, limit=10) if x.strip() and not x.strip().startswith("$RS") and not x.strip().startswith("PDF")]
        status = next((x for x in pv[:4] if x in ("In Force", "Revoked")), None)
        num = next((x for x in pv[:5] if re.match(r"^(\d{4}[/-][A-Z0-9-]+|\d{4}/R-\d+)$", x)), None)
        u = urllib.parse.urljoin(BASE, a["href"]); rid = f"mv-sc-reg:{slug(num or '')}:{slug(en)[:80]}".replace("::", ":")
        if rid in orid: continue
        try: p, sh, n = fetch(u, f"{ROOT}/rules/raw/mv", "pdf")
        except Exception as e: print("fail", u, str(e)[:60]); continue
        if sh in rsha: continue
        rsha.add(sh); orid.add(rid)
        if not num: status = None  # cards without a number (page 2+) show no reliable status next to them
        rep = re.search(r"\(Repealed\s*-\s*([^)]+)\)", en)
        if rep: status = "Repealed"
        txt = subprocess.run(["pdftotext", "-layout", p, "-"], capture_output=True, text=True).stdout.strip()
        rr.append({"rule_id": rid, "rule_set_id": rid, "court_id": "mv-supreme-court", "jurisdiction": "MV", "rule_set": en, "rule_set_local": dv,
            "rule_number": num, "title": en, "title_local": dv, "status": {"In Force": "in_force", "Revoked": "revoked", "Repealed": "repealed"}.get(status, status),
            "text": re.sub(r"[ \t]+", " ", txt)[:200000] if len(txt) > 200 else None, "effective_date": None, "pdf_path": os.path.relpath(p, ROOT),
            "pdf_sha256": sh, "source_sha256": sh, "file_bytes": n, "source_url": u, "index_url": U, "source_kind": "official", "site_policy": POL,
            "retrieved_at": now, "license": LIC, "language": "dv",
            "record_note": "document-level row (whole regulation, as listed on Supreme Court 'Regulations' page); text layer, if any, is mostly Dhivehi"})
app(OUTR, rr); print("rules added", len(rr), "in force", sum(1 for x in rr if x["status"] == "in_force"))
