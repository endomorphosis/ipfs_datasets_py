# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import json,glob,re,sys
sys.path.insert(0,(_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/pipeline"))
from schema import html_cid
import pyarrow.parquet as pq
def norm(u): return re.sub(r"^https?://(www\.)?","",(u or "").strip()).rstrip("/").lower()
def nnum(n): return re.sub(r"\W+","",(n or "").lower())
def rows(p):
    if p.endswith(".jsonl"):
        for l in open(p,encoding="utf-8"):
            try: yield json.loads(l)
            except: pass
    else:
        pf=pq.ParquetFile(p);cols=[c for c in ("place_id","doc_id","source_url","number","cid") if c in pf.schema_arrow.names]
        for b in pf.iter_batches(columns=cols,batch_size=5000): yield from b.to_pylist()
out={}
for cc in ("PL","BE"):
    other=[p for b in ("staging","processed") for d in glob.glob(f"{b}/*/{cc}") for p in glob.glob(d+"/*.jsonl")+glob.glob(d+"/*.parquet") if ".hf2026" not in p]
    ids,urls,nums,cids=set(),set(),set(),set()
    for p in other:
        for r in rows(p):
            ids.add(str(r.get("doc_id"))); u=norm(r.get("source_url"))
            if u: urls.add(u)
            if r.get("number"): nums.add(nnum(r["number"]))
            pid=r.get("place_id")
            if pid and r.get("doc_id"): cids.add(html_cid(pid.replace(":","_",1),str(r["doc_id"])))
    mine=[p for b in ("staging","processed") for p in glob.glob(f"{b}/national/{cc}/*.hf2026*.jsonl")]
    d={"other_files":len(other),"other_docs_ids":len(ids),"my_files":len(mine),"my_docs":0,"dup_by":{"cid":0,"doc_id":0,"source_url":0,"number":0},"dup_doc_ids":[]}
    for p in mine:
        for r in rows(p):
            d["my_docs"]+=1; why=[]
            if html_cid("iso_"+cc,str(r["doc_id"])) in cids: why.append("cid")
            if str(r["doc_id"]) in ids: why.append("doc_id")
            if norm(r.get("source_url")) in urls and "huggingface.co" not in r.get("source_url",""): why.append("source_url")
            if r.get("number") and nnum(r["number"]) in nums: why.append("number")
            for w in why: d["dup_by"][w]+=1
            if [w for w in why if w!="number"]: d["dup_doc_ids"].append({"doc_id":r["doc_id"],"file":p.split("/")[-1],"by":why})
            elif why: d.setdefault("number_only_matches",[]).append({"doc_id":r["doc_id"],"number":r.get("number")})
    d["dup_count"]=len(d["dup_doc_ids"]); d["number_only_count"]=len(d.get("number_only_matches",[]))
    d["number_only_matches"]=d.get("number_only_matches",[])[:200]
    out[cc]=d
out["note"]="CID = html_cid(place_key, doc_id); my place is iso_PL/iso_BE while eu-bot files are iso_PL-xx gazettes / wd_ municipal, so CID matches imply same place_key+doc_id. Strong dup = cid/doc_id/source_url. number-only matches listed (max 200) as weak, not counted as dups."
json.dump(out,open("staging/national/_hf_import/dedupe_PL_BE.json","w"),indent=1)
print({k:(v if isinstance(v,str) else {x:v[x] for x in v if x not in("dup_doc_ids","number_only_matches")}) for k,v in out.items()})
