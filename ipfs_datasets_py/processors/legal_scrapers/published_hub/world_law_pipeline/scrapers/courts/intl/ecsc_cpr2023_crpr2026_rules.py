"""ECSC rules from official PDFs on cms.eccourts.org (Eastern Caribbean Supreme Court, seat Castries, Saint Lucia):
 (a) Civil Procedure Rules (Revised Edition) 2023 - part-level rows for the parts not published as web pages
     (web pages only cover Parts 1-11 + 5A, already ingested by ecsc_cms.py as ecsc-cpr-2023:partN);
 (b) Eastern Caribbean Supreme Court (Criminal Procedure) Rules 2026 - rule-level rows, text from the Saint Lucia
     gazetted copy (S.I. 2026 No. 4); identical rules gazetted in VC, KN, MS, GD, DM, VG (S.I./S.R.O. 2026).
Rows appended to data/lc/lc_rules.jsonl (dedupe by rule_id; never overwrite). robots: cms.eccourts.org has no robots.txt."""
import json, re, os, sys, hashlib, datetime, subprocess, time, urllib.request
ROOT = "/workspace/world_courts"; RAW = f"{ROOT}/rules/raw/lc"; OUT = f"{ROOT}/data/lc/lc_rules.jsonl"
UA = {"User-Agent": "Mozilla/5.0 world-courts-research (public court data)"}
MEMBERS = ["AG", "DM", "GD", "KN", "LC", "VC", "AI", "MS", "VG"]
now = datetime.datetime.now(datetime.UTC).isoformat()
IDX = "https://www.eccourts.org/rules"
CPR = "https://cms.eccourts.org/wp-content/uploads/2023/09/Civil-Procedure-Rules-Revised-Edition-2023.pdf"
CRPR = "https://cms.eccourts.org/wp-content/uploads/2026/02/SLU-S.I.-4-of-2026-ECSC-CRIMINAL-PROCEDURE-RULES.pdf"
CRPR_OTHERS = {"VC": "https://cms.eccourts.org/wp-content/uploads/2026/02/SVG-S.I.-No.-1-EASTERN-CARIBBEAN-SUPREME-COURT-CRIMINAL-PROCEDURE-RULES-2026.pdf",
 "KN": "https://cms.eccourts.org/wp-content/uploads/2026/02/SKB-SRO-2-of-2026-CRIMINAL-PROCEDURE-RULES.pdf",
 "MS": "https://cms.eccourts.org/wp-content/uploads/2026/02/MNI-SRO-No.-3-of-2026-Criminal-Procedure-Rules-2026.pdf",
 "GD": "https://cms.eccourts.org/wp-content/uploads/2026/02/GDA-S.R.O.-1-of-2026-Eastern-Caribbean-Supreme-Court-Criminal-Procedure-Rules-2026.pdf",
 "DM": "https://cms.eccourts.org/wp-content/uploads/2026/02/DOM-Criminal-Procedure-Rules-SI-No.-1-of-2026.pdf",
 "VG": "https://cms.eccourts.org/wp-content/uploads/2026/03/BVI-SI-No.-13-of-2026-ECSC-Criminal-Procedure-Rules-2026.pdf"}
def fetch(url):
    p = f"{RAW}/{url.rsplit('/', 1)[1]}"
    if not os.path.exists(p):
        time.sleep(2); open(p, "wb").write(urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=180).read())
    return p, hashlib.sha256(open(p, "rb").read()).hexdigest()
def txt(p): return subprocess.run(["pdftotext", "-layout", p, "-"], capture_output=True, text=True).stdout.splitlines()
def clean(lines, junk=()):
    out = [l.rstrip() for l in lines if not re.fullmatch(r"\s*\d{1,3}\s*", l) and not any(re.search(j, l) for j in junk)]
    t = "\n".join(out).strip(); return re.sub(r"\n{3,}", "\n\n", t)
old = {json.loads(l)["rule_id"] for l in open(OUT)} if os.path.exists(OUT) else set()
rows = []
# ---- (a) CPR 2023 part-level
p, sha = fetch(CPR); L = txt(p)
order = ["1", "2", "3", "4", "5", "5A"] + [str(i) for i in range(6, 39)] + ["38A"] + [str(i) for i in range(39, 76)]
start = next(i for i, l in enumerate(L) if re.fullmatch(r"PART 1\s*", l) and i > 1000)
end = next(i for i, l in enumerate(L) if i > start and l.strip() == "Appendix")
hdr, k = [], 0
for i in range(start, end):
    m = re.fullmatch(r"\s{0,2}(?:PART|Part) (\d+[A-Z]?)\s*", L[i])
    if m and k < len(order) and m.group(1) == order[k]: hdr.append((order[k], i)); k += 1
assert k == len(order), (k, len(order))
for j, (num, i) in enumerate(hdr):
    e = hdr[j + 1][1] if j + 1 < len(hdr) else end
    body = L[i + 1:e]; title = next(x.strip() for x in body if x.strip())
    rid = f"ecsc-cpr-2023:part{num.lower()}"
    if rid in old: continue
    rows.append({"rule_id": rid, "rule_set_id": "ecsc-cpr-2023", "court_id": "lc-supreme-court", "jurisdiction": "ECSC",
        "applies_to": MEMBERS, "rule_set": "Eastern Caribbean Supreme Court Civil Procedure Rules (Revised Edition) 2023",
        "rule_number": f"Part {num}", "title": title, "text": f"PART {num}\n" + clean(body), "effective_date": None,
        "pdf_path": None, "pdf_sha256": sha, "source_sha256": sha, "source_url": CPR, "index_url": IDX, "source_kind": "official",
        "site_policy": "no_robots_txt", "retrieved_at": now, "granularity": "part",
        "license": "Official ECSC rules text published on eccourts.org; no licence stated", "language": "en",
        "version_note": "Revised Edition 2023 consolidated PDF; parts 1-11 and 5A taken from the eccourts.org web pages instead"})
