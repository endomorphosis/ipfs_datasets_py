#!/usr/bin/env python3
"""NL-M tranche 1 inventory (offline): ids >=600000 from index/scan overlaid by index/rescan_bom; availability in out_packed / out / raw."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os, gzip, json, glob, collections, sys, resource
B='{_CORPORA}/nl_municipal'; LO=600000
st={}; info={}
for p in sorted(glob.glob(f'{B}/index/scan/*.jsonl.gz')):
    hi=int(os.path.basename(p).split('.')[0])
    if hi < LO: continue
    with gzip.open(p,'rt') as f:
        for l in f:
            r=json.loads(l)
            if r['id']>=LO: st[r['id']]=r['s']; 
            if r['s']=='ok' and r['id']>=LO: info[r['id']]=(r.get('jur'),r.get('atype'),r.get('rtype'))
resc=set()
for p in sorted(glob.glob(f'{B}/index/rescan_bom/*.jsonl.gz')):
    with gzip.open(p,'rt') as f:
        for l in f:
            r=json.loads(l)
            if r['id']>=LO:
                st[r['id']]=r['s']; resc.add(r['id'])
                if r['s']=='ok': info[r['id']]=(r.get('jur'),r.get('atype'),r.get('rtype'))
                else: info.pop(r['id'],None)
c=collections.Counter(st.values())
ok=[i for i,s in st.items() if s=='ok']
packed=set()
m=json.load(open(f'{B}/index/out_packed/manifest.json'))
for name in m['shards']:
    with gzip.open(f'{B}/index/out_packed/{name}','rt') as f:
        for l in f: packed.add(int(l[:60].split("CVDR",1)[1].split(chr(34))[0]))
outl=set(int(x[4:].split('.')[0]) for x in os.listdir(f'{B}/out/laws')); outa=set(int(x[4:].split('.')[0]) for x in os.listdir(f'{B}/out/articles'))
rawm=set(int(x[4:].split('.')[0]) for x in os.listdir(f'{B}/raw/manifest') if x.startswith('CVDR'))
av=collections.Counter()
for i in ok:
    if i in resc and i in outl and i in outa: av['rescan_out']+=1
    elif i in packed and i not in resc: av['packed']+=1
    elif i in outl and i in outa: av['out_loose']+=1
    elif i in rawm: av['raw_only']+=1
    else: av['missing']+=1
ids=sorted(st); 
print(json.dumps(dict(n_ids_scanned=len(st), id_min=ids[0], id_max=ids[-1], status=c, n_ok=len(ok), n_rescan_ids=len(resc),
  rescan_ok=sum(1 for i in resc if st[i]=='ok'), availability=av, packed_total=len(packed), packed_ok_overlap=len(packed&set(ok)),
  rescan_ok_in_packed=len(packed & {i for i in resc if st[i]=='ok'}),
  by_atype=collections.Counter(v[1] for v in info.values()), n_jur=len({v[0] for v in info.values()}),
  rss_mb=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss//1024), default=str, indent=1))
