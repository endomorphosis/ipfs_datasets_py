#!/usr/bin/env python3
"""Wave 10 step 2 helper: probe candidate FAOLEX filename prefixes via
Wayback CDX over the two FAO PDF hosts; report UNIQUE matching files
(snapshot rows != unique files — wave-9 VU lesson).
Usage: probe_prefixes.py cc:prefix1,prefix2 cc2:...  (cc is just a label)
Writes ../stats/prefix_probe.json
"""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import json, os, re, sys, time
import requests

WAVE10 = os.path.expanduser("~/workspace/goals/global-law-scraping-coverage/hidden_files/wave10")
S = requests.Session(); S.headers.update({'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) legal-data-research/1.0'})
HOSTS = ('faolex.fao.org', 'extwprlegs1.fao.org')

def probe(prefix):
    files = set()
    rows_total = 0
    for host in HOSTS:
        url = (f"https://web.archive.org/cdx/search/cdx?url={host}/docs/pdf/{prefix}*"
               f"&output=json&limit=5000&collapse=urlkey&fl=original,timestamp")
        for attempt in range(3):
            try:
                r = S.get(url, timeout=120)
                if r.status_code == 200 and r.text.strip().startswith('['):
                    rows = r.json()
                    rows_total += max(0, len(rows) - 1)
                    for orig, ts in rows[1:]:
                        fn = orig.split('/')[-1].split('?')[0].lower()
                        if re.fullmatch(rf"{prefix}\d+[a-z0-9]*\.pdf", fn):
                            files.add(fn)
                    break
            except Exception:
                time.sleep(3 * (attempt + 1))
    return rows_total, sorted(files)

def main():
    out_path = os.path.join(WAVE10, 'stats', 'prefix_probe.json')
    results = {}
    if os.path.isfile(out_path):
        results = json.load(open(out_path))
    for spec in sys.argv[1:]:
        label, _, prefs = spec.partition(':')
        results.setdefault(label, {})
        for p in prefs.split(','):
            p = p.strip().lower()
            if not p or p in results[label]:
                continue
            rows, files = probe(p)
            results[label][p] = {'snapshot_rows_collapsed': rows, 'unique_files': len(files),
                                 'sample': files[:5]}
            print(label, p, 'unique:', len(files), 'sample:', files[:3], flush=True)
            json.dump(results, open(out_path, 'w'), indent=1)

if __name__ == '__main__':
    main()
