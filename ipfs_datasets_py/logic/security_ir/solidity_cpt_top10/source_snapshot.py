"""Immutable, bounded intake contracts for the Solidity CPT Top-10 source.

The Hugging Face repository, Parquet file, and every decoded row are untrusted
input.  This module performs no network access and never compiles, executes, or
interprets Solidity text.  A caller must first verify the exact reviewed
snapshot before adapting rows.

Raw Solidity bodies are represented by separate content-addressed artifacts.
The normalized row record contains only the body's digest and CID.  Persisted
loaders rehash all supplied identities and reject missing, stale, or
caller-selected values.
"""

from __future__ import annotations

import hashlib
import os
import stat
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Any, Final

from ...ir_core.canonical import canonical_json_bytes
from ...ir_core.identity import CanonicalIdentity, canonical_identity, cid_v1
from .release_policy import (
    SOLIDITY_CPT_COLUMN_TYPES,
    SOLIDITY_CPT_COLUMNS,
    SOLIDITY_CPT_CONFIG_NAME,
    SOLIDITY_CPT_DATASET_ID,
    SOLIDITY_CPT_REVISION,
    SOLIDITY_CPT_ROW_COUNT,
    SOLIDITY_CPT_SHARD_PATH,
    SOLIDITY_CPT_SHARD_SHA256,
    SOLIDITY_CPT_SHARD_SIZE_BYTES,
    SOLIDITY_CPT_SPLIT,
)

SOURCE_SNAPSHOT_SCHEMA_VERSION: Final = "solidity-cpt-source-snapshot/v1"
SOURCE_BODY_SCHEMA_VERSION: Final = "solidity-cpt-source-body/v1"
SOURCE_ROW_SCHEMA_VERSION: Final = "solidity-cpt-source-row/v1"
ROW_ADAPTER_SCHEMA_VERSION: Final = "solidity-cpt-row-adapter/v1"
QUARANTINE_SCHEMA_VERSION: Final = "solidity-cpt-quarantine/v1"

_SHA256_RE = frozenset("0123456789abcdef")
_CID_ALPHABET = frozenset("abcdefghijklmnopqrstuvwxyz234567")
_AUTHORITY_FIELD_NAMES: Final = frozenset(
    {
        "allow",
        "authoritative",
        "authority",
        "deployed_bytecode_equal",
        "execution_authority",
        "grants_authority",
        "proof_authority",
        "safe",
        "transaction_authority",
        "verified_source",
    }
)


class SourceSnapshotError(ValueError):
    """Base error for source-pin, persisted-artifact, or row failures."""


class SourceSnapshotVerificationError(SourceSnapshotError):
    """Raised when observed source facts differ from the immutable pin."""


class SolidityCPTRowError(SourceSnapshotError):
    """Raised when an untrusted row is malformed."""


class SolidityCPTRowOversizeError(SolidityCPTRowError):
    """Raised when a row exceeds an explicit resource bound."""


class SolidityCPTRowPoisonedError(SolidityCPTRowError):
    """Raised for unsafe encodings, paths, or control characters."""


class SolidityCPTRowDriftError(SolidityCPTRowError):
    """Raised for unknown/missing fields or inconsistent source metadata."""


class SolidityCPTUnknownAuthorityError(SolidityCPTRowError):
    """Raised when input attempts to smuggle authority into source data."""


def _is_sha256(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(character in _SHA256_RE for character in value)


def _is_cid(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 59
        and value.startswith("b")
        and all(character in _CID_ALPHABET for character in value)
    )


def _strict_mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise SourceSnapshotVerificationError(f"{label} must be a mapping")
    return value


def _exact_keys(
    value: Mapping[str, Any],
    expected: frozenset[str],
    label: str,
    error_type: type[ValueError] = SourceSnapshotVerificationError,
) -> None:
    actual = set(value)
    if actual == set(expected):
        return
    missing = sorted(set(expected) - actual)
    unexpected = sorted(actual - set(expected))
    details: list[str] = []
    if missing:
        details.append("missing=" + ",".join(missing))
    if unexpected:
        details.append("unexpected=" + ",".join(unexpected))
    raise error_type(f"{label} schema drift: {'; '.join(details)}")


def _parse_columns(value: Any) -> tuple[tuple[str, str], ...]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Sequence):
        raise SourceSnapshotVerificationError("columns must be an ordered sequence of typed fields")
    columns: list[tuple[str, str]] = []
    for index, item in enumerate(value):
        if isinstance(item, Mapping):
            _exact_keys(
                item,
                frozenset({"name", "type"}),
                f"columns[{index}]",
            )
            name, field_type = item["name"], item["type"]
        elif isinstance(item, Sequence) and not isinstance(item, (str, bytes, bytearray)) and len(item) == 2:
            name, field_type = item
        else:
            raise SourceSnapshotVerificationError(f"columns[{index}] must contain exactly name and type")
        if not isinstance(name, str) or not isinstance(field_type, str):
            raise SourceSnapshotVerificationError("column names and types must be strings")
        columns.append((name, field_type))
    return tuple(columns)


def _columns_wire(
    columns: tuple[tuple[str, str], ...],
) -> list[dict[str, str]]:
    return [{"name": name, "type": field_type} for name, field_type in columns]


