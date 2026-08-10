"""One-time FAISS metadata import with shadow dual-read/write (DQK-023).

Unsafe pickle is confined to an explicit, opt-in import path
(``allow_unpickle=True``). Normal runtime never unpickles: importing this
module performs no pickle I/O, and every public entry point other than the
one-time importer refuses untrusted binary metadata.

Every imported generation records:

* a source digest over the raw pickle bytes
* a reject report (dimension / mapping / value failures)
* quarantined stale duplicates (within-batch and against live store rows)

During shadow mode the dual-read/write adapter keeps DuckDB exact search as
the candidate authority while FAISS, Qdrant, and Elasticsearch remain active
backends. External backend parity is measured and must pass before promotion.
"""

from __future__ import annotations

import hashlib
import json
import math
import pickle
import threading
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import (
    Any,
    Callable,
    Final,
    Mapping,
    MutableMapping,
    Optional,
    Protocol,
    Sequence,
    Union,
)

from ipfs_datasets_py.vector_stores.duckdb_exact import (
    ExactHit,
    ExactVectorStore,
    ExactVectorStoreError,
    vector_digest,
)

__all__ = [
    "DEFAULT_PARITY_MIN_RATIO",
    "DUCKDB_VECTOR_MIGRATION_SCHEMA",
    "ExternalBackend",
    "ImportReject",
    "MigrationReport",
    "ParityReport",
    "PromotionBlockedError",
    "ShadowDualResult",
    "ShadowMode",
    "VectorMigrationError",
    "VectorShadowAdapter",
    "import_faiss_pickle_metadata",
    "measure_external_parity",
    "require_parity_for_promotion",
]


DUCKDB_VECTOR_MIGRATION_SCHEMA: Final[str] = (
    "ipfs_datasets_py/vector-stores-duckdb-migration@1"
)
DEFAULT_PARITY_MIN_RATIO: Final[float] = 0.8

# Reject / quarantine reason codes (stable for operators and tests).
REASON_NEVER_UNPICKLE: Final[str] = "normal runtime never unpickles"
REASON_DIM_MISMATCH: Final[str] = "dimension mismatch"
REASON_VALUES_MISSING: Final[str] = "vector values missing"
REASON_NON_FINITE: Final[str] = "non-finite vector component"
REASON_INVALID_ID: Final[str] = "invalid vector_id"
REASON_MAPPING_INCONSISTENT: Final[str] = "id_mapping inconsistent"
REASON_STALE_DUPLICATE: Final[str] = "stale_duplicate"
REASON_CONTENT_DUPLICATE: Final[str] = "content_duplicate"
REASON_BATCH_DUPLICATE: Final[str] = "batch_duplicate"


class VectorMigrationError(ValueError):
    """Fail-closed rejection of a migration contract or unsafe runtime path."""

    def __init__(self, message: str, *, code: str = "MIGRATION_ERROR") -> None:
        super().__init__(message)
        self.code = code


class PromotionBlockedError(VectorMigrationError):
    """Raised when external backend parity is insufficient for promotion."""

    def __init__(self, message: str, *, report: "ParityReport") -> None:
        super().__init__(message, code="PROMOTION_BLOCKED")
        self.report = report


class ExternalBackend(str, Enum):
    """External vector adapters retained during shadow mode."""

    FAISS = "faiss"
    QDRANT = "qdrant"
    ELASTICSEARCH = "elasticsearch"


class ShadowMode(str, Enum):
    """Shadow dual-path operating mode."""

    # Dual-read only: external remains primary for caller-visible results.
    DUAL_READ = "dual_read"
    # Dual-read + dual-write: mutations fan out with an idempotency key.
    DUAL_WRITE = "dual_write"
    # Promotion candidate: DuckDB exact is authoritative when parity passes.
    PROMOTED = "promoted"


@dataclass(frozen=True)
class ImportReject:
    """One rejected vector with a stable reason code."""

    vector_id: str
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {"vector_id": self.vector_id, "reason": self.reason}


