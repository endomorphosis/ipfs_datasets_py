"""Adelaide OCR recovery: verify ON-DISK pilot parquet is the 36-row
rebuild, upload superseding in place, remote-verify by re-download."""
import os, sys
from pathlib import Path
os.environ["no_proxy"] = "localhost,127.0.0.1"; os.environ["NO_PROXY"] = "localhost,127.0.0.1"
PILOT = Path(__file__).resolve().parent.parent / "au_pilot"
sys.path.insert(0, str(Path.home() / "workspace/ipfs_datasets_py/ipfs_datasets_py/processors/legal_scrapers"))
from world_municipal.parquet_io import read_html_parquet
from world_municipal.schema import validate_table
t = read_html_parquet(PILOT / "data" / "40070_html.parquet")
print("on-disk rows:", t.num_rows, flush=True)
from collections import Counter as _C
_titles = set(t.column("title").to_pylist())
assert t.num_rows > 26 and len(_titles) == 4, \
    f"on-disk parquet ({t.num_rows} rows, titles={_titles}) is not the OCR rebuild — aborting"
EXPECTED_ROWS = t.num_rows
print("expecting remote rows:", EXPECTED_ROWS, dict(_C(t.column("title").to_pylist())), flush=True)
sys.path.insert(0, "/opt/hatch/skills/skill-creator/bin")
from dynamic_credentials import dynamic_credential_entry
e = dynamic_credential_entry("custom.huggingface"); tok = str(e["surrogate"]).strip()
from huggingface_hub import HfApi, hf_hub_download
api = HfApi(token=tok); REPO = "endomorphosis/ipfs_australia_municipal_laws"
for local, remote in [(PILOT / "data/40070_html.parquet", "data/40070_html.parquet"),
                      (PILOT / "data/40070_validation.json", "data/40070_validation.json")]:
    api.upload_file(path_or_fileobj=str(local), path_in_repo=remote, repo_id=REPO,
                    repo_type="dataset", commit_message=f"AU tranche1 Adelaide OCR recovery: {remote}")
    print("uploaded", remote, flush=True)
info = api.dataset_info(REPO, files_metadata=True)
sizes = {s.rfilename: s.size for s in info.siblings or []}
local_size = (PILOT / "data/40070_html.parquet").stat().st_size
print("remote size:", sizes.get("data/40070_html.parquet"), "local size:", local_size, flush=True)
assert sizes.get("data/40070_html.parquet") == local_size, "size mismatch after upload"
p = hf_hub_download(REPO, "data/40070_html.parquet", repo_type="dataset", token=tok, force_download=True)
t2 = read_html_parquet(p)
errs = validate_table(t2, jurisdiction_id="40070", jurisdiction_name="Adelaide", country="AU")
from collections import Counter
print("remote rows:", t2.num_rows, "errors:", errs, dict(Counter(t2.column("title").to_pylist())), flush=True)
assert t2.num_rows == EXPECTED_ROWS and not errs
print(f"ADELAIDE OK: {EXPECTED_ROWS} rows remote-verified", flush=True)
