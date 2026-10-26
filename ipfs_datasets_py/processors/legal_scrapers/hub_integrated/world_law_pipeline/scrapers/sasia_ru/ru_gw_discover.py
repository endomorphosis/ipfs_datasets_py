# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import json,re,requests,concurrent.futures as cf,collections
L=[json.loads(l) for l in open((_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + '/staging/sasia_ru/_ru/reach.jsonl'))]
live=[x for x in L if 'status' in x]
print('entries',len(L),'live',len(live),'places live',sum(len(x['places']) for x in live), collections.Counter(x['status'] for x in live).most_common(6))
errs=collections.Counter(next((v for k,v in x.items() if k.startswith('err_')),'?') for x in L if 'status' not in x); print('fail',errs.most_common(5))
def home(x):
    try:
        r=requests.get(f"{x['scheme']}://{x['host']}/",timeout=(10,25),headers={'User-Agent':'Mozilla/5.0 (compatible; WorldLawMunicipalResearch/1.0)'})
        hs=set(re.findall(r'https?://([a-z0-9\-]+(?:-r\d+\.gosweb)?\.gosuslugi\.ru)',r.text+r.url))
        hs={h for h in hs if h not in('www.gosuslugi.ru','gosuslugi.ru','pos.gosuslugi.ru','esia.gosuslugi.ru','lk.gosuslugi.ru') and not h.startswith(('pos','esia','lk.','www'))}
        own='gosuslugi.ru' in r.url or 'gw-' in r.text[:200000] and 'gosweb' in r.text
        return x, r.url if own else None, sorted(hs)
    except Exception: return x,None,[]
out=open((_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + '/staging/sasia_ru/_ru/gosweb_candidates.jsonl'),'w')
with cf.ThreadPoolExecutor(12) as ex:
    for x,own,hs in ex.map(home,live):
        if own or hs: out.write(json.dumps({'host':x['host'],'places':x['places'],'own':own,'linked':hs},ensure_ascii=False)+'\n'); out.flush()
