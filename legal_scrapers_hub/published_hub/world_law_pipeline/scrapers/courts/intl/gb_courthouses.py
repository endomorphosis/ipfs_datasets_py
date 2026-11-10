"""Build data/gb/gb_courthouses.jsonl : FaCT (via ipfs_uk_courts, OGL) + SCTS + NI + UKSC + OSM + Wikidata, with court-body hierarchy and place_ids."""
import sys, glob
sys.path.insert(0, "/workspace/world_courts/scrapers/courts/intl"); sys.path.insert(0, "/workspace/world_courts/scrapers/courts/rules")
from courts_common import *
import pandas as pd
from rules_common import RAW, html_text
J = "https://www.judiciary.uk/about-the-judiciary/our-justice-system/court-structure/"
BODIES = [  # id, name, level, parent, subdivision, source
 ("gb-uksc", "Supreme Court of the United Kingdom", "supreme", None, "GB", "https://www.supremecourt.uk/"),
 ("gb-jcpc", "Judicial Committee of the Privy Council", "appellate", None, "GB", "https://www.jcpc.uk/"),
 ("gb-ew-court-of-appeal", "Court of Appeal (England and Wales)", "appellate", "gb-uksc", "GB-EAW", J),
 ("gb-ew-high-court", "High Court of Justice (England and Wales)", "trial_general", "gb-ew-court-of-appeal", "GB-EAW", J),
 ("gb-ew-crown-court", "Crown Court (England and Wales)", "trial_general", "gb-ew-court-of-appeal", "GB-EAW", J),
 ("gb-ew-county-court", "County Court (England and Wales)", "trial_general", "gb-ew-high-court", "GB-EAW", J),
 ("gb-ew-family-court", "Family Court (England and Wales)", "family", "gb-ew-high-court", "GB-EAW", J),
 ("gb-ew-magistrates-court", "Magistrates' Courts (England and Wales)", "trial_limited", "gb-ew-crown-court", "GB-EAW", J),
 ("gb-ew-tribunals-first-tier", "First-tier Tribunals (England and Wales)", "administrative", "gb-ew-tribunals-upper", "GB-EAW", "https://www.judiciary.uk/about-the-judiciary/our-justice-system/jurisdictions/tribunals/"),
 ("gb-ew-tribunals-upper", "Upper Tribunal", "administrative", "gb-ew-court-of-appeal", "GB-EAW", "https://www.judiciary.uk/about-the-judiciary/our-justice-system/jurisdictions/tribunals/"),
 ("gb-ew-employment-tribunal", "Employment Tribunals", "administrative", "gb-ew-employment-appeal-tribunal", "GB-EAW", "https://www.judiciary.uk/about-the-judiciary/our-justice-system/jurisdictions/tribunals/"),
 ("gb-ew-employment-appeal-tribunal", "Employment Appeal Tribunal", "administrative", "gb-ew-court-of-appeal", "GB-EAW", "https://www.judiciary.uk/about-the-judiciary/our-justice-system/jurisdictions/tribunals/"),
 ("gb-sct-court-of-session", "Court of Session", "appellate", "gb-uksc", "GB-SCT", "https://www.scotcourts.gov.uk/courts-and-tribunals/the-supreme-courts/the-court-of-session"),
 ("gb-sct-high-court-justiciary", "High Court of Justiciary", "appellate", "gb-uksc", "GB-SCT", "https://www.scotcourts.gov.uk/courts-and-tribunals/the-supreme-courts/the-high-court-of-justiciary"),
 ("gb-sct-sheriff-appeal-court", "Sheriff Appeal Court", "appellate", "gb-sct-court-of-session", "GB-SCT", "https://www.scotcourts.gov.uk/courts-and-tribunals/appeals-courts"),
 ("gb-sct-sheriff-court", "Sheriff Courts", "trial_general", "gb-sct-sheriff-appeal-court", "GB-SCT", "https://www.scotcourts.gov.uk/courts-and-tribunals/sheriff-and-justice-of-the-peace-courts"),
 ("gb-sct-jp-court", "Justice of the Peace Courts", "trial_limited", "gb-sct-sheriff-appeal-court", "GB-SCT", "https://www.scotcourts.gov.uk/courts-and-tribunals/sheriff-and-justice-of-the-peace-courts"),
 ("gb-sct-tribunals-upper", "Upper Tribunal for Scotland", "administrative", "gb-sct-court-of-session", "GB-SCT", "https://www.scotcourts.gov.uk/courts-and-tribunals/scottish-tribunals"),
 ("gb-sct-tribunals-first-tier", "First-tier Tribunal for Scotland", "administrative", "gb-sct-tribunals-upper", "GB-SCT", "https://www.scotcourts.gov.uk/courts-and-tribunals/scottish-tribunals"),
 ("gb-sct-land-court", "Scottish Land Court", "specialized", "gb-sct-court-of-session", "GB-SCT", "https://www.scotcourts.gov.uk/courts-and-tribunals/courts-tribunals-and-office-locations/find-us/scottish-land-court-and-lands-tribunal-for-scotland"),
 ("gb-ni-court-of-appeal", "Court of Appeal in Northern Ireland", "appellate", "gb-uksc", "GB-NIR", "https://www.judiciaryni.uk/courts"),
 ("gb-ni-high-court", "High Court of Justice in Northern Ireland", "trial_general", "gb-ni-court-of-appeal", "GB-NIR", "https://www.judiciaryni.uk/courts"),
 ("gb-ni-crown-court", "Crown Court (Northern Ireland)", "trial_general", "gb-ni-court-of-appeal", "GB-NIR", "https://www.judiciaryni.uk/courts"),
 ("gb-ni-county-court", "County Courts (Northern Ireland)", "trial_general", "gb-ni-high-court", "GB-NIR", "https://www.judiciaryni.uk/courts"),
 ("gb-ni-magistrates-court", "Magistrates' Courts (Northern Ireland)", "trial_limited", "gb-ni-county-court", "GB-NIR", "https://www.judiciaryni.uk/courts"),
 ("gb-ni-coroners-court", "Coroners Service for Northern Ireland", "other", None, "GB-NIR", "https://www.judiciaryni.uk/courts"),
 ("gb-ni-tribunals", "Tribunals (Northern Ireland)", "administrative", "gb-ni-court-of-appeal", "GB-NIR", "https://www.judiciaryni.uk/courts"),
]
SUBDIV = {"England": "GB-ENG", "Wales": "GB-WLS", "Scotland": "GB-SCT", "Northern Ireland": "GB-NIR"}
BODY = {b[0]: b for b in BODIES}

