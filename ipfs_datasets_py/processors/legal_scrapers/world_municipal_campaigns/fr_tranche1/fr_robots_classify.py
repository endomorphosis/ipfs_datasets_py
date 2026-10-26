"""France tranche 1 — robots classification, lean pass.

Classifies hosts whose robots.txt bodies were already saved by
fr_robots_census.py (no refetch), and fetches the remaining hosts
with tight timeouts (25 s, 2 attempts). Classification matches the
census script: parse the FULL body with RobotFileParser and test
the family's document path; whole-host Disallow:/ and /api/
disallows are reported verbatim for the record.
"""
import json
import sys
import time
from pathlib import Path
from urllib.robotparser import RobotFileParser

HF = Path.home() / "workspace" / "goals" / "world-municipal-law-coverage" / "hidden_files"
sys.path.insert(0, str(HF / "fr_pilot" / "scripts"))
import fr_build as B  # noqa: E402

OUT = HF / "fr_tranche1"
ROBOTS_DIR = OUT / "robots"

HOSTS = {
    "datasets.grandbesancon.fr": ("grandbesancon_webservice", "/fichiers/delibs/"),
    "data.grandbesancon.fr": ("grandbesancon_portal", "/opendata/dataset/conseilsCCAS"),
    "data.capatlantique.fr": ("opendatasoft", "/api/v2/catalog/datasets"),
    "data.agglo-carene.fr": ("opendatasoft", "/api/v2/catalog/datasets"),
    "data.nantesmetropole.fr": ("opendatasoft", "/api/records/1.0/search/"),
    "data.rennesmetropole.fr": ("opendatasoft", "/api/records/1.0/search/"),
    "data.toulouse-metropole.fr": ("opendatasoft", "/api/records/1.0/search/"),
    "data.strasbourg.eu": ("opendatasoft", "/api/records/1.0/search/"),
    "data.montpellier3m.fr": ("opendatasoft", "/api/records/1.0/search/"),
    "opendata.bordeaux-metropole.fr": ("opendatasoft", "/api/records/1.0/search/"),
    "datahub.bordeaux-metropole.fr": ("bordeaux_datahub", "/"),
    "opendata.paris.fr": ("opendatasoft", "/api/records/1.0/search/"),
    "parisdata.opendatasoft.com": ("opendatasoft", "/api/records/1.0/search/"),
    "anglet-opendatapaysbasque.opendatasoft.com": ("opendatasoft", "/api/records/1.0/search/"),
    "blois-agglopolys-centrevaldeloire.opendatasoft.com": ("opendatasoft", "/api/records/1.0/search/"),
    "data.blois.agglopolys.fr": ("opendatasoft", "/api/v2/catalog/datasets"),
    "trouver.datasud.fr": ("datasud", "/"),
    "www.datasud.fr": ("datasud", "/"),
    "datacat.datalocale.fr": ("datalocale", "/"),
    "geo.brest-metropole.fr": ("brest_geoportal", "/"),
    "www.brest.fr": ("ville_site", "/"),
    "www.ccpro.fr": ("cc_site", "/"),
    "open-data-chelles.opendata.arcgis.com": ("arcgis_hub", "/"),
    "services8.arcgis.com": ("arcgis_server", "/"),
}

import requests  # noqa: E402


def fetch_robots(host):
    url = f"https://{host}/robots.txt"
    s = requests.Session()
    for i in range(2):
        try:
            r = s.get(url, headers=B.HEADERS, timeout=25)
            if r.status_code == 200:
                return r.text, 200
            if r.status_code == 404:
                return "", 404
            return None, r.status_code
        except Exception as e:  # noqa: BLE001
            last = type(e).__name__
        time.sleep(3)
    return None, last


def classify(host, family, docpath, body, status):
    rec = {"host": host, "family": family, "robots_status": status, "test_path": docpath}
    if body is None:
        rec["class"] = "unreachable"
        return rec
    if body == "":
        rec["class"] = "allowed_no_robots"
        rec["doc_allowed"] = True
        return rec
    rec["robots_bytes"] = len(body.encode("utf-8"))
    rp = RobotFileParser()
    rp.set_url(f"https://{host}/robots.txt")
    rp.parse(body.splitlines())
    rec["doc_allowed"] = rp.can_fetch(B.UA, f"https://{host}{docpath}")
    rec["crawl_delay"] = rp.crawl_delay(B.UA)
    import re
    star = re.findall(r"user-agent:\s*\*\s*\n((?:(?!\nuser-agent).*\n?)*)", body, re.IGNORECASE)
    rec["star_disallows"] = [ln.split(":", 1)[1].strip() for blk in star[:1]
                             for ln in blk.splitlines() if ln.lower().startswith("disallow:")][:14]
    rec["class"] = "allowed" if rec["doc_allowed"] else "parked"
    return rec


def main():
    results = []
    for host, (family, docpath) in sorted(HOSTS.items()):
        saved = ROBOTS_DIR / f"{host}.txt"
        if saved.exists():
            body, status = saved.read_text(encoding="utf-8"), 200
        else:
            body, status = fetch_robots(host)
            if body:
                ROBOTS_DIR.mkdir(exist_ok=True)
                saved.write_text(body, encoding="utf-8")
        rec = classify(host, family, docpath, body, status)
        results.append(rec)
        print(f"{rec['class']:18s} {host} status={status} delay={rec.get('crawl_delay')} "
              f"disallows={rec.get('star_disallows')}", flush=True)
    (OUT / "robots_census.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    print("ROBOTS CLASSIFY DONE", flush=True)


if __name__ == "__main__":
    main()
