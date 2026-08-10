"""One-time FAISS metadata import with shadow dual-read/write (DQK-023).

Unsafe pickle is confined to an explicit import path. Normal runtime never
unpickles. Every imported generation records source digests and reject reports.
External backend parity is measured before promotion.
"""

from __future__ import annotations

import hashlib
import json
import pickle
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Final, Mapping, Sequence

from ipfs_datasets_py.vector_stores.duckdb_exact import ExactVectorStore, vector_digest

__all__ = [
    "DUCKDB_VECTOR_MIGRATION_SCHEMA",
    "ExternalBackend",
    "ImportReject",
    "MigrationReport",
    "ParityReport",
    "VectorMigrationError",
    "import_faiss_pickle_metadata",
    "measure_external_parity",
]


DUCKDB_VECTOR_MIGRATION_SCHEMA: Final[str] = (
    "ipfs_datasets_py/vector-stores-duckdb-migration@1"
)


class VectorMigrationError(ValueError):
    pass


class ExternalBackend(str, Enum):
    FAISS = "faiss"
    QDRANT = "qdrant"
    ELASTICSEARCH = "elasticsearch"


@dataclass(frozen=True)
class ImportReject:
    vector_id: str
    reason: str


@dataclass
class MigrationReport:
    source_digest: str
    imported_count: int
    rejected: list[ImportReject] = field(default_factory=list)
    quarantined_duplicates: list[str] = field(default_factory=list)
    generation_id: int = 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": DUCKDB_VECTOR_MIGRATION_SCHEMA,
            "source_digest": self.source_digest,
            "imported_count": self.imported_count,
            "rejected": [
                {"vector_id": r.vector_id, "reason": r.reason} for r in self.rejected
            ],
            "quarantined_duplicates": list(self.quarantined_duplicates),
            "generation_id": self.generation_id,
        }


@dataclass(frozen=True)
class ParityReport:
    backend: ExternalBackend
    matched: int
    total: int
    promotion_allowed: bool

    @property
    def ratio(self) -> float:
        return self.matched / self.total if self.total else 1.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "backend": self.backend.value,
            "matched": self.matched,
            "total": self.total,
            "ratio": self.ratio,
            "promotion_allowed": self.promotion_allowed,
        }


def _digest_bytes(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def import_faiss_pickle_metadata(
    pickle_path: Path | str,
    store: ExactVectorStore,
    *,
    collection_id: str,
    dimension: int,
    allow_unpickle: bool = False,
) -> MigrationReport:
    """Isolated one-time import. Requires ``allow_unpickle=True`` explicitly."""

    if not allow_unpickle:
        raise VectorMigrationError(
            "normal runtime never unpickles; pass allow_unpickle=True "
            "only for the one-time migration path"
        )
    path = Path(pickle_path)
    raw = path.read_bytes()
    source_digest = _digest_bytes(raw)
    try:
        payload = pickle.loads(raw)  # noqa: S301 — explicit migration path only
    except Exception as exc:  # pragma: no cover
        raise VectorMigrationError(f"pickle load failed: {exc}") from exc
    if not isinstance(payload, Mapping):
        raise VectorMigrationError("pickle root must be a mapping")

    store.create_collection(collection_id, dimension=dimension)
    seen: set[str] = set()
    rejected: list[ImportReject] = []
    quarantined: list[str] = []
    imported = 0
    items = payload.get("vectors") or payload.get("items") or payload
    if isinstance(items, Mapping):
        iterator = items.items()
    else:
        raise VectorMigrationError("pickle payload missing vectors mapping")

    for vector_id, entry in iterator:
        vid = str(vector_id)
        if vid in seen:
            quarantined.append(vid)
            continue
        seen.add(vid)
        if isinstance(entry, Mapping):
            values = entry.get("vector") or entry.get("values")
        else:
            values = entry
        if not isinstance(values, Sequence) or isinstance(values, (str, bytes)):
            rejected.append(ImportReject(vid, "vector values missing"))
            continue
        if len(values) != dimension:
            rejected.append(ImportReject(vid, "dimension mismatch"))
            continue
        try:
            store.upsert_vector(collection_id, vid, [float(x) for x in values])
            imported += 1
        except Exception as exc:  # pragma: no cover
            rejected.append(ImportReject(vid, str(exc)))

    return MigrationReport(
        source_digest=source_digest,
        imported_count=imported,
        rejected=rejected,
        quarantined_duplicates=quarantined,
    )


def measure_external_parity(
    store: ExactVectorStore,
    *,
    collection_id: str,
    query: Sequence[float],
    external_hits: Sequence[str],
    backend: ExternalBackend,
    k: int = 10,
    min_ratio: float = 0.8,
) -> ParityReport:
    """Compare exact DuckDB ranking with an external backend hit list."""

    exact = store.search(collection_id, query, k=k)
    exact_ids = [h.vector_id for h in exact]
    ext = list(external_hits)[:k]
    matched = len(set(exact_ids) & set(ext))
    total = max(len(exact_ids), 1)
    ratio = matched / total
    return ParityReport(
        backend=backend,
        matched=matched,
        total=total,
        promotion_allowed=ratio >= min_ratio,
    )
