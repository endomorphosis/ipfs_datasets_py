# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import csv, requests, time, io
UA = "JusticeDAO-WorldLaw/1.0 (+https://github.com/endomorphosis/ipfs_datasets_py)"
cand = [r for r in csv.DictReader(open((_wl_os.environ.get("GLOBAL_MUNICIPALITIES_ROOT", "/workspace/global_municipalities") + '/global_municipalities_candidate.csv'))) if r['country_code'] == 'PE']
qids = [r['qid'] for r in cand]
out = []
for i in range(0, len(qids), 300):
    vals = " ".join("wd:" + q for q in qids[i:i+300])
    q = f"""SELECT ?item ?itemLabel ?p1 ?p1Label ?p2 ?p2Label ?site ?alias WHERE {{ VALUES ?item {{ {vals} }}
      OPTIONAL {{ ?item wdt:P131 ?p1 . OPTIONAL {{ ?p1 wdt:P131 ?p2 . }} }}
      OPTIONAL {{ ?item wdt:P856 ?site . }}
      OPTIONAL {{ ?item skos:altLabel ?alias FILTER(LANG(?alias)="es") }}
      SERVICE wikibase:label {{ bd:serviceParam wikibase:language "es,en". }} }}"""
    for k in range(4):
        r = requests.get("https://query.wikidata.org/sparql", params={"query": q}, headers={"Accept": "text/csv", "User-Agent": UA}, timeout=120)
        if r.status_code == 200: break
        time.sleep(10)
    out += list(csv.DictReader(io.StringIO(r.text)))
    time.sleep(2)
with open('wd_pe_hier.csv', 'w', newline='') as fh:
    w = csv.DictWriter(fh, fieldnames=list(out[0].keys())); w.writeheader(); w.writerows(out)
print(len(out))
