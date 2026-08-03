"""Immutable, versioned graph revision manifests (KGP-004).

A revision manifest is the content-addressed control-plane descriptor for one
immutable graph snapshot. Catalog branch heads point at these manifests; stores
and query backends only consume the descriptors declared here.

This module is intentionally free of backend imports (no Parquet, Kubo,
``ipfs_kit_py``, or IPLD codec libraries). Codecs and storage profiles are
closed string enumerations; payload verification is checksum/CID level only.

Contract version: ``kg-revision-manifest/v1``
"""

from __future__ import annotations

import base64
import hashlib
import json
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from types import MappingProxyType
from typing import Any, Final, Iterable, Optional

# ---------------------------------------------------------------------------
# Schema / bounds
# ---------------------------------------------------------------------------

MANIFEST_SCHEMA_VERSION: Final = "kg-revision-manifest/v1"
CANONICAL_JSON_PROFILE: Final = "kg-canonical-json-v1"
IDENTITY_DOMAIN: Final = "kg.revision-manifest"

STORAGE_PROFILES: Final = frozenset({"parquet", "ipfs_ipld", "ipfs_kit", "hybrid"})

CODECS: Final = frozenset(
    {
        "parquet",
        "dag-cbor",
        "car",
        "json",
        "jsonl",
        "arrow-ipc",
        "bloom-v1",
        "btree-v1",
        "faiss",
        "bm25-postings",
        "raw",
    }
)

PARTITION_KINDS: Final = frozenset(
    {
        "nodes",
        "edges",
        "adjacency",
        "properties",
        "documents",
        "vectors",
        "postings",
        "communities",
        "other",
    }
)

INDEX_KINDS: Final = frozenset(
    {
        "btree",
        "hash",
        "bloom",
        "vector",
        "fulltext",
        "type",
        "adjacency",
        "composite",
        "other",
    }
)

CHECKSUM_ALGORITHMS: Final = frozenset({"sha256"})

# Slugs for tenant / graph_id / graph_kind segments (aligned with GraphTarget).
_SLUG_RE = re.compile(r"^[a-z0-9]([a-z0-9_-]{0,62}[a-z0-9])?$")
# Revision / parent / artifact ids and CIDs (catalog id or multiformat CID text).
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
# CIDv0 (base58btc) or CIDv1 multibase (typically base32, prefix ``b``).
_CID_RE = re.compile(
    r"^(?:Qm[1-9A-HJ-NP-Za-km-z]{44}|b[a-z2-7]{50,120}|bagu[a-z2-7]{50,120})$"
)
_ONTOLOGY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$")
_SCHEMA_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$")
_FIELD_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.]{0,63}$")

MAX_PARTITIONS: Final = 4_096
MAX_INDEXES: Final = 1_024
MAX_SHARDS: Final = 65_536
MAX_PATH_LENGTH: Final = 512
MAX_PROVENANCE_KEYS: Final = 64
MAX_PROVENANCE_STRING: Final = 1_024
MAX_INDEX_FIELDS: Final = 32
MAX_NODE_COUNT: Final = 2**63 - 1
MAX_EDGE_COUNT: Final = 2**63 - 1
MAX_BYTES: Final = 2**63 - 1

# Top-level keys required on every serialized manifest.
_REQUIRED_MANIFEST_KEYS: Final = frozenset(
    {
        "manifest_version",
        "tenant",
        "graph_id",
        "revision_id",
        "parent_revision",
        "schema_id",
        "schema_version",
        "ontology_id",
        "ontology_version",
        "graph_kind",
        "storage_profile",
        "codec",
        "counts",
        "partitions",
        "indexes",
        "shards",
        "provenance",
        "checksum",
        "root_cid",
    }
)

