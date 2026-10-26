"""Scan our staged archive docs (staging/asia_latam/*/*.archive*.jsonl) against the cached archived
bodies for robots meta noarchive/noindex. Read-only; writes _archive_work/_meta/hits.json."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import sys as _sys; _sys.path.insert(0, (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/pipeline/scrapers/asia_latam/common")); from jsonl_io import open_text, glob_jsonl, locate  # noqa: E402,E702
import json,glob,gzip,sys,collections,re
from robots_meta import robots_meta_flags
C=(_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + '/pipeline/archive/_cache/body')
OUT=(_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + '/staging/asia_latam/_archive_work/_meta/hits.json')
def main():
    idx={}
    for j in glob.glob(C+'/*/*.json'):
        try: m=json.load(open(j))
        except Exception: continue
        idx.setdefault(m.get('archive_url'),[]).append(j)
    res=collections.defaultdict(collections.Counter); hits=[]
    for f in glob_jsonl((_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + '/staging/asia_latam/*/*.archive*.jsonl')):
        cc=f.split('/')[-2]
        for l in open_text(f):
            r=json.loads(l); urls=[r.get('archive_url')]
            a=(r.get('extra_metadata') or {}).get('archive') or {}
            urls+=[a.get('archive_url')]+[p.get('archive_url') for p in (a.get('pdfs') or []) if isinstance(p,dict)]
            urls=[u for u in dict.fromkeys(urls) if u]
            host=re.sub(r'https?://([^/]+).*',r'\1',r.get('original_url') or '')
            key=cc+' '+('g-reiki' if 'g-reiki' in host else host if 'd1-law' in host else '')
            fl=set(); found=0
            for u in urls:
                for j in idx.get(u,[]):
                    found+=1; m=json.load(open(j))
                    b=gzip.open(j[:-5]+'.bin.gz').read()
                    fl|=set(robots_meta_flags(b,content_type=m.get('content_type','')))
            res[key]['docs']+=1; res[key]['body_cached' if found else 'body_missing']+=1
            for x in fl: res[key][x]+=1
            hits.append({'file':f,'doc_id':r['doc_id'],'flags':sorted(fl),'cached':found,'urls':urls})
    for k,v in sorted(res.items()): print(k,dict(v))
    json.dump(hits,open(OUT,'w'))
if __name__=='__main__': main()
