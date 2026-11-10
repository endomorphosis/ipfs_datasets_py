#!/usr/bin/env python3
"""Courthouse seats (vestigingen) of the Gemeenschappelijk Hof van Justitie (GHvJ) and the
Gerechten in eerste aanleg for AW, CW, SX and BQ (Bonaire, Sint Eustatius, Saba), from the
official ghvj.org/contact/<island>/ pages. Append-only, dedup by court_id.
Robots: ghvj.org robots.txt allows all (checked); polite 2 s delay; honest UA."""
import json, re, html, time, datetime, hashlib, os, urllib.request
ROOT = "/workspace/world_courts/data"
UA = "WorldCourtsResearchBot/1.0 (court-data research; contact via Benjamin Barber)"
ISL = [("aruba","AW","AW","Gerecht in Eerste Aanleg van Aruba","Aruba"),
       ("curacao","CW","CW","Gerecht in Eerste Aanleg van Curaçao","Curaçao"),
       ("sint-maarten","SX","SX","Gerecht in Eerste Aanleg van Sint Maarten","Sint Maarten"),
       ("bonaire","BQ","BQ-BO","Gerecht in Eerste Aanleg van Bonaire, Sint Eustatius en Saba – zittingsplaats Bonaire","Bonaire"),
       ("sint-eustatius","BQ","BQ-SE","Gerecht in Eerste Aanleg van Bonaire, Sint Eustatius en Saba – zittingsplaats Sint Eustatius","Sint Eustatius"),
       ("saba","BQ","BQ-SA","Gerecht in Eerste Aanleg van Bonaire, Sint Eustatius en Saba – zittingsplaats Saba","Saba")]
EN = {"AW":"Court of First Instance of Aruba","CW":"Court of First Instance of Curaçao","SX":"Court of First Instance of Sint Maarten"}
def text(u):
    t = urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": UA}), timeout=30).read().decode("utf-8","replace")
    s = re.sub(r'<script.*?</script>|<style.*?</style>|<!--.*?-->', '', t, flags=re.S)
    s = html.unescape(re.sub(r'<[^>]+>', '\n', s)); return re.sub(r'\n\s*\n+', '\n', s), t
def field(s, label):
    m = re.search(label + r'\s*\n?\s*:\s*\n?\s*([^\n]+)', s); return m.group(1).strip().rstrip('.') if m else None
now = datetime.datetime.now(datetime.timezone.utc).isoformat()
rows = {}
for slug, cc, sub, name, island in ISL:
    u = f"https://ghvj.org/contact/{slug}/"; s, raw = text(u); time.sleep(2)
    adr = field(s, "Adres"); tel = field(s, "Algemeen telefoonnummer")
    hrs = re.search(r'Openingstijden informatiebalie\n([^\n]+)', s)
    parts = [p.strip() for p in (adr or "").split(",")]
    street = ", ".join(parts[:-2]) if len(parts) >= 3 else (parts[0] if parts else None)
    city = parts[-2] if len(parts) >= 3 else None
    cid = f"{cc.lower()}-ghvj-gea-{slug}"
    r = {"court_id": cid, "record_type": "courthouse", "name": EN.get(cc, f"Court of First Instance of Bonaire, Sint Eustatius and Saba – {island} seat"),
         "name_local": name, "level": "trial", "court_system": "national", "country_code": cc, "subdivision": sub,
         "jurisdiction": island, "parent_court_id": f"{cc.lower()}-lower-court" if cc != "BQ" else None,
         "address": {"street": street, "city": city, "postcode": None, "region": island, "country": cc},
         "geo": {"lat": None, "lon": None}, "phone": tel, "website": u, "wikidata": None, "place_ids": [],
         "source_url": u, "source_kind": "official",
         "site_policy": "robots_allowed|ghvj.org (Gemeenschappelijk Hof van Justitie van Aruba, Curaçao, Sint Maarten en van Bonaire, Sint Eustatius en Saba) official contact page; no licence stated",
         "retrieved_at": now, "license": "official public information; no licence stated",
         "sources": [{"source_url": u, "site_policy": "robots_allowed|ghvj.org", "source_kind": "official"}],
         "opening_hours_note": hrs.group(1).strip() if hrs else None,
         "record_note": "GHvJ vestiging; the Joint Court of Justice (appeal) also sits at this seat. Address as published; not geocoded.",
         "source_sha256": hashlib.sha256(raw.encode()).hexdigest(), "needs_review": False, "language": "nl"}
    rows.setdefault(cc, []).append(r)
added = {}
for cc, rs in rows.items():
    p = f"{ROOT}/{cc.lower()}/{cc.lower()}_courthouses.jsonl"
    have = set()
    if os.path.exists(p):
        for l in open(p):
            if l.strip(): have.add(json.loads(l)["court_id"])
    new = [r for r in rs if r["court_id"] not in have]
    with open(p, "a") as f:
        for r in new: f.write(json.dumps(r, ensure_ascii=False) + "\n")
    added[cc] = len(new)
print(added)
