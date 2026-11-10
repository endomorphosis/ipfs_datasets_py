"""TC: Turks and Caicos court rules & procedure laws from the Attorney General's Chambers Revised Laws 2021 (official, gov.tc/agc;
documents via the site's own edocman 'fdocument' links). Section/rule-level rows parsed from the PDF text layer (marginal-note headings).
Sets: Court of Appeal (Practice and Procedure) Rules (GN 51/1975), Court of Appeal Rules of the Bahama Islands as applied by Sched.
(Cap 2.01), Probate and Administration Rules, Supreme Court (Oaths) Rules, Supreme Court (Appointment of Queen's Counsel) Rules (Cap 2.02),
Criminal Procedure Ordinance (Cap 3.03), Civil Procedure Ordinance (Cap 4.01). Rules of the Supreme Court are 'Omitted' from the revised
edition (TCI CPR 2000 not published there) -> not available.
Usage: tc_agc_court_rules.py [--dry]"""
import json, re, sys, hashlib, subprocess, datetime, os, time, requests
ROOT = "/workspace/world_courts"; RAW = f"{ROOT}/rules/raw/tc"; OUT = f"{ROOT}/data/tc/tc_rules.jsonl"
UA = "world_courts/0.1 (open court-data research; github.com/endomorphosis)"; B = "https://www.gov.tc/agc/component/edocman/"
POL = "robots_allowed|gov.tc robots.txt disallows only Joomla system paths (/administrator/, /components/ etc.), not /agc/component/edocman; AGC Revised Laws, no terms stated"
LIC = "Turks and Caicos Islands Government legislation (Revised Edition 2021, Law Revision Commissioner); no open licence stated"
now = datetime.datetime.now(datetime.timezone.utc).isoformat()
def get(slug):
    p = f"{RAW}/{slug}.pdf"
    if not os.path.exists(p) or os.path.getsize(p) < 1000:
        r = requests.get(f"{B}{slug}/fdocument?Itemid=9999", headers={"User-Agent": UA}, timeout=180); r.raise_for_status(); open(p, "wb").write(r.content); time.sleep(3)
    return p
HDR = re.compile(r"LAWS OF TURKS|CAICOS ISLANDS|Revision Date:|\[Subsidiary Legislation\]|CAP\. \d|^\s*\d{1,3}\s*$")
SETS = [  # (slug, set_id, name, court_id, start_regex(occurrence -1 = last), end_regex, effective)
 ("02-01-court-of-appeal-ordinance-2", "tc-coa-pp-rules", "Court of Appeal (Practice and Procedure) Rules (Cap. 2.01, GN 51/1975)", "tc-court-of-appeal",
  r"^\s+COURT OF APPEAL \(PRACTICE AND PROCEDURE\) RULES\s*–\s*SECTION 22", r"^\s+SCHEDULE\s*$", "1975-03-17"),
 ("02-01-court-of-appeal-ordinance-2", "tc-coa-rules-bahamas-sched", "Court of Appeal Rules of the Bahama Islands, as applied to TCI by Schedule to the Court of Appeal (Practice and Procedure) Rules", "tc-court-of-appeal",
  r"^\s+THE COURT OF APPEAL RULES OF THE BAHAMA ISLANDS\s*$", r"^\s+JUDICIAL COMMITTEE", "1975-03-17"),
 ("02-02-supreme-court-ordinance-2", "tc-probate-admin-rules", "Probate and Administration Rules (Cap. 2.02, s.16)", "tc-supreme-court",
  r"^\s+PROBATE AND ADMINISTRATION RULES – SECTION 16", r"^\s+SUPREME COURT \(OATHS\) RULES – SECTION 16", None),
 ("02-02-supreme-court-ordinance-2", "tc-sc-oaths-rules", "Supreme Court (Oaths) Rules (Cap. 2.02, s.16)", "tc-supreme-court",
  r"^\s+SUPREME COURT \(OATHS\) RULES – SECTION 16", r"^\s+SUPREME COURT \(APPOINTMENT OF QUEEN’S COUNSEL\) RULES\s*$", None),
 ("02-02-supreme-court-ordinance-2", "tc-sc-qc-rules", "Supreme Court (Appointment of Queen's Counsel) Rules (Cap. 2.02, s.16)", "tc-supreme-court",
  r"^\s+SUPREME COURT \(APPOINTMENT OF QUEEN’S COUNSEL\) RULES – SECTION 16", None, None),
 ("03-03-criminal-procedure-ordinance-2", "tc-criminal-procedure-ordinance", "Criminal Procedure Ordinance (Cap. 3.03, Ord. 26 of 1968)", "tc-supreme-court",
  r"^\s+CRIMINAL PROCEDURE ORDINANCE\s*$#4", r"^\s+(EXTRADITION|TRIALS WITHOUT A JURY ORDINANCE)\s*$", "1969-01-18"),
 ("04-01-civil-procedure-ordinance-2", "tc-civil-procedure-ordinance", "Civil Procedure Ordinance (Cap. 4.01, Ord. 2 of 1866)", "tc-supreme-court",
  r"^\s+CIVIL PROCEDURE ORDINANCE\s*$#4", None, "1866-10-10")]
