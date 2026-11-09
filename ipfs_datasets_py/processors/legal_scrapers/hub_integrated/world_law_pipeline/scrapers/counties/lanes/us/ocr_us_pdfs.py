"""OCR image-only US county PDFs (skips.jsonl 'image-only pdf (ocr pending)') with rapidocr-onnxruntime. Resumable: one JSON per PDF in raw/ocr/.
Memory guard: waits whenever MemAvailable < 4.5Gi (+margin before starting a PDF). Disk guard: stops if <10G free. Logs progress into _state/PROGRESS.md every 10 PDFs."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_WORLD = _ipfs_Path(_ipfs_os.environ.get("WORLD_LAW_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "world_law")))
_LEGAL_WS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_WORKSPACE", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_workspace")))
import sys,os,json,time,shutil,datetime
import pymupdf as fitz, numpy as np
from rapidocr_onnxruntime import RapidOCR
B=(str(_CORPORA) + '/county'); OUT=B+'/US/raw/ocr'; os.makedirs(OUT,exist_ok=True)
FLOOR=int(4.5*1024*1024)  # kB
def memav():
    for l in open('/proc/meminfo'):
        if l.startswith('MemAvailable'): return int(l.split()[1])
def guard(extra=0):
    while memav()<FLOOR+extra:
        print('mem wait',memav()//1024,'MiB',flush=True); time.sleep(30)
    if shutil.disk_usage((str(_LEGAL_WS))).free<10*2**30: print('DISK FLOOR; stopping',flush=True); sys.exit(3)
eng=RapidOCR(intra_op_num_threads=3,inter_op_num_threads=1)
rows=[json.loads(l) for l in open(B+'/US/raw/county_sites/skips.jsonl')]
rows=[r for r in rows if 'image-only' in r['reason']]
seen=set(); todo=[]
for r in rows:
    if r['pdf'] in seen: continue
    seen.add(r['pdf']); todo.append(r)
todo.sort(key=lambda r:os.path.getsize(r['pdf']))
def note(s):
    with open(B+'/_state/PROGRESS.md','a') as f: f.write(f"- {datetime.datetime.now():%Y-%m-%d %H:%M:%S} {s}\n")
done=sum(os.path.exists(f"{OUT}/{os.path.basename(r['pdf'])[:-4]}.json") for r in todo)
note(f"US OCR job (US/scrapers/ocr_us_pdfs.py, pid {os.getpid()}, log US/logs/ocr_us_*.log) started: {done}/{len(todo)} already done. Resumable (skips raw/ocr/*.json). Restart: cd US; nohup ../_state/venv_ocr/bin/python scrapers/ocr_us_pdfs.py >> logs/ocr_us_<ts>.log 2>&1 &")
cnt=0
for r in todo:
    base=os.path.basename(r['pdf'])[:-4]; o=f'{OUT}/{base}.json'
    if os.path.exists(o): continue
    guard(500*1024)
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
        mc=round(float(np.mean(confs)),4) if confs else None
        d=dict(pdf=base,url=r['url'],geoid=r['geoid'],pages=n,ocr=True,engine='rapidocr-onnxruntime 1.2.3',render_long_side_px=2200,use_cls=False,mean_conf=mc,seconds=round(time.time()-t0,1),page_text=pages)
        json.dump(d,open(o+'.tmp','w')); os.replace(o+'.tmp',o)
        print('ocr',base,n,'pages',round(time.time()-t0),'s conf',mc,flush=True)
    except Exception as e:
        print('ERR',base,repr(e),flush=True); json.dump(dict(pdf=base,url=r['url'],geoid=r['geoid'],ocr=False,error=repr(e)),open(o,'w'))
    cnt+=1
    if cnt%10==0: note(f"US OCR {done+cnt}/{len(todo)} PDFs done")
note(f"US OCR COMPLETE loop exhausted: {len(os.listdir(OUT))} json files in US/raw/ocr")
