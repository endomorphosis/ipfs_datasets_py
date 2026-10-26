#!/usr/bin/env python3
"""Retry the download-error ActIDs listed in ../stats/retry_ids.json
(outage-window failures, not true negatives), same save path as the walker."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import json, os, sys, time
sys.path.insert(0, os.path.expanduser("~/workspace/ipfs_datasets_py/ipfs_datasets_py/processors/legal_scrapers/national_collectors"))
import collect_xk
from common import existing_ids, log_failure, slug_id
from world_lib import pdf_to_text, save_instrument, setup_log
WAVE=os.path.expanduser("~/workspace/goals/global-law-scraping-coverage/hidden_files/kosovo_wave")
def main():
    setup_log("xk")
    ids=json.load(open(os.path.join(WAVE,"stats","retry_ids.json")))["download_error_act_ids"]
    hf={r["id"] for r in json.load(open(os.path.join(WAVE,"dedupe","xk_dedupe.json")))}
    local=existing_ids("xk")
    af=open(os.path.join(WAVE,"stats","attempts.jsonl"),"a")
    ok=fail=skip=0
    for aid in sorted(ids, reverse=True):
        rid=slug_id("xk",str(aid))
        if rid in local or rid in hf: skip+=1; continue
        t1=time.time()
        try: raw,title,date=collect_xk.download_act_pdf(aid)
        except Exception as exc:
            af.write(json.dumps({"act_id":aid,"result":f"error_retry:{exc}"[:160]})+"\n"); af.flush(); fail+=1; continue
        if not raw:
            af.write(json.dumps({"act_id":aid,"result":"no_pdf","retry":True,"secs":round(time.time()-t1,1)})+"\n"); af.flush()
            log_failure("xk",{"identifier":str(aid),"reason":"no_pdf"}); fail+=1; time.sleep(0.6); continue
        text=pdf_to_text(raw)
        if len(text)<120:
            af.write(json.dumps({"act_id":aid,"result":"pdf_short","retry":True,"pdf_bytes":len(raw),"text_len":len(text),"secs":round(time.time()-t1,1)})+"\n"); af.flush()
            log_failure("xk",{"identifier":str(aid),"reason":"pdf_short"}); fail+=1; time.sleep(0.6); continue
        url=f"https://gzk.rks-gov.net/ActDetail.aspx?ActID={aid}"
        saved=save_instrument(cc="xk",country="Kosovo",language="sq",ident=str(aid),title=title or f"Act {aid}",text=text,source_url=url,source_type=collect_xk.SOURCE_TYPE,license_text=collect_xk.LICENSE,collector="collect_xk.py",date=date or None,article_re=collect_xk.ART,extra_meta={"fetch_method":"aspnet_pdf_postback","act_id":aid})
        af.write(json.dumps({"act_id":aid,"result":"ok" if saved else "save_failed","retry":True,"text_len":len(text),"secs":round(time.time()-t1,1)})+"\n"); af.flush()
        if saved: ok+=1; print(f"retry ok {aid} chars={len(text)}",flush=True)
        else: fail+=1
        time.sleep(0.6)
    af.close(); print(f"RETRY DONE ok={ok} fail={fail} skip={skip}",flush=True)
if __name__=="__main__":
    main()
