"""usage: afme_gate.py <CC> <glob-suffix> : exit 0 iff every matching test file validates with 0 bad rows (and at least one row unless --allow-empty)"""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import sys,glob
sys.path.insert(0,(_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/pipeline")); from schema import validate_file
fs=glob.glob(f"/workspace/world_law/out/afme/{sys.argv[1]}/*{sys.argv[2]}"); r=b=0
for f in fs: v=validate_file(f); r+=v["rows"]; b+=v["bad_rows"]
print(sys.argv[1:],len(fs),"files",r,"rows",b,"bad"); sys.exit(0 if b==0 and (r>0 or "--allow-empty" in sys.argv) else 1)
