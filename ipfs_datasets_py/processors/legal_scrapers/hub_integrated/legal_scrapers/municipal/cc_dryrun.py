#!/usr/bin/env python3
"""Count-only Common Crawl dry run + HEAD reachability for municipal portals.
Ranged reads only against data.commoncrawl.org (cluster.idx binary search ->
matching cdx-*.gz blocks). No WARC fetches. Count capped per domain/collection.
Usage: python3 cc_dryrun.py [COLL ...]   (default CC-MAIN-2026-30 CC-MAIN-2026-21)
Writes /tmp/muni_dryrun.json"""
import json, sys, time, zlib, requests
BASE="https://data.commoncrawl.org/cc-index/collections/%s/indexes/"
UA={"User-Agent":"world-laws-recon/0.1"}; S=requests.Session(); S.headers.update(UA)
DOMAINS={
 "PL":["edziennik.mazowieckie.pl","dziennikiurzedowy.malopolska.uw.gov.pl","bip.gov.pl"],
 "CH":["lexfind.ch","fedlex.admin.ch"], "DK":["retsinformation.dk"], "NO":["lovdata.no"],
 "FI":["finlex.fi"], "SK":["slov-lex.sk"], "HR":["sluzbeni-glasnik.hr","zakon.hr"],
 "LT":["e-tar.lt"], "HU":["njt.hu"], "RO":["legislatie.just.ro"],
 "IE":["irishstatutebook.ie","dublincity.ie"], "LU":["legilux.public.lu"], "GR":["diavgeia.gov.gr"],
 "TW":["law.moj.gov.tw","law.gov.taipei","lawdata.kcg.gov.tw"], "PH":["lawphil.net","quezoncity.gov.ph"],
 "IN":["indiacode.nic.in","mcgm.gov.in"], "CO":["secretariajuridica.gov.co"], "CL":["bcn.cl"],
 "AR":["boletinoficial.buenosaires.gob.ar","infoleg.gob.ar"], "EC":["quito.gob.ec","registroficial.gob.ec"],
}
def surt(d): return ",".join(reversed(d.lower().split(".")))+")"
_sz={}
def rng(url,a,b):
    for i in range(4):
        try:
            r=S.get(url,headers={"Range":f"bytes={a}-{b}"},timeout=60)
            if r.status_code in (200,206): return r.content
        except Exception: pass
        time.sleep(2*(i+1))
    raise IOError(url)
def size(url):
    if url not in _sz: _sz[url]=int(S.head(url,timeout=30).headers["Content-Length"])
    return _sz[url]
def line_at(url,pos):
    buf=rng(url,pos,pos+8192); s=buf.find(b"\n")+1 if pos else 0
    e=buf.find(b"\n",s); return buf[s:e].decode(), pos+s
def blocks_for(coll,key):
    url=BASE%coll+"cluster.idx"; lo,hi=0,size(url)
    while hi-lo>16384:            # binary search for last line with surt < key
        mid=(lo+hi)//2; ln,_=line_at(url,mid)
        if ln.split(" ")[0]<key: lo=mid
        else: hi=mid
    chunk=rng(url,lo,lo+262144).decode(errors="ignore").splitlines()[1 if lo else 0:]
    out=[];prev=None
    for ln in chunk:
        k=ln.split(" ")[0]; f=ln.split("\t")
        if k<key: prev=f; continue
        if prev and not out: out.append(prev)
        if k.startswith(key) or k<key+"\xff": out.append(f)
        if not k.startswith(key.rstrip(")")): break
    if not out and prev: out=[prev]
    return out
def cc_count(coll,dom,cap=200):
    key=surt(dom); n=0
    for f in blocks_for(coll,key)[:6]:
        fn,off,ln=f[1],int(f[2]),int(f[3])
        raw=zlib.decompress(rng(BASE%coll+fn,off,off+ln-1),16+zlib.MAX_WBITS)
        for l in raw.decode(errors="ignore").splitlines():
            k=l.split(" ")[0]
            if (k.startswith(key) or k.startswith(key[:-1]+",")) and '"status": "200"' in l:
                n+=1
                if n>=cap: return n
    return n
def head(dom):
    err=None
    for s in ("https://","http://"):
        try:
            r=S.head(s+dom,timeout=15,allow_redirects=True)
            if r.status_code in (403,405): r=S.get(s+dom,timeout=15,stream=True)
            return r.status_code
        except Exception as e: err=type(e).__name__
    return err
if __name__=="__main__":
    colls=sys.argv[1:] or ["CC-MAIN-2026-30","CC-MAIN-2026-21"]; out={}
    for cc,doms in DOMAINS.items():
        for d in doms:
            n=[]
            for c in colls:
                try: n.append(cc_count(c,d))
                except Exception as e: n.append(type(e).__name__)
            h=head(d); out[f"{cc}:{d}"]={"cc":n,"head":h}
            print(cc,d,"cc200(cap200)=",n,"HEAD=",h,flush=True)
    json.dump({"collections":colls,"results":out},open("/tmp/muni_dryrun.json","w"),indent=1)
