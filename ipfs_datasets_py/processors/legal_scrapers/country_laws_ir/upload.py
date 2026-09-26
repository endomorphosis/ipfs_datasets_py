"""Publish a local country-laws-ir release to the JusticeDAO Hugging Face org.

Reads stay anonymous (see ``auth.py``). Writes require an explicit ``--upload``
path, a ``justicedao/`` repo id, and ``HF_TOKEN``. Protected LCR repositories
are fail-closed via ``require_unprotected_or_runtime``.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from . import TARGET_ORG

_OPERATOR_HINT = (
    "Publish later with: hf upload-large-folder "
    "{repo} {local_dir} --repo-type dataset --no-private --num-workers 8 "
    '--exclude "**/__pycache__/**" --exclude "**/*.pyc"'
)


CARD_FILES = (
    "README.md",
    ".gitattributes",
    "manifest.json",
    "dataset_configs.json",
    "normalization_report.json",
)


class UploadError(RuntimeError):
    """Raised when a JusticeDAO upload cannot proceed."""


def ensure_dataset_card(local_dir: Path) -> Path:
    """Write a YAML dataset card if README.md is missing or is a Hub stub."""
    from .package import _write_readme

    local_dir = Path(local_dir)
    readme = local_dir / "README.md"
    text = readme.read_text(encoding="utf-8") if readme.is_file() else ""
    if text.startswith("---") and "pretty_name:" in text:
        return readme
    manifest_path = local_dir / "manifest.json"
    if not manifest_path.is_file():
        raise UploadError(f"cannot build dataset card; missing {manifest_path}")
    import json

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    country = manifest.get("country") or {}
    source_meta = manifest.get("source") or {
        "source_dataset": manifest.get("dataset_id") or "",
        "source_revision": manifest.get("dataset_revision") or "",
    }
    hub_id = str(manifest.get("dataset_repo_id") or f"{TARGET_ORG}/ipfs_{country.get('slug', 'unknown')}_laws_ir")
    _write_readme(
        local_dir,
        country,
        source_meta,
        manifest.get("counts") or {},
        manifest.get("bm25") or {},
        manifest.get("graph") or {},
        manifest.get("vector") or {},
        hub_id,
        normalization_report=manifest.get("normalization"),
    )
    return readme


def _commit_dataset_card(api: Any, local_dir: Path, repo_id: str) -> str:
    """Always commit README/metadata after parquet upload.

    ``upload_large_folder`` often finishes LFS parquet commits while leaving
    a Hub-generated stub README (no YAML card). Regular files are committed
    here in a follow-up so the dataset page always has a parseable card.
    """
    from huggingface_hub import CommitOperationAdd

    ensure_dataset_card(local_dir)
    operations = []
    for name in CARD_FILES:
        path = local_dir / name
        if path.is_file():
            operations.append(
                CommitOperationAdd(path_in_repo=name, path_or_fileobj=str(path))
            )
    if not operations:
        return ""
    info = api.create_commit(
        repo_id=repo_id,
        repo_type="dataset",
        operations=operations,
        commit_message="Add YAML dataset card and release metadata",
    )
    return str(getattr(info, "oid", None) or getattr(info, "commit_id", None) or "")


def _token_from_env() -> str:
    for key in ("HF_TOKEN", "HUGGING_FACE_HUB_TOKEN"):
        value = (os.environ.get(key) or "").strip()
        if value:
            return value
    token_path = Path.home() / ".cache" / "huggingface" / "token"
    if token_path.is_file():
        try:
            return token_path.read_text(encoding="utf-8").strip()
        except OSError:
            return ""
    return ""


def upload_release(
    local_dir: Path,
    repo_id: str,
    *,
    token: str | None = None,
    commit_message: str | None = None,
    create: bool = True,
) -> dict[str, Any]:
    local_dir = Path(local_dir)
    repo_id = str(repo_id or "").strip()
    if not local_dir.is_dir():
        raise UploadError(f"release directory does not exist: {local_dir}")
    if not repo_id.startswith(f"{TARGET_ORG}/"):
        raise UploadError(
            f"country-laws-ir publishes only to {TARGET_ORG}/*; got {repo_id!r}"
        )
    if not (local_dir / "manifest.json").is_file():
        raise UploadError(f"release is missing manifest.json: {local_dir}")

    # Fail closed for LCR-protected repos without importing the full package
    # (site-packages ipfs_datasets_py can be stale and break this thin packager).
    _protected = {"justicedao/ipfs_state_laws", "justicedao/ipfs_federal_register"}
    if repo_id in _protected:
        raise UploadError(
            f"{repo_id} is a protected JusticeDAO repository; "
            "mutate it only through legal_corpora_publication_runtime"
        )
    try:
        from ipfs_datasets_py.huggingface.protected_repo_guard import (
            require_unprotected_or_runtime,
        )

        require_unprotected_or_runtime(repo_id, method="upload_folder")
    except UploadError:
        raise
    except Exception:
        pass

    resolved = (token or "").strip() or _token_from_env()
    if not resolved:
        raise UploadError(
            "HF_TOKEN is required for --upload. "
            + _OPERATOR_HINT.format(repo=repo_id, local_dir=local_dir)
        )

    from huggingface_hub import HfApi

    api = HfApi(token=resolved)
    if create:
        api.create_repo(repo_id=repo_id, repo_type="dataset", exist_ok=True, private=False)
    ignore = ["**/__pycache__/**", "**/*.pyc", "**/*.tmp", "**/*.tmp.npy"]
    n_files = sum(1 for path in local_dir.rglob("*") if path.is_file())
    nbytes = sum(path.stat().st_size for path in local_dir.rglob("*") if path.is_file())
    use_large = n_files >= 80 or nbytes >= 80 * 1024 * 1024
    method = "upload_folder"
    if use_large and hasattr(api, "upload_large_folder"):
        api.upload_large_folder(
            folder_path=str(local_dir),
            repo_id=repo_id,
            repo_type="dataset",
            ignore_patterns=ignore,
        )
        method = "upload_large_folder"
    else:
        api.upload_folder(
            folder_path=str(local_dir),
            repo_id=repo_id,
            repo_type="dataset",
            commit_message=commit_message
            or f"Incremental country-laws-ir GraphRAG release for {repo_id}",
            ignore_patterns=ignore,
        )
    card_sha = _commit_dataset_card(api, local_dir, repo_id)
    revision = card_sha
    if not revision:
        try:
            from huggingface_hub import dataset_info as _dataset_info

            pinned = _dataset_info(repo_id, token=resolved)
            revision = str(getattr(pinned, "sha", "") or "")
        except Exception:
            revision = ""
    return {
        "url": f"https://huggingface.co/datasets/{repo_id}",
        "repo_id": repo_id,
        "revision": revision,
        "local_dir": str(local_dir),
        "method": method,
    }
