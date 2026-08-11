"""Capability-gated rebuildable VSS/HNSW acceleration (DQK-022).

VSS is a **derived** index layer only — never the identity authority. Authoritative
vectors live in :mod:`ipfs_datasets_py.vector_stores.duckdb_exact` (exact FLOAT[N]
tables + content digests). This module materializes a rebuildable HNSW-style
acceleration view on top of that exact store.

Contract
--------
* **Identity authority** is always ``\"exact\"`` on every build/compaction receipt.
* **Pinned extension**: VSS is the DuckDB core build ``vss@1.5.5+core``
  (see :mod:`ipfs_datasets_py.duckdb_control.capabilities`). Missing, mismatched,
  or failed extension loads never raise into the query path — they fall back to
  exact search.
* **Build receipts** record generation, digest, health, and extension availability.
* **Health checks** cover healthy / missing_extension / extension_failed /
  corrupt / stale / empty.
* **Tombstone / compaction policy**: tombstones soft-exclude IDs from results;
  the accelerated materialization may still hold them until ``compact()`` or
  ``rebuild()``. Tombstone parity and recall thresholds are explicit constants;
  falling below either threshold forces exact-search fallback.
* **Corruption-safe rebuild**: ``rebuild()`` clears the derived view and
  re-materializes live (non-tombstoned) rows from the exact authority mirror.
"""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, ClassVar, Final, Mapping, Sequence

from ipfs_datasets_py.vector_stores.duckdb_exact import (
    ExactHit,
    ExactVectorStore,
    distance,
)

try:
    # Prefer the control-plane pin (DQK-002) when available.
    from ipfs_datasets_py.duckdb_control.capabilities import (
        PINNED_VSS_EXTENSION_BUILD as _PINNED_VSS_EXTENSION_BUILD,
    )
except Exception:  # pragma: no cover - hermetic / partial installs
    _PINNED_VSS_EXTENSION_BUILD = "vss@1.5.5+core"

__all__ = [
    "DEFAULT_RECALL_THRESHOLD",
    "DEFAULT_TOMBSTONE_PARITY_THRESHOLD",
    "DUCKDB_VSS_SCHEMA",
    "IndexHealth",
    "PINNED_VSS_EXTENSION_BUILD",
    "VSSBuildReceipt",
    "VSSCompactionReceipt",
    "VSSIndex",
    "VSSIndexError",
    "VSSSearchResult",
    "probe_vss_extension_default",
]


DUCKDB_VSS_SCHEMA: Final[str] = "ipfs_datasets_py/vector-stores-duckdb-vss@1"
PINNED_VSS_EXTENSION_BUILD: Final[str] = str(_PINNED_VSS_EXTENSION_BUILD)

# Explicit acceptance thresholds (DQK-022).
# Recall: fraction of exact top-k IDs recovered by the accelerated path.
DEFAULT_RECALL_THRESHOLD: Final[float] = 0.9
# Tombstone parity: fraction of tombstoned IDs correctly excluded from the
# accelerated materialization (1.0 = no tombstone leakage into the live index).
DEFAULT_TOMBSTONE_PARITY_THRESHOLD: Final[float] = 1.0

_AUTHORITY_EXACT: Final[str] = "exact"
_SUPPORTED_METRICS: Final[frozenset[str]] = frozenset({"l2", "cosine"})


class VSSIndexError(ValueError):
    """Fail-closed rejection of a VSS contract or mutation."""

    def __init__(self, code: str, message: str, **details: Any) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.details = details


class IndexHealth(str, Enum):
    """Health of the derived VSS acceleration layer (never identity state)."""

    HEALTHY = "healthy"
    MISSING_EXTENSION = "missing_extension"
    EXTENSION_FAILED = "extension_failed"
    CORRUPT = "corrupt"
    STALE = "stale"
    EMPTY = "empty"


def _utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


def probe_vss_extension_default() -> bool:
    """Default probe: VSS is unavailable unless an explicit probe injects True.

    Sealed validation environments must not INSTALL/LOAD network extensions.
    Production callers inject a probe that LOADs the pinned local ``vss``
    extension binary (``PINNED_VSS_EXTENSION_BUILD``) without auto-install.
    """

    return False


