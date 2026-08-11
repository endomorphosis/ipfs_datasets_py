"""Parallel DuckLake subplan execution via the trusted query broker (DQK-092).

Integrates snapshot-bound lake subplans with
:mod:`ipfs_datasets_py.duckdb_control.parallel_query` so independent catalog
shards execute concurrently against distinct Quack endpoints under per-catalog
connection, row, byte, memory, time, spill, and cancellation budgets while
control-plane capacity remains reserved for supervisor heartbeats.

Same-shard catalog mutations remain serialized by that shard's single owner
mutex. Each worker acquires a DQK-090 authoritative reader lease *before*
opening the remote Quack attachment, renews it throughout scan and result
materialization, and releases it only after connections and file readers
close. Cancellation closes readers before release; crash recovery relies on
bounded lease expiry (PID reuse, owner failover, and generation-fence changes
fail closed and never leave a renewable stale lease).

Acceptance (DQK-092)
--------------------
* Independent shard scans overlap without sharing mutable connections while
  same-shard mutations are serialized
* Every worker acquires, renews, and releases an authoritative DQK-090 lease
  around the complete lifetime of its remote Quack attachment, scan, and
  result materialization
* Lease evidence binds process birth identity, endpoint owner generation, and
  task/run/generation fences; cancellation closes readers before release while
  crash recovery relies on bounded expiry
* Deadlines and cancellation propagate to every worker
* A slow or failed catalog owner cannot starve supervisor heartbeats or
  unrelated shards
* Receipts bind plan, snapshot vector, Quack endpoint/owner identity,
  reader-lease identity, resource use, result digest, and partial-failure
  policy

Import is side-effect free: no DuckDB, network, or filesystem authority.
Integration tests inject hermetic Quack endpoint doubles and in-memory lease
authority.
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import (
    Any,
    Callable,
    Final,
    Mapping,
    Protocol,
    Sequence,
)

from ipfs_datasets_py.duckdb_control import parallel_query as pq
from ipfs_datasets_py.duckdb_control.contracts import content_identity
from ipfs_datasets_py.duckdb_control.query_registry import (
    CancellationToken,
    QueryBudgetExceeded,
    QueryCancelled,
)
from ipfs_datasets_py.ducklake.config import ProcessBirthBinding
from ipfs_datasets_py.ducklake.snapshots import (
    AuthoritativeSnapshotDatabase,
    LeaseStatus,
    ReaderLease,
    ReaderLeaseError,
    SnapshotVector,
    SnapshotVectorMember,
    build_remote_worker_attach,
)

__all__ = [
    "LAKE_EXECUTION_SCHEMA",
    "LAKE_EXECUTION_RECEIPT_SCHEMA",
    "LAKE_WORKER_EVIDENCE_SCHEMA",
    "LAKE_EXECUTION_IMPLEMENTATION_GENERATION",
    "CatalogOwnerMutationGate",
    "IsolatedQuackAttachment",
    "LakeCatalogBudget",
    "LakeExecutionError",
    "LakeExecutionPlan",
    "LakeExecutionReceipt",
    "LakeExecutionResult",
    "LakeExecutionStatus",
    "LakeParallelExecutor",
    "LakeQuackEndpoint",
    "LakeShardSubplan",
    "LakeWorkerEvidence",
    "LeaseLifecycle",
    "MutationKind",
    "open_default_lake_executor",
]


# ---------------------------------------------------------------------------
# Schema pins / defaults
# ---------------------------------------------------------------------------

LAKE_EXECUTION_SCHEMA: Final[str] = (
    "ipfs_datasets_py/ducklake-parallel-execution@1"
)
LAKE_EXECUTION_RECEIPT_SCHEMA: Final[str] = (
    "ipfs_datasets_py/ducklake-parallel-execution-receipt@1"
)
LAKE_WORKER_EVIDENCE_SCHEMA: Final[str] = (
    "ipfs_datasets_py/ducklake-parallel-worker-evidence@1"
)
LAKE_EXECUTION_IMPLEMENTATION_GENERATION: Final[str] = (
    "dqk-092-lake-parallel-execution-20260810"
)

_DEFAULT_LEASE_TTL_SECONDS: Final[int] = 60
_DEFAULT_RENEW_INTERVAL_MS: Final[int] = 25
_DOMAIN_CYCLE: Final[tuple[pq.SubqueryDomain, ...]] = tuple(pq.SubqueryDomain)


# ---------------------------------------------------------------------------
# Errors / enums
# ---------------------------------------------------------------------------


class LakeExecutionError(ValueError):
    """Fail-closed rejection of a lake parallel plan, budget, or lease path."""

    def __init__(self, code: str, message: str, **details: Any) -> None:
        super().__init__(f"{code}: {message}")
        self.code = str(code)
        self.details = dict(details)


class LakeExecutionStatus(str, Enum):
    SUCCEEDED = "succeeded"
    PARTIAL = "partial"
    TRUNCATED = "truncated"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMEOUT = "timeout"


class MutationKind(str, Enum):
    """Catalog-owner mutation kinds that must serialize per shard."""

    INGEST = "ingest"
    SCHEMA_EVOLVE = "schema_evolve"
    COMPACT = "compact"
    SNAPSHOT_EXPIRE = "snapshot_expire"
    MAINTENANCE = "maintenance"


# ---------------------------------------------------------------------------
# Budgets / mutation serialization
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class LakeCatalogBudget:
    """Per-catalog resource caps for one lake shard worker."""

    max_connections: int = 1
    max_rows: int = pq.DEFAULT_MAX_ROWS_PER_SUBQUERY
    max_bytes: int = pq.DEFAULT_MAX_BYTES
    max_memory_bytes: int = pq.DEFAULT_MAX_MEMORY_BYTES
    max_duration_ms: int = pq.DEFAULT_MAX_DURATION_MS
    max_spill_bytes: int = pq.DEFAULT_MAX_SPILL_BYTES
    lease_ttl_seconds: int = _DEFAULT_LEASE_TTL_SECONDS
    renew_interval_ms: int = _DEFAULT_RENEW_INTERVAL_MS

    def __post_init__(self) -> None:
        bounds = (
            ("max_connections", self.max_connections, 1, pq.MAX_CONNECTIONS_PER_CATALOG_HARD),
            ("max_rows", self.max_rows, 1, pq.MAX_ROWS_HARD),
            ("max_bytes", self.max_bytes, 1, pq.MAX_BYTES_HARD),
            ("max_memory_bytes", self.max_memory_bytes, 1, pq.MAX_MEMORY_HARD),
            ("max_duration_ms", self.max_duration_ms, 1, pq.MAX_DURATION_MS_HARD),
            ("max_spill_bytes", self.max_spill_bytes, 0, pq.MAX_SPILL_HARD),
            ("lease_ttl_seconds", self.lease_ttl_seconds, 1, 86_400),
            ("renew_interval_ms", self.renew_interval_ms, 1, 60_000),
        )
        for name, value, lo, hi in bounds:
            if (
                not isinstance(value, int)
                or isinstance(value, bool)
                or value < lo
                or value > hi
            ):
                raise LakeExecutionError(
                    "BUDGET",
                    f"{name} must be an int in [{lo}, {hi}], got {value!r}",
                )

    def to_dict(self) -> dict[str, Any]:
        return {
            "max_connections": self.max_connections,
            "max_rows": self.max_rows,
            "max_bytes": self.max_bytes,
            "max_memory_bytes": self.max_memory_bytes,
            "max_duration_ms": self.max_duration_ms,
            "max_spill_bytes": self.max_spill_bytes,
            "lease_ttl_seconds": self.lease_ttl_seconds,
            "renew_interval_ms": self.renew_interval_ms,
        }

    def to_parallel_budget(
        self,
        *,
        max_workers: int,
        reserved_control_plane_ms: int = pq.DEFAULT_RESERVED_CONTROL_PLANE_MS,
        reserved_control_plane_slots: int = pq.DEFAULT_RESERVED_CONTROL_PLANE_SLOTS,
        total_slots: int | None = None,
        heartbeat_interval_ms: int = pq.DEFAULT_HEARTBEAT_INTERVAL_MS,
        heartbeat_p99_slo_ms: float = pq.DEFAULT_HEARTBEAT_P99_SLO_MS,
        max_total_rows: int | None = None,
    ) -> pq.ParallelQueryBudget:
        slots = total_slots
        if slots is None:
            # Ensure analytical slots >= max_workers and control-plane reserved.
            slots = max(max_workers + reserved_control_plane_slots, pq.DEFAULT_TOTAL_SLOTS)
        return pq.ParallelQueryBudget(
            max_workers=max_workers,
            max_duration_ms=self.max_duration_ms,
            max_rows_per_subquery=self.max_rows,
            max_total_rows=max_total_rows or max(self.max_rows * max_workers, self.max_rows),
            max_bytes=self.max_bytes,
            max_memory_bytes=self.max_memory_bytes,
            max_spill_bytes=self.max_spill_bytes,
            max_connections_per_catalog=self.max_connections,
            reserved_control_plane_ms=reserved_control_plane_ms,
            reserved_control_plane_slots=reserved_control_plane_slots,
            total_slots=slots,
            heartbeat_interval_ms=heartbeat_interval_ms,
            heartbeat_p99_slo_ms=heartbeat_p99_slo_ms,
        )


class CatalogOwnerMutationGate:
    """Serializes same-shard catalog mutations via a single owner lock.

    Independent catalog shards hold independent mutexes so unrelated owners
    never contend. Scan workers do *not* take this lock; they use the parallel
    query broker's per-catalog connection pool instead.
    """

    def __init__(self) -> None:
        self._locks: dict[str, threading.RLock] = {}
        self._meta: dict[str, dict[str, Any]] = {}
        self._guard = threading.Lock()
        self._history: list[dict[str, Any]] = []

    def _lock_for(self, catalog_id: str) -> threading.RLock:
        cid = str(catalog_id or "").strip()
        if not cid:
            raise LakeExecutionError("MUTATION", "catalog_id is required")
        with self._guard:
            lock = self._locks.get(cid)
            if lock is None:
                lock = threading.RLock()
                self._locks[cid] = lock
                self._meta[cid] = {
                    "active": False,
                    "holder": "",
                    "kind": "",
                    "started_monotonic": 0.0,
                    "serialized_count": 0,
                }
            return lock

    def mutate(
        self,
        catalog_id: str,
        kind: MutationKind | str,
        operation: Callable[[], Any],
        *,
        holder: str = "",
        timeout: float | None = None,
    ) -> Any:
        """Run ``operation`` under exclusive ownership of ``catalog_id``."""

        lock = self._lock_for(catalog_id)
        mk = kind if isinstance(kind, MutationKind) else MutationKind(str(kind))
        acquired = lock.acquire(timeout=timeout if timeout is not None else -1)
        if not acquired:
            raise LakeExecutionError(
                "MUTATION",
                f"timed out acquiring owner mutation lock for {catalog_id!r}",
                catalog_id=catalog_id,
            )
        started = time.monotonic()
        try:
            with self._guard:
                meta = self._meta[catalog_id]
                if meta["active"]:
                    # RLock re-entry by same thread is allowed; record nesting.
                    meta["serialized_count"] += 1
                meta["active"] = True
                meta["holder"] = holder or threading.current_thread().name
                meta["kind"] = mk.value
                meta["started_monotonic"] = started
                meta["serialized_count"] = int(meta.get("serialized_count", 0)) + 1
            result = operation()
            finished = time.monotonic()
            with self._guard:
                self._history.append(
                    {
                        "catalog_id": catalog_id,
                        "kind": mk.value,
                        "holder": holder or threading.current_thread().name,
                        "started_monotonic": started,
                        "finished_monotonic": finished,
                        "duration_ms": max(0.0, (finished - started) * 1000.0),
                    }
                )
            return result
        finally:
            with self._guard:
                meta = self._meta[catalog_id]
                meta["active"] = False
                meta["holder"] = ""
                meta["kind"] = ""
            lock.release()

    def is_active(self, catalog_id: str) -> bool:
        with self._guard:
            meta = self._meta.get(str(catalog_id))
            return bool(meta and meta.get("active"))

    def history(self) -> tuple[Mapping[str, Any], ...]:
        with self._guard:
            return tuple(dict(h) for h in self._history)

    def snapshot(self) -> Mapping[str, Any]:
        with self._guard:
            return MappingProxyType(
                {
                    "catalogs": {
                        cid: dict(meta) for cid, meta in sorted(self._meta.items())
                    },
                    "history_count": len(self._history),
                }
            )


# ---------------------------------------------------------------------------
# Isolated Quack attachment + endpoint protocol
# ---------------------------------------------------------------------------


@dataclass
class IsolatedQuackAttachment:
    """Mutable remote Quack attachment owned by exactly one worker.

    Never shared across workers. ``close()`` is idempotent and must run before
    reader-lease release on both success and cancellation paths.
    """

    connection_id: str
    catalog_id: str
    quack_endpoint_identity: str
    owner_generation: int
    fencing_epoch: int
    snapshot_version: int
    opens_catalog_file: bool = False
    _closed: bool = field(default=False, repr=False)
    _reader_open: bool = field(default=False, repr=False)
    _bytes_read: int = field(default=0, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def __post_init__(self) -> None:
        if self.opens_catalog_file:
            raise LakeExecutionError(
                "ATTACH",
                "remote workers must not open catalog metadata files",
                catalog_id=self.catalog_id,
            )

    @property
    def closed(self) -> bool:
        with self._lock:
            return self._closed

    @property
    def reader_open(self) -> bool:
        with self._lock:
            return self._reader_open and not self._closed

    def open_reader(self) -> None:
        with self._lock:
            if self._closed:
                raise LakeExecutionError(
                    "ATTACH",
                    f"cannot open reader on closed attachment {self.connection_id}",
                )
            self._reader_open = True

    def scan_rows(
        self,
        rows: Sequence[Mapping[str, Any]],
        *,
        check: Callable[[], None] | None = None,
        hold_ms: float = 0.0,
    ) -> list[dict[str, Any]]:
        """Materialize rows while the exclusive attachment remains open."""

        with self._lock:
            if self._closed:
                raise LakeExecutionError(
                    "SCAN",
                    f"scan on closed attachment {self.connection_id}",
                )
            if not self._reader_open:
                self._reader_open = True
        out: list[dict[str, Any]] = []
        deadline = time.monotonic() + (max(0.0, float(hold_ms)) / 1000.0)
        for row in rows:
            if check is not None:
                check()
            payload = dict(row)
            payload.setdefault("catalog_id", self.catalog_id)
            payload.setdefault("connection_id", self.connection_id)
            out.append(payload)
            encoded = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
            with self._lock:
                self._bytes_read += len(encoded)
        # Hold the critical section so concurrent peers can overlap.
        while time.monotonic() < deadline:
            if check is not None:
                check()
            time.sleep(0.005)
        return out

    def close(self) -> None:
        with self._lock:
            self._reader_open = False
            self._closed = True

    def bytes_read(self) -> int:
        with self._lock:
            return self._bytes_read

    def as_mapping(self) -> Mapping[str, Any]:
        with self._lock:
            return MappingProxyType(
                {
                    "connection_id": self.connection_id,
                    "catalog_id": self.catalog_id,
                    "quack_endpoint_identity": self.quack_endpoint_identity,
                    "owner_generation": self.owner_generation,
                    "fencing_epoch": self.fencing_epoch,
                    "snapshot_version": self.snapshot_version,
                    "opens_catalog_file": False,
                    "closed": self._closed,
                    "reader_open": self._reader_open and not self._closed,
                    "bytes_read": self._bytes_read,
                }
            )


class LakeQuackEndpoint(Protocol):
    """Typed Quack endpoint for one catalog shard (never opens catalog files)."""

    catalog_id: str
    quack_endpoint_identity: str
    available: bool

    def open_attachment(
        self,
        *,
        connection_id: str,
        member: SnapshotVectorMember,
        lease: ReaderLease,
    ) -> IsolatedQuackAttachment:
        """Open a remote Quack attachment *after* lease acquire."""
        ...

    def scan(
        self,
        attachment: IsolatedQuackAttachment,
        subplan: "LakeShardSubplan",
        *,
        check: Callable[[], None] | None = None,
    ) -> Sequence[Mapping[str, Any]]:
        """Execute the shard-local scan through the exclusive attachment."""
        ...


# ---------------------------------------------------------------------------
# Plan / lease evidence
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class LakeShardSubplan:
    """One snapshot-bound subplan targeted at a single catalog-shard Quack endpoint."""

    subplan_id: str
    catalog_id: str
    shard_id: str
    quack_endpoint_identity: str
    owner_generation: int
    fencing_epoch: int
    snapshot_version: int
    vector_id: str
    dataset_id: str = ""
    canonical_sql: str = ""
    projected_columns: tuple[str, ...] = ()
    max_rows: int | None = None
    hold_ms: float = 0.0
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        sid = str(self.subplan_id or "").strip()
        if not sid:
            raise LakeExecutionError("PLAN", "subplan_id is required")
        object.__setattr__(self, "subplan_id", sid)
        cid = str(self.catalog_id or "").strip()
        if not cid:
            raise LakeExecutionError("PLAN", "catalog_id is required")
        object.__setattr__(self, "catalog_id", cid)
        object.__setattr__(self, "shard_id", str(self.shard_id or cid).strip())
        endpoint = str(self.quack_endpoint_identity or "").strip()
        if not endpoint:
            raise LakeExecutionError("PLAN", "quack_endpoint_identity is required")
        # Workers never ATTACH catalog files.
        lowered = endpoint.lower()
        if lowered.startswith("file:") or lowered.endswith(".duckdb"):
            raise LakeExecutionError(
                "ATTACH",
                "quack endpoint must not be a catalog metadata file path",
                endpoint=endpoint,
            )
        object.__setattr__(self, "quack_endpoint_identity", endpoint)
        for name, value in (
            ("owner_generation", self.owner_generation),
            ("fencing_epoch", self.fencing_epoch),
        ):
            if (
                not isinstance(value, int)
                or isinstance(value, bool)
                or value < 1
            ):
                raise LakeExecutionError("PLAN", f"{name} must be a positive int")
        if (
            not isinstance(self.snapshot_version, int)
            or isinstance(self.snapshot_version, bool)
            or self.snapshot_version < 0
        ):
            raise LakeExecutionError("PLAN", "snapshot_version must be a non-negative int")
        object.__setattr__(
            self, "vector_id", str(self.vector_id or "").strip() or "vector-unset"
        )
        object.__setattr__(self, "dataset_id", str(self.dataset_id or "").strip())
        cols = tuple(str(c) for c in (self.projected_columns or ()))
        object.__setattr__(self, "projected_columns", cols)
        if not self.canonical_sql:
            col_sql = ", ".join(cols) if cols else "*"
            object.__setattr__(
                self,
                "canonical_sql",
                (
                    f"SELECT {col_sql} FROM lake.{self.dataset_id or self.catalog_id} "
                    f"/* snapshot={self.snapshot_version} */"
                ),
            )
        object.__setattr__(
            self, "metadata", MappingProxyType(dict(self.metadata or {}))
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "subplan_id": self.subplan_id,
            "catalog_id": self.catalog_id,
            "shard_id": self.shard_id,
            "quack_endpoint_identity": self.quack_endpoint_identity,
            "owner_generation": self.owner_generation,
            "fencing_epoch": self.fencing_epoch,
            "snapshot_version": self.snapshot_version,
            "vector_id": self.vector_id,
            "dataset_id": self.dataset_id,
            "canonical_sql": self.canonical_sql,
            "projected_columns": list(self.projected_columns),
            "max_rows": self.max_rows,
            "hold_ms": self.hold_ms,
            "metadata": dict(self.metadata),
            "opens_catalog_file": False,
        }


@dataclass(frozen=True, slots=True)
class LakeExecutionPlan:
    """Bounded plan of independent lake shard subplans."""

    subplans: tuple[LakeShardSubplan, ...]
    snapshot_vector: SnapshotVector
    process_birth: ProcessBirthBinding
    task_id: str
    run_id: str = ""
    plan_id: str = ""
    catalog_budget: LakeCatalogBudget = field(default_factory=LakeCatalogBudget)
    partial_failure_policy: pq.PartialFailurePolicy = pq.PartialFailurePolicy.CONTINUE
    reserved_control_plane_ms: int = pq.DEFAULT_RESERVED_CONTROL_PLANE_MS
    reserved_control_plane_slots: int = pq.DEFAULT_RESERVED_CONTROL_PLANE_SLOTS
    total_slots: int | None = None
    heartbeat_interval_ms: int = pq.DEFAULT_HEARTBEAT_INTERVAL_MS
    heartbeat_p99_slo_ms: float = pq.DEFAULT_HEARTBEAT_P99_SLO_MS

    def __post_init__(self) -> None:
        if not self.subplans:
            raise LakeExecutionError("PLAN", "plan requires at least one subplan")
        if not isinstance(self.snapshot_vector, SnapshotVector):
            raise LakeExecutionError("PLAN", "snapshot_vector must be SnapshotVector")
        if not isinstance(self.process_birth, ProcessBirthBinding):
            raise LakeExecutionError(
                "PLAN", "process_birth must be ProcessBirthBinding"
            )
        task = str(self.task_id or "").strip()
        if not task:
            raise LakeExecutionError("PLAN", "task_id is required")
        object.__setattr__(self, "task_id", task)
        run = str(self.run_id or "").strip() or f"run-{uuid.uuid4().hex[:16]}"
        object.__setattr__(self, "run_id", run)
        plan = str(self.plan_id or "").strip() or f"lake-plan-{uuid.uuid4().hex[:16]}"
        object.__setattr__(self, "plan_id", plan)
        seen: set[str] = set()
        catalogs: set[str] = set()
        for sp in self.subplans:
            if not isinstance(sp, LakeShardSubplan):
                raise LakeExecutionError("PLAN", "subplans must be LakeShardSubplan")
            if sp.subplan_id in seen:
                raise LakeExecutionError(
                    "PLAN", f"duplicate subplan_id {sp.subplan_id!r}"
                )
            seen.add(sp.subplan_id)
            catalogs.add(sp.catalog_id)
            # Vector must cover the catalog; fence must match.
            try:
                member = self.snapshot_vector.member_for(sp.catalog_id)
            except Exception as exc:
                raise LakeExecutionError(
                    "PLAN",
                    f"snapshot vector missing catalog {sp.catalog_id!r}",
                ) from exc
            if member.owner_generation != sp.owner_generation:
                raise LakeExecutionError(
                    "PLAN",
                    f"owner_generation mismatch for {sp.catalog_id!r}",
                )
            if member.fencing_epoch != sp.fencing_epoch:
                raise LakeExecutionError(
                    "PLAN",
                    f"fencing_epoch mismatch for {sp.catalog_id!r}",
                )
            if member.catalog_global_snapshot_id != sp.snapshot_version:
                raise LakeExecutionError(
                    "PLAN",
                    f"snapshot_version mismatch for {sp.catalog_id!r}",
                )
            if member.quack_endpoint_identity != sp.quack_endpoint_identity:
                raise LakeExecutionError(
                    "PLAN",
                    f"quack endpoint mismatch for {sp.catalog_id!r}",
                )
            if sp.vector_id and sp.vector_id != self.snapshot_vector.vector_id:
                raise LakeExecutionError(
                    "PLAN",
                    f"vector_id mismatch for {sp.catalog_id!r}",
                )
        object.__setattr__(self, "subplans", tuple(self.subplans))
        if not isinstance(self.catalog_budget, LakeCatalogBudget):
            raise LakeExecutionError("PLAN", "catalog_budget must be LakeCatalogBudget")
        if not isinstance(self.partial_failure_policy, pq.PartialFailurePolicy):
            object.__setattr__(
                self,
                "partial_failure_policy",
                pq.PartialFailurePolicy(str(self.partial_failure_policy)),
            )

    @property
    def catalog_ids(self) -> frozenset[str]:
        return frozenset(sp.catalog_id for sp in self.subplans)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": LAKE_EXECUTION_SCHEMA,
            "plan_id": self.plan_id,
            "task_id": self.task_id,
            "run_id": self.run_id,
            "subplans": [sp.to_dict() for sp in self.subplans],
            "snapshot_vector_id": self.snapshot_vector.vector_id,
            "snapshot_vector_digest": self.snapshot_vector.identity_digest,
            "process_birth": dict(self.process_birth.as_mapping()),
            "catalog_budget": self.catalog_budget.to_dict(),
            "partial_failure_policy": self.partial_failure_policy.value,
            "catalog_ids": sorted(self.catalog_ids),
        }


@dataclass(frozen=True, slots=True)
class LeaseLifecycle:
    """Evidence that a worker acquired / renewed / released a DQK-090 lease."""

    lease_id: str
    lease_token_redacted: str
    catalog_id: str
    vector_id: str
    owner_generation: int
    fencing_epoch: int
    process_birth: Mapping[str, Any]
    task_id: str
    run_id: str
    worker_id: str
    acquired: bool
    renewed_count: int
    released: bool
    final_status: str
    readers_closed_before_release: bool
    acquired_at: str = ""
    released_at: str = ""
    expires_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "lease_id": self.lease_id,
            "lease_token": self.lease_token_redacted,
            "catalog_id": self.catalog_id,
            "vector_id": self.vector_id,
            "owner_generation": self.owner_generation,
            "fencing_epoch": self.fencing_epoch,
            "process_birth": dict(self.process_birth),
            "task_id": self.task_id,
            "run_id": self.run_id,
            "worker_id": self.worker_id,
            "acquired": self.acquired,
            "renewed_count": self.renewed_count,
            "released": self.released,
            "final_status": self.final_status,
            "readers_closed_before_release": self.readers_closed_before_release,
            "acquired_at": self.acquired_at,
            "released_at": self.released_at,
            "expires_at": self.expires_at,
        }


@dataclass(frozen=True, slots=True)
class LakeWorkerEvidence:
    """Per-worker lease, endpoint, connection, and resource evidence."""

    SCHEMA: str = LAKE_WORKER_EVIDENCE_SCHEMA
    subplan_id: str = ""
    catalog_id: str = ""
    shard_id: str = ""
    quack_endpoint_identity: str = ""
    owner_generation: int = 0
    fencing_epoch: int = 0
    snapshot_version: int = 0
    connection_id: str = ""
    lease: LeaseLifecycle | None = None
    resource_use: Mapping[str, Any] = field(default_factory=dict)
    opens_catalog_file: bool = False
    status: str = ""
    row_count: int = 0
    result_digest: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.SCHEMA,
            "subplan_id": self.subplan_id,
            "catalog_id": self.catalog_id,
            "shard_id": self.shard_id,
            "quack_endpoint_identity": self.quack_endpoint_identity,
            "owner_generation": self.owner_generation,
            "fencing_epoch": self.fencing_epoch,
            "snapshot_version": self.snapshot_version,
            "connection_id": self.connection_id,
            "lease": self.lease.to_dict() if self.lease is not None else None,
            "resource_use": dict(self.resource_use or {}),
            "opens_catalog_file": False,
            "status": self.status,
            "row_count": self.row_count,
            "result_digest": self.result_digest,
        }


@dataclass(frozen=True, slots=True)
class LakeExecutionReceipt:
    """Deterministic receipt binding plan, vector, leases, and resources."""

    schema: str
    plan_id: str
    run_id: str
    task_id: str
    snapshot_vector_id: str
    snapshot_vector_digest: str
    status: str
    partial_failure_policy: str
    worker_evidence: tuple[dict[str, Any], ...]
    resource_use: Mapping[str, Any]
    result_digest: str
    broker_receipt: Mapping[str, Any]
    process_birth: Mapping[str, Any]
    mutation_gate: Mapping[str, Any]
    duration_ms: float
    created_at: str
    implementation_generation: str = LAKE_EXECUTION_IMPLEMENTATION_GENERATION
    independent_shards_overlapped: bool = False
    no_shared_mutable_connections: bool = True
    control_plane_within_slo: bool = True

    @property
    def identity_id(self) -> str:
        payload = {
            "schema": self.schema,
            "plan_id": self.plan_id,
            "run_id": self.run_id,
            "task_id": self.task_id,
            "snapshot_vector_id": self.snapshot_vector_id,
            "snapshot_vector_digest": self.snapshot_vector_digest,
            "status": self.status,
            "partial_failure_policy": self.partial_failure_policy,
            "worker_evidence": list(self.worker_evidence),
            "resource_use": dict(self.resource_use),
            "result_digest": self.result_digest,
            "process_birth": dict(self.process_birth),
            "duration_ms": self.duration_ms,
            "created_at": self.created_at,
            "implementation_generation": self.implementation_generation,
            "independent_shards_overlapped": self.independent_shards_overlapped,
            "no_shared_mutable_connections": self.no_shared_mutable_connections,
            "control_plane_within_slo": self.control_plane_within_slo,
        }
        return content_identity(payload)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "plan_id": self.plan_id,
            "run_id": self.run_id,
            "task_id": self.task_id,
            "snapshot_vector_id": self.snapshot_vector_id,
            "snapshot_vector_digest": self.snapshot_vector_digest,
            "status": self.status,
            "partial_failure_policy": self.partial_failure_policy,
            "worker_evidence": list(self.worker_evidence),
            "resource_use": dict(self.resource_use),
            "result_digest": self.result_digest,
            "broker_receipt": dict(self.broker_receipt),
            "process_birth": dict(self.process_birth),
            "mutation_gate": dict(self.mutation_gate),
            "duration_ms": self.duration_ms,
            "created_at": self.created_at,
            "implementation_generation": self.implementation_generation,
            "independent_shards_overlapped": self.independent_shards_overlapped,
            "no_shared_mutable_connections": self.no_shared_mutable_connections,
            "control_plane_within_slo": self.control_plane_within_slo,
            "identity_id": self.identity_id,
        }


@dataclass(frozen=True, slots=True)
class LakeExecutionResult:
    """Joined rows, worker evidence, broker result, and lake receipt."""

    rows: tuple[Mapping[str, Any], ...]
    worker_evidence: tuple[LakeWorkerEvidence, ...]
    broker_result: pq.ParallelQueryResult
    receipt: LakeExecutionReceipt
    mutation_gate: CatalogOwnerMutationGate

    @property
    def status(self) -> str:
        return self.receipt.status

    @property
    def independent_shards_overlapped(self) -> bool:
        return self.receipt.independent_shards_overlapped

    def evidence_for(self, catalog_id: str) -> LakeWorkerEvidence | None:
        for ev in self.worker_evidence:
            if ev.catalog_id == catalog_id:
                return ev
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "rows": [dict(r) for r in self.rows],
            "worker_evidence": [e.to_dict() for e in self.worker_evidence],
            "broker_result": self.broker_result.to_dict(),
            "receipt": self.receipt.to_dict(),
            "mutation_gate": dict(self.mutation_gate.snapshot()),
        }


# ---------------------------------------------------------------------------
# Hermetic default endpoint
# ---------------------------------------------------------------------------


class InMemoryLakeQuackEndpoint:
    """Hermetic Quack endpoint double for tests and offline execution."""

    def __init__(
        self,
        *,
        catalog_id: str,
        quack_endpoint_identity: str,
        rows: Sequence[Mapping[str, Any]] | None = None,
        available: bool = True,
        fail: BaseException | None = None,
        slow_ms: float = 0.0,
        scan_hold_ms: float = 0.0,
    ) -> None:
        self.catalog_id = catalog_id
        self.quack_endpoint_identity = quack_endpoint_identity
        self.available = available
        self.rows = [dict(r) for r in (rows or ({"id": catalog_id, "ok": True},))]
        self.fail = fail
        self.slow_ms = float(slow_ms)
        self.scan_hold_ms = float(scan_hold_ms)
        self.attachments: list[IsolatedQuackAttachment] = []
        self.lease_ids_seen: list[str] = []
        self._lock = threading.Lock()

    def open_attachment(
        self,
        *,
        connection_id: str,
        member: SnapshotVectorMember,
        lease: ReaderLease,
    ) -> IsolatedQuackAttachment:
        if not self.available:
            raise LakeExecutionError(
                "ENDPOINT",
                f"catalog {self.catalog_id!r} is unavailable",
                catalog_id=self.catalog_id,
            )
        if lease.catalog_id != self.catalog_id:
            raise LakeExecutionError(
                "LEASE",
                "lease catalog does not match endpoint",
                catalog_id=self.catalog_id,
            )
        # Prove remote attach plan never opens the catalog file.
        remote = build_remote_worker_attach(member, vector_id=lease.vector_id)
        if remote.opens_catalog_file:
            raise LakeExecutionError(
                "ATTACH",
                "remote worker attach plan opens catalog file",
            )
        att = IsolatedQuackAttachment(
            connection_id=connection_id,
            catalog_id=self.catalog_id,
            quack_endpoint_identity=self.quack_endpoint_identity,
            owner_generation=member.owner_generation,
            fencing_epoch=member.fencing_epoch,
            snapshot_version=member.catalog_global_snapshot_id,
            opens_catalog_file=False,
        )
        att.open_reader()
        with self._lock:
            self.attachments.append(att)
            self.lease_ids_seen.append(lease.lease_id)
        return att

    def scan(
        self,
        attachment: IsolatedQuackAttachment,
        subplan: LakeShardSubplan,
        *,
        check: Callable[[], None] | None = None,
    ) -> Sequence[Mapping[str, Any]]:
        if self.fail is not None:
            raise self.fail
        if self.slow_ms > 0:
            end = time.monotonic() + (self.slow_ms / 1000.0)
            while time.monotonic() < end:
                if check is not None:
                    check()
                time.sleep(0.005)
        hold = subplan.hold_ms if subplan.hold_ms > 0 else self.scan_hold_ms
        return attachment.scan_rows(self.rows, check=check, hold_ms=hold)


# ---------------------------------------------------------------------------
# Executor
# ---------------------------------------------------------------------------


def _utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _digest_rows(rows: Sequence[Mapping[str, Any]]) -> str:
    return content_identity([dict(r) for r in rows])


class LakeParallelExecutor:
    """Trusted lake subplan executor backed by the parallel query broker.

    Lifecycle per worker (strict order)::

        acquire DQK-090 lease
          → open exclusive Quack attachment
            → scan + renew lease
              → materialize results
            → close readers / attachment
          → release lease

    Cancellation closes readers before release. Worker death relies on bounded
    lease TTL expiry; PID reuse and generation-fence drift fail closed.
    """

    def __init__(
        self,
        *,
        lease_db: AuthoritativeSnapshotDatabase | None = None,
        scheduler: pq.ParallelQueryScheduler | None = None,
        mutation_gate: CatalogOwnerMutationGate | None = None,
        endpoints: Mapping[str, LakeQuackEndpoint] | None = None,
    ) -> None:
        self._lease_db = lease_db or AuthoritativeSnapshotDatabase()
        self._scheduler = scheduler
        self._mutation_gate = mutation_gate or CatalogOwnerMutationGate()
        self._endpoints: dict[str, LakeQuackEndpoint] = dict(endpoints or {})
        self._lock = threading.RLock()
        self._evidence: dict[str, LakeWorkerEvidence] = {}

    @property
    def lease_db(self) -> AuthoritativeSnapshotDatabase:
        return self._lease_db

    @property
    def mutation_gate(self) -> CatalogOwnerMutationGate:
        return self._mutation_gate

    def register_endpoint(self, endpoint: LakeQuackEndpoint) -> None:
        with self._lock:
            self._endpoints[endpoint.catalog_id] = endpoint

    def execute(
        self,
        plan: LakeExecutionPlan,
        *,
        cancellation: CancellationToken | None = None,
        deadline_monotonic: float | None = None,
        run_heartbeat_monitor: bool = True,
    ) -> LakeExecutionResult:
        """Execute independent lake subplans under the parallel query broker."""

        if not isinstance(plan, LakeExecutionPlan):
            raise LakeExecutionError("PLAN", "plan must be a LakeExecutionPlan")

        # Persist vector before any lease references it.
        self._lease_db.put_vector(plan.snapshot_vector)

        budget = plan.catalog_budget.to_parallel_budget(
            max_workers=max(1, len(plan.subplans)),
            reserved_control_plane_ms=plan.reserved_control_plane_ms,
            reserved_control_plane_slots=plan.reserved_control_plane_slots,
            total_slots=plan.total_slots,
            heartbeat_interval_ms=plan.heartbeat_interval_ms,
            heartbeat_p99_slo_ms=plan.heartbeat_p99_slo_ms,
        )

        # Shared evidence bag written by workers (thread-safe via lock).
        evidence_bag: dict[str, LakeWorkerEvidence] = {}
        evidence_lock = threading.Lock()

        specs: list[pq.SubquerySpec] = []
        for idx, subplan in enumerate(plan.subplans):
            domain = _DOMAIN_CYCLE[idx % len(_DOMAIN_CYCLE)]
            runner = self._make_runner(
                plan=plan,
                subplan=subplan,
                evidence_bag=evidence_bag,
                evidence_lock=evidence_lock,
            )
            specs.append(
                pq.SubquerySpec(
                    subquery_id=subplan.subplan_id,
                    domain=domain,
                    runner=runner,
                    max_rows=subplan.max_rows or plan.catalog_budget.max_rows,
                    catalog_id=subplan.catalog_id,
                    metadata={
                        "catalog_id": subplan.catalog_id,
                        "shard_id": subplan.shard_id,
                        "quack_endpoint_identity": subplan.quack_endpoint_identity,
                        "owner_generation": subplan.owner_generation,
                        "fencing_epoch": subplan.fencing_epoch,
                        "snapshot_version": subplan.snapshot_version,
                        "vector_id": plan.snapshot_vector.vector_id,
                        "dataset_id": subplan.dataset_id,
                    },
                )
            )

        broker_plan = pq.ParallelQueryPlan(
            subqueries=tuple(specs),
            budget=budget,
            partial_failure_policy=plan.partial_failure_policy,
            join_policy=pq.JoinPolicy.CONCAT,
            snapshot=None,
            plan_id=plan.plan_id,
        )

        scheduler = self._scheduler or pq.open_default_scheduler(
            total_slots=budget.total_slots,
            reserved_control_plane_slots=budget.reserved_control_plane_slots,
            max_connections_per_catalog=budget.max_connections_per_catalog,
        )

        started = time.monotonic()
        broker_result = scheduler.run(
            broker_plan,
            cancellation=cancellation,
            deadline_monotonic=deadline_monotonic,
            run_heartbeat_monitor=run_heartbeat_monitor,
        )
        duration_ms = max(0.0, (time.monotonic() - started) * 1000.0)

        # Assemble worker evidence in plan order; fill gaps for cancelled-before-start.
        ordered_evidence: list[LakeWorkerEvidence] = []
        for subplan in plan.subplans:
            with evidence_lock:
                ev = evidence_bag.get(subplan.subplan_id)
            if ev is None:
                outcome = broker_result.outcome_for(subplan.subplan_id)
                ev = LakeWorkerEvidence(
                    subplan_id=subplan.subplan_id,
                    catalog_id=subplan.catalog_id,
                    shard_id=subplan.shard_id,
                    quack_endpoint_identity=subplan.quack_endpoint_identity,
                    owner_generation=subplan.owner_generation,
                    fencing_epoch=subplan.fencing_epoch,
                    snapshot_version=subplan.snapshot_version,
                    connection_id=(
                        outcome.connection_id if outcome is not None else ""
                    ),
                    lease=None,
                    resource_use={},
                    status=outcome.status.value if outcome is not None else "failed",
                    row_count=0,
                    result_digest="",
                )
            ordered_evidence.append(ev)

        shard_overlap = dict(broker_result.receipt.shard_overlap or {})
        independent = bool(shard_overlap.get("independent_shards_overlapped"))
        # Also treat ≥2 distinct successful catalog intervals as overlap.
        if not independent and len(plan.catalog_ids) >= 2:
            independent = bool(shard_overlap.get("max_concurrency", 0) >= 2) and (
                len(
                    {
                        o.catalog_id
                        for o in broker_result.outcomes
                        if o.catalog_id and o.succeeded
                    }
                )
                >= 2
                or bool(shard_overlap.get("shards_that_overlapped"))
            )

        no_shared = bool(shard_overlap.get("no_shared_mutable_connections", True))
        # Connection identity uniqueness across successful workers.
        conn_ids = [
            e.connection_id for e in ordered_evidence if e.connection_id
        ]
        if len(conn_ids) != len(set(conn_ids)):
            no_shared = False

        result_digest = _digest_rows(broker_result.rows)
        status = self._map_status(broker_result)

        receipt = LakeExecutionReceipt(
            schema=LAKE_EXECUTION_RECEIPT_SCHEMA,
            plan_id=plan.plan_id,
            run_id=plan.run_id,
            task_id=plan.task_id,
            snapshot_vector_id=plan.snapshot_vector.vector_id,
            snapshot_vector_digest=plan.snapshot_vector.identity_digest,
            status=status,
            partial_failure_policy=plan.partial_failure_policy.value,
            worker_evidence=tuple(e.to_dict() for e in ordered_evidence),
            resource_use=MappingProxyType(
                dict(broker_result.receipt.resource_use or {})
            ),
            result_digest=result_digest,
            broker_receipt=MappingProxyType(broker_result.receipt.to_dict()),
            process_birth=MappingProxyType(dict(plan.process_birth.as_mapping())),
            mutation_gate=MappingProxyType(dict(self._mutation_gate.snapshot())),
            duration_ms=duration_ms,
            created_at=_utc_now(),
            independent_shards_overlapped=independent,
            no_shared_mutable_connections=no_shared,
            control_plane_within_slo=bool(broker_result.heartbeat.within_slo),
        )

        return LakeExecutionResult(
            rows=broker_result.rows,
            worker_evidence=tuple(ordered_evidence),
            broker_result=broker_result,
            receipt=receipt,
            mutation_gate=self._mutation_gate,
        )

    def _map_status(self, broker_result: pq.ParallelQueryResult) -> str:
        status = broker_result.status
        if status in {s.value for s in LakeExecutionStatus}:
            return status
        return status

    def _make_runner(
        self,
        *,
        plan: LakeExecutionPlan,
        subplan: LakeShardSubplan,
        evidence_bag: dict[str, LakeWorkerEvidence],
        evidence_lock: threading.Lock,
    ) -> pq.SubqueryRunner:
        def _runner(context: pq.SubqueryContext) -> Sequence[Mapping[str, Any]]:
            return self._run_shard_worker(
                plan=plan,
                subplan=subplan,
                context=context,
                evidence_bag=evidence_bag,
                evidence_lock=evidence_lock,
            )

        return _runner

    def _run_shard_worker(
        self,
        *,
        plan: LakeExecutionPlan,
        subplan: LakeShardSubplan,
        context: pq.SubqueryContext,
        evidence_bag: dict[str, LakeWorkerEvidence],
        evidence_lock: threading.Lock,
    ) -> Sequence[Mapping[str, Any]]:
        worker_id = f"worker-{subplan.subplan_id}"
        member = plan.snapshot_vector.member_for(subplan.catalog_id)
        lease: ReaderLease | None = None
        attachment: IsolatedQuackAttachment | None = None
        renewed = 0
        readers_closed_before_release = False
        acquired = False
        released = False
        final_status = "failed"
        rows: list[Mapping[str, Any]] = []
        result_digest = ""
        connection_id = context.connection_id or f"pending-{subplan.subplan_id}"

        renew_stop = threading.Event()
        renew_thread: threading.Thread | None = None

        def _close_readers() -> None:
            nonlocal readers_closed_before_release, attachment
            if attachment is not None and not attachment.closed:
                attachment.close()
                readers_closed_before_release = True

        context.set_close_hook(_close_readers)

        def _renew_loop() -> None:
            nonlocal lease, renewed
            interval = max(0.005, plan.catalog_budget.renew_interval_ms / 1000.0)
            while not renew_stop.wait(interval):
                if lease is None:
                    continue
                try:
                    context.check()
                    lease = self._lease_db.renew_lease(
                        lease_id=lease.lease_id,
                        lease_token=lease.lease_token,
                        process_birth=plan.process_birth,
                        task_id=plan.task_id,
                        run_id=plan.run_id,
                        ttl_seconds=plan.catalog_budget.lease_ttl_seconds,
                        owner_generation=subplan.owner_generation,
                        fencing_epoch=subplan.fencing_epoch,
                    )
                    renewed += 1
                    context.record_renewal()
                except (ReaderLeaseError, QueryCancelled, QueryBudgetExceeded):
                    # Stop renewing; main path will observe cancel/deadline.
                    renew_stop.set()
                    return
                except Exception:
                    renew_stop.set()
                    return

        try:
            context.check()

            # 1. Acquire authoritative DQK-090 lease BEFORE Quack attachment.
            lease = self._lease_db.acquire_lease(
                vector=plan.snapshot_vector,
                catalog_id=subplan.catalog_id,
                process_birth=plan.process_birth,
                task_id=plan.task_id,
                run_id=plan.run_id,
                worker_id=worker_id,
                ttl_seconds=plan.catalog_budget.lease_ttl_seconds,
                expected_owner_generation=subplan.owner_generation,
                expected_fencing_epoch=subplan.fencing_epoch,
            )
            acquired = True

            # Start renewals for the full attachment/scan/materialize window.
            renew_thread = threading.Thread(
                target=_renew_loop,
                name=f"lease-renew-{subplan.catalog_id}",
                daemon=True,
            )
            renew_thread.start()

            context.check()

            with self._lock:
                endpoint = self._endpoints.get(subplan.catalog_id)
            if endpoint is None:
                raise LakeExecutionError(
                    "ENDPOINT",
                    f"no Quack endpoint registered for catalog "
                    f"{subplan.catalog_id!r}",
                    catalog_id=subplan.catalog_id,
                )
            if not getattr(endpoint, "available", True):
                raise LakeExecutionError(
                    "ENDPOINT",
                    f"catalog {subplan.catalog_id!r} is unavailable",
                    catalog_id=subplan.catalog_id,
                )

            # 2. Open exclusive remote Quack attachment (never catalog file).
            attachment = endpoint.open_attachment(
                connection_id=connection_id,
                member=member,
                lease=lease,
            )
            if attachment.opens_catalog_file:
                raise LakeExecutionError(
                    "ATTACH",
                    "endpoint opened a catalog metadata file",
                    catalog_id=subplan.catalog_id,
                )

            context.check()

            # 3. Scan + materialize under budgets; renew continues in background.
            raw = endpoint.scan(attachment, subplan, check=context.check)
            materialised: list[Mapping[str, Any]] = []
            total_bytes = 0
            for row in raw:
                context.check()
                if not isinstance(row, Mapping):
                    raise LakeExecutionError("SCAN", "row must be a mapping")
                payload = dict(row)
                payload.setdefault("catalog_id", subplan.catalog_id)
                payload.setdefault("connection_id", connection_id)
                payload.setdefault("lease_id", lease.lease_id)
                encoded = json.dumps(
                    payload, sort_keys=True, default=str
                ).encode("utf-8")
                total_bytes += len(encoded)
                context.record_memory(total_bytes)
                if total_bytes > plan.catalog_budget.max_bytes:
                    raise QueryBudgetExceeded("bytes", plan.catalog_budget.max_bytes)
                if len(materialised) >= context.max_rows:
                    break
                materialised.append(MappingProxyType(payload))

            # Synthetic spill accounting for hermetic scans (zero unless set).
            spill = int(subplan.metadata.get("spill_bytes", 0) or 0)
            if spill:
                context.record_spill(spill)

            rows = materialised
            result_digest = _digest_rows(rows)
            final_status = "succeeded"
            return rows

        except QueryCancelled:
            final_status = "cancelled"
            raise
        except QueryBudgetExceeded as exc:
            final_status = "timeout" if getattr(exc, "kind", "") == "time" else "budget_exceeded"
            raise
        except Exception:
            final_status = "failed"
            raise
        finally:
            renew_stop.set()
            if renew_thread is not None:
                renew_thread.join(timeout=1.0)

            # 4. Close readers/attachment BEFORE lease release.
            _close_readers()
            if attachment is not None:
                readers_closed_before_release = attachment.closed

            # 5. Release exact fenced lease (or leave for bounded expiry on crash).
            if lease is not None and acquired:
                try:
                    released_lease = self._lease_db.release_lease(
                        lease_id=lease.lease_id,
                        lease_token=lease.lease_token,
                        process_birth=plan.process_birth,
                        task_id=plan.task_id,
                        run_id=plan.run_id,
                        owner_generation=subplan.owner_generation,
                        fencing_epoch=subplan.fencing_epoch,
                    )
                    lease = released_lease
                    released = True
                    final_lease_status = released_lease.status.value
                except ReaderLeaseError:
                    # Stale fence / already expired: not renewable.
                    final_lease_status = (
                        lease.status.value if lease is not None else "unknown"
                    )
                else:
                    final_lease_status = LeaseStatus.RELEASED.value
            else:
                final_lease_status = "not_acquired"

            lifecycle = None
            if lease is not None:
                lifecycle = LeaseLifecycle(
                    lease_id=lease.lease_id,
                    lease_token_redacted="***",
                    catalog_id=lease.catalog_id,
                    vector_id=lease.vector_id,
                    owner_generation=lease.owner_generation,
                    fencing_epoch=lease.fencing_epoch,
                    process_birth=dict(lease.process_birth.as_mapping()),
                    task_id=lease.task_id,
                    run_id=lease.run_id,
                    worker_id=lease.worker_id,
                    acquired=acquired,
                    renewed_count=renewed,
                    released=released,
                    final_status=final_lease_status,
                    readers_closed_before_release=readers_closed_before_release,
                    acquired_at=lease.acquired_at,
                    released_at=_utc_now() if released else "",
                    expires_at=lease.expires_at,
                )

            evidence = LakeWorkerEvidence(
                subplan_id=subplan.subplan_id,
                catalog_id=subplan.catalog_id,
                shard_id=subplan.shard_id,
                quack_endpoint_identity=subplan.quack_endpoint_identity,
                owner_generation=subplan.owner_generation,
                fencing_epoch=subplan.fencing_epoch,
                snapshot_version=subplan.snapshot_version,
                connection_id=connection_id,
                lease=lifecycle,
                resource_use=context.resource_use(
                    rows=len(rows), bytes_=sum(
                        len(json.dumps(dict(r), sort_keys=True, default=str).encode())
                        for r in rows
                    )
                ).to_dict(),
                status=final_status,
                row_count=len(rows),
                result_digest=result_digest,
            )
            with evidence_lock:
                evidence_bag[subplan.subplan_id] = evidence

    def mutate_catalog(
        self,
        catalog_id: str,
        kind: MutationKind | str,
        operation: Callable[[], Any],
        *,
        holder: str = "",
        timeout: float | None = None,
    ) -> Any:
        """Serialize a same-shard catalog mutation through the owner gate."""

        return self._mutation_gate.mutate(
            catalog_id,
            kind,
            operation,
            holder=holder,
            timeout=timeout,
        )


def open_default_lake_executor(
    *,
    lease_db: AuthoritativeSnapshotDatabase | None = None,
) -> LakeParallelExecutor:
    """Construct a lake executor with in-memory lease authority."""

    return LakeParallelExecutor(lease_db=lease_db or AuthoritativeSnapshotDatabase())
