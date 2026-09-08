"""Upload a local IR release to justicedao/* without printing the token."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

TOKEN_PATH = Path("/home/box/agent-data/connector-secrets/67930c3f-c94b-445b-a5bc-01d3fc1135c1/huggingface.json")


def load_token() -> str:
    payload = json.loads(TOKEN_PATH.read_text(encoding="utf-8"))
    token = payload.get("token")
    if not token:
        raise RuntimeError("Hugging Face token missing from connector secret")
    return token


def upload_release(out: Path, repo_id: str, private: bool = False) -> dict[str, Any]:
    from huggingface_hub import HfApi

    token = load_token()
    api = HfApi(token=token)
    who = api.whoami()
    username = who.get("name")
    orgs = [o.get("name") for o in who.get("orgs", []) if isinstance(o, dict)]
    api.create_repo(repo_id=repo_id, repo_type="dataset", exist_ok=True, private=private)
    info = api.upload_folder(
        repo_id=repo_id,
        repo_type="dataset",
        folder_path=str(out),
        commit_message=f"Update {repo_id} IR release (research / not legal advice)",
        ignore_patterns=["*.pyc", "__pycache__/*"],
    )
    sha = getattr(info, "oid", None) or getattr(info, "commit_id", None) or str(info)
    return {
        "repo_id": repo_id,
        "url": f"https://huggingface.co/datasets/{repo_id}",
        "revision": sha,
        "uploader": username,
        "orgs": orgs,
    }
