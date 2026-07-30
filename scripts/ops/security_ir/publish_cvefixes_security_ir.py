#!/usr/bin/env python3
"""Safely publish and verify a staged CVEfixes Security IR Hub release.

The command is deliberately dry-run by default.  ``--execute`` reads a token
from the named environment variable, authenticates it, searches the bounded
Hub history for the release tuple, and uploads only when that tuple is absent.
No token is accepted on the command line or included in output, exceptions,
commit metadata, or receipts.

A publication receipt is only a *proposal*: it cannot grant completion or
execution authority.  It is produced after the immutable Hub commit, every
remote artifact, and the Dataset Viewer shards/features have been verified.
"""

from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import sys
import time
from typing import Any, Final, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen


DEFAULT_TARGET_REPO: Final = "sofiyapervane/cvefixes-security-ir-graphrag"
PUBLICATION_RECEIPT_VERSION: Final = (
    "cvefixes-security-ir-publication-receipt/v1"
)
RELEASE_SCHEMA_VERSION: Final = "cvefixes-huggingface-release/v1"
PARQUET_SCHEMA_VERSION: Final = "cvefixes-huggingface-parquet/v1"
EXPECTED_COLUMNS: Final[tuple[str, ...]] = (
    "record_id",
    "record_type",
    "authority",
    "source_cids",
    "parent_cids",
    "config_cid",
    "record_json",
)
MAX_MANIFEST_BYTES: Final = 8 * 1024 * 1024
MAX_VIEWER_RESPONSE_BYTES: Final = 16 * 1024 * 1024
MAX_ARTIFACT_BYTES: Final = 128 * 1024 * 1024
MAX_ARTIFACTS: Final = 2_048
MAX_HISTORY_COMMITS: Final = 100

_DATASET_ID_RE = re.compile(
    r"[A-Za-z0-9][A-Za-z0-9._-]{0,95}/"
    r"[A-Za-z0-9][A-Za-z0-9._-]{0,95}"
)
_CID_RE = re.compile(r"b[a-z2-7]{58}")
_SHA256_RE = re.compile(r"[0-9a-f]{64}")
_COMMIT_RE = re.compile(r"[0-9a-f]{40,64}")
_CONFIG_RE = re.compile(r"[a-z][a-z0-9_]{0,63}")
_ENV_RE = re.compile(r"[A-Z][A-Z0-9_]{0,127}")
_SECRET_VALUE_RE = re.compile(
    r"(?:-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----|"
    r"(?<![A-Za-z0-9])(?:gh[pousr]_[A-Za-z0-9]{30,255}|"
    r"github_pat_[A-Za-z0-9_]{40,255}|"
    r"hf_[A-Za-z0-9]{20,255}|"
    r"sk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{20,})(?![A-Za-z0-9]))"
)
_SECRET_KEYS: Final[frozenset[str]] = frozenset(
    {
        "access_token",
        "api_key",
        "authorization",
        "credential",
        "credentials",
        "hf_token",
        "password",
        "private_key",
        "secret",
        "token",
    }
)
_JSON_MEDIA_TYPES: Final[frozenset[str]] = frozenset(
    {"application/json", "text/markdown; charset=utf-8"}
)


class PublicationError(RuntimeError):
    """Base class for safe, user-facing publication failures."""


class LocalReleaseError(PublicationError):
    """The staged release is malformed, unsafe, or internally inconsistent."""


class AuthenticationError(PublicationError):
    """The explicitly supplied environment credential is absent or rejected."""


class RemoteVerificationError(PublicationError):
    """The immutable Hub data or Dataset Viewer response failed closed."""


class ViewerNotReadyError(RemoteVerificationError):
    """The Dataset Viewer has not finished processing the current release."""


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=True, allow_nan=False, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")


def _object(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise LocalReleaseError(f"{label} must be a JSON object")
    return value


def _bounded_bytes(path: Path, *, maximum: int, label: str) -> bytes:
    try:
        stat = path.stat()
    except OSError as exc:
        raise LocalReleaseError(f"cannot inspect {label}") from exc
    if not path.is_file() or path.is_symlink():
        raise LocalReleaseError(f"{label} must be a regular file")
    if stat.st_size > maximum:
        raise LocalReleaseError(f"{label} exceeds its byte limit")
    try:
        return path.read_bytes()
    except OSError as exc:
        raise LocalReleaseError(f"cannot read {label}") from exc


def _json_bytes(content: bytes, label: str) -> Mapping[str, Any]:
    try:
        value = json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LocalReleaseError(f"{label} is not valid UTF-8 JSON") from exc
    return _object(value, label)


def _safe_artifact_path(value: Any) -> str:
    if not isinstance(value, str) or not value or len(value) > 512:
        raise LocalReleaseError("artifact path must be bounded text")
    parsed = PurePosixPath(value)
    if (
        parsed.is_absolute()
        or value != parsed.as_posix()
        or "\\" in value
        or any(part in {"", ".", ".."} for part in parsed.parts)
    ):
        raise LocalReleaseError("artifact path is unsafe")
    if len(parsed.parts) == 1:
        if value not in {
            "README.md",
            "dataset_infos.json",
            "evaluation-report.json",
        }:
            raise LocalReleaseError("unexpected top-level release artifact")
    elif (
        len(parsed.parts) != 3
        or parsed.parts[0] != "data"
        or not _CONFIG_RE.fullmatch(parsed.parts[1])
        or not re.fullmatch(
            r"train-\d{5}-of-\d{5}\.parquet", parsed.parts[2]
        )
    ):
        raise LocalReleaseError("unexpected release artifact path")
    return value


def _safe_public_value(value: Any, *, location: str = "$") -> None:
    if isinstance(value, Mapping):
        for raw_key, item in value.items():
            if not isinstance(raw_key, str):
                raise LocalReleaseError(f"non-string key at {location}")
            if raw_key.casefold() in _SECRET_KEYS:
                raise LocalReleaseError(
                    f"credential-like field is forbidden at {location}"
                )
            _safe_public_value(item, location=f"{location}.{raw_key}")
        return
    if isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray)
    ):
        for index, item in enumerate(value):
            _safe_public_value(item, location=f"{location}[{index}]")
        return
    if isinstance(value, str) and _SECRET_VALUE_RE.search(value):
        raise LocalReleaseError(f"secret-like value is forbidden at {location}")


