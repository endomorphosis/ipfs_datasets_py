"""Archived-copy harvester for dead/blocked municipal hosts (wave 9). usage: afme_lus_arch.py cfg.json [test]
One archive worker, sequential. Common Crawl first (index API via ratelimit.slot('cc_index'), WARC range reads via slot('cc_data')),
then Wayback (slot('wayback'), only while the box-wide breaker is closed). Rows tagged archive_source/crawl/timestamp/url, source_policy
'<src>_archive_fallback' (or archived_robots_disallowed when the live robots disallowed), source_official=true (council's own host)."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import sys,os,re,json,time,datetime,gzip,io,subprocess,tempfile,shutil
import requests
sys.path.insert(0,(_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/pipeline")); sys.path.insert(0,(_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/pipeline/archive"))
from schema import place_key
import ratelimit as RL
os.environ.setdefault("ARCHIVE_LANE","afme")
UA="JusticeDAO-WorldLaw/1.0 (+https://huggingface.co/datasets/endomorphosis/world_municipal_law; municipal law research)"
cfg=json.load(open(sys.argv[1])); TEST=len(sys.argv)>2; CC=cfg["cc"]; LANG=cfg.get("language","pt")
OUT=f"/workspace/world_law/out/afme/{CC}"; os.makedirs(OUT,exist_ok=True); BATCH=cfg.get("batch","arch_w9")
LAW=re.compile(cfg["url_regex"]); BAD=re.compile(cfg.get("exclude_regex","^$")); CRAWLS=cfg.get("crawls",[]); S=requests.Session(); S.headers["User-Agent"]=UA
DONE=f"{OUT}/_arch_done{'_test' if TEST else ''}.tsv"; done={l.split("\t")[0] for l in open(DONE)} if os.path.exists(DONE) else set()
EXCL=set()
if cfg.get("exclude_file"):
    for l in open(cfg["exclude_file"]): EXCL.add(tuple(l.rstrip("\n").split("\t",1)))
def nid(u): return re.sub(r"^https?://(www\.)?","",u.split("#")[0]).rstrip("/").lower()
def ts(): return datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
def get(fam,url,**kw):
    for att in range(3):
        try:
            with RL.slot(fam,max_wait=900) as rq:
                try: r=S.get(url,timeout=rq.timeout,**kw)
                except Exception: rq.fail(None); continue
                if r.status_code==429 or r.status_code>=500 or (fam=="cc_data" and r.status_code==403): rq.fail(r.status_code); continue
                rq.ok(r.status_code); return r
        except Exception as e: print("slot",fam,type(e).__name__,str(e)[:100],flush=True); return None
    return None
def cc_lookup(host):
    caps={}
    for c in CRAWLS:
        r=get("cc_index",f"https://index.commoncrawl.org/{c}-index",params={"url":f"*.{host}","output":"json","filter":"status:200","fl":"url,timestamp,mime,mime-detected,filename,offset,length"})
        if r is None or r.status_code!=200: continue
        for l in r.text.splitlines():
            try: x=json.loads(l)
            except Exception: continue
            u=x["url"]
            if LAW.search(u) and not BAD.search(u) and ("pdf" in (x.get("mime-detected","")+x.get("mime","")) or u.lower().endswith(".pdf")):
                k=nid(u)
                if k not in caps or x["timestamp"]>caps[k]["timestamp"]: caps[k]=dict(x,crawl=c)
    return caps
def cc_fetch(x):
    o,n=int(x["offset"]),int(x["length"])
    r=get("cc_data",f"https://data.commoncrawl.org/{x['filename']}",headers={"Range":f"bytes={o}-{o+n-1}"})
    if r is None or r.status_code not in (200,206): return None,None
    try: w=gzip.decompress(r.content)
    except Exception: return None,None
    hdr,_,rest=w.partition(b"\r\n\r\n"); hh,_,body=rest.partition(b"\r\n\r\n")
    trunc=b"WARC-Truncated" in hdr
    return body,trunc
def wb_lookup(host):
    if not RL.wayback_available(): return {}
    r=get("wayback","https://web.archive.org/cdx/search/cdx",params={"url":host+"/*","output":"json","filter":["statuscode:200","mimetype:application/pdf"],"collapse":"urlkey","limit":"5000"})
    if r is None or r.status_code!=200: return {}
    try: rows=r.json()[1:]
    except Exception: return {}
    return {nid(x[2]):{"url":x[2],"timestamp":x[1]} for x in rows if LAW.search(x[2]) and not BAD.search(x[2])}
def pdftext(b):
    with tempfile.NamedTemporaryFile(suffix=".pdf",dir=(_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/out/afme")) as f:
        f.write(b); f.flush()
        try: return subprocess.run(["pdftotext","-layout",f.name,"-"],capture_output=True,timeout=120).stdout.decode("utf8","replace")
        except Exception: return ""
for p in cfg["places"]:
    key=place_key(p["place_id"],None,CC)
    if key in done: continue
    if shutil.disk_usage("/workspace").free<35*2**30: print("STOP disk floor"); sys.exit(3)
    rows=[]; st={"key":key,"host":p["host"]}
    caps=cc_lookup(p["host"]); st["cc_caps"]=len(caps)
    wb={} if (caps and not cfg.get("wayback_too")) else wb_lookup(p["host"]); st["wb_caps"]=len(wb)
    items=[("commoncrawl",k,v) for k,v in caps.items()]+[("wayback",k,v) for k,v in wb.items() if k not in caps]
    for src,k,v in items[:cfg.get("doc_cap",60)]:
        if (key,k) in EXCL: continue
        if src=="commoncrawl": body,trunc=cc_fetch(v); aurl=f"https://data.commoncrawl.org/{v['filename']}"; cid=v["crawl"]
        else:
            aurl=f"https://web.archive.org/web/{v['timestamp']}id_/{v['url']}"; r=get("wayback",aurl); body=r.content if r is not None and r.status_code==200 else None; trunc=False; cid="wayback"
        if not body or body[:4]!=b"%PDF": continue
        txt="" if trunc else pdftext(body).strip()
        title=re.sub(r"(?i)\.pdf$","",requests.utils.unquote(v["url"].rstrip("/").rsplit("/",1)[-1])).replace("_"," ").replace("-"," ")
        title=re.sub(r"\s+"," ",title).strip()
        if cfg.get("bad_title") and re.search(cfg["bad_title"],title): continue
        complete=len(txt)>200
        rec=dict(place_id=p["place_id"],country_code=CC,doc_id=k,source_platform=f"{src}_archive",source_url=v["url"],doc_type="regulation" if re.search(cfg.get("regulation_re","(?i)regulament"),title) else "ordinance",
            language=LANG,title_native=title[:400],number=None,published_date=None,consolidated=False,in_force=None,content_format="pdf_text",text=txt if complete else "",retrieved_at=ts(),
            content_complete=complete,archive_source=src,archive_crawl_id=cid,archive_timestamp=v["timestamp"],archive_url=aurl,original_url=v["url"],
            source_policy=p.get("archived_policy",f"{'cc' if src=='commoncrawl' else 'wayback'}_archive_fallback"),source_official=True,source_org=p["name"],
            place_name=p["name"],qid=p["place_id"].split(":")[1],admin_level=p.get("admin_level","municipality"),platform=f"{src}_archive",platform_place_id=p["host"],
            extra_metadata={"live_status":p.get("live_status"),"warc_truncated":bool(trunc)})
        if p.get("source_policy_raw"): rec["source_policy_raw"]=p["source_policy_raw"]
        rows.append(rec)
    if rows:
        f=f"{OUT}/{key}.{BATCH}{'.test' if TEST else ''}.jsonl"
        with open(f+".tmp","w") as o:
            for x in rows: o.write(json.dumps(x,ensure_ascii=False)+"\n")
            o.flush(); os.fsync(o.fileno())
        os.rename(f+".tmp",f)
        if not TEST:
            with open((_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/out/afme/_ocr_queue.jsonl"),"a") as q:
                for x in rows:
                    if not x["content_complete"]: q.write(json.dumps({"cc":CC,"place_key":key,"doc_id":x["doc_id"],"pdf_url":x["original_url"],"archive_url":x["archive_url"],"file":f})+"\n")
    st["rows"]=len(rows)
    with open(DONE,"a") as d: d.write(f"{key}\t{json.dumps(st)}\n")
    print(json.dumps(st),flush=True)
print("DONE",flush=True)
