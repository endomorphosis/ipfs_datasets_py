"""Build data/ca/ca_courthouses.jsonl from official provincial sources (ON CSV, BC ArcGIS, QC justice.gouv.qc.ca, SK/MB/NS court sites), federal courts, OSM, Wikidata."""
import sys, glob, csv, io
sys.path.insert(0, "/workspace/world_courts/scrapers/courts/intl"); sys.path.insert(0, "/workspace/world_courts/scrapers/courts/rules")
from courts_common import *
from rules_common import RAW, html_text
CS = "https://www.justice.gc.ca/eng/csj-sjc/ccs-ajc/"
PROV = {  # code: (name, appeal, superior, provincial)
 "ON": ("Ontario", "Court of Appeal for Ontario", "Superior Court of Justice (Ontario)", "Ontario Court of Justice"),
 "BC": ("British Columbia", "Court of Appeal for British Columbia", "Supreme Court of British Columbia", "Provincial Court of British Columbia"),
 "AB": ("Alberta", "Court of Appeal of Alberta", "Court of King's Bench of Alberta", "Alberta Court of Justice"),
 "SK": ("Saskatchewan", "Court of Appeal for Saskatchewan", "Court of King's Bench for Saskatchewan", "Provincial Court of Saskatchewan"),
 "MB": ("Manitoba", "Manitoba Court of Appeal", "Court of King's Bench of Manitoba", "Provincial Court of Manitoba"),
 "QC": ("Québec", "Court of Appeal of Quebec", "Superior Court of Quebec", "Court of Quebec"),
 "NB": ("New Brunswick", "Court of Appeal of New Brunswick", "Court of King's Bench of New Brunswick", "Provincial Court of New Brunswick"),
 "NS": ("Nova Scotia", "Nova Scotia Court of Appeal", "Supreme Court of Nova Scotia", "Provincial Court of Nova Scotia"),
 "PE": ("Prince Edward Island", "Court of Appeal of Prince Edward Island", "Supreme Court of Prince Edward Island", "Provincial Court of Prince Edward Island"),
 "NL": ("Newfoundland and Labrador", "Court of Appeal of Newfoundland and Labrador", "Supreme Court of Newfoundland and Labrador", "Provincial Court of Newfoundland and Labrador"),
 "YT": ("Yukon", "Court of Appeal of Yukon", "Supreme Court of Yukon", "Territorial Court of Yukon"),
 "NT": ("Northwest Territories", "Court of Appeal of the Northwest Territories", "Supreme Court of the Northwest Territories", "Territorial Court of the Northwest Territories"),
 "NU": ("Nunavut", "Nunavut Court of Appeal", "Nunavut Court of Justice", "Nunavut Court of Justice (Justice of the Peace / Territorial jurisdiction)"),
}
FED = [("ca-scc", "Supreme Court of Canada", "supreme", None, "https://www.scc-csc.ca/"), ("ca-fca", "Federal Court of Appeal", "federal_appellate", "ca-scc", "https://decisions.fca-caf.gc.ca/"),
       ("ca-fc", "Federal Court", "federal_district", "ca-fca", "https://www.fct-cf.gc.ca/"), ("ca-tcc", "Tax Court of Canada", "tax", "ca-fca", "https://www.tcc-cci.gc.ca/"),
       ("ca-cmac", "Court Martial Appeal Court of Canada", "federal_appellate", "ca-scc", "https://www.cmac-cacm.ca/")]
