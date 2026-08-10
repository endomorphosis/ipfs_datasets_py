"""Cross-domain parallel query scheduler with control-plane capacity (DQK-042/092).

Runs independent graph / vector / proof / AST / wallet subqueries concurrently,
propagates deadlines and cancellation, joins bounded results, and reserves
control-plane capacity so lease heartbeats are not starved under analytical load.

DQK-092 extends the broker for lake shard subplans: per-catalog connection,
row, byte, memory, time, spill, and cancellation budgets; isolated worker
connections (no shared mutable handles); and capacity isolation so a slow or
failed catalog owner cannot starve supervisor heartbeats or unrelated shards.

Acceptance (DQK-042)
--------------------
* Independent subqueries actually overlap
* Partial timeout/failure is typed
* Lease heartbeat p99 stays within SLO under benchmark load

Acceptance (DQK-092 broker surface)
----------------------------------
* Per-catalog connection / memory / spill budgets with backpressure
* Independent catalog workers never share mutable connections
* Reserved control-plane capacity remains available under analytical fan-out
* Deadlines and cancellation propagate to every worker

Architecture notes
------------------
* Analytical workers never borrow reserved control-plane slots. Heartbeats and
  lease renewals always have exclusive capacity.
* Analytical wall-clock budget leaves ``reserved_control_plane_ms`` headroom
  inside the caller deadline so control-plane work is not starved by scans.
* Partial failures are closed under a typed ``FailureKind`` enum; callers never
  receive opaque strings as the only signal.
* Join is row-bounded and domain-tagged; unbounded cartesian products are
  refused.
* Catalog connection pools bound concurrent attachments per catalog identity;
  distinct catalogs execute concurrently under independent slots.

Importing this module is inert: no DuckDB, network, or filesystem I/O.
"""

from __future__ import annotations

import math
import threading
import time
import uuid
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from types import MappingProxyType
from typing import (
    Any,
    Callable,
    Final,
    Iterable,
    Mapping,
    Protocol,
    Sequence,
)

from ipfs_datasets_py.duckdb_control.contracts import (
    ContractError,
    SnapshotId,
    content_identity,
    normalize_timestamp,
    parse_snapshot_id,
)
from ipfs_datasets_py.duckdb_control.query_registry import (
    CancellationToken as RegistryCancellationToken,
    QueryBudgetExceeded,
    QueryCancelled,
    QueryRegistryError,
)

__all__ = [
    "PARALLEL_QUERY_SCHEMA",
    "PARALLEL_RECEIPT_SCHEMA",
    "DEFAULT_PARALLEL_BUDGET",
    "DEFAULT_HEARTBEAT_P99_SLO_MS",
    "DEFAULT_RESERVED_CONTROL_PLANE_MS",
    "DEFAULT_RESERVED_CONTROL_PLANE_SLOTS",
    "DEFAULT_MAX_MEMORY_BYTES",
    "DEFAULT_MAX_SPILL_BYTES",
    "DEFAULT_MAX_CONNECTIONS_PER_CATALOG",
    "CROSS_DOMAIN_SET",
    "CatalogConnectionPool",
    "ControlPlaneCapacity",
    "FailureKind",
    "HeartbeatSample",
    "HeartbeatStats",
    "JoinPolicy",
    "LeaseHeartbeatMonitor",
    "OverlapEvidence",
    "PARALLEL_QUERY_IMPLEMENTATION_GENERATION",
    "ParallelQueryBudget",
    "ParallelQueryError",
    "ParallelQueryPlan",
    "ParallelQueryReceipt",
    "ParallelQueryResult",
    "ParallelQueryScheduler",
    "PartialFailurePolicy",
    "ResourceUse",
    "SubqueryContext",
    "SubqueryDomain",
    "SubqueryOutcome",
    "SubqueryRunner",
    "SubquerySpec",
    "SubqueryStatus",
    "TypedPartialFailure",
    "compute_overlap_evidence",
    "compute_shard_overlap_evidence",
    "intervals_overlap",
    "join_bounded_results",
    "open_default_scheduler",
    "percentile",
]


# ---------------------------------------------------------------------------
# Schema pins / defaults
# ---------------------------------------------------------------------------

PARALLEL_QUERY_SCHEMA: Final[str] = (
    "ipfs_datasets_py/duckdb-control-parallel-query@1"
)
PARALLEL_RECEIPT_SCHEMA: Final[str] = (
    "ipfs_datasets_py/duckdb-control-parallel-receipt@1"
)
PARALLEL_QUERY_IMPLEMENTATION_GENERATION: Final[str] = (
    "dqk-042-dqk-092-parallel-broker-20260810"
)

DEFAULT_RESERVED_CONTROL_PLANE_MS: Final[int] = 250
DEFAULT_RESERVED_CONTROL_PLANE_SLOTS: Final[int] = 1
DEFAULT_HEARTBEAT_P99_SLO_MS: Final[float] = 50.0
DEFAULT_MAX_WORKERS: Final[int] = 5
DEFAULT_MAX_DURATION_MS: Final[int] = 10_000
DEFAULT_MAX_ROWS_PER_SUBQUERY: Final[int] = 5_000
DEFAULT_MAX_TOTAL_ROWS: Final[int] = 20_000
DEFAULT_MAX_BYTES: Final[int] = 16 * 1024 * 1024
DEFAULT_MAX_MEMORY_BYTES: Final[int] = 64 * 1024 * 1024
DEFAULT_MAX_SPILL_BYTES: Final[int] = 128 * 1024 * 1024
DEFAULT_MAX_CONNECTIONS_PER_CATALOG: Final[int] = 1
DEFAULT_HEARTBEAT_INTERVAL_MS: Final[int] = 10
DEFAULT_TOTAL_SLOTS: Final[int] = 8

MAX_WORKERS_HARD: Final[int] = 64
MAX_DURATION_MS_HARD: Final[int] = 600_000
MAX_ROWS_HARD: Final[int] = 1_000_000
MAX_BYTES_HARD: Final[int] = 256 * 1024 * 1024
MAX_MEMORY_HARD: Final[int] = 8 * 1024 * 1024 * 1024
MAX_SPILL_HARD: Final[int] = 16 * 1024 * 1024 * 1024
MAX_CONNECTIONS_PER_CATALOG_HARD: Final[int] = 64
MAX_SUBQUERIES_HARD: Final[int] = 64


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class ParallelQueryError(ValueError):
    """Fail-closed rejection of a parallel plan, budget, or join contract."""

    def __init__(self, code: str, message: str, **details: Any) -> None:
        super().__init__(f"{code}: {message}")
        self.code = str(code)
        self.details = dict(details)


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class SubqueryDomain(str, Enum):
    """Independent cross-domain analytical subquery surfaces (DQK-042)."""

    GRAPH = "graph"
    VECTOR = "vector"
    PROOF = "proof"
    AST = "ast"
    WALLET = "wallet"


CROSS_DOMAIN_SET: Final[frozenset[SubqueryDomain]] = frozenset(SubqueryDomain)


class SubqueryStatus(str, Enum):
    """Terminal status of one subquery worker."""

    SUCCEEDED = "succeeded"
    TRUNCATED = "truncated"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"
    FAILED = "failed"
    BUDGET_EXCEEDED = "budget_exceeded"
    CAPACITY_DENIED = "capacity_denied"
    SKIPPED = "skipped"


class FailureKind(str, Enum):
    """Closed set of typed partial / terminal failure kinds.

    Callers and receipts must branch on this enum, never on free-form message
    parsing. Message text is diagnostic only.
    """

    TIMEOUT = "timeout"
    DEADLINE_EXCEEDED = "deadline_exceeded"
    CANCELLED = "cancelled"
    EXECUTION_ERROR = "execution_error"
    BUDGET_EXCEEDED = "budget_exceeded"
    CAPACITY_DENIED = "capacity_denied"
    JOIN_TRUNCATED = "join_truncated"
    INTERNAL = "internal"


class PartialFailurePolicy(str, Enum):
    """How the scheduler treats partial subquery failures."""

    CONTINUE = "continue"  # return successes + typed partials
    FAIL_FAST = "fail_fast"  # cancel siblings on first non-success
    REQUIRE_ALL = "require_all"  # overall failed unless every subquery succeeded


class JoinPolicy(str, Enum):
    """How independent domain results are joined into a bounded bag."""

    CONCAT = "concat"  # domain-tagged concatenation (default, safe)
    ZIP_SHORTEST = "zip_shortest"  # align by index, stop at shortest


# ---------------------------------------------------------------------------
# Capacity / budgets
# ---------------------------------------------------------------------------


