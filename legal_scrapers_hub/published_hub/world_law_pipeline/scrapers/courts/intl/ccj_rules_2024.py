"""CCJ Appellate Jurisdiction Rules 2024 and Original Jurisdiction Rules 2024 from official
PDFs on ccj.org. Part-level rows appended to data/tt/tt_rules.jsonl. Dedup by rule_id.
AJR applies_to appellate acceptors; OJR applies_to CARICOM members in our scope. robots allows."""
import json, re, os, sys, hashlib, datetime, subprocess, time, urllib.request
ROOT = "/workspace/world_courts"
RAW = f"{ROOT}/rules/raw/tt"
OUT = f"{ROOT}/data/tt/tt_rules.jsonl"
UA = {"User-Agent": "WorldCourtsResearchBot/1.0 (court-data research; contact via Benjamin Barber)"}
IDX = "https://ccj.org/rules/"
now = datetime.datetime.now(datetime.UTC).isoformat()
AJR = ("https://ccj.org/wp-content/uploads/2024/05/Caribbean-Court-of-Justice-Appellate-Jurisdiction-Rules-2024.pdf",
       "ccj-ajr-2024", "Caribbean Court of Justice (Appellate Jurisdiction) Rules 2024",
       ["TT", "BB", "BZ", "DM", "GY"])
OJR = ("https://ccj.org/wp-content/uploads/2024/05/Caribbean-Court-of-Justice-Original-Jurisdiction-Rules-2024-.pdf",
       "ccj-ojr-2024", "Caribbean Court of Justice (Original Jurisdiction) Rules 2024",
       ["TT", "AG", "BB", "BZ", "DM", "GD", "GY", "HT", "JM", "KN", "LC", "SR", "VC"])  # CARICOM in scope

def fetch(url, name):
    os.makedirs(RAW, exist_ok=True)
    path = f"{RAW}/{name}"
    if not os.path.exists(path) or os.path.getsize(path) < 1000:
        time.sleep(2)
        req = urllib.request.Request(url, headers=UA)
        open(path, "wb").write(urllib.request.urlopen(req, timeout=180).read())
    return path, hashlib.sha256(open(path, "rb").read()).hexdigest()

def parts_from_pdf(path):
    lines = subprocess.run(["pdftotext", "-layout", path, "-"], capture_output=True, text=True).stdout.splitlines()
    hdrs = []
    for i, l in enumerate(lines):
        # Match PART 10 / PART 10A etc. Whole line is just PART N or PART N + title
        m = re.match(r"^\s*PART\s+([0-9]+[A-Za-z]?)\s*$", l, re.I)
        if m:
            hdrs.append((i, m.group(1).upper(), ""))
            continue
        m = re.match(r"^\s*PART\s+([0-9]+[A-Za-z]?)\s*[:.\-]?\s+(.+)$", l.strip(), re.I)
        if m:
            hdrs.append((i, m.group(1).upper(), m.group(2).strip()))
    by = {}
    for i, num, rest in hdrs:
        by.setdefault(num, []).append((i, rest))
    # Body starts after TOC: take the last occurrence of each part number
    ordered = []
    for num, occ in by.items():
        i, rest = occ[-1]
        title = rest
        if not title or len(title) < 4 or title.upper().startswith("RULE ") or title.startswith("A,"):
            title = ""
            for j in range(i + 1, min(i + 8, len(lines))):
                s = lines[j].strip()
                if not s: continue
                if re.match(r"^Contents of this Part", s, re.I): continue
                if re.match(r"^PART\s+", s, re.I): break
                # Title lines are typically ALL CAPS / Title Case short headings
                if len(s) < 120 and not re.match(r"^\d", s) and "Rule " not in s:
                    title = s; break
        ordered.append((i, num, title))
    ordered.sort(key=lambda x: x[0])
    rows = []
    for k, (i, num, title) in enumerate(ordered):
        end = ordered[k + 1][0] if k + 1 < len(ordered) else len(lines)
        body = "\n".join(lines[i:end]).strip()
        body = re.sub(r"\n{3,}", "\n\n", body)
        rows.append((num, title, body, i))
    return rows, hashlib.sha256(open(path, "rb").read()).hexdigest()

have = set()
if os.path.exists(OUT):
    for l in open(OUT):
        try: have.add(json.loads(l)["rule_id"])
        except Exception: pass

out_rows = []
for url, sid, rset, applies in (AJR, OJR):
    name = url.rstrip("/").rsplit("/", 1)[-1]
    path, sha = fetch(url, name)
    parts, sha2 = parts_from_pdf(path)
    sha = sha or sha2
    print(sid, "parts", len(parts), "file", path, "sha", sha[:12])
    for num, title, body, _ in parts:
        rid = f"{sid}:part{str(num).lower()}"
        if rid in have: continue
        have.add(rid)
        out_rows.append({
            "rule_id": rid, "rule_set_id": sid, "court_id": "osm:way/386989837",
            "jurisdiction": "CCJ", "applies_to": applies, "rule_set": rset,
            "rule_number": f"Part {num}", "title": title or f"Part {num}",
            "text": body[:200000], "effective_date": "2024",
            "pdf_path": f"rules/raw/tt/{name}", "pdf_sha256": sha, "source_sha256": sha,
            "source_url": url, "index_url": IDX, "source_kind": "official",
            "site_policy": "robots_allowed", "retrieved_at": now, "granularity": "part",
            "license": "Official CCJ rules published on ccj.org; no licence stated",
            "language": "en", "needs_review": False,
            "version_note": "2024 consolidation PDF from ccj.org/rules",
        })

if "--dry" not in sys.argv and out_rows:
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "a") as f:
        for r in out_rows: f.write(json.dumps(r, ensure_ascii=False) + "\n")
print("added", len(out_rows))
