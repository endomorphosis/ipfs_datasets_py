"""Upload a local IR release to justicedao/* without printing the token."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .auth import configure_hf, load_token


def upload_release(out: Path, repo_id: str, private: bool = False) -> dict[str, Any]:
    from huggingface_hub import HfApi

    configure_hf()
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
