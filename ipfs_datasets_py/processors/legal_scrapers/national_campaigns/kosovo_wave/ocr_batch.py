#!/usr/bin/env python3
"""Bounded OCR recovery for Kosovo scanned gazette PDFs (waves 7/8 pattern).
Candidates: ../stats/attempts.jsonl rows with result=pdf_short, text_len=0,
pdf_bytes>=20000, not already in local corpus / on HF / already OCR-attempted.
Per candidate: re-download PDF via collect_xk.download_act_pdf, render with
pdftoppm (300 dpi), OCR with tesseract -l sqi (traineddata in ../tessdata/),
join pages, require >=300 chars and >=50% alphabetic, then save via
world_lib.save_instrument with extra_meta ocr flag. Outcomes appended to
../stats/ocr_attempts.jsonl; successes also appended to ../stats/attempts.jsonl
as ok_ocr. Env: XK_OCR_MAX (default 40), XK_OCR_MAX_SECONDS (default 3000),
XK_OCR_MAX_PAGES (default 15; longer PDFs deferred, recorded).
"""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import json, os, subprocess, sys, tempfile, time
sys.path.insert(0, os.path.expanduser("~/workspace/ipfs_datasets_py/ipfs_datasets_py/processors/legal_scrapers/national_collectors"))
import collect_xk
from common import existing_ids, slug_id
from world_lib import save_instrument, setup_log, env_int
WAVE=os.path.expanduser("~/workspace/goals/global-law-scraping-coverage/hidden_files/kosovo_wave")
TESS=os.path.join(WAVE,"tessdata")
def candidates():
    seen=set(); out=[]
    hf={r["id"] for r in json.load(open(os.path.join(WAVE,"dedupe","xk_dedupe.json")))}
    local=existing_ids("xk")
    done=set()
    op=os.path.join(WAVE,"stats","ocr_attempts.jsonl")
    if os.path.exists(op):
        for line in open(op):
            try: done.add(int(json.loads(line)["act_id"]))
            except Exception: pass
    for line in open(os.path.join(WAVE,"stats","attempts.jsonl")):
        try: r=json.loads(line)
        except Exception: continue
        if r.get("result")!="pdf_short": continue
        if r.get("text_len",999)!=0: continue
        if r.get("pdf_bytes",0)<20000: continue
        aid=int(r["act_id"])
        if aid in seen or aid in done: continue
        rid=slug_id("xk",str(aid))
        if rid in local or rid in hf: continue
        seen.add(aid); out.append(aid)
    return sorted(out, reverse=True)
def ocr_pdf(raw, max_pages):
    with tempfile.TemporaryDirectory() as td:
        p=os.path.join(td,"doc.pdf"); open(p,"wb").write(raw)
        info=subprocess.run(["pdfinfo",p],capture_output=True,text=True,timeout=60)
        pages=0
        for line in info.stdout.splitlines():
            if line.startswith("Pages:"): pages=int(line.split(":")[1])
        if pages==0: return "",0,"pdfinfo_failed"
        if pages>max_pages: return "",pages,"deferred_long"
        subprocess.run(["pdftoppm","-r","200","-png",p,os.path.join(td,"pg")],capture_output=True,timeout=600)
        env=dict(os.environ); env["TESSDATA_PREFIX"]=TESS
        texts=[]
        for fn in sorted(os.listdir(td)):
            if fn.startswith("pg") and fn.endswith(".png"):
                r=subprocess.run(["tesseract",os.path.join(td,fn),"stdout","-l","sqi","--psm","6"],capture_output=True,text=True,timeout=300,env=env)
                texts.append(r.stdout or "")
        return "\n".join(texts).strip(), pages, ""
def main():
    setup_log("xk")
    max_n=env_int("XK_OCR_MAX",40); max_s=env_int("XK_OCR_MAX_SECONDS",3000); max_pages=env_int("XK_OCR_MAX_PAGES",15)
    cands=candidates()
    print(f"ocr candidates={len(cands)} max={max_n}",flush=True)
    op=open(os.path.join(WAVE,"stats","ocr_attempts.jsonl"),"a")
    ap=open(os.path.join(WAVE,"stats","attempts.jsonl"),"a")
    ok=fail=0; t0=time.time()
    for aid in cands[:max_n]:
        if time.time()-t0>max_s: print("ocr max_seconds",flush=True); break
        t1=time.time()
        try: raw,title,date=collect_xk.download_act_pdf(aid)
        except Exception as exc:
            op.write(json.dumps({"act_id":aid,"result":f"error:{exc}"[:160]})+"\n"); op.flush(); fail+=1; continue
        if not raw:
            op.write(json.dumps({"act_id":aid,"result":"no_pdf"})+"\n"); op.flush(); fail+=1; continue
        try: text,pages,err=ocr_pdf(raw,max_pages)
        except Exception as exc:
            op.write(json.dumps({"act_id":aid,"result":f"ocr_error:{exc}"[:160],"secs":round(time.time()-t1,1)})+"\n"); op.flush(); fail+=1; continue
        if err:
            op.write(json.dumps({"act_id":aid,"result":err,"pages":pages,"secs":round(time.time()-t1,1)})+"\n"); op.flush(); fail+=1; continue
        alpha=sum(c.isalpha() for c in text); ratio=alpha/max(1,len(text))
        if len(text)<300 or ratio<0.5:
            op.write(json.dumps({"act_id":aid,"result":"ocr_short_or_junk","pages":pages,"text_len":len(text),"alpha_ratio":round(ratio,2),"secs":round(time.time()-t1,1)})+"\n"); op.flush(); fail+=1; continue
        url=f"https://gzk.rks-gov.net/ActDetail.aspx?ActID={aid}"
        saved=save_instrument(cc="xk",country="Kosovo",language="sq",ident=str(aid),title=title or f"Act {aid}",text=text,source_url=url,source_type=collect_xk.SOURCE_TYPE,license_text=collect_xk.LICENSE,collector="collect_xk.py",date=date or None,article_re=collect_xk.ART,extra_meta={"fetch_method":"aspnet_pdf_postback_ocr","act_id":aid,"ocr":{"engine":"tesseract","lang":"sqi","dpi":200,"pages":pages}})
        rec={"act_id":aid,"result":"ok_ocr" if saved else "save_failed","pages":pages,"text_len":len(text),"secs":round(time.time()-t1,1)}
        op.write(json.dumps(rec)+"\n"); op.flush()
        if saved:
            ok+=1; ap.write(json.dumps({"act_id":aid,"result":"ok_ocr","text_len":len(text)})+"\n"); ap.flush()
            print(f"ocr ok {aid} pages={pages} chars={len(text)} total_ok={ok} elapsed={time.time()-t0:.0f}s",flush=True)
        else: fail+=1
        time.sleep(0.6)
    op.close(); ap.close()
    print(f"OCR DONE ok={ok} fail={fail} elapsed={time.time()-t0:.0f}s",flush=True)
if __name__=="__main__":
    main()
