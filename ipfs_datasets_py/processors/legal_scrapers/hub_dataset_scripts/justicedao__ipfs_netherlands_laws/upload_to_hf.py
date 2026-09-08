#!/usr/bin/env python3
"""Upload the IPFS Netherlands laws package to Hugging Face."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from huggingface_hub import HfApi


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-id", default="justicedao/ipfs_netherlands_laws")
    parser.add_argument("--token", default=None)
    parser.add_argument("--private", action="store_true")
    args = parser.parse_args()

    root = Path(__file__).resolve().parent
    api = HfApi(token=args.token)
    api.create_repo(repo_id=args.repo_id, repo_type="dataset", exist_ok=True, private=args.private)
    result = api.upload_folder(
        folder_path=str(root),
        repo_id=args.repo_id,
        repo_type="dataset",
        commit_message="Publish IPFS Netherlands laws dataset with CIDs",
        allow_patterns=["*.md", "*.json", "*.jsonl", "*.parquet", ".gitattributes"],
    )
    print(json.dumps({"repo_id": args.repo_id, "upload_commit": str(result)}, indent=2))


if __name__ == "__main__":
    main()
