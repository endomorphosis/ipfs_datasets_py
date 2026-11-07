"""US county / municipal / judicial-district courts from official state directories (no judge or staff names stored):
TX  Office of Court Administration 'Municipal Courts by City' (PDF)
WA  Administrative Office of the Courts Court Directory (PDF): county District Courts + Municipal Courts
SC  Judicial Branch municipal court directory (HTML, with judicial circuit)
VA  Office of the Executive Secretary District Courts Directory (PDF): General District + J&DR courts, with judicial district
GA  GeorgiaCourtAccess.org all-courts list (state courts portal; secondary): municipal, county-level courts
Steps: parse -> Census batch geocode (street addresses) -> place_ids (census geoid then city name) -> dedupe vs data/us/us_courthouses.jsonl -> append (backup kept).
usage: us_muni_dirs.py [parse|merge]"""
import re, json, sys, os, glob, math, hashlib, html, subprocess, datetime, shutil
sys.path.insert(0, "/workspace/world_courts/scrapers/courts")
import us_place_match as pm
from us_merge_courthouses import batch_geocode, hav, toks
D = "/workspace/world_courts/data/us/"; RAWD = D + "muni_raw/"
NOW = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.%fZ")
POBOX = re.compile(r"(?i)^(p\.?\s*o\.?\s*(box|drawer)|post office|drawer|box)\b")
def mk(sub, name, level, system, street, city, zip_, phone, web, url, pol, kind="official", jur=None, parent=None, note=None):
    st = (street or "").strip(" ,"); po = bool(POBOX.match(st)) if st else True
    cid = "usmuni:" + hashlib.sha1(f"{sub}|{name}|{city}|{st}".lower().encode()).hexdigest()[:12]
    return dict(court_id=cid, name=name, level=level, court_system=system, country_code="US", subdivision="US-" + sub, jurisdiction=jur, parent_court_id=parent, address=dict(street=None if po else st, city=city, postcode=zip_, region=sub, country="US"),
                geo=None, phone=phone, website=web, wikidata=None, place_ids=[], place_match_method=None, source_url=url, source_kind=kind, site_policy=pol, retrieved_at=NOW, needs_review=True, record_note=note,
                sources=[dict(source_url=url, site_policy=pol, source_kind=kind)])
def txt(p): return open(p, errors="ignore").read().replace("\x0c", "\n")
# ---------------- TX ----------------
def tx():
    out = []; url = "https://www.txcourts.gov/media/1331970/Municipal-Courts-by-City.pdf"; pol = "robots_unknown:fetched_ok (txcourts.gov OCA directory PDF; judge names deliberately not stored)"
    for c in (0, 205, 410):
        L = txt(RAWD + f"col_{c}.txt").split("\n"); i = 0; cur = None
        for ln in L:
            if not ln.strip():
                continue
            if not ln.startswith(" ") and "Municipal Courts by City" not in ln and not re.match(r"^\d+$", ln.strip()):
                if cur: out.append(cur)
                cur = dict(city=ln.strip(), lines=[])
            elif cur is not None: cur["lines"].append(ln.strip())
        if cur: out.append(cur)
    rows = []
    for e in out:
        z = next((x for x in e["lines"] if re.search(r",\s*TX\s+\d{5}", x)), None)
        if not z: continue
        k = e["lines"].index(z); m = re.match(r"(.+?),\s*TX\s+(\d{5})", z); ph = next((x for x in e["lines"] if re.match(r"\(\d{3}\)\s*\d{3}-\d{4}", x)), None)
        street = e["lines"][k - 1] if k > 0 else None
        if street and POBOX.match(street) is None and k > 1 and re.match(r"^(suite|ste|room|rm|building|bldg|floor)\b", street, re.I): street = e["lines"][k - 2] + ", " + street
        rows.append(mk("TX", f"{e['city']} Municipal Court", "municipal", "municipal", street, m.group(1).title() if m.group(1).isupper() else m.group(1), m.group(2), ph, None, url, pol, jur=f"City of {e['city']}"))
    return rows
# ---------------- WA ----------------
def wa():
    L = [x.rstrip() for x in txt(RAWD + "wa_dir.txt").split("\n")]; rows = []; county = None; sec = None; url = "https://www.courts.wa.gov/court_dir/courtdirectory.pdf"; pol = "robots_allowed (courts.wa.gov robots.txt: only admin paths disallowed; AOC directory PDF; judge/staff names not stored)"
    HDR = {"SUPERIOR COURT", "COUNTY CLERK", "JUVENILE COURT", "DISTRICT COURT", "MUNICIPAL COURTS", "MUNICIPAL COURT", "PROBATION SERVICES", "DISTRICT COURT PROBATION", "FAMILY LAW ANNEX", "COURT OF APPEALS", "SUPREME COURT"}
    ADR = re.compile(r",\s*WA\s+\d{5}")
    for i, raw in enumerate(L):
        x = raw.strip(); m = re.match(r"^([A-Z][A-Z .'-]+) COUNTY(?:, CONTINUED)?$", x)
        if m and x not in HDR:
            nc = m.group(1).title()
            if not x.endswith("CONTINUED"): sec = None
            county = nc; continue
        if x in HDR:
            sec = x
            if x == "DISTRICT COURT" and county:
                blk = L[i + 1:i + 9]; addr = next((b.strip() for b in blk[:3] if ADR.search(b) and not b.strip().startswith("Mailing")), None)
                if addr: rows.append(wa_row(f"{county} County District Court", "trial_limited", "state", addr, blk, url, pol, county))
            continue
        if not county or sec not in ("DISTRICT COURT", "MUNICIPAL COURTS", "MUNICIPAL COURT"): continue
        if not re.fullmatch(r"[A-Z][A-Z .'-]{2,40}", x): continue
        nxt = [y.strip() for y in L[i + 1:i + 5]]
        if not nxt or nxt[0].startswith("See ") or not any(ADR.search(y) for y in nxt[:3]): continue
        blk = L[i + 1:i + 9]; addr = next((b.strip() for b in blk[:4] if ADR.search(b) and not b.strip().startswith("Mailing")), None)
        if not addr: continue
        if sec == "DISTRICT COURT":
            name = f"{x.title()} District Court" if "COUNTY" in x else f"{county} County District Court"
            rows.append(wa_row(name, "trial_limited", "state", addr, blk, url, pol, county))
        else: rows.append(wa_row(f"{re.sub(chr(32)+'(Violations Bureau Only|Violations Bureau)$', '', x.title())} Municipal Court", "municipal", "municipal", addr, blk, url, pol, county, x.title()))
    return rows
