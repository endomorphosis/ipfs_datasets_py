#!/usr/bin/env python3
"""Re-audit every URL the EU-lane scrapers fetched against robots.txt using RFC 9309 (common/rfc9309.py)."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import glob, json, sys
from collections import Counter, defaultdict
from pathlib import Path
import requests
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common.rfc9309 import RobotsCache  # noqa: E402

UA = "world-municipal-law-research/1.0"
CA = (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/staging/eu/_state/pl_certs/ca_bundle_plus.pem")
S = (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/staging/eu/_state")


def sf(base):
    s = requests.Session()
    s.headers.update({"User-Agent": UA, "Accept-Language": "pl-PL,pl;q=0.9,en;q=0.5"})
    s.verify = CA
    return s


rc = RobotsCache(sf, UA)
urls = defaultdict(set)  # source -> urls
# CVDR: SRU listing (accepted exception), repository XML for every fetched doc
urls["cvdr_sru"].add("https://zoekservice.overheid.nl/sru/Search?x-connection=cvdr&operation=searchRetrieve")
cat = {}
for l in open(f"{S}/catalog_2026-10-10.jsonl", encoding="utf-8"):
    d = json.loads(l)
    cat[d["identifier"]] = d.get("publicatieurl_xml")
fetched_cvdr = {p.name[:-7] for p in Path((_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/staging/eu/_raw/cvdr")).glob("*/*.xml.gz")}
for i in fetched_cvdr:
    urls["cvdr_repo"].add(cat.get(i) or "")
# Poland: list endpoints + every act PDF/HTML attempted (done + failed + test)
for f in glob.glob(f"{S}/pl/catalog_*.state.json"):
    st = json.load(open(f))
    woj = Path(f).name.split("_")[1][:2]
    host = {"DS": "edzienniki.duw.pl", "LS": "dzienniki.luw.pl", "LD": "dziennik.lodzkie.eu", "MP": "edziennik.malopolska.uw.gov.pl",
            "MZ": "edziennik.mazowieckie.pl", "OP": "duwo.opole.uw.gov.pl", "PK": "edziennik.rzeszow.uw.gov.pl",
            "PL": "edziennik.bialystok.uw.gov.pl", "PM": "edziennik.gdansk.uw.gov.pl", "SL": "dzienniki.slask.eu",
            "SK": "edziennik.kielce.uw.gov.pl", "WM": "edzienniki.olsztyn.uw.gov.pl", "ZP": "e-dziennik.szczecin.uw.gov.pl",
            "KP": "edzienniki.bydgoszcz.uw.gov.pl", "LB": "edziennik.lublin.uw.gov.pl", "WP": "edziennik.poznan.uw.gov.pl"}[woj]
    urls["pl_list"].add(f"https://{host}/api/eli/acts")
    for y in st.get("years_done", {}):
        urls["pl_list"].add(f"https://{host}/api/eli/acts/POL_WOJ_{woj}/{y}")
for f in glob.glob((_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/staging/eu/PL/*.jsonl")) + glob.glob((_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/staging/eu/_unmatched/pl_*.jsonl")) \
        + glob.glob((_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/staging/eu/_test_pl/*.jsonl")):
    for l in open(f, encoding="utf-8"):
        r = json.loads(l)
        urls["pl_acts"].add(r["pdf_url"])
        urls["pl_acts"].add(r["html_url"])
# auxiliary hosts
urls["aux"].update({"https://repository.certum.pl/certumdvtlsg2r39ca.cer", "https://repository.certum.pl/homepldvtlsg2r35ca.cer",
                    "https://query.wikidata.org/sparql",
                    "https://raw.githubusercontent.com/jamarpl21/prawo-pl-eli/main/plugins/prawo-pl-edzienniki/skills/prawo-pl-edzienniki/references/api.md"})
report = {}
for src, us in urls.items():
    us = {u for u in us if u}
    bad = [u for u in sorted(us) if not rc.can_fetch(u)]
    report[src] = {"checked": len(us), "disallowed": len(bad), "examples": bad[:5]}
hosts = {b: str(v[2]) for b, v in rc.cache.items()}
out = {"robots_status": hosts, "report": report}
print(json.dumps(out, indent=1, ensure_ascii=False))
Path((_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/staging/eu/_logs/robots_audit.json")).write_text(json.dumps(out, indent=1, ensure_ascii=False))
