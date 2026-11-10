# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import requests, json, time, collections
s=requests.Session(); s.headers["User-Agent"]="python-requests (research collection of official state legislation texts; polite)"
def v(x,k):
    y=x.get(k); return y.get('__value__') if isinstance(y,dict) else y
SITES={"NSW":("legislation.nsw.gov.au","NSW_PCO-BrowseDataSource"),"QLD":("www.legislation.qld.gov.au","OQPC-BrowseDataSource")}
for st,(host,ds) in SITES.items():
    allr={}
    for pt in ["act.reprint","reprint","epi.reprint","sl.reprint","epi"]:
        start=1
        while True:
            p={"ds":ds,"collection":"OQPC.toc","subset":"browse","expression":f'PitValid=@pointInTime(20260928000000) AND PrintType="{pt}"',"count":1000,"sortField":"sort.title","sortDirection":"asc"}
            if start>1: p["start"]=start
            r=s.get(f"https://{host}/projectdata",params=p,timeout=300)
            if r.status_code!=200: print(st,pt,start,r.status_code,r.text[:150],flush=True); break
            d=r.json(); L=d.get('data',[]); L=L if isinstance(L,list) else [L]
            tot=int(d['totalCount']['__value__'])
            for x in L:
                if x: allr[(v(x,'id'),v(x,'print.type'))]=x
            print(st,pt,start,tot,len(L),flush=True)
            start+=1000; time.sleep(2)
            if start>tot or not L: break
        time.sleep(2)
    L=list(allr.values())
    json.dump(L,open(f"{_CORPORA}/au_subnational/index/{st}_pit_all.json","w"))
    c=collections.Counter((v(x,'print.type'),v(x,'type'),v(x,'repealed')) for x in L)
    for k,n in c.most_common(): print('  ',st,k,n,flush=True)
