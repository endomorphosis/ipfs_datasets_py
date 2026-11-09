"""Nepal district/high/special court judges + contact addresses from Common Crawl captures of
supremecourt.gov.np/court/<slug>/judges (live site unreachable from this box). Uses saved CDX picks
(np_judges_best.json) and WARC extracts in a state dir. Judges: public names/titles only; no staff.
Usage: python3 np_court_pages_cc.py <state_dir>"""
import hashlib, json, re, sys, os, glob, datetime
from bs4 import BeautifulSoup
SD = sys.argv[1]
best = json.load(open(os.path.join(SD, "np_judges_best.json")))
CH = "/workspace/world_courts/data/np/np_courthouses.jsonl"; JG = "/workspace/world_courts/data/np/np_judges.jsonl"
POL = "robots_unknown(robots.txt not retrievable; live site unreachable)|supremecourt.gov.np: (c) Supreme Court of Nepal, all rights reserved; via Common Crawl"
now = datetime.datetime.now(datetime.timezone.utc).isoformat()
def slug(s): return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")
def cid_for(s):
    if s == "specialcourt": return "np-special-court", "Special Court (Kathmandu)", "special", "np-supreme-court"
    if s.endswith("hc"): b = s[:-2]; return f"np-hc-{b}", f"High Court ({b.title()})", "appellate_intermediate", "np-high-court"
    b = s[:-2]; return f"np-dc-{b}", f"{b.title()} District Court", "trial_general", "np-lower-court"
haveC = {json.loads(l)["court_id"] for l in open(CH)}; haveJ = {json.loads(l)["judge_id"] for l in open(JG)}
nc = nj = 0
fc, fj = open(CH, "a"), open(JG, "a")
for u, r in sorted(best.items()):
    s = u.split("/court/")[1].split("/")[0]
    f = os.path.join(SD, "npw", s + ".warc")
    if not os.path.exists(f): continue
    html = open(f, "rb").read().decode("utf-8", "replace").split("\r\n\r\n", 2)[-1]
    t = [x.strip() for x in BeautifulSoup(html, "lxml").get_text("\n", strip=True).split("\n")]
    cid, ename, lvl, parent = cid_for(s)
    arc = f"commoncrawl:{r['filename']}@{r['offset']}+{r['length']} ts={r['timestamp']}"
    k = t.index("सम्पर्क ठेगाना") if "सम्पर्क ठेगाना" in t else None
    local = addr = None; phones = []; email = None
    if k is not None and t[k + 1] != "फोन नं. :":
        local = t[k + 1]; addr = t[k + 2] if t[k + 2] != "फोन नं. :" else None
        p = t.index("फोन नं. :", k); e = t.index("इमेल :", k)
        phones = [x for x in t[p + 1:e]]
        em = t[e + 1] if e + 1 < len(t) else ""
        email = em if "@" in em else None
    if local is None:
        hdr = BeautifulSoup(html, "lxml").select_one("a.site-logo span"); local = hdr.get_text(strip=True) if hdr else None
    site = f"https://supremecourt.gov.np/court/{s}"
    if cid not in haveC:
        fc.write(json.dumps({"court_id": cid, "record_type": "court", "name": ename, "name_local": local, "level": lvl,
            "court_system": "national", "country_code": "NP", "subdivision": None, "jurisdiction": "NP", "parent_court_id": parent,
            "address": {"street": addr, "city": None, "postcode": None, "region": None, "country": "NP"} if addr else None,
            "geo": None, "phone": "; ".join(phones) or None, "email": email, "website": site, "wikidata": None, "place_ids": [],
            "source_url": u, "source_kind": "archive", "site_policy": POL, "retrieved_at": now,
            "license": "official public information; no licence stated", "language": "ne",
            "sources": [{"source_url": u, "archive": arc, "source_kind": "archive"}], "needs_review": True,
            "record_note": "English name derived from the court's URL slug; address/phone as printed (Nepali) on the court page"}, ensure_ascii=False) + "\n")
        haveC.add(cid); nc += 1
    try: i = t.index("ईमेल")
    except ValueError: continue
    role = None
    for x in t[i + 1:]:
        if x in ("प्रमाणीकरण भएका फैसलाको विवरण", "प्रमाणीकरण भएका फैसलाहरु", "दैनिक पेशी सूची"): break
        if x in ("(अध्यक्ष)", "(सदस्य)"): role = x; continue
        if x.startswith("माननीय"): title_ne = re.sub(r"\s+", " ", x); continue
        if x.startswith("श्री"):
            name = re.sub(r"\s+", " ", re.sub(r"^श्री\s*", "", x)).strip(" .")
            if len(name) < 3: role = None; continue
            if "मुख्य न्यायाधीश" in title_ne:
                title = "Acting Chief Judge" if "कायम मुकायम" in title_ne else "Chief Judge"; pt = "chief"
            elif role == "(अध्यक्ष)": title, pt = "Judge (Chair)", "chief"
            elif role == "(सदस्य)": title, pt = "Judge (Member)", "associate"
            else: title, pt = "Judge", "associate"
            jid = f"{cid}-" + (slug(name) or hashlib.sha1(name.encode()).hexdigest()[:12])
            if jid in haveJ: role = None; continue
            fj.write(json.dumps({"judge_id": jid, "court_id": cid, "name": name, "name_as_listed": x, "title": title,
                "title_local": title_ne + (" " + role if role else ""), "position_type": pt, "term_start": None, "term_end": None,
                "status": "sitting_as_of_capture", "jurisdiction": "NP", "roster_url": u, "source_url": u, "source_kind": "archive",
                "site_policy": POL, "retrieved_at": now, "needs_review": True, "language": "ne",
                "extraction": f"court 'judges' page as captured by Common Crawl ({arc}); name in Nepali (Devanagari), honorific श्री removed",
                "license": "official public information; no licence stated"}, ensure_ascii=False) + "\n")
            haveJ.add(jid); nj += 1; role = None
print("courts +", nc, "judges +", nj)
