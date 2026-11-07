"""Add real court_body hierarchy rows for LK NP BT MV SG KH LA MM BN TL (replacing reliance on generic 4-node placeholders)
plus IN consumer commissions / CIC / ITAT benches and SG tribunals. Structure compiled from constitutions/judicature acts and
official judiciary sites (cited per row); Wikidata QIDs attached only on exact English-label match via wbsearchentities.
Placeholders are kept: '-supreme-court' (and '-court-of-appeal' where a real Court of Appeal exists) are enriched in place, ids unchanged."""
import sys, json, time, urllib.parse, urllib.request, os, shutil
sys.path.insert(0, "/workspace/world_courts/scrapers/courts/intl")
from row_common import *
TODAY = "2026-10-29"
if shutil.disk_usage("/workspace").free < 20e9: sys.exit("disk below 20GB, pausing")
UA = {"User-Agent": "world_courts-research/0.1 (court hierarchy compilation)"}
_wdc = {}
def wd(label):
    if label in _wdc: return _wdc[label]
    q = None
    try:
        u = "https://www.wikidata.org/w/api.php?" + urllib.parse.urlencode({"action": "wbsearchentities", "search": label, "language": "en", "format": "json", "limit": 3})
        d = json.load(urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=30))
        for s in d.get("search", []):
            if s.get("label", "").lower() == label.lower(): q = s["id"]; break
        time.sleep(0.5)
    except Exception as e: print("wd fail", label, e)
    _wdc[label] = q; return q