@dataclass(frozen=True)
class VSSBuildReceipt:
    """Immutable receipt for one derived-index materialization."""

    SCHEMA: ClassVar[str] = DUCKDB_VSS_SCHEMA
    collection_id: str
    generation_id: int
    dimension: int
    vector_count: int
    build_digest: str
    authority: str = _AUTHORITY_EXACT
    created_at: str = ""
    extension_available: bool = False
    extension_build: str = PINNED_VSS_EXTENSION_BUILD
    health: IndexHealth = IndexHealth.EMPTY
    build_id: str = ""
    tombstone_count: int = 0
    index_kind: str = "vss_hnsw"

    def __post_init__(self) -> None:
        # Authority is a hard invariant — VSS never becomes identity authority.
        if self.authority != _AUTHORITY_EXACT:
            object.__setattr__(self, "authority", _AUTHORITY_EXACT)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": DUCKDB_VSS_SCHEMA,
            "build_id": self.build_id,
            "collection_id": self.collection_id,
            "generation_id": self.generation_id,
            "dimension": self.dimension,
            "vector_count": self.vector_count,
            "tombstone_count": self.tombstone_count,
            "build_digest": self.build_digest,
            # Always exact — derived indexes never claim identity authority.
            "authority": _AUTHORITY_EXACT,
            "created_at": self.created_at,
            "extension_available": self.extension_available,
            "extension_build": self.extension_build,
            "health": self.health.value if isinstance(self.health, IndexHealth) else str(self.health),
            "index_kind": self.index_kind,
        }


@dataclass(frozen=True)
class VSSCompactionReceipt:
    """Receipt for purging tombstoned IDs from the derived acceleration view."""

    SCHEMA: ClassVar[str] = DUCKDB_VSS_SCHEMA
    compaction_id: str
    collection_id: str
    generation_id: int
    removed_count: int
    remaining_count: int
    receipt_digest: str
    authority: str = _AUTHORITY_EXACT
    created_at: str = ""
    tombstone_parity: float = 1.0

    def __post_init__(self) -> None:
        if self.authority != _AUTHORITY_EXACT:
            object.__setattr__(self, "authority", _AUTHORITY_EXACT)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": DUCKDB_VSS_SCHEMA,
            "compaction_id": self.compaction_id,
            "collection_id": self.collection_id,
            "generation_id": self.generation_id,
            "removed_count": self.removed_count,
            "remaining_count": self.remaining_count,
            "receipt_digest": self.receipt_digest,
            "authority": _AUTHORITY_EXACT,
            "created_at": self.created_at,
            "tombstone_parity": self.tombstone_parity,
        }


@dataclass
class VSSSearchResult:
    """Search outcome with fallback / health / recall diagnostics."""

    hits: list[ExactHit]
    used_fallback: bool
    health: IndexHealth
    recall_estimate: float | None = None
    tombstone_parity: float | None = None