def body_for(name, sub):
    n = name.lower(); ni = sub == "GB-NIR"; sc = sub == "GB-SCT"
    pre = "gb-ni" if ni else "gb-sct" if sc else "gb-ew"
    if "supreme court" in n and "united kingdom" in n: return "gb-uksc"
    if "employment appeal" in n: return "gb-ew-employment-appeal-tribunal"
    if "employment tribunal" in n: return "gb-ew-employment-tribunal"
    if "upper tribunal" in n: return "gb-sct-tribunals-upper" if sc else "gb-ew-tribunals-upper"
    if "tribunal" in n: return "gb-ni-tribunals" if ni else "gb-sct-tribunals-first-tier" if sc else "gb-ew-tribunals-first-tier"
    if "court of appeal" in n: return f"{pre}-court-of-appeal" if pre != "gb-sct" else "gb-sct-court-of-session"
    if any(k in n for k in ("high court", "royal courts of justice", "administrative court", "business and property", "technology and construction", "chancery", "king's bench", "kings bench", "queen's bench", "planning court", "commercial court", "admiralty")):
        return f"{pre}-high-court" if pre != "gb-sct" else "gb-sct-high-court-justiciary" if "justiciary" in n else "gb-sct-court-of-session"
    if "crown court" in n or "combined court" in n: return f"{pre}-crown-court"
    if "county court" in n or "justice centre" in n or "civil and family" in n: return f"{pre}-county-court"
    if "magistrates" in n: return f"{pre}-magistrates-court"
    if "family court" in n or "family proceedings" in n: return f"{pre}-family-court" if pre == "gb-ew" else f"{pre}-county-court"
    if "sheriff" in n: return "gb-sct-sheriff-court"
    if "central criminal" in n: return "gb-ew-crown-court"
    if "youth court" in n: return f"{pre}-magistrates-court"
    if "sscs" in n or "hearing centre" in n or "appeals" in n: return "gb-ni-tribunals" if ni else "gb-sct-tribunals-first-tier" if sc else "gb-ew-tribunals-first-tier"
    if "court of protection" in n or "family division" in n or "probate" in n: return f"{pre}-high-court" if pre != "gb-sct" else "gb-sct-court-of-session"
    if "law courts" in n or "court house" in n or "courthouse" in n or "family and civil" in n or "justice of the peace" in n:
        return "gb-sct-jp-court" if sc and "peace" in n else f"{pre}-county-court" if pre != "gb-sct" else "gb-sct-sheriff-court"
    if "coroner" in n and ni: return "gb-ni-coroners-court"
    return None

