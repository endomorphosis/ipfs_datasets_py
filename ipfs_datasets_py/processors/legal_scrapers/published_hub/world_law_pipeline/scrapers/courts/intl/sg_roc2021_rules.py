"""SG: Rules of Court 2021 (S 914/2021, as in force from 1 Apr 2026), split into rule-level rows.
Source: official PDF view on Singapore Statutes Online (sso.agc.gov.sg). robots.txt returns 403 (CloudFront), so robots_unknown;
SSO content is Government of Singapore copyright, terms of use permit reproduction with attribution for non-commercial use."""
import json, re, sys, os, hashlib, datetime, subprocess
sys.path.insert(0, "/workspace/world_courts/scrapers/courts/intl")
from courts_common import ROOT, rjl
SRC = "https://sso.agc.gov.sg/SL/SCJA1969-S914-2021?DocDate=20260331&ViewType=Pdf"
IDX = "https://sso.agc.gov.sg/SL/SCJA1969-S914-2021"
PDF = f"{ROOT}/rules/raw/sg/roc2021.pdf"
sha = hashlib.sha256(open(PDF, "rb").read()).hexdigest()
L = subprocess.run(["pdftotext", "-layout", PDF, "-"], capture_output=True, text=True).stdout.split("\n")
start = next(i for i, l in enumerate(L) if i > 1000 and re.match(r"\s*Citation and commencement \(O\. 1, r\. 1\)", l))
end = next(i for i, l in enumerate(L) if i > start and re.match(r"\s*FIRST SCHEDULE\s*$", l))
noise = re.compile(r"Informal Consolidation – version in force|^\s*S 914/2021\s+\d+\s*$|^\s*\d+\s+S 914/2021\s*$|^\s*(PART|ORDER) \d+[A-Z]?\s*$")
B = [l for l in L[start:end] if not noise.search(l)]
hdr = re.compile(r"^(\S.*?)\s*\(O\.\s?(\d+[A-Z]?), r\.\s?(\d+[A-Z]?)\)\s*$")
heads = []
for i, l in enumerate(B):
    m = hdr.match(l.strip())
    if m and not l.startswith("   "):
        title = m.group(1); j = i
        # heading may wrap: previous non-indented line without terminal punctuation that is not body text
        if i > 0 and B[i-1].strip() and not B[i-1].startswith(" ") and not re.search(r"[.;:—,)]$", B[i-1].strip()) and B[i-1].strip()[0].isupper() and len(B[i-1].strip()) < 70:
            title = B[i-1].strip() + " " + title; j = i - 1
        heads.append((m.group(2), m.group(3), title, i, j))
OUT = f"{ROOT}/data/sg/sg_rules.jsonl"
old = {r["rule_id"] for r in rjl(OUT)} if os.path.exists(OUT) else set()
now = datetime.datetime.now(datetime.UTC).isoformat(); rows = []; seen = set()
for k, (o, r, title, i, j) in enumerate(heads):
    e = heads[k+1][4] if k + 1 < len(heads) else len(B)
    seg = B[i+1:e]
    # drop trailing all-caps order headings (e.g. order titles between orders)
    while seg and (not seg[-1].strip() or (seg[-1].strip().isupper() and len(seg[-1].strip()) > 3)): seg = seg[:-1]
    txt = re.sub(r"\s+", " ", " ".join(s.strip() for s in seg)).strip()
    rid = f"sg-roc-2021:o{o}r{r}"
    if rid in seen or rid in old or len(txt) < 10: continue
    seen.add(rid)
    rows.append({"rule_id": rid, "rule_set_id": "sg-roc-2021", "court_id": None, "jurisdiction": "SG",
        "rule_set": "Rules of Court 2021 (S 914/2021)", "rule_number": f"Order {o}, Rule {r}", "title": title,
        "text": txt, "effective_date": "2022-04-01", "pdf_path": None, "pdf_sha256": sha, "source_sha256": sha, "source_url": SRC,
        "index_url": IDX, "site_policy": "robots_unknown:robots.txt 403; SSO terms of use (Government of Singapore copyright, reproduction with attribution)",
        "retrieved_at": now, "license": "Singapore subsidiary legislation; Government of Singapore copyright (SSO terms of use); informal consolidation in force from 2026-04-01",
        "language": "en", "version_note": "Informal Consolidation – version in force from 1/4/2026"})
if "--dry" not in sys.argv:
    with open(OUT, "a") as f:
        for x in rows: f.write(json.dumps(x, ensure_ascii=False) + "\n")
print("heads", len(heads), "added", len(rows), "orders", len({x["rule_id"].split(":o")[1].split("r")[0] for x in rows}))
json.dump(rows, open("/tmp/sg_rows.json", "w"), ensure_ascii=False)
