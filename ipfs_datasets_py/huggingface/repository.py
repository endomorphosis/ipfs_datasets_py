"""Injected, read-only access to immutable Hugging Face repository revisions."""

from __future__ import annotations

import json
import os
import re
import shutil
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..logic.ir_core.canonical import canonical_json_bytes
from .snapshot import (
    HuggingFaceSnapshot,
    HuggingFaceSnapshotFetchError,
)

HUGGINGFACE_REPOSITORY_REVISION_SCHEMA_VERSION = "huggingface-repository-revision/v1"
_COMMIT_SHA_RE = re.compile(r"^[0-9a-f]{40,64}$")
_REPO_TYPES = frozenset({"dataset", "model", "space"})


class HuggingFaceRepositoryError(ValueError):
    """Raised when repository metadata cannot prove an immutable revision."""


def _text(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or not value or value.strip() != value:
        raise HuggingFaceRepositoryError(f"{label} must be a non-empty string without surrounding whitespace")
    if "\x00" in value:
        raise HuggingFaceRepositoryError(f"{label} must not contain NUL")
    return value


def _commit_sha(value: Any, *, label: str = "commit_sha") -> str:
    sha = _text(value, label=label)
    if not _COMMIT_SHA_RE.fullmatch(sha):
        raise HuggingFaceRepositoryError(f"{label} must be a 40-64 character lowercase hexadecimal commit SHA")
    return sha


@dataclass(frozen=True, slots=True)
class HuggingFaceRepositoryRevision:
    """Canonical receipt mapping a requested ref to an immutable commit."""

    repository_id: str
    requested_revision: str
    commit_sha: str
    repository_type: str = "dataset"
    schema_version: str = HUGGINGFACE_REPOSITORY_REVISION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        repository_id = _text(self.repository_id, label="repository_id")
        requested = _text(self.requested_revision, label="requested_revision")
        commit_sha = _commit_sha(self.commit_sha)
        repository_type = _text(self.repository_type, label="repository_type").casefold()
        if repository_type not in _REPO_TYPES:
            raise HuggingFaceRepositoryError("repository_type must be dataset, model, or space")
        if self.schema_version != HUGGINGFACE_REPOSITORY_REVISION_SCHEMA_VERSION:
            raise HuggingFaceRepositoryError("unsupported Hugging Face repository revision schema_version")
        object.__setattr__(self, "repository_id", repository_id)
        object.__setattr__(self, "requested_revision", requested)
        object.__setattr__(self, "commit_sha", commit_sha)
        object.__setattr__(self, "repository_type", repository_type)

    def to_dict(self) -> dict[str, str]:
        return {
            "commit_sha": self.commit_sha,
            "repository_id": self.repository_id,
            "repository_type": self.repository_type,
            "requested_revision": self.requested_revision,
            "schema_version": self.schema_version,
        }

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_dict())

    def to_json(self) -> str:
        return self.canonical_bytes().decode("utf-8")

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> HuggingFaceRepositoryRevision:
        if not isinstance(value, Mapping):
            raise HuggingFaceRepositoryError("revision receipt must be a mapping")
        expected = {
            "commit_sha",
            "repository_id",
            "repository_type",
            "requested_revision",
            "schema_version",
        }
        if set(value) != expected:
            raise HuggingFaceRepositoryError("revision receipt has unknown or missing fields")
        if any(not isinstance(value[field], str) for field in expected):
            raise HuggingFaceRepositoryError("revision receipt fields must be strings")
        return cls(
            repository_id=value["repository_id"],
            requested_revision=value["requested_revision"],
            commit_sha=value["commit_sha"],
            repository_type=value["repository_type"],
            schema_version=value["schema_version"],
        )

    @classmethod
    def from_json(cls, value: str | bytes | bytearray) -> HuggingFaceRepositoryRevision:
        if isinstance(value, bytes | bytearray):
            try:
                value = bytes(value).decode("utf-8")
            except UnicodeDecodeError as exc:
                raise HuggingFaceRepositoryError("revision receipt JSON must be UTF-8") from exc
        if not isinstance(value, str):
            raise TypeError("revision receipt JSON must be str or bytes")
        try:
            decoded = json.loads(value)
        except (TypeError, ValueError) as exc:
            raise HuggingFaceRepositoryError(f"invalid revision receipt JSON: {exc}") from exc
        return cls.from_dict(decoded)


