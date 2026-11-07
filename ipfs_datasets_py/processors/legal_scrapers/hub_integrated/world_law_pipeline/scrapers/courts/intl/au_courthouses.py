"""Build data/au/au_courthouses.jsonl : GA Judicial Courts (federal registries), Queensland Courts directory, OSM, Wikidata; court-body hierarchy; place_ids."""
import sys, csv, io, collections
sys.path.insert(0, "/workspace/world_courts/scrapers/courts/intl"); sys.path.insert(0, "/workspace/world_courts/scrapers/courts/rules")
from courts_common import *
from rules_common import RAW, html_text
ST = {  # code: (name, supreme, intermediate, lower, iso)
 "NSW": ("New South Wales", "Supreme Court of New South Wales", "District Court of New South Wales", "Local Court of New South Wales"),
 "VIC": ("Victoria", "Supreme Court of Victoria", "County Court of Victoria", "Magistrates' Court of Victoria"),
 "QLD": ("Queensland", "Supreme Court of Queensland", "District Court of Queensland", "Magistrates Courts of Queensland"),
 "WA": ("Western Australia", "Supreme Court of Western Australia", "District Court of Western Australia", "Magistrates Court of Western Australia"),
 "SA": ("South Australia", "Supreme Court of South Australia", "District Court of South Australia", "Magistrates Court of South Australia"),
 "TAS": ("Tasmania", "Supreme Court of Tasmania", None, "Magistrates Court of Tasmania"),
 "NT": ("Northern Territory", "Supreme Court of the Northern Territory", None, "Local Court of the Northern Territory"),
 "ACT": ("Australian Capital Territory", "Supreme Court of the Australian Capital Territory", None, "Magistrates Court of the Australian Capital Territory"),
}
ISO = {v[0]: k for k, v in ST.items()}
SRC = "https://www.hcourt.gov.au/about/about-the-court/the-australian-court-system"
HIER = "https://www.ag.gov.au/legal-system/australias-court-system"
def bodies():
    out = [rec(court_id="au-hca", record_type="court_body", name="High Court of Australia", level="supreme", court_system="federal", country_code="AU", subdivision="AU", source_url=SRC),
           rec(court_id="au-fca", record_type="court_body", name="Federal Court of Australia", level="federal_district", court_system="federal", country_code="AU", subdivision="AU", parent_court_id="au-hca", source_url="https://www.fedcourt.gov.au/"),
           rec(court_id="au-fcfcoa", record_type="court_body", name="Federal Circuit and Family Court of Australia", level="family", court_system="federal", country_code="AU", subdivision="AU", parent_court_id="au-hca", source_url="https://www.fcfcoa.gov.au/")]
    for c, (n, s, i, l) in ST.items():
        lc = c.lower(); sub = f"AU-{c}"; sp = subdivision_place("AU", n); pid = [sp] if sp else []
        sys_ = "territorial" if c in ("NT", "ACT") else "state"
        out.append(rec(court_id=f"au-{lc}-supreme-court", record_type="court_body", name=s, level="supreme", court_system=sys_, country_code="AU", subdivision=sub, parent_court_id="au-hca", source_url=HIER, place_ids=pid))
        if i: out.append(rec(court_id=f"au-{lc}-intermediate-court", record_type="court_body", name=i, level="trial_general", court_system=sys_, country_code="AU", subdivision=sub, parent_court_id=f"au-{lc}-supreme-court", source_url=HIER, place_ids=pid))
        out.append(rec(court_id=f"au-{lc}-lower-court", record_type="court_body", name=l, level="trial_limited", court_system=sys_, country_code="AU", subdivision=sub, parent_court_id=f"au-{lc}-intermediate-court" if i else f"au-{lc}-supreme-court", source_url=HIER, place_ids=pid))
    return out

def body_for(name, sub):
    n = name.lower(); c = (sub or "").replace("AU-", "").lower()
    if c not in [x.lower() for x in ST]:
        return "au-hca" if "high court" in n else "au-fcfcoa" if re.search(r"federal circuit|family court", n) else "au-fca" if "federal court" in n else None
    if "high court" in n: return "au-hca"
    if re.search(r"federal circuit|family court", n): return "au-fcfcoa"
    if "federal court" in n: return "au-fca"
    if "supreme" in n or "court of appeal" in n or "court of criminal appeal" in n: return f"au-{c}-supreme-court"
    if re.search(r"district court|county court", n) and c not in ("tas", "nt", "act"): return f"au-{c}-intermediate-court"
    return f"au-{c}-lower-court"