@dataclass(frozen=True, slots=True)
class ArtifactDescriptor:
    path: str
    media_type: str
    byte_length: int
    sha256: str
    content_id: str
    config_name: str = ""
    row_count: int = 0

    @classmethod
    def from_dict(cls, value: Any) -> "ArtifactDescriptor":
        item = _object(value, "artifact descriptor")
        path = _safe_artifact_path(item.get("path"))
        parquet = path.endswith(".parquet")
        required = {
            "byte_length",
            "content_id",
            "media_type",
            "path",
            "sha256",
        }
        if parquet:
            required |= {"config_name", "row_count"}
        if set(item) != required:
            raise LocalReleaseError("artifact descriptor fields are not canonical")
        byte_length = item["byte_length"]
        row_count = item.get("row_count", 0)
        media_type = item["media_type"]
        sha256 = item["sha256"]
        content_id = item["content_id"]
        config_name = item.get("config_name", "")
        if (
            type(byte_length) is not int
            or byte_length < 0
            or byte_length > MAX_ARTIFACT_BYTES
        ):
            raise LocalReleaseError("artifact byte_length is invalid")
        if not isinstance(media_type, str) or not media_type or len(media_type) > 128:
            raise LocalReleaseError("artifact media_type is invalid")
        if not isinstance(sha256, str) or not _SHA256_RE.fullmatch(sha256):
            raise LocalReleaseError("artifact SHA-256 is invalid")
        if not isinstance(content_id, str) or not _CID_RE.fullmatch(content_id):
            raise LocalReleaseError("artifact content ID is invalid")
        if parquet:
            if (
                media_type != "application/vnd.apache.parquet"
                or not isinstance(config_name, str)
                or not _CONFIG_RE.fullmatch(config_name)
                or PurePosixPath(path).parts[1] != config_name
                or type(row_count) is not int
                or row_count <= 0
            ):
                raise LocalReleaseError("Parquet descriptor metadata is invalid")
        elif media_type not in _JSON_MEDIA_TYPES:
            raise LocalReleaseError("release artifact media type is unexpected")
        return cls(
            path=path,
            media_type=media_type,
            byte_length=byte_length,
            sha256=sha256,
            content_id=content_id,
            config_name=config_name,
            row_count=row_count,
        )

    def receipt_dict(self) -> dict[str, Any]:
        return {
            "byte_length": self.byte_length,
            "config_name": self.config_name,
            "content_id": self.content_id,
            "path": self.path,
            "row_count": self.row_count,
            "sha256": self.sha256,
        }


@dataclass(frozen=True, slots=True)
class LocalRelease:
    directory: Path
    dataset_id: str
    source_dataset_id: str
    source_revision: str
    release_root: str
    manifest_bytes: bytes
    manifest_sha256: str
    artifacts: tuple[ArtifactDescriptor, ...]
    config_names: tuple[str, ...]
    config_shard_counts: tuple[tuple[str, int], ...]

    @property
    def parquet_artifacts(self) -> tuple[ArtifactDescriptor, ...]:
        return tuple(item for item in self.artifacts if item.config_name)

    @property
    def idempotency_key(self) -> str:
        digest = hashlib.sha256(
            _canonical_json(
                {
                    "release_root": self.release_root,
                    "source_revision": self.source_revision,
                    "target_repo": self.dataset_id,
                }
            )
        ).hexdigest()
        return f"cvefixes-publication:{digest}"


def _validate_parquet(
    path: Path, descriptor: ArtifactDescriptor
) -> None:
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError as exc:  # pragma: no cover - release dependency in CI
        raise LocalReleaseError(
            "pyarrow is required to validate release shards"
        ) from exc
    try:
        parquet = pq.ParquetFile(path)
        schema = parquet.schema_arrow
    except Exception as exc:
        raise LocalReleaseError(
            f"Parquet shard is unreadable: {descriptor.path}"
        ) from exc
    if tuple(schema.names) != EXPECTED_COLUMNS:
        raise LocalReleaseError(
            f"Parquet schema mismatch: {descriptor.path}"
        )
    scalar_columns = {
        "record_id",
        "record_type",
        "authority",
        "config_cid",
        "record_json",
    }
    for field in schema:
        if field.name in scalar_columns and not pa.types.is_string(field.type):
            raise LocalReleaseError("Parquet scalar columns must be strings")
        if field.name in {"source_cids", "parent_cids"} and not (
            pa.types.is_list(field.type)
            and pa.types.is_string(field.type.value_type)
        ):
            raise LocalReleaseError("Parquet lineage columns must be string lists")
    if parquet.metadata.num_rows != descriptor.row_count:
        raise LocalReleaseError("Parquet row count does not match manifest")
    rows_seen = 0
    try:
        batches = parquet.iter_batches(
            batch_size=1_024,
            columns=("record_id", "record_type", "record_json"),
        )
        for batch in batches:
            for row in batch.to_pylist():
                record_id = row["record_id"]
                record_type = row["record_type"]
                record_json = row["record_json"]
                if (
                    not isinstance(record_id, str)
                    or not isinstance(record_type, str)
                    or record_type != descriptor.config_name
                    or not isinstance(record_json, str)
                ):
                    raise LocalReleaseError(
                        "Parquet row identity columns are invalid"
                    )
                record = _json_bytes(
                    record_json.encode("utf-8"), "Parquet record_json"
                )
                _safe_public_value(record, location="$.record_json")
                if (
                    record.get("record_id") != record_id
                    or record.get("record_type") != record_type
                    or _canonical_json(record).decode("utf-8") != record_json
                ):
                    raise LocalReleaseError(
                        "Parquet canonical row identity is invalid"
                    )
                rows_seen += 1
    except LocalReleaseError:
        raise
    except Exception as exc:
        raise LocalReleaseError("Parquet row validation failed") from exc
    if rows_seen != descriptor.row_count:
        raise LocalReleaseError("Parquet scanned row count is inconsistent")


