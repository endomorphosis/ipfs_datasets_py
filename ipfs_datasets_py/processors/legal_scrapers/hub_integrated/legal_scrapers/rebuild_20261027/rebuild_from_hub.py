#!/usr/bin/env python3
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_WORLD = _ipfs_Path(_ipfs_os.environ.get("WORLD_LAW_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "world_law")))
_TESSDATA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_TESSDATA", str(_ipfs_Path.home() / ".ipfs_datasets" / "tessdata")))
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
# Read-only against the Hub. Rebuild staging_<cc> for the 13 CCs. No uploads/deletes.
import os, sys, json, shutil, hashlib
os.environ["HF_HUB_DISABLE_XET"]="1"
from pathlib import Path
from huggingface_hub import HfApi, hf_hub_download
import pyarrow.parquet as pq
ROOT=Path(str(_SCRAPERS)); CACHE="/workspace/hf_cache_rebuild_20261027"
REPOS={"bo":"bolivia","az":"azerbaijan","al":"albania","ao":"angola","do":"dominicanrepublic","et":"ethiopia","ir":"iran","mw":"malawi","zm":"zambia","la":"laos","lk":"srilanka","tn":"tunisia","rs":"serbia"}
EXP={"bo":(8443,60988),"az":(9917,10846),"al":(8186,149002),"ao":(6137,62070),"do":(8394,307951),"et":(6470,38795),"ir":(7388,25385),"mw":(5361,4712),"zm":(5444,10940),"la":(6420,57487),"lk":(8459,11104),"tn":(9472,97718),"rs":(7803,99095)}
FILES=["data/laws.parquet","data/articles.parquet","README.md","MANIFEST.md"]
api=HfApi(); out={}
def sha(p):
    h=hashlib.sha256()
    with open(p,"rb") as f:
        for b in iter(lambda:f.read(1<<20),b""): h.update(b)
    return h.hexdigest()
for cc,name in REPOS.items():
    repo=f"endomorphosis/ipfs_{name}_laws"
    info=api.dataset_info(repo, revision="main", files_metadata=True)
    commit=info.sha
    meta={s.rfilename:s for s in info.siblings}
    d=ROOT/f"staging_{cc}"; old=ROOT/f"staging_{cc}.sep_snapshot"
    if d.exists():
        if old.exists(): raise SystemExit(f"{old} exists")
        d.rename(old)
    (d/"data").mkdir(parents=True)
    rec={"repo":repo,"commit":commit,"files":{}}
    for fn in FILES:
        assert ".bak" not in fn
        if fn not in meta: rec["files"][fn]={"missing_on_hub":True}; continue
        p=hf_hub_download(repo,fn,repo_type="dataset",revision=commit,cache_dir=CACHE)
        dst=d/fn; shutil.copyfile(p,dst); os.chmod(dst,0o444)
        s=sha(dst); lfs=getattr(meta[fn],"lfs",None)
        lfs_sha=(lfs.sha256 if lfs and hasattr(lfs,"sha256") else (lfs or {}).get("sha256") if isinstance(lfs,dict) else None)
        rec["files"][fn]={"bytes":dst.stat().st_size,"sha256":s,"hub_lfs_sha256":lfs_sha,"lfs_match":(lfs_sha==s) if lfs_sha else None}
    L=pq.ParquetFile(d/"data/laws.parquet").metadata.num_rows
    A=pq.ParquetFile(d/"data/articles.parquet").metadata.num_rows
    rec.update(L=L,A=A,expected=list(EXP[cc]),match=(L,A)==EXP[cc])
    out[cc]=rec; print(cc,commit[:8],L,A,rec["match"],flush=True)
json.dump(out,open(ROOT/"rebuild_20261027/hub_rebuild.json","w"),indent=1)
