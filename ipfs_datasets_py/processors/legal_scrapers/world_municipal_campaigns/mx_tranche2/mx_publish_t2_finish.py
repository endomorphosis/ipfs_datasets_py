"""Mexico tranche 2 — publish finisher.

Run after mx_publish_t2.py uploaded README/coverage and the first data
files but stalled on per-file commits through the proxy: uploads the
REMAINING tranche-2 files in ONE upload_folder commit, then runs the
publisher's identical remote-verify pass (every dataset parquet
re-downloaded, validate_table, row counts == manifests) and writes
publish_result.json in the same shape.
"""
import json
import os
import shutil
import sys
import time
from pathlib import Path

os.environ["no_proxy"] = "localhost,127.0.0.1"
os.environ["NO_PROXY"] = "localhost,127.0.0.1"
sys.path.insert(0, "/opt/hatch/workflow-skills/custom-connector-setup/bin")
from dynamic_credentials import dynamic_credential_entry  # noqa: E402

HERE = Path(__file__).resolve().parent
OUT = HERE.parent                       # mx_tranche2/
T1 = OUT.parent / "mx_tranche1"
PILOT = OUT.parent / "mx_pilot"
REPO = "endomorphosis/ipfs_mexico_municipal_laws"


def valid_munis(path: Path) -> dict:
    m = json.loads((path / "run_manifest.json").read_text())
    return {k: v for k, v in m["municipios"].items() if v.get("valid")}


pilot_munis = valid_munis(PILOT)
t1_munis = valid_munis(T1)
new_munis = valid_munis(OUT)
assert not (set(pilot_munis) & set(new_munis)) and not (set(t1_munis) & set(new_munis))
munis = {**pilot_munis, **t1_munis, **new_munis}
print(f"combined: {len(munis)} municipios ({len(new_munis)} new in t2)", flush=True)

entry = dynamic_credential_entry("custom.huggingface")
token = entry["surrogate"]
if not token:
    raise RuntimeError("no HF surrogate credential")

from huggingface_hub import HfApi  # noqa: E402
api = HfApi(token=token)


def dataset_files():
    for attempt in range(6):
        try:
            info = api.dataset_info(REPO, files_metadata=True)
            return {s.rfilename: s.size for s in info.siblings or []}
        except Exception as e:  # noqa: BLE001
            print(f"dataset_info attempt {attempt} failed: {type(e).__name__}", flush=True)
            time.sleep(20)
    raise RuntimeError("dataset_info unreachable")


existing = dataset_files()
print(f"dataset before finish: {len(existing)} files", flush=True)

wanted = []
for c in sorted(new_munis):
    wanted.append((OUT / "data" / f"{c}_html.parquet", f"data/{c}_html.parquet"))
    wanted.append((OUT / "data" / f"{c}_validation.json", f"data/{c}_validation.json"))
for s in ("mx_build_t2.py", "mx_publish_t2.py"):
    wanted.append((HERE / s, f"scrapers/{s}"))
missing = [(l, r) for l, r in wanted if r not in existing]
print(f"missing files: {len(missing)}", flush=True)
for _, r in missing:
    print("  ", r, flush=True)

uploaded = []
if missing:
    stage = OUT / "stage_finish"
    if stage.exists():
        shutil.rmtree(stage)
    for local, remote in missing:
        dest = stage / remote
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(local, dest)
    for attempt in range(4):
        try:
            api.upload_folder(folder_path=str(stage), repo_id=REPO,
                              repo_type="dataset",
                              commit_message="MX tranche 2: remaining data + scrapers (single-commit finish)")
            break
        except Exception as e:  # noqa: BLE001
            print(f"upload_folder attempt {attempt} failed: {type(e).__name__}: {e}", flush=True)
            time.sleep(30)
    else:
        raise RuntimeError("upload_folder failed repeatedly")
    uploaded = [r for _, r in missing]
    print("uploaded (single commit):", uploaded, flush=True)

remote = dataset_files()
print(f"remote files: {len(remote)}", flush=True)
bad = []
for local, remote_path in wanted:
    if remote_path not in remote:
        bad.append((remote_path, "missing"))
    elif remote_path.startswith("data/") and remote[remote_path] != local.stat().st_size:
        bad.append((remote_path, f"size {remote[remote_path]} != {local.stat().st_size}"))
print("upload mismatches:", bad, flush=True)

sys.path.insert(0, str(Path.home() / "workspace/ipfs_datasets_py/ipfs_datasets_py/processors/legal_scrapers"))
from huggingface_hub import hf_hub_download  # noqa: E402
from world_municipal.parquet_io import read_html_parquet  # noqa: E402
from world_municipal.schema import validate_table  # noqa: E402

reg = {}
for ln in (PILOT / "data" / "jurisdictions.jsonl").read_text().splitlines():
    r = json.loads(ln)
    reg[r["jurisdiction_id"]] = r["jurisdiction_name"]
verify = {}
for c in sorted(munis):
    p = None
    for attempt in range(4):
        try:
            p = hf_hub_download(REPO, f"data/{c}_html.parquet", repo_type="dataset", token=token)
            break
        except Exception as e:  # noqa: BLE001
            print(f"download {c} attempt {attempt} failed: {type(e).__name__}", flush=True)
            time.sleep(20)
    t = read_html_parquet(p)
    errs = validate_table(t, jurisdiction_id=c, jurisdiction_name=reg[c], country="MX")
    verify[c] = {"remote_rows": t.num_rows, "local_rows": munis[c]["rows"], "errors": errs}
    print("verify", c, verify[c], flush=True)
assert all(v["remote_rows"] == v["local_rows"] and not v["errors"] for v in verify.values())
assert not bad
(OUT / "publish_result.json").write_text(json.dumps(
    {"repo": REPO, "files": sorted(remote), "uploaded": uploaded,
     "total_rows": sum(v["remote_rows"] for v in verify.values()),
     "verify": verify}, indent=1))
print("PUBLISH + REMOTE VERIFY OK")
print(f"REMOTE TOTAL: {len(remote)} files, "
      f"{sum(v['remote_rows'] for v in verify.values())} rows")
