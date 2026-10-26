# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import sys, os, json
sys.path.insert(0, os.path.expanduser("~/workspace/goals/global-law-scraping-coverage/hidden_files/wave13/scripts"))
os.environ["no_proxy"] = "localhost,127.0.0.1"
os.environ["NO_PROXY"] = "localhost,127.0.0.1"
from common13 import download_remote_parquet, TARGETS
import pyarrow.compute as pc

results = {}
for cc in ["ba", "sv", "sz", "pw", "ci", "by", "ge", "ne"]:
    repo = TARGETS[cc][0]
    try:
        table, blob = download_remote_parquet(repo)
        ids = table.column("id").to_pylist()
        texts = table.column("text").to_pylist()
        empty = sum(1 for t in texts if not t or not str(t).strip())
        results[cc] = {"repo": repo, "rows": table.num_rows, "unique_ids": len(set(ids)), "empty_texts": empty}
    except Exception as e:
        results[cc] = {"repo": repo, "error": f"{type(e).__name__}: {e}"}
    print(json.dumps({cc: results[cc]}), flush=True)
print("ALL:", json.dumps(results), flush=True)
