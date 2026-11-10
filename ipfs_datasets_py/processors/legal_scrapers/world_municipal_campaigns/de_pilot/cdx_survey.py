#!/usr/bin/env python3
"""Wayback CDX survey: per candidate town domain, count archived PDFs
whose URL suggests Satzungen/Ortsrecht, and sample listing pages."""
import json
import sys
import time
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


HERE = _campaign_data_file(__file__).parent.parent
S = requests.Session()
S.headers["User-Agent"] = (
    "ipfs_datasets_py world-municipal pilot (open legal data research)"
)

DOMAINS = [
    ("Heide SH", "01051044", "heide.de"),
    ("Brunsbuettel SH", "01051011", "brunsbuettel.de"),
    ("Marne SH", "01051057", "stadt-marne.de"),
    ("Ahaus NW", "05554004", "ahaus.de"),
    ("Borken NW", "05554012", "borken.de"),
    ("Detmold NW", "05766020", "detmold.de"),
    ("Berchtesgaden BY", "09172116", "gemeinde-berchtesgaden.de"),
    ("Tuessling BY", "09171145", "tuessling.de"),
    ("Boeblingen BW", "08115003", "boeblingen.de"),
    ("Celle NI", "03351006", "celle.de"),
]


def cdx(domain, extra):
    u = (f"http://web.archive.org/cdx/search/cdx?url={domain}*"
         f"&output=text&fl=original,timestamp,statuscode,mimetype"
         f"&collapse=urlkey&limit=4000{extra}")
    r = S.get(u, timeout=100)
    r.raise_for_status()
    return [ln.split(" ") for ln in r.text.splitlines() if ln.strip()]


def main():
    out = []
    for label, ags, domain in DOMAINS:
        rec = {"label": label, "ags": ags, "domain": domain}
        try:
            rows = cdx(domain, "&filter=mimetype:application/pdf")
            pdfs = [r[0] for r in rows if r[2] == "200"]
            satz = [p for p in pdfs if "satzung" in p.lower()]
            ort = [p for p in pdfs if "ortsrecht" in p.lower()]
            rec.update(total_pdfs=len(pdfs), satzung_pdfs=len(satz),
                       ortsrecht_pdfs=len(ort),
                       sample_satzung=satz[:5])
        except Exception as e:
            rec["error"] = f"{type(e).__name__}: {str(e)[:100]}"
        print(json.dumps(rec, ensure_ascii=False), flush=True)
        out.append(rec)
        time.sleep(2)
    (HERE / "raw" / "cdx_survey.json").write_text(
        json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
