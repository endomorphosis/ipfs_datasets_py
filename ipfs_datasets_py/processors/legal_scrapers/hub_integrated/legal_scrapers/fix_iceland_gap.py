# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_WORLD = _ipfs_Path(_ipfs_os.environ.get("WORLD_LAW_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "world_law")))
_TESSDATA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_TESSDATA", str(_ipfs_Path.home() / ".ipfs_datasets" / "tessdata")))
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import json
from pathlib import Path
p = Path(str(_SCRAPERS) + "/world_gap.json")
d = json.loads(p.read_text())
have = set(d.get("have") or [])
have.add("iceland")
missing = [m for m in d.get("missing") or [] if (m[1] if isinstance(m,(list,tuple)) else m) not in ("iceland","is") and (m[0] if isinstance(m,(list,tuple)) else "") != "is"]
d["have"] = sorted(have)
d["missing"] = missing
d["notes"] = dict(d.get("notes") or {})
d["notes"]["iceland"] = "false_positive_fixed: already on HF as ipfs_iceland_laws"
p.write_text(json.dumps(d, indent=2))
print("have", len(d["have"]), "missing", len(d["missing"]))
