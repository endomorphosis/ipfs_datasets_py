#!/usr/bin/env python3
"""Publish Kosovo continuation parquet to HF — wave6/7/8 publish pattern.
Usage: publish_xk.py <expected_rows>
1. Record current remote row count (fresh download, surrogate auth).
2. Upload staged folder ../staging/ipfs_kosovo_laws/ as one commit.
3. Re-download remote parquet; verify rows==expected, ids unique, 0 empty texts.
Credential never printed/persisted; hsurr surrogate only to huggingface.co.
"""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import io, json, os, sys, urllib.request, urllib.error
sys.path.insert(0, "/opt/hatch/skills/skill-creator/bin")
from dynamic_credentials import add_surrogate_to_request, dynamic_credential_entry
os.environ["no_proxy"]="localhost,127.0.0.1"; os.environ["NO_PROXY"]="localhost,127.0.0.1"
WAVE=os.path.expanduser("~/workspace/goals/global-law-scraping-coverage/hidden_files/kosovo_wave")
HOST="huggingface.co"; CONNECTOR="custom.huggingface"
REPO="ipfs_kosovo_laws"; REPO_ID=f"endomorphosis/{REPO}"
STAGING=os.path.join(WAVE,"staging",REPO)
PROGRESS=os.path.join(WAVE,"stats","publish_ocr2_progress.json")

def redact(m):
    if "hsurr:" in m:
        i=m.index("hsurr:"); m=m[:i]+"hsurr:*[redacted]*"+m[i+60:]
    return m
def download_remote():
    import pyarrow.parquet as pq
    url=f"https://{HOST}/datasets/{REPO_ID}/resolve/main/data/laws.parquet"
    req=urllib.request.Request(url)
    add_surrogate_to_request(req,CONNECTOR,allowed_hosts=[HOST])
    try:
        with urllib.request.urlopen(req,timeout=300) as r: blob=r.read()
    except urllib.error.HTTPError as e:
        if e.code==404: return None
        raise
    return pq.read_table(io.BytesIO(blob))
def validate(table,expected):
    n=table.num_rows
    if n!=expected: return False,f"row_count={n} expected={expected}"
    ids=table.column("id").to_pylist()
    if len(set(ids))!=len(ids): return False,f"duplicate ids: {len(ids)-len(set(ids))}"
    texts=table.column("text").to_pylist()
    empty=sum(1 for t in texts if t is None or not str(t).strip())
    if empty: return False,f"empty texts: {empty}"
    return True,f"rows={n} ids_unique={len(set(ids))} empty_texts=0"
def main():
    import pyarrow.parquet as pq
    expected=int(sys.argv[1])
    local=os.path.join(STAGING,"data","laws.parquet")
    ok,detail=validate(pq.read_table(local),expected)
    print(f"local {detail} ok={ok}",flush=True)
    if not ok: print("FATAL local validation"); return 2
    entry=dynamic_credential_entry(CONNECTOR)
    token = (entry.get("surrogate") or entry.get("token") or entry.get("value")) if isinstance(entry,dict) else getattr(entry,"surrogate",None)
    if not token: raise RuntimeError("no surrogate from dynamic_credential_entry")
    from huggingface_hub import HfApi
    api=HfApi(token=token)
    progress={"repo":REPO_ID,"expected_rows":expected}
    before=download_remote(); progress["before_rows"]=None if before is None else before.num_rows
    print(f"before_rows: {progress['before_rows']}",flush=True)
    info=api.upload_folder(folder_path=STAGING,repo_id=REPO_ID,repo_type="dataset",
        commit_message=f"Kosovo OCR wave 2: scanned gazette acts recovered via sqi OCR ({expected} rows)")
    progress["commit_oid"]=getattr(info,"oid",None) or getattr(info,"commit_oid",None)
    print(f"upload commit: {progress['commit_oid']}",flush=True)
    after=download_remote()
    if after is None:
        progress["verify"]="FAIL: remote 404 after upload"; json.dump(progress,open(PROGRESS,"w"),indent=2); return 1
    ok,detail=validate(after,expected)
    progress["after_rows"]=after.num_rows; progress["verify"]=("OK: " if ok else "FAIL: ")+detail
    # extra checks
    df=after.to_pandas()
    progress["jurisdictions"]=df['jurisdiction'].value_counts().to_dict()
    progress["languages"]=df['language'].value_counts().to_dict()
    print(f"verify: {progress['verify']}",flush=True)
    json.dump(progress,open(PROGRESS,"w"),indent=2)
    return 0 if ok else 1
if __name__=="__main__":
    raise SystemExit(main())