@dataclass
class VSSIndex:
    """In-process VSS acceleration facade over an exact vector store.

    The exact store is the identity authority. This object holds a derived
    accelerated materialization (``_index_ids`` + ``_vectors`` mirror) that can
    be rebuilt or compacted without mutating identity semantics.
    """

    exact: ExactVectorStore
    collection_id: str
    dimension: int
    generation_id: int = 1
    recall_threshold: float = DEFAULT_RECALL_THRESHOLD
    tombstone_parity_threshold: float = DEFAULT_TOMBSTONE_PARITY_THRESHOLD
    extension_probe: Callable[[], bool] | None = None
    extension_build: str = PINNED_VSS_EXTENSION_BUILD
    # Soft-deleted IDs (excluded from results; may still sit in materialization).
    _tombstoned: set[str] = field(default_factory=set)
    # Derived HNSW materialization membership (may lag tombstones until compact).
    _index_ids: list[str] = field(default_factory=list)
    # Local mirror of vectors also written to the exact authority store.
    _vectors: dict[str, list[float]] = field(default_factory=dict)
    _last_receipt: VSSBuildReceipt | None = None
    _last_compaction: VSSCompactionReceipt | None = None
    _corrupt: bool = False
    _extension_failed: bool = False
    _stale: bool = False
    _build_count: int = 0

    # ------------------------------------------------------------------
    # Extension capability
    # ------------------------------------------------------------------

    def _extension_available(self) -> bool:
        """Probe the pinned VSS extension; failures become EXTENSION_FAILED."""

        probe = self.extension_probe
        if probe is None:
            probe = probe_vss_extension_default
        try:
            return bool(probe())
        except Exception:
            self._extension_failed = True
            return False

    # ------------------------------------------------------------------
    # Build / rebuild
    # ------------------------------------------------------------------

    def build(self, vectors: Mapping[str, Sequence[float]]) -> VSSBuildReceipt:
        """Upsert vectors into the exact authority and re-materialize the index.

        Vectors already tombstoned are accepted into the exact store but are
        **not** added to the accelerated materialization.
        """

        if not isinstance(vectors, Mapping):
            raise VSSIndexError("VEC", "vectors must be a mapping of id -> values")

        for vid, vals in vectors.items():
            if not isinstance(vid, str) or not vid:
                raise VSSIndexError("ID", "vector_id must be a non-empty string")
            if not isinstance(vals, Sequence) or isinstance(vals, (str, bytes, bytearray)):
                raise VSSIndexError("VEC", "values must be a numeric sequence", vector_id=vid)
            if len(vals) != self.dimension:
                raise VSSIndexError(
                    "DIM",
                    "dimension mismatch",
                    vector_id=vid,
                    expected=self.dimension,
                    got=len(vals),
                )
            floats = [float(x) for x in vals]
            # Identity write goes to exact authority first.
            self.exact.upsert_vector(self.collection_id, vid, floats)
            self._vectors[vid] = floats

        # Re-materialize accelerated membership from the live (non-tombstoned) set.
        live_ids = sorted(
            vid for vid in self._vectors if vid not in self._tombstoned
        )
        self._index_ids = list(live_ids)
        self._stale = False
        self._build_count += 1

        return self._emit_build_receipt()

    def rebuild(self) -> VSSBuildReceipt:
        """Corruption-safe rebuild from the exact-authority mirror.

        Clears the derived view, drops the corrupt flag, and re-materializes
        only non-tombstoned vectors already known from prior exact upserts.
        Identity rows in the exact store are left untouched.
        """

        self._corrupt = False
        self._extension_failed = False
        self._stale = False
        live = {
            vid: list(vals)
            for vid, vals in self._vectors.items()
            if vid not in self._tombstoned
        }
        # Drop accelerated materialization before rebuild so a partial failure
        # cannot leave a half-corrupt index claiming HEALTHY.
        self._index_ids = []
        if not live:
            self._build_count += 1
            return self._emit_build_receipt()
        return self.build(live)

    def _emit_build_receipt(self) -> VSSBuildReceipt:
        available = self._extension_available() and not self._extension_failed
        live_count = len([vid for vid in self._index_ids if vid not in self._tombstoned])
        material = json.dumps(
            {
                "ids": sorted(self._index_ids),
                "dim": self.dimension,
                "generation_id": self.generation_id,
                "collection_id": self.collection_id,
                "tombstoned": sorted(self._tombstoned),
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        digest = "sha256:" + hashlib.sha256(material.encode("utf-8")).hexdigest()
        health = self._compute_health(extension_available=available)
        receipt = VSSBuildReceipt(
            collection_id=self.collection_id,
            generation_id=self.generation_id,
            dimension=self.dimension,
            vector_count=live_count,
            build_digest=digest,
            authority=_AUTHORITY_EXACT,
            created_at=_utc_now(),
            extension_available=available,
            extension_build=self.extension_build,
            health=health,
            build_id=_new_id("vssbuild"),
            tombstone_count=len(self._tombstoned),
            index_kind="vss_hnsw",
        )
        self._last_receipt = receipt
        return receipt

    # ------------------------------------------------------------------
    # Tombstone / compaction policy
    # ------------------------------------------------------------------

    def tombstone(self, vector_id: str) -> None:
        """Soft-exclude ``vector_id`` from results.

        The accelerated materialization may still contain the ID until
        :meth:`compact` or :meth:`rebuild`. Search always post-filters
        tombstones; parity may drop until compaction.
        """

        if not isinstance(vector_id, str) or not vector_id:
            raise VSSIndexError("ID", "vector_id must be a non-empty string")
        self._tombstoned.add(vector_id)
        # Index still holding the ID is expected until compact — mark stale so
        # health/search prefer exact fallback when parity drops below threshold.
        if vector_id in self._index_ids:
            self._stale = True

    def compact(self) -> VSSCompactionReceipt:
        """Purge tombstoned IDs from the accelerated materialization.

        Compaction is a derived-layer operation: it never deletes identity rows
        from the exact store. After compaction, tombstone parity returns to 1.0
        when every tombstone is absent from ``_index_ids``.
        """

        before = list(self._index_ids)
        removed = [vid for vid in before if vid in self._tombstoned]
        self._index_ids = [vid for vid in before if vid not in self._tombstoned]
        self._stale = False
        parity = self.tombstone_parity()
        payload = json.dumps(
            {
                "collection_id": self.collection_id,
                "generation_id": self.generation_id,
                "removed": sorted(removed),
                "remaining": sorted(self._index_ids),
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        digest = "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()
        receipt = VSSCompactionReceipt(
            compaction_id=_new_id("vsscompact"),
            collection_id=self.collection_id,
            generation_id=self.generation_id,
            removed_count=len(removed),
            remaining_count=len(self._index_ids),
            receipt_digest=digest,
            authority=_AUTHORITY_EXACT,
            created_at=_utc_now(),
            tombstone_parity=parity,
        )
        self._last_compaction = receipt
        return receipt

    def tombstone_parity(self) -> float:
        """Fraction of tombstoned IDs excluded from the accelerated set.

        ``1.0`` means no tombstoned ID appears in the live HNSW materialization.
        ``0.0`` means every tombstone still leaks into the accelerated view.
        When there are no tombstones, parity is defined as ``1.0``.
        """

        if not self._tombstoned:
            return 1.0
        index_set = set(self._index_ids)
        leaked = self._tombstoned & index_set
        return 1.0 - (len(leaked) / len(self._tombstoned))

    # ------------------------------------------------------------------
    # Health
    # ------------------------------------------------------------------

    def mark_corrupt(self) -> None:
        """Force the derived index into CORRUPT health (exact remains authoritative)."""

        self._corrupt = True

    def mark_extension_failed(self) -> None:
        """Record that the pinned VSS extension failed to load/initialize."""

        self._extension_failed = True

    def health(self) -> IndexHealth:
        return self._compute_health(extension_available=None)

    def _compute_health(self, *, extension_available: bool | None) -> IndexHealth:
        if self._corrupt:
            return IndexHealth.CORRUPT
        if self._extension_failed:
            return IndexHealth.EXTENSION_FAILED
        if extension_available is None:
            available = self._extension_available()
        else:
            available = extension_available
        if not available:
            return IndexHealth.MISSING_EXTENSION
        live = [vid for vid in self._index_ids if vid not in self._tombstoned]
        if not live:
            return IndexHealth.EMPTY
        if self._stale or self.tombstone_parity() < self.tombstone_parity_threshold:
            return IndexHealth.STALE
        return IndexHealth.HEALTHY

    @property
    def last_receipt(self) -> VSSBuildReceipt | None:
        return self._last_receipt

    @property
    def last_compaction(self) -> VSSCompactionReceipt | None:
        return self._last_compaction

    # ------------------------------------------------------------------
    # Search (accelerated with exact fallback)
    # ------------------------------------------------------------------

    def search(
        self,
        query: Sequence[float],
        *,
        k: int = 10,
        metric: str = "l2",
    ) -> VSSSearchResult:
        """Search with automatic exact fallback when the derived index is unsafe.

        Exact search is always computed as the authority baseline. Accelerated
        results are only returned when health is HEALTHY, tombstone parity meets
        ``tombstone_parity_threshold``, and estimated recall meets
        ``recall_threshold``.
        """

        if not isinstance(k, int) or isinstance(k, bool) or k < 1:
            raise VSSIndexError("K", "k must be >= 1")
        if metric not in _SUPPORTED_METRICS:
            raise VSSIndexError("METRIC", f"unsupported metric {metric!r}")
        if not isinstance(query, Sequence) or isinstance(query, (str, bytes, bytearray)):
            raise VSSIndexError("VEC", "query must be a numeric sequence")
        if len(query) != self.dimension:
            raise VSSIndexError(
                "DIM",
                "query dimension mismatch",
                expected=self.dimension,
                got=len(query),
            )

        parity = self.tombstone_parity()
        health = self.health()

        # Identity authority path — always available when exact store is healthy.
        exact_hits = [
            h
            for h in self.exact.search(
                self.collection_id, query, k=max(k * 2, k), metric=metric
            )
            if h.vector_id not in self._tombstoned
        ][:k]

        must_fallback = health in {
            IndexHealth.MISSING_EXTENSION,
            IndexHealth.EXTENSION_FAILED,
            IndexHealth.CORRUPT,
            IndexHealth.EMPTY,
            IndexHealth.STALE,
        } or parity < self.tombstone_parity_threshold

        if must_fallback:
            return VSSSearchResult(
                hits=exact_hits,
                used_fallback=True,
                health=health if health is not IndexHealth.HEALTHY else IndexHealth.STALE,
                recall_estimate=1.0,
                tombstone_parity=parity,
            )

        # Derived accelerated path (hermetic stand-in for HNSW): rank the
        # materialization with the same distance function, post-filter tombstones.
        approx = self._accelerated_search(query, k=k, metric=metric)
        recall = self._estimate_recall(exact_hits, approx)
        if recall < self.recall_threshold:
            return VSSSearchResult(
                hits=exact_hits,
                used_fallback=True,
                health=IndexHealth.STALE,
                recall_estimate=recall,
                tombstone_parity=parity,
            )
        return VSSSearchResult(
            hits=approx,
            used_fallback=False,
            health=health,
            recall_estimate=recall,
            tombstone_parity=parity,
        )

    def _accelerated_search(
        self,
        query: Sequence[float],
        *,
        k: int,
        metric: str,
    ) -> list[ExactHit]:
        """Rank the derived materialization (HNSW stand-in for hermetic tests)."""

        q = [float(x) for x in query]
        scored: list[tuple[float, str]] = []
        for vid in self._index_ids:
            if vid in self._tombstoned:
                continue
            vec = self._vectors.get(vid)
            if vec is None:
                continue
            scored.append((distance(q, vec, metric=metric), vid))
        scored.sort(key=lambda item: (item[0], item[1]))
        hits: list[ExactHit] = []
        for dist, vid in scored[:k]:
            # Bind generation/digest via a one-id exact lookup so identity fields
            # stay consistent with the authority store.
            authority = self.exact.search(
                self.collection_id,
                self._vectors[vid],
                k=1,
                metric=metric,
            )
            if authority and authority[0].vector_id == vid:
                hits.append(
                    ExactHit(
                        vector_id=vid,
                        collection_id=authority[0].collection_id,
                        generation_id=authority[0].generation_id,
                        content_digest=authority[0].content_digest,
                        distance=dist,
                        metadata=dict(authority[0].metadata),
                    )
                )
            else:
                hits.append(
                    ExactHit(
                        vector_id=vid,
                        collection_id=self.collection_id,
                        generation_id=self.generation_id,
                        content_digest="",
                        distance=dist,
                        metadata={},
                    )
                )
        return hits

    @staticmethod
    def _estimate_recall(
        exact_hits: Sequence[ExactHit],
        approx_hits: Sequence[ExactHit],
    ) -> float:
        if not exact_hits:
            return 1.0
        exact_ids = {h.vector_id for h in exact_hits}
        approx_ids = {h.vector_id for h in approx_hits}
        return len(exact_ids & approx_ids) / len(exact_ids)