@dataclass
class MigrationReport:
    """Evidence for one imported generation.

    Authority after cutover lives in DuckDB exact tables. This report is
    operator evidence: source digest, reject list, quarantine list, and
    generation binding. It is never pickle authority.
    """

    source_digest: str
    imported_count: int
    rejected: list[ImportReject] = field(default_factory=list)
    quarantined_duplicates: list[str] = field(default_factory=list)
    generation_id: int = 1
    collection_id: str = ""
    dimension: int = 0
    mapping_validated: bool = False
    quarantine_reasons: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": DUCKDB_VECTOR_MIGRATION_SCHEMA,
            "source_digest": self.source_digest,
            "imported_count": self.imported_count,
            "rejected": [r.to_dict() for r in self.rejected],
            "quarantined_duplicates": list(self.quarantined_duplicates),
            "quarantine_reasons": dict(self.quarantine_reasons),
            "generation_id": self.generation_id,
            "collection_id": self.collection_id,
            "dimension": self.dimension,
            "mapping_validated": self.mapping_validated,
            # Import reports are evidence; DuckDB is authority after import.
            "authority": "duckdb",
            "pickle_authority": False,
        }


@dataclass(frozen=True)
class ParityReport:
    """External backend ranking parity versus DuckDB exact search."""

    backend: ExternalBackend
    matched: int
    total: int
    promotion_allowed: bool
    exact_ids: tuple[str, ...] = ()
    external_ids: tuple[str, ...] = ()
    min_ratio: float = DEFAULT_PARITY_MIN_RATIO

    @property
    def ratio(self) -> float:
        return self.matched / self.total if self.total else 1.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": DUCKDB_VECTOR_MIGRATION_SCHEMA,
            "backend": self.backend.value,
            "matched": self.matched,
            "total": self.total,
            "ratio": self.ratio,
            "min_ratio": self.min_ratio,
            "promotion_allowed": self.promotion_allowed,
            "exact_ids": list(self.exact_ids),
            "external_ids": list(self.external_ids),
        }


@dataclass(frozen=True)
class ShadowDualResult:
    """Outcome of one dual-read or dual-write operation in shadow mode."""

    mode: ShadowMode
    backend: ExternalBackend
    primary_ids: tuple[str, ...]
    candidate_ids: tuple[str, ...]
    matched: bool
    caller_ids: tuple[str, ...]
    dual_write_applied: bool = False
    idempotency_key: str = ""
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": DUCKDB_VECTOR_MIGRATION_SCHEMA,
            "mode": self.mode.value,
            "backend": self.backend.value,
            "primary_ids": list(self.primary_ids),
            "candidate_ids": list(self.candidate_ids),
            "matched": self.matched,
            "caller_ids": list(self.caller_ids),
            "dual_write_applied": self.dual_write_applied,
            "idempotency_key": self.idempotency_key,
            "error": self.error,
        }


class _ExternalSearchBackend(Protocol):
    """Minimal protocol for FAISS / Qdrant / Elasticsearch search adapters."""

    def search(
        self,
        collection_id: str,
        query: Sequence[float],
        *,
        k: int = 10,
    ) -> Sequence[str]:
        """Return ordered hit vector ids (best first)."""
        ...


class _ExternalWriteBackend(Protocol):
    """Minimal protocol for external upsert during dual-write."""

    def upsert(
        self,
        collection_id: str,
        vector_id: str,
        values: Sequence[float],
        *,
        metadata: Mapping[str, Any] | None = None,
    ) -> None: ...