def wa_rowfix(): pass
def wa_row(name, level, system, addr, blk, url, pol, county, city=None):
    if re.search(r"(?i)tribal|dispute|probation|resolution|kcdc|office|department|misdemeanant|bureau", name): return None
    addr = re.sub(r"^(Location|Address):\s*", "", addr); m = re.match(r"(.+?),\s*([^,]+),\s*WA\s+(\d{5})", addr)
    if not m: return None
    street, c, z = m.group(1), m.group(2), m.group(3); ph = next((re.search(r"Phone:\s*([\d\- ()]+)", b).group(1).strip() for b in blk if re.search(r"Phone:\s*[\d]", b)), None)
    web = next((b.split("Website:", 1)[1].strip() for b in blk if b.strip().startswith("Website:")), None)
    return mk("WA", name, level, system, street, c, z, ph, web, url, pol, jur=f"{county} County, Washington")
# ---------------- SC ----------------
def sc():
    s = open(RAWD + "sc_muni.html", errors="ignore").read(); t = html.unescape(re.sub(r"<[^>]+>", "\n", re.sub(r"(?s)<(script|style)[^>]*>.*?</\1>", "", s))); L = [x.strip() for x in t.split("\n") if x.strip()]
    url = "https://www.sccourts.org/courts/trial-courts/municipal-court/courts/"; pol = "robots_allowed (sccourts.org robots.txt disallows only Googlebot paths; SC Judicial Branch directory)"; rows = []
    i = L.index("Courts") + 1 if "Courts" in L else 0
    while i < len(L):
        if i + 1 < len(L) and L[i] == L[i + 1] and i + 2 < len(L) and L[i + 2] == "Mailing Address:": i += 1
        if i + 1 < len(L) and L[i + 1] == "Mailing Address:":
            name = L[i]; j = i + 2; blk = []
            while j < len(L) and not (j + 1 < len(L) and L[j + 1] == "Mailing Address:" ) and not (j + 2 < len(L) and L[j] == L[j + 1] and L[j + 2] == "Mailing Address:") and j < i + 20: blk.append(L[j]); j += 1
            pa = blk.index("Physical Address:") if "Physical Address:" in blk else -1
            if pa >= 0:
                street = blk[pa + 1]; cz = re.match(r"(.+?),\s*SC\s+(\d{5})", blk[pa + 2]) if pa + 2 < len(blk) else None
                ph = blk[blk.index("Office:") + 1] if "Office:" in blk else None; cir = blk[blk.index("Circuit:") + 1] if "Circuit:" in blk else None
                if cz: rows.append(mk("SC", f"{name} Municipal Court", "municipal", "municipal", street, cz.group(1), cz.group(2), ph, None, url, pol, jur=(f"South Carolina Judicial Circuit {cir}" if cir else None)))
            i = j; continue
        i += 1
    return rows
# ---------------- VA ----------------
def va():
    L = txt(RAWD + "va_dist.txt").split("\n"); rows = []; url = "https://vacourts.gov/static/directories/dist.pdf"; pol = "robots_allowed (vacourts.gov robots.txt: only judicial-conference paths disallowed for Googlebot; OES directory PDF; judge/clerk names not stored)"
    blocks = []; cur = []
    HDR = re.compile(r"^([A-Z][\w .'/&-]+? (?:GD & JDR|GD|JDR))(?:\s{2,}|$)")
    for ln in L:
        hm = HDR.match(ln); a_ = ln[:44].rstrip().strip()
        if hm:
            if cur: blocks.append(cur)
            cur = [hm.group(1)]
        elif a_ and cur: cur.append(a_)
    if cur: blocks.append(cur)
    for b in blocks:
        m = re.match(r"^(.+?)\s+(GD & JDR|GD|JDR)$", b[0])
        if not m or len(b) < 3: continue
        loc, typ = m.group(1), m.group(2)
        z = next((x for x in b if re.search(r",\s*VA\s+\d{5}", x)), None)
        if not z: continue
        k = b.index(z); mm = re.match(r"(.+?),\s*VA\s+(\d{5})", z); street = b[k - 1]
        if POBOX.match(street) is None and street.lower().startswith(("suite", "room", "rm", "ste")) and k > 1: street = b[k - 2] + ", " + street
        dist = b[1]; jd = re.search(r"\((\d+)\)", dist); ord_ = re.match(r"(\w+)\s+Judicial District", dist)
        jur = ("Virginia " + dist) if dist else None
        ph = next((re.search(r"\(\d{3}\)\s*\d{3}-\d{4}", x).group(0) for x in b if re.search(r"^\(\d{3}\)\s*\d{3}-\d{4}", x)), None)
        for t_ in (["GD", "JDR"] if typ == "GD & JDR" else [typ]):
            if t_ == "GD": name, lvl, sysm = f"{loc} General District Court", "trial_limited", "state"
            else: name, lvl, sysm = f"{loc} Juvenile and Domestic Relations District Court", "juvenile", "state"
            r = mk("VA", name, lvl, sysm, street, mm.group(1), mm.group(2), ph, None, url, pol, jur=jur); rows.append(r)
    return rows
# ---------------- GA ----------------
def ga():
    s = open(RAWD + "ga_all.html", errors="ignore").read(); t = html.unescape(re.sub(r"<[^>]+>", "\n", re.sub(r"(?s)<(script|style)[^>]*>.*?</\1>", "", s))); L = [x.strip() for x in t.split("\n") if x.strip()]
    url = "https://georgiacourtaccess.org/all-courts"; pol = "robots_unknown:fetched_ok (georgiacourtaccess.org state court-records portal; secondary aggregator, verify)"; rows = []
    for i, x in enumerate(L):
        if i + 2 < len(L) and L[i + 1] == "More Info" and L[i + 2] == "Address:":
            name = x; j = i + 3; addr = L[j] if j < len(L) else ""
            ph = L[L.index("Phone Number:", j) + 1] if "Phone Number:" in L[j:j + 6] else None
            web = L[j + L[j:j + 10].index("Website:") + 1] if "Website:" in L[j:j + 10] else None
            m = re.match(r"(.+),\s*([^,]+),\s*GA,?\s*(\d{5})", addr)
            if not m: continue
            nl = name.lower()
            if "superior" in nl: lvl, sysm = "trial_general", "state"
            elif "municipal" in nl: lvl, sysm = "municipal", "municipal"
            elif "probate" in nl: lvl, sysm = "probate", "state"
            elif "juvenile" in nl: lvl, sysm = "juvenile", "state"
            else: lvl, sysm = "trial_limited", ("municipal" if "city" in nl else "state")
            rows.append(mk("GA", name, lvl, sysm, m.group(1), m.group(2), m.group(3), ph, web, url, pol, kind="official_portal"))
    return rows