class HuggingFaceRepository:
    """Resolve repository refs through an explicitly injected metadata client."""

    def __init__(
        self,
        repository_id: str,
        *,
        client: Any,
        repository_type: str = "dataset",
    ) -> None:
        self.repository_id = _text(repository_id, label="repository_id")
        repository_type = _text(repository_type, label="repository_type").casefold()
        if repository_type not in _REPO_TYPES:
            raise HuggingFaceRepositoryError("repository_type must be dataset, model, or space")
        if client is None:
            raise HuggingFaceRepositoryError("an injected repository metadata client is required")
        self.repository_type = repository_type
        self.client = client

    def resolve_revision(self, revision: str) -> HuggingFaceRepositoryRevision:
        """Resolve ``revision`` and return a receipt containing only its commit."""

        requested = _text(revision, label="revision")
        repo_info = getattr(self.client, "repo_info", None)
        if not callable(repo_info):
            repo_info = self.client if callable(self.client) else None
        if not callable(repo_info):
            raise HuggingFaceRepositoryError("repository client must be callable or provide repo_info")
        try:
            info = repo_info(
                repo_id=self.repository_id,
                revision=requested,
                repo_type=self.repository_type,
            )
        except Exception as exc:
            raise HuggingFaceRepositoryError(f"failed to resolve repository revision: {exc}") from exc
        commit = info.get("sha") if isinstance(info, Mapping) else getattr(info, "sha", None)
        return HuggingFaceRepositoryRevision(
            repository_id=self.repository_id,
            requested_revision=requested,
            commit_sha=_commit_sha(commit, label="resolved commit_sha"),
            repository_type=self.repository_type,
        )

    def snapshot(
        self,
        *,
        revision: str,
        repository_file: str,
        expected_sha256: str,
        expected_size_bytes: int,
        **snapshot_options: Any,
    ) -> HuggingFaceSnapshot:
        """Resolve a ref and build a canonical snapshot pinned to its commit."""

        resolved = self.resolve_revision(revision)
        if self.repository_type != "dataset":
            raise HuggingFaceRepositoryError("the compatibility snapshot/cache currently supports datasets")
        return HuggingFaceSnapshot(
            dataset_id=self.repository_id,
            dataset_revision=resolved.commit_sha,
            repository_file=repository_file,
            expected_sha256=expected_sha256,
            expected_size_bytes=expected_size_bytes,
            **snapshot_options,
        )


class HuggingFaceRepositoryFetcher:
    """Snapshot fetcher backed by an explicitly injected download operation."""

    producer_id = "producer:huggingface-repository-download"

    def __init__(
        self,
        *,
        download: Callable[..., str | os.PathLike[str]],
        local_files_only: bool = False,
    ) -> None:
        if not callable(download):
            raise TypeError("download must be callable")
        self.download = download
        self.local_files_only = bool(local_files_only)

    def __call__(
        self,
        snapshot: HuggingFaceSnapshot,
        destination: Path,
    ) -> Path:
        try:
            downloaded = self.download(
                repo_id=snapshot.dataset_id,
                filename=snapshot.repository_file,
                revision=snapshot.dataset_revision,
                repo_type="dataset",
                local_files_only=self.local_files_only,
            )
            source = Path(downloaded)
            if not source.is_file():
                raise OSError("download did not return a file")
            shutil.copyfile(source, destination)
        except Exception as exc:
            raise HuggingFaceSnapshotFetchError(f"failed to fetch {snapshot.logical_source}: {exc}") from exc
        return destination


__all__ = [
    "HUGGINGFACE_REPOSITORY_REVISION_SCHEMA_VERSION",
    "HuggingFaceRepository",
    "HuggingFaceRepositoryError",
    "HuggingFaceRepositoryFetcher",
    "HuggingFaceRepositoryRevision",
]
