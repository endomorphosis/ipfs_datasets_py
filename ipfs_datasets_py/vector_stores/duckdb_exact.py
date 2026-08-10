"""DuckDB exact FLOAT[N] vector search (DQK-021).

Authoritative dimension-specific physical tables store fixed-width SQL arrays
(``FLOAT[N]`` / ``DOUBLE[N]``).  Exact distance ranking, metadata filters, and
deterministic tie-breaking live here.  Collection generation identity and
content digests are bound on every row and returned with every hit.

Lifecycle metadata (collections, drafts, tombstones) remains in
:mod:`duckdb_store` (DQK-020).  This module may share the same DuckDB file and
materialize query-visible vectors into FLOAT[N] tables, or operate as a
standalone exact index.

Design invariants:

* One physical table per ``(dtype, dimension)`` — mixed dimensions cannot share
  a table (enforced by SQL array type and Python contracts).
* Exact metrics match NumPy float32/float64 fixtures (L2, cosine distance,
  negative inner product for ranking).
* Search results bind ``generation_id``, ``generation_content_digest``,
  ``value_digest``, and ``chunk_content_digest``.
* Equal distances break ties by ``chunk_id`` ascending (then document/ordinal).
* No pickle authority; import is side-effect free (does not open DuckDB).
"""

from __future__ import annotations

import hashlib
import json
import re
import threading
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
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

from ipfs_datasets_py.vector_stores.duckdb_store import (
    ALLOWED_DTYPES,
    DuckDBVectorStore,
    VectorStoreContractError,
    decode_vector_bytes,
    encode_vector_bytes,
    vector_content_digest,
)

__all__ = [
    "ALLOWED_METRICS",
    "DUCKDB_EXACT_SCHEMA",
    "EXACT_SCHEMA_VERSION",
    "DistanceMetric",
    "DuckDBExactVectorStore",
    "ExactSearchHit",
    "ExactVectorRow",
    "canonical_json_digest",
    "numpy_cosine_distance",
    "numpy_inner_product",
    "numpy_l2_distance",
    "physical_table_name",
    "sql_array_type",
]


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DUCKDB_EXACT_SCHEMA: Final[str] = (
    "ipfs_datasets_py/vector-stores-duckdb-exact@1"
)
EXACT_SCHEMA_VERSION: Final[int] = 1

ALLOWED_METRICS: Final[frozenset[str]] = frozenset(
    {
        "l2",
        "euclidean",
        "cosine",
        "ip",
        "inner_product",
        "dot",
    }
)

_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/@+-]{0,191}$")
_TABLE_NAME_RE = re.compile(r"^vector_exact_(f32|f64)_d([1-9][0-9]{0,4})$")
_DTYPE_SQL: Final[Mapping[str, str]] = MappingProxyType(
    {"float32": "FLOAT", "float64": "DOUBLE"}
)
_DTYPE_SHORT: Final[Mapping[str, str]] = MappingProxyType(
    {"float32": "f32", "float64": "f64"}
)

# Registry + meta always present; physical FLOAT[N] tables are created on demand.
_EXACT_CORE_SQL: Final[str] = """
CREATE TABLE IF NOT EXISTS vector_exact_meta (
    key VARCHAR PRIMARY KEY,
    value VARCHAR NOT NULL
);

CREATE TABLE IF NOT EXISTS vector_exact_dimension_tables (
    table_name VARCHAR PRIMARY KEY,
    dimension INTEGER NOT NULL,
    dtype VARCHAR NOT NULL,
    sql_array_type VARCHAR NOT NULL,
    created_at VARCHAR NOT NULL,
    UNIQUE (dimension, dtype)
);
""".strip()


# ---------------------------------------------------------------------------
# Pure helpers
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


