"""Shared bounded artifact schemas for Hugging Face GraphRAG releases (USCIR-009).

Domain-neutral contracts for physical retrieval units used by corpus, BM25,
vector, and graph builders.  This module defines:

* the authoritative **4,096 rows/pointers** physical bound;
* fail-closed relative path and digest validation;
* row/byte/hash artifact descriptors;
* compact routing-index (chunk meta) row schemas; and
* stable sort / tie-breaker key helpers for deterministic shard layout.

It performs no Parquet I/O or network access; writers live in ``artifacts``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
import hashlib
import json
import re
from pathlib import PurePosixPath
from types import MappingProxyType
from typing import Any, Final, Optional, Union

# ---------------------------------------------------------------------------
# Schema identity
# ---------------------------------------------------------------------------

SCHEMA_VERSION: Final = "hf-graphrag-artifact-schema/v1"
COMPACT_INDEX_SCHEMA_VERSION: Final = "hf-graphrag-compact-index/v1"
DESCRIPTOR_SCHEMA_VERSION: Final = "hf-graphrag-artifact-descriptor/v1"
PARQUET_MEDIA_TYPE: Final = "application/vnd.apache.parquet"
JSON_MEDIA_TYPE: Final = "application/json"

# ---------------------------------------------------------------------------
# Physical bounds (authoritative; never reuse as model-token ceilings)
# ---------------------------------------------------------------------------

MAX_ROWS_PER_PHYSICAL_SHARD: Final = 4096
MAX_POINTERS_PER_ROW: Final = 4096
MAX_TERM_ROWS_PER_SHARD: Final = 4096
MAX_ROUTING_ROWS_PER_INDEX: Final = 4096
MAX_ADJACENCY_POINTERS_PER_ROW: Final = 4096
MAX_ROWS_PER_VECTOR_CENTROID: Final = 8192
MAX_VECTOR_SHARDS_PER_CENTROID: Final = 2
DEFAULT_CANDIDATE_CENTROIDS: Final = 4

PARQUET_COMPRESSION: Final = "zstd"
PARQUET_COMPRESSION_LEVEL: Final = 6
PARQUET_MAGIC: Final = b"PAR1"

# ---------------------------------------------------------------------------
# Regular expressions / path policy
# ---------------------------------------------------------------------------

_SHA256_HEX_RE = re.compile(r"^[0-9a-f]{64}$")
_SHA256_PREFIXED_RE = re.compile(r"^sha256:([0-9a-f]{64})$")
_CID_V1_RE = re.compile(r"^b[a-z2-7]{20,}$")
_CACHE_PATH_PARTS: Final = frozenset(
    {"__pycache__", ".cache", ".git", ".pytest_cache", ".mypy_cache"}
)

JsonMapping = Mapping[str, Any]
PathLike = Union[str, PurePosixPath]

# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class HfGraphragSchemaError(ValueError):
    """Base error for shared HF GraphRAG schema contract failures."""


class ArtifactPathError(HfGraphragSchemaError):
    """Raised when an artifact path is absolute, traverses, or is unsafe."""


class InvalidDigestError(HfGraphragSchemaError):
    """Raised when a digest/CID field is malformed."""


class PhysicalBoundError(HfGraphragSchemaError):
    """Raised when a physical row/pointer bound is violated."""


class SortKeyError(HfGraphragSchemaError):
    """Raised when a sort/tie-breaker key cannot be applied."""


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class ArtifactFamily(str, Enum):
    """Top-level artifact families in a bounded HF GraphRAG release."""

    CORPUS = "corpus"
    BM25_DOCUMENTS = "bm25_documents"
    BM25_POSTINGS = "bm25_postings"
    VECTORS = "vectors"
    CENTROIDS = "centroids"
    GRAPH_NODES = "graph_nodes"
    GRAPH_EDGES = "graph_edges"
    GRAPH_ADJACENCY_OUT = "graph_adjacency_out"
    GRAPH_ADJACENCY_IN = "graph_adjacency_in"
    LOCATOR_INDEX = "locator_index"
    ROUTING_INDEX = "routing_index"
    MANIFEST = "manifest"
    RECEIPT = "receipt"
    REPORT = "report"
    RELEASE_METADATA = "release_metadata"

    @classmethod
    def coerce(cls, value: Any) -> "ArtifactFamily":
        if isinstance(value, ArtifactFamily):
            return value
        text = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
        aliases = {
            "bm25_docs": cls.BM25_DOCUMENTS,
            "bm25_document": cls.BM25_DOCUMENTS,
            "postings": cls.BM25_POSTINGS,
            "bm25_posting": cls.BM25_POSTINGS,
            "vector": cls.VECTORS,
            "centroid": cls.CENTROIDS,
            "nodes": cls.GRAPH_NODES,
            "edges": cls.GRAPH_EDGES,
            "adjacency_out": cls.GRAPH_ADJACENCY_OUT,
            "adjacency_in": cls.GRAPH_ADJACENCY_IN,
            "out_adjacency": cls.GRAPH_ADJACENCY_OUT,
            "in_adjacency": cls.GRAPH_ADJACENCY_IN,
            "locator": cls.LOCATOR_INDEX,
            "locators": cls.LOCATOR_INDEX,
            "index": cls.ROUTING_INDEX,
            "routing": cls.ROUTING_INDEX,
            "compact_index": cls.ROUTING_INDEX,
        }
        if text in aliases:
            return aliases[text]
        for family in cls:
            if family.value == text or family.name.lower() == text:
                return family
        raise HfGraphragSchemaError(f"unknown artifact family: {value!r}")


# Families that carry physical row bounds (data shards / indexes).
_ROW_BOUNDED_FAMILIES: Final = frozenset(
    {
        ArtifactFamily.CORPUS,
        ArtifactFamily.BM25_DOCUMENTS,
        ArtifactFamily.BM25_POSTINGS,
        ArtifactFamily.VECTORS,
        ArtifactFamily.CENTROIDS,
        ArtifactFamily.GRAPH_NODES,
        ArtifactFamily.GRAPH_EDGES,
        ArtifactFamily.GRAPH_ADJACENCY_OUT,
        ArtifactFamily.GRAPH_ADJACENCY_IN,
        ArtifactFamily.LOCATOR_INDEX,
        ArtifactFamily.ROUTING_INDEX,
    }
)

# ---------------------------------------------------------------------------
# Primitive helpers
# ---------------------------------------------------------------------------


def _require_non_empty_str(value: Any, name: str, *, maximum: int = 4096) -> str:
    if not isinstance(value, str) or not value.strip():
        raise HfGraphragSchemaError(f"{name} must be a non-empty string")
    if "\x00" in value:
        raise HfGraphragSchemaError(f"{name} must not contain NUL")
    text = value.strip()
    if len(text) > maximum:
        raise HfGraphragSchemaError(f"{name} exceeds maximum length {maximum}")
    return text


def _optional_str(value: Any, name: str = "value") -> Optional[str]:
    if value is None or value == "":
        return None
    return _require_non_empty_str(value, name)


def _require_non_negative_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise HfGraphragSchemaError(f"{name} must be an integer")
    if value < 0:
        raise HfGraphragSchemaError(f"{name} must be >= 0")
    return value


def _require_positive_int(value: Any, name: str) -> int:
    number = _require_non_negative_int(value, name)
    if number <= 0:
        raise HfGraphragSchemaError(f"{name} must be a positive integer")
    return number


def canonical_json_dumps(payload: Any) -> str:
    """Return deterministic JSON text for fixtures and content addressing."""

    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def canonical_json_bytes(payload: Any) -> bytes:
    """Return UTF-8 canonical JSON bytes."""

    return canonical_json_dumps(payload).encode("utf-8")


def content_sha256(data: bytes | str) -> str:
    """Return lowercase hex SHA-256 of *data*."""

    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def digest_mapping(payload: Mapping[str, Any]) -> str:
    """SHA-256 of the canonical JSON encoding of *payload*."""

    return content_sha256(canonical_json_dumps(payload))


# ---------------------------------------------------------------------------
# Digest / path validation
# ---------------------------------------------------------------------------


def normalize_sha256(value: Any, *, name: str = "sha256") -> str:
    """Normalize a SHA-256 digest to lowercase 64-char hex (no prefix)."""

    text = _require_non_empty_str(value, name).lower()
    match = _SHA256_PREFIXED_RE.fullmatch(text)
    if match:
        text = match.group(1)
    if not _SHA256_HEX_RE.fullmatch(text):
        raise InvalidDigestError(
            f"{name} must be a lowercase 64-char hex SHA-256 "
            f"(optionally prefixed with 'sha256:'), got {value!r}"
        )
    return text


def validate_digest(value: Any, *, name: str = "digest") -> str:
    """Accept SHA-256 (raw or ``sha256:``) or CIDv1 base32; return normalized form."""

    text = _require_non_empty_str(value, name).lower()
    if text.startswith("sha256:"):
        return f"sha256:{normalize_sha256(text, name=name)}"
    if _SHA256_HEX_RE.fullmatch(text):
        return text
    if _CID_V1_RE.fullmatch(text):
        return text
    raise InvalidDigestError(
        f"{name} must be SHA-256 hex, sha256:<hex>, or CIDv1 base32; got {value!r}"
    )


def normalize_relative_artifact_path(
    value: Any,
    *,
    name: str = "relative_path",
) -> str:
    """Normalize and validate a release-relative artifact path.

    Rejects absolute paths, drive letters, backslashes, empty segments,
    ``.`` / ``..`` traversal, and cache/VCS directory components.
    """

    text = _require_non_empty_str(value, name, maximum=512)
    if "\\" in text:
        raise ArtifactPathError(f"{name} must use POSIX separators, got {value!r}")
    if text.startswith("/") or text.startswith("~"):
        raise ArtifactPathError(f"{name} must be relative, not absolute: {value!r}")
    if len(text) >= 2 and text[1] == ":":
        raise ArtifactPathError(f"{name} must not include a drive letter: {value!r}")
    if text.startswith("//"):
        raise ArtifactPathError(f"{name} must not be a UNC path: {value!r}")

    parsed = PurePosixPath(text)
    if parsed.is_absolute():
        raise ArtifactPathError(f"{name} must be relative, not absolute: {value!r}")
    if text != parsed.as_posix():
        raise ArtifactPathError(
            f"{name} must be a normalized POSIX path without redundant "
            f"segments: {value!r}"
        )
    if any(part in {"", ".", ".."} for part in parsed.parts):
        raise ArtifactPathError(
            f"{name} must not contain empty, '.', or '..' segments: {value!r}"
        )
    if any(part.casefold() in _CACHE_PATH_PARTS for part in parsed.parts):
        raise ArtifactPathError(
            f"{name} must not include cache/VCS path components: {value!r}"
        )
    return parsed.as_posix()


def validate_physical_row_count(
    value: Any,
    *,
    name: str = "row_count",
    maximum: int = MAX_ROWS_PER_PHYSICAL_SHARD,
) -> int:
    """Require a non-negative row count within the physical shard bound."""

    count = _require_non_negative_int(value, name)
    if count > maximum:
        raise PhysicalBoundError(
            f"{name}={count} exceeds physical bound {maximum}"
        )
    return count


def validate_physical_pointer_count(
    value: Any,
    *,
    name: str = "pointer_count",
    maximum: int = MAX_POINTERS_PER_ROW,
) -> int:
    """Require a non-negative pointer count within the physical pointer bound."""

    count = _require_non_negative_int(value, name)
    if count > maximum:
        raise PhysicalBoundError(
            f"{name}={count} exceeds physical pointer bound {maximum}"
        )
    return count


def validate_centroid_capacity(
    *,
    row_count: Any,
    shard_count: Any,
) -> tuple[int, int]:
    """Enforce centroid capacity: ≤8192 rows and ≤2 physical shards."""

    rows = _require_non_negative_int(row_count, "row_count")
    shards = _require_non_negative_int(shard_count, "shard_count")
    if rows > MAX_ROWS_PER_VECTOR_CENTROID:
        raise PhysicalBoundError(
            f"centroid row_count={rows} exceeds {MAX_ROWS_PER_VECTOR_CENTROID}"
        )
    if shards > MAX_VECTOR_SHARDS_PER_CENTROID:
        raise PhysicalBoundError(
            f"centroid shard_count={shards} exceeds "
            f"{MAX_VECTOR_SHARDS_PER_CENTROID}"
        )
    if shards > 0:
        max_via_shards = shards * MAX_ROWS_PER_PHYSICAL_SHARD
        if rows > max_via_shards:
            raise PhysicalBoundError(
                f"centroid row_count={rows} exceeds capacity of "
                f"{shards} shard(s) × {MAX_ROWS_PER_PHYSICAL_SHARD}"
            )
    return rows, shards


def physical_bounds_policy() -> dict[str, int]:
    """Return the sealed physical-bound policy as a plain dict."""

    return {
        "max_adjacency_pointers_per_row": MAX_ADJACENCY_POINTERS_PER_ROW,
        "max_pointers_per_row": MAX_POINTERS_PER_ROW,
        "max_routing_rows_per_index": MAX_ROUTING_ROWS_PER_INDEX,
        "max_rows_per_physical_shard": MAX_ROWS_PER_PHYSICAL_SHARD,
        "max_rows_per_vector_centroid": MAX_ROWS_PER_VECTOR_CENTROID,
        "max_term_rows_per_shard": MAX_TERM_ROWS_PER_SHARD,
        "max_vector_shards_per_centroid": MAX_VECTOR_SHARDS_PER_CENTROID,
    }


# ---------------------------------------------------------------------------
# Stable sort / tie-breaker keys
# ---------------------------------------------------------------------------


def _scalar_sort_value(value: Any) -> Any:
    """Normalize a single cell into a total-orderable sort scalar."""

    if value is None:
        return (0, "")
    if isinstance(value, bool):
        return (1, int(value))
    if isinstance(value, int) and not isinstance(value, bool):
        return (2, value)
    if isinstance(value, float):
        # NaN sorts after all finite values; -0.0 == 0.0.
        if value != value:  # NaN
            return (4, 0.0)
        return (3, value)
    if isinstance(value, (bytes, bytearray)):
        return (5, bytes(value))
    text = str(value)
    return (6, text)


def row_sort_key(
    row: Mapping[str, Any],
    primary_keys: Sequence[str],
    *,
    tie_breakers: Sequence[str] = (),
    descending: Sequence[str] = (),
) -> tuple[Any, ...]:
    """Build a total-order sort key for *row*.

    *primary_keys* are applied first, then *tie_breakers*.  Columns listed in
    *descending* invert their order (useful for cosine similarity).  Missing
    fields raise :class:`SortKeyError` so silent reordering cannot occur.
    """

    if not isinstance(row, Mapping):
        raise SortKeyError("row must be a mapping")
    if not primary_keys and not tie_breakers:
        raise SortKeyError("at least one primary or tie-breaker key is required")
    desc = frozenset(str(name) for name in descending)
    parts: list[Any] = []
    for name in (*primary_keys, *tie_breakers):
        key = str(name)
        if key not in row:
            raise SortKeyError(f"sort key field missing from row: {key!r}")
        scalar = _scalar_sort_value(row[key])
        if key in desc:
            # Invert: wrap in a descending marker so equal primary keys still
            # resolve by subsequent ascending tie-breakers.
            if isinstance(scalar, tuple) and len(scalar) == 2 and scalar[0] in {2, 3}:
                kind, number = scalar
                parts.append((kind, -number))
            elif isinstance(scalar, tuple) and len(scalar) == 2 and scalar[0] == 1:
                parts.append((1, -int(scalar[1])))
            else:
                # For non-numeric values, descending means reverse string order
                # via a complement tag rather than Python's reverse=True.
                parts.append((9, scalar))
        else:
            parts.append(scalar)
    return tuple(parts)


def stable_sort_rows(
    rows: Sequence[Mapping[str, Any]],
    primary_keys: Sequence[str],
    *,
    tie_breakers: Sequence[str] = ("entry_cid",),
    descending: Sequence[str] = (),
) -> tuple[dict[str, Any], ...]:
    """Return rows sorted by *primary_keys* then stable *tie_breakers*.

    Default tie-breaker is ``entry_cid`` (the durable content key).  Sort is
    deterministic for the same multiset of rows regardless of input order.
    """

    if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes, bytearray)):
        raise SortKeyError("rows must be a sequence of mappings")
    indexed: list[tuple[tuple[Any, ...], int, dict[str, Any]]] = []
    for position, row in enumerate(rows):
        if not isinstance(row, Mapping):
            raise SortKeyError(f"rows[{position}] must be a mapping")
        key = row_sort_key(
            row,
            primary_keys,
            tie_breakers=tie_breakers,
            descending=descending,
        )
        # Materialize a plain dict so callers cannot mutate inputs through us.
        indexed.append((key, position, dict(row)))
    # Final position is a last-resort stable index (input order) so equal keys
    # never depend on interpreter dict ordering; after primary+tie-break the
    # position only matters when all declared keys collide.
    indexed.sort(key=lambda item: (item[0], item[1]))
    return tuple(item[2] for item in indexed)


def shard_sequence(
    values: Sequence[Any],
    *,
    max_rows: int = MAX_ROWS_PER_PHYSICAL_SHARD,
) -> tuple[tuple[Any, ...], ...]:
    """Partition *values* into ordered shards of at most *max_rows* items."""

    if (
        not isinstance(max_rows, int)
        or isinstance(max_rows, bool)
        or max_rows <= 0
    ):
        raise PhysicalBoundError("max_rows must be a positive integer")
    if max_rows > MAX_ROWS_PER_PHYSICAL_SHARD:
        raise PhysicalBoundError(
            f"max_rows={max_rows} exceeds physical bound "
            f"{MAX_ROWS_PER_PHYSICAL_SHARD}"
        )
    if not values:
        return ((),)
    return tuple(
        tuple(values[index : index + max_rows])
        for index in range(0, len(values), max_rows)
    )


def chunk_pointers(
    pointers: Sequence[Any],
    *,
    max_pointers: int = MAX_POINTERS_PER_ROW,
) -> tuple[tuple[Any, ...], ...]:
    """Split *pointers* into cells of at most *max_pointers* items each."""

    if (
        not isinstance(max_pointers, int)
        or isinstance(max_pointers, bool)
        or max_pointers <= 0
    ):
        raise PhysicalBoundError("max_pointers must be a positive integer")
    if max_pointers > MAX_POINTERS_PER_ROW:
        raise PhysicalBoundError(
            f"max_pointers={max_pointers} exceeds physical pointer bound "
            f"{MAX_POINTERS_PER_ROW}"
        )
    if not pointers:
        return ((),)
    return tuple(
        tuple(pointers[index : index + max_pointers])
        for index in range(0, len(pointers), max_pointers)
    )


# ---------------------------------------------------------------------------
# Descriptors and compact-index records
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ArtifactDescriptor:
    """Integrity descriptor for one release artifact (row/byte/hash bound).

    Paths are relative to the release root. Digests are SHA-256. Row counts
    for data families must respect the physical 4,096 bound.
    """

    relative_path: str
    sha256: str
    size_bytes: int
    row_count: int = 0
    media_type: str = PARQUET_MEDIA_TYPE
    schema_id: str = DESCRIPTOR_SCHEMA_VERSION
    family: ArtifactFamily = ArtifactFamily.CORPUS
    content_cid: Optional[str] = None
    first_key: Optional[str] = None
    last_key: Optional[str] = None
    shard_id: Optional[int] = None
    key_range: Optional[tuple[str, str]] = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "relative_path",
            normalize_relative_artifact_path(self.relative_path),
        )
        object.__setattr__(
            self, "sha256", normalize_sha256(self.sha256, name="sha256")
        )
        object.__setattr__(
            self,
            "size_bytes",
            _require_non_negative_int(self.size_bytes, "size_bytes"),
        )
        object.__setattr__(
            self,
            "media_type",
            _require_non_empty_str(self.media_type, "media_type", maximum=256),
        )
        object.__setattr__(
            self,
            "schema_id",
            _require_non_empty_str(self.schema_id, "schema_id", maximum=256),
        )
        family = ArtifactFamily.coerce(self.family)
        object.__setattr__(self, "family", family)
        if family in _ROW_BOUNDED_FAMILIES:
            rows = validate_physical_row_count(self.row_count)
        else:
            rows = _require_non_negative_int(self.row_count, "row_count")
        object.__setattr__(self, "row_count", rows)
        if self.content_cid is not None:
            object.__setattr__(
                self,
                "content_cid",
                validate_digest(self.content_cid, name="content_cid"),
            )
        if self.first_key is not None:
            object.__setattr__(
                self, "first_key", _optional_str(self.first_key, "first_key")
            )
        if self.last_key is not None:
            object.__setattr__(
                self, "last_key", _optional_str(self.last_key, "last_key")
            )
        if self.shard_id is not None:
            object.__setattr__(
                self,
                "shard_id",
                _require_non_negative_int(self.shard_id, "shard_id"),
            )
        if self.key_range is not None:
            if (
                not isinstance(self.key_range, (tuple, list))
                or len(self.key_range) != 2
            ):
                raise HfGraphragSchemaError(
                    "key_range must be a (first, last) pair"
                )
            object.__setattr__(
                self,
                "key_range",
                (
                    _require_non_empty_str(self.key_range[0], "key_range[0]"),
                    _require_non_empty_str(self.key_range[1], "key_range[1]"),
                ),
            )
        if not isinstance(self.metadata, Mapping):
            raise HfGraphragSchemaError("metadata must be a mapping")
        object.__setattr__(
            self, "metadata", MappingProxyType(dict(self.metadata))
        )

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "family": self.family.value,
            "media_type": self.media_type,
            "relative_path": self.relative_path,
            "row_count": self.row_count,
            "schema_id": self.schema_id,
            "sha256": self.sha256,
            "size_bytes": self.size_bytes,
        }
        if self.content_cid is not None:
            payload["content_cid"] = self.content_cid
        if self.first_key is not None:
            payload["first_key"] = self.first_key
        if self.last_key is not None:
            payload["last_key"] = self.last_key
        if self.shard_id is not None:
            payload["shard_id"] = self.shard_id
        if self.key_range is not None:
            payload["key_range"] = list(self.key_range)
        if self.metadata:
            payload["metadata"] = dict(self.metadata)
        return payload

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "ArtifactDescriptor":
        if not isinstance(value, Mapping):
            raise HfGraphragSchemaError("artifact descriptor must be a mapping")
        key_range = value.get("key_range")
        if isinstance(key_range, list):
            key_range = tuple(key_range)
        return cls(
            relative_path=value.get("relative_path") or value.get("path") or "",
            sha256=value.get("sha256") or "",
            size_bytes=value.get("size_bytes", value.get("byte_length", 0)),
            row_count=value.get("row_count", 0),
            media_type=value.get("media_type") or PARQUET_MEDIA_TYPE,
            schema_id=(
                value.get("schema_id")
                or value.get("schema_identifier")
                or DESCRIPTOR_SCHEMA_VERSION
            ),
            family=value.get("family", ArtifactFamily.CORPUS),
            content_cid=value.get("content_cid") or value.get("cid"),
            first_key=value.get("first_key"),
            last_key=value.get("last_key"),
            shard_id=value.get("shard_id"),
            key_range=key_range,
            metadata=(
                value.get("metadata")
                if isinstance(value.get("metadata"), Mapping)
                else {}
            ),
        )


@dataclass(frozen=True, slots=True)
class CompactIndexRow:
    """One compact routing-index row pointing at a bounded data shard.

    Compact indexes map inclusive key ranges (and optional document-index
    ranges) to a relative Parquet path with verified size/sha256/row_count.
    """

    relative_path: str
    sha256: str
    size_bytes: int
    row_count: int
    shard_id: int
    first_key: str
    last_key: str
    kind: str
    schema_version: str = COMPACT_INDEX_SCHEMA_VERSION
    content_cid: Optional[str] = None
    start_document_index: Optional[int] = None
    end_document_index: Optional[int] = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "relative_path",
            normalize_relative_artifact_path(self.relative_path),
        )
        object.__setattr__(
            self, "sha256", normalize_sha256(self.sha256, name="sha256")
        )
        object.__setattr__(
            self,
            "size_bytes",
            _require_non_negative_int(self.size_bytes, "size_bytes"),
        )
        object.__setattr__(
            self, "row_count", validate_physical_row_count(self.row_count)
        )
        object.__setattr__(
            self,
            "shard_id",
            _require_non_negative_int(self.shard_id, "shard_id"),
        )
        object.__setattr__(
            self,
            "first_key",
            _require_non_empty_str(self.first_key, "first_key"),
        )
        object.__setattr__(
            self, "last_key", _require_non_empty_str(self.last_key, "last_key")
        )
        object.__setattr__(
            self, "kind", _require_non_empty_str(self.kind, "kind", maximum=128)
        )
        object.__setattr__(
            self,
            "schema_version",
            _require_non_empty_str(self.schema_version, "schema_version"),
        )
        if self.content_cid is not None:
            object.__setattr__(
                self,
                "content_cid",
                validate_digest(self.content_cid, name="content_cid"),
            )
        if self.start_document_index is not None:
            object.__setattr__(
                self,
                "start_document_index",
                _require_non_negative_int(
                    self.start_document_index, "start_document_index"
                ),
            )
        if self.end_document_index is not None:
            object.__setattr__(
                self,
                "end_document_index",
                _require_non_negative_int(
                    self.end_document_index, "end_document_index"
                ),
            )
        if (
            self.start_document_index is not None
            and self.end_document_index is not None
            and self.end_document_index < self.start_document_index
        ):
            raise HfGraphragSchemaError(
                "end_document_index must be >= start_document_index"
            )
        if not isinstance(self.metadata, Mapping):
            raise HfGraphragSchemaError("metadata must be a mapping")
        object.__setattr__(
            self, "metadata", MappingProxyType(dict(self.metadata))
        )

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "first_key": self.first_key,
            "kind": self.kind,
            "last_key": self.last_key,
            "relative_path": self.relative_path,
            "row_count": self.row_count,
            "schema_version": self.schema_version,
            "sha256": self.sha256,
            "shard_id": self.shard_id,
            "size_bytes": self.size_bytes,
        }
        if self.content_cid is not None:
            payload["content_cid"] = self.content_cid
            payload["cid"] = self.content_cid
        if self.start_document_index is not None:
            payload["start_document_index"] = self.start_document_index
        if self.end_document_index is not None:
            payload["end_document_index"] = self.end_document_index
        if self.metadata:
            payload["metadata"] = dict(self.metadata)
        return payload

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "CompactIndexRow":
        if not isinstance(value, Mapping):
            raise HfGraphragSchemaError("compact index row must be a mapping")
        return cls(
            relative_path=value.get("relative_path") or "",
            sha256=value.get("sha256") or "",
            size_bytes=value.get("size_bytes", 0),
            row_count=value.get("row_count", 0),
            shard_id=value.get("shard_id", 0),
            first_key=value.get("first_key") or "",
            last_key=value.get("last_key") or "",
            kind=value.get("kind") or "",
            schema_version=value.get(
                "schema_version", COMPACT_INDEX_SCHEMA_VERSION
            ),
            content_cid=value.get("content_cid") or value.get("cid"),
            start_document_index=value.get("start_document_index"),
            end_document_index=value.get("end_document_index"),
            metadata=(
                value.get("metadata")
                if isinstance(value.get("metadata"), Mapping)
                else {}
            ),
        )


def part_filename(shard_id: int, *, width: int = 6) -> str:
    """Return the canonical ``part-NNNNNN.parquet`` name for *shard_id*."""

    number = _require_non_negative_int(shard_id, "shard_id")
    if width < 1:
        raise HfGraphragSchemaError("width must be a positive integer")
    return f"part-{number:0{width}d}.parquet"


def example_descriptor_payload() -> dict[str, Any]:
    """Minimal valid descriptor payload for fixtures."""

    digest = content_sha256("fixture-shard-v1")
    return {
        "family": ArtifactFamily.CORPUS.value,
        "first_key": "entry-a",
        "last_key": "entry-b",
        "media_type": PARQUET_MEDIA_TYPE,
        "relative_path": "data/corpus/part-000000.parquet",
        "row_count": 2,
        "schema_id": DESCRIPTOR_SCHEMA_VERSION,
        "sha256": digest,
        "shard_id": 0,
        "size_bytes": 128,
    }


def example_compact_index_payload() -> dict[str, Any]:
    """Minimal valid compact-index row payload for fixtures."""

    digest = content_sha256("fixture-index-v1")
    return {
        "end_document_index": 1,
        "first_key": "entry-a",
        "kind": "corpus",
        "last_key": "entry-b",
        "relative_path": "data/corpus/part-000000.parquet",
        "row_count": 2,
        "schema_version": COMPACT_INDEX_SCHEMA_VERSION,
        "sha256": digest,
        "shard_id": 0,
        "size_bytes": 128,
        "start_document_index": 0,
    }


__all__ = [
    "COMPACT_INDEX_SCHEMA_VERSION",
    "DEFAULT_CANDIDATE_CENTROIDS",
    "DESCRIPTOR_SCHEMA_VERSION",
    "JSON_MEDIA_TYPE",
    "MAX_ADJACENCY_POINTERS_PER_ROW",
    "MAX_POINTERS_PER_ROW",
    "MAX_ROUTING_ROWS_PER_INDEX",
    "MAX_ROWS_PER_PHYSICAL_SHARD",
    "MAX_ROWS_PER_VECTOR_CENTROID",
    "MAX_TERM_ROWS_PER_SHARD",
    "MAX_VECTOR_SHARDS_PER_CENTROID",
    "PARQUET_COMPRESSION",
    "PARQUET_COMPRESSION_LEVEL",
    "PARQUET_MAGIC",
    "PARQUET_MEDIA_TYPE",
    "SCHEMA_VERSION",
    "ArtifactDescriptor",
    "ArtifactFamily",
    "ArtifactPathError",
    "CompactIndexRow",
    "HfGraphragSchemaError",
    "InvalidDigestError",
    "PhysicalBoundError",
    "SortKeyError",
    "canonical_json_bytes",
    "canonical_json_dumps",
    "chunk_pointers",
    "content_sha256",
    "digest_mapping",
    "example_compact_index_payload",
    "example_descriptor_payload",
    "normalize_relative_artifact_path",
    "normalize_sha256",
    "part_filename",
    "physical_bounds_policy",
    "row_sort_key",
    "shard_sequence",
    "stable_sort_rows",
    "validate_centroid_capacity",
    "validate_digest",
    "validate_physical_pointer_count",
    "validate_physical_row_count",
]
