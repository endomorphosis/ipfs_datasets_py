"""Read-only Hub access, pinned per run to the commit recorded in hub_pins.json."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_WORLD = _ipfs_Path(_ipfs_os.environ.get("WORLD_LAW_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "world_law")))
_LEGAL_WS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_WORKSPACE", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_workspace")))
_COLLECTORS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors")))
import json
from pathlib import Path
from huggingface_hub import hf_hub_download, HfApi
B2 = Path((str(_COLLECTORS) + "/africa_me_b2")); PINS = B2 / "hub_pins.json"
SNAP = {r[0]: r[1] for r in json.load(open(B2 / "hub_snapshot_20261016.json"))}
def hub_repo(code): return SNAP.get(code.upper())
def pin(code):
    pins = json.loads(PINS.read_text()) if PINS.exists() else {}
    if code.upper() not in pins:
        pins[code.upper()] = HfApi().dataset_info(hub_repo(code)).sha; PINS.write_text(json.dumps(pins, indent=1))
    return pins[code.upper()]
def hub_file(code, fn):
    r = hub_repo(code)
    if not r: return None
    return hf_hub_download(r, fn, repo_type="dataset", revision=pin(code), local_dir=str(B2 / "hub" / code.lower()))
