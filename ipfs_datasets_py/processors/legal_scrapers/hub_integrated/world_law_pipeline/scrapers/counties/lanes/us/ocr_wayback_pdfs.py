"""NEW wrapper (2026-10-29): OCR image-only Wayback county PDFs (raw/wayback/skips.jsonl 'image-only pdf (ocr pending)', files in raw/wayback/pdf/)
with the same rapidocr-onnxruntime settings as ocr_us_pdfs.py (2200px gray render, use_cls=False). Local files only - no network.
Output: one JSON per PDF in raw/wayback/ocr/ (resumable; atomic .tmp + os.replace). Each JSON keeps IA provenance: fetch_via=wayback,
wb_timestamp/wb_url (recovered from the cached CDX rows raw/wayback/cdx/ using wb_gap's newest-snapshot rule), content_signal/robots_live
(from docs.jsonl rows of the same host if any, else 'unknown'), ia_terms. ocr=True on every successful JSON.
Memory guard: waits while MemAvailable < 4.5Gi (+500MiB margin before each PDF). Disk guard: stops if / free < 10G.
Usage: ocr_wayback_pdfs.py [THREADS=2]"""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_WORLD = _ipfs_Path(_ipfs_os.environ.get("WORLD_LAW_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "world_law")))
_LEGAL_WS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_WORKSPACE", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_workspace")))
import sys,os,json,time,shutil,datetime,glob,urllib.parse
import pymupdf as fitz, numpy as np
from rapidocr_onnxruntime import RapidOCR
B=(str(_CORPORA) + '/county'); RAW=B+'/US/raw/wayback'; OUT=RAW+'/ocr'; os.makedirs(OUT,exist_ok=True)
EXCLUDE={'21111','21067','29510'}
TH=int(sys.argv[1]) if len(sys.argv)>1 else 2
FLOOR=int(4.5*1024*1024)  # kB
def memav():
    for l in open('/proc/meminfo'):
        if l.startswith('MemAvailable'): return int(l.split()[1])
def guard(extra=0):
    while memav()<FLOOR+extra:
        print('mem wait',memav()//1024,'MiB',flush=True); time.sleep(30)
    if shutil.disk_usage('/').free<10*2**30: print('DISK FLOOR; stopping',flush=True); note('US Wayback OCR stopped: disk floor (<10G free)'); sys.exit(3)
def note(s):
    with open(B+'/_state/PROGRESS.md','a') as f: f.write(f"- {datetime.datetime.now():%Y-%m-%d %H:%M:%S} PDT {s}\n")
def jl(p):
    out=[]
    for l in open(p):
        try: out.append(json.loads(l))
        except ValueError: pass
    return out
def norm(u): return u.split('#')[0].replace('http://','https://').replace('://www.','://').replace(':80/','/')
def host(u):
    h=urllib.parse.urlparse(u).netloc.lower(); return h[4:] if h.startswith('www.') else h
# provenance indexes
ts={}  # (geoid, normalized url) -> newest ts, exact url
for p in glob.glob(RAW+'/cdx/*.json'):
    g=os.path.basename(p).split('_',1)[0]
    try: rows=json.load(open(p))
    except ValueError: continue
    for x in rows:
        if len(x)<5: continue
        k=(g,norm(x[1]))
        if k not in ts or x[0]>ts[k][0]: ts[k]=(x[0],x[1])
hostinfo={}
for d in jl(RAW+'/docs.jsonl'):
    hostinfo.setdefault(host(d['url']),(d.get('content_signal',''),d.get('robots_live','unknown')))
rows=[r for r in jl(RAW+'/skips.jsonl') if 'ocr pending' in r.get('reason','') and r.get('pdf') and r['geoid'] not in EXCLUDE]
seen=set(); todo=[]
for r in rows:
    if r['pdf'] in seen or not os.path.exists(r['pdf']): continue
    seen.add(r['pdf']); todo.append(r)
todo.sort(key=lambda r:os.path.getsize(r['pdf']))
eng=RapidOCR(intra_op_num_threads=TH,inter_op_num_threads=1)
done=sum(os.path.exists(f"{OUT}/{os.path.basename(r['pdf'])[:-4]}.json") for r in todo)
note(f"US Wayback OCR job (US/scrapers/ocr_wayback_pdfs.py, pid {os.getpid()}, threads {TH}) started: {done}/{len(todo)} already done; out US/raw/wayback/ocr/. Resumable.")
cnt=0
for r in todo:
    base=os.path.basename(r['pdf'])[:-4]; o=f'{OUT}/{base}.json'
    if os.path.exists(o): continue
    guard(500*1024)
    t=ts.get((r['geoid'],norm(r['url'])),(None,None)); sig,rl=hostinfo.get(host(r['url']),('','unknown'))
    prov=dict(pdf=base,local_pdf=r['pdf'],url=r['url'],geoid=r['geoid'],fetch_via='wayback',wb_timestamp=t[0],
              wb_url=f'https://web.archive.org/web/{t[0]}/{t[1]}' if t[0] else None,content_signal=sig,robots_live=rl,
              ia_terms='Internet Archive Terms of Use apply to the archive copy; fetched <=1 req/s by wb_gap.py',
              pdf_fetched=datetime.datetime.fromtimestamp(os.path.getmtime(r['pdf'])).astimezone().strftime('%Y-%m-%dT%H:%M:%S%z'))
    try:
        doc=fitz.open(r['pdf']); n=len(doc); pages=[];confs=[];t0=time.time()
        for pg in doc:
            guard()
            z=2200/max(pg.rect.width,pg.rect.height); pix=pg.get_pixmap(matrix=fitz.Matrix(z,z),colorspace=fitz.csGRAY)
            img=np.stack([np.frombuffer(pix.samples,dtype=np.uint8).reshape(pix.h,pix.w)]*3,-1)
            res,_=eng(img,use_cls=False); lines=[]
            if res:
                items=sorted(res,key=lambda q:(round(np.mean([pt[1] for pt in q[0]])/18),np.mean([pt[0] for pt in q[0]])))
                cur=None;row=[]
                for q in items:
                    y=round(np.mean([pt[1] for pt in q[0]])/18)
                    if cur is not None and y!=cur: lines.append(' '.join(row)); row=[]
                    cur=y; row.append(q[1]); confs.append(float(q[2]))
                if row: lines.append(' '.join(row))
            pages.append('\n'.join(lines))
            del pix,img
        mc=round(float(np.mean(confs)),4) if confs else None
        d=dict(prov,pages=n,ocr=True,engine='rapidocr-onnxruntime 1.2.3',render_long_side_px=2200,use_cls=False,mean_conf=mc,seconds=round(time.time()-t0,1),page_text=pages)
        json.dump(d,open(o+'.tmp','w')); os.replace(o+'.tmp',o)
        print(time.strftime('%H:%M:%S'),'ocr',base,n,'pages',round(time.time()-t0),'s conf',mc,flush=True)
    except Exception as e:
        print(time.strftime('%H:%M:%S'),'ERR',base,repr(e),flush=True); json.dump(dict(prov,ocr=False,error=repr(e)),open(o,'w'))
    cnt+=1
    if cnt%25==0: note(f"US Wayback OCR {done+cnt}/{len(todo)} PDFs done")
note(f"US Wayback OCR COMPLETE loop exhausted: {len(glob.glob(OUT+'/*.json'))} json files in US/raw/wayback/ocr")