def _require_metric(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise VectorStoreContractError(
            "INVALID_METRIC",
            "metric must be nonempty text",
        )
    metric = value.strip().lower()
    if metric not in ALLOWED_METRICS:
        raise VectorStoreContractError(
            "INVALID_METRIC",
            f"metric must be one of {sorted(ALLOWED_METRICS)}",
            details={"value": value},
        )
    return metric


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
    if re.fullmatch(r"[0-9a-f]{64}", hex_part) is None:
        raise VectorStoreContractError(
            "INVALID_DIGEST",
            f"{field} must be sha256:<64 hex> or 64 hex chars",
            details={"field": field, "value": value},
        )
    return f"sha256:{hex_part}"


def _canonical_json(payload: Any) -> bytes:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def canonical_json_digest(payload: Any) -> str:
    return "sha256:" + hashlib.sha256(_canonical_json(payload)).hexdigest()


def physical_table_name(dimension: int, dtype: str) -> str:
    """Stable, injectable-safe physical table name for one (dtype, dim)."""

    dimension = _require_dimension(dimension)
    dtype = _require_dtype(dtype)
    short = _DTYPE_SHORT[dtype]
    name = f"vector_exact_{short}_d{dimension}"
    if _TABLE_NAME_RE.fullmatch(name) is None:  # pragma: no cover - defensive
        raise VectorStoreContractError(
            "INVALID_TABLE",
            f"refusing unsafe physical table name {name!r}",
        )
    return name


def sql_array_type(dimension: int, dtype: str) -> str:
    dimension = _require_dimension(dimension)
    dtype = _require_dtype(dtype)
    return f"{_DTYPE_SQL[dtype]}[{dimension}]"


def _normalize_vector(
    values: Sequence[float],
    *,
    dimension: int,
    dtype: str,
) -> list[float]:
    """Validate and re-quantize through the same binary contract as lifecycle."""

    raw = encode_vector_bytes(values, dimension=dimension, dtype=dtype)
    decoded = decode_vector_bytes(raw, dimension=dimension, dtype=dtype)
    return list(decoded)


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


def _distance_sql_expr(metric: str) -> str:
    """SQL distance expression: lower is always better for ranking."""

    metric = _require_metric(metric)
    if metric in ("l2", "euclidean"):
        return "array_distance(v.embedding, ?::{array_type})"
    if metric == "cosine":
        return "array_cosine_distance(v.embedding, ?::{array_type})"
    # ip / inner_product / dot — rank by negative IP so ASC is nearest.
    return "array_negative_inner_product(v.embedding, ?::{array_type})"


# ---------------------------------------------------------------------------
# NumPy reference metrics (fixtures / parity)
# ---------------------------------------------------------------------------


def _as_numpy(values: Sequence[float], *, dtype: str):
    try:
        import numpy as np
    except ImportError as exc:  # pragma: no cover - test env gate
        raise VectorStoreContractError(
            "NUMPY_UNAVAILABLE",
            "numpy is required for reference distance helpers",
        ) from exc
    np_dtype = np.float32 if dtype == "float32" else np.float64
    arr = np.asarray(list(values), dtype=np_dtype)
    return np, arr


def numpy_l2_distance(
    a: Sequence[float],
    b: Sequence[float],
    *,
    dtype: str = "float32",
) -> float:
    np, aa = _as_numpy(a, dtype=dtype)
    _, bb = _as_numpy(b, dtype=dtype)
    if aa.shape != bb.shape:
        raise VectorStoreContractError(
            "DIMENSION_MISMATCH",
            f"vector shapes {aa.shape} != {bb.shape}",
        )
    return float(np.linalg.norm(aa - bb))


def numpy_cosine_distance(
    a: Sequence[float],
    b: Sequence[float],
    *,
    dtype: str = "float32",
) -> float:
    np, aa = _as_numpy(a, dtype=dtype)
    _, bb = _as_numpy(b, dtype=dtype)
    if aa.shape != bb.shape:
        raise VectorStoreContractError(
            "DIMENSION_MISMATCH",
            f"vector shapes {aa.shape} != {bb.shape}",
        )
    na = float(np.linalg.norm(aa))
    nb = float(np.linalg.norm(bb))
    if na == 0.0 or nb == 0.0:
        raise VectorStoreContractError(
            "INVALID_VECTOR",
            "cosine distance undefined for zero-norm vector",
        )
    sim = float(np.dot(aa, bb) / (na * nb))
    # Clamp float noise into [-1, 1] before converting to distance.
    if sim > 1.0:
        sim = 1.0
    elif sim < -1.0:
        sim = -1.0
    return float(1.0 - sim)


def numpy_inner_product(
    a: Sequence[float],
    b: Sequence[float],
    *,
    dtype: str = "float32",
) -> float:
    np, aa = _as_numpy(a, dtype=dtype)
    _, bb = _as_numpy(b, dtype=dtype)
    if aa.shape != bb.shape:
        raise VectorStoreContractError(
            "DIMENSION_MISMATCH",
            f"vector shapes {aa.shape} != {bb.shape}",
        )
    return float(np.dot(aa, bb))


# ---------------------------------------------------------------------------
# Records
# ---------------------------------------------------------------------------


# Public alias for documentation / type hints.
DistanceMetric = str


@dataclass(frozen=True)
class ExactVectorRow:
    """One authoritative FLOAT[N] row bound to a collection generation."""

    chunk_id: str
    collection_id: str
    document_id: str
    generation_id: int
    ordinal: int
    vector: tuple[float, ...]
    value_digest: str
    chunk_content_digest: str
    generation_content_digest: str
    dimension: int
    dtype: str
    status: str = "live"
    metadata: Mapping[str, Any] = field(default_factory=dict)
    created_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "chunk_id": self.chunk_id,
            "collection_id": self.collection_id,
            "document_id": self.document_id,
            "generation_id": self.generation_id,
            "ordinal": self.ordinal,
            "vector": list(self.vector),
            "value_digest": self.value_digest,
            "chunk_content_digest": self.chunk_content_digest,
            "generation_content_digest": self.generation_content_digest,
            "dimension": self.dimension,
            "dtype": self.dtype,
            "status": self.status,
            "metadata": dict(self.metadata),
            "created_at": self.created_at,
        }


