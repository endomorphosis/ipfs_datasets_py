#!/usr/bin/env python3
"""Guarded launcher for US local (US_COUNTY queue entry; PREPPED, NOT launched). Refuses: markers, already running, IT DAIT / FR SCDL not done or running,
>=3 collectors running, MemAvail<4608 (4.5G), dryrun fail. Starts us_local_supervise.py detached; log /workspace/logs/us_local_collect_<ts>.log."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_WORLD = _ipfs_Path(_ipfs_os.environ.get("WORLD_LAW_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "world_law")))
_TESSDATA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_TESSDATA", str(_ipfs_Path.home() / ".ipfs_datasets" / "tessdata")))
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os, sys, time, subprocess
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); from strict_mem_guard import memavail
B = str(_CORPORA) + '/us_local'
STOPS = [f'{B}/STOP_US_LOCAL', '/workspace/logs/STOP_US_LOCAL', f'{B}/HOLD_US_LOCAL', '/workspace/logs/HOLD_US_LOCAL']
pg = lambda rx: bool(subprocess.run(['pgrep', '-f', rx], capture_output=True).stdout.strip())
if [s for s in STOPS if os.path.exists(s)]: print('REFUSE markers'); sys.exit(1)
if pg(r'us_local_(collect|supervise)\.py'): print('REFUSE already running'); sys.exit(1)
for nm, rx, done in [('FR SCDL', r'fr_scdl_(collect|supervise)\.py', str(_CORPORA) + '/fr_scdl/FR_SCDL_DONE'), ('IT DAIT', r'it_dait_(collect|supervise)\.py', str(_CORPORA) + '/it_dait/IT_DAIT_DONE')]:
    if pg(rx) or not os.path.exists(done): print('REFUSE queued after', nm); sys.exit(1)
n = sum(pg(rx) for rx in [r'nl_municipal_collect|nlm_.*collect\.py full', r'nlm2_collect\.py full', r'es_seue_collect\.py', r'fr_scdl_collect\.py', r'it_dait_collect\.py', r'nl_prov\w*_collect\.py'])
if n >= 3: print('REFUSE 3 collectors running', n); sys.exit(1)
m = memavail()
if m < 4608: print('REFUSE MemAvail', m); sys.exit(1)
if subprocess.call([sys.executable, '/workspace/scripts/us_local_collect.py', 'dryrun'], stdout=subprocess.DEVNULL) != 0: print('REFUSE dryrun failed'); sys.exit(1)
ts = time.strftime('%Y%m%dT%H%M%S'); lg = f'/workspace/logs/us_local_collect_{ts}.log'
p = subprocess.Popen([sys.executable, '/workspace/scripts/us_local_supervise.py'], stdout=open(lg, 'a'), stderr=subprocess.STDOUT, start_new_session=True, cwd='/workspace')
print('LAUNCHED supervisor pid', p.pid, 'log', lg, 'MemAvail', m)
