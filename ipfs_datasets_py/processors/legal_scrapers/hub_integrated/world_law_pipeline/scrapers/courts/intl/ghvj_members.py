"""CW/AW/SX/BQ: Gemeenschappelijk Hof van Justitie (ghvj.org).
Members (leden), substitute members (plv. leden) and substitute judges (rechters-plaatsvervanger)
from the official public register of side functions ('Register nevenfuncties Rechterlijke Macht',
art. 26(4) Rijkswet GHvJ). Names + official role only; side functions and non-judicial staff omitted.
Primary seat Willemstad (CW); identical roster also written under AW/SX/BQ (shared court) with
applies_to AW/CW/SX/BQ. robots.txt allows all."""
import json, re, os, sys, hashlib, datetime, subprocess, time, requests, unicodedata
from bs4 import BeautifulSoup as B
ROOT = "/workspace/world_courts"
H = {"User-Agent": "WorldCourtsResearchBot/1.0 (court-data research; contact via Benjamin Barber)"}
IDX = "https://ghvj.org/over-het-hof/nevenfuncties-rechterlijke-macht/"
CCS = ["cw", "aw", "sx", "bq"]
OUTS = {cc: f"{ROOT}/data/{cc}/{cc}_judges.jsonl" for cc in CCS}
COURT = {"cw": "osm:way/1446424248", "aw": "aw-ghvj-gea-aruba", "sx": "sx-ghvj-gea-sint-maarten",
         "bq": "bq-ghvj-gea-bonaire"}
now = datetime.datetime.now(datetime.UTC).isoformat()
def slug(s):
    return re.sub(r"[^a-z0-9]+", "-", unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()).strip("-")
s = B(requests.get(IDX, headers=H, timeout=60).text, "html.parser"); time.sleep(2)
pdf = next(a["href"] for a in s.find_all("a", href=True) if re.search(r"nevenfuncties.*\.pdf$", a["href"], re.I))
if pdf.startswith("/"): pdf = "https://ghvj.org" + pdf
c = requests.get(pdf, headers=H, timeout=120).content
sha = hashlib.sha256(c).hexdigest()
open("/tmp/ghvj_reg.pdf", "wb").write(c)
T = subprocess.run(["pdftotext", "-layout", "/tmp/ghvj_reg.pdf", "-"], capture_output=True, text=True).stdout
asof = re.search(r"\(per ([a-z]+ \d{4})\)", T)
asof = asof.group(1) if asof else None
ROLE = {"lid": ("Lid (member)", "associate"), "vice-president": ("Vice-president", "vice_president"),
        "vice-": ("Vice-president", "vice_president"),
        "plv. lid": ("Plaatsvervangend lid (substitute member)", "substitute"),
        "plv lid": ("Plaatsvervangend lid (substitute member)", "substitute"),
        "plv.": ("Plaatsvervangend lid (substitute member)", "substitute"),
        "rechter-plv": ("Rechter-plaatsvervanger (substitute judge)", "substitute"),
        "rechter-plv.": ("Rechter-plaatsvervanger (substitute judge)", "substitute"),
        "rechter-": ("Rechter-plaatsvervanger (substitute judge)", "substitute"),
        "president": ("President", "chief")}
have = {cc: set() for cc in CCS}
for cc, path in OUTS.items():
    if os.path.exists(path):
        for l in open(path):
            try: have[cc].add(json.loads(l)["judge_id"])
            except Exception: pass
rows = {cc: [] for cc in CCS}; skipped = []
for l in T.split("\n"):
    left = re.split(r"\s{3,}-\s{3,}|\s{5,}", l.strip())[0]
    m = re.match(r"^((?:(?:mr|Mr|drs|prof|dr|Prof|Dr)\.\s*)+)(.+?)\s*\(([^)]*)\)?\s*$", left)
    if not m: continue
    nm = m.group(2).strip(" ,"); role = m.group(3).strip().lower()
    if role not in ROLE: skipped.append((nm, role)); continue
    title, pt = ROLE[role]; jid = f"ghvj-{slug(nm)}"
    for cc in CCS:
        if jid in have[cc]: continue
        have[cc].add(jid)
        rows[cc].append({
            "judge_id": jid, "court_id": COURT[cc], "name": nm,
            "name_as_listed": f"{m.group(1).strip()} {nm}", "title": title,
            "title_local": m.group(3).strip(), "position_type": pt,
            "term_start": None, "term_end": None, "status": "sitting",
            "jurisdiction": "GHvJ", "applies_to": ["AW", "CW", "SX", "BQ"],
            "roster_url": IDX, "source_url": pdf, "source_kind": "official",
            "site_policy": "robots_allowed|ghvj.org: no licence stated; register published by law (art. 26(4) Rijkswet GHvJ)",
            "retrieved_at": now, "needs_review": False,
            "extraction": f"GHvJ register of side functions (names + role only; side functions not stored), as of {asof}",
            "license": "official public register; no licence stated",
            "source_sha256": sha, "language": "nl"})
if "--dry" not in sys.argv:
    for cc, rs in rows.items():
        if not rs: continue
        os.makedirs(os.path.dirname(OUTS[cc]), exist_ok=True)
        with open(OUTS[cc], "a") as f:
            for x in rs: f.write(json.dumps(x, ensure_ascii=False) + "\n")
print("added", {cc: len(rs) for cc, rs in rows.items()}, "skipped", skipped, "as of", asof)
