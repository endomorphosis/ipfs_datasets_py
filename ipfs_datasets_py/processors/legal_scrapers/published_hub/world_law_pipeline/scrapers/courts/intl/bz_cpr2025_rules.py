"""BZ: Senior Courts (Civil Procedure) Rules, 2025 (S.I. No. 1 of 2025, gazetted 2 Jan 2025) rule-level rows from the official PDF published by the
Attorney General's Ministry of Belize (agm.gov.bz; robots.txt not served => absent). Two-column layout with marginal notes: margins are dropped per page,
then cpr_pdf_parse (Part.Rule numbering). Footnote text can leak into rule text => needs_review."""
import json, os, re, sys, hashlib, datetime, statistics, requests
sys.path.insert(0, "/workspace/world_courts/scrapers/courts/intl")
import cpr_pdf_parse as c
ROOT = "/workspace/world_courts"
SRC = "https://www.agm.gov.bz/uploads/laws/67fe894f294ac_SI_No._001_of_2025_Senior_Courts__Civil_Procedure__Rules__2025.pdf"
RAW = f"{ROOT}/rules/raw/bz/bz_cpr2025.pdf"; OUT = f"{ROOT}/data/bz/bz_rules.jsonl"
now = datetime.datetime.now(datetime.UTC).isoformat()
if not os.path.exists(RAW):
    r = requests.get(SRC, headers={"User-Agent": "WorldCourtsResearchBot/1.0"}, timeout=180); r.raise_for_status(); open(RAW, "wb").write(r.content)
sha = hashlib.sha256(open(RAW, "rb").read()).hexdigest()
def bz_pre(pages):
    out = []
    for pg in pages:
        ls = pg.splitlines()
        ind = [len(l) - len(l.lstrip()) for l in ls if l.strip() and len(l.strip()) > 35]
        left = bool(ind) and statistics.median(ind) >= 14
        for l in ls:
            if not l.strip(): out.append(""); continue
            st = len(l) - len(l.lstrip())
            if left:
                if st < 12:
                    m = re.match(r"^(\s*\S.*?)\s{3,}(\S.*)$", l)
                    if m and l.find(m.group(2)) >= 14: l = " " * l.find(m.group(2)) + m.group(2)
                    elif len(l.strip()) <= 30 and not re.match(r"^\s*(\d+|No\. 1\])", l): continue
            else:
                if st >= 60 and len(l.strip()) <= 34: continue
                m = re.match(r"^(.*\S)\s{4,}(\S.{0,34})$", l)
                if m and l.rfind(m.group(2)) >= 60 and not re.search(r"Rule\s*\d+\.\d+$|Senior Courts|\[No\. 1", l): l = m.group(1)
            out.append(l)
    return out
J = [r"^\s*\d*\s*Senior Courts\s*\d*\s*$", r"^\s*No\. 1\]\s+Senior Courts", r"Senior Courts\s+\[No\. 1", r"^\s*\d+\s+Senior Courts"]
R = c.parse_text("\n".join(bz_pre(c.pdftext(RAW).split("\x0c"))), J)
pages = c.pdftext(RAW).split("\x0c")
TOC = {}; prevline = ""
for l in "\n".join(pages[:39]).splitlines():
    m = re.match(r"^\s*(.*?)[\s\.…]*Rule\s*(\d+\.\d+)\s*$", l)
    if m:
        t = m.group(1).strip(" .…")
        if prevline and not re.search(r"Rule\s*\d+\.\d+|^PART|TABLE OF CONTENTS|Senior Courts", prevline) and not prevline.isupper() and (not t or t[:1].islower()):
            t = (prevline.strip(" .…") + " " + t).strip()
        if t: TOC.setdefault(m.group(2), t)
        prevline = ""
    else: prevline = l.strip()
rows = [{"rule_id": f"bz-scpr-2025:r{r['rule']}", "rule_set_id": "bz-scpr-2025", "court_id": None, "jurisdiction": "BZ",
    "rule_set": "Senior Courts (Civil Procedure) Rules, 2025 (S.I. No. 1 of 2025)", "rule_number": f"Rule {r['rule']}", "title": TOC.get(r["rule"]),
    "part": f"Part {r['part']}" + (f" – {r['part_title'].title() if r['part_title'] and r['part_title'].isupper() else r['part_title']}" if r["part_title"] else ""),
    "text": r["text"], "effective_date": "2025-01-02", "pdf_path": None, "pdf_sha256": sha, "source_sha256": sha, "source_url": SRC,
    "index_url": "https://www.agm.gov.bz/", "site_policy": "robots_absent_allowed", "retrieved_at": now,
    "license": "Belize statutory instrument (Rules Committee under s.101 Senior Courts Act 2022); official public text from the Attorney General's Ministry, no licence stated",
    "language": "en", "needs_review": True, "extraction": "pdftotext layout; marginal notes removed heuristically; footnote text may be inline"} for r in R]
old = {json.loads(l)["rule_id"] for l in open(OUT)} if os.path.exists(OUT) else set()
new = [x for x in rows if x["rule_id"] not in old]
with open(OUT, "a") as f:
    for x in new: f.write(json.dumps(x, ensure_ascii=False) + "\n")
print("parsed", len(rows), "added", len(new))
