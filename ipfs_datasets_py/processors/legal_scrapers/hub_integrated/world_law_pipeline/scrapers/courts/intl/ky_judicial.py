"""KY: Cayman Islands Judicial Administration (judicial.ky, official WordPress site).
1) judges: Chief Justice, President/Judges of the Court of Appeal, Judges of the Grand Court, Chief Magistrate, Magistrates pages
   (name + official title only; entries labelled 'Former ...' are skipped).
2) rules: Grand Court Rules (2023 Revision) Vol I - Orders split into order/rule rows; other rule sets in force listed in the
   site's 'Court Rules In Force' document library -> one document-level row each (PDF kept under rules/raw/ky by sha256).
3) forms: Grand Court Rules (2023 Revision) Vol II - Forms split into per-form rows (form number, title, start page) pointing at the
   consolidated PDF (forms/ky/<sha>.pdf), plus standalone forms documents (Summary Jurisdiction (Forms) Rules 1976,
   Children Act (Forms) Rules 2013, Registered Land Rules forms RL9/RL10).
robots.txt: allows these pages/PDFs (crawl-delay 5 honoured); the document-library listing was read through /wp-json/wp/v2/media?...,
which falls under robots 'Disallow: /*?' -> those rows tagged robots_disallowed_user_authorized."""
import json, re, sys, os, hashlib, datetime, time, subprocess, shutil, requests, unicodedata
from bs4 import BeautifulSoup as B
ROOT = "/workspace/world_courts"; H = {"User-Agent": "Mozilla/5.0 (world_courts research; public court data)"}
BASE = "https://judicial.ky"; now = datetime.datetime.now(datetime.UTC).isoformat()
TERMS = "judicial.ky: (c) Cayman Islands Law Courts, all rights reserved; no open licence stated"
POL_OK = f"robots_allowed|{TERMS}"; POL_Q = f"robots_disallowed_user_authorized:/*? (wp-json media listing)|{TERMS}"
LIC = "Cayman Islands legislation / official court publication; no licence stated"
dry = "--dry" in sys.argv
def slug(s): return re.sub(r"[^a-z0-9]+", "-", unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()).strip("-")
def rjl(p): return [json.loads(l) for l in open(p)] if os.path.exists(p) else []
def get(u, **kw):
    r = requests.get(u, headers=H, timeout=120, **kw); time.sleep(5); r.raise_for_status(); return r
def app(p, rows):
    if dry or not rows: return
    with open(p, "a") as f:
        for x in rows: f.write(json.dumps(x, ensure_ascii=False) + "\n")
# ---------------- judges
PAGES = {"chief-justice": "ky-high-court", "president-of-the-court-of-appeal": "ky-court-of-appeal", "court-of-appeal-judges": "ky-court-of-appeal",
         "grand-court-judges": "ky-high-court", "chief-magistrate": "ky-lower-court", "magistrates": "ky-lower-court"}
OUTJ = f"{ROOT}/data/ky/ky_judges.jsonl"; have = {slug(o["name"]) for o in rjl(OUTJ)}; jrows = []
HON = re.compile(r"^(The Chief Justice of the Cayman Islands,\s*)?(Rt\.?\s*Hon\.?|Hon\.?|Her Hon\.?|His Hon\.?|The Hon\.?)\s+(Justice\s+|Sir\s+|Mrs\.?\s+|Ms\.?\s+|Mr\.?\s+)?", re.I)
for p, cid in PAGES.items():
    url = f"{BASE}/{p}/"; r = get(url); sha = hashlib.sha256(r.content).hexdigest(); s = B(r.text, "html.parser")
    for h in s.find_all("h3"):
        raw = re.sub(r"\s+", " ", h.get_text(" ", strip=True)); nx = h.find_next(string=lambda t: t and t.strip() and t.strip() != raw)
        title = re.sub(r"\s+", " ", nx.strip()) if nx else ""
        if "Chief Justice of the Cayman Islands" in raw and p != "chief-justice": continue
        if p == "chief-justice" and "Chief Justice of the Cayman Islands" in raw: title = "Chief Justice of the Cayman Islands"
        m_ = re.match(r"Former [^,]+,\s*(Judge of .+)$", title)
        if m_: title = m_.group(1)  # e.g. former Chief Justice now sitting as Judge of the Court of Appeal
        if not title or title.lower().startswith("read more") or title.lower().startswith("former"): continue
        name = HON.sub("", raw).strip()
        name = re.sub(r"\s+(KCMG|KC|QC|PC|CBE|OBE|MBE|JP)\b\.?", "", name).strip(" ,")
        if raw.startswith(("Rt", "Hon. Sir", "Hon. Justice Sir")) and "Sir" in raw and not name.startswith("Sir"): name = "Sir " + name
        k = slug(name.replace("Sir ", ""))
        if k in have: continue
        have.add(k)
        pt = "chief" if title.lower().startswith(("chief justice", "chief magistrate")) else "president" if title.lower().startswith("president") else \
             "magistrate" if "magistrate" in title.lower() else "associate"
        jrows.append({"judge_id": f"ky-{k}", "court_id": cid, "name": name, "honorific_as_listed": raw, "title": title, "position_type": pt,
            "term_start": None, "term_end": None, "status": "sitting", "jurisdiction": "KY", "roster_url": url, "source_url": url, "source_kind": "official",
            "site_policy": POL_OK, "retrieved_at": now, "needs_review": False, "extraction": "judicial.ky judiciary/magistracy roster page (name + official title only)",
            "license": "official public information; no licence stated", "source_sha256": sha})
