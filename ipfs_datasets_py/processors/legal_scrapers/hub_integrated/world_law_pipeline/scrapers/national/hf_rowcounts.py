# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
# Read-only: parquet footer row counts for endomorphosis/ipfs_*_laws datasets. No uploads.
import json, re
import pyarrow.parquet as pq
from huggingface_hub import HfFileSystem
fs=HfFileSystem()
rows=[json.loads(l) for l in open((_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + '/staging/national/hf_national_datasets.jsonl'))]
out=open((_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + '/staging/national/hf_rowcounts.jsonl'),'w')
for r in rows:
    if not re.match(r'endomorphosis/ipfs_.*_(laws|local_acts)$', r['id']): continue
    rec={'id':r['id'],'last_modified':r['last_modified'],'bytes':r.get('bytes')}
    try:
        files=[f for f in fs.ls(f"datasets/{r['id']}/data", detail=False) if f.endswith('.parquet')]
        for f in files:
            name=f.rsplit('/',1)[-1]
            with fs.open(f,'rb') as fh:
                rec[name]=pq.ParquetFile(fh).metadata.num_rows
    except Exception as e:
        rec['err']=str(e)[:150]
    out.write(json.dumps(rec)+'\n'); out.flush()
print('done')
