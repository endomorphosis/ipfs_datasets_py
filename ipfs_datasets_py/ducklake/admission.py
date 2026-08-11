"""Streaming Parquet discovery and admission service (DQK-087).

Captures canonical URI, streaming whole-file digest/CID, immutable object
generation/version/ETag, footer and schema identity, row/file statistics,
partition hints, producer and tenant provenance, policy classification, and an
immutable decision receipt **before** any file reaches DuckLake. All identity
evidence is revalidated immediately before copy and registration.

Discovery streams a whole-file digest plus bounded footer metadata without
loading row groups or materializing datasets. Symlink, path traversal,
replacement, object-generation/ETag drift, footer drift, duplicate, and
schema-conflict cases fail closed. Sensitive sources require an explicit
policy decision. Admission records source ownership and whether a lifecycle-
managed copy is required before registration.

Import is side-effect free: no DuckDB connection, no network, no filesystem
writes until an admission entry point is called.
"""

from __future__ import annotations

import hashlib
import json
import os
import struct
import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import (
    Any,
    Callable,
    ClassVar,
    Final,
    Iterable,
    Iterator,
    Mapping,
    Sequence,
)

from ipfs_datasets_py.ducklake.schema import ContentIdentity, LakeIdentityError

__all__ = [
    "ADMISSION_DECISION_RECEIPT_SCHEMA",
    "ADMISSION_SCHEMA",
    "DEFAULT_CHUNK_SIZE",
    "DEFAULT_MAX_FOOTER_BYTES",
    "DISCOVERY_EVIDENCE_SCHEMA",
    "PARQUET_MAGIC",
    "AdmissionDecisionReceipt",
    "AdmissionError",
    "AdmissionLedger",
    "AdmissionService",
    "DecisionOutcome",
    "DiscoveryEvidence",
    "DuplicateSourceError",
    "FooterDriftError",
    "FooterMetadata",
    "ObjectGenerationDriftError",
    "ObjectGenerationIdentity",
    "ParquetDiscoveryError",
    "PathTraversalError",
    "PolicyClassification",
    "PolicyClass",
    "PolicyDecision",
    "PolicyRequiredError",
    "Provenance",
    "RejectionReason",
    "ReplacementError",
    "SchemaConflictError",
    "SchemaIdentity",
    "SourceOwnership",
    "SourceOwnershipKind",
    "Statistics",
    "SymlinkRejectedError",
    "admit_parquet_source",
    "canonical_uri_for_path",
    "discover_parquet_file",
    "iter_discover_parquet",
    "revalidate_before_copy_register",
    "render_admission_parquet_bytes",
    "stream_file_digest",
    "write_admission_parquet",
]


# ---------------------------------------------------------------------------
# Schema / constants
# ---------------------------------------------------------------------------

ADMISSION_SCHEMA: Final[str] = "ipfs_datasets_py/ducklake-parquet-admission@1"
DISCOVERY_EVIDENCE_SCHEMA: Final[str] = (
    "ipfs_datasets_py/ducklake-parquet-discovery-evidence@1"
)
ADMISSION_DECISION_RECEIPT_SCHEMA: Final[str] = (
    "ipfs_datasets_py/ducklake-parquet-admission-decision-receipt@1"
)

_IMPLEMENTATION_GENERATION: Final[str] = (
    "dqk-087-parquet-admission-20260810"
)

PARQUET_MAGIC: Final[bytes] = b"PAR1"
DEFAULT_CHUNK_SIZE: Final[int] = 1024 * 1024
# Bound footer reads so discovery never loads multi-GB row-group payloads.
DEFAULT_MAX_FOOTER_BYTES: Final[int] = 16 * 1024 * 1024
_ADMISSION_FOOTER_FORMAT: Final[str] = "ducklake-parquet-admission@1"
_ENVELOPE_FOOTER_FORMAT: Final[str] = "parquet-envelope@1"
_SHA256_RE_PREFIX: Final[str] = "sha256:"


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class AdmissionError(ValueError):
    """Fail-closed Parquet discovery / admission rejection."""

    def __init__(
        self,
        message: str,
        *,
        reason: "RejectionReason | None" = None,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.reason = reason
        self.details = dict(details or {})


class ParquetDiscoveryError(AdmissionError):
    """Source path is not a discoverable Parquet object."""


class SymlinkRejectedError(AdmissionError):
    """Symlink sources are rejected (fail closed)."""


class PathTraversalError(AdmissionError):
    """Resolved path escapes the allowed discovery roots."""


class ReplacementError(AdmissionError):
    """Whole-file digest changed between discovery and revalidation."""


class ObjectGenerationDriftError(AdmissionError):
    """Object generation / version / ETag drifted before copy/register."""


class FooterDriftError(AdmissionError):
    """Footer identity drifted before copy/register."""


class DuplicateSourceError(AdmissionError):
    """Identical content was already admitted (fail closed)."""


class SchemaConflictError(AdmissionError):
    """Schema identity conflicts with a registered dataset contract."""


class PolicyRequiredError(AdmissionError):
    """Sensitive / restricted source lacks an explicit policy decision."""


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class RejectionReason(str, Enum):
    """Closed set of fail-closed rejection reasons."""

    SYMLINK = "symlink"
    PATH_TRAVERSAL = "path_traversal"
    NOT_PARQUET = "not_parquet"
    TOO_SMALL = "too_small"
    FOOTER_INVALID = "footer_invalid"
    FOOTER_UNBOUNDED = "footer_unbounded"
    REPLACEMENT = "replacement"
    OBJECT_GENERATION_DRIFT = "object_generation_drift"
    FOOTER_DRIFT = "footer_drift"
    DUPLICATE = "duplicate"
    SCHEMA_CONFLICT = "schema_conflict"
    POLICY_REQUIRED = "policy_required"
    POLICY_DENIED = "policy_denied"
    REVALIDATION_FAILED = "revalidation_failed"
    MISSING_IDENTITY = "missing_identity"
    UNSAFE_PATH = "unsafe_path"


class DecisionOutcome(str, Enum):
    """Admission decision outcomes."""

    ADMITTED = "admitted"
    REJECTED = "rejected"
    PENDING_POLICY = "pending_policy"


class PolicyClass(str, Enum):
    """Policy classification for a source."""

    PUBLIC = "public"
    INTERNAL = "internal"
    SENSITIVE = "sensitive"
    RESTRICTED = "restricted"

    @classmethod
    def parse(cls, value: str | "PolicyClass") -> "PolicyClass":
        if isinstance(value, PolicyClass):
            return value
        text = str(value or "").strip().lower()
        try:
            return cls(text)
        except ValueError as exc:
            raise AdmissionError(
                f"unknown policy class {value!r}",
                reason=RejectionReason.POLICY_REQUIRED,
            ) from exc

    @property
    def requires_explicit_decision(self) -> bool:
        return self in {PolicyClass.SENSITIVE, PolicyClass.RESTRICTED}


class SourceOwnershipKind(str, Enum):
    """Whether the source is lifecycle-managed by the lake owner."""

    EXTERNAL_UNMANAGED = "external_unmanaged"
    LIFECYCLE_MANAGED = "lifecycle_managed"
    PENDING_TRANSFER = "pending_transfer"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _utc_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _canonical_json(payload: Any) -> str:
    return json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )


