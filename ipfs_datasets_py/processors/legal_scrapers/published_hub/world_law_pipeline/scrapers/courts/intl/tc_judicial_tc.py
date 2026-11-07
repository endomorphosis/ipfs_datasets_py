"""TC: Judiciary of the Turks and Caicos Islands (judicial.tc, official; robots.txt disallows only Joomla system dirs) -
forms (Supreme Court + Magistrate's Court pages), court rules and practice directions (practice-directions/* pages; documents via the
site's own edocman 'fdocument' links), and judges (about/members page + gov.tc AGC speech of 5 May 2026 for the current bench).
Rules of the Supreme Court 2000 (OCR text of scanned PDF) -> Order-level rows; other rules/PDs -> one row per document.
Usage: tc_judicial_tc.py [--dry]  (re-downloads only files missing from rules/raw/tc_judicial/dl)"""
import json, re, sys, os, time, hashlib, subprocess, datetime, shutil, html
ROOT = "/workspace/world_courts"; RAW = f"{ROOT}/rules/raw/tc_judicial"; DL = f"{RAW}/dl"; B = "https://judicial.tc"
UA = "world_courts/0.1 (open court-data research; github.com/endomorphosis)"
POL = "robots_allowed|judicial.tc robots.txt disallows only Joomla system dirs (/administrator/, /components/ ...), not /component/edocman; Judiciary of TCI website, no terms of use stated"
now = datetime.datetime.now(datetime.timezone.utc).isoformat(); dry = "--dry" in sys.argv
items = json.load(open(f"{RAW}/items.json"))
def fetch(i):
    p = f"{DL}/{i['slug']}"
    if not os.path.exists(p):
        if shutil.disk_usage("/workspace").free < 20 * 2**30: raise SystemExit("disk < 20 GB, pausing downloads")
        subprocess.run(["curl", "-sL", "-A", UA, "-m", "300", "-o", p, f"{B}/component/edocman/{i['slug']}/fdocument?Itemid=9999"], check=True); time.sleep(2)
    return p
def pdftext(p, layout=True): return subprocess.run(["pdftotext"] + (["-layout"] if layout else []) + [p, "-"], capture_output=True, text=True).stdout
def rjl(p): return [json.loads(l) for l in open(p) if l.strip()] if os.path.exists(p) else []
def app(p, rows):
    if dry or not rows: return
    with open(p, "a") as f:
        for r in rows: f.write(json.dumps(r, ensure_ascii=False) + "\n")
src_of = lambda i: f"{B}/component/edocman/{i['slug']}/fdocument?Itemid=9999"
idx_of = {"form-sc": "/forms/supreme-court", "form-mc": "/forms/magistrates-court", "rules": "/practice-directions/rules",
          "pd-sc": "/practice-directions/supreme-court", "pd-ca": "/practice-directions/court-of-appeal"}
# ---------------- forms
FO = f"{ROOT}/data/tc/tc_forms.jsonl"; FD = f"{ROOT}/forms/tc"; os.makedirs(FD, exist_ok=True)
have = {r["pdf_sha256"] for r in rjl(FO)}; frows = []
SKIPF = {"civil-procedure-fees-order-2020", "contents-of-divorce-petition-guidance"}  # not forms (fees order -> rules; guidance note)
for i in items:
    if not i["kind"].startswith("form") or i["slug"] in SKIPF: continue
    p = fetch(i); b = open(p, "rb").read(); sha = hashlib.sha256(b).hexdigest()
    if sha in have: continue
    have.add(sha)
    if not dry: shutil.copy(p, f"{FD}/{sha}.pdf")
    t = i["title"].replace("-", " ") if i["title"].isupper() and "-" in i["title"] else i["title"]
    m = re.match(r"Form (\d+)\s*[–-]\s*(.*)", t)
    cat = "family/domestic-violence" if ("PROTECTION" in t.upper() or re.match(r"Form \d", t)) else "family" if re.search(r"ACCESS|ADOPTION|MAINTENANCE|Divorce", t, re.I) \
        else "legal-aid" if "Legal Aid" in t or "Roster" in t else "criminal" if "Bail" in t else "civil"
    frows.append({"form_id": f"tc-{sha[:16]}", "court_id": "tc-supreme-court" if i["kind"] == "form-sc" else "tc-lower-court", "jurisdiction": "TC",
        "form_number": m.group(1) if m else None, "title": (m.group(2) if m else t).strip().title() if t.isupper() else (m.group(2) if m else t).strip(),
        "category": cat, "language": "en", "revision_date": None, "file_format": "pdf", "pdf_path": f"forms/tc/{sha}.pdf", "pdf_sha256": sha,
        "file_bytes": len(b), "source_url": src_of(i), "index_url": B + idx_of[i["kind"]], "source_kind": "official", "site_policy": POL,
        "license": "Judiciary of the Turks and Caicos Islands official court form; no licence stated", "retrieved_at": now,
        "description": "Magistrate's Court form" if i["kind"] == "form-mc" else "Supreme Court form"})
