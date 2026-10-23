#!/usr/bin/env python3
"""Publish the Austria/Carinthia pilot seed to HF (additive, verify)."""
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

REPO = "endomorphosis/ipfs_austria_municipal_laws"
OUT = Path(__file__).resolve().parent / "out"
GKZS = ["20911", "20503", "21001", "20701", "20802", "20302"]


def make_api():
    entry = dynamic_credential_entry("custom.huggingface")
    token = entry.get("surrogate") if isinstance(entry, dict) else None
    if not token:
        raise RuntimeError("no surrogate from dynamic_credential_entry")
    return HfApi(token=token), token


def main():
    api, token = make_api()
    # existence check
    try:
        info = api.dataset_info(REPO, files_metadata=True)
        existing = {f.rfilename: f.size for f in (info.siblings or [])}
        print(f"repo EXISTS with {len(existing)} files")
    except Exception as e:
        print(f"repo does not exist yet ({type(e).__name__}); creating")
        api.create_repo(REPO, repo_type="dataset", private=False, exist_ok=True)
        existing = {}

    uploads = []
    for gkz in GKZS:
        uploads.append((OUT / f"{gkz}_html.parquet", f"data/{gkz}_html.parquet"))
        uploads.append((OUT / f"{gkz}_validation.json", f"data/{gkz}_validation.json"))
    uploads.append((OUT / "coverage_report.md", "coverage_report.md"))
    uploads.append((OUT / "README.md", "README.md"))

    verify_list, todo = [], []
    for local, remote in uploads:
        if remote in existing:
            if existing[remote] == local.stat().st_size:
                print(f"skip upload (present, same size): {remote}")
                verify_list.append((local, remote))
                continue
            if remote == "README.md":
                # Pre-existing README from the earlier RIS pack in this
                # repo — never overwrite; our coverage lives in
                # coverage_report.md.
                print("skip README.md: pre-existing file with different "
                      "size — left untouched by design")
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

    # remote verify
    info = api.dataset_info(REPO, files_metadata=True)
    remote_files = {f.rfilename: f.size for f in (info.siblings or [])}
    problems = []
    for local, remote in verify_list:
        if remote not in remote_files:
            problems.append(f"missing remotely: {remote}")
        elif remote_files[remote] != local.stat().st_size:
            problems.append(f"size mismatch: {remote}")
    p = hf_hub_download(REPO, "data/20911_html.parquet", repo_type="dataset",
                        token=token, force_download=True)
    rows = pq.read_table(p).num_rows
    print(f"remote 20911 parquet rows: {rows}")
    if rows != 211:
        problems.append(f"20911 remote rows {rows} != 211")
    print("remote file count:", len(remote_files))
    print("PROBLEMS:", problems if problems else "none")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