class ControlPlaneCapacity:
    """Slot pool that permanently reserves control-plane capacity.

    Analytical workers may only acquire from the non-reserved pool. Lease
    heartbeats acquire from the reserved pool and therefore cannot be starved
    by concurrent analytical fan-out.
    """

    __slots__ = (
        "total_slots",
        "reserved_control_plane_slots",
        "_analytical",
        "_control",
        "_lock",
        "_analytical_in_use",
        "_control_in_use",
        "_analytical_wait_ms",
        "_control_wait_ms",
    )

    def __init__(
        self,
        *,
        total_slots: int = DEFAULT_TOTAL_SLOTS,
        reserved_control_plane_slots: int = DEFAULT_RESERVED_CONTROL_PLANE_SLOTS,
    ) -> None:
        if (
            not isinstance(total_slots, int)
            or isinstance(total_slots, bool)
            or total_slots < 1
            or total_slots > 1024
        ):
            raise ParallelQueryError(
                "CAPACITY", f"total_slots out of range: {total_slots!r}"
            )
        if (
            not isinstance(reserved_control_plane_slots, int)
            or isinstance(reserved_control_plane_slots, bool)
            or reserved_control_plane_slots < 1
            or reserved_control_plane_slots >= total_slots
        ):
            raise ParallelQueryError(
                "CAPACITY",
                "reserved_control_plane_slots must be in [1, total_slots)",
                total_slots=total_slots,
                reserved=reserved_control_plane_slots,
            )
        self.total_slots = total_slots
        self.reserved_control_plane_slots = reserved_control_plane_slots
        analytical = total_slots - reserved_control_plane_slots
        self._analytical = threading.Semaphore(analytical)
        self._control = threading.Semaphore(reserved_control_plane_slots)
        self._lock = threading.Lock()
        self._analytical_in_use = 0
        self._control_in_use = 0
        self._analytical_wait_ms: list[float] = []
        self._control_wait_ms: list[float] = []

    @property
    def analytical_slots(self) -> int:
        return self.total_slots - self.reserved_control_plane_slots

    def acquire_analytical(self, *, timeout: float | None = None) -> bool:
        started = time.monotonic()
        ok = self._analytical.acquire(timeout=timeout if timeout is not None else None)
        waited = (time.monotonic() - started) * 1000.0
        with self._lock:
            self._analytical_wait_ms.append(waited)
            if ok:
                self._analytical_in_use += 1
        return ok

    def release_analytical(self) -> None:
        with self._lock:
            if self._analytical_in_use > 0:
                self._analytical_in_use -= 1
        self._analytical.release()

    def acquire_control(self, *, timeout: float | None = None) -> bool:
        started = time.monotonic()
        ok = self._control.acquire(timeout=timeout if timeout is not None else None)
        waited = (time.monotonic() - started) * 1000.0
        with self._lock:
            self._control_wait_ms.append(waited)
            if ok:
                self._control_in_use += 1
        return ok

    def release_control(self) -> None:
        with self._lock:
            if self._control_in_use > 0:
                self._control_in_use -= 1
        self._control.release()

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "total_slots": self.total_slots,
                "reserved_control_plane_slots": self.reserved_control_plane_slots,
                "analytical_slots": self.analytical_slots,
                "analytical_in_use": self._analytical_in_use,
                "control_in_use": self._control_in_use,
                "analytical_wait_samples": len(self._analytical_wait_ms),
                "control_wait_samples": len(self._control_wait_ms),
                "control_wait_p99_ms": percentile(self._control_wait_ms, 99.0)
                if self._control_wait_ms
                else 0.0,
            }


class CatalogConnectionPool:
    """Per-catalog connection slots that never share mutable handles.

    Independent catalog shards acquire concurrent connections. Workers on the
    same catalog are back-pressured by ``max_connections_per_catalog``. Every
    acquire returns a unique connection identity so lake workers can prove they
    did not reuse a peer's mutable attachment.
    """

    __slots__ = (
        "max_connections_per_catalog",
        "_semaphores",
        "_in_use",
        "_owners",
        "_lock",
        "_wait_ms",
        "_total_acquires",
    )

    def __init__(
        self,
        *,
        max_connections_per_catalog: int = DEFAULT_MAX_CONNECTIONS_PER_CATALOG,
    ) -> None:
        if (
            not isinstance(max_connections_per_catalog, int)
            or isinstance(max_connections_per_catalog, bool)
            or max_connections_per_catalog < 1
            or max_connections_per_catalog > MAX_CONNECTIONS_PER_CATALOG_HARD
        ):
            raise ParallelQueryError(
                "CAPACITY",
                f"max_connections_per_catalog out of range: "
                f"{max_connections_per_catalog!r}",
            )
        self.max_connections_per_catalog = max_connections_per_catalog
        self._semaphores: dict[str, threading.Semaphore] = {}
        self._in_use: dict[str, int] = {}
        # connection_id -> catalog_id (proves exclusive ownership)
        self._owners: dict[str, str] = {}
        self._lock = threading.Lock()
        self._wait_ms: list[float] = []
        self._total_acquires = 0

    def _semaphore_for(self, catalog_id: str) -> threading.Semaphore:
        cid = str(catalog_id or "").strip() or "__default__"
        with self._lock:
            sem = self._semaphores.get(cid)
            if sem is None:
                sem = threading.Semaphore(self.max_connections_per_catalog)
                self._semaphores[cid] = sem
                self._in_use.setdefault(cid, 0)
            return sem

    def acquire(
        self,
        catalog_id: str,
        *,
        timeout: float | None = None,
        owner_token: str = "",
    ) -> str | None:
        """Acquire an exclusive connection slot for ``catalog_id``.

        Returns a unique connection identity on success, or ``None`` on timeout.
        """

        cid = str(catalog_id or "").strip() or "__default__"
        sem = self._semaphore_for(cid)
        started = time.monotonic()
        ok = sem.acquire(timeout=timeout if timeout is not None else None)
        waited = (time.monotonic() - started) * 1000.0
        with self._lock:
            self._wait_ms.append(waited)
            if not ok:
                return None
            self._in_use[cid] = self._in_use.get(cid, 0) + 1
            self._total_acquires += 1
            conn_id = (
                f"conn-{cid}-{self._total_acquires:08d}-"
                f"{uuid.uuid4().hex[:12]}"
            )
            if owner_token:
                conn_id = f"{conn_id}:{owner_token[:32]}"
            self._owners[conn_id] = cid
            return conn_id

    def release(self, catalog_id: str, connection_id: str) -> None:
        cid = str(catalog_id or "").strip() or "__default__"
        with self._lock:
            owner = self._owners.pop(connection_id, None)
            if owner is not None and owner != cid:
                # Defensive: still release the semaphore for the true owner.
                cid = owner
            if self._in_use.get(cid, 0) > 0:
                self._in_use[cid] -= 1
        sem = self._semaphore_for(cid)
        sem.release()

    def connection_owner(self, connection_id: str) -> str | None:
        with self._lock:
            return self._owners.get(connection_id)

    def in_use(self, catalog_id: str) -> int:
        cid = str(catalog_id or "").strip() or "__default__"
        with self._lock:
            return int(self._in_use.get(cid, 0))

    def active_connection_ids(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(sorted(self._owners))

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "max_connections_per_catalog": self.max_connections_per_catalog,
                "catalogs": {
                    cid: {
                        "in_use": self._in_use.get(cid, 0),
                        "connections": sorted(
                            c for c, o in self._owners.items() if o == cid
                        ),
                    }
                    for cid in sorted(
                        set(self._semaphores) | set(self._in_use) | set(self._owners.values())
                    )
                },
                "total_acquires": self._total_acquires,
                "active_connections": len(self._owners),
                "wait_samples": len(self._wait_ms),
                "wait_p99_ms": percentile(self._wait_ms, 99.0) if self._wait_ms else 0.0,
            }


@dataclass(frozen=True, slots=True)
class ResourceUse:
    """Measured resource consumption for one worker or the joined plan."""

    rows: int = 0
    bytes: int = 0
    memory_bytes: int = 0
    spill_bytes: int = 0
    duration_ms: float = 0.0
    connections: int = 0
    renewals: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "rows": int(self.rows),
            "bytes": int(self.bytes),
            "memory_bytes": int(self.memory_bytes),
            "spill_bytes": int(self.spill_bytes),
            "duration_ms": float(self.duration_ms),
            "connections": int(self.connections),
            "renewals": int(self.renewals),
        }

    def merge(self, other: "ResourceUse") -> "ResourceUse":
        return ResourceUse(
            rows=self.rows + other.rows,
            bytes=self.bytes + other.bytes,
            memory_bytes=max(self.memory_bytes, other.memory_bytes),
            spill_bytes=self.spill_bytes + other.spill_bytes,
            duration_ms=max(self.duration_ms, other.duration_ms),
            connections=self.connections + other.connections,
            renewals=self.renewals + other.renewals,
        )


