"""Batch Overpass: one request for a group of countries, split by `out count`. usage: osm_batch.py CC CC ... -> data/row/osm_<CC>.jsonl"""
import sys, os, json, time
sys.path.insert(0, "/workspace/world_courts/scrapers/courts/intl")
import row_osm_wd as w
def run(ccs):
    ccs = [c for c in ccs if not os.path.exists(f"{w.R}/osm_{c}.jsonl")]
    if not ccs: return
    q = "[out:json][timeout:600];" + "".join(f'area["ISO3166-1"="{c}"]->.a{i};nwr["amenity"="courthouse"](area.a{i})->.r{i};.r{i} out center tags;.r{i} out count;' for i, c in enumerate(ccs))
    for a in range(5):
        try: d = json.loads(w.post(os.environ.get("OVERPASS", "https://overpass-api.de/api/interpreter"), {"data": q}, to=650)); break
        except Exception as e: print("osmb retry", ccs, str(e)[:80], file=sys.stderr, flush=True); time.sleep(45)
    else:
        print("osmb FAILED", ccs, flush=True); return
    groups = [[]]
    for e in d["elements"]:
        if e["type"] == "count": groups.append([])
        else: groups[-1].append(e)
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    for cc, els in zip(ccs, groups):
        with open(f"{w.R}/osm_{cc}.jsonl.tmp", "w") as f:
            for e in els:
                t = e.get("tags", {}); lat = e.get("lat") or e.get("center", {}).get("lat"); lon = e.get("lon") or e.get("center", {}).get("lon")
                if lat is None: continue
                f.write(json.dumps({"osm_id": f"{e['type']}/{e['id']}", "name": t.get("name:en") or t.get("name") or t.get("official_name"), "name_local": t.get("name"), "country_code": cc,
                  "street": " ".join(x for x in [t.get("addr:housenumber"), t.get("addr:street")] if x) or None, "city": t.get("addr:city") or t.get("addr:town") or t.get("addr:suburb") or t.get("addr:place"), "postcode": t.get("addr:postcode"),
                  "region": t.get("addr:state") or t.get("addr:province"), "lat": lat, "lon": lon, "phone": t.get("phone") or t.get("contact:phone"), "website": t.get("website") or t.get("contact:website"),
                  "wikidata": t.get("wikidata"), "operator": t.get("operator"), "court_type": t.get("court:type") or t.get("courthouse"), "retrieved_at": now}, ensure_ascii=False) + "\n")
        os.replace(f"{w.R}/osm_{cc}.jsonl.tmp", f"{w.R}/osm_{cc}.jsonl"); print("osm", cc, len(els), flush=True)
if __name__ == "__main__": run(sys.argv[1:])
