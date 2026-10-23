#!/usr/bin/env python3
"""Wave 11: fresh live row counts (parquet footer via Range) for the repos
this wave touches. Writes wave11/stats/live_counts.json."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import json, os, sys
sys.path.insert(0, os.path.expanduser('~/workspace/goals/global-law-scraping-coverage/hidden_files/wave10/scripts'))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from rank_repos import footer_rows
from common11 import WAVE11, TARGETS

REPOS = {}
for cc, (repo, *_rest) in sorted(TARGETS.items()):
    REPOS.setdefault(repo, []).append(cc)

out = {}
for repo, ccs in sorted(REPOS.items()):
    try:
        rows, size = footer_rows(repo, 'data/laws.parquet')
        out[repo] = {'rows': rows, 'bytes': size, 'ccs': ccs}
        print(repo, rows, flush=True)
    except Exception as e:
        out[repo] = {'error': f'{type(e).__name__}: {e}'[:200], 'ccs': ccs}
        print(repo, 'ERROR', out[repo]['error'], flush=True)
json.dump(out, open(os.path.join(WAVE11, 'stats', 'live_counts.json'), 'w'), indent=1)
print('wrote live_counts.json')