app(OUTJ, jrows); print("judges added", len(jrows), [(x["name"], x["title"]) for x in jrows])
# ---------------- documents via media listing
media = []
for pg in (1, 2, 3):
    r = requests.get(f"{BASE}/wp-json/wp/v2/media", params={"search": "rules", "per_page": 100, "page": pg, "_fields": "id,source_url,title,date,mime_type"}, headers=H, timeout=60); time.sleep(5)
    if r.status_code != 200: break
    media += [m for m in r.json() if m["mime_type"] == "application/pdf"]
def fetch(u, d, ext="pdf"):
    if shutil.disk_usage("/workspace").free < 20 * 2**30: raise SystemExit("disk < 20 GB, pausing")
    c = get(u).content; sha = hashlib.sha256(c).hexdigest(); os.makedirs(d, exist_ok=True)
    p = f"{d}/{sha}.{ext}"
    if not os.path.exists(p): open(p, "wb").write(c)
    return p, sha, len(c)
# ---------------- rules
OUTR = f"{ROOT}/data/ky/ky_rules.jsonl"; oldr = {o["rule_id"] for o in rjl(OUTR)}; rrows = []
GCR1 = f"{BASE}/wp-content/uploads/Grand-Court-Rules-VolI-Orders-2023-Revision-1.pdf"
p1, sha1, _ = fetch(GCR1, f"{ROOT}/rules/raw/ky")
L = subprocess.run(["pdftotext", "-layout", p1, "-"], capture_output=True, text=True).stdout.split("\n")
st = next(i for i, l in enumerate(L) if i > 2000 and re.match(r"\s*ORDER 1\s*$", l)); en = max(i for i, l in enumerate(L) if l.startswith("ENDNOTES"))
noise = re.compile(r"^\s*c?\s*Revised as at 31st December, 2022\s*(Page \d+)?\s*c?\s*$|^\s*Page \d+\s+Revised as at|Grand Court Rules - Vol I [-–] Orders \(2023 Revision\)|^\s*c\s*$")
Bd = [l for l in L[st:en] if not noise.search(l)]
hd = re.compile(r"^(\d+[A-Z]?)\.\s+(.*?)\s*\(O\.\s?(\d+[A-Z]?),\s?r\.\s?(\d+[A-Z]?)\)\s*$")
heads = []
for i, l in enumerate(Bd):
    m = hd.match(l)
    if m: heads.append((m.group(3), m.group(4), m.group(2), i)); continue
    m2 = re.match(r"^\s{0,6}(\S.*?)\s*\(O\.\s?(\d+[A-Z]?),\s?r\.\s?(\d+[A-Z]?)\)\s*$", l)
    if m2 and i and re.match(r"^\d+[A-Z]?\.\s+\S", Bd[i-1]) and not l.startswith("     "):
        t = re.sub(r"^\d+[A-Z]?\.\s+", "", Bd[i-1]).strip() + " " + m2.group(1); heads.append((m2.group(2), m2.group(3), t, i))
ordt = {}
for i, l in enumerate(Bd):
    m = re.match(r"^\s*ORDER (\d+[A-Z]?)\s*$", l)
    if m:
        t = next((x.strip() for x in Bd[i+1:i+4] if x.strip()), ""); ordt[m.group(1)] = t
