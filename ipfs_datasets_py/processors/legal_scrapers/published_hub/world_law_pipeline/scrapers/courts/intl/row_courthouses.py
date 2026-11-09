"""Rest-of-world courthouse + court_body builder (phase 7). Usage: row_courthouses.py CC  -> data/<cc>/<cc>_courthouses.jsonl
Sources: official finder / upstream endomorphosis datasets (NZ ipfs_newzealand_courts, BR ipfs_brazil_courts: imported with their court_id and licence, not re-scraped),
OSM amenity=courthouse (ODbL), Wikidata courthouses (CC0); GeoNames cities500 (CC-BY 4.0) for nearest-city place matching."""
import sys, json, collections, hashlib
def hashlib_sha(x): return hashlib.sha1(x.encode()).hexdigest()[:8]
sys.path.insert(0, "/workspace/world_courts/scrapers/courts/intl")
from row_common import *
import pandas as pd
RD = f"{ROOT}/data/row"
def body(cc, bid, name, level, parent, system="national", name_local=None, sub=None, url=None, pol="robots_unknown:reference", lic="CC0-1.0 (compiled structure)", notes=None, **kw):
    return rec(record_note=notes, court_id=f"{cc.lower()}-{bid}", record_type="court_body", name=name, name_local=name_local, level=level, court_system=system, country_code=cc, subdivision=sub or cc,
               parent_court_id=f"{cc.lower()}-{parent}" if parent else None, source_url=url, source_kind="reference", site_policy=pol, license=lic, **kw)
def osm_rows(cc):
    out = []
    for l in rjl(f"{RD}/osm_{cc}.jsonl"):
        nm = l.get("name") or l.get("name_local") or "Courthouse"
        out.append(rec(court_id=f"osm:{l['osm_id']}", name=nm, name_local=l.get("name_local"), country_code=cc, subdivision=cc, address={"street": l.get("street"), "city": l.get("city"), "postcode": l.get("postcode"), "region": l.get("region"), "country": cc},
                       geo={"lat": l["lat"], "lon": l["lon"]}, phone=l.get("phone"), website=l.get("website"), wikidata=l.get("wikidata"), source_url=f"https://www.openstreetmap.org/{l['osm_id']}", source_kind="osm",
                       site_policy="open_license:ODbL", license="ODbL-1.0", geo_source="osm", retrieved_at=l.get("retrieved_at") or NOW()))
    return out
def wd_rows(cc):
    out = []
    for l in rjl(f"{RD}/wd_{cc}.jsonl"):
        if l.get("lat") is None: continue
        out.append(rec(court_id=f"wd:{l['wikidata']}", name=l["name"], country_code=cc, subdivision=cc, wikidata=l["wikidata"], address={"street": l.get("street"), "city": l.get("city"), "postcode": l.get("postcode"), "region": None, "country": cc},
                       geo={"lat": l["lat"], "lon": l["lon"]}, phone=l.get("phone"), website=l.get("website"), source_url=f"https://www.wikidata.org/wiki/{l['wikidata']}", source_kind="wikidata",
                       site_policy="open_license:CC0", license="CC0-1.0", geo_source="wikidata", admin_qid=l.get("admin_qid"), geoname_ids=l.get("geonames") or []))
    return out
ADMIN2_FIRST = {"NZ", "ZA", "IN"}
def assign_places(rows, cc, extra_state=None):
    """place_ids: Wikidata P131 admin qid -> GM; else city/locality name; else GeoNames nearest city name (<=25 km); state place appended if known."""
    stats = collections.Counter()
    for r in rows:
        if r["record_type"] != "courthouse" or r.get("place_ids"): continue
        pl = []; meth = None
        if r.get("admin_qid"):
            p = qplace(r["admin_qid"], cc)
            if p: pl.append(p); meth = "wikidata_p131"
        if not pl and r["address"].get("city") and cc not in ADMIN2_FIRST:
            pl = rmatch([r["address"]["city"]], cc)
            if pl: meth = "name"
        c = None
        if r["geo"]["lat"] is not None:
            c = nearest_city(r["geo"]["lat"], r["geo"]["lon"], cc)
            if c:
                r["geonames_city"] = c[2]; r["geonames_admin1"] = c[3]; a2 = gn_admin2(cc).get(f"{c[3]}.{c[6]}"); r["geonames_admin2"] = a2
                if not r["address"].get("city"): r["address"]["city"] = c[2]
                if not pl:
                    pl = rmatch([a2, c[2]] if cc in ADMIN2_FIRST else [c[2], a2], cc)
                    if pl: meth = "geonames_nearest_city_admin2_name"
        if not pl and r["address"].get("city"):
            pl = rmatch([r["address"]["city"]], cc)
            if pl: meth = "name"
        if not pl and r["name"]:
            nm = re.sub(r"(?i)\b(court ?house|courthouse|court|tribunal|high|supreme|district|family|youth|magistrates?'?s?|sessions|civil|criminal|registry|forum|f[oó]rum|juzgado|tribunal|palacio de justicia|ciudad judicial)\b", " ", r["name"]); nm = nm.strip()
            if nm:
                pl = rmatch([nm], cc)
                if pl: meth = "name_in_court_name"
        if pl: r["place_ids"] = pl; r["place_match_method"] = meth; stats[meth] += 1
        else: stats["none"] += 1
    return stats
