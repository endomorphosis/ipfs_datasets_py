"""Batch Wikidata courts for a list of ISO codes (direct instance-of court/courthouse, with coordinates). usage: wd_batch.py CC.. -> data/row/wd_<CC>.jsonl"""
import sys, os, json, re, time
sys.path.insert(0, "/workspace/world_courts/scrapers/courts/intl")
import row_osm_wd as w
Q = """SELECT ?item ?itemLabel ?coord ?street ?postcode ?admin ?web ?phone ?gn ?cc WHERE {
 VALUES ?cc { %s } ?country wdt:P297 ?cc . VALUES ?cls { wd:Q1137809 wd:Q41487 } ?item wdt:P31 ?cls . ?item wdt:P17 ?country . ?item wdt:P625 ?coord .
 OPTIONAL{?item wdt:P6375 ?street} OPTIONAL{?item wdt:P281 ?postcode} OPTIONAL{?item wdt:P131 ?admin} OPTIONAL{?item wdt:P856 ?web} OPTIONAL{?item wdt:P1329 ?phone} OPTIONAL{?item wdt:P1566 ?gn}
 SERVICE wikibase:label { bd:serviceParam wikibase:language "en,fr,es,pt,ru,ar,mul". } }"""
def run(ccs):
    ccs = [c for c in ccs if not os.path.exists(f"{w.R}/wd_{c}.jsonl")]
    if not ccs: return
    r = w.sparql(Q % " ".join('"%s"' % c for c in ccs))
    if not r: print("wdb FAILED", ccs, flush=True); return
    rows = {c: {} for c in ccs}
    for b in r["results"]["bindings"]:
        v = {k: x["value"] for k, x in b.items()}; qid = v["item"].rsplit("/", 1)[-1]; cc = v["cc"]
        if v["itemLabel"] == qid: continue
        m = re.match(r"Point\(([-\d.]+) ([-\d.]+)\)", v.get("coord", ""))
        x = rows[cc].setdefault(qid, {"wikidata": qid, "name": v["itemLabel"], "country_code": cc, "lat": float(m.group(2)) if m else None, "lon": float(m.group(1)) if m else None,
              "street": v.get("street"), "postcode": v.get("postcode"), "city": None, "admin_qid": v["admin"].rsplit("/", 1)[-1] if v.get("admin") else None, "website": v.get("web"), "phone": v.get("phone"), "geonames": []})
        if v.get("gn") and v["gn"] not in x["geonames"]: x["geonames"].append(v["gn"])
    for c in ccs:
        with open(f"{w.R}/wd_{c}.jsonl", "w") as f:
            for x in rows[c].values(): f.write(json.dumps(x, ensure_ascii=False) + "\n")
        print("wd", c, len(rows[c]), flush=True)
if __name__ == "__main__":
    ccs = sys.argv[1:]
    for i in range(0, len(ccs), 8): run(ccs[i:i + 8]); time.sleep(30)
