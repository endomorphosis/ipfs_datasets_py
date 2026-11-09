"""OSM amenity=courthouse (ODbL) + Wikidata courthouses (CC0) + Wikidata<->GeoNames id map (P1566) for the 27 EU Member States.
Usage: eu_osm_wd.py osm|wd|gn [CC...]  -> data/eu/osm_<CC>.jsonl, wd_<CC>.jsonl, gn_<CC>.tsv"""
import sys, json, time, datetime, urllib.request, urllib.parse, os, re
R = "/workspace/world_courts/data/eu"; os.makedirs(R, exist_ok=True)
QID = dict(AT="Q40", BE="Q31", BG="Q219", HR="Q224", CY="Q229", CZ="Q213", DK="Q35", EE="Q191", FI="Q33", FR="Q142", DE="Q183", GR="Q41", HU="Q28", IE="Q27", IT="Q38", LV="Q211", LT="Q37", LU="Q32", MT="Q233", NL="Q55", PL="Q36", PT="Q45", RO="Q218", SK="Q214", SI="Q215", ES="Q29", SE="Q34")
UA = {"User-Agent": "world_courts/0.1 (research; contact via endomorphosis HF)"}
def post(url, data, to=300):
    return urllib.request.urlopen(urllib.request.Request(url, data=urllib.parse.urlencode(data).encode(), headers=UA), timeout=to).read()
def osm(cc):
    out = f"{R}/osm_{cc}.jsonl"
    if os.path.exists(out): return
    q = f'[out:json][timeout:280];area["ISO3166-1"="{cc}"][admin_level=2]->.a;nwr["amenity"="courthouse"](area.a);out center tags;'
    for a in range(5):
        try: d = json.loads(post("https://overpass-api.de/api/interpreter", {"data": q}, 330)); break
        except Exception as e: print(cc, "retry", e, file=sys.stderr); time.sleep(45)
    else: return
    now = datetime.datetime.utcnow().isoformat() + "Z"; rows = []
    for e in d["elements"]:
        t = e.get("tags", {}); lat = e.get("lat") or e.get("center", {}).get("lat"); lon = e.get("lon") or e.get("center", {}).get("lon")
        if lat is None: continue
        rows.append({"osm_id": f"{e['type']}/{e['id']}", "name": t.get("name") or t.get("official_name"), "name_en": t.get("name:en"), "country_code": cc,
          "street": " ".join(x for x in [t.get("addr:street"), t.get("addr:housenumber")] if x) or None, "city": t.get("addr:city") or t.get("addr:town") or t.get("addr:village"), "postcode": t.get("addr:postcode"),
          "lat": lat, "lon": lon, "phone": t.get("phone") or t.get("contact:phone"), "website": t.get("website") or t.get("contact:website"), "wikidata": t.get("wikidata"), "operator": t.get("operator"), "court_type": t.get("court:type") or t.get("courthouse"), "retrieved_at": now})
    with open(out + ".tmp", "w") as f:
        for r in rows: f.write(json.dumps(r, ensure_ascii=False) + "\n")
    os.replace(out + ".tmp", out); print("osm", cc, len(rows), flush=True); time.sleep(10)
def sparql(q):
    for a in range(4):
        try: return json.loads(urllib.request.urlopen(urllib.request.Request("https://query.wikidata.org/sparql?format=json&query=" + urllib.parse.quote(q), headers={**UA, "Accept": "application/sparql-results+json"}), timeout=200).read())
        except Exception as e: print("sparql retry", e, file=sys.stderr); time.sleep(30)
WDQ = """SELECT ?item ?itemLabel ?itemLabel_en ?coord ?street ?postcode ?adminLabel ?web ?phone ?gn WHERE {
 ?item wdt:P31/wdt:P279* wd:Q1137809 . ?item wdt:P17 wd:%s .
 OPTIONAL{?item wdt:P625 ?coord} OPTIONAL{?item wdt:P6375 ?street} OPTIONAL{?item wdt:P281 ?postcode} OPTIONAL{?item wdt:P131 ?admin}
 OPTIONAL{?item wdt:P856 ?web} OPTIONAL{?item wdt:P1329 ?phone}
 SERVICE wikibase:label { bd:serviceParam wikibase:language "en,de,fr,es,it,nl,pl,mul". } }"""
def wd(cc):
    out = f"{R}/wd_{cc}.jsonl"
    if os.path.exists(out): return
    r = sparql(WDQ % QID[cc])
    if not r: return
    rows = {}
    for b in r["results"]["bindings"]:
        v = {k: x["value"] for k, x in b.items()}; qid = v["item"].rsplit("/", 1)[-1]
        if v["itemLabel"] == qid: continue
        m = re.match(r"Point\(([-\d.]+) ([-\d.]+)\)", v.get("coord", ""))
        x = rows.setdefault(qid, {"wikidata": qid, "name": v["itemLabel"], "country_code": cc, "lat": float(m.group(2)) if m else None, "lon": float(m.group(1)) if m else None,
              "street": v.get("street"), "postcode": v.get("postcode"), "city": v.get("adminLabel"), "website": v.get("web"), "phone": v.get("phone"), "geonames": []})
        if v.get("gn") and v["gn"] not in x["geonames"]: x["geonames"].append(v["gn"])
    with open(out, "w") as f:
        for x in rows.values(): f.write(json.dumps(x, ensure_ascii=False) + "\n")
    print("wd", cc, len(rows), flush=True); time.sleep(5)
GNQ = "SELECT ?item ?gn WHERE { ?item wdt:P1566 ?gn . ?item wdt:P17 wd:%s . } ORDER BY ?item LIMIT %d OFFSET %d"
def gn(cc):
    out = f"{R}/gn_{cc}.tsv"
    if os.path.exists(out): return
    rows = []; off = 0
    while True:
        r = sparql(GNQ % (QID[cc], 8000, off))
        if r is None: print("gn fail", cc); return
        b = r["results"]["bindings"]
        rows += [(x["item"]["value"].rsplit("/", 1)[-1], x["gn"]["value"]) for x in b]
        if len(b) < 8000: break
        off += 8000; time.sleep(5)
    open(out, "w").write("\n".join(f"{a}\t{b}" for a, b in rows)); print("gn", cc, len(rows), flush=True); time.sleep(5)
if __name__ == "__main__":
    mode = sys.argv[1]; ccs = sys.argv[2:] or list(QID)
    for cc in ccs: {"osm": osm, "wd": wd, "gn": gn}[mode](cc)
