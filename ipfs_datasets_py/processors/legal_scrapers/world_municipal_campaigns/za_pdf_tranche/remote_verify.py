"""Remote verification for the ZA PDF tranche: fresh listing +
round-trip download of all 11 *_html.parquet (row counts), and full
world_municipal re-validation of two updated parquets — CPT (metro)
and WC015 (local, was heavily PDF-only). Public read."""
import json
import os
import sys
from pathlib import Path

os.environ["no_proxy"] = "localhost,127.0.0.1"
os.environ["NO_PROXY"] = "localhost,127.0.0.1"
REPO = Path.home() / "workspace" / "ipfs_datasets_py"
sys.path.insert(0, str(REPO / "ipfs_datasets_py" / "processors" / "legal_scrapers"))
from world_municipal.schema import validation_report  # noqa: E402
from world_municipal.parquet_io import read_html_parquet  # noqa: E402

from huggingface_hub import HfApi, hf_hub_download  # noqa: E402

REPO_ID = "endomorphosis/ipfs_south_africa_municipal_laws"
Z = Path.home() / "workspace/goals/world-municipal-law-coverage/hidden_files/za_pdf_tranche"
manifest = json.load(open(Z / "run_manifest.json"))

api = HfApi()
info = api.dataset_info(REPO_ID)
files = sorted(s.rfilename for s in info.siblings or [])
print(f"REMOTE TOTAL: {len(files)}")
html_files = [f for f in files if f.startswith("data/") and f.endswith("_html.parquet")]
print("REMOTE *_html.parquet:", html_files)

import pyarrow.parquet as pq
counts = {}
for f in html_files:
    p = hf_hub_download(REPO_ID, f, repo_type="dataset", local_dir="/tmp/za_pdf_remote_verify")
    counts[f] = pq.read_table(p).num_rows
    print(f"ROWS {f} {counts[f]}")

expected = {f"data/{c}_html.parquet": v["rows_after"]
            for c, v in manifest["municipalities"].items()}
assert counts == expected, (counts, expected)
total = sum(counts.values())
print(f"TOTAL ROWS {total} (baseline 15439)")

result = {"remote_total": len(files), "remote_files": files, "row_counts": counts,
          "total_rows": total}
for code, jname in [("CPT", "City of Cape Town"), ("WC015", "Swartland")]:
    p = hf_hub_download(REPO_ID, f"data/{code}_html.parquet",
                        repo_type="dataset", local_dir="/tmp/za_pdf_remote_verify")
    t = read_html_parquet(p)
    rep = validation_report(t, jurisdiction_id=code, jurisdiction_name=jname,
                            country="ZA")
    print(f"REVALIDATE {code}: {rep}")
    assert rep["valid"], rep
    assert rep["rows"] == manifest["municipalities"][code]["rows_after"]
    result[f"revalidated_{code}"] = rep
json.dump(result, open(Z / "remote_verify_result.json", "w"), indent=2)
print("REMOTE VERIFY OK")
