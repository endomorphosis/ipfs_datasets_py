"""Wikidata court items (P31/P279* court Q41487 or courthouse Q1137809) for countries given on argv; adds items not present by QID or normalized name. CC0."""
import json, sys, re, datetime, time, urllib.request, urllib.parse
sys.path.insert(0, "/workspace/world_courts/scrapers/courts/intl")
from row_common import *
CQ = {"PE":"Q419","VN":"Q881","PH":"Q928","PK":"Q843","BD":"Q902","JM":"Q766","BS":"Q778","GY":"Q734","DO":"Q786","HT":"Q790","CU":"Q241","EC":"Q736","BO":"Q750",
      "VE":"Q717","UY":"Q77","PY":"Q733","GT":"Q774","HN":"Q783","SV":"Q792","NI":"Q811","CR":"Q800","PA":"Q804","BZ":"Q242","TH":"Q869","NP":"Q837"}
Q = """SELECT ?i ?l ?coord ?c ?cl WHERE { { ?i wdt:P31/wdt:P279* wd:Q41487 } UNION { ?i wdt:P31/wdt:P279* wd:Q1137809 }
 ?i wdt:P17 wd:%s . FILTER NOT EXISTS { ?i wdt:P576 [] }
 OPTIONAL{?i wdt:P625 ?coord} OPTIONAL{?i wdt:P131 ?c} OPTIONAL{?i wdt:P31 ?t . ?t rdfs:label ?cl FILTER(lang(?cl)="en")}
 ?i rdfs:label ?l FILTER(lang(?l) in ("%s","en")) }"""
LANG = {"PE":"es","VN":"vi","PH":"en","PK":"en","BD":"en","HT":"fr","TH":"th","NP":"en","BR":"pt"}
def lvl(n):
    n = n.lower()
    for k, v in [("supreme","supreme"),("suprema","supreme"),("constitu","constitutional"),("tối cao","supreme"),("high court","appellate"),("appeal","appellate"),("apelaci","appellate"),
                 ("superior","appellate"),("administrat","administrative"),("family","family"),("familia","family"),("district","trial_general"),("magistrat","trial_limited"),
                 ("paz","trial_limited"),("juzgado","trial_general"),("regional trial","trial_general"),("municipal","trial_limited"),("tòa án nhân dân","trial_general"),("ศาล","trial_general")]:
        if k in n: return v
    return "other"
tot = {}
for cc in sys.argv[1:]:
    lo = cc.lower(); OUT = f"{ROOT}/data/{lo}/{lo}_courthouses.jsonl"
    try: rows = [json.loads(l) for l in open(OUT)]
    except FileNotFoundError: rows = []
    txt = json.dumps(rows); names = {norm(r["name"]) for r in rows}
    url = "https://query.wikidata.org/sparql?format=json&query=" + urllib.parse.quote(Q % (CQ[cc], LANG.get(cc, "es")))
    for a in range(3):
        try: d = json.load(urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "WorldCourtsResearch/0.3 (bbarber)"}), timeout=120)); break
        except Exception as e: print(cc, "retry", e); time.sleep(20)
    else: continue
    items = {}
    for b in d["results"]["bindings"]:
        q = b["i"]["value"].rsplit("/", 1)[1]; it = items.setdefault(q, {})
        if b["l"]["xml:lang"] != "en" or "l" not in it: it["l"] = b["l"]["value"]; it["lang"] = b["l"]["xml:lang"]
        if "coord" in b: it["c"] = b["coord"]["value"]
        if "c" in b: it["p"] = b["c"]["value"].rsplit("/", 1)[1]
    now = datetime.datetime.now(datetime.UTC).isoformat(); new = []
    for q, it in items.items():
        if f'"{q}"' in txt or f"wd:{q}" in txt or f"-{q.lower()}" in txt or norm(it["l"]) in names or re.fullmatch(r"Q\d+", it["l"]): continue
        names.add(norm(it["l"])); lat = lon = None
        m = re.match(r"Point\(([-\d.eE]+) ([-\d.eE]+)\)", it.get("c", ""))
        if m: lon, lat = float(m[1]), float(m[2])
        L = lvl(it["l"]); pl = [p for p in [qplace(it.get("p"), cc)] if p]
        new.append({"court_id": f"{lo}-wd-{q.lower()}", "record_type": "courthouse" if (lat or pl) else "court_body", "name": it["l"], "name_local": it["l"] if it["lang"] != "en" else None,
          "level": L, "court_system": "national", "country_code": cc, "subdivision": cc, "jurisdiction": None, "parent_court_id": None,
          "address": {"street": None, "city": None, "postcode": None, "region": None, "country": None}, "geo": {"lat": lat, "lon": lon}, "phone": None, "website": None,
          "wikidata": q, "place_ids": pl, "source_url": f"https://www.wikidata.org/wiki/{q}", "source_kind": "wikidata", "site_policy": "open_license(CC0)", "retrieved_at": now,
          "license": "CC0-1.0", "geo_source": "wikidata" if lat else None, "sources": [{"source_url": f"https://www.wikidata.org/wiki/{q}", "site_policy": "open_license(CC0)", "source_kind": "wikidata"}],
          "record_note": "Wikidata court item", "needs_review": L == "other" or not (lat or pl)})
    import os; os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "a") as f:
        for r in new: f.write(json.dumps(r, ensure_ascii=False) + "\n")
    tot[cc] = (len(items), len(new)); print(cc, "wd", len(items), "added", len(new), flush=True); time.sleep(3)
print(tot)