# ---------------- depth pass 3: CA IL OH WI MO ----------------
def ca():
    rows = []; url = "https://courts.ca.gov/system/files?file=solicitation-request-document%2Fit-2025-203-rb-exh-d-regional-map-and-jbe-listingpdf.pdf"; pol = "robots_allowed (courts.ca.gov robots.txt: admin paths only; Judicial Council public RFP exhibit listing court facilities with addresses)"
    rx = re.compile(r"^\s*(\S.*?)\s{2,}(\S.*?)\s{2,}(\S.*?)\s{2,}(\S.*?)\s+CA\s+(\d{5}(?:-\d{4})?)\s*$")
    for ln in txt(RAWD + "ca_jbe.txt").split("\n"):
        m = rx.match(ln)
        if not m: continue
        cty, court, street, city, z = [x.strip() for x in m.groups()]
        if re.search(r"(?i)judicial council|administrative|AOC", court): continue
        if re.search(r"(?i)supreme", court): name, lvl = "Supreme Court of California (facility)", "supreme"
        elif re.search(r"(?i)appeal", court): name, lvl = f"California {court.title().replace('Of','of')}", "appellate_intermediate"
        else: name, lvl = f"Superior Court of California, County of {cty}", "trial_general"
        if lvl != "trial_general": continue  # appellate/supreme already present in the base dataset
        rows.append(mk("CA", name, lvl, "state", street, city, z, None, None, url, pol, jur=f"{cty} County, California"))
    return rows
def il():
    s = open(RAWD + "il_dir.html", errors="ignore").read(); t = html.unescape(re.sub(r"<[^>]+>", "\n", re.sub(r"(?s)<(script|style)[^>]*>.*?</\1>", "", s))); L = [x.strip() for x in t.split("\n") if x.strip()]
    url = "https://www.illinoiscourts.gov/courts-directory/"; pol = "robots_allowed (illinoiscourts.gov robots.txt disallows only /antilles/, /App_Code/, /Bin/; Office of the Illinois Courts directory)"; rows = []
    for i, x in enumerate(L):
        if x == "Address" and i > 0 and i + 3 < len(L) and L[i - 2].startswith("Learn more about"):
            name = L[i - 1]
            if not re.search(r"(?i)courthouse|circuit court", name): continue
            street = L[i + 1]; m = re.match(r"(.+?),\s*IL\s+(\d{5})", L[i + 2])
            if not m: continue
            ph = L[i + 3] if re.match(r"\(\d{3}\)", L[i + 3]) else None
            cty = re.sub(r" (County )?(Courthouse|Circuit Court).*", "", name)
            rows.append(mk("IL", f"{cty} County Circuit Court (Courthouse)", "trial_general", "state", street, m.group(1), m.group(2), ph, None, url, pol, jur=f"{cty} County, Illinois"))
    return rows
def oh():
    rows = []; url = "https://www.supremecourt.ohio.gov/eStatsSubmission/Files/eStats%20Court%20List.pdf"; pol = "robots_allowed (supremecourt.ohio.gov robots.txt: /cms/ and /Content/ODCMB/ disallowed; Supreme Court of Ohio court ID list; names only, no street address in source)"
    for ln in txt(RAWD + "oh_estats.txt").split("\n"):
        m = re.match(r"^(MC\d+)\s+(.+?)\s*$", ln)
        if not m: continue
        nm = m.group(2)
        mm = re.match(r"^(.+?) Municipal Court$", nm)
        if not mm or "County" in mm.group(1) or "Mayor" in nm: continue
        city = mm.group(1)
        r = mk("OH", nm, "municipal", "municipal", None, city, None, None, None, url, pol, jur=f"City of {city}, Ohio", note="address not given in the source list; place matched by city name")
        rows.append(r)
    return rows
def wi():
    rows = []; pol1 = "robots_allowed (wicourts.gov has no robots.txt restrictions; Wisconsin Court System circuit court clerk directory; clerk names not stored)"
    s = open(RAWD + "wi_clerk.html", errors="ignore").read(); t = html.unescape(re.sub(r"<[^>]+>", "\n", re.sub(r"(?s)<(script|style)[^>]*>.*?</\1>", "", s))); L = [x.strip() for x in t.split("\n") if x.strip()]
    url = "https://www.wicourts.gov/courts/circuit/clerkcontact.htm"
    i0 = L.index("Contact") + 1
    i = i0
    while i < len(L):
        if i + 1 < len(L) and re.match(r"^[A-Z][A-Za-z .'-]+$", L[i]) and "," in L[i + 1] and not re.search(r"\d", L[i + 1].split(",")[0]) and i + 2 < len(L) and re.match(r"^\d", L[i + 2]):
            cty = L[i]; j = i + 3; blk = []
            while j < len(L) and L[j] != "Website" and j < i + 12: blk.append(L[j]); j += 1
            zi = next((k for k, b in enumerate(blk) if re.search(r",\s*WI\s+\d{5}", b)), None)
            if zi is not None:
                m = re.match(r"(.+?),\s*WI\s+(\d{5})", blk[zi]); street = L[i + 2]
                ph = next((b.split("Ph:", 1)[1].strip() for b in blk if b.startswith("Ph:")), None)
                rows.append(mk("WI", f"{cty} County Circuit Court", "trial_general", "state", street, m.group(1), m.group(2), ph, None, url, pol1, jur=f"{cty} County, Wisconsin"))
            i = j; continue
        i += 1
    url2 = "https://www.wicourts.gov/contact/docs/muni.pdf"; pol2 = "robots_allowed (wicourts.gov; Directory of Wisconsin Municipal Courts, April 1 2021 interim edition: may be outdated; judge/clerk names not stored)"
    Lm = txt(RAWD + "wi_muni_dir.txt").split("\n"); end = next(k for k, x in enumerate(Lm) if k > 30 and x.strip().startswith("Joint Municipal Courts") and "Dist" not in x and "…" not in x) if any(k > 30 and x.strip().startswith("Joint Municipal Courts") and "…" not in x for k, x in enumerate(Lm)) else len(Lm)
    for lo, hi in ((0, 50), (50, 200)):
        cur = None; blocks = []
        for ln in Lm[22:end]:
            c = ln[lo:hi].strip() if len(ln) > lo else ""
            m = re.match(r"^(.+? Municipal Court)(?: \(Dist\. \d+\))?$", c)
            if m: cur = [m.group(1)]; blocks.append(cur)
            elif c and cur is not None: cur.append(c)
        for b in blocks:
            z = next((x for x in b if re.search(r",\s*Wisconsin\s+\d{5}", x)), None)
            if not z: continue
            k = b.index(z); m = re.match(r"(.+?),\s*Wisconsin\s+(\d{5})", z); street = b[k - 1] if k > 1 and not b[k - 1].endswith("Clerk") else None
            if street and re.match(r"(?i)^(hon\.|court phone)", street): street = None
            ph = next((re.search(r"Court phone:\s*([\d-]+)", x).group(1) for x in b if x.startswith("Court phone:")), None)
            rows.append(mk("WI", re.sub(r"^[^A-Za-z0-9]+", "", b[0]), "municipal", "municipal", street, m.group(1), m.group(2), ph, None, url2, pol2, jur=f"{m.group(1)}, Wisconsin"))
    return rows
