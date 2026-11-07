"""India High Court sitting judges (permanent + additional) from Wikipedia
'List of sitting judges of the high courts of India' (secondary source, CC BY-SA 4.0).
Official HC sites (bombayhighcourt.nic.in, phhc.gov.in, hckerala.gov.in, ...) unreachable from this box.
Rows needs_review=True. Usage: python3 in_hc_judges_wiki.py [cached_parse.json]"""
import json, re, sys, os, io, datetime, urllib.request
from bs4 import BeautifulSoup
from dateutil import parser as dp
PAGE = "List_of_sitting_judges_of_the_high_courts_of_India"
UA = "WorldCourtsResearchBot/1.0 (public court directory research)"
OUT = "/workspace/world_courts/data/in/in_judges.jsonl"
CH = "/workspace/world_courts/data/in/in_courthouses.jsonl"
def slug(s): return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")
if len(sys.argv) > 1: d = json.load(open(sys.argv[1]))["parse"]
else:
    u = f"https://en.wikipedia.org/w/api.php?action=parse&page={PAGE}&prop=text|revid&format=json&formatversion=2"
    d = json.load(urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": UA}), timeout=60))["parse"]
rev = d["revid"]; src = f"https://en.wikipedia.org/w/index.php?title={PAGE}&oldid={rev}"
ids = {json.loads(l)["court_id"]: json.loads(l)["name"] for l in open(CH)}
MAP = {"gauhati": "in-hc-gauhati", "guwahati": "in-hc-gauhati", "jammu & kashmir and ladakh": "in-hc-jammu-kashmir-ladakh",
       "punjab and haryana": "in-hc-punjab-haryana"}
def court_for(h):
    k = h.lower().replace(" high court", "").replace("high court of ", "").strip()
    cid = MAP.get(k, "in-hc-" + slug(k))
    if cid not in ids: raise SystemExit(f"no court id for {h} -> {cid}")
    return cid
def date(s):
    s = re.sub(r"\[.*?\]", "", s or "").strip()
    if not s or s in ("--", "-"): return None
    try: return dp.parse(s, dayfirst=True).date().isoformat()
    except Exception: return None
now = datetime.datetime.now(datetime.timezone.utc).isoformat()
soup = BeautifulSoup(d["text"], "lxml")
rows, h2 = [], None
for el in soup.find_all(["h2", "table"]):
    if el.name == "h2": h2 = el.get_text(strip=True); continue
    cap = el.find("caption"); cap = cap.get_text(" ", strip=True).lower() if cap else ""
    if not h2 or "High Court" not in h2 or not (cap.startswith("permanent") or cap.startswith("additional")): continue
    cid = court_for(h2); addl = cap.startswith("additional")
    trs = el.find_all("tr"); hdr = [c.get_text(" ", strip=True) for c in trs[0].find_all(["th", "td"])]
    for tr in trs[1:]:
        cells = [c.get_text(" ", strip=True) for c in tr.find_all(["th", "td"])]
        if len(cells) < 3: continue
        raw = re.sub(r"\[.*?\]", "", cells[0]).strip()
        if not raw or raw.startswith("--"): continue
        m = re.search(r"\((A\.?C\.?J|CJ|ACJ)\)", raw, re.I)
        name = re.sub(r"\s*\(.*?\)\s*", " ", raw).strip()
        name = re.sub(r"^(Justice|Hon'?ble)\s+", "", name).strip()
        rec = dict(zip(hdr, cells))
        if m and m.group(1).upper().replace(".", "") == "CJ": title, pt = "Chief Justice", "chief"
        elif m: title, pt = "Acting Chief Justice", "chief"
        elif addl: title, pt = "Additional Judge", "associate"
        else: title, pt = "Judge", "associate"
        ts = date(cells[2]) or (date(cells[3]) if not addl and len(cells) > 3 else None)
        te = None
        for k, v in rec.items():
            if "retire" in k.lower() or "expiry" in k.lower(): te = date(v)
        rows.append({"judge_id": f"{cid}-{slug(name)}", "court_id": cid, "name": name, "name_as_listed": raw,
            "title": title, "position_type": pt, "term_start": ts, "term_end": te, "status": "sitting",
            "jurisdiction": "IN", "roster_url": src, "source_url": src, "source_kind": "secondary",
            "site_policy": "robots_allowed|en.wikipedia.org: CC BY-SA 4.0, attribution required (Wikimedia Terms of Use)",
            "retrieved_at": now, "needs_review": True,
            "extraction": f"Wikipedia rev {rev}, section '{h2}', table '{cap}'; official HC rosters unreachable",
            "license": "CC BY-SA 4.0 (Wikipedia contributors)"})
existing = set(); keep = []
if os.path.exists(OUT):
    for l in open(OUT):
        r = json.loads(l); existing.add(r["judge_id"]); keep.append(l)
new = [r for r in rows if r["judge_id"] not in existing]
seen = set(); new = [r for r in new if not (r["judge_id"] in seen or seen.add(r["judge_id"]))]
with open(OUT, "a") as f:
    for r in new: f.write(json.dumps(r, ensure_ascii=False) + "\n")
import collections
print("parsed", len(rows), "new", len(new), collections.Counter(r["court_id"] for r in new).most_common())
