"""Rebuild out/afme/_ocr_queue.jsonl (pdf_collect lane 'afme' input) from the Hub parquet shards, read-only.
- waits for the Normalizer run_loop hold to be released (state/HOLD_RUN_LOOP.md gone and no hold_run_loop.py process)
- afme places = state/confirmed_batches/afme.jsonl (cc, place_key) -> world_law/data/<CC>/<place_key>_html*.parquet
- HTTP range reads only (footer + projected column chunks), >=2 s between requests, exponential backoff on 429/5xx; no PDF fetches
- checkpoint: _hubscan/done.txt (files scanned), _hubscan/rows.jsonl (content_complete=false rows); queue rewritten atomically every 100 files + at end
"""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import io,os,re,sys,json,time,glob,subprocess,collections,datetime
import requests, pyarrow.parquet as pq
WL=_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law"); D=f"{WL}/out/afme/_hubscan"; Q=f"{WL}/out/afme/_ocr_queue.jsonl"
REPO="endomorphosis/world_municipal_law"; BASE=f"https://huggingface.co/datasets/{REPO}/resolve/main/"
TOK=os.environ.get("HF_TOKEN"); H={"User-Agent":"world-municipal-law-afme-hubscan/1.0"}
if TOK: H["Authorization"]=f"Bearer {TOK}"
COLS=["place_id","country_code","doc_id","source_url","original_url","archive_url","archive_source","archive_crawl_id","archive_timestamp",
      "source_policy","source_platform","content_complete","content_format","title_native","extra_metadata"]
def log(*a): print(datetime.datetime.now().strftime("%H:%M:%S"),*a,flush=True)
# ---- hold
def held():
    if os.path.exists(f"{WL}/state/HOLD_RUN_LOOP.md"): return True
    return subprocess.run(["pgrep","-f","hold_run_loop.py"],capture_output=True).returncode==0
while held(): log("run_loop hold active; waiting"); time.sleep(120)
log("hold released")
# ---- throttled session
S=requests.Session(); last=[0.0]; NREQ=[0]
def req(url,headers,allow_redirects=True):
    d=2.0
    for i in range(8):
        w=2.0-(time.time()-last[0])
        if w>0: time.sleep(w)
        last[0]=time.time(); NREQ[0]+=1
        try: r=S.get(url,headers={**H,**headers} if "huggingface.co" in url else headers,allow_redirects=allow_redirects,timeout=90)
        except Exception as e: log("neterr",repr(e)[:100]); time.sleep(d); d=min(d*2,600); continue
        if r.status_code in (429,500,502,503,504):
            ra=r.headers.get("Retry-After"); s=float(ra) if ra and ra.replace('.','',1).isdigit() else d
            log("backoff",r.status_code,s); time.sleep(s); d=min(d*2,600); continue
        return r
    raise RuntimeError("giving up "+url)
class RangeFile(io.RawIOBase):
    def __init__(s,path):
        s.path=path; s.pos=0; s.cache={}
        r=req(BASE+path,{"Range":"bytes=-131072"})
        if r.status_code not in (200,206): raise RuntimeError(f"http {r.status_code}")
        cr=r.headers.get("Content-Range","")
        s.size=int(cr.split("/")[-1]) if "/" in cr else len(r.content)
        s.url=r.url  # signed CDN url after redirect (reused for column reads)
        s.tail_start=s.size-len(r.content); s.tail=r.content
    def readable(s): return True
    def seekable(s): return True
    def tell(s): return s.pos
    def seek(s,o,wh=0):
        s.pos={0:o,1:s.pos+o,2:s.size+o}[wh]; return s.pos
    def read(s,n=-1):
        if n<0: n=s.size-s.pos
        a,b=s.pos,min(s.size,s.pos+n)
        if a>=s.tail_start: data=s.tail[a-s.tail_start:b-s.tail_start]
        else:
            r=req(s.url,{"Range":f"bytes={a}-{b-1}"})
            if r.status_code==403 or r.status_code>=400:   # signed url expired -> re-resolve
                r=req(BASE+s.path,{"Range":f"bytes={a}-{b-1}"})
            data=r.content
        s.pos=b; return data
    def readinto(s,buf):
        d=s.read(len(buf)); buf[:len(d)]=d; return len(d)
