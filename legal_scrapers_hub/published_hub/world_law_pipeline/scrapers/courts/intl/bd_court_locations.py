"""BD: district judiciary portals <district>.judiciary.gov.bd 'Court Location' pages (official, robots: no rules). Adds courthouse rows, dedup vs existing names."""
import json, sys, re, time, datetime, os, requests
sys.path.insert(0, "/workspace/world_courts/scrapers/courts/intl")
from row_common import *
from bs4 import BeautifulSoup as B
D = "bagerhat bandarban barguna barishal bhola bogura brahmanbaria chandpur chapainawabganj chattogram chuadanga coxsbazar cumilla dhaka dinajpur faridpur feni gaibandha gazipur gopalganj habiganj jamalpur jashore jhalokati jhenaidah joypurhat khagrachhari khulna kishoreganj kurigram kushtia lakshmipur lalmonirhat madaripur magura manikganj meherpur moulvibazar munshiganj mymensingh naogaon narail narayanganj narsingdi natore netrokona nilphamari noakhali pabna panchagarh patuakhali pirojpur rajbari rajshahi rangamati rangpur satkhira shariatpur sherpur sirajganj sunamganj sylhet tangail thakurgaon".split()
now = datetime.datetime.now(datetime.UTC).isoformat(); OUT = f"{ROOT}/data/bd/bd_courthouses.jsonl"
old = [json.loads(l) for l in open(OUT)]; oldn = {norm(r["name"]) for r in old}; rows = []; fail = []
for d in D:
    u = f"https://{d}.judiciary.gov.bd/en/servicve-box-detail/court-location"; p = f"{ROOT}/rules/raw/bd_dir/{d}.html"
    if not os.path.exists(p):
        try:
            r = requests.get(u, timeout=40, headers={"User-Agent": "world-courts-research/0.3"}); time.sleep(3)
            if r.status_code != 200: fail.append((d, r.status_code)); continue
            open(p, "w").write(r.text)
        except Exception as e: fail.append((d, type(e).__name__)); continue
    s = B(open(p), "html.parser")
    for t in s(["script", "style", "nav", "header", "footer"]): t.decompose()
    L = s.get_text("\n", strip=True).split("\n")
    try: L = L[max(i for i, x in enumerate(L) if x.strip() == "Court Location") + 1:]
    except ValueError: fail.append((d, "no_section")); continue
    for i, x in enumerate(L):
        x = re.sub(r"^(Locator\s*-\s*)", "", x).strip()
        if not re.search(r"\bCourt\b", x, re.I) or re.search(r"click|google|map", x, re.I) or len(x) > 120: continue
        name, addr = x, None
        m = re.match(r"^(.*?Court[^,]*,\s*[A-Za-z ]+?)\s+(District .*|Address.*)$", x)
        if m: name, addr = m.group(1), m.group(2)
        elif i + 1 < len(L) and not re.search(r"Court|click|google|map|Contact", L[i + 1], re.I): addr = L[i + 1]
        if addr: addr = re.sub(r"^Address:\s*", "", addr)[:200]
        cid = f"bd-jp-{d}-" + re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:60]
        if norm(name) in oldn or cid in {r["court_id"] for r in rows}: continue
        lv = "trial"
        rows.append({"court_id": cid, "record_type": "courthouse", "name": name, "name_local": None, "level": lv, "court_system": "national", "country_code": "BD",
          "subdivision": "BD", "jurisdiction": d.title(), "parent_court_id": "bd-district-court", "address": {"street": addr, "city": d.title(), "postcode": None, "region": None, "country": "BD"},
          "geo": {"lat": None, "lon": None}, "phone": None, "website": f"https://{d}.judiciary.gov.bd/", "wikidata": None, "place_ids": [], "source_url": u,
          "source_kind": "official", "site_policy": "robots_allowed(no rules; content-signal preamble only);official:District Judiciary portal (judiciary.gov.bd)",
          "retrieved_at": now, "license": "Bangladesh government public information", "needs_review": True})
with open(OUT, "a") as f:
    for r in rows: f.write(json.dumps(r, ensure_ascii=False) + "\n")
print("added", len(rows), "fail", fail)
