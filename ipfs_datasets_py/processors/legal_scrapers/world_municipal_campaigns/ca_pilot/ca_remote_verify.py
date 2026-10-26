"""Canada pilot — remote verification: list the published repo, download
each parquet back, re-run the world_municipal gates, compare row counts."""
import json
import os
import sys
from pathlib import Path

os.environ["no_proxy"] = "localhost,127.0.0.1"
os.environ["NO_PROXY"] = "localhost,127.0.0.1"
sys.path.insert(0, "/opt/hatch/skills/skill-creator/bin")
from dynamic_credentials import dynamic_credential_entry  # noqa: E402

REPO_ROOT = Path.home() / "workspace" / "ipfs_datasets_py"
sys.path.insert(0, str(REPO_ROOT / "ipfs_datasets_py" / "processors" / "legal_scrapers"))
from world_municipal.schema import validation_report  # noqa: E402

PILOT = Path.home() / "workspace/goals/world-municipal-law-coverage/hidden_files/ca_pilot"
REPO = "endomorphosis/ipfs_canada_municipal_laws"
NAMES = {"3520005": "Toronto", "5915004": "Surrey",
         "1209034": "Halifax", "2481017": "Gatineau"}
manifest = json.load(open(PILOT / "run_manifest.json"))

entry = dynamic_credential_entry("custom.huggingface")
token = entry.get("surrogate") if isinstance(entry, dict) else None
assert token
from huggingface_hub import HfApi, hf_hub_download  # noqa: E402
import pyarrow.parquet as pq  # noqa: E402

api = HfApi(token=token)
info = api.dataset_info(REPO)
files = sorted(s.rfilename for s in info.siblings or [])
print(f"REMOTE {REPO}: {len(files)} files")
for f in files:
    print(" ", f)

out = {}
for jid, name in NAMES.items():
    remote = f"data/{jid}_html.parquet"
    assert remote in files, f"MISSING {remote}"
    p = hf_hub_download(REPO, remote, repo_type="dataset", local_dir="/tmp/ca_hf_check")
    t = pq.read_table(p)
    rep = validation_report(t, jurisdiction_id=jid, jurisdiction_name=name, country="Canada")
    want = manifest["municipalities"][jid]["rows"]
    ok = rep["valid"] and t.num_rows == want
    out[jid] = {"rows": t.num_rows, "expected": want, "valid": rep["valid"], "ok": ok}
    print(f"{jid} {name}: rows={t.num_rows} expected={want} valid={rep['valid']} ok={ok} errors={rep['errors']}")
assert all(v["ok"] for v in out.values()), "REMOTE VERIFY FAILED"
json.dump({"repo": REPO, "files": files, "per_jurisdiction": out},
          open(PILOT / "remote_verify_result.json", "w"), indent=1)
print("REMOTE VERIFY: ALL OK")
