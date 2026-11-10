"""JM: Parish Courts (13 parishes, parishcourt.gov.jm sidebar; crawl-delay 10 respected) and Supreme Court judges (supremecourt.gov.jm/content/current-judges). Names/titles only."""
import json, sys, re, datetime, hashlib, html, os
sys.path.insert(0, "/workspace/world_courts/scrapers/courts/intl")
from row_common import *
now = datetime.datetime.now(datetime.UTC).isoformat(); RAW = f"{ROOT}/rules/raw/jm"
def sha(p): return hashlib.sha256(open(p, "rb").read()).hexdigest()
def slug(s): return re.sub(r"[^a-z0-9]+", "-", norm(s)).strip("-")[:90]
S = "https://parishcourt.gov.jm/"; P = f"{RAW}/pc_home.html"
PAR = [("Kingston and St. Andrew", "Kingston", "JM-01"), ("St. Catherine", "Spanish Town", "JM-14"), ("Clarendon", "May Pen", "JM-13"), ("Manchester", "Mandeville", "JM-12"),
       ("St. Elizabeth", "Black River", "JM-11"), ("Westmoreland", "Savanna-la-Mar", "JM-10"), ("Hanover", "Lucea", "JM-09"), ("St. James", "Montego Bay", "JM-08"),
       ("Trelawny", "Falmouth", "JM-07"), ("St. Ann", "St. Ann's Bay", "JM-06"), ("St. Mary", "Port Maria", "JM-05"), ("Portland", "Port Antonio", "JM-04"), ("St. Thomas", "Morant Bay", "JM-03")]
CO = f"{ROOT}/data/jm/jm_courthouses.jsonl"; old = [json.loads(l) for l in open(CO)]; ids = {r["court_id"] for r in old}; names = {norm(r["name"]) for r in old}; new = []
for par, town, sub in PAR:
    nm = f"{par} Parish Court"; cid = f"jm-pc-{slug(par)}"
    if cid in ids or norm(nm) in names: continue
    new.append({"court_id": cid, "record_type": "court_body", "name": nm, "name_local": None, "level": "trial_limited", "court_system": "national", "country_code": "JM", "subdivision": sub,
      "jurisdiction": f"Parish of {par}", "parent_court_id": "jm-lower-court", "address": {"street": None, "city": town, "postcode": None, "region": par, "country": "Jamaica"},
      "geo": {"lat": None, "lon": None}, "phone": None, "website": S, "wikidata": None, "place_ids": rmatch([town], "JM"), "source_url": S, "source_kind": "official",
      "site_policy": "robots_allowed(crawl-delay 10)", "retrieved_at": now, "license": "Judiciary of Jamaica website (facts)", "source_sha256": sha(P),
      "sources": [{"source_url": S, "site_policy": "robots_allowed(crawl-delay 10)", "source_kind": "official"}],
      "record_note": "Parish Court (court body for the parish; may sit at several courthouses). City = parish capital (assumed)", "needs_review": True})
with open(CO, "a") as f:
    for r in new: f.write(json.dumps(r, ensure_ascii=False) + "\n")
print("courts +", len(new))
S = "https://supremecourt.gov.jm/content/current-judges"; P = f"{RAW}/sc_judges.html"
t = html.unescape(re.sub(r"<[^>]+>", "\n", re.sub(r"(?s)<(script|style|head).*?</\1>", "", open(P, errors="ignore").read())))
JO = f"{ROOT}/data/jm/jm_judges.jsonl"; jids = {json.loads(l)["judge_id"] for l in open(JO)} if os.path.exists(JO) else set(); J = []; sec = "Puisne Judge"
for l in t.split("\n"):
    s = re.sub(r"\s+", " ", l).strip()
    if re.search(r"Masters? in Chambers", s, re.I) and len(s) < 60: sec = "Master in Chambers"
    m = re.match(r"^(?:The Hon(?:ourable|\.)|Her Hon\.|His Hon\.)\s+(Mr\.|Mrs\.|Miss|Ms\.)?\s*(?:Justice\s+)?(.+)$", s)
    if not m: continue
    name = re.split(r"\s+[–-]\s+|,\s*(?:O\.J|CD|C\.D)|\s+Ag\b", m.group(2))[0].strip(" ,")
    note = s[len(m.group(0)) - len(m.group(2)) + len(name):].strip(" ,–-")
    cj = "Sykes" in name; title = "Chief Justice" if cj else (sec + (f" ({note})" if note and len(note) < 80 else ""))
    jid = f"jm-supreme-court-{slug(name)}"
    if jid in jids or any(j["judge_id"] == jid for j in J): continue
    J.append({"judge_id": jid, "court_id": "jm-supreme-court", "name": name, "title": title, "position_type": "chief" if cj else ("master" if sec.startswith("Master") else "trial"),
      "term_start": None, "term_end": None, "status": "sitting", "roster_url": S, "source_url": S, "site_policy": "robots_allowed", "retrieved_at": now, "needs_review": sec.startswith("Master") or "Her Hon" in s,
      "extraction": "official 'Current Judges' page (names and titles only)", "license": "Judiciary of Jamaica website (facts)", "source_sha256": sha(P)})
with open(JO, "a") as f:
    for j in J: f.write(json.dumps(j, ensure_ascii=False) + "\n")
print("judges +", len(J)); [print(" ", j["name"], "|", j["title"]) for j in J[:3] + J[-4:]]