LEVEL = {"gb-uksc": "supreme", "gb-ew-court-of-appeal": "appellate", "gb-ni-court-of-appeal": "appellate", "gb-ew-high-court": "trial_general", "gb-ni-high-court": "trial_general",
         "gb-ew-crown-court": "trial_general", "gb-ni-crown-court": "trial_general", "gb-ew-county-court": "trial_general", "gb-ni-county-court": "trial_general",
         "gb-ew-family-court": "family", "gb-ew-magistrates-court": "trial_limited", "gb-ni-magistrates-court": "trial_limited"}

def build():
    rows = []
    fact = pd.read_parquet(f"{ROOT}/data/ref/hf_intl_uk/data/courts-00000.parquet")
    pcs = set(fact.postcode.dropna())
    # --- Scotland pages
    sc_rows = []
    for u in json.load(open(f"{ROOT}/data/gb/scts_urls.json")):
        k = u.rstrip("/").split("/")[-1]
        try: h = open(f"{RAW}/intl_scts_{k}.html", "rb").read().decode("utf-8", "replace")
        except FileNotFoundError: continue
        t = html_text(h); title = re.sub(r"\s*\|.*$", "", t.splitlines()[0].replace("html ", "", 1)).strip()
        m = re.search(r"\n(?:Postal address|Address)\n((?:[^\n]+\n){1,7}?)([A-Z]{1,2}\d{1,2}[A-Z]? ?\d[A-Z]{2})\n", t)
        if not m: print("no addr", k); continue
        lines = [x.strip() for x in m.group(1).split("\n") if x.strip()]
        pc = m.group(2); street = ", ".join(lines[:-1]) if len(lines) > 1 else None; city = lines[-1] if lines else None
        ph = re.search(r"(0\d{3,4} ?\d{3} ?\d{3,4}|0\d{2} ?\d{4} ?\d{4})", t[m.end():m.end()+800]); ph = ph.group(1) if ph else None
        em = re.search(r"[\w.]+@scotcourts\.gov\.uk", t[m.end():m.end()+1200]); 
        sc_rows.append(dict(k=k, title=title, street=street, city=city, pc=pc, phone=ph, url=u, lines=lines))
        pcs.add(pc)
    # --- NI page
    ni_rows = []
    lines = [l.strip() for l in html_text(open(f"{RAW}/intl_ni_offices.html", "rb").read().decode("utf-8", "replace")).split("\n")]
    for i, l in enumerate(lines):
        if re.fullmatch(r"BT\d{1,2} ?\d[A-Z]{2}", l):
            blk = []; j = i - 1
            while j >= 0 and i - j <= 6 and len(lines[j]) < 70 and not re.match(r"(Phone|Tel|E-?mail|Services)\b", lines[j], re.I) and lines[j]:
                blk.insert(0, lines[j]); j -= 1
            head = next((b for b in blk if re.search(r"Court|Justice|Office|Centre|Commission", b) and not b.lower().startswith("the courthouse")), blk[0] if blk else None)
            if not head: continue
            addr = blk[blk.index(head) + 1:]
            seg = " ".join(lines[i+1:i+6]); ph = re.search(r"(0\d{3} ?\d{3} ?\d{4})", seg)
            ni_rows.append(dict(head=head, street=", ".join(addr[:-1]) or None, city=(addr[-1] if addr else None), pc=l, phone=ph.group(1) if ph else None))
            pcs.add(l)
    pgeo = postcodes_io(pcs); print("postcodes geocoded", len(pgeo), "of", len(pcs), flush=True)
    now = NOW()
    # --- bodies
    for bid, nm, lv, par, sub, src in BODIES:
        rows.append(rec(court_id=bid, record_type="court_body", name=nm, level=lv, court_system="national", country_code="GB", subdivision=sub, parent_court_id=par,
                        source_url=src, source_kind="official", site_policy="robots_allowed", geo={"lat": None, "lon": None}))
    # --- FaCT
    for r in fact.itertuples():
        g = pgeo.get(r.postcode, (None,) * 6) if isinstance(r.postcode, str) else (None,) * 6
        sub = SUBDIV.get(g[3]) or "GB-EAW"
        bd = body_for(r.name, sub); lv = LEVEL.get(bd) or {"administrative": "administrative", "appellate": "appellate", "trial_limited": "trial_limited", "trial_general": "trial_general"}.get(r.level, "other")
        city = r.locality if isinstance(r.locality, str) else None
        pl, meth = match_place(city, "GB", [g[2]] if g[2] else [])
        rows.append(rec(court_id=r.court_id, name=r.name, level=lv, court_system="national", country_code="GB", subdivision=sub, parent_court_id=bd,
                        jurisdiction=r.jurisdiction_name, address={"street": r.address_street, "city": city, "postcode": r.postcode if isinstance(r.postcode, str) else None, "region": g[4], "country": "GB"},
                        geo={"lat": None if pd.isna(r.lat) else float(r.lat), "lon": None if pd.isna(r.lon) else float(r.lon)},
                        phone=(list(r.phones)[0] if r.phones is not None and len(r.phones) else None), website=(list(r.urls)[0] if r.urls is not None and len(r.urls) else None),
                        place_ids=pl, place_match_method=meth, source_url=r.source_url, source_kind="official", site_policy="robots_allowed", retrieved_at=r.source_retrieved_at.isoformat(),
                        license="ogl-3.0", upstream="endomorphosis/ipfs_uk_courts", source_sha256=r.source_sha256, email=r.email_institutional if isinstance(r.email_institutional, str) else None,
                        hours=r.hours if isinstance(r.hours, str) else None, geo_source="GOV.UK FaCT lat/lon"))
        if pd.isna(r.lat) and g[0] is not None:
            rows[-1]["geo"] = {"lat": g[0], "lon": g[1]}; rows[-1]["geo_source"] = "postcodes.io centroid"
    # --- Scotland
    for s in sc_rows:
        g = pgeo.get(s["pc"], (None,) * 6); n = s["title"]; k = s["k"]
        if "high-court" in k and "sheriff" not in k: bd = "gb-sct-high-court-justiciary"
        elif k == "court-of-session": bd = "gb-sct-court-of-session"
        elif k == "sheriff-appeal-court": bd = "gb-sct-sheriff-appeal-court"
        elif k in ("supreme-courts",): bd = "gb-sct-court-of-session"
        elif "tribunals-centre" in k: bd = "gb-sct-tribunals-first-tier"
        elif "land-court" in k: bd = "gb-sct-land-court"
        elif "justice-of-the-peace" in k and "sheriff" not in k: bd = "gb-sct-jp-court"
        elif "sheriff" in k or "justice" in k or "civil" in k or "injury" in k: bd = "gb-sct-sheriff-court"
        else: bd = None
        is_court = bd is not None
        lv = {"gb-sct-court-of-session": "appellate", "gb-sct-high-court-justiciary": "appellate", "gb-sct-sheriff-appeal-court": "appellate", "gb-sct-sheriff-court": "trial_general", "gb-sct-jp-court": "trial_limited",
              "gb-sct-tribunals-first-tier": "administrative", "gb-sct-land-court": "other"}.get(bd, "other")
        pl, meth = match_place(s["city"], "GB", list(reversed(s["lines"][:-1])) + ([g[2]] if g[2] else []))
        pl = pl[:2]
        rows.append(rec(court_id=f"gb-sct-{k}", name=n, level=lv, court_system="national", country_code="GB", subdivision="GB-SCT", parent_court_id=bd,
                        address={"street": s["street"], "city": s["city"], "postcode": s["pc"], "region": g[4], "country": "GB"},
                        geo={"lat": g[0], "lon": g[1]}, geo_source="postcodes.io centroid" if g[0] else None, phone=s["phone"], website=s["url"], place_ids=pl, place_match_method=meth,
                        source_url=s["url"], source_kind="official", site_policy="robots_allowed", license="OGL-3.0 (SCTS; verify per page)", record_note="facility page; may host several courts" if is_court else "non-court office/HQ"))
    # --- NI
    for n in ni_rows:
        g = pgeo.get(n["pc"], (None,) * 6); h = n["head"]
        bd = ("gb-ni-court-of-appeal" if "Royal Courts" in h else "gb-ni-crown-court" if "Laganside" in h else "gb-ni-county-court") if re.search(r"Court", h) else None
        pl, meth = match_place(n["city"], "GB", [g[2]] if g[2] else [])
        rows.append(rec(court_id=f"gb-ni-{slug(h)}", name=h, level=LEVEL.get(bd, "other"), court_system="national", country_code="GB", subdivision="GB-NIR", parent_court_id=bd,
                        address={"street": n["street"], "city": n["city"], "postcode": n["pc"], "region": g[4], "country": "GB"}, geo={"lat": g[0], "lon": g[1]},
                        geo_source="postcodes.io centroid" if g[0] else None, phone=n["phone"], website="https://www.justice-ni.gov.uk/articles/information-our-court-offices", place_ids=pl, place_match_method=meth,
                        source_url="https://www.justice-ni.gov.uk/articles/information-our-court-offices", source_kind="official", site_policy="robots_allowed", license="OGL-3.0"))
    # --- UKSC / JCPC
    g = pgeo.get("SW1P 3BD") or postcodes_io(["SW1P 3BD"]).get("SW1P 3BD", (None,) * 6)
    rows.append(rec(court_id="gb-uksc-parliament-square", name="Supreme Court of the United Kingdom (Middlesex Guildhall)", level="supreme", court_system="national", country_code="GB", subdivision="GB-ENG", parent_court_id="gb-uksc",
                    address={"street": "Parliament Square", "city": "London", "postcode": "SW1P 3BD", "region": g[4], "country": "GB"}, geo={"lat": g[0], "lon": g[1]}, geo_source="postcodes.io centroid",
                    place_ids=match_place("London", "GB")[0], place_match_method="name", website="https://www.supremecourt.uk/visiting/contact-us", source_url="https://www.supremecourt.uk/visiting/contact-us", license="OGL-3.0"))
    for r in rows:
        if r["record_type"] == "court_body" and r["court_id"] in LEVEL: pass
    # --- dedupe additions (OSM, wikidata)
    official = rows
    for kind in ("osm", "wd"):
        sec = []
        for l in rjl(f"{ROOT}/data/gb/gb_courthouses_{kind}.jsonl"):
            if kind == "osm":
                n = l.get("name") or l.get("name_local") or "Courthouse"
                sub = {"ENG": "GB-ENG", "SCT": "GB-SCT", "WLS": "GB-WLS", "NIR": "GB-NIR"}.get((l.get("subdivision") or "").split("-")[-1], l.get("subdivision"))
                a = {"street": l.get("street"), "city": l.get("city"), "postcode": l.get("postcode"), "region": None, "country": "GB"}
                r = rec(court_id=f"osm:{l['osm_id']}", name=n, name_local=l.get("name_local"), country_code="GB", subdivision=sub, address=a, geo={"lat": l.get("lat"), "lon": l.get("lon")}, phone=l.get("phone"), website=l.get("website"),
                        wikidata=l.get("wikidata"), source_url=f"https://www.openstreetmap.org/{l['osm_id']}", source_kind="osm", site_policy="open_license:ODbL", license="ODbL-1.0", retrieved_at=l.get("retrieved_at") or NOW())
            else:
                r = l; r["subdivision"] = None
            sec.append(r)
        official, dup, add = merge_dedupe(official, sec); print(kind, "dup", dup, "added", add, flush=True)
    rows = official
    # place ids + subdivision + parent for added osm/wd rows
    need = [r for r in rows if r["source_kind"] in ("osm", "wikidata") and r["geo"]["lat"] is not None and not r["address"].get("postcode")]
    rev = {}
    for r in rows:
        if r["source_kind"] in ("osm", "wikidata"):
            if not r["place_ids"]:
                pl, meth = match_place(r["address"].get("city"), "GB")
                if not pl: pl, meth = match_place(r["name"].replace("Court House", "").replace("Courthouse", "").replace("Crown Court", "").replace("Magistrates' Court", "").replace("County Court", "").strip(), "GB")
                r["place_ids"] = pl; r["place_match_method"] = meth
            if r["parent_court_id"] is None:
                r["parent_court_id"] = body_for(r["name"], r["subdivision"] or "")
            if r["subdivision"] is None and r["geo"]["lat"] is not None:
                la, lo = r["geo"]["lat"], r["geo"]["lon"]
                r["subdivision"] = "GB-NIR" if (-8.2 < lo < -5.4 and 54.0 < la < 55.4) else "GB-SCT" if la > 55.3 or (la > 54.9 and lo < -3.1 and la>55) else "GB-WLS" if (-5.4 < lo < -2.6 and 51.3 < la < 53.45 and lo < -2.9) else "GB-ENG"
            r["level"] = LEVEL.get(r["parent_court_id"], r["level"])
    seen = {}
    for r in rows:
        n = seen.get(r["court_id"], 0); seen[r["court_id"]] = n + 1
        if n: r["court_id"] = f'{r["court_id"]}~{n}'
    wjl(f"{ROOT}/data/gb/gb_courthouses.jsonl", rows)
    ch = [r for r in rows if r["record_type"] == "courthouse"]
    print("GB total", len(rows), "courthouses", len(ch), "with geo", sum(1 for r in ch if r["geo"]["lat"] is not None), "place_ids", sum(1 for r in ch if r["place_ids"]), "parent", sum(1 for r in ch if r["parent_court_id"]))
if __name__ == "__main__": build()
