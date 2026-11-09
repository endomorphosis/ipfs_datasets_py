"""Polite Wayback/CDX client: <=1 req/s, TLS verified, UA set, state under $IPFS_DATASETS_LEGAL_WORKSPACE. Never contacts origin sites."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_WORLD = _ipfs_Path(_ipfs_os.environ.get("WORLD_LAW_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "world_law")))
_LEGAL_WS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_WORKSPACE", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_workspace")))
import requests,time,json,os,hashlib
UA='EndomorphosisCountyLawsBot/1.0 (research; Wayback <=1 req/s)'
_last=[0.0]
def get(url,params=None,timeout=60,retries=3):
    for i in range(retries):
        d=1.05-(time.time()-_last[0]); 
        if d>0: time.sleep(d)
        _last[0]=time.time()
        try:
            r=requests.get(url,params=params,headers={'User-Agent':UA},timeout=timeout)
        except requests.RequestException as e:
            time.sleep(5*(i+1)); continue
        if r.status_code in (429,503): time.sleep(30*(i+1)); continue
        return r
    return None
def cdx(url,**kw):
    p={'url':url,'output':'json','fl':'timestamp,original,statuscode,mimetype,length','filter':'statuscode:200'}; p.update(kw)
    r=get('https://web.archive.org/cdx/search/cdx',p,timeout=120)
    if r is None or r.status_code!=200: return None
    try: j=r.json()
    except Exception: return None
    return j[1:] if j else []
def snap(ts,orig):  # raw (id_) capture
    return get(f'https://web.archive.org/web/{ts}id_/{orig}',timeout=90)