app(FO, frows); print("forms new", len(frows))
# ---------------- rules
RO = f"{ROOT}/data/tc/tc_rules.jsonl"; haver = {r["rule_id"] for r in rjl(RO)}; rrows = []; seen_sha = set()
SKIPR = {"probate-administration-rules"}  # same rules already ingested from AGC revised laws (tc_agc_court_rules.py)
LIC = "Turks and Caicos Islands court rules / practice directions published by the Judiciary; no open licence stated"
def rrow(rid, sid, rs, num, title, text, i, sha, cid, eff=None, review=True, note=None):
    return {"rule_id": rid, "rule_set_id": sid, "court_id": cid, "jurisdiction": "TC", "rule_set": rs, "rule_number": num, "title": title, "part": None,
            "text": text[:150000], "effective_date": eff, "pdf_path": f"rules/raw/tc_judicial/dl/{i['slug']}", "pdf_sha256": sha, "source_sha256": sha,
            "source_url": src_of(i), "index_url": B + idx_of[i["kind"]], "source_kind": "official", "site_policy": POL, "license": LIC, "retrieved_at": now,
            "language": "en", "needs_review": review, "version_note": note}
for i in items:
    if i["kind"].startswith("form") and i["slug"] != "civil-procedure-fees-order-2020": continue
    if i["slug"] in SKIPR: continue
    p = fetch(i); sha = hashlib.sha256(open(p, "rb").read()).hexdigest()
    if sha in seen_sha: continue
    seen_sha.add(sha)
    cid = "tc-court-of-appeal" if i["kind"] == "pd-ca" or "court-of-appeal" in i["slug"] else "tc-supreme-court"
    if i["slug"] == "rules-of-the-supreme-court-2000":
        L = pdftext(p).splitlines(); hs = [(j, re.match(r"^\s*ORDER\s+(\d{1,3}[A-Z]?)\s*$", l).group(1)) for j, l in enumerate(L) if re.match(r"^\s*ORDER\s+(\d{1,3}[A-Z]?)\s*$", l)]
        endall = next((j for j in range(hs[-1][0], len(L)) if re.match(r"^\s*APPENDIX", L[j])), len(L))
        pre = "\n".join(L[:hs[0][0]]).strip()
        rrows.append(rrow("tc-rsc2000:preface", "tc-rsc2000", "Rules of the Supreme Court 2000 (Turks and Caicos Islands)", "Preface", "Preface and arrangement", pre, i, sha, "tc-supreme-court", "2000-03-01", True, "OCR text of scanned official PDF (judicial.tc)"))
        for k, (j, o) in enumerate(hs):
            e = hs[k + 1][0] if k + 1 < len(hs) else endall
            body = re.sub(r"\n{3,}", "\n\n", "\n".join(L[j + 1:e])).strip()
            title = next((x.strip() for x in body.splitlines() if len(x.strip()) > 3), "")[:150]
            rrows.append(rrow(f"tc-rsc2000:o{o}".lower(), "tc-rsc2000", "Rules of the Supreme Court 2000 (Turks and Caicos Islands)", f"Order {o}", title.title() if title.isupper() else title,
                              body, i, sha, "tc-supreme-court", "2000-03-01", True, "OCR text of scanned official PDF (judicial.tc); Order-level split; based on English RSC as at 1 Jan 1999"))
        if endall < len(L):
            rrows.append(rrow("tc-rsc2000:appendix", "tc-rsc2000", "Rules of the Supreme Court 2000 (Turks and Caicos Islands)", "Appendix", "Appendix (prescribed forms)",
                              "\n".join(L[endall:]).strip(), i, sha, "tc-supreme-court", "2000-03-01", True, "OCR text; appendix of prescribed forms"))
        continue
    txt = re.sub(r"[ \t]+", " ", pdftext(p, False)); txt = re.sub(r"\n{3,}", "\n\n", txt).strip()
    if len(txt) < 200: txt = None
    t = i["title"]; t = t.title() if t.isupper() else t
    sid = "tc-" + ("pd-" if i["kind"].startswith("pd") else "") + i["slug"][:80]
    rrows.append(rrow(f"{sid}:doc", sid, t, None, t, txt or "", i, sha, cid, None, True,
                      ("document-level row; " if txt else "scanned PDF without text layer (no OCR on box); ") + f"listed on {B}{idx_of[i['kind']]}"))
