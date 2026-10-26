# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import sys,glob,os,json,collections
sys.path.insert(0,(_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + '/pipeline'))
from schema import validate_file
S=(_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + '/staging/national')
tot=collections.Counter(); size=collections.Counter(); bad=[]; arch=collections.Counter()
for f in sorted(glob.glob(S+'/[A-Z][A-Z]/*.jsonl')):
    b=os.path.basename(f); cc=f.split('/')[-2]
    if b.startswith(('_','.')): continue
    n=sum(1 for _ in open(f))
    if 'archive' in b: arch[cc]+=n; continue
    try:
        r=validate_file(f)
    except Exception as e: bad.append((f,str(e)[:150])); continue
    if not r.get('ok') or r.get('bad_rows'): bad.append((f,r.get('bad_rows'),str(r.get('errors')[:1])[:150],r.get('file_errors')))
    tot[cc]+=n; size[cc]+=os.path.getsize(f)
print(json.dumps({'mine':dict(sorted(tot.items(),key=lambda x:-x[1])),'MB':{k:round(v/1e6) for k,v in size.items() if v>50e6},'archive_other_process':dict(arch),'bad':bad},indent=0))
