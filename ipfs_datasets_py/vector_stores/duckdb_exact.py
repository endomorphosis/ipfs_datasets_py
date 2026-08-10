"""Exact SQL FLOAT[N] vector search on dimension-specific tables (DQK-021).

Authoritative vectors live in one physical table per dimension
(``exact_vectors_d{N}`` with a native ``FLOAT[N]`` column). Exact
distance/ranking/filter queries bind results to collection generation and
content digest. Mixed dimensions are rejected at the collection boundary —
they cannot enter one physical table. VSS/HNSW is not used here (see DQK-022).
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
from typing import Any, Final, Mapping, Sequence, Union

__all__ = [
    "DUCKDB_EXACT_SCHEMA",
    "ExactHit",
    "ExactVectorStore",
    "ExactVectorStoreError",
    "decode_vector",
    "distance",
    "encode_vector",
    "vector_digest",
]


DUCKDB_EXACT_SCHEMA: Final[str] = "ipfs_datasets_py/vector-stores-duckdb-exact@1"
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@+-]{0,127}$")
_SUPPORTED_METRICS: Final[frozenset[str]] = frozenset({"l2", "cosine"})


class ExactVectorStoreError(ValueError):
    """Fail-closed rejection of an exact vector store contract or mutation."""

    def __init__(self, code: str, message: str, **details: Any) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.details = details


def _require_duckdb() -> Any:
    try:
        import duckdb  # type: ignore
    except ImportError as exc:  # pragma: no cover
        raise ExactVectorStoreError(
            "DUCKDB_REQUIRED", "duckdb package is required"
        ) from exc
    return duckdb


def encode_vector(values: Sequence[float]) -> bytes:
    """Pack floats as little-endian float32 bytes (canonical wire form)."""

    return struct.pack(f"<{len(values)}f", *[float(v) for v in values])


def decode_vector(data: bytes, dimension: int) -> list[float]:
    """Unpack little-endian float32 bytes into a Python float list."""

    expected = dimension * 4
    if len(data) != expected:
        raise ExactVectorStoreError(
            "SIZE",
            f"vector bytes length {len(data)} != {expected}",
        )
    return list(struct.unpack(f"<{dimension}f", data))


def vector_digest(values: Sequence[float]) -> str:
    """Content digest over the canonical float32 encoding of ``values``."""

    return "sha256:" + hashlib.sha256(encode_vector(values)).hexdigest()


def distance(
    left: Sequence[float],
    right: Sequence[float],
    *,
    metric: str = "l2",
) -> float:
    """Exact pairwise distance used for hermetic ranking and fixtures.

    * ``l2`` — Euclidean (L2) distance
    * ``cosine`` — cosine distance ``1 - cos_sim`` (1.0 for zero vectors)
    """

    if len(left) != len(right):
        raise ExactVectorStoreError("DIM", "vector dimensions differ")
    if metric == "l2":
        return math.sqrt(
            sum((float(a) - float(b)) ** 2 for a, b in zip(left, right))
        )
    if metric == "cosine":
        dot = sum(float(a) * float(b) for a, b in zip(left, right))
        na = math.sqrt(sum(float(a) ** 2 for a in left))
        nb = math.sqrt(sum(float(b) ** 2 for b in right))
        if na == 0.0 or nb == 0.0:
            return 1.0
        return 1.0 - (dot / (na * nb))
    raise ExactVectorStoreError("METRIC", f"unsupported metric {metric!r}")


@dataclass(frozen=True)
class ExactHit:
    """One ranked exact-search hit bound to generation and content digest."""

    vector_id: str
    collection_id: str
    generation_id: int
    content_digest: str
    distance: float
    metadata: dict[str, Any]


class ExactVectorStore:
    """Dimension-partitioned exact vector store with native FLOAT[N] tables.

    Physical layout
    ---------------
    * ``exact_collections`` — collection_id → (dimension, generation_id)
    * ``exact_vectors_d{N}`` — one table per dimension with column
      ``vector FLOAT[N]``; rows from different collections that share ``N``
      coexist, filtered by ``collection_id`` / ``generation_id`` at query time.
    """

    def __init__(self, path: Union[str, Path]) -> None:
        duckdb = _require_duckdb()
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = duckdb.connect(str(self._path))
        self._closed = False
        self._known_tables: set[int] = set()
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS exact_collections (
                collection_id VARCHAR PRIMARY KEY,
                dimension INTEGER NOT NULL,
                generation_id INTEGER NOT NULL
            )
            """
        )

    def close(self) -> None:
        with self._lock:
            if not self._closed:
                self._conn.close()
                self._closed = True

    def __enter__(self) -> "ExactVectorStore":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # ------------------------------------------------------------------
    # Schema helpers
    # ------------------------------------------------------------------

    def _require_dimension(self, dimension: Any) -> int:
        if not isinstance(dimension, int) or isinstance(dimension, bool) or dimension < 1:
            raise ExactVectorStoreError("DIM", "dimension must be positive int")
        if dimension > 65536:
            raise ExactVectorStoreError("DIM", "dimension exceeds hard cap 65536")
        return int(dimension)

    def _table(self, dimension: int) -> str:
        dim = self._require_dimension(dimension)
        return f"exact_vectors_d{dim}"

    def _ensure_table(self, dimension: int) -> str:
        dim = self._require_dimension(dimension)
        table = self._table(dim)
        if dim in self._known_tables:
            return table
        # Native FLOAT[N] column — dimension is fixed into the physical type so
        # mixed lengths cannot be inserted into the same table by construction.
        self._conn.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {table} (
                vector_id VARCHAR PRIMARY KEY,
                collection_id VARCHAR NOT NULL,
                generation_id INTEGER NOT NULL,
                content_digest VARCHAR NOT NULL,
                vector FLOAT[{dim}] NOT NULL,
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
        self._known_tables.add(dim)
        return table

    # ------------------------------------------------------------------
    # Collections
    # ------------------------------------------------------------------

    def create_collection(
        self,
        collection_id: str,
        *,
        dimension: int,
        generation_id: int = 1,
    ) -> None:
        if _SAFE_ID.fullmatch(collection_id) is None:
            raise ExactVectorStoreError("ID", "invalid collection_id")
        dim = self._require_dimension(dimension)
        if not isinstance(generation_id, int) or isinstance(generation_id, bool):
            raise ExactVectorStoreError("GEN", "generation_id must be int")
        if generation_id < 1:
            raise ExactVectorStoreError("GEN", "generation_id must be >= 1")
        with self._lock:
            self._ensure_table(dim)
            existing = self._conn.execute(
                "SELECT dimension FROM exact_collections WHERE collection_id = ?",
                [collection_id],
            ).fetchone()
            if existing is not None:
                if int(existing[0]) != dim:
                    raise ExactVectorStoreError(
                        "DIM",
                        "collection dimension mismatch",
                        collection_id=collection_id,
                        expected=int(existing[0]),
                        got=dim,
                    )
                return
            self._conn.execute(
                "INSERT INTO exact_collections "
                "(collection_id, dimension, generation_id) VALUES (?, ?, ?)",
                [collection_id, dim, int(generation_id)],
            )

    def set_generation(self, collection_id: str, generation_id: int) -> None:
        """Advance the collection generation used to bind search results."""

        if not isinstance(generation_id, int) or isinstance(generation_id, bool):
            raise ExactVectorStoreError("GEN", "generation_id must be int")
        if generation_id < 1:
            raise ExactVectorStoreError("GEN", "generation_id must be >= 1")
        with self._lock:
            dim, _ = self._collection_dim(collection_id)
            self._conn.execute(
                "UPDATE exact_collections SET generation_id = ? "
                "WHERE collection_id = ?",
                [int(generation_id), collection_id],
            )
            # Ensure the physical table for this dim still exists after reopen.
            self._ensure_table(dim)

    def _collection_dim(self, collection_id: str) -> tuple[int, int]:
        row = self._conn.execute(
            "SELECT dimension, generation_id FROM exact_collections "
            "WHERE collection_id = ?",
            [collection_id],
        ).fetchone()
        if row is None:
            raise ExactVectorStoreError(
                "NOT_FOUND", f"unknown collection {collection_id!r}"
            )
        return int(row[0]), int(row[1])

    # ------------------------------------------------------------------
    # Mutations
    # ------------------------------------------------------------------

    def upsert_vector(
        self,
        collection_id: str,
        vector_id: str,
        values: Sequence[float],
        *,
        metadata: Mapping[str, Any] | None = None,
    ) -> str:
        if _SAFE_ID.fullmatch(vector_id) is None:
            raise ExactVectorStoreError("ID", "invalid vector_id")
        if not isinstance(values, Sequence) or isinstance(values, (str, bytes, bytearray)):
            raise ExactVectorStoreError("VEC", "values must be a numeric sequence")
        with self._lock:
            dim, gen = self._collection_dim(collection_id)
            if len(values) != dim:
                raise ExactVectorStoreError(
                    "DIM",
                    "mixed dimensions cannot enter one physical table",
                    expected=dim,
                    got=len(values),
                )
            floats = [float(x) for x in values]
            table = self._ensure_table(dim)
            digest = vector_digest(floats)
            meta = json.dumps(dict(metadata or {}), sort_keys=True, separators=(",", ":"))
            # DELETE+INSERT keeps PK uniqueness without relying on OR REPLACE
            # dialect quirks across DuckDB builds.
            self._conn.execute(
                f"DELETE FROM {table} WHERE vector_id = ?", [vector_id]
            )
            self._conn.execute(
                f"""
                INSERT INTO {table}
                    (vector_id, collection_id, generation_id, content_digest,
                     vector, metadata_json)
                VALUES (?, ?, ?, ?, ?::FLOAT[{dim}], ?)
                """,
                [vector_id, collection_id, gen, digest, floats, meta],
            )
            return digest

    def delete_vector(self, collection_id: str, vector_id: str) -> bool:
        with self._lock:
            dim, _ = self._collection_dim(collection_id)
            table = self._ensure_table(dim)
            before = self._conn.execute(
                f"SELECT 1 FROM {table} WHERE vector_id = ? AND collection_id = ?",
                [vector_id, collection_id],
            ).fetchone()
            if before is None:
                return False
            self._conn.execute(
                f"DELETE FROM {table} WHERE vector_id = ? AND collection_id = ?",
                [vector_id, collection_id],
            )
            return True

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    def search(
        self,
        collection_id: str,
        query: Sequence[float],
        *,
        k: int = 10,
        metric: str = "l2",
        metadata_filter: Mapping[str, Any] | None = None,
    ) -> list[ExactHit]:
        if not isinstance(k, int) or isinstance(k, bool) or k < 1:
            raise ExactVectorStoreError("K", "k must be >= 1")
        if metric not in _SUPPORTED_METRICS:
            raise ExactVectorStoreError("METRIC", f"unsupported metric {metric!r}")
        if not isinstance(query, Sequence) or isinstance(query, (str, bytes, bytearray)):
            raise ExactVectorStoreError("VEC", "query must be a numeric sequence")
        with self._lock:
            dim, gen = self._collection_dim(collection_id)
            if len(query) != dim:
                raise ExactVectorStoreError(
                    "DIM",
                    "query dimension mismatch",
                    expected=dim,
                    got=len(query),
                )
            table = self._ensure_table(dim)
            q = [float(x) for x in query]
            rows = self._conn.execute(
                f"""
                SELECT vector_id, collection_id, generation_id, content_digest,
                       vector, metadata_json
                FROM {table}
                WHERE collection_id = ? AND generation_id = ?
                """,
                [collection_id, gen],
            ).fetchall()

            scored: list[ExactHit] = []
            for row in rows:
                meta = json.loads(row[5] or "{}")
                if not isinstance(meta, dict):
                    meta = {}
                if metadata_filter:
                    if any(
                        meta.get(key) != value
                        for key, value in metadata_filter.items()
                    ):
                        continue
                # DuckDB returns FLOAT[N] as a tuple/list of floats.
                raw = row[4]
                if raw is None:
                    continue
                vec = [float(x) for x in raw]
                if len(vec) != dim:
                    # Defensive: physical type should already enforce length.
                    raise ExactVectorStoreError(
                        "DIM",
                        "stored vector dimension mismatch",
                        expected=dim,
                        got=len(vec),
                        vector_id=row[0],
                    )
                dist = distance(q, vec, metric=metric)
                scored.append(
                    ExactHit(
                        vector_id=str(row[0]),
                        collection_id=str(row[1]),
                        generation_id=int(row[2]),
                        content_digest=str(row[3]),
                        distance=dist,
                        metadata=meta,
                    )
                )
            # Deterministic tie-break: distance ascending, then vector_id ascending.
            scored.sort(key=lambda h: (h.distance, h.vector_id))
            return scored[:k]

    def physical_table_name(self, dimension: int) -> str:
        """Return the physical table name for a dimension (test/introspection)."""

        return self._table(dimension)

    def count(self, collection_id: str) -> int:
        with self._lock:
            dim, gen = self._collection_dim(collection_id)
            table = self._ensure_table(dim)
            row = self._conn.execute(
                f"""
                SELECT COUNT(*) FROM {table}
                WHERE collection_id = ? AND generation_id = ?
                """,
                [collection_id, gen],
            ).fetchone()
            return int(row[0]) if row else 0
