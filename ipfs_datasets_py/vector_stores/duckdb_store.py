"""DuckDB typed vector collection and lifecycle store (DQK-020).

Provides durable metadata authority for:

* collections (dimension / dtype contracts, published generation)
* embedding models
* documents and chunks with normalized source identities
* generation lifecycle (draft → published atomically)
* shards, index-build receipts, tombstones, and compaction receipts

Design invariants:

* **No pickle authority** — metadata is SQL + canonical JSON; vector bytes
  are little-endian IEEE floats packed with ``struct`` (never ``pickle``).
* **Exact dimension and dtype contracts** — every stored vector must match
  the collection's fixed ``dimension`` and ``dtype`` (``float32`` / ``float64``).
* **Mandatory model / chunking / normalization identity** — collections and
  generations refuse incomplete identity bindings.
* **Query-visible vectors never go stale** — updates and deletes are
  transactional; query surfaces only the published generation's active
  (non-tombstoned) chunks.
* **Generations publish atomically** — a single transaction flips generation
  status, collection pointer, and supersedes the previous published generation.

Importing this module is inert with respect to network and filesystem until a
:class:`DuckDBVectorStore` is constructed.  DuckDB is imported lazily at open.
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
from pathlib import Path
from typing import Any, Dict, Iterator, List, Mapping, Optional, Sequence, Union

from ipfs_datasets_py.duckdb_control.contracts import (
    ContractError,
    SourceDigest,
    canonical_json_bytes,
    content_identity,
    normalize_timestamp,
    parse_source_digest,
)

__all__ = [
    "ALLOWED_DTYPES",
    "DISTANCE_METRICS",
    "GENERATION_STATUSES",
    "SCHEMA_VERSION",
    "VECTOR_STORE_SCHEMA",
    "ChunkRecord",
    "CollectionRecord",
    "CompactionRecord",
    "DocumentRecord",
    "DuckDBVectorStore",
    "EmbeddingModelRecord",
    "GenerationRecord",
    "IndexBuildRecord",
    "ShardRecord",
    "TombstoneRecord",
    "VectorStoreError",
    "encode_vector_bytes",
    "normalize_chunking_identity",
    "normalize_normalization_identity",
    "normalize_source_identity",
    "open_vector_store",
    "vector_content_digest",
]


# ---------------------------------------------------------------------------
# Constants / contracts
# ---------------------------------------------------------------------------

VECTOR_STORE_SCHEMA: str = "ipfs_datasets_py/vector-stores-duckdb@1"
SCHEMA_VERSION: int = 1

ALLOWED_DTYPES = frozenset({"float32", "float64"})
DISTANCE_METRICS = frozenset({"cosine", "l2", "ip", "inner_product"})
GENERATION_STATUSES = frozenset(
    {"draft", "published", "superseded", "aborted"}
)
CHUNK_STATUSES = frozenset({"active", "tombstoned"})
COLLECTION_STATUSES = frozenset({"active", "tombstoned"})
SHARD_STATUSES = frozenset({"open", "sealed", "compacted", "abandoned"})
COMPACTION_STATUSES = frozenset(
    {"planned", "running", "completed", "failed", "aborted"}
)
INDEX_BUILD_STATUSES = frozenset(
    {"planned", "running", "completed", "failed", "aborted"}
)
ENTITY_TYPES = frozenset(
    {"collection", "document", "chunk", "generation", "shard"}
)

_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,191}$")
_IDENTITY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@+/-]{0,511}$")
_MAX_DIMENSION = 16_384
_MAX_METADATA_BYTES = 1_048_576
_MAX_TEXT_BYTES = 4_194_304

PathLike = Union[str, Path]


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class VectorStoreError(Exception):
    """Typed fail-closed error for the DuckDB vector store."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        details: Optional[Mapping[str, Any]] = None,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.code = str(code)
        self.message = str(message)
        self.details: Dict[str, Any] = dict(details or {})
        self.retryable = bool(retryable)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "details": dict(self.details),
            "retryable": self.retryable,
        }

    def __str__(self) -> str:  # pragma: no cover - trivial
        return f"{self.code}: {self.message}"


# ---------------------------------------------------------------------------
# Identity / encoding helpers
# ---------------------------------------------------------------------------


def _utc_now_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .strftime("%Y-%m-%dT%H:%M:%SZ")
    )


