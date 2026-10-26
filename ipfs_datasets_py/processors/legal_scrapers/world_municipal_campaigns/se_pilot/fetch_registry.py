"""Fetch the official SCB list of län och kommuner (kodnummerordning)
and build jurisdictions.jsonl for all 290 kommuner."""
import json
import re
import sys
from pathlib import Path

import requests

OUT = Path(__file__).resolve().parent
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