def mo():
    s = open(RAWD + "mo_muni.html", errors="ignore").read(); t = html.unescape(re.sub(r"<[^>]+>", "\n", re.sub(r"(?s)<(script|style)[^>]*>.*?</\1>", "", s))); L = [x.strip() for x in t.split("\n") if x.strip()]
    url = "https://www.courts.mo.gov/mcw/findacourt/muniDivisionList.htm"; pol = "robots_allowed (courts.mo.gov robots.txt disallows only case/bench paths; Missouri Courts 'Find a Court' municipal division list; no street address in the list)"; rows = []
    idx = [k for k, x in enumerate(L) if x.endswith("Municipal Division")]
    for a, k in enumerate(idx):
        e = idx[a + 1] if a + 1 < len(idx) else len(L); blk = L[k + 1:min(e, k + 6)]
        nm = L[k]; city = nm[:-len(" Municipal Division")].strip()
        held = next((b for b in blk if b.startswith("Held at")), None); ph = next((b for b in blk if re.match(r"^\(\d{3}\)", b)), None); cty = next((b for b in blk if b.endswith(" County") or b.endswith("City")), None)
        rows.append(mk("MO", f"{city} Municipal Division", "municipal", "municipal", None, city, None, ph, None, url, pol, jur=f"City of {city}, Missouri", note=(held or "address not given in the source list; place matched by city name") + (f"; {cty}" if cty else "")))
    return rows
PARSERS3 = dict(CA=ca, IL=il, OH=oh, WI=wi, MO=mo)

# ---------------- depth pass 4: NJ NE CT (+ IA KY CO MD) ----------------
def nj():
    L = txt(RAWD + "nj_muni.txt").split("\n"); rows = []; url = "https://njj-aocmedia-prod-general-purpose.s3.amazonaws.com/rosters/municipal/municipal-court-listing.pdf"; pol = "robots_unknown:no_robots_txt (NJ Judiciary State List of Municipal Courts PDF, run date 26 Oct 2026; judge and administrator names not stored)"
    for i, ln in enumerate(L):
        m = re.match(r"^COURT CODE\s+([A-Z .'-]+ COUNTY)\s*$", ln.strip())
        if not m or i + 4 >= len(L): continue
        cty = m.group(1).title(); h = L[i + 1]; mm = re.match(r"^\s*(\d{4})\s+MVC # \w+\s+(.+?)\s{2,}PHONE : (\S+)", h)
        if not mm: continue
        street = L[i + 2].strip(); cz = re.match(r"^\s*(.+?)\s+NJ\s+(\d{5})", L[i + 3])
        if not cz: continue
        name = re.sub(r"\bTWP\b", "Township", re.sub(r"\bBORO\b", "Borough", mm.group(2).strip())).title().replace("Municipal Ct", "Municipal Court")
        rows.append(mk("NJ", name, "municipal", "municipal", street.title() if street.isupper() else street, cz.group(1).title(), cz.group(2), mm.group(3), None, url, pol, jur=f"{cty}, New Jersey", note=f"NJ court code {mm.group(1)}"))
    return rows
def ne():
    rows = []; pol = "robots_allowed (nebraskajudicial.gov robots.txt: system paths only; Nebraska Judicial Branch directories; clerk names/emails not stored)"
    for f, kind, url in (("ne_county.html", "County Court", "https://nebraskajudicial.gov/directories/county-court-contacts"), ("ne_district.html", "District Court", "https://nebraskajudicial.gov/directories/district-court-contacts")):
        s = open(RAWD + f, errors="ignore").read(); t = html.unescape(re.sub(r"<[^>]+>", "\n", re.sub(r"(?s)<(script|style)[^>]*>.*?</\1>", "", s))); L = [x.strip() for x in t.split("\n") if x.strip()]
        for i, x in enumerate(L):
            if x == "Email" and i + 3 < len(L) and re.match(r"^[A-Z][A-Za-z .'-]+$", L[i + 1]) and re.match(r"^[\d-]{12}", L[i + 2]):
                cty = L[i + 1]; ph = L[i + 2]; j = i + 4; blk = []
                while j < len(L) and L[j] != "More Info" and j < i + 10: blk.append(L[j]); j += 1
                z = next((b for b in blk if re.search(r",\s*NE\s+\d{5}", b)), None)
                if not z: continue
                m = re.match(r"(.+?),\s*NE\s+(\d{5})", z); st = [b for b in blk if b != z]
                street = ", ".join(st) if st else None
                if street and re.match(r"(?i)^(p\.?\s*o\.?\s*(box)?)", street) and len(st) > 1: street = ", ".join(b for b in st if not re.match(r"(?i)^p\.?\s*o\.", b)) or street
                lvl = "trial_limited" if kind == "County Court" else "trial_general"
                rows.append(mk("NE", (f"{cty} County Court" if kind == "County Court" else f"{cty} County District Court"), lvl, "state", street, m.group(1), m.group(2), ph, None, url, pol, jur=f"{cty} County, Nebraska"))
    return rows
