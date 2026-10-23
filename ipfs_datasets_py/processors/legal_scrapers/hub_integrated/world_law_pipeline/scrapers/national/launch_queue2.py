"""Second (Wayback) queue launcher: replaces the tail of wayback_watch.sh.
Robots-gates top-2 hosts with RFC 9309 (common/robots.py: unreachable/5xx => disallow-all).
Excludes blocked_from_box CCs (handled by the separate archive pipeline) and coordinator skip-list."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import json, sys, os, subprocess
sys.path.insert(0,(_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + '/pipeline/scrapers/national/common'))
from robots import robots_for, UA
S=(_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + '/staging/national'); N=(_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + '/pipeline/scrapers/national')
EXCL={'MX','EG','RU','BD','AT','IR','TH',  # blocked_from_box -> archive pipeline owns these
      'NZ','SG','KE','PH','ID','CN','VN','PE','KW'}  # coordinator skip / separately handled / stopped
cat={e['country_code']:e['collector'] for e in json.load(open(N+'/snapshot_catalog.json'))['entries'] if not e.get('alias_of')}
meta=json.load(open(S+'/_collector_meta.json'))
ok=[]
for l in open(S+'/_logs/smoke/results_retest.jsonl'):
    r=json.loads(l); cc=r['cc']
    if r['status']!='works': continue
    if cc in EXCL: print(cc,'excluded'); continue
    if os.path.exists(f'{S}/_logs/full/{cc}.log'): print(cc,'already has full run'); continue
    hosts=meta[cc]['hosts'][:2]; res=[]
    for h in hosts:
        rb,info=robots_for('https://'+h+'/'); res.append((h,rb.can_fetch(UA,'https://'+h+'/'),info.get('rule') or info.get('status')))
    good=all(x[1] for x in res); print(cc,'robots','ok' if good else 'DISALLOWED',res)
    if good: ok.append(f"{cc}:{cat[cc]}")
print('QUEUE',' '.join(ok))
if ok and '--launch' in sys.argv:
    log=open(S+'/_logs/full/_queue_wayback.log','a')
    p=subprocess.Popen([sys.executable,N+'/queue_full.py',*ok],stdout=log,stderr=subprocess.STDOUT,env={**os.environ,'MAX_CONC':'2'},start_new_session=True)
    print('queue pid',p.pid)