def finish(cc, rows):
    ch = [r for r in rows if r["record_type"] == "courthouse"]
    os.makedirs(f"{ROOT}/data/{cc.lower()}", exist_ok=True); wjl(f"{ROOT}/data/{cc.lower()}/{cc.lower()}_courthouses.jsonl", rows)
    st = dict(cc=cc, rows=len(rows), courthouses=len(ch), bodies=len(rows) - len(ch), geo=sum(1 for r in ch if r["geo"]["lat"] is not None), place_ids=sum(1 for r in ch if r["place_ids"]),
              wikidata=sum(1 for r in ch if r.get("wikidata")), parent=sum(1 for r in ch if r["parent_court_id"]), kinds=dict(collections.Counter(r["source_kind"] for r in ch)))
    json.dump(st, open(f"{ROOT}/data/row/build_stats_{cc}.json", "w")); print(st, flush=True)
def merge_sec(prim, sec, dist_m=150):
    out = prim
    for kind in ("osm", "wikidata", None):  # stage-wise so Wikidata rows also dedupe against OSM rows added earlier
        part = [s_ for s_ in sec if (s_.get("source_kind") == kind if kind else s_.get("source_kind") not in ("osm", "wikidata"))]
        if not part: continue
        out, dup, add = merge_dedupe(out, part, dist_m=dist_m); print("merge", kind, "dup", dup, "added", add, flush=True)
    return out
# ---------------------------------------------------------------- NZ
def nz_bodies():
    U = "https://www.courtsofnz.govt.nz/about-the-judiciary/structure-of-the-court-system"
    B = lambda *a, **k: body("NZ", *a, url=U, **k)
    return [B("supreme-court", "Supreme Court of New Zealand", "supreme", None, name_local="Te Kōti Mana Nui"), B("court-of-appeal", "Court of Appeal of New Zealand", "appellate", "supreme-court", name_local="Te Kōti Pīra"),
            B("high-court", "High Court of New Zealand", "trial_general", "court-of-appeal", name_local="Te Kōti Matua"), B("district-court", "District Court of New Zealand", "trial_limited", "high-court", name_local="Te Kōti ā-Rohe"),
            B("family-court", "Family Court of New Zealand", "family", "high-court", name_local="Te Kōti Whānau"), B("youth-court", "Youth Court of New Zealand", "juvenile", "high-court", name_local="Te Kōti Taiohi"),
            B("coroners-court", "Coroners Court of New Zealand", "other", "high-court"), B("environment-court", "Environment Court of New Zealand", "other", "high-court", name_local="Te Kōti Taiao o Aotearoa"),
            B("employment-court", "Employment Court of New Zealand", "other", "court-of-appeal", name_local="Te Kōti Take Ahumahi"), B("employment-relations-authority", "Employment Relations Authority", "other", "employment-court"),
            B("maori-appellate-court", "Māori Appellate Court", "appellate", "court-of-appeal", name_local="Te Kōti Pīra Māori"), B("maori-land-court", "Māori Land Court", "trial_general", "maori-appellate-court", name_local="Te Kōti Whenua Māori"),
            B("disputes-tribunal", "Disputes Tribunals", "trial_limited", "district-court"), B("tenancy-tribunal", "Tenancy Tribunal", "trial_limited", "district-court"),
            B("other-tribunals", "Other tribunals and authorities", "other", "high-court"), B("ministry-offices", "Ministry of Justice offices and services (non-court)", "other", None)]
def nz_body_for(n):
    n = n.lower()
    for k, v in (("supreme court", "supreme-court"), ("court of appeal", "court-of-appeal"), ("high court", "high-court"), ("family court", "family-court"), ("youth court", "youth-court"), ("coroner", "coroners-court"), ("coronial", "coroners-court"),
                 ("environment court", "environment-court"), ("employment court", "employment-court"), ("employment relations", "employment-relations-authority"), ("maori land court", "maori-land-court"), ("māori land court", "maori-land-court"),
                 ("maori appellate", "maori-appellate-court"), ("disputes tribunal", "disputes-tribunal"), ("tenancy tribunal", "tenancy-tribunal"), ("district court", "district-court"),
                 ("public defence", "ministry-offices"), ("legal aid", "ministry-offices"), ("national office", "ministry-offices"), ("complaints review", "ministry-offices"), ("reimbursement scheme", "ministry-offices"), ("tribunal", "other-tribunals"), ("authority", "other-tribunals"), ("commissioner", "other-tribunals")):
        if k in n: return v
    return None
def nz():
    rows = nz_bodies(); now = NOW()
    d = pd.read_parquet(f"{ROOT}/data/ref/hf_intl_nz/data/courts-00000.parquet"); up = []
    for r in d.itertuples():
        bid = nz_body_for(r.name); fk = r.facility_kind
        urls = list(r.urls) if r.urls is not None else []
        up.append(rec(court_id=r.court_id, name=r.name, name_local=r.name_local, official_name=None, level={"supreme": "supreme", "appellate": "appellate", "trial_general": "trial_general", "trial_limited": "trial_limited", "specialized": "other", "administrative": "other"}.get(r.level, "other"),
                      court_system="national", country_code="NZ", subdivision="NZ", parent_court_id=f"nz-{bid}" if bid else None, address={"street": r.address_street if isinstance(r.address_street, str) else None, "city": r.locality if isinstance(r.locality, str) else None, "postcode": r.postcode if isinstance(r.postcode, str) else None, "region": r.region if isinstance(r.region, str) else None, "country": "NZ"},
                      geo={"lat": None if pd.isna(r.lat) else float(r.lat), "lon": None if pd.isna(r.lon) else float(r.lon)}, phone=(list(r.phones)[0] if r.phones is not None and len(r.phones) else None), website=urls[0] if urls else None, source_url=r.source_url, source_kind="official",
                      site_policy="upstream_dataset", license=r.license, geo_source=r.geo_source if isinstance(r.geo_source, str) else None, hours=r.hours if isinstance(r.hours, str) else None, email=r.email_institutional if isinstance(r.email_institutional, str) else None,
                      upstream="endomorphosis/ipfs_newzealand_courts", facility_kind=fk, record_note=None if fk in ("court",) else f"non-court facility kind: {fk} (secondary state body)", retrieved_at=r.source_retrieved_at.isoformat()))
    rows = merge_sec(rows + up, [], 150)
    sec = osm_rows("NZ") + wd_rows("NZ")
    for s in sec:
        if re.search(r"(?i)\b(old|former|historic|museum|heritage)\b", s["name"] or ""): s["needs_review"] = True; s["record_note"] = "name suggests historic/former courthouse; operational status unverified"
        s["parent_court_id"] = (lambda b: f"nz-{b}" if b else None)(nz_body_for(s["name"]))
    rows = merge_sec(rows, sec, 150)
    for r in rows:
        if r["record_type"] == "courthouse":
            r["court_system"] = "national"
            if r["parent_court_id"] is None and r["source_kind"] in ("osm", "wikidata") and re.search(r"(?i)court", r["name"] or ""): r["needs_review"] = True
    print("places", dict(assign_places(rows, "NZ")), flush=True)
    for r in rows:
        if r["record_type"] == "court_body": r["place_ids"] = []
    finish("NZ", rows)
