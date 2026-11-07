#!/usr/bin/env python3
"""Idempotent uploader for amea-* shards -> endomorphosis/world_caselaw data/<cc>/.
1) commit shards whose sha256 isn't in the manifest; 2) verify each against the Hub (LFS sha256, or
size+downloaded sha256 for non-LFS); 3) only verified shards are deleted locally (all sources).
Shards held back for policy (none currently) would be gzipped under amea/heldback/ instead."""
import glob, hashlib, json, os, sys, fcntl
from huggingface_hub import HfApi, CommitOperationAdd, hf_hub_download
BASE="/workspace/world_caselaw"; ST=BASE+"/amea/state"; MAN=ST+"/upload_manifest.json"; REPO="endomorphosis/world_caselaw"
lock=open(ST+"/upload.lock","w")
try: fcntl.flock(lock, fcntl.LOCK_EX|fcntl.LOCK_NB)
except OSError: print("another upload running"); sys.exit(0)
man=json.load(open(MAN)) if os.path.exists(MAN) else {}
def sha(p):
    h=hashlib.sha256()
    with open(p,"rb") as f:
        for b in iter(lambda: f.read(1<<20), b""): h.update(b)
    return h.hexdigest()
def save(): json.dump(man,open(MAN+".tmp","w"),indent=0); os.replace(MAN+".tmp",MAN)
api=HfApi(); files=sorted(glob.glob(BASE+"/data/*/amea-*_part*.jsonl"))
ops=[]; local={}
for p in files:
    rel=os.path.relpath(p,BASE); h=sha(p); local[rel]=h
    if man.get(rel)!=h: ops.append(CommitOperationAdd(path_in_repo=rel, path_or_fileobj=p))
for i in range(0,len(ops),100):
    b=ops[i:i+100]
    c=api.create_commit(repo_id=REPO, repo_type="dataset", operations=b, commit_message=f"amea caselaw: {len(b)} shard(s)")
    for o in b: man[o.path_in_repo]=local[o.path_in_repo]
    save(); print("committed",len(b),c.commit_url,flush=True)
# verify every local shard against the Hub, delete only verified ones
rels=list(local)
for i in range(0,len(rels),50):
    infos={x.path:x for x in api.get_paths_info(REPO, rels[i:i+50], repo_type="dataset")}
    for rel in rels[i:i+50]:
        x=infos.get(rel); ok=False
        if x is not None:
            if getattr(x,"lfs",None) is not None: ok = x.lfs.sha256==local[rel]
            else:
                q=hf_hub_download(REPO, rel, repo_type="dataset", cache_dir=ST+"/hfverify")
                ok = sha(q)==local[rel]; os.remove(q)
        if ok:
            os.remove(os.path.join(BASE,rel)); print("verified+deleted",rel,flush=True)
        else: print("NOT verified, kept",rel,flush=True)