seen = set()
for k, (o, rn, t, i) in enumerate(heads):
    e = heads[k+1][3] - (1 if k + 1 < len(heads) and not hd.match(Bd[heads[k+1][3]]) else 0) if k + 1 < len(heads) else len(Bd)
    seg = Bd[i+1:e]
    while seg and (not seg[-1].strip() or re.match(r"^\s*ORDER \d+[A-Z]?\s*$", seg[-1]) or (seg[-1].strip().isupper() and len(seg[-1].strip()) > 3)): seg = seg[:-1]
    txt = re.sub(r"\s+", " ", " ".join(x.strip() for x in seg)).strip()
    txt = re.sub(r"\s*Grand Court Rules - Vol I - Orders\s*I?\s*\(2023 Revision\)\s*(ORDER \d+[A-Z]?)?\s*", " ", txt).strip()
    rid = f"ky-gcr-2023:o{o.lower()}r{rn.lower()}"
    if rid in seen or rid in oldr: continue
    seen.add(rid)
    rrows.append({"rule_id": rid, "rule_set_id": "ky-gcr-2023", "court_id": "ky-high-court", "jurisdiction": "KY",
        "rule_set": "Grand Court Rules (2023 Revision) Volume I - Orders", "rule_number": f"Order {o}, Rule {rn}", "title": re.sub(r"\s+", " ", t),
        "order_title": ordt.get(o), "text": txt or None, "effective_date": None, "pdf_path": os.path.relpath(p1, ROOT), "pdf_sha256": sha1, "source_sha256": sha1,
        "source_url": GCR1, "index_url": f"{BASE}/court-rules/", "source_kind": "official", "site_policy": POL_Q, "retrieved_at": now, "license": LIC,
        "language": "en", "version_note": "2023 Revision, revised as at 31 December 2022 (Supplement No. 1, Legislation Gazette No. 3, 19 Jan 2023)"})
print("gcr heads", len(heads), "rows", len(rrows), "orders", len({r['rule_number'].split(',')[0] for r in rrows}))
SKIP = re.compile(r"Vol ?II|Forms|RL\d|Practice ?Direction|WebsiteNotice|explanatory|Vol ?I\b|VolI-", re.I)
CID = lambda t: "ky-court-of-appeal" if "Court of Appeal" in t else "ky-lower-court" if re.search(r"Summary Court|Drug Rehab", t) else "ky-high-court"
docs = {}
for m in media:
    t = re.sub(r"\s+", " ", m["title"]["rendered"].replace("&#8211;", "–")).strip(); u = m["source_url"]
    if SKIP.search(t) or SKIP.search(u.rsplit("/", 1)[-1]) and "Orders" in u or "/practice-directions/" in u: continue
    if not re.search(r"[A-Z]", t): t = re.sub(r"-", " ", t).title().replace(" Rules ", " Rules ")
    key = slug(re.sub(r"\(.*?\)|\d{4}|revision|consolidation|latest|amended by errata|\b1\b", "", t, flags=re.I))
    if key in docs and docs[key][2] >= m["date"]: continue
    docs[key] = (t, u, m["date"])
dsha = {o.get("pdf_sha256") for o in rjl(OUTR) if o["rule_id"].startswith("ky-doc")}
for key, (t, u, d) in sorted(docs.items()):
    rid = f"ky-doc:{slug(t)}"
    if rid in oldr: continue
    try: p, sh, n = fetch(u, f"{ROOT}/rules/raw/ky")
    except Exception as e: print("fail", u, str(e)[:60]); continue
    if sh in dsha: continue  # same PDF uploaded under two titles
    dsha.add(sh)
    txt = subprocess.run(["pdftotext", "-layout", p, "-"], capture_output=True, text=True).stdout
    rrows.append({"rule_id": rid, "rule_set_id": f"ky-{slug(t)}", "court_id": CID(t), "jurisdiction": "KY", "rule_set": t, "rule_number": None,
        "title": t, "text": re.sub(r"[ \t]+", " ", txt).strip()[:200000] or None, "text_truncated": len(txt) > 200000, "effective_date": None,
        "pdf_path": os.path.relpath(p, ROOT), "pdf_sha256": sh, "source_sha256": sh, "file_bytes": n, "source_url": u, "index_url": f"{BASE}/court-rules/",
        "source_kind": "official", "site_policy": POL_Q, "retrieved_at": now, "license": LIC, "language": "en",
        "record_note": f"document-level row (whole rule set); listed in judicial.ky 'Court Rules In Force' library, media upload date {d[:10]}"})