@dataclass(frozen=True, slots=True)
class ParallelQueryBudget:
    """Hard caps plus reserved control-plane capacity for a parallel plan.

    ``reserved_control_plane_ms`` is *not* available to analytical subqueries.
    Effective analytical wall-clock is::

        max(1, max_duration_ms - reserved_control_plane_ms)

    Per-catalog connection / memory / spill caps (DQK-092) bound lake workers
    without borrowing reserved control-plane capacity.
    """

    max_workers: int = DEFAULT_MAX_WORKERS
    max_duration_ms: int = DEFAULT_MAX_DURATION_MS
    max_rows_per_subquery: int = DEFAULT_MAX_ROWS_PER_SUBQUERY
    max_total_rows: int = DEFAULT_MAX_TOTAL_ROWS
    max_bytes: int = DEFAULT_MAX_BYTES
    max_memory_bytes: int = DEFAULT_MAX_MEMORY_BYTES
    max_spill_bytes: int = DEFAULT_MAX_SPILL_BYTES
    max_connections_per_catalog: int = DEFAULT_MAX_CONNECTIONS_PER_CATALOG
    reserved_control_plane_ms: int = DEFAULT_RESERVED_CONTROL_PLANE_MS
    reserved_control_plane_slots: int = DEFAULT_RESERVED_CONTROL_PLANE_SLOTS
    total_slots: int = DEFAULT_TOTAL_SLOTS
    heartbeat_interval_ms: int = DEFAULT_HEARTBEAT_INTERVAL_MS
    heartbeat_p99_slo_ms: float = DEFAULT_HEARTBEAT_P99_SLO_MS

    def __post_init__(self) -> None:
        int_bounds = (
            ("max_workers", self.max_workers, 1, MAX_WORKERS_HARD),
            ("max_duration_ms", self.max_duration_ms, 1, MAX_DURATION_MS_HARD),
            ("max_rows_per_subquery", self.max_rows_per_subquery, 1, MAX_ROWS_HARD),
            ("max_total_rows", self.max_total_rows, 1, MAX_ROWS_HARD),
            ("max_bytes", self.max_bytes, 1, MAX_BYTES_HARD),
            ("max_memory_bytes", self.max_memory_bytes, 1, MAX_MEMORY_HARD),
            ("max_spill_bytes", self.max_spill_bytes, 0, MAX_SPILL_HARD),
            (
                "max_connections_per_catalog",
                self.max_connections_per_catalog,
                1,
                MAX_CONNECTIONS_PER_CATALOG_HARD,
            ),
            ("reserved_control_plane_ms", self.reserved_control_plane_ms, 0, MAX_DURATION_MS_HARD),
            ("reserved_control_plane_slots", self.reserved_control_plane_slots, 1, 256),
            ("total_slots", self.total_slots, 2, 1024),
            ("heartbeat_interval_ms", self.heartbeat_interval_ms, 1, 60_000),
        )
        for name, value, lo, hi in int_bounds:
            if (
                not isinstance(value, int)
                or isinstance(value, bool)
                or value < lo
                or value > hi
            ):
                raise ParallelQueryError(
                    "BUDGET",
                    f"{name} must be an int in [{lo}, {hi}], got {value!r}",
                )
        if (
            not isinstance(self.heartbeat_p99_slo_ms, (int, float))
            or isinstance(self.heartbeat_p99_slo_ms, bool)
            or self.heartbeat_p99_slo_ms <= 0
        ):
            raise ParallelQueryError(
                "BUDGET",
                f"heartbeat_p99_slo_ms must be a positive number, got "
                f"{self.heartbeat_p99_slo_ms!r}",
            )
        if self.reserved_control_plane_ms >= self.max_duration_ms:
            raise ParallelQueryError(
                "BUDGET",
                "reserved_control_plane_ms must be < max_duration_ms "
                "(control-plane capacity must remain)",
            )
        if self.reserved_control_plane_slots >= self.total_slots:
            raise ParallelQueryError(
                "BUDGET",
                "reserved_control_plane_slots must be < total_slots",
            )
        if self.max_workers > self.analytical_slots:
            raise ParallelQueryError(
                "BUDGET",
                "max_workers cannot exceed analytical_slots "
                f"({self.analytical_slots})",
            )

    @property
    def analytical_time_ms(self) -> int:
        return max(1, int(self.max_duration_ms) - int(self.reserved_control_plane_ms))

    @property
    def analytical_slots(self) -> int:
        return int(self.total_slots) - int(self.reserved_control_plane_slots)

    def to_dict(self) -> dict[str, Any]:
        return {
            "max_workers": self.max_workers,
            "max_duration_ms": self.max_duration_ms,
            "max_rows_per_subquery": self.max_rows_per_subquery,
            "max_total_rows": self.max_total_rows,
            "max_bytes": self.max_bytes,
            "max_memory_bytes": self.max_memory_bytes,
            "max_spill_bytes": self.max_spill_bytes,
            "max_connections_per_catalog": self.max_connections_per_catalog,
            "reserved_control_plane_ms": self.reserved_control_plane_ms,
            "reserved_control_plane_slots": self.reserved_control_plane_slots,
            "total_slots": self.total_slots,
            "analytical_time_ms": self.analytical_time_ms,
            "analytical_slots": self.analytical_slots,
            "heartbeat_interval_ms": self.heartbeat_interval_ms,
            "heartbeat_p99_slo_ms": float(self.heartbeat_p99_slo_ms),
        }


DEFAULT_PARALLEL_BUDGET: Final[ParallelQueryBudget] = ParallelQueryBudget()


# ---------------------------------------------------------------------------
# Heartbeat monitoring
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class HeartbeatSample:
    """One lease-heartbeat probe observation."""

    sequence: int
    latency_ms: float
    acquired_slot: bool
    at_monotonic: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "sequence": self.sequence,
            "latency_ms": self.latency_ms,
            "acquired_slot": self.acquired_slot,
            "at_monotonic": self.at_monotonic,
        }


@dataclass(frozen=True, slots=True)
class HeartbeatStats:
    """Aggregate lease-heartbeat latency statistics."""

    count: int
    p50_ms: float
    p95_ms: float
    p99_ms: float
    max_ms: float
    mean_ms: float
    slo_ms: float
    within_slo: bool
    samples: tuple[HeartbeatSample, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "count": self.count,
            "p50_ms": self.p50_ms,
            "p95_ms": self.p95_ms,
            "p99_ms": self.p99_ms,
            "max_ms": self.max_ms,
            "mean_ms": self.mean_ms,
            "slo_ms": self.slo_ms,
            "within_slo": self.within_slo,
        }


def percentile(samples: Sequence[float], p: float) -> float:
    """Nearest-rank percentile for a finite sample (inclusive)."""

    if not samples:
        return 0.0
    if p <= 0:
        return float(min(samples))
    if p >= 100:
        return float(max(samples))
    ordered = sorted(float(x) for x in samples)
    # Nearest-rank: rank = ceil(p/100 * N), 1-indexed.
    rank = max(1, int(math.ceil((p / 100.0) * len(ordered))))
    return float(ordered[min(len(ordered), rank) - 1])


class LeaseHeartbeatMonitor:
    """Runs lease heartbeats on reserved control-plane capacity.

    The probe work itself is intentionally cheap (slot acquire + synthetic
    lease renewal). Latency is dominated by waiting for the reserved control
    slot, which must remain available even when analytical workers are fully
    saturated.
    """

    def __init__(
        self,
        capacity: ControlPlaneCapacity,
        *,
        interval_ms: int = DEFAULT_HEARTBEAT_INTERVAL_MS,
        slo_ms: float = DEFAULT_HEARTBEAT_P99_SLO_MS,
        work_ms: float = 0.2,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self._capacity = capacity
        self._interval_s = max(0.001, float(interval_ms) / 1000.0)
        self._slo_ms = float(slo_ms)
        self._work_s = max(0.0, float(work_ms) / 1000.0)
        self._clock = clock or time.monotonic
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._samples: list[HeartbeatSample] = []
        self._lock = threading.Lock()
        self._sequence = 0

    def start(self) -> None:
        if self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="lease-heartbeat-monitor",
            daemon=True,
        )
        self._thread.start()

    def stop(self, *, timeout: float = 5.0) -> HeartbeatStats:
        self._stop.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=timeout)
        self._thread = None
        return self.stats()

    def _run(self) -> None:
        while not self._stop.is_set():
            self._beat_once()
            # Interruptible sleep.
            self._stop.wait(self._interval_s)

    def _beat_once(self) -> None:
        started = self._clock()
        acquired = self._capacity.acquire_control(timeout=self._slo_ms / 1000.0 * 4.0)
        try:
            if acquired and self._work_s > 0:
                # Synthetic lease renewal body (hermetic; no I/O).
                time.sleep(self._work_s)
        finally:
            if acquired:
                self._capacity.release_control()
        finished = self._clock()
        latency_ms = max(0.0, (finished - started) * 1000.0)
        with self._lock:
            self._sequence += 1
            sample = HeartbeatSample(
                sequence=self._sequence,
                latency_ms=latency_ms,
                acquired_slot=bool(acquired),
                at_monotonic=finished,
            )
            self._samples.append(sample)

    def stats(self) -> HeartbeatStats:
        with self._lock:
            samples = tuple(self._samples)
        latencies = [s.latency_ms for s in samples]
        if not latencies:
            return HeartbeatStats(
                count=0,
                p50_ms=0.0,
                p95_ms=0.0,
                p99_ms=0.0,
                max_ms=0.0,
                mean_ms=0.0,
                slo_ms=self._slo_ms,
                within_slo=True,
                samples=(),
            )
        p99 = percentile(latencies, 99.0)
        return HeartbeatStats(
            count=len(latencies),
            p50_ms=percentile(latencies, 50.0),
            p95_ms=percentile(latencies, 95.0),
            p99_ms=p99,
            max_ms=float(max(latencies)),
            mean_ms=float(sum(latencies) / len(latencies)),
            slo_ms=self._slo_ms,
            within_slo=p99 <= self._slo_ms,
            samples=samples,
        )


# ---------------------------------------------------------------------------
# Subquery contracts
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TypedPartialFailure:
    """Typed partial / terminal failure for one subquery (or the join)."""

    kind: FailureKind
    domain: SubqueryDomain | None
    subquery_id: str
    message: str
    details: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.kind, FailureKind):
            raise ParallelQueryError("FAILURE", f"invalid kind {self.kind!r}")
        if self.domain is not None and not isinstance(self.domain, SubqueryDomain):
            raise ParallelQueryError("FAILURE", f"invalid domain {self.domain!r}")
        sid = str(self.subquery_id or "").strip()
        if not sid:
            raise ParallelQueryError("FAILURE", "subquery_id is required")
        object.__setattr__(self, "subquery_id", sid)
        object.__setattr__(self, "message", str(self.message or self.kind.value))
        object.__setattr__(
            self,
            "details",
            MappingProxyType(dict(self.details or {})),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind.value,
            "domain": self.domain.value if self.domain is not None else None,
            "subquery_id": self.subquery_id,
            "message": self.message,
            "details": dict(self.details),
        }


