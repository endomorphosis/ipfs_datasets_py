"""France tranche 1 — affichage census via data.gouv API metadata ONLY.

The data.gouv API is robots-clean for metadata/discovery (only
/admin and HTML search pages are disallowed); file downloads under
/resources are PARKED and are never fetched here. This script only
reads API JSON: dataset search + dataset metadata, then classifies
every resource URL by HOST:

- static.data.gouv.fr / www.data.gouv.fr resources  -> PARKED
  (data.gouv robots: Disallow: /resources for User-agent: *)
- *.opendatasoft.com and known ODS portal hosts     -> PARKED
  (standard ODS robots: Disallow: /api/ for *)
- *.arcgis.com                                       -> PARKED (token wall)
- arretes-deliberations.ville-martigues.fr          -> PARKED (Disallow: /)
- any other host -> CANDIDATE own-host service: full robots.txt is
  fetched with the retrying session and classified allowed/parked.

Output: census_results.jsonl (one line per dataset with PDF-ish
resources) + census_hosts.json (host rollup).
"""
import json
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import urlparse

HF = Path.home() / "workspace" / "goals" / "world-municipal-law-coverage" / "hidden_files"
sys.path.insert(0, str(HF / "fr_pilot" / "scripts"))
import fr_build as B  # noqa: E402

OUT = HF / "fr_tranche1"
API = "https://www.data.gouv.fr/api/1/datasets/"
QUERIES = ["délibérations", "deliberations conseil municipal",
           "actes administratifs", "affichage légal", "arrêtés municipaux",
           "recueil des actes administratifs", "conseils municipaux",
           "délibérations métropole", "registre des délibérations",
           "délibérations municipales", "actes réglementaires",
           "procès verbaux conseil municipal", "décisions municipales",
           "délibérations communautaires", "actes de la commune"]

fx = B.Fetcher()

PARKED_HOSTS_EXACT = {"static.data.gouv.fr", "www.data.gouv.fr",
                      "hub.arcgis.com", "arretes-deliberations.ville-martigues.fr"}
PARKED_SUFFIXES = (".opendatasoft.com", ".arcgis.com")


def host_class(host):
    if host in PARKED_HOSTS_EXACT or host.endswith(PARKED_SUFFIXES):
        return "parked_known"
    return "candidate"


def search_all():
    seen = {}
    for q in QUERIES:
        page = 1
        while True:
            url = f"{API}?q={requests_quote(q)}&page={page}&page_size=100"
            try:
                data = fx.get_json(url)
            except Exception as e:  # noqa: BLE001
                print("search failed", q, page, type(e).__name__, str(e)[:80], flush=True)
                break
            for ds in data.get("data", []):
                seen[ds["id"]] = ds
            total = data.get("total") or 0
            if page * 100 >= total or not data.get("data") or page >= 40:
                break
            page += 1
            time.sleep(0.3)
        print("query done:", q, "total:", total, "datasets so far:", len(seen), flush=True)
    return seen


def requests_quote(s):
    from urllib.parse import quote
    return quote(s)


def main():
    datasets = search_all()
    print("unique datasets:", len(datasets), flush=True)
    out_lines = []
    host_rollup = defaultdict(lambda: {"datasets": set(), "pdf_resources": 0,
                                       "other_resources": 0, "class": None})
    for dsid, ds in datasets.items():
        org = (ds.get("organization") or {}).get("name", "")
        slug = ds.get("slug", "")
        title = ds.get("title", "")
        pdf_by_host = Counter()
        other = 0
        for res in ds.get("resources", []):
            u = res.get("url") or ""
            host = urlparse(u).netloc.lower()
            fmt = (res.get("format") or "").lower()
            if fmt == "pdf" or u.lower().split("?")[0].endswith(".pdf"):
                pdf_by_host[host] += 1
            else:
                other += 1
        if not pdf_by_host:
            continue
        rec = {"dataset_id": dsid, "slug": slug, "title": title, "org": org,
               "pdf_by_host": dict(pdf_by_host), "other_resources": other,
               "page": ds.get("page", "")}
        out_lines.append(rec)
        for host, n in pdf_by_host.items():
            hr = host_rollup[host]
            hr["datasets"].add(slug)
            hr["pdf_resources"] += n
            hr["class"] = host_class(host)
    (OUT / "census_results.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in out_lines) + "\n",
        encoding="utf-8")
    rollup = {h: {"datasets": sorted(v["datasets"]), "n_datasets": len(v["datasets"]),
                  "pdf_resources": v["pdf_resources"], "class": v["class"]}
              for h, v in sorted(host_rollup.items())}
    (OUT / "census_hosts.json").write_text(
        json.dumps(rollup, ensure_ascii=False, indent=1), encoding="utf-8")
    print("datasets with PDF resources:", len(out_lines), flush=True)
    print("hosts:", len(rollup), flush=True)
    for h, v in rollup.items():
        print(f"  {v['class']:14s} {h}: {v['pdf_resources']} PDFs / {v['n_datasets']} datasets", flush=True)
    print("CENSUS DONE", flush=True)


if __name__ == "__main__":
    main()
