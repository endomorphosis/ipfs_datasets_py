"""Second-pass place matching for GB/CA/AU courthouses lacking a name match: Nominatim reverse geocode (<=1 req/s, cached) -> locality names -> global_municipalities wd: ids."""
import sys, json, os, urllib.parse
sys.path.insert(0, "/workspace/world_courts/scrapers/courts/intl")
from courts_common import *
CACHE = f"{ROOT}/data/ref/nominatim_reverse_cache.json"
try: cache = json.load(open(CACHE))
except Exception: cache = {}
def rev(lat, lon):
    k = f"{lat:.4f},{lon:.4f}"
    if k in cache: return cache[k]
    url = "https://nominatim.openstreetmap.org/reverse?" + urllib.parse.urlencode({"lat": lat, "lon": lon, "format": "jsonv2", "zoom": 12, "addressdetails": 1})
    try: v = json.loads(get(url, delay=1.2)).get("address", {})
    except Exception as e: print("err", e); return None
    cache[k] = v
    if len(cache) % 20 == 0: json.dump(cache, open(CACHE + ".tmp", "w")); os.replace(CACHE + ".tmp", CACHE)
    return v
for cc in sys.argv[1:] or ["gb", "ca", "au"]:
    p = f"{ROOT}/data/{cc}/{cc}_courthouses.jsonl"; rows = rjl(p); n = 0; hit = 0
    for r in rows:
        if r["record_type"] != "courthouse" or r.get("place_match_method") or r["geo"]["lat"] is None: continue
        a = rev(r["geo"]["lat"], r["geo"]["lon"]); n += 1
        if not a: continue
        names = [a.get(k) for k in ("city", "town", "village", "suburb", "municipality", "city_district", "county", "state_district") if a.get(k)]
        if not r["address"].get("city") and names: r["address"]["city"] = names[0]
        pl, meth = match_place(names[0] if names else None, cc.upper(), names[1:])
        if pl:
            keep = [x for x in r["place_ids"] if x not in pl]
            r["place_ids"] = pl[:2] + keep; r["place_match_method"] = "reverse_geocode_name"; hit += 1
    wjl(p, rows); json.dump(cache, open(CACHE, "w"))
    print(cc, "reverse-tried", n, "matched", hit, flush=True)