def _canonical_json_bytes(payload: Any) -> bytes:
    return _canonical_json(payload).encode("utf-8")


def _sha256_bytes(data: bytes) -> str:
    return _SHA256_RE_PREFIX + hashlib.sha256(data).hexdigest()


def _sha256_text(text: str) -> str:
    return _SHA256_RE_PREFIX + hashlib.sha256(text.encode("utf-8")).hexdigest()


def _require_nonempty(value: str, *, field_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise AdmissionError(
            f"{field_name} must be non-empty",
            reason=RejectionReason.MISSING_IDENTITY,
        )
    return text


def _normalize_digest(digest: str) -> str:
    text = str(digest or "").strip().lower()
    if text.startswith(_SHA256_RE_PREFIX):
        hexpart = text[len(_SHA256_RE_PREFIX) :]
    else:
        hexpart = text
        text = _SHA256_RE_PREFIX + hexpart
    if len(hexpart) != 64 or any(c not in "0123456789abcdef" for c in hexpart):
        raise AdmissionError(
            f"digest must be sha256 hex, got {digest!r}",
            reason=RejectionReason.MISSING_IDENTITY,
        )
    return text


def stream_file_digest(
    path: str | os.PathLike[str] | Path,
    *,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    digest_factory: Callable[[], Any] = hashlib.sha256,
) -> tuple[int, str]:
    """Hash *path* with bounded memory; return ``(size_bytes, sha256:hex)``.

    Reads at most *chunk_size* bytes at a time so multi-hundred-MB corpora never
    load wholly into RAM. Does not parse Parquet row groups.
    """
    if chunk_size <= 0:
        raise AdmissionError(
            f"chunk_size must be positive, got {chunk_size}",
            reason=RejectionReason.UNSAFE_PATH,
        )
    target = Path(path)
    hasher = digest_factory()
    update = getattr(hasher, "update")
    hexdigest = getattr(hasher, "hexdigest")
    size = 0
    with target.open("rb") as handle:
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            size += len(chunk)
            update(chunk)
    return size, _SHA256_RE_PREFIX + str(hexdigest())


def canonical_uri_for_path(path: str | os.PathLike[str] | Path) -> str:
    """Return a stable ``file://`` URI for a resolved local path."""
    resolved = Path(path).resolve(strict=False)
    return resolved.as_uri()


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def assert_safe_source_path(
    path: str | os.PathLike[str] | Path,
    *,
    allowed_roots: Sequence[str | os.PathLike[str] | Path] | None = None,
    reject_symlinks: bool = True,
) -> Path:
    """Resolve *path* and fail closed on symlinks / traversal.

    Returns the resolved absolute path when safe.
    """
    raw = Path(path)
    # Reject symlink leaves before resolve follows them.
    if reject_symlinks and raw.exists() and raw.is_symlink():
        raise SymlinkRejectedError(
            f"symlink sources are rejected: {raw}",
            reason=RejectionReason.SYMLINK,
            details={"path": str(raw)},
        )
    # Also reject when any parent component is a symlink into foreign space
    # once we have an allowlist (checked after resolve against roots).
    try:
        resolved = raw.resolve(strict=False)
    except OSError as exc:
        raise ParquetDiscoveryError(
            f"cannot resolve path {raw}: {exc}",
            reason=RejectionReason.UNSAFE_PATH,
            details={"path": str(raw)},
        ) from exc

    text = os.fspath(path).replace("\\", "/")
    if ".." in PurePosixPath(text).parts:
        # Relative inputs containing ".." must still land under an allow root.
        if not allowed_roots:
            raise PathTraversalError(
                f"path traversal rejected without allow roots: {path}",
                reason=RejectionReason.PATH_TRAVERSAL,
                details={"path": str(path)},
            )

    if reject_symlinks and resolved.exists() and resolved.is_symlink():
        raise SymlinkRejectedError(
            f"symlink sources are rejected: {resolved}",
            reason=RejectionReason.SYMLINK,
            details={"path": str(resolved)},
        )

    if allowed_roots:
        roots = [Path(r).resolve(strict=False) for r in allowed_roots]
        if not any(_is_relative_to(resolved, root) for root in roots):
            raise PathTraversalError(
                f"path escapes allowed roots: {resolved}",
                reason=RejectionReason.PATH_TRAVERSAL,
                details={
                    "path": str(resolved),
                    "allowed_roots": [str(r) for r in roots],
                },
            )
        # Fail closed if the path is reached via a symlink chain from outside.
        for root in roots:
            if _is_relative_to(resolved, root):
                try:
                    # Walk from root using the relative parts without following
                    # mid-path symlinks that would escape.
                    rel = resolved.relative_to(root)
                    cursor = root
                    for part in rel.parts:
                        cursor = cursor / part
                        if cursor.is_symlink() and reject_symlinks:
                            # Symlink under root is still rejected for sources.
                            raise SymlinkRejectedError(
                                f"symlink component rejected: {cursor}",
                                reason=RejectionReason.SYMLINK,
                                details={"path": str(cursor)},
                            )
                except ValueError:
                    continue
                break

    return resolved


# ---------------------------------------------------------------------------
# Identity / metadata records
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ObjectGenerationIdentity:
    """Immutable object-store generation / version / ETag binding."""

    object_generation: str = ""
    version_id: str = ""
    etag: str = ""

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "object_generation": self.object_generation,
                "version_id": self.version_id,
                "etag": self.etag,
            }
        )

    def is_bound(self) -> bool:
        return bool(self.object_generation or self.version_id or self.etag)

    def matches(self, other: "ObjectGenerationIdentity") -> bool:
        return (
            self.object_generation == other.object_generation
            and self.version_id == other.version_id
            and self.etag == other.etag
        )


@dataclass(frozen=True, slots=True)
class FooterMetadata:
    """Bounded footer identity captured without loading row groups."""

    footer_length: int
    footer_digest: str
    magic_head_ok: bool
    magic_tail_ok: bool
    footer_format: str = "opaque"
    max_footer_bytes: int = DEFAULT_MAX_FOOTER_BYTES

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "footer_length": self.footer_length,
                "footer_digest": self.footer_digest,
                "magic_head_ok": self.magic_head_ok,
                "magic_tail_ok": self.magic_tail_ok,
                "footer_format": self.footer_format,
                "max_footer_bytes": self.max_footer_bytes,
            }
        )


@dataclass(frozen=True, slots=True)
class SchemaIdentity:
    """Schema identity derived from bounded footer metadata."""

    schema_digest: str
    fields: tuple[Mapping[str, str], ...] = ()
    field_count: int = 0

    def __post_init__(self) -> None:
        if self.schema_digest:
            object.__setattr__(
                self, "schema_digest", _normalize_digest(self.schema_digest)
            )
        if self.field_count == 0 and self.fields:
            object.__setattr__(self, "field_count", len(self.fields))

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "schema_digest": self.schema_digest,
                "fields": [dict(f) for f in self.fields],
                "field_count": self.field_count,
            }
        )


