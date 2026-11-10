"""BT: Civil and Criminal Procedure Code of Bhutan, 2001 (English version) section-level rows, from the official PDF on judiciary.gov.bt
(robots.txt: Allow /). Sequential section-number parse of pdftotext -layout output; Part/Chapter headings carried. Note: amended 2011 and 2021
(amendment acts listed on the same page; the 2011 file link returned 404) — this is the original 2001 text."""
import json, os, re, sys, hashlib, datetime, subprocess, requests
ROOT = "/workspace/world_courts"
SRC = "https://www.judiciary.gov.bt/storage/files/1/Civil-and-Criminal-Procedure-Code-of-Bhutan-2001English-version0.pdf"
IDX = "https://www.judiciary.gov.bt/posts/first-category/acts"
RAW = f"{ROOT}/rules/raw/bt/ccpc2001.pdf"; OUT = f"{ROOT}/data/bt/bt_rules.jsonl"
now = datetime.datetime.now(datetime.UTC).isoformat()
if not os.path.exists(RAW):
    r = requests.get(SRC, headers={"User-Agent": "WorldCourtsResearchBot/1.0"}, timeout=120); r.raise_for_status(); open(RAW, "wb").write(r.content)
sha = hashlib.sha256(open(RAW, "rb").read()).hexdigest()
L = subprocess.run(["pdftotext", "-layout", RAW, "-"], capture_output=True, text=True).stdout.replace("\f", "\n").splitlines()
part = chap = None; prev = 0; cand = []
for i, l in enumerate(L):
    s = l.strip()
    m = re.fullmatch(r"PART ([IVX]+)", s)
    if m: part = f"Part {m.group(1)}" + (f" – {L[i+1].strip().title()}" if i + 1 < len(L) and L[i+1].strip() else ""); continue
    m = re.fullmatch(r"CHAPTER (\d+)", s)
    if m: chap = f"Chapter {m.group(1)}" + (f" – {L[i+1].strip()}" if i + 1 < len(L) and L[i+1].strip() else ""); continue
    m = re.match(r"^\s{0,8}(\d{1,3})\.(?!\d)\s*(\S.*)$", l)
    if m and int(m.group(1)) == prev + 1:
        prev += 1; cand.append((i, prev, part, chap))
rows = []
for j, (i, n, part, chap) in enumerate(cand):
    end = cand[j + 1][0] if j + 1 < len(cand) else len(L)
    blk = [x.strip() for x in L[i:end] if x.strip() and not re.fullmatch(r"\d{1,3}", x.strip())]
    # drop trailing heading lines that belong to the next section / next chapter
    while blk and (re.fullmatch(r"(PART [IVX]+|CHAPTER \d+)", blk[-1]) or (j + 1 < len(cand) and blk[-1] in [L[k].strip() for k in range(max(i, cand[j+1][0] - 6), cand[j+1][0])] and not re.match(r"^\d", blk[-1]) and len(blk) > 1 and len(blk[-1]) < 80 and not blk[-1].endswith((".", ";", ":", ",")))):
        blk.pop()
    while blk and re.fullmatch(r"(PART [IVX]+|CHAPTER \d+|[A-Z][A-Z ]+)", blk[-1]): blk.pop()
    back = [x.strip() for x in L[max(0, i - 4):i] if x.strip() and not re.fullmatch(r"\d{1,3}", x.strip())]
    title = back[-1] if back and len(back[-1]) < 90 and not back[-1].endswith((".", ";", ",", ":")) and not re.fullmatch(r"(PART [IVX]+|CHAPTER \d+|PRELIMINARY)", back[-1]) and not re.match(r"^\(?\d", back[-1]) else None
    first = re.sub(rf"^{n}\.\s*", "", blk[0]) if blk else ""
    if not title and len(first) < 80 and not first.endswith((".", ";", ":", ",")): title = first
    if title and chap and title == chap.split(" – ", 1)[-1] and n != 1: pass
    rows.append({"rule_id": f"bt-ccpc-2001:s{n}", "rule_set_id": "bt-ccpc-2001", "court_id": None, "jurisdiction": "BT",
        "rule_set": "Civil and Criminal Procedure Code of Bhutan, 2001", "rule_number": f"Section {n}", "title": title,
        "part": " / ".join(x for x in (part, chap) if x) or None, "text": re.sub(r"\s+", " ", " ".join(blk)).strip(),
        "effective_date": "2001-07-23", "pdf_path": None, "pdf_sha256": sha, "source_sha256": sha, "source_url": SRC, "index_url": IDX,
        "site_policy": "robots_allowed", "retrieved_at": now, "license": "Act of the National Assembly of Bhutan (Royal Government of Bhutan); official public text published by the Judiciary of Bhutan, no licence stated",
        "language": "en", "version_note": "original 2001 English text; amended by the CCPC (Amendment) Acts 2011 and 2021 (not consolidated here)"})
old = {json.loads(l)["rule_id"] for l in open(OUT)} if os.path.exists(OUT) else set()
new = [x for x in rows if x["rule_id"] not in old]
with open(OUT, "a") as f:
    for x in new: f.write(json.dumps(x, ensure_ascii=False) + "\n")
print("parsed", len(rows), "added", len(new))