class SubqueryContext:
    """Per-worker execution context with deadline and cancellation checks.

    Lake workers (DQK-092) additionally observe catalog identity, exclusive
    connection identity, memory/spill caps, and optional close-before-release
    hooks so cancellation never leaves a renewable stale attachment.
    """

    __slots__ = (
        "subquery_id",
        "domain",
        "budget",
        "catalog_id",
        "connection_id",
        "_cancel",
        "_deadline_monotonic",
        "_started_monotonic",
        "_max_rows",
        "_memory_bytes",
        "_spill_bytes",
        "_on_cancel_close",
        "_closed",
        "_renewals",
        "_lock",
    )

    def __init__(
        self,
        *,
        subquery_id: str,
        domain: SubqueryDomain,
        budget: ParallelQueryBudget,
        cancel: RegistryCancellationToken | None,
        deadline_monotonic: float,
        max_rows: int,
        catalog_id: str = "",
        connection_id: str = "",
        on_cancel_close: Callable[[], None] | None = None,
    ) -> None:
        self.subquery_id = subquery_id
        self.domain = domain
        self.budget = budget
        self.catalog_id = str(catalog_id or "")
        self.connection_id = str(connection_id or "")
        self._cancel = cancel
        self._deadline_monotonic = float(deadline_monotonic)
        self._started_monotonic = time.monotonic()
        self._max_rows = int(max_rows)
        self._memory_bytes = 0
        self._spill_bytes = 0
        self._on_cancel_close = on_cancel_close
        self._closed = False
        self._renewals = 0
        self._lock = threading.Lock()

    @property
    def max_rows(self) -> int:
        return self._max_rows

    @property
    def max_memory_bytes(self) -> int:
        return int(self.budget.max_memory_bytes)

    @property
    def max_spill_bytes(self) -> int:
        return int(self.budget.max_spill_bytes)

    @property
    def max_bytes(self) -> int:
        return int(self.budget.max_bytes)

    @property
    def is_cancelled(self) -> bool:
        return bool(self._cancel is not None and self._cancel.is_cancelled)

    @property
    def cancel_reason(self) -> str:
        if self._cancel is None:
            return ""
        return self._cancel.reason or "cancelled"

    @property
    def renewals(self) -> int:
        return self._renewals

    @property
    def memory_bytes(self) -> int:
        return self._memory_bytes

    @property
    def spill_bytes(self) -> int:
        return self._spill_bytes

    @property
    def readers_closed(self) -> bool:
        return self._closed

    def remaining_ms(self) -> float:
        return max(0.0, (self._deadline_monotonic - time.monotonic()) * 1000.0)

    def elapsed_ms(self) -> float:
        return max(0.0, (time.monotonic() - self._started_monotonic) * 1000.0)

    def record_renewal(self) -> int:
        with self._lock:
            self._renewals += 1
            return self._renewals

    def record_memory(self, bytes_used: int) -> None:
        used = max(0, int(bytes_used))
        with self._lock:
            self._memory_bytes = max(self._memory_bytes, used)
        if used > self.budget.max_memory_bytes:
            raise QueryBudgetExceeded("memory", self.budget.max_memory_bytes)

    def record_spill(self, bytes_used: int) -> None:
        used = max(0, int(bytes_used))
        with self._lock:
            self._spill_bytes += used
            total = self._spill_bytes
        if total > self.budget.max_spill_bytes:
            raise QueryBudgetExceeded("spill", self.budget.max_spill_bytes)

    def close_readers(self) -> None:
        """Close remote readers/attachments before lease release (cancel path)."""

        with self._lock:
            if self._closed:
                return
            self._closed = True
            hook = self._on_cancel_close
        if hook is not None:
            hook()

    def set_close_hook(self, hook: Callable[[], None] | None) -> None:
        self._on_cancel_close = hook

    def check(self) -> None:
        """Raise typed errors when cancelled or past the analytical deadline.

        On cancellation, readers are closed before the exception propagates so
        lake workers never release a lease while attachments remain open.
        """

        if self._cancel is not None and self._cancel.is_cancelled:
            self.close_readers()
            raise QueryCancelled(self._cancel.reason or "cancelled")
        if time.monotonic() >= self._deadline_monotonic:
            self.close_readers()
            raise QueryBudgetExceeded("time", self.budget.analytical_time_ms)

    def resource_use(self, *, rows: int = 0, bytes_: int = 0) -> ResourceUse:
        return ResourceUse(
            rows=int(rows),
            bytes=int(bytes_),
            memory_bytes=self._memory_bytes,
            spill_bytes=self._spill_bytes,
            duration_ms=self.elapsed_ms(),
            connections=1 if self.connection_id else 0,
            renewals=self._renewals,
        )


class SubqueryRunner(Protocol):
    """Callable that executes one independent domain subquery."""

    def __call__(self, context: SubqueryContext) -> Sequence[Mapping[str, Any]]: ...


@dataclass(frozen=True, slots=True)
class SubquerySpec:
    """One independent graph/vector/proof/AST/wallet (or lake-shard) subquery."""

    subquery_id: str
    domain: SubqueryDomain
    runner: SubqueryRunner
    max_rows: int | None = None
    catalog_id: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        sid = str(self.subquery_id or "").strip()
        if not sid or len(sid) > 128:
            raise ParallelQueryError(
                "SPEC", f"invalid subquery_id {self.subquery_id!r}"
            )
        object.__setattr__(self, "subquery_id", sid)
        if not isinstance(self.domain, SubqueryDomain):
            try:
                object.__setattr__(self, "domain", SubqueryDomain(str(self.domain)))
            except ValueError as exc:
                raise ParallelQueryError(
                    "SPEC", f"unsupported domain {self.domain!r}"
                ) from exc
        if not callable(self.runner):
            raise ParallelQueryError("SPEC", "runner must be callable")
        if self.max_rows is not None:
            if (
                not isinstance(self.max_rows, int)
                or isinstance(self.max_rows, bool)
                or self.max_rows < 1
                or self.max_rows > MAX_ROWS_HARD
            ):
                raise ParallelQueryError(
                    "SPEC", f"max_rows out of range: {self.max_rows!r}"
                )
        cid = str(self.catalog_id or "").strip()
        object.__setattr__(self, "catalog_id", cid)
        meta = dict(self.metadata or {})
        if cid and "catalog_id" not in meta:
            meta["catalog_id"] = cid
        object.__setattr__(self, "metadata", MappingProxyType(meta))

    def to_dict(self) -> dict[str, Any]:
        return {
            "subquery_id": self.subquery_id,
            "domain": self.domain.value,
            "max_rows": self.max_rows,
            "catalog_id": self.catalog_id,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True, slots=True)
class ParallelQueryPlan:
    """Bounded plan of independent cross-domain subqueries."""

    subqueries: tuple[SubquerySpec, ...]
    budget: ParallelQueryBudget = field(default_factory=lambda: DEFAULT_PARALLEL_BUDGET)
    partial_failure_policy: PartialFailurePolicy = PartialFailurePolicy.CONTINUE
    join_policy: JoinPolicy = JoinPolicy.CONCAT
    snapshot: SnapshotId | None = None
    plan_id: str = ""

    def __post_init__(self) -> None:
        if not self.subqueries:
            raise ParallelQueryError("PLAN", "plan requires at least one subquery")
        if len(self.subqueries) > MAX_SUBQUERIES_HARD:
            raise ParallelQueryError(
                "PLAN", f"too many subqueries (>{MAX_SUBQUERIES_HARD})"
            )
        if not isinstance(self.budget, ParallelQueryBudget):
            raise ParallelQueryError("PLAN", "budget must be a ParallelQueryBudget")
        if not isinstance(self.partial_failure_policy, PartialFailurePolicy):
            raise ParallelQueryError("PLAN", "invalid partial_failure_policy")
        if not isinstance(self.join_policy, JoinPolicy):
            raise ParallelQueryError("PLAN", "invalid join_policy")

        seen: set[str] = set()
        domains: set[SubqueryDomain] = set()
        for spec in self.subqueries:
            if not isinstance(spec, SubquerySpec):
                raise ParallelQueryError("PLAN", "subqueries must be SubquerySpec")
            if spec.subquery_id in seen:
                raise ParallelQueryError(
                    "PLAN", f"duplicate subquery_id {spec.subquery_id!r}"
                )
            seen.add(spec.subquery_id)
            domains.add(spec.domain)

        object.__setattr__(self, "subqueries", tuple(self.subqueries))
        if self.snapshot is not None and not isinstance(self.snapshot, SnapshotId):
            object.__setattr__(self, "snapshot", parse_snapshot_id(self.snapshot))
        plan_id = str(self.plan_id or "").strip() or f"plan-{uuid.uuid4().hex[:16]}"
        object.__setattr__(self, "plan_id", plan_id)

    @property
    def domains(self) -> frozenset[SubqueryDomain]:
        return frozenset(s.domain for s in self.subqueries)

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "subqueries": [s.to_dict() for s in self.subqueries],
            "budget": self.budget.to_dict(),
            "partial_failure_policy": self.partial_failure_policy.value,
            "join_policy": self.join_policy.value,
            "snapshot": self.snapshot.to_dict() if self.snapshot is not None else None,
            "domains": sorted(d.value for d in self.domains),
        }


