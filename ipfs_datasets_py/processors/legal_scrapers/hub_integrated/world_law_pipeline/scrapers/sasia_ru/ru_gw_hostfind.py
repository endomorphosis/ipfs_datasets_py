"""Retry crt.sh and Wayback CDX to enumerate *.gosuslugi.ru Gosweb hosts. Appends to _ru/gosweb_found.txt"""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import requests,re,time,json
OUT=(_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + '/staging/sasia_ru/_ru/gosweb_found.txt')
def save(hs,src):
    old=set(open(OUT).read().split()) if __import__('os').path.exists(OUT) else set()
    new=sorted(set(hs)-old)
    with open(OUT,'a') as f: f.write(''.join(h+'\n' for h in new))
    print(time.strftime('%T'),src,'found',len(hs),'new',len(new),flush=True)
pat=re.compile(r'([a-z0-9][a-z0-9\-]*(?:\.gosweb)?\.gosuslugi\.ru)')
for rnd in range(12):
    for q in ['%.gosweb.gosuslugi.ru','%.gosuslugi.ru']:
        try:
            r=requests.get('https://crt.sh/',params={'q':q,'output':'json','exclude':'expired'},timeout=300)
            if r.status_code==200: save(pat.findall(r.text.lower()),'crt '+q)
            else: print('crt',q,r.status_code,flush=True)
        except Exception as e: print('crt err',type(e).__name__,flush=True)
        time.sleep(60)
    for flt in ['original:.*/ofitsialno/dokumenty/.*','original:.*/o-munitsipalnom-obrazovanii/.*']:
        try:
            r=requests.get('https://web.archive.org/cdx/search/cdx',params={'url':'gosuslugi.ru','matchType':'domain','fl':'original','filter':flt,'collapse':'urlkey','limit':'50000'},timeout=300)
            if r.status_code==200: save(pat.findall(r.text.lower()),'wb '+flt)
            else: print('wb',r.status_code,flush=True)
        except Exception as e: print('wb err',type(e).__name__,flush=True)
        time.sleep(60)
    time.sleep(900)