def load_local_release(
    release_directory: str | os.PathLike[str],
    *,
    expected_target: str | None = None,
) -> LocalRelease:
    """Fail-closed validation of a previously staged local release."""

    root = Path(release_directory)
    if not root.exists() or not root.is_dir() or root.is_symlink():
        raise LocalReleaseError("release directory must be a real directory")
    try:
        root = root.resolve(strict=True)
    except OSError as exc:
        raise LocalReleaseError("cannot resolve release directory") from exc

    manifest_path = root / "manifest.json"
    manifest_bytes = _bounded_bytes(
        manifest_path, maximum=MAX_MANIFEST_BYTES, label="manifest.json"
    )
    manifest = _json_bytes(manifest_bytes, "manifest.json")
    if set(manifest) != {
        "artifacts",
        "dataset_id",
        "derived_dataset_root",
        "release_manifest",
        "release_root",
        "schema_version",
        "source",
    }:
        raise LocalReleaseError("manifest fields are not canonical")
    _safe_public_value(manifest)
    dataset_id = manifest.get("dataset_id")
    release_root = manifest.get("release_root")
    if (
        not isinstance(dataset_id, str)
        or not _DATASET_ID_RE.fullmatch(dataset_id)
        or (expected_target is not None and dataset_id != expected_target)
    ):
        raise LocalReleaseError("manifest target dataset does not match")
    if (
        not isinstance(release_root, str)
        or not _CID_RE.fullmatch(release_root)
        or manifest.get("schema_version") != RELEASE_SCHEMA_VERSION
    ):
        raise LocalReleaseError("manifest release identity is invalid")

    source = _object(manifest.get("source"), "manifest source")
    source_dataset_id = source.get("dataset_id")
    source_revision = source.get("source_revision")
    if (
        not isinstance(source_dataset_id, str)
        or not source_dataset_id
        or not isinstance(source_revision, str)
        or not source_revision
        or len(source_revision) > 256
    ):
        raise LocalReleaseError("manifest source binding is invalid")

    release_manifest = _object(
        manifest.get("release_manifest"), "canonical release manifest"
    )
    payload = _object(release_manifest.get("payload"), "release manifest payload")
    if (
        release_manifest.get("dataset_id") != dataset_id
        or payload.get("release_root") != release_root
        or payload.get("release_schema_version") != RELEASE_SCHEMA_VERSION
    ):
        raise LocalReleaseError("canonical release manifest binding is invalid")

    raw_artifacts = manifest.get("artifacts")
    if (
        not isinstance(raw_artifacts, list)
        or not raw_artifacts
        or len(raw_artifacts) > MAX_ARTIFACTS
    ):
        raise LocalReleaseError("manifest artifact inventory is invalid")
    artifacts = tuple(
        ArtifactDescriptor.from_dict(item) for item in raw_artifacts
    )
    paths = tuple(item.path for item in artifacts)
    if paths != tuple(sorted(paths)) or len(set(paths)) != len(paths):
        raise LocalReleaseError("artifact inventory must be sorted and unique")
    required = {"README.md", "dataset_infos.json", "evaluation-report.json"}
    if not required <= set(paths) or not any(item.config_name for item in artifacts):
        raise LocalReleaseError("release artifact inventory is incomplete")

    actual_files: set[str] = set()
    for candidate in root.rglob("*"):
        if candidate.is_symlink():
            raise LocalReleaseError("release directory cannot contain symlinks")
        if candidate.is_file():
            actual_files.add(candidate.relative_to(root).as_posix())
        elif not candidate.is_dir():
            raise LocalReleaseError("release directory contains a special file")
    if actual_files != set(paths) | {"manifest.json"}:
        raise LocalReleaseError("local files do not exactly match the manifest")

    for descriptor in artifacts:
        path = root.joinpath(*PurePosixPath(descriptor.path).parts)
        content = _bounded_bytes(
            path,
            maximum=MAX_ARTIFACT_BYTES,
            label=f"artifact {descriptor.path}",
        )
        if (
            len(content) != descriptor.byte_length
            or hashlib.sha256(content).hexdigest() != descriptor.sha256
        ):
            raise LocalReleaseError(
                f"artifact content mismatch: {descriptor.path}"
            )
        if descriptor.config_name:
            _validate_parquet(path, descriptor)
        elif descriptor.path.endswith(".json"):
            _safe_public_value(
                _json_bytes(content, descriptor.path),
                location=f"$.{descriptor.path}",
            )
        else:
            try:
                text = content.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise LocalReleaseError("README.md must be valid UTF-8") from exc
            if _SECRET_VALUE_RE.search(text):
                raise LocalReleaseError(
                    "secret-like value is forbidden in README.md"
                )

    infos = _json_bytes(
        _bounded_bytes(
            root / "dataset_infos.json",
            maximum=MAX_MANIFEST_BYTES,
            label="dataset_infos.json",
        ),
        "dataset_infos.json",
    )
    configs = _object(infos.get("configs"), "dataset configs")
    if (
        infos.get("dataset_id") != dataset_id
        or infos.get("derived_dataset_root") != manifest.get("derived_dataset_root")
        or infos.get("schema_version") != PARQUET_SCHEMA_VERSION
        or not configs
    ):
        raise LocalReleaseError("dataset_infos release binding is invalid")
    config_names = tuple(sorted(configs))
    if any(not _CONFIG_RE.fullmatch(name) for name in config_names):
        raise LocalReleaseError("dataset config name is invalid")
    shard_counts: dict[str, int] = {}
    for descriptor in artifacts:
        if descriptor.config_name:
            shard_counts[descriptor.config_name] = (
                shard_counts.get(descriptor.config_name, 0) + 1
            )
    if tuple(sorted(shard_counts)) != config_names:
        raise LocalReleaseError("dataset configs do not match Parquet shards")
    for name in config_names:
        config = _object(configs[name], f"dataset config {name}")
        features = _object(config.get("features"), f"dataset config {name} features")
        splits = _object(config.get("splits"), f"dataset config {name} splits")
        train = _object(splits.get("train"), f"dataset config {name} train split")
        if set(features) != set(EXPECTED_COLUMNS):
            raise LocalReleaseError("dataset config feature schema is invalid")
        expected_rows = sum(
            item.row_count for item in artifacts if item.config_name == name
        )
        expected_bytes = sum(
            item.byte_length for item in artifacts if item.config_name == name
        )
        if (
            train.get("num_examples") != expected_rows
            or train.get("num_bytes") != expected_bytes
        ):
            raise LocalReleaseError("dataset config row inventory is invalid")

    declared_shards = release_manifest.get("shard_cids")
    if (
        not isinstance(declared_shards, list)
        or set(declared_shards)
        != {
            item.content_id for item in artifacts if item.config_name
        }
    ):
        raise LocalReleaseError("release manifest shard inventory is invalid")

    return LocalRelease(
        directory=root,
        dataset_id=dataset_id,
        source_dataset_id=source_dataset_id,
        source_revision=source_revision,
        release_root=release_root,
        manifest_bytes=manifest_bytes,
        manifest_sha256=hashlib.sha256(manifest_bytes).hexdigest(),
        artifacts=artifacts,
        config_names=config_names,
        config_shard_counts=tuple(sorted(shard_counts.items())),
    )