# ---------------------------------------------------------------- IN
IN_HC = {  # slug: (name, seat, [GeoNames admin1 names])
 "allahabad": ("Allahabad High Court", "Prayagraj", ["Uttar Pradesh"]), "andhra-pradesh": ("High Court of Andhra Pradesh", "Amaravati", ["Andhra Pradesh"]),
 "bombay": ("Bombay High Court", "Mumbai", ["Maharashtra", "Goa", "Daman and Diu", "Dadra and Nagar Haveli", "Dadra and Nagar Haveli and Daman and Diu"]), "calcutta": ("Calcutta High Court", "Kolkata", ["West Bengal", "Andaman and Nicobar Islands"]),
 "chhattisgarh": ("Chhattisgarh High Court", "Bilaspur", ["Chhattisgarh"]), "delhi": ("Delhi High Court", "New Delhi", ["NCT", "Delhi", "National Capital Territory of Delhi", "NCT of Delhi"]),
 "gauhati": ("Gauhati High Court", "Guwahati", ["Assam", "Nagaland", "Mizoram", "Arunachal Pradesh"]), "gujarat": ("Gujarat High Court", "Ahmedabad", ["Gujarat"]),
 "himachal-pradesh": ("Himachal Pradesh High Court", "Shimla", ["Himachal Pradesh"]), "jammu-kashmir-ladakh": ("High Court of Jammu & Kashmir and Ladakh", "Srinagar / Jammu", ["Jammu and Kashmir", "Ladakh"]),
 "jharkhand": ("Jharkhand High Court", "Ranchi", ["Jharkhand"]), "karnataka": ("High Court of Karnataka", "Bengaluru", ["Karnataka"]), "kerala": ("High Court of Kerala", "Kochi", ["Kerala", "Lakshadweep"]),
 "madhya-pradesh": ("Madhya Pradesh High Court", "Jabalpur", ["Madhya Pradesh"]), "madras": ("Madras High Court", "Chennai", ["Tamil Nadu", "Puducherry"]), "manipur": ("Manipur High Court", "Imphal", ["Manipur"]),
 "meghalaya": ("Meghalaya High Court", "Shillong", ["Meghalaya"]), "orissa": ("Orissa High Court", "Cuttack", ["Odisha", "Orissa"]), "patna": ("Patna High Court", "Patna", ["Bihar"]),
 "punjab-haryana": ("Punjab and Haryana High Court", "Chandigarh", ["Punjab", "Haryana", "Chandigarh"]), "rajasthan": ("Rajasthan High Court", "Jodhpur", ["Rajasthan"]), "sikkim": ("Sikkim High Court", "Gangtok", ["Sikkim"]),
 "telangana": ("Telangana High Court", "Hyderabad", ["Telangana"]), "tripura": ("Tripura High Court", "Agartala", ["Tripura"]), "uttarakhand": ("Uttarakhand High Court", "Nainital", ["Uttarakhand"])}
IN_STATE_HC = {norm(st): k for k, v in IN_HC.items() for st in v[2]}
def in_bodies():
    U = "https://www.sci.gov.in/"; B = lambda *a, **k: body("IN", *a, url=U, **k)
    out = [B("supreme-court", "Supreme Court of India", "supreme", None)]
    for k, (n, seat, sts) in IN_HC.items():
        out.append(B(f"hc-{k}", n, "appellate", "supreme-court", system="state", sub="IN", notes=f"seat: {seat}; jurisdiction: {', '.join(sts)}"))
        out.append(B(f"dc-{k}", f"District and subordinate courts under the {n}", "trial_general", f"hc-{k}", system="state", notes="district & sessions, civil, family and magistrate courts"))
    return out
def in_hc_for(r):
    a1 = (r.get("geonames_admin1") or ""); nm = gn_admin1("IN").get(a1, ("",))[0]
    k = IN_STATE_HC.get(norm(nm)); return k
def india():
    rows = in_bodies(); sec = osm_rows("IN") + wd_rows("IN")
    assign_places(sec, "IN")   # also fills geonames_admin1
    for s in sec:
        n = (s["name"] or "").lower(); hc = in_hc_for(s)
        if "supreme court" in n and "india" in n: s["parent_court_id"] = "in-supreme-court"; s["level"] = "supreme"
        elif re.search(r"high court|\bhc\b|उच्च न्यायालय", n) and hc: s["parent_court_id"] = f"in-hc-{hc}"; s["level"] = "appellate"
        elif hc: s["parent_court_id"] = f"in-dc-{hc}"; s["level"] = "trial_general"
        s["court_system"] = "national" if s["parent_court_id"] == "in-supreme-court" else "state"
        if not hc and not s["parent_court_id"]: s["needs_review"] = True
    rows = merge_sec(rows, sec, 100)
    for r in rows:
        if r["record_type"] == "court_body": r["place_ids"] = []
    finish("IN", rows)
    # expand the rules crosswalk tier placeholders to concrete body ids
    p = f"{ROOT}/data/in/in_rules_crosswalk.jsonl"
    if os.path.exists(p):
        new = []
        for x in rjl(p):
            if x["court_id"] == "in-high-courts": new += [dict(x, court_id=f"in-hc-{k}") for k in IN_HC]
            elif x["court_id"] == "in-district-courts": new += [dict(x, court_id=f"in-dc-{k}") for k in IN_HC]
            else: new.append(x)
        wjl(p, new)
