"""Aruba: Wetboek van Burgerlijke Rechtsvordering van Aruba (AB 2005 no. 34, consolidated in the
Centraal Wettenregister 14 Nov 2024, through AB 2023 nos. 24 and 56), official PDF published by the
Government of Aruba (gobierno.aw page 15.06 -> cuatro.sim-cdn.nl/arubaoverheid2858bd CDN).
Article-level rows -> data/aw/aw_rules.jsonl (dedup by rule_id). pdftotext -layout, text PDF (no OCR)."""
import re, json, hashlib, os, subprocess, urllib.request, datetime, time
W = "/workspace/world_courts"; RAW = f"{W}/rules/raw/aw"; OUT = f"{W}/data/aw/aw_rules.jsonl"
UA = "WorldCourtsResearchBot/1.0 (court-data research; contact via Benjamin Barber)"
URL = "https://cuatro.sim-cdn.nl/arubaoverheid2858bd/uploads/1506ab05.034.pdf?cb=jOGWjRdl"
INDEX = "https://www.gobierno.aw/nl/1506-wetboek-van-burgerlijke-rechtsvordering"
PDF = f"{RAW}/1506ab05.034.pdf"
POLICY = ("robots_allowed|cuatro.sim-cdn.nl robots.txt has no rule for this path; gobierno.aw robots.txt only disallows named SEO bots|"
          "official Government of Aruba legislation register (Centraal Wettenregister), no restrictive terms found|single PDF download")
RSID = "aw-rv"; RS = "Wetboek van Burgerlijke Rechtsvordering van Aruba (AB 2005 no. 34, as amended to AB 2023 nos. 24 and 56)"
os.makedirs(RAW, exist_ok=True)
if not os.path.exists(PDF) or os.path.getsize(PDF) < 100000:
    open(PDF, "wb").write(urllib.request.urlopen(urllib.request.Request(URL, headers={"User-Agent": UA}), timeout=120).read())
sha = hashlib.sha256(open(PDF, "rb").read()).hexdigest()
txt = subprocess.run(["pdftotext", "-layout", PDF, "-"], capture_output=True, text=True).stdout
lines = []
for l in txt.split("\n"):
    s = l.strip()
    if re.fullmatch(r"\*+", s) or s.startswith("====") or re.match(r"AB 2005 no\. 34\s+\*CENTRAAL", s) or re.fullmatch(r"\d{1,3}", s) or "\f" in l and not s:
        continue
    lines.append(l.replace("\f", ""))
start = next(i for i, l in enumerate(lines) if l.strip() == "VOORAFGAANDE BEPALINGEN")
lines = lines[start:]
hdr = {"BOEK": None, "TITEL": None, "AFDELING": None}
rows, cur, i = [], None, 0
def flush():
    if cur:
        t = "\n".join(cur["buf"]).strip()
        t = re.sub(r"-\n\s*(?=[a-z])", "", t); t = re.sub(r"[ \t]+", " ", t); t = re.sub(r"\n\s*\n+", "\n", t)
        cur["text"] = t; rows.append(cur)
while i < len(lines):
    s = lines[i].strip()
    m = re.fullmatch(r"(BOEK|TITEL|AFDELING) (\d+[A-Z]?|[IVX]+)", s)
    if m and lines[i].startswith("    "):
        # heading title = following non-empty centred lines until blank
        j = i + 1; tl = []
        while j < len(lines) and not lines[j].strip(): j += 1
        while j < len(lines) and lines[j].strip() and not re.match(r"\s*Artikel ", lines[j]):
            tl.append(lines[j].strip()); j += 1
        k = m.group(1)
        hdr[k] = f"{k.capitalize()} {m.group(2)}" + (f" {' '.join(tl)}" if tl else "")
        if k == "BOEK": hdr["TITEL"] = hdr["AFDELING"] = None
        if k == "TITEL": hdr["AFDELING"] = None
        i = j; continue
    if s in ("SLOTBEPALINGEN", "OVERGANGSBEPALINGEN", "OVERGANGS- EN SLOTBEPALINGEN") and lines[i].startswith("          "):
        hdr["TITEL"] = s.capitalize(); hdr["AFDELING"] = None; i += 1; continue
    m = re.fullmatch(r"Artikel (\d+[a-z]{0,3}|[A-Z])", s)
    if m and len(lines[i]) - len(lines[i].lstrip()) >= 15:
        flush()
        cur = dict(num=m.group(1), part=" > ".join(v for v in (hdr["BOEK"], hdr["TITEL"], hdr["AFDELING"]) if v) or "Voorafgaande bepalingen", buf=[])
        i += 1; continue
    if cur is not None: cur["buf"].append(lines[i])
    i += 1
flush()
now = datetime.datetime.now(datetime.timezone.utc).isoformat()
seen = set(); out = []
for r in rows:
    rid = f"{RSID}:art{r['num']}"
    n = 2
    while rid in seen: rid = f"{RSID}:art{r['num']}-{n}"; n += 1
    seen.add(rid)
    out.append(dict(rule_id=rid, rule_set_id=RSID, court_id="aw-lower-court", jurisdiction="AW", applies_to=["AW"],
        rule_set=RS, rule_number=f"Artikel {r['num']}", title=None, part=r["part"], text=r["text"],
        effective_date=None, pdf_path="rules/raw/aw/1506ab05.034.pdf", pdf_sha256=sha, source_sha256=sha,
        source_url=URL, index_url=INDEX, source_kind="official", site_policy=POLICY,
        license="Aruba legislation (public law, official consolidated text); no licence stated", retrieved_at=now, language="nl",
        needs_review=bool(rid.count("-") > 1 or len(r["text"]) < 15 or "vervallen" == r["text"].strip(". ").lower()),
        version_note="Centraal Wettenregister consolidation dated 14 Nov 2024 (through AB 2023 nos. 24, 56); pdftotext -layout; articles shown as 'Vervallen' kept as repealed"))
existing = set()
if os.path.exists(OUT):
    existing = {json.loads(l)["rule_id"] for l in open(OUT)}
new = [r for r in out if r["rule_id"] not in existing]
with open(OUT, "a") as f:
    for r in new: f.write(json.dumps(r, ensure_ascii=False) + "\n")
print("parsed", len(out), "new", len(new), "review", sum(r["needs_review"] for r in new))
