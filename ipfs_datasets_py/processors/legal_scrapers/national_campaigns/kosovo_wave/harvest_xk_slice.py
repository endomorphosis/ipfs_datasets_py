#!/usr/bin/env python3
"""Kosovo GZK continuation slice — resumable, checkpointed.

Reuses the repo collector collect_xk.py (download_act_pdf, article regex,
license/source constants) and world_lib.save_instrument / common helpers.
Unlike collect_xk.main's discover_act_ids() (SearchIn latest-20 + 250-step
walk + seeds, which Wave 6 exhausted for the 125076-125325 block), this
runner walks an explicit contiguous ActID range descending, skipping:
  - IDs already in the local corpus (existing_ids)
  - IDs already on Hugging Face (baseline dedupe json in ../dedupe/)
  - IDs already recorded in the corpus failures.jsonl (pdf_short/no_pdf)
  - IDs already attempted by THIS runner (../stats/attempts.jsonl)
State: every attempt appended to ../stats/attempts.jsonl (flush per ID);
chunk summaries appended to ../stats/chunks.jsonl. Safe to kill/resume:
rerunning with the same range skips everything already attempted.
Env: XK_START (default 125075), XK_END (default 124076), XK_MAX_NEW (0=unlimited),
XK_MAX_SECONDS (default 5400), XK_CHUNK (default 100).
"""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import json, os, sys, time
sys.path.insert(0, os.path.expanduser("~/workspace/ipfs_datasets_py/ipfs_datasets_py/processors/legal_scrapers/national_collectors"))
os.environ.setdefault("no_proxy","localhost,127.0.0.1"); os.environ.setdefault("NO_PROXY","localhost,127.0.0.1")
import collect_xk
from common import existing_ids, log_failure, slug_id, ROOT
from world_lib import env_int, pdf_to_text, save_instrument, setup_log
import logging
log = logging.getLogger("xk_slice")

WAVE = os.path.expanduser("~/workspace/goals/global-law-scraping-coverage/hidden_files/kosovo_wave")
STATS = os.path.join(WAVE, "stats")
ATTEMPTS = os.path.join(STATS, "attempts.jsonl")

def load_jsonl_ids(path, key="identifier"):
    out=set()
    if os.path.exists(path):
        for line in open(path):
            try:
                d=json.loads(line); out.add(str(d.get(key)))
            except Exception: pass
    return out

