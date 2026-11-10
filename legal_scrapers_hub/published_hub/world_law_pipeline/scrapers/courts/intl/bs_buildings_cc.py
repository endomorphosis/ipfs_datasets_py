"""Bahamas Supreme Court buildings (New Providence, Bank Lane) from Common Crawl capture of courts.bs/courts/buildings/
(CC-MAIN-2026-43 WARC; live courts.bs returns 500). Appends courthouse rows to data/bs/bs_courthouses.jsonl."""
import json, gzip, urllib.request, datetime, re
from bs4 import BeautifulSoup
FN, OFF, LN = "crawl-data/CC-MAIN-2026-43/segments/1791170054246.18/warc/CC-MAIN-20261008000509-20261008030509-00175.warc.gz", 167890465, 12058
URL = "https://courts.bs/courts/buildings/"
OUT = "/workspace/world_courts/data/bs/bs_courthouses.jsonl"
r = urllib.request.Request("https://data.commoncrawl.org/" + FN, headers={"Range": f"bytes={OFF}-{OFF+LN-1}", "User-Agent": "WorldCourtsResearchBot/1.0"})
html = gzip.decompress(urllib.request.urlopen(r, timeout=120).read()).decode("utf-8", "replace").split("\r\n\r\n", 2)[-1]
txt = BeautifulSoup(html, "lxml").get_text("\n", strip=True)
blds = [b for b in ["Annex 1", "Hansard Building", "Supreme Court Building", "Annex 2"] if re.search(re.escape(b) + r"\nSee on google maps\nAddress\nBank Lane", txt)]
now = datetime.datetime.now(datetime.timezone.utc).isoformat()
have = {json.loads(l)["court_id"] for l in open(OUT)}
n = 0
with open(OUT, "a") as f:
    for b in blds:
        cid = "bs-supreme-court-np-" + re.sub(r"[^a-z0-9]+", "-", b.lower()).strip("-")
        if cid in have: continue
        f.write(json.dumps({"court_id": cid, "record_type": "courthouse", "name": f"Supreme Court of The Bahamas, {b} (New Providence)",
            "name_local": None, "level": "trial_general", "court_system": "national", "country_code": "BS", "subdivision": None,
            "jurisdiction": "BS", "parent_court_id": "bs-supreme-court",
            "address": {"street": "Bank Lane", "city": "Nassau", "postcode": None, "region": "New Providence", "country": "BS"},
            "geo": None, "phone": None, "website": URL, "wikidata": None, "place_ids": [], "source_url": URL, "source_kind": "archive",
            "site_policy": "robots_allowed|courts.bs (Judiciary of The Bahamas): no open licence stated; via Common Crawl CC-MAIN-2026-43",
            "retrieved_at": now, "license": "official public information; no licence stated",
            "sources": [{"source_url": URL, "archive": "commoncrawl:" + FN, "source_kind": "archive"}], "needs_review": True,
            "record_note": "Supreme Court building listed on courts.bs Buildings page (office hours 09:00-17:00)"}, ensure_ascii=False) + "\n"); n += 1
print("buildings", blds, "new", n)