# ---------------------------------------------------------------- JP
JP_HC = {"sapporo": "札幌", "sendai": "仙台", "tokyo": "東京", "nagoya": "名古屋", "osaka": "大阪", "hiroshima": "広島", "takamatsu": "高松", "fukuoka": "福岡"}
JP_EN = {"sapporo": "Sapporo", "sendai": "Sendai", "tokyo": "Tokyo", "nagoya": "Nagoya", "osaka": "Osaka", "hiroshima": "Hiroshima", "takamatsu": "Takamatsu", "fukuoka": "Fukuoka"}
JP_CIRCUIT = {}
for _c, _l in {"sapporo": ["01"], "sendai": ["02", "03", "04", "05", "06", "07"], "tokyo": ["08", "09", "10", "11", "12", "13", "14", "15", "19", "20", "22"], "nagoya": ["16", "17", "18", "21", "23", "24"],
               "osaka": ["25", "26", "27", "28", "29", "30"], "hiroshima": ["31", "32", "33", "34", "35"], "takamatsu": ["36", "37", "38", "39"], "fukuoka": ["40", "41", "42", "43", "44", "45", "46", "47"]}.items():
    for _x in _l: JP_CIRCUIT[_x] = _c
def jp_bodies():
    U = "https://www.courts.go.jp/courthouse/map/index.html"; B = lambda *a, **k: body("JP", *a, url=U, pol="robots_allowed", lic="Supreme Court of Japan (courts.go.jp) published structure; reuse per site terms", **k)
    out = [B("supreme-court", "Supreme Court of Japan", "supreme", None, name_local="最高裁判所")]
    for k, n in JP_HC.items():
        out.append(B(f"hc-{k}", f"{JP_EN[k]} High Court", "appellate", "supreme-court", name_local=f"{n}高等裁判所", notes="High Court circuit"))
        out.append(B(f"dc-{k}", f"District Courts of the {JP_EN[k]} High Court circuit", "trial_general", f"hc-{k}", name_local=f"{n}高等裁判所管内の地方裁判所"))
        out.append(B(f"fc-{k}", f"Family Courts of the {JP_EN[k]} High Court circuit", "family", f"hc-{k}", name_local=f"{n}高等裁判所管内の家庭裁判所"))
        out.append(B(f"sc-{k}", f"Summary Courts of the {JP_EN[k]} High Court circuit", "trial_limited", f"dc-{k}", name_local=f"{n}高等裁判所管内の簡易裁判所"))
    out.append(B("ip-high-court", "Intellectual Property High Court", "appellate", "hc-tokyo", name_local="知的財産高等裁判所"))
    # national tier aliases used by the rules crosswalk (jp-high, jp-district, jp-family, jp-summary)
    out += [B("high", "High Courts of Japan (8 circuits + IP High Court)", "appellate", "supreme-court", name_local="高等裁判所"), B("district", "District Courts of Japan", "trial_general", "high", name_local="地方裁判所"),
            B("family", "Family Courts of Japan", "family", "high", name_local="家庭裁判所"), B("summary", "Summary Courts of Japan", "trial_limited", "district", name_local="簡易裁判所")]
    return out
def jp_kind(names):
    j = " ".join(names)
    if "知的財産高等裁判所" in j or "Intellectual Property High" in j: return "ip-high-court"
    if "高等裁判所" in j or "High Court" in j: return "hc"
    if "地方裁判所" in j or "District Court" in j: return "dc"
    if "家庭裁判所" in j or "Family Court" in j: return "fc"
    if "簡易裁判所" in j or "Summary Court" in j: return "sc"
    return "dc"
def jp_geocode(r):
    a = r["address"]["street"]; 
    g = nominatim(a, "JP")
    if g: return g, "nominatim(OSM) geocode of official address"
    m = re.match(r"(.+?[都道府県])(.+?(?:郡.+?[町村]|[市区町村]))", a)
    if m:
        g = nominatim(m.group(1) + m.group(2), "JP")
        if g: return g, "nominatim(OSM) municipality centroid of official address (municipality precision)"
    return None, None