# ---- targets
led=collections.OrderedDict()
for l in open(f"{WL}/state/confirmed_batches/afme.jsonl"):
    r=json.loads(l); led[(r["cc"],r["place_key"])]=1
lst=f"{D}/repo_files.json"
if not os.path.exists(lst):
    from huggingface_hub import HfApi
    json.dump(HfApi(token=TOK).list_repo_files(REPO,repo_type="dataset"),open(lst,"w"))
files=json.load(open(lst)); byk=collections.defaultdict(list)
for f in files:
    m=re.match(r"world_law/data/([A-Z]{2})/(.+?)_html(?:[._-].*)?\.parquet$",f)
    if m: byk[(m.group(1),m.group(2))].append(f)
targets=[f for k in led for f in sorted(byk.get(k,[]))]
missing=[k for k in led if k not in byk]
log("afme places",len(led),"hub files",len(targets),"places not on hub",len(missing))
json.dump(missing,open(f"{D}/missing_on_hub.json","w"))
done=set(open(f"{D}/done.txt").read().split()) if os.path.exists(f"{D}/done.txt") else set()
def cc_false(v): return v is False or (isinstance(v,str) and v.strip().lower()=="false")
def write_queue():
    rows=[json.loads(l) for l in open(f"{D}/rows.jsonl")] if os.path.exists(f"{D}/rows.jsonl") else []
    seen=set(); out=[]
    for r in rows:
        k=(r["place_id"],r["doc_id"])
        if k in seen: continue
        seen.add(k); out.append(r)
    with open(Q+".tmp","w") as f:
        for r in out: f.write(json.dumps(r,ensure_ascii=False)+"\n")
        f.flush(); os.fsync(f.fileno())
    os.rename(Q+".tmp",Q); return len(out)
rf=open(f"{D}/rows.jsonl","a"); df=open(f"{D}/done.txt","a"); n=0; t0=time.time()
for path in targets:
    if path in done: continue
    try:
        pf=pq.ParquetFile(RangeFile(path),pre_buffer=True)
        names=set(pf.schema_arrow.names); cols=[c for c in COLS if c in names]
        t=pf.read(columns=cols); hits=0
        for r in t.to_pylist():
            if not cc_false(r.get("content_complete")): continue
            em=r.get("extra_metadata")
            if isinstance(em,str):
                try: em=json.loads(em)
                except Exception: em={"raw":em}
            sp=r.get("source_policy")
            if isinstance(sp,str) and sp.startswith("["):
                try: sp=json.loads(sp)
                except Exception: pass
            q={k:(None if r.get(k) in ("None","") else r.get(k)) for k in cols if k not in("content_complete","extra_metadata","source_policy")}
            q.update(content_complete=False,extra_metadata=em or {},source_policy=sp,lane="afme",queued_from="hub_parquet",hub_path=path,
                     pdf_url_like=bool(re.search(r"\.pdf($|[?#])",(r.get("source_url") or "")+" "+(r.get("original_url") or ""),re.I)))
            rf.write(json.dumps(q,ensure_ascii=False)+"\n"); hits+=1
        rf.flush(); df.write(path+"\n"); df.flush(); n+=1
        if hits: log("file",path,"incomplete",hits)
    except Exception as e:
        log("ERR",path,repr(e)[:160])
    if n and n%100==0: log("progress",n,"files this run, reqs",NREQ[0],"queue rows",write_queue(),"elapsed_min",round((time.time()-t0)/60))
log("DONE files",n,"reqs",NREQ[0],"queue rows",write_queue())
