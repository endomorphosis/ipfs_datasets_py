#!/usr/bin/env python3
"""Full Wayback CDX lists for winner domains (all PDFs + ortsrecht/
satzungen HTML listing pages), saved under raw/cdx_<domain>.json."""
import json
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

TARGETS = [
    ("heide.de", "pdf"),
    ("brunsbuettel.de", "pdf"),
    ("ahaus.de", "pdf"),
    ("borken.de", "pdf"),
    ("tuessling.de", "pdf"),
    ("boeblingen.de", "pdf"),
    ("celle.de", "pdf"),
    ("detmold.de", "pdf"),
]


def cdx(domain, kind, tries=3):
    filt = "&filter=mimetype:application/pdf" if kind == "pdf" else ""
    u = (f"http://web.archive.org/cdx/search/cdx?url={domain}*"
         f"&output=text&fl=original,timestamp,statuscode,mimetype"
         f"&collapse=urlkey&limit=20000{filt}")
    last = None
    for i in range(tries):
        try:
            r = S.get(u, timeout=110)
            r.raise_for_status()
            return [ln.split(" ") for ln in r.text.splitlines() if ln.strip()]
        except Exception as e:
            last = e
            time.sleep(15 * (i + 1))
    raise last


def main():
    for domain, kind in TARGETS:
        out_path = HERE / "raw" / f"cdx_{domain.replace('.', '_')}.json"
        try:
            rows = cdx(domain, kind)
            ok = [r for r in rows if r[2] == "200"]
            out_path.write_text(json.dumps(
                [{"url": r[0], "ts": r[1], "mime": r[3]} for r in ok],
                indent=0, ensure_ascii=False), encoding="utf-8")
            satz = [r for r in ok if "satzung" in r[0].lower()]
            ort = [r for r in ok if "ortsrecht" in r[0].lower()]
            print(f"{domain}: {len(ok)} pdfs ok, satzung {len(satz)}, "
                  f"ortsrecht {len(ort)} -> {out_path.name}", flush=True)
        except Exception as e:
            print(f"{domain}: FAILED {type(e).__name__}: {str(e)[:90]}", flush=True)
        time.sleep(8)


if __name__ == "__main__":
    main()
