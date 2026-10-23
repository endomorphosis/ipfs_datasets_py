#!/usr/bin/env python3
"""Download gob.pe sitemap index + child sitemaps (robots.txt Sitemap: line), keep only normas-legales URLs
and institution roots. Polite: 2 s between requests, identifying UA. Resumable (skips files already extracted)."""
import gzip, re, time, sys, json
from pathlib import Path
import requests
UA = "JusticeDAO-WorldLaw/1.0 (+https://github.com/endomorphosis/ipfs_datasets_py; municipal law research crawler; polite)"
D = Path(__file__).resolve().parent / "_sitemaps"; D.mkdir(exist_ok=True)
s = requests.Session(); s.headers["User-Agent"] = UA
idx = gzip.decompress(s.get("https://www.gob.pe/sitemaps/sitemap.xml.gz", timeout=60).content).decode()
locs = re.findall(r"<loc>([^<]+)</loc>", idx)
print(len(locs), "child sitemaps", flush=True)
for i, u in enumerate(locs):
    out = D / (u.rsplit("/", 1)[-1].replace(".xml.gz", ".normas.txt"))
    if out.exists() or out.with_name(out.name + ".gz").exists():   # extracted lists are kept gzipped (disk hygiene)
        continue
    time.sleep(2)
    for k in range(3):
        try:
            r = s.get(u.replace("http://", "https://"), timeout=120); break
        except requests.RequestException as e:
            print("retry", u, e, flush=True); time.sleep(20)
    else:
        continue
    xml = gzip.decompress(r.content).decode("utf-8", "replace")
    keep = [x for x in re.findall(r"<loc>([^<]+)</loc>", xml) if "/normas-legales/" in x]
    tmp = out.with_suffix(".tmp"); tmp.write_text("\n".join(keep)); tmp.rename(out)
    print(i, u, len(keep), flush=True)
print("done", flush=True)
