"""JM: Judicature (Supreme Court) (Proceeds of Crime) Rules, 2021, split into rule-level rows.
Source PDF is linked from supremecourt.gov.jm/content/rules-court (robots allows /sites/default/files)."""
import json, re, sys, os, subprocess, hashlib, datetime
sys.path.insert(0, "/workspace/world_courts/scrapers/courts/intl")
from courts_common import ROOT, rjl
SRC = "https://supremecourt.gov.jm/sites/default/files/Proc.-Judicature.pdf"
PDF = f"{ROOT}/forms/jm/8dcf42b7fd1316c6056d2a77db46827b0785d0ebd833b4442c0a7fcb390a442d.pdf"
sha = hashlib.sha256(open(PDF, "rb").read()).hexdigest()
L = subprocess.run(["pdftotext", "-layout", PDF, "-"], capture_output=True, text=True).stdout.split("\n")
body0 = next(i for i, l in enumerate(L) if i > 150 and re.match(r"\s*Citation and commencement", l))
toc = []
for l in L[:body0]:
    m = re.match(r"\s*(\d+\.\d+)\s+(\S.*?)\s*$", l)
    if m: toc.append((m.group(1), m.group(2).rstrip(".")))
seen = set(); toc = [t for t in toc if not (t[0] in seen or seen.add(t[0]))]
pos = []; i = body0
for num, title in toc:
    pat = re.compile(r"^\s*" + re.escape(num).replace("\\.", r"\s?\.") + r"(\s|$)")
    j = i
    while j < len(L) and not pat.match(L[j]): j += 1
    if j >= len(L): print("missing", num); continue
    pos.append((num, title, j)); i = j + 1
noise = re.compile(r"(PROCLAMATIONS, RULES AND REGULATIONS|THE JAMAICA GAZETTE|^\s*PART \d+\s*—|^\s*\d+[A-Z]*\d*\s*$)")
OUT = f"{ROOT}/data/jm/jm_rules.jsonl"
old = {r["rule_id"] for r in rjl(OUT)} if os.path.exists(OUT) else set()
now = datetime.datetime.now(datetime.UTC).isoformat(); rows = []
for k, (num, title, j) in enumerate(pos):
    end = pos[k + 1][2] if k + 1 < len(pos) else len(L)
    seg = L[j:end]
    if k + 1 < len(pos):
        nt = pos[k + 1][1].lower()[:15]
        while seg and (not seg[-1].strip() or seg[-1].strip().lower().startswith(nt)): seg = seg[:-1]
    else:
        for q, l in enumerate(seg):
            if re.match(r"\s*(FIRST )?SCHEDULE\b|\s*FORM\s+\d|\s*THE JUDICATURE \(SUPREME COURT\) ACT", l): seg = seg[:q]; break
    txt = re.sub(r"\s+", " ", " ".join(l for l in seg if not noise.search(l))).strip()
    rid = f"jm-sc-poca-rules-2021:r{num}"
    if rid in old or len(txt) < 15: continue
    rows.append({"rule_id": rid, "rule_set_id": "jm-sc-poca-rules-2021", "court_id": None, "jurisdiction": "JM",
        "rule_set": "Judicature (Supreme Court) (Proceeds of Crime) Rules, 2021", "rule_number": f"Rule {num}", "title": title,
        "text": txt, "effective_date": "2021-04-07", "pdf_path": None, "pdf_sha256": sha, "source_sha256": sha, "source_url": SRC,
        "index_url": "https://supremecourt.gov.jm/content/rules-court", "site_policy": "robots_allowed", "retrieved_at": now,
        "license": "Jamaican subsidiary legislation published in the Jamaica Gazette; official public text, no licence stated", "language": "en"})
if "--dry" not in sys.argv:
    with open(OUT, "a") as f:
        for r in rows: f.write(json.dumps(r, ensure_ascii=False) + "\n")
print("toc", len(toc), "found", len(pos), "added", len(rows))
json.dump(rows, open("/tmp/jm_rows.json", "w"))
