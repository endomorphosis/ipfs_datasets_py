#!/usr/bin/env python3
"""Publish the Germany pilot seed to HF (create-or-additive, verify).

Layout (Portugal precedent): data/{ags}_html.parquet +
data/{ags}_validation.json per Gemeinde, data/jurisdictions.jsonl,
coverage_report.md, README.md, scrapers/ (this pilot's code).
Refuses to overwrite a remote file whose size differs from local.
"""
import json
import os
import sys
from pathlib import Path

os.environ["no_proxy"] = "localhost,127.0.0.1"
os.environ["NO_PROXY"] = "localhost,127.0.0.1"
os.environ["HF_HUB_DISABLE_PROGRESS_BARS"] = "1"
os.environ["TQDM_DISABLE"] = "1"

sys.path.insert(0, "/opt/hatch/skills/skill-creator/bin")
from dynamic_credentials import dynamic_credential_entry  # noqa: E402
from huggingface_hub import HfApi, hf_hub_download  # noqa: E402
import pyarrow.parquet as pq  # noqa: E402

REPO = "endomorphosis/ipfs_germany_municipal_laws"
HERE = Path(__file__).resolve().parent.parent
DATA = HERE / "data"
OUT = HERE / "out"
SCRIPTS = HERE / "scripts"


def make_api():
    entry = dynamic_credential_entry("custom.huggingface")
    token = entry.get("surrogate") if isinstance(entry, dict) else None
    if not token:
        raise RuntimeError("no surrogate from dynamic_credential_entry")
    return HfApi(token=token), token


def main():
    summary = json.loads((OUT / "pilot_summary.json").read_text(encoding="utf-8"))
    agss = [s["ags"] for s in summary if s["valid"]]
    if len(agss) != len(summary):
        raise RuntimeError("not all Gemeinden valid — refusing to publish")
    expected_rows = {s["ags"]: s["rows"] for s in summary}

    api, token = make_api()
    try:
        info = api.dataset_info(REPO, files_metadata=True)
        existing = {f.rfilename: f.size for f in (info.siblings or [])}
        print(f"repo EXISTS with {len(existing)} files")
    except Exception as e:
        print(f"repo does not exist yet ({type(e).__name__}); creating")
        api.create_repo(REPO, repo_type="dataset", private=False, exist_ok=True)
        existing = {}

    uploads = []
    for ags in agss:
        uploads.append((DATA / f"{ags}_html.parquet", f"data/{ags}_html.parquet"))
        uploads.append((DATA / f"{ags}_validation.json", f"data/{ags}_validation.json"))
    uploads.append((DATA / "jurisdictions.jsonl", "data/jurisdictions.jsonl"))
    uploads.append((OUT / "coverage_report.md", "coverage_report.md"))
    uploads.append((OUT / "README.md", "README.md"))
    for script in sorted(SCRIPTS.glob("*.py")):
        uploads.append((script, f"scrapers/{script.name}"))

    verify_list, todo = [], []
    for local, remote in uploads:
        if remote in existing:
            if existing[remote] == local.stat().st_size:
                print(f"skip upload (present, same size): {remote}")
                verify_list.append((local, remote))
                continue
            raise RuntimeError(
                f"remote {remote} exists with different size "
                f"({existing[remote]} vs local {local.stat().st_size}) — "
                "refusing to overwrite in pilot seed publish")
        todo.append((local, remote))
        verify_list.append((local, remote))

    for local, remote in todo:
        api.upload_file(path_or_fileobj=str(local), path_in_repo=remote,
                        repo_id=REPO, repo_type="dataset")
        print(f"uploaded {remote} ({local.stat().st_size} B)", flush=True)

    info = api.dataset_info(REPO, files_metadata=True)
    remote_files = {f.rfilename: f.size for f in (info.siblings or [])}
    problems = []
    for local, remote in verify_list:
        if remote not in remote_files:
            problems.append(f"missing remotely: {remote}")
        elif remote_files[remote] != local.stat().st_size:
            problems.append(f"size mismatch: {remote}")
    total_remote_rows = 0
    for ags in agss:
        p = hf_hub_download(REPO, f"data/{ags}_html.parquet", repo_type="dataset",
                            token=token, force_download=True)
        rows = pq.read_table(p).num_rows
        total_remote_rows += rows
        print(f"remote {ags} parquet rows: {rows} (expected {expected_rows[ags]})")
        if rows != expected_rows[ags]:
            problems.append(f"{ags} remote rows {rows} != {expected_rows[ags]}")
    print(f"remote total rows: {total_remote_rows}")
    print("remote file count:", len(remote_files))
    print("PROBLEMS:", problems if problems else "none")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
