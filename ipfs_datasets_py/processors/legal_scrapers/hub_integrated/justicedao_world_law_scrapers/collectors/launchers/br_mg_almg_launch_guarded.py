#!/usr/bin/env python3
"""Guarded launcher BR_MG_ALMG (PREPPED, NOT launched). Refuses: markers, already running, previous queue entry (second_collector.json) not DONE, >=3 collectors, MemAvail<4608, dryrun fail."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_WORLD = _ipfs_Path(_ipfs_os.environ.get("WORLD_LAW_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "world_law")))
_TESSDATA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_TESSDATA", str(_ipfs_Path.home() / ".ipfs_datasets" / "tessdata")))
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os, sys, time, json, subprocess
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); from strict_mem_guard import memavail
B = str(_CORPORA) + '/br_mg_almg'; J = f'{B}/jobs.json'
pg = lambda rx: bool(subprocess.run(['pgrep', '-f', rx], capture_output=True).stdout.strip())
if [s for s in [f'{B}/STOP_BR_MG_ALMG', '/workspace/logs/STOP_BR_MG_ALMG', f'{B}/HOLD_BR_MG_ALMG', '/workspace/logs/HOLD_BR_MG_ALMG'] if os.path.exists(s)]: print('REFUSE markers'); sys.exit(1)
if pg(r'add_collect\.py.*br_mg_almg/|br_mg_almg_supervise'): print('REFUSE already running'); sys.exit(1)
Q = json.load(open('/workspace/logs/second_collector.json'))['queued_next']; i = [q['name'] for q in Q].index('BR_MG_ALMG')
prev = Q[i - 1] if i else None
if prev and not any(os.path.exists(m) for m in prev.get('done_markers', [])): print('REFUSE predecessor not done', prev['name']); sys.exit(1)
n = sum(pg(rx) for rx in [r'nl_municipal_collect|nlm_.*collect\.py full', r'nlm2_collect\.py full', r'es_seue_collect\.py', r'fr_scdl_collect\.py', r'it_dait_collect\.py', r'add_collect\.py', r'us_.*collect\.py'])
if n >= 3: print('REFUSE 3 collectors running'); sys.exit(1)
m = memavail()
if m < 4608: print('REFUSE MemAvail', m); sys.exit(1)
if subprocess.call([sys.executable, '/workspace/scripts/add_collect.py', J, 'dryrun'], stdout=subprocess.DEVNULL) != 0: print('REFUSE dryrun failed'); sys.exit(1)
ts = time.strftime('%Y%m%dT%H%M%S'); lg = f'/workspace/logs/br_mg_almg_collect_{ts}.log'
p = subprocess.Popen([sys.executable, '/workspace/scripts/br_mg_almg_supervise.py'], stdout=open(lg, 'a'), stderr=subprocess.STDOUT, start_new_session=True, cwd='/workspace')
print('LAUNCHED supervisor pid', p.pid, 'log', lg, 'MemAvail', m)
