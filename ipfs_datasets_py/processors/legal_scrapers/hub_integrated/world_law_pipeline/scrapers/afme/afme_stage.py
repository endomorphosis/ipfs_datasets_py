"""Stage completed, validate_file-clean afme place files into staging/afme/<CC>/ (copy, atomic). Idempotent via manifests in staging/afme/_logs/.
Rebuilt 2026-10-18 after the second reboot. Same behaviour as before: PR->US redirect (US-coded GNIS rows, fresh batch ts), skips _ files and invalid/empty files,
drops '.full.' variants for multi-batch places, and holds an exclusive flock on staging/afme/_logs/.stage.lock (concurrent chains wait)."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import json,glob,os,re,shutil,datetime,sys,collections,fcntl
os.makedirs((_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/staging/afme/_logs"),exist_ok=True)
_LK=open((_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/staging/afme/_logs/.stage.lock"),"a"); fcntl.flock(_LK,fcntl.LOCK_EX)
sys.path.insert(0,(_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/pipeline")); from schema import validate_file
SRC=(_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/out/afme"); DST=(_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/staging/afme"); LOGS=f"{DST}/_logs"
REDIRECT={"PR":"US"}
if shutil.disk_usage("/workspace").free<35*2**30: print("STOP disk floor"); sys.exit(2)
staged=set()
for m in glob.glob(f"{LOGS}/staged_*.json"):
    try: d=json.load(open(m))
    except Exception: continue
    for f in d.get("files",[]) if isinstance(d.get("files"),list) else []:
        staged.add((os.path.basename(f["src"]),os.path.dirname(f["dst"]).rsplit("/",1)[-1]))
ts=datetime.datetime.now(datetime.UTC).strftime("%Y%m%dT%H%M%SZ"); files=[]; summ=collections.defaultdict(lambda:{"files":0,"rows":0,"bad":0,"skipped_invalid":0})
only=set(sys.argv[1:])
for d in sorted(glob.glob(f"{SRC}/[A-Z][A-Z]")):
    cc=os.path.basename(d)
    if only and cc not in only: continue
    fs=[f for f in sorted(glob.glob(f"{d}/*.jsonl")) if not os.path.basename(f).startswith("_") and ".test." not in os.path.basename(f)]
    keys=collections.Counter(os.path.basename(f).split(".")[0] for f in fs)
    for f in fs:
        b=os.path.basename(f)
        if ".full." in b and keys[b.split(".")[0]]>1: continue
        dcc=REDIRECT.get(cc,cc)
        if (b,dcc) in staged: continue
        v=validate_file(f)
        if not v.get("ok") or not v.get("rows"): summ[cc]["skipped_invalid"]+=1; continue
        nb=b
        if cc in REDIRECT: nb=re.sub(r"(\d{8}T\d{6}Z)",ts,b,count=1)
        os.makedirs(f"{DST}/{dcc}",exist_ok=True); out=f"{DST}/{dcc}/{nb}"
        shutil.copyfile(f,out+".tmp"); os.rename(out+".tmp",out)
        files.append({"src":f,"dst":out,"rows":v["rows"],"ok":True}); summ[dcc]["files"]+=1; summ[dcc]["rows"]+=v["rows"]
man=f"{LOGS}/staged_{ts}.json"
if files: json.dump({"staged_at":ts,"summary":summ,"files":files},open(man,"w"),indent=1)
print(json.dumps(summ),man if files else "(nothing new)")
