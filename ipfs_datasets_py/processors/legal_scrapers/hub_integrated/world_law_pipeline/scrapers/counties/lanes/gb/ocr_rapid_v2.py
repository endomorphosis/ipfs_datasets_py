"""OCR image-only local PDFs with rapidocr-onnxruntime (venv under county/_state). Writes text + conf JSON to raw/ukla_ocr/. Usage: ocr_rapid.py file.pdf ..."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_WORLD = _ipfs_Path(_ipfs_os.environ.get("WORLD_LAW_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "world_law")))
_LEGAL_WS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_WORKSPACE", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_workspace")))
import sys,os,json,subprocess,io,time
import pymupdf as fitz, numpy as np
from rapidocr_onnxruntime import RapidOCR
OUT=(str(_CORPORA) + '/county/GB/raw/ukla_ocr'); os.makedirs(OUT,exist_ok=True)
eng=RapidOCR(intra_op_num_threads=6,inter_op_num_threads=1)
def textlayer_chars(p): return len(subprocess.run(['pdftotext',p,'-'],capture_output=True,text=True).stdout.strip())
import glob
files=sys.argv[1:] or sorted(glob.glob((str(_CORPORA) + '/county/GB/raw/ukla_pdf/*.pdf')),key=os.path.getsize)
for p in files:
    base=os.path.basename(p)[:-4]; o=f'{OUT}/{base}.json'
    if os.path.exists(o): continue
    doc=fitz.open(p); n=len(doc); tl=textlayer_chars(p)
    if tl>200*n**0.5+200 and tl/max(n,1)>150: json.dump(dict(pdf=base,pages=n,textlayer=True,note='has text layer; not OCR-ed'),open(o,'w')); print('textlayer',base,flush=True); continue
    pages=[];confs=[];t0=time.time()
    for i,pg in enumerate(doc):
        z=2200/max(pg.rect.width,pg.rect.height); pix=pg.get_pixmap(matrix=fitz.Matrix(z,z),colorspace=fitz.csGRAY)
        img=np.frombuffer(pix.samples,dtype=np.uint8).reshape(pix.h,pix.w)
        img=np.stack([img]*3,-1)
        res,_=eng(img,use_cls=False)
        lines=[]
        if res:
            items=sorted(res,key=lambda r:(round(np.mean([pt[1] for pt in r[0]])/18),np.mean([pt[0] for pt in r[0]])))
            cur=None;row=[]
            for r in items:
                y=round(np.mean([pt[1] for pt in r[0]])/18)
                if cur is not None and y!=cur: lines.append(' '.join(row)); row=[]
                cur=y; row.append(r[1]); confs.append(float(r[2]))
            if row: lines.append(' '.join(row))
        pages.append('\n'.join(lines))
    json.dump(dict(pdf=base,pages=n,textlayer=False,ocr=True,engine='rapidocr-onnxruntime 1.2.3',render_long_side_px=2200,use_cls=False,mean_conf=round(float(np.mean(confs)),4) if confs else None,seconds=round(time.time()-t0,1),page_text=pages),open(o,'w'))
    print('ocr',base,n,'pages',round(time.time()-t0),'s conf',round(float(np.mean(confs)),3) if confs else None,flush=True)