@dataclass(frozen=True)
class ExactSearchHit:
    """Exact-search result bound to generation and content digests."""

    chunk_id: str
    collection_id: str
    document_id: str
    generation_id: int
    ordinal: int
    distance: float
    metric: str
    value_digest: str
    chunk_content_digest: str
    generation_content_digest: str
    rank: int
    metadata: Mapping[str, Any] = field(default_factory=dict)
    vector: Optional[tuple[float, ...]] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "chunk_id": self.chunk_id,
            "collection_id": self.collection_id,
            "document_id": self.document_id,
            "generation_id": self.generation_id,
            "ordinal": self.ordinal,
            "distance": self.distance,
            "metric": self.metric,
            "value_digest": self.value_digest,
            "chunk_content_digest": self.chunk_content_digest,
            "generation_content_digest": self.generation_content_digest,
            "rank": self.rank,
            "metadata": dict(self.metadata),
            "vector": list(self.vector) if self.vector is not None else None,
        }


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------


class DuckDBExactVectorStore:
    """Dimension-specific FLOAT[N] exact vector index over DuckDB.

    Importing this module does not open DuckDB.  Construction creates or opens
    a database and applies the exact-search core schema (registry + meta).
    Physical ``FLOAT[N]`` / ``DOUBLE[N]`` tables are created lazily per
    dimension.
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
                "duckdb is required for DuckDBExactVectorStore",
            ) from exc
        if self._path != ":memory:":
            parent = Path(self._path).expanduser().resolve().parent
            if not self._read_only:
                parent.mkdir(parents=True, exist_ok=True)
        connect_kwargs: dict[str, Any] = {}
        if self._read_only and self._path != ":memory:":
            connect_kwargs["read_only"] = True
        conn = duckdb.connect(self._path, **connect_kwargs)
        try:
            conn.execute("SET autoinstall_known_extensions=false")
            conn.execute("SET autoload_known_extensions=false")
        except Exception:
            pass
        return conn

    def _initialize_schema(self) -> None:
        with self._lock:
            self._conn.execute("BEGIN")
            try:
                self._conn.execute(_EXACT_CORE_SQL)
                row = self._conn.execute(
                    "SELECT value FROM vector_exact_meta WHERE key = 'schema_version'"
                ).fetchone()
                if row is None:
                    self._conn.execute(
                        "INSERT INTO vector_exact_meta (key, value) VALUES (?, ?), (?, ?)",
                        [
                            "schema_version",
                            str(EXACT_SCHEMA_VERSION),
                            "schema_id",
                            DUCKDB_EXACT_SCHEMA,
                        ],
                    )
                else:
                    applied = int(row[0])
                    if applied != EXACT_SCHEMA_VERSION:
                        raise VectorStoreContractError(
                            "SCHEMA_MISMATCH",
                            f"exact schema version {applied} != {EXACT_SCHEMA_VERSION}",
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
        return DUCKDB_EXACT_SCHEMA

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None

    def __enter__(self) -> "DuckDBExactVectorStore":
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

    def list_dimension_tables(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT table_name, dimension, dtype, sql_array_type, created_at
                FROM vector_exact_dimension_tables
                ORDER BY dtype, dimension
                """
            ).fetchall()
        return [
            {
                "table_name": r[0],
                "dimension": int(r[1]),
                "dtype": r[2],
                "sql_array_type": r[3],
                "created_at": r[4],
            }
            for r in rows
        ]

    def schema_digest(self) -> str:
        tables = self.list_dimension_tables()
        payload = {
            "schema_id": DUCKDB_EXACT_SCHEMA,
            "schema_version": EXACT_SCHEMA_VERSION,
            "dimension_tables": [
                {
                    "table_name": t["table_name"],
                    "dimension": t["dimension"],
                    "dtype": t["dtype"],
                    "sql_array_type": t["sql_array_type"],
                }
                for t in tables
            ],
        }
        return canonical_json_digest(payload)

    # -- physical tables -----------------------------------------------------

    def ensure_dimension_table(
        self,
        *,
        dimension: int,
        dtype: str = "float32",
    ) -> str:
        """Create the physical FLOAT[N]/DOUBLE[N] table for ``(dtype, dim)``."""

        dimension = _require_dimension(dimension)
        dtype = _require_dtype(dtype)
        table = physical_table_name(dimension, dtype)
        array_type = sql_array_type(dimension, dtype)
        created_at = _utc_now()
        # Table name is validated by physical_table_name / _TABLE_NAME_RE.
        ddl = f"""
        CREATE TABLE IF NOT EXISTS {table} (
            chunk_id VARCHAR PRIMARY KEY,
            collection_id VARCHAR NOT NULL,
            document_id VARCHAR NOT NULL,
            generation_id INTEGER NOT NULL,
            ordinal INTEGER NOT NULL,
            embedding {array_type} NOT NULL,
            value_digest VARCHAR NOT NULL,
            chunk_content_digest VARCHAR NOT NULL,
            generation_content_digest VARCHAR NOT NULL,
            status VARCHAR NOT NULL,
            metadata_json VARCHAR NOT NULL DEFAULT '{{}}',
            created_at VARCHAR NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_{table}_collection_gen
            ON {table} (collection_id, generation_id, status);
        CREATE INDEX IF NOT EXISTS idx_{table}_collection_live
            ON {table} (collection_id, status, chunk_id);
        """
        with self._transaction() as conn:
            existing = conn.execute(
                """
                SELECT table_name, dimension, dtype, sql_array_type
                FROM vector_exact_dimension_tables
                WHERE table_name = ?
                """,
                [table],
            ).fetchone()
            if existing is not None:
                if int(existing[1]) != dimension or existing[2] != dtype:
                    raise VectorStoreContractError(
                        "DIMENSION_TABLE_CONFLICT",
                        f"table {table!r} already registered with incompatible contract",
                        details={
                            "registered_dimension": int(existing[1]),
                            "registered_dtype": existing[2],
                            "requested_dimension": dimension,
                            "requested_dtype": dtype,
                        },
                    )
                return table
            # Mixed-dimension collision: same table name must not already exist
            # outside the registry (defensive).
            present = conn.execute(
                """
                SELECT 1 FROM information_schema.tables
                WHERE table_schema = 'main' AND table_name = ?
                """,
                [table],
            ).fetchone()
            conn.execute(ddl)
            if present is None:
                conn.execute(
                    """
                    INSERT INTO vector_exact_dimension_tables (
                        table_name, dimension, dtype, sql_array_type, created_at
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    [table, dimension, dtype, array_type, created_at],
                )
            else:
                # Table existed without registry row — still register if types match.
                conn.execute(
                    """
                    INSERT INTO vector_exact_dimension_tables (
                        table_name, dimension, dtype, sql_array_type, created_at
                    ) VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT (table_name) DO NOTHING
                    """,
                    [table, dimension, dtype, array_type, created_at],
                )
        return table

    def _resolve_table(self, dimension: int, dtype: str) -> str:
        dimension = _require_dimension(dimension)
        dtype = _require_dtype(dtype)
        table = physical_table_name(dimension, dtype)
        with self._lock:
            row = self._conn.execute(
                """
                SELECT table_name FROM vector_exact_dimension_tables
                WHERE table_name = ?
                """,
                [table],
            ).fetchone()
        if row is None:
            raise VectorStoreContractError(
                "DIMENSION_TABLE_MISSING",
                f"no physical exact table for dtype={dtype!r} dimension={dimension}",
                details={"table_name": table},
            )
        return table

    # -- writes --------------------------------------------------------------

    def upsert_vector(
        self,
        *,
        chunk_id: str,
        collection_id: str,
        document_id: str,
        generation_id: int,
        vector: Sequence[float],
        generation_content_digest: str,
        dimension: int,
        dtype: str = "float32",
        ordinal: int = 0,
        chunk_content_digest: Optional[str] = None,
        metadata: Optional[Mapping[str, Any]] = None,
        status: str = "live",
    ) -> ExactVectorRow:
        """Insert or replace one vector in the dimension-specific physical table.

        Rejects vectors whose length does not match ``dimension`` (mixed
        dimensions cannot enter one physical table).
        """

        chunk_id = _require_id(chunk_id, field="chunk_id")
        collection_id = _require_id(collection_id, field="collection_id")
        document_id = _require_id(document_id, field="document_id")
        dimension = _require_dimension(dimension)
        dtype = _require_dtype(dtype)
        if not isinstance(generation_id, int) or isinstance(generation_id, bool):
            raise VectorStoreContractError(
                "INVALID_GENERATION",
                "generation_id must be an integer",
            )
        if generation_id < 1:
            raise VectorStoreContractError(
                "INVALID_GENERATION",
                "generation_id must be >= 1",
            )
        if not isinstance(ordinal, int) or isinstance(ordinal, bool) or ordinal < 0:
            raise VectorStoreContractError(
                "INVALID_ORDINAL",
                "ordinal must be a non-negative integer",
            )
        status = _require_id(status, field="status")
        if status not in ("live", "tombstoned"):
            raise VectorStoreContractError(
                "INVALID_STATUS",
                "status must be 'live' or 'tombstoned'",
            )
        gen_digest = _require_digest(
            generation_content_digest, field="generation_content_digest"
        )
        if not isinstance(vector, Sequence) or isinstance(vector, (str, bytes, bytearray)):
            raise VectorStoreContractError(
                "INVALID_VECTOR",
                "vector must be a sequence of floats",
            )
        if len(vector) != dimension:
            raise VectorStoreContractError(
                "DIMENSION_MISMATCH",
                f"vector length {len(vector)} cannot enter physical table for dimension {dimension}",
                details={
                    "vector_length": len(vector),
                    "table_dimension": dimension,
                    "table_name": physical_table_name(dimension, dtype),
                },
            )
        normalized = _normalize_vector(vector, dimension=dimension, dtype=dtype)
        value_digest = vector_content_digest(
            normalized, dimension=dimension, dtype=dtype
        )
        if chunk_content_digest is None:
            chunk_digest = canonical_json_digest(
                {
                    "chunk_id": chunk_id,
                    "document_id": document_id,
                    "ordinal": ordinal,
                    "value_digest": value_digest,
                }
            )
        else:
            chunk_digest = _require_digest(
                chunk_content_digest, field="chunk_content_digest"
            )
        meta_json = _metadata_json(metadata)
        created_at = _utc_now()
        table = self.ensure_dimension_table(dimension=dimension, dtype=dtype)
        array_type = sql_array_type(dimension, dtype)
        with self._transaction() as conn:
            conn.execute(
                f"""
                INSERT OR REPLACE INTO {table} (
                    chunk_id, collection_id, document_id, generation_id, ordinal,
                    embedding, value_digest, chunk_content_digest,
                    generation_content_digest, status, metadata_json, created_at
                ) VALUES (
                    ?, ?, ?, ?, ?,
                    ?::{array_type}, ?, ?,
                    ?, ?, ?, ?
                )
                """,
                [
                    chunk_id,
                    collection_id,
                    document_id,
                    generation_id,
                    ordinal,
                    normalized,
                    value_digest,
                    chunk_digest,
                    gen_digest,
                    status,
                    meta_json,
                    created_at,
                ],
            )
        return ExactVectorRow(
            chunk_id=chunk_id,
            collection_id=collection_id,
            document_id=document_id,
            generation_id=generation_id,
            ordinal=ordinal,
            vector=tuple(normalized),
            value_digest=value_digest,
            chunk_content_digest=chunk_digest,
            generation_content_digest=gen_digest,
            dimension=dimension,
            dtype=dtype,
            status=status,
            metadata=_parse_metadata(meta_json),
            created_at=created_at,
        )

    def upsert_many(
        self,
        rows: Sequence[Mapping[str, Any]],
        *,
        dimension: int,
        dtype: str = "float32",
        collection_id: Optional[str] = None,
        generation_id: Optional[int] = None,
        generation_content_digest: Optional[str] = None,
    ) -> list[ExactVectorRow]:
        """Batch upsert with a shared dimension contract.

        Every row must share the same physical table dimension; mixed lengths
        raise ``DIMENSION_MISMATCH`` before any write commits when called
        through individual upserts inside one transaction path.
        """

        dimension = _require_dimension(dimension)
        dtype = _require_dtype(dtype)
        results: list[ExactVectorRow] = []
        # Single transaction for atomic batch.
        table = self.ensure_dimension_table(dimension=dimension, dtype=dtype)
        array_type = sql_array_type(dimension, dtype)
        created_at = _utc_now()
        prepared: list[tuple[Any, ...]] = []
        built: list[ExactVectorRow] = []
        for index, raw in enumerate(rows):
            if not isinstance(raw, Mapping):
                raise VectorStoreContractError(
                    "INVALID_ROW",
                    f"rows[{index}] must be a mapping",
                )
            chunk_id = _require_id(raw.get("chunk_id"), field="chunk_id")
            col_id = _require_id(
                raw.get("collection_id", collection_id), field="collection_id"
            )
            doc_id = _require_id(raw.get("document_id"), field="document_id")
            gen_id = raw.get("generation_id", generation_id)
            if not isinstance(gen_id, int) or isinstance(gen_id, bool) or gen_id < 1:
                raise VectorStoreContractError(
                    "INVALID_GENERATION",
                    f"rows[{index}].generation_id must be an integer >= 1",
                )
            ordinal = raw.get("ordinal", 0)
            if not isinstance(ordinal, int) or isinstance(ordinal, bool) or ordinal < 0:
                raise VectorStoreContractError(
                    "INVALID_ORDINAL",
                    f"rows[{index}].ordinal must be a non-negative integer",
                )
            vector = raw.get("vector")
            if not isinstance(vector, Sequence) or isinstance(
                vector, (str, bytes, bytearray)
            ):
                raise VectorStoreContractError(
                    "INVALID_VECTOR",
                    f"rows[{index}].vector must be a sequence of floats",
                )
            if len(vector) != dimension:
                raise VectorStoreContractError(
                    "DIMENSION_MISMATCH",
                    f"rows[{index}] length {len(vector)} cannot enter dimension {dimension} table",
                    details={
                        "index": index,
                        "vector_length": len(vector),
                        "table_dimension": dimension,
                        "table_name": table,
                    },
                )
            status = str(raw.get("status", "live"))
            if status not in ("live", "tombstoned"):
                raise VectorStoreContractError(
                    "INVALID_STATUS",
                    f"rows[{index}].status must be 'live' or 'tombstoned'",
                )
            gen_digest = _require_digest(
                raw.get("generation_content_digest", generation_content_digest),
                field="generation_content_digest",
            )
            normalized = _normalize_vector(vector, dimension=dimension, dtype=dtype)
            value_digest = vector_content_digest(
                normalized, dimension=dimension, dtype=dtype
            )
            if raw.get("chunk_content_digest") is not None:
                chunk_digest = _require_digest(
                    raw["chunk_content_digest"], field="chunk_content_digest"
                )
            else:
                chunk_digest = canonical_json_digest(
                    {
                        "chunk_id": chunk_id,
                        "document_id": doc_id,
                        "ordinal": ordinal,
                        "value_digest": value_digest,
                    }
                )
            meta_json = _metadata_json(raw.get("metadata"))
            prepared.append(
                (
                    chunk_id,
                    col_id,
                    doc_id,
                    gen_id,
                    ordinal,
                    normalized,
                    value_digest,
                    chunk_digest,
                    gen_digest,
                    status,
                    meta_json,
                    created_at,
                )
            )
            built.append(
                ExactVectorRow(
                    chunk_id=chunk_id,
                    collection_id=col_id,
                    document_id=doc_id,
                    generation_id=gen_id,
                    ordinal=ordinal,
                    vector=tuple(normalized),
                    value_digest=value_digest,
                    chunk_content_digest=chunk_digest,
                    generation_content_digest=gen_digest,
                    dimension=dimension,
                    dtype=dtype,
                    status=status,
                    metadata=_parse_metadata(meta_json),
                    created_at=created_at,
                )
            )
        with self._transaction() as conn:
            for params in prepared:
                conn.execute(
                    f"""
                    INSERT OR REPLACE INTO {table} (
                        chunk_id, collection_id, document_id, generation_id, ordinal,
                        embedding, value_digest, chunk_content_digest,
                        generation_content_digest, status, metadata_json, created_at
                    ) VALUES (
                        ?, ?, ?, ?, ?,
                        ?::{array_type}, ?, ?,
                        ?, ?, ?, ?
                    )
                    """,
                    list(params),
                )
        results.extend(built)
        return results

    def tombstone_chunk(
        self,
        *,
        chunk_id: str,
        dimension: int,
        dtype: str = "float32",
    ) -> None:
        chunk_id = _require_id(chunk_id, field="chunk_id")
        table = self._resolve_table(dimension, dtype)
        with self._transaction() as conn:
            conn.execute(
                f"UPDATE {table} SET status = 'tombstoned' WHERE chunk_id = ?",
                [chunk_id],
            )

    def delete_chunk(
        self,
        *,
        chunk_id: str,
        dimension: int,
        dtype: str = "float32",
    ) -> None:
        chunk_id = _require_id(chunk_id, field="chunk_id")
        table = self._resolve_table(dimension, dtype)
        with self._transaction() as conn:
            conn.execute(f"DELETE FROM {table} WHERE chunk_id = ?", [chunk_id])

    # -- lifecycle materialization -------------------------------------------

    def materialize_from_lifecycle(
        self,
        lifecycle: DuckDBVectorStore,
        *,
        collection_id: str,
    ) -> list[ExactVectorRow]:
        """Project query-visible lifecycle vectors into the FLOAT[N] table.

        Binds each row to the collection's published generation and its
        generation content digest.  Only live, published, non-tombstoned chunks
        are materialised.
        """

        collection = lifecycle.get_collection(collection_id)
        if collection.published_generation is None:
            return []
        gen = lifecycle.get_generation(
            collection.collection_id, collection.published_generation
        )
        dimension = collection.dimension
        dtype = collection.dtype
        self.ensure_dimension_table(dimension=dimension, dtype=dtype)
        table = physical_table_name(dimension, dtype)
        array_type = sql_array_type(dimension, dtype)

        visible = lifecycle.list_query_visible_chunks(collection.collection_id)
        rows_out: list[ExactVectorRow] = []
        created_at = _utc_now()

        with self._transaction() as conn:
            # Drop prior materialisation for this collection+generation so the
            # exact table mirrors the published generation atomically.
            conn.execute(
                f"""
                DELETE FROM {table}
                WHERE collection_id = ?
                """,
                [collection.collection_id],
            )
            for chunk in visible:
                value = lifecycle.get_query_visible_vector(
                    collection.collection_id, chunk.chunk_id
                )
                if value is None:
                    raise VectorStoreContractError(
                        "VECTOR_NOT_FOUND",
                        f"query-visible chunk {chunk.chunk_id!r} missing vector bytes",
                    )
                if value.dimension != dimension or value.dtype != dtype:
                    raise VectorStoreContractError(
                        "DIMENSION_MISMATCH",
                        "lifecycle vector contract does not match collection",
                        details={
                            "chunk_id": chunk.chunk_id,
                            "value_dimension": value.dimension,
                            "collection_dimension": dimension,
                        },
                    )
                normalized = list(value.vector)
                if len(normalized) != dimension:
                    raise VectorStoreContractError(
                        "DIMENSION_MISMATCH",
                        f"vector length {len(normalized)} != collection dimension {dimension}",
                    )
                # Re-verify digest against authoritative bytes.
                expected = vector_content_digest(
                    normalized, dimension=dimension, dtype=dtype
                )
                if expected != value.value_digest:
                    raise VectorStoreContractError(
                        "DIGEST_MISMATCH",
                        f"value_digest drift for chunk {chunk.chunk_id!r}",
                        details={
                            "expected": expected,
                            "stored": value.value_digest,
                        },
                    )
                conn.execute(
                    f"""
                    INSERT INTO {table} (
                        chunk_id, collection_id, document_id, generation_id, ordinal,
                        embedding, value_digest, chunk_content_digest,
                        generation_content_digest, status, metadata_json, created_at
                    ) VALUES (
                        ?, ?, ?, ?, ?,
                        ?::{array_type}, ?, ?,
                        ?, 'live', ?, ?
                    )
                    """,
                    [
                        chunk.chunk_id,
                        collection.collection_id,
                        chunk.document_id,
                        chunk.generation_id,
                        chunk.ordinal,
                        normalized,
                        value.value_digest,
                        chunk.content_digest,
                        gen.content_digest,
                        _metadata_json(dict(chunk.metadata)),
                        created_at,
                    ],
                )
                rows_out.append(
                    ExactVectorRow(
                        chunk_id=chunk.chunk_id,
                        collection_id=collection.collection_id,
                        document_id=chunk.document_id,
                        generation_id=chunk.generation_id,
                        ordinal=chunk.ordinal,
                        vector=tuple(normalized),
                        value_digest=value.value_digest,
                        chunk_content_digest=chunk.content_digest,
                        generation_content_digest=gen.content_digest,
                        dimension=dimension,
                        dtype=dtype,
                        status="live",
                        metadata=dict(chunk.metadata),
                        created_at=created_at,
                    )
                )
        return rows_out

    # -- reads / search ------------------------------------------------------

    def get_vector(
        self,
        chunk_id: str,
        *,
        dimension: int,
        dtype: str = "float32",
    ) -> Optional[ExactVectorRow]:
        chunk_id = _require_id(chunk_id, field="chunk_id")
        table = self._resolve_table(dimension, dtype)
        with self._lock:
            row = self._conn.execute(
                f"""
                SELECT chunk_id, collection_id, document_id, generation_id, ordinal,
                       embedding, value_digest, chunk_content_digest,
                       generation_content_digest, status, metadata_json, created_at
                FROM {table}
                WHERE chunk_id = ?
                """,
                [chunk_id],
            ).fetchone()
        if row is None:
            return None
        emb = row[5]
        vector = tuple(float(x) for x in emb)
        return ExactVectorRow(
            chunk_id=row[0],
            collection_id=row[1],
            document_id=row[2],
            generation_id=int(row[3]),
            ordinal=int(row[4]),
            vector=vector,
            value_digest=row[6],
            chunk_content_digest=row[7],
            generation_content_digest=row[8],
            dimension=dimension,
            dtype=dtype,
            status=row[9],
            metadata=_parse_metadata(row[10]),
            created_at=row[11],
        )

    def count_live(
        self,
        *,
        collection_id: str,
        dimension: int,
        dtype: str = "float32",
        generation_id: Optional[int] = None,
    ) -> int:
        collection_id = _require_id(collection_id, field="collection_id")
        table = self._resolve_table(dimension, dtype)
        sql = f"""
            SELECT COUNT(*) FROM {table}
            WHERE collection_id = ? AND status = 'live'
        """
        params: list[Any] = [collection_id]
        if generation_id is not None:
            sql += " AND generation_id = ?"
            params.append(generation_id)
        with self._lock:
            row = self._conn.execute(sql, params).fetchone()
        return int(row[0]) if row else 0

    def search(
        self,
        *,
        collection_id: str,
        query: Sequence[float],
        dimension: int,
        dtype: str = "float32",
        metric: str = "l2",
        top_k: int = 10,
        generation_id: Optional[int] = None,
        generation_content_digest: Optional[str] = None,
        metadata_filter: Optional[Mapping[str, Any]] = None,
        include_vector: bool = False,
    ) -> list[ExactSearchHit]:
        """Exact k-NN over the dimension-specific physical table.

        Ranking is ascending distance (L2, cosine distance, or negative inner
        product).  Ties break deterministically by ``chunk_id``, then
        ``document_id``, then ``ordinal``.

        When ``generation_id`` / ``generation_content_digest`` are supplied,
        only rows bound to that generation identity are considered.
        """

        collection_id = _require_id(collection_id, field="collection_id")
        dimension = _require_dimension(dimension)
        dtype = _require_dtype(dtype)
        metric = _require_metric(metric)
        if not isinstance(top_k, int) or isinstance(top_k, bool) or top_k < 1:
            raise VectorStoreContractError(
                "INVALID_TOP_K",
                "top_k must be a positive integer",
            )
        if not isinstance(query, Sequence) or isinstance(query, (str, bytes, bytearray)):
            raise VectorStoreContractError(
                "INVALID_VECTOR",
                "query must be a sequence of floats",
            )
        if len(query) != dimension:
            raise VectorStoreContractError(
                "DIMENSION_MISMATCH",
                f"query length {len(query)} != table dimension {dimension}",
                details={
                    "query_length": len(query),
                    "table_dimension": dimension,
                },
            )
        normalized_query = _normalize_vector(query, dimension=dimension, dtype=dtype)
        table = self._resolve_table(dimension, dtype)
        array_type = sql_array_type(dimension, dtype)
        dist_expr = _distance_sql_expr(metric).format(array_type=array_type)

        where = ["v.collection_id = ?", "v.status = 'live'"]
        params: list[Any] = [normalized_query, collection_id]

        if generation_id is not None:
            if not isinstance(generation_id, int) or isinstance(generation_id, bool):
                raise VectorStoreContractError(
                    "INVALID_GENERATION",
                    "generation_id must be an integer",
                )
            where.append("v.generation_id = ?")
            params.append(generation_id)
        if generation_content_digest is not None:
            gen_digest = _require_digest(
                generation_content_digest, field="generation_content_digest"
            )
            where.append("v.generation_content_digest = ?")
            params.append(gen_digest)

        if metadata_filter is not None:
            if not isinstance(metadata_filter, Mapping):
                raise VectorStoreContractError(
                    "INVALID_METADATA",
                    "metadata_filter must be a mapping",
                )
            for key, value in metadata_filter.items():
                if not isinstance(key, str) or not key or not re.fullmatch(
                    r"[A-Za-z_][A-Za-z0-9_]*", key
                ):
                    raise VectorStoreContractError(
                        "INVALID_METADATA",
                        f"metadata filter key {key!r} is not a safe identifier",
                    )
                path = f"$.{key}"
                where.append("json_extract(v.metadata_json, ?) = ?")
                params.append(path)
                params.append(json.dumps(value))

        vector_select = ", v.embedding" if include_vector else ""
        sql = f"""
            SELECT
                v.chunk_id,
                v.collection_id,
                v.document_id,
                v.generation_id,
                v.ordinal,
                {dist_expr} AS distance,
                v.value_digest,
                v.chunk_content_digest,
                v.generation_content_digest,
                v.metadata_json
                {vector_select}
            FROM {table} AS v
            WHERE {' AND '.join(where)}
            ORDER BY distance ASC, v.chunk_id ASC, v.document_id ASC, v.ordinal ASC
            LIMIT ?
        """
        params.append(top_k)

        with self._lock:
            raw_rows = self._conn.execute(sql, params).fetchall()

        hits: list[ExactSearchHit] = []
        for rank, row in enumerate(raw_rows, start=1):
            vector: Optional[tuple[float, ...]] = None
            if include_vector:
                emb = row[10]
                vector = tuple(float(x) for x in emb)
            hits.append(
                ExactSearchHit(
                    chunk_id=row[0],
                    collection_id=row[1],
                    document_id=row[2],
                    generation_id=int(row[3]),
                    ordinal=int(row[4]),
                    distance=float(row[5]),
                    metric=metric,
                    value_digest=row[6],
                    chunk_content_digest=row[7],
                    generation_content_digest=row[8],
                    rank=rank,
                    metadata=_parse_metadata(row[9]),
                    vector=vector,
                )
            )
        return hits

    def distances_for_collection(
        self,
        *,
        collection_id: str,
        query: Sequence[float],
        dimension: int,
        dtype: str = "float32",
        metric: str = "l2",
        generation_id: Optional[int] = None,
    ) -> dict[str, float]:
        """Return ``{chunk_id: distance}`` for all live rows (test / parity aid)."""

        hits = self.search(
            collection_id=collection_id,
            query=query,
            dimension=dimension,
            dtype=dtype,
            metric=metric,
            top_k=10**9,
            generation_id=generation_id,
        )
        return {h.chunk_id: h.distance for h in hits}
