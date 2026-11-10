"""Fetch the official SCB list of län och kommuner (kodnummerordning)
and build jurisdictions.jsonl for all 290 kommuner."""
import json
import re
import sys
from pathlib import Path

import requests


# Generated campaign files live outside the installed package; the mapping is
# legal_scrapers/user_data_paths.py (IPFS_DATASETS_LEGAL_WORK_ROOT).
import importlib.util as _udp_util
from pathlib import Path as _udp_Path
_udp_spec = _udp_util.spec_from_file_location(
    "_legal_scrapers_user_data_paths",
    next(p for p in _udp_Path(__file__).resolve().parents if p.name == "legal_scrapers") / "user_data_paths.py",
)
_udp = _udp_util.module_from_spec(_udp_spec)
_udp_spec.loader.exec_module(_udp)
_campaign_data_file = _udp.work_mirror_path
def _campaign_source_path(path):
    return _udp.source_path_for_mirror(path, __file__)


OUT = _campaign_data_file(__file__).parent
URL = ("https://www.scb.se/hitta-statistik/regional-statistik-och-kartor/"
       "regionala-indelningar/lan-och-kommuner/"
       "lan-och-kommuner-i-kodnummerordning/")

s = requests.Session()
s.headers["User-Agent"] = "world-municipal-law-pilot/1.0 (research; polite harvest)"
r = s.get(URL, timeout=60)
print("status", r.status_code, "bytes", len(r.content))
r.raise_for_status()
html = r.text
(OUT / "scratch" / "scb_kommuner.html").write_text(html, encoding="utf-8")

# The page lists entries like "0180 Stockholm" inside table/list markup.
text = re.sub(r"<[^>]+>", "\n", html)
text = text.replace("&nbsp;", " ")
pairs = re.findall(r"\b(\d{4})\s+([A-ZÅÄÖ][A-Za-zÅÄÖåäöé\- ]{1,40}?)\s*(?:\n|$)", text)
seen = {}
for code, name in pairs:
    name = name.strip()
    if code not in seen and name:
        seen[code] = name
print("raw pairs:", len(seen))
for c in sorted(seen)[:8]:
    print(c, seen[c])
(OUT / "scratch" / "scb_pairs.json").write_text(
    json.dumps(seen, ensure_ascii=False, indent=1), encoding="utf-8")
