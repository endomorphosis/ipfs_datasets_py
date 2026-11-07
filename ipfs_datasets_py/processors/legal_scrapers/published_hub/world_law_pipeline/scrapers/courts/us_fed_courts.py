"""US federal courts: court bodies from uscourts.gov 'Court Website Links' (robots allowed; /federal-court-finder/ is disallowed and not used),
plus courthouse/divisional addresses extracted from each court's own site (home + location/contact pages, robots + crawl delay).
Writes data/us/us_federal_courts.jsonl (bodies) and data/us/cos/FED.jsonl (courthouse rows for us_cos_ingest merge)."""
import re, json, sys, datetime, urllib.parse, collections
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, "/workspace/world_courts/scrapers/courts")
import us_cos_ingest as I, us_directory_extract as de
LINKS = "/workspace/world_courts/data/ref/us_fed/links.html"; SRC = "https://www.uscourts.gov/about-federal-courts/court-role-and-structure/court-website-links"
ST = {"Alabama":"AL","Alaska":"AK","Arizona":"AZ","Arkansas":"AR","California":"CA","Colorado":"CO","Connecticut":"CT","Delaware":"DE","District of Columbia":"DC","Florida":"FL","Georgia":"GA","Guam":"GU","Hawaii":"HI","Idaho":"ID","Illinois":"IL","Indiana":"IN","Iowa":"IA","Kansas":"KS","Kentucky":"KY","Louisiana":"LA","Maine":"ME","Maryland":"MD","Massachusetts":"MA","Michigan":"MI","Minnesota":"MN","Mississippi":"MS","Missouri":"MO","Montana":"MT","Nebraska":"NE","Nevada":"NV","New Hampshire":"NH","New Jersey":"NJ","New Mexico":"NM","New York":"NY","North Carolina":"NC","North Dakota":"ND","Northern Mariana Islands":"MP","Ohio":"OH","Oklahoma":"OK","Oregon":"OR","Pennsylvania":"PA","Puerto Rico":"PR","Rhode Island":"RI","South Carolina":"SC","South Dakota":"SD","Tennessee":"TN","Texas":"TX","Utah":"UT","Vermont":"VT","Virgin Islands":"VI","Virginia":"VA","Washington":"WA","West Virginia":"WV","Wisconsin":"WI","Wyoming":"WY"}
def bodies():
    h = open(LINKS).read(); out = {}
    for u, t in re.findall(r'href="(https?://[^"]*uscourts\.gov[^"]*)"[^>]*>([^<]*)', h):
        t = t.strip(); m = re.match(r"https?://(?:www\.)?([a-z0-9]+)\.uscourts\.gov", u)
        if not m or "www.uscourts.gov" in u or re.search(r"pretrial|probation", t, re.I): continue
        k = m.group(1)
        if re.match(r"ca\d+$|cadc$|cafc$", k): typ, lvl = "circuit", "federal_appellate"
        elif u.rstrip("/").endswith("/bankruptcy") or k.endswith("b"): typ, lvl = "bankruptcy", "federal_bankruptcy"
        elif k.endswith("d") or k in ("are", "mow", "txs"): typ, lvl = "district", "federal_district"
        else: continue
        cid = "us-fed-" + k + ("b" if typ == "bankruptcy" and not k.endswith("b") else "")
        if cid in out: continue
        stname = next((s for s in sorted(ST, key=len, reverse=True) if t.startswith(s)), None)
        name = {"circuit": f"U.S. Court of Appeals for the {t}", "district": f"U.S. District Court, {t}", "bankruptcy": f"U.S. Bankruptcy Court, {t}"}[typ]
        out[cid] = {"record_type": "court_body", "court_id": cid, "name": name, "level": lvl, "court_system": "federal", "country_code": "US",
            "subdivision": ("US-" + ST[stname]) if stname else "US", "jurisdiction": "US-federal", "court_type": typ, "website": u, "parent_court_id": None,
            "source_url": SRC, "source_kind": "official", "site_policy": "robots_allowed"}
    for cid, n, lvl, u, sd in (("us-fed-scotus", "Supreme Court of the United States", "federal_supreme", "https://www.supremecourt.gov/", "US-DC"),
                           ("us-fed-cofc", "U.S. Court of Federal Claims", "federal_specialized", "https://www.uscfc.uscourts.gov/", "US-DC"),
                           ("us-fed-cit", "U.S. Court of International Trade", "federal_specialized", "https://www.cit.uscourts.gov/", "US-NY")):
        out[cid] = {"record_type": "court_body", "court_id": cid, "name": n, "level": lvl, "court_system": "federal", "country_code": "US", "subdivision": sd,
            "jurisdiction": "US-federal", "court_type": cid[7:], "website": u, "parent_court_id": None, "source_url": u, "source_kind": "official", "site_policy": "robots_allowed"}
    return out