def ct():
    s = open(RAWD + "ct_courts.html", errors="ignore").read(); t = html.unescape(re.sub(r"<[^>]+>", "\n", re.sub(r"(?s)<(script|style)[^>]*>.*?</\1>", "", s))); L = [x.strip().replace("\xa0", " ") for x in t.split("\n") if x.strip()]
    url = "https://www.jud.ct.gov/directory/courthouses.htm"; pol = "robots_allowed (jud.ct.gov robots.txt disallows only specific document paths; CT Judicial Branch State Courthouses directory)"; rows = []
    sec = None; name = None
    for x in L:
        if x in ("Judicial District Courts", "Geographical Area Courts"): sec = x; continue
        if sec is None: continue
        m = re.match(r"^(\d[^,]*?),\s*([A-Za-z .]+?)(?:,?\s*CT)?,?\s*(\d{5})\b", x)
        if m and name:
            street, city, z = m.group(1), m.group(2), m.group(3)
            nm = re.sub(r"\s*[-,]?\s*G\.A\.\s*\d+$", "", name).strip()
            if sec == "Judicial District Courts": cname, lvl = f"{nm} Judicial District Superior Court", "trial_general"
            else: cname, lvl = f"{nm} Geographical Area Superior Court", "trial_limited"
            rows.append(mk("CT", cname, lvl, "state", street, city.strip(), z, None, None, url, pol, jur="Connecticut")); name = None; continue
        if not x.startswith(("Chief Clerk", "Map", "Top", "-->", ",", "(")) and not re.match(r"^\d", x) and len(x) < 40: name = x
    return rows

def _lines(f):
    s = open(f, errors="ignore").read(); t = html.unescape(re.sub(r"<[^>]+>", "\n", re.sub(r"(?s)<(script|style)[^>]*>.*?</\1>", "", s)))
    return [x.strip().replace("\xa0", " ") for x in t.split("\n") if x.strip()]
def md():
    rows = []; pol = "robots_allowed (mdcourts.gov robots.txt: system paths only; Maryland Judiciary court directory county pages; clerk names not stored)"
    for f in sorted(glob.glob(RAWD + "md_c/*.html")):
        L = _lines(f); slug = os.path.basename(f)[:-5]; url = f"https://www.mdcourts.gov/courtsdirectory/{slug}"; seen = set()
        for i, x in enumerate(L):
            m = re.match(r"^(Circuit Court for .+|Circuit Court of .+|Orphans[’'] Court(?: for .+)?)$", x)
            if not m or i + 2 >= len(L): continue
            j = i + 1
            while j < min(i + 4, len(L)) and not re.search(r",\s*MD,?\s+\d{5}", L[j]): j += 1
            if j >= min(i + 4, len(L)) or j == i + 1 or not re.search(r",\s*MD,?\s+\d{5}", L[j]): continue
            cz = re.match(r"(.+?),\s*MD,?\s+(\d{5})", L[j]); street = ", ".join(L[i + 1:j])
            if re.match(r"(?i)^(p\.?\s*o\.?\s*box|mailing)", street): continue
            probate = x.startswith("Orphans"); nm = x if not probate or " for " in x else None
            if probate and nm is None: nm = "Orphans’ Court for " + re.sub(r"^Circuit Court for ", "", next((y for y in L if y.startswith("Circuit Court for")), slug.title() + " County"))
            key = (nm, street)
            if key in seen: continue
            seen.add(key)
            rows.append(mk("MD", nm, "probate" if probate else "trial_general", "state", street, cz.group(1), cz.group(2), None, None, url, pol, jur=re.sub(r"^(Circuit Court|Orphans[’'] Court) for ", "", nm)))
    return rows
def ia():
    rows = []; pol = "robots_allowed (iowacourts.gov robots.txt has no disallow rules; Iowa Judicial Branch county district court pages; clerk and judge names not stored)"
    for f in sorted(glob.glob(RAWD + "ia_c/*.html")):
        L = _lines(f); cty = os.path.basename(f)[:-5].replace("_", " "); url = "https://www.iowacourts.gov/iowa-courts/court-directory"
        i = next((k for k, x in enumerate(L) if x == "Clerk of Court"), None)
        if i is None: continue
        j = i + 1; blk = []
        while j < min(i + 6, len(L)) and not re.search(r",\s*IA\s+\d{5}", L[j]): blk.append(L[j]); j += 1
        if j >= len(L) or not re.search(r",\s*IA\s+\d{5}", L[j]): continue
        m = re.match(r"(.+?),\s*IA\s+(\d{5})", L[j]); ph = next((y.split("Phone:", 1)[1].strip() for y in L[j + 1:j + 3] if y.startswith("Phone:")), None)
        rows.append(mk("IA", f"{cty} County District Court", "trial_general", "state", ", ".join(blk) or None, m.group(1), m.group(2), ph, None, url, pol, jur=f"{cty} County, Iowa"))
    return rows