def build():
    rows = bodies(); now = NOW()
    # GA Judicial Courts (Geoscience Australia; federal court registries; CC-BY)
    txt = open(f"{RAW}/intl_au_ga_judicial.csv", "rb").read().decode("utf-8-sig", "replace")
    for r in csv.DictReader(io.StringIO(txt)):
        sub = "AU-" + ISO.get(r["STATE"], "")
        cls = r["CLASS"]; nm = f"{cls} registry – {r['NAME']}"
        pl, meth = match_place(r["SUBURB"], "AU")
        bd = body_for(cls, sub)
        rr = rec(court_id=f"au-ga-{slug(cls)}-{slug(r['NAME'])}-{r['FID']}", name=nm, level={"au-hca": "supreme", "au-fca": "federal_district", "au-fcfcoa": "family"}.get(bd, "other"), court_system="federal", country_code="AU", subdivision=sub, parent_court_id=bd,
                 address={"street": r["ADDRESS"], "city": r["SUBURB"], "postcode": None, "region": ISO.get(r["STATE"]), "country": "AU"}, geo={"lat": float(r["LATITUDE"]), "lon": float(r["LONGITUDE"])},
                 place_ids=pl, place_match_method=meth, source_url="https://data.gov.au/data/dataset/judicial-courts", source_kind="official", site_policy="robots_disallowed_archive_used", license="CC-BY-4.0 (Geoscience Australia)",
                 geo_source="GA 2012 survey", operational_status=r["OPERATIONALSTATUS"], dataset_revised=r["REVISED"])
        rows.append(rr)
    # Queensland Courts directory
    t = html_text(open(f"{RAW}/intl_au_qld.html", "rb").read().decode("utf-8", "replace")); ls = [l.strip() for l in t.split("\n")]
    heads = [i for i, l in enumerate(ls) if re.search(r"(Court|Courthouse|Tribunal|Registry|Court of Appeal)( \(.*\))?$", l) and i + 1 < len(ls) and ls[i + 1] in ("Court location", "Address:", "Registry location (enquiries and filing)", "Court and registry location")]
    n_q = 0
    for hi, i in enumerate(heads):
        end = heads[hi + 1] if hi + 1 < len(heads) else min(len(ls), i + 40)
        seg = ls[i + 1:end]; name = ls[i]
        a = None
        for k, l in enumerate(seg):
            if l == "Address:":
                lines = []
                for x in seg[k + 1:k + 8]:
                    if x in ("Map", "Phone:", "Business hours:", "Email:", "Registry location (enquiries and filing)"): break
                    lines.append(x)
                a = lines; break
        if not a: continue
        m = None
        for x in a:
            m = re.search(r"^(.*?)\s+(?:QLD|Qld)\s+(\d{4})$", x)
            if m: break
        if not m: continue
        city = m.group(1).title(); pc = m.group(2)
        street_lines = [x for x in a if not x.startswith("(") and x is not None and not re.search(r"(?:QLD|Qld)\s+\d{4}$", x)]
        ph = next((seg[k + 1] for k, l in enumerate(seg) if l == "Phone:" and k + 1 < len(seg)), None)
        pl, meth = match_place(city, "AU")
        bd = body_for(name, "AU-QLD")
        rr = rec(court_id=f"au-qld-{slug(name)}", name=name, level={"supreme": "supreme", "intermediate": "trial_general", "lower": "trial_limited"}.get(bd.split("-")[2], "other") if bd.startswith("au-qld") else "other",
                 court_system="state", country_code="AU", subdivision="AU-QLD", parent_court_id=bd, address={"street": ", ".join(street_lines) or None, "city": city, "postcode": pc, "region": "QLD", "country": "AU"},
                 geo={"lat": None, "lon": None}, phone=ph, place_ids=pl, place_match_method=meth, source_url="https://www.courts.qld.gov.au/contacts/courthouses", source_kind="official", site_policy="robots_absent_allowed", license="CC-BY-4.0 (Queensland Government)")
        rows.append(rr); n_q += 1
    print("qld official", n_q, flush=True)
    todo = [r for r in rows if r["record_type"] == "courthouse" and r["geo"]["lat"] is None and r["address"].get("street")]
    for r in todo:
        a = r["address"]
        g = nominatim(", ".join(x for x in [a["street"].split(", ")[-1], a["city"], a["region"], a["postcode"], "Australia"] if x), "AU") or nominatim(", ".join(x for x in [a["city"], a["region"], a["postcode"], "Australia"] if x), "AU")
        if g: r["geo"] = {"lat": g[0], "lon": g[1]}; r["geo_source"] = "nominatim(OSM) geocode of official address"
    nominatim_flush()
    official = rows
    for kind in ("osm", "wd"):
        sec = []
        for l in rjl(f"{ROOT}/data/au/au_courthouses_{kind}.jsonl"):
            if kind == "osm":
                a = {"street": l.get("street"), "city": l.get("city"), "postcode": l.get("postcode"), "region": (l.get("subdivision") or "").replace("AU-", "") or None, "country": "AU"}
                r = rec(court_id=f"osm:{l['osm_id']}", name=l.get("name") or l.get("name_local") or "Courthouse", name_local=l.get("name_local"), country_code="AU", subdivision=l.get("subdivision"), address=a,
                        geo={"lat": l.get("lat"), "lon": l.get("lon")}, phone=l.get("phone"), website=l.get("website"), wikidata=l.get("wikidata"), source_url=f"https://www.openstreetmap.org/{l['osm_id']}",
                        source_kind="osm", site_policy="open_license:ODbL", license="ODbL-1.0", retrieved_at=l.get("retrieved_at") or NOW())
            else: r = l
            sec.append(r)
        official, dup, add = merge_dedupe(official, sec, dist_m=200); print(kind, "dup", dup, "added", add, flush=True)
    rows = official
    # subdivision by nearest labelled (AU state boxes are big; require <300 km)
    lab = [(r["geo"]["lat"], r["geo"]["lon"], r["subdivision"]) for r in rows if r["record_type"] == "courthouse" and r["subdivision"] and r["subdivision"] != "AU-" and r["geo"]["lat"] is not None and r["source_kind"] != "wikidata"]
    for r in rows:
        if r["record_type"] == "courthouse" and (not r["subdivision"] or r["subdivision"] == "AU-") and r["geo"]["lat"] is not None:
            b = min(lab, key=lambda x: haversine((x[0], x[1]), (r["geo"]["lat"], r["geo"]["lon"])))
            if haversine((b[0], b[1]), (r["geo"]["lat"], r["geo"]["lon"])) < 300000: r["subdivision"] = b[2]; r["subdivision_method"] = "nearest_labelled"
    for r in rows:
        if r["record_type"] != "courthouse": continue
        if r["source_kind"] in ("osm", "wikidata"):
            if not r["place_ids"]:
                pl, meth = match_place(r["address"].get("city"), "AU")
                if not pl:
                    nm = re.sub(r"(?i)\b(court ?house|courthouse|law courts?|supreme|district|county|local|magistrates?'?s?|court|building|of|the|new south wales|victoria|queensland|family|federal|circuit|old|historic)\b", " ", r["name"]); pl, meth = match_place(nm.strip(), "AU")
                r["place_ids"] = pl; r["place_match_method"] = meth
            if r["parent_court_id"] is None: r["parent_court_id"] = body_for(r["name"], r["subdivision"])
            if r["level"] == "other" and r["parent_court_id"]:
                p = r["parent_court_id"]; r["level"] = {"au-hca": "supreme", "au-fca": "federal_district", "au-fcfcoa": "family"}.get(p) or ("supreme" if p.endswith("supreme-court") else "trial_general" if p.endswith("intermediate-court") else "trial_limited")
            r["court_system"] = "federal" if r["parent_court_id"] in ("au-hca", "au-fca", "au-fcfcoa") else "territorial" if r["subdivision"] in ("AU-NT", "AU-ACT") else "state"
        if r["subdivision"] and r["subdivision"].startswith("AU-"):
            sp = subdivision_place("AU", ST.get(r["subdivision"][3:], ("",))[0])
            if sp and sp not in r["place_ids"]: r["place_ids"] = r["place_ids"] + [sp]
    wjl(f"{ROOT}/data/au/au_courthouses.jsonl", rows)
    ch = [r for r in rows if r["record_type"] == "courthouse"]
    print("AU total", len(rows), "courthouses", len(ch), "geo", sum(1 for r in ch if r["geo"]["lat"] is not None), "place_ids", sum(1 for r in ch if r["place_ids"]), "parent", sum(1 for r in ch if r["parent_court_id"]), collections.Counter(r["source_kind"] for r in ch), collections.Counter(r["subdivision"] for r in ch).most_common(12))
if __name__ == "__main__": build()
