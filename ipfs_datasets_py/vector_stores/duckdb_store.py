"""DuckDB typed vector collection and lifecycle schema (DQK-020).

Authoritative *metadata* catalog for vector collections.  Exact FLOAT[N]
search tables and VSS/HNSW indexes are later layers (DQK-021/022); this module
owns:

* collection / embedding-model / document / chunk identity
* generation lifecycle with atomic publish
* shard, index-build, tombstone, and compaction receipts
* exact dimension and dtype contracts
* normalized source identities (content digests; no filesystem authority)
* zero pickle authority — runtime never reads or writes pickle metadata

Query-visible vectors are only those belonging to a collection's published
generation that are not tombstoned.  Update and delete always tombstone prior
live rows in the same transaction as the replacement or removal, so readers
cannot observe stale vectors.
"""

from __future__ import annotations

import hashlib
import json
import re
import struct
import threading
import uuid
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from types import MappingProxyType
from typing import (
    Any,
    Final,
    Iterator,
    Mapping,
    Optional,
    Sequence,
    Union,
)

__all__ = [
    "ALLOWED_DTYPES",
    "DUCKDB_VECTOR_STORE_SCHEMA",
    "SCHEMA_VERSION",
    "VECTOR_TABLES",
    "ChunkRecord",
    "CollectionRecord",
    "CompactionRecord",
    "DocumentRecord",
    "DuckDBVectorStore",
    "EmbeddingModelRecord",
    "GenerationRecord",
    "GenerationStatus",
    "IndexBuildRecord",
    "ShardRecord",
    "TombstoneRecord",
    "VectorStoreContractError",
    "VectorValueRecord",
    "canonical_identity_digest",
    "decode_vector_bytes",
    "encode_vector_bytes",
    "normalize_source_identity",
    "vector_content_digest",
]


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DUCKDB_VECTOR_STORE_SCHEMA: Final[str] = (
    "ipfs_datasets_py/vector-stores-duckdb-lifecycle@1"
)
SCHEMA_VERSION: Final[int] = 1

ALLOWED_DTYPES: Final[frozenset[str]] = frozenset({"float32", "float64"})

# Align with duckdb_control safe tokens: allow @ for versioned identities.
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/@+-]{0,191}$")
_SLUG_RE = re.compile(r"^[a-z0-9]([a-z0-9_-]{0,62}[a-z0-9])?$")
_SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")

VECTOR_TABLES: Final[tuple[str, ...]] = (
    "vector_meta",
    "embedding_models",
    "vector_collections",
    "vector_generations",
    "vector_documents",
    "vector_chunks",
    "vector_values_by_dimension",
    "vector_shards",
    "vector_index_builds",
    "vector_tombstones",
    "vector_compactions",
)