@dataclass(frozen=True, slots=True)
class Statistics:
    """Row / file statistics captured at discovery."""

    byte_size: int
    row_count: int = 0
    num_row_groups: int = 0
    column_count: int = 0

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "byte_size": self.byte_size,
                "row_count": self.row_count,
                "num_row_groups": self.num_row_groups,
                "column_count": self.column_count,
            }
        )


@dataclass(frozen=True, slots=True)
class Provenance:
    """Producer and tenant provenance for an admitted source."""

    producer: str
    tenant: str = ""
    dataset_alias: str = ""
    namespace: str = ""
    extra: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "producer", _require_nonempty(self.producer, field_name="producer")
        )
        object.__setattr__(self, "extra", MappingProxyType(dict(self.extra or {})))

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "producer": self.producer,
                "tenant": self.tenant,
                "dataset_alias": self.dataset_alias,
                "namespace": self.namespace,
                "extra": dict(self.extra),
            }
        )


@dataclass(frozen=True, slots=True)
class PolicyClassification:
    """Policy classification attached to a source."""

    policy_class: PolicyClass
    labels: tuple[str, ...] = ()
    notes: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "policy_class", PolicyClass.parse(self.policy_class)
        )

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "policy_class": self.policy_class.value,
                "labels": list(self.labels),
                "notes": self.notes,
                "requires_explicit_decision": (
                    self.policy_class.requires_explicit_decision
                ),
            }
        )


@dataclass(frozen=True, slots=True)
class PolicyDecision:
    """Explicit policy decision required for sensitive / restricted sources."""

    decision_id: str
    allowed: bool
    decided_by: str
    policy_class: PolicyClass
    reason: str = ""
    decided_at: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "decision_id",
            _require_nonempty(self.decision_id, field_name="decision_id"),
        )
        object.__setattr__(
            self,
            "decided_by",
            _require_nonempty(self.decided_by, field_name="decided_by"),
        )
        object.__setattr__(
            self, "policy_class", PolicyClass.parse(self.policy_class)
        )
        if not self.decided_at:
            object.__setattr__(self, "decided_at", _utc_iso())

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "decision_id": self.decision_id,
                "allowed": bool(self.allowed),
                "decided_by": self.decided_by,
                "policy_class": self.policy_class.value,
                "reason": self.reason,
                "decided_at": self.decided_at,
            }
        )


@dataclass(frozen=True, slots=True)
class SourceOwnership:
    """Source ownership recorded at admission time."""

    owner_id: str
    ownership_kind: SourceOwnershipKind
    copy_required: bool
    tenant: str = ""
    shard_id: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "owner_id", _require_nonempty(self.owner_id, field_name="owner_id")
        )
        if not isinstance(self.ownership_kind, SourceOwnershipKind):
            object.__setattr__(
                self,
                "ownership_kind",
                SourceOwnershipKind(str(self.ownership_kind)),
            )
        object.__setattr__(self, "copy_required", bool(self.copy_required))

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "owner_id": self.owner_id,
                "ownership_kind": self.ownership_kind.value,
                "copy_required": self.copy_required,
                "tenant": self.tenant,
                "shard_id": self.shard_id,
            }
        )


def default_copy_required(ownership_kind: SourceOwnershipKind) -> bool:
    """Lifecycle-managed lake copies are always required for unmanaged sources.

    DuckLake must never register an external / immutable CID source that
    maintenance is not allowed to replace and delete (DQK-088 contract).
    """
    if ownership_kind is SourceOwnershipKind.LIFECYCLE_MANAGED:
        return False
    return True


# ---------------------------------------------------------------------------
# Synthetic Parquet envelope (stdlib, hermetic tests + metadata-only sources)
# ---------------------------------------------------------------------------


def schema_digest_for_fields(fields: Sequence[Mapping[str, Any]]) -> str:
    """Canonical schema digest over ordered field name/type pairs."""
    normalized = [
        {
            "name": str(f.get("name", "")).strip(),
            "type": str(f.get("type", "bytes")).strip().lower(),
        }
        for f in fields
    ]
    if any(not item["name"] for item in normalized):
        raise AdmissionError(
            "schema fields require non-empty names",
            reason=RejectionReason.FOOTER_INVALID,
        )
    return _sha256_text(_canonical_json({"fields": normalized}))


def render_admission_parquet_bytes(
    *,
    fields: Sequence[Mapping[str, Any]],
    rows: Sequence[Mapping[str, Any]] | None = None,
    row_count: int | None = None,
    partition_hints: Mapping[str, Any] | None = None,
    statistics: Mapping[str, Any] | None = None,
    key_value_metadata: Mapping[str, Any] | None = None,
) -> bytes:
    """Render a PAR1-framed admission envelope without pyarrow/duckdb.

    Layout: ``PAR1`` + body + footer + ``u32le(len(footer))`` + ``PAR1``.
    Body and footer are canonical JSON. Discovery reads only the footer region
    plus a streaming whole-file digest — row materialization is never required.
    """
    field_list = [
        {
            "name": str(f.get("name", "")).strip(),
            "type": str(f.get("type", "bytes")).strip().lower(),
        }
        for f in fields
    ]
    schema_digest = schema_digest_for_fields(field_list)
    material_rows = [dict(r) for r in (rows or ())]
    effective_row_count = (
        int(row_count) if row_count is not None else len(material_rows)
    )
    body_obj = {
        "kind": "ducklake_parquet_admission_body",
        "schema_digest": schema_digest,
        "rows": material_rows,
    }
    body = _canonical_json_bytes(body_obj)
    footer_obj: dict[str, Any] = {
        "format": _ADMISSION_FOOTER_FORMAT,
        "row_count": effective_row_count,
        "num_row_groups": 1 if effective_row_count else 0,
        "schema": {"fields": field_list, "schema_digest": schema_digest},
        "schema_digest": schema_digest,
        "body_digest": _sha256_bytes(body),
        "partition_hints": dict(partition_hints or {}),
        "statistics": dict(statistics or {}),
        "key_value_metadata": dict(key_value_metadata or {}),
        "column_count": len(field_list),
    }
    footer = _canonical_json_bytes(footer_obj)
    out = bytearray()
    out.extend(PARQUET_MAGIC)
    out.extend(body)
    out.extend(footer)
    out.extend(struct.pack("<I", len(footer)))
    out.extend(PARQUET_MAGIC)
    return bytes(out)