def nm():
    L = [x.rstrip() for x in txt(RAWD + "nm_master.txt").split("\n")]; rows = []; url = "https://nmcourts.gov/wp-content/uploads/sites/62/2026/08/NM-COURTS-MASTER-LIST.pdf"; pol = "robots_allowed (nmcourts.gov robots.txt empty; New Mexico Courts Master List PDF, Updated 09/09/25; no judge or staff names)"
    for i, x in enumerate(L):
        if x.strip().startswith("Phone Number:") and i > 0:
            name = L[i - 1].strip()
            if not re.search(r"(?i)court|metropolitan", name) or "Satellite" in name: continue
            loc = next((y.strip() for y in L[i + 1:i + 6] if y.strip().startswith("Physical Location:")), None)
            if not loc: continue
            loc = loc.split(":", 1)[1].strip(); m = re.match(r"^(.*?)[ ,]+NM\s+(\d{5})", loc)
            if not m: continue
            body = m.group(1).strip(" ,")
            if "," in body: street, city = body.rsplit(",", 1)
            else: street, city = body, None
            if city is None:
                mm = re.match(r"^(.*\d.*?)\s+([A-Z][a-z]+(?: [A-Z][a-z]+)?)$", body)
                if mm: street, city = mm.group(1), mm.group(2)
            ph = L[i].split(":", 1)[1].strip().split()[0] if L[i].split(":", 1)[1].strip() else None
            nl = name.lower()
            if "municipal" in nl: lvl, sysm = "municipal", "municipal"
            elif "magistrate" in nl: lvl, sysm = "trial_limited", "state"
            elif "probate" in nl: lvl, sysm = "probate", "state"
            elif "metropolitan" in nl: lvl, sysm = "trial_limited", "state"
            elif "district" in nl: lvl, sysm = "trial_general", "state"
            else: lvl, sysm = "trial_limited", "state"
            if city is None or POBOX.match(street.strip()): street_ = None if POBOX.match(street.strip()) else street.strip()
            else: street_ = street.strip()
            rows.append(mk("NM", name, lvl, sysm, street_, (city or "").strip() or None, m.group(2), ph, None, url, pol, jur="New Mexico"))
    return rows
def indiana():
    t = open(RAWD + "in_dir.txt", errors="ignore").read(); rows = []; url = "https://www.in.gov/courts/files/court-directory.pdf"; pol = "robots_allowed (in.gov robots.txt: User-agent * with no disallow; Indiana Judicial Branch Directory of Courts and Clerks PDF; judge, magistrate and clerk names not stored)"
    CT = re.compile(r"^(?:(?P<city>[A-Z][A-Za-z.'’ -]+?) (?P<kind>City Court|Town Court)|(?P<typ>Circuit Court|County Court|Probate Court|Superior Court(?: [A-Za-z0-9 -]+)?|[A-Z][a-z]+ Superior Court))$")
    for pg in t.split("\x0c")[1:]:
        cols = ([ln[:44] for ln in pg.split("\n")], [ln[44:] for ln in pg.split("\n")]); 
        for col in cols:
            C = [x.strip() for x in col]; county = None
            for i, x in enumerate(C):
                m = re.match(r"^([A-Z][A-Za-z .'-]+) County$", x)
                if m: county = m.group(1); continue
                cm = CT.match(x)
                if not cm or county is None and not cm.group("city"): continue
                if re.search(r"(?i)small claims|division|magistrate", x): continue
                j = i + 1; z = None
                while j < min(i + 14, len(C)):
                    if CT.match(C[j]) or re.match(r"^[A-Z][A-Za-z .'-]+ County$", C[j]) or C[j] == "Clerk’s Office": break
                    if re.search(r",\s*IN\s+\d{5}", C[j]): z = j; break
                    j += 1
                if z is None: continue
                mz = re.match(r"(.+?),\s*IN\s+(\d{5})", C[z]); street = C[z - 1] if z - 1 > i and re.match(r"^(\d|P\.?\s*O|One |Two |Room|Suite|Box)", C[z - 1]) else None
                ph = next((re.search(r"Pho:\s*([\d-]+)", C[k]).group(1) for k in range(z, min(z + 3, len(C))) if "Pho:" in C[k] and re.search(r"Pho:\s*[\d-]+", C[k])), None)
                if cm.group("city"): name, lvl, sysm, jur = f"{cm.group('city')} {cm.group('kind')}", "municipal", "municipal", f"{cm.group('city')}, Indiana"
                else:
                    typ = cm.group("typ"); name = f"{county} County {typ}"; sysm = "state"; lvl = "trial_limited" if typ.startswith("County") else ("probate" if typ.startswith("Probate") else "trial_general"); jur = f"{county} County, Indiana"
                rows.append(mk("IN", name, lvl, sysm, street, mz.group(1), mz.group(2), ph, None, url, pol, jur=jur))
    return rows

def co():
    rows = []; pol = "robots_allowed (coloradojudicial.gov robots.txt: system paths only; Colorado Judicial Branch county trial court pages; judge and staff names not stored)"
    for f in sorted(glob.glob(RAWD + "co_c/*.html")):
        L = _lines(f); slug = os.path.basename(f)[:-5]; url = f"https://www.coloradojudicial.gov/courts/trial-courts/{slug}"; seen = set()
        for i in range(len(L) - 2):
            if L[i] == "CO" and re.match(r"^\d{5}", L[i + 1]) and i >= 3 and L[i - 1] == ",":
                city = L[i - 2]; k = i - 3; blk = []
                while k >= 0 and not re.search(r"(?i)court ?house|justice|judicial|center|building|courts?\b|annex|complex|plaza", L[k]) and len(blk) < 3: blk.insert(0, L[k]); k -= 1
                if k < 0: continue
                name = L[k]; street = ", ".join(b for b in blk if not re.match(r"(?i)^p\.?\s*o\.?", b)) or None
                if re.search(r"(?i)^(probation|self-help|judges)", name) or len(name) > 70 or (name, street) in seen: continue
                seen.add((name, street)); cty = re.sub(r"-county$", "", slug).replace("-", " ").title()
                rows.append(mk("CO", name, "trial_general", "state", street, city, L[i + 1][:5], None, None, url, pol, jur=f"{cty} County, Colorado", note="Colorado county and district courts share this courthouse"))
    return rows

def ar():
    import html as _h
    rows = []; url = "https://arcourts.gov/directories/district-courts"; pol = "robots_allowed (arcourts.gov robots.txt: Drupal system paths only; Arkansas Judiciary district court directory; judge and clerk names not stored)"
    for f in sorted(glob.glob(RAWD + "ar_p*.html"), key=lambda x: int(re.search(r"ar_p(\d+)", x).group(1))):
        s = open(f, errors="ignore").read(); vc = s[s.find("view-content"):]; cur = None
        for part in re.split(r"(<table.*?</table>)", vc, flags=re.S):
            if part.startswith("<table"):
                cap = re.search(r"<caption>(.*?)</caption>", part, re.S); cap = _h.unescape(re.sub(r"<[^>]+>", "", cap.group(1))).strip() if cap else ""
                for tr in re.findall(r"<tr>(.*?)</tr>", part.split("<tbody>")[1], re.S):
                    t = [_h.unescape(re.sub(r"<[^>]+>", "", x)).strip() for x in re.findall(r"<td.*?>(.*?)</td>", tr, re.S)]
                    if len(t) >= 6 and t[0] == "Chief District Court Clerk" and cur and cap:
                        name = cur if cap.lower() in cur.lower() else f"{cur} - {cap}"
                        rows.append(mk("AR", name, "trial_limited", "state", t[3], t[2], t[4], t[5] or None, None, url, pol, jur="Arkansas", note="Arkansas district court department; address is the department clerk office"))
            else:
                m = [x.strip() for x in re.sub(r"<[^>]+>", "\n", part).split("\n") if x.strip()]
                if m and "Pagination" not in m[0] and not m[-1].startswith("Hon."): cur = _h.unescape(m[-1])
    return rows
