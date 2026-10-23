"""Final remote verification for AU tranche 2 (watchdog run 2026-10-14).

Fresh HF listing + re-download of every council parquet in
endomorphosis/ipfs_australia_municipal_laws; validate each (19-col
world_municipal schema, fail-closed); cross-check tranche-2 councils
against au_tranche2/state.json row counts exactly.
HF credential via vault connector helper only, never written to disk.
"""
import json
import os
import sys
from pathlib import Path

os.environ["no_proxy"] = "localhost,127.0.0.1"
os.environ["NO_PROXY"] = "localhost,127.0.0.1"

HERE = Path(__file__).resolve().parent
REPO = "endomorphosis/ipfs_australia_municipal_laws"

sys.path.insert(0, "/opt/hatch/workflow-skills/custom-connector-setup/bin")
from dynamic_credentials import dynamic_credential_entry  # noqa: E402

entry = dynamic_credential_entry("custom.huggingface")
token = str(entry["surrogate"]).strip() if entry and entry.get("surrogate") else None
if not token:
    raise RuntimeError("no HF surrogate credential")

from huggingface_hub import HfApi, hf_hub_download  # noqa: E402

REPO_PY = Path.home() / "workspace" / "ipfs_datasets_py"
sys.path.insert(0, str(REPO_PY / "ipfs_datasets_py" / "processors" / "legal_scrapers"))
from world_municipal.parquet_io import read_html_parquet  # noqa: E402
from world_municipal.schema import validate_table  # noqa: E402

PILOT = HERE.parent / "au_pilot"
reg = {}
for ln in (PILOT / "data" / "jurisdictions.jsonl").read_text().splitlines():
    r = json.loads(ln)
    if r["kind"] == "lga":
        reg[r["code"]] = r["name"]

api = HfApi(token=token)
info = api.dataset_info(REPO, files_metadata=True)
files = sorted(s.rfilename for s in info.siblings or [])
parquets = [f for f in files if f.endswith("_html.parquet")]
print(f"FILES {len(files)}")
print(f"PARQUETS {len(parquets)}")

state = json.loads((HERE / "state.json").read_text())
t2_expected = {k: v["rows"] for k, v in state["councils"].items()
               if v.get("status") == "published_verified"}

total_rows = 0
errors_all = {}
per_council = {}
for f in parquets:
    code = Path(f).name.replace("_html.parquet", "")
    p = hf_hub_download(REPO, f, repo_type="dataset", token=token, force_download=True)
    t = read_html_parquet(p)
    errs = validate_table(t, jurisdiction_id=code,
                          jurisdiction_name=reg.get(code, code), country="AU")
    per_council[code] = t.num_rows
    total_rows += t.num_rows
    if errs:
        errors_all[code] = errs
    print(f"{code} rows={t.num_rows} errors={len(errs)}")

print("PER_COUNCIL", json.dumps(per_council, sort_keys=True))
print(f"TOTAL_ROWS {total_rows}")
print(f"COUNCILS {len(per_council)}")
print("ERRORS", json.dumps(errors_all))
mismatch = {k: (per_council.get(k), v) for k, v in t2_expected.items()
            if per_council.get(k) != v}
print("TRANCHE2_EXPECTED", json.dumps(t2_expected, sort_keys=True))
print("TRANCHE2_MISMATCH", json.dumps(mismatch))
print("TRANCHE2_ROWS", sum(t2_expected.values()))
missing_t2 = [k for k in t2_expected if k not in per_council]
print("TRANCHE2_MISSING_REMOTE", missing_t2)
out = {
    "files": len(files), "parquets": len(parquets), "councils": len(per_council),
    "total_rows": total_rows, "per_council": per_council,
    "errors": errors_all, "tranche2_mismatch": mismatch,
    "tranche2_missing_remote": missing_t2,
    "tranche2_rows": sum(t2_expected.values()),
}
(HERE / "survey" / "hf_final_verify.json").write_text(json.dumps(out, indent=2))
print("WROTE survey/hf_final_verify.json")
