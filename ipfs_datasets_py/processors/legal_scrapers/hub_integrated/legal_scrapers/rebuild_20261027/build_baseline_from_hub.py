#!/usr/bin/env python3
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_WORLD = _ipfs_Path(_ipfs_os.environ.get("WORLD_LAW_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "world_law")))
_TESSDATA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_TESSDATA", str(_ipfs_Path.home() / ".ipfs_datasets" / "tessdata")))
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
# Same TSV format as countries-laws-verifier/tip31zm_save_baseline.py, built from Hub-downloaded staging_<cc>.
import hashlib, json, gc
from pathlib import Path
import pyarrow.parquet as pq
ST=Path(str(_SCRAPERS)); OUT=Path('/workspace/countries-laws-verifier/baseline_tip31zza'); OUT.mkdir()
CC='bo az al ao do et ir mw zm la lk tn rs'.split()
def sha(x): return hashlib.sha256(('' if x is None else str(x)).encode('utf-8','replace')).hexdigest()
def rowbytes(v): return ('\x1f'.join(('' if x is None else str(x)) for x in v)+'\n').encode('utf8','replace')
res={}
for cc in CC:
    lines=[]; pf=pq.ParquetFile(ST/f'staging_{cc}/data/laws.parquet',pre_buffer=False,buffer_size=65536)
    for b in pf.iter_batches(batch_size=64,columns=['id','text','title'],use_threads=False):
        ids,tx,ti=b.column(0).to_pylist(),b.column(1).to_pylist(),b.column(2).to_pylist()
        for i in range(b.num_rows): lines.append(f"{ids[i]}\t{sha(tx[i])}\t{sha(ti[i])}\n")
    (OUT/f'{cc}.laws.tsv').write_text(''.join(lines)); L=len(lines); gc.collect()
    cur={}; pf=pq.ParquetFile(ST/f'staging_{cc}/data/articles.parquet',pre_buffer=False,buffer_size=65536); cols=pf.schema.names
    for b in pf.iter_batches(batch_size=512,columns=cols,use_threads=False):
        d={n:b.column(n).to_pylist() for n in cols}; n=b.num_rows
        for i in range(n):
            lid=str(d.get('law_id',[None]*n)[i]); c,h=cur.get(lid,(0,None)); h=h or hashlib.sha256()
            h.update(rowbytes([d[c2][i] for c2 in cols])); cur[lid]=(c+1,h)
    (OUT/f'{cc}.articles.tsv').write_text(''.join(f"{k}\t{c}\t{h.hexdigest()}\n" for k,(c,h) in sorted(cur.items())))
    A=sum(v[0] for v in cur.values()); res[cc]=[L,A]; print(cc,L,A,flush=True); gc.collect()
json.dump(res,open(ST/'rebuild_20261027/baseline_counts.json','w'))
