#!/usr/bin/env python3
"""Upload rebuilt parquet shards to a Hugging Face dataset repository.

Supports:
- Optional repo creation.
- Folder upload with allow-patterns.
- Optional remote smoke checks for thin-client retrieval.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from huggingface_hub import HfApi, hf_hub_url, list_repo_files
import requests


def _resolve_token(token: Optional[str]) -> Optional[str]:
    explicit = str(token or "").strip()
    if explicit:
        return explicit
    try:
        from ipfs_datasets_py.processors.legal_data.legal_source_recovery_promotion import _resolve_hf_token

        return _resolve_hf_token()
    except Exception:
        return None


def _range_magic_check(url: str, timeout: int = 60) -> Dict[str, Any]:
    import time
    for attempt in range(3):
        try:
            head = requests.get(url, headers={"Range": "bytes=0-3"}, allow_redirects=True, timeout=timeout)
            foot = requests.get(url, headers={"Range": "bytes=-4"}, allow_redirects=True, timeout=timeout)
            if head.status_code == 429 or foot.status_code == 429:
                wait = 15 * (attempt + 1)
                time.sleep(wait)
                continue
            head.raise_for_status()
            foot.raise_for_status()
            head_bytes = head.content
            foot_bytes = foot.content
            return {
                "header_hex": head_bytes.hex(),
                "footer_hex": foot_bytes.hex(),
                "header_ok": head_bytes == b"PAR1",
                "footer_ok": foot_bytes == b"PAR1",
            }
        except requests.exceptions.HTTPError as exc:
            if attempt < 2:
                time.sleep(15 * (attempt + 1))
                continue
            return {"error": str(exc), "header_ok": False, "footer_ok": False}
    return {"error": "rate_limited_after_retries", "header_ok": False, "footer_ok": False}


def _duckdb_remote_probe(url: str, cid_column: str) -> Dict[str, Any]:
    import duckdb

    con = duckdb.connect()
    schema_rows = con.execute(
        f"DESCRIBE SELECT * FROM read_parquet('{url}')"
    ).fetchall()
    column_names = [str(row[0]) for row in schema_rows]
    probe: Dict[str, Any] = {
        "columns": column_names,
        "cid_column": cid_column,
        "cid_column_present": cid_column in column_names,
    }
    if cid_column not in column_names:
        return probe

    rows = con.execute(
        f"SELECT {cid_column} FROM read_parquet('{url}') WHERE {cid_column} IS NOT NULL LIMIT 5"
    ).fetchall()
    probe["cid_sample"] = [r[0] for r in rows]
    return probe


def _uploaded_parquet_repo_paths(local_dir: Path, path_in_repo: str) -> List[str]:
    prefix = path_in_repo.strip("/")
    repo_paths: List[str] = []
    for path in sorted(local_dir.rglob("*.parquet")):
        relative = path.relative_to(local_dir).as_posix()
        repo_paths.append(f"{prefix}/{relative}" if prefix else relative)
    return repo_paths


def publish(
    local_dir: Path,
    repo_id: str,
    commit_message: str,
    create_repo: bool,
    token: Optional[str],
    path_in_repo: str,
    allow_patterns: Optional[List[str]],
    do_verify: bool,
    cid_column: str,
) -> Dict[str, Any]:
    token = _resolve_token(token)
    api = HfApi(token=token)

    if create_repo:
        api.create_repo(repo_id=repo_id, repo_type="dataset", exist_ok=True)

    upload_info = None
    try:
        upload_info = api.upload_folder(
            folder_path=str(local_dir),
            repo_id=repo_id,
            repo_type="dataset",
            path_in_repo=path_in_repo,
            commit_message=commit_message,
            allow_patterns=allow_patterns,
        )
    except Exception as exc:
        msg = str(exc)
        # HF raises when nothing changed — treat as success (files already current)
        if "no files have been modified" in msg.lower() or "nothing to commit" in msg.lower() or "empty commit" in msg.lower():
            upload_info = "no_change_already_current"
        else:
            raise

    report: Dict[str, Any] = {
        "repo_id": repo_id,
        "upload_commit": str(upload_info),
    }

    if not do_verify:
        return report

    files = list_repo_files(repo_id=repo_id, repo_type="dataset", token=token)
    parquet_files = [f for f in files if f.endswith(".parquet")]
    uploaded_parquet_files = _uploaded_parquet_repo_paths(local_dir=local_dir, path_in_repo=path_in_repo)
    remote_file_set = set(files)
    matched_uploaded_parquet_files = [path for path in uploaded_parquet_files if path in remote_file_set]

    normalized_prefix = path_in_repo.strip("/")
    if normalized_prefix:
        scoped = [f for f in parquet_files if f.startswith(normalized_prefix + "/")]
        if scoped:
            parquet_files = scoped

    report["remote_parquet_count"] = len(parquet_files)
    report["uploaded_parquet_count"] = len(uploaded_parquet_files)
    report["matched_uploaded_parquet_count"] = len(matched_uploaded_parquet_files)

    verification_candidates = matched_uploaded_parquet_files or parquet_files

    if not verification_candidates:
        report["verify_error"] = "No parquet files found after upload"
        return report

    first_file = sorted(verification_candidates)[0]
    url = hf_hub_url(repo_id=repo_id, repo_type="dataset", filename=first_file)

    magic = _range_magic_check(url)
    report["first_file"] = first_file
    report["range_magic"] = magic

    if magic.get("header_ok") and magic.get("footer_ok"):
        try:
            report["duckdb_probe"] = _duckdb_remote_probe(url=url, cid_column=cid_column)
        except Exception as exc:  # pragma: no cover - network/runtime variability
            report["duckdb_probe_error"] = str(exc)

    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Publish local parquet shards to a Hugging Face dataset")
    parser.add_argument("--local-dir", required=True, help="Local directory containing parquet shards")
    parser.add_argument("--repo-id", required=True, help="Hugging Face dataset repo id, e.g. user/dataset")
    parser.add_argument("--token", default=None, help="HF token (optional if already authenticated)")
    parser.add_argument("--create-repo", action="store_true", help="Create dataset repo if missing")
    parser.add_argument("--path-in-repo", default="", help="Destination path inside dataset repo")
    parser.add_argument("--commit-message", default="Publish validated parquet shards", help="Commit message")
    parser.add_argument(
        "--allow-pattern",
        action="append",
        default=["*.parquet", "*.json", "*.md"],
        help="Upload allow-pattern (repeatable)",
    )
    parser.add_argument("--verify", action="store_true", help="Run remote range+duckdb verification after upload")
    parser.add_argument("--cid-column", default="cid", help="CID column name for SQL probe")
    args = parser.parse_args()

    local_dir = Path(args.local_dir).expanduser().resolve()
    if not local_dir.exists():
        raise SystemExit(f"Local directory does not exist: {local_dir}")

    report = publish(
        local_dir=local_dir,
        repo_id=args.repo_id,
        commit_message=args.commit_message,
        create_repo=args.create_repo,
        token=args.token,
        path_in_repo=args.path_in_repo,
        allow_patterns=args.allow_pattern,
        do_verify=args.verify,
        cid_column=args.cid_column,
    )

    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
