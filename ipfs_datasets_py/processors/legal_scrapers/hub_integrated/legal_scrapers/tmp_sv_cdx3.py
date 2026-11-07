# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_WORLD = _ipfs_Path(_ipfs_os.environ.get("WORLD_LAW_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "world_law")))
_TESSDATA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_TESSDATA", str(_ipfs_Path.home() / ".ipfs_datasets" / "tessdata")))
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import sys
sys.path.insert(0,str(_SCRAPERS) + "/scrapers")
from world_lib import cdx_urls
prefixes=[
"www.diariooficial.gob.sv/diarios/2024/",
"www.diariooficial.gob.sv/diarios/2023/",
"www.diariooficial.gob.sv/diarios/2022/",
"www.diariooficial.gob.sv/diarios/2020/",
"www.diariooficial.gob.sv/diarios/2018/",
"www.diariooficial.gob.sv/diarios/2015/",
"www.diariooficial.gob.sv/diarios/2010/",
"www.diariooficial.gob.sv/diarios/2005/",
]
for prefix in prefixes:
    hits=cdx_urls(prefix, limit=60, match_type="prefix", extra_filters=["mimetype:application/pdf"])
    print(prefix, len(hits))
    for h in hits[:2]:
        print(" ", h.get("original"), h.get("timestamp"))
