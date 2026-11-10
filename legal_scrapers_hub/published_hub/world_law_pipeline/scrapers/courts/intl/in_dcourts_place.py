"""Place IN dcourts rows lacking state: match subdomain name to GeoNames cities500 (largest pop) -> admin1 -> HC; also fill place_ids."""
import json, sys
sys.path.insert(0, "/workspace/world_courts/scrapers/courts/intl")
from row_common import *
HC = {"Andhra Pradesh":"andhra-pradesh","Telangana":"telangana","Assam":"gauhati","Nagaland":"gauhati","Mizoram":"gauhati","Arunachal Pradesh":"gauhati",
"Bihar":"patna","Chhattisgarh":"chhattisgarh","Delhi":"delhi","Goa":"bombay","Maharashtra":"bombay","Gujarat":"gujarat","Himachal Pradesh":"himachal-pradesh",
"Jammu and Kashmir":"jammu-kashmir-ladakh","Ladakh":"jammu-kashmir-ladakh","Jharkhand":"jharkhand","Karnataka":"karnataka","Kerala":"kerala","Madhya Pradesh":"madhya-pradesh",
"Tamil Nadu":"madras","Puducherry":"madras","Manipur":"manipur","Meghalaya":"meghalaya","Odisha":"orissa","Punjab":"punjab-haryana","Haryana":"punjab-haryana","Chandigarh":"punjab-haryana",
"Rajasthan":"rajasthan","Sikkim":"sikkim","Tripura":"tripura","Uttarakhand":"uttarakhand","Uttar Pradesh":"allahabad","West Bengal":"calcutta","Andaman and Nicobar Islands":"calcutta"}

OUT = f"{ROOT}/data/in/in_courthouses.jsonl"
a1 = gn_admin1("IN"); best = {}
for c in gn_cities("IN"):
    for n in {c[2]}:
        k = rcore(n, "IN")
        if k not in best or c[4] > best[k][4]: best[k] = c
rows = [json.loads(l) for l in open(OUT)]; ids = {r["court_id"] for r in rows}; fx = 0
for r in rows:
    if not r["court_id"].startswith("in-dc-") or not r.get("needs_review"): continue
    nm = r["name"].replace("District Court ", ""); c = best.get(rcore(nm, "IN")) or best.get(rcore(nm.split()[0], "IN"))
    if not c: continue
    st = a1.get(c[3], ("",))[0]
    r["jurisdiction"] += f", {st}"; r["address"]["region"] = st
    hc = f"in-hc-{HC.get(st,'')}"; r["parent_court_id"] = hc if hc in ids else None
    r["place_ids"] = r["place_ids"] or rmatch([nm, c[2]], "IN")
    r["record_note"] = r["record_note"].replace("; state unmatched", "; state via GeoNames cities500 name match")
    r["needs_review"] = True; r["geonames_admin1"] = c[3]; fx += 1
open(OUT, "w").write("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))
print("placed", fx)
