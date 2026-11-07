"""IN: Wikidata items (instance of court, P17=India) not yet present by QID or normalized name."""
import json, sys, re, datetime
sys.path.insert(0, "/workspace/world_courts/scrapers/courts/intl")
from row_common import *
OUT = f"{ROOT}/data/in/in_courthouses.jsonl"
rows = [json.loads(l) for l in open(OUT)]; txt = open(OUT).read()
def k(n): return re.sub(r"\b(the|of|court|hon ble|honourable)\b", "", norm(n)).strip()
names = {k(r["name"]) for r in rows}
d = json.load(open(f"{ROOT}/scrapers/courts/intl/seeds/wd_in_courts.json"))["results"]["bindings"]
items = {}
for b in d:
    q = b["i"]["value"].rsplit("/", 1)[1]; it = items.setdefault(q, {"l": b["l"]["value"]})
    if "coord" in b: it["c"] = b["coord"]["value"]
    if "c" in b: it["p"] = b["c"]["value"].rsplit("/", 1)[1]
now = datetime.datetime.now(datetime.UTC).isoformat(); new = []
for q, it in items.items():
    if f'"{q}"' in txt or f"wd:{q}" in txt or k(it["l"]) in names: continue
    names.add(k(it["l"])); lat = lon = None
    if "c" in it:
        m = re.match(r"Point\(([-\d.]+) ([-\d.]+)\)", it["c"]); lon, lat = float(m[1]), float(m[2])
    nmn = it["l"].lower(); lvl = "supreme" if "supreme" in nmn else "appellate" if "high court" in nmn else "other"
    pl = [p for p in [qplace(it.get("p"), "IN")] if p]
    new.append({"court_id": f"in-wd-{q.lower()}", "record_type": "courthouse" if lat else "court_body", "name": it["l"], "name_local": None,
      "level": lvl, "court_system": "state" if lvl != "supreme" else "national", "country_code": "IN", "subdivision": "IN", "jurisdiction": None,
      "parent_court_id": None, "address": {"street": None, "city": None, "postcode": None, "region": None, "country": "India"},
      "geo": {"lat": lat, "lon": lon}, "phone": None, "website": None, "wikidata": q, "place_ids": pl,
      "source_url": f"https://www.wikidata.org/wiki/{q}", "source_kind": "wikidata", "site_policy": "open_license(CC0)", "retrieved_at": now,
      "license": "CC0-1.0", "geo_source": "wikidata" if lat else None,
      "sources": [{"source_url": f"https://www.wikidata.org/wiki/{q}", "site_policy": "open_license(CC0)", "source_kind": "wikidata"}],
      "record_note": "Wikidata court item", "needs_review": lvl == "other"})
with open(OUT, "a") as f:
    for r in new: f.write(json.dumps(r, ensure_ascii=False) + "\n")
print("wd items", len(items), "added", len(new)); [print(" ", r["name"]) for r in new]