def bodies():
    out = []
    for cid, nm, lv, par, src in FED:
        out.append(rec(court_id=cid, record_type="court_body", name=nm, level=lv, court_system="federal", country_code="CA", subdivision="CA", parent_court_id=par, source_url=src))
    for c, (pn, a, s, p) in PROV.items():
        sub = f"CA-{c}"; sp = subdivision_place("CA", pn)
        l = c.lower()
        if c == "NU":
            out.append(rec(court_id="ca-nu-court-of-appeal", record_type="court_body", name=a, level="appellate", court_system="territorial", country_code="CA", subdivision=sub, parent_court_id="ca-scc", source_url=CS, place_ids=[sp] if sp else []))
            out.append(rec(court_id="ca-nu-superior-court", record_type="court_body", name=s, level="trial_general", court_system="territorial", country_code="CA", subdivision=sub, parent_court_id="ca-nu-court-of-appeal", source_url=CS, place_ids=[sp] if sp else []))
            continue
        out.append(rec(court_id=f"ca-{l}-court-of-appeal", record_type="court_body", name=a, level="appellate", court_system="territorial" if c in ("YT", "NT") else "state", country_code="CA", subdivision=sub, parent_court_id="ca-scc", source_url=CS, place_ids=[sp] if sp else []))
        out.append(rec(court_id=f"ca-{l}-superior-court", record_type="court_body", name=s, level="trial_general", court_system="territorial" if c in ("YT", "NT") else "state", country_code="CA", subdivision=sub, parent_court_id=f"ca-{l}-court-of-appeal", source_url=CS, place_ids=[sp] if sp else []))
        out.append(rec(court_id=f"ca-{l}-provincial-court", record_type="court_body", name=p, level="trial_limited", court_system="territorial" if c in ("YT", "NT") else "state", country_code="CA", subdivision=sub, parent_court_id=f"ca-{l}-superior-court", source_url=CS, place_ids=[sp] if sp else []))
    return out
PCRE = r"([A-Z]\d[A-Z] ?\d[A-Z]\d)"
def pc_fmt(p): p = p.replace(" ", ""); return p[:3] + " " + p[3:]
def mk(cid, name, prov, street, city, pc, parent, url, kind, policy, lat=None, lon=None, phone=None, lic=None, level=None, extra=None, **kw):
    pn = PROV[prov][0]
    return rec(court_id=cid, name=name, level=level or ("trial_general" if "superior" in (parent or "") else "trial_limited" if "provincial" in (parent or "") else "other"),
               court_system="territorial" if prov in ("YT", "NT", "NU") else "state", country_code="CA", subdivision=f"CA-{prov}", parent_court_id=parent,
               address={"street": street, "city": city, "postcode": pc, "region": prov, "country": "CA"}, geo={"lat": lat, "lon": lon}, phone=phone, website=url,
               source_url=url, source_kind=kind, site_policy=policy, license=lic, geo_source=("official" if lat else None), **kw)

def parse_pc_pages(files, prov, parent, label, urlbase=None):
    """generic: any line ending '<city>, <prov|province> A1A 1A1' -> street = previous usable line (or same line before first comma)"""
    out = []
    for fp, url in files:
        try: t = html_text(open(fp, "rb").read().decode("utf-8", "replace"))
        except FileNotFoundError: continue
        ls = [l.strip() for l in t.split("\n")]
        seen = set()
        for i, l in enumerate(ls):
            m = re.search(r"^(?:(.+?),\s*)?([A-Za-zÀ-ÿ.' -]+?),?\s+(?:SK|MB|NS|Saskatchewan|Manitoba|Nova Scotia),?\s*" + PCRE + r"$", l)
            if not m: continue
            street, city, pc = m.group(1), m.group(2).strip(), pc_fmt(m.group(3))
            if not street:
                j = i - 1
                while j >= 0 and (not ls[j] or re.match(r"\(?(mailing|box|p\.?o\.? box)", ls[j], re.I)): j -= 1
                street = ls[j] if j >= 0 else None
            key = (street, pc)
            if key in seen: continue
            seen.add(key); out.append(dict(street=street, city=city, pc=pc, url=url, fp=fp, line=i, lines=ls))
    return out

