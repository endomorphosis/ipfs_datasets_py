"""For courts whose GeoNames municipality is a town/village that is not itself a place in global_municipalities: walk Wikidata P131 (located in) ancestors of the GeoNames-linked item (P1566),
so the court gets the enclosing municipality's wd: id. Input data/eu/need_p131_all.json -> data/eu/p131_<CC>.json {qid:[ancestor qids]}"""
import sys, json, os, time, glob
sys.path.insert(0, "/workspace/world_courts/scrapers/courts/intl")
from eu_osm_wd import sparql, R
need = json.load(open(f"{R}/need_p131_all.json"))
for cc, qs in need.items():
    out = f"{R}/p131_{cc}.json"
    done = json.load(open(out)) if os.path.exists(out) else {}
    qs = [q for q in qs if q not in done]
    for i in range(0, len(qs), 80):
        b = qs[i:i + 80]
        r = sparql("SELECT ?q ?a WHERE { VALUES ?q { %s } ?q wdt:P131+ ?a . }" % " ".join(f"wd:{q}" for q in b))
        if r is None: print("fail", cc, i); continue
        for x in r["results"]["bindings"]:
            done.setdefault(x["q"]["value"].rsplit("/", 1)[-1], []).append(x["a"]["value"].rsplit("/", 1)[-1])
        for q in b: done.setdefault(q, [])
        json.dump(done, open(out + ".tmp", "w")); os.replace(out + ".tmp", out); print(cc, i + len(b), "/", len(qs), flush=True); time.sleep(8)