# ---------------------------------------------------------------------------
# Outcomes / receipts
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SubqueryOutcome:
    """Result of one concurrent subquery worker."""

    subquery_id: str
    domain: SubqueryDomain
    status: SubqueryStatus
    rows: tuple[Mapping[str, Any], ...]
    started_monotonic: float
    finished_monotonic: float
    duration_ms: float
    failure: TypedPartialFailure | None = None
    row_bytes: int = 0
    catalog_id: str = ""
    connection_id: str = ""
    resource_use: ResourceUse | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "rows", tuple(self.rows))
        if self.duration_ms < 0:
            object.__setattr__(self, "duration_ms", 0.0)
        object.__setattr__(self, "catalog_id", str(self.catalog_id or ""))
        object.__setattr__(self, "connection_id", str(self.connection_id or ""))
        if self.resource_use is not None and not isinstance(
            self.resource_use, ResourceUse
        ):
            raise ParallelQueryError("OUTCOME", "resource_use must be ResourceUse")

    @property
    def succeeded(self) -> bool:
        return self.status in {SubqueryStatus.SUCCEEDED, SubqueryStatus.TRUNCATED}

    def to_dict(self) -> dict[str, Any]:
        return {
            "subquery_id": self.subquery_id,
            "domain": self.domain.value,
            "status": self.status.value,
            "row_count": len(self.rows),
            "started_monotonic": self.started_monotonic,
            "finished_monotonic": self.finished_monotonic,
            "duration_ms": self.duration_ms,
            "row_bytes": self.row_bytes,
            "catalog_id": self.catalog_id,
            "connection_id": self.connection_id,
            "resource_use": (
                self.resource_use.to_dict() if self.resource_use is not None else None
            ),
            "failure": self.failure.to_dict() if self.failure is not None else None,
        }


@dataclass(frozen=True, slots=True)
class OverlapEvidence:
    """Proof that independent subqueries actually ran concurrently."""

    concurrent_pairs: tuple[tuple[str, str], ...]
    max_concurrency: int
    domains_that_overlapped: tuple[str, ...]
    independent_domains_overlapped: bool
    sample_intervals: tuple[dict[str, Any], ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "concurrent_pairs": [list(p) for p in self.concurrent_pairs],
            "max_concurrency": self.max_concurrency,
            "domains_that_overlapped": list(self.domains_that_overlapped),
            "independent_domains_overlapped": self.independent_domains_overlapped,
            "sample_intervals": list(self.sample_intervals),
        }


def intervals_overlap(
    a_start: float,
    a_end: float,
    b_start: float,
    b_end: float,
    *,
    epsilon: float = 1e-9,
) -> bool:
    """Return True when two half-open time intervals overlap."""

    if a_end < a_start or b_end < b_start:
        return False
    return (a_start < b_end - epsilon) and (b_start < a_end - epsilon)


def compute_overlap_evidence(
    outcomes: Sequence[SubqueryOutcome],
) -> OverlapEvidence:
    """Derive concurrency evidence from per-worker start/finish timestamps."""

    intervals = [
        (
            o.subquery_id,
            o.domain.value,
            float(o.started_monotonic),
            float(o.finished_monotonic),
        )
        for o in outcomes
        if o.status != SubqueryStatus.SKIPPED
    ]
    pairs: list[tuple[str, str]] = []
    domain_hits: set[str] = set()
    for i, (aid, ad, a0, a1) in enumerate(intervals):
        for bid, bd, b0, b1 in intervals[i + 1 :]:
            if intervals_overlap(a0, a1, b0, b1):
                ordered = tuple(sorted((aid, bid)))
                pairs.append((ordered[0], ordered[1]))  # type: ignore[arg-type]
                if ad != bd:
                    domain_hits.add(ad)
                    domain_hits.add(bd)

    # Sweep-line max concurrency.
    events: list[tuple[float, int]] = []
    for _, _, start, end in intervals:
        events.append((start, +1))
        events.append((end, -1))
    events.sort(key=lambda item: (item[0], -item[1]))
    current = 0
    max_conc = 0
    for _, delta in events:
        current += delta
        if current > max_conc:
            max_conc = current

    sample = [
        {
            "subquery_id": sid,
            "domain": dom,
            "started_monotonic": start,
            "finished_monotonic": end,
        }
        for sid, dom, start, end in intervals
    ]
    return OverlapEvidence(
        concurrent_pairs=tuple(pairs),
        max_concurrency=max_conc,
        domains_that_overlapped=tuple(sorted(domain_hits)),
        independent_domains_overlapped=len(domain_hits) >= 2,
        sample_intervals=tuple(sample),
    )


def compute_shard_overlap_evidence(
    outcomes: Sequence[SubqueryOutcome],
) -> dict[str, Any]:
    """Overlap evidence keyed by catalog/shard identity (DQK-092).

    Independent catalog shards must overlap without sharing connection
    identities. Same-catalog workers are permitted only when the connection
    pool serializes them under ``max_connections_per_catalog``.
    """

    intervals = [
        (
            o.subquery_id,
            o.catalog_id or str(o.domain.value),
            o.connection_id,
            float(o.started_monotonic),
            float(o.finished_monotonic),
        )
        for o in outcomes
        if o.status != SubqueryStatus.SKIPPED
    ]
    pairs: list[tuple[str, str]] = []
    shard_hits: set[str] = set()
    shared_connections: list[tuple[str, str, str]] = []
    for i, (aid, acat, aconn, a0, a1) in enumerate(intervals):
        for bid, bcat, bconn, b0, b1 in intervals[i + 1 :]:
            if not intervals_overlap(a0, a1, b0, b1):
                continue
            ordered = tuple(sorted((aid, bid)))
            pairs.append((ordered[0], ordered[1]))  # type: ignore[arg-type]
            if acat != bcat:
                shard_hits.add(acat)
                shard_hits.add(bcat)
            if aconn and bconn and aconn == bconn:
                shared_connections.append((aid, bid, aconn))

    events: list[tuple[float, int]] = []
    for _, _, _, start, end in intervals:
        events.append((start, +1))
        events.append((end, -1))
    events.sort(key=lambda item: (item[0], -item[1]))
    current = 0
    max_conc = 0
    for _, delta in events:
        current += delta
        if current > max_conc:
            max_conc = current

    connection_ids = [c for _, _, c, _, _ in intervals if c]
    return {
        "concurrent_pairs": [list(p) for p in pairs],
        "max_concurrency": max_conc,
        "shards_that_overlapped": sorted(shard_hits),
        "independent_shards_overlapped": len(shard_hits) >= 2,
        "shared_mutable_connections": shared_connections,
        "no_shared_mutable_connections": len(shared_connections) == 0,
        "distinct_connection_ids": len(set(connection_ids)),
        "sample_intervals": [
            {
                "subquery_id": sid,
                "catalog_id": cat,
                "connection_id": conn,
                "started_monotonic": start,
                "finished_monotonic": end,
            }
            for sid, cat, conn, start, end in intervals
        ],
    }


def join_bounded_results(
    outcomes: Sequence[SubqueryOutcome],
    *,
    policy: JoinPolicy = JoinPolicy.CONCAT,
    max_total_rows: int = DEFAULT_MAX_TOTAL_ROWS,
    max_bytes: int = DEFAULT_MAX_BYTES,
) -> tuple[tuple[Mapping[str, Any], ...], TypedPartialFailure | None]:
    """Join successful domain results under hard row/byte bounds."""

    if max_total_rows < 1:
        raise ParallelQueryError("JOIN", "max_total_rows must be >= 1")

    successes = [o for o in outcomes if o.succeeded]
    joined: list[Mapping[str, Any]] = []
    total_bytes = 0
    truncated = False

    def _append(domain: SubqueryDomain, row: Mapping[str, Any]) -> bool:
        nonlocal total_bytes, truncated
        if len(joined) >= max_total_rows:
            truncated = True
            return False
        projected = {
            "domain": domain.value,
            **{str(k): v for k, v in dict(row).items() if k != "domain"},
        }
        try:
            row_bytes = len(content_identity(projected).encode("utf-8"))
        except (ContractError, TypeError, ValueError):
            row_bytes = len(repr(projected).encode("utf-8", errors="replace"))
        if total_bytes + row_bytes > max_bytes:
            truncated = True
            return False
        total_bytes += row_bytes
        joined.append(MappingProxyType(projected))
        return True

    if policy is JoinPolicy.CONCAT:
        for outcome in successes:
            for row in outcome.rows:
                if not _append(outcome.domain, row):
                    break
            if truncated:
                break
    elif policy is JoinPolicy.ZIP_SHORTEST:
        if successes:
            limit = min(len(o.rows) for o in successes)
            for idx in range(limit):
                for outcome in successes:
                    if not _append(outcome.domain, outcome.rows[idx]):
                        break
                if truncated:
                    break
    else:
        raise ParallelQueryError("JOIN", f"unsupported join policy {policy!r}")

    failure: TypedPartialFailure | None = None
    if truncated:
        failure = TypedPartialFailure(
            kind=FailureKind.JOIN_TRUNCATED,
            domain=None,
            subquery_id="__join__",
            message="joined result exceeded max_total_rows or max_bytes",
            details={
                "max_total_rows": max_total_rows,
                "max_bytes": max_bytes,
                "row_count": len(joined),
                "bytes": total_bytes,
            },
        )
    return tuple(joined), failure


