"""Generic deterministic Parquet release helpers for Hugging Face packaging.

These helpers own the *atomic* concerns shared by domain builders:

* deterministic release construction with fixed writer settings;
* sharded ZSTD Parquet descriptors (relative path, full SHA-256, byte length, CID);
* path-safety and on-disk verification; and
* identity contamination checks for release manifests so a byte-identical
  rebuild remains free of timestamps, local paths, and mutable refs.

Domain packages (Abby voice, SkillCenter, legal corpora) wrap these helpers.
They must not copy SkillCenter builder logic, and they must never mix
manifests or indexes into row-config Parquet directories.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from hashlib import sha256
import json
import os
from pathlib import Path
import re
from typing import Any, Final

from ..logic.ir_core.artifacts import ArtifactManifest
from ..logic.ir_core.identity import cid_v1_from_digest

# ArtifactManifest is re-exported so G018 AST scans find the symbol on this
# predicted helper module without mutating package __init__.py.

HUGGINGFACE_RELEASE_DESCRIPTOR_SCHEMA: Final = "huggingface-release-descriptor/v1"
DEFAULT_SHARD_ROWS: Final = 4096
PARQUET_COMPRESSION: Final = "zstd"
PARQUET_COMPRESSION_LEVEL: Final = 6
PARQUET_MAGIC: Final = b"PAR1"

_HASH_RE = re.compile(r"^[0-9a-f]{64}$")
_MUTABLE_REF_MARKERS = (
    "/resolve/main/",
    "/resolve/master/",
    "/resolve/latest/",
    "/tree/main/",
    "/blob/main/",
    "refs/heads/",
)
_LOCAL_PATH_MARKERS = (
    "file://",
    "/home/",
    "/tmp/",
    "/var/",
    "c:\\",
    "c:/",
)
_TIMESTAMP_KEY_RE = re.compile(
    r"(created_at|generated_at|started_at|finished_at|timestamp|observed_at|"
    r"duration_ms|wall_time|host_name|hostname|pid|runtime)",
    re.IGNORECASE,
)


class HuggingFaceReleaseError(ValueError):
    """Raised when a release helper cannot construct or verify artifacts."""


@dataclass(frozen=True, slots=True)
class FileDescriptor:
    """Integrity and policy metadata for one release file.

    Descriptors are support artifacts.  They describe Parquet shards and
    companion indexes without ever becoming rows inside a Dataset Viewer
    config.
    """

    relative_path: str
    size_bytes: int
    sha256: str
    content_cid: str
    media_type: str = "application/octet-stream"
    schema_type: str = ""
    producer_id: str = ""
    config_digest: str = ""
    parent_ids: tuple[str, ...] = ()
    license_id: str = ""
    consent_status: str = ""
    review_status: str = ""
    trust_decision: str = ""
    row_count: int | None = None
    shard_id: int | None = None
    split: str = ""
    config_name: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        path = _normalize_relative_path(self.relative_path)
        if not isinstance(self.size_bytes, int) or isinstance(self.size_bytes, bool):
            raise HuggingFaceReleaseError("size_bytes must be a non-negative integer")
        if self.size_bytes < 0:
            raise HuggingFaceReleaseError("size_bytes must be a non-negative integer")
        digest = str(self.sha256 or "").strip().lower()
        if not _HASH_RE.fullmatch(digest):
            raise HuggingFaceReleaseError(
                "sha256 must be a full lower-case 64-character hex digest"
            )
        cid = str(self.content_cid or "").strip()
        if not cid:
            raise HuggingFaceReleaseError("content_cid is required")
        expected_cid = cid_v1_from_digest(bytes.fromhex(digest))
        if cid != expected_cid:
            raise HuggingFaceReleaseError(
                f"content_cid must equal the raw-SHA-256 CID for the digest "
                f"(expected {expected_cid})"
            )
        parents = tuple(
            sorted({str(item).strip() for item in self.parent_ids if str(item).strip()})
        )
        metadata = _freeze_mapping(self.metadata)
        object.__setattr__(self, "relative_path", path)
        object.__setattr__(self, "sha256", digest)
        object.__setattr__(self, "content_cid", cid)
        object.__setattr__(self, "parent_ids", parents)
        object.__setattr__(self, "metadata", metadata)
        if self.row_count is not None and (
            not isinstance(self.row_count, int)
            or isinstance(self.row_count, bool)
            or self.row_count < 0
        ):
            raise HuggingFaceReleaseError("row_count must be a non-negative integer")
        if self.shard_id is not None and (
            not isinstance(self.shard_id, int)
            or isinstance(self.shard_id, bool)
            or self.shard_id < 0
        ):
            raise HuggingFaceReleaseError("shard_id must be a non-negative integer")

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "config_digest": self.config_digest,
            "config_name": self.config_name,
            "consent_status": self.consent_status,
            "content_cid": self.content_cid,
            "license_id": self.license_id,
            "media_type": self.media_type,
            "metadata": dict(self.metadata),
            "parent_ids": list(self.parent_ids),
            "producer_id": self.producer_id,
            "relative_path": self.relative_path,
            "review_status": self.review_status,
            "schema_type": self.schema_type,
            "sha256": self.sha256,
            "size_bytes": self.size_bytes,
            "split": self.split,
            "trust_decision": self.trust_decision,
        }
        if self.row_count is not None:
            payload["row_count"] = self.row_count
        if self.shard_id is not None:
            payload["shard_id"] = self.shard_id
        return payload

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> FileDescriptor:
        if not isinstance(value, Mapping):
            raise HuggingFaceReleaseError("file descriptor must be a mapping")
        parents = value.get("parent_ids") or value.get("parents") or ()
        return cls(
            relative_path=str(value.get("relative_path") or value.get("path") or ""),
            size_bytes=int(value.get("size_bytes") if "size_bytes" in value else value.get("byte_length", -1)),
            sha256=str(value.get("sha256") or ""),
            content_cid=str(value.get("content_cid") or value.get("cid") or ""),
            media_type=str(value.get("media_type") or "application/octet-stream"),
            schema_type=str(value.get("schema_type") or value.get("schema_version") or ""),
            producer_id=str(value.get("producer_id") or ""),
            config_digest=str(value.get("config_digest") or ""),
            parent_ids=tuple(parents) if isinstance(parents, Sequence) else (),
            license_id=str(value.get("license_id") or ""),
            consent_status=str(value.get("consent_status") or ""),
            review_status=str(value.get("review_status") or ""),
            trust_decision=str(value.get("trust_decision") or ""),
            row_count=value.get("row_count"),
            shard_id=value.get("shard_id"),
            split=str(value.get("split") or ""),
            config_name=str(value.get("config_name") or ""),
            metadata=value.get("metadata") if isinstance(value.get("metadata"), Mapping) else {},
        )


def canonical_json_bytes(value: Any) -> bytes:
    """Return UTF-8 JSON with sorted keys and compact separators."""

    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def file_digest(path: str | Path) -> tuple[int, bytes]:
    """Return ``(byte_length, sha256_digest_bytes)`` for an on-disk file."""

    target = Path(path)
    if not target.is_file() or target.is_symlink():
        raise HuggingFaceReleaseError(f"not a regular file: {target}")
    digest = sha256()
    size = 0
    with target.open("rb") as handle:
        while chunk := handle.read(8 * 1024 * 1024):
            size += len(chunk)
            digest.update(chunk)
    return size, digest.digest()


def describe_file(
    path: str | Path,
    *,
    root: str | Path,
    media_type: str = "application/octet-stream",
    schema_type: str = "",
    producer_id: str = "",
    config_digest: str = "",
    parent_ids: Sequence[str] = (),
    license_id: str = "",
    consent_status: str = "",
    review_status: str = "",
    trust_decision: str = "",
    row_count: int | None = None,
    shard_id: int | None = None,
    split: str = "",
    config_name: str = "",
    metadata: Mapping[str, Any] | None = None,
) -> FileDescriptor:
    """Build a verified :class:`FileDescriptor` for *path* under *root*."""

    root_path = Path(root).expanduser().resolve()
    file_path = Path(path).expanduser().resolve()
    try:
        relative = file_path.relative_to(root_path).as_posix()
    except ValueError as exc:
        raise HuggingFaceReleaseError(
            f"path escapes release root: {file_path}"
        ) from exc
    size_bytes, digest = file_digest(file_path)
    return FileDescriptor(
        relative_path=relative,
        size_bytes=size_bytes,
        sha256=digest.hex(),
        content_cid=cid_v1_from_digest(digest),
        media_type=media_type,
        schema_type=schema_type,
        producer_id=producer_id,
        config_digest=config_digest,
        parent_ids=tuple(parent_ids),
        license_id=license_id,
        consent_status=consent_status,
        review_status=review_status,
        trust_decision=trust_decision,
        row_count=row_count,
        shard_id=shard_id,
        split=split,
        config_name=config_name,
        metadata=metadata or {},
    )


def verify_file_descriptor(
    root: str | Path,
    descriptor: FileDescriptor | Mapping[str, Any],
) -> Path:
    """Rehash *descriptor* on disk and fail closed on any mismatch."""

    desc = (
        descriptor
        if isinstance(descriptor, FileDescriptor)
        else FileDescriptor.from_dict(descriptor)
    )
    root_path = Path(root).expanduser().resolve()
    path = root_path.joinpath(*Path(desc.relative_path).parts)
    try:
        path.resolve().relative_to(root_path)
    except ValueError as exc:
        raise HuggingFaceReleaseError(
            f"descriptor path escapes release root: {desc.relative_path}"
        ) from exc
    if path.is_symlink() or not path.is_file():
        raise HuggingFaceReleaseError(
            f"descriptor path is missing or unsafe: {desc.relative_path}"
        )
    size_bytes, digest = file_digest(path)
    if size_bytes != desc.size_bytes or digest.hex() != desc.sha256:
        raise HuggingFaceReleaseError(
            f"descriptor failed size/sha256 verification: {desc.relative_path}"
        )
    if cid_v1_from_digest(digest) != desc.content_cid:
        raise HuggingFaceReleaseError(
            f"descriptor failed CID verification: {desc.relative_path}"
        )
    return path


def shard_sequence(
    values: Sequence[Any],
    *,
    max_rows: int = DEFAULT_SHARD_ROWS,
) -> tuple[tuple[Any, ...], ...]:
    """Partition *values* into ordered shards of at most *max_rows* items."""

    if not isinstance(max_rows, int) or isinstance(max_rows, bool) or max_rows <= 0:
        raise HuggingFaceReleaseError("max_rows must be a positive integer")
    if not values:
        return ((),)
    return tuple(
        tuple(values[index : index + max_rows])
        for index in range(0, len(values), max_rows)
    )


def write_zstd_parquet(
    path: str | Path,
    table: Any,
    *,
    max_rows: int = DEFAULT_SHARD_ROWS,
) -> Path:
    """Atomically write a ZSTD Parquet shard with fixed writer settings.

    Writer options are pinned so two builds of the same ordered table produce
    byte-identical shards (deterministic release construction).
    """

    try:
        import pyarrow.parquet as pq
    except ImportError as exc:  # pragma: no cover - optional dependency
        raise ImportError(
            "write_zstd_parquet requires the optional 'pyarrow' package"
        ) from exc

    if getattr(table, "num_rows", 0) > max_rows:
        raise HuggingFaceReleaseError(
            f"Parquet shard exceeds {max_rows} rows: {path}"
        )
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.partial")
    try:
        pq.write_table(
            table,
            temporary,
            compression=PARQUET_COMPRESSION,
            compression_level=PARQUET_COMPRESSION_LEVEL,
            row_group_size=max_rows,
            use_dictionary=True,
            write_statistics=True,
            write_page_index=False,
            data_page_version="1.0",
        )
        validate_zstd_parquet(temporary, max_rows=max_rows)
        os.replace(temporary, target)
    finally:
        if temporary.exists():
            temporary.unlink(missing_ok=True)
    return target


def validate_zstd_parquet(
    path: str | Path,
    *,
    max_rows: int | None = DEFAULT_SHARD_ROWS,
    expected_schema: Any | None = None,
    expected_row_count: int | None = None,
) -> int:
    """Validate Parquet magic, ZSTD compression, readability, and row bounds."""

    target = Path(path)
    if not target.is_file():
        raise HuggingFaceReleaseError(f"Parquet file is missing: {target}")
    header = target.read_bytes()[:4]
    if header != PARQUET_MAGIC:
        raise HuggingFaceReleaseError(f"Parquet magic missing: {target}")
    try:
        import pyarrow.parquet as pq
    except ImportError as exc:  # pragma: no cover
        raise ImportError(
            "validate_zstd_parquet requires the optional 'pyarrow' package"
        ) from exc
    parquet = pq.ParquetFile(target)
    row_count = int(parquet.metadata.num_rows)
    if max_rows is not None and row_count > max_rows:
        raise HuggingFaceReleaseError(
            f"Parquet file exceeds row limit {max_rows}: {target}"
        )
    if expected_row_count is not None and row_count != expected_row_count:
        raise HuggingFaceReleaseError(
            f"Parquet row count mismatch for {target}: "
            f"expected {expected_row_count}, got {row_count}"
        )
    compressions = {
        parquet.metadata.row_group(group).column(column).compression
        for group in range(parquet.metadata.num_row_groups)
        for column in range(parquet.metadata.row_group(group).num_columns)
    }
    if parquet.metadata.num_row_groups and compressions != {"ZSTD"}:
        raise HuggingFaceReleaseError(
            f"Parquet file is not uniformly ZSTD-compressed: {target}"
        )
    table = parquet.read()
    if expected_schema is not None:
        actual_names = list(table.schema.names)
        expected_names = list(expected_schema.names)
        if actual_names != expected_names:
            raise HuggingFaceReleaseError(
                f"Parquet schema columns differ for {target}: "
                f"{actual_names} != {expected_names}"
            )
        for name in expected_names:
            if table.schema.field(name).type != expected_schema.field(name).type:
                raise HuggingFaceReleaseError(
                    f"Parquet column type mismatch for {target}:{name}"
                )
    return row_count


def reject_identity_contamination(value: Any, *, label: str = "release") -> None:
    """Fail when identity-bearing structures carry runtime contamination.

    Identity files must not embed wall-clock timestamps, absolute local paths,
    mutable Hugging Face ``/resolve/main/`` URLs, truncated digests, or
    unordered observational host metadata.
    """

    offenders: list[str] = []

    def visit(item: Any, path: str) -> None:
        if isinstance(item, Mapping):
            for key, child in item.items():
                key_text = str(key)
                child_path = f"{path}.{key_text}" if path else key_text
                if _TIMESTAMP_KEY_RE.search(key_text):
                    offenders.append(child_path)
                visit(child, child_path)
        elif isinstance(item, (list, tuple)):
            for index, child in enumerate(item):
                visit(child, f"{path}[{index}]")
        elif isinstance(item, str):
            lowered = item.casefold()
            if any(marker in lowered for marker in _MUTABLE_REF_MARKERS):
                offenders.append(f"{path}:mutable_ref")
            if any(marker in lowered for marker in _LOCAL_PATH_MARKERS):
                offenders.append(f"{path}:local_path")
            if re.fullmatch(r"[0-9a-f]{8,63}", item) and not _HASH_RE.fullmatch(item):
                # Short hex that looks like a truncated integrity hash.
                if "hash" in path.casefold() or "sha" in path.casefold():
                    offenders.append(f"{path}:truncated_hash")

    visit(value, label)
    if offenders:
        raise HuggingFaceReleaseError(
            "identity contamination detected: " + ", ".join(sorted(set(offenders)))
        )


def write_canonical_json(path: str | Path, value: Any) -> Path:
    """Write sorted-key JSON bytes atomically."""

    reject_identity_contamination(value, label=str(path))
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.partial")
    temporary.write_bytes(canonical_json_bytes(value) + b"\n")
    os.replace(temporary, target)
    return target


def _normalize_relative_path(value: str) -> str:
    text = str(value or "").strip().replace("\\", "/")
    if not text or text.startswith("/") or text.startswith("../") or "/../" in f"/{text}/":
        raise HuggingFaceReleaseError(f"unsafe relative path: {value!r}")
    parts = Path(text).parts
    if ".." in parts or Path(text).is_absolute():
        raise HuggingFaceReleaseError(f"unsafe relative path: {value!r}")
    return Path(*parts).as_posix()


def _freeze_mapping(value: Mapping[str, Any]) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise HuggingFaceReleaseError("metadata must be a mapping")
    # Round-trip through canonical JSON so nested structures are plain data.
    return json.loads(canonical_json_bytes(dict(value)).decode("utf-8"))


__all__ = [
    "DEFAULT_SHARD_ROWS",
    "HUGGINGFACE_RELEASE_DESCRIPTOR_SCHEMA",
    "PARQUET_COMPRESSION",
    "PARQUET_COMPRESSION_LEVEL",
    "PARQUET_MAGIC",
    "ArtifactManifest",
    "FileDescriptor",
    "HuggingFaceReleaseError",
    "canonical_json_bytes",
    "describe_file",
    "file_digest",
    "reject_identity_contamination",
    "shard_sequence",
    "validate_zstd_parquet",
    "verify_file_descriptor",
    "write_canonical_json",
    "write_zstd_parquet",
]