def japan():
    rows = jp_bodies(); off = rjl(f"{RD}/jp_official.jsonl"); osm = osm_rows("JP"); wd = wd_rows("JP"); used = set(); ch = []
    def cname(n): return re.sub(r"\s+", "", n)
    for o in off:
        names = [cname(n) for n in o["names"] if cname(n) not in ("地図表示",)]
        k = jp_kind(names); circ = o["circuit"]
        parent = "jp-ip-high-court" if k == "ip-high-court" else f"jp-{k}-{circ}"
        ch.append(rec(court_id=f"jp-moj-{o['slug']}-{hashlib_sha(o['postcode']+o['address']+'|'.join(names))}", name=" / ".join(names), name_local=" / ".join(names), level={"hc": "appellate", "ip-high-court": "appellate", "dc": "trial_general", "fc": "family", "sc": "trial_limited"}[k],
                      court_system="national", country_code="JP", subdivision="JP", parent_court_id=parent, address={"street": o["address"], "city": None, "postcode": o["postcode"], "region": None, "country": "JP"}, geo={"lat": None, "lon": None}, phone=o.get("phone"),
                      source_url=o["source_url"], source_kind="official", site_policy=o["site_policy"], license="Supreme Court of Japan (courts.go.jp) published court locations; reuse per site terms",
                      record_note=("hosts several courts: " + "; ".join(names)) if len(names) > 1 else None, high_court_circuit=circ, _names=names))
    # geo: match OSM rows by court name
    for r in ch:
        for l in osm:
            if l["court_id"] in used or not l.get("name"): continue
            n = cname(l["name"])
            if n in r["_names"] or any(len(n) >= 6 and (n in x or x in n) for x in r["_names"]):
                r["geo"] = dict(l["geo"]); r["geo_source"] = "osm (matched by court name; building precision)"; r["wikidata"] = r.get("wikidata") or l.get("wikidata"); used.add(l["court_id"])
                r["sources"].append({"source_url": l["source_url"], "site_policy": l["site_policy"], "source_kind": "osm"}); break
    todo = [r for r in ch if r["geo"]["lat"] is None]; print("official", len(ch), "osm-matched", len(ch) - len(todo), "to geocode", len(todo), flush=True)
    for r in todo:
        g, how = jp_geocode(r)
        if g: r["geo"] = {"lat": g[0], "lon": g[1]}; r["geo_source"] = how
    nominatim_flush()
    for r in ch: r.pop("_names", None)
    sec = [l for l in osm if l["court_id"] not in used] + wd
    for s in sec:
        s["name_local"] = s["name_local"] or s["name"]; k = jp_kind([s["name"] or ""]) if re.search("裁判所", s["name"] or "") else None
        s["parent_court_id"] = None
    rows = merge_sec(rows + ch, sec, 120)
    print("places", dict(assign_places(rows, "JP")), flush=True)
    for r in rows:
        if r["record_type"] != "courthouse": continue
        a1 = r.get("geonames_admin1")
        if a1:
            nm = gn_admin1("JP").get(a1)
            if nm:
                r["subdivision"] = f"JP-{a1}"; sp = state_place(nm[0], "JP")
                if sp and sp not in r["place_ids"]: r["place_ids"] = r["place_ids"] + [sp]
        if r["parent_court_id"] is None and r["source_kind"] in ("osm", "wikidata"):
            nm = r["name"] or ""; circ = JP_CIRCUIT.get(a1 or "")
            if re.search("法務局|検察|Prosecut|Marshall|Legal Affairs|Bureau|Training", nm):
                r["needs_review"] = True; r["record_note"] = (r.get("record_note") or "") + " not a court (prosecution/legal-affairs/training facility); kept for review only"
            elif nm.strip() in ("Supreme Court", "最高裁判所") or "Supreme Court of Japan" in nm:
                r["parent_court_id"] = "jp-supreme-court"; r["level"] = "supreme"
            elif re.search("裁判所|High Court|District Court|Family Court|Summary Court", nm) and circ:
                k = jp_kind([nm]); r["parent_court_id"] = "jp-ip-high-court" if k == "ip-high-court" else f"jp-{k}-{circ}"; r["level"] = {"hc": "appellate", "ip-high-court": "appellate", "dc": "trial_general", "fc": "family", "sc": "trial_limited"}[k]
                r["record_note"] = (r.get("record_note") or "") + " OSM/Wikidata courthouse not in the official location list; tier from name keywords"
            else:
                r["needs_review"] = True; r["record_note"] = (r.get("record_note") or "") + " osm/wikidata-only courthouse, court type not classified"
    for r in rows:
        if r["record_type"] == "court_body": r["place_ids"] = []
    finish("JP", rows)
# ---------------------------------------------------------------- ZA
ZA_PROV = {"Eastern Cape": ("ec", "ZA-EC", "High Court of South Africa, Eastern Cape Division (Makhanda; local divisions Bhisho, Mthatha, Gqeberha)"), "Free State": ("fs", "ZA-FS", "High Court of South Africa, Free State Division (Bloemfontein)"),
 "Gauteng": ("gp", "ZA-GT", "High Court of South Africa, Gauteng Division, Pretoria and Gauteng Local Division, Johannesburg"), "KwaZulu-Natal": ("kzn", "ZA-NL", "High Court of South Africa, KwaZulu-Natal Division, Pietermaritzburg and Local Division, Durban"),
 "Limpopo": ("lp", "ZA-LP", "High Court of South Africa, Limpopo Division (Polokwane) and Local Division (Thohoyandou)"), "Mpumalanga": ("mp", "ZA-MP", "High Court of South Africa, Mpumalanga Division (Mbombela; Middelburg)"),
 "Northern Cape": ("nc", "ZA-NC", "High Court of South Africa, Northern Cape Division (Kimberley)"), "North West": ("nw", "ZA-NW", "High Court of South Africa, North West Division (Mahikeng)"),
 "Western Cape": ("wc", "ZA-WC", "High Court of South Africa, Western Cape Division (Cape Town)")}