@dataclass(frozen=True, slots=True)
class ParallelQueryReceipt:
    """Deterministic receipt for one parallel plan execution."""

    schema: str
    plan_id: str
    run_id: str
    snapshot_identity: str | None
    status: str
    budget: Mapping[str, Any]
    outcomes: tuple[dict[str, Any], ...]
    partial_failures: tuple[dict[str, Any], ...]
    overlap: Mapping[str, Any]
    heartbeat: Mapping[str, Any]
    capacity: Mapping[str, Any]
    joined_row_count: int
    joined_truncated: bool
    duration_ms: float
    created_at: str
    implementation_generation: str = PARALLEL_QUERY_IMPLEMENTATION_GENERATION
    resource_use: Mapping[str, Any] = field(default_factory=dict)
    shard_overlap: Mapping[str, Any] = field(default_factory=dict)
    catalog_capacity: Mapping[str, Any] = field(default_factory=dict)
    partial_failure_policy: str = ""
    result_digest: str = ""

    @property
    def identity_id(self) -> str:
        payload = {
            "schema": self.schema,
            "plan_id": self.plan_id,
            "run_id": self.run_id,
            "snapshot_identity": self.snapshot_identity,
            "status": self.status,
            "budget": dict(self.budget),
            "outcomes": list(self.outcomes),
            "partial_failures": list(self.partial_failures),
            "overlap": dict(self.overlap),
            "heartbeat": {
                k: self.heartbeat[k]
                for k in (
                    "count",
                    "p50_ms",
                    "p95_ms",
                    "p99_ms",
                    "max_ms",
                    "mean_ms",
                    "slo_ms",
                    "within_slo",
                )
                if k in self.heartbeat
            },
            "capacity": dict(self.capacity),
            "joined_row_count": self.joined_row_count,
            "joined_truncated": self.joined_truncated,
            "duration_ms": self.duration_ms,
            "created_at": self.created_at,
            "implementation_generation": self.implementation_generation,
            "resource_use": dict(self.resource_use or {}),
            "shard_overlap": dict(self.shard_overlap or {}),
            "catalog_capacity": dict(self.catalog_capacity or {}),
            "partial_failure_policy": self.partial_failure_policy,
            "result_digest": self.result_digest,
        }
        return content_identity(payload)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "plan_id": self.plan_id,
            "run_id": self.run_id,
            "snapshot_identity": self.snapshot_identity,
            "status": self.status,
            "budget": dict(self.budget),
            "outcomes": list(self.outcomes),
            "partial_failures": list(self.partial_failures),
            "overlap": dict(self.overlap),
            "heartbeat": dict(self.heartbeat),
            "capacity": dict(self.capacity),
            "joined_row_count": self.joined_row_count,
            "joined_truncated": self.joined_truncated,
            "duration_ms": self.duration_ms,
            "created_at": self.created_at,
            "implementation_generation": self.implementation_generation,
            "resource_use": dict(self.resource_use or {}),
            "shard_overlap": dict(self.shard_overlap or {}),
            "catalog_capacity": dict(self.catalog_capacity or {}),
            "partial_failure_policy": self.partial_failure_policy,
            "result_digest": self.result_digest,
            "identity_id": self.identity_id,
        }


@dataclass(frozen=True, slots=True)
class ParallelQueryResult:
    """Joined rows plus outcomes, overlap evidence, heartbeats, and receipt."""

    rows: tuple[Mapping[str, Any], ...]
    outcomes: tuple[SubqueryOutcome, ...]
    partial_failures: tuple[TypedPartialFailure, ...]
    overlap: OverlapEvidence
    heartbeat: HeartbeatStats
    receipt: ParallelQueryReceipt

    @property
    def status(self) -> str:
        return self.receipt.status

    @property
    def independent_domains_overlapped(self) -> bool:
        return self.overlap.independent_domains_overlapped

    @property
    def heartbeat_within_slo(self) -> bool:
        return self.heartbeat.within_slo

    def outcome_for(self, subquery_id: str) -> SubqueryOutcome | None:
        for outcome in self.outcomes:
            if outcome.subquery_id == subquery_id:
                return outcome
        return None

    def failures_of_kind(self, kind: FailureKind) -> tuple[TypedPartialFailure, ...]:
        return tuple(f for f in self.partial_failures if f.kind is kind)

    def to_dict(self) -> dict[str, Any]:
        return {
            "rows": [dict(r) for r in self.rows],
            "outcomes": [o.to_dict() for o in self.outcomes],
            "partial_failures": [f.to_dict() for f in self.partial_failures],
            "overlap": self.overlap.to_dict(),
            "heartbeat": self.heartbeat.to_dict(),
            "receipt": self.receipt.to_dict(),
        }


# ---------------------------------------------------------------------------
# Scheduler
# ---------------------------------------------------------------------------


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def _estimate_row_bytes(row: Mapping[str, Any]) -> int:
    try:
        return len(content_identity(dict(row)).encode("utf-8"))
    except (ContractError, TypeError, ValueError):
        return len(repr(row).encode("utf-8", errors="replace"))


def _map_exception_to_failure(
    *,
    subquery_id: str,
    domain: SubqueryDomain,
    exc: BaseException,
) -> tuple[SubqueryStatus, TypedPartialFailure]:
    if isinstance(exc, QueryCancelled):
        return SubqueryStatus.CANCELLED, TypedPartialFailure(
            kind=FailureKind.CANCELLED,
            domain=domain,
            subquery_id=subquery_id,
            message=str(exc) or "cancelled",
        )
    if isinstance(exc, QueryBudgetExceeded):
        kind = (
            FailureKind.TIMEOUT
            if getattr(exc, "kind", "") == "time"
            else FailureKind.BUDGET_EXCEEDED
        )
        status = (
            SubqueryStatus.TIMEOUT
            if kind is FailureKind.TIMEOUT
            else SubqueryStatus.BUDGET_EXCEEDED
        )
        return status, TypedPartialFailure(
            kind=kind,
            domain=domain,
            subquery_id=subquery_id,
            message=str(exc),
            details={"budget_kind": getattr(exc, "kind", ""), "limit": getattr(exc, "limit", None)},
        )
    if isinstance(exc, ParallelQueryError) and exc.code == "CAPACITY":
        return SubqueryStatus.CAPACITY_DENIED, TypedPartialFailure(
            kind=FailureKind.CAPACITY_DENIED,
            domain=domain,
            subquery_id=subquery_id,
            message=str(exc),
            details=dict(exc.details),
        )
    if isinstance(exc, (QueryRegistryError, ParallelQueryError)):
        return SubqueryStatus.FAILED, TypedPartialFailure(
            kind=FailureKind.EXECUTION_ERROR,
            domain=domain,
            subquery_id=subquery_id,
            message=str(exc),
        )
    return SubqueryStatus.FAILED, TypedPartialFailure(
        kind=FailureKind.EXECUTION_ERROR,
        domain=domain,
        subquery_id=subquery_id,
        message=f"{type(exc).__name__}: {exc}",
        details={"exception_type": type(exc).__name__},
    )


