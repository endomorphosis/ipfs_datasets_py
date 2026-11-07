# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_WORLD = _ipfs_Path(_ipfs_os.environ.get("WORLD_LAW_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "world_law")))
_TESSDATA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_TESSDATA", str(_ipfs_Path.home() / ".ipfs_datasets" / "tessdata")))
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
from huggingface_hub import HfApi
import json,re
api=HfApi(token=open("/home/USER/.cache/huggingface/token").read().strip())
have=sorted({m.group(1).lower().replace("_","") for d in api.list_datasets(author="endomorphosis") for m in [re.match(r"endomorphosis/ipfs_(.+)_laws$", d.id)] if m})
old=json.load(open(str(_SCRAPERS) + "/world_gap.json"))
missing=[m for m in old.get("missing",[]) if (m[1] if isinstance(m,(list,tuple)) else m).replace("_","") not in have]
json.dump({"have":have,"missing":missing,"skip":old.get("skip",["us","unitedstates"]),"notes":old.get("notes",{})}, open(str(_SCRAPERS) + "/world_gap.json","w"), indent=2)
print(len(have), len(missing), have[:5], "...")
