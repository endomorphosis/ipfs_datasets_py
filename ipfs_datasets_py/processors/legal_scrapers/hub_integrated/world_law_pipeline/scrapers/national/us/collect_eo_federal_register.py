# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_WORLD = _ipfs_Path(_ipfs_os.environ.get("WORLD_LAW_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "world_law")))
_LEGAL_WS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_WORKSPACE", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_workspace")))
import requests, time, shutil, json, sys, os, re
import pyarrow as pa, pyarrow.parquet as pq
OUT=(str(_LEGAL_WS) + "/regs_eo/out/fr_executive_orders.parquet")
API="https://www.federalregister.gov/api/v1/documents.json"
FIELDS=["document_number","executive_order_number","title","signing_date","publication_date","president","citation","volume","start_page","end_page","html_url","pdf_url","full_text_xml_url","raw_text_url","body_html_url","disposition_notes","executive_order_notes","subtype","type"]
S=requests.Session(); S.headers["User-Agent"]="endomorphosis-world-laws research (polite; contact via github endomorphosis)"
def guard():
    free=shutil.disk_usage("/").free/2**30
    mem=[int(l.split()[1]) for l in open("/proc/meminfo") if l.startswith("MemAvailable")][0]/2**20
    if free<11 or mem<4.5:
        print(f"PAUSE free={free:.2f}G memavail={mem:.2f}Gi",flush=True); sys.exit(3)
def get(url,params=None):
    for a in range(5):
        r=S.get(url,params=params,timeout=60)
        if r.status_code in (429,500,502,503,504): time.sleep(5*(a+1)); continue
        ct=r.headers.get("content-type","")
        if r.status_code==403 or ("captcha" in r.text[:3000].lower()):
            print("BOTWALL",url,r.status_code,flush=True); sys.exit(4)
        r.raise_for_status(); return r
    r.raise_for_status()
# list metadata, partition by year to avoid 10k cap
meta=[]
for y in range(1993,2027):
    guard(); page=1
    while True:
        p=[("conditions[type][]","PRESDOCU"),("conditions[presidential_document_type][]","executive_order"),
           ("conditions[publication_date][gte]",f"{y}-01-01"),("conditions[publication_date][lte]",f"{y}-12-31"),
           ("per_page","1000"),("page",str(page)),("order","oldest")]+[("fields[]",f) for f in FIELDS]
        j=get(API,p).json(); res=j.get("results",[]); meta+=res
        time.sleep(1)
        if page>=j.get("total_pages",1) or not res: break
        page+=1
    print(y,len(meta),flush=True)
schema=pa.schema([(f,pa.string()) for f in FIELDS]+[("full_text",pa.string()),("full_text_source",pa.string()),("fetch_error",pa.string())])
w=pq.ParquetWriter(OUT,schema,compression="zstd")
buf=[]
def flush():
    global buf
    if buf: w.write_table(pa.Table.from_pylist(buf,schema=schema)); buf=[]
for i,m in enumerate(meta):
    if i%100==0: guard(); flush(); print("text",i,len(meta),flush=True)
    rec={f:(json.dumps(m.get(f)) if isinstance(m.get(f),(dict,list)) else (None if m.get(f) is None else str(m.get(f)))) for f in FIELDS}
    rec["full_text"]=None; rec["full_text_source"]=None; rec["fetch_error"]=None
    for k in ("raw_text_url","body_html_url"):
        u=m.get(k)
        if not u: continue
        try:
            t=get(u).text
            if k=="body_html_url": t=re.sub(r"<[^>]+>"," ",t)
            rec["full_text"]=t.strip(); rec["full_text_source"]=k; break
        except SystemExit: raise
        except Exception as e: rec["fetch_error"]=f"{k}: {e}"[:300]
        finally: time.sleep(0.5)
    buf.append(rec)
flush(); w.close(); print("DONE",len(meta),flush=True)
