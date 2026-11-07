"""IN district judiciary units from Certificate-Transparency logs (crt.sh) of *.dcourts.gov.in.
Each subdomain = an official eCourts district-court website (one per judicial district). Rows are court_body
nodes (no address/geo). Places matched by name to global_municipalities (wd:). Dedup vs existing court_ids/websites."""
import json, sys, re, datetime
sys.path.insert(0, "/workspace/world_courts/scrapers/courts/intl")
from row_common import *
OUT = "/workspace/world_courts/data/in/in_courthouses.jsonl"
HC = {"Andhra Pradesh":"andhra-pradesh","Telangana":"telangana","Assam":"gauhati","Nagaland":"gauhati","Mizoram":"gauhati","Arunachal Pradesh":"gauhati",
"Bihar":"patna","Chhattisgarh":"chhattisgarh","Delhi":"delhi","Goa":"bombay","Maharashtra":"bombay","Gujarat":"gujarat","Himachal Pradesh":"himachal-pradesh",
"Jammu and Kashmir":"jammu-kashmir-ladakh","Ladakh":"jammu-kashmir-ladakh","Jharkhand":"jharkhand","Karnataka":"karnataka","Kerala":"kerala","Madhya Pradesh":"madhya-pradesh",
"Tamil Nadu":"madras","Puducherry":"madras","Manipur":"manipur","Meghalaya":"meghalaya","Odisha":"orissa","Punjab":"punjab-haryana","Haryana":"punjab-haryana","Chandigarh":"punjab-haryana",
"Rajasthan":"rajasthan","Sikkim":"sikkim","Tripura":"tripura","Uttarakhand":"uttarakhand","Uttar Pradesh":"allahabad","West Bengal":"calcutta","Andaman and Nicobar Islands":"calcutta"}
rows = [json.loads(l) for l in open(OUT)]
ids = {r["court_id"] for r in rows}; hcs = {i for i in ids if i.startswith("in-hc-")}
webs = {(r.get("website") or "").lower() for r in rows}
a1 = gn_admin1("IN"); a2 = gn_admin2("IN")
d2s = {}
for k, n in a2.items(): d2s.setdefault(rcore(n, "IN"), a1.get(k.split(".")[0], ("",))[0])
subs = json.load(open("/workspace/world_courts/scrapers/courts/intl/seeds/dc_subs.json")); now = datetime.datetime.utcnow().isoformat() + "Z"
new = []
for s in subs:
    host = f"{s}.dcourts.gov.in"; url = f"https://{host}/"
    if any(host in w for w in webs): continue
    base = s.split(".")[0]; nm = re.sub(r"[-_]", " ", base).title()
    cid = f"in-dc-{s.replace('.', '-')}"
    if cid in ids: continue
    state = d2s.get(rcore(nm, "IN"))
    hc = f"in-hc-{HC[state]}" if state in HC and f"in-hc-{HC[state]}" in hcs else None
    new.append({"court_id": cid, "record_type": "court_body", "name": f"District Court {nm}", "name_local": None,
      "level": "trial_general", "court_system": "state", "country_code": "IN", "subdivision": "IN",
      "jurisdiction": f"{nm} judicial district" + (f", {state}" if state else ""), "parent_court_id": hc,
      "address": {"street": None, "city": None, "postcode": None, "region": state or None, "country": "India"},
      "geo": {"lat": None, "lon": None}, "phone": None, "website": url, "wikidata": None,
      "place_ids": rmatch([nm], "IN"), "source_url": "https://crt.sh/?q=%25.dcourts.gov.in", "source_kind": "official",
      "site_policy": "ct_log_public:official_domain_inventory", "retrieved_at": now, "license": "public-domain-facts",
      "sources": [{"source_url": "https://crt.sh/?q=%25.dcourts.gov.in", "site_policy": "ct_log_public", "source_kind": "official"}],
      "record_note": "district judiciary unit inferred from official eCourts subdomain (CT log); site not reachable from box; name from subdomain" + ("" if state else "; state unmatched"),
      "needs_review": state is None})
with open(OUT, "a") as f:
    for r in new: f.write(json.dumps(r, ensure_ascii=False) + "\n")
print("added", len(new), "with_place", sum(bool(r["place_ids"]) for r in new), "with_hc", sum(bool(r["parent_court_id"]) for r in new))
