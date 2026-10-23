"""France tranche 1 — robots census of candidate own-host services.

Candidate hosts are taken ONLY from grounded sources: the data.gouv
API metadata census (fr_census.py output) and the pilot's probe
result files. For each host we fetch the FULL robots.txt with the
retrying session (browser UA, 4 attempts — the pilot's truncated-read
lesson) and classify:

- parked: a User-agent:* group disallows the document path class
  (/api/ for ODS-style portals, / for whole-host bans, /resources…)
- allowed: robots fetched (or 404 = no rules) and nothing bars the
  document paths
- unreachable: robots could not be fetched after retries

We fetch robots.txt ONLY in this script — no document content.
"""
import json
import re
import sys
import time
from pathlib import Path
from urllib.robotparser import RobotFileParser

HF = Path.home() / "workspace" / "goals" / "world-municipal-law-coverage" / "hidden_files"
sys.path.insert(0, str(HF / "fr_pilot" / "scripts"))
import fr_build as B  # noqa: E402

OUT = HF / "fr_tranche1"

# host -> (family guess, example document path to test against robots)
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
    "data.blois.agglopolys.fr": ("agglopolys_portal", "/"),
    "trouver.datasud.fr": ("datasud", "/"),
    "www.datasud.fr": ("datasud", "/"),
    "datacat.datalocale.fr": ("datalocale", "/"),
    "geo.brest-metropole.fr": ("brest_geoportal", "/"),
    "www.brest.fr": ("ville_site", "/"),
    "www.ccpro.fr": ("cc_site", "/"),
    "open-data-chelles.opendata.arcgis.com": ("arcgis_hub", "/"),
    "services8.arcgis.com": ("arcgis_server", "/"),
}

fx = B.Fetcher()


def fetch_robots(host):
    url = f"https://{host}/robots.txt"
    body, status = None, None
    for i in range(4):
        try:
            r = fx.s.get(url, headers=B.HEADERS, timeout=60)
            status = r.status_code
            if status == 200:
                body = r.text
                break
            if status == 404:
                body = ""
                break
        except Exception as e:  # noqa: BLE001
            status = f"{type(e).__name__}"
        time.sleep(3 * (i + 1))
    return body, status


def main():
    results = []
    for host, (family, docpath) in sorted(HOSTS.items()):
        body, status = fetch_robots(host)
        rec = {"host": host, "family": family, "robots_status": status,
               "test_path": docpath}
        if body is None:
            rec["class"] = "unreachable"
        elif body == "":
            rec["class"] = "allowed_no_robots"
            rec["doc_allowed"] = True
        else:
            rec["robots_bytes"] = len(body.encode("utf-8"))
            (OUT / "robots").mkdir(exist_ok=True)
            (OUT / "robots" / f"{host}.txt").write_text(body, encoding="utf-8")
            rp = RobotFileParser()
            rp.set_url(f"https://{host}/robots.txt")
            rp.parse(body.splitlines())
            test_url = f"https://{host}{docpath}"
            rec["doc_allowed"] = rp.can_fetch(B.UA, test_url)
            rec["crawl_delay"] = rp.crawl_delay(B.UA)
            star = re.findall(r"user-agent:\s*\*\s*\n((?:(?!\nuser-agent).*\n?)*)",
                              body, re.IGNORECASE)
            rec["star_disallows"] = [ln.split(":", 1)[1].strip()
                                     for blk in star[:1]
                                     for ln in blk.splitlines()
                                     if ln.lower().startswith("disallow:")][:12]
            rec["class"] = "allowed" if rec["doc_allowed"] else "parked"
        results.append(rec)
        print(f"{rec['class']:18s} {host} status={status} "
              f"delay={rec.get('crawl_delay')} disallows={rec.get('star_disallows')}", flush=True)
        time.sleep(0.5)
    (OUT / "robots_census.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    print("ROBOTS CENSUS DONE", flush=True)


if __name__ == "__main__":
    main()
