#!/usr/bin/env python3
"""Download LexML sitemap index + map*.xml (robots: allowed, Crawl-delay 5) and keep only
state/municipal (non-judicial) URNs. Resumable: skips maps already extracted. Logs to stdout."""
import re, sys, time
from pathlib import Path
import requests
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common.rfc9309 import Robots
UA = "JusticeDAO-WorldLaw/1.0 (+https://github.com/endomorphosis/ipfs_datasets_py; municipal law research crawler; polite)"
D = Path(__file__).resolve().parent / "_sitemaps"; D.mkdir(exist_ok=True)
s = requests.Session(); s.headers["User-Agent"] = UA
rt = s.get("https://www.lexml.gov.br/robots.txt", timeout=60)
if rt.status_code >= 500: sys.exit("robots 5xx -> disallow all")
rb = Robots(rt.text) if rt.status_code == 200 else Robots(allow_all=True)
delay = max(5.0, float(rb.crawl_delay(UA) or 0))
JUD = re.compile(r"tribunal|justica|turma|camara.criminal|camara.civel|vara|juizado|supremo|superior|ministerio.publico|tce|conselho", re.I)
def keep(u):
    m = re.search(r"urn:lex:br([^:]*):([^:]*):", u)
    if not m: return False
    loc, auth = m.group(1), m.group(2)
    if not loc.startswith(";"): return False      # federal
    if "justica" in loc or JUD.search(auth): return False
    return True
idx = s.get("https://www.lexml.gov.br/sitemap_index.xml", timeout=120).text
locs = re.findall(r"<loc>([^<]+)</loc>", idx)
print(len(locs), "maps; delay", delay, flush=True)
for i, u in enumerate(locs):
    out = D / (u.rsplit("/", 1)[-1].replace(".xml", ".txt"))
    if out.exists(): continue
    if not rb.can_fetch(UA, u): print("robots disallow", u, flush=True); continue
    time.sleep(delay)
    for k in range(4):
        try:
            r = s.get(u, timeout=300)
            if r.status_code == 200: break
            print("http", r.status_code, u, flush=True)
        except requests.RequestException as e:
            print("retry", u, e, flush=True)
        time.sleep(30 * (k + 1))
    else:
        continue
    urns = [x.split("/urn/", 1)[-1] for x in re.findall(r"<loc>([^<]+)</loc>", r.text)]
    kept = [x for x in urns if keep(x)]
    tmp = D / ("." + out.name + ".tmp"); tmp.write_text("\n".join(kept)); tmp.rename(out)
    print(i, u, len(urns), "kept", len(kept), flush=True)
print("done", flush=True)