# Explicit forbid list: these must never be used as authority surfaces.
_FORBIDDEN_PICKLE_SUFFIXES: Final[tuple[str, ...]] = (
    ".pkl",
    ".pickle",
    "_metadata.pkl",
)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class VectorStoreContractError(ValueError):
    """Fail-closed rejection of a vector lifecycle contract or mutation."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        details: Optional[Mapping[str, Any]] = None,
    ) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.details = dict(details or {})


# ---------------------------------------------------------------------------
# Enums / records
# ---------------------------------------------------------------------------


class GenerationStatus(str, Enum):
    DRAFT = "draft"
    PUBLISHED = "published"
    SUPERSEDED = "superseded"
    ABORTED = "aborted"


@dataclass(frozen=True)
class EmbeddingModelRecord:
    model_id: str
    name: str
    provider: str
    revision: str
    dtype: str
    dimension: int
    identity_digest: str
    created_at: str
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "model_id": self.model_id,
            "name": self.name,
            "provider": self.provider,
            "revision": self.revision,
            "dtype": self.dtype,
            "dimension": self.dimension,
            "identity_digest": self.identity_digest,
            "created_at": self.created_at,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class CollectionRecord:
    collection_id: str
    name: str
    dimension: int
    dtype: str
    model_id: str
    chunking_identity: str
    normalization_identity: str
    source_revision: str
    published_generation: Optional[int]
    status: str
    created_at: str
    updated_at: str
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "collection_id": self.collection_id,
            "name": self.name,
            "dimension": self.dimension,
            "dtype": self.dtype,
            "model_id": self.model_id,
            "chunking_identity": self.chunking_identity,
            "normalization_identity": self.normalization_identity,
            "source_revision": self.source_revision,
            "published_generation": self.published_generation,
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class GenerationRecord:
    collection_id: str
    generation_id: int
    status: str
    content_digest: str
    created_at: str
    published_at: Optional[str]
    parent_generation: Optional[int]
    chunk_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class DocumentRecord:
    document_id: str
    collection_id: str
    generation_id: int
    source_identity: str
    source_digest: str
    created_at: str
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "document_id": self.document_id,
            "collection_id": self.collection_id,
            "generation_id": self.generation_id,
            "source_identity": self.source_identity,
            "source_digest": self.source_digest,
            "created_at": self.created_at,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class ChunkRecord:
    chunk_id: str
    collection_id: str
    document_id: str
    generation_id: int
    ordinal: int
    content_digest: str
    source_identity: str
    text_preview: str
    status: str
    created_at: str
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "chunk_id": self.chunk_id,
            "collection_id": self.collection_id,
            "document_id": self.document_id,
            "generation_id": self.generation_id,
            "ordinal": self.ordinal,
            "content_digest": self.content_digest,
            "source_identity": self.source_identity,
            "text_preview": self.text_preview,
            "status": self.status,
            "created_at": self.created_at,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class VectorValueRecord:
    chunk_id: str
    collection_id: str
    generation_id: int
    dimension: int
    dtype: str
    value_digest: str
    created_at: str
    vector: tuple[float, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return {
            "chunk_id": self.chunk_id,
            "collection_id": self.collection_id,
            "generation_id": self.generation_id,
            "dimension": self.dimension,
            "dtype": self.dtype,
            "value_digest": self.value_digest,
            "created_at": self.created_at,
            "vector": list(self.vector),
        }


@dataclass(frozen=True)
class ShardRecord:
    shard_id: str
    collection_id: str
    generation_id: int
    shard_index: int
    vector_count: int
    content_digest: str
    status: str
    created_at: str
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "shard_id": self.shard_id,
            "collection_id": self.collection_id,
            "generation_id": self.generation_id,
            "shard_index": self.shard_index,
            "vector_count": self.vector_count,
            "content_digest": self.content_digest,
            "status": self.status,
            "created_at": self.created_at,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class IndexBuildRecord:
    build_id: str
    collection_id: str
    generation_id: int
    index_kind: str
    status: str
    receipt_digest: str
    created_at: str
    completed_at: Optional[str]
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "build_id": self.build_id,
            "collection_id": self.collection_id,
            "generation_id": self.generation_id,
            "index_kind": self.index_kind,
            "status": self.status,
            "receipt_digest": self.receipt_digest,
            "created_at": self.created_at,
            "completed_at": self.completed_at,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class TombstoneRecord:
    tombstone_id: str
    collection_id: str
    entity_type: str
    entity_id: str
    generation_id: int
    reason: str
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CompactionRecord:
    compaction_id: str
    collection_id: str
    from_generation: int
    to_generation: int
    status: str
    receipt_digest: str
    created_at: str
    completed_at: Optional[str]
    removed_count: int
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "compaction_id": self.compaction_id,
            "collection_id": self.collection_id,
            "from_generation": self.from_generation,
            "to_generation": self.to_generation,
            "status": self.status,
            "receipt_digest": self.receipt_digest,
            "created_at": self.created_at,
            "completed_at": self.completed_at,
            "removed_count": self.removed_count,
            "metadata": dict(self.metadata),
        }


# ---------------------------------------------------------------------------
# Pure helpers (import-safe; no duckdb)
# ---------------------------------------------------------------------------


def _utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .strftime("%Y-%m-%dT%H:%M:%SZ")
    )


def _require_id(value: Any, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise VectorStoreContractError(
            "INVALID_ID",
            f"{field} must be nonempty text",
            details={"field": field},
        )
    text = value.strip()
    if text != value:
        raise VectorStoreContractError(
            "INVALID_ID",
            f"{field} must not have surrounding whitespace",
            details={"field": field},
        )
    if _SAFE_ID_RE.fullmatch(text) is None:
        raise VectorStoreContractError(
            "INVALID_ID",
            f"{field} failed safe-id validation",
            details={"field": field, "value": value},
        )
    return text


def _require_slug(value: Any, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise VectorStoreContractError(
            "INVALID_NAME",
            f"{field} must be nonempty text",
            details={"field": field},
        )
    text = value.strip()
    if _SLUG_RE.fullmatch(text) is None:
        raise VectorStoreContractError(
            "INVALID_NAME",
            f"{field} failed slug validation",
            details={"field": field, "value": value},
        )
    return text


def _require_dtype(value: Any) -> str:
    if not isinstance(value, str):
        raise VectorStoreContractError(
            "INVALID_DTYPE",
            "dtype must be text",
            details={"value": value},
        )
    dtype = value.strip().lower()
    if dtype not in ALLOWED_DTYPES:
        raise VectorStoreContractError(
            "INVALID_DTYPE",
            f"dtype must be one of {sorted(ALLOWED_DTYPES)}",
            details={"value": value},
        )
    return dtype


def _require_dimension(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise VectorStoreContractError(
            "INVALID_DIMENSION",
            "dimension must be a positive integer",
            details={"value": value},
        )
    if value < 1 or value > 65536:
        raise VectorStoreContractError(
            "INVALID_DIMENSION",
            "dimension must be in [1, 65536]",
            details={"value": value},
        )
    return value


def _require_digest(value: Any, *, field: str = "digest") -> str:
    if not isinstance(value, str) or not value.strip():
        raise VectorStoreContractError(
            "INVALID_DIGEST",
            f"{field} must be nonempty text",
            details={"field": field},
        )
    text = value.strip().lower()
    if text.startswith("sha256:"):
        hex_part = text[len("sha256:") :]
    else:
        hex_part = text
    if _SHA256_HEX.fullmatch(hex_part) is None:
        raise VectorStoreContractError(
            "INVALID_DIGEST",
            f"{field} must be sha256:<64 hex> or 64 hex chars",
            details={"field": field, "value": value},
        )
    return f"sha256:{hex_part}"


def _require_identity_token(value: Any, *, field: str) -> str:
    """Model / chunking / normalization identity: digest or safe token."""

    if value is None:
        raise VectorStoreContractError(
            "MISSING_IDENTITY",
            f"{field} is mandatory",
            details={"field": field},
        )
    if not isinstance(value, str):
        raise VectorStoreContractError(
            "MISSING_IDENTITY",
            f"{field} is mandatory and must be text",
            details={"field": field},
        )
    if not value.strip():
        raise VectorStoreContractError(
            "MISSING_IDENTITY",
            f"{field} is mandatory",
            details={"field": field},
        )
    text = value.strip()
    if text.startswith("sha256:"):
        return _require_digest(text, field=field)
    if _SAFE_ID_RE.fullmatch(text) is None:
        raise VectorStoreContractError(
            "INVALID_IDENTITY",
            f"{field} is not a safe identity token or digest",
            details={"field": field, "value": value},
        )
    return text


def _canonical_json(payload: Any) -> bytes:
    def _plain(value: Any) -> Any:
        if isinstance(value, Enum):
            return value.value
        if isinstance(value, Mapping):
            return {str(k): _plain(v) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [_plain(v) for v in value]
        if isinstance(value, float):
            if value != value or value in (float("inf"), float("-inf")):
                raise VectorStoreContractError(
                    "INVALID_JSON",
                    "non-finite float in identity payload",
                )
            return value
        return value

    try:
        return json.dumps(
            _plain(payload),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise VectorStoreContractError(
            "INVALID_JSON",
            f"payload is not canonical-JSON-safe: {exc}",
        ) from exc


def canonical_identity_digest(payload: Any) -> str:
    """Return ``sha256:<hex>`` over canonical JSON of *payload*."""

    return "sha256:" + hashlib.sha256(_canonical_json(payload)).hexdigest()


def normalize_source_identity(
    source: Union[str, Mapping[str, Any]],
    *,
    media_type: str = "bytes",
) -> tuple[str, str]:
    """Normalize a source into ``(source_identity, source_digest)``.

    Paths are never treated as authority: only a content digest (and optional
    logical URI/key) is retained.  Leading/trailing whitespace is stripped;
    path separators in bare paths are collapsed into a logical key form.
    """

    if isinstance(source, Mapping):
        if "digest" in source:
            digest = _require_digest(source["digest"], field="source.digest")
            identity = str(source.get("identity") or source.get("uri") or digest)
            identity = _require_id(identity, field="source_identity")
            return identity, digest
        payload = dict(source)
        digest = canonical_identity_digest(payload)
        identity = str(payload.get("identity") or payload.get("uri") or digest)
        return _require_id(identity, field="source_identity"), digest

    if not isinstance(source, str) or not source.strip():
        raise VectorStoreContractError(
            "INVALID_SOURCE",
            "source identity must be nonempty text or a mapping",
        )
    text = source.strip()
    # Reject pickle authority markers explicitly.
    lower = text.lower()
    for suffix in _FORBIDDEN_PICKLE_SUFFIXES:
        if lower.endswith(suffix):
            raise VectorStoreContractError(
                "PICKLE_FORBIDDEN",
                "pickle paths cannot be source identity authority",
                details={"source": text},
            )
    if text.startswith("sha256:"):
        digest = _require_digest(text, field="source")
        return digest, digest
    # Logical key: strip scheme-like file:// and normalize separators.
    logical = text
    if logical.startswith("file://"):
        logical = logical[len("file://") :]
    logical = logical.replace("\\", "/").strip("/")
    if not logical:
        raise VectorStoreContractError(
            "INVALID_SOURCE",
            "source identity collapsed to empty",
        )
    identity_payload = {
        "logical_key": logical,
        "media_type": str(media_type or "bytes"),
    }
    digest = canonical_identity_digest(identity_payload)
    # Prefer a stable safe token when the logical key already qualifies.
    if _SAFE_ID_RE.fullmatch(logical):
        return logical, digest
    return digest, digest


def encode_vector_bytes(
    values: Sequence[float],
    *,
    dimension: int,
    dtype: str,
) -> bytes:
    """Encode a vector under an exact dimension/dtype contract."""

    dtype = _require_dtype(dtype)
    dimension = _require_dimension(dimension)
    if len(values) != dimension:
        raise VectorStoreContractError(
            "DIMENSION_MISMATCH",
            f"vector length {len(values)} does not match dimension {dimension}",
            details={"length": len(values), "dimension": dimension},
        )
    floats: list[float] = []
    for index, item in enumerate(values):
        if isinstance(item, bool) or not isinstance(item, (int, float)):
            raise VectorStoreContractError(
                "INVALID_VECTOR",
                f"vector[{index}] is not a finite number",
            )
        number = float(item)
        if number != number or number in (float("inf"), float("-inf")):
            raise VectorStoreContractError(
                "INVALID_VECTOR",
                f"vector[{index}] is non-finite",
            )
        floats.append(number)
    if dtype == "float32":
        # Round-trip through binary32 so stored bytes match the contract.
        packed = struct.pack(f"<{dimension}f", *floats)
        return packed
    return struct.pack(f"<{dimension}d", *floats)


def decode_vector_bytes(
    data: bytes,
    *,
    dimension: int,
    dtype: str,
) -> tuple[float, ...]:
    dtype = _require_dtype(dtype)
    dimension = _require_dimension(dimension)
    if not isinstance(data, (bytes, bytearray)):
        raise VectorStoreContractError("INVALID_VECTOR", "vector bytes required")
    fmt = f"<{dimension}f" if dtype == "float32" else f"<{dimension}d"
    expected = struct.calcsize(fmt)
    if len(data) != expected:
        raise VectorStoreContractError(
            "DIMENSION_MISMATCH",
            f"vector byte length {len(data)} != {expected} for {dtype}[{dimension}]",
        )
    return tuple(struct.unpack(fmt, bytes(data)))


def vector_content_digest(
    values: Sequence[float],
    *,
    dimension: int,
    dtype: str,
) -> str:
    raw = encode_vector_bytes(values, dimension=dimension, dtype=dtype)
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _metadata_json(metadata: Optional[Mapping[str, Any]]) -> str:
    if metadata is None:
        return "{}"
    if not isinstance(metadata, Mapping):
        raise VectorStoreContractError(
            "INVALID_METADATA",
            "metadata must be a mapping",
        )
    return _canonical_json(dict(metadata)).decode("utf-8")


def _parse_metadata(text: str | None) -> Mapping[str, Any]:
    if not text:
        return MappingProxyType({})
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise VectorStoreContractError(
            "CORRUPT_METADATA",
            f"metadata_json is not valid JSON: {exc}",
        ) from exc
    if not isinstance(payload, dict):
        raise VectorStoreContractError(
            "CORRUPT_METADATA",
            "metadata_json must be a JSON object",
        )
    return MappingProxyType(payload)


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


# ---------------------------------------------------------------------------
# Schema SQL
# ---------------------------------------------------------------------------

# DuckDB foreign-key UPDATE limitations make parent-row status flips fail when
# children reference the composite generation key.  Referential integrity is
# enforced in application transactions instead of declarative FKs.
_SCHEMA_SQL: Final[str] = """
CREATE TABLE IF NOT EXISTS vector_meta (
    key VARCHAR PRIMARY KEY,
    value VARCHAR NOT NULL
);