def za_bodies():
    U = "https://www.justice.gov.za/about/sa-courts.html"; B = lambda *a, **k: body("ZA", *a, url=U, pol="robots_unknown:reference", **k)
    out = [B("constitutional-court", "Constitutional Court of South Africa", "supreme", None), B("supreme-court-of-appeal", "Supreme Court of Appeal of South Africa", "appellate", "constitutional-court"),
           B("labour-appeal-court", "Labour Appeal Court", "appellate", "supreme-court-of-appeal"), B("labour-court", "Labour Court", "other", "labour-appeal-court"), B("land-claims-court", "Land Claims Court", "other", "supreme-court-of-appeal"),
           B("competition-appeal-court", "Competition Appeal Court", "other", "supreme-court-of-appeal"), B("electoral-court", "Electoral Court", "other", "supreme-court-of-appeal"), B("high-court", "High Court of South Africa (all divisions)", "trial_general", "supreme-court-of-appeal"),
           B("magistrates-courts", "Magistrates' Courts of South Africa (all)", "trial_limited", "high-court"), B("small-claims-courts", "Small Claims Courts", "trial_limited", "magistrates-courts")]
    for nm, (k, iso, hcn) in ZA_PROV.items():
        out.append(B(f"hc-{k}", hcn, "trial_general", "high-court", system="provincial", sub=iso))
        out.append(B(f"mc-{k}", f"Magistrates' Courts, {nm}", "trial_limited", f"hc-{k}", system="provincial", sub=iso))
    return out
def za_class(n):
    n = (n or "").lower()
    for k, v in (("constitutional court", "constitutional-court"), ("supreme court of appeal", "supreme-court-of-appeal"), ("labour appeal", "labour-appeal-court"), ("labour court", "labour-court"), ("land claims", "land-claims-court"), ("competition appeal", "competition-appeal-court"),
                 ("electoral court", "electoral-court"), ("small claims", "small-claims-courts"), ("high court", "hc"), ("magistrate", "mc"), ("regional court", "mc"), ("court", "mc")):
        if k in n: return v
def south_africa():
    import openpyxl
    rows = za_bodies(); wb = openpyxl.load_workbook(f"{ROOT}/rules/raw/za/LowerCourts.xlsx", read_only=True); L = list(wb.worksheets[0].iter_rows(values_only=True)); h = L[0]; ch = []
    src = "https://www.justice.gov.za/contact/lowercourts_full.html"
    for r in L[1:]:
        if not r[0]: continue
        d = dict(zip(h, r)); prov = d["Province"]; k, iso, _ = ZA_PROV[prov]
        try: la, lo = [float(x) for x in re.split(r"[;,]", d["GPS [S;E]"])]
        except Exception: la = lo = None
        phys = (d["Physical"] or "").strip(); pcm = re.search(r"(\d{4})\s*$", phys); city = d["Office"]
        pl = rmatch([d["Municipality"]], "ZA", states_ok=False) if d.get("Municipality") else []
        sp = state_place(prov, "ZA")
        ch.append(rec(court_id=f"za-doj-{slug(prov)}-{slug(d['CourtType'])}-{slug(d['Office'])}", name=f"{d['Office']} {d['CourtType']}", name_local=None, level="trial_limited", court_system="provincial", country_code="ZA", subdivision=iso, parent_court_id=f"za-mc-{k}",
                      address={"street": phys or None, "city": city, "postcode": pcm.group(1) if pcm else None, "region": prov, "country": "ZA"}, geo={"lat": la, "lon": lo}, phone=(d["Tel"] or None), website=None,
                      place_ids=pl + ([sp] if sp else []), place_match_method="official_municipality_name" if pl else None, source_url=src, source_kind="official", site_policy="robots_unknown:fetched_ok",
                      license="Department of Justice and Constitutional Development (South Africa) published court list; GODL-style public information, reuse per site terms", geo_source="official court list GPS",
                      hours=(d["Hours"] or None), court_type_official=d["CourtType"], also_known_as=d["Other Names"], places_of_sitting=d["Places of Sitting"], services=d["Services"], municipality=d["Municipality"], mag_district=d["MagDistrict"], small_claims=d["SCC"], equality_court=d["EQC"]))
    sec = osm_rows("ZA") + wd_rows("ZA")
    lab = [(r["geo"]["lat"], r["geo"]["lon"], r["subdivision"]) for r in ch if r["geo"]["lat"] is not None]
    for s_ in sec:
        c = za_class(s_["name"]); g = s_["geo"]
        if lab:
            b = min(lab, key=lambda x: haversine((x[0], x[1]), (g["lat"], g["lon"])))
            if haversine((b[0], b[1]), (g["lat"], g["lon"])) < 150000:
                s_["subdivision"] = b[2]; pk = next(v[0] for v in ZA_PROV.values() if v[1] == b[2])
                s_["parent_court_id"] = f"za-hc-{pk}" if c == "hc" else f"za-mc-{pk}" if c == "mc" else (f"za-{c}" if c else None)
        if c in ("constitutional-court", "supreme-court-of-appeal", "labour-appeal-court", "labour-court", "land-claims-court", "competition-appeal-court", "electoral-court"): s_["parent_court_id"] = f"za-{c}"
        if c == "small-claims-courts": s_["parent_court_id"] = s_["parent_court_id"] or "za-small-claims-courts"
        s_["level"] = {"hc": "trial_general", "mc": "trial_limited", "constitutional-court": "supreme", "supreme-court-of-appeal": "appellate"}.get(c, "other")
        if not s_["parent_court_id"]: s_["needs_review"] = True
    rows = merge_sec(rows + ch, sec, 150)
    print("places", dict(assign_places(rows, "ZA")), flush=True)
    for r in rows:
        if r["record_type"] == "court_body": r["place_ids"] = []
    finish("ZA", rows)
