"""OSM amenity=courthouse (ODbL) + Wikidata courthouses (CC0) for rest-of-world countries. Usage: row_osm_wd.py osm|wd CC..  -> data/row/osm_<CC>.jsonl, wd_<CC>.jsonl"""
import sys, json, time, urllib.request, urllib.parse, os, re
R = "/workspace/world_courts/data/row"; os.makedirs(R, exist_ok=True)
QID = dict(NZ="Q664", IN="Q668", JP="Q17", BR="Q155", MX="Q96", ZA="Q258", KR="Q884", TW="Q865", PH="Q928", AR="Q414", CO="Q739", CL="Q298", NG="Q1033", KE="Q114", CN="Q148", ID="Q252", EG="Q79", TR="Q43", RU="Q159", PK="Q843", BD="Q902", VN="Q881", TH="Q869", MY="Q833", SG="Q334", IL="Q801", SA="Q851", AE="Q878", PE="Q419", VE="Q717", EC="Q736", GH="Q117", ET="Q115", MA="Q1028", DZ="Q262", IR="Q794", IQ="Q796", UA="Q212", KZ="Q232", UZ="Q265", TZ="Q924", UG="Q1036", SN="Q1041", CI="Q1008", CM="Q1009", JO="Q810", LB="Q822", TN="Q948", LK="Q854", NP="Q837", MM="Q836", KH="Q424", BO="Q750", PY="Q733", UY="Q77", CR="Q800", PA="Q804", GT="Q774", DO="Q786", ZM="Q953", ZW="Q954")
UA = {"User-Agent": "world_courts/0.1 (research; contact via endomorphosis HF)"}
def post(url, data, to=300):
    return urllib.request.urlopen(urllib.request.Request(url, data=urllib.parse.urlencode(data).encode(), headers=UA), timeout=to).read()
def osm(cc):
    out = f"{R}/osm_{cc}.jsonl"
    if os.path.exists(out): return
    q = f'[out:json][timeout:280];area["ISO3166-1"="{cc}"][admin_level=2]->.a;nwr["amenity"="courthouse"](area.a);out center tags;'
    for a in range(4):
        try: d = json.loads(post(os.environ.get("OVERPASS", "https://overpass-api.de/api/interpreter"), {"data": q})); break
        except Exception as e: print("osm retry", cc, e, file=sys.stderr); time.sleep(40)
    else: return
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    with open(out + ".tmp", "w") as f:
        for e in d["elements"]:
            t = e.get("tags", {}); lat = e.get("lat") or e.get("center", {}).get("lat"); lon = e.get("lon") or e.get("center", {}).get("lon")
            if lat is None: continue
            f.write(json.dumps({"osm_id": f"{e['type']}/{e['id']}", "name": t.get("name:en") or t.get("name") or t.get("official_name"), "name_local": t.get("name"), "country_code": cc,
              "street": " ".join(x for x in [t.get("addr:housenumber"), t.get("addr:street")] if x) or None, "city": t.get("addr:city") or t.get("addr:town") or t.get("addr:suburb") or t.get("addr:place"), "postcode": t.get("addr:postcode"),
              "region": t.get("addr:state") or t.get("addr:province"), "lat": lat, "lon": lon, "phone": t.get("phone") or t.get("contact:phone"), "website": t.get("website") or t.get("contact:website"),
              "wikidata": t.get("wikidata"), "operator": t.get("operator"), "court_type": t.get("court:type") or t.get("courthouse"), "retrieved_at": now}, ensure_ascii=False) + "\n")
    os.replace(out + ".tmp", out); print("osm", cc, len(d["elements"]), flush=True); time.sleep(10)
def sparql(q):
    for a in range(5):
        try: return json.loads(urllib.request.urlopen(urllib.request.Request("https://query.wikidata.org/sparql?format=json&query=" + urllib.parse.quote(q), headers={**UA, "Accept": "application/sparql-results+json"}), timeout=200).read())
        except Exception as e: print("sparql retry", e, file=sys.stderr); time.sleep(60)
WDQ = """SELECT ?item ?itemLabel ?coord ?street ?postcode ?admin ?adminLabel ?web ?phone ?gn ?inst ?instLabel WHERE {
 ?item wdt:P31/wdt:P279* wd:Q1137809 . ?item wdt:P17 wd:%s .
 OPTIONAL{?item wdt:P625 ?coord} OPTIONAL{?item wdt:P6375 ?street} OPTIONAL{?item wdt:P281 ?postcode} OPTIONAL{?item wdt:P131 ?admin}
 OPTIONAL{?item wdt:P856 ?web} OPTIONAL{?item wdt:P1329 ?phone} OPTIONAL{?item wdt:P1566 ?gn} OPTIONAL{?item wdt:P466 ?inst}
 SERVICE wikibase:label { bd:serviceParam wikibase:language "en,ja,pt,es,hi,mul". } }"""
WDQ2 = WDQ.replace("?item wdt:P31/wdt:P279* wd:Q1137809 .", "VALUES ?cls { wd:Q1137809 wd:Q41487 } ?item wdt:P31 ?cls .").replace("SERVICE wikibase:label", "FILTER EXISTS { ?item wdt:P625 ?cc0 } SERVICE wikibase:label")
def wd(cc, direct=False):
    out = f"{R}/wd_{cc}.jsonl"
    if os.path.exists(out) and os.path.getsize(out) > 0: return
    r = sparql((WDQ2 if direct else WDQ) % QID[cc])
    if not r: return
    rows = {}
    for b in r["results"]["bindings"]:
        v = {k: x["value"] for k, x in b.items()}; qid = v["item"].rsplit("/", 1)[-1]
        if v["itemLabel"] == qid: continue
        m = re.match(r"Point\(([-\d.]+) ([-\d.]+)\)", v.get("coord", ""))
        x = rows.setdefault(qid, {"wikidata": qid, "name": v["itemLabel"], "country_code": cc, "lat": float(m.group(2)) if m else None, "lon": float(m.group(1)) if m else None,
              "street": v.get("street"), "postcode": v.get("postcode"), "city": v.get("adminLabel"), "admin_qid": v["admin"].rsplit("/", 1)[-1] if v.get("admin") else None, "website": v.get("web"), "phone": v.get("phone"), "geonames": []})
        if v.get("gn") and v["gn"] not in x["geonames"]: x["geonames"].append(v["gn"])
    with open(out, "w") as f:
        for x in rows.values(): f.write(json.dumps(x, ensure_ascii=False) + "\n")
    print("wd", cc, len(rows), flush=True); time.sleep(5 if direct else 65)
if __name__ == "__main__":
    mode = sys.argv[1]
    for cc in sys.argv[2:]: {"osm": osm, "wd": wd, "wd2": lambda c: wd(c, True)}[mode](cc)