class HubGateway(Protocol):
    """Small injectable side-effect boundary used by the command and tests."""

    def authenticate(self, token: str) -> str: ...

    def head(self, repo_id: str, token: str | None) -> str: ...

    def revisions(
        self, repo_id: str, token: str | None, *, limit: int
    ) -> Sequence[str]: ...

    def read_file(
        self, repo_id: str, revision: str, path: str, token: str | None
    ) -> bytes: ...

    def upload(
        self,
        release: LocalRelease,
        token: str,
        *,
        parent_commit: str,
        commit_message: str,
        commit_description: str,
    ) -> str: ...

    def viewer(
        self,
        endpoint: str,
        params: Mapping[str, str],
        token: str | None,
    ) -> Mapping[str, Any]: ...


class HuggingFaceHubGateway:
    """Production Hub gateway with bounded, cache-free remote reads."""

    def __init__(
        self,
        *,
        hub_base_url: str = "https://huggingface.co",
        viewer_base_url: str = "https://datasets-server.huggingface.co",
        timeout_seconds: float = 30.0,
    ) -> None:
        self._hub_base_url = hub_base_url.rstrip("/")
        self._viewer_base_url = viewer_base_url.rstrip("/")
        self._timeout = timeout_seconds

    @staticmethod
    def _api() -> Any:
        try:
            from huggingface_hub import HfApi
        except ImportError as exc:  # pragma: no cover - normal project dependency
            raise PublicationError("huggingface_hub is required for publication") from exc
        return HfApi()

    def authenticate(self, token: str) -> str:
        try:
            identity = self._api().whoami(token=token)
        except Exception as exc:
            raise AuthenticationError("Hugging Face authentication failed") from exc
        if not isinstance(identity, Mapping):
            raise AuthenticationError("Hugging Face returned no authenticated identity")
        principal = identity.get("name") or identity.get("fullname")
        if not isinstance(principal, str) or not principal.strip():
            raise AuthenticationError("Hugging Face returned no authenticated identity")
        return principal.strip()

    def head(self, repo_id: str, token: str | None) -> str:
        try:
            info = self._api().repo_info(
                repo_id=repo_id,
                repo_type="dataset",
                revision="main",
                token=token,
            )
            commit = getattr(info, "sha", "")
        except Exception as exc:
            raise RemoteVerificationError("cannot resolve Hub dataset head") from exc
        if not isinstance(commit, str) or not _COMMIT_RE.fullmatch(commit):
            raise RemoteVerificationError("Hub dataset head is not immutable")
        return commit

    def revisions(
        self, repo_id: str, token: str | None, *, limit: int
    ) -> Sequence[str]:
        try:
            commits = self._api().list_repo_commits(
                repo_id, repo_type="dataset", token=token
            )
        except Exception as exc:
            raise RemoteVerificationError("cannot inspect Hub dataset history") from exc
        result: list[str] = []
        for item in commits[:limit]:
            commit = getattr(item, "commit_id", "")
            if isinstance(commit, str) and _COMMIT_RE.fullmatch(commit):
                result.append(commit)
        return tuple(result)

    def _read_url(
        self, url: str, token: str | None, *, maximum: int
    ) -> bytes:
        headers = {"Accept": "application/json", "User-Agent": "cvefixes-security-ir-publisher/1"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        request = Request(url, headers=headers)
        try:
            with urlopen(request, timeout=self._timeout) as response:
                length = response.headers.get("Content-Length")
                if length and int(length) > maximum:
                    raise RemoteVerificationError("remote response exceeds byte limit")
                content = response.read(maximum + 1)
        except RemoteVerificationError:
            raise
        except (HTTPError, URLError, OSError, ValueError) as exc:
            raise RemoteVerificationError("bounded remote read failed") from exc
        if len(content) > maximum:
            raise RemoteVerificationError("remote response exceeds byte limit")
        return content

    def read_file(
        self, repo_id: str, revision: str, path: str, token: str | None
    ) -> bytes:
        if not _DATASET_ID_RE.fullmatch(repo_id) or not _COMMIT_RE.fullmatch(revision):
            raise RemoteVerificationError("unsafe Hub file binding")
        safe_path = _safe_artifact_path(path) if path != "manifest.json" else path
        url = (
            f"{self._hub_base_url}/datasets/{quote(repo_id, safe='/')}/resolve/"
            f"{quote(revision, safe='')}/{quote(safe_path, safe='/')}"
        )
        maximum = (
            MAX_MANIFEST_BYTES if path.endswith((".json", ".md")) else MAX_ARTIFACT_BYTES
        )
        return self._read_url(url, token, maximum=maximum)

    def upload(
        self,
        release: LocalRelease,
        token: str,
        *,
        parent_commit: str,
        commit_message: str,
        commit_description: str,
    ) -> str:
        patterns = [item.path for item in release.artifacts] + ["manifest.json"]
        try:
            result = self._api().upload_folder(
                repo_id=release.dataset_id,
                repo_type="dataset",
                folder_path=release.directory,
                token=token,
                revision="main",
                parent_commit=parent_commit,
                commit_message=commit_message,
                commit_description=commit_description,
                allow_patterns=patterns,
                delete_patterns=[
                    "README.md",
                    "dataset_infos.json",
                    "evaluation-report.json",
                    "manifest.json",
                    "data/**",
                ],
            )
            commit = getattr(result, "oid", "") or getattr(result, "commit_id", "")
        except Exception as exc:
            raise PublicationError("Hugging Face upload failed") from exc
        if not isinstance(commit, str) or not _COMMIT_RE.fullmatch(commit):
            raise PublicationError("upload did not return an immutable Hub commit")
        return commit

    def viewer(
        self,
        endpoint: str,
        params: Mapping[str, str],
        token: str | None,
    ) -> Mapping[str, Any]:
        if endpoint not in {"is-valid", "splits", "parquet", "first-rows"}:
            raise RemoteVerificationError("unsupported Dataset Viewer endpoint")
        url = f"{self._viewer_base_url}/{endpoint}?{urlencode(params)}"
        content = self._read_url(
            url, token, maximum=MAX_VIEWER_RESPONSE_BYTES
        )
        try:
            value = json.loads(content)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ViewerNotReadyError("Dataset Viewer returned invalid JSON") from exc
        if not isinstance(value, Mapping):
            raise ViewerNotReadyError("Dataset Viewer returned an invalid object")
        return value


def _remote_tuple(content: bytes) -> tuple[str, str, str] | None:
    try:
        value = json.loads(content)
        source = value["source"]
        result = (
            value["dataset_id"],
            source["source_revision"],
            value["release_root"],
        )
    except (KeyError, TypeError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not all(isinstance(item, str) for item in result):
        return None
    return result


def find_existing_revision(
    gateway: HubGateway,
    release: LocalRelease,
    token: str | None,
    *,
    head: str,
) -> str | None:
    """Find a prior identical tuple without making a second release commit."""

    revisions = [head]
    revisions.extend(
        revision
        for revision in gateway.revisions(
            release.dataset_id, token, limit=MAX_HISTORY_COMMITS
        )
        if revision != head
    )
    expected = (
        release.dataset_id,
        release.source_revision,
        release.release_root,
    )
    for revision in revisions[:MAX_HISTORY_COMMITS]:
        if not isinstance(revision, str) or not _COMMIT_RE.fullmatch(revision):
            raise RemoteVerificationError(
                "Hub history returned a non-immutable revision"
            )
        try:
            remote = gateway.read_file(
                release.dataset_id, revision, "manifest.json", token
            )
        except RemoteVerificationError:
            continue
        if _remote_tuple(remote) == expected:
            if remote != release.manifest_bytes:
                raise RemoteVerificationError(
                    "existing release tuple has non-identical manifest bytes"
                )
            return revision
    return None


def _feature_names(response: Mapping[str, Any]) -> tuple[str, ...]:
    features = response.get("features")
    if not isinstance(features, list):
        raise ViewerNotReadyError("Dataset Viewer features are unavailable")
    names: list[str] = []
    for feature in features:
        if not isinstance(feature, Mapping) or not isinstance(feature.get("name"), str):
            raise ViewerNotReadyError("Dataset Viewer feature schema is malformed")
        names.append(feature["name"])
    return tuple(names)


def verify_dataset_viewer(
    gateway: HubGateway,
    release: LocalRelease,
    token: str | None,
) -> dict[str, Any]:
    """Verify Viewer validity, configs/splits, shard counts, and row schema."""

    validity = gateway.viewer(
        "is-valid", {"dataset": release.dataset_id}, token
    )
    if validity.get("viewer") is not True:
        raise ViewerNotReadyError("Dataset Viewer does not mark the dataset valid")

    splits_response = gateway.viewer(
        "splits", {"dataset": release.dataset_id}, token
    )
    raw_splits = splits_response.get("splits")
    if not isinstance(raw_splits, list):
        raise ViewerNotReadyError("Dataset Viewer splits are unavailable")
    actual_splits = {
        (item.get("config"), item.get("split"))
        for item in raw_splits
        if isinstance(item, Mapping)
    }
    expected_splits = {(name, "train") for name in release.config_names}
    if actual_splits != expected_splits:
        raise ViewerNotReadyError("Dataset Viewer split inventory mismatch")

    parquet_response = gateway.viewer(
        "parquet", {"dataset": release.dataset_id}, token
    )
    raw_parquet = parquet_response.get("parquet_files")
    if not isinstance(raw_parquet, list):
        raise ViewerNotReadyError("Dataset Viewer Parquet inventory is unavailable")
    viewer_shards: dict[str, list[dict[str, Any]]] = {
        name: [] for name in release.config_names
    }
    for item in raw_parquet:
        if not isinstance(item, Mapping):
            raise ViewerNotReadyError("Dataset Viewer Parquet item is malformed")
        config = item.get("config")
        if (
            config not in viewer_shards
            or item.get("split") != "train"
            or not isinstance(item.get("filename"), str)
            or type(item.get("size")) is not int
            or item["size"] <= 0
        ):
            raise ViewerNotReadyError("Dataset Viewer Parquet binding is invalid")
        viewer_shards[config].append(
            {"filename": item["filename"], "size": item["size"]}
        )
    for config, expected_count in release.config_shard_counts:
        if len(viewer_shards[config]) != expected_count:
            raise ViewerNotReadyError("Dataset Viewer shard count mismatch")

    for config in release.config_names:
        first_rows = gateway.viewer(
            "first-rows",
            {
                "config": config,
                "dataset": release.dataset_id,
                "split": "train",
            },
            token,
        )
        if (
            first_rows.get("dataset") not in {None, release.dataset_id}
            or first_rows.get("config") not in {None, config}
            or first_rows.get("split") not in {None, "train"}
            or _feature_names(first_rows) != EXPECTED_COLUMNS
        ):
            raise ViewerNotReadyError("Dataset Viewer feature binding mismatch")
        rows = first_rows.get("rows")
        if not isinstance(rows, list) or not rows:
            raise ViewerNotReadyError("Dataset Viewer returned no verification row")
        first = rows[0]
        row = first.get("row") if isinstance(first, Mapping) else None
        if not isinstance(row, Mapping) or tuple(row) != EXPECTED_COLUMNS:
            raise ViewerNotReadyError("Dataset Viewer row schema mismatch")
        if row.get("record_type") != config:
            raise ViewerNotReadyError("Dataset Viewer row crossed configurations")
        try:
            canonical_record = json.loads(row["record_json"])
        except (KeyError, TypeError, json.JSONDecodeError) as exc:
            raise ViewerNotReadyError(
                "Dataset Viewer row lacks canonical record JSON"
            ) from exc
        if (
            not isinstance(canonical_record, Mapping)
            or canonical_record.get("record_id") != row.get("record_id")
            or canonical_record.get("record_type") != config
        ):
            raise ViewerNotReadyError("Dataset Viewer row identity mismatch")

    return {
        "columns": list(EXPECTED_COLUMNS),
        "configs": list(release.config_names),
        "shards": {
            key: sorted(value, key=lambda item: item["filename"])
            for key, value in sorted(viewer_shards.items())
        },
        "splits": [
            {"config": config, "split": split}
            for config, split in sorted(actual_splits)
        ],
        "verified": True,
    }


def verify_remote_release(
    gateway: HubGateway,
    release: LocalRelease,
    revision: str,
    token: str | None,
    *,
    viewer_attempts: int = 1,
    viewer_delay_seconds: float = 0.0,
) -> dict[str, Any]:
    """Verify a stable immutable revision and its corresponding Viewer output."""

    if (
        type(viewer_attempts) is not int
        or not 1 <= viewer_attempts <= 60
        or viewer_delay_seconds < 0
        or viewer_delay_seconds > 60
    ):
        raise PublicationError("Dataset Viewer retry bounds are invalid")
    if gateway.head(release.dataset_id, token) != revision:
        raise RemoteVerificationError(
            "target head does not match the release revision"
        )
    remote_manifest = gateway.read_file(
        release.dataset_id, revision, "manifest.json", token
    )
    if (
        remote_manifest != release.manifest_bytes
        or hashlib.sha256(remote_manifest).hexdigest() != release.manifest_sha256
    ):
        raise RemoteVerificationError("remote manifest verification failed")

    remote_artifacts: list[dict[str, Any]] = []
    for artifact in release.artifacts:
        content = gateway.read_file(
            release.dataset_id, revision, artifact.path, token
        )
        if (
            len(content) != artifact.byte_length
            or hashlib.sha256(content).hexdigest() != artifact.sha256
        ):
            raise RemoteVerificationError(
                f"remote artifact verification failed: {artifact.path}"
            )
        remote_artifacts.append(artifact.receipt_dict())

    viewer_result: dict[str, Any] | None = None
    last_error: ViewerNotReadyError | None = None
    for attempt in range(viewer_attempts):
        try:
            viewer_result = verify_dataset_viewer(gateway, release, token)
            break
        except ViewerNotReadyError as exc:
            last_error = exc
            if attempt + 1 < viewer_attempts and viewer_delay_seconds:
                time.sleep(viewer_delay_seconds)
    if viewer_result is None:
        raise last_error or ViewerNotReadyError(
            "Dataset Viewer verification did not complete"
        )
    if gateway.head(release.dataset_id, token) != revision:
        raise RemoteVerificationError(
            "target head changed during remote verification"
        )
    return {
        "artifacts": remote_artifacts,
        "dataset_viewer": viewer_result,
        "manifest_sha256": release.manifest_sha256,
        "remote_artifacts_verified": True,
        "remote_manifest_verified": True,
        "remote_revision_verified": True,
    }


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _receipt(
    release: LocalRelease,
    *,
    principal: str,
    revision: str,
    operation: str,
    verification: Mapping[str, Any],
    proposed_at: str,
) -> dict[str, Any]:
    receipt = {
        "authoritative": False,
        "grants_completion_authority": False,
        "grants_execution_authority": False,
        "hub_commit": revision,
        "idempotency": {
            "key": release.idempotency_key,
            "release_root": release.release_root,
            "source_revision": release.source_revision,
            "target_repo": release.dataset_id,
        },
        "operation": operation,
        "principal": principal,
        "proposed_at": proposed_at,
        "schema_version": PUBLICATION_RECEIPT_VERSION,
        "source_dataset_id": release.source_dataset_id,
        "status": "proposed",
        "verification": dict(verification),
    }
    _safe_public_value(receipt)
    return receipt


def publish_release(
    release_directory: str | os.PathLike[str],
    *,
    target_repo: str = DEFAULT_TARGET_REPO,
    execute: bool = False,
    token_env: str = "HF_TOKEN",
    gateway: HubGateway | None = None,
    viewer_attempts: int = 1,
    viewer_delay_seconds: float = 0.0,
    now: Any = _utc_now,
) -> dict[str, Any]:
    """Plan or execute one idempotent publication attempt."""

    if type(execute) is not bool:
        raise PublicationError("execute must be boolean")
    if not _DATASET_ID_RE.fullmatch(target_repo):
        raise PublicationError("target repo must be owner/name")
    if not _ENV_RE.fullmatch(token_env):
        raise PublicationError("token environment variable name is invalid")
    release = load_local_release(
        release_directory, expected_target=target_repo
    )
    plan = {
        "artifact_count": len(release.artifacts) + 1,
        "dry_run": True,
        "idempotency_key": release.idempotency_key,
        "release_root": release.release_root,
        "schema_version": PUBLICATION_RECEIPT_VERSION,
        "shard_count": len(release.parquet_artifacts),
        "source_dataset_id": release.source_dataset_id,
        "source_revision": release.source_revision,
        "status": "planned",
        "target_repo": release.dataset_id,
    }
    if not execute:
        return plan

    token = os.environ.get(token_env)
    if not isinstance(token, str) or not token:
        raise AuthenticationError(
            f"execute requires a token in environment variable {token_env}"
        )
    client = gateway or HuggingFaceHubGateway()
    principal = client.authenticate(token)
    head = client.head(release.dataset_id, token)
    existing = find_existing_revision(
        client, release, token, head=head
    )
    if existing is not None:
        revision = existing
        operation = "verified_existing"
        if existing != head:
            raise RemoteVerificationError(
                "matching historical release is not the target head"
            )
    else:
        revision = client.upload(
            release,
            token,
            parent_commit=head,
            commit_message=(
                f"Publish CVEfixes Security IR {release.release_root}"
            ),
            commit_description=(
                f"Idempotency-Key: {release.idempotency_key}\n"
                f"Source-Revision: {release.source_revision}"
            ),
        )
        operation = "uploaded"
    verification = verify_remote_release(
        client,
        release,
        revision,
        token,
        viewer_attempts=viewer_attempts,
        viewer_delay_seconds=viewer_delay_seconds,
    )
    return _receipt(
        release,
        principal=principal,
        revision=revision,
        operation=operation,
        verification=verification,
        proposed_at=now(),
    )


def _receipt_release(receipt: Mapping[str, Any]) -> LocalRelease:
    """Build the bounded verification projection carried by a receipt."""

    if set(receipt) != {
        "authoritative",
        "grants_completion_authority",
        "grants_execution_authority",
        "hub_commit",
        "idempotency",
        "operation",
        "principal",
        "proposed_at",
        "schema_version",
        "source_dataset_id",
        "status",
        "verification",
    }:
        raise LocalReleaseError("publication receipt fields are not canonical")
    if (
        receipt.get("schema_version") != PUBLICATION_RECEIPT_VERSION
        or receipt.get("status") != "proposed"
        or receipt.get("authoritative") is not False
        or receipt.get("grants_completion_authority") is not False
        or receipt.get("grants_execution_authority") is not False
        or receipt.get("operation") not in {"uploaded", "verified_existing"}
    ):
        raise LocalReleaseError("publication receipt authority is invalid")
    if (
        not isinstance(receipt.get("principal"), str)
        or not receipt["principal"].strip()
        or not isinstance(receipt.get("proposed_at"), str)
        or not receipt["proposed_at"].endswith("Z")
    ):
        raise LocalReleaseError("publication receipt provenance is invalid")
    _safe_public_value(receipt)
    binding = _object(receipt.get("idempotency"), "receipt idempotency")
    verification = _object(receipt.get("verification"), "receipt verification")
    raw_artifacts = verification.get("artifacts")
    if not isinstance(raw_artifacts, list) or not raw_artifacts:
        raise LocalReleaseError("receipt artifact inventory is invalid")
    artifacts: list[ArtifactDescriptor] = []
    for raw in raw_artifacts:
        item = _object(raw, "receipt artifact")
        expected = {
            "byte_length",
            "config_name",
            "content_id",
            "path",
            "row_count",
            "sha256",
        }
        if set(item) != expected:
            raise LocalReleaseError("receipt artifact fields are invalid")
        descriptor_value = {
            "byte_length": item["byte_length"],
            "content_id": item["content_id"],
            "media_type": (
                "application/vnd.apache.parquet"
                if item["config_name"]
                else (
                    "text/markdown; charset=utf-8"
                    if item["path"] == "README.md"
                    else "application/json"
                )
            ),
            "path": item["path"],
            "sha256": item["sha256"],
        }
        if item["config_name"]:
            descriptor_value["config_name"] = item["config_name"]
            descriptor_value["row_count"] = item["row_count"]
        elif item["row_count"] != 0:
            raise LocalReleaseError("receipt non-shard row count is invalid")
        artifacts.append(ArtifactDescriptor.from_dict(descriptor_value))
    if (
        tuple(item.path for item in artifacts)
        != tuple(sorted(item.path for item in artifacts))
        or len({item.path for item in artifacts}) != len(artifacts)
    ):
        raise LocalReleaseError("receipt artifact inventory is not canonical")
    viewer = _object(verification.get("dataset_viewer"), "receipt Dataset Viewer")
    configs = viewer.get("configs")
    if (
        verification.get("remote_artifacts_verified") is not True
        or verification.get("remote_manifest_verified") is not True
        or verification.get("remote_revision_verified") is not True
        or viewer.get("verified") is not True
        or not isinstance(configs, list)
        or not configs
        or configs != sorted(set(configs))
        or any(
            not isinstance(config, str) or not _CONFIG_RE.fullmatch(config)
            for config in configs
        )
        or viewer.get("columns") != list(EXPECTED_COLUMNS)
    ):
        raise LocalReleaseError("receipt Dataset Viewer proof is invalid")
    shard_counts = tuple(
        sorted(
            (
                config,
                sum(1 for item in artifacts if item.config_name == config),
            )
            for config in configs
        )
    )
    dataset_id = binding.get("target_repo")
    source_revision = binding.get("source_revision")
    release_root = binding.get("release_root")
    source_dataset_id = receipt.get("source_dataset_id")
    manifest_sha = verification.get("manifest_sha256")
    if (
        not isinstance(dataset_id, str)
        or not _DATASET_ID_RE.fullmatch(dataset_id)
        or not isinstance(source_revision, str)
        or not source_revision
        or not isinstance(source_dataset_id, str)
        or not source_dataset_id
        or not isinstance(release_root, str)
        or not _CID_RE.fullmatch(release_root)
        or not isinstance(manifest_sha, str)
        or not _SHA256_RE.fullmatch(manifest_sha)
    ):
        raise LocalReleaseError("receipt release binding is invalid")
    expected_key = "cvefixes-publication:" + hashlib.sha256(
        _canonical_json(
            {
                "release_root": release_root,
                "source_revision": source_revision,
                "target_repo": dataset_id,
            }
        )
    ).hexdigest()
    if binding.get("key") != expected_key:
        raise LocalReleaseError("receipt idempotency key is invalid")
    return LocalRelease(
        directory=Path(),
        dataset_id=dataset_id,
        source_dataset_id=source_dataset_id,
        source_revision=source_revision,
        release_root=release_root,
        manifest_bytes=b"",
        manifest_sha256=manifest_sha,
        artifacts=tuple(artifacts),
        config_names=tuple(configs),
        config_shard_counts=shard_counts,
    )


def verify_receipt(
    receipt_path: str | os.PathLike[str],
    *,
    gateway: HubGateway | None = None,
    token_env: str = "HF_TOKEN",
) -> dict[str, Any]:
    """Read-only verification of a proposed publication receipt."""

    if not _ENV_RE.fullmatch(token_env):
        raise PublicationError("token environment variable name is invalid")
    content = _bounded_bytes(
        Path(receipt_path),
        maximum=MAX_MANIFEST_BYTES,
        label="publication receipt",
    )
    receipt = _json_bytes(content, "publication receipt")
    release = _receipt_release(receipt)
    revision = receipt.get("hub_commit")
    if not isinstance(revision, str) or not _COMMIT_RE.fullmatch(revision):
        raise LocalReleaseError("receipt Hub commit is invalid")
    token = os.environ.get(token_env) or None
    client = gateway or HuggingFaceHubGateway()
    if client.head(release.dataset_id, token) != revision:
        raise RemoteVerificationError("receipt commit is not the target head")
    manifest = client.read_file(
        release.dataset_id, revision, "manifest.json", token
    )
    if hashlib.sha256(manifest).hexdigest() != release.manifest_sha256:
        raise RemoteVerificationError("receipt remote manifest digest mismatch")
    if _remote_tuple(manifest) != (
        release.dataset_id,
        release.source_revision,
        release.release_root,
    ):
        raise RemoteVerificationError("receipt remote manifest binding mismatch")
    for artifact in release.artifacts:
        remote = client.read_file(
            release.dataset_id, revision, artifact.path, token
        )
        if (
            len(remote) != artifact.byte_length
            or hashlib.sha256(remote).hexdigest() != artifact.sha256
        ):
            raise RemoteVerificationError(
                f"receipt remote artifact mismatch: {artifact.path}"
            )
    viewer = verify_dataset_viewer(client, release, token)
    return {
        "hub_commit": revision,
        "release_root": release.release_root,
        "schema_version": PUBLICATION_RECEIPT_VERSION,
        "status": "verified",
        "target_repo": release.dataset_id,
        "verification": {
            "dataset_viewer": viewer,
            "remote_artifacts_verified": True,
            "remote_manifest_verified": True,
            "remote_revision_verified": True,
        },
    }


def write_receipt(
    receipt: Mapping[str, Any], destination: str | os.PathLike[str]
) -> None:
    """Atomically create a receipt without overwriting operator evidence."""

    path = Path(destination)
    if path.exists() or path.is_symlink():
        raise PublicationError("receipt destination already exists")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    if temporary.exists() or temporary.is_symlink():
        raise PublicationError("receipt temporary destination already exists")
    content = _canonical_json(receipt) + b"\n"
    try:
        with temporary.open("xb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(path)
    except OSError as exc:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        raise PublicationError("could not write publication receipt") from exc


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "release_directory",
        nargs="?",
        help="Validated staging directory; required unless --verify-receipt is used.",
    )
    parser.add_argument("--target-repo", default=DEFAULT_TARGET_REPO)
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Authenticate and publish; omission is always a credential-free dry run.",
    )
    parser.add_argument(
        "--token-env",
        default="HF_TOKEN",
        help="Name of the environment variable holding the token (never the token itself).",
    )
    parser.add_argument(
        "--receipt-out",
        type=Path,
        help="Atomically create the proposed receipt after complete verification.",
    )
    parser.add_argument(
        "--verify-receipt",
        type=Path,
        help="Read-only remote verification of an existing proposed receipt.",
    )
    parser.add_argument("--viewer-attempts", type=int, default=12)
    parser.add_argument("--viewer-delay-seconds", type=float, default=5.0)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.verify_receipt is not None:
            if args.release_directory or args.execute or args.receipt_out:
                raise PublicationError(
                    "--verify-receipt cannot be combined with publication arguments"
                )
            result = verify_receipt(
                args.verify_receipt, token_env=args.token_env
            )
        else:
            if not args.release_directory:
                raise PublicationError("release_directory is required")
            result = publish_release(
                args.release_directory,
                target_repo=args.target_repo,
                execute=args.execute,
                token_env=args.token_env,
                viewer_attempts=args.viewer_attempts,
                viewer_delay_seconds=args.viewer_delay_seconds,
            )
            if args.receipt_out is not None:
                if not args.execute:
                    raise PublicationError(
                        "--receipt-out requires --execute and complete verification"
                    )
                write_receipt(result, args.receipt_out)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except PublicationError as exc:
        print(f"publication failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