n_cpr = len(rows)
# ---- (b) Criminal Procedure Rules 2026, rule-level
p, sha = fetch(CRPR); L = txt(p)
others = {}
for cc, u in CRPR_OTHERS.items():
    try: others[cc] = fetch(u)[1]
    except Exception as ex: print("other copy fail", cc, ex)
toc_end = next(i for i, l in enumerate(L) if "In exercise of the powers" in l)
toc, parts, cur = [], {}, None
for i in range(toc_end):
    m = re.fullmatch(r"\s*PART (\d+)\s*", L[i])
    if m: cur = int(m.group(1)); parts[cur] = next(x.strip() for x in L[i + 1:i + 4] if x.strip()); continue
    m = re.match(r"\s+(\d{1,2})\.(\d{1,3})\s+(\S.*)", L[i])
    if m and cur:
        t = m.group(3).strip(); k = i + 1
        while k < toc_end and L[k].strip() and not re.match(r"\s+\d{1,2}\.\d{1,3}\s", L[k]) and not re.fullmatch(r"\s*PART \d+\s*", L[k]):
            t += " " + L[k].strip(); k += 1
        toc.append((int(m.group(1)), int(m.group(2)), re.sub(r"\s+", " ", t).strip()))
sched = next(i for i, l in enumerate(L) if i > toc_end and l.strip() == "SCHEDULE")
starts, k = [], 0
for i in range(toc_end, sched):
    if k >= len(toc): break
    a, b, _ = toc[k]
    if re.match(rf"\s{{0,12}}{a}\.\s?{b}(?!\d)\s*(—|–|-|\s|$)", L[i]): starts.append(i); k += 1
assert k == len(toc), (k, len(toc), toc[k] if k < len(toc) else None)
junk = [r"^\s*Eastern Caribbean Supreme Court \(Criminal Procedure\) Rules\s*$", r"^\s*PART \d+\s*$"]
ptitles = {v.upper() for v in parts.values()}
for j, (a, b, title) in enumerate(toc):
    s = starts[j]; e = starts[j + 1] if j + 1 < len(starts) else sched
    body = L[s:e]
    # drop trailing heading lines belonging to the next rule / next part
    nxt = toc[j + 1][2] if j + 1 < len(toc) else ""
    while body and (not body[-1].strip() or body[-1].strip().upper() in ptitles or re.fullmatch(r"\s*PART \d+\s*", body[-1])
                    or (nxt and nxt.lower().startswith(body[-1].strip().lower()[:25]) and len(body[-1].strip()) > 3)
                    or re.fullmatch(r"\s*\d{1,3}\s*", body[-1])
                    or (len(body[-1]) - len(body[-1].lstrip()) >= 15 and not body[-1].rstrip().endswith((".", ";", ":", ",")))):
        body = body[:-1]
    P = (".", ";", ":", ",", "—")
    nb = [i for i, x in enumerate(body) if x.strip()]
    tail = 0
    while tail < len(nb) and not body[nb[-1 - tail]].rstrip().endswith(P): tail += 1
    if 0 < tail <= 4 and tail < len(nb): body = body[:nb[-1 - tail] + 1]
    if j + 1 < len(toc) and toc[j + 1][0] != a:  # part boundary: drop part sub-headings
        while body and (len(body[-1].strip()) < 70 and not body[-1].rstrip().endswith((".", ";", ":", ",")) ): body = body[:-1]
    rid = f"ecsc-crpr-2026:r{a}.{b}"
    if rid in old: continue
    rows.append({"rule_id": rid, "rule_set_id": "ecsc-crpr-2026", "court_id": "lc-supreme-court", "jurisdiction": "ECSC",
        "applies_to": ["LC"] + sorted(others), "rule_set": "Eastern Caribbean Supreme Court (Criminal Procedure) Rules, 2026",
        "rule_number": f"Rule {a}.{b}", "title": title, "part": f"Part {a} – {parts.get(a, '').title()}", "text": clean(body, junk),
        "effective_date": "2026-02-02", "pdf_path": None, "pdf_sha256": sha, "source_sha256": sha, "source_url": CRPR, "index_url": IDX,
        "source_kind": "official", "site_policy": "no_robots_txt", "retrieved_at": now, "granularity": "rule",
        "license": "Official gazetted text (Saint Lucia S.I. 2026 No. 4) published on eccourts.org; no licence stated", "language": "en",
        "parallel_instruments": {cc: {"source_url": CRPR_OTHERS[cc], "pdf_sha256": h} for cc, h in others.items()},
        "version_note": "Text from the Saint Lucia gazetted copy; the same rules were gazetted separately in each listed member state (Antigua and Barbuda and Anguilla copies not found on eccourts.org)",
        "needs_review": True})
print("cpr2023 parts", n_cpr, "crpr2026 rules", len(rows) - n_cpr, "toc", len(toc))
if "--dry" in sys.argv:
    for r in rows[n_cpr:n_cpr + 3] + rows[-2:] + rows[:1]: print(json.dumps({k: (v[:400] if isinstance(v, str) else v) for k, v in r.items() if k in ("rule_id", "title", "part", "text")}, ensure_ascii=False))
else:
    with open(OUT, "a") as f:
        for r in rows: f.write(json.dumps(r, ensure_ascii=False) + "\n")