app(OUTR, rrows); print("rules added", len(rrows))
# ---------------- forms
OUTF = f"{ROOT}/data/ky/ky_forms.jsonl"; oldf = rjl(OUTF); ofid = {o["form_id"] for o in oldf}; frows = []
GCR2 = f"{BASE}/wp-content/uploads/GrandCourtRules-VolII-Forms_2023-Revision.pdf"
p2, sha2, n2 = fetch(GCR2, f"{ROOT}/forms/ky")
L = subprocess.run(["pdftotext", "-layout", p2, "-"], capture_output=True, text=True).stdout.split("\n")
toc_end = next(i for i, l in enumerate(L) if re.match(r"^\s*1\.\s+These Rules may be cited", l))
app_ = None; cur = None; ents = []
for l in L[80:toc_end]:
    s_ = l.strip()
    m = re.match(r"^Appendix ([IVX]+)$", s_)
    if m: app_ = m.group(1); cur = None; continue
    m = re.match(r"^Form No\. (\d+[A-Z]?)\s+(\d+)$", s_)
    if m: cur = {"no": m.group(1), "page": int(m.group(2)), "t": "", "app": app_}; ents.append(cur); continue
    if cur is not None and s_ and not re.search(r"Revised as at|Arrangement of Rules|Grand Court Rules - Vol II", s_):
        if cur["t"] and re.search(r"\s\d+$", cur["t"]): continue
        cur["t"] = (cur["t"] + " " + s_).strip()
APPN = {"I": "General - Prescribed Forms (O.1, r.10)", "II": "Courts Funds Office - Prescribed Forms (O.1, r.10)", "III": "Costs - Prescribed Forms (O.1, r.10)"}
for e in ents:
    t = re.sub(r"\s+\d+$", "", e["t"]).strip(); fid = f"ky-gcr-2023-form-{e['no'].lower()}"
    if fid in ofid or not t: continue
    ofid.add(fid)
    frows.append({"form_id": fid, "court_id": "ky-high-court", "jurisdiction": "KY", "form_number": e["no"], "title": t,
        "category": (f"Grand Court Rules (2023 Revision) Vol II Appendix {e['app']}: {APPN.get(e['app'], '')}" if not e["no"].startswith("4") else
                     "Grand Court Rules (2023 Revision) Vol II: Status of Children Act parentage-testing forms (O.112) (listed after Appendix III; no appendix heading)"), "language": "en", "revision_date": "2022-12-31",
        "file_format": "pdf", "pdf_path": os.path.relpath(p2, ROOT), "pdf_sha256": sha2, "file_bytes": n2, "pdf_start_page": e["page"],
        "source_url": GCR2, "index_url": f"{BASE}/forms/", "source_kind": "official", "site_policy": POL_OK, "retrieved_at": now, "license": LIC,
        "record_note": "prescribed form inside the consolidated Grand Court Rules Vol II - Forms (2023 Revision) PDF; pdf_start_page = printed page number"})
SA = [("ky-summary-jurisdiction-forms-rules-1976", "Summary Jurisdiction (Forms) Rules, 1976", "ky-lower-court", f"{BASE}/wp-content/uploads/summary-jurisdiction-forms-rules-1976.pdf"),
      ("ky-children-act-forms-rules-2013", "Children Act (Forms) Rules 2013", "ky-high-court", f"{BASE}/wp-content/uploads/Children-Act-Forms-Rules-2013-Complete.pdf"),
      ("ky-summary-court-rules-2004-forms-1-9", "Summary Court Rules 2004 - Forms 1 to 9 (pp. 21-35)", "ky-lower-court", f"{BASE}/wp-content/uploads/The-Summary-Court-Rules-2004.pdf")]
for m in media:
    mm = re.search(r"Form-(RL\d+)\.pdf$", m["source_url"])
    if mm: SA.append((f"ky-registered-land-rules-form-{mm.group(1).lower()}", re.sub(r"\s+", " ", m["title"]["rendered"].replace("&#8211;", "–")), None, m["source_url"]))
for fid, t, cid, u in SA:
    if fid in ofid: continue
    try: p, sh, n = fetch(u, f"{ROOT}/forms/ky")
    except Exception as e: print("fail", u, str(e)[:60]); continue
    num = re.search(r"(RL\d+)", fid.upper()); ofid.add(fid)
    frows.append({"form_id": fid, "court_id": cid, "jurisdiction": "KY", "form_number": num.group(1) if num else None, "title": t,
        "category": "registered-land" if num else "court-forms-rules", "language": "en", "revision_date": None, "file_format": "pdf",
        "pdf_path": os.path.relpath(p, ROOT), "pdf_sha256": sh, "file_bytes": n, "source_url": u, "index_url": f"{BASE}/forms/", "source_kind": "official",
        "site_policy": POL_Q if num else POL_OK, "retrieved_at": now, "license": LIC,
        "record_note": "RL form title as given in site media library (RL9 file is captioned 'RL10 - Charge' on site)" if num and "RL9" in u else None})
app(OUTF, frows); print("forms added", len(frows), "gcr toc entries", len(ents))
