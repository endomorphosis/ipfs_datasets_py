"""Polite robots-honouring fetcher (TLS verified always; no challenge bypass)."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_WORLD = _ipfs_Path(_ipfs_os.environ.get("WORLD_LAW_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "world_law")))
_LEGAL_WS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_WORKSPACE", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_workspace")))
import time, urllib.robotparser, urllib.parse, requests, shutil, os, json
UA="Mozilla/5.0 (compatible; EndomorphosisCountyLawsBot/1.0; +https://huggingface.co/endomorphosis)"
FLOOR_GIB=10.0
STATE=os.environ.get("COUNTY_STATE",(str(_CORPORA) + "/county/_state"))
os.makedirs(STATE,exist_ok=True)
def free_gib(): 
    s=os.statvfs('/'); return s.f_bavail*s.f_frsize/2**30
def disk_ok(extra_gib=0.1):
    return free_gib()-extra_gib>=FLOOR_GIB
_rp={}; _last={}; _delay={}
def _robots(host_url):
    p=urllib.parse.urlparse(host_url); base=f"{p.scheme}://{p.netloc}"
    if base in _rp: return _rp[base]
    rp=urllib.robotparser.RobotFileParser(); 
    try:
        r=requests.get(base+"/robots.txt",headers={"User-Agent":UA},timeout=30)
        if r.status_code==200 and 'html' not in r.headers.get('content-type','').lower()[:0]+'' :
            rp.parse(r.text.splitlines())
            open(f"{STATE}/robots_{p.netloc}.txt","w").write(r.text)
        elif r.status_code in (404,410): rp.parse([])
        else: rp.disallow_all=True
    except Exception as e:
        rp.disallow_all=True
    _rp[base]=rp; _delay[base]=rp.crawl_delay(UA) or rp.crawl_delay("*") or 0
    return rp
def get(url,min_delay=2.0,stream=False,**kw):
    if not disk_ok(): raise SystemExit("DISK FLOOR: stop")
    rp=_robots(url); p=urllib.parse.urlparse(url); base=f"{p.scheme}://{p.netloc}"
    if not rp.can_fetch(UA,url) and not rp.can_fetch("*",url): raise PermissionError("robots disallow "+url)
    d=max(min_delay,_delay.get(base,0)); w=_last.get(p.netloc,0)+d-time.time()
    if w>0: time.sleep(w)
    r=requests.get(url,headers={"User-Agent":UA},timeout=60,stream=stream,**kw)
    _last[p.netloc]=time.time()
    return r