LOC = re.compile(r"locat|courthouse|division|contact|address|visit|directions|hours", re.I)
for s_ in ST.values(): de.STNAME[s_] = s_
def crawl(b):
    u = b["website"]; h, pol, err = I.fetch(u)
    if not h: return b, [], err
    host = urllib.parse.urlsplit(u).netloc; pages = [(h, u, pol)]
    kids = [urllib.parse.urljoin(u, x) for x, t in re.findall(r'href="([^"#]+)"[^>]*>(.*?)</a>', h, re.S) if LOC.search(x + " " + re.sub(r"<[^>]+>", "", t))]
    kids = [k for k in dict.fromkeys(kids) if urllib.parse.urlsplit(k).netloc == host and not re.search(r"\.(pdf|docx?|jpg|png)$|mailto|calendar|news", k, re.I)][:5]
    for k in kids:
        hh, pp, ee = I.fetch(k)
        if hh: pages.append((hh, k, pp))
    st = b["subdivision"][3:] if b["subdivision"] != "US" else "DC"; out = {}
    for hh, uu, pp in pages:
        for a in de.extract(de.totext(hh), st):
            if re.match(r"(?i)p\.?\s*o\.?\s*box", a["street"]) or not re.match(r"\d+\s+\S", a["street"]): continue
            key = (a["street"].lower(), a["postcode"])
            if key in out: continue
            g = I.goodname(a["name"]); nm = g or f'{b["name"]} ({a["city"]})'
            out[key] = {"court_id": None, "name": nm, "level": b["level"], "court_system": "federal", "country_code": "US", "subdivision": "US-" + st,
                "jurisdiction": "US-federal", "parent_court_id": b["court_id"], "address": {"street": a["street"].split("\n")[-1].strip(" ,"), "city": a["city"], "postcode": a["postcode"], "region": st, "country": "US"},
                "geo": None, "place_ids": [], "gnis_id": None, "source_url": uu, "source_kind": "official", "site_policy": pp, "retrieved_at": datetime.datetime.now(datetime.UTC).isoformat(),
                "needs_review": True, "name_derived": not g}
    return b, list(out.values()), None if out else "no_address_found"
if __name__ == "__main__":
    B = bodies(); print("bodies", len(B), collections.Counter(b["court_type"] for b in B.values()), flush=True)
    with open(I.D + "us_federal_courts.jsonl", "w") as f:
        for b in B.values(): f.write(json.dumps(b) + "\n")
    if "bodies" in sys.argv: sys.exit()
    with ThreadPoolExecutor(16) as ex: res = list(ex.map(crawl, [b for b in B.values() if b["court_id"] != "us-fed-scotus"]))
    rows = [r for _, rs, _ in res for r in rs]; blk = [{"court_id": b["court_id"], "url": b["website"], "reason": e} for b, rs, e in res if e]
    rows.append({"court_id": None, "name": "Supreme Court of the United States", "level": "federal_supreme", "court_system": "federal", "country_code": "US", "subdivision": "US-DC", "jurisdiction": "US-federal",
        "parent_court_id": "us-fed-scotus", "address": {"street": "1 First Street NE", "city": "Washington", "postcode": "20543", "region": "DC", "country": "US"}, "geo": None, "place_ids": [], "gnis_id": None,
        "source_url": "https://www.supremecourt.gov/contact/contactus.aspx", "source_kind": "official", "site_policy": "robots_allowed", "retrieved_at": datetime.datetime.now(datetime.UTC).isoformat(), "needs_review": False})
    u = {}
    for r in rows: u.setdefault((r["address"]["street"].lower(), r["address"]["postcode"]), r)
    with open(I.D + "cos/FED.jsonl", "w") as f:
        for r in u.values(): f.write(json.dumps(r) + "\n")
    with open(I.D + "cos/FED.blockers.jsonl", "w") as f:
        for b in blk: f.write(json.dumps(b) + "\n")
    print("rows", len(u), "blocked", collections.Counter(b["reason"] for b in blk))