# ---------------------------------------------------------------- BR
BR_UF = {"01": "AC", "02": "AL", "03": "AP", "04": "AM", "05": "BA", "06": "CE", "07": "DF", "08": "ES", "29": "GO", "13": "MA", "11": "MS", "14": "MT", "15": "MG", "16": "PA", "17": "PB", "18": "PR", "30": "PE", "20": "PI", "21": "RJ", "22": "RN", "23": "RS", "24": "RO", "25": "RR", "26": "SC", "27": "SP", "28": "SE", "31": "TO"}
BR_TRF = {"1": "AC AM AP BA DF GO MA MT PA PI RO RR TO", "2": "RJ ES", "3": "SP MS", "4": "RS SC PR", "5": "AL CE PB PE RN SE", "6": "MG"}
BR_TRF_OF = {u: k for k, v in BR_TRF.items() for u in v.split()}
BR_TRT = {"1": "RJ", "3": "MG", "4": "RS", "5": "BA", "6": "PE", "7": "CE", "8": "PA AP", "9": "PR", "10": "DF TO", "11": "AM RR", "12": "SC", "13": "PB", "14": "RO AC", "16": "MA", "17": "ES", "18": "GO", "19": "AL", "20": "SE", "21": "RN", "22": "PI", "23": "MT", "24": "MS"}
BR_TRT_OF = {u: k for k, v in BR_TRT.items() for u in v.split()}
BR_NOT_COURT = re.compile(r"(?i)minist[eé]rio p[uú]blico|promotoria|procuradoria|procon|defensoria|cart[oó]rio|c[aâ]mara|inss|tribunal de contas|n[uú]cleo de pr[aá]tica|registry|registration|prosecutor|delegacia|pol[ií]cia|prefeitura|ouvidoria|conselho tutelar|escola|faculdade|universidade")
def br_bodies():
    d = pd.read_parquet(f"{ROOT}/data/ref/hf_intl_br/data/courts-00000.parquet"); out = []
    for r in d.itertuples():
        urls = list(r.urls) if r.urls is not None else []
        par = r.parent_court_id if isinstance(r.parent_court_id, str) else None
        cid = r.court_id
        m = re.match(r"br-national-appellate-(trf\d+)$", cid) or re.match(r"br-[a-z]{2}-appellate-(tj[a-z]{2}|tjdft)$", cid)
        if m and cid.startswith("br-national-appellate-trf") or (m and "-tj" in cid): par = "br-national-supreme-stj"
        if re.match(r"br-national-appellate-trt\d+$", cid): par = "br-national-supreme-tst"
        if re.search(r"-appellate-tre-", cid): par = "br-national-supreme-tse"
        if re.match(r"br-national-supreme-(stj|tst|tse|stm)$", cid): par = "br-national-supreme-stf"
        out.append(rec(court_id=cid, record_type="court_body", name=r.name, name_local=r.name_local, level=r.level, court_system="national" if "-national-" in cid else "state", country_code="BR", subdivision=("BR-" + cid.split("-")[1].upper()) if re.match(r"br-[a-z]{2}-", cid) else "BR",
                       parent_court_id=par, website=urls[0] if urls else None, source_url=r.source_url, source_kind="reference", site_policy="upstream_dataset", license=r.license, upstream="endomorphosis/ipfs_brazil_courts", record_note=f"imported from upstream (CNJ structure); court_type={r.court_type}", retrieved_at=r.source_retrieved_at.isoformat()))
    out.append(rec(court_id="br-national-supreme-stf", record_type="court_body", name="Supremo Tribunal Federal", name_local="Supremo Tribunal Federal", level="supreme", court_system="national", country_code="BR", subdivision="BR", parent_court_id=None,
                   website="https://portal.stf.jus.br/", source_url="https://portal.stf.jus.br/", source_kind="reference", site_policy="robots_unknown:reference", license="CC0-1.0 (compiled structure)", record_note="added: apex court (CF/88 art. 101); absent from upstream CNJ list"))
    return out
def br_class(name, uf):
    n = (name or "").lower()
    if not n: return None
    if re.search(r"trabalh|\btrt\b|trabalhista", n): k = BR_TRT_OF.get(uf); return f"br-national-appellate-trt{k}" if k else None
    if re.search(r"eleitor|\btre\b|cart[oó]rio eleitoral", n): return f"br-{uf.lower()}-appellate-tre-{uf.lower()}"
    if "milit" in n: return "br-national-supreme-stm"
    if re.search(r"federal|\btrf\b", n): k = BR_TRF_OF.get(uf); return f"br-national-appellate-trf{k}" if k else None
    if re.search(r"f[oó]rum|juizado|vara|comarca|tribunal de justi|\btj[a-z]{2}\b|court of justice|poder judici|justi[cç]a estadual|j[uú]ri|palacio|pal[aá]cio|centro judici", n):
        return "br-df-appellate-tjdft" if uf == "DF" else f"br-{uf.lower()}-appellate-tj{uf.lower()}"
    return None
def brazil():
    rows = br_bodies(); ids = {r["court_id"] for r in rows}
    sec = osm_rows("BR") + wd_rows("BR"); keep = []; drop = 0
    for s_ in sec:
        if BR_NOT_COURT.search(s_["name"] or ""): drop += 1; continue
        g = s_["geo"]; c = nearest_city(g["lat"], g["lon"], "BR") if g["lat"] is not None else None
        uf = BR_UF.get(c[3]) if c else None
        if uf: s_["subdivision"] = f"BR-{uf}"
        if s_["name"] == "Courthouse": s_["name"] = "Fórum (unnamed OSM courthouse)"; s_["needs_review"] = True; s_["record_note"] = "OSM courthouse without name"
        par = br_class(s_["name"], uf) if uf else None
        if par in ids: s_["parent_court_id"] = par
        elif par: s_["parent_court_id"] = None; s_["needs_review"] = True; s_["record_note"] = (s_.get("record_note") or "") + f" parent body {par} not in CNJ list"
        else: s_["needs_review"] = True; s_["record_note"] = (s_.get("record_note") or "") + " court branch not classifiable from name"
        s_["court_system"] = "state" if par and "-appellate-tj" in par else "national"
        keep.append(s_)
    print("non-court OSM rows dropped", drop, flush=True)
    rows = merge_sec(rows, keep, 120)
    print("places", dict(assign_places(rows, "BR")), flush=True)
    for r in rows:
        if r["record_type"] == "court_body": r["place_ids"] = []
    finish("BR", rows)
