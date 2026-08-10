"""Exact SQL FLOAT[N] vector search on dimension-specific tables (DQK-021).

Authoritative vectors live in one physical table per dimension as DuckDB
``FLOAT[N]`` fixed-size arrays. Exact distance/ranking/filter queries run in
SQL (``array_distance`` / ``array_cosine_distance``) and bind every hit to the
collection's active ``generation_id`` and the vector's ``content_digest``.

Mixed dimensions cannot share a physical table: the ``FLOAT[N]`` column type
rejects wrong-length embeddings at the engine, and application checks fail
closed before write. VSS/HNSW is deliberately not used here — exact search is
the identity authority; approximate indexes are a later derived layer.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import struct
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, Mapping, Optional, Sequence, Union

__all__ = [
    "DUCKDB_EXACT_SCHEMA",
    "SCHEMA_VERSION",
    "SUPPORTED_METRICS",
    "ExactHit",
    "ExactVectorStore",
    "ExactVectorStoreError",
    "decode_vector",
    "distance",
    "encode_vector",
    "physical_table_name",
    "vector_digest",
]


DUCKDB_EXACT_SCHEMA: Final[str] = "ipfs_datasets_py/vector-stores-duckdb-exact@1"
SCHEMA_VERSION: Final[int] = 1
SUPPORTED_METRICS: Final[frozenset[str]] = frozenset({"l2", "cosine"})

# Align with safe identity tokens used across duckdb vector modules.
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@+/-]{0,191}$")
_META_KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
_MAX_DIMENSION: Final[int] = 65536


class ExactVectorStoreError(ValueError):
    """Fail-closed rejection of an exact-vector contract or mutation."""

    def __init__(
        self,
        code: str,
        message: str,
        **details: Any,
    ) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.details = details


def _require_duckdb() -> Any:
    try:
        import duckdb  # type: ignore
    except ImportError as exc:  # pragma: no cover
        raise ExactVectorStoreError(
            "DUCKDB_REQUIRED",
            "duckdb package is required for ExactVectorStore",
        ) from exc
    return duckdb


def _require_dimension(dimension: Any) -> int:
    if isinstance(dimension, bool) or not isinstance(dimension, int):
        raise ExactVectorStoreError(
            "DIM",
            "dimension must be a positive int",
            got=repr(dimension),
        )
    if dimension < 1 or dimension > _MAX_DIMENSION:
        raise ExactVectorStoreError(
            "DIM",
            f"dimension must be in 1..{_MAX_DIMENSION}",
            got=dimension,
        )
    return dimension


def _require_id(value: str, *, field: str) -> str:
    if not isinstance(value, str) or _SAFE_ID.fullmatch(value) is None:
        raise ExactVectorStoreError("ID", f"invalid {field}", value=value)
    return value


def _require_finite_floats(values: Sequence[float], *, dimension: int) -> list[float]:
    if len(values) != dimension:
        raise ExactVectorStoreError(
            "DIM",
            "mixed dimensions cannot enter one physical table",
            expected=dimension,
            got=len(values),
        )
    out: list[float] = []
    for index, raw in enumerate(values):
        try:
            number = float(raw)
        except (TypeError, ValueError) as exc:
            raise ExactVectorStoreError(
                "INVALID_VECTOR",
                f"vector[{index}] is not a float",
            ) from exc
        if number != number or number in (float("inf"), float("-inf")):
            raise ExactVectorStoreError(
                "INVALID_VECTOR",
                f"vector[{index}] is non-finite",
            )
        out.append(number)
    return out


def physical_table_name(dimension: int) -> str:
    """Return the dimension-specific physical table identifier."""
    dim = _require_dimension(dimension)
    return f"exact_vectors_d{dim}"


def encode_vector(values: Sequence[float]) -> bytes:
    """Pack values as little-endian float32 bytes (content-digest authority)."""
    if not values:
        raise ExactVectorStoreError("DIM", "vector must be non-empty")
    floats = _require_finite_floats(values, dimension=len(values))
    # Round-trip through binary32 so digest matches stored FLOAT[N] authority.
    packed = struct.pack(f"<{len(floats)}f", *floats)
    return packed


def decode_vector(data: bytes, dimension: int) -> list[float]:
    """Unpack little-endian float32 bytes into a Python list."""
    dim = _require_dimension(dimension)
    expected = dim * 4
    if not isinstance(data, (bytes, bytearray)):
        raise ExactVectorStoreError("SIZE", "vector bytes required")
    if len(data) != expected:
        raise ExactVectorStoreError(
            "SIZE",
            f"vector bytes length {len(data)} != {expected}",
            expected=expected,
            got=len(data),
        )
    return list(struct.unpack(f"<{dim}f", bytes(data)))


def vector_digest(values: Sequence[float]) -> str:
    """Content digest of the float32 encoding of ``values``."""
    return "sha256:" + hashlib.sha256(encode_vector(values)).hexdigest()


def distance(
    left: Sequence[float],
    right: Sequence[float],
    *,
    metric: str = "l2",
) -> float:
    """Reference exact distance used to cross-check SQL results.

    Metrics:

    * ``l2`` — Euclidean distance
    * ``cosine`` — cosine distance ``1 - cos`` (range ``[0, 2]``); zero-norm
      vectors return ``2.0`` to match DuckDB ``array_cosine_distance``
    """
    if len(left) != len(right):
        raise ExactVectorStoreError("DIM", "vector dimensions differ")
    if metric not in SUPPORTED_METRICS:
        raise ExactVectorStoreError("METRIC", f"unsupported metric {metric!r}")
    a = [float(x) for x in left]
    b = [float(x) for x in right]
    if metric == "l2":
        return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))
    # cosine
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 2.0
    cos = max(-1.0, min(1.0, dot / (na * nb)))
    return 1.0 - cos


def _canonical_metadata_json(metadata: Optional[Mapping[str, Any]]) -> str:
    if metadata is None:
        return "{}"
    if not isinstance(metadata, Mapping):
        raise ExactVectorStoreError("INVALID_METADATA", "metadata must be a mapping")
    try:
        return json.dumps(dict(metadata), sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError) as exc:
        raise ExactVectorStoreError(
            "INVALID_METADATA",
            f"metadata is not JSON-serializable: {exc}",
        ) from exc


def _parse_metadata(text: Any) -> dict[str, Any]:
    if text is None or text == "":
        return {}
    if not isinstance(text, str):
        text = str(text)
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ExactVectorStoreError(
            "CORRUPT_METADATA",
            f"metadata_json is not valid JSON: {exc}",
        ) from exc
    if not isinstance(payload, dict):
        raise ExactVectorStoreError(
            "CORRUPT_METADATA",
            "metadata_json must be a JSON object",
        )
    return payload


@dataclass(frozen=True)
class ExactHit:
    """One exact nearest-neighbor hit bound to generation and content digest."""

    vector_id: str
    collection_id: str
    generation_id: int
    content_digest: str
    distance: float
    metadata: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "vector_id": self.vector_id,
            "collection_id": self.collection_id,
            "generation_id": self.generation_id,
            "content_digest": self.content_digest,
            "distance": self.distance,
            "metadata": dict(self.metadata),
        }


class ExactVectorStore:
    """Dimension-partitioned exact FLOAT[N] vector store backed by DuckDB.

    Each embedding dimension owns a dedicated physical table
    ``exact_vectors_d{N}`` with column ``embedding FLOAT[N]``. Collections
    record their dimension and active generation; search always filters to the
    collection's current generation and returns the stored content digest.
    """

    def __init__(
        self,
        path: Union[str, Path] = ":memory:",
        *,
        read_only: bool = False,
    ) -> None:
        duckdb = _require_duckdb()
        if path in (None, ":memory:"):
            self._path_str = ":memory:"
            self._path: Optional[Path] = None
        else:
            self._path = Path(path)
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path_str = str(self._path)
        self._read_only = bool(read_only)
        self._lock = threading.RLock()
        self._closed = False
        if self._read_only and self._path_str == ":memory:":
            raise ExactVectorStoreError(
                "CONFIG",
                "read_only is not supported for :memory: stores",
            )
        if self._read_only:
            self._conn = duckdb.connect(self._path_str, read_only=True)
        else:
            self._conn = duckdb.connect(self._path_str)
            self._initialize_schema()

    # -- lifecycle -----------------------------------------------------------

    def close(self) -> None:
        with self._lock:
            if not self._closed:
                self._conn.close()
                self._closed = True

    def __enter__(self) -> "ExactVectorStore":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    @property
    def path(self) -> str:
        return self._path_str

    @property
    def schema_name(self) -> str:
        return DUCKDB_EXACT_SCHEMA

    def _initialize_schema(self) -> None:
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS exact_meta (
                key VARCHAR PRIMARY KEY,
                value VARCHAR NOT NULL
            )
            """
        )
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS exact_collections (
                collection_id VARCHAR PRIMARY KEY,
                dimension INTEGER NOT NULL,
                generation_id INTEGER NOT NULL,
                created_at TIMESTAMP DEFAULT current_timestamp
            )
            """
        )
        # Catalog of physical tables that have been provisioned.
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS exact_dimension_tables (
                dimension INTEGER PRIMARY KEY,
                table_name VARCHAR NOT NULL UNIQUE,
                created_at TIMESTAMP DEFAULT current_timestamp
            )
            """
        )
        row = self._conn.execute(
            "SELECT value FROM exact_meta WHERE key = 'schema'"
        ).fetchone()
        if row is None:
            self._conn.execute(
                "INSERT INTO exact_meta (key, value) VALUES ('schema', ?), "
                "('schema_version', ?)",
                [DUCKDB_EXACT_SCHEMA, str(SCHEMA_VERSION)],
            )
        elif row[0] != DUCKDB_EXACT_SCHEMA:
            raise ExactVectorStoreError(
                "SCHEMA",
                "exact store schema identity mismatch",
                expected=DUCKDB_EXACT_SCHEMA,
                got=row[0],
            )

    def _ensure_open(self) -> None:
        if self._closed:
            raise ExactVectorStoreError("CLOSED", "ExactVectorStore is closed")

    # -- physical tables -----------------------------------------------------

    def _table(self, dimension: int) -> str:
        return physical_table_name(dimension)

    def _ensure_table(self, dimension: int) -> str:
        dim = _require_dimension(dimension)
        table = self._table(dim)
        # FLOAT[N] is the authoritative physical type: wrong-length vectors
        # cannot be inserted into this table at the engine level.
        self._conn.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {table} (
                vector_id VARCHAR PRIMARY KEY,
                collection_id VARCHAR NOT NULL,
                generation_id INTEGER NOT NULL,
                content_digest VARCHAR NOT NULL,
                embedding FLOAT[{dim}] NOT NULL,
                metadata_json VARCHAR NOT NULL DEFAULT '{{}}'
            )
            """
        )
        self._conn.execute(
            f"""
            CREATE INDEX IF NOT EXISTS idx_{table}_collection_gen
            ON {table} (collection_id, generation_id)
            """
        )
        self._conn.execute(
            """
            INSERT INTO exact_dimension_tables (dimension, table_name)
            SELECT ?, ?
            WHERE NOT EXISTS (
                SELECT 1 FROM exact_dimension_tables WHERE dimension = ?
            )
            """,
            [dim, table, dim],
        )
        return table

    def physical_tables(self) -> dict[int, str]:
        """Map dimension → physical table name for provisioned tables."""
        with self._lock:
            self._ensure_open()
            rows = self._conn.execute(
                "SELECT dimension, table_name FROM exact_dimension_tables "
                "ORDER BY dimension"
            ).fetchall()
            return {int(r[0]): str(r[1]) for r in rows}

    def physical_table_name(self, dimension: int) -> str:
        """Return the physical table name for a dimension (introspection)."""
        return physical_table_name(dimension)

    # -- collections ---------------------------------------------------------

    def create_collection(
        self,
        collection_id: str,
        *,
        dimension: int,
        generation_id: int = 1,
    ) -> None:
        """Create or validate a collection bound to a single dimension."""
        cid = _require_id(collection_id, field="collection_id")
        dim = _require_dimension(dimension)
        if isinstance(generation_id, bool) or not isinstance(generation_id, int):
            raise ExactVectorStoreError(
                "GENERATION",
                "generation_id must be a positive int",
            )
        if generation_id < 1:
            raise ExactVectorStoreError(
                "GENERATION",
                "generation_id must be >= 1",
                got=generation_id,
            )
        with self._lock:
            self._ensure_open()
            if self._read_only:
                raise ExactVectorStoreError("READ_ONLY", "store is read-only")
            self._ensure_table(dim)
            existing = self._conn.execute(
                "SELECT dimension, generation_id FROM exact_collections "
                "WHERE collection_id = ?",
                [cid],
            ).fetchone()
            if existing is not None:
                if int(existing[0]) != dim:
                    raise ExactVectorStoreError(
                        "DIM",
                        "collection dimension mismatch",
                        collection_id=cid,
                        expected=int(existing[0]),
                        got=dim,
                    )
                return
            self._conn.execute(
                "INSERT INTO exact_collections "
                "(collection_id, dimension, generation_id) VALUES (?, ?, ?)",
                [cid, dim, int(generation_id)],
            )

    def set_generation(self, collection_id: str, generation_id: int) -> None:
        """Advance the active generation used for search visibility."""
        cid = _require_id(collection_id, field="collection_id")
        if isinstance(generation_id, bool) or not isinstance(generation_id, int):
            raise ExactVectorStoreError(
                "GENERATION",
                "generation_id must be a positive int",
            )
        if generation_id < 1:
            raise ExactVectorStoreError(
                "GENERATION",
                "generation_id must be >= 1",
                got=generation_id,
            )
        with self._lock:
            self._ensure_open()
            if self._read_only:
                raise ExactVectorStoreError("READ_ONLY", "store is read-only")
            updated = self._conn.execute(
                "UPDATE exact_collections SET generation_id = ? "
                "WHERE collection_id = ? RETURNING collection_id",
                [int(generation_id), cid],
            ).fetchone()
            if updated is None:
                raise ExactVectorStoreError(
                    "NOT_FOUND",
                    f"unknown collection {cid!r}",
                )

    def get_collection(self, collection_id: str) -> dict[str, Any]:
        cid = _require_id(collection_id, field="collection_id")
        with self._lock:
            self._ensure_open()
            row = self._conn.execute(
                "SELECT collection_id, dimension, generation_id "
                "FROM exact_collections WHERE collection_id = ?",
                [cid],
            ).fetchone()
            if row is None:
                raise ExactVectorStoreError(
                    "NOT_FOUND",
                    f"unknown collection {cid!r}",
                )
            return {
                "collection_id": row[0],
                "dimension": int(row[1]),
                "generation_id": int(row[2]),
                "physical_table": self._table(int(row[1])),
            }

    def _collection_dim(self, collection_id: str) -> tuple[int, int]:
        row = self._conn.execute(
            "SELECT dimension, generation_id FROM exact_collections "
            "WHERE collection_id = ?",
            [collection_id],
        ).fetchone()
        if row is None:
            raise ExactVectorStoreError(
                "NOT_FOUND",
                f"unknown collection {collection_id!r}",
            )
        return int(row[0]), int(row[1])

    # -- mutations -----------------------------------------------------------

    def upsert_vector(
        self,
        collection_id: str,
        vector_id: str,
        values: Sequence[float],
        *,
        metadata: Optional[Mapping[str, Any]] = None,
        generation_id: Optional[int] = None,
    ) -> str:
        """Insert or replace a vector in the collection's physical table.

        Returns the content digest (``sha256:<hex>``) of the float32 encoding.
        Vectors are always written as ``FLOAT[N]`` for the collection
        dimension; wrong lengths are rejected before and by the engine.
        """
        cid = _require_id(collection_id, field="collection_id")
        vid = _require_id(vector_id, field="vector_id")
        with self._lock:
            self._ensure_open()
            if self._read_only:
                raise ExactVectorStoreError("READ_ONLY", "store is read-only")
            dim, active_gen = self._collection_dim(cid)
            floats = _require_finite_floats(values, dimension=dim)
            # Re-encode through float32 so stored values match the digest.
            floats = decode_vector(encode_vector(floats), dim)
            gen = active_gen if generation_id is None else int(generation_id)
            if gen < 1:
                raise ExactVectorStoreError(
                    "GENERATION",
                    "generation_id must be >= 1",
                    got=gen,
                )
            table = self._ensure_table(dim)
            digest = vector_digest(floats)
            meta = _canonical_metadata_json(metadata)
            # DELETE + INSERT keeps PRIMARY KEY semantics without upsert quirks.
            self._conn.execute(
                f"DELETE FROM {table} WHERE vector_id = ?",
                [vid],
            )
            try:
                self._conn.execute(
                    f"""
                    INSERT INTO {table} (
                        vector_id, collection_id, generation_id,
                        content_digest, embedding, metadata_json
                    ) VALUES (?, ?, ?, ?, ?::FLOAT[{dim}], ?)
                    """,
                    [vid, cid, gen, digest, floats, meta],
                )
            except Exception as exc:
                # Surface engine-level length / type rejections as DIM.
                msg = str(exc).lower()
                if "length" in msg or "array" in msg or "cast" in msg:
                    raise ExactVectorStoreError(
                        "DIM",
                        "mixed dimensions cannot enter one physical table",
                        expected=dim,
                        got=len(values),
                        cause=str(exc),
                    ) from exc
                raise
            return digest

    def delete_vector(self, collection_id: str, vector_id: str) -> bool:
        """Delete a vector by id from the collection's physical table."""
        cid = _require_id(collection_id, field="collection_id")
        vid = _require_id(vector_id, field="vector_id")
        with self._lock:
            self._ensure_open()
            if self._read_only:
                raise ExactVectorStoreError("READ_ONLY", "store is read-only")
            dim, _gen = self._collection_dim(cid)
            table = self._table(dim)
            before = self._conn.execute(
                f"SELECT 1 FROM {table} WHERE vector_id = ? AND collection_id = ?",
                [vid, cid],
            ).fetchone()
            if before is None:
                return False
            self._conn.execute(
                f"DELETE FROM {table} WHERE vector_id = ? AND collection_id = ?",
                [vid, cid],
            )
            return True

    # -- search --------------------------------------------------------------

    def _sql_distance_expr(self, metric: str, dimension: int) -> str:
        if metric == "l2":
            return f"array_distance(embedding, ?::FLOAT[{dimension}])"
        if metric == "cosine":
            return f"array_cosine_distance(embedding, ?::FLOAT[{dimension}])"
        raise ExactVectorStoreError("METRIC", f"unsupported metric {metric!r}")

    def _metadata_filter_sql(
        self,
        metadata_filter: Optional[Mapping[str, Any]],
    ) -> tuple[str, list[Any]]:
        """Build SQL AND clauses for equality metadata filters.

        Only top-level keys matching ``_META_KEY`` are accepted. Values are
        compared as JSON-extracted strings against the filter value's string
        form for scalars; ``None`` matches JSON null.
        """
        if not metadata_filter:
            return "", []
        if not isinstance(metadata_filter, Mapping):
            raise ExactVectorStoreError(
                "INVALID_FILTER",
                "metadata_filter must be a mapping",
            )
        clauses: list[str] = []
        params: list[Any] = []
        for key, value in metadata_filter.items():
            if not isinstance(key, str) or _META_KEY.fullmatch(key) is None:
                raise ExactVectorStoreError(
                    "INVALID_FILTER",
                    f"unsupported metadata filter key {key!r}",
                )
            path = f"$.{key}"
            if value is None:
                clauses.append(
                    f"json_extract_string(metadata_json, '{path}') IS NULL "
                    f"AND json_extract(metadata_json, '{path}') IS NOT NULL "
                    f"AND json_extract(metadata_json, '{path}') = 'null'"
                )
            elif isinstance(value, bool):
                # JSON true/false — extract as string "true"/"false".
                clauses.append(
                    f"json_extract_string(metadata_json, '{path}') = ?"
                )
                params.append("true" if value else "false")
            elif isinstance(value, (int, float)) and not isinstance(value, bool):
                # Compare numeric JSON values via cast for stable equality.
                clauses.append(
                    f"CAST(json_extract(metadata_json, '{path}') AS DOUBLE) = ?"
                )
                params.append(float(value))
            elif isinstance(value, str):
                clauses.append(
                    f"json_extract_string(metadata_json, '{path}') = ?"
                )
                params.append(value)
            else:
                # Fallback: canonical JSON equality of the extracted value.
                try:
                    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"))
                except (TypeError, ValueError) as exc:
                    raise ExactVectorStoreError(
                        "INVALID_FILTER",
                        f"filter value for {key!r} is not JSON-serializable",
                    ) from exc
                clauses.append(
                    f"CAST(json_extract(metadata_json, '{path}') AS VARCHAR) = ?"
                )
                params.append(encoded)
        if not clauses:
            return "", []
        return " AND " + " AND ".join(clauses), params

    def search(
        self,
        collection_id: str,
        query: Sequence[float],
        *,
        k: int = 10,
        metric: str = "l2",
        metadata_filter: Optional[Mapping[str, Any]] = None,
        generation_id: Optional[int] = None,
    ) -> list[ExactHit]:
        """Exact k-NN over the collection's active generation.

        Ranking is SQL ``ORDER BY distance ASC, vector_id ASC`` so equal
        distances break ties deterministically by vector id. Only rows for the
        bound generation are visible. Each hit carries ``content_digest``.
        """
        cid = _require_id(collection_id, field="collection_id")
        if isinstance(k, bool) or not isinstance(k, int) or k < 1:
            raise ExactVectorStoreError("K", "k must be >= 1")
        if metric not in SUPPORTED_METRICS:
            raise ExactVectorStoreError("METRIC", f"unsupported metric {metric!r}")

        with self._lock:
            self._ensure_open()
            dim, active_gen = self._collection_dim(cid)
            q = _require_finite_floats(query, dimension=dim)
            q = decode_vector(encode_vector(q), dim)
            gen = active_gen if generation_id is None else int(generation_id)
            table = self._table(dim)
            # Table must exist for a registered collection (created on create).
            exists = self._conn.execute(
                "SELECT 1 FROM exact_dimension_tables WHERE dimension = ?",
                [dim],
            ).fetchone()
            if exists is None:
                return []

            dist_expr = self._sql_distance_expr(metric, dim)
            filter_sql, filter_params = self._metadata_filter_sql(metadata_filter)
            sql = f"""
                SELECT
                    vector_id,
                    collection_id,
                    generation_id,
                    content_digest,
                    {dist_expr} AS distance,
                    metadata_json
                FROM {table}
                WHERE collection_id = ?
                  AND generation_id = ?
                  {filter_sql}
                ORDER BY distance ASC, vector_id ASC
                LIMIT ?
            """
            params: list[Any] = [q, cid, gen, *filter_params, int(k)]
            rows = self._conn.execute(sql, params).fetchall()
            hits: list[ExactHit] = []
            for row in rows:
                hits.append(
                    ExactHit(
                        vector_id=str(row[0]),
                        collection_id=str(row[1]),
                        generation_id=int(row[2]),
                        content_digest=str(row[3]),
                        distance=float(row[4]),
                        metadata=_parse_metadata(row[5]),
                    )
                )
            return hits

    def count(
        self,
        collection_id: str,
        *,
        generation_id: Optional[int] = None,
    ) -> int:
        """Count vectors visible for a collection generation."""
        cid = _require_id(collection_id, field="collection_id")
        with self._lock:
            self._ensure_open()
            dim, active_gen = self._collection_dim(cid)
            gen = active_gen if generation_id is None else int(generation_id)
            table = self._table(dim)
            exists = self._conn.execute(
                "SELECT 1 FROM exact_dimension_tables WHERE dimension = ?",
                [dim],
            ).fetchone()
            if exists is None:
                return 0
            row = self._conn.execute(
                f"SELECT COUNT(*) FROM {table} "
                f"WHERE collection_id = ? AND generation_id = ?",
                [cid, gen],
            ).fetchone()
            return int(row[0]) if row else 0
