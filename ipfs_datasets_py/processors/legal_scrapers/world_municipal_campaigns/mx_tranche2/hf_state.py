"""Fresh HF listing helper for the MX dataset (vault surrogate auth,
never persisted). Usage: hf_state.py [out.json]  — prints repo file list
+ per-parquet row counts (metadata only) and saves JSON if asked."""
import json
import os
import sys
from pathlib import Path

os.environ["no_proxy"] = "localhost,127.0.0.1"
os.environ["NO_PROXY"] = "localhost,127.0.0.1"
sys.path.insert(0, "/opt/hatch/workflow-skills/custom-connector-setup/bin")
from dynamic_credentials import dynamic_credential_entry  # noqa: E402

REPO = "endomorphosis/ipfs_mexico_municipal_laws"

entry = dynamic_credential_entry("custom.huggingface")
token = entry.get("surrogate") or (entry.get("fields") or {}).get("hf_token")
if not token:
    raise RuntimeError("no HF credential from vault helper")

from huggingface_hub import HfApi  # noqa: E402

api = HfApi(token=token)
info = api.dataset_info(REPO, files_metadata=True)
files = {s.rfilename: s.size for s in info.siblings or []}
out = {"repo": REPO, "n_files": len(files), "files": files}
print(json.dumps(out, indent=1))
if len(sys.argv) > 1:
    Path(sys.argv[1]).write_text(json.dumps(out, indent=1))
