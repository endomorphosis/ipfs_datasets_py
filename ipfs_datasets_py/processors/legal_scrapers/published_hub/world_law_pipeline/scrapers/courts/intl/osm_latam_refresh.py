"""Fresh Overpass pass (ODbL): amenity=courthouse plus court-named offices/buildings (Juzgado/Tribunal/Corte/Palacio de Justicia/Tribunal de Paix/Tribunal Popular).
Appends only OSM objects not already present (by osm id or name+~150 m) to data/<cc>/<cc>_courthouses.jsonl. One request per country, 20 s apart."""
import json, sys, os, time, math, re, urllib.request, urllib.parse, datetime
sys.path.insert(0, "/workspace/world_courts/scrapers/courts/intl")
from row_common import *
NM = r"^(Juzgado|Tribunal|Corte (Suprema|de Apelaci|Superior|Nacional|Provincial)|Palacio de Justicia|Palais de Justice|Tribunal de Paix|Cour d|Sala )"
def lvl(n):
    n = (n or "").lower()
    for k, v in [("suprema", "supreme"), ("cassation", "supreme"), ("constitucional", "constitutional"), ("apelaci", "appellate"), ("appel", "appellate"), ("superior", "appellate"), ("provincial", "appellate"),
                 ("familia", "family"), ("niñez", "juvenile"), ("menores", "juvenile"), ("adolescen", "juvenile"), ("laboral", "labor"), ("trabajo", "labor"), ("administrativ", "administrative"),
                 ("paz", "trial_limited"), ("paix", "trial_limited"), ("municipal", "trial_limited"), ("juzgado", "trial_general"), ("tribunal", "trial_general"), ("palacio de justicia", "trial_general")]:
        if k in n: return v
    return "other"
def dist(a, b, c, d): return 6371000 * math.hypot(math.radians(c - a), math.radians(d - b) * math.cos(math.radians(a)))
tot = {}
for cc in sys.argv[1:]:
    lo = cc.lower(); OUT = f"{ROOT}/data/{lo}/{lo}_courthouses.jsonl"; R = [json.loads(l) for l in open(OUT)]
    ids = {r["court_id"] for r in R} | {m for r in R for m in r.get("merged_ids") or []}; pts = [(norm(r["name"]), r["geo"]["lat"], r["geo"]["lon"]) for r in R if (r.get("geo") or {}).get("lat")]
    q = f'[out:json][timeout:300];area["ISO3166-1"="{cc}"]->.a;(nwr["amenity"="courthouse"](area.a);nwr["office"~"government|court"]["name"~"{NM}"](area.a);nwr["building"]["name"~"{NM}"](area.a););out center tags;'
    for a in range(3):
        try:
            req = urllib.request.Request("https://overpass-api.de/api/interpreter", data=urllib.parse.urlencode({"data": q}).encode(), headers={"User-Agent": "WorldCourtsResearch/0.3 (bbarber)"})
            d = json.load(urllib.request.urlopen(req, timeout=330)); break
        except Exception as e: print(cc, "retry", str(e)[:80], flush=True); time.sleep(60)
    else: print(cc, "FAILED"); continue
    now = datetime.datetime.now(datetime.UTC).isoformat(); new = []
    for e in d["elements"]:
        t = e.get("tags", {}); oid = f"osm:{e['type']}/{e['id']}"; lat = e.get("lat") or e.get("center", {}).get("lat"); lon = e.get("lon") or e.get("center", {}).get("lon")
        name = t.get("name") or t.get("official_name")
        if oid in ids or lat is None: continue
        if name and any(n == norm(name) and dist(lat, lon, a2, b2) < 150 for n, a2, b2 in pts): continue
        if name and re.search(r"(?i)abogad|notar|bufete|polic|fiscal[ií]a|registro|lawyer", name): continue
        city = t.get("addr:city") or t.get("addr:town") or t.get("addr:place"); L = lvl(name)
        ids.add(oid); pts.append((norm(name or ""), lat, lon))
        new.append({"court_id": oid, "record_type": "courthouse", "name": name or "Courthouse", "name_local": t.get("name"), "level": L, "court_system": "national", "country_code": cc,
          "subdivision": cc, "jurisdiction": None, "parent_court_id": None, "address": {"street": " ".join(x for x in [t.get("addr:street"), t.get("addr:housenumber")] if x) or None, "city": city,
          "postcode": t.get("addr:postcode"), "region": t.get("addr:state") or t.get("addr:province"), "country": None}, "geo": {"lat": lat, "lon": lon}, "phone": t.get("phone"),
          "website": t.get("website"), "wikidata": t.get("wikidata"), "place_ids": rmatch([city], cc) if city else [], "source_url": f"https://www.openstreetmap.org/{e['type']}/{e['id']}",
          "source_kind": "osm", "site_policy": "open_license(ODbL)", "retrieved_at": now, "license": "ODbL-1.0 (© OpenStreetMap contributors)", "geo_source": "osm",
          "sources": [{"source_url": f"https://www.openstreetmap.org/{e['type']}/{e['id']}", "site_policy": "open_license(ODbL)", "source_kind": "osm"}],
          "record_note": "OSM refresh 2026-10-28 (" + ("amenity=courthouse" if t.get("amenity") == "courthouse" else "court-named office/building") + ")", "needs_review": L == "other" or not name or t.get("amenity") != "courthouse"})
    with open(OUT, "a") as f:
        for r in new: f.write(json.dumps(r, ensure_ascii=False) + "\n")
    tot[cc] = (len(d["elements"]), len(new)); print(cc, "osm", len(d["elements"]), "added", len(new), flush=True); time.sleep(20)
print(tot)