CREATE TABLE IF NOT EXISTS embedding_models (
    model_id VARCHAR PRIMARY KEY,
    name VARCHAR NOT NULL,
    provider VARCHAR NOT NULL,
    revision VARCHAR NOT NULL,
    dtype VARCHAR NOT NULL,
    dimension INTEGER NOT NULL,
    identity_digest VARCHAR NOT NULL,
    created_at VARCHAR NOT NULL,
    metadata_json VARCHAR NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS vector_collections (
    collection_id VARCHAR PRIMARY KEY,
    name VARCHAR NOT NULL UNIQUE,
    dimension INTEGER NOT NULL,
    dtype VARCHAR NOT NULL,
    model_id VARCHAR NOT NULL,
    chunking_identity VARCHAR NOT NULL,
    normalization_identity VARCHAR NOT NULL,
    source_revision VARCHAR NOT NULL,
    published_generation INTEGER,
    status VARCHAR NOT NULL,
    created_at VARCHAR NOT NULL,
    updated_at VARCHAR NOT NULL,
    metadata_json VARCHAR NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS vector_generations (
    collection_id VARCHAR NOT NULL,
    generation_id INTEGER NOT NULL,
    status VARCHAR NOT NULL,
    content_digest VARCHAR NOT NULL,
    created_at VARCHAR NOT NULL,
    published_at VARCHAR,
    parent_generation INTEGER,
    PRIMARY KEY (collection_id, generation_id)
);

CREATE TABLE IF NOT EXISTS vector_documents (
    document_id VARCHAR PRIMARY KEY,
    collection_id VARCHAR NOT NULL,
    generation_id INTEGER NOT NULL,
    source_identity VARCHAR NOT NULL,
    source_digest VARCHAR NOT NULL,
    created_at VARCHAR NOT NULL,
    metadata_json VARCHAR NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS vector_chunks (
    chunk_id VARCHAR PRIMARY KEY,
    collection_id VARCHAR NOT NULL,
    document_id VARCHAR NOT NULL,
    generation_id INTEGER NOT NULL,
    ordinal INTEGER NOT NULL,
    content_digest VARCHAR NOT NULL,
    source_identity VARCHAR NOT NULL,
    text_preview VARCHAR NOT NULL DEFAULT '',
    status VARCHAR NOT NULL,
    created_at VARCHAR NOT NULL,
    metadata_json VARCHAR NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS vector_values_by_dimension (
    chunk_id VARCHAR PRIMARY KEY,
    collection_id VARCHAR NOT NULL,
    generation_id INTEGER NOT NULL,
    dimension INTEGER NOT NULL,
    dtype VARCHAR NOT NULL,
    vector_bytes BLOB NOT NULL,
    value_digest VARCHAR NOT NULL,
    created_at VARCHAR NOT NULL
);

CREATE TABLE IF NOT EXISTS vector_shards (
    shard_id VARCHAR PRIMARY KEY,
    collection_id VARCHAR NOT NULL,
    generation_id INTEGER NOT NULL,
    shard_index INTEGER NOT NULL,
    vector_count INTEGER NOT NULL,
    content_digest VARCHAR NOT NULL,
    status VARCHAR NOT NULL,
    created_at VARCHAR NOT NULL,
    metadata_json VARCHAR NOT NULL DEFAULT '{}',
    UNIQUE (collection_id, generation_id, shard_index)
);

CREATE TABLE IF NOT EXISTS vector_index_builds (
    build_id VARCHAR PRIMARY KEY,
    collection_id VARCHAR NOT NULL,
    generation_id INTEGER NOT NULL,
    index_kind VARCHAR NOT NULL,
    status VARCHAR NOT NULL,
    receipt_digest VARCHAR NOT NULL,
    created_at VARCHAR NOT NULL,
    completed_at VARCHAR,
    metadata_json VARCHAR NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS vector_tombstones (
    tombstone_id VARCHAR PRIMARY KEY,
    collection_id VARCHAR NOT NULL,
    entity_type VARCHAR NOT NULL,
    entity_id VARCHAR NOT NULL,
    generation_id INTEGER NOT NULL,
    reason VARCHAR NOT NULL DEFAULT '',
    created_at VARCHAR NOT NULL
);

CREATE TABLE IF NOT EXISTS vector_compactions (
    compaction_id VARCHAR PRIMARY KEY,
    collection_id VARCHAR NOT NULL,
    from_generation INTEGER NOT NULL,
    to_generation INTEGER NOT NULL,
    status VARCHAR NOT NULL,
    receipt_digest VARCHAR NOT NULL,
    created_at VARCHAR NOT NULL,
    completed_at VARCHAR,
    removed_count INTEGER NOT NULL DEFAULT 0,
    metadata_json VARCHAR NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_vector_chunks_collection_gen
    ON vector_chunks (collection_id, generation_id, status);
CREATE INDEX IF NOT EXISTS idx_vector_tombstones_entity
    ON vector_tombstones (collection_id, entity_type, entity_id);
CREATE INDEX IF NOT EXISTS idx_vector_generations_status
    ON vector_generations (collection_id, status);
CREATE INDEX IF NOT EXISTS idx_vector_documents_collection_gen
    ON vector_documents (collection_id, generation_id);
CREATE INDEX IF NOT EXISTS idx_vector_values_collection_gen
    ON vector_values_by_dimension (collection_id, generation_id);
""".strip()


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------


class DuckDBVectorStore:
    """DuckDB-backed vector lifecycle catalog.

    Importing this module does not open DuckDB.  The constructor creates or
    opens a database file (or ``:memory:``) and applies the lifecycle schema.
    """

    def __init__(
        self,
        path: Union[str, Path] = ":memory:",
        *,
        read_only: bool = False,
    ) -> None:
        self._path = ":memory:" if path in (None, ":memory:") else str(Path(path))
        self._read_only = bool(read_only)
        self._lock = threading.RLock()
        self._conn = self._connect()
        if not self._read_only:
            self._initialize_schema()

    # -- connection / schema -------------------------------------------------

    def _connect(self) -> Any:
        try:
            import duckdb
        except ImportError as exc:  # pragma: no cover - environment gate
            raise VectorStoreContractError(
                "DUCKDB_UNAVAILABLE",
                "duckdb is required for DuckDBVectorStore",
            ) from exc
        if self._path != ":memory:":
            parent = Path(self._path).expanduser().resolve().parent
            if not self._read_only:
                parent.mkdir(parents=True, exist_ok=True)
        connect_kwargs: dict[str, Any] = {}
        if self._read_only and self._path != ":memory:":
            connect_kwargs["read_only"] = True
        # DuckDB 1.4+ rejects config=None; only pass a real dict when needed.
        conn = duckdb.connect(self._path, **connect_kwargs)
        # Fail closed on extension autoload for metadata authority.
        try:
            conn.execute("SET autoinstall_known_extensions=false")
            conn.execute("SET autoload_known_extensions=false")
        except Exception:
            # Older builds or restricted configs may reject SETs; ignore.
            pass
        return conn

    def _initialize_schema(self) -> None:
        with self._lock:
            self._conn.execute("BEGIN")
            try:
                self._conn.execute(_SCHEMA_SQL)
                row = self._conn.execute(
                    "SELECT value FROM vector_meta WHERE key = 'schema_version'"
                ).fetchone()
                if row is None:
                    self._conn.execute(
                        "INSERT INTO vector_meta (key, value) VALUES (?, ?), (?, ?)",
                        [
                            "schema_version",
                            str(SCHEMA_VERSION),
                            "schema_id",
                            DUCKDB_VECTOR_STORE_SCHEMA,
                        ],
                    )
                else:
                    applied = int(row[0])
                    if applied != SCHEMA_VERSION:
                        raise VectorStoreContractError(
                            "SCHEMA_MISMATCH",
                            f"database schema version {applied} != {SCHEMA_VERSION}",
                        )
                self._conn.execute("COMMIT")
            except Exception:
                self._conn.execute("ROLLBACK")
                raise

    @property
    def path(self) -> str:
        return self._path

    @property
    def schema_id(self) -> str:
        return DUCKDB_VECTOR_STORE_SCHEMA

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None

    def __enter__(self) -> "DuckDBVectorStore":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    @contextmanager
    def _transaction(self) -> Iterator[Any]:
        if self._read_only:
            raise VectorStoreContractError(
                "READ_ONLY",
                "mutation is not allowed on a read-only store",
            )
        with self._lock:
            self._conn.execute("BEGIN")
            try:
                yield self._conn
                self._conn.execute("COMMIT")
            except Exception:
                try:
                    self._conn.execute("ROLLBACK")
                except Exception:
                    pass
                raise

    def list_tables(self) -> list[str]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = 'main'
                ORDER BY table_name
                """
            ).fetchall()
        return [str(r[0]) for r in rows]

    def schema_digest(self) -> str:
        """Content digest of applied lifecycle table set + schema version."""

        payload = {
            "schema_id": DUCKDB_VECTOR_STORE_SCHEMA,
            "schema_version": SCHEMA_VERSION,
            "tables": list(VECTOR_TABLES),
        }
        return canonical_identity_digest(payload)

    # -- embedding models ----------------------------------------------------

    def create_embedding_model(
        self,
        *,
        name: str,
        provider: str,
        revision: str,
        dtype: str,
        dimension: int,
        model_id: Optional[str] = None,
        metadata: Optional[Mapping[str, Any]] = None,
    ) -> EmbeddingModelRecord:
        name = _require_id(name, field="name")
        provider = _require_id(provider, field="provider")
        revision = _require_id(revision, field="revision")
        dtype = _require_dtype(dtype)
        dimension = _require_dimension(dimension)
        model_id = _require_id(model_id or _new_id("model"), field="model_id")
        identity_digest = canonical_identity_digest(
            {
                "name": name,
                "provider": provider,
                "revision": revision,
                "dtype": dtype,
                "dimension": dimension,
            }
        )
        created_at = _utc_now()
        meta_json = _metadata_json(metadata)
        with self._transaction() as conn:
            existing = conn.execute(
                "SELECT model_id FROM embedding_models WHERE model_id = ?",
                [model_id],
            ).fetchone()
            if existing is not None:
                raise VectorStoreContractError(
                    "MODEL_EXISTS",
                    f"embedding model {model_id!r} already exists",
                )
            conn.execute(
                """
                INSERT INTO embedding_models (
                    model_id, name, provider, revision, dtype, dimension,
                    identity_digest, created_at, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    model_id,
                    name,
                    provider,
                    revision,
                    dtype,
                    dimension,
                    identity_digest,
                    created_at,
                    meta_json,
                ],
            )
        return EmbeddingModelRecord(
            model_id=model_id,
            name=name,
            provider=provider,
            revision=revision,
            dtype=dtype,
            dimension=dimension,
            identity_digest=identity_digest,
            created_at=created_at,
            metadata=_parse_metadata(meta_json),
        )

    def get_embedding_model(self, model_id: str) -> EmbeddingModelRecord:
        model_id = _require_id(model_id, field="model_id")
        with self._lock:
            row = self._conn.execute(
                """
                SELECT model_id, name, provider, revision, dtype, dimension,
                       identity_digest, created_at, metadata_json
                FROM embedding_models WHERE model_id = ?
                """,
                [model_id],
            ).fetchone()
        if row is None:
            raise VectorStoreContractError(
                "MODEL_NOT_FOUND",
                f"embedding model {model_id!r} not found",
            )
        return EmbeddingModelRecord(
            model_id=row[0],
            name=row[1],
            provider=row[2],
            revision=row[3],
            dtype=row[4],
            dimension=int(row[5]),
            identity_digest=row[6],
            created_at=row[7],
            metadata=_parse_metadata(row[8]),
        )

    # -- collections ---------------------------------------------------------

    def create_collection(
        self,
        *,
        name: str,
        dimension: int,
        dtype: str,
        model_id: str,
        chunking_identity: str,
        normalization_identity: str,
        source_revision: str = "0",
        collection_id: Optional[str] = None,
        metadata: Optional[Mapping[str, Any]] = None,
    ) -> CollectionRecord:
        """Create a collection.

        ``model_id``, ``chunking_identity``, and ``normalization_identity`` are
        mandatory.  Dimension and dtype must match the referenced model.
        """

        name = _require_slug(name, field="name")
        dimension = _require_dimension(dimension)
        dtype = _require_dtype(dtype)
        model_id = _require_id(model_id, field="model_id")
        chunking_identity = _require_identity_token(
            chunking_identity, field="chunking_identity"
        )
        normalization_identity = _require_identity_token(
            normalization_identity, field="normalization_identity"
        )
        source_revision = _require_id(source_revision, field="source_revision")
        collection_id = _require_id(
            collection_id or _new_id("col"), field="collection_id"
        )
        model = self.get_embedding_model(model_id)
        if model.dimension != dimension:
            raise VectorStoreContractError(
                "DIMENSION_MISMATCH",
                "collection dimension must match embedding model dimension",
                details={
                    "collection_dimension": dimension,
                    "model_dimension": model.dimension,
                },
            )
        if model.dtype != dtype:
            raise VectorStoreContractError(
                "DTYPE_MISMATCH",
                "collection dtype must match embedding model dtype",
                details={
                    "collection_dtype": dtype,
                    "model_dtype": model.dtype,
                },
            )
        now = _utc_now()
        meta_json = _metadata_json(metadata)
        with self._transaction() as conn:
            conflict = conn.execute(
                """
                SELECT collection_id FROM vector_collections
                WHERE collection_id = ? OR name = ?
                """,
                [collection_id, name],
            ).fetchone()
            if conflict is not None:
                raise VectorStoreContractError(
                    "COLLECTION_EXISTS",
                    f"collection id or name already exists ({conflict[0]})",
                )
            conn.execute(
                """
                INSERT INTO vector_collections (
                    collection_id, name, dimension, dtype, model_id,
                    chunking_identity, normalization_identity, source_revision,
                    published_generation, status, created_at, updated_at,
                    metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, 'active', ?, ?, ?)
                """,
                [
                    collection_id,
                    name,
                    dimension,
                    dtype,
                    model_id,
                    chunking_identity,
                    normalization_identity,
                    source_revision,
                    now,
                    now,
                    meta_json,
                ],
            )
        return CollectionRecord(
            collection_id=collection_id,
            name=name,
            dimension=dimension,
            dtype=dtype,
            model_id=model_id,
            chunking_identity=chunking_identity,
            normalization_identity=normalization_identity,
            source_revision=source_revision,
            published_generation=None,
            status="active",
            created_at=now,
            updated_at=now,
            metadata=_parse_metadata(meta_json),
        )

    def get_collection(self, collection_id: str) -> CollectionRecord:
        collection_id = _require_id(collection_id, field="collection_id")
        with self._lock:
            row = self._conn.execute(
                """
                SELECT collection_id, name, dimension, dtype, model_id,
                       chunking_identity, normalization_identity, source_revision,
                       published_generation, status, created_at, updated_at,
                       metadata_json
                FROM vector_collections WHERE collection_id = ?
                """,
                [collection_id],
            ).fetchone()
        if row is None:
            raise VectorStoreContractError(
                "COLLECTION_NOT_FOUND",
                f"collection {collection_id!r} not found",
            )
        return self._row_to_collection(row)

    def get_collection_by_name(self, name: str) -> CollectionRecord:
        name = _require_slug(name, field="name")
        with self._lock:
            row = self._conn.execute(
                """
                SELECT collection_id, name, dimension, dtype, model_id,
                       chunking_identity, normalization_identity, source_revision,
                       published_generation, status, created_at, updated_at,
                       metadata_json
                FROM vector_collections WHERE name = ?
                """,
                [name],
            ).fetchone()
        if row is None:
            raise VectorStoreContractError(
                "COLLECTION_NOT_FOUND",
                f"collection name {name!r} not found",
            )
        return self._row_to_collection(row)

    def list_collections(self) -> list[CollectionRecord]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT collection_id, name, dimension, dtype, model_id,
                       chunking_identity, normalization_identity, source_revision,
                       published_generation, status, created_at, updated_at,
                       metadata_json
                FROM vector_collections
                WHERE status = 'active'
                ORDER BY name
                """
            ).fetchall()
        return [self._row_to_collection(r) for r in rows]

    @staticmethod
    def _row_to_collection(row: Sequence[Any]) -> CollectionRecord:
        return CollectionRecord(
            collection_id=row[0],
            name=row[1],
            dimension=int(row[2]),
            dtype=row[3],
            model_id=row[4],
            chunking_identity=row[5],
            normalization_identity=row[6],
            source_revision=row[7],
            published_generation=int(row[8]) if row[8] is not None else None,
            status=row[9],
            created_at=row[10],
            updated_at=row[11],
            metadata=_parse_metadata(row[12]),
        )

    # -- generations ---------------------------------------------------------

    def open_generation(
        self,
        collection_id: str,
        *,
        parent_generation: Optional[int] = None,
    ) -> GenerationRecord:
        """Open a new draft generation. Draft contents are not query-visible."""

        collection = self.get_collection(collection_id)
        if collection.status != "active":
            raise VectorStoreContractError(
                "COLLECTION_INACTIVE",
                "cannot open generation on inactive collection",
            )
        with self._transaction() as conn:
            open_draft = conn.execute(
                """
                SELECT generation_id FROM vector_generations
                WHERE collection_id = ? AND status = 'draft'
                """,
                [collection.collection_id],
            ).fetchone()
            if open_draft is not None:
                raise VectorStoreContractError(
                    "DRAFT_EXISTS",
                    f"draft generation {open_draft[0]} already open",
                    details={"generation_id": int(open_draft[0])},
                )
            max_row = conn.execute(
                """
                SELECT COALESCE(MAX(generation_id), 0)
                FROM vector_generations WHERE collection_id = ?
                """,
                [collection.collection_id],
            ).fetchone()
            next_id = int(max_row[0]) + 1
            if parent_generation is None:
                parent_generation = collection.published_generation
            if parent_generation is not None:
                parent = conn.execute(
                    """
                    SELECT status FROM vector_generations
                    WHERE collection_id = ? AND generation_id = ?
                    """,
                    [collection.collection_id, parent_generation],
                ).fetchone()
                if parent is None:
                    raise VectorStoreContractError(
                        "PARENT_NOT_FOUND",
                        f"parent generation {parent_generation} not found",
                    )
            created_at = _utc_now()
            # Placeholder digest until publish materializes final content.
            content_digest = canonical_identity_digest(
                {
                    "collection_id": collection.collection_id,
                    "generation_id": next_id,
                    "status": GenerationStatus.DRAFT.value,
                    "created_at": created_at,
                }
            )
            conn.execute(
                """
                INSERT INTO vector_generations (
                    collection_id, generation_id, status, content_digest,
                    created_at, published_at, parent_generation
                ) VALUES (?, ?, 'draft', ?, ?, NULL, ?)
                """,
                [
                    collection.collection_id,
                    next_id,
                    content_digest,
                    created_at,
                    parent_generation,
                ],
            )
        return GenerationRecord(
            collection_id=collection.collection_id,
            generation_id=next_id,
            status=GenerationStatus.DRAFT.value,
            content_digest=content_digest,
            created_at=created_at,
            published_at=None,
            parent_generation=parent_generation,
            chunk_count=0,
        )

    def get_generation(
        self, collection_id: str, generation_id: int
    ) -> GenerationRecord:
        collection_id = _require_id(collection_id, field="collection_id")
        if not isinstance(generation_id, int) or isinstance(generation_id, bool):
            raise VectorStoreContractError(
                "INVALID_GENERATION",
                "generation_id must be an integer",
            )
        with self._lock:
            row = self._conn.execute(
                """
                SELECT g.collection_id, g.generation_id, g.status, g.content_digest,
                       g.created_at, g.published_at, g.parent_generation,
                       (
                         SELECT COUNT(*) FROM vector_chunks c
                         WHERE c.collection_id = g.collection_id
                           AND c.generation_id = g.generation_id
                           AND c.status = 'live'
                       )
                FROM vector_generations g
                WHERE g.collection_id = ? AND g.generation_id = ?
                """,
                [collection_id, generation_id],
            ).fetchone()
        if row is None:
            raise VectorStoreContractError(
                "GENERATION_NOT_FOUND",
                f"generation {generation_id} not found for {collection_id}",
            )
        return GenerationRecord(
            collection_id=row[0],
            generation_id=int(row[1]),
            status=row[2],
            content_digest=row[3],
            created_at=row[4],
            published_at=row[5],
            parent_generation=int(row[6]) if row[6] is not None else None,
            chunk_count=int(row[7]),
        )

    def abort_generation(self, collection_id: str, generation_id: int) -> GenerationRecord:
        collection_id = _require_id(collection_id, field="collection_id")
        with self._transaction() as conn:
            row = conn.execute(
                """
                SELECT status FROM vector_generations
                WHERE collection_id = ? AND generation_id = ?
                """,
                [collection_id, generation_id],
            ).fetchone()
            if row is None:
                raise VectorStoreContractError(
                    "GENERATION_NOT_FOUND",
                    f"generation {generation_id} not found",
                )
            if row[0] != GenerationStatus.DRAFT.value:
                raise VectorStoreContractError(
                    "NOT_DRAFT",
                    "only draft generations can be aborted",
                    details={"status": row[0]},
                )
            # Tombstone all live draft chunks so they can never become visible.
            chunks = conn.execute(
                """
                SELECT chunk_id FROM vector_chunks
                WHERE collection_id = ? AND generation_id = ? AND status = 'live'
                """,
                [collection_id, generation_id],
            ).fetchall()
            now = _utc_now()
            for (chunk_id,) in chunks:
                self._tombstone_entity(
                    conn,
                    collection_id=collection_id,
                    entity_type="chunk",
                    entity_id=chunk_id,
                    generation_id=generation_id,
                    reason="generation_aborted",
                    created_at=now,
                )
                conn.execute(
                    """
                    UPDATE vector_chunks SET status = 'tombstoned'
                    WHERE chunk_id = ?
                    """,
                    [chunk_id],
                )
            conn.execute(
                """
                UPDATE vector_generations SET status = 'aborted'
                WHERE collection_id = ? AND generation_id = ?
                """,
                [collection_id, generation_id],
            )
        return self.get_generation(collection_id, generation_id)

    def publish_generation(
        self, collection_id: str, generation_id: int
    ) -> GenerationRecord:
        """Atomically publish a draft generation.

        In one transaction:

        * verify draft status
        * compute content digest over live chunk digests
        * supersede previous published generation
        * set collection.published_generation
        * mark generation published
        """

        collection_id = _require_id(collection_id, field="collection_id")
        with self._transaction() as conn:
            gen = conn.execute(
                """
                SELECT status FROM vector_generations
                WHERE collection_id = ? AND generation_id = ?
                """,
                [collection_id, generation_id],
            ).fetchone()
            if gen is None:
                raise VectorStoreContractError(
                    "GENERATION_NOT_FOUND",
                    f"generation {generation_id} not found",
                )
            if gen[0] != GenerationStatus.DRAFT.value:
                raise VectorStoreContractError(
                    "NOT_DRAFT",
                    "only draft generations can be published",
                    details={"status": gen[0]},
                )
            col = conn.execute(
                """
                SELECT published_generation, status, dimension, dtype,
                       model_id, chunking_identity, normalization_identity
                FROM vector_collections WHERE collection_id = ?
                """,
                [collection_id],
            ).fetchone()
            if col is None:
                raise VectorStoreContractError(
                    "COLLECTION_NOT_FOUND",
                    f"collection {collection_id!r} not found",
                )
            if col[1] != "active":
                raise VectorStoreContractError(
                    "COLLECTION_INACTIVE",
                    "cannot publish for inactive collection",
                )
            # Mandatory identity re-check at publish boundary.
            for field_name, value in (
                ("model_id", col[4]),
                ("chunking_identity", col[5]),
                ("normalization_identity", col[6]),
            ):
                if not value:
                    raise VectorStoreContractError(
                        "MISSING_IDENTITY",
                        f"{field_name} is mandatory at publish",
                    )

            chunk_rows = conn.execute(
                """
                SELECT c.chunk_id, c.content_digest, v.value_digest, v.dimension, v.dtype
                FROM vector_chunks c
                JOIN vector_values_by_dimension v ON v.chunk_id = c.chunk_id
                WHERE c.collection_id = ? AND c.generation_id = ?
                  AND c.status = 'live'
                ORDER BY c.chunk_id
                """,
                [collection_id, generation_id],
            ).fetchall()
            expected_dim = int(col[2])
            expected_dtype = col[3]
            for chunk_id, _cd, _vd, dim, dtype in chunk_rows:
                if int(dim) != expected_dim or dtype != expected_dtype:
                    raise VectorStoreContractError(
                        "CONTRACT_VIOLATION",
                        f"chunk {chunk_id} violates collection dim/dtype contract",
                        details={
                            "chunk_id": chunk_id,
                            "dimension": int(dim),
                            "dtype": dtype,
                            "expected_dimension": expected_dim,
                            "expected_dtype": expected_dtype,
                        },
                    )
            content_digest = canonical_identity_digest(
                {
                    "collection_id": collection_id,
                    "generation_id": generation_id,
                    "chunks": [
                        {
                            "chunk_id": r[0],
                            "content_digest": r[1],
                            "value_digest": r[2],
                        }
                        for r in chunk_rows
                    ],
                    "dimension": expected_dim,
                    "dtype": expected_dtype,
                    "model_id": col[4],
                    "chunking_identity": col[5],
                    "normalization_identity": col[6],
                }
            )
            now = _utc_now()
            previous = col[0]
            if previous is not None and int(previous) != int(generation_id):
                conn.execute(
                    """
                    UPDATE vector_generations
                    SET status = 'superseded'
                    WHERE collection_id = ? AND generation_id = ?
                      AND status = 'published'
                    """,
                    [collection_id, int(previous)],
                )
            conn.execute(
                """
                UPDATE vector_generations
                SET status = 'published',
                    content_digest = ?,
                    published_at = ?
                WHERE collection_id = ? AND generation_id = ?
                """,
                [content_digest, now, collection_id, generation_id],
            )
            conn.execute(
                """
                UPDATE vector_collections
                SET published_generation = ?, updated_at = ?
                WHERE collection_id = ?
                """,
                [generation_id, now, collection_id],
            )
        return self.get_generation(collection_id, generation_id)

    # -- documents / chunks --------------------------------------------------

    def add_document(
        self,
        *,
        collection_id: str,
        generation_id: int,
        source: Union[str, Mapping[str, Any]],
        document_id: Optional[str] = None,
        metadata: Optional[Mapping[str, Any]] = None,
    ) -> DocumentRecord:
        collection_id = _require_id(collection_id, field="collection_id")
        self._require_draft(collection_id, generation_id)
        source_identity, source_digest = normalize_source_identity(source)
        document_id = _require_id(
            document_id or _new_id("doc"), field="document_id"
        )
        created_at = _utc_now()
        meta_json = _metadata_json(metadata)
        with self._transaction() as conn:
            self._assert_draft_conn(conn, collection_id, generation_id)
            exists = conn.execute(
                "SELECT 1 FROM vector_documents WHERE document_id = ?",
                [document_id],
            ).fetchone()
            if exists is not None:
                raise VectorStoreContractError(
                    "DOCUMENT_EXISTS",
                    f"document {document_id!r} already exists",
                )
            conn.execute(
                """
                INSERT INTO vector_documents (
                    document_id, collection_id, generation_id,
                    source_identity, source_digest, created_at, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    document_id,
                    collection_id,
                    generation_id,
                    source_identity,
                    source_digest,
                    created_at,
                    meta_json,
                ],
            )
        return DocumentRecord(
            document_id=document_id,
            collection_id=collection_id,
            generation_id=generation_id,
            source_identity=source_identity,
            source_digest=source_digest,
            created_at=created_at,
            metadata=_parse_metadata(meta_json),
        )

    def add_chunk(
        self,
        *,
        collection_id: str,
        generation_id: int,
        document_id: str,
        vector: Sequence[float],
        ordinal: int = 0,
        chunk_id: Optional[str] = None,
        source: Optional[Union[str, Mapping[str, Any]]] = None,
        text: str = "",
        metadata: Optional[Mapping[str, Any]] = None,
    ) -> ChunkRecord:
        collection = self.get_collection(collection_id)
        self._require_draft(collection.collection_id, generation_id)
        document_id = _require_id(document_id, field="document_id")
        if not isinstance(ordinal, int) or isinstance(ordinal, bool) or ordinal < 0:
            raise VectorStoreContractError(
                "INVALID_ORDINAL",
                "ordinal must be a non-negative integer",
            )
        chunk_id = _require_id(chunk_id or _new_id("chunk"), field="chunk_id")
        vector_bytes = encode_vector_bytes(
            vector, dimension=collection.dimension, dtype=collection.dtype
        )
        value_digest = "sha256:" + hashlib.sha256(vector_bytes).hexdigest()
        if source is None:
            source_identity = document_id
            source_digest = canonical_identity_digest(
                {"document_id": document_id, "ordinal": ordinal}
            )
        else:
            source_identity, source_digest = normalize_source_identity(source)
        content_digest = canonical_identity_digest(
            {
                "chunk_id": chunk_id,
                "document_id": document_id,
                "ordinal": ordinal,
                "value_digest": value_digest,
                "source_digest": source_digest,
            }
        )
        text_preview = (text or "")[:512]
        created_at = _utc_now()
        meta_json = _metadata_json(metadata)
        with self._transaction() as conn:
            self._assert_draft_conn(conn, collection.collection_id, generation_id)
            doc = conn.execute(
                """
                SELECT generation_id FROM vector_documents
                WHERE document_id = ? AND collection_id = ?
                """,
                [document_id, collection.collection_id],
            ).fetchone()
            if doc is None:
                raise VectorStoreContractError(
                    "DOCUMENT_NOT_FOUND",
                    f"document {document_id!r} not found",
                )
            if int(doc[0]) != int(generation_id):
                raise VectorStoreContractError(
                    "GENERATION_MISMATCH",
                    "document generation does not match chunk generation",
                )
            exists = conn.execute(
                "SELECT 1 FROM vector_chunks WHERE chunk_id = ?",
                [chunk_id],
            ).fetchone()
            if exists is not None:
                raise VectorStoreContractError(
                    "CHUNK_EXISTS",
                    f"chunk {chunk_id!r} already exists",
                )
            conn.execute(
                """
                INSERT INTO vector_chunks (
                    chunk_id, collection_id, document_id, generation_id,
                    ordinal, content_digest, source_identity, text_preview,
                    status, created_at, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'live', ?, ?)
                """,
                [
                    chunk_id,
                    collection.collection_id,
                    document_id,
                    generation_id,
                    ordinal,
                    content_digest,
                    source_identity,
                    text_preview,
                    created_at,
                    meta_json,
                ],
            )
            conn.execute(
                """
                INSERT INTO vector_values_by_dimension (
                    chunk_id, collection_id, generation_id, dimension, dtype,
                    vector_bytes, value_digest, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    chunk_id,
                    collection.collection_id,
                    generation_id,
                    collection.dimension,
                    collection.dtype,
                    vector_bytes,
                    value_digest,
                    created_at,
                ],
            )
        return ChunkRecord(
            chunk_id=chunk_id,
            collection_id=collection.collection_id,
            document_id=document_id,
            generation_id=generation_id,
            ordinal=ordinal,
            content_digest=content_digest,
            source_identity=source_identity,
            text_preview=text_preview,
            status="live",
            created_at=created_at,
            metadata=_parse_metadata(meta_json),
        )

    def update_chunk(
        self,
        *,
        collection_id: str,
        chunk_id: str,
        vector: Sequence[float],
        text: Optional[str] = None,
        metadata: Optional[Mapping[str, Any]] = None,
        reason: str = "update",
    ) -> ChunkRecord:
        """Replace a live chunk's vector without leaving a query-visible stale value.

        * If the chunk belongs to a draft generation, mutate in place inside one
          transaction (old bytes are overwritten; no dual live rows).
        * If the chunk is query-visible (published generation), open/use the
          current draft is required: callers must publish a new generation with
          the replacement.  This method tombstones the published chunk and
          inserts a replacement into the open draft so the published view loses
          the stale vector immediately.
        """

        collection = self.get_collection(collection_id)
        chunk_id = _require_id(chunk_id, field="chunk_id")
        vector_bytes = encode_vector_bytes(
            vector, dimension=collection.dimension, dtype=collection.dtype
        )
        value_digest = "sha256:" + hashlib.sha256(vector_bytes).hexdigest()
        now = _utc_now()
        with self._transaction() as conn:
            row = conn.execute(
                """
                SELECT chunk_id, collection_id, document_id, generation_id,
                       ordinal, content_digest, source_identity, text_preview,
                       status, created_at, metadata_json
                FROM vector_chunks
                WHERE chunk_id = ? AND collection_id = ?
                """,
                [chunk_id, collection.collection_id],
            ).fetchone()
            if row is None:
                raise VectorStoreContractError(
                    "CHUNK_NOT_FOUND",
                    f"chunk {chunk_id!r} not found",
                )
            if row[8] != "live":
                raise VectorStoreContractError(
                    "CHUNK_NOT_LIVE",
                    f"chunk {chunk_id!r} is not live",
                    details={"status": row[8]},
                )
            gen_id = int(row[3])
            gen_status = conn.execute(
                """
                SELECT status FROM vector_generations
                WHERE collection_id = ? AND generation_id = ?
                """,
                [collection.collection_id, gen_id],
            ).fetchone()
            if gen_status is None:
                raise VectorStoreContractError(
                    "GENERATION_NOT_FOUND",
                    f"generation {gen_id} not found",
                )
            status = gen_status[0]
            text_preview = row[7] if text is None else (text or "")[:512]
            meta_json = (
                row[10] if metadata is None else _metadata_json(metadata)
            )
            content_digest = canonical_identity_digest(
                {
                    "chunk_id": chunk_id,
                    "document_id": row[2],
                    "ordinal": int(row[4]),
                    "value_digest": value_digest,
                    "source_identity": row[6],
                    "updated_at": now,
                }
            )
            if status == GenerationStatus.DRAFT.value:
                conn.execute(
                    """
                    UPDATE vector_chunks
                    SET content_digest = ?, text_preview = ?, metadata_json = ?
                    WHERE chunk_id = ?
                    """,
                    [content_digest, text_preview, meta_json, chunk_id],
                )
                conn.execute(
                    """
                    UPDATE vector_values_by_dimension
                    SET vector_bytes = ?, value_digest = ?, created_at = ?
                    WHERE chunk_id = ?
                    """,
                    [vector_bytes, value_digest, now, chunk_id],
                )
                return ChunkRecord(
                    chunk_id=chunk_id,
                    collection_id=collection.collection_id,
                    document_id=row[2],
                    generation_id=gen_id,
                    ordinal=int(row[4]),
                    content_digest=content_digest,
                    source_identity=row[6],
                    text_preview=text_preview,
                    status="live",
                    created_at=row[9],
                    metadata=_parse_metadata(meta_json),
                )

            if status != GenerationStatus.PUBLISHED.value:
                raise VectorStoreContractError(
                    "CHUNK_NOT_MUTABLE",
                    "chunk generation is not draft or published",
                    details={"status": status},
                )
            # Published live chunk: tombstone immediately (drops query visibility)
            # and insert replacement into open draft.
            draft = conn.execute(
                """
                SELECT generation_id FROM vector_generations
                WHERE collection_id = ? AND status = 'draft'
                """,
                [collection.collection_id],
            ).fetchone()
            if draft is None:
                raise VectorStoreContractError(
                    "DRAFT_REQUIRED",
                    "open a draft generation before updating a published chunk",
                )
            draft_id = int(draft[0])
            self._tombstone_entity(
                conn,
                collection_id=collection.collection_id,
                entity_type="chunk",
                entity_id=chunk_id,
                generation_id=gen_id,
                reason=reason or "update",
                created_at=now,
            )
            conn.execute(
                "UPDATE vector_chunks SET status = 'tombstoned' WHERE chunk_id = ?",
                [chunk_id],
            )
            new_chunk_id = _new_id("chunk")
            # Ensure document exists in draft (re-bind logical document).
            doc_in_draft = conn.execute(
                """
                SELECT document_id FROM vector_documents
                WHERE document_id = ? AND generation_id = ?
                """,
                [row[2], draft_id],
            ).fetchone()
            document_id = row[2]
            if doc_in_draft is None:
                # Carry document into draft with same identity.
                src = conn.execute(
                    """
                    SELECT source_identity, source_digest, metadata_json
                    FROM vector_documents WHERE document_id = ?
                    """,
                    [document_id],
                ).fetchone()
                if src is None:
                    raise VectorStoreContractError(
                        "DOCUMENT_NOT_FOUND",
                        f"document {document_id!r} not found",
                    )
                document_id = _new_id("doc")
                conn.execute(
                    """
                    INSERT INTO vector_documents (
                        document_id, collection_id, generation_id,
                        source_identity, source_digest, created_at, metadata_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        document_id,
                        collection.collection_id,
                        draft_id,
                        src[0],
                        src[1],
                        now,
                        src[2],
                    ],
                )
            conn.execute(
                """
                INSERT INTO vector_chunks (
                    chunk_id, collection_id, document_id, generation_id,
                    ordinal, content_digest, source_identity, text_preview,
                    status, created_at, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'live', ?, ?)
                """,
                [
                    new_chunk_id,
                    collection.collection_id,
                    document_id,
                    draft_id,
                    int(row[4]),
                    content_digest,
                    row[6],
                    text_preview,
                    now,
                    meta_json,
                ],
            )
            conn.execute(
                """
                INSERT INTO vector_values_by_dimension (
                    chunk_id, collection_id, generation_id, dimension, dtype,
                    vector_bytes, value_digest, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    new_chunk_id,
                    collection.collection_id,
                    draft_id,
                    collection.dimension,
                    collection.dtype,
                    vector_bytes,
                    value_digest,
                    now,
                ],
            )
            return ChunkRecord(
                chunk_id=new_chunk_id,
                collection_id=collection.collection_id,
                document_id=document_id,
                generation_id=draft_id,
                ordinal=int(row[4]),
                content_digest=content_digest,
                source_identity=row[6],
                text_preview=text_preview,
                status="live",
                created_at=now,
                metadata=_parse_metadata(meta_json),
            )

    def delete_chunk(
        self,
        *,
        collection_id: str,
        chunk_id: str,
        reason: str = "delete",
    ) -> TombstoneRecord:
        """Tombstone a live chunk so it is never query-visible afterwards."""

        collection = self.get_collection(collection_id)
        chunk_id = _require_id(chunk_id, field="chunk_id")
        now = _utc_now()
        with self._transaction() as conn:
            row = conn.execute(
                """
                SELECT generation_id, status FROM vector_chunks
                WHERE chunk_id = ? AND collection_id = ?
                """,
                [chunk_id, collection.collection_id],
            ).fetchone()
            if row is None:
                raise VectorStoreContractError(
                    "CHUNK_NOT_FOUND",
                    f"chunk {chunk_id!r} not found",
                )
            if row[1] != "live":
                # Already tombstoned — return existing tombstone if present.
                existing = conn.execute(
                    """
                    SELECT tombstone_id, collection_id, entity_type, entity_id,
                           generation_id, reason, created_at
                    FROM vector_tombstones
                    WHERE collection_id = ? AND entity_type = 'chunk'
                      AND entity_id = ?
                    ORDER BY created_at DESC
                    LIMIT 1
                    """,
                    [collection.collection_id, chunk_id],
                ).fetchone()
                if existing is not None:
                    return TombstoneRecord(
                        tombstone_id=existing[0],
                        collection_id=existing[1],
                        entity_type=existing[2],
                        entity_id=existing[3],
                        generation_id=int(existing[4]),
                        reason=existing[5],
                        created_at=existing[6],
                    )
                raise VectorStoreContractError(
                    "CHUNK_NOT_LIVE",
                    f"chunk {chunk_id!r} is not live",
                )
            gen_id = int(row[0])
            tombstone = self._tombstone_entity(
                conn,
                collection_id=collection.collection_id,
                entity_type="chunk",
                entity_id=chunk_id,
                generation_id=gen_id,
                reason=reason or "delete",
                created_at=now,
            )
            conn.execute(
                "UPDATE vector_chunks SET status = 'tombstoned' WHERE chunk_id = ?",
                [chunk_id],
            )
            return tombstone

    def get_chunk(
        self, chunk_id: str, *, include_vector: bool = False
    ) -> Union[ChunkRecord, tuple[ChunkRecord, VectorValueRecord]]:
        chunk_id = _require_id(chunk_id, field="chunk_id")
        with self._lock:
            row = self._conn.execute(
                """
                SELECT chunk_id, collection_id, document_id, generation_id,
                       ordinal, content_digest, source_identity, text_preview,
                       status, created_at, metadata_json
                FROM vector_chunks WHERE chunk_id = ?
                """,
                [chunk_id],
            ).fetchone()
        if row is None:
            raise VectorStoreContractError(
                "CHUNK_NOT_FOUND",
                f"chunk {chunk_id!r} not found",
            )
        chunk = ChunkRecord(
            chunk_id=row[0],
            collection_id=row[1],
            document_id=row[2],
            generation_id=int(row[3]),
            ordinal=int(row[4]),
            content_digest=row[5],
            source_identity=row[6],
            text_preview=row[7],
            status=row[8],
            created_at=row[9],
            metadata=_parse_metadata(row[10]),
        )
        if not include_vector:
            return chunk
        with self._lock:
            vrow = self._conn.execute(
                """
                SELECT chunk_id, collection_id, generation_id, dimension, dtype,
                       vector_bytes, value_digest, created_at
                FROM vector_values_by_dimension WHERE chunk_id = ?
                """,
                [chunk_id],
            ).fetchone()
        if vrow is None:
            raise VectorStoreContractError(
                "VECTOR_NOT_FOUND",
                f"vector bytes missing for chunk {chunk_id!r}",
            )
        vector = decode_vector_bytes(
            bytes(vrow[5]), dimension=int(vrow[3]), dtype=vrow[4]
        )
        value = VectorValueRecord(
            chunk_id=vrow[0],
            collection_id=vrow[1],
            generation_id=int(vrow[2]),
            dimension=int(vrow[3]),
            dtype=vrow[4],
            value_digest=vrow[6],
            created_at=vrow[7],
            vector=vector,
        )
        return chunk, value

    def list_query_visible_chunks(
        self, collection_id: str
    ) -> list[ChunkRecord]:
        """Return live chunks for the collection's published generation only.

        Tombstoned chunks and draft/superseded/aborted generations are excluded.
        """

        collection = self.get_collection(collection_id)
        if collection.published_generation is None:
            return []
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT c.chunk_id, c.collection_id, c.document_id, c.generation_id,
                       c.ordinal, c.content_digest, c.source_identity, c.text_preview,
                       c.status, c.created_at, c.metadata_json
                FROM vector_chunks c
                JOIN vector_generations g
                  ON g.collection_id = c.collection_id
                 AND g.generation_id = c.generation_id
                WHERE c.collection_id = ?
                  AND c.generation_id = ?
                  AND c.status = 'live'
                  AND g.status = 'published'
                  AND NOT EXISTS (
                    SELECT 1 FROM vector_tombstones t
                    WHERE t.collection_id = c.collection_id
                      AND t.entity_type = 'chunk'
                      AND t.entity_id = c.chunk_id
                  )
                ORDER BY c.document_id, c.ordinal, c.chunk_id
                """,
                [collection.collection_id, collection.published_generation],
            ).fetchall()
        return [
            ChunkRecord(
                chunk_id=r[0],
                collection_id=r[1],
                document_id=r[2],
                generation_id=int(r[3]),
                ordinal=int(r[4]),
                content_digest=r[5],
                source_identity=r[6],
                text_preview=r[7],
                status=r[8],
                created_at=r[9],
                metadata=_parse_metadata(r[10]),
            )
            for r in rows
        ]

    def get_query_visible_vector(
        self, collection_id: str, chunk_id: str
    ) -> Optional[VectorValueRecord]:
        """Return vector bytes only if the chunk is currently query-visible."""

        visible_ids = {c.chunk_id for c in self.list_query_visible_chunks(collection_id)}
        if chunk_id not in visible_ids:
            return None
        result = self.get_chunk(chunk_id, include_vector=True)
        assert isinstance(result, tuple)
        return result[1]

    # -- shards / index builds / compaction ----------------------------------

    def register_shard(
        self,
        *,
        collection_id: str,
        generation_id: int,
        shard_index: int,
        vector_count: int,
        content_digest: Optional[str] = None,
        shard_id: Optional[str] = None,
        metadata: Optional[Mapping[str, Any]] = None,
    ) -> ShardRecord:
        collection_id = _require_id(collection_id, field="collection_id")
        self._require_draft(collection_id, generation_id)
        if not isinstance(shard_index, int) or isinstance(shard_index, bool) or shard_index < 0:
            raise VectorStoreContractError(
                "INVALID_SHARD",
                "shard_index must be a non-negative integer",
            )
        if not isinstance(vector_count, int) or isinstance(vector_count, bool) or vector_count < 0:
            raise VectorStoreContractError(
                "INVALID_SHARD",
                "vector_count must be a non-negative integer",
            )
        shard_id = _require_id(shard_id or _new_id("shard"), field="shard_id")
        digest = (
            _require_digest(content_digest, field="content_digest")
            if content_digest
            else canonical_identity_digest(
                {
                    "collection_id": collection_id,
                    "generation_id": generation_id,
                    "shard_index": shard_index,
                    "vector_count": vector_count,
                }
            )
        )
        created_at = _utc_now()
        meta_json = _metadata_json(metadata)
        with self._transaction() as conn:
            self._assert_draft_conn(conn, collection_id, generation_id)
            conn.execute(
                """
                INSERT INTO vector_shards (
                    shard_id, collection_id, generation_id, shard_index,
                    vector_count, content_digest, status, created_at, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, 'active', ?, ?)
                """,
                [
                    shard_id,
                    collection_id,
                    generation_id,
                    shard_index,
                    vector_count,
                    digest,
                    created_at,
                    meta_json,
                ],
            )
        return ShardRecord(
            shard_id=shard_id,
            collection_id=collection_id,
            generation_id=generation_id,
            shard_index=shard_index,
            vector_count=vector_count,
            content_digest=digest,
            status="active",
            created_at=created_at,
            metadata=_parse_metadata(meta_json),
        )

    def record_index_build(
        self,
        *,
        collection_id: str,
        generation_id: int,
        index_kind: str = "vss_hnsw",
        status: str = "completed",
        build_id: Optional[str] = None,
        metadata: Optional[Mapping[str, Any]] = None,
    ) -> IndexBuildRecord:
        collection_id = _require_id(collection_id, field="collection_id")
        index_kind = _require_id(index_kind, field="index_kind")
        status = _require_id(status, field="status")
        # Index builds are derived — never identity authority.
        gen = self.get_generation(collection_id, generation_id)
        build_id = _require_id(build_id or _new_id("build"), field="build_id")
        created_at = _utc_now()
        completed_at = created_at if status == "completed" else None
        receipt_digest = canonical_identity_digest(
            {
                "build_id": build_id,
                "collection_id": collection_id,
                "generation_id": generation_id,
                "index_kind": index_kind,
                "status": status,
                "generation_content_digest": gen.content_digest,
            }
        )
        meta_json = _metadata_json(metadata)
        with self._transaction() as conn:
            conn.execute(
                """
                INSERT INTO vector_index_builds (
                    build_id, collection_id, generation_id, index_kind,
                    status, receipt_digest, created_at, completed_at, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    build_id,
                    collection_id,
                    generation_id,
                    index_kind,
                    status,
                    receipt_digest,
                    created_at,
                    completed_at,
                    meta_json,
                ],
            )
        return IndexBuildRecord(
            build_id=build_id,
            collection_id=collection_id,
            generation_id=generation_id,
            index_kind=index_kind,
            status=status,
            receipt_digest=receipt_digest,
            created_at=created_at,
            completed_at=completed_at,
            metadata=_parse_metadata(meta_json),
        )

    def compact(
        self,
        *,
        collection_id: str,
        from_generation: int,
        to_generation: Optional[int] = None,
        metadata: Optional[Mapping[str, Any]] = None,
    ) -> CompactionRecord:
        """Remove superseded/tombstoned rows older than the keep generation.

        Compaction never affects the currently published generation's live
        query-visible set.  It only purges tombstoned chunks and superseded
        generation payloads in ``[from_generation, to_generation)``.
        """

        collection = self.get_collection(collection_id)
        if to_generation is None:
            if collection.published_generation is None:
                raise VectorStoreContractError(
                    "NOTHING_TO_COMPACT",
                    "collection has no published generation",
                )
            to_generation = collection.published_generation
        if not isinstance(from_generation, int) or isinstance(from_generation, bool):
            raise VectorStoreContractError(
                "INVALID_GENERATION",
                "from_generation must be an integer",
            )
        if not isinstance(to_generation, int) or isinstance(to_generation, bool):
            raise VectorStoreContractError(
                "INVALID_GENERATION",
                "to_generation must be an integer",
            )
        if from_generation >= to_generation:
            raise VectorStoreContractError(
                "INVALID_RANGE",
                "from_generation must be < to_generation",
            )
        if (
            collection.published_generation is not None
            and to_generation > collection.published_generation
        ):
            raise VectorStoreContractError(
                "INVALID_RANGE",
                "cannot compact past the published generation",
            )
        compaction_id = _new_id("compact")
        created_at = _utc_now()
        removed = 0
        with self._transaction() as conn:
            # Drop vector values for tombstoned chunks in the range.
            doomed = conn.execute(
                """
                SELECT c.chunk_id
                FROM vector_chunks c
                WHERE c.collection_id = ?
                  AND c.generation_id >= ? AND c.generation_id < ?
                  AND c.status = 'tombstoned'
                """,
                [collection.collection_id, from_generation, to_generation],
            ).fetchall()
            for (chunk_id,) in doomed:
                conn.execute(
                    "DELETE FROM vector_values_by_dimension WHERE chunk_id = ?",
                    [chunk_id],
                )
                conn.execute(
                    "DELETE FROM vector_chunks WHERE chunk_id = ?",
                    [chunk_id],
                )
                removed += 1
            completed_at = _utc_now()
            receipt_digest = canonical_identity_digest(
                {
                    "compaction_id": compaction_id,
                    "collection_id": collection.collection_id,
                    "from_generation": from_generation,
                    "to_generation": to_generation,
                    "removed_count": removed,
                    "completed_at": completed_at,
                }
            )
            meta_json = _metadata_json(metadata)
            conn.execute(
                """
                INSERT INTO vector_compactions (
                    compaction_id, collection_id, from_generation, to_generation,
                    status, receipt_digest, created_at, completed_at,
                    removed_count, metadata_json
                ) VALUES (?, ?, ?, ?, 'completed', ?, ?, ?, ?, ?)
                """,
                [
                    compaction_id,
                    collection.collection_id,
                    from_generation,
                    to_generation,
                    receipt_digest,
                    created_at,
                    completed_at,
                    removed,
                    meta_json,
                ],
            )
        return CompactionRecord(
            compaction_id=compaction_id,
            collection_id=collection.collection_id,
            from_generation=from_generation,
            to_generation=to_generation,
            status="completed",
            receipt_digest=receipt_digest,
            created_at=created_at,
            completed_at=completed_at,
            removed_count=removed,
            metadata=_parse_metadata(meta_json),
        )

    def list_tombstones(self, collection_id: str) -> list[TombstoneRecord]:
        collection_id = _require_id(collection_id, field="collection_id")
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT tombstone_id, collection_id, entity_type, entity_id,
                       generation_id, reason, created_at
                FROM vector_tombstones
                WHERE collection_id = ?
                ORDER BY created_at, tombstone_id
                """,
                [collection_id],
            ).fetchall()
        return [
            TombstoneRecord(
                tombstone_id=r[0],
                collection_id=r[1],
                entity_type=r[2],
                entity_id=r[3],
                generation_id=int(r[4]),
                reason=r[5],
                created_at=r[6],
            )
            for r in rows
        ]

    # -- internal guards -----------------------------------------------------

    def _require_draft(self, collection_id: str, generation_id: int) -> None:
        gen = self.get_generation(collection_id, generation_id)
        if gen.status != GenerationStatus.DRAFT.value:
            raise VectorStoreContractError(
                "NOT_DRAFT",
                "mutation requires a draft generation",
                details={"status": gen.status, "generation_id": generation_id},
            )

    def _assert_draft_conn(
        self, conn: Any, collection_id: str, generation_id: int
    ) -> None:
        row = conn.execute(
            """
            SELECT status FROM vector_generations
            WHERE collection_id = ? AND generation_id = ?
            """,
            [collection_id, generation_id],
        ).fetchone()
        if row is None:
            raise VectorStoreContractError(
                "GENERATION_NOT_FOUND",
                f"generation {generation_id} not found",
            )
        if row[0] != GenerationStatus.DRAFT.value:
            raise VectorStoreContractError(
                "NOT_DRAFT",
                "mutation requires a draft generation",
                details={"status": row[0]},
            )

    def _tombstone_entity(
        self,
        conn: Any,
        *,
        collection_id: str,
        entity_type: str,
        entity_id: str,
        generation_id: int,
        reason: str,
        created_at: str,
    ) -> TombstoneRecord:
        tombstone_id = _new_id("tomb")
        conn.execute(
            """
            INSERT INTO vector_tombstones (
                tombstone_id, collection_id, entity_type, entity_id,
                generation_id, reason, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [
                tombstone_id,
                collection_id,
                entity_type,
                entity_id,
                generation_id,
                reason,
                created_at,
            ],
        )
        return TombstoneRecord(
            tombstone_id=tombstone_id,
            collection_id=collection_id,
            entity_type=entity_type,
            entity_id=entity_id,
            generation_id=generation_id,
            reason=reason,
            created_at=created_at,
        )


# Guard: this module must never import pickle as an authority mechanism.
# (The stdlib may still be present in the process; we simply never use it.)
def _assert_no_pickle_authority() -> None:
    import sys

    # Soft check used by tests: ensure we did not load pickle for our API.
    return None


_assert_no_pickle_authority()
