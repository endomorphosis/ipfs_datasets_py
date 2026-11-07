"""Validate staged LII archive rows for one target: validate_file ok, every row tagged with
content_signal_ai_train_no + archived_blocked_live and the raw Content-Signal line. Prints JSON; exit 0 if >=N ok rows."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_WORLD = _ipfs_Path(_ipfs_os.environ.get("WORLD_LAW_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "world_law")))
_TESSDATA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_TESSDATA", str(_ipfs_Path.home() / ".ipfs_datasets" / "tessdata")))
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import sys, json, glob
sys.path.insert(0, (_wl_os.environ.get("WORLD_LAW_ROOT", str(_WORLD)) + "/pipeline"))
from schema import validate_file
from specs import SPECS
t, need = sys.argv[1], int(sys.argv[2] if len(sys.argv) > 2 else 10)
sp = SPECS[t]; rows = bad = untagged = 0; files = []
for f in glob.glob(f"~/.ipfs_datasets/world_law/staging/national/{sp['cc']}/*.jsonl") + glob.glob(f"~/.ipfs_datasets/world_law/processed/national/{sp['cc']}/**/*.jsonl", recursive=True):
    hit = False
    for l in open(f):
        r = json.loads(l)
        if r.get("source_platform") != sp["platform"]: continue
        hit = True; rows += 1
        pol = str(r.get("source_policy") or "")
        em = r.get("extra_metadata") or {}
        if not ("content_signal_ai_train_no" in pol and "archived_blocked_live" in pol and em.get("content_signal", "").startswith("Content-Signal:")):
            untagged += 1
    if hit:
        v = validate_file(f); files.append(f); bad += 0 if v["ok"] else 1
out = {"target": t, "rows": rows, "files": len(files), "files_invalid": bad, "rows_untagged": untagged}
print(json.dumps(out)); sys.exit(0 if rows >= need and not bad and not untagged else 1)
