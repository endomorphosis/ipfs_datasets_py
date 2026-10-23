"""Low-memory Common Crawl CDX lookup via the zipnum index files on data.commoncrawl.org (no index.commoncrawl.org server).
- cluster.idx cached on disk per crawl (out/afme/_ccidx/<crawl>/cluster.idx) and bisected on disk (seek), never loaded in RAM
- the cdx-*.gz blocks are range-fetched and streamed; candidates go to a tmp file, deduped with `sort -S 64M` (external sort)
usage: afme_ccidx.py cfg.json   cfg: {cc, outdir (rel. to out/afme), crawls[], surt_prefixes[], url_regex, exclude_regex, status:"200"}
output: out/afme/<outdir>/_cdx_<CC>.jsonl (latest capture per URL: url, mime, mime-detected, status, digest, length, offset, filename, timestamp, crawl)"""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import os,re,sys,json,gzip,time,subprocess,tempfile,urllib.request
UA="world-municipal-law-research/1.0 (afme lane; CC index files)"
cfg=json.load(open(sys.argv[1])); BASE=(_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/out/afme")
OUT=f"{BASE}/{cfg['outdir']}"; os.makedirs(OUT,exist_ok=True)
URX=re.compile(cfg.get("url_regex",".")); EXC=re.compile(cfg.get("exclude_regex","$^")); ST=cfg.get("status","200")
last=[0.0]
def get(url,rng=None,tries=6):
    d=5
    for i in range(tries):
        w=0.3-(time.time()-last[0]); time.sleep(max(0,w)); last[0]=time.time()
        try:
            h={"User-Agent":UA}; 
            if rng: h["Range"]=rng
            return urllib.request.urlopen(urllib.request.Request(url,headers=h),timeout=120).read()
        except urllib.error.HTTPError as e:
            if e.code==404: raise
            time.sleep(d); d*=2
        except Exception: time.sleep(d); d*=2
    raise RuntimeError("fetch failed "+url)
def cluster(crawl):
    p=f"{BASE}/_ccidx/{crawl}/cluster.idx"
    if not os.path.exists(p):
        os.makedirs(os.path.dirname(p),exist_ok=True)
        u=f"https://data.commoncrawl.org/cc-index/collections/{crawl}/indexes/cluster.idx"
        with urllib.request.urlopen(urllib.request.Request(u,headers={"User-Agent":UA}),timeout=600) as r, open(p+".tmp","wb") as f:
            while True:
                b=r.read(1<<20)
                if not b: break
                f.write(b)
        os.rename(p+".tmp",p)
    return p
def first_ge(f,size,key):
    """byte offset of the last line whose key < key (block that may contain key)."""
    lo,hi=0,size
    while hi-lo>1:
        mid=(lo+hi)//2; f.seek(mid); f.readline(); pos=f.tell()
        if pos>=size: hi=mid; continue
        k=f.readline().split(b" ",1)[0]
        if k<key: lo=mid
        else: hi=mid
    f.seek(lo); 
    if lo: f.readline()
    return f.tell()
tmp=tempfile.NamedTemporaryFile("w",delete=False,dir=OUT,suffix=".cands"); n=0
for crawl in cfg["crawls"]:
    try: ci=cluster(crawl)
    except Exception as e: print(crawl,"cluster.idx failed",repr(e)[:100],flush=True); continue
    size=os.path.getsize(ci)
    with open(ci,"rb") as f:
        for pre in cfg["surt_prefixes"]:
            pk=pre.encode(); start=first_ge(f,size,pk)
            # step back one block line so the block containing the first key is included
            f.seek(max(0,start-4096)); 
            if start>4096: f.readline()
            blocks=[]
            while True:
                l=f.readline()
                if not l: break
                k=l.split(b" ",1)[0]
                parts=l.rstrip(b"\n").split(b"\t")
                if k<pk: blocks=[parts]; continue  # keep only the last block before prefix
                if not k.startswith(pk): blocks.append(parts); break
                blocks.append(parts)
            scanned=c0=0
            for parts in blocks:
                fn,off,ln=parts[1].decode(),int(parts[2]),int(parts[3])
                try: raw=gzip.decompress(get(f"https://data.commoncrawl.org/cc-index/collections/{crawl}/indexes/{fn}",f"bytes={off}-{off+ln-1}"))
                except Exception as e: print("block fail",fn,off,repr(e)[:80],flush=True); continue
                for line in raw.split(b"\n"):
                    if not line.startswith(pk): continue
                    scanned+=1
                    try: surt,ts,js=line.decode("utf-8","replace").split(" ",2); j=json.loads(js)
                    except Exception: continue
                    u=j.get("url","")
                    if j.get("status")!=ST or not URX.search(u) or EXC.search(u): continue
                    rec={"url":u,"mime":j.get("mime"),"mime-detected":j.get("mime-detected"),"status":j.get("status"),"digest":j.get("digest"),
                         "length":j.get("length"),"offset":j.get("offset"),"filename":j.get("filename"),"timestamp":ts,"crawl":crawl}
                    tmp.write(u+"\t"+ts+"\t"+json.dumps(rec)+"\n"); c0+=1; n+=1
            print(crawl,pre,"blocks",len(blocks),"scanned",scanned,"raw cands",c0,flush=True)
tmp.close()
out=f"{OUT}/_cdx_{cfg['cc']}.jsonl"
# external sort: by url asc, timestamp desc; keep first per url
subprocess.run(f"LC_ALL=C sort -S 64M -T {OUT} -t$'\\t' -k1,1 -k2,2r -o {tmp.name}.s {tmp.name}",shell=True,executable="/bin/bash",check=True)
prev=None; m=0
with open(out+".tmp","w") as o, open(tmp.name+".s") as sf:
    for line in sf:
        line=line.rstrip("\n")
        u,ts,js=line.split("\t",2)
        if u==prev: continue
        prev=u; o.write(js+"\n"); m+=1
os.rename(out+".tmp",out); os.remove(tmp.name); os.remove(tmp.name+".s")
print("wrote",out,m,flush=True)
