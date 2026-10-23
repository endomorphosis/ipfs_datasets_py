# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import json,requests,concurrent.futures as cf
L=[json.loads(l) for l in open((_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + '/staging/sasia_ru/_ru/reach.jsonl'))]
bad=[x for x in L if 'status' not in x]
def chk(x):
    for s in ('https','http'):
        try:
            r=requests.get(f"{s}://{x['host']}/robots.txt",timeout=(20,30),headers={'User-Agent':'Mozilla/5.0 (world-law municipal research)'})
            return {**x,'retry_status':r.status_code,'scheme':s}
        except Exception as e: x['retry_err_'+s]=type(e).__name__
    return x
with cf.ThreadPoolExecutor(12) as ex, open((_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + '/staging/sasia_ru/_ru/reach_retry.jsonl'),'w') as o:
    for r in ex.map(chk,bad): o.write(json.dumps(r,ensure_ascii=False)+'\n'); o.flush()
