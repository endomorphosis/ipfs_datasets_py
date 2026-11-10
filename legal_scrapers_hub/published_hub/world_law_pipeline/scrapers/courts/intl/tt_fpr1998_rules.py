"""TT: Family Proceedings Rules, 1998 (Supreme Court of Trinidad and Tobago, Family Court) rule-level rows from the official consolidated PDF
on ttlawcourts.org (robots.txt allows /sites/default/files). Text-layer PDF -> pdftotext -layout -> sequential rule-number parse."""
import json, re, sys, os, hashlib, datetime, subprocess, shutil, requests
ROOT = "/workspace/world_courts"
SRC = "https://www.ttlawcourts.org/sites/default/files/2026-08/familyproceedingsrules.pdf"
IDX = "https://www.ttlawcourts.org/media-public-information/family-court-rules-practice-directions"
RAW = f"{ROOT}/rules/raw/tt/familyproceedingsrules.pdf"; OUT = f"{ROOT}/data/tt/tt_rules.jsonl"
now = datetime.datetime.now(datetime.UTC).isoformat()
if not os.path.exists(RAW):
    r = requests.get(SRC, headers={"User-Agent": "WorldCourtsResearchBot/1.0"}, timeout=120); r.raise_for_status(); open(RAW, "wb").write(r.content)
sha = hashlib.sha256(open(RAW, "rb").read()).hexdigest()
txt = subprocess.run(["pdftotext", "-layout", RAW, "-"], capture_output=True, text=True).stdout
L = txt.splitlines()
# body begins at the second "Part 1" heading line (first is the ToC entry)
starts = [i for i, l in enumerate(L) if re.fullmatch(r"\s*Part 1\s*", l)]; b0 = starts[0]
parts = {}  # part titles from body headings
for i in range(b0, len(L)):
    m = re.fullmatch(r"\s*Part (\d+)\s*", L[i])
    if m:
        t = [x.strip() for x in L[i + 1:i + 6] if x.strip()][:1]
        parts.setdefault(int(m.group(1)), t[0] if t else None)
cand = []; prev = (0, 0); in_contents = False
for i in range(b0, len(L)):
    l = L[i]
    m = re.match(r"^\s{0,8}(\d{1,2})\.(\d{1,2})\s+(\S.*)$", l)
    if not m: continue
    k = (int(m.group(1)), int(m.group(2)))
    ok = (k[0] == prev[0] and k[1] == prev[1] + 1) or (k[0] > prev[0] and k[1] == 1)
    if ok: cand.append((i, k)); prev = k
def clean(block):
    out = []
    for x in block:
        s = x.strip()
        if not s or re.fullmatch(r"[0-9ivxlc]+", s): continue
        if re.fullmatch(r"Part \d+", s) or re.match(r"Appendix [A-Z]\b", s): break
        out.append(s)
    return out
rows = []
for j, (i, k) in enumerate(cand):
    end = cand[j + 1][0] if j + 1 < len(cand) else len(L)
    blk = clean(L[i:end])
    # the last non-empty line before the next rule start is that rule's heading
    title = None
    back = [x.strip() for x in L[max(b0, i - 4):i] if x.strip() and not re.fullmatch(r"[0-9ivxlc]+", x.strip())]
    if back and not re.match(r"^\(?[a-z0-9]+\)", back[-1]) and len(back[-1]) < 120 and not back[-1].endswith(("-", ";", ",")): title = back[-1]
    if j + 1 < len(cand) and blk:
        nb = [x.strip() for x in L[cand[j + 1][0] - 4:cand[j + 1][0]] if x.strip()]
        if nb and blk[-1] == nb[-1]: blk = blk[:-1]
    text = re.sub(r"\s+", " ", " ".join(blk)).strip()
    if title and re.fullmatch(r"Part \d+|Contents of this Part|-+", title): title = None
    rn = f"{k[0]}.{k[1]}"
    rows.append({"rule_id": f"tt-fpr-1998:r{rn}", "rule_set_id": "tt-fpr-1998", "court_id": None, "jurisdiction": "TT",
        "rule_set": "Family Proceedings Rules, 1998 (Trinidad and Tobago)", "rule_number": f"Rule {rn}", "title": title,
        "part": f"Part {k[0]}" + (f" – {parts[k[0]]}" if parts.get(k[0]) else ""), "text": text, "effective_date": None,
        "pdf_path": None, "pdf_sha256": sha, "source_sha256": sha, "source_url": SRC, "index_url": IDX, "site_policy": "robots_allowed",
        "retrieved_at": now, "license": "Trinidad and Tobago subsidiary legislation (Rules Committee); official public text published by the Judiciary of Trinidad and Tobago, no licence stated",
        "language": "en", "version_note": "consolidated text as published by the Judiciary (commencement 2003 per r.2.1; amendments may be gazetted separately)"})
old = {json.loads(l)["rule_id"] for l in open(OUT)} if os.path.exists(OUT) else set()
new = [r for r in rows if r["rule_id"] not in old]
with open(OUT, "a") as f:
    for r in new: f.write(json.dumps(r, ensure_ascii=False) + "\n")
print("parsed", len(rows), "added", len(new), "parts", len({r['part'] for r in rows}), "empty", sum(1 for r in rows if len(r['text']) < 20))
