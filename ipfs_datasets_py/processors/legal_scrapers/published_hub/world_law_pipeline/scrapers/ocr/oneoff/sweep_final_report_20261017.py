import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import json, glob, os, collections
B=(_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/staging/pdf"); WL=_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law")
def jl(p):
    for l in open(p, encoding="utf-8"):
        l=l.strip()
        if l:
            try: yield json.loads(l)
            except Exception: pass
C=collections.defaultdict(collections.Counter)
# uploaded: sweep rows in pushed batches
pushed=set(os.path.basename(p)[:-7] for p in glob.glob(B+"/_manifest/*.pushed"))
up={}; ready_unpushed=collections.Counter()
for p in sorted(glob.glob(B+"/_manifest/batch_*.jsonl")):
    name=os.path.basename(p)[:-6]
    for r in jl(p):
        if r.get("lane")!="sweep": continue
        if name in pushed: up[r["doc_id"]]=r
        else: ready_unpushed[name]+=1
fet={}
for r in jl(B+"/_logs/fetched.jsonl"):
    if r.get("lane")=="sweep": fet[r["doc_id"]]=r
sk={}
for r in jl(B+"/_logs/skipped.jsonl"):
    if r.get("lane")=="sweep": sk[r["doc_id"]]=r
done=set(l.strip() for l in open(B+"/_state/done.txt") if l.startswith("sweep|"))
# country for fetched rows via manifest / skipped rows
def cc_of(d, default=None):
    for src in (up, sk, fet):
        if d in src and src[d].get("country_code"): return src[d]["country_code"]
    return default
queued_ids=set(fet)|set(sk)
for d in queued_ids:
    cc=cc_of(d) or ("PL" if "/" in d and d.startswith(("POL_","DU","WDU")) else ("GR" if d.startswith("gr_diavgeia:") else "??"))
    C[cc]["queued_into_collector"]+=1
    if d in up:
        C[cc]["uploaded_pushed"]+=1
        if up[d].get("issue_shared"): C[cc]["uploaded_as_whole_issue"]+=1
    elif d in fet: C[cc]["fetched_not_yet_pushed"]+=1
    if d in sk:
        r=sk[d]; C[cc]["skip_"+str(r.get("reason"))]+=1
        if not r.get("terminal"): C[cc]["skip_nonterminal"]+=1
# build stats
bs=json.load(open(B+"/_state/sweep_work/build_stats.json"))
for cc,v in bs.get("by_country",{}).items():
    for k,n in v.items(): C[cc]["build_"+k]+=n
# EU inputs
plq=WL+"/staging/eu/_state/pl/ocr_queue_pl.jsonl"; pln=collections.Counter()
if os.path.exists(plq):
    for e in jl(plq): pln["needs_"+str(e.get("needs","ocr"))]+=1
grq=WL+"/staging/eu/_state/gr/failed.jsonl"; grn=collections.Counter()
if os.path.exists(grq):
    for e in jl(grq): grn[str(e.get("reason"))]+=1
pending = [d for d in fet if d not in up]
print(json.dumps({"by_country":{k:dict(v) for k,v in sorted(C.items())},"pl_queue":pln,"gr_failed":grn,
  "unpushed_sweep_rows_by_batch":ready_unpushed,"sweep_done_txt":len(done),"fetched":len(fet),"skipped":len(sk),"uploaded":len(up),
  "pl_too_large_detail":[ (sk[d].get("detail") or "")[:160] for d in sk if sk[d].get("reason")=="too_large"][:20]},indent=1,ensure_ascii=False))