# ---------------------------------------------------------------- MX
MX_ISO = {"01": "AGU", "02": "BCN", "03": "BCS", "04": "CAM", "05": "CHP", "06": "CHH", "07": "COA", "08": "COL", "09": "CMX", "10": "DUR", "11": "GUA", "12": "GRO", "13": "HID", "14": "JAL", "15": "MEX", "16": "MIC", "17": "MOR", "18": "NAY", "19": "NLE", "20": "OAX",
          "21": "PUE", "22": "QUE", "23": "ROO", "24": "SLP", "25": "SIN", "26": "SON", "27": "TAB", "28": "TAM", "29": "TLA", "30": "VER", "31": "YUC", "32": "ZAC"}
MX_NOT_COURT = re.compile(r"(?i)fiscal[ií]a|procuradur|\bpgr\b|\bpgje\b|registro civil|defensor[ií]a|alcald[ií]a|delegaci[oó]n|el torito|^casa$|ejemplo|empleo|abogado|ministerio p[uú]blico|polic[ií]a|ayuntamiento|presidencia municipal|notar[ií]a|\bdif\b")
def mx_bodies():
    U = "https://www.scjn.gob.mx/"; B = lambda *a, **k: body("MX", *a, url=U, pol="robots_unknown:reference", **k)
    out = [B("scjn", "Suprema Corte de Justicia de la Nación", "supreme", None, name_local="Suprema Corte de Justicia de la Nación"), B("tribunal-disciplina-judicial", "Tribunal de Disciplina Judicial", "other", None), B("organo-administracion-judicial", "Órgano de Administración Judicial", "other", None),
           B("tepjf", "Tribunal Electoral del Poder Judicial de la Federación", "appellate", "scjn", system="national"), B("tribunales-colegiados", "Tribunales Colegiados de Circuito", "appellate", "scjn"), B("tribunales-unitarios", "Tribunales Unitarios de Circuito", "appellate", "scjn"),
           B("juzgados-distrito", "Juzgados de Distrito", "trial_general", "tribunales-colegiados"), B("tribunales-agrarios", "Tribunales Agrarios", "other", None), B("tfja", "Tribunal Federal de Justicia Administrativa", "other", None)]
    for c, iso in MX_ISO.items():
        nm = gn_admin1("MX")[c][0]
        out.append(B(f"tsj-{iso.lower()}", f"Poder Judicial del Estado de {nm} (Tribunal Superior de Justicia)", "appellate", None, system="state", sub=f"MX-{iso}"))
    return out
def mx_class(n, iso):
    n = (n or "").lower()
    if re.search(r"suprema corte", n): return "mx-scjn"
    if re.search(r"tribunal electoral", n): return "mx-tepjf"
    if re.search(r"unitario agrario|tribunal agrario", n): return "mx-tribunales-agrarios"
    if re.search(r"federal de justicia administrativa", n): return "mx-tfja"
    if re.search(r"colegiado", n): return "mx-tribunales-colegiados"
    if re.search(r"unitario de circuito", n): return "mx-tribunales-unitarios"
    if re.search(r"de distrito|federaci[oó]n|federal|circuito|judicatura federal", n): return "mx-juzgados-distrito"
    if re.search(r"c[ií]vico", n): return None
    if re.search(r"juzgado|juez|tribunal|palacio de justicia|ciudad judicial|casa de justicia|centro de justicia|poder judicial|sala de juicios|justicia|salas|cejum", n) and iso: return f"mx-tsj-{iso.lower()}"
    return None
def mexico():
    rows = mx_bodies(); ids = {r["court_id"] for r in rows}
    sec = osm_rows("MX") + wd_rows("MX"); keep = []; drop = 0
    for s_ in sec:
        if MX_NOT_COURT.search(s_["name"] or ""): drop += 1; continue
        g = s_["geo"]; c = nearest_city(g["lat"], g["lon"], "MX") if g["lat"] is not None else None
        iso = MX_ISO.get(c[3]) if c else None
        if iso: s_["subdivision"] = f"MX-{iso}"
        if s_["name"] == "Courthouse": s_["name"] = "Juzgado (unnamed OSM courthouse)"; s_["needs_review"] = True; s_["record_note"] = "OSM courthouse without name"
        par = mx_class(s_["name"], iso)
        if par in ids: s_["parent_court_id"] = par
        else:
            s_["needs_review"] = True; s_["record_note"] = (s_.get("record_note") or "") + (" municipal civic court (juzgado cívico); not part of the state judiciary" if re.search(r"(?i)c[ií]vico", s_["name"] or "") else " court branch not classifiable from name")
        s_["court_system"] = "state" if par and "-tsj-" in par else "national" if par else "state"
        keep.append(s_)
    print("non-court rows dropped", drop, flush=True)
    rows = merge_sec(rows, keep, 120)
    print("places", dict(assign_places(rows, "MX")), flush=True)
    for r in rows:
        if r["record_type"] == "court_body": r["place_ids"] = []
        elif r.get("subdivision", "").startswith("MX-"):
            nm = gn_admin1("MX").get(next((k for k, v in MX_ISO.items() if "MX-" + v == r["subdivision"]), ""))
            sp = state_place(nm[0], "MX") if nm else None
            if sp and sp not in r["place_ids"]: r["place_ids"] = r["place_ids"] + [sp]
    finish("MX", rows)
BUILD = {"NZ": nz, "IN": india, "JP": japan, "ZA": south_africa, "BR": brazil, "MX": mexico}
if __name__ == "__main__":
    for cc in sys.argv[1:]: BUILD[cc]()