def main():
    setup_log("xk")
    start = env_int("XK_START", 125075)
    end = env_int("XK_END", 124076)
    max_new = env_int("XK_MAX_NEW", 0)
    max_seconds = env_int("XK_MAX_SECONDS", 5400)
    chunk_size = env_int("XK_CHUNK", 100)
    t_start=time.time()
    local_done = existing_ids("xk")
    hf_ids=set()
    dedupe_path=os.path.join(WAVE,"dedupe","xk_dedupe.json")
    if os.path.exists(dedupe_path):
        hf_ids={r["id"] for r in json.load(open(dedupe_path))}
    old_failures = load_jsonl_ids(str(ROOT/"xk"/"failures.jsonl"))
    attempted = load_jsonl_ids(ATTEMPTS, key="act_id")
    # attempts file uses act_id as int; normalize
    attempted_ids=set()
    if os.path.exists(ATTEMPTS):
        for line in open(ATTEMPTS):
            try: attempted_ids.add(int(json.loads(line)["act_id"]))
            except Exception: pass
    print(f"range {end}..{start} local_done={len(local_done)} hf={len(hf_ids)} old_failures={len(old_failures)} prior_attempts={len(attempted_ids)}", flush=True)
    ok=skip_hf=skip_local=skip_fail=skip_attempted=fail=0
    n_in_chunk=0; chunk_no=0; chunk_ok=0; chunk_fail=0
    af=open(ATTEMPTS,"a")
    for act_id in range(start, end-1, -1):
        if max_new and ok>=max_new: print("max_new reached",flush=True); break
        if time.time()-t_start>max_seconds: print("max_seconds reached",flush=True); break
        rid=slug_id("xk", str(act_id))
        reason=None
        if act_id in attempted_ids: skip_attempted+=1; continue
        if rid in local_done: reason="skip_local"; skip_local+=1
        elif rid in hf_ids: reason="skip_hf"; skip_hf+=1
        elif str(act_id) in old_failures: reason="skip_old_failure"; skip_fail+=1
        if reason:
            af.write(json.dumps({"act_id":act_id,"result":reason})+"\n"); af.flush(); attempted_ids.add(act_id); continue
        t1=time.time()
        try:
            raw,title,date = collect_xk.download_act_pdf(act_id)
        except Exception as exc:
            fail+=1; chunk_fail+=1
            af.write(json.dumps({"act_id":act_id,"result":f"error:{exc}"[:200],"secs":round(time.time()-t1,1)})+"\n"); af.flush()
            log_failure("xk", {"identifier":str(act_id),"reason":f"download:{exc}"[:200]})
            attempted_ids.add(act_id); n_in_chunk+=1
            continue
        if not raw:
            fail+=1; chunk_fail+=1
            af.write(json.dumps({"act_id":act_id,"result":"no_pdf","secs":round(time.time()-t1,1)})+"\n"); af.flush()
            log_failure("xk", {"identifier":str(act_id),"reason":"no_pdf"})
            attempted_ids.add(act_id); n_in_chunk+=1
            time.sleep(0.6); continue
        text=pdf_to_text(raw)
        if len(text)<120:
            fail+=1; chunk_fail+=1
            af.write(json.dumps({"act_id":act_id,"result":"pdf_short","pdf_bytes":len(raw),"text_len":len(text),"secs":round(time.time()-t1,1)})+"\n"); af.flush()
            log_failure("xk", {"identifier":str(act_id),"reason":"pdf_short"})
            attempted_ids.add(act_id); n_in_chunk+=1
            time.sleep(0.6); continue
        url=f"https://gzk.rks-gov.net/ActDetail.aspx?ActID={act_id}"
        saved=save_instrument(cc="xk",country="Kosovo",language="sq",ident=str(act_id),
            title=title or f"Act {act_id}", text=text, source_url=url,
            source_type=collect_xk.SOURCE_TYPE, license_text=collect_xk.LICENSE,
            collector="collect_xk.py", date=date or None, article_re=collect_xk.ART,
            extra_meta={"fetch_method":"aspnet_pdf_postback","act_id":act_id})
        if saved:
            ok+=1; chunk_ok+=1; local_done.add(rid)
            af.write(json.dumps({"act_id":act_id,"result":"ok","text_len":len(text),"title":(title or "")[:120],"date":date,"secs":round(time.time()-t1,1)})+"\n")
            print(f"ok {act_id} chars={len(text)} total_ok={ok} elapsed={time.time()-t_start:.0f}s title={(title or '')[:60]}", flush=True)
        else:
            fail+=1; chunk_fail+=1
            af.write(json.dumps({"act_id":act_id,"result":"save_failed","secs":round(time.time()-t1,1)})+"\n"); af.flush()
            print(f"save_failed {act_id}", flush=True)
        af.flush(); attempted_ids.add(act_id); n_in_chunk+=1
        if n_in_chunk>=chunk_size:
            chunk_no+=1
            rec={"chunk":chunk_no,"last_act_id":act_id,"ok":chunk_ok,"fail":chunk_fail,"total_ok":ok,"total_fail":fail,"elapsed_s":round(time.time()-t_start)}
            with open(os.path.join(STATS,"chunks.jsonl"),"a") as cf: cf.write(json.dumps(rec)+"\n")
            print("CHUNK",json.dumps(rec),flush=True)
            n_in_chunk=0; chunk_ok=0; chunk_fail=0
        time.sleep(0.6)
    af.close()
    summary={"range":[end,start],"ok":ok,"fail":fail,"skip_hf":skip_hf,"skip_local":skip_local,"skip_old_failure":skip_fail,"skip_attempted":skip_attempted,"elapsed_s":round(time.time()-t_start)}
    print("DONE",json.dumps(summary),flush=True)
    with open(os.path.join(STATS,"harvest_summary.json"),"w") as f: json.dump(summary,f,indent=1)
if __name__=="__main__":
    main()
