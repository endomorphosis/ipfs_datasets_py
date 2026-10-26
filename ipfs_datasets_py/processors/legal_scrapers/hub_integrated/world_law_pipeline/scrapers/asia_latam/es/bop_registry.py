#!/usr/bin/env python3
"""Robots/reachability sweep of all ES official gazettes carrying municipal ordinances -> _bop_registry_es.csv."""
import csv, sys, time
from pathlib import Path
from urllib.parse import urlparse
sys.path.insert(0, str(Path(__file__).resolve().parent))
from es_bop import Fetcher, STAGE, UA
ADAPTERS = {"28": "bocm (historic walk, XML/PDF)"}
# content-path probes: a URL of the gazette's archive/notice area that a scraper would need
PROBE = {"15": "https://bop.dacoruna.gal/bopportal/publicado/2026/10/09/2026_0000001.pdf", "36": "https://boppo.depo.gal/detalle/-/boppo/2026/10/09/2026012345",
         "17": "https://www.ddgi.cat/bop/", "43": "https://www.dipta.cat/ebop/", "45": "https://bop.diputoledo.es/webEbop/", "35": "https://www.boplaspalmas.net/nbop2/",
         "08": "https://bop.diba.cat/anteriors/2026-10-09"}
rows = []
for line in open(Path(__file__).parent / "bop" / "hosts.txt"):
    name, url = line.strip().split("|")
    prov = name[:2]
    f = Fetcher()
    ok, why = f.allowed(url)
    home_ok = ok
    probe = PROBE.get(prov)
    p_ok, p_why = (f.allowed(probe) if probe and ok else (None, None))
    if not ok:
        status, reason = ("unreachable" if "unreachable" in (why or "") else "robots_disallow"), why
    elif p_ok is False:
        status, reason = "robots_disallow", f"content path {urlparse(probe).path}: {p_why}"
    elif prov in ADAPTERS:
        status, reason = "covered", ADAPTERS[prov]
    else:
        status, reason = "allowed_no_adapter_yet", ""
    if prov == "08" and status == "robots_disallow":
        reason += " (archive /anteriors/ disallowed; only today's bulletin + /anunci/<id> pages allowed -> daily-incremental only)"
    rows.append([prov, name[3:], url, urlparse(url).netloc, status, reason])
    print(rows[-1], flush=True)
with open(STAGE / "_bop_registry_es.csv", "w", newline="") as fh:
    w = csv.writer(fh); w.writerow(["province_code", "gazette", "url", "host", "status", "reason"]); w.writerows(rows)