# (slug|full id, name, name_local, level, parent(slug or full id), source_url, place city, needs_review, note)
SUP, COA = "@supreme", "@coa"   # enrich-in-place markers
C = {}
C["LK"] = dict(city="Colombo", sup=("Supreme Court of Sri Lanka", "https://supremecourt.lk/"), coa=("Court of Appeal of Sri Lanka", "https://courtofappeal.lk/"), rows=[
 ("lk-high-court-provinces", "High Court of the Provinces", None, "trial_general", COA, "https://www.parliament.lk/files/pdf/constitution.pdf", 0, "13th Amendment Art.154P; one per province, criminal/writ/appellate jurisdiction"),
 ("lk-civil-appellate-high-court", "Civil Appellate High Courts of the Provinces", None, "appellate", COA, "https://www.moj.gov.lk/", 0, "High Court of the Provinces (Special Provisions) Act No.19 of 1990, as amended 2006"),
 ("lk-commercial-high-court", "Commercial High Court of Colombo", None, "trial_general", "lk-supreme-court", "https://www.moj.gov.lk/", 0, "High Court of the Provinces (Special Provisions) Act 1996; appeals lie directly to Supreme Court"),
 ("lk-district-courts", "District Courts", None, "trial_general", "lk-civil-appellate-high-court", "https://www.moj.gov.lk/", 0, "Judicature Act No.2 of 1978"),
 ("lk-magistrates-courts", "Magistrate's Courts", None, "trial_limited", "lk-high-court-provinces", "https://www.moj.gov.lk/", 0, "Judicature Act No.2 of 1978"),
 ("lk-primary-courts", "Primary Courts", None, "trial_limited", "lk-high-court-provinces", "https://www.moj.gov.lk/", 0, "Judicature Act No.2 of 1978"),
 ("lk-labour-tribunals", "Labour Tribunals", None, "other", "lk-high-court-provinces", "https://www.labourdept.gov.lk/", 1, "Industrial Disputes Act; appeals to High Court of the Province"),
 ("lk-board-of-quazis", "Board of Quazis", None, "appellate", COA, "https://jsc.gov.lk/", 1, "Muslim Marriage and Divorce Act"),
 ("lk-quazi-courts", "Quazi Courts", None, "family", "lk-board-of-quazis", "https://jsc.gov.lk/", 1, "Muslim Marriage and Divorce Act"),
])
C["NP"] = dict(city="Kathmandu", sup=("Supreme Court of Nepal", "https://supremecourt.gov.np/"), coa=None, rows=[
 ("np-high-courts", "High Courts of Nepal", None, "appellate", SUP, "https://supremecourt.gov.np/", 0, "Constitution of Nepal 2015 Art.139; one per province, replaced Appellate Courts in 2016"),
 ("np-high-court-biratnagar", "High Court Biratnagar", "उच्च अदालत विराटनगर", "appellate", "np-high-courts", "https://supremecourt.gov.np/", 0, "Koshi Province"),
 ("np-high-court-janakpur", "High Court Janakpur", "उच्च अदालत जनकपुर", "appellate", "np-high-courts", "https://supremecourt.gov.np/", 0, "Madhesh Province"),
 ("np-high-court-patan", "High Court Patan", "उच्च अदालत पाटन", "appellate", "np-high-courts", "https://supremecourt.gov.np/", 0, "Bagmati Province"),
 ("np-high-court-pokhara", "High Court Pokhara", "उच्च अदालत पोखरा", "appellate", "np-high-courts", "https://supremecourt.gov.np/", 0, "Gandaki Province"),
 ("np-high-court-tulsipur", "High Court Tulsipur", "उच्च अदालत तुलसीपुर", "appellate", "np-high-courts", "https://supremecourt.gov.np/", 0, "Lumbini Province"),
 ("np-high-court-surkhet", "High Court Surkhet", "उच्च अदालत सुर्खेत", "appellate", "np-high-courts", "https://supremecourt.gov.np/", 0, "Karnali Province"),
 ("np-high-court-dipayal", "High Court Dipayal", "उच्च अदालत दिपायल", "appellate", "np-high-courts", "https://supremecourt.gov.np/", 0, "Sudurpashchim Province"),
 ("np-district-courts", "District Courts of Nepal", "जिल्ला अदालत", "trial_general", "np-high-courts", "https://supremecourt.gov.np/", 0, "Constitution Art.148; 77 districts"),
 ("np-special-court", "Special Court", "विशेष अदालत", "other", SUP, "https://supremecourt.gov.np/", 0, "Special Court Act 2059; corruption cases, appeals to Supreme Court"),
 ("np-administrative-court", "Administrative Court", "प्रशासकीय अदालत", "administrative", SUP, "https://supremecourt.gov.np/", 1, "civil service disputes"),
 ("np-labour-court", "Labour Court", "श्रम अदालत", "other", "np-high-court-patan", "https://supremecourt.gov.np/", 1, "Labour Act 2074"),
 ("np-revenue-tribunal", "Revenue Tribunal", "राजस्व न्यायाधिकरण", "tax", "np-high-courts", "https://supremecourt.gov.np/", 1, "Revenue Tribunal Act 2031; appellate route needs confirmation"),
 ("np-foreign-employment-tribunal", "Foreign Employment Tribunal", "वैदेशिक रोजगार न्यायाधिकरण", "other", "np-high-courts", "https://supremecourt.gov.np/", 1, "Foreign Employment Act 2064"),
])
C["BT"] = dict(city="Thimphu", sup=("Supreme Court of Bhutan", "https://www.judiciary.gov.bt/"), coa=None, rows=[
 ("bt-high-court-of-bhutan", "High Court of Bhutan", "Drangpon Gongma", "appellate", SUP, "https://www.judiciary.gov.bt/", 0, "Constitution of Bhutan 2008 Art.21(15)"),
 ("bt-dzongkhag-courts", "Dzongkhag Courts", None, "trial_general", "bt-high-court-of-bhutan", "https://www.judiciary.gov.bt/", 0, "20 district courts, Constitution Art.21(17)"),
 ("bt-dungkhag-courts", "Dungkhag Courts", None, "trial_limited", "bt-dzongkhag-courts", "https://www.judiciary.gov.bt/", 0, "sub-district courts"),
 ("bt-thimphu-family-child-bench", "Family and Child Bench, Thimphu Dzongkhag Court", None, "family", "bt-dzongkhag-courts", "https://www.judiciary.gov.bt/", 1, "specialised bench"),
])
C["MV"] = dict(city="Malé", sup=("Supreme Court of the Maldives", "https://supremecourt.mv/"), coa=None, rows=[
 ("mv-high-court-of-maldives", "High Court of the Maldives", None, "appellate", SUP, "https://highcourt.gov.mv/", 0, "Judicature Act 22/2010"),
 ("mv-civil-court", "Civil Court", None, "trial_general", "mv-high-court-of-maldives", "https://civilcourt.gov.mv/", 0, "superior court, Malé"),
 ("mv-criminal-court", "Criminal Court", None, "trial_general", "mv-high-court-of-maldives", "https://criminalcourt.gov.mv/", 0, "superior court, Malé"),
 ("mv-family-court", "Family Court", None, "family", "mv-high-court-of-maldives", "https://familycourt.gov.mv/", 0, "superior court, Malé"),
 ("mv-juvenile-court", "Juvenile Court", None, "juvenile", "mv-high-court-of-maldives", "https://juvenilecourt.gov.mv/", 0, "superior court, Malé"),
 ("mv-drug-court", "Drug Court", None, "other", "mv-high-court-of-maldives", "https://judiciary.gov.mv/", 1, "Drugs Act 17/2011"),
 ("mv-magistrate-courts", "Magistrate Courts", None, "trial_limited", "mv-high-court-of-maldives", "https://judiciary.gov.mv/", 0, "island magistrate courts"),
 ("mv-employment-tribunal", "Employment Tribunal", None, "other", "mv-high-court-of-maldives", "https://judiciary.gov.mv/", 1, "Employment Act 2/2008; quasi-judicial"),
 ("mv-tax-appeal-tribunal", "Tax Appeal Tribunal", None, "tax", "mv-high-court-of-maldives", "https://judiciary.gov.mv/", 1, "Tax Administration Act 3/2010; quasi-judicial"),
])
C["SG"] = dict(city="Downtown Core", sup=("Supreme Court of Singapore", "https://www.judiciary.gov.sg/"), coa=("Court of Appeal of Singapore", "https://www.judiciary.gov.sg/who-we-are/courts-and-tribunals"), rows=[
 ("sg-high-court-appellate-division", "Appellate Division of the High Court", None, "appellate", COA, "https://www.judiciary.gov.sg/who-we-are/courts-and-tribunals", 0, "since 2 Jan 2021"),
 ("sg-high-court-general-division", "General Division of the High Court", None, "trial_general", "sg-high-court-appellate-division", "https://www.judiciary.gov.sg/who-we-are/courts-and-tribunals", 0, "eLitigation SGHC"),
 ("sg-sicc", "Singapore International Commercial Court", None, "other", "sg-high-court-general-division", "https://www.sicc.gov.sg/", 0, "division of the General Division"),
 ("sg-high-court-family-division", "Family Division of the High Court", None, "family", "sg-high-court-appellate-division", "https://www.judiciary.gov.sg/who-we-are/courts-and-tribunals", 0, "eLitigation SGHCF"),
 ("sg-state-courts", "State Courts of Singapore", None, "trial_general", "sg-high-court-general-division", "https://www.judiciary.gov.sg/who-we-are/courts-and-tribunals", 0, ""),
 ("sg-district-courts", "District Courts", None, "trial_general", "sg-state-courts", "https://www.judiciary.gov.sg/who-we-are/courts-and-tribunals", 0, "eLitigation SGDC"),
 ("sg-magistrates-courts", "Magistrates' Courts", None, "trial_limited", "sg-state-courts", "https://www.judiciary.gov.sg/who-we-are/courts-and-tribunals", 0, "eLitigation SGMC"),
 ("sg-coroners-courts", "Coroners' Courts", None, "other", "sg-state-courts", "https://www.judiciary.gov.sg/who-we-are/courts-and-tribunals", 0, ""),
 ("sg-small-claims-tribunals", "Small Claims Tribunals", None, "trial_limited", "sg-state-courts", "https://www.judiciary.gov.sg/civil/small-claims", 0, "eLitigation SGSCT; Small Claims Tribunals Act"),
 ("sg-employment-claims-tribunals", "Employment Claims Tribunals", None, "other", "sg-state-courts", "https://www.judiciary.gov.sg/employment-disputes", 0, "eLitigation SGECT; Employment Claims Act 2016"),
 ("sg-community-disputes-resolution-tribunals", "Community Disputes Resolution Tribunals", None, "trial_limited", "sg-state-courts", "https://www.judiciary.gov.sg/who-we-are/courts-and-tribunals", 0, "eLitigation SGCDT"),
 ("sg-protection-from-harassment-court", "Protection from Harassment Court", None, "trial_limited", "sg-state-courts", "https://www.judiciary.gov.sg/protection-harassment", 0, "Protection from Harassment Act; established 1 Jun 2021"),
 ("sg-family-justice-courts", "Family Justice Courts", None, "family", "sg-high-court-family-division", "https://www.judiciary.gov.sg/who-we-are/courts-and-tribunals", 0, ""),
 ("sg-family-courts", "Family Courts", None, "family", "sg-family-justice-courts", "https://www.judiciary.gov.sg/who-we-are/courts-and-tribunals", 0, "eLitigation SGFC"),
 ("sg-youth-courts", "Youth Courts", None, "juvenile", "sg-family-justice-courts", "https://www.judiciary.gov.sg/who-we-are/courts-and-tribunals", 0, "eLitigation SGYC"),
])
C["KH"] = dict(city="Phnom Penh", sup=("Supreme Court of Cambodia", "https://www.moj.gov.kh/"), coa=("Court of Appeal of Cambodia", "https://www.moj.gov.kh/"), rows=[
 ("kh-regional-appeal-courts", "Regional Courts of Appeal", None, "appellate", SUP, "https://www.moj.gov.kh/", 1, "Law on Organization of Courts 2014; Battambang, Tbong Khmum, Preah Sihanouk courts of appeal opened c.2019-2020"),
 ("kh-phnom-penh-municipal-court", "Phnom Penh Municipal Court of First Instance", "សាលាដំបូងរាជធានីភ្នំពេញ", "trial_general", COA, "https://www.moj.gov.kh/", 0, ""),
 ("kh-provincial-courts", "Provincial Courts of First Instance", "សាលាដំបូងខេត្ត", "trial_general", COA, "https://www.moj.gov.kh/", 0, "one per province"),
 ("kh-military-court", "Military Court", "តុលាការយោធា", "other", COA, "https://www.moj.gov.kh/", 1, ""),
 ("kh-commercial-court", "Commercial Court", None, "other", COA, "https://www.moj.gov.kh/", 1, "provided by Law on Organization of Courts 2014; operational status unverified"),
])
C["LA"] = dict(city="Vientiane", sup=("People's Supreme Court of Lao PDR", "https://www.peoplecourt.gov.la/"), coa=None, rows=[
 ("la-regional-peoples-courts", "Regional People's Courts", None, "appellate", SUP, "https://www.peoplecourt.gov.la/", 1, "Law on People's Courts 2017; three regional (appellate) courts: northern, central, southern"),
 ("la-provincial-peoples-courts", "Provincial and Vientiane Capital People's Courts", None, "trial_general", "la-regional-peoples-courts", "https://www.peoplecourt.gov.la/", 0, ""),
 ("la-area-peoples-courts", "Area (District) People's Courts", None, "trial_limited", "la-provincial-peoples-courts", "https://www.peoplecourt.gov.la/", 1, "inter-district courts"),
 ("la-military-courts", "Military Courts", None, "other", SUP, "https://www.peoplecourt.gov.la/", 1, ""),
 ("la-juvenile-chambers", "Juvenile Chambers of the People's Courts", None, "juvenile", "la-provincial-peoples-courts", "https://www.peoplecourt.gov.la/", 1, "specialised chambers"),
])
C["MM"] = dict(city="Naypyidaw Township", sup=("Supreme Court of the Union of Myanmar", "https://www.unionsupremecourt.gov.mm/"), coa=None, rows=[
 ("mm-high-courts-region-state", "High Courts of the Regions and States", None, "appellate", SUP, "https://www.unionsupremecourt.gov.mm/", 0, "Constitution 2008 s.305; 14 high courts"),
 ("mm-sad-courts", "Courts of the Self-Administered Divisions and Zones", None, "trial_general", "mm-high-courts-region-state", "https://www.unionsupremecourt.gov.mm/", 1, ""),
 ("mm-district-courts", "District Courts", None, "trial_general", "mm-high-courts-region-state", "https://www.unionsupremecourt.gov.mm/", 0, "Union Judiciary Law 2010"),
 ("mm-township-courts", "Township Courts", None, "trial_limited", "mm-district-courts", "https://www.unionsupremecourt.gov.mm/", 0, ""),
 ("mm-juvenile-courts", "Juvenile Courts", None, "juvenile", "mm-district-courts", "https://www.unionsupremecourt.gov.mm/", 1, ""),
 ("mm-courts-martial", "Courts-Martial", None, "other", None, "https://www.unionsupremecourt.gov.mm/", 1, "Constitution s.293(b); outside civilian appellate chain"),
 ("mm-constitutional-tribunal", "Constitutional Tribunal of the Union", None, "other", None, "https://www.unionsupremecourt.gov.mm/", 1, "Constitution s.46/320; separate from Supreme Court; post-2021 status uncertain"),
])
C["BN"] = dict(city="Bandar Seri Begawan", sup=("Supreme Court of Brunei Darussalam", "https://www.judiciary.gov.bn/"), coa=("Court of Appeal of Brunei Darussalam", "https://www.judiciary.gov.bn/"), rows=[
 ("bn-high-court-of-brunei", "High Court of Brunei Darussalam", None, "trial_general", COA, "https://www.judiciary.gov.bn/", 0, "Supreme Court Act Cap.5"),
 ("bn-intermediate-courts", "Intermediate Courts", None, "trial_general", "bn-high-court-of-brunei", "https://www.judiciary.gov.bn/", 0, "Intermediate Courts Act Cap.162"),
 ("bn-magistrates-courts", "Magistrates' Courts", None, "trial_limited", "bn-high-court-of-brunei", "https://www.judiciary.gov.bn/", 0, "Subordinate Courts Act Cap.6"),
 ("bn-juvenile-court", "Juvenile Court", None, "juvenile", "bn-high-court-of-brunei", "https://www.judiciary.gov.bn/", 1, ""),
 ("bn-small-claims-tribunal", "Small Claims Tribunal", None, "trial_limited", "bn-magistrates-courts", "https://www.judiciary.gov.bn/", 1, "Small Claims Tribunals Order 2006"),
 ("bn-syariah-court-of-appeal", "Syariah Court of Appeal", "Mahkamah Rayuan Syariah", "appellate", None, "https://www.syariah.gov.bn/", 0, "separate Syariah court system (Syariah Courts Act Cap.184)"),
 ("bn-syariah-high-court", "Syariah High Court", "Mahkamah Tinggi Syariah", "trial_general", "bn-syariah-court-of-appeal", "https://www.syariah.gov.bn/", 0, ""),
 ("bn-syariah-subordinate-courts", "Syariah Subordinate Courts", "Mahkamah Rendah Syariah", "trial_limited", "bn-syariah-high-court", "https://www.syariah.gov.bn/", 0, ""),
])
C["TL"] = dict(city="Dili", sup=("Supreme Court of Justice of Timor-Leste", "https://www.tribunais.tl/"), coa=("Court of Appeal of Timor-Leste", "https://www.tribunais.tl/"), rows=[
 ("tl-district-court-dili", "Dili District Court", "Tribunal Distrital de Díli", "trial_general", COA, "https://www.tribunais.tl/", 0, ""),
 ("tl-district-court-baucau", "Baucau District Court", "Tribunal Distrital de Baucau", "trial_general", COA, "https://www.tribunais.tl/", 0, ""),
 ("tl-district-court-suai", "Suai District Court", "Tribunal Distrital de Suai", "trial_general", COA, "https://www.tribunais.tl/", 0, ""),
 ("tl-district-court-oecusse", "Oecusse District Court", "Tribunal Distrital de Oecusse", "trial_general", COA, "https://www.tribunais.tl/", 0, ""),
 ("tl-chamber-of-accounts", "Chamber of Accounts of the Court of Appeal", "Câmara de Contas", "other", COA, "https://www.tribunais.tl/", 1, "exercises functions of the constitutional High Administrative, Tax and Audit Court pending its creation"),
])
IN_ROWS = [
 ("in-ncdrc", "National Consumer Disputes Redressal Commission", None, "appellate", "in-supreme-court", "https://ncdrc.nic.in/", "New Delhi", 0, "Consumer Protection Act 2019 s.53"),
 ("in-scdrc", "State Consumer Disputes Redressal Commissions", None, "appellate", "in-ncdrc", "https://ncdrc.nic.in/", None, 0, "CPA 2019 s.42; one per State/UT"),
 ("in-dcdrc", "District Consumer Disputes Redressal Commissions", None, "trial_limited", "in-scdrc", "https://ncdrc.nic.in/", None, 0, "CPA 2019 s.28"),
 ("in-cic", "Central Information Commission", None, "administrative", "in-hc-delhi", "https://cic.gov.in/", "New Delhi", 0, "RTI Act 2005 s.12; decisions reviewable by writ before High Courts"),
 ("in-itat", "Income Tax Appellate Tribunal", None, "tax", "in-supreme-court", "https://itat.gov.in/", None, 0, "Income-tax Act s.252; appeals on law to High Courts"),
 ("in-itat-delhi", "Income Tax Appellate Tribunal - Delhi", None, "tax", "in-itat", "https://itat.gov.in/", "New Delhi", 0, "Delhi benches; further appeal to Delhi High Court"),
 ("in-itat-mumbai", "Income Tax Appellate Tribunal - Mumbai", None, "tax", "in-itat", "https://itat.gov.in/", None, 0, "Mumbai benches; further appeal to Bombay High Court"),
]
POL = "reference_compiled:official_site_cited(not_crawled)"
def mk(cc, cid, name, nl, level, parent, src, city, nr, note):
    q = wd(name) if len(name.split()) > 2 and cc.lower() not in ("xx",) else None  # generic labels mis-match
    r = rec(court_id=cid, record_type="court_body", name=name, name_local=nl, level=level, country_code=cc, subdivision=cc, parent_court_id=parent,
            website=src, wikidata=q, place_ids=(rmatch([city], cc, True) if city else []), source_url=src, source_kind="official", site_policy=POL,
            license="CC0-1.0 (compiled structure)", record_note=note or None)
    r["address"]["country"] = cc
    if q: r["sources"].append({"source_url": f"https://www.wikidata.org/wiki/{q}", "site_policy": "open_license(CC0)", "source_kind": "wikidata"})
    if nr: r["needs_review"] = True
    r["added_by"] = f"ssea_court_bodies.py {TODAY}"
    return r