# Keys allowed in the deterministic (identity) payload. ``root_cid`` is optional
# and may be derived; when present it is validated against ``checksum``.
_IDENTITY_KEYS: Final = frozenset(
    {
        "manifest_version",
        "tenant",
        "graph_id",
        "revision_id",
        "parent_revision",
        "schema_id",
        "schema_version",
        "ontology_id",
        "ontology_version",
        "graph_kind",
        "storage_profile",
        "codec",
        "counts",
        "partitions",
        "indexes",
        "shards",
        "provenance",
    }
)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class ManifestError(ValueError):
    """Base validation error for revision manifests.

    ``code`` is a stable machine token used by tests and service error mapping.
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class ManifestValidationError(ManifestError):
    """Raised when a manifest or descriptor is malformed."""


class ManifestIntegrityError(ManifestError):
    """Raised when checksums or CIDs disagree with declared values."""


# ---------------------------------------------------------------------------
# Low-level validators / helpers
# ---------------------------------------------------------------------------


def _reject(code: str, message: str) -> None:
    raise ManifestValidationError(code, message)


def _require_str(label: str, value: Any, *, code: str = "NONCANONICAL_VALUE") -> str:
    if not isinstance(value, str):
        _reject(code, f"{label} must be a string")
    if not value or value.strip() != value:
        _reject(code, f"{label} must be non-empty without surrounding whitespace")
    if "\x00" in value:
        _reject(code, f"{label} must not contain NUL")
    return value


def _require_slug(label: str, value: Any) -> str:
    text = _require_str(label, value, code="AMBIGUOUS_ID")
    if not _SLUG_RE.fullmatch(text):
        _reject("AMBIGUOUS_ID", f"{label} failed slug validation: {value!r}")
    return text


def _require_id(label: str, value: Any) -> str:
    text = _require_str(label, value, code="AMBIGUOUS_ID")
    if not _ID_RE.fullmatch(text):
        _reject("AMBIGUOUS_ID", f"{label} is not a stable identifier: {value!r}")
    if "//" in text or text.startswith("/") or text.endswith("/"):
        _reject("AMBIGUOUS_ID", f"{label} is ambiguous or path-like: {value!r}")
    return text


def _require_schema_ref(label: str, value: Any) -> str:
    text = _require_str(label, value, code="AMBIGUOUS_ID")
    if not _SCHEMA_RE.fullmatch(text):
        _reject("AMBIGUOUS_ID", f"{label} is not a valid schema reference: {value!r}")
    return text


def _require_ontology_ref(label: str, value: Any) -> str:
    text = _require_str(label, value, code="AMBIGUOUS_ID")
    if not _ONTOLOGY_RE.fullmatch(text):
        _reject("AMBIGUOUS_ID", f"{label} is not a valid ontology reference: {value!r}")
    return text


def _require_nonneg_int(
    label: str,
    value: Any,
    *,
    maximum: int = MAX_BYTES,
) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        _reject("INVALID_COUNT", f"{label} must be an integer (got {type(value).__name__})")
    if value < 0:
        _reject("INVALID_COUNT", f"{label} must be >= 0 (got {value})")
    if value > maximum:
        _reject("INVALID_COUNT", f"{label} exceeds maximum {maximum}")
    return value


def _require_codec(label: str, value: Any) -> str:
    text = _require_str(label, value, code="NONCANONICAL_VALUE")
    if text not in CODECS:
        _reject("NONCANONICAL_VALUE", f"{label} unknown codec: {text!r}")
    return text


def _require_storage_profile(label: str, value: Any) -> str:
    text = _require_str(label, value, code="NONCANONICAL_VALUE")
    if text not in STORAGE_PROFILES:
        _reject("NONCANONICAL_VALUE", f"{label} unknown storage_profile: {text!r}")
    return text


def _require_sha256_hex(label: str, value: Any) -> str:
    text = _require_str(label, value, code="NONCANONICAL_VALUE")
    if text.startswith("sha256:"):
        text = text[len("sha256:") :]
    if not _SHA256_RE.fullmatch(text):
        _reject(
            "NONCANONICAL_VALUE",
            f"{label} must be 64 lowercase hexadecimal characters",
        )
    return text


def _require_cid(label: str, value: Any) -> str:
    text = _require_str(label, value, code="NONCANONICAL_VALUE")
    if not _CID_RE.fullmatch(text):
        _reject("NONCANONICAL_VALUE", f"{label} is not a recognized CID: {value!r}")
    return text


def _safe_relative_path(label: str, value: Any) -> str:
    """Reject absolute, parent, Windows, and non-normalized POSIX paths."""
    text = _require_str(label, value, code="UNSAFE_PATH")
    if len(text) > MAX_PATH_LENGTH:
        _reject("UNSAFE_PATH", f"{label} exceeds max path length {MAX_PATH_LENGTH}")
    if "\\" in text or "\x00" in text:
        _reject("UNSAFE_PATH", f"{label} must be a POSIX path without backslashes")
    if text.startswith("/") or text.startswith("~"):
        _reject("UNSAFE_PATH", f"{label} must be root-relative (got {value!r})")
    path = PurePosixPath(text)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        _reject(
            "UNSAFE_PATH",
            f"{label} must be normalized root-relative without '.'/'..' segments",
        )
    normalized = path.as_posix()
    if normalized != text:
        _reject("UNSAFE_PATH", f"{label} must be canonical POSIX text (got {value!r})")
    return normalized


def _optional_path(label: str, value: Any) -> Optional[str]:
    if value is None:
        return None
    return _safe_relative_path(label, value)


def _optional_cid(label: str, value: Any) -> Optional[str]:
    if value is None:
        return None
    return _require_cid(label, value)


def _optional_id(label: str, value: Any) -> Optional[str]:
    if value is None:
        return None
    return _require_id(label, value)


def _field_names(value: Any, *, label: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Sequence):
        _reject("NONCANONICAL_VALUE", f"{label} must be a sequence of field names")
    names: list[str] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, str) or not _FIELD_NAME_RE.fullmatch(item):
            _reject("NONCANONICAL_VALUE", f"{label} contains invalid field name {item!r}")
        if item in seen:
            _reject("AMBIGUOUS_ID", f"{label} contains duplicate field {item!r}")
        seen.add(item)
        names.append(item)
    if len(names) > MAX_INDEX_FIELDS:
        _reject("NONCANONICAL_VALUE", f"{label} exceeds max fields {MAX_INDEX_FIELDS}")
    # Canonical order: lexicographic unique names.
    ordered = tuple(sorted(names))
    if ordered != tuple(names):
        _reject("NONCANONICAL_VALUE", f"{label} must be lexicographically sorted")
    return ordered


def _freeze_json_mapping(value: Any, *, label: str) -> Mapping[str, Any]:
    """Deep-freeze a JSON-compatible mapping; reject non-JSON and NaN/Inf."""

    def visit(item: Any, path: str) -> Any:
        if item is None or isinstance(item, bool):
            return item
        if isinstance(item, int) and not isinstance(item, bool):
            return item
        if isinstance(item, float):
            if math.isnan(item) or math.isinf(item):
                _reject("NONCANONICAL_VALUE", f"non-finite float at {path}")
            return item
        if isinstance(item, str):
            if "\x00" in item:
                _reject("NONCANONICAL_VALUE", f"NUL in string at {path}")
            if len(item) > MAX_PROVENANCE_STRING:
                _reject("NONCANONICAL_VALUE", f"string too long at {path}")
            return item
        if isinstance(item, Sequence) and not isinstance(item, (str, bytes, bytearray)):
            return tuple(visit(child, f"{path}[{i}]") for i, child in enumerate(item))
        if isinstance(item, Mapping):
            if len(item) > MAX_PROVENANCE_KEYS:
                _reject("NONCANONICAL_VALUE", f"too many keys at {path}")
            out: dict[str, Any] = {}
            for key, child in item.items():
                if not isinstance(key, str) or not key or key.strip() != key:
                    _reject("NONCANONICAL_VALUE", f"invalid key at {path}: {key!r}")
                out[key] = visit(child, f"{path}.{key}" if path else key)
            return MappingProxyType(out)
        _reject(
            "NONCANONICAL_VALUE",
            f"disallowed type {type(item).__name__} at {path or label}",
        )

    if not isinstance(value, Mapping):
        _reject("NONCANONICAL_VALUE", f"{label} must be a mapping")
    return visit(value, label)  # type: ignore[return-value]


def _thaw_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {k: _thaw_json(v) for k, v in value.items()}
    if isinstance(value, tuple):
        return [_thaw_json(v) for v in value]
    return value


def canonical_json_bytes(value: Any) -> bytes:
    """Serialize a JSON value with sorted keys, compact separators, no NaN."""

    def normalize(item: Any) -> Any:
        if item is None or isinstance(item, bool):
            return item
        if isinstance(item, int) and not isinstance(item, bool):
            return item
        if isinstance(item, float):
            if math.isnan(item) or math.isinf(item):
                raise ManifestValidationError(
                    "NONCANONICAL_VALUE", "non-finite float in canonical JSON"
                )
            return item
        if isinstance(item, str):
            return item
        if isinstance(item, Mapping):
            return {str(k): normalize(item[k]) for k in sorted(item.keys(), key=str)}
        if isinstance(item, Sequence) and not isinstance(item, (str, bytes, bytearray)):
            return [normalize(v) for v in item]
        raise ManifestValidationError(
            "NONCANONICAL_VALUE",
            f"cannot canonicalize type {type(item).__name__}",
        )

    return json.dumps(
        normalize(value),
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def cid_v1_from_sha256_digest(digest: bytes) -> str:
    """CIDv1 / raw / sha2-256 / base32 (unpadded), independent of optional CID libs."""
    if len(digest) != 32:
        raise ManifestIntegrityError(
            "CHECKSUM_CID_MISMATCH",
            f"sha256 digest must be 32 bytes (got {len(digest)})",
        )
    multihash = bytes([0x12, 32]) + digest
    cid_bytes = bytes([0x01, 0x55]) + multihash
    encoded = base64.b32encode(cid_bytes).decode("ascii").lower().rstrip("=")
    return "b" + encoded


def cid_v1_from_sha256_hex(hex_digest: str) -> str:
    return cid_v1_from_sha256_digest(bytes.fromhex(_require_sha256_hex("digest", hex_digest)))


def _check_checksum_cid_pair(
    *,
    label: str,
    checksum_hex: Optional[str],
    cid: Optional[str],
) -> None:
    if checksum_hex is None or cid is None:
        return
    expected = cid_v1_from_sha256_hex(checksum_hex)
    if cid != expected:
        raise ManifestIntegrityError(
            "CHECKSUM_CID_MISMATCH",
            f"{label}: cid {cid!r} does not match sha256 {checksum_hex} "
            f"(expected {expected})",
        )


def _unique_ids(items: Iterable[str], *, label: str) -> None:
    seen: set[str] = set()
    for item in items:
        if item in seen:
            _reject("AMBIGUOUS_ID", f"{label} contains duplicate id {item!r}")
        seen.add(item)


def _require_known_keys(
    data: Mapping[str, Any],
    *,
    required: frozenset[str],
    optional: frozenset[str] = frozenset(),
    label: str,
) -> None:
    if not isinstance(data, Mapping):
        _reject("UNKNOWN_REQUIRED_FIELD", f"{label} must be a mapping")
    keys = frozenset(data.keys())
    missing = required - keys
    if missing:
        _reject(
            "UNKNOWN_REQUIRED_FIELD",
            f"{label} missing required field(s): {sorted(missing)}",
        )
    allowed = required | optional
    unknown = keys - allowed
    if unknown:
        _reject(
            "UNKNOWN_REQUIRED_FIELD",
            f"{label} has unknown field(s): {sorted(unknown)}",
        )


# ---------------------------------------------------------------------------
# Descriptors
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ContentChecksum:
    """Content integrity digest for a descriptor or the whole revision."""

    algorithm: str
    hex_digest: str

    def __post_init__(self) -> None:
        algo = _require_str("ContentChecksum.algorithm", self.algorithm)
        if algo not in CHECKSUM_ALGORITHMS:
            _reject("NONCANONICAL_VALUE", f"unsupported checksum algorithm: {algo!r}")
        digest = _require_sha256_hex("ContentChecksum.hex_digest", self.hex_digest)
        object.__setattr__(self, "algorithm", algo)
        object.__setattr__(self, "hex_digest", digest)

    def to_dict(self) -> dict[str, str]:
        return {"algorithm": self.algorithm, "hex_digest": self.hex_digest}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ContentChecksum":
        _require_known_keys(
            data,
            required=frozenset({"algorithm", "hex_digest"}),
            label="ContentChecksum",
        )
        return cls(algorithm=data["algorithm"], hex_digest=data["hex_digest"])

    @classmethod
    def from_sha256_hex(cls, hex_digest: str) -> "ContentChecksum":
        return cls(algorithm="sha256", hex_digest=hex_digest)

    @classmethod
    def of_bytes(cls, data: bytes) -> "ContentChecksum":
        return cls.from_sha256_hex(sha256_hex(data))

    def as_cid(self) -> str:
        return cid_v1_from_sha256_hex(self.hex_digest)

    def labeled(self) -> str:
        return f"{self.algorithm}:{self.hex_digest}"


@dataclass(frozen=True, slots=True)
class PartitionDescriptor:
    """Bounded descriptor for one versioned partition of graph payload."""

    partition_id: str
    kind: str
    path: str
    codec: str
    checksum: ContentChecksum
    row_count: int
    size_bytes: int
    cid: Optional[str] = None
    schema_version: Optional[str] = None

    def __post_init__(self) -> None:
        pid = _require_id("PartitionDescriptor.partition_id", self.partition_id)
        kind = _require_str("PartitionDescriptor.kind", self.kind)
        if kind not in PARTITION_KINDS:
            _reject("NONCANONICAL_VALUE", f"unknown partition kind: {kind!r}")
        path = _safe_relative_path("PartitionDescriptor.path", self.path)
        codec = _require_codec("PartitionDescriptor.codec", self.codec)
        if not isinstance(self.checksum, ContentChecksum):
            _reject("NONCANONICAL_VALUE", "PartitionDescriptor.checksum must be ContentChecksum")
        rows = _require_nonneg_int(
            "PartitionDescriptor.row_count", self.row_count, maximum=MAX_NODE_COUNT
        )
        size = _require_nonneg_int(
            "PartitionDescriptor.size_bytes", self.size_bytes, maximum=MAX_BYTES
        )
        cid = _optional_cid("PartitionDescriptor.cid", self.cid)
        schema_version = (
            None
            if self.schema_version is None
            else _require_schema_ref(
                "PartitionDescriptor.schema_version", self.schema_version
            )
        )
        _check_checksum_cid_pair(
            label=f"partition {pid}",
            checksum_hex=self.checksum.hex_digest,
            cid=cid,
        )
        object.__setattr__(self, "partition_id", pid)
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "path", path)
        object.__setattr__(self, "codec", codec)
        object.__setattr__(self, "row_count", rows)
        object.__setattr__(self, "size_bytes", size)
        object.__setattr__(self, "cid", cid)
        object.__setattr__(self, "schema_version", schema_version)

    def to_dict(self) -> dict[str, Any]:
        return {
            "partition_id": self.partition_id,
            "kind": self.kind,
            "path": self.path,
            "codec": self.codec,
            "checksum": self.checksum.to_dict(),
            "row_count": self.row_count,
            "size_bytes": self.size_bytes,
            "cid": self.cid,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "PartitionDescriptor":
        _require_known_keys(
            data,
            required=frozenset(
                {
                    "partition_id",
                    "kind",
                    "path",
                    "codec",
                    "checksum",
                    "row_count",
                    "size_bytes",
                }
            ),
            optional=frozenset({"cid", "schema_version"}),
            label="PartitionDescriptor",
        )
        checksum_raw = data["checksum"]
        if not isinstance(checksum_raw, Mapping):
            _reject("NONCANONICAL_VALUE", "PartitionDescriptor.checksum must be an object")
        return cls(
            partition_id=data["partition_id"],
            kind=data["kind"],
            path=data["path"],
            codec=data["codec"],
            checksum=ContentChecksum.from_dict(checksum_raw),
            row_count=data["row_count"],
            size_bytes=data["size_bytes"],
            cid=data.get("cid"),
            schema_version=data.get("schema_version"),
        )


@dataclass(frozen=True, slots=True)
class IndexDescriptor:
    """Bounded descriptor for a secondary index over a revision."""

    index_id: str
    kind: str
    path: str
    codec: str
    checksum: ContentChecksum
    fields: tuple[str, ...]
    size_bytes: int
    cid: Optional[str] = None
    schema_version: Optional[str] = None

    def __post_init__(self) -> None:
        iid = _require_id("IndexDescriptor.index_id", self.index_id)
        kind = _require_str("IndexDescriptor.kind", self.kind)
        if kind not in INDEX_KINDS:
            _reject("NONCANONICAL_VALUE", f"unknown index kind: {kind!r}")
        path = _safe_relative_path("IndexDescriptor.path", self.path)
        codec = _require_codec("IndexDescriptor.codec", self.codec)
        if not isinstance(self.checksum, ContentChecksum):
            _reject("NONCANONICAL_VALUE", "IndexDescriptor.checksum must be ContentChecksum")
        fields = _field_names(self.fields, label="IndexDescriptor.fields")
        size = _require_nonneg_int(
            "IndexDescriptor.size_bytes", self.size_bytes, maximum=MAX_BYTES
        )
        cid = _optional_cid("IndexDescriptor.cid", self.cid)
        schema_version = (
            None
            if self.schema_version is None
            else _require_schema_ref("IndexDescriptor.schema_version", self.schema_version)
        )
        _check_checksum_cid_pair(
            label=f"index {iid}",
            checksum_hex=self.checksum.hex_digest,
            cid=cid,
        )
        object.__setattr__(self, "index_id", iid)
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "path", path)
        object.__setattr__(self, "codec", codec)
        object.__setattr__(self, "fields", fields)
        object.__setattr__(self, "size_bytes", size)
        object.__setattr__(self, "cid", cid)
        object.__setattr__(self, "schema_version", schema_version)

    def to_dict(self) -> dict[str, Any]:
        return {
            "index_id": self.index_id,
            "kind": self.kind,
            "path": self.path,
            "codec": self.codec,
            "checksum": self.checksum.to_dict(),
            "fields": list(self.fields),
            "size_bytes": self.size_bytes,
            "cid": self.cid,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "IndexDescriptor":
        _require_known_keys(
            data,
            required=frozenset(
                {
                    "index_id",
                    "kind",
                    "path",
                    "codec",
                    "checksum",
                    "fields",
                    "size_bytes",
                }
            ),
            optional=frozenset({"cid", "schema_version"}),
            label="IndexDescriptor",
        )
        checksum_raw = data["checksum"]
        if not isinstance(checksum_raw, Mapping):
            _reject("NONCANONICAL_VALUE", "IndexDescriptor.checksum must be an object")
        return cls(
            index_id=data["index_id"],
            kind=data["kind"],
            path=data["path"],
            codec=data["codec"],
            checksum=ContentChecksum.from_dict(checksum_raw),
            fields=tuple(data["fields"]),
            size_bytes=data["size_bytes"],
            cid=data.get("cid"),
            schema_version=data.get("schema_version"),
        )


@dataclass(frozen=True, slots=True)
class ShardDescriptor:
    """Bounded descriptor for a physical or virtual shard of a revision."""

    shard_id: str
    codec: str
    checksum: ContentChecksum
    size_bytes: int
    path: Optional[str] = None
    cid: Optional[str] = None
    partition_ids: tuple[str, ...] = ()
    row_count: int = 0

    def __post_init__(self) -> None:
        sid = _require_id("ShardDescriptor.shard_id", self.shard_id)
        codec = _require_codec("ShardDescriptor.codec", self.codec)
        if not isinstance(self.checksum, ContentChecksum):
            _reject("NONCANONICAL_VALUE", "ShardDescriptor.checksum must be ContentChecksum")
        size = _require_nonneg_int(
            "ShardDescriptor.size_bytes", self.size_bytes, maximum=MAX_BYTES
        )
        path = _optional_path("ShardDescriptor.path", self.path)
        cid = _optional_cid("ShardDescriptor.cid", self.cid)
        if path is None and cid is None:
            _reject(
                "AMBIGUOUS_ID",
                f"shard {sid!r} requires path and/or cid for addressing",
            )
        rows = _require_nonneg_int(
            "ShardDescriptor.row_count", self.row_count, maximum=MAX_NODE_COUNT
        )
        if isinstance(self.partition_ids, (str, bytes, bytearray)) or not isinstance(
            self.partition_ids, Sequence
        ):
            _reject("NONCANONICAL_VALUE", "ShardDescriptor.partition_ids must be a sequence")
        pids = tuple(self.partition_ids)
        for pid in pids:
            _require_id("ShardDescriptor.partition_ids[]", pid)
        _unique_ids(pids, label="ShardDescriptor.partition_ids")
        ordered = tuple(sorted(pids))
        if ordered != pids:
            _reject(
                "NONCANONICAL_VALUE",
                "ShardDescriptor.partition_ids must be lexicographically sorted",
            )
        _check_checksum_cid_pair(
            label=f"shard {sid}",
            checksum_hex=self.checksum.hex_digest,
            cid=cid,
        )
        object.__setattr__(self, "shard_id", sid)
        object.__setattr__(self, "codec", codec)
        object.__setattr__(self, "size_bytes", size)
        object.__setattr__(self, "path", path)
        object.__setattr__(self, "cid", cid)
        object.__setattr__(self, "partition_ids", ordered)
        object.__setattr__(self, "row_count", rows)

    def to_dict(self) -> dict[str, Any]:
        return {
            "shard_id": self.shard_id,
            "codec": self.codec,
            "checksum": self.checksum.to_dict(),
            "size_bytes": self.size_bytes,
            "path": self.path,
            "cid": self.cid,
            "partition_ids": list(self.partition_ids),
            "row_count": self.row_count,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ShardDescriptor":
        _require_known_keys(
            data,
            required=frozenset({"shard_id", "codec", "checksum", "size_bytes"}),
            optional=frozenset({"path", "cid", "partition_ids", "row_count"}),
            label="ShardDescriptor",
        )
        checksum_raw = data["checksum"]
        if not isinstance(checksum_raw, Mapping):
            _reject("NONCANONICAL_VALUE", "ShardDescriptor.checksum must be an object")
        return cls(
            shard_id=data["shard_id"],
            codec=data["codec"],
            checksum=ContentChecksum.from_dict(checksum_raw),
            size_bytes=data["size_bytes"],
            path=data.get("path"),
            cid=data.get("cid"),
            partition_ids=tuple(data.get("partition_ids") or ()),
            row_count=int(data.get("row_count") or 0),
        )


@dataclass(frozen=True, slots=True)
class GraphCounts:
    """Canonical node/edge (and optional document) counts for a revision."""

    node_count: int
    edge_count: int
    document_count: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "node_count",
            _require_nonneg_int("GraphCounts.node_count", self.node_count, maximum=MAX_NODE_COUNT),
        )
        object.__setattr__(
            self,
            "edge_count",
            _require_nonneg_int("GraphCounts.edge_count", self.edge_count, maximum=MAX_EDGE_COUNT),
        )
        object.__setattr__(
            self,
            "document_count",
            _require_nonneg_int(
                "GraphCounts.document_count", self.document_count, maximum=MAX_NODE_COUNT
            ),
        )

    def to_dict(self) -> dict[str, int]:
        return {
            "node_count": self.node_count,
            "edge_count": self.edge_count,
            "document_count": self.document_count,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "GraphCounts":
        _require_known_keys(
            data,
            required=frozenset({"node_count", "edge_count"}),
            optional=frozenset({"document_count"}),
            label="GraphCounts",
        )
        return cls(
            node_count=data["node_count"],
            edge_count=data["edge_count"],
            document_count=int(data.get("document_count") or 0),
        )


@dataclass(frozen=True, slots=True)
class ProvenanceDescriptor:
    """Bounded provenance for who/what produced a revision."""

    producer_id: str
    producer_version: str
    source: str
    created_at: str
    repository_revision: Optional[str] = None
    parent_manifest_cid: Optional[str] = None
    extra: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        producer_id = _require_id("ProvenanceDescriptor.producer_id", self.producer_id)
        producer_version = _require_str(
            "ProvenanceDescriptor.producer_version", self.producer_version
        )
        if len(producer_version) > 128:
            _reject("NONCANONICAL_VALUE", "producer_version too long")
        source = _require_str("ProvenanceDescriptor.source", self.source)
        if len(source) > MAX_PROVENANCE_STRING:
            _reject("NONCANONICAL_VALUE", "source too long")
        created_at = _require_str("ProvenanceDescriptor.created_at", self.created_at)
        # Minimal ISO-8601 shape: YYYY-MM-DDTHH:MM:SSZ or with offset.
        if not re.fullmatch(
            r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})",
            created_at,
        ):
            _reject(
                "NONCANONICAL_VALUE",
                f"created_at must be ISO-8601 UTC/offset timestamp: {created_at!r}",
            )
        repo = _optional_id(
            "ProvenanceDescriptor.repository_revision", self.repository_revision
        )
        parent_cid = _optional_cid(
            "ProvenanceDescriptor.parent_manifest_cid", self.parent_manifest_cid
        )
        extra = _freeze_json_mapping(self.extra or {}, label="ProvenanceDescriptor.extra")
        object.__setattr__(self, "producer_id", producer_id)
        object.__setattr__(self, "producer_version", producer_version)
        object.__setattr__(self, "source", source)
        object.__setattr__(self, "created_at", created_at)
        object.__setattr__(self, "repository_revision", repo)
        object.__setattr__(self, "parent_manifest_cid", parent_cid)
        object.__setattr__(self, "extra", extra)

    def to_dict(self) -> dict[str, Any]:
        return {
            "producer_id": self.producer_id,
            "producer_version": self.producer_version,
            "source": self.source,
            "created_at": self.created_at,
            "repository_revision": self.repository_revision,
            "parent_manifest_cid": self.parent_manifest_cid,
            "extra": _thaw_json(self.extra),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ProvenanceDescriptor":
        _require_known_keys(
            data,
            required=frozenset(
                {"producer_id", "producer_version", "source", "created_at"}
            ),
            optional=frozenset(
                {"repository_revision", "parent_manifest_cid", "extra"}
            ),
            label="ProvenanceDescriptor",
        )
        extra = data.get("extra") or {}
        if not isinstance(extra, Mapping):
            _reject("NONCANONICAL_VALUE", "ProvenanceDescriptor.extra must be an object")
        return cls(
            producer_id=data["producer_id"],
            producer_version=data["producer_version"],
            source=data["source"],
            created_at=data["created_at"],
            repository_revision=data.get("repository_revision"),
            parent_manifest_cid=data.get("parent_manifest_cid"),
            extra=dict(extra),
        )


# ---------------------------------------------------------------------------
# Graph revision manifest
# ---------------------------------------------------------------------------


def _sorted_by_id(
    items: Sequence[Any],
    *,
    id_attr: str,
    label: str,
) -> tuple[Any, ...]:
    if isinstance(items, (str, bytes, bytearray)) or not isinstance(items, Sequence):
        _reject("NONCANONICAL_VALUE", f"{label} must be a sequence")
    seq = tuple(items)
    if len(seq) > {
        "partitions": MAX_PARTITIONS,
        "indexes": MAX_INDEXES,
        "shards": MAX_SHARDS,
    }.get(label, MAX_PARTITIONS):
        _reject("NONCANONICAL_VALUE", f"{label} exceeds bound")
    ids = [getattr(item, id_attr) for item in seq]
    _unique_ids(ids, label=label)
    ordered = tuple(sorted(seq, key=lambda item: getattr(item, id_attr)))
    if tuple(getattr(item, id_attr) for item in ordered) != tuple(ids):
        _reject("NONCANONICAL_VALUE", f"{label} must be sorted by {id_attr}")
    return ordered


@dataclass(frozen=True, slots=True)
class GraphRevisionManifest:
    """Immutable, versioned, canonical descriptor for one graph revision.

    Fields cover parent linkage, schema/ontology, graph kind, counts,
    partitions, indexes, shards, provenance, checksums, codecs, storage
    profile, and optional root CID.
    """

    tenant: str
    graph_id: str
    revision_id: str
    schema_id: str
    schema_version: str
    ontology_id: str
    ontology_version: str
    graph_kind: str
    storage_profile: str
    codec: str
    counts: GraphCounts
    provenance: ProvenanceDescriptor
    checksum: ContentChecksum
    parent_revision: Optional[str] = None
    partitions: tuple[PartitionDescriptor, ...] = ()
    indexes: tuple[IndexDescriptor, ...] = ()
    shards: tuple[ShardDescriptor, ...] = ()
    root_cid: Optional[str] = None
    manifest_version: str = MANIFEST_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.manifest_version != MANIFEST_SCHEMA_VERSION:
            _reject(
                "NONCANONICAL_VALUE",
                f"unsupported manifest_version: {self.manifest_version!r}",
            )
        tenant = _require_slug("tenant", self.tenant)
        graph_id = _require_slug("graph_id", self.graph_id)
        revision_id = _require_id("revision_id", self.revision_id)
        parent = _optional_id("parent_revision", self.parent_revision)
        if parent is not None and parent == revision_id:
            _reject(
                "AMBIGUOUS_ID",
                "parent_revision must not equal revision_id",
            )
        schema_id = _require_schema_ref("schema_id", self.schema_id)
        schema_version = _require_schema_ref("schema_version", self.schema_version)
        ontology_id = _require_ontology_ref("ontology_id", self.ontology_id)
        ontology_version = _require_ontology_ref(
            "ontology_version", self.ontology_version
        )
        graph_kind = _require_slug("graph_kind", self.graph_kind)
        storage_profile = _require_storage_profile(
            "storage_profile", self.storage_profile
        )
        codec = _require_codec("codec", self.codec)
        if not isinstance(self.counts, GraphCounts):
            _reject("NONCANONICAL_VALUE", "counts must be GraphCounts")
        if not isinstance(self.provenance, ProvenanceDescriptor):
            _reject("NONCANONICAL_VALUE", "provenance must be ProvenanceDescriptor")
        if not isinstance(self.checksum, ContentChecksum):
            _reject("NONCANONICAL_VALUE", "checksum must be ContentChecksum")

        partitions = _sorted_by_id(
            self.partitions, id_attr="partition_id", label="partitions"
        )
        indexes = _sorted_by_id(self.indexes, id_attr="index_id", label="indexes")
        shards = _sorted_by_id(self.shards, id_attr="shard_id", label="shards")

        partition_ids = {p.partition_id for p in partitions}
        for shard in shards:
            missing = set(shard.partition_ids) - partition_ids
            if missing:
                _reject(
                    "AMBIGUOUS_ID",
                    f"shard {shard.shard_id!r} references unknown partitions "
                    f"{sorted(missing)}",
                )

        # Count consistency: when node/edge partitions exist, their row totals
        # must match declared counts.
        node_rows = sum(p.row_count for p in partitions if p.kind == "nodes")
        edge_rows = sum(p.row_count for p in partitions if p.kind == "edges")
        doc_rows = sum(p.row_count for p in partitions if p.kind == "documents")
        if any(p.kind == "nodes" for p in partitions) and node_rows != self.counts.node_count:
            _reject(
                "INVALID_COUNT",
                f"node partition row_count sum {node_rows} != counts.node_count "
                f"{self.counts.node_count}",
            )
        if any(p.kind == "edges" for p in partitions) and edge_rows != self.counts.edge_count:
            _reject(
                "INVALID_COUNT",
                f"edge partition row_count sum {edge_rows} != counts.edge_count "
                f"{self.counts.edge_count}",
            )
        if (
            any(p.kind == "documents" for p in partitions)
            and doc_rows != self.counts.document_count
        ):
            _reject(
                "INVALID_COUNT",
                f"document partition row_count sum {doc_rows} != counts.document_count "
                f"{self.counts.document_count}",
            )

        root_cid = _optional_cid("root_cid", self.root_cid)
        _check_checksum_cid_pair(
            label="manifest root",
            checksum_hex=self.checksum.hex_digest,
            cid=root_cid,
        )

        object.__setattr__(self, "tenant", tenant)
        object.__setattr__(self, "graph_id", graph_id)
        object.__setattr__(self, "revision_id", revision_id)
        object.__setattr__(self, "parent_revision", parent)
        object.__setattr__(self, "schema_id", schema_id)
        object.__setattr__(self, "schema_version", schema_version)
        object.__setattr__(self, "ontology_id", ontology_id)
        object.__setattr__(self, "ontology_version", ontology_version)
        object.__setattr__(self, "graph_kind", graph_kind)
        object.__setattr__(self, "storage_profile", storage_profile)
        object.__setattr__(self, "codec", codec)
        object.__setattr__(self, "partitions", partitions)
        object.__setattr__(self, "indexes", indexes)
        object.__setattr__(self, "shards", shards)
        object.__setattr__(self, "root_cid", root_cid)

        # Verify declared checksum matches deterministic identity payload.
        expected = ContentChecksum.of_bytes(self.identity_bytes())
        if self.checksum.hex_digest != expected.hex_digest:
            raise ManifestIntegrityError(
                "CHECKSUM_CID_MISMATCH",
                "manifest checksum does not match canonical identity payload "
                f"(declared {self.checksum.hex_digest}, expected {expected.hex_digest})",
            )
        if root_cid is not None and root_cid != expected.as_cid():
            raise ManifestIntegrityError(
                "CHECKSUM_CID_MISMATCH",
                f"root_cid {root_cid!r} does not match identity payload CID "
                f"{expected.as_cid()!r}",
            )

    # -- serialization -----------------------------------------------------

    def identity_dict(self) -> dict[str, Any]:
        """Deterministic fields that define content identity (excludes checksum/CID)."""
        return {
            "manifest_version": self.manifest_version,
            "tenant": self.tenant,
            "graph_id": self.graph_id,
            "revision_id": self.revision_id,
            "parent_revision": self.parent_revision,
            "schema_id": self.schema_id,
            "schema_version": self.schema_version,
            "ontology_id": self.ontology_id,
            "ontology_version": self.ontology_version,
            "graph_kind": self.graph_kind,
            "storage_profile": self.storage_profile,
            "codec": self.codec,
            "counts": self.counts.to_dict(),
            "partitions": [p.to_dict() for p in self.partitions],
            "indexes": [i.to_dict() for i in self.indexes],
            "shards": [s.to_dict() for s in self.shards],
            "provenance": self.provenance.to_dict(),
        }

    def identity_bytes(self) -> bytes:
        return canonical_json_bytes(self.identity_dict())

    def to_dict(self) -> dict[str, Any]:
        payload = self.identity_dict()
        payload["checksum"] = self.checksum.to_dict()
        payload["root_cid"] = self.root_cid
        return payload

    def to_json(self) -> str:
        return canonical_json_bytes(self.to_dict()).decode("utf-8")

    def to_json_dict(self) -> dict[str, Any]:
        """Alias for service-contract style callers."""
        return self.to_dict()

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "GraphRevisionManifest":
        if not isinstance(data, Mapping):
            _reject("UNKNOWN_REQUIRED_FIELD", "manifest must be a mapping")
        # Require the full closed set of top-level keys (nulls allowed where optional).
        missing = _REQUIRED_MANIFEST_KEYS - frozenset(data.keys())
        if missing:
            _reject(
                "UNKNOWN_REQUIRED_FIELD",
                f"manifest missing required field(s): {sorted(missing)}",
            )
        unknown = frozenset(data.keys()) - _REQUIRED_MANIFEST_KEYS
        if unknown:
            _reject(
                "UNKNOWN_REQUIRED_FIELD",
                f"manifest has unknown field(s): {sorted(unknown)}",
            )
        if data.get("manifest_version") != MANIFEST_SCHEMA_VERSION:
            _reject(
                "NONCANONICAL_VALUE",
                f"unsupported manifest_version: {data.get('manifest_version')!r}",
            )

        counts_raw = data["counts"]
        if not isinstance(counts_raw, Mapping):
            _reject("NONCANONICAL_VALUE", "counts must be an object")
        prov_raw = data["provenance"]
        if not isinstance(prov_raw, Mapping):
            _reject("NONCANONICAL_VALUE", "provenance must be an object")
        checksum_raw = data["checksum"]
        if not isinstance(checksum_raw, Mapping):
            _reject("NONCANONICAL_VALUE", "checksum must be an object")

        partitions_raw = data["partitions"]
        indexes_raw = data["indexes"]
        shards_raw = data["shards"]
        if not isinstance(partitions_raw, Sequence) or isinstance(
            partitions_raw, (str, bytes, bytearray)
        ):
            _reject("NONCANONICAL_VALUE", "partitions must be an array")
        if not isinstance(indexes_raw, Sequence) or isinstance(
            indexes_raw, (str, bytes, bytearray)
        ):
            _reject("NONCANONICAL_VALUE", "indexes must be an array")
        if not isinstance(shards_raw, Sequence) or isinstance(
            shards_raw, (str, bytes, bytearray)
        ):
            _reject("NONCANONICAL_VALUE", "shards must be an array")

        return cls(
            tenant=data["tenant"],
            graph_id=data["graph_id"],
            revision_id=data["revision_id"],
            parent_revision=data["parent_revision"],
            schema_id=data["schema_id"],
            schema_version=data["schema_version"],
            ontology_id=data["ontology_id"],
            ontology_version=data["ontology_version"],
            graph_kind=data["graph_kind"],
            storage_profile=data["storage_profile"],
            codec=data["codec"],
            counts=GraphCounts.from_dict(counts_raw),
            partitions=tuple(
                PartitionDescriptor.from_dict(p) for p in partitions_raw  # type: ignore[arg-type]
            ),
            indexes=tuple(
                IndexDescriptor.from_dict(i) for i in indexes_raw  # type: ignore[arg-type]
            ),
            shards=tuple(
                ShardDescriptor.from_dict(s) for s in shards_raw  # type: ignore[arg-type]
            ),
            provenance=ProvenanceDescriptor.from_dict(prov_raw),
            checksum=ContentChecksum.from_dict(checksum_raw),
            root_cid=data["root_cid"],
            manifest_version=data["manifest_version"],
        )

    @classmethod
    def from_json(cls, text: str) -> "GraphRevisionManifest":
        if not isinstance(text, str) or not text:
            _reject("NONCANONICAL_VALUE", "json must be a non-empty string")
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ManifestValidationError(
                "NONCANONICAL_VALUE", f"invalid JSON: {exc}"
            ) from exc
        if not isinstance(data, Mapping):
            _reject("NONCANONICAL_VALUE", "json root must be an object")
        return cls.from_dict(data)

    @classmethod
    def build(cls, **kwargs: Any) -> "GraphRevisionManifest":
        """Construct a manifest with a computed checksum (and optional root CID)."""
        return build_graph_revision_manifest(**kwargs)


def _normalize_manifest_fields(
    *,
    tenant: str,
    graph_id: str,
    revision_id: str,
    schema_id: str,
    schema_version: str,
    ontology_id: str,
    ontology_version: str,
    graph_kind: str,
    storage_profile: str,
    codec: str,
    counts: GraphCounts,
    provenance: ProvenanceDescriptor,
    parent_revision: Optional[str],
    partitions: Sequence[PartitionDescriptor],
    indexes: Sequence[IndexDescriptor],
    shards: Sequence[ShardDescriptor],
) -> dict[str, Any]:
    """Validate and normalize fields; return identity dict ready for hashing."""
    tenant_n = _require_slug("tenant", tenant)
    graph_id_n = _require_slug("graph_id", graph_id)
    revision_id_n = _require_id("revision_id", revision_id)
    parent_n = _optional_id("parent_revision", parent_revision)
    if parent_n is not None and parent_n == revision_id_n:
        _reject("AMBIGUOUS_ID", "parent_revision must not equal revision_id")
    schema_id_n = _require_schema_ref("schema_id", schema_id)
    schema_version_n = _require_schema_ref("schema_version", schema_version)
    ontology_id_n = _require_ontology_ref("ontology_id", ontology_id)
    ontology_version_n = _require_ontology_ref("ontology_version", ontology_version)
    graph_kind_n = _require_slug("graph_kind", graph_kind)
    storage_profile_n = _require_storage_profile("storage_profile", storage_profile)
    codec_n = _require_codec("codec", codec)
    if not isinstance(counts, GraphCounts):
        _reject("NONCANONICAL_VALUE", "counts must be GraphCounts")
    if not isinstance(provenance, ProvenanceDescriptor):
        _reject("NONCANONICAL_VALUE", "provenance must be ProvenanceDescriptor")

    partitions_n = _sorted_by_id(partitions, id_attr="partition_id", label="partitions")
    indexes_n = _sorted_by_id(indexes, id_attr="index_id", label="indexes")
    shards_n = _sorted_by_id(shards, id_attr="shard_id", label="shards")

    partition_ids = {p.partition_id for p in partitions_n}
    for shard in shards_n:
        missing = set(shard.partition_ids) - partition_ids
        if missing:
            _reject(
                "AMBIGUOUS_ID",
                f"shard {shard.shard_id!r} references unknown partitions "
                f"{sorted(missing)}",
            )

    node_rows = sum(p.row_count for p in partitions_n if p.kind == "nodes")
    edge_rows = sum(p.row_count for p in partitions_n if p.kind == "edges")
    doc_rows = sum(p.row_count for p in partitions_n if p.kind == "documents")
    if any(p.kind == "nodes" for p in partitions_n) and node_rows != counts.node_count:
        _reject(
            "INVALID_COUNT",
            f"node partition row_count sum {node_rows} != counts.node_count "
            f"{counts.node_count}",
        )
    if any(p.kind == "edges" for p in partitions_n) and edge_rows != counts.edge_count:
        _reject(
            "INVALID_COUNT",
            f"edge partition row_count sum {edge_rows} != counts.edge_count "
            f"{counts.edge_count}",
        )
    if (
        any(p.kind == "documents" for p in partitions_n)
        and doc_rows != counts.document_count
    ):
        _reject(
            "INVALID_COUNT",
            f"document partition row_count sum {doc_rows} != counts.document_count "
            f"{counts.document_count}",
        )

    return {
        "manifest_version": MANIFEST_SCHEMA_VERSION,
        "tenant": tenant_n,
        "graph_id": graph_id_n,
        "revision_id": revision_id_n,
        "parent_revision": parent_n,
        "schema_id": schema_id_n,
        "schema_version": schema_version_n,
        "ontology_id": ontology_id_n,
        "ontology_version": ontology_version_n,
        "graph_kind": graph_kind_n,
        "storage_profile": storage_profile_n,
        "codec": codec_n,
        "counts": counts,
        "partitions": partitions_n,
        "indexes": indexes_n,
        "shards": shards_n,
        "provenance": provenance,
    }


def build_graph_revision_manifest(
    *,
    tenant: str,
    graph_id: str,
    revision_id: str,
    schema_id: str,
    schema_version: str,
    ontology_id: str,
    ontology_version: str,
    graph_kind: str,
    storage_profile: str,
    codec: str,
    counts: GraphCounts,
    provenance: ProvenanceDescriptor,
    parent_revision: Optional[str] = None,
    partitions: Sequence[PartitionDescriptor] = (),
    indexes: Sequence[IndexDescriptor] = (),
    shards: Sequence[ShardDescriptor] = (),
    include_root_cid: bool = True,
) -> GraphRevisionManifest:
    """Build a fully validated manifest with computed checksum and optional root CID."""
    fields = _normalize_manifest_fields(
        tenant=tenant,
        graph_id=graph_id,
        revision_id=revision_id,
        schema_id=schema_id,
        schema_version=schema_version,
        ontology_id=ontology_id,
        ontology_version=ontology_version,
        graph_kind=graph_kind,
        storage_profile=storage_profile,
        codec=codec,
        counts=counts,
        provenance=provenance,
        parent_revision=parent_revision,
        partitions=partitions,
        indexes=indexes,
        shards=shards,
    )
    identity = {
        "manifest_version": fields["manifest_version"],
        "tenant": fields["tenant"],
        "graph_id": fields["graph_id"],
        "revision_id": fields["revision_id"],
        "parent_revision": fields["parent_revision"],
        "schema_id": fields["schema_id"],
        "schema_version": fields["schema_version"],
        "ontology_id": fields["ontology_id"],
        "ontology_version": fields["ontology_version"],
        "graph_kind": fields["graph_kind"],
        "storage_profile": fields["storage_profile"],
        "codec": fields["codec"],
        "counts": fields["counts"].to_dict(),
        "partitions": [p.to_dict() for p in fields["partitions"]],
        "indexes": [i.to_dict() for i in fields["indexes"]],
        "shards": [s.to_dict() for s in fields["shards"]],
        "provenance": fields["provenance"].to_dict(),
    }
    checksum = ContentChecksum.of_bytes(canonical_json_bytes(identity))
    root_cid = checksum.as_cid() if include_root_cid else None
    return GraphRevisionManifest(
        tenant=fields["tenant"],
        graph_id=fields["graph_id"],
        revision_id=fields["revision_id"],
        parent_revision=fields["parent_revision"],
        schema_id=fields["schema_id"],
        schema_version=fields["schema_version"],
        ontology_id=fields["ontology_id"],
        ontology_version=fields["ontology_version"],
        graph_kind=fields["graph_kind"],
        storage_profile=fields["storage_profile"],
        codec=fields["codec"],
        counts=fields["counts"],
        partitions=fields["partitions"],
        indexes=fields["indexes"],
        shards=fields["shards"],
        provenance=fields["provenance"],
        checksum=checksum,
        root_cid=root_cid,
        manifest_version=fields["manifest_version"],
    )


__all__ = [
    "MANIFEST_SCHEMA_VERSION",
    "CANONICAL_JSON_PROFILE",
    "IDENTITY_DOMAIN",
    "STORAGE_PROFILES",
    "CODECS",
    "PARTITION_KINDS",
    "INDEX_KINDS",
    "CHECKSUM_ALGORITHMS",
    "MAX_PARTITIONS",
    "MAX_INDEXES",
    "MAX_SHARDS",
    "ManifestError",
    "ManifestValidationError",
    "ManifestIntegrityError",
    "ContentChecksum",
    "PartitionDescriptor",
    "IndexDescriptor",
    "ShardDescriptor",
    "GraphCounts",
    "ProvenanceDescriptor",
    "GraphRevisionManifest",
    "build_graph_revision_manifest",
    "canonical_json_bytes",
    "sha256_hex",
    "cid_v1_from_sha256_digest",
    "cid_v1_from_sha256_hex",
]
