"""Wikidata courthouses (CC0) for GB/CA/AU -> data/<cc>/<cc>_courthouses_wd.jsonl"""
import sys, json, urllib.parse
sys.path.insert(0, "/workspace/world_courts/scrapers/courts/intl")
from courts_common import *
CC = {"GB": "Q145", "CA": "Q16", "AU": "Q408"}
Q = """SELECT ?item ?itemLabel ?coord ?street ?postcode ?adminLabel ?typeLabel ?web ?phone WHERE {
 ?item wdt:P31/wdt:P279* wd:Q1137809 . ?item wdt:P17 wd:%s . ?item wdt:P625 ?coord .
 OPTIONAL{?item wdt:P6375 ?street} OPTIONAL{?item wdt:P281 ?postcode} OPTIONAL{?item wdt:P131 ?admin}
 OPTIONAL{?item wdt:P856 ?web} OPTIONAL{?item wdt:P1329 ?phone} OPTIONAL{?item wdt:P31 ?type}
 SERVICE wikibase:label { bd:serviceParam wikibase:language "en,fr". } }"""
for cc, q in CC.items():
    url = "https://query.wikidata.org/sparql?format=json&query=" + urllib.parse.quote(Q % q)
    try: r = json.loads(get(url, delay=3, timeout=180))
    except Exception as e: print(cc, "ERR", e); continue
    rows = {}
    for b in r["results"]["bindings"]:
        v = {k: x["value"] for k, x in b.items()}
        qid = v["item"].rsplit("/", 1)[-1]
        if v["itemLabel"] == qid: continue
        m = re.match(r"Point\(([-\d.]+) ([-\d.]+)\)", v["coord"])
        if not m: continue
        rows[qid] = rec(court_id=f"wd:{qid}", name=v["itemLabel"], country_code=cc, wikidata=qid,
                        address={"street": v.get("street"), "city": v.get("adminLabel"), "postcode": v.get("postcode"), "region": None, "country": cc},
                        geo={"lat": float(m.group(2)), "lon": float(m.group(1))}, phone=v.get("phone"), website=v.get("web"),
                        source_url=f"https://www.wikidata.org/wiki/{qid}", source_kind="wikidata", site_policy="open_license:CC0", license="CC0-1.0")
    wjl(f"{ROOT}/data/{cc.lower()}/{cc.lower()}_courthouses_wd.jsonl", rows.values())
    print(cc, len(rows), flush=True)