@dataclass(frozen=True, slots=True)
class SourceShard:
    """Identity and physical bounds for the single immutable Parquet shard."""

    path: str
    sha256: str
    size_bytes: int
    row_count: int

    def __post_init__(self) -> None:
        if (
            not isinstance(self.path, str)
            or not self.path
            or self.path != PurePosixPath(self.path).as_posix()
            or PurePosixPath(self.path).is_absolute()
            or any(part in {"", ".", ".."} for part in PurePosixPath(self.path).parts)
            or "\\" in self.path
            or not self.path.endswith(".parquet")
        ):
            raise SourceSnapshotError("shard path must be safe relative Parquet path")
        if not _is_sha256(self.sha256):
            raise SourceSnapshotError("shard sha256 must be lowercase SHA-256")
        if type(self.size_bytes) is not int or self.size_bytes <= 0:
            raise SourceSnapshotError("shard size_bytes must be a positive integer")
        if type(self.row_count) is not int or self.row_count <= 0:
            raise SourceSnapshotError("shard row_count must be a positive integer")

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "row_count": self.row_count,
            "sha256": self.sha256,
            "size_bytes": self.size_bytes,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> SourceShard:
        value = _strict_mapping(value, "source shard")
        _exact_keys(
            value,
            frozenset({"path", "row_count", "sha256", "size_bytes"}),
            "source shard",
        )
        return cls(
            path=value["path"],
            sha256=value["sha256"],
            size_bytes=value["size_bytes"],
            row_count=value["row_count"],
        )


PINNED_SOURCE_SHARD: Final = SourceShard(
    path=SOLIDITY_CPT_SHARD_PATH,
    sha256=SOLIDITY_CPT_SHARD_SHA256,
    size_bytes=SOLIDITY_CPT_SHARD_SIZE_BYTES,
    row_count=SOLIDITY_CPT_ROW_COUNT,
)