def nv():
    L = [x.rstrip() for x in open(RAWD + "nv_dir.txt", errors="ignore").read().split("\n")]; rows = []; url = "https://nvcourts.gov/__data/assets/pdf_file/0014/11282/Judicial_Directory_03.23.26.pdf"; pol = "robots_allowed (nvcourts.gov robots.txt: system paths only; Nevada Judicial Directory PDF Rev. March 17, 2026; no street addresses published, no judge names stored)"
    sect = None; cur = None; cty = set("Churchill Clark Douglas Elko Esmeralda Eureka Humboldt Lander Lincoln Lyon Mineral Nye Pershing Storey Washoe".split()) | {"Carson City", "White Pine"}
    def flush():
        nonlocal cur
        if cur and cur["city"]:
            nm_ = " ".join(cur["name"]).strip(); city = " ".join(cur["city"]).strip(); sect_ = cur["sect"]
            ph = re.sub(r"\s+", "", " ".join(cur["ph"]))
            if not nm_ or not ph: cur = None; return
            nm_ = f"{nm_} Justice Court" if sect_ == "J" else f"{nm_} Municipal Court"
            rows.append(mk("NV", nm_, "municipal" if sect_ == "M" else "trial_limited", "municipal" if sect_ == "M" else "state", None, city, None, ph[:14] if ph else None, None, url, pol, jur=f"{cur['county']} County, Nevada" if sect_ == "J" else f"{city}, Nevada", note="Nevada directory gives city and website only; no street address"))
        cur = None
    for ln in L:
        if re.match(r"^\s+JUSTICE COURTS\s*$", ln): flush(); sect = "J"; continue
        if re.match(r"^\s+MUNICIPAL COURTS\s*$", ln): flush(); sect = "M"; continue
        if "SENIOR" in ln or "Contact the Supreme" in ln: flush(); sect = sect if "SENIOR" not in ln else None; continue
        if sect is None or not ln.strip() or "JUDICIAL DIRECTORY" in ln or "Rev. March" in ln or "(Continued)" in ln: continue
        cols = [(m.start(), m.group().strip()) for m in re.finditer(r"\S+(?: \S+)*", ln)]
        if re.match(r"^\s+(Justice|Municipal)\s*$", ln) or re.match(r"^\s+(Court|City)\s+(City|County)", ln) or "Main Website" in ln: continue
        kc = next(((c, t) for c, t in cols if 40 <= c < 78 and t in cty), None)
        kcol = kc[0] if kc else 50
        names = [t for c, t in cols if c + len(t) <= 26 and c < 24]; city = [t for c, t in cols if c + len(t) > 26 and c < kcol]; county = [kc[1]] if kc else []
        ph = [t for c, t in cols if c >= 120 or re.match(r"^\(?\d{3}\)?[ -]?\d{0,3}-?\d*$", t)]
        if county and county[0] in cty and names and city:
            flush(); cur = dict(name=names, city=city, county=county[0], ph=ph, sect=sect)
        elif cur:
            cur["name"] += names; cur["city"] += city; cur["ph"] += ph
    flush()
    return rows

def orr():
    rows = []; url = "https://www.courts.oregon.gov/courts/Documents/rpt_JP-Muni_Court_Registry_by_Court.pdf"; pol = "robots_allowed (courts.oregon.gov robots.txt: SharePoint system paths only; Oregon Justice/Municipal Court Registry PDF dated 2022-03-04, read via Wayback snapshot 20220727214900 because the live file now 404s; judge names not stored)"
    for ln in open(RAWD + "or_reg.txt", errors="ignore"):
        ln = ln.rstrip()
        m = re.match(r"^(\S.*?(?:Court|Cout)[^\s]*(?: [A-Za-z#0-9 -]*?)?)\s{2,}(M; J|M|J)\s{2,}(.*)$", ln)
        if not m: continue
        name, typ, rest = m.group(1).strip(), m.group(2), m.group(3)
        z = re.search(r"\s(97\d{3})(?:\s|$)", rest)
        if not z: continue
        parts = [x.strip() for x in re.split(r"\s{2,}", rest[:z.start()].strip()) if x.strip()]
        if len(parts) < 3: continue
        county, city = parts[-1], parts[-2]; pre = parts[:-2]; phone = None
        if pre and re.match(r"^[\d(][\d() ,.-]+", pre[0]) and re.search(r"\d{3}\D*\d{4}", pre[0]): phone = pre.pop(0)
        street = pre[0] if pre and not re.match(r"(?i)^(p\.?\s?o\.?|po)\b", pre[0]) else None
        web = None
        tail = rest[z.end():]; wm = re.search(r"(www\.\S+|https?://\S+)", tail)
        if wm: web = wm.group(1) if wm.group(1).startswith("http") else "http://" + wm.group(1)
        name = name.replace("Cout", "Court")
        lvl, sysm = ("municipal", "municipal") if typ == "M" else ("trial_limited", "state")
        if typ == "M; J": lvl, sysm = "trial_limited", "municipal"
        rows.append(mk("OR", name, lvl, sysm, street, city, z.group(1), phone, web, url, pol, jur=(f"{county} County, Oregon" if typ != "M" else f"{city}, Oregon"), note="Oregon registry data dated 2022-03-04 (Wayback 2022-07-27); verify before relying"))
    return rows
