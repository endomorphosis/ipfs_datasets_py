"""OSM courthouses for CN, queried per province (a single country-wide Overpass query returns 502/timeouts). Writes data/row/osm_CN.jsonl via row_osm_wd.osm()."""
import sys, json, time
sys.path.insert(0, "/workspace/world_courts/scrapers/courts/intl")
import row_osm_wd as w
PROV = "AH BJ CQ FJ GS GD GX GZ HI HE HL HA HB HN JS JX JL LN NM NX QH SD SN SH SX SC TJ XJ XZ YN ZJ HK MO".split()
orig = w.post
def post(url, data, to=300):
    if '"ISO3166-1"="CN"' not in data["data"]: return orig(url, data, to)
    els = []; seen = set()
    for p in PROV:
        q = f'[out:json][timeout:120];area["ISO3166-2"="CN-{p}"]->.a;nwr["amenity"="courthouse"](area.a);out center tags;'
        for a in range(4):
            try: d = json.loads(orig(url, {"data": q}, 200)); break
            except Exception as e: print("cn retry", p, e, file=sys.stderr, flush=True); time.sleep(20)
        else: print("cn prov failed", p, flush=True); continue
        for e in d["elements"]:
            k = (e["type"], e["id"])
            if k not in seen: seen.add(k); els.append(e)
        print("cn", p, len(d["elements"]), flush=True); time.sleep(5)
    return json.dumps({"elements": els}).encode()
w.post = post
w.osm("CN")