@dataclass(frozen=True, slots=True)
class SourceSnapshotObservation:
    """Untrusted Hub/Parquet facts supplied by an offline observer."""

    dataset_id: str
    revision: str
    config_name: str
    split: str
    shard: SourceShard
    columns: tuple[tuple[str, str], ...]

    def __post_init__(self) -> None:
        for name in ("dataset_id", "revision", "config_name", "split"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value:
                raise SourceSnapshotVerificationError(f"{name} must not be empty")
        if not isinstance(self.shard, SourceShard):
            raise SourceSnapshotVerificationError("shard must be SourceShard")
        if not isinstance(self.columns, tuple):
            raise SourceSnapshotVerificationError("columns must be an ordered tuple")

    def to_dict(self) -> dict[str, Any]:
        return {
            "columns": _columns_wire(self.columns),
            "config_name": self.config_name,
            "dataset_id": self.dataset_id,
            "revision": self.revision,
            "shard": self.shard.to_dict(),
            "split": self.split,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> SourceSnapshotObservation:
        value = _strict_mapping(value, "source observation")
        _exact_keys(
            value,
            frozenset(
                {
                    "columns",
                    "config_name",
                    "dataset_id",
                    "revision",
                    "shard",
                    "split",
                }
            ),
            "source observation",
        )
        return cls(
            dataset_id=value["dataset_id"],
            revision=value["revision"],
            config_name=value["config_name"],
            split=value["split"],
            shard=SourceShard.from_dict(_strict_mapping(value["shard"], "shard")),
            columns=_parse_columns(value["columns"]),
        )


@dataclass(frozen=True, slots=True)
class SolidityCPTSourceSnapshot:
    """The reviewed immutable source profile and its canonical identity."""

    dataset_id: str = SOLIDITY_CPT_DATASET_ID
    revision: str = SOLIDITY_CPT_REVISION
    config_name: str = SOLIDITY_CPT_CONFIG_NAME
    split: str = SOLIDITY_CPT_SPLIT
    shard: SourceShard = PINNED_SOURCE_SHARD
    columns: tuple[tuple[str, str], ...] = SOLIDITY_CPT_COLUMN_TYPES
    snapshot_id: str = ""
    schema_version: str = SOURCE_SNAPSHOT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        expected = (
            ("dataset_id", self.dataset_id, SOLIDITY_CPT_DATASET_ID),
            ("revision", self.revision, SOLIDITY_CPT_REVISION),
            ("config_name", self.config_name, SOLIDITY_CPT_CONFIG_NAME),
            ("split", self.split, SOLIDITY_CPT_SPLIT),
            ("shard", self.shard, PINNED_SOURCE_SHARD),
            ("columns", self.columns, SOLIDITY_CPT_COLUMN_TYPES),
            ("schema_version", self.schema_version, SOURCE_SNAPSHOT_SCHEMA_VERSION),
        )
        for name, observed, pinned in expected:
            if observed != pinned:
                raise SourceSnapshotVerificationError(f"{name} differs from reviewed source pin")
        computed = self.identity.cid
        if self.snapshot_id and self.snapshot_id != computed:
            raise SourceSnapshotVerificationError("snapshot_id does not match rehashed source profile")
        object.__setattr__(self, "snapshot_id", computed)

    def deterministic_dict(self) -> dict[str, Any]:
        return {
            "columns": _columns_wire(self.columns),
            "config_name": self.config_name,
            "dataset_id": self.dataset_id,
            "revision": self.revision,
            "schema_version": self.schema_version,
            "shard": self.shard.to_dict(),
            "split": self.split,
        }

    def observation_dict(self) -> dict[str, Any]:
        return SourceSnapshotObservation(
            dataset_id=self.dataset_id,
            revision=self.revision,
            config_name=self.config_name,
            split=self.split,
            shard=self.shard,
            columns=self.columns,
        ).to_dict()

    def to_dict(self) -> dict[str, Any]:
        return {"snapshot_id": self.snapshot_id, **self.deterministic_dict()}

    @property
    def identity(self) -> CanonicalIdentity:
        return canonical_identity(
            self.deterministic_dict(),
            domain="solidity-cpt/source-snapshot",
            schema_version=self.schema_version,
        )

    @property
    def cid(self) -> str:
        return self.snapshot_id

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> SolidityCPTSourceSnapshot:
        """Strict persisted load; an identity assertion is mandatory."""

        value = _strict_mapping(value, "source snapshot")
        _exact_keys(
            value,
            frozenset(
                {
                    "columns",
                    "config_name",
                    "dataset_id",
                    "revision",
                    "schema_version",
                    "shard",
                    "snapshot_id",
                    "split",
                }
            ),
            "source snapshot",
        )
        if not value["snapshot_id"]:
            raise SourceSnapshotVerificationError("persisted source snapshot requires snapshot_id")
        return cls(
            dataset_id=value["dataset_id"],
            revision=value["revision"],
            config_name=value["config_name"],
            split=value["split"],
            shard=SourceShard.from_dict(_strict_mapping(value["shard"], "shard")),
            columns=_parse_columns(value["columns"]),
            snapshot_id=value["snapshot_id"],
            schema_version=value["schema_version"],
        )


PINNED_SOURCE_SNAPSHOT: Final = SolidityCPTSourceSnapshot()
PINNED_SOLIDITY_CPT_SOURCE: Final = PINNED_SOURCE_SNAPSHOT


@dataclass(frozen=True, slots=True)
class SourceSnapshotVerification:
    """Content-addressed receipt for exact source-profile verification."""

    snapshot_id: str
    shard_sha256: str
    shard_size_bytes: int
    row_count: int
    receipt_id: str = ""
    verified: bool = True
    bytes_verified: bool = False
    verification_method: str = "metadata_only"
    schema_version: str = SOURCE_SNAPSHOT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.snapshot_id != PINNED_SOURCE_SNAPSHOT.cid:
            raise SourceSnapshotVerificationError("verification snapshot_id mismatch")
        if self.shard_sha256 != SOLIDITY_CPT_SHARD_SHA256:
            raise SourceSnapshotVerificationError("verification shard digest mismatch")
        if self.shard_size_bytes != SOLIDITY_CPT_SHARD_SIZE_BYTES:
            raise SourceSnapshotVerificationError("verification shard size mismatch")
        if self.row_count != SOLIDITY_CPT_ROW_COUNT:
            raise SourceSnapshotVerificationError("verification row_count mismatch")
        if self.verified is not True:
            raise SourceSnapshotVerificationError("verification receipt must be verified")
        if self.verification_method not in {
            "metadata_only",
            "injected_bytes",
            "local_bytes",
        }:
            raise SourceSnapshotVerificationError("unknown verification method")
        expected_bytes_verified = self.verification_method != "metadata_only"
        if self.bytes_verified is not expected_bytes_verified:
            raise SourceSnapshotVerificationError("bytes_verified does not match verification method")
        if self.schema_version != SOURCE_SNAPSHOT_SCHEMA_VERSION:
            raise SourceSnapshotVerificationError("unknown verification schema")
        computed = canonical_identity(
            self.deterministic_dict(),
            domain="solidity-cpt/source-verification",
            schema_version=self.schema_version,
        ).cid
        if self.receipt_id and self.receipt_id != computed:
            raise SourceSnapshotVerificationError("receipt_id does not match rehashed verification")
        object.__setattr__(self, "receipt_id", computed)

    def deterministic_dict(self) -> dict[str, Any]:
        return {
            "bytes_verified": self.bytes_verified,
            "row_count": self.row_count,
            "schema_version": self.schema_version,
            "shard_sha256": self.shard_sha256,
            "shard_size_bytes": self.shard_size_bytes,
            "snapshot_id": self.snapshot_id,
            "verified": self.verified,
            "verification_method": self.verification_method,
        }

    def to_dict(self) -> dict[str, Any]:
        return {"receipt_id": self.receipt_id, **self.deterministic_dict()}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> SourceSnapshotVerification:
        value = _strict_mapping(value, "source verification")
        _exact_keys(
            value,
            frozenset(
                {
                    "bytes_verified",
                    "receipt_id",
                    "row_count",
                    "schema_version",
                    "shard_sha256",
                    "shard_size_bytes",
                    "snapshot_id",
                    "verified",
                    "verification_method",
                }
            ),
            "source verification",
        )
        if not value["receipt_id"]:
            raise SourceSnapshotVerificationError("persisted source verification requires receipt_id")
        return cls(**value)


def verify_source_snapshot(
    observation: SourceSnapshotObservation | Mapping[str, Any],
) -> SourceSnapshotVerification:
    """Verify exact dataset, revision, split, shard, row, and typed schema facts."""

    if isinstance(observation, Mapping):
        observation = SourceSnapshotObservation.from_dict(observation)
    if not isinstance(observation, SourceSnapshotObservation):
        raise SourceSnapshotVerificationError("observation must be SourceSnapshotObservation or mapping")
    expected = SourceSnapshotObservation(
        dataset_id=SOLIDITY_CPT_DATASET_ID,
        revision=SOLIDITY_CPT_REVISION,
        config_name=SOLIDITY_CPT_CONFIG_NAME,
        split=SOLIDITY_CPT_SPLIT,
        shard=PINNED_SOURCE_SHARD,
        columns=SOLIDITY_CPT_COLUMN_TYPES,
    )
    mismatches = [
        name
        for name in (
            "dataset_id",
            "revision",
            "config_name",
            "split",
            "shard",
            "columns",
        )
        if getattr(observation, name) != getattr(expected, name)
    ]
    if mismatches:
        raise SourceSnapshotVerificationError("source snapshot verification failed: " + ", ".join(mismatches))
    return SourceSnapshotVerification(
        snapshot_id=PINNED_SOURCE_SNAPSHOT.cid,
        shard_sha256=observation.shard.sha256,
        shard_size_bytes=observation.shard.size_bytes,
        row_count=observation.shard.row_count,
    )


def verify_shard_file(
    path: str | Path,
    shard: SourceShard = PINNED_SOURCE_SHARD,
    *,
    chunk_size: int = 1024 * 1024,
) -> None:
    """Stream-hash a local regular file and compare size and SHA-256 exactly."""

    read_verified_shard_bytes(path, shard, chunk_size=chunk_size)


def read_verified_shard_bytes(
    path: str | Path,
    shard: SourceShard = PINNED_SOURCE_SHARD,
    *,
    chunk_size: int = 1024 * 1024,
) -> bytes:
    """Return immutable bytes read from the same descriptor that was hashed."""

    if not isinstance(shard, SourceShard):
        raise TypeError("shard must be SourceShard")
    if type(chunk_size) is not int or chunk_size <= 0:
        raise ValueError("chunk_size must be a positive integer")
    file_path = Path(path)
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(file_path, flags)
    except OSError as exc:
        raise SourceSnapshotVerificationError("source shard is missing, not regular, or a symlink") from exc
    try:
        file_stat = os.fstat(descriptor)
        if not stat.S_ISREG(file_stat.st_mode):
            raise SourceSnapshotVerificationError("source shard is not a regular file")
        if file_stat.st_size != shard.size_bytes:
            raise SourceSnapshotVerificationError(
                f"source shard size mismatch ({file_stat.st_size} != {shard.size_bytes})"
            )
        digest = hashlib.sha256()
        counted = 0
        chunks: list[bytes] = []
        with os.fdopen(descriptor, "rb", closefd=True) as handle:
            descriptor = -1
            while True:
                chunk = handle.read(chunk_size)
                if not chunk:
                    break
                counted += len(chunk)
                if counted > shard.size_bytes:
                    raise SourceSnapshotVerificationError("source shard exceeded pinned byte size while hashing")
                digest.update(chunk)
                chunks.append(chunk)
    except SourceSnapshotVerificationError:
        raise
    except OSError as exc:
        raise SourceSnapshotVerificationError("cannot read source shard") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    if counted != shard.size_bytes or digest.hexdigest() != shard.sha256:
        raise SourceSnapshotVerificationError("source shard sha256 mismatch")
    return b"".join(chunks)


def verify_shard_bytes(
    content: bytes | bytearray | memoryview,
    observation: SourceSnapshotObservation | Mapping[str, Any],
    *,
    verification_method: str = "injected_bytes",
) -> SourceSnapshotVerification:
    """Verify supplied immutable bytes plus independently observed metadata."""

    metadata = verify_source_snapshot(observation)
    if not isinstance(content, (bytes, bytearray, memoryview)):
        raise SourceSnapshotVerificationError("shard content must be bytes-like")
    raw = bytes(content)
    if len(raw) != PINNED_SOURCE_SHARD.size_bytes:
        raise SourceSnapshotVerificationError("source shard byte size mismatch")
    if hashlib.sha256(raw).hexdigest() != PINNED_SOURCE_SHARD.sha256:
        raise SourceSnapshotVerificationError("source shard sha256 mismatch")
    if verification_method not in {"injected_bytes", "local_bytes"}:
        raise SourceSnapshotVerificationError("byte verification method must be injected_bytes or local_bytes")
    return SourceSnapshotVerification(
        snapshot_id=metadata.snapshot_id,
        shard_sha256=metadata.shard_sha256,
        shard_size_bytes=metadata.shard_size_bytes,
        row_count=metadata.row_count,
        bytes_verified=True,
        verification_method=verification_method,
    )


@dataclass(frozen=True, slots=True)
class SolidityCPTRowBounds:
    """Hard limits applied before untrusted decoded values are admitted."""

    max_source_bytes: int = 2 * 1024 * 1024
    max_source_chars: int = 2 * 1024 * 1024
    max_total_bytes: int = 2 * 1024 * 1024 + 16 * 1024
    max_total_chars: int = 2 * 1024 * 1024 + 16 * 1024
    max_metadata_chars: int = 4096
    max_path_chars: int = 4096
    max_path_segments: int = 256
    max_fields: int = len(SOLIDITY_CPT_COLUMNS)
    max_nesting_depth: int = 1
    max_container_items: int = len(SOLIDITY_CPT_COLUMNS)
    max_diagnostics: int = 64
    max_diagnostic_chars: int = 512

    def __post_init__(self) -> None:
        for name in self.__dataclass_fields__:
            value = getattr(self, name)
            if type(value) is not int or value <= 0:
                raise ValueError(f"{name} must be a positive integer")
        if self.max_fields < len(SOLIDITY_CPT_COLUMNS):
            raise ValueError("max_fields cannot be below pinned column count")
        if self.max_container_items < len(SOLIDITY_CPT_COLUMNS):
            raise ValueError("max_container_items cannot be below pinned column count")

    def to_dict(self) -> dict[str, int]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}

    @property
    def config_cid(self) -> str:
        return canonical_identity(
            self.to_dict(),
            domain="solidity-cpt-security-ir/config",
            schema_version="solidity-cpt-producer-config/v1",
        ).cid


DEFAULT_ROW_BOUNDS: Final = SolidityCPTRowBounds()


@dataclass(frozen=True, slots=True)
class SolidityCPTSourceBody:
    """A separately persisted, content-addressed inert Solidity body."""

    text: str
    byte_length: int = 0
    sha256: str = ""
    content_cid: str = ""
    schema_version: str = SOURCE_BODY_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.text, str):
            raise SolidityCPTRowError("source body text must be a string")
        try:
            encoded = self.text.encode("utf-8")
        except UnicodeEncodeError as exc:
            raise SolidityCPTRowPoisonedError("source body contains invalid Unicode") from exc
        computed_length = len(encoded)
        if not self.text:
            raise SolidityCPTRowError("source body must not be empty")
        if len(self.text) > DEFAULT_ROW_BOUNDS.max_source_chars:
            raise SolidityCPTRowOversizeError("source body exceeds character bound")
        if computed_length > DEFAULT_ROW_BOUNDS.max_source_bytes:
            raise SolidityCPTRowOversizeError("source body exceeds byte bound")
        computed_sha = hashlib.sha256(encoded).hexdigest()
        computed_cid = cid_v1(encoded)
        for label, supplied, computed in (
            ("byte_length", self.byte_length, computed_length),
            ("sha256", self.sha256, computed_sha),
            ("content_cid", self.content_cid, computed_cid),
        ):
            if supplied not in ("", 0) and supplied != computed:
                raise SolidityCPTRowError(f"{label} does not match rehashed source body")
        if self.schema_version != SOURCE_BODY_SCHEMA_VERSION:
            raise SolidityCPTRowError("unknown source body schema")
        object.__setattr__(self, "byte_length", computed_length)
        object.__setattr__(self, "sha256", computed_sha)
        object.__setattr__(self, "content_cid", computed_cid)

    def to_dict(self) -> dict[str, Any]:
        return {
            "byte_length": self.byte_length,
            "content_cid": self.content_cid,
            "schema_version": self.schema_version,
            "sha256": self.sha256,
            "text": self.text,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> SolidityCPTSourceBody:
        value = _strict_mapping(value, "source body")
        _exact_keys(
            value,
            frozenset({"byte_length", "content_cid", "schema_version", "sha256", "text"}),
            "source body",
            SolidityCPTRowError,
        )
        for identity_name in ("content_cid", "sha256"):
            if not value[identity_name]:
                raise SolidityCPTRowError(f"persisted source body requires {identity_name}")
        if type(value["byte_length"]) is not int or value["byte_length"] <= 0:
            raise SolidityCPTRowError("persisted source body requires positive byte_length")
        return cls(**value)


@dataclass(frozen=True, slots=True)
class SolidityCPTRow:
    """Source-body-free normalized metadata for one exact source row."""

    row_index: int
    source: str
    address: str
    name: str
    compiler: str
    license: str
    path: str
    n_chars: int
    source_body_cid: str
    source_body_sha256: str
    source_snapshot_cid: str
    config_cid: str
    raw_row_cid: str
    row_id: str = ""
    address_is_unverified_hint: bool = True
    deployed_bytecode_equality: bool = False
    schema_version: str = SOURCE_ROW_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if type(self.row_index) is not int or not 0 <= self.row_index < SOLIDITY_CPT_ROW_COUNT:
            raise SolidityCPTRowError("row_index is outside the pinned snapshot")
        for name in (
            "source",
            "address",
            "name",
            "compiler",
            "license",
            "path",
            "source_body_cid",
            "source_body_sha256",
            "source_snapshot_cid",
            "config_cid",
            "raw_row_cid",
        ):
            if not isinstance(getattr(self, name), str):
                raise SolidityCPTRowError(f"{name} must be text")
        for name in ("source", "address", "name", "compiler", "license"):
            _clean_text(
                getattr(self, name),
                name,
                max_chars=DEFAULT_ROW_BOUNDS.max_metadata_chars,
                max_bytes=DEFAULT_ROW_BOUNDS.max_metadata_chars * 4,
            )
        _safe_path(self.path, DEFAULT_ROW_BOUNDS)
        if type(self.n_chars) is not int or self.n_chars < 0:
            raise SolidityCPTRowError("n_chars must be a non-negative integer")
        if self.n_chars > DEFAULT_ROW_BOUNDS.max_source_chars:
            raise SolidityCPTRowOversizeError("n_chars exceeds source character bound")
        if not _is_cid(self.source_body_cid):
            raise SolidityCPTRowError("source_body_cid must be an ir_core CID")
        if not _is_sha256(self.source_body_sha256):
            raise SolidityCPTRowError("source_body_sha256 must be lowercase SHA-256")
        if self.source_snapshot_cid != PINNED_SOURCE_SNAPSHOT.cid:
            raise SolidityCPTRowError("source_snapshot_cid is not the reviewed pin")
        if not _is_cid(self.config_cid):
            raise SolidityCPTRowError("config_cid must be an ir_core CID")
        if not _is_cid(self.raw_row_cid):
            raise SolidityCPTRowError("raw_row_cid must be an ir_core CID")
        if self.address_is_unverified_hint is not True:
            raise SolidityCPTRowError("address must remain an unverified hint")
        if self.deployed_bytecode_equality is not False:
            raise SolidityCPTRowError("source metadata cannot assert deployed bytecode equality")
        if self.schema_version != SOURCE_ROW_SCHEMA_VERSION:
            raise SolidityCPTRowError("unknown source row schema")
        computed = self.identity.cid
        if self.row_id and self.row_id != computed:
            raise SolidityCPTRowError("row_id does not match rehashed normalized row")
        object.__setattr__(self, "row_id", computed)

    def deterministic_dict(self) -> dict[str, Any]:
        return {
            "address": self.address,
            "address_is_unverified_hint": self.address_is_unverified_hint,
            "compiler": self.compiler,
            "config_cid": self.config_cid,
            "deployed_bytecode_equality": self.deployed_bytecode_equality,
            "license": self.license,
            "n_chars": self.n_chars,
            "name": self.name,
            "path": self.path,
            "raw_row_cid": self.raw_row_cid,
            "row_index": self.row_index,
            "schema_version": self.schema_version,
            "source": self.source,
            "source_body_cid": self.source_body_cid,
            "source_body_sha256": self.source_body_sha256,
            "source_snapshot_cid": self.source_snapshot_cid,
        }

    def to_dict(self) -> dict[str, Any]:
        return {"row_id": self.row_id, **self.deterministic_dict()}

    @property
    def identity(self) -> CanonicalIdentity:
        return canonical_identity(
            self.deterministic_dict(),
            domain="solidity-cpt/source-row",
            schema_version=self.schema_version,
        )

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> SolidityCPTRow:
        value = _strict_mapping(value, "source row record")
        expected = frozenset(
            {
                "address",
                "address_is_unverified_hint",
                "compiler",
                "config_cid",
                "deployed_bytecode_equality",
                "license",
                "n_chars",
                "name",
                "path",
                "raw_row_cid",
                "row_id",
                "row_index",
                "schema_version",
                "source",
                "source_body_cid",
                "source_body_sha256",
                "source_snapshot_cid",
            }
        )
        _exact_keys(value, expected, "source row record", SolidityCPTRowError)
        if not value["row_id"]:
            raise SolidityCPTRowError("persisted source row requires row_id")
        return cls(**value)


@dataclass(frozen=True, slots=True)
class AdaptedSolidityCPTRow:
    """A runtime pair whose persisted components remain physically separate."""

    row: SolidityCPTRow
    source_body: SolidityCPTSourceBody

    def __post_init__(self) -> None:
        if self.row.source_body_cid != self.source_body.content_cid:
            raise SolidityCPTRowError("row/source body CID mismatch")
        if self.row.source_body_sha256 != self.source_body.sha256:
            raise SolidityCPTRowError("row/source body digest mismatch")
        if self.row.n_chars != len(self.source_body.text):
            raise SolidityCPTRowError("row/source body character count mismatch")

    @property
    def text(self) -> str:
        return self.source_body.text

    @property
    def row_index(self) -> int:
        return self.row.row_index

    @property
    def row_id(self) -> str:
        return self.row.row_id

    def to_dict(self) -> dict[str, Any]:
        return {
            "row": self.row.to_dict(),
            "source_body": self.source_body.to_dict(),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> AdaptedSolidityCPTRow:
        value = _strict_mapping(value, "adapted row")
        _exact_keys(
            value,
            frozenset({"row", "source_body"}),
            "adapted row",
            SolidityCPTRowError,
        )
        return cls(
            row=SolidityCPTRow.from_dict(_strict_mapping(value["row"], "normalized row")),
            source_body=SolidityCPTSourceBody.from_dict(_strict_mapping(value["source_body"], "source body")),
        )


class QuarantineReason(StrEnum):
    MALFORMED = "malformed"
    OVERSIZE = "oversize"
    POISONED = "poisoned"
    DRIFTED = "drifted"
    TRUNCATED = "truncated"
    DUPLICATE = "duplicate"
    UNKNOWN_AUTHORITY = "unknown_authority"


@dataclass(frozen=True, slots=True)
class QuarantineDiagnostic:
    """Bounded, source-free diagnostic for one rejected input item."""

    reason: QuarantineReason
    code: str
    message: str
    row_index: int | None = None
    diagnostic_id: str = ""
    schema_version: str = QUARANTINE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        try:
            reason = self.reason if isinstance(self.reason, QuarantineReason) else QuarantineReason(self.reason)
        except (TypeError, ValueError) as exc:
            raise SolidityCPTRowError("unknown quarantine reason") from exc
        object.__setattr__(self, "reason", reason)
        for name in ("code", "message"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value or "\x00" in value:
                raise SolidityCPTRowError(f"diagnostic {name} must be bounded text")
        if len(self.code) > 128:
            raise SolidityCPTRowError("diagnostic code exceeds character bound")
        if len(self.message) > DEFAULT_ROW_BOUNDS.max_diagnostic_chars:
            raise SolidityCPTRowError("diagnostic message exceeds character bound")
        if self.row_index is not None and (type(self.row_index) is not int or self.row_index < 0):
            raise SolidityCPTRowError("diagnostic row_index must be non-negative or null")
        if self.schema_version != QUARANTINE_SCHEMA_VERSION:
            raise SolidityCPTRowError("unknown quarantine schema")
        computed = canonical_identity(
            self.deterministic_dict(),
            domain="solidity-cpt/quarantine",
            schema_version=self.schema_version,
        ).cid
        if self.diagnostic_id and self.diagnostic_id != computed:
            raise SolidityCPTRowError("diagnostic_id does not match rehashed diagnostic")
        object.__setattr__(self, "diagnostic_id", computed)

    def deterministic_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "reason": self.reason.value,
            "row_index": self.row_index,
            "schema_version": self.schema_version,
        }

    def to_dict(self) -> dict[str, Any]:
        return {"diagnostic_id": self.diagnostic_id, **self.deterministic_dict()}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> QuarantineDiagnostic:
        value = _strict_mapping(value, "quarantine diagnostic")
        _exact_keys(
            value,
            frozenset(
                {
                    "code",
                    "diagnostic_id",
                    "message",
                    "reason",
                    "row_index",
                    "schema_version",
                }
            ),
            "quarantine diagnostic",
            SolidityCPTRowError,
        )
        if not value["diagnostic_id"]:
            raise SolidityCPTRowError("persisted diagnostic requires diagnostic_id")
        return cls(**value)


def _clean_text(
    value: Any,
    label: str,
    *,
    max_chars: int,
    max_bytes: int | None = None,
    required: bool = False,
) -> str:
    if value is None and not required:
        return ""
    if not isinstance(value, str) or (required and not value):
        raise SolidityCPTRowError(f"{label} must be text")
    if len(value) > max_chars:
        raise SolidityCPTRowOversizeError(f"{label} exceeds character bound")
    if "\x00" in value:
        raise SolidityCPTRowPoisonedError(f"{label} contains NUL")
    if any(ord(character) < 32 and character not in "\t\n\r" for character in value):
        raise SolidityCPTRowPoisonedError(f"{label} contains unsupported control characters")
    try:
        encoded = value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise SolidityCPTRowPoisonedError(f"{label} contains invalid Unicode") from exc
    if max_bytes is not None and len(encoded) > max_bytes:
        raise SolidityCPTRowOversizeError(f"{label} exceeds byte bound")
    return value


def _safe_path(value: Any, bounds: SolidityCPTRowBounds) -> str:
    path = _clean_text(
        value,
        "path",
        max_chars=bounds.max_path_chars,
        max_bytes=bounds.max_path_chars * 4,
    )
    if not path:
        return ""
    pure = PurePosixPath(path)
    if (
        pure.is_absolute()
        or "\\" in path
        or pure.as_posix() != path
        or any(part in {"", ".", ".."} for part in pure.parts)
    ):
        raise SolidityCPTRowPoisonedError("path must be safe relative POSIX text")
    if len(pure.parts) > bounds.max_path_segments:
        raise SolidityCPTRowOversizeError("path exceeds segment bound")
    return path


class SolidityCPTRowAdapter:
    """Strict adapter from the exact eight-column row into inert artifacts."""

    def __init__(self, bounds: SolidityCPTRowBounds = DEFAULT_ROW_BOUNDS) -> None:
        if not isinstance(bounds, SolidityCPTRowBounds):
            raise TypeError("bounds must be SolidityCPTRowBounds")
        self._bounds = bounds

    @property
    def bounds(self) -> SolidityCPTRowBounds:
        return self._bounds

    @property
    def config_cid(self) -> str:
        return self._bounds.config_cid

    def adapt(
        self,
        value: Mapping[str, Any],
        *,
        row_index: int,
    ) -> AdaptedSolidityCPTRow:
        if not isinstance(value, Mapping):
            raise SolidityCPTRowError("source row must be a mapping")
        actual = set(value)
        expected = set(SOLIDITY_CPT_COLUMNS)
        unexpected = actual - expected
        if unexpected & _AUTHORITY_FIELD_NAMES:
            raise SolidityCPTUnknownAuthorityError("source row contains unknown authority field")
        if len(value) > self._bounds.max_container_items:
            raise SolidityCPTRowOversizeError("source row exceeds item bound")
        _exact_keys(
            value,
            frozenset(expected),
            "source row",
            SolidityCPTRowDriftError,
        )
        if len(value) > self._bounds.max_fields:
            raise SolidityCPTRowOversizeError("source row exceeds field bound")
        for name, item in value.items():
            if isinstance(item, (Mapping, Sequence)) and not isinstance(item, (str, bytes, bytearray)):
                raise SolidityCPTRowDriftError(f"{name} must be a scalar; nested input is not admitted")
            if isinstance(item, (bytes, bytearray, memoryview)):
                raise SolidityCPTRowDriftError(f"{name} must be decoded scalar data")

        text = _clean_text(
            value["text"],
            "text",
            max_chars=self._bounds.max_source_chars,
            max_bytes=self._bounds.max_source_bytes,
            required=True,
        )
        body = SolidityCPTSourceBody(text=text)
        n_chars = value["n_chars"]
        if type(n_chars) is not int or n_chars < 0:
            raise SolidityCPTRowError("n_chars must be a non-negative integer")
        if n_chars != len(text):
            raise SolidityCPTRowDriftError("n_chars does not equal source text length")

        metadata = {
            name: _clean_text(
                value[name],
                name,
                max_chars=self._bounds.max_metadata_chars,
                max_bytes=self._bounds.max_metadata_chars * 4,
            )
            for name in ("source", "address", "name", "compiler", "license")
        }
        path = _safe_path(value["path"], self._bounds)
        total_chars = len(text) + sum(len(item) for item in metadata.values()) + len(path)
        total_bytes = body.byte_length + sum(len(item.encode("utf-8")) for item in (*metadata.values(), path))
        if total_chars > self._bounds.max_total_chars:
            raise SolidityCPTRowOversizeError("source row exceeds total character bound")
        if total_bytes > self._bounds.max_total_bytes:
            raise SolidityCPTRowOversizeError("source row exceeds total byte bound")

        row = SolidityCPTRow(
            row_index=row_index,
            source=metadata["source"],
            address=metadata["address"],
            name=metadata["name"],
            compiler=metadata["compiler"],
            license=metadata["license"],
            path=path,
            n_chars=n_chars,
            source_body_cid=body.content_cid,
            source_body_sha256=body.sha256,
            source_snapshot_cid=PINNED_SOURCE_SNAPSHOT.cid,
            config_cid=self.config_cid,
            raw_row_cid=canonical_identity(
                value,
                domain="solidity-cpt/raw-row",
                schema_version=SOURCE_ROW_SCHEMA_VERSION,
            ).cid,
        )
        return AdaptedSolidityCPTRow(row=row, source_body=body)

    def quarantine(
        self,
        error: Exception,
        *,
        row_index: int | None,
    ) -> QuarantineDiagnostic:
        if isinstance(error, SolidityCPTUnknownAuthorityError):
            reason = QuarantineReason.UNKNOWN_AUTHORITY
        elif isinstance(error, SolidityCPTRowOversizeError):
            reason = QuarantineReason.OVERSIZE
        elif isinstance(error, SolidityCPTRowPoisonedError):
            reason = QuarantineReason.POISONED
        elif isinstance(error, SolidityCPTRowDriftError):
            reason = QuarantineReason.DRIFTED
        else:
            reason = QuarantineReason.MALFORMED
        message = str(error).replace("\x00", "\\0")
        maximum = min(
            self._bounds.max_diagnostic_chars,
            DEFAULT_ROW_BOUNDS.max_diagnostic_chars,
        )
        if len(message) > maximum:
            message = message[: maximum - 1] + "…"
        return QuarantineDiagnostic(
            reason=reason,
            code=f"solidity_cpt.row.{reason.value}",
            message=message or "row rejected",
            row_index=row_index,
        )


DEFAULT_ROW_ADAPTER: Final = SolidityCPTRowAdapter()


def adapt_solidity_cpt_row(
    value: Mapping[str, Any],
    *,
    row_index: int,
    bounds: SolidityCPTRowBounds = DEFAULT_ROW_BOUNDS,
) -> AdaptedSolidityCPTRow:
    """Adapt one decoded row without execution or authority inference."""

    return SolidityCPTRowAdapter(bounds).adapt(value, row_index=row_index)


SOLIDITY_CPT_COLUMN_TYPE_MAP: Final[Mapping[str, str]] = MappingProxyType(dict(SOLIDITY_CPT_COLUMN_TYPES))


__all__ = [
    "AdaptedSolidityCPTRow",
    "DEFAULT_ROW_ADAPTER",
    "DEFAULT_ROW_BOUNDS",
    "PINNED_SOLIDITY_CPT_SOURCE",
    "PINNED_SOURCE_SHARD",
    "PINNED_SOURCE_SNAPSHOT",
    "QUARANTINE_SCHEMA_VERSION",
    "QuarantineDiagnostic",
    "QuarantineReason",
    "ROW_ADAPTER_SCHEMA_VERSION",
    "SOURCE_BODY_SCHEMA_VERSION",
    "SOURCE_ROW_SCHEMA_VERSION",
    "SOURCE_SNAPSHOT_SCHEMA_VERSION",
    "SOLIDITY_CPT_COLUMN_TYPE_MAP",
    "SolidityCPTRow",
    "SolidityCPTRowAdapter",
    "SolidityCPTRowBounds",
    "SolidityCPTRowDriftError",
    "SolidityCPTRowError",
    "SolidityCPTRowOversizeError",
    "SolidityCPTRowPoisonedError",
    "SolidityCPTSourceBody",
    "SolidityCPTSourceSnapshot",
    "SolidityCPTUnknownAuthorityError",
    "SourceShard",
    "SourceSnapshotError",
    "SourceSnapshotObservation",
    "SourceSnapshotVerification",
    "SourceSnapshotVerificationError",
    "adapt_solidity_cpt_row",
    "read_verified_shard_bytes",
    "verify_shard_file",
    "verify_shard_bytes",
    "verify_source_snapshot",
]