def build():
    now = NOW(); rows = bodies(); added = []
    # ---- Ontario official CSV (lat/lon, MAG courthouse list)
    txt = open(f"{RAW}/intl_on_courthouses.csv", "rb").read().decode("utf-8-sig", "replace")
    n_on = 0
    for r in csv.DictReader(io.StringIO(txt), quotechar="'"):
        nm = r["Bldg_Ministry_Official_Name"]
        if not re.search(r"court", nm, re.I): continue
        m = re.match(r"^(.*?)\s+-\s+(.*)$", nm); street, name = (m.group(1), m.group(2)) if m else (None, nm)
        try: lat, lon = float(r["Bldg_Latitude"]), float(r["Bldg_Longitude"])
        except: lat = lon = None
        city = r["Bldg_City"]; pl, meth = match_place(city, "CA")
        rr = mk(f"ca-on-{slug(name)}-{slug(street or city)}"[:110], name, "ON", street, city, r["Bldg_Postal_Code"], "ca-on-superior-court", "https://www.ontario.ca/page/courthouse-locations", "official", "robots_allowed", lat, lon,
                lic="OGL-Ontario", place_ids=pl, place_match_method=meth, level="trial_general", upstream="data.ontario.ca Ministry of Government and Consumer Services courthouse building list")
        rr["source_url"] = "https://data.ontario.ca/dataset/ontario-courthouse-locations"; rows.append(rr); n_on += 1
    # ---- BC ArcGIS
    import json as _j
    bc = _j.load(open(f"{RAW}/intl_bc_courts.json"))
    for f in bc["features"]:
        a = f["attributes"]; g = f.get("geometry") or {}
        svc = (a.get("COURT_LEVEL_SERVICES") or "")
        parent = "ca-bc-superior-court" if "supreme" in svc.lower() else "ca-bc-provincial-court"
        pl, meth = match_place(a.get("LOCALITY"), "CA")
        nm = (a.get("OCCUPANT_NAME") or "").title()
        rr = mk(f"ca-bc-{slug(nm)}-{a.get('SEQUENCE_ID')}", nm, "BC", a.get("STREET_ADDRESS"), a.get("LOCALITY"), a.get("POSTAL_CODE"), parent,
                "https://delivery.maps.gov.bc.ca/arcgis/rest/services/mpcm/bcgwpub/MapServer/222", "official", "robots_absent_allowed", g.get("y") or a.get("LATITUDE"), g.get("x") or a.get("LONGITUDE"),
                phone=a.get("CONTACT_PHONE"), lic="OGL-BC", place_ids=pl, place_match_method=meth, level="trial_general" if parent.endswith("superior-court") else "trial_limited")
        rr["hours"] = a.get("HOURS_OF_OPERATION"); rr["services"] = svc; rows.append(rr)
    # ---- Quebec (justice.gouv.qc.ca; archived copies where live fetch blocked)
    for fp in sorted(glob.glob(f"{RAW}/intl_qc_*.html")):
        k = fp.split("intl_qc_")[1][:-5]
        if not k.startswith(("palais", "point")): continue
        try: meta = _j.load(open(fp + ".meta")); h = open(fp, "rb").read().decode("utf-8", "replace")
        except Exception: continue
        t = html_text(h); ls = [l.strip() for l in t.split("\n")]
        title = re.sub(r"\s*-\s*Minist.*$", "", ls[0].replace("html ", "", 1)).strip()
        m = re.search(r"\n([^\n]+?),?\n([^\n]+?)(?: \((?:Qu[ée]bec|Québec)\)|,\s*Q[Cc]),?\n?\s*" + PCRE + r"\s*(?:District judiciaire ([^\n]+))?", t)
        if not m: print("QC no addr", k); continue
        street, city, pc, dist = m.group(1).strip(), m.group(2).strip(), pc_fmt(m.group(3)), (m.group(4) or "").strip()
        ph = re.search(r"(\d{3} \d{3}-\d{4})", t[m.end():])
        pl, meth = match_place(city, "CA")
        rr = mk(f"ca-qc-{k}", title, "QC", street, city, pc, "ca-qc-superior-court" if k.startswith("palais") else "ca-qc-provincial-court", meta.get("url") or "https://justice.gouv.qc.ca/nous-joindre/trouver-un-palais-de-justice/" + k,
                "official", "robots_absent_allowed" + ("+archive_wayback" if "archive" in str(meta.get("policy")) else ""), phone=ph.group(1) if ph else None, lic="CC-BY-4.0 (Quebec gov.)" , place_ids=pl, place_match_method=meth,
                level="trial_general" if k.startswith("palais") else "trial_limited", name_local=title)
        rr["jurisdiction"] = dist or None; rows.append(rr)
    # ---- SK / MB / NS pages
    sk = parse_pc_pages([(f"{RAW}/intl_ca_sk_pc.html", "https://sasklawcourts.ca/provincial-court/about-the-court/provincial-court-offices/")], "SK", "ca-sk-provincial-court", "Provincial Court of Saskatchewan")
    for s in sk:
        i = s["line"]; ls = s["lines"]; j = i - 1
        while j >= 0 and not (ls[j].isupper() and len(ls[j]) < 40): j -= 1
        city = s["city"]; pl, meth = match_place(city, "CA"); nm = f"Provincial Court of Saskatchewan – {city}"
        rows.append(mk(f"ca-sk-provincial-{slug(city)}", nm, "SK", s["street"], city, s["pc"], "ca-sk-provincial-court", s["url"], "official", "robots_allowed", level="trial_limited", place_ids=pl, place_match_method=meth))
    skk = parse_pc_pages([(f"{RAW}/intl_ca_sk_kb.html", "https://sasklawcourts.ca/kings-bench/court-locations/")], "SK", "ca-sk-superior-court", "")
    for s in skk:
        city = s["city"]; pl, meth = match_place(city, "CA")
        rows.append(mk(f"ca-sk-kb-{slug(city)}", f"Court of King's Bench for Saskatchewan – {city}", "SK", s["street"], city, s["pc"], "ca-sk-superior-court", s["url"], "official", "robots_allowed", level="trial_general", place_ids=pl, place_match_method=meth))
    mbf = [(fp, "https://www.manitobacourts.mb.ca/provincial-court/locations-and-contact-info/location/" + fp.split("intl_ca_mb_")[1][:-5]) for fp in sorted(glob.glob(f"{RAW}/intl_ca_mb_*.html")) if not fp.endswith(("_pc.html", "_kb.html", "_sub.html"))]
    for s in parse_pc_pages(mbf, "MB", "ca-mb-provincial-court", ""):
        slg = s["fp"].split("intl_ca_mb_")[1][:-5]; city = s["city"]; pl, meth = match_place(city, "CA")
        rows.append(mk(f"ca-mb-provincial-{slug(slg)}-{slug(s['street'] or '')}"[:100], f"Provincial Court of Manitoba – {slg.replace('-', ' ').title()} ({s['street']})", "MB", s["street"], city, s["pc"], "ca-mb-provincial-court", s["url"], "official", "robots_allowed", level="trial_limited", place_ids=pl, place_match_method=meth))
    nsf = [(fp, "https://www.courts.ns.ca/locations/" + fp.split("intl_ca_ns_")[1][:-5]) for fp in sorted(glob.glob(f"{RAW}/intl_ca_ns_*.html")) if not fp.endswith("_sub.html")]
    for s in parse_pc_pages(nsf, "NS", "ca-ns-superior-court", ""):
        i = s["line"]; ls = s["lines"]; nm = ls[i-1] if i > 0 and not ls[i-1][:1].isdigit() else (s["fp"].split("intl_ca_ns_")[1][:-5].title() + " Courthouse")
        city = s["city"]; pl, meth = match_place(city, "CA")
        parent = "ca-ns-provincial-court" if re.search(r"provincial|pleasant|spring garden", (nm + s["street"]).lower()) else "ca-ns-superior-court"
        rows.append(mk(f"ca-ns-{slug(nm)}-{slug(s['street'])}"[:100], f"{nm} ({city}, NS)", "NS", s["street"], city, s["pc"], parent, s["url"], "official", "robots_allowed", level="trial_limited" if "provincial" in parent else "trial_general", place_ids=pl, place_match_method=meth))
    # ---- Federal (Ottawa)
    fed_addr = {"ca-scc": ("301 Wellington Street", "K1A 0J1", 45.4236, -75.7054, "https://www.scc-csc.ca/contact/"), "ca-fca": ("90 Sparks Street", "K1A 0H9", 45.4223, -75.6985, "https://www.fct-cf.gc.ca/en/pages/contact-us"),
                "ca-fc": ("90 Sparks Street", "K1A 0H9", 45.4223, -75.6985, "https://www.fct-cf.gc.ca/en/pages/contact-us"), "ca-tcc": ("200 Kent Street", "K1A 0M1", 45.4208, -75.6948, "https://www.tcc-cci.gc.ca/contact/")}
    for cid, (st, pc, la, lo, u) in fed_addr.items():
        b = next(b for b in FED if b[0] == cid)
        pl, meth = match_place("Ottawa", "CA")
        rr = mk(f"{cid}-ottawa", b[1] + " (Ottawa)", "ON", st, "Ottawa", pc, cid, u, "official", "robots_allowed", None, None, place_ids=pl, place_match_method="name", level=b[2], lic="Crown-copyright / GC terms")
        rr["court_system"] = "federal"; rr["subdivision"] = "CA-ON"; rr["geo"] = {"lat": None, "lon": None}; rr["hand_entered"] = True; rr["approx_geo_hint"] = [la, lo]
        rows.append(rr)
    # ---- geocode address-only official rows via Nominatim (<=1 req/s, cached)
    todo = [r for r in rows if r["record_type"] == "courthouse" and r["geo"]["lat"] is None and r["address"].get("street")]
    print("to geocode", len(todo), flush=True)
    for r in todo:
        a = r["address"]
        q = ", ".join(x for x in [a["street"], a["city"], a["region"], a["postcode"], "Canada"] if x)
        g = nominatim(q, "CA") or nominatim(", ".join(x for x in [a["street"], a["city"], a["region"], "Canada"] if x), "CA")
        if g:
            r["geo"] = {"lat": g[0], "lon": g[1]}; r["geo_source"] = "nominatim(OSM) geocode of official address"
        elif r.get("approx_geo_hint"):
            r["geo"] = {"lat": r["approx_geo_hint"][0], "lon": r["approx_geo_hint"][1]}; r["geo_source"] = "hand-entered approx"
    nominatim_flush()
    # ---- OSM + Wikidata merge
    nominatim_flush()
    official = rows
    for kind in ("osm", "wd"):
        sec = []
        for l in rjl(f"{ROOT}/data/ca/ca_courthouses_{kind}.jsonl"):
            if kind == "osm":
                a = {"street": l.get("street"), "city": l.get("city"), "postcode": l.get("postcode"), "region": (l.get("subdivision") or "").replace("CA-", "") or None, "country": "CA"}
                r = rec(court_id=f"osm:{l['osm_id']}", name=l.get("name") or l.get("name_local") or "Courthouse", name_local=l.get("name_local"), country_code="CA", subdivision=l.get("subdivision"), address=a,
                        geo={"lat": l.get("lat"), "lon": l.get("lon")}, phone=l.get("phone"), website=l.get("website"), wikidata=l.get("wikidata"), source_url=f"https://www.openstreetmap.org/{l['osm_id']}",
                        source_kind="osm", site_policy="open_license:ODbL", license="ODbL-1.0", retrieved_at=l.get("retrieved_at") or NOW())
            else: r = l
            sec.append(r)
        official, dup, add = merge_dedupe(official, sec, dist_m=200); print(kind, "dup", dup, "added", add, flush=True)
    rows = official
    # subdivision for rows lacking it: nearest labelled row within 400 km
    lab = [(r["geo"]["lat"], r["geo"]["lon"], r["subdivision"]) for r in rows if r["record_type"] == "courthouse" and r["subdivision"] and r["geo"]["lat"] is not None and r["source_kind"] != "wikidata"]
    for r in rows:
        if r["record_type"] == "courthouse" and not r["subdivision"] and r["geo"]["lat"] is not None:
            best = min(lab, key=lambda x: haversine((x[0], x[1]), (r["geo"]["lat"], r["geo"]["lon"])))
            if haversine((best[0], best[1]), (r["geo"]["lat"], r["geo"]["lon"])) < 150000: r["subdivision"] = best[2]; r["subdivision_method"] = "nearest_labelled"
    for r in rows:
        if r["record_type"] != "courthouse" or r["source_kind"] not in ("osm", "wikidata"): continue
        sub = (r["subdivision"] or "").replace("CA-", "")
        if not r["place_ids"]:
            pl, meth = match_place(r["address"].get("city"), "CA")
            if not pl:
                nm = re.sub(r"(?i)\b(court ?house|courthouse|palais de justice|law courts?|provincial|court|cour|supreme|superior|of justice|building|municipal|de|du)\b", " ", r["name"]); pl, meth = match_place(nm.strip(), "CA")
            r["place_ids"] = pl; r["place_match_method"] = meth
        if r["parent_court_id"] is None and sub in PROV:
            n = r["name"].lower(); l = sub.lower()
            r["parent_court_id"] = f"ca-{l}-court-of-appeal" if "appeal" in n else f"ca-{l}-provincial-court" if re.search(r"provincial|territorial|municipal|cour du qu|youth|family", n) else f"ca-{l}-superior-court"
            if sub == "NU": r["parent_court_id"] = "ca-nu-superior-court"
            r["level"] = {"appeal": "appellate", "provincial": "trial_limited", "superior": "trial_general"}.get(r["parent_court_id"].split("-")[-2 if r["parent_court_id"].endswith("court-of-appeal") else -2], r["level"]) if False else r["level"]
        if r["subdivision"] in [f"CA-{c}" for c in PROV] and r["parent_court_id"] and r["level"] == "other":
            r["level"] = "appellate" if r["parent_court_id"].endswith("appeal") else "trial_limited" if r["parent_court_id"].endswith("provincial-court") else "trial_general"
        r["court_system"] = "territorial" if sub in ("YT", "NT", "NU") else "state"
    for r in rows:   # province place id as secondary
        if r["record_type"] == "courthouse" and r["subdivision"] and r["subdivision"].startswith("CA-"):
            sp = subdivision_place("CA", PROV.get(r["subdivision"][3:], ("",))[0])
            if sp and sp not in r["place_ids"]: r["place_ids"] = r["place_ids"] + [sp]
    seen = {}
    for r in rows:
        n = seen.get(r["court_id"], 0); seen[r["court_id"]] = n + 1
        if n: r["court_id"] = f'{r["court_id"]}~{n}'
    wjl(f"{ROOT}/data/ca/ca_courthouses.jsonl", rows)
    ch = [r for r in rows if r["record_type"] == "courthouse"]
    import collections
    print("CA total", len(rows), "courthouses", len(ch), "geo", sum(1 for r in ch if r["geo"]["lat"] is not None), "place_ids", sum(1 for r in ch if r["place_ids"]), "parent", sum(1 for r in ch if r["parent_court_id"]), collections.Counter(r["source_kind"] for r in ch), collections.Counter(r["subdivision"] for r in ch).most_common(15))
if __name__ == "__main__": build()