class ParallelQueryScheduler:
    """Trusted broker that fans out independent domain subqueries concurrently.

    The scheduler:

    1. Reserves control-plane capacity for lease heartbeats.
    2. Starts a lease-heartbeat monitor on reserved slots.
    3. Executes independent domain runners under a shared deadline + cancel token.
    4. Bounds per-catalog connection fan-out (DQK-092) without sharing handles.
    5. Joins bounded domain-tagged results.
    6. Emits typed partial failures and a deterministic receipt.
    """

    def __init__(
        self,
        *,
        capacity: ControlPlaneCapacity | None = None,
        catalog_pool: CatalogConnectionPool | None = None,
        clock: Callable[[], float] | None = None,
        wall_clock: Callable[[], str] | None = None,
        heartbeat_work_ms: float = 0.2,
    ) -> None:
        self._capacity = capacity
        self._catalog_pool = catalog_pool
        self._clock = clock or time.monotonic
        self._wall_clock = wall_clock or _utc_now
        self._heartbeat_work_ms = float(heartbeat_work_ms)
        self._lock = threading.Lock()

    @property
    def capacity(self) -> ControlPlaneCapacity | None:
        return self._capacity

    @property
    def catalog_pool(self) -> CatalogConnectionPool | None:
        return self._catalog_pool

    def run(
        self,
        plan: ParallelQueryPlan,
        *,
        cancellation: RegistryCancellationToken | None = None,
        deadline_monotonic: float | None = None,
        run_heartbeat_monitor: bool = True,
    ) -> ParallelQueryResult:
        """Execute ``plan`` concurrently and return joined, typed results."""

        if not isinstance(plan, ParallelQueryPlan):
            raise ParallelQueryError("PLAN", "plan must be a ParallelQueryPlan")

        started = self._clock()
        budget = plan.budget
        capacity = self._capacity or ControlPlaneCapacity(
            total_slots=budget.total_slots,
            reserved_control_plane_slots=budget.reserved_control_plane_slots,
        )
        catalog_pool = self._catalog_pool or CatalogConnectionPool(
            max_connections_per_catalog=budget.max_connections_per_catalog,
        )

        if cancellation is not None and cancellation.is_cancelled:
            return self._cancelled_before_start(plan, started, capacity, catalog_pool)

        analytical_deadline = started + (budget.analytical_time_ms / 1000.0)
        if deadline_monotonic is not None:
            analytical_deadline = min(analytical_deadline, float(deadline_monotonic))

        monitor: LeaseHeartbeatMonitor | None = None
        if run_heartbeat_monitor:
            monitor = LeaseHeartbeatMonitor(
                capacity,
                interval_ms=budget.heartbeat_interval_ms,
                slo_ms=budget.heartbeat_p99_slo_ms,
                work_ms=self._heartbeat_work_ms,
                clock=self._clock,
            )
            monitor.start()

        cancel = cancellation or RegistryCancellationToken()
        outcomes: list[SubqueryOutcome] = []
        fail_fast_triggered = threading.Event()

        try:
            max_workers = min(budget.max_workers, len(plan.subqueries), budget.analytical_slots)
            with ThreadPoolExecutor(
                max_workers=max(1, max_workers),
                thread_name_prefix="dqk042-subquery",
            ) as pool:
                future_map: dict[Future[SubqueryOutcome], SubquerySpec] = {}
                for spec in plan.subqueries:
                    future = pool.submit(
                        self._run_one,
                        spec=spec,
                        budget=budget,
                        capacity=capacity,
                        catalog_pool=catalog_pool,
                        cancel=cancel,
                        deadline_monotonic=analytical_deadline,
                        fail_fast=fail_fast_triggered,
                        policy=plan.partial_failure_policy,
                    )
                    future_map[future] = spec

                pending = set(future_map)
                while pending:
                    # Bound wait so we can enforce the analytical deadline and
                    # fail-fast cancellation even if a worker ignores checks.
                    remaining = max(0.0, analytical_deadline - self._clock())
                    done, pending = wait(
                        pending,
                        timeout=min(0.05, remaining) if remaining > 0 else 0.0,
                        return_when=FIRST_COMPLETED,
                    )
                    for future in done:
                        try:
                            outcome = future.result()
                        except Exception as exc:  # noqa: BLE001 — typed at boundary
                            spec = future_map[future]
                            status, failure = _map_exception_to_failure(
                                subquery_id=spec.subquery_id,
                                domain=spec.domain,
                                exc=exc,
                            )
                            now = self._clock()
                            outcome = SubqueryOutcome(
                                subquery_id=spec.subquery_id,
                                domain=spec.domain,
                                status=status,
                                rows=(),
                                started_monotonic=now,
                                finished_monotonic=now,
                                duration_ms=0.0,
                                failure=failure,
                                catalog_id=spec.catalog_id,
                            )
                        outcomes.append(outcome)
                        if (
                            plan.partial_failure_policy is PartialFailurePolicy.FAIL_FAST
                            and not outcome.succeeded
                        ):
                            fail_fast_triggered.set()
                            cancel.cancel(
                                f"fail_fast:{outcome.subquery_id}:{outcome.status.value}"
                            )

                    # Global analytical deadline: cancel remaining work.
                    if self._clock() >= analytical_deadline and pending:
                        cancel.cancel("analytical_deadline_exceeded")
                        fail_fast_triggered.set()

                    if cancel.is_cancelled and pending and not done:
                        # Nudge wait loop; workers should observe cancel.
                        continue

                # Drain any stragglers that finished after deadline cancel.
                for future in list(pending):
                    try:
                        outcomes.append(future.result(timeout=0.5))
                    except Exception as exc:  # noqa: BLE001
                        spec = future_map[future]
                        status, failure = _map_exception_to_failure(
                            subquery_id=spec.subquery_id,
                            domain=spec.domain,
                            exc=exc,
                        )
                        now = self._clock()
                        outcomes.append(
                            SubqueryOutcome(
                                subquery_id=spec.subquery_id,
                                domain=spec.domain,
                                status=status,
                                rows=(),
                                started_monotonic=now,
                                finished_monotonic=now,
                                duration_ms=0.0,
                                failure=failure,
                                catalog_id=spec.catalog_id,
                            )
                        )
        finally:
            heartbeat = (
                monitor.stop(timeout=2.0)
                if monitor is not None
                else HeartbeatStats(
                    count=0,
                    p50_ms=0.0,
                    p95_ms=0.0,
                    p99_ms=0.0,
                    max_ms=0.0,
                    mean_ms=0.0,
                    slo_ms=budget.heartbeat_p99_slo_ms,
                    within_slo=True,
                    samples=(),
                )
            )

        # Preserve plan order for deterministic receipts.
        by_id = {o.subquery_id: o for o in outcomes}
        ordered = tuple(
            by_id[s.subquery_id]
            for s in plan.subqueries
            if s.subquery_id in by_id
        )
        # Include any unexpected extras deterministically.
        extras = tuple(
            o for o in outcomes if o.subquery_id not in {s.subquery_id for s in plan.subqueries}
        )
        ordered = ordered + extras

        joined_rows, join_failure = join_bounded_results(
            ordered,
            policy=plan.join_policy,
            max_total_rows=budget.max_total_rows,
            max_bytes=budget.max_bytes,
        )

        partials: list[TypedPartialFailure] = []
        for outcome in ordered:
            if outcome.failure is not None:
                partials.append(outcome.failure)
        if join_failure is not None:
            partials.append(join_failure)

        overlap = compute_overlap_evidence(ordered)
        shard_overlap = compute_shard_overlap_evidence(ordered)
        finished = self._clock()
        duration_ms = max(0.0, (finished - started) * 1000.0)
        status = self._overall_status(
            plan=plan,
            outcomes=ordered,
            partials=partials,
            heartbeat=heartbeat,
        )

        snapshot_identity: str | None = None
        if plan.snapshot is not None:
            snapshot_identity = plan.snapshot.identity_id

        resource = ResourceUse(duration_ms=duration_ms)
        for outcome in ordered:
            if outcome.resource_use is not None:
                resource = resource.merge(outcome.resource_use)
            else:
                resource = resource.merge(
                    ResourceUse(
                        rows=len(outcome.rows),
                        bytes=outcome.row_bytes,
                        duration_ms=outcome.duration_ms,
                        connections=1 if outcome.connection_id else 0,
                    )
                )

        result_digest = content_identity(
            {
                "plan_id": plan.plan_id,
                "rows": [dict(r) for r in joined_rows],
                "status": status,
                "partial_failures": [f.to_dict() for f in partials],
            }
        )

        receipt = ParallelQueryReceipt(
            schema=PARALLEL_RECEIPT_SCHEMA,
            plan_id=plan.plan_id,
            run_id=f"run-{uuid.uuid4().hex}",
            snapshot_identity=snapshot_identity,
            status=status,
            budget=MappingProxyType(plan.budget.to_dict()),
            outcomes=tuple(o.to_dict() for o in ordered),
            partial_failures=tuple(f.to_dict() for f in partials),
            overlap=MappingProxyType(overlap.to_dict()),
            heartbeat=MappingProxyType(heartbeat.to_dict()),
            capacity=MappingProxyType(capacity.snapshot()),
            joined_row_count=len(joined_rows),
            joined_truncated=join_failure is not None,
            duration_ms=duration_ms,
            created_at=normalize_timestamp(self._wall_clock())
            if callable(self._wall_clock)
            else _utc_now(),
            resource_use=MappingProxyType(resource.to_dict()),
            shard_overlap=MappingProxyType(shard_overlap),
            catalog_capacity=MappingProxyType(catalog_pool.snapshot()),
            partial_failure_policy=plan.partial_failure_policy.value,
            result_digest=result_digest,
        )

        return ParallelQueryResult(
            rows=joined_rows,
            outcomes=ordered,
            partial_failures=tuple(partials),
            overlap=overlap,
            heartbeat=heartbeat,
            receipt=receipt,
        )

    def _run_one(
        self,
        *,
        spec: SubquerySpec,
        budget: ParallelQueryBudget,
        capacity: ControlPlaneCapacity,
        catalog_pool: CatalogConnectionPool,
        cancel: RegistryCancellationToken,
        deadline_monotonic: float,
        fail_fast: threading.Event,
        policy: PartialFailurePolicy,
    ) -> SubqueryOutcome:
        started = self._clock()
        catalog_id = spec.catalog_id or str(spec.metadata.get("catalog_id") or "")
        connection_id = ""
        catalog_acquired = False

        if cancel.is_cancelled or fail_fast.is_set():
            failure = TypedPartialFailure(
                kind=FailureKind.CANCELLED,
                domain=spec.domain,
                subquery_id=spec.subquery_id,
                message=cancel.reason or "cancelled_before_start",
            )
            finished = self._clock()
            return SubqueryOutcome(
                subquery_id=spec.subquery_id,
                domain=spec.domain,
                status=SubqueryStatus.CANCELLED,
                rows=(),
                started_monotonic=started,
                finished_monotonic=finished,
                duration_ms=max(0.0, (finished - started) * 1000.0),
                failure=failure,
                catalog_id=catalog_id,
            )

        remaining = max(0.0, deadline_monotonic - self._clock())
        acquired = capacity.acquire_analytical(timeout=remaining)
        if not acquired:
            finished = self._clock()
            # Distinguish deadline vs pure capacity exhaustion.
            if self._clock() >= deadline_monotonic:
                kind = FailureKind.DEADLINE_EXCEEDED
                status = SubqueryStatus.TIMEOUT
                message = "analytical deadline exceeded while waiting for capacity"
            else:
                kind = FailureKind.CAPACITY_DENIED
                status = SubqueryStatus.CAPACITY_DENIED
                message = "analytical capacity denied (backpressure)"
            failure = TypedPartialFailure(
                kind=kind,
                domain=spec.domain,
                subquery_id=spec.subquery_id,
                message=message,
            )
            return SubqueryOutcome(
                subquery_id=spec.subquery_id,
                domain=spec.domain,
                status=status,
                rows=(),
                started_monotonic=started,
                finished_monotonic=finished,
                duration_ms=max(0.0, (finished - started) * 1000.0),
                failure=failure,
                catalog_id=catalog_id,
            )

        try:
            # Per-catalog connection slot (distinct catalogs never contend).
            pool_key = catalog_id or f"__domain__:{spec.domain.value}:{spec.subquery_id}"
            remaining = max(0.0, deadline_monotonic - self._clock())
            connection_id_or_none = catalog_pool.acquire(
                pool_key,
                timeout=remaining,
                owner_token=spec.subquery_id,
            )
            if connection_id_or_none is None:
                finished = self._clock()
                if self._clock() >= deadline_monotonic:
                    kind = FailureKind.DEADLINE_EXCEEDED
                    status = SubqueryStatus.TIMEOUT
                    message = (
                        "analytical deadline exceeded while waiting for "
                        "per-catalog connection capacity"
                    )
                else:
                    kind = FailureKind.CAPACITY_DENIED
                    status = SubqueryStatus.CAPACITY_DENIED
                    message = (
                        f"per-catalog connection capacity denied for {pool_key!r}"
                    )
                failure = TypedPartialFailure(
                    kind=kind,
                    domain=spec.domain,
                    subquery_id=spec.subquery_id,
                    message=message,
                    details={"catalog_id": catalog_id or pool_key},
                )
                return SubqueryOutcome(
                    subquery_id=spec.subquery_id,
                    domain=spec.domain,
                    status=status,
                    rows=(),
                    started_monotonic=started,
                    finished_monotonic=finished,
                    duration_ms=max(0.0, (finished - started) * 1000.0),
                    failure=failure,
                    catalog_id=catalog_id,
                )
            connection_id = connection_id_or_none
            catalog_acquired = True

            max_rows = (
                int(spec.max_rows)
                if spec.max_rows is not None
                else int(budget.max_rows_per_subquery)
            )
            context = SubqueryContext(
                subquery_id=spec.subquery_id,
                domain=spec.domain,
                budget=budget,
                cancel=cancel,
                deadline_monotonic=deadline_monotonic,
                max_rows=max_rows,
                catalog_id=catalog_id,
                connection_id=connection_id,
            )

            try:
                context.check()
                raw_rows = spec.runner(context)
                if raw_rows is None:
                    raw_rows = ()
                if not isinstance(raw_rows, Sequence) or isinstance(
                    raw_rows, (str, bytes)
                ):
                    raise ParallelQueryError(
                        "EXEC",
                        "subquery runner must return a sequence of row mappings",
                    )

                projected: list[Mapping[str, Any]] = []
                total_bytes = 0
                truncated = False
                for row in raw_rows:
                    context.check()
                    if fail_fast.is_set() or cancel.is_cancelled:
                        raise QueryCancelled(cancel.reason or "cancelled")
                    if not isinstance(row, Mapping):
                        raise ParallelQueryError("EXEC", "row must be a mapping")
                    if len(projected) >= max_rows:
                        truncated = True
                        break
                    row_bytes = _estimate_row_bytes(row)
                    if total_bytes + row_bytes > budget.max_bytes:
                        truncated = True
                        break
                    # Memory budget tracks materialization peak (row bag size).
                    context.record_memory(total_bytes + row_bytes)
                    total_bytes += row_bytes
                    projected.append(MappingProxyType(dict(row)))

                finished = self._clock()
                status = (
                    SubqueryStatus.TRUNCATED if truncated else SubqueryStatus.SUCCEEDED
                )
                use = context.resource_use(rows=len(projected), bytes_=total_bytes)
                return SubqueryOutcome(
                    subquery_id=spec.subquery_id,
                    domain=spec.domain,
                    status=status,
                    rows=tuple(projected),
                    started_monotonic=started,
                    finished_monotonic=finished,
                    duration_ms=max(0.0, (finished - started) * 1000.0),
                    failure=None,
                    row_bytes=total_bytes,
                    catalog_id=catalog_id,
                    connection_id=connection_id,
                    resource_use=use,
                )
            except BaseException as exc:  # noqa: BLE001 — mapped to typed failure
                # Ensure readers close on any failure path before slot release.
                context.close_readers()
                finished = self._clock()
                # Deadline race: map budget/time errors that happen near deadline.
                if (
                    isinstance(exc, QueryBudgetExceeded)
                    and getattr(exc, "kind", "") == "time"
                ) or (
                    not isinstance(exc, QueryCancelled)
                    and self._clock() >= deadline_monotonic
                    and not isinstance(exc, ParallelQueryError)
                ):
                    if isinstance(exc, QueryBudgetExceeded):
                        status, failure = _map_exception_to_failure(
                            subquery_id=spec.subquery_id,
                            domain=spec.domain,
                            exc=exc,
                        )
                    else:
                        status = SubqueryStatus.TIMEOUT
                        failure = TypedPartialFailure(
                            kind=FailureKind.TIMEOUT,
                            domain=spec.domain,
                            subquery_id=spec.subquery_id,
                            message="analytical deadline exceeded during execution",
                            details={"exception_type": type(exc).__name__},
                        )
                else:
                    status, failure = _map_exception_to_failure(
                        subquery_id=spec.subquery_id,
                        domain=spec.domain,
                        exc=exc,
                    )
                use = context.resource_use(rows=0, bytes_=0)
                return SubqueryOutcome(
                    subquery_id=spec.subquery_id,
                    domain=spec.domain,
                    status=status,
                    rows=(),
                    started_monotonic=started,
                    finished_monotonic=finished,
                    duration_ms=max(0.0, (finished - started) * 1000.0),
                    failure=failure,
                    catalog_id=catalog_id,
                    connection_id=connection_id,
                    resource_use=use,
                )
        finally:
            if catalog_acquired and connection_id:
                catalog_pool.release(
                    catalog_id or f"__domain__:{spec.domain.value}:{spec.subquery_id}",
                    connection_id,
                )
            capacity.release_analytical()

    def _overall_status(
        self,
        *,
        plan: ParallelQueryPlan,
        outcomes: Sequence[SubqueryOutcome],
        partials: Sequence[TypedPartialFailure],
        heartbeat: HeartbeatStats,
    ) -> str:
        if not outcomes:
            return "failed"
        successes = sum(1 for o in outcomes if o.succeeded)
        all_ok = successes == len(outcomes) and not any(
            f.kind is not FailureKind.JOIN_TRUNCATED for f in partials
        )
        if plan.partial_failure_policy is PartialFailurePolicy.REQUIRE_ALL:
            if successes != len(outcomes):
                return "failed"
        if successes == 0:
            # Prefer the most specific aggregate label.
            kinds = {o.status for o in outcomes}
            if kinds <= {SubqueryStatus.CANCELLED}:
                return "cancelled"
            if kinds <= {SubqueryStatus.TIMEOUT, SubqueryStatus.CANCELLED}:
                return "timeout"
            return "failed"
        if all_ok and not any(f.kind is FailureKind.JOIN_TRUNCATED for f in partials):
            status = "succeeded"
        elif successes == len(outcomes):
            status = "truncated"
        else:
            status = "partial"
        # Heartbeat SLO breach is reported on the receipt; it does not rewrite
        # a successful analytical join into failure, but is visible via
        # heartbeat.within_slo for gates.
        _ = heartbeat
        return status

    def _cancelled_before_start(
        self,
        plan: ParallelQueryPlan,
        started: float,
        capacity: ControlPlaneCapacity,
        catalog_pool: CatalogConnectionPool | None = None,
    ) -> ParallelQueryResult:
        outcomes = []
        partials = []
        for spec in plan.subqueries:
            failure = TypedPartialFailure(
                kind=FailureKind.CANCELLED,
                domain=spec.domain,
                subquery_id=spec.subquery_id,
                message="cancelled_before_start",
            )
            partials.append(failure)
            outcomes.append(
                SubqueryOutcome(
                    subquery_id=spec.subquery_id,
                    domain=spec.domain,
                    status=SubqueryStatus.CANCELLED,
                    rows=(),
                    started_monotonic=started,
                    finished_monotonic=started,
                    duration_ms=0.0,
                    failure=failure,
                    catalog_id=spec.catalog_id,
                )
            )
        ordered = tuple(outcomes)
        overlap = compute_overlap_evidence(ordered)
        shard_overlap = compute_shard_overlap_evidence(ordered)
        heartbeat = HeartbeatStats(
            count=0,
            p50_ms=0.0,
            p95_ms=0.0,
            p99_ms=0.0,
            max_ms=0.0,
            mean_ms=0.0,
            slo_ms=plan.budget.heartbeat_p99_slo_ms,
            within_slo=True,
            samples=(),
        )
        pool = catalog_pool or CatalogConnectionPool(
            max_connections_per_catalog=plan.budget.max_connections_per_catalog
        )
        receipt = ParallelQueryReceipt(
            schema=PARALLEL_RECEIPT_SCHEMA,
            plan_id=plan.plan_id,
            run_id=f"run-{uuid.uuid4().hex}",
            snapshot_identity=(
                plan.snapshot.identity_id if plan.snapshot is not None else None
            ),
            status="cancelled",
            budget=MappingProxyType(plan.budget.to_dict()),
            outcomes=tuple(o.to_dict() for o in ordered),
            partial_failures=tuple(f.to_dict() for f in partials),
            overlap=MappingProxyType(overlap.to_dict()),
            heartbeat=MappingProxyType(heartbeat.to_dict()),
            capacity=MappingProxyType(capacity.snapshot()),
            joined_row_count=0,
            joined_truncated=False,
            duration_ms=0.0,
            created_at=_utc_now(),
            resource_use=MappingProxyType(ResourceUse().to_dict()),
            shard_overlap=MappingProxyType(shard_overlap),
            catalog_capacity=MappingProxyType(pool.snapshot()),
            partial_failure_policy=plan.partial_failure_policy.value,
            result_digest=content_identity(
                {"plan_id": plan.plan_id, "status": "cancelled", "rows": []}
            ),
        )
        return ParallelQueryResult(
            rows=(),
            outcomes=ordered,
            partial_failures=tuple(partials),
            overlap=overlap,
            heartbeat=heartbeat,
            receipt=receipt,
        )


def open_default_scheduler(
    *,
    total_slots: int = DEFAULT_TOTAL_SLOTS,
    reserved_control_plane_slots: int = DEFAULT_RESERVED_CONTROL_PLANE_SLOTS,
    max_connections_per_catalog: int = DEFAULT_MAX_CONNECTIONS_PER_CATALOG,
) -> ParallelQueryScheduler:
    """Construct a scheduler with an explicit capacity pool."""

    capacity = ControlPlaneCapacity(
        total_slots=total_slots,
        reserved_control_plane_slots=reserved_control_plane_slots,
    )
    catalog_pool = CatalogConnectionPool(
        max_connections_per_catalog=max_connections_per_catalog
    )
    return ParallelQueryScheduler(capacity=capacity, catalog_pool=catalog_pool)