def _digest_bytes(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _is_numeric_sequence(values: Any) -> bool:
    return isinstance(values, Sequence) and not isinstance(
        values, (str, bytes, bytearray)
    )


def _as_float_list(values: Sequence[Any]) -> list[float] | None:
    out: list[float] = []
    for item in values:
        try:
            f = float(item)
        except (TypeError, ValueError):
            return None
        if not math.isfinite(f):
            return None
        out.append(f)
    return out


def _normalize_vector_id(vector_id: Any) -> str | None:
    if vector_id is None:
        return None
    # Integer FAISS indices are accepted as decimal strings.
    if isinstance(vector_id, bool):
        return None
    if isinstance(vector_id, int):
        return str(vector_id)
    if isinstance(vector_id, str):
        vid = vector_id.strip()
        return vid or None
    return str(vector_id)


def _extract_vector_entry(entry: Any) -> tuple[Any, dict[str, Any]]:
    """Return (raw_values, metadata) from a pickle entry."""

    if isinstance(entry, Mapping):
        values = entry.get("vector")
        if values is None:
            values = entry.get("values")
        if values is None:
            values = entry.get("embedding")
        meta_raw = entry.get("metadata")
        meta: dict[str, Any]
        if isinstance(meta_raw, Mapping):
            meta = dict(meta_raw)
        else:
            meta = {}
        # Preserve non-vector scalar fields as metadata when useful.
        for key in ("content", "chunk_id", "model_name"):
            if key in entry and key not in meta:
                meta[key] = entry[key]
        return values, meta
    return entry, {}


def _validate_id_mappings(
    id_mapping: Mapping[Any, Any] | None,
    reverse_id_mapping: Mapping[Any, Any] | None,
) -> list[ImportReject]:
    """Validate FAISS string↔integer id mappings for consistency."""

    rejects: list[ImportReject] = []
    if id_mapping is None and reverse_id_mapping is None:
        return rejects
    forward = dict(id_mapping or {})
    reverse = dict(reverse_id_mapping or {})

    for point_id, faiss_id in forward.items():
        vid = _normalize_vector_id(point_id)
        if vid is None:
            rejects.append(ImportReject(str(point_id), REASON_INVALID_ID))
            continue
        rev = reverse.get(faiss_id)
        if rev is None:
            # Also try string-keyed reverse maps.
            rev = reverse.get(str(faiss_id))
        if rev is None:
            rejects.append(ImportReject(vid, REASON_MAPPING_INCONSISTENT))
            continue
        if _normalize_vector_id(rev) != vid:
            rejects.append(ImportReject(vid, REASON_MAPPING_INCONSISTENT))
    # Reverse without forward is also inconsistent.
    for faiss_id, point_id in reverse.items():
        vid = _normalize_vector_id(point_id)
        if vid is None:
            rejects.append(
                ImportReject(str(point_id), REASON_MAPPING_INCONSISTENT)
            )
            continue
        if vid not in {_normalize_vector_id(k) for k in forward.keys()}:
            # Only flag when forward was provided and non-empty.
            if forward:
                rejects.append(ImportReject(vid, REASON_MAPPING_INCONSISTENT))
    return rejects


def _iter_payload_vectors(
    payload: Mapping[str, Any],
) -> tuple[Any, bool]:
    """Locate the vectors mapping inside a pickle payload.

    Supports:
    * ``{"vectors": {id: values|entry}}``
    * ``{"items": {id: values|entry}}``
    * FAISS metadata: ``{"metadata": {...}, "id_mapping": ..., ...}`` with
      optional parallel ``vectors`` / ``embeddings`` map
    * bare ``{id: values}`` root mapping
    """

    if "vectors" in payload and isinstance(payload["vectors"], Mapping):
        return payload["vectors"], True
    if "items" in payload and isinstance(payload["items"], Mapping):
        return payload["items"], True
    if "embeddings" in payload and isinstance(payload["embeddings"], Mapping):
        return payload["embeddings"], True
    # FAISS on-disk metadata without inline vectors cannot be materialised.
    if "metadata" in payload and isinstance(payload["metadata"], Mapping):
        # Prefer an accompanying vectors map when present.
        for key in ("vectors", "embeddings", "vector_data"):
            if key in payload and isinstance(payload[key], Mapping):
                return payload[key], True
        # Metadata-only: treat entries that embed vectors as candidates.
        return payload["metadata"], True
    # Bare id → vector map (no reserved keys).
    reserved = {
        "id_mapping",
        "reverse_id_mapping",
        "collection",
        "dimension",
        "schema",
    }
    if payload and not (set(payload.keys()) <= reserved):
        return payload, True
    return None, False


def _lookup_existing_digest(
    store: ExactVectorStore,
    collection_id: str,
    vector_id: str,
) -> str | None:
    """Return the live content digest for ``vector_id``, if present.

    Uses package-internal ExactVectorStore state so re-import can quarantine
    stale duplicates without adding a public get API on the exact store.
    """

    try:
        lock = getattr(store, "_lock", None)
        if lock is not None:
            lock.acquire()
        try:
            dim_gen = store._collection_dim(collection_id)  # type: ignore[attr-defined]
            dim = int(dim_gen[0])
            table = store._ensure_table(dim)  # type: ignore[attr-defined]
            row = store._conn.execute(  # type: ignore[attr-defined]
                f"""
                SELECT content_digest FROM {table}
                WHERE vector_id = ? AND collection_id = ?
                """,
                [vector_id, collection_id],
            ).fetchone()
            if row is None:
                return None
            return str(row[0])
        finally:
            if lock is not None:
                lock.release()
    except Exception:
        return None


def import_faiss_pickle_metadata(
    pickle_path: Path | str,
    store: ExactVectorStore,
    *,
    collection_id: str,
    dimension: int,
    allow_unpickle: bool = False,
    generation_id: int = 1,
    quarantine_existing: bool = True,
) -> MigrationReport:
    """Isolated one-time FAISS metadata import.

    Parameters
    ----------
    allow_unpickle:
        Must be ``True``. Default ``False`` enforces the acceptance rule
        that normal runtime never unpickles.
    generation_id:
        Bound into the collection and recorded on the reject report.
    quarantine_existing:
        When ``True`` (default), vector ids already present in the store
        are quarantined rather than overwritten (stale duplicates).
    """

    if not allow_unpickle:
        raise VectorMigrationError(
            "normal runtime never unpickles; pass allow_unpickle=True "
            "only for the one-time migration path",
            code="UNPICKLE_FORBIDDEN",
        )
    if not isinstance(generation_id, int) or isinstance(generation_id, bool):
        raise VectorMigrationError(
            "generation_id must be int", code="GENERATION"
        )
    if generation_id < 1:
        raise VectorMigrationError(
            "generation_id must be >= 1", code="GENERATION"
        )
    if not isinstance(dimension, int) or isinstance(dimension, bool) or dimension < 1:
        raise VectorMigrationError(
            "dimension must be a positive int", code="DIM"
        )

    path = Path(pickle_path)
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise VectorMigrationError(
            f"cannot read pickle path: {exc}", code="IO"
        ) from exc

    source_digest = _digest_bytes(raw)

    # Pickle is confined to this block; no other code path in this module
    # unpickles, and callers must pass allow_unpickle=True to reach here.
    try:
        payload = pickle.loads(raw)  # noqa: S301 — explicit migration path only
    except Exception as exc:
        raise VectorMigrationError(
            f"pickle load failed: {exc}", code="PICKLE_LOAD"
        ) from exc

    if not isinstance(payload, Mapping):
        raise VectorMigrationError(
            "pickle root must be a mapping", code="PICKLE_SHAPE"
        )

    mapping_rejects = _validate_id_mappings(
        payload.get("id_mapping") if isinstance(payload.get("id_mapping"), Mapping) else None,
        payload.get("reverse_id_mapping")
        if isinstance(payload.get("reverse_id_mapping"), Mapping)
        else None,
    )
    mapping_validated = (
        isinstance(payload.get("id_mapping"), Mapping)
        or isinstance(payload.get("reverse_id_mapping"), Mapping)
    )

    items, found = _iter_payload_vectors(payload)
    if not found or not isinstance(items, Mapping):
        raise VectorMigrationError(
            "pickle payload missing vectors mapping", code="PICKLE_SHAPE"
        )

    store.create_collection(
        collection_id, dimension=dimension, generation_id=generation_id
    )
    # Bind generation so search and report share the same published gen.
    try:
        store.set_generation(collection_id, generation_id)
    except ExactVectorStoreError:
        # Collection already at this generation or store without set_generation.
        pass

    seen_ids: set[str] = set()
    seen_digests: dict[str, str] = {}  # content_digest → first vector_id
    rejected: list[ImportReject] = list(mapping_rejects)
    # Mapping rejects do not block vector import of unrelated ids, but the
    # inconsistent ids themselves should not be trusted as sole authority.
    mapping_bad_ids = {r.vector_id for r in mapping_rejects}
    quarantined: list[str] = []
    quarantine_reasons: dict[str, str] = {}
    imported = 0

    for vector_id, entry in items.items():
        vid = _normalize_vector_id(vector_id)
        if vid is None:
            rejected.append(ImportReject(str(vector_id), REASON_INVALID_ID))
            continue

        if vid in seen_ids:
            quarantined.append(vid)
            quarantine_reasons[vid] = REASON_BATCH_DUPLICATE
            continue
        seen_ids.add(vid)

        raw_values, metadata = _extract_vector_entry(entry)
        if not _is_numeric_sequence(raw_values):
            rejected.append(ImportReject(vid, REASON_VALUES_MISSING))
            continue
        floats = _as_float_list(raw_values)
        if floats is None:
            rejected.append(ImportReject(vid, REASON_NON_FINITE))
            continue
        if len(floats) != dimension:
            rejected.append(ImportReject(vid, REASON_DIM_MISMATCH))
            continue

        digest = vector_digest(floats)

        # Content-identical under a different id → quarantine as duplicate.
        prior_id = seen_digests.get(digest)
        if prior_id is not None and prior_id != vid:
            quarantined.append(vid)
            quarantine_reasons[vid] = REASON_CONTENT_DUPLICATE
            continue

        if quarantine_existing:
            existing = _lookup_existing_digest(store, collection_id, vid)
            if existing is not None:
                # Same id already live — treat as stale duplicate whether or
                # not the content digest matches (idempotent re-import still
                # quarantines rather than re-authorising pickle bytes).
                quarantined.append(vid)
                quarantine_reasons[vid] = REASON_STALE_DUPLICATE
                continue

        # Mapping-inconsistent ids still import when vectors validate, but the
        # reject report retains the mapping failure for operator review.
        _ = mapping_bad_ids  # retained for future hard-fail policy hooks

        try:
            store.upsert_vector(
                collection_id,
                vid,
                floats,
                metadata=metadata or None,
            )
            imported += 1
            seen_digests[digest] = vid
        except ExactVectorStoreError as exc:
            rejected.append(ImportReject(vid, str(exc)))
        except Exception as exc:  # pragma: no cover — defensive
            rejected.append(ImportReject(vid, str(exc)))

    return MigrationReport(
        source_digest=source_digest,
        imported_count=imported,
        rejected=rejected,
        quarantined_duplicates=quarantined,
        generation_id=generation_id,
        collection_id=collection_id,
        dimension=dimension,
        mapping_validated=mapping_validated,
        quarantine_reasons=quarantine_reasons,
    )


def measure_external_parity(
    store: ExactVectorStore,
    *,
    collection_id: str,
    query: Sequence[float],
    external_hits: Sequence[str],
    backend: ExternalBackend,
    k: int = 10,
    min_ratio: float = DEFAULT_PARITY_MIN_RATIO,
) -> ParityReport:
    """Compare exact DuckDB ranking with an external backend hit list.

    Promotion is allowed only when the intersection ratio of top-``k`` ids
    meets ``min_ratio``. Call this for each retained backend before promotion.
    """

    if backend not in ExternalBackend:
        raise VectorMigrationError(
            f"unknown backend {backend!r}", code="BACKEND"
        )
    if not isinstance(k, int) or isinstance(k, bool) or k < 1:
        raise VectorMigrationError("k must be >= 1", code="K")
    if not 0.0 <= float(min_ratio) <= 1.0:
        raise VectorMigrationError(
            "min_ratio must be in [0, 1]", code="RATIO"
        )

    exact = store.search(collection_id, query, k=k)
    exact_ids = tuple(h.vector_id for h in exact)
    ext = tuple(str(x) for x in list(external_hits)[:k])
    if not exact_ids and not ext:
        return ParityReport(
            backend=backend,
            matched=0,
            total=0,
            promotion_allowed=True,
            exact_ids=exact_ids,
            external_ids=ext,
            min_ratio=float(min_ratio),
        )
    matched = len(set(exact_ids) & set(ext))
    total = max(len(exact_ids), len(ext), 1)
    ratio = matched / total
    return ParityReport(
        backend=backend,
        matched=matched,
        total=total,
        promotion_allowed=ratio >= float(min_ratio),
        exact_ids=exact_ids,
        external_ids=ext,
        min_ratio=float(min_ratio),
    )


def require_parity_for_promotion(
    reports: Sequence[ParityReport],
) -> list[ParityReport]:
    """Fail closed unless every backend report allows promotion."""

    reports = list(reports)
    if not reports:
        raise VectorMigrationError(
            "promotion requires at least one external parity report",
            code="PROMOTION_BLOCKED",
        )
    for report in reports:
        if not report.promotion_allowed:
            raise PromotionBlockedError(
                f"external backend parity insufficient for promotion: "
                f"{report.backend.value} ratio={report.ratio:.4f} "
                f"< {report.min_ratio}",
                report=report,
            )
    return reports


class VectorShadowAdapter:
    """Dual-read / dual-write FAISS, Qdrant, and Elasticsearch in shadow mode.

    * **Dual-read** — query the external (primary/legacy) backend and DuckDB
      exact (candidate) for the same request; the caller always receives the
      external ordering while shadow mode is active.
    * **Dual-write** — opt-in mutations fan out to DuckDB and the external
      backend under a non-empty idempotency key.
    * **Promotion** — requires measured parity on every retained backend via
      :func:`require_parity_for_promotion`.
    """

    def __init__(
        self,
        store: ExactVectorStore,
        *,
        collection_id: str,
        mode: ShadowMode = ShadowMode.DUAL_READ,
        allow_dual_write: bool = False,
        min_ratio: float = DEFAULT_PARITY_MIN_RATIO,
    ) -> None:
        self._store = store
        self._collection_id = collection_id
        self._mode = mode
        self._allow_dual_write = bool(allow_dual_write)
        self._min_ratio = float(min_ratio)
        self._lock = threading.RLock()
        self._searchers: dict[ExternalBackend, Callable[..., Sequence[str]]] = {}
        self._writers: dict[ExternalBackend, Callable[..., None]] = {}
        self._parity_samples: list[ParityReport] = []
        self._idempotency_seen: set[str] = set()

    @property
    def mode(self) -> ShadowMode:
        return self._mode

    @property
    def allow_dual_write(self) -> bool:
        return self._allow_dual_write

    def register_backend(
        self,
        backend: ExternalBackend,
        *,
        search: Callable[..., Sequence[str]] | None = None,
        upsert: Callable[..., None] | None = None,
    ) -> None:
        """Register FAISS / Qdrant / Elasticsearch callables for shadow mode."""

        if backend not in ExternalBackend:
            raise VectorMigrationError(
                f"unknown backend {backend!r}", code="BACKEND"
            )
        with self._lock:
            if search is not None:
                self._searchers[backend] = search
            if upsert is not None:
                self._writers[backend] = upsert

    def dual_read(
        self,
        query: Sequence[float],
        *,
        backend: ExternalBackend,
        k: int = 10,
    ) -> ShadowDualResult:
        """Dual-read: external primary ordering, DuckDB candidate comparison."""

        with self._lock:
            searcher = self._searchers.get(backend)
            if searcher is None:
                raise VectorMigrationError(
                    f"no search adapter registered for {backend.value}",
                    code="BACKEND",
                )
            try:
                external_ids = tuple(
                    str(x)
                    for x in searcher(
                        self._collection_id, query, k=k
                    )
                )[:k]
            except TypeError:
                # Allow simpler signatures: search(query, k=...).
                external_ids = tuple(
                    str(x) for x in searcher(query, k=k)  # type: ignore[call-arg]
                )[:k]
            except Exception as exc:
                return ShadowDualResult(
                    mode=self._mode,
                    backend=backend,
                    primary_ids=(),
                    candidate_ids=(),
                    matched=False,
                    caller_ids=(),
                    error=str(exc),
                )

            candidate = self._store.search(self._collection_id, query, k=k)
            candidate_ids = tuple(h.vector_id for h in candidate)
            matched = set(external_ids) == set(candidate_ids) and list(
                external_ids
            ) == list(candidate_ids)
            # Soft match for ranking parity samples: set intersection ratio.
            report = measure_external_parity(
                self._store,
                collection_id=self._collection_id,
                query=query,
                external_hits=external_ids,
                backend=backend,
                k=k,
                min_ratio=self._min_ratio,
            )
            self._parity_samples.append(report)

            if self._mode is ShadowMode.PROMOTED:
                caller = candidate_ids
            else:
                # Shadow: external remains caller-visible primary.
                caller = external_ids

            return ShadowDualResult(
                mode=self._mode,
                backend=backend,
                primary_ids=external_ids,
                candidate_ids=candidate_ids,
                matched=matched or report.promotion_allowed,
                caller_ids=caller,
            )

    def dual_write(
        self,
        vector_id: str,
        values: Sequence[float],
        *,
        backend: ExternalBackend,
        idempotency_key: str,
        metadata: Mapping[str, Any] | None = None,
    ) -> ShadowDualResult:
        """Dual-write DuckDB exact + external backend (opt-in)."""

        if not self._allow_dual_write and self._mode is not ShadowMode.DUAL_WRITE:
            raise VectorMigrationError(
                "dual-write requires allow_dual_write=True or mode=dual_write",
                code="DUAL_WRITE_DISABLED",
            )
        if not self._allow_dual_write:
            raise VectorMigrationError(
                "dual-write requires explicit allow_dual_write=True",
                code="DUAL_WRITE_DISABLED",
            )
        key = str(idempotency_key or "").strip()
        if not key:
            raise VectorMigrationError(
                "dual-write requires a non-empty idempotency_key",
                code="IDEMPOTENCY_REQUIRED",
            )

        with self._lock:
            if key in self._idempotency_seen:
                # Idempotent no-op: still report current dual state.
                return ShadowDualResult(
                    mode=self._mode,
                    backend=backend,
                    primary_ids=(vector_id,),
                    candidate_ids=(vector_id,),
                    matched=True,
                    caller_ids=(vector_id,),
                    dual_write_applied=False,
                    idempotency_key=key,
                    error="idempotent_replay",
                )

            writer = self._writers.get(backend)
            # Primary (DuckDB candidate) write first for durable authority path.
            try:
                self._store.upsert_vector(
                    self._collection_id,
                    vector_id,
                    values,
                    metadata=metadata,
                )
            except Exception as exc:
                return ShadowDualResult(
                    mode=self._mode,
                    backend=backend,
                    primary_ids=(),
                    candidate_ids=(),
                    matched=False,
                    caller_ids=(),
                    dual_write_applied=False,
                    idempotency_key=key,
                    error=f"duckdb_write_failed: {exc}",
                )

            external_error = ""
            if writer is not None:
                try:
                    try:
                        writer(
                            self._collection_id,
                            vector_id,
                            values,
                            metadata=metadata,
                        )
                    except TypeError:
                        writer(vector_id, values)  # type: ignore[call-arg]
                except Exception as exc:
                    external_error = str(exc)
            else:
                external_error = f"no write adapter registered for {backend.value}"

            self._idempotency_seen.add(key)
            ok = not external_error
            return ShadowDualResult(
                mode=self._mode,
                backend=backend,
                primary_ids=(vector_id,),
                candidate_ids=(vector_id,),
                matched=ok,
                caller_ids=(vector_id,),
                dual_write_applied=ok,
                idempotency_key=key,
                error=external_error,
            )

    def measure_all_backends(
        self,
        query: Sequence[float],
        *,
        external_hits: Mapping[ExternalBackend, Sequence[str]],
        k: int = 10,
    ) -> list[ParityReport]:
        """Measure parity for every retained external backend before promotion."""

        reports: list[ParityReport] = []
        for backend, hits in external_hits.items():
            reports.append(
                measure_external_parity(
                    self._store,
                    collection_id=self._collection_id,
                    query=query,
                    external_hits=hits,
                    backend=backend,
                    k=k,
                    min_ratio=self._min_ratio,
                )
            )
        with self._lock:
            self._parity_samples.extend(reports)
        return reports

    def promote_if_parity(
        self,
        reports: Sequence[ParityReport] | None = None,
    ) -> ShadowMode:
        """Promote DuckDB exact only when every parity report allows it."""

        with self._lock:
            use = list(reports) if reports is not None else list(self._parity_samples)
            # Keep only the latest report per backend when using samples.
            if reports is None and use:
                latest: dict[ExternalBackend, ParityReport] = {}
                for r in use:
                    latest[r.backend] = r
                use = list(latest.values())
            require_parity_for_promotion(use)
            self._mode = ShadowMode.PROMOTED
            return self._mode

    def parity_samples(self) -> list[ParityReport]:
        with self._lock:
            return list(self._parity_samples)