new_list = []; counts = {}
def run(cc, rows, enrich):
    p = f"{ROOT}/data/{cc.lower()}/{cc.lower()}_courthouses.jsonl"; ex = rjl(p)
    ids = {r["court_id"] for r in ex}; names = {norm(r["name"]) for r in ex if r.get("record_type") == "court_body"}
    up = 0
    for pid, (nm, src) in enrich.items():
        for r in ex:
            if r["court_id"] == pid and not r.get("source_url"):
                q = wd(nm)
                r.update(name=nm, source_url=src, website=src, source_kind="official", site_policy=POL, wikidata=q, retrieved_at=NOW(),
                         record_note=f"upgraded from generic placeholder by ssea_court_bodies.py {TODAY}; id kept")
                r["sources"] = [{"source_url": src, "site_policy": POL, "source_kind": "official"}] + ([{"source_url": f"https://www.wikidata.org/wiki/{q}", "site_policy": "open_license(CC0)", "source_kind": "wikidata"}] if q else [])
                if cc == "TL" and pid.endswith("supreme-court"):
                    r["needs_review"] = True; r["record_note"] += "; constitutional Supreme Court of Justice not yet installed, Court of Appeal acts as apex"
                up += 1; new_list.append((cc, pid, nm, r["level"], "upgraded"))
    add = 0
    for x in rows:
        cid, nm = x[0], x[1]
        if cid in ids or norm(nm) in names: print("dup skip", cc, cid); continue
        r = mk(cc, *x); ex.append(r); ids.add(cid); add += 1; new_list.append((cc, cid, nm, r["level"], "new"))
    wjl(p, ex); counts[cc] = (add, up)
for cc, d in C.items():
    pre = cc.lower()
    fix = lambda v: f"{pre}-supreme-court" if v == SUP else f"{pre}-court-of-appeal" if v == COA else v
    rows = [(s, n, nl, lv, fix(par), src, d["city"], nr, note) for (s, n, nl, lv, par, src, nr, note) in d["rows"]]
    enrich = {f"{pre}-supreme-court": d["sup"]}
    if d["coa"]: enrich[f"{pre}-court-of-appeal"] = d["coa"]
    run(cc, rows, enrich)
run("IN", IN_ROWS, {})
with open(f"{ROOT}/state/new_court_ids_ssea_{TODAY}.tsv", "w") as f:
    f.write("country\tcourt_id\tname\tlevel\tstatus\n")
    for t in new_list: f.write("\t".join(t) + "\n")
print(json.dumps(counts))
