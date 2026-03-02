#!/usr/bin/env python3
"""Publish Oregon Administrative Rules dataset artifacts to Hugging Face.

This is a thin convenience wrapper around scripts/repair/publish_parquet_to_hf.py
with defaults tailored for OAR outputs.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _bootstrap_pythonpath() -> None:
    root = _repo_root()
    root_str = str(root)
    if root_str not in sys.path:
        sys.path.insert(0, root_str)


def _default_local_dir() -> Path:
    return _repo_root() / "data" / "state_administrative_rules" / "OR" / "parsed"


def _publish(args: argparse.Namespace) -> Dict[str, Any]:
    _bootstrap_pythonpath()
    from scripts.repair.publish_parquet_to_hf import publish

    local_dir = Path(args.local_dir).expanduser().resolve()
    if not local_dir.exists():
        raise FileNotFoundError(f"Local directory does not exist: {local_dir}")

    if args.dry_run:
        parquet_files = sorted(str(p.relative_to(local_dir)) for p in local_dir.rglob("*.parquet"))
        json_files = sorted(str(p.relative_to(local_dir)) for p in local_dir.rglob("*.json"))
        jsonl_files = sorted(str(p.relative_to(local_dir)) for p in local_dir.rglob("*.jsonl"))
        return {
            "status": "dry_run",
            "local_dir": str(local_dir),
            "repo_id": args.repo_id,
            "path_in_repo": args.path_in_repo,
            "create_repo": bool(args.create_repo),
            "verify": bool(args.verify),
            "counts": {
                "parquet": len(parquet_files),
                "json": len(json_files),
                "jsonl": len(jsonl_files),
            },
            "sample_files": {
                "parquet": parquet_files[:5],
                "json": json_files[:5],
                "jsonl": jsonl_files[:5],
            },
        }

    allow_patterns = ["*.parquet", "*.json", "*.jsonl", "*.md"]
    return publish(
        local_dir=local_dir,
        repo_id=args.repo_id,
        commit_message=args.commit_message,
        create_repo=args.create_repo,
        token=args.token,
        path_in_repo=args.path_in_repo,
        allow_patterns=allow_patterns,
        do_verify=args.verify,
        cid_column=args.cid_column,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Publish Oregon administrative rules dataset to Hugging Face")
    parser.add_argument("--local-dir", default=str(_default_local_dir()))
    parser.add_argument("--repo-id", default="justicedao/ipfs_state_admin_rules")
    parser.add_argument("--path-in-repo", default="OR/parsed")
    parser.add_argument("--token", default=None, help="HF token (optional if already authenticated)")
    parser.add_argument("--create-repo", action="store_true")
    parser.add_argument("--verify", action="store_true", help="Run remote parquet verification")
    parser.add_argument("--dry-run", action="store_true", help="Print upload plan without pushing files")
    parser.add_argument("--cid-column", default="statute_id")
    parser.add_argument(
        "--commit-message",
        default="Publish Oregon Administrative Rules dataset",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = _publish(args)
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
