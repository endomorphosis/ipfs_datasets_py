"""Exact SQL FLOAT[N] vector search on dimension-specific tables (DQK-021).

Authoritative vectors live in one physical table per dimension. Exact
distance/ranking/filter queries bind results to collection generation and
content digest. Mixed dimensions are rejected. VSS/HNSW is not used here.
"""

from __future__ import annotations

import hashlib
import math
import re
import struct
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, Sequence, Union

__all__ = [
    "DUCKDB_EXACT_SCHEMA",
    "ExactHit",
    "ExactVectorStore",
    "ExactVectorStoreError",
    "distance",
    "encode_vector",
    "vector_digest",
]


DUCKDB_EXACT_SCHEMA: Final[str] = "ipfs_datasets_py/vector-stores-duckdb-exact@1"
_SAFE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@+-]{0,127}$")


class ExactVectorStoreError(ValueError):
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
    return struct.pack(f"<{len(values)}f", *[float(v) for v in values])


def decode_vector(data: bytes, dimension: int) -> list[float]:
    expected = dimension * 4
    if len(data) != expected:
        raise ExactVectorStoreError(
            "SIZE",
            f"vector bytes length {len(data)} != {expected}",
        )
    return list(struct.unpack(f"<{dimension}f", data))


def vector_digest(values: Sequence[float]) -> str:
    return "sha256:" + hashlib.sha256(encode_vector(values)).hexdigest()


def distance(
    left: Sequence[float],
    right: Sequence[float],
    *,
    metric: str = "l2",
) -> float:
    if len(left) != len(right):
        raise ExactVectorStoreError("DIM", "vector dimensions differ")
    if metric == "l2":
        return math.sqrt(sum((float(a) - float(b)) ** 2 for a, b in zip(left, right)))
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
    vector_id: str
    collection_id: str
    generation_id: int
    content_digest: str
    distance: float
    metadata: dict[str, Any]


class ExactVectorStore:
    """Dimension-partitioned exact vector store."""

    def __init__(self, path: Union[str, Path]) -> None:
        duckdb = _require_duckdb()
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = duckdb.connect(str(self._path))
        self._closed = False
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

    def _table(self, dimension: int) -> str:
        if not isinstance(dimension, int) or isinstance(dimension, bool) or dimension < 1:
            raise ExactVectorStoreError("DIM", "dimension must be positive int")
        return f"exact_vectors_d{int(dimension)}"

    def _ensure_table(self, dimension: int) -> str:
        table = self._table(dimension)
        self._conn.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {table} (
                vector_id VARCHAR PRIMARY KEY,
                collection_id VARCHAR NOT NULL,
                generation_id INTEGER NOT NULL,
                content_digest VARCHAR NOT NULL,
                vector_blob BLOB NOT NULL,
                metadata_json VARCHAR NOT NULL DEFAULT '{{}}'
            )
            """
        )
        return table

    def create_collection(
        self, collection_id: str, *, dimension: int, generation_id: int = 1
    ) -> None:
        if _SAFE.fullmatch(collection_id) is None:
            raise ExactVectorStoreError("ID", "invalid collection_id")
        with self._lock:
            self._ensure_table(dimension)
            existing = self._conn.execute(
                "SELECT dimension FROM exact_collections WHERE collection_id = ?",
                [collection_id],
            ).fetchone()
            if existing is not None:
                if int(existing[0]) != int(dimension):
                    raise ExactVectorStoreError(
                        "DIM",
                        "collection dimension mismatch",
                        collection_id=collection_id,
                        expected=int(existing[0]),
                        got=int(dimension),
                    )
                return
            self._conn.execute(
                "INSERT INTO exact_collections "
                "(collection_id, dimension, generation_id) VALUES (?, ?, ?)",
                [collection_id, int(dimension), int(generation_id)],
            )

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

    def upsert_vector(
        self,
        collection_id: str,
        vector_id: str,
        values: Sequence[float],
        *,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        if _SAFE.fullmatch(vector_id) is None:
            raise ExactVectorStoreError("ID", "invalid vector_id")
        with self._lock:
            dim, gen = self._collection_dim(collection_id)
            if len(values) != dim:
                raise ExactVectorStoreError(
                    "DIM",
                    "mixed dimensions cannot enter one physical table",
                    expected=dim,
                    got=len(values),
                )
            table = self._ensure_table(dim)
            digest = vector_digest(values)
            blob = encode_vector(values)
            import json

            meta = json.dumps(dict(metadata or {}), sort_keys=True)
            self._conn.execute(f"DELETE FROM {table} WHERE vector_id = ?", [vector_id])
            self._conn.execute(
                f"INSERT INTO {table} "
                "(vector_id, collection_id, generation_id, content_digest, "
                "vector_blob, metadata_json) VALUES (?, ?, ?, ?, ?, ?)",
                [vector_id, collection_id, gen, digest, blob, meta],
            )
            return digest

    def search(
        self,
        collection_id: str,
        query: Sequence[float],
        *,
        k: int = 10,
        metric: str = "l2",
        metadata_filter: dict[str, Any] | None = None,
    ) -> list[ExactHit]:
        if k < 1:
            raise ExactVectorStoreError("K", "k must be >= 1")
        with self._lock:
            dim, gen = self._collection_dim(collection_id)
            if len(query) != dim:
                raise ExactVectorStoreError(
                    "DIM",
                    "query dimension mismatch",
                    expected=dim,
                    got=len(query),
                )
            table = self._table(dim)
            rows = self._conn.execute(
                f"SELECT vector_id, collection_id, generation_id, content_digest, "
                f"vector_blob, metadata_json FROM {table} "
                f"WHERE collection_id = ? AND generation_id = ?",
                [collection_id, gen],
            ).fetchall()
            import json

            scored: list[ExactHit] = []
            for row in rows:
                meta = json.loads(row[5] or "{}")
                if metadata_filter:
                    if any(meta.get(key) != value for key, value in metadata_filter.items()):
                        continue
                vec = decode_vector(bytes(row[4]), dim)
                dist = distance(query, vec, metric=metric)
                scored.append(
                    ExactHit(
                        vector_id=row[0],
                        collection_id=row[1],
                        generation_id=int(row[2]),
                        content_digest=row[3],
                        distance=dist,
                        metadata=meta,
                    )
                )
            # Deterministic tie-break: distance asc, then vector_id asc.
            scored.sort(key=lambda h: (h.distance, h.vector_id))
            return scored[:k]
