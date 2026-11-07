"""NC courthouses from nccourts.gov/locations/<county>-county (official; robots allowed, 2 s delay). Writes data/us/cos/NC_loc.jsonl for us_cos_ingest merge."""
import re, json, sys, datetime
sys.path.insert(0, "/workspace/world_courts/scrapers/courts")
import us_cos_ingest as I, us_directory_extract as de
B = "https://www.nccourts.gov"
seeds = {}
for l in open(I.SEED):
    s = json.loads(l)
    if s["state"] == "NC" and s["county_or_place"].endswith("County"): seeds[s["county_or_place"]] = s["gnis_id"]
h, pol, err = I.fetch(B + "/locations")
counties = sorted(set(re.findall(r'href="/locations/([a-z-]+-county)"', h or "")))
print("counties", len(counties), err, flush=True)
REC = re.compile(r"Location\n\s*(.+?)\s*\n(?:.*\n){0,3}?\s*Visit us\n\s*(.+?)\s*\n(?:\s*((?:Suite|Room|Ste|Floor|Unit)[^\n]*)\n)?\s*([A-Za-z .'-]+?)\s*,\n\s*NC\s*\n\s*(\d{5})")
now = datetime.datetime.now(datetime.UTC).isoformat(); out = []; blk = []
for c in counties:
    ch, pol, err = I.fetch(f"{B}/locations/{c}")
    if not ch: blk.append({"url": f"{B}/locations/{c}", "reason": err}); continue
    kids = sorted(set(k for k in re.findall(rf'href="(/locations/{c}/[a-z0-9-]+)"', ch) if not re.search(r"contact-directory|jury|schedule|rules-and-forms|payment|news|calendar", k)))
    cname = c.replace("-", " ").title()
    for k in kids:
        kh, kp, ke = I.fetch(B + k)
        if not kh: blk.append({"url": B + k, "reason": ke}); continue
        m = REC.search(de.totext(kh).replace(" \n", "\n"))
        if not m: continue
        out.append({"court_id": None, "name": m.group(1).strip(), "level": None, "court_system": "state", "country_code": "US", "subdivision": "US-NC", "jurisdiction": None,
            "parent_court_id": None, "address": {"street": m.group(2).strip(), "city": m.group(4).strip(), "postcode": m.group(5), "region": "NC", "country": "US"}, "geo": None,
            "place_ids": [], "gnis_id": seeds.get(cname), "seed_county_or_place": cname, "source_url": B + k, "source_kind": "official", "site_policy": kp,
            "retrieved_at": now, "needs_review": False, "seed": "chief_of_staff_inbox:nccourts_locations"})
    print(c, len(out), flush=True)
with open(I.D + "cos/NCLOC.jsonl", "w") as f:
    for r in out: f.write(json.dumps(r) + "\n")
with open(I.D + "cos/NCLOC.blockers.jsonl", "w") as f:
    for b in blk: f.write(json.dumps(b) + "\n")
print("NC rows", len(out), "blocked", len(blk))
