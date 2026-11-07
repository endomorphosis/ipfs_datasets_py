#!/usr/bin/env python3
"""Append-only, idempotent contribution of new state court rules to justicedao/ipfs_court_rules.
Layout mirrored exactly: state_court_rules_jsonld/STATE-XX.jsonld, state_court_rules_parquet_cid/STATE-XX.parquet (+ _embeddings.parquet).
NEVER modifies/deletes existing remote files or rows: only adds new paths. If STATE-XX.* already exist remotely, only rows whose
ipfs_cid/identifier are absent remotely are added, as new files STATE-XX.add-<sha8>.{jsonld,parquet}. Falls back to a PR if direct push is refused.
Usage: python contribute_ipfs_court_rules.py [--dry-run] [--states NV,ME]"""
import os,sys,json,glob,hashlib,io,fcntl
import pandas as pd
from huggingface_hub import HfApi,CommitOperationAdd,hf_hub_download
from huggingface_hub.utils import HfHubHTTPError
REPO="justicedao/ipfs_court_rules";UP="/workspace/world_courts/rules/out/upstream";LOCAL="/workspace/world_courts/data/ref/hf_dl"
def main():
    dry="--dry-run" in sys.argv;only=None
    if "--states" in sys.argv: only=set(sys.argv[sys.argv.index("--states")+1].split(","))
    lk=open("/workspace/world_courts/rules/out/.contrib.lock","w");fcntl.flock(lk,fcntl.LOCK_EX|fcntl.LOCK_NB)
    api=HfApi(token=os.environ["HF_TOKEN"]);files=set(api.list_repo_files(REPO,repo_type="dataset"))
    # remote known keys (all parquet shards under parquet_cid except aggregates/embeddings)
    rem=[f for f in files if f.startswith("state_court_rules_parquet_cid/STATE-") and f.endswith(".parquet") and "_embeddings" not in f]
    cids,idents,sids=set(),set(),set()
    for f in rem:
        d=pd.read_parquet(hf_hub_download(REPO,f,repo_type="dataset",local_dir=LOCAL,token=os.environ["HF_TOKEN"]),columns=["ipfs_cid","identifier","source_id"])
        cids|=set(d.ipfs_cid);idents|=set(d.identifier);sids|=set(d.source_id)
    ops=[];report={}
    for pq in sorted(glob.glob(UP+"/state_court_rules_parquet_cid/STATE-*.parquet")):
        b=os.path.basename(pq)
        if "_embeddings" in b or ".add-" in b: continue
        st=b[6:8]
        if only and st not in only: continue
        df=pd.read_parquet(pq);n0=len(df)
        df=df[~(df.ipfs_cid.isin(cids)|df.identifier.isin(idents)|df.source_id.isin(sids))]
        jl=[l for l in open(f"{UP}/state_court_rules_jsonld/STATE-{st}.jsonld")]
        keep_ids=set(df.identifier);jl=[l for l in jl if json.loads(l)["identifier"] in keep_ids]
        report[st]={"candidate":n0,"new":len(df)}
        if df.empty: continue
        suffix=""
        if f"state_court_rules_parquet_cid/STATE-{st}.parquet" in files:
            suffix=".add-"+hashlib.sha256("".join(sorted(df.ipfs_cid)).encode()).hexdigest()[:8]
        pp=f"state_court_rules_parquet_cid/STATE-{st}{suffix}.parquet";jp=f"state_court_rules_jsonld/STATE-{st}{suffix}.jsonld"
        if pp in files: continue
        buf=io.BytesIO();df.to_parquet(buf,index=False)
        ops+=[CommitOperationAdd(pp,buf.getvalue()),CommitOperationAdd(jp,"".join(jl).encode())]
        ep=pq.replace(".parquet","_embeddings.parquet")
        if os.path.exists(ep) and not suffix:
            e=pd.read_parquet(ep);e=e[e.ipfs_cid.isin(set(df.ipfs_cid))];b2=io.BytesIO();e.to_parquet(b2,index=False)
            ops.append(CommitOperationAdd(f"state_court_rules_parquet_cid/STATE-{st}_embeddings.parquet",b2.getvalue()))
        man={"contributed_by":"world_courts pipeline (endomorphosis)","state":st,"rows":len(df),"files":[pp,jp],"cid_scheme":"CIDv1 dag-json sha2-256 over jsonld without ipfs_cid","dedupe":"ipfs_cid/identifier/source_id vs all remote STATE-*.parquet"}
        ops.append(CommitOperationAdd(f"state_court_rules_parquet_cid/manifest.contrib.{st}{suffix}.json",json.dumps(man,indent=1).encode()))
    print(json.dumps(report));print("adds:",[o.path_in_repo for o in ops])
    # safety: no op may target an existing path
    assert not any(o.path_in_repo in files for o in ops),"refusing to overwrite existing remote file"
    if dry or not ops: return
    msg="Add court rules for "+", ".join(f"{k} ({v['new']})" for k,v in report.items() if v["new"])+" (append-only; new files only)"
    try:
        r=api.create_commit(REPO,repo_type="dataset",operations=ops,commit_message=msg,parent_commit=api.dataset_info(REPO).sha)
    except HfHubHTTPError as e:
        if e.response is not None and e.response.status_code in (401,403):
            r=api.create_commit(REPO,repo_type="dataset",operations=ops,commit_message=msg,create_pr=True)
        else: raise
    print("RESULT",getattr(r,"commit_url",r),getattr(r,"pr_url",""))
if __name__=="__main__": main()