def write_admission_parquet(
    path: str | os.PathLike[str] | Path,
    *,
    fields: Sequence[Mapping[str, Any]],
    rows: Sequence[Mapping[str, Any]] | None = None,
    row_count: int | None = None,
    partition_hints: Mapping[str, Any] | None = None,
    statistics: Mapping[str, Any] | None = None,
    key_value_metadata: Mapping[str, Any] | None = None,
) -> Path:
    """Write :func:`render_admission_parquet_bytes` to *path*."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = render_admission_parquet_bytes(
        fields=fields,
        rows=rows,
        row_count=row_count,
        partition_hints=partition_hints,
        statistics=statistics,
        key_value_metadata=key_value_metadata,
    )
    target.write_bytes(payload)
    return target


# ---------------------------------------------------------------------------
# Bounded footer reader
# ---------------------------------------------------------------------------


def _read_bounded_footer(
    path: Path,
    *,
    max_footer_bytes: int = DEFAULT_MAX_FOOTER_BYTES,
) -> tuple[bytes, int, bool, bool]:
    """Return ``(footer_bytes, footer_length, magic_head_ok, magic_tail_ok)``.

    Only the trailing footer region is loaded — never the row-group body.
    """
    data_size = path.stat().st_size
    if data_size < 8:
        raise ParquetDiscoveryError(
            f"parquet file too small: {data_size} bytes",
            reason=RejectionReason.TOO_SMALL,
            details={"path": str(path), "byte_size": data_size},
        )
    with path.open("rb") as handle:
        head = handle.read(4)
        magic_head_ok = head == PARQUET_MAGIC
        handle.seek(-8, os.SEEK_END)
        footer_len_bytes = handle.read(4)
        tail_magic = handle.read(4)
        magic_tail_ok = tail_magic == PARQUET_MAGIC
        if not magic_tail_ok:
            raise ParquetDiscoveryError(
                "parquet footer magic missing",
                reason=RejectionReason.NOT_PARQUET,
                details={"path": str(path), "tail_magic": tail_magic.hex()},
            )
        footer_len = struct.unpack("<I", footer_len_bytes)[0]
        if footer_len <= 0:
            raise ParquetDiscoveryError(
                f"invalid parquet footer length {footer_len}",
                reason=RejectionReason.FOOTER_INVALID,
                details={"path": str(path)},
            )
        if footer_len > max_footer_bytes:
            raise ParquetDiscoveryError(
                f"footer length {footer_len} exceeds bound {max_footer_bytes}",
                reason=RejectionReason.FOOTER_UNBOUNDED,
                details={
                    "path": str(path),
                    "footer_length": footer_len,
                    "max_footer_bytes": max_footer_bytes,
                },
            )
        if footer_len > data_size - 8:
            raise ParquetDiscoveryError(
                f"footer length {footer_len} exceeds file size {data_size}",
                reason=RejectionReason.FOOTER_INVALID,
                details={"path": str(path)},
            )
        handle.seek(-(8 + footer_len), os.SEEK_END)
        footer = handle.read(footer_len)
    if len(footer) != footer_len:
        raise ParquetDiscoveryError(
            "short footer read",
            reason=RejectionReason.FOOTER_INVALID,
            details={"path": str(path)},
        )
    if not magic_head_ok:
        raise ParquetDiscoveryError(
            "parquet header magic missing",
            reason=RejectionReason.NOT_PARQUET,
            details={"path": str(path), "head_magic": head.hex()},
        )
    return footer, footer_len, magic_head_ok, magic_tail_ok


def _parse_footer_metadata(
    footer: bytes,
    *,
    footer_length: int,
    magic_head_ok: bool,
    magic_tail_ok: bool,
    max_footer_bytes: int,
) -> tuple[FooterMetadata, SchemaIdentity, dict[str, Any]]:
    """Parse bounded footer into identity + optional structured extras."""
    footer_digest = _sha256_bytes(footer)
    extras: dict[str, Any] = {}
    schema = SchemaIdentity(schema_digest="")
    footer_format = "opaque"

    # Prefer JSON footers (admission envelope / control-plane envelope).
    try:
        text = footer.decode("utf-8")
        payload = json.loads(text)
    except (UnicodeDecodeError, json.JSONDecodeError):
        payload = None

    if isinstance(payload, dict):
        fmt = str(payload.get("format") or "")
        if fmt in {_ADMISSION_FOOTER_FORMAT, _ENVELOPE_FOOTER_FORMAT}:
            footer_format = fmt
            extras["row_count"] = int(payload.get("row_count") or 0)
            extras["num_row_groups"] = int(payload.get("num_row_groups") or 0)
            extras["column_count"] = int(payload.get("column_count") or 0)
            extras["partition_hints"] = dict(payload.get("partition_hints") or {})
            extras["statistics"] = dict(payload.get("statistics") or {})
            extras["key_value_metadata"] = dict(
                payload.get("key_value_metadata") or {}
            )
            schema_block = payload.get("schema") or {}
            fields_raw = []
            if isinstance(schema_block, Mapping):
                fields_raw = list(schema_block.get("fields") or [])
                digest = str(
                    schema_block.get("schema_digest")
                    or payload.get("schema_digest")
                    or ""
                )
            else:
                digest = str(payload.get("schema_digest") or "")
            field_tuples: list[dict[str, str]] = []
            for item in fields_raw:
                if not isinstance(item, Mapping):
                    continue
                name = str(item.get("name") or "").strip()
                typ = str(item.get("type") or "bytes").strip().lower()
                if name:
                    field_tuples.append({"name": name, "type": typ})
            if not digest and field_tuples:
                digest = schema_digest_for_fields(field_tuples)
            if digest:
                schema = SchemaIdentity(
                    schema_digest=_normalize_digest(digest),
                    fields=tuple(MappingProxyType(f) for f in field_tuples),
                    field_count=len(field_tuples),
                )
            if not extras["column_count"] and field_tuples:
                extras["column_count"] = len(field_tuples)

    meta = FooterMetadata(
        footer_length=footer_length,
        footer_digest=footer_digest,
        magic_head_ok=magic_head_ok,
        magic_tail_ok=magic_tail_ok,
        footer_format=footer_format,
        max_footer_bytes=max_footer_bytes,
    )
    return meta, schema, extras


# ---------------------------------------------------------------------------
# Discovery evidence
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DiscoveryEvidence:
    """Immutable discovery evidence for one Parquet source."""

    SCHEMA: ClassVar[str] = DISCOVERY_EVIDENCE_SCHEMA

    canonical_uri: str
    content_digest: str
    content_cid: str
    byte_size: int
    footer: FooterMetadata
    schema: SchemaIdentity
    statistics: Statistics
    object_generation: ObjectGenerationIdentity = field(
        default_factory=ObjectGenerationIdentity
    )
    partition_hints: Mapping[str, Any] = field(default_factory=dict)
    provenance: Provenance | None = None
    policy: PolicyClassification | None = None
    local_path: str = ""
    discovered_at: str = ""
    implementation_generation: str = _IMPLEMENTATION_GENERATION

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "canonical_uri",
            _require_nonempty(self.canonical_uri, field_name="canonical_uri"),
        )
        object.__setattr__(
            self, "content_digest", _normalize_digest(self.content_digest)
        )
        object.__setattr__(
            self, "partition_hints", MappingProxyType(dict(self.partition_hints or {}))
        )
        if not self.discovered_at:
            object.__setattr__(self, "discovered_at", _utc_iso())

    def content_identity(self) -> ContentIdentity:
        return ContentIdentity(
            content_digest=self.content_digest,
            content_cid=self.content_cid,
            media_type="parquet",
        )

    def identity_fingerprint(self) -> str:
        """Stable fingerprint of all identity evidence used at revalidation."""
        body = {
            "canonical_uri": self.canonical_uri,
            "content_digest": self.content_digest,
            "content_cid": self.content_cid,
            "byte_size": self.byte_size,
            "footer_digest": self.footer.footer_digest,
            "footer_length": self.footer.footer_length,
            "schema_digest": self.schema.schema_digest,
            "object_generation": dict(self.object_generation.as_mapping()),
        }
        return _sha256_text(_canonical_json(body))

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "schema": DISCOVERY_EVIDENCE_SCHEMA,
                "canonical_uri": self.canonical_uri,
                "content_digest": self.content_digest,
                "content_cid": self.content_cid,
                "byte_size": self.byte_size,
                "footer": dict(self.footer.as_mapping()),
                "schema_identity": dict(self.schema.as_mapping()),
                "statistics": dict(self.statistics.as_mapping()),
                "object_generation": dict(self.object_generation.as_mapping()),
                "partition_hints": dict(self.partition_hints),
                "provenance": (
                    dict(self.provenance.as_mapping()) if self.provenance else None
                ),
                "policy": dict(self.policy.as_mapping()) if self.policy else None,
                "local_path": self.local_path,
                "discovered_at": self.discovered_at,
                "identity_fingerprint": self.identity_fingerprint(),
                "implementation_generation": self.implementation_generation,
            }
        )


def discover_parquet_file(
    path: str | os.PathLike[str] | Path,
    *,
    allowed_roots: Sequence[str | os.PathLike[str] | Path] | None = None,
    reject_symlinks: bool = True,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    max_footer_bytes: int = DEFAULT_MAX_FOOTER_BYTES,
    object_generation: ObjectGenerationIdentity | None = None,
    content_cid: str = "",
    provenance: Provenance | None = None,
    policy: PolicyClassification | None = None,
    partition_hints: Mapping[str, Any] | None = None,
    canonical_uri: str | None = None,
) -> DiscoveryEvidence:
    """Stream whole-file digest + bounded footer metadata for one Parquet path.

    Never materializes row groups or loads the dataset into memory. Peak buffer
    is ``max(chunk_size, footer_length)`` with ``footer_length`` hard-capped.
    """
    safe = assert_safe_source_path(
        path,
        allowed_roots=allowed_roots,
        reject_symlinks=reject_symlinks,
    )
    if not safe.is_file():
        raise ParquetDiscoveryError(
            f"source is not a regular file: {safe}",
            reason=RejectionReason.UNSAFE_PATH,
            details={"path": str(safe)},
        )

    footer_bytes, footer_len, magic_head_ok, magic_tail_ok = _read_bounded_footer(
        safe, max_footer_bytes=max_footer_bytes
    )
    footer_meta, schema, extras = _parse_footer_metadata(
        footer_bytes,
        footer_length=footer_len,
        magic_head_ok=magic_head_ok,
        magic_tail_ok=magic_tail_ok,
        max_footer_bytes=max_footer_bytes,
    )

    # Stream whole-file digest without retaining file bytes.
    byte_size, content_digest = stream_file_digest(safe, chunk_size=chunk_size)

    stats = Statistics(
        byte_size=byte_size,
        row_count=int(extras.get("row_count") or 0),
        num_row_groups=int(extras.get("num_row_groups") or 0),
        column_count=int(
            extras.get("column_count") or schema.field_count or 0
        ),
    )
    hints = dict(partition_hints or extras.get("partition_hints") or {})
    uri = canonical_uri or canonical_uri_for_path(safe)
    return DiscoveryEvidence(
        canonical_uri=uri,
        content_digest=content_digest,
        content_cid=str(content_cid or "").strip(),
        byte_size=byte_size,
        footer=footer_meta,
        schema=schema,
        statistics=stats,
        object_generation=object_generation or ObjectGenerationIdentity(),
        partition_hints=hints,
        provenance=provenance,
        policy=policy,
        local_path=str(safe),
    )


def iter_discover_parquet(
    roots: Sequence[str | os.PathLike[str] | Path],
    *,
    allowed_roots: Sequence[str | os.PathLike[str] | Path] | None = None,
    reject_symlinks: bool = True,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    max_footer_bytes: int = DEFAULT_MAX_FOOTER_BYTES,
    suffix: str = ".parquet",
    on_error: Callable[[Path, AdmissionError], None] | None = None,
) -> Iterator[DiscoveryEvidence]:
    """Yield discovery evidence for every ``*suffix`` file under *roots*.

    Directory walks are deterministic (sorted by path bytes). Symlink
    directories are not followed. Failures are re-raised unless *on_error*
    is provided (then the path is skipped after the callback).
    """
    allow = list(allowed_roots) if allowed_roots is not None else list(roots)
    resolved_roots = sorted(
        (Path(r).resolve(strict=False) for r in roots),
        key=lambda p: str(p).encode("utf-8"),
    )
    for root in resolved_roots:
        if not root.exists():
            continue
        if root.is_file():
            candidates = [root]
        else:
            candidates = sorted(
                (
                    p
                    for p in root.rglob(f"*{suffix}")
                    if p.is_file() and not p.is_symlink()
                ),
                key=lambda p: str(p).encode("utf-8"),
            )
        for candidate in candidates:
            try:
                yield discover_parquet_file(
                    candidate,
                    allowed_roots=allow,
                    reject_symlinks=reject_symlinks,
                    chunk_size=chunk_size,
                    max_footer_bytes=max_footer_bytes,
                )
            except AdmissionError as exc:
                if on_error is not None:
                    on_error(candidate, exc)
                    continue
                raise


# ---------------------------------------------------------------------------
# Revalidation immediately before copy / register
# ---------------------------------------------------------------------------


def revalidate_before_copy_register(
    evidence: DiscoveryEvidence,
    *,
    allowed_roots: Sequence[str | os.PathLike[str] | Path] | None = None,
    reject_symlinks: bool = True,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    max_footer_bytes: int = DEFAULT_MAX_FOOTER_BYTES,
    observed_object_generation: ObjectGenerationIdentity | None = None,
    source_path: str | os.PathLike[str] | Path | None = None,
) -> DiscoveryEvidence:
    """Recheck source identity immediately before copy and registration.

    Re-streams the whole-file digest and bounded footer. Any replacement,
    footer drift, or object-generation/ETag drift fails closed.
    """
    if not isinstance(evidence, DiscoveryEvidence):
        raise AdmissionError(
            "evidence must be DiscoveryEvidence",
            reason=RejectionReason.MISSING_IDENTITY,
        )
    path = Path(source_path or evidence.local_path)
    if not path.as_posix():
        raise AdmissionError(
            "revalidation requires a local_path or source_path",
            reason=RejectionReason.MISSING_IDENTITY,
        )

    fresh = discover_parquet_file(
        path,
        allowed_roots=allowed_roots,
        reject_symlinks=reject_symlinks,
        chunk_size=chunk_size,
        max_footer_bytes=max_footer_bytes,
        object_generation=observed_object_generation or evidence.object_generation,
        content_cid=evidence.content_cid,
        provenance=evidence.provenance,
        policy=evidence.policy,
        partition_hints=dict(evidence.partition_hints),
        canonical_uri=evidence.canonical_uri,
    )

    if fresh.content_digest != evidence.content_digest:
        raise ReplacementError(
            "whole-file digest changed between discovery and revalidation",
            reason=RejectionReason.REPLACEMENT,
            details={
                "expected": evidence.content_digest,
                "observed": fresh.content_digest,
                "path": str(path),
            },
        )
    if fresh.byte_size != evidence.byte_size:
        raise ReplacementError(
            "byte size changed between discovery and revalidation",
            reason=RejectionReason.REPLACEMENT,
            details={
                "expected": evidence.byte_size,
                "observed": fresh.byte_size,
                "path": str(path),
            },
        )
    if fresh.footer.footer_digest != evidence.footer.footer_digest:
        raise FooterDriftError(
            "footer digest drifted before copy/register",
            reason=RejectionReason.FOOTER_DRIFT,
            details={
                "expected": evidence.footer.footer_digest,
                "observed": fresh.footer.footer_digest,
                "path": str(path),
            },
        )
    if fresh.footer.footer_length != evidence.footer.footer_length:
        raise FooterDriftError(
            "footer length drifted before copy/register",
            reason=RejectionReason.FOOTER_DRIFT,
            details={
                "expected": evidence.footer.footer_length,
                "observed": fresh.footer.footer_length,
            },
        )
    if (
        evidence.schema.schema_digest
        and fresh.schema.schema_digest
        and fresh.schema.schema_digest != evidence.schema.schema_digest
    ):
        raise FooterDriftError(
            "schema identity drifted before copy/register",
            reason=RejectionReason.FOOTER_DRIFT,
            details={
                "expected": evidence.schema.schema_digest,
                "observed": fresh.schema.schema_digest,
            },
        )

    expected_ogen = evidence.object_generation
    observed_ogen = observed_object_generation or fresh.object_generation
    if expected_ogen.is_bound() and not expected_ogen.matches(observed_ogen):
        raise ObjectGenerationDriftError(
            "object generation/version/ETag drifted before copy/register",
            reason=RejectionReason.OBJECT_GENERATION_DRIFT,
            details={
                "expected": dict(expected_ogen.as_mapping()),
                "observed": dict(observed_ogen.as_mapping()),
            },
        )

    return fresh


# ---------------------------------------------------------------------------
# Decision receipt + ledger
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AdmissionDecisionReceipt:
    """Immutable admission decision receipt (never mutates DuckLake)."""

    SCHEMA: ClassVar[str] = ADMISSION_DECISION_RECEIPT_SCHEMA

    receipt_id: str
    outcome: DecisionOutcome
    evidence: DiscoveryEvidence
    ownership: SourceOwnership
    copy_required: bool
    policy_decision: PolicyDecision | None = None
    rejection_reason: RejectionReason | None = None
    rejection_message: str = ""
    dataset_id: str = ""
    decided_at: str = ""
    revalidated: bool = False
    revalidation_fingerprint: str = ""
    implementation_generation: str = _IMPLEMENTATION_GENERATION

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "receipt_id",
            _require_nonempty(self.receipt_id, field_name="receipt_id"),
        )
        if not isinstance(self.outcome, DecisionOutcome):
            object.__setattr__(self, "outcome", DecisionOutcome(str(self.outcome)))
        object.__setattr__(self, "copy_required", bool(self.copy_required))
        if not self.decided_at:
            object.__setattr__(self, "decided_at", _utc_iso())

    @property
    def admitted(self) -> bool:
        return self.outcome is DecisionOutcome.ADMITTED

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "schema": ADMISSION_DECISION_RECEIPT_SCHEMA,
                "receipt_id": self.receipt_id,
                "outcome": self.outcome.value,
                "admitted": self.admitted,
                "evidence": dict(self.evidence.as_mapping()),
                "ownership": dict(self.ownership.as_mapping()),
                "copy_required": self.copy_required,
                "policy_decision": (
                    dict(self.policy_decision.as_mapping())
                    if self.policy_decision
                    else None
                ),
                "rejection_reason": (
                    self.rejection_reason.value if self.rejection_reason else None
                ),
                "rejection_message": self.rejection_message,
                "dataset_id": self.dataset_id,
                "decided_at": self.decided_at,
                "revalidated": self.revalidated,
                "revalidation_fingerprint": self.revalidation_fingerprint,
                "implementation_generation": self.implementation_generation,
                "receipt_digest": self.receipt_digest(),
            }
        )

    def receipt_digest(self) -> str:
        body = {
            "receipt_id": self.receipt_id,
            "outcome": self.outcome.value,
            "evidence_fingerprint": self.evidence.identity_fingerprint(),
            "ownership": dict(self.ownership.as_mapping()),
            "copy_required": self.copy_required,
            "policy_decision": (
                dict(self.policy_decision.as_mapping())
                if self.policy_decision
                else None
            ),
            "rejection_reason": (
                self.rejection_reason.value if self.rejection_reason else None
            ),
            "dataset_id": self.dataset_id,
            "decided_at": self.decided_at,
            "revalidated": self.revalidated,
            "revalidation_fingerprint": self.revalidation_fingerprint,
        }
        return _sha256_text(_canonical_json(body))


class AdmissionLedger:
    """In-memory fail-closed ledger of admitted digests and schema contracts.

    Production owners persist equivalent rows into the companion registry
    (``lake_sources`` / ``lake_schema_contracts``). This ledger is sufficient
    for hermetic admission decisions and duplicate/schema-conflict checks.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._by_digest: dict[str, AdmissionDecisionReceipt] = {}
        self._schema_by_dataset: dict[str, str] = {}
        self._receipts: dict[str, AdmissionDecisionReceipt] = {}

    def get_by_digest(self, content_digest: str) -> AdmissionDecisionReceipt | None:
        with self._lock:
            return self._by_digest.get(_normalize_digest(content_digest))

    def schema_for_dataset(self, dataset_id: str) -> str | None:
        with self._lock:
            return self._schema_by_dataset.get(dataset_id)

    def record(self, receipt: AdmissionDecisionReceipt) -> None:
        if not receipt.admitted:
            with self._lock:
                self._receipts[receipt.receipt_id] = receipt
            return
        digest = receipt.evidence.content_digest
        with self._lock:
            existing = self._by_digest.get(digest)
            if existing is not None and existing.receipt_id != receipt.receipt_id:
                raise DuplicateSourceError(
                    f"content already admitted under receipt {existing.receipt_id}",
                    reason=RejectionReason.DUPLICATE,
                    details={
                        "content_digest": digest,
                        "existing_receipt_id": existing.receipt_id,
                    },
                )
            dataset_id = receipt.dataset_id
            schema_digest = receipt.evidence.schema.schema_digest
            if dataset_id and schema_digest:
                prior = self._schema_by_dataset.get(dataset_id)
                if prior and prior != schema_digest:
                    raise SchemaConflictError(
                        f"schema conflict for dataset {dataset_id}",
                        reason=RejectionReason.SCHEMA_CONFLICT,
                        details={
                            "dataset_id": dataset_id,
                            "expected_schema_digest": prior,
                            "observed_schema_digest": schema_digest,
                        },
                    )
                self._schema_by_dataset[dataset_id] = schema_digest
            self._by_digest[digest] = receipt
            self._receipts[receipt.receipt_id] = receipt

    def assert_admissible(
        self,
        evidence: DiscoveryEvidence,
        *,
        dataset_id: str = "",
    ) -> None:
        digest = evidence.content_digest
        with self._lock:
            if digest in self._by_digest:
                existing = self._by_digest[digest]
                raise DuplicateSourceError(
                    f"duplicate content digest already admitted: {digest}",
                    reason=RejectionReason.DUPLICATE,
                    details={
                        "content_digest": digest,
                        "existing_receipt_id": existing.receipt_id,
                    },
                )
            if dataset_id and evidence.schema.schema_digest:
                prior = self._schema_by_dataset.get(dataset_id)
                if prior and prior != evidence.schema.schema_digest:
                    raise SchemaConflictError(
                        f"schema conflict for dataset {dataset_id}",
                        reason=RejectionReason.SCHEMA_CONFLICT,
                        details={
                            "dataset_id": dataset_id,
                            "expected_schema_digest": prior,
                            "observed_schema_digest": evidence.schema.schema_digest,
                        },
                    )


