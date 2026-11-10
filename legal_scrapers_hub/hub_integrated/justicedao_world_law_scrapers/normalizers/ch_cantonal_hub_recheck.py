# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os, json, hashlib, time
import pyarrow.parquet as pq
from huggingface_hub import HfApi, snapshot_download
REPO="endomorphosis/ipfs_switzerland_laws"; OLD="25cd3f9f14d6e6ee5453bb5ab36a9c2d6e8f8c1c"; NEW="7f9da5c8665870636242b176cea65e29d4f7ef0b"
api=HfApi(token=os.environ["HF_TOKEN"])
info=api.dataset_info(REPO, files_metadata=True)
commits=api.list_repo_commits(REPO, repo_type="dataset")
old_files={s.rfilename for s in api.dataset_info(REPO, revision=OLD).siblings}
new_files={s.rfilename for s in info.siblings}
on=snapshot_download(REPO, repo_type="dataset", revision=OLD); nn=snapshot_download(REPO, repo_type="dataset", revision=NEW)
def sha(p):
    h=hashlib.sha256()
    with open(p,"rb") as f:
        for b in iter(lambda:f.read(1<<20),b""): h.update(b)
    return h.hexdigest()
def cmp(o,n):
    O=pq.ParquetFile(o); N=pq.ParquetFile(n); it=N.iter_batches(batch_size=1000); buf=None; mism=0; rows=0; ids=set()
    for ob in O.iter_batches(batch_size=1000):
        need=ob.num_rows; parts=[]
        while need>0:
            if buf is None or buf.num_rows==0: buf=next(it)
            t=min(need,buf.num_rows); parts.append(buf.slice(0,t)); buf=buf.slice(t); need-=t
        for c in ob.schema.names:
            a=ob.column(c).to_pylist(); b=[x for p in parts for x in p.column(c).to_pylist()]
            mism+=sum(1 for x,y in zip(a,b) if x!=y)
        ids.update(ob.column("id").to_pylist()); rows+=ob.num_rows
    allids=set(); jur={}
    for b in N.iter_batches(batch_size=20000, columns=["id"]): allids.update(b.column("id").to_pylist())
    return {"old_rows":O.metadata.num_rows,"new_rows":N.metadata.num_rows,"old_rows_compared":rows,"old_row_field_mismatches":mism,
            "old_ids_missing":len(ids-allids),"unique_ids_after":len(allids),"schema_equal":O.schema_arrow.equals(N.schema_arrow)}
laws=cmp(f"{on}/data/laws.parquet",f"{nn}/data/laws.parquet"); arts=cmp(f"{on}/data/articles.parquet",f"{nn}/data/articles.parquet")
staged="{_CORPORA}/hf-staging/ipfs_switzerland_laws_cantonal_20260927T082541"
jc={}
for b in pq.ParquetFile(f"{nn}/data/laws.parquet").iter_batches(batch_size=20000,columns=["jurisdiction"]):
    for j in b.column("jurisdiction").to_pylist(): jc[j]=jc.get(j,0)+1
res={"repo":REPO,"new_tip":info.sha,"parent":commits[1].commit_id if len(commits)>1 else None,"expected_parent":OLD,"commit_title":commits[0].title,
 "checked_at":time.strftime("%Y-%m-%dT%H:%M:%S%z"),
 "laws":laws,"articles":arts,"old_files_removed":sorted(old_files-new_files),"files_added":sorted(new_files-old_files),
 "laws_sha_hub":sha(f"{nn}/data/laws.parquet"),"articles_sha_hub":sha(f"{nn}/data/articles.parquet"),
 "hub_matches_staged":sha(f"{nn}/data/laws.parquet")==sha(f"{staged}/data/laws.parquet") and sha(f"{nn}/data/articles.parquet")==sha(f"{staged}/data/articles.parquet"),
 "laws_by_jurisdiction":dict(sorted(jc.items()))}
res["PASS"]=bool(info.sha==NEW and res["parent"]==OLD and laws["new_rows"]==20080 and arts["new_rows"]==483891 and laws["old_rows_compared"]==5086 and arts["old_rows_compared"]==141697
 and laws["old_row_field_mismatches"]==0 and arts["old_row_field_mismatches"]==0 and laws["old_ids_missing"]==0 and arts["old_ids_missing"]==0 and not res["old_files_removed"])
json.dump(res,open("/workspace/country-law-triage/switzerland_cantonal_hub_republish_result.json","w"),indent=1)
print(json.dumps(res,indent=1))
