"""Hugging Face upload and verification helpers for Netherlands laws packages."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from .paths import (
    BM25_INDEX_DATASET_NAME,
    DEFAULT_HF_NAMESPACE,
    DEFAULT_HF_REPO_IDS,
    HF_DATA_DIR,
    IPFS_DATASET_NAME,
    KNOWLEDGE_GRAPH_DATASET_NAME,
    NORMALIZED_DATASET_NAME,
    VECTOR_INDEX_DATASET_NAME,
    repo_id_for,
)


@dataclass(frozen=True)
class DatasetUploadTarget:
    key: str
    local_dir: Path
    repo_id: str
    required_files: tuple[str, ...]


UPLOAD_TARGETS: dict[str, DatasetUploadTarget] = {
    "base": DatasetUploadTarget(
        key="base",
        local_dir=HF_DATA_DIR / IPFS_DATASET_NAME,
        repo_id=DEFAULT_HF_REPO_IDS["base"],
        required_files=(
            "README.md",
            "dataset_manifest.json",
            "parquet/laws/train-00000-of-00001.parquet",
            "parquet/articles/train-00000-of-00001.parquet",
            "parquet/cid_index/train-00000-of-00001.parquet",
        ),
    ),
    "vector": DatasetUploadTarget(
        key="vector",
        local_dir=HF_DATA_DIR / VECTOR_INDEX_DATASET_NAME,
        repo_id=DEFAULT_HF_REPO_IDS["vector"],
        required_files=("README.md", "dataset_manifest.json", "parquet/mapping/train-00000-of-00001.parquet"),
    ),
    "bm25": DatasetUploadTarget(
        key="bm25",
        local_dir=HF_DATA_DIR / BM25_INDEX_DATASET_NAME,
        repo_id=DEFAULT_HF_REPO_IDS["bm25"],
        required_files=(
            "README.md",
            "dataset_manifest.json",
            "parquet/documents/train-00000-of-00001.parquet",
            "parquet/terms/train-00000-of-00001.parquet",
        ),
    ),
    "knowledge-graph": DatasetUploadTarget(
        key="knowledge-graph",
        local_dir=HF_DATA_DIR / KNOWLEDGE_GRAPH_DATASET_NAME,
        repo_id=DEFAULT_HF_REPO_IDS["knowledge-graph"],
        required_files=(
            "README.md",
            "dataset_manifest.json",
            "data/graph/ipfs_netherlands_laws_kg.jsonld",
            "parquet/nodes/train-00000-of-00001.parquet",
            "parquet/edges/train-00000-of-00001.parquet",
        ),
    ),
    "normalized": DatasetUploadTarget(
        key="normalized",
        local_dir=HF_DATA_DIR / NORMALIZED_DATASET_NAME,
        repo_id=DEFAULT_HF_REPO_IDS["normalized"],
        required_files=(
            "README.md",
            "dataset_manifest.json",
            "parquet/laws/train-00000-of-00001.parquet",
            "parquet/articles/train-00000-of-00001.parquet",
        ),
    ),
}

TARGET_ALIASES = {
    "all": ("base", "vector", "bm25", "knowledge-graph"),
    "ipfs": ("base",),
    "cid": ("base",),
    "kg": ("knowledge-graph",),
    "knowledge_graph": ("knowledge-graph",),
}


def resolve_targets(names: Iterable[str] | None = None, namespace: str = DEFAULT_HF_NAMESPACE) -> list[DatasetUploadTarget]:
    names = tuple(names or ("all",))
    keys: list[str] = []
    for name in names:
        normalized = name.strip().lower()
        expanded = TARGET_ALIASES.get(normalized, (normalized,))
        for key in expanded:
            if key not in UPLOAD_TARGETS:
                raise ValueError(f"Unknown Netherlands laws upload target: {name}")
            if key not in keys:
                keys.append(key)

    resolved: list[DatasetUploadTarget] = []
    for key in keys:
        target = UPLOAD_TARGETS[key]
        resolved.append(
            DatasetUploadTarget(
                key=target.key,
                local_dir=target.local_dir,
                repo_id=repo_id_for(key, namespace) if namespace else target.repo_id,
                required_files=target.required_files,
            )
        )
    return resolved


def token_from_env(token_env: str | None = "HF_TOKEN") -> str | None:
    if not token_env:
        return None
    return os.environ.get(token_env)


def load_local_manifest(local_dir: Path) -> dict[str, Any]:
    return json.loads((local_dir / "dataset_manifest.json").read_text(encoding="utf-8"))


def assert_local_upload_ready(target: DatasetUploadTarget) -> dict[str, Any]:
    missing = [rel for rel in target.required_files if not (target.local_dir / rel).exists()]
    if missing:
        raise FileNotFoundError(f"{target.key} is missing required upload files: {missing}")
    manifest = load_local_manifest(target.local_dir)
    required_manifest_keys = {"files", "records", "repo_target", "upload_target"}
    missing_manifest_keys = sorted(required_manifest_keys - set(manifest))
    if missing_manifest_keys:
        raise ValueError(f"{target.key} manifest missing keys: {missing_manifest_keys}")
    for rel, info in manifest.get("files", {}).items():
        if not {"sha256", "file_cid"}.issubset(info):
            raise ValueError(f"{target.key} manifest file entry missing hash/CID fields: {rel}")
    return manifest


def upload_dataset(
    target: DatasetUploadTarget,
    *,
    token: str | None = None,
    private: bool = False,
    commit_message: str | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    manifest = assert_local_upload_ready(target)
    if dry_run:
        return {"target": target.key, "repo_id": target.repo_id, "local_dir": str(target.local_dir), "dry_run": True}

    from huggingface_hub import HfApi

    api = HfApi(token=token)
    api.create_repo(repo_id=target.repo_id, repo_type="dataset", exist_ok=True, private=private, token=token)
    api.upload_folder(
        folder_path=str(target.local_dir),
        repo_id=target.repo_id,
        repo_type="dataset",
        commit_message=commit_message or f"Update {target.local_dir.name}",
        token=token,
    )
    return {"target": target.key, "repo_id": target.repo_id, "records": manifest["records"], "uploaded": True}


def upload_datasets(
    targets: Iterable[str] | None = None,
    *,
    namespace: str = DEFAULT_HF_NAMESPACE,
    token: str | None = None,
    private: bool = False,
    dry_run: bool = False,
) -> list[dict[str, Any]]:
    return [
        upload_dataset(target, token=token, private=private, dry_run=dry_run)
        for target in resolve_targets(targets, namespace)
    ]


def verify_remote_dataset(target: DatasetUploadTarget, *, token: str | None = None) -> dict[str, Any]:
    from huggingface_hub import HfApi, hf_hub_download

    api = HfApi(token=token)
    files = set(api.list_repo_files(repo_id=target.repo_id, repo_type="dataset"))
    missing = [rel for rel in target.required_files if rel not in files]

    manifest: dict[str, Any] | None = None
    with tempfile.TemporaryDirectory() as tmpdir:
        manifest_path = hf_hub_download(
            repo_id=target.repo_id,
            repo_type="dataset",
            filename="dataset_manifest.json",
            token=token,
            local_dir=tmpdir,
        )
        manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))

    return {
        "target": target.key,
        "repo_id": target.repo_id,
        "ok": not missing and bool(manifest.get("files")) and bool(manifest.get("records")),
        "missing": missing,
        "records": manifest.get("records", {}),
        "file_count": len(files),
    }


def verify_remote_datasets(
    targets: Iterable[str] | None = None,
    *,
    namespace: str = DEFAULT_HF_NAMESPACE,
    token: str | None = None,
) -> list[dict[str, Any]]:
    return [verify_remote_dataset(target, token=token) for target in resolve_targets(targets, namespace)]