class AdmissionService:
    """Streaming Parquet discovery + fail-closed admission decision service.

    The service never mutates DuckLake catalogs. It only emits immutable
    decision receipts after discovery, policy checks, duplicate/schema gates,
    and immediate pre-copy/register revalidation.
    """

    def __init__(
        self,
        *,
        owner_id: str,
        shard_id: str = "",
        ledger: AdmissionLedger | None = None,
        allowed_roots: Sequence[str | os.PathLike[str] | Path] | None = None,
        default_ownership_kind: SourceOwnershipKind = (
            SourceOwnershipKind.EXTERNAL_UNMANAGED
        ),
        chunk_size: int = DEFAULT_CHUNK_SIZE,
        max_footer_bytes: int = DEFAULT_MAX_FOOTER_BYTES,
    ) -> None:
        self.owner_id = _require_nonempty(owner_id, field_name="owner_id")
        self.shard_id = str(shard_id or "")
        self.ledger = ledger or AdmissionLedger()
        self.allowed_roots = tuple(Path(r) for r in (allowed_roots or ()))
        self.default_ownership_kind = default_ownership_kind
        self.chunk_size = chunk_size
        self.max_footer_bytes = max_footer_bytes
        self._lock = threading.RLock()

    def discover(
        self,
        path: str | os.PathLike[str] | Path,
        **kwargs: Any,
    ) -> DiscoveryEvidence:
        roots = kwargs.pop("allowed_roots", None)
        return discover_parquet_file(
            path,
            allowed_roots=roots if roots is not None else self.allowed_roots or None,
            chunk_size=kwargs.pop("chunk_size", self.chunk_size),
            max_footer_bytes=kwargs.pop("max_footer_bytes", self.max_footer_bytes),
            **kwargs,
        )

    def _resolve_policy(
        self,
        evidence: DiscoveryEvidence,
        *,
        policy: PolicyClassification | None,
        policy_decision: PolicyDecision | None,
    ) -> tuple[PolicyClassification, PolicyDecision | None]:
        effective = policy or evidence.policy or PolicyClassification(
            policy_class=PolicyClass.INTERNAL
        )
        if effective.policy_class.requires_explicit_decision:
            if policy_decision is None:
                raise PolicyRequiredError(
                    "sensitive/restricted sources require an explicit "
                    "policy decision",
                    reason=RejectionReason.POLICY_REQUIRED,
                    details={
                        "policy_class": effective.policy_class.value,
                        "canonical_uri": evidence.canonical_uri,
                    },
                )
            if PolicyClass.parse(policy_decision.policy_class) != effective.policy_class:
                raise PolicyRequiredError(
                    "policy decision class does not match source classification",
                    reason=RejectionReason.POLICY_REQUIRED,
                    details={
                        "source_class": effective.policy_class.value,
                        "decision_class": policy_decision.policy_class.value
                        if isinstance(policy_decision.policy_class, PolicyClass)
                        else str(policy_decision.policy_class),
                    },
                )
            if not policy_decision.allowed:
                raise PolicyRequiredError(
                    "policy decision denied admission",
                    reason=RejectionReason.POLICY_DENIED,
                    details={
                        "decision_id": policy_decision.decision_id,
                        "reason": policy_decision.reason,
                    },
                )
        return effective, policy_decision

    def admit(
        self,
        path: str | os.PathLike[str] | Path,
        *,
        provenance: Provenance,
        policy: PolicyClassification | None = None,
        policy_decision: PolicyDecision | None = None,
        ownership_kind: SourceOwnershipKind | None = None,
        copy_required: bool | None = None,
        object_generation: ObjectGenerationIdentity | None = None,
        observed_object_generation: ObjectGenerationIdentity | None = None,
        content_cid: str = "",
        dataset_id: str = "",
        partition_hints: Mapping[str, Any] | None = None,
        receipt_id: str | None = None,
        revalidate: bool = True,
        reject_symlinks: bool = True,
    ) -> AdmissionDecisionReceipt:
        """Discover, gate, revalidate, and emit an immutable decision receipt.

        On success the receipt records source ownership and whether a
        lifecycle-managed copy is required before registration. Nothing is
        written to DuckLake.
        """
        with self._lock:
            return self._admit_locked(
                path,
                provenance=provenance,
                policy=policy,
                policy_decision=policy_decision,
                ownership_kind=ownership_kind,
                copy_required=copy_required,
                object_generation=object_generation,
                observed_object_generation=observed_object_generation,
                content_cid=content_cid,
                dataset_id=dataset_id,
                partition_hints=partition_hints,
                receipt_id=receipt_id,
                revalidate=revalidate,
                reject_symlinks=reject_symlinks,
            )

    def _admit_locked(
        self,
        path: str | os.PathLike[str] | Path,
        *,
        provenance: Provenance,
        policy: PolicyClassification | None,
        policy_decision: PolicyDecision | None,
        ownership_kind: SourceOwnershipKind | None,
        copy_required: bool | None,
        object_generation: ObjectGenerationIdentity | None,
        observed_object_generation: ObjectGenerationIdentity | None,
        content_cid: str,
        dataset_id: str,
        partition_hints: Mapping[str, Any] | None,
        receipt_id: str | None,
        revalidate: bool,
        reject_symlinks: bool,
    ) -> AdmissionDecisionReceipt:
        kind = ownership_kind or self.default_ownership_kind
        require_copy = (
            default_copy_required(kind) if copy_required is None else bool(copy_required)
        )
        # Lifecycle-managed sources still cannot skip copy when the caller
        # explicitly marks external unmanaged ownership.
        if kind is not SourceOwnershipKind.LIFECYCLE_MANAGED:
            require_copy = True

        ownership = SourceOwnership(
            owner_id=self.owner_id,
            ownership_kind=kind,
            copy_required=require_copy,
            tenant=provenance.tenant,
            shard_id=self.shard_id,
        )
        rid = receipt_id or f"adm-{uuid.uuid4().hex}"

        try:
            evidence = self.discover(
                path,
                reject_symlinks=reject_symlinks,
                object_generation=object_generation,
                content_cid=content_cid,
                provenance=provenance,
                policy=policy,
                partition_hints=partition_hints,
            )
            effective_policy, bound_decision = self._resolve_policy(
                evidence, policy=policy, policy_decision=policy_decision
            )
            # Attach effective policy onto evidence for the receipt.
            evidence = DiscoveryEvidence(
                canonical_uri=evidence.canonical_uri,
                content_digest=evidence.content_digest,
                content_cid=evidence.content_cid,
                byte_size=evidence.byte_size,
                footer=evidence.footer,
                schema=evidence.schema,
                statistics=evidence.statistics,
                object_generation=evidence.object_generation,
                partition_hints=dict(evidence.partition_hints),
                provenance=provenance,
                policy=effective_policy,
                local_path=evidence.local_path,
                discovered_at=evidence.discovered_at,
            )

            self.ledger.assert_admissible(evidence, dataset_id=dataset_id)

            revalidated = False
            revalidation_fingerprint = ""
            if revalidate:
                fresh = revalidate_before_copy_register(
                    evidence,
                    allowed_roots=self.allowed_roots or None,
                    reject_symlinks=reject_symlinks,
                    chunk_size=self.chunk_size,
                    max_footer_bytes=self.max_footer_bytes,
                    observed_object_generation=(
                        observed_object_generation or object_generation
                    ),
                    source_path=evidence.local_path,
                )
                revalidated = True
                revalidation_fingerprint = fresh.identity_fingerprint()
                # Prefer revalidated footer/stats while keeping provenance.
                evidence = DiscoveryEvidence(
                    canonical_uri=fresh.canonical_uri,
                    content_digest=fresh.content_digest,
                    content_cid=fresh.content_cid,
                    byte_size=fresh.byte_size,
                    footer=fresh.footer,
                    schema=fresh.schema,
                    statistics=fresh.statistics,
                    object_generation=fresh.object_generation,
                    partition_hints=dict(fresh.partition_hints),
                    provenance=provenance,
                    policy=effective_policy,
                    local_path=fresh.local_path,
                    discovered_at=evidence.discovered_at,
                )

            # Validate content identity shape (raises LakeIdentityError).
            try:
                evidence.content_identity()
            except LakeIdentityError as exc:
                raise AdmissionError(
                    f"invalid content identity: {exc}",
                    reason=RejectionReason.MISSING_IDENTITY,
                ) from exc

            receipt = AdmissionDecisionReceipt(
                receipt_id=rid,
                outcome=DecisionOutcome.ADMITTED,
                evidence=evidence,
                ownership=ownership,
                copy_required=require_copy,
                policy_decision=bound_decision,
                dataset_id=dataset_id,
                revalidated=revalidated,
                revalidation_fingerprint=revalidation_fingerprint,
            )
            self.ledger.record(receipt)
            return receipt
        except AdmissionError:
            raise

    def admit_or_receipt(
        self,
        path: str | os.PathLike[str] | Path,
        **kwargs: Any,
    ) -> AdmissionDecisionReceipt:
        """Like :meth:`admit` but converts fail-closed errors into reject receipts.

        Structural path errors (symlink/traversal) still raise so callers can
        distinguish unsafe path handling from content-level rejects when
        desired; pass ``capture_path_errors=True`` to capture them too.
        """
        capture_path_errors = bool(kwargs.pop("capture_path_errors", False))
        provenance = kwargs.get("provenance")
        if not isinstance(provenance, Provenance):
            raise AdmissionError(
                "provenance is required",
                reason=RejectionReason.MISSING_IDENTITY,
            )
        kind = kwargs.get("ownership_kind") or self.default_ownership_kind
        require_copy = kwargs.get("copy_required")
        if require_copy is None:
            require_copy = default_copy_required(kind)
        if kind is not SourceOwnershipKind.LIFECYCLE_MANAGED:
            require_copy = True
        ownership = SourceOwnership(
            owner_id=self.owner_id,
            ownership_kind=kind,
            copy_required=bool(require_copy),
            tenant=provenance.tenant,
            shard_id=self.shard_id,
        )
        rid = kwargs.get("receipt_id") or f"adm-{uuid.uuid4().hex}"
        try:
            return self.admit(path, **kwargs)
        except (SymlinkRejectedError, PathTraversalError) as exc:
            if not capture_path_errors:
                raise
            return self._reject_receipt(
                rid=rid,
                path=path,
                ownership=ownership,
                provenance=provenance,
                exc=exc,
                dataset_id=str(kwargs.get("dataset_id") or ""),
                policy=kwargs.get("policy"),
                policy_decision=kwargs.get("policy_decision"),
                object_generation=kwargs.get("object_generation"),
            )
        except AdmissionError as exc:
            return self._reject_receipt(
                rid=rid,
                path=path,
                ownership=ownership,
                provenance=provenance,
                exc=exc,
                dataset_id=str(kwargs.get("dataset_id") or ""),
                policy=kwargs.get("policy"),
                policy_decision=kwargs.get("policy_decision"),
                object_generation=kwargs.get("object_generation"),
            )

    def _reject_receipt(
        self,
        *,
        rid: str,
        path: str | os.PathLike[str] | Path,
        ownership: SourceOwnership,
        provenance: Provenance,
        exc: AdmissionError,
        dataset_id: str,
        policy: PolicyClassification | None,
        policy_decision: PolicyDecision | None,
        object_generation: ObjectGenerationIdentity | None,
    ) -> AdmissionDecisionReceipt:
        # Best-effort placeholder evidence when discovery itself failed.
        placeholder_digest = _sha256_text(f"rejected:{path}:{exc}")
        empty_footer = FooterMetadata(
            footer_length=0,
            footer_digest=placeholder_digest,
            magic_head_ok=False,
            magic_tail_ok=False,
            footer_format="none",
        )
        try:
            uri = canonical_uri_for_path(path)
            local = str(Path(path).resolve(strict=False))
        except OSError:
            uri = f"file://{path}"
            local = str(path)
        evidence = DiscoveryEvidence(
            canonical_uri=uri,
            content_digest=placeholder_digest,
            content_cid="",
            byte_size=0,
            footer=empty_footer,
            schema=SchemaIdentity(schema_digest=""),
            statistics=Statistics(byte_size=0),
            object_generation=object_generation or ObjectGenerationIdentity(),
            provenance=provenance,
            policy=policy,
            local_path=local,
        )
        receipt = AdmissionDecisionReceipt(
            receipt_id=rid,
            outcome=DecisionOutcome.REJECTED,
            evidence=evidence,
            ownership=ownership,
            copy_required=ownership.copy_required,
            policy_decision=policy_decision,
            rejection_reason=exc.reason or RejectionReason.REVALIDATION_FAILED,
            rejection_message=str(exc),
            dataset_id=dataset_id,
            revalidated=False,
        )
        self.ledger.record(receipt)
        return receipt


def admit_parquet_source(
    path: str | os.PathLike[str] | Path,
    *,
    owner_id: str,
    provenance: Provenance,
    shard_id: str = "",
    **kwargs: Any,
) -> AdmissionDecisionReceipt:
    """Module-level convenience wrapper around :class:`AdmissionService.admit`."""
    service = AdmissionService(
        owner_id=owner_id,
        shard_id=shard_id,
        allowed_roots=kwargs.pop("allowed_roots", None),
    )
    return service.admit(path, provenance=provenance, **kwargs)