SEC = re.compile(r"^\s{1,12}(\d{1,3}[A-Z]?)\.\s+(\S.*)$")
rows = []; cids = {json.loads(l)["court_id"] for l in open(f"{ROOT}/data/tc/tc_courthouses.jsonl")}
for slug, sid, name, cid, sre, ere, eff in SETS:
    p = get(slug); sha = hashlib.sha256(open(p, "rb").read()).hexdigest()
    L = subprocess.run(["pdftotext", "-layout", p, "-"], capture_output=True, text=True).stdout.splitlines()
    sre, _, occ = sre.partition("#"); hits = [i for i, l in enumerate(L) if re.search(sre, l)]
    s = hits[int(occ) - 1] if occ else hits[-1] if "COURT OF APPEAL (PRACTICE" not in sre else hits[-1]
    e = next((i for i in range(s + 1, len(L)) if ere and re.search(ere, L[i])), len(L))
    seg = [l for l in L[s:e] if not HDR.search(l)]
    secs = []; prevn = 0
    for j, l in enumerate(seg):
        m = SEC.match(l)
        if not m: continue
        n = int(re.match(r"\d+", m.group(1)).group()); k = j - 1
        while k >= 0 and not seg[k].strip(): k -= 1
        h = seg[k].strip() if k >= 0 else ""
        if not h or h[0].isdigit() or len(h) > 80 or h.endswith((".", ";", ",", ":", "—")) or h.startswith("("): continue
        if not (prevn < n <= prevn + 5 or (n == prevn and m.group(1) != secs[-1][1])): continue
        secs.append((j, m.group(1), h, k)); prevn = n
    for x, (j, num, h, k) in enumerate(secs):
        end = secs[x + 1][3] if x + 1 < len(secs) else len(seg)
        txt = re.sub(r"\n{3,}", "\n\n", "\n".join(seg[j:end])).strip()
        txt = re.sub(r"[ \t]+", " ", txt)
        rows.append({"rule_id": f"{sid}:s{num}".lower(), "rule_set_id": sid, "court_id": cid if cid in cids else None, "jurisdiction": "TC",
            "rule_set": name, "rule_number": num, "title": h, "part": None, "text": txt[:150000], "effective_date": eff,
            "pdf_path": f"rules/raw/tc/{slug}.pdf", "pdf_sha256": sha, "source_sha256": sha, "source_url": f"{B}{slug}/fdocument?Itemid=9999",
            "index_url": "https://www.gov.tc/agc/2021-revised-laws", "source_kind": "official", "site_policy": POL, "license": LIC, "retrieved_at": now,
            "language": "en", "needs_review": True, "version_note": "Revised Edition showing the law as at 31 March 2021; section boundaries parsed from marginal notes"})
from collections import Counter
print(Counter(r["rule_set_id"] for r in rows))
have = {json.loads(l)["rule_id"] for l in open(OUT)} if os.path.exists(OUT) else set()
new = [r for r in rows if r["rule_id"] not in have]; print("new", len(new), "court_ids", Counter(r["court_id"] for r in rows))
for r in rows[:2] + rows[-2:]: print(r["rule_id"], "|", r["title"], len(r["text"]))
if "--dry" not in sys.argv:
    with open(OUT, "a") as f:
        for r in new: f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print("wrote", len(new))