PARSERS4 = dict(NJ=nj, NE=ne, CT=ct, MD=md, IA=ia, NM=nm, IN=indiana, CO=co)
PARSERS = dict(TX=tx, WA=wa, SC=sc, VA=va)  # GA portal list is paginated/JS (only 5 rows in static HTML): not used
def parse(PS=None):
    allr = []
    for k, f in (PS or PARSERS).items():
        r = [x for x in f() if x]; seen = {}
        for x in r: seen[x["court_id"]] = x
        r = list(seen.values()); print(k, len(r), sum(1 for x in r if x["address"]["street"]), flush=True); allr += r
    with open(D + "us_muni_parsed.jsonl", "w") as f:
        for r in allr: f.write(json.dumps(r) + "\n")
def merge():
    new = [json.loads(l) for l in open(D + "us_muni_parsed.jsonl")]
    # judicial-district bodies (SC circuits, VA districts)
    bodies = {}
    for r in new:
        if r["subdivision"] in ("US-SC", "US-VA") and r["jurisdiction"]:
            bid = "us-" + r["subdivision"][3:].lower() + "-jd-" + re.sub(r"[^a-z0-9]+", "-", r["jurisdiction"].lower()).strip("-")
            r["parent_court_id"] = bid
            bodies.setdefault(bid, dict(court_id=bid, record_type="court_body", name=r["jurisdiction"], level="judicial_district", court_system="state", country_code="US", subdivision=r["subdivision"], jurisdiction=None, parent_court_id=None, address=dict(street=None, city=None, postcode=None, region=r["subdivision"][3:], country="US"), geo=None, phone=None, website=None, wikidata=None, place_ids=[], place_match_method=None,
                source_url=r["source_url"], source_kind="official", site_policy=r["site_policy"], retrieved_at=NOW, needs_review=True, record_note="judicial circuit/district grouping derived from the state directory", sources=[dict(source_url=r["source_url"], site_policy=r["site_policy"], source_kind="official")]))
    old = [json.loads(l) for l in open(D + "us_courthouses.jsonl")]
    # geocode street addresses
    todo = [r for r in new if r["address"]["street"]]
    g = batch_geocode(todo); print("geocoded", len(g), "of", len(todo), flush=True)
    for i, r in enumerate(todo):
        if i in g: r["geo"] = dict(lat=g[i]["lat"], lon=g[i]["lon"]); r["county_fips"] = g[i]["county_fips"]
    grid = {}
    for k, r in enumerate(old):
        if r.get("geo"): grid.setdefault((r["subdivision"], round(r["geo"]["lat"], 2), round(r["geo"]["lon"], 2)), []).append(k)
    bycity = {}
    for k, r in enumerate(old):
        c = pm.norm((r.get("address") or {}).get("city")); 
        if c: bycity.setdefault((r["subdivision"], c), []).append(k)
    add = []; merged = 0
    for r in new:
        best = None; nt = toks(r["name"])
        if r.get("geo"):
            la, lo = round(r["geo"]["lat"], 2), round(r["geo"]["lon"], 2)
            for dla in (-0.01, 0, 0.01):
                for dlo in (-0.01, 0, 0.01):
                    for k in grid.get((r["subdivision"], round(la + dla, 2), round(lo + dlo, 2)), []):
                        d = hav(r["geo"], old[k]["geo"]); same_kind = (r["level"] == "municipal") == ("municipal" in (old[k]["name"] or "").lower() or old[k].get("level") == "municipal")
                        if same_kind and (d < 150 or (d < 600 and nt & toks(old[k]["name"]))):
                            if best is None or d < best[0]: best = (d, k)
        if best is None and r["level"] == "municipal":
            for k in bycity.get((r["subdivision"], pm.norm(r["address"]["city"])), []):
                if "municipal" in (old[k]["name"] or "").lower() or old[k].get("level") == "municipal": best = (0, k); break
        if best:
            o = old[best[1]]; o.setdefault("sources", []).append(dict(r["sources"][0], name=r["name"], address=r["address"])); merged += 1
            o["official_name"] = o.get("official_name") or r["name"]
            for f_ in ("phone", "website", "jurisdiction"):
                if not o.get(f_) and r.get(f_): o[f_] = r[f_]
            if r.get("parent_court_id") and not o.get("parent_court_id"): o["parent_court_id"] = r["parent_court_id"]
        else: add.append(r)
    # place ids for added rows
    withg = [r for r in add if r.get("geo")]; nog = [r for r in add if not r.get("geo")]
    with open(D + "us_muni_new_geo.jsonl", "w") as f:
        for r in withg: f.write(json.dumps(r) + "\n")
    if withg: pm.main(D + "us_muni_new_geo.jsonl", D + "us_muni_new_placed.jsonl"); withg = [json.loads(l) for l in open(D + "us_muni_new_placed.jsonl")]
    geo, nm = pm.load_gm()
    for r in withg:
        if not r["place_ids"] and r["address"].get("city"):
            p = nm.get((pm.norm(r["address"]["city"]), r["subdivision"][3:]))
            if p: r["place_ids"] = [p] + r["place_ids"]; r["place_match_method"] = "name"
    for r in nog:
        ids = []; p = nm.get((pm.norm(r["address"]["city"]), r["subdivision"][3:]))
        if p: ids.append(p)
        r["place_ids"] = ids; r["place_match_method"] = "name" if ids else None
    added = withg + nog
    shutil.copy(D + "us_courthouses.jsonl", D + "us_courthouses.jsonl.bak_pre_muni")
    out = old + added + list(bodies.values())
    with open(D + "us_courthouses.jsonl", "w") as f:
        for r in out: f.write(json.dumps(r) + "\n")
    import collections
    print(json.dumps(dict(parsed=len(new), merged_into_existing=merged, added=len(added), added_with_place=sum(1 for r in added if r["place_ids"]), added_geocoded=len(withg), bodies=len(bodies), total=len(out), by_state=collections.Counter(r["subdivision"] for r in added))))
if __name__ == "__main__" and sys.argv[1:2] == ["parse"]: parse()
if __name__ == "__main__" and sys.argv[1:2] == ["merge"]: merge()

if __name__ == "__main__" and sys.argv[1:2] == ["parse3"]: parse(PARSERS3)

if __name__ == "__main__" and sys.argv[1:2] == ["parse4"]: parse(PARSERS4)

PARSERS5 = dict(AR=ar, NV=nv, OR=orr)
if __name__ == "__main__" and sys.argv[1:2] == ["parse5"]: parse(PARSERS5)
