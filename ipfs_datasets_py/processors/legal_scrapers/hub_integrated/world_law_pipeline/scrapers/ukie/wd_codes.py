#!/usr/bin/env python3
"""Propose official codes for GB/IE places missing from codes/place_codes (for the Normalizer; read-only here).
GB: ONS GSS code (Wikidata P836). One SPARQL POST to query.wikidata.org. Output: _state/proposed_place_codes.csv"""
import csv, sys, time
from pathlib import Path
import requests
sys.path.insert(0, str(Path(__file__).resolve().parent))
from common.util import STATE_DIR, UA, utcnow  # noqa: E402
from places import Places  # noqa: E402

P = Places()
rows = [r for r in P.rows if r["phase"] in (1, 3) and r.get("qid")]
qids = " ".join("wd:" + r["qid"] for r in rows)
q = f"""SELECT ?item ?gss ?end WHERE {{ VALUES ?item {{ {qids} }}
  ?item p:P836 ?st . ?st ps:P836 ?gss . OPTIONAL {{ ?st pq:P582 ?end }} }}"""
r = requests.post("https://query.wikidata.org/sparql", data={"query": q}, timeout=120,
                  headers={"User-Agent": UA, "Accept": "application/sparql-results+json"})
r.raise_for_status()
got = {}
for b in r.json()["results"]["bindings"]:
    qid = b["item"]["value"].rsplit("/", 1)[1]
    got.setdefault(qid, []).append((b["gss"]["value"], "end" in b))
out = STATE_DIR / "proposed_place_codes.csv"
with out.open("w", newline="", encoding="utf-8") as f:
    w = csv.writer(f)
    w.writerow(["place_id", "country_code", "code_system", "code", "wikidata_property", "source", "retrieved_at",
                "is_current", "place_name", "admin_level", "phase"])
    n = 0
    for r0 in rows:
        for code, ended in got.get(r0["qid"], []):
            w.writerow([r0["place_id"], r0["country_code"], "gb_ons_gss", code, "P836", "wikidata(query.wikidata.org)",
                        utcnow(), not ended, r0["place_name"], r0["admin_level"], r0["phase"]])
            n += 1
nocode = [r0 for r0 in rows if r0["qid"] not in got]
with (STATE_DIR / "places_without_official_code.csv").open("w", newline="", encoding="utf-8") as f:
    w = csv.writer(f)
    w.writerow(["place_id", "country_code", "phase", "admin_level", "place_name", "site"])
    for r0 in nocode:
        w.writerow([r0["place_id"], r0["country_code"], r0["phase"], r0["admin_level"], r0["place_name"], r0["site"]])
print(f"places {len(rows)}; with GSS {len(got)}; codes {n}; without {len(nocode)} -> {out}")
