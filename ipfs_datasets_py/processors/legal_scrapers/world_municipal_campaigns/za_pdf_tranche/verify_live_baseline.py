"""Live baseline check for the ZA OCR recovery: fresh listing +
row counts of all 11 data/<MDB>_html.parquet. Public read."""
import json
import os
import sys
from pathlib import Path

os.environ["no_proxy"] = "localhost,127.0.0.1"
os.environ["NO_PROXY"] = "localhost,127.0.0.1"

Z = Path.home() / "workspace/goals/world-municipal-law-coverage/hidden_files/za_pdf_tranche"
MDB_ORDER = ["CPT", "ETH", "JHB", "EC443", "WC011", "WC012", "WC013",
             "WC015", "WC023", "WC033", "WC041"]
REPO_ID = "endomorphosis/ipfs_south_africa_municipal_laws"

import pyarrow.parquet as pq
from huggingface_hub import HfApi, hf_hub_download

api = HfApi()
info = api.dataset_info(REPO_ID)
files = sorted(s.rfilename for s in info.siblings or [])
print(f"REMOTE TOTAL FILES: {len(files)}")
counts = {}
dl_dir = Z / "live_recovery"
for code in MDB_ORDER:
    p = hf_hub_download(REPO_ID, f"data/{code}_html.parquet",
                        repo_type="dataset", local_dir=str(dl_dir))
    counts[code] = pq.read_table(p).num_rows
    print(f"ROWS {code}: {counts[code]}")
print("TOTAL ROWS:", sum(counts.values()))
manifest = json.load(open(Z / "run_manifest.json"))
expected = {c: v["rows_after"] for c, v in manifest["municipalities"].items()}
print("MATCHES run_manifest rows_after:", counts == expected)
print("README present:", "README.md" in files,
      "| crosswalk present:", "manifests/za_overlap_crosswalk.jsonl" in files,
      "| Layer1 present:", any(f.startswith("data/laws-") for f in files))
json.dump({"remote_total": len(files), "row_counts": counts,
           "total_rows": sum(counts.values())},
          open(Z / "live_recovery_baseline.json", "w"), indent=2)
