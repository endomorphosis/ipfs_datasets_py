"""Poll for out/eap/FJ/_national_lg_regs.json every 15 min until 21:00 PT; collect only items missing from my staged iso:FJ lgregs batch."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import os, sys, json, time, glob, datetime, subprocess
SRC = (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/out/eap/FJ/_national_lg_regs.json"); DEADLINE = datetime.datetime(2026, 10, 16, 21, 0)
def log(*a): print(time.strftime("%Y-%m-%d %H:%M:%S"), *a, flush=True)
while not os.path.exists(SRC):
    if datetime.datetime.now() >= DEADLINE: log("DEADLINE 21:00 PT reached; list never appeared"); sys.exit(2)
    log("waiting for", SRC); time.sleep(900)
time.sleep(30); lst = json.load(open(SRC)); want = {x["legal_id"] for x in lst}
have = set()
for f in glob.glob((_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/staging/national/FJ/iso_FJ.lgregs*.jsonl")) + glob.glob((_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/processed/national/FJ/iso_FJ.lgregs*.jsonl*")):
    if f.endswith(".jsonl"):
        for l in open(f): have.add(json.loads(l)["doc_id"].replace("fj_laws_", "") + ".BODY")
have |= {json.loads(l)["legal_id"] for l in open((_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/staging/national/FJ/_ckpt_lg/parts.jsonl"))}
miss = sorted(want - have); log("list", len(want), "already", len(want & have), "missing", len(miss), miss, "extra_mine", sorted(have - want))
if not miss: log("nothing missing; no new batch"); sys.exit(0)
json.dump(miss, open((_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/staging/national/FJ/_ckpt_lg2_ids.json"), "w"))
sys.exit(subprocess.call([sys.executable, "collect_fj_lg_national.py"], env=dict(os.environ, FJ_ONLY=(_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/staging/national/FJ/_ckpt_lg2_ids.json"))))
