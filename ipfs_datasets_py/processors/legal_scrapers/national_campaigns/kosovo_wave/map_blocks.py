#!/usr/bin/env python3
"""Stepped block-mapping for Kosovo GZK: sample ActIDs at a fixed step over
segments, saving digital-text successes via the same save_instrument path as
harvest_xk_slice.py, recording every sample into ../stats/attempts.jsonl with
result 'ok'/'pdf_short'/'no_pdf' (+ 'sample' flag) and logging pdf_short /
no_pdf into the corpus failures.jsonl (so later contiguous walks skip them).
Segments from env XK_SEGMENTS='125030:124900:20,124800:123000:20' (start:end:step).
"""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import json, os, sys, time
sys.path.insert(0, os.path.expanduser("~/workspace/ipfs_datasets_py/ipfs_datasets_py/processors/legal_scrapers/national_collectors"))
import collect_xk
from common import existing_ids, log_failure, slug_id, ROOT
from world_lib import pdf_to_text, save_instrument, setup_log
WAVE=os.path.expanduser("~/workspace/goals/global-law-scraping-coverage/hidden_files/kosovo_wave")
ATTEMPTS=os.path.join(WAVE,"stats","attempts.jsonl")
def load_attempted():
    s=set()
    if os.path.exists(ATTEMPTS):
        for line in open(ATTEMPTS):
            try: s.add(int(json.loads(line)["act_id"]))
            except Exception: pass
    return s
def main():
    setup_log("xk")
    segs=os.environ.get("XK_SEGMENTS","124800:123000:20")
    hf={r["id"] for r in json.load(open(os.path.join(WAVE,"dedupe","xk_dedupe.json")))}
    local_done=existing_ids("xk")
    old_fail=set()
    fp=ROOT/"xk"/"failures.jsonl"
    if fp.exists():
        for line in open(fp):
            try: old_fail.add(str(json.loads(line)["identifier"]))
            except Exception: pass
    attempted=load_attempted()
    af=open(ATTEMPTS,"a"); ok=fail=skip=0; t0=time.time()
    for seg in segs.split(","):
        a,b,step=[int(x) for x in seg.split(":")]
        for act_id in range(a,b-1,-step):
            if act_id in attempted: skip+=1; continue
            rid=slug_id("xk",str(act_id))
            if rid in local_done or rid in hf:
                af.write(json.dumps({"act_id":act_id,"result":"skip_known","sample":True})+"\n"); af.flush(); attempted.add(act_id); skip+=1; continue
            if str(act_id) in old_fail:
                af.write(json.dumps({"act_id":act_id,"result":"skip_old_failure","sample":True})+"\n"); af.flush(); attempted.add(act_id); skip+=1; continue
            t1=time.time()
            try: raw,title,date=collect_xk.download_act_pdf(act_id)
            except Exception as exc:
                af.write(json.dumps({"act_id":act_id,"result":f"error:{exc}"[:160],"sample":True})+"\n"); af.flush(); attempted.add(act_id); fail+=1; continue
            if not raw:
                af.write(json.dumps({"act_id":act_id,"result":"no_pdf","sample":True,"secs":round(time.time()-t1,1)})+"\n"); af.flush()
                log_failure("xk",{"identifier":str(act_id),"reason":"no_pdf"}); attempted.add(act_id); fail+=1; time.sleep(0.6); continue
            text=pdf_to_text(raw)
            if len(text)<120:
                af.write(json.dumps({"act_id":act_id,"result":"pdf_short","sample":True,"pdf_bytes":len(raw),"text_len":len(text),"secs":round(time.time()-t1,1)})+"\n"); af.flush()
                log_failure("xk",{"identifier":str(act_id),"reason":"pdf_short"}); attempted.add(act_id); fail+=1; time.sleep(0.6); continue
            url=f"https://gzk.rks-gov.net/ActDetail.aspx?ActID={act_id}"
            saved=save_instrument(cc="xk",country="Kosovo",language="sq",ident=str(act_id),title=title or f"Act {act_id}",text=text,source_url=url,source_type=collect_xk.SOURCE_TYPE,license_text=collect_xk.LICENSE,collector="collect_xk.py",date=date or None,article_re=collect_xk.ART,extra_meta={"fetch_method":"aspnet_pdf_postback","act_id":act_id})
            af.write(json.dumps({"act_id":act_id,"result":"ok" if saved else "save_failed","sample":True,"text_len":len(text),"secs":round(time.time()-t1,1)})+"\n"); af.flush()
            attempted.add(act_id)
            if saved: ok+=1; local_done.add(rid); print(f"ok {act_id} chars={len(text)}",flush=True)
            else: fail+=1
            time.sleep(0.6)
    af.close()
    print(f"MAP DONE ok={ok} fail={fail} skip={skip} elapsed={time.time()-t0:.0f}s",flush=True)
if __name__=="__main__":
    main()
