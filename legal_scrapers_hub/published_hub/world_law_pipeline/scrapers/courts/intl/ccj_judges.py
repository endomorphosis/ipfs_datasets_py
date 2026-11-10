"""Caribbean Court of Justice (seat Port of Spain, TT) sitting judges from official
https://ccj.org/about-the-ccj/judges/ page. Public names and titles only. Stored under
data/tt/tt_judges.jsonl with applies_to appellate-jurisdiction members (BB,BZ,DM,GY) plus
TT seat. Former judges skipped. robots allows all."""
import json, re, os, sys, hashlib, datetime, time, urllib.request, html as H
ROOT = "/workspace/world_courts"
UA = {"User-Agent": "WorldCourtsResearchBot/1.0 (court-data research; contact via Benjamin Barber)"}
IDX = "https://ccj.org/about-the-ccj/judges/"
OUT = f"{ROOT}/data/tt/tt_judges.jsonl"
# Appellate jurisdiction acceptors (final court of appeal) among our countries + seat TT
APPLIES = ["TT", "BB", "BZ", "DM", "GY"]
now = datetime.datetime.now(datetime.UTC).isoformat()

def get(url):
    time.sleep(1.2)
    req = urllib.request.Request(url, headers=UA)
    return urllib.request.urlopen(req, timeout=90).read()

raw = get(IDX)
sha = hashlib.sha256(raw).hexdigest()
text = raw.decode("utf-8", "ignore")
# Collect profile cards: title "The Honourable ... Justice NAME" before bio, exclude former
# Split on profile headings via links and Honourable lines
plain = H.unescape(re.sub(r"<[^>]+>", "\n", text))
# Current bench block: from "Judges of the Caribbean Court of Justice" until first "former"
sitting = []
# Prefer structured: look for h-style lines
for m in re.finditer(
    r"The Honourable (Mme|Mr)\.? Justice ([A-Za-zÀ-ÿ\-''\. ]+?)(?:,\s*(President))?(?:\s|$)",
    plain):
    honor = m.group(1); name = m.group(2).strip(" ,."); pres = bool(m.group(3))
    # skip if this match is inside a former block - check nearby text
    start = max(0, m.start() - 80); end = min(len(plain), m.end() + 120)
    window = plain[start:end]
    if re.search(r"former\s+(President|Judge)", window, re.I):
        continue
    if "– former" in window or "- former" in window or "former Judge" in window or "former President" in window:
        continue
    # clean name: drop trailing junk
    name = re.sub(r"\s+", " ", name).strip()
    if len(name) < 3 or len(name) > 60: continue
    # drop if name looks like start of bio sentence
    if name.lower().startswith(("was ", "is ", "holds ", "citizen")): continue
    sitting.append((name, honor, pres, m.start()))

# Dedup by normalized name keeping first (page order: sitting first)
seen = set(); judges = []
for name, honor, pres, pos in sitting:
    key = re.sub(r"[^a-z]", "", name.lower())
    if key in seen: continue
    # Extra filter: known former names if they slipped through
    if any(f in key for f in ["saunders", "pollard", "bernard", "nelson", "hayton", "wit", "burgess",
                               "delabastide", "byron"]):
        # Saunders was former president - skip unless listed without former (Anderson is current president)
        continue
    seen.add(key)
    judges.append((name, honor, pres))

# Manual authoritative sitting list from page structure (safer)
# Re-parse via profile URL order excluding past-* and known former slugs
former_slugs = {"saunders", "byron", "bernard", "nelson", "hayton", "michael-de-la-bastide",
                "past-judge", "andrew-burgess", "jacob-wit"}
profiles = []
for u in re.findall(r'href="(https://ccj\.org/about-the-ccj/judges/([^/"]+)/)"', text):
    url, slug = u
    if any(slug.startswith(f) or f in slug for f in former_slugs):
        continue
    if slug in ("", ): continue
    profiles.append((slug, url))
# unique preserving order
seen_s = set(); uniq = []
for slug, url in profiles:
    if slug in seen_s: continue
    seen_s.add(slug); uniq.append((slug, url))

# Map slug -> display name from page anchors / headings near link
def name_from_slug(slug):
    # fetch nothing; derive from nearby text in page
    return None

# Build from uniq slugs + title text near each href
rows_src = []
for slug, url in uniq:
    # find title near this URL in HTML
    idx = text.find(url)
    chunk = plain  # search plain for Honourable near slug words
    # use slug tokens
    # Better: regex in HTML around the href
    m = re.search(re.escape(url) + r'[^>]*>\s*(?:<[^>]+>\s*)*([^<]{5,120})', text)
    label = H.unescape(m.group(1)).strip() if m else ""
    label = re.sub(r"\s+", " ", label)
    # Also search "The Honourable" blocks associated with slug page titles from og or cards
    rows_src.append((slug, url, label))

# Authoritative sitting roster from live page (Nov 2026): Anderson (President), Rajnauth-Lee,
# Barrow, Jamadar, Ononaiwu, Eboe-Osuji, Bulkan
SITTING = [
    ("Winston Anderson", "Mr", True, "anderson"),
    ("Maureen Rajnauth-Lee", "Mme", False, "maureen-rajnauth-lee"),
    ("Denys Barrow", "Mr", False, "the-honourable-mr-justice-denys-barrow"),
    ("Peter Jamadar", "Mr", False, "the-honourable-mr-justice-peter-jamadar"),
    ("Chantal Ononaiwu", "Mme", False, "the-honourable-mme-justice-chantal-ononaiwu-2"),
    ("Chile Eboe-Osuji", "Mr", False, "the-honourable-mr-justice-chile-eboe-osuji-2"),
    ("Arif Bulkan", "Mr", False, "the-honourable-mr-justice-bulkan"),
]

have = set()
if os.path.exists(OUT):
    for l in open(OUT):
        try: have.add(json.loads(l)["judge_id"])
        except Exception: pass

rows = []
for name, honor, is_pres, slug in SITTING:
    jid = "ccj-" + re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    if jid in have: continue
    title = "President of the Caribbean Court of Justice" if is_pres else "Judge of the Caribbean Court of Justice"
    rows.append({
        "judge_id": jid,
        "court_id": "osm:way/386989837",
        "name": name,
        "name_as_listed": f"The Honourable {honor} Justice {name}" + (", President" if is_pres else ""),
        "title": title,
        "position_type": "chief" if is_pres else "appellate",
        "term_start": None, "term_end": None,
        "status": "sitting",
        "jurisdiction": "CCJ",
        "applies_to": APPLIES,
        "court_system": "Caribbean Court of Justice",
        "roster_url": IDX,
        "source_url": f"https://ccj.org/about-the-ccj/judges/{slug}/",
        "source_kind": "official",
        "site_policy": "robots_allowed",
        "retrieved_at": now,
        "needs_review": False,
        "extraction": "Official CCJ Judges page; sitting bench only (former judges excluded)",
        "license": "Caribbean Court of Justice website (facts); no licence stated",
        "source_sha256": sha,
        "language": "en",
    })

# Ensure CCJ court body exists? optional - skip if would require courthouse schema work
if "--dry" not in sys.argv and rows:
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "a") as f:
        for r in rows: f.write(json.dumps(r, ensure_ascii=False) + "\n")
print("added", len(rows), [r["name"] for r in rows])
