"""GY: Civil Procedure Rules 2016 of the High Court of the Supreme Court of Judicature of Guyana (in force 16 Jan 2017), rule-level rows from the
official PDF on supremecourt.gy (robots.txt allows /sites/default/files; Crawl-delay 10 respected). judiciary.gov.gy remains unreachable; supremecourt.gy is
the Supreme Court's own site. Rule numbers like 1.01; titles on the rule line."""
import json, os, re, sys, hashlib, datetime, subprocess, time, requests
ROOT = "/workspace/world_courts"
SRC = "https://supremecourt.gy/sites/default/files/Civil%20Procedure%20Rules%202016.PDF"; IDX = "https://supremecourt.gy/rules-of-court"
RAW = f"{ROOT}/rules/raw/gy/gy_cpr2016.pdf"; OUT = f"{ROOT}/data/gy/gy_rules.jsonl"
now = datetime.datetime.now(datetime.UTC).isoformat()
if not os.path.exists(RAW):
    time.sleep(10); r = requests.get(SRC, headers={"User-Agent": "WorldCourtsResearchBot/1.0"}, timeout=180); r.raise_for_status(); open(RAW, "wb").write(r.content)
sha = hashlib.sha256(open(RAW, "rb").read()).hexdigest()
L = subprocess.run(["pdftotext", "-layout", RAW, "-"], capture_output=True, text=True).stdout.replace("\f", "\n").splitlines()
JUNK = re.compile(r"^\s*(- [ivxlc\d]+ -|Supreme Court of Guyana|CIVIL PROCEDURE RULES 2016)\s*$")
L = [l for l in L if not JUNK.match(l)]
b0 = [i for i, l in enumerate(L) if re.match(r"^PART 1: ", l) and "...." not in l][0]
part = None; prev = (0, 0); cand = []
for i in range(b0, len(L)):
    l = L[i]
    m = re.match(r"^PART (\d+): (.+?)\s*$", l)
    if m and "...." not in l: part = (int(m.group(1)), m.group(2).strip()); continue
    m = re.match(r"^\s{0,4}(\d{1,2})\.(\d{2})\s+([A-Z].*?)\s*$", l)
    if not m: continue
    k = (int(m.group(1)), int(m.group(2)))
    if (k[0] == prev[0] and 0 < k[1] - prev[1] <= 3) or (0 < k[0] - prev[0] <= 3 and k[1] == 1):
        cand.append((i, k, f"{m.group(1)}.{m.group(2)}", m.group(3), part)); prev = k
rows = []
for j, (i, k, rn, title, part) in enumerate(cand):
    end = cand[j + 1][0] if j + 1 < len(cand) else len(L)
    blk = []
    for x in L[i + 1:end]:
        s = x.strip()
        if re.match(r"^PART \d+: ", s) or re.match(r"^(SCHEDULE|APPENDIX)\b", s): break
        if s: blk.append(s)
    pt = f"Part {part[0]} – {part[1].title()}" if part else None
    rows.append({"rule_id": f"gy-cpr-2016:r{rn}", "rule_set_id": "gy-cpr-2016", "court_id": None, "jurisdiction": "GY",
        "rule_set": "Civil Procedure Rules 2016 (High Court of the Supreme Court of Judicature of Guyana)", "rule_number": f"Rule {rn}", "title": title,
        "part": pt, "text": re.sub(r"\s+", " ", " ".join(blk)).strip(), "effective_date": "2017-01-16", "pdf_path": None, "pdf_sha256": sha,
        "source_sha256": sha, "source_url": SRC, "index_url": IDX, "site_policy": "robots_allowed (crawl-delay 10 respected)", "retrieved_at": now,
        "license": "Guyana rules of court (Rules Committee, laid in the National Assembly Nov 2016); official public text from the Supreme Court of Judicature, no licence stated",
        "language": "en", "version_note": "2016 text as published; Civil Procedure (Amendment) Rule 2019 not consolidated"})
old = {json.loads(l)["rule_id"] for l in open(OUT)} if os.path.exists(OUT) else set()
new = [x for x in rows if x["rule_id"] not in old]
with open(OUT, "a") as f:
    for x in new: f.write(json.dumps(x, ensure_ascii=False) + "\n")
print("parsed", len(rows), "added", len(new), "parts", len({r['part'] for r in rows}))