def _require_id(value: Any, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise VectorStoreError(
            "INVALID_REQUEST",
            f"{field} must be a non-empty string",
            details={"field": field},
        )
    text = value.strip()
    if text != value:
        raise VectorStoreError(
            "INVALID_REQUEST",
            f"{field} must not have surrounding whitespace",
            details={"field": field},
        )
    if _SAFE_ID_RE.fullmatch(text) is None:
        raise VectorStoreError(
            "INVALID_REQUEST",
            f"{field} failed identifier validation",
            details={"field": field, "value": text},
        )
    return text


def _require_identity(value: Any, *, field: str) -> str:
    """Require a non-empty identity token (model / chunking / normalization)."""

    if value is None or (isinstance(value, str) and not value.strip()):
        raise VectorStoreError(
            "INVALID_REQUEST",
            f"{field} is mandatory",
            details={"field": field},
        )
    if not isinstance(value, str):
        raise VectorStoreError(
            "INVALID_REQUEST",
            f"{field} must be a string",
            details={"field": field},
        )
    text = value.strip()
    if not text:
        raise VectorStoreError(
            "INVALID_REQUEST",
            f"{field} is mandatory",
            details={"field": field},
        )
    if _IDENTITY_RE.fullmatch(text) is None:
        raise VectorStoreError(
            "INVALID_REQUEST",
            f"{field} failed identity validation",
            details={"field": field, "value": text},
        )
    return text


def normalize_source_identity(
    value: Union[str, Mapping[str, Any]],
) -> str:
    """Normalize a source identity to a stable, comparable token.

    * Strings are stripped; internal whitespace is collapsed; URI-like schemes
      are lower-cased (``File://X`` → ``file://x`` path segment lower only for
      scheme). Path/body after scheme is preserved except leading/trailing
      whitespace on the whole string.
    * Mappings are reduced via :func:`content_identity` over canonical JSON.
    """

    if isinstance(value, Mapping):
        return content_identity(dict(value))
    if not isinstance(value, str) or not value.strip():
        raise VectorStoreError(
            "INVALID_REQUEST",
            "source_identity must be nonempty text or a mapping",
            details={"field": "source_identity"},
        )
    text = " ".join(value.strip().split())
    if "://" in text:
        scheme, rest = text.split("://", 1)
        scheme = scheme.lower()
        # Normalize empty host separators; keep body exact after scheme.
        text = f"{scheme}://{rest.strip()}"
    if _IDENTITY_RE.fullmatch(text) is None and not text.startswith("sha256:"):
        # Allow long path bodies by hashing when the raw form is unsafe/long.
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        return f"src:sha256:{digest}"
    return text


def normalize_chunking_identity(value: Any) -> str:
    return _require_identity(value, field="chunking_identity")


def normalize_normalization_identity(value: Any) -> str:
    return _require_identity(value, field="normalization_identity")


def _require_dimension(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise VectorStoreError(
            "INVALID_REQUEST",
            "dimension must be a positive integer",
            details={"field": "dimension"},
        )
    if value < 1 or value > _MAX_DIMENSION:
        raise VectorStoreError(
            "INVALID_REQUEST",
            f"dimension must be in [1, {_MAX_DIMENSION}]",
            details={"field": "dimension", "value": value},
        )
    return value


def _require_dtype(value: Any) -> str:
    if not isinstance(value, str) or value not in ALLOWED_DTYPES:
        raise VectorStoreError(
            "INVALID_REQUEST",
            f"dtype must be one of {sorted(ALLOWED_DTYPES)}",
            details={"field": "dtype", "value": value},
        )
    return value


def _require_distance_metric(value: Any) -> str:
    if value is None:
        return "cosine"
    if not isinstance(value, str) or value not in DISTANCE_METRICS:
        raise VectorStoreError(
            "INVALID_REQUEST",
            f"distance_metric must be one of {sorted(DISTANCE_METRICS)}",
            details={"field": "distance_metric", "value": value},
        )
    # Normalize alias.
    if value == "inner_product":
        return "ip"
    return value


def _metadata_json(metadata: Optional[Mapping[str, Any]]) -> str:
    payload: Dict[str, Any] = dict(metadata or {})
    try:
        raw = canonical_json_bytes(payload)
    except ContractError as exc:
        raise VectorStoreError(
            "INVALID_REQUEST",
            f"metadata is not canonical-JSON-safe: {exc}",
            details={"field": "metadata"},
        ) from exc
    if len(raw) > _MAX_METADATA_BYTES:
        raise VectorStoreError(
            "INVALID_REQUEST",
            "metadata exceeds size bound",
            details={"field": "metadata", "bytes": len(raw)},
        )
    return raw.decode("utf-8")


def _parse_metadata(text: Any) -> Dict[str, Any]:
    if text is None or text == "":
        return {}
    if isinstance(text, dict):
        return dict(text)
    try:
        data = json.loads(str(text))
    except (TypeError, ValueError) as exc:
        raise VectorStoreError(
            "STORAGE",
            f"corrupt metadata_json: {exc}",
        ) from exc
    if not isinstance(data, dict):
        raise VectorStoreError("STORAGE", "metadata_json must be a JSON object")
    return data


def encode_vector_bytes(
    values: Sequence[float],
    *,
    dimension: int,
    dtype: str,
) -> bytes:
    """Encode floats as little-endian IEEE bytes under a dimension/dtype contract."""

    dtype = _require_dtype(dtype)
    dimension = _require_dimension(dimension)
    if not isinstance(values, Sequence) or isinstance(values, (str, bytes, bytearray)):
        raise VectorStoreError(
            "INVALID_REQUEST",
            "vector must be a sequence of finite numbers",
            details={"field": "vector"},
        )
    if len(values) != dimension:
        raise VectorStoreError(
            "DIMENSION_MISMATCH",
            f"vector length {len(values)} does not match dimension {dimension}",
            details={
                "expected_dimension": dimension,
                "actual_dimension": len(values),
            },
        )
    floats: List[float] = []
    for index, item in enumerate(values):
        if isinstance(item, bool) or not isinstance(item, (int, float)):
            raise VectorStoreError(
                "INVALID_REQUEST",
                f"vector[{index}] is not a number",
                details={"index": index},
            )
        number = float(item)
        if number != number or number in (float("inf"), float("-inf")):
            raise VectorStoreError(
                "INVALID_REQUEST",
                f"vector[{index}] is non-finite",
                details={"index": index},
            )
        floats.append(number)
    fmt = "<" + ("f" if dtype == "float32" else "d") * dimension
    return struct.pack(fmt, *floats)


def decode_vector_bytes(
    blob: bytes,
    *,
    dimension: int,
    dtype: str,
) -> List[float]:
    dtype = _require_dtype(dtype)
    dimension = _require_dimension(dimension)
    raw = bytes(blob)
    width = 4 if dtype == "float32" else 8
    expected = dimension * width
    if len(raw) != expected:
        raise VectorStoreError(
            "STORAGE",
            f"vector blob length {len(raw)} != expected {expected}",
            details={"dimension": dimension, "dtype": dtype},
        )
    fmt = "<" + ("f" if dtype == "float32" else "d") * dimension
    return list(struct.unpack(fmt, raw))


def vector_content_digest(vector_bytes: bytes) -> str:
    return "sha256:" + hashlib.sha256(vector_bytes).hexdigest()


def _digest_text(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


# ---------------------------------------------------------------------------
# Record types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EmbeddingModelRecord:
    model_id: str
    model_name: str
    provider: str
    dimension: int
    dtype: str
    model_digest: str
    config: Dict[str, Any] = field(default_factory=dict)
    created_at: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CollectionRecord:
    collection_id: str
    name: str
    dimension: int
    dtype: str
    distance_metric: str
    model_id: str
    chunking_identity: str
    normalization_identity: str
    published_generation_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class GenerationRecord:
    collection_id: str
    generation_id: str
    parent_generation_id: Optional[str]
    status: str
    model_id: str
    chunking_identity: str
    normalization_identity: str
    content_digest: Optional[str]
    created_at: str
    published_at: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class DocumentRecord:
    collection_id: str
    document_id: str
    generation_id: str
    source_identity: str
    source_digest: str
    content_digest: str
    created_at: str
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ChunkRecord:
    collection_id: str
    chunk_id: str
    document_id: str
    generation_id: str
    source_identity: str
    chunk_index: int
    text_digest: str
    content_digest: str
    vector_digest: str
    dimension: int
    dtype: str
    status: str
    revision: int
    shard_id: Optional[str]
    created_at: str
    updated_at: str
    metadata: Dict[str, Any] = field(default_factory=dict)
    vector: Optional[List[float]] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ShardRecord:
    shard_id: str
    collection_id: str
    generation_id: str
    dimension: int
    dtype: str
    status: str
    vector_count: int
    content_digest: Optional[str]
    created_at: str
    sealed_at: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class TombstoneRecord:
    tombstone_id: str
    collection_id: str
    entity_type: str
    entity_id: str
    generation_id: Optional[str]
    prior_content_digest: Optional[str]
    reason: Optional[str]
    tombstoned_at: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CompactionRecord:
    compaction_id: str
    collection_id: str
    generation_id: str
    status: str
    input_shard_ids: List[str]
    output_shard_id: Optional[str]
    receipt: Dict[str, Any]
    created_at: str
    completed_at: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class IndexBuildRecord:
    build_id: str
    collection_id: str
    generation_id: str
    index_kind: str
    status: str
    receipt: Dict[str, Any]
    created_at: str
    completed_at: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Schema SQL
# ---------------------------------------------------------------------------

_SCHEMA_SQL = f"""
CREATE TABLE IF NOT EXISTS vector_store_meta (
    key VARCHAR PRIMARY KEY,
    value VARCHAR NOT NULL
);

CREATE TABLE IF NOT EXISTS embedding_models (
    model_id VARCHAR PRIMARY KEY,
    model_name VARCHAR NOT NULL,
    provider VARCHAR NOT NULL,
    dimension INTEGER NOT NULL,
    dtype VARCHAR NOT NULL,
    model_digest VARCHAR NOT NULL,
    config_json VARCHAR NOT NULL,
    created_at VARCHAR NOT NULL
);

CREATE TABLE IF NOT EXISTS vector_collections (
    collection_id VARCHAR PRIMARY KEY,
    name VARCHAR NOT NULL,
    dimension INTEGER NOT NULL,
    dtype VARCHAR NOT NULL,
    distance_metric VARCHAR NOT NULL,
    model_id VARCHAR NOT NULL,
    chunking_identity VARCHAR NOT NULL,
    normalization_identity VARCHAR NOT NULL,
    published_generation_id VARCHAR,
    status VARCHAR NOT NULL,
    created_at VARCHAR NOT NULL,
    updated_at VARCHAR NOT NULL,
    metadata_json VARCHAR NOT NULL
);

CREATE TABLE IF NOT EXISTS vector_generations (
    collection_id VARCHAR NOT NULL,
    generation_id VARCHAR NOT NULL,
    parent_generation_id VARCHAR,
    status VARCHAR NOT NULL,
    model_id VARCHAR NOT NULL,
    chunking_identity VARCHAR NOT NULL,
    normalization_identity VARCHAR NOT NULL,
    content_digest VARCHAR,
    created_at VARCHAR NOT NULL,
    published_at VARCHAR,
    metadata_json VARCHAR NOT NULL,
    PRIMARY KEY (collection_id, generation_id)
);

CREATE TABLE IF NOT EXISTS vector_documents (
    collection_id VARCHAR NOT NULL,
    document_id VARCHAR NOT NULL,
    generation_id VARCHAR NOT NULL,
    source_identity VARCHAR NOT NULL,
    source_digest VARCHAR NOT NULL,
    content_digest VARCHAR NOT NULL,
    created_at VARCHAR NOT NULL,
    metadata_json VARCHAR NOT NULL,
    PRIMARY KEY (collection_id, document_id, generation_id)
);

CREATE TABLE IF NOT EXISTS vector_chunks (
    collection_id VARCHAR NOT NULL,
    chunk_id VARCHAR NOT NULL,
    document_id VARCHAR NOT NULL,
    generation_id VARCHAR NOT NULL,
    source_identity VARCHAR NOT NULL,
    chunk_index INTEGER NOT NULL,
    text_digest VARCHAR NOT NULL,
    content_digest VARCHAR NOT NULL,
    vector_digest VARCHAR NOT NULL,
    dimension INTEGER NOT NULL,
    dtype VARCHAR NOT NULL,
    status VARCHAR NOT NULL,
    revision INTEGER NOT NULL,
    shard_id VARCHAR,
    vector_blob BLOB NOT NULL,
    created_at VARCHAR NOT NULL,
    updated_at VARCHAR NOT NULL,
    metadata_json VARCHAR NOT NULL,
    PRIMARY KEY (collection_id, chunk_id, generation_id)
);

CREATE TABLE IF NOT EXISTS vector_shards (
    shard_id VARCHAR PRIMARY KEY,
    collection_id VARCHAR NOT NULL,
    generation_id VARCHAR NOT NULL,
    dimension INTEGER NOT NULL,
    dtype VARCHAR NOT NULL,
    status VARCHAR NOT NULL,
    vector_count INTEGER NOT NULL,
    content_digest VARCHAR,
    created_at VARCHAR NOT NULL,
    sealed_at VARCHAR,
    metadata_json VARCHAR NOT NULL
);

CREATE TABLE IF NOT EXISTS vector_values_by_dimension (
    dimension INTEGER NOT NULL,
    dtype VARCHAR NOT NULL,
    physical_table VARCHAR NOT NULL,
    created_at VARCHAR NOT NULL,
    PRIMARY KEY (dimension, dtype)
);

CREATE TABLE IF NOT EXISTS vector_tombstones (
    tombstone_id VARCHAR PRIMARY KEY,
    collection_id VARCHAR NOT NULL,
    entity_type VARCHAR NOT NULL,
    entity_id VARCHAR NOT NULL,
    generation_id VARCHAR,
    prior_content_digest VARCHAR,
    reason VARCHAR,
    tombstoned_at VARCHAR NOT NULL
);

CREATE TABLE IF NOT EXISTS vector_compactions (
    compaction_id VARCHAR PRIMARY KEY,
    collection_id VARCHAR NOT NULL,
    generation_id VARCHAR NOT NULL,
    status VARCHAR NOT NULL,
    input_shards_json VARCHAR NOT NULL,
    output_shard_id VARCHAR,
    receipt_json VARCHAR NOT NULL,
    created_at VARCHAR NOT NULL,
    completed_at VARCHAR
);

CREATE TABLE IF NOT EXISTS vector_index_builds (
    build_id VARCHAR PRIMARY KEY,
    collection_id VARCHAR NOT NULL,
    generation_id VARCHAR NOT NULL,
    index_kind VARCHAR NOT NULL,
    status VARCHAR NOT NULL,
    receipt_json VARCHAR NOT NULL,
    created_at VARCHAR NOT NULL,
    completed_at VARCHAR
);

CREATE INDEX IF NOT EXISTS idx_vector_chunks_generation
    ON vector_chunks (collection_id, generation_id, status);
CREATE INDEX IF NOT EXISTS idx_vector_chunks_source
    ON vector_chunks (collection_id, source_identity);
CREATE INDEX IF NOT EXISTS idx_vector_docs_source
    ON vector_documents (collection_id, source_identity);
CREATE INDEX IF NOT EXISTS idx_vector_tombstones_entity
    ON vector_tombstones (collection_id, entity_type, entity_id);
CREATE INDEX IF NOT EXISTS idx_vector_generations_status
    ON vector_generations (collection_id, status);
CREATE INDEX IF NOT EXISTS idx_vector_shards_generation
    ON vector_shards (collection_id, generation_id);
"""


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------


class DuckDBVectorStore:
    """DuckDB-backed vector metadata and lifecycle authority.

    Process memory is never the authority for published heads or chunk
    visibility: reopening the same path after restart restores durable state.
    """

    def __init__(
        self,
        path: PathLike = ":memory:",
        *,
        read_only: bool = False,
    ) -> None:
        self._path = Path(path) if path != ":memory:" and str(path) != ":memory:" else Path(":memory:")
        self._path_str = ":memory:" if str(self._path) == ":memory:" else str(self._path)
        self._read_only = bool(read_only)
        self._lock = threading.RLock()
        self._closed = False
        if self._path_str != ":memory:" and not self._read_only:
            parent = Path(self._path_str).parent
            if str(parent) not in ("", "."):
                parent.mkdir(parents=True, exist_ok=True)
        self._conn = self._open_connection()
        if not self._read_only:
            self._initialize_schema()

    # -- lifecycle ---------------------------------------------------------

    @property
    def path(self) -> str:
        return self._path_str

    @property
    def schema_version(self) -> int:
        return SCHEMA_VERSION

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            try:
                self._conn.close()
            finally:
                self._closed = True

    def __enter__(self) -> "DuckDBVectorStore":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _ensure_open(self) -> None:
        if self._closed:
            raise VectorStoreError("STORAGE", "vector store is closed")

    def _open_connection(self) -> Any:
        try:
            import duckdb  # type: ignore[import-not-found]
        except ImportError as exc:  # pragma: no cover
            raise VectorStoreError(
                "STORAGE",
                "duckdb is not installed; provision the pinned DuckDB 1.5.5 environment",
            ) from exc
        try:
            # In-memory databases cannot open read-only.
            read_only = self._read_only and self._path_str != ":memory:"
            return duckdb.connect(database=self._path_str, read_only=read_only)
        except Exception as exc:  # noqa: BLE001
            raise VectorStoreError(
                "STORAGE",
                f"failed to open DuckDB vector store at {self._path_str!r}: {exc}",
            ) from exc

    def _initialize_schema(self) -> None:
        with self._lock:
            self._conn.execute("BEGIN")
            try:
                for statement in _SCHEMA_SQL.split(";"):
                    sql = statement.strip()
                    if sql:
                        self._conn.execute(sql)
                row = self._conn.execute(
                    "SELECT value FROM vector_store_meta WHERE key = ?",
                    ["schema_version"],
                ).fetchone()
                if row is None:
                    self._conn.execute(
                        "INSERT INTO vector_store_meta (key, value) VALUES (?, ?)",
                        ["schema_version", str(SCHEMA_VERSION)],
                    )
                    self._conn.execute(
                        "INSERT INTO vector_store_meta (key, value) VALUES (?, ?)",
                        ["schema_id", VECTOR_STORE_SCHEMA],
                    )
                    self._conn.execute(
                        "INSERT INTO vector_store_meta (key, value) VALUES (?, ?)",
                        ["pickle_authority", "forbidden"],
                    )
                else:
                    version = int(row[0])
                    if version > SCHEMA_VERSION:
                        raise VectorStoreError(
                            "STORAGE",
                            f"vector store schema version {version} is newer than "
                            f"supported {SCHEMA_VERSION}",
                        )
                self._conn.execute("COMMIT")
            except Exception:
                try:
                    self._conn.execute("ROLLBACK")
                except Exception:  # noqa: BLE001
                    pass
                raise

    @contextmanager
    def _txn(self) -> Iterator[Any]:
        self._ensure_open()
        if self._read_only:
            raise VectorStoreError("STORAGE", "vector store is read-only")
        with self._lock:
            self._conn.execute("BEGIN")
            try:
                yield self._conn
                self._conn.execute("COMMIT")
            except Exception:
                try:
                    self._conn.execute("ROLLBACK")
                except Exception:  # noqa: BLE001
                    pass
                raise

    def _execute(self, sql: str, params: Optional[Sequence[Any]] = None) -> Any:
        self._ensure_open()
        with self._lock:
            if params is None:
                return self._conn.execute(sql)
            return self._conn.execute(sql, list(params))

    # -- row mappers -------------------------------------------------------

    def _model_from_row(self, row: Sequence[Any]) -> EmbeddingModelRecord:
        return EmbeddingModelRecord(
            model_id=row[0],
            model_name=row[1],
            provider=row[2],
            dimension=int(row[3]),
            dtype=row[4],
            model_digest=row[5],
            config=_parse_metadata(row[6]),
            created_at=row[7],
        )

    def _collection_from_row(self, row: Sequence[Any]) -> CollectionRecord:
        return CollectionRecord(
            collection_id=row[0],
            name=row[1],
            dimension=int(row[2]),
            dtype=row[3],
            distance_metric=row[4],
            model_id=row[5],
            chunking_identity=row[6],
            normalization_identity=row[7],
            published_generation_id=row[8],
            status=row[9],
            created_at=row[10],
            updated_at=row[11],
            metadata=_parse_metadata(row[12]),
        )

    def _generation_from_row(self, row: Sequence[Any]) -> GenerationRecord:
        return GenerationRecord(
            collection_id=row[0],
            generation_id=row[1],
            parent_generation_id=row[2],
            status=row[3],
            model_id=row[4],
            chunking_identity=row[5],
            normalization_identity=row[6],
            content_digest=row[7],
            created_at=row[8],
            published_at=row[9],
            metadata=_parse_metadata(row[10]),
        )

    def _document_from_row(self, row: Sequence[Any]) -> DocumentRecord:
        return DocumentRecord(
            collection_id=row[0],
            document_id=row[1],
            generation_id=row[2],
            source_identity=row[3],
            source_digest=row[4],
            content_digest=row[5],
            created_at=row[6],
            metadata=_parse_metadata(row[7]),
        )

    def _chunk_from_row(
        self,
        row: Sequence[Any],
        *,
        include_vector: bool = False,
    ) -> ChunkRecord:
        vector: Optional[List[float]] = None
        if include_vector:
            vector = decode_vector_bytes(
                row[14],
                dimension=int(row[9]),
                dtype=row[10],
            )
        return ChunkRecord(
            collection_id=row[0],
            chunk_id=row[1],
            document_id=row[2],
            generation_id=row[3],
            source_identity=row[4],
            chunk_index=int(row[5]),
            text_digest=row[6],
            content_digest=row[7],
            vector_digest=row[8],
            dimension=int(row[9]),
            dtype=row[10],
            status=row[11],
            revision=int(row[12]),
            shard_id=row[13],
            created_at=row[15],
            updated_at=row[16],
            metadata=_parse_metadata(row[17]),
            vector=vector,
        )

    def _shard_from_row(self, row: Sequence[Any]) -> ShardRecord:
        return ShardRecord(
            shard_id=row[0],
            collection_id=row[1],
            generation_id=row[2],
            dimension=int(row[3]),
            dtype=row[4],
            status=row[5],
            vector_count=int(row[6]),
            content_digest=row[7],
            created_at=row[8],
            sealed_at=row[9],
            metadata=_parse_metadata(row[10]),
        )

    def _tombstone_from_row(self, row: Sequence[Any]) -> TombstoneRecord:
        return TombstoneRecord(
            tombstone_id=row[0],
            collection_id=row[1],
            entity_type=row[2],
            entity_id=row[3],
            generation_id=row[4],
            prior_content_digest=row[5],
            reason=row[6],
            tombstoned_at=row[7],
        )

    def _compaction_from_row(self, row: Sequence[Any]) -> CompactionRecord:
        try:
            inputs = json.loads(row[4] or "[]")
        except (TypeError, ValueError):
            inputs = []
        if not isinstance(inputs, list):
            inputs = []
        return CompactionRecord(
            compaction_id=row[0],
            collection_id=row[1],
            generation_id=row[2],
            status=row[3],
            input_shard_ids=[str(x) for x in inputs],
            output_shard_id=row[5],
            receipt=_parse_metadata(row[6]),
            created_at=row[7],
            completed_at=row[8],
        )

    def _index_build_from_row(self, row: Sequence[Any]) -> IndexBuildRecord:
        return IndexBuildRecord(
            build_id=row[0],
            collection_id=row[1],
            generation_id=row[2],
            index_kind=row[3],
            status=row[4],
            receipt=_parse_metadata(row[5]),
            created_at=row[6],
            completed_at=row[7],
        )

    # -- internal getters --------------------------------------------------

    def _get_model_row(
        self, conn: Any, model_id: str
    ) -> Optional[Sequence[Any]]:
        return conn.execute(
            "SELECT model_id, model_name, provider, dimension, dtype, "
            "model_digest, config_json, created_at "
            "FROM embedding_models WHERE model_id = ?",
            [model_id],
        ).fetchone()

    def _get_collection_row(
        self, conn: Any, collection_id: str
    ) -> Optional[Sequence[Any]]:
        return conn.execute(
            "SELECT collection_id, name, dimension, dtype, distance_metric, "
            "model_id, chunking_identity, normalization_identity, "
            "published_generation_id, status, created_at, updated_at, "
            "metadata_json FROM vector_collections WHERE collection_id = ?",
            [collection_id],
        ).fetchone()

    def _require_collection(
        self, conn: Any, collection_id: str, *, allow_tombstoned: bool = False
    ) -> CollectionRecord:
        row = self._get_collection_row(conn, collection_id)
        if row is None:
            raise VectorStoreError(
                "NOT_FOUND",
                f"collection not found: {collection_id}",
                details={"collection_id": collection_id},
            )
        record = self._collection_from_row(row)
        if not allow_tombstoned and record.status == "tombstoned":
            raise VectorStoreError(
                "NOT_FOUND",
                f"collection is tombstoned: {collection_id}",
                details={"collection_id": collection_id},
            )
        return record

    def _get_generation_row(
        self, conn: Any, collection_id: str, generation_id: str
    ) -> Optional[Sequence[Any]]:
        return conn.execute(
            "SELECT collection_id, generation_id, parent_generation_id, status, "
            "model_id, chunking_identity, normalization_identity, content_digest, "
            "created_at, published_at, metadata_json "
            "FROM vector_generations "
            "WHERE collection_id = ? AND generation_id = ?",
            [collection_id, generation_id],
        ).fetchone()

    def _require_generation(
        self,
        conn: Any,
        collection_id: str,
        generation_id: str,
        *,
        require_status: Optional[str] = None,
    ) -> GenerationRecord:
        row = self._get_generation_row(conn, collection_id, generation_id)
        if row is None:
            raise VectorStoreError(
                "NOT_FOUND",
                f"generation not found: {generation_id}",
                details={
                    "collection_id": collection_id,
                    "generation_id": generation_id,
                },
            )
        record = self._generation_from_row(row)
        if require_status is not None and record.status != require_status:
            raise VectorStoreError(
                "CONFLICT",
                f"generation status is {record.status!r}, expected {require_status!r}",
                details={
                    "collection_id": collection_id,
                    "generation_id": generation_id,
                    "status": record.status,
                    "expected": require_status,
                },
            )
        return record

    def _get_chunk_row(
        self,
        conn: Any,
        collection_id: str,
        chunk_id: str,
        generation_id: str,
    ) -> Optional[Sequence[Any]]:
        return conn.execute(
            "SELECT collection_id, chunk_id, document_id, generation_id, "
            "source_identity, chunk_index, text_digest, content_digest, "
            "vector_digest, dimension, dtype, status, revision, shard_id, "
            "vector_blob, created_at, updated_at, metadata_json "
            "FROM vector_chunks "
            "WHERE collection_id = ? AND chunk_id = ? AND generation_id = ?",
            [collection_id, chunk_id, generation_id],
        ).fetchone()

    def _insert_tombstone(
        self,
        conn: Any,
        *,
        collection_id: str,
        entity_type: str,
        entity_id: str,
        generation_id: Optional[str],
        prior_content_digest: Optional[str],
        reason: Optional[str],
        now: str,
    ) -> TombstoneRecord:
        if entity_type not in ENTITY_TYPES:
            raise VectorStoreError(
                "INVALID_REQUEST",
                f"entity_type must be one of {sorted(ENTITY_TYPES)}",
            )
        tombstone_id = _new_id("tomb")
        conn.execute(
            "INSERT INTO vector_tombstones ("
            "tombstone_id, collection_id, entity_type, entity_id, "
            "generation_id, prior_content_digest, reason, tombstoned_at"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [
                tombstone_id,
                collection_id,
                entity_type,
                entity_id,
                generation_id,
                prior_content_digest,
                reason,
                now,
            ],
        )
        return TombstoneRecord(
            tombstone_id=tombstone_id,
            collection_id=collection_id,
            entity_type=entity_type,
            entity_id=entity_id,
            generation_id=generation_id,
            prior_content_digest=prior_content_digest,
            reason=reason,
            tombstoned_at=now,
        )

    def _ensure_dimension_registry(
        self,
        conn: Any,
        *,
        dimension: int,
        dtype: str,
        now: str,
    ) -> None:
        physical = f"vector_values_d{dimension}_{dtype}"
        existing = conn.execute(
            "SELECT physical_table FROM vector_values_by_dimension "
            "WHERE dimension = ? AND dtype = ?",
            [dimension, dtype],
        ).fetchone()
        if existing is None:
            conn.execute(
                "INSERT INTO vector_values_by_dimension "
                "(dimension, dtype, physical_table, created_at) "
                "VALUES (?, ?, ?, ?)",
                [dimension, dtype, physical, now],
            )
        elif existing[0] != physical:
            raise VectorStoreError(
                "CONFLICT",
                "dimension registry physical table mismatch",
                details={
                    "dimension": dimension,
                    "dtype": dtype,
                    "expected": physical,
                    "actual": existing[0],
                },
            )

    # -- public: models ----------------------------------------------------

    def register_model(
        self,
        *,
        model_id: Optional[str] = None,
        model_name: str,
        provider: str = "unknown",
        dimension: int,
        dtype: str = "float32",
        config: Optional[Mapping[str, Any]] = None,
    ) -> EmbeddingModelRecord:
        mid = _require_id(model_id or _new_id("model"), field="model_id")
        if not isinstance(model_name, str) or not model_name.strip():
            raise VectorStoreError(
                "INVALID_REQUEST", "model_name is mandatory"
            )
        name = model_name.strip()
        if not isinstance(provider, str) or not provider.strip():
            raise VectorStoreError(
                "INVALID_REQUEST", "provider is mandatory"
            )
        prov = provider.strip()
        dim = _require_dimension(dimension)
        dt = _require_dtype(dtype)
        cfg = dict(config or {})
        digest = content_identity(
            {
                "model_name": name,
                "provider": prov,
                "dimension": dim,
                "dtype": dt,
                "config": cfg,
            }
        )
        now = _utc_now_iso()
        with self._txn() as conn:
            existing = self._get_model_row(conn, mid)
            if existing is not None:
                record = self._model_from_row(existing)
                if (
                    record.model_name == name
                    and record.provider == prov
                    and record.dimension == dim
                    and record.dtype == dt
                    and record.model_digest == digest
                ):
                    return record
                raise VectorStoreError(
                    "ALREADY_EXISTS",
                    f"model_id already registered with different identity: {mid}",
                    details={"model_id": mid},
                )
            conn.execute(
                "INSERT INTO embedding_models ("
                "model_id, model_name, provider, dimension, dtype, "
                "model_digest, config_json, created_at"
                ") VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    mid,
                    name,
                    prov,
                    dim,
                    dt,
                    digest,
                    _metadata_json(cfg),
                    now,
                ],
            )
            return EmbeddingModelRecord(
                model_id=mid,
                model_name=name,
                provider=prov,
                dimension=dim,
                dtype=dt,
                model_digest=digest,
                config=cfg,
                created_at=now,
            )

    def get_model(self, model_id: str) -> EmbeddingModelRecord:
        mid = _require_id(model_id, field="model_id")
        row = self._execute(
            "SELECT model_id, model_name, provider, dimension, dtype, "
            "model_digest, config_json, created_at "
            "FROM embedding_models WHERE model_id = ?",
            [mid],
        ).fetchone()
        if row is None:
            raise VectorStoreError(
                "NOT_FOUND",
                f"model not found: {mid}",
                details={"model_id": mid},
            )
        return self._model_from_row(row)

    def list_models(self) -> List[EmbeddingModelRecord]:
        rows = self._execute(
            "SELECT model_id, model_name, provider, dimension, dtype, "
            "model_digest, config_json, created_at "
            "FROM embedding_models ORDER BY model_id"
        ).fetchall()
        return [self._model_from_row(r) for r in rows]

    # -- public: collections -----------------------------------------------

    def create_collection(
        self,
        *,
        collection_id: Optional[str] = None,
        name: str,
        model_id: str,
        chunking_identity: str,
        normalization_identity: str,
        dimension: Optional[int] = None,
        dtype: Optional[str] = None,
        distance_metric: str = "cosine",
        metadata: Optional[Mapping[str, Any]] = None,
    ) -> CollectionRecord:
        cid = _require_id(
            collection_id or _new_id("col"), field="collection_id"
        )
        if not isinstance(name, str) or not name.strip():
            raise VectorStoreError("INVALID_REQUEST", "name is mandatory")
        cname = name.strip()
        mid = _require_id(model_id, field="model_id")
        chunking = normalize_chunking_identity(chunking_identity)
        normalization = normalize_normalization_identity(
            normalization_identity
        )
        metric = _require_distance_metric(distance_metric)
        meta_json = _metadata_json(metadata)
        now = _utc_now_iso()

        with self._txn() as conn:
            model_row = self._get_model_row(conn, mid)
            if model_row is None:
                raise VectorStoreError(
                    "NOT_FOUND",
                    f"model not found: {mid}",
                    details={"model_id": mid},
                )
            model = self._model_from_row(model_row)
            dim = _require_dimension(
                dimension if dimension is not None else model.dimension
            )
            dt = _require_dtype(dtype if dtype is not None else model.dtype)
            if dim != model.dimension or dt != model.dtype:
                raise VectorStoreError(
                    "DIMENSION_MISMATCH",
                    "collection dimension/dtype must match embedding model",
                    details={
                        "collection_dimension": dim,
                        "collection_dtype": dt,
                        "model_dimension": model.dimension,
                        "model_dtype": model.dtype,
                    },
                )
            existing = self._get_collection_row(conn, cid)
            if existing is not None:
                raise VectorStoreError(
                    "ALREADY_EXISTS",
                    f"collection already exists: {cid}",
                    details={"collection_id": cid},
                )
            self._ensure_dimension_registry(
                conn, dimension=dim, dtype=dt, now=now
            )
            conn.execute(
                "INSERT INTO vector_collections ("
                "collection_id, name, dimension, dtype, distance_metric, "
                "model_id, chunking_identity, normalization_identity, "
                "published_generation_id, status, created_at, updated_at, "
                "metadata_json"
                ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, 'active', ?, ?, ?)",
                [
                    cid,
                    cname,
                    dim,
                    dt,
                    metric,
                    mid,
                    chunking,
                    normalization,
                    now,
                    now,
                    meta_json,
                ],
            )
            return CollectionRecord(
                collection_id=cid,
                name=cname,
                dimension=dim,
                dtype=dt,
                distance_metric=metric,
                model_id=mid,
                chunking_identity=chunking,
                normalization_identity=normalization,
                published_generation_id=None,
                status="active",
                created_at=now,
                updated_at=now,
                metadata=_parse_metadata(meta_json),
            )

    def get_collection(self, collection_id: str) -> CollectionRecord:
        cid = _require_id(collection_id, field="collection_id")
        row = self._execute(
            "SELECT collection_id, name, dimension, dtype, distance_metric, "
            "model_id, chunking_identity, normalization_identity, "
            "published_generation_id, status, created_at, updated_at, "
            "metadata_json FROM vector_collections WHERE collection_id = ?",
            [cid],
        ).fetchone()
        if row is None:
            raise VectorStoreError(
                "NOT_FOUND",
                f"collection not found: {cid}",
                details={"collection_id": cid},
            )
        return self._collection_from_row(row)

    def list_collections(
        self, *, include_tombstoned: bool = False
    ) -> List[CollectionRecord]:
        if include_tombstoned:
            rows = self._execute(
                "SELECT collection_id, name, dimension, dtype, distance_metric, "
                "model_id, chunking_identity, normalization_identity, "
                "published_generation_id, status, created_at, updated_at, "
                "metadata_json FROM vector_collections ORDER BY collection_id"
            ).fetchall()
        else:
            rows = self._execute(
                "SELECT collection_id, name, dimension, dtype, distance_metric, "
                "model_id, chunking_identity, normalization_identity, "
                "published_generation_id, status, created_at, updated_at, "
                "metadata_json FROM vector_collections "
                "WHERE status = 'active' ORDER BY collection_id"
            ).fetchall()
        return [self._collection_from_row(r) for r in rows]

    def delete_collection(
        self,
        collection_id: str,
        *,
        reason: Optional[str] = None,
    ) -> TombstoneRecord:
        """Tombstone a collection so it is no longer query-visible."""

        cid = _require_id(collection_id, field="collection_id")
        now = _utc_now_iso()
        with self._txn() as conn:
            col = self._require_collection(conn, cid, allow_tombstoned=True)
            if col.status == "tombstoned":
                # Idempotent: return latest tombstone if present.
                row = conn.execute(
                    "SELECT tombstone_id, collection_id, entity_type, entity_id, "
                    "generation_id, prior_content_digest, reason, tombstoned_at "
                    "FROM vector_tombstones "
                    "WHERE collection_id = ? AND entity_type = 'collection' "
                    "AND entity_id = ? ORDER BY tombstoned_at DESC LIMIT 1",
                    [cid, cid],
                ).fetchone()
                if row is not None:
                    return self._tombstone_from_row(row)
            conn.execute(
                "UPDATE vector_collections SET status = 'tombstoned', "
                "updated_at = ?, published_generation_id = NULL "
                "WHERE collection_id = ?",
                [now, cid],
            )
            # Hide all active chunks for this collection from query surfaces.
            conn.execute(
                "UPDATE vector_chunks SET status = 'tombstoned', updated_at = ? "
                "WHERE collection_id = ? AND status = 'active'",
                [now, cid],
            )
            return self._insert_tombstone(
                conn,
                collection_id=cid,
                entity_type="collection",
                entity_id=cid,
                generation_id=col.published_generation_id,
                prior_content_digest=None,
                reason=reason,
                now=now,
            )

    # -- public: generations -----------------------------------------------

    def begin_generation(
        self,
        collection_id: str,
        *,
        generation_id: Optional[str] = None,
        model_id: Optional[str] = None,
        chunking_identity: Optional[str] = None,
        normalization_identity: Optional[str] = None,
        metadata: Optional[Mapping[str, Any]] = None,
    ) -> GenerationRecord:
        """Open a draft generation. Identity fields default to the collection."""

        cid = _require_id(collection_id, field="collection_id")
        gid = _require_id(
            generation_id or _new_id("gen"), field="generation_id"
        )
        now = _utc_now_iso()
        meta_json = _metadata_json(metadata)

        with self._txn() as conn:
            col = self._require_collection(conn, cid)
            mid = _require_id(model_id or col.model_id, field="model_id")
            chunking = normalize_chunking_identity(
                chunking_identity or col.chunking_identity
            )
            normalization = normalize_normalization_identity(
                normalization_identity or col.normalization_identity
            )
            model_row = self._get_model_row(conn, mid)
            if model_row is None:
                raise VectorStoreError(
                    "NOT_FOUND",
                    f"model not found: {mid}",
                    details={"model_id": mid},
                )
            model = self._model_from_row(model_row)
            if model.dimension != col.dimension or model.dtype != col.dtype:
                raise VectorStoreError(
                    "DIMENSION_MISMATCH",
                    "generation model contracts must match collection",
                    details={
                        "collection_dimension": col.dimension,
                        "model_dimension": model.dimension,
                    },
                )
            existing = self._get_generation_row(conn, cid, gid)
            if existing is not None:
                raise VectorStoreError(
                    "ALREADY_EXISTS",
                    f"generation already exists: {gid}",
                    details={"generation_id": gid},
                )
            # Only one draft per collection at a time (simplifies publication).
            draft = conn.execute(
                "SELECT generation_id FROM vector_generations "
                "WHERE collection_id = ? AND status = 'draft' LIMIT 1",
                [cid],
            ).fetchone()
            if draft is not None:
                raise VectorStoreError(
                    "CONFLICT",
                    f"collection already has draft generation {draft[0]}",
                    details={
                        "collection_id": cid,
                        "draft_generation_id": draft[0],
                    },
                )
            parent = col.published_generation_id
            conn.execute(
                "INSERT INTO vector_generations ("
                "collection_id, generation_id, parent_generation_id, status, "
                "model_id, chunking_identity, normalization_identity, "
                "content_digest, created_at, published_at, metadata_json"
                ") VALUES (?, ?, ?, 'draft', ?, ?, ?, NULL, ?, NULL, ?)",
                [
                    cid,
                    gid,
                    parent,
                    mid,
                    chunking,
                    normalization,
                    now,
                    meta_json,
                ],
            )
            return GenerationRecord(
                collection_id=cid,
                generation_id=gid,
                parent_generation_id=parent,
                status="draft",
                model_id=mid,
                chunking_identity=chunking,
                normalization_identity=normalization,
                content_digest=None,
                created_at=now,
                published_at=None,
                metadata=_parse_metadata(meta_json),
            )

    def publish_generation(
        self,
        collection_id: str,
        generation_id: str,
    ) -> GenerationRecord:
        """Atomically publish a draft generation as the query-visible head."""

        cid = _require_id(collection_id, field="collection_id")
        gid = _require_id(generation_id, field="generation_id")
        now = _utc_now_iso()

        with self._txn() as conn:
            col = self._require_collection(conn, cid)
            gen = self._require_generation(
                conn, cid, gid, require_status="draft"
            )
            # Require mandatory identities still present (defensive).
            if not (
                gen.model_id and gen.chunking_identity and gen.normalization_identity
            ):
                raise VectorStoreError(
                    "INVALID_REQUEST",
                    "generation lacks mandatory model/chunking/normalization identity",
                )

            # Content digest over all active chunks in this generation.
            chunk_rows = conn.execute(
                "SELECT chunk_id, content_digest, vector_digest, revision "
                "FROM vector_chunks "
                "WHERE collection_id = ? AND generation_id = ? AND status = 'active' "
                "ORDER BY chunk_id",
                [cid, gid],
            ).fetchall()
            digest = content_identity(
                {
                    "collection_id": cid,
                    "generation_id": gid,
                    "model_id": gen.model_id,
                    "chunking_identity": gen.chunking_identity,
                    "normalization_identity": gen.normalization_identity,
                    "chunks": [
                        {
                            "chunk_id": r[0],
                            "content_digest": r[1],
                            "vector_digest": r[2],
                            "revision": int(r[3]),
                        }
                        for r in chunk_rows
                    ],
                }
            )

            previous = col.published_generation_id
            if previous is not None and previous != gid:
                prev_row = self._get_generation_row(conn, cid, previous)
                if prev_row is not None and prev_row[3] == "published":
                    conn.execute(
                        "UPDATE vector_generations SET status = 'superseded' "
                        "WHERE collection_id = ? AND generation_id = ? "
                        "AND status = 'published'",
                        [cid, previous],
                    )

            conn.execute(
                "UPDATE vector_generations SET status = 'published', "
                "published_at = ?, content_digest = ? "
                "WHERE collection_id = ? AND generation_id = ? AND status = 'draft'",
                [now, digest, cid, gid],
            )
            # Verify single-row update (atomic CAS-like).
            status_row = conn.execute(
                "SELECT status, content_digest, published_at FROM vector_generations "
                "WHERE collection_id = ? AND generation_id = ?",
                [cid, gid],
            ).fetchone()
            if status_row is None or status_row[0] != "published":
                raise VectorStoreError(
                    "CONFLICT",
                    "generation publish failed (status not published)",
                    details={"generation_id": gid},
                )

            conn.execute(
                "UPDATE vector_collections SET published_generation_id = ?, "
                "updated_at = ?, model_id = ?, chunking_identity = ?, "
                "normalization_identity = ? "
                "WHERE collection_id = ? AND status = 'active'",
                [
                    gid,
                    now,
                    gen.model_id,
                    gen.chunking_identity,
                    gen.normalization_identity,
                    cid,
                ],
            )
            return GenerationRecord(
                collection_id=cid,
                generation_id=gid,
                parent_generation_id=gen.parent_generation_id,
                status="published",
                model_id=gen.model_id,
                chunking_identity=gen.chunking_identity,
                normalization_identity=gen.normalization_identity,
                content_digest=digest,
                created_at=gen.created_at,
                published_at=now,
                metadata=gen.metadata,
            )

    def abort_generation(
        self,
        collection_id: str,
        generation_id: str,
        *,
        reason: Optional[str] = None,
    ) -> GenerationRecord:
        cid = _require_id(collection_id, field="collection_id")
        gid = _require_id(generation_id, field="generation_id")
        now = _utc_now_iso()
        with self._txn() as conn:
            gen = self._require_generation(
                conn, cid, gid, require_status="draft"
            )
            conn.execute(
                "UPDATE vector_generations SET status = 'aborted' "
                "WHERE collection_id = ? AND generation_id = ?",
                [cid, gid],
            )
            conn.execute(
                "UPDATE vector_chunks SET status = 'tombstoned', updated_at = ? "
                "WHERE collection_id = ? AND generation_id = ? AND status = 'active'",
                [now, cid, gid],
            )
            self._insert_tombstone(
                conn,
                collection_id=cid,
                entity_type="generation",
                entity_id=gid,
                generation_id=gid,
                prior_content_digest=gen.content_digest,
                reason=reason or "aborted",
                now=now,
            )
            return GenerationRecord(
                collection_id=cid,
                generation_id=gid,
                parent_generation_id=gen.parent_generation_id,
                status="aborted",
                model_id=gen.model_id,
                chunking_identity=gen.chunking_identity,
                normalization_identity=gen.normalization_identity,
                content_digest=gen.content_digest,
                created_at=gen.created_at,
                published_at=None,
                metadata=gen.metadata,
            )

    def get_generation(
        self, collection_id: str, generation_id: str
    ) -> GenerationRecord:
        cid = _require_id(collection_id, field="collection_id")
        gid = _require_id(generation_id, field="generation_id")
        row = self._execute(
            "SELECT collection_id, generation_id, parent_generation_id, status, "
            "model_id, chunking_identity, normalization_identity, content_digest, "
            "created_at, published_at, metadata_json "
            "FROM vector_generations "
            "WHERE collection_id = ? AND generation_id = ?",
            [cid, gid],
        ).fetchone()
        if row is None:
            raise VectorStoreError(
                "NOT_FOUND",
                f"generation not found: {gid}",
                details={"collection_id": cid, "generation_id": gid},
            )
        return self._generation_from_row(row)

    def list_generations(self, collection_id: str) -> List[GenerationRecord]:
        cid = _require_id(collection_id, field="collection_id")
        rows = self._execute(
            "SELECT collection_id, generation_id, parent_generation_id, status, "
            "model_id, chunking_identity, normalization_identity, content_digest, "
            "created_at, published_at, metadata_json "
            "FROM vector_generations WHERE collection_id = ? "
            "ORDER BY created_at, generation_id",
            [cid],
        ).fetchall()
        return [self._generation_from_row(r) for r in rows]

    # -- public: documents / chunks ----------------------------------------

    def upsert_document(
        self,
        *,
        collection_id: str,
        document_id: str,
        generation_id: str,
        source_identity: Union[str, Mapping[str, Any]],
        source_bytes: Optional[bytes] = None,
        source_digest: Optional[str] = None,
        metadata: Optional[Mapping[str, Any]] = None,
    ) -> DocumentRecord:
        cid = _require_id(collection_id, field="collection_id")
        did = _require_id(document_id, field="document_id")
        gid = _require_id(generation_id, field="generation_id")
        source = normalize_source_identity(source_identity)
        if source_bytes is not None:
            sdigest = SourceDigest.from_bytes(bytes(source_bytes)).digest
        elif source_digest is not None:
            try:
                sdigest = parse_source_digest(source_digest)
            except ContractError as exc:
                raise VectorStoreError(
                    "INVALID_REQUEST",
                    f"invalid source_digest: {exc}",
                ) from exc
        else:
            sdigest = _digest_text(source)
        meta_json = _metadata_json(metadata)
        content_digest = content_identity(
            {
                "document_id": did,
                "source_identity": source,
                "source_digest": sdigest,
                "metadata": _parse_metadata(meta_json),
            }
        )
        now = _utc_now_iso()
        with self._txn() as conn:
            self._require_collection(conn, cid)
            self._require_generation(conn, cid, gid, require_status="draft")
            existing = conn.execute(
                "SELECT collection_id FROM vector_documents "
                "WHERE collection_id = ? AND document_id = ? AND generation_id = ?",
                [cid, did, gid],
            ).fetchone()
            if existing is None:
                conn.execute(
                    "INSERT INTO vector_documents ("
                    "collection_id, document_id, generation_id, source_identity, "
                    "source_digest, content_digest, created_at, metadata_json"
                    ") VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    [
                        cid,
                        did,
                        gid,
                        source,
                        sdigest,
                        content_digest,
                        now,
                        meta_json,
                    ],
                )
            else:
                conn.execute(
                    "UPDATE vector_documents SET source_identity = ?, "
                    "source_digest = ?, content_digest = ?, metadata_json = ? "
                    "WHERE collection_id = ? AND document_id = ? AND generation_id = ?",
                    [
                        source,
                        sdigest,
                        content_digest,
                        meta_json,
                        cid,
                        did,
                        gid,
                    ],
                )
            return DocumentRecord(
                collection_id=cid,
                document_id=did,
                generation_id=gid,
                source_identity=source,
                source_digest=sdigest,
                content_digest=content_digest,
                created_at=now,
                metadata=_parse_metadata(meta_json),
            )

    def upsert_chunk(
        self,
        *,
        collection_id: str,
        chunk_id: str,
        document_id: str,
        generation_id: str,
        vector: Sequence[float],
        source_identity: Union[str, Mapping[str, Any]],
        chunk_index: int = 0,
        text: Optional[str] = None,
        text_digest: Optional[str] = None,
        shard_id: Optional[str] = None,
        metadata: Optional[Mapping[str, Any]] = None,
    ) -> ChunkRecord:
        """Insert or replace a chunk in a **draft** generation.

        Replacement is transactional: the prior vector is tombstoned for audit
        and the row is rewritten so no query can observe a mixed old/new state.
        """

        cid = _require_id(collection_id, field="collection_id")
        chid = _require_id(chunk_id, field="chunk_id")
        did = _require_id(document_id, field="document_id")
        gid = _require_id(generation_id, field="generation_id")
        source = normalize_source_identity(source_identity)
        if not isinstance(chunk_index, int) or isinstance(chunk_index, bool) or chunk_index < 0:
            raise VectorStoreError(
                "INVALID_REQUEST",
                "chunk_index must be a non-negative integer",
            )
        if text is not None:
            if not isinstance(text, str):
                raise VectorStoreError("INVALID_REQUEST", "text must be a string")
            if len(text.encode("utf-8")) > _MAX_TEXT_BYTES:
                raise VectorStoreError("INVALID_REQUEST", "text exceeds size bound")
            tdigest = _digest_text(text)
        elif text_digest is not None:
            try:
                tdigest = parse_source_digest(text_digest)
            except ContractError as exc:
                raise VectorStoreError(
                    "INVALID_REQUEST", f"invalid text_digest: {exc}"
                ) from exc
        else:
            tdigest = _digest_text("")
        sid = (
            _require_id(shard_id, field="shard_id")
            if shard_id is not None
            else None
        )
        meta_json = _metadata_json(metadata)
        now = _utc_now_iso()

        with self._txn() as conn:
            col = self._require_collection(conn, cid)
            self._require_generation(conn, cid, gid, require_status="draft")
            vector_blob = encode_vector_bytes(
                vector, dimension=col.dimension, dtype=col.dtype
            )
            vdigest = vector_content_digest(vector_blob)
            content_digest = content_identity(
                {
                    "chunk_id": chid,
                    "document_id": did,
                    "source_identity": source,
                    "chunk_index": chunk_index,
                    "text_digest": tdigest,
                    "vector_digest": vdigest,
                    "dimension": col.dimension,
                    "dtype": col.dtype,
                    "metadata": _parse_metadata(meta_json),
                }
            )
            existing = self._get_chunk_row(conn, cid, chid, gid)
            if existing is None:
                revision = 1
                conn.execute(
                    "INSERT INTO vector_chunks ("
                    "collection_id, chunk_id, document_id, generation_id, "
                    "source_identity, chunk_index, text_digest, content_digest, "
                    "vector_digest, dimension, dtype, status, revision, shard_id, "
                    "vector_blob, created_at, updated_at, metadata_json"
                    ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?, ?, ?, ?, ?)",
                    [
                        cid,
                        chid,
                        did,
                        gid,
                        source,
                        chunk_index,
                        tdigest,
                        content_digest,
                        vdigest,
                        col.dimension,
                        col.dtype,
                        revision,
                        sid,
                        vector_blob,
                        now,
                        now,
                        meta_json,
                    ],
                )
                created_at = now
            else:
                prior = self._chunk_from_row(existing, include_vector=False)
                # Tombstone prior content so update never leaves stale authority.
                self._insert_tombstone(
                    conn,
                    collection_id=cid,
                    entity_type="chunk",
                    entity_id=chid,
                    generation_id=gid,
                    prior_content_digest=prior.content_digest,
                    reason="update",
                    now=now,
                )
                revision = prior.revision + 1
                conn.execute(
                    "UPDATE vector_chunks SET document_id = ?, source_identity = ?, "
                    "chunk_index = ?, text_digest = ?, content_digest = ?, "
                    "vector_digest = ?, status = 'active', revision = ?, "
                    "shard_id = ?, vector_blob = ?, updated_at = ?, metadata_json = ? "
                    "WHERE collection_id = ? AND chunk_id = ? AND generation_id = ?",
                    [
                        did,
                        source,
                        chunk_index,
                        tdigest,
                        content_digest,
                        vdigest,
                        revision,
                        sid,
                        vector_blob,
                        now,
                        meta_json,
                        cid,
                        chid,
                        gid,
                    ],
                )
                created_at = prior.created_at

            if sid is not None:
                shard_row = conn.execute(
                    "SELECT shard_id, dimension, dtype FROM vector_shards "
                    "WHERE shard_id = ?",
                    [sid],
                ).fetchone()
                if shard_row is None:
                    raise VectorStoreError(
                        "NOT_FOUND",
                        f"shard not found: {sid}",
                        details={"shard_id": sid},
                    )
                if int(shard_row[1]) != col.dimension or shard_row[2] != col.dtype:
                    raise VectorStoreError(
                        "DIMENSION_MISMATCH",
                        "shard dimension/dtype does not match collection",
                    )

            return ChunkRecord(
                collection_id=cid,
                chunk_id=chid,
                document_id=did,
                generation_id=gid,
                source_identity=source,
                chunk_index=chunk_index,
                text_digest=tdigest,
                content_digest=content_digest,
                vector_digest=vdigest,
                dimension=col.dimension,
                dtype=col.dtype,
                status="active",
                revision=revision,
                shard_id=sid,
                created_at=created_at,
                updated_at=now,
                metadata=_parse_metadata(meta_json),
                vector=list(map(float, vector)),
            )

    def update_chunk(
        self,
        *,
        collection_id: str,
        chunk_id: str,
        generation_id: str,
        vector: Sequence[float],
        source_identity: Optional[Union[str, Mapping[str, Any]]] = None,
        text: Optional[str] = None,
        metadata: Optional[Mapping[str, Any]] = None,
    ) -> ChunkRecord:
        """Update an existing draft chunk; fails if missing.

        Atomic replace: tombstone prior content + rewrite row in one transaction.
        """

        cid = _require_id(collection_id, field="collection_id")
        chid = _require_id(chunk_id, field="chunk_id")
        gid = _require_id(generation_id, field="generation_id")
        with self._lock:
            self._ensure_open()
            row = self._get_chunk_row(self._conn, cid, chid, gid)
            if row is None:
                raise VectorStoreError(
                    "NOT_FOUND",
                    f"chunk not found: {chid}",
                    details={
                        "collection_id": cid,
                        "chunk_id": chid,
                        "generation_id": gid,
                    },
                )
            prior = self._chunk_from_row(row, include_vector=False)
        return self.upsert_chunk(
            collection_id=cid,
            chunk_id=chid,
            document_id=prior.document_id,
            generation_id=gid,
            vector=vector,
            source_identity=(
                source_identity
                if source_identity is not None
                else prior.source_identity
            ),
            chunk_index=prior.chunk_index,
            text=text,
            text_digest=None if text is not None else prior.text_digest,
            shard_id=prior.shard_id,
            metadata=metadata if metadata is not None else prior.metadata,
        )

    def delete_chunk(
        self,
        *,
        collection_id: str,
        chunk_id: str,
        generation_id: str,
        reason: Optional[str] = None,
    ) -> TombstoneRecord:
        """Tombstone a chunk so it is never query-visible after commit."""

        cid = _require_id(collection_id, field="collection_id")
        chid = _require_id(chunk_id, field="chunk_id")
        gid = _require_id(generation_id, field="generation_id")
        now = _utc_now_iso()
        with self._txn() as conn:
            # Deletion is allowed on draft only for generation integrity;
            # published generations are immutable — delete via new generation.
            self._require_generation(conn, cid, gid, require_status="draft")
            row = self._get_chunk_row(conn, cid, chid, gid)
            if row is None:
                raise VectorStoreError(
                    "NOT_FOUND",
                    f"chunk not found: {chid}",
                    details={
                        "collection_id": cid,
                        "chunk_id": chid,
                        "generation_id": gid,
                    },
                )
            prior = self._chunk_from_row(row, include_vector=False)
            if prior.status == "tombstoned":
                existing = conn.execute(
                    "SELECT tombstone_id, collection_id, entity_type, entity_id, "
                    "generation_id, prior_content_digest, reason, tombstoned_at "
                    "FROM vector_tombstones "
                    "WHERE collection_id = ? AND entity_type = 'chunk' "
                    "AND entity_id = ? AND generation_id = ? "
                    "ORDER BY tombstoned_at DESC LIMIT 1",
                    [cid, chid, gid],
                ).fetchone()
                if existing is not None:
                    return self._tombstone_from_row(existing)
            conn.execute(
                "UPDATE vector_chunks SET status = 'tombstoned', updated_at = ? "
                "WHERE collection_id = ? AND chunk_id = ? AND generation_id = ?",
                [now, cid, chid, gid],
            )
            return self._insert_tombstone(
                conn,
                collection_id=cid,
                entity_type="chunk",
                entity_id=chid,
                generation_id=gid,
                prior_content_digest=prior.content_digest,
                reason=reason or "delete",
                now=now,
            )

    def get_chunk(
        self,
        *,
        collection_id: str,
        chunk_id: str,
        generation_id: Optional[str] = None,
        include_vector: bool = True,
        query_visible_only: bool = False,
    ) -> ChunkRecord:
        cid = _require_id(collection_id, field="collection_id")
        chid = _require_id(chunk_id, field="chunk_id")
        col = self.get_collection(cid)
        gid = generation_id
        if gid is None:
            if col.published_generation_id is None:
                raise VectorStoreError(
                    "NOT_FOUND",
                    "collection has no published generation",
                    details={"collection_id": cid},
                )
            gid = col.published_generation_id
        gid = _require_id(gid, field="generation_id")
        row = self._execute(
            "SELECT collection_id, chunk_id, document_id, generation_id, "
            "source_identity, chunk_index, text_digest, content_digest, "
            "vector_digest, dimension, dtype, status, revision, shard_id, "
            "vector_blob, created_at, updated_at, metadata_json "
            "FROM vector_chunks "
            "WHERE collection_id = ? AND chunk_id = ? AND generation_id = ?",
            [cid, chid, gid],
        ).fetchone()
        if row is None:
            raise VectorStoreError(
                "NOT_FOUND",
                f"chunk not found: {chid}",
                details={
                    "collection_id": cid,
                    "chunk_id": chid,
                    "generation_id": gid,
                },
            )
        record = self._chunk_from_row(row, include_vector=include_vector)
        if query_visible_only:
            if (
                col.published_generation_id != gid
                or record.status != "active"
                or col.status != "active"
            ):
                raise VectorStoreError(
                    "NOT_FOUND",
                    f"chunk is not query-visible: {chid}",
                    details={
                        "collection_id": cid,
                        "chunk_id": chid,
                        "generation_id": gid,
                        "status": record.status,
                    },
                )
        return record

    def list_visible_chunks(
        self,
        collection_id: str,
        *,
        include_vector: bool = False,
        limit: Optional[int] = None,
    ) -> List[ChunkRecord]:
        """Return query-visible chunks (published generation, active only)."""

        cid = _require_id(collection_id, field="collection_id")
        col = self.get_collection(cid)
        if col.status != "active" or col.published_generation_id is None:
            return []
        gid = col.published_generation_id
        sql = (
            "SELECT collection_id, chunk_id, document_id, generation_id, "
            "source_identity, chunk_index, text_digest, content_digest, "
            "vector_digest, dimension, dtype, status, revision, shard_id, "
            "vector_blob, created_at, updated_at, metadata_json "
            "FROM vector_chunks "
            "WHERE collection_id = ? AND generation_id = ? AND status = 'active' "
            "ORDER BY chunk_id"
        )
        params: List[Any] = [cid, gid]
        if limit is not None:
            if not isinstance(limit, int) or isinstance(limit, bool) or limit < 0:
                raise VectorStoreError(
                    "INVALID_REQUEST", "limit must be a non-negative int"
                )
            sql += " LIMIT ?"
            params.append(limit)
        rows = self._execute(sql, params).fetchall()
        return [
            self._chunk_from_row(r, include_vector=include_vector) for r in rows
        ]

    def list_chunks(
        self,
        collection_id: str,
        generation_id: str,
        *,
        include_tombstoned: bool = False,
        include_vector: bool = False,
    ) -> List[ChunkRecord]:
        cid = _require_id(collection_id, field="collection_id")
        gid = _require_id(generation_id, field="generation_id")
        if include_tombstoned:
            rows = self._execute(
                "SELECT collection_id, chunk_id, document_id, generation_id, "
                "source_identity, chunk_index, text_digest, content_digest, "
                "vector_digest, dimension, dtype, status, revision, shard_id, "
                "vector_blob, created_at, updated_at, metadata_json "
                "FROM vector_chunks "
                "WHERE collection_id = ? AND generation_id = ? "
                "ORDER BY chunk_id",
                [cid, gid],
            ).fetchall()
        else:
            rows = self._execute(
                "SELECT collection_id, chunk_id, document_id, generation_id, "
                "source_identity, chunk_index, text_digest, content_digest, "
                "vector_digest, dimension, dtype, status, revision, shard_id, "
                "vector_blob, created_at, updated_at, metadata_json "
                "FROM vector_chunks "
                "WHERE collection_id = ? AND generation_id = ? AND status = 'active' "
                "ORDER BY chunk_id",
                [cid, gid],
            ).fetchall()
        return [
            self._chunk_from_row(r, include_vector=include_vector) for r in rows
        ]

    # -- public: shards / compaction / index builds ------------------------

    def create_shard(
        self,
        *,
        collection_id: str,
        generation_id: str,
        shard_id: Optional[str] = None,
        metadata: Optional[Mapping[str, Any]] = None,
    ) -> ShardRecord:
        cid = _require_id(collection_id, field="collection_id")
        gid = _require_id(generation_id, field="generation_id")
        sid = _require_id(shard_id or _new_id("shard"), field="shard_id")
        meta_json = _metadata_json(metadata)
        now = _utc_now_iso()
        with self._txn() as conn:
            col = self._require_collection(conn, cid)
            self._require_generation(conn, cid, gid)
            existing = conn.execute(
                "SELECT shard_id FROM vector_shards WHERE shard_id = ?",
                [sid],
            ).fetchone()
            if existing is not None:
                raise VectorStoreError(
                    "ALREADY_EXISTS",
                    f"shard already exists: {sid}",
                    details={"shard_id": sid},
                )
            conn.execute(
                "INSERT INTO vector_shards ("
                "shard_id, collection_id, generation_id, dimension, dtype, "
                "status, vector_count, content_digest, created_at, sealed_at, "
                "metadata_json"
                ") VALUES (?, ?, ?, ?, ?, 'open', 0, NULL, ?, NULL, ?)",
                [
                    sid,
                    cid,
                    gid,
                    col.dimension,
                    col.dtype,
                    now,
                    meta_json,
                ],
            )
            return ShardRecord(
                shard_id=sid,
                collection_id=cid,
                generation_id=gid,
                dimension=col.dimension,
                dtype=col.dtype,
                status="open",
                vector_count=0,
                content_digest=None,
                created_at=now,
                sealed_at=None,
                metadata=_parse_metadata(meta_json),
            )

    def seal_shard(
        self,
        shard_id: str,
        *,
        content_digest: Optional[str] = None,
    ) -> ShardRecord:
        sid = _require_id(shard_id, field="shard_id")
        now = _utc_now_iso()
        with self._txn() as conn:
            row = conn.execute(
                "SELECT shard_id, collection_id, generation_id, dimension, dtype, "
                "status, vector_count, content_digest, created_at, sealed_at, "
                "metadata_json FROM vector_shards WHERE shard_id = ?",
                [sid],
            ).fetchone()
            if row is None:
                raise VectorStoreError(
                    "NOT_FOUND",
                    f"shard not found: {sid}",
                    details={"shard_id": sid},
                )
            count_row = conn.execute(
                "SELECT COUNT(*) FROM vector_chunks "
                "WHERE shard_id = ? AND status = 'active'",
                [sid],
            ).fetchone()
            count = int(count_row[0]) if count_row else 0
            digests = conn.execute(
                "SELECT vector_digest FROM vector_chunks "
                "WHERE shard_id = ? AND status = 'active' ORDER BY chunk_id",
                [sid],
            ).fetchall()
            auto_digest = content_identity(
                {"shard_id": sid, "vectors": [r[0] for r in digests]}
            )
            final_digest = (
                parse_source_digest(content_digest)
                if content_digest is not None
                else auto_digest
            )
            conn.execute(
                "UPDATE vector_shards SET status = 'sealed', vector_count = ?, "
                "content_digest = ?, sealed_at = ? WHERE shard_id = ?",
                [count, final_digest, now, sid],
            )
            return ShardRecord(
                shard_id=sid,
                collection_id=row[1],
                generation_id=row[2],
                dimension=int(row[3]),
                dtype=row[4],
                status="sealed",
                vector_count=count,
                content_digest=final_digest,
                created_at=row[8],
                sealed_at=now,
                metadata=_parse_metadata(row[10]),
            )

    def list_shards(
        self, collection_id: str, *, generation_id: Optional[str] = None
    ) -> List[ShardRecord]:
        cid = _require_id(collection_id, field="collection_id")
        if generation_id is None:
            rows = self._execute(
                "SELECT shard_id, collection_id, generation_id, dimension, dtype, "
                "status, vector_count, content_digest, created_at, sealed_at, "
                "metadata_json FROM vector_shards "
                "WHERE collection_id = ? ORDER BY shard_id",
                [cid],
            ).fetchall()
        else:
            gid = _require_id(generation_id, field="generation_id")
            rows = self._execute(
                "SELECT shard_id, collection_id, generation_id, dimension, dtype, "
                "status, vector_count, content_digest, created_at, sealed_at, "
                "metadata_json FROM vector_shards "
                "WHERE collection_id = ? AND generation_id = ? ORDER BY shard_id",
                [cid, gid],
            ).fetchall()
        return [self._shard_from_row(r) for r in rows]

    def record_compaction(
        self,
        *,
        collection_id: str,
        generation_id: str,
        input_shard_ids: Sequence[str],
        output_shard_id: Optional[str] = None,
        compaction_id: Optional[str] = None,
        status: str = "completed",
        receipt: Optional[Mapping[str, Any]] = None,
    ) -> CompactionRecord:
        cid = _require_id(collection_id, field="collection_id")
        gid = _require_id(generation_id, field="generation_id")
        cpid = _require_id(
            compaction_id or _new_id("compact"), field="compaction_id"
        )
        if status not in COMPACTION_STATUSES:
            raise VectorStoreError(
                "INVALID_REQUEST",
                f"status must be one of {sorted(COMPACTION_STATUSES)}",
            )
        inputs = [
            _require_id(s, field="input_shard_id") for s in input_shard_ids
        ]
        out = (
            _require_id(output_shard_id, field="output_shard_id")
            if output_shard_id is not None
            else None
        )
        receipt_json = _metadata_json(receipt)
        now = _utc_now_iso()
        completed_at = now if status == "completed" else None
        with self._txn() as conn:
            self._require_collection(conn, cid)
            self._require_generation(conn, cid, gid)
            for shard in inputs:
                row = conn.execute(
                    "SELECT shard_id FROM vector_shards WHERE shard_id = ?",
                    [shard],
                ).fetchone()
                if row is None:
                    raise VectorStoreError(
                        "NOT_FOUND",
                        f"input shard not found: {shard}",
                        details={"shard_id": shard},
                    )
            if out is not None:
                row = conn.execute(
                    "SELECT shard_id FROM vector_shards WHERE shard_id = ?",
                    [out],
                ).fetchone()
                if row is None:
                    raise VectorStoreError(
                        "NOT_FOUND",
                        f"output shard not found: {out}",
                        details={"shard_id": out},
                    )
            conn.execute(
                "INSERT INTO vector_compactions ("
                "compaction_id, collection_id, generation_id, status, "
                "input_shards_json, output_shard_id, receipt_json, "
                "created_at, completed_at"
                ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    cpid,
                    cid,
                    gid,
                    status,
                    json.dumps(inputs, separators=(",", ":")),
                    out,
                    receipt_json,
                    now,
                    completed_at,
                ],
            )
            if status == "completed":
                for shard in inputs:
                    conn.execute(
                        "UPDATE vector_shards SET status = 'compacted' "
                        "WHERE shard_id = ?",
                        [shard],
                    )
            return CompactionRecord(
                compaction_id=cpid,
                collection_id=cid,
                generation_id=gid,
                status=status,
                input_shard_ids=list(inputs),
                output_shard_id=out,
                receipt=_parse_metadata(receipt_json),
                created_at=now,
                completed_at=completed_at,
            )

    def list_compactions(self, collection_id: str) -> List[CompactionRecord]:
        cid = _require_id(collection_id, field="collection_id")
        rows = self._execute(
            "SELECT compaction_id, collection_id, generation_id, status, "
            "input_shards_json, output_shard_id, receipt_json, created_at, "
            "completed_at FROM vector_compactions "
            "WHERE collection_id = ? ORDER BY created_at, compaction_id",
            [cid],
        ).fetchall()
        return [self._compaction_from_row(r) for r in rows]

    def record_index_build(
        self,
        *,
        collection_id: str,
        generation_id: str,
        index_kind: str,
        build_id: Optional[str] = None,
        status: str = "completed",
        receipt: Optional[Mapping[str, Any]] = None,
    ) -> IndexBuildRecord:
        cid = _require_id(collection_id, field="collection_id")
        gid = _require_id(generation_id, field="generation_id")
        bid = _require_id(build_id or _new_id("idx"), field="build_id")
        if not isinstance(index_kind, str) or not index_kind.strip():
            raise VectorStoreError(
                "INVALID_REQUEST", "index_kind is mandatory"
            )
        kind = index_kind.strip()
        if status not in INDEX_BUILD_STATUSES:
            raise VectorStoreError(
                "INVALID_REQUEST",
                f"status must be one of {sorted(INDEX_BUILD_STATUSES)}",
            )
        receipt_json = _metadata_json(receipt)
        now = _utc_now_iso()
        completed_at = now if status == "completed" else None
        with self._txn() as conn:
            self._require_collection(conn, cid)
            self._require_generation(conn, cid, gid)
            conn.execute(
                "INSERT INTO vector_index_builds ("
                "build_id, collection_id, generation_id, index_kind, status, "
                "receipt_json, created_at, completed_at"
                ") VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    bid,
                    cid,
                    gid,
                    kind,
                    status,
                    receipt_json,
                    now,
                    completed_at,
                ],
            )
            return IndexBuildRecord(
                build_id=bid,
                collection_id=cid,
                generation_id=gid,
                index_kind=kind,
                status=status,
                receipt=_parse_metadata(receipt_json),
                created_at=now,
                completed_at=completed_at,
            )

    def list_index_builds(self, collection_id: str) -> List[IndexBuildRecord]:
        cid = _require_id(collection_id, field="collection_id")
        rows = self._execute(
            "SELECT build_id, collection_id, generation_id, index_kind, status, "
            "receipt_json, created_at, completed_at "
            "FROM vector_index_builds "
            "WHERE collection_id = ? ORDER BY created_at, build_id",
            [cid],
        ).fetchall()
        return [self._index_build_from_row(r) for r in rows]

    def list_tombstones(
        self,
        collection_id: str,
        *,
        entity_type: Optional[str] = None,
    ) -> List[TombstoneRecord]:
        cid = _require_id(collection_id, field="collection_id")
        if entity_type is None:
            rows = self._execute(
                "SELECT tombstone_id, collection_id, entity_type, entity_id, "
                "generation_id, prior_content_digest, reason, tombstoned_at "
                "FROM vector_tombstones WHERE collection_id = ? "
                "ORDER BY tombstoned_at, tombstone_id",
                [cid],
            ).fetchall()
        else:
            if entity_type not in ENTITY_TYPES:
                raise VectorStoreError(
                    "INVALID_REQUEST",
                    f"entity_type must be one of {sorted(ENTITY_TYPES)}",
                )
            rows = self._execute(
                "SELECT tombstone_id, collection_id, entity_type, entity_id, "
                "generation_id, prior_content_digest, reason, tombstoned_at "
                "FROM vector_tombstones "
                "WHERE collection_id = ? AND entity_type = ? "
                "ORDER BY tombstoned_at, tombstone_id",
                [cid, entity_type],
            ).fetchall()
        return [self._tombstone_from_row(r) for r in rows]

    def list_dimension_tables(self) -> List[Dict[str, Any]]:
        rows = self._execute(
            "SELECT dimension, dtype, physical_table, created_at "
            "FROM vector_values_by_dimension ORDER BY dimension, dtype"
        ).fetchall()
        return [
            {
                "dimension": int(r[0]),
                "dtype": r[1],
                "physical_table": r[2],
                "created_at": r[3],
            }
            for r in rows
        ]

    def meta(self) -> Dict[str, str]:
        rows = self._execute(
            "SELECT key, value FROM vector_store_meta ORDER BY key"
        ).fetchall()
        return {str(r[0]): str(r[1]) for r in rows}

    def asserts_no_pickle_authority(self) -> bool:
        """Return True when the store declares pickle authority forbidden."""

        meta = self.meta()
        return meta.get("pickle_authority") == "forbidden"


def open_vector_store(
    path: PathLike = ":memory:",
    *,
    read_only: bool = False,
) -> DuckDBVectorStore:
    """Open (or create) a DuckDB vector store at ``path``."""

    return DuckDBVectorStore(path, read_only=read_only)