rrows = [r for r in rrows if r["rule_id"] not in haver]
app(RO, rrows); print("rules new", len(rrows), "no-text", sum(1 for r in rrows if not r["text"]))
# ---------------- judges (names + official titles only)
JO = f"{ROOT}/data/tc/tc_judges.jsonl"; havej = {r["judge_id"] for r in rjl(JO)}
SP = "https://www.gov.tc/agc/latest-speeches/speech-by-the-hon-attorney-general-on-the-administration-of-oaths-of-the-chief-justice-designate-of-the-turks-and-caicos-islands-hon-mrs-justice-yonette-cummings-edwards"
MEM = f"{B}/about/members"
J = [  # name, court, title, position, status, term_start, term_end, source, extraction
 ("Yonette Cummings-Edwards", "tc-supreme-court", "Chief Justice", "chief", "sitting", "2026-05-05", None, SP, "gov.tc AGC speech, swearing-in 5 May 2026"),
 ("Yorke Soo-Hon", "tc-court-of-appeal", "President of the Court of Appeal", "president", "sitting", None, None, SP, "gov.tc AGC speech 5 May 2026 ('My Lady President of the Court of Appeal Mrs. Justice Yorke Soo-Hon'); given name not stated"),
 ("Indra Charles", "tc-court-of-appeal", "Justice of Appeal", "associate", "sitting", None, None, SP, "gov.tc AGC speech 5 May 2026"),
 ("Anthony Gruchot", "tc-supreme-court", "Judge of the Supreme Court (Puisne Judge)", "puisne", "sitting", "2022-09-01", None, MEM, "judicial.tc members page; listed as sitting SC judge in gov.tc AGC speech 5 May 2026"),
 ("Selochan", "tc-supreme-court", "Judge of the Supreme Court", "puisne", "sitting", None, None, SP, "gov.tc AGC speech 5 May 2026 (surname only)"),
 ("Bakre", "tc-supreme-court", "Judge of the Supreme Court", "puisne", "sitting", None, None, SP, "gov.tc AGC speech 5 May 2026 (surname only)"),
 ("Jolyon Hatmin", "tc-lower-court", "Chief Magistrate", "chief", "sitting", "2020-04-01", None, MEM, "judicial.tc members page (Chief Magistrate since 1 April 2020); 'His Honour the Chief Magistrate' present per gov.tc speech 5 May 2026"),
 ("Oreika Selver-Gardiner", "tc-lower-court", "Resident Magistrate", "magistrate", "unverified", None, None, MEM, "judicial.tc members page (page not updated since 2020-2022)"),
 ("Tanya Lobban Jackson", "tc-supreme-court", "Judge of the Supreme Court (Puisne Judge)", "puisne", "unverified", "2020-04-02", None, MEM, "judicial.tc members page; not named among SC judges in gov.tc speech 5 May 2026"),
 ("Stanley John", "tc-court-of-appeal", "Justice of Appeal (non-resident)", "associate", "unverified", "2020-03", None, MEM, "judicial.tc members page"),
 ("Ian R. Winder", "tc-court-of-appeal", "Justice of Appeal", "associate", "unverified", None, None, MEM, "judicial.tc members page"),
 ("Dennis Morrison", "tc-court-of-appeal", "President of the Court of Appeal", "president", "former", None, None, MEM, "judicial.tc members page lists him as President; gov.tc speech 5 May 2026 names Yorke Soo-Hon as President"),
 ("Mabel Agyemang", "tc-supreme-court", "Chief Justice", "chief", "former", "2020-04-01", None, MEM, "judicial.tc members page (CJ from 1 April 2020); succeeded by Cummings-Edwards (sworn in 5 May 2026)"),
]
def slug(s): return re.sub(r"[^a-z0-9]+", "-", s.lower().replace("é", "e")).strip("-")
jrows = []
for n, c, t, pt, st, ts, te, src, ex in J:
    jid = f"{c}-{slug(n)}"
    if jid in havej: continue
    jrows.append({"judge_id": jid, "court_id": c, "name": n, "title": t, "position_type": pt, "term_start": ts, "term_end": te, "status": st, "jurisdiction": "TC",
        "roster_url": MEM, "source_url": src, "source_kind": "official",
        "site_policy": POL if src == MEM else "robots_allowed|gov.tc robots.txt disallows only Joomla system dirs; AGC website, no terms stated",
        "retrieved_at": now, "needs_review": True, "extraction": ex, "license": "official public judiciary/government information (facts)"})
app(JO, jrows); print("judges new", len(jrows))
