"""PK-BA: Balochistan High Court 'District Judiciary' sessions divisions list (bhc.gov.pk, robots allows /district-judiciary). One District & Sessions Court row per division."""
import json, sys, re, datetime
sys.path.insert(0, "/workspace/world_courts/scrapers/courts/intl")
from row_common import *
from bs4 import BeautifulSoup as B
now = datetime.datetime.now(datetime.UTC).isoformat(); OUT = f"{ROOT}/data/pk/pk_courthouses.jsonl"
old = [json.loads(l) for l in open(OUT)]; oldn = " | ".join(norm(r["name"]) + " " + norm((r.get("address") or {}).get("city") or "") for r in old)
s = B(open(f"{ROOT}/rules/raw/pk_dir/bhc.html", errors="ignore"), "html.parser"); rows = []; dup = []
for a in s.select('a[href^="https://bhc.gov.pk/district-judiciary/"]'):
    t = a.get("title", "");
    if not t.startswith("Sessions Division "): continue
    d = t.replace("Sessions Division ", "").strip(); seat = re.split(r" at |\(", d)[-1].strip(" )")
    cid = "pk-ba-dsc-" + re.sub(r"[^a-z0-9]+", "-", d.lower()).strip("-")
    if cid in {r["court_id"] for r in rows}: continue
    if re.search(rf"(district|session)[^|]*{re.escape(norm(seat))}", oldn): dup.append(d); continue
    rows.append({"court_id": cid, "record_type": "courthouse", "name": f"District & Sessions Court, {d}", "name_local": None, "level": "trial", "court_system": "provincial",
      "country_code": "PK", "subdivision": "PK-BA", "jurisdiction": f"Sessions Division {d}", "parent_court_id": None,
      "address": {"street": None, "city": seat, "postcode": None, "region": "Balochistan", "country": "PK"}, "geo": {"lat": None, "lon": None}, "phone": None,
      "website": a["href"], "wikidata": None, "place_ids": [], "source_url": "https://bhc.gov.pk/district-judiciary", "source_kind": "official",
      "site_policy": "robots_allowed;official:Balochistan High Court", "retrieved_at": now, "license": "Pakistan government public information"})
with open(OUT, "a") as f:
    for r in rows: f.write(json.dumps(r, ensure_ascii=False) + "\n")
print("added", len(rows), "dup", dup)
