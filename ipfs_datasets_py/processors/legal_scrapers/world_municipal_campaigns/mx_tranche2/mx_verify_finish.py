"""Mexico tranche 2 — remote-verify finisher (curl transport).

The huggingface_hub download of one parquet hung inside the finisher
(proxy stall on a metadata request, blob already cached). This pass
re-downloads every dataset parquet via curl against the HF resolve
endpoint (hard --max-time, bearer = vault surrogate), then runs the
identical checks as the publisher: read_html_parquet + validate_table
(19-column schema, jurisdiction match) + row count == manifest, and
writes publish_result.json.
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

os.environ["no_proxy"] = "localhost,127.0.0.1"
os.environ["NO_PROXY"] = "localhost,127.0.0.1"
sys.path.insert(0, "/opt/hatch/workflow-skills/custom-connector-setup/bin")
from dynamic_credentials import dynamic_credential_entry  # noqa: E402

HERE = Path(__file__).resolve().parent
OUT = HERE.parent
T1 = OUT.parent / "mx_tranche1"
PILOT = OUT.parent / "mx_pilot"
REPO = "endomorphosis/ipfs_mexico_municipal_laws"
DL = OUT / "scratch" / "verify_dl"
DL.mkdir(parents=True, exist_ok=True)


def valid_munis(path: Path) -> dict:
    m = json.loads((path / "run_manifest.json").read_text())
    return {k: v for k, v in m["municipios"].items() if v.get("valid")}


munis = {**valid_munis(PILOT), **valid_munis(T1), **valid_munis(OUT)}
print(f"verifying {len(munis)} municipios", flush=True)

entry = dynamic_credential_entry("custom.huggingface")
token = entry["surrogate"]
if not token:
    raise RuntimeError("no HF surrogate credential")

sys.path.insert(0, str(Path.home() / "workspace/ipfs_datasets_py/ipfs_datasets_py/processors/legal_scrapers"))
from world_municipal.parquet_io import read_html_parquet  # noqa: E402
from world_municipal.schema import validate_table  # noqa: E402

reg = {}
for ln in (PILOT / "data" / "jurisdictions.jsonl").read_text().splitlines():
    r = json.loads(ln)
    reg[r["jurisdiction_id"]] = r["jurisdiction_name"]

verify = {}
for c in sorted(munis):
    dest = DL / f"{c}_html.parquet"
    ok = False
    if dest.exists() and dest.stat().st_size > 0:
        try:
            read_html_parquet(str(dest))
            ok = True
        except Exception:  # noqa: BLE001
            dest.unlink()
    if not ok:
        url = f"https://huggingface.co/datasets/{REPO}/resolve/main/data/{c}_html.parquet"
        for attempt in range(4):
            p = subprocess.run(["curl", "-sL", "--max-time", "240",
                                "-H", f"Authorization: Bearer {token}",
                                "-o", str(dest), "-w", "%{http_code}", url],
                               capture_output=True, timeout=280)
            code = p.stdout.decode().strip()
            if code == "200" and dest.exists() and dest.stat().st_size > 0:
                ok = True
                break
            print(f"download {c} attempt {attempt}: HTTP {code}", flush=True)
            time.sleep(15)
    assert ok, f"could not download {c}"
    t = read_html_parquet(str(dest))
    errs = validate_table(t, jurisdiction_id=c, jurisdiction_name=reg[c], country="MX")
    verify[c] = {"remote_rows": t.num_rows, "local_rows": munis[c]["rows"], "errors": errs}
    print("verify", c, verify[c], flush=True)

assert all(v["remote_rows"] == v["local_rows"] and not v["errors"] for v in verify.values())

before = json.loads((OUT / "probe" / "hf_before.json").read_text())
files = set(before["files"])
files |= {f"data/{c}_html.parquet" for c in valid_munis(OUT)}
files |= {f"data/{c}_validation.json" for c in valid_munis(OUT)}
files |= {"scrapers/mx_build_t2.py", "scrapers/mx_publish_t2.py"}
(OUT / "publish_result.json").write_text(json.dumps(
    {"repo": REPO, "files": sorted(files),
     "uploaded": sorted(files - set(before["files"])),
     "total_rows": sum(v["remote_rows"] for v in verify.values()),
     "verify": verify,
     "note": "remote-verify via curl resolve-endpoint re-download "
             "(mx_verify_finish.py) after the hub download of 14120 hung; "
             "uploads by mx_publish_t2.py + mx_publish_t2_finish.py "
             "(73 files confirmed by dataset_info, zero size mismatches)"},
    indent=1))
print("REMOTE VERIFY OK")
print(f"REMOTE TOTAL: {sum(v['remote_rows'] for v in verify.values())} rows "
      f"across {len(verify)} municipios")
