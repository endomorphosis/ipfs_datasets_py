"""Process-safe CPU and memory leases for nested LegalIR runtimes.

The optimizer launches work from several independently managed processes:
hammer requests, ATP/SMT portfolios, Lean reconstruction, validation, and
Codex workers.  Per-component thread-pool limits are insufficient because a
pool can itself launch another pool.  This module provides one host-local,
file-backed scheduler whose *root* leases consume global capacity and whose
child leases consume their parent's already-accounted envelope.

The state file contains identifiers and resource counts only.  It is guarded
by an OS advisory lock and is therefore shared by unrelated Python processes;
no manager process or inherited semaphore is required.  Lease owners publish
heartbeats and process birth markers, allowing capacity to be recovered after
a crash without confusing a recycled PID for the original owner.
"""

from __future__ import annotations

import json
import math
import os
import tempfile
import threading
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, Mapping, Optional, Protocol, Union

try:  # pragma: no cover - all supported production targets are POSIX today.
    import fcntl
except ImportError:  # pragma: no cover
    fcntl = None  # type: ignore[assignment]

from ipfs_datasets_py.optimizers.logic_theorem_optimizer.runtime_telemetry import (
    ResourceSnapshot,
    collect_resource_snapshot,
)


RESOURCE_SCHEDULER_SCHEMA_VERSION = "legal-ir-global-resource-scheduler-v1"
DEFAULT_STATE_ENV = "IPFS_DATASETS_RESOURCE_SCHEDULER_PATH"
DEFAULT_CPU_ENV = "IPFS_DATASETS_RESOURCE_CPU_SLOTS"
DEFAULT_MEMORY_ENV = "IPFS_DATASETS_RESOURCE_MEMORY_MB"
DEFAULT_GPU_MEMORY_ENV = "IPFS_DATASETS_RESOURCE_GPU_MEMORY_MB"


class ResourceLane(str, Enum):
    """Stable reservation lanes used by the parallel LegalIR runtime."""

    HAMMER_LEAN = "hammer_lean"
    CODEX = "codex"
    VALIDATION = "validation"
    ORCHESTRATION = "orchestration"
    RESERVE = "reserve"


DEFAULT_LANE_CPU_RESERVATIONS: Mapping[str, int] = {
    ResourceLane.HAMMER_LEAN.value: 8,
    ResourceLane.CODEX.value: 4,
    ResourceLane.VALIDATION.value: 4,
    ResourceLane.ORCHESTRATION.value: 2,
    ResourceLane.RESERVE.value: 2,
}


class CancellationSignal(Protocol):
    def is_set(self) -> bool: ...


class ResourceSchedulerError(RuntimeError):
    """Base class for resource scheduler failures."""


class ResourceConfigurationError(ResourceSchedulerError, ValueError):
    """The configured capacities or reservations are inconsistent."""


class ResourceUnavailableError(ResourceSchedulerError):
    """A request can never fit inside its global or parent capacity."""


class LeaseTimeoutError(ResourceSchedulerError, TimeoutError):
    """A resource request did not acquire a lease before its deadline."""


class LeaseCancelledError(ResourceSchedulerError):
    """A waiting request or one of its parent leases was cancelled."""


class LeaseNotFoundError(ResourceSchedulerError):
    """A requested parent or active lease no longer exists."""


class SchedulerStateError(ResourceSchedulerError):
    """The shared state is corrupt or incompatible with this scheduler."""


ResourcePressureSampler = Callable[[], ResourceSnapshot | Mapping[str, Any]]


@dataclass(frozen=True)
class SchedulerPressureSummary:
    """Normalized source-free pressure evidence for adaptive worker decisions."""

    cpu_utilization: float = 0.0
    memory_pressure: float = 0.0
    swap_pressure: float = 0.0
    gpu_memory_pressure: float = 0.0
    gpu_utilization: float = 0.0
    gpu_telemetry_known: bool = True
    child_process_count: int = 0
    child_process_limit: int = 64
    active_child_lease_count: int = 0
    waiting_request_count: int = 0
    saturation_events_total: int = 0

    @staticmethod
    def _ratio(value: Any) -> float:
        try:
            result = float(value)
        except (TypeError, ValueError):
            return 0.0
        if not math.isfinite(result) or result < 0.0:
            return 0.0
        if result > 1.0:
            result /= 100.0
        return max(0.0, min(1.0, result))

    def __post_init__(self) -> None:
        for name in (
            "cpu_utilization",
            "memory_pressure",
            "swap_pressure",
            "gpu_memory_pressure",
            "gpu_utilization",
        ):
            object.__setattr__(self, name, self._ratio(getattr(self, name)))
        for name in (
            "child_process_count",
            "child_process_limit",
            "active_child_lease_count",
            "waiting_request_count",
            "saturation_events_total",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ResourceConfigurationError(f"{name} must be a non-negative integer")
        if self.child_process_limit <= 0:
            raise ResourceConfigurationError("child_process_limit must be positive")
        if not isinstance(self.gpu_telemetry_known, bool):
            raise ResourceConfigurationError("gpu_telemetry_known must be a bool")

    @classmethod
    def from_resource_snapshot(
        cls,
        snapshot: ResourceSnapshot | Mapping[str, Any],
        *,
        child_process_limit: int = 64,
        scheduler_snapshot: Optional[Mapping[str, Any]] = None,
    ) -> "SchedulerPressureSummary":
        data = snapshot.to_dict() if isinstance(snapshot, ResourceSnapshot) else dict(snapshot)
        scheduler = dict(scheduler_snapshot or {})
        counters = dict(scheduler.get("counters") or {})
        gpu_status = str(data.get("collector_status") or "")
        gpu_known = bool(data.get("gpu_telemetry_available", "gpu_unavailable" not in gpu_status))
        return cls(
            cpu_utilization=data.get("cpu_percent", data.get("cpu_utilization", 0.0)),
            memory_pressure=data.get("memory_percent", data.get("memory_pressure", 0.0)),
            swap_pressure=data.get("swap_percent", data.get("swap_pressure", 0.0)),
            gpu_memory_pressure=data.get(
                "gpu_memory_percent",
                data.get("gpu_memory_pressure", 0.0),
            ),
            gpu_utilization=data.get(
                "gpu_utilization_percent",
                data.get("gpu_utilization", 0.0),
            ),
            gpu_telemetry_known=gpu_known,
            child_process_count=int(data.get("child_process_count", 0) or 0),
            child_process_limit=max(1, int(child_process_limit or 1)),
            active_child_lease_count=int(scheduler.get("active_child_lease_count", 0) or 0),
            waiting_request_count=int(scheduler.get("waiting_request_count", 0) or 0),
            saturation_events_total=int(counters.get("saturation_events_total", 0) or 0),
        )

    @classmethod
    def from_scheduler_snapshot(
        cls,
        snapshot: Mapping[str, Any],
        *,
        resource_snapshot: ResourceSnapshot | Mapping[str, Any] | None = None,
        child_process_limit: int = 64,
    ) -> "SchedulerPressureSummary":
        if resource_snapshot is not None:
            return cls.from_resource_snapshot(
                resource_snapshot,
                child_process_limit=child_process_limit,
                scheduler_snapshot=snapshot,
            )
        data = dict(snapshot or {})
        capacity = dict(data.get("capacity") or {})
        allocated = dict(data.get("allocated") or {})
        available = dict(data.get("available") or {})
        total_cpu = max(1.0, float(capacity.get("cpu_slots", 1) or 1))
        total_mem = max(1.0, float(capacity.get("usable_memory_mb", capacity.get("memory_mb", 1)) or 1))
        available_mem = max(0.0, float(available.get("memory_mb", 0) or 0))
        gpu_total = capacity.get("usable_gpu_memory_mb")
        gpu_available = available.get("gpu_memory_mb")
        gpu_pressure = 0.0
        if gpu_total not in {None, 0} and gpu_available is not None:
            gpu_pressure = 1.0 - (max(0.0, float(gpu_available)) / max(1.0, float(gpu_total)))
        counters = dict(data.get("counters") or {})
        return cls(
            cpu_utilization=float(allocated.get("cpu_slots", 0) or 0) / total_cpu,
            memory_pressure=1.0 - (available_mem / total_mem),
            swap_pressure=0.0,
            gpu_memory_pressure=gpu_pressure,
            gpu_utilization=0.0,
            gpu_telemetry_known=gpu_total is not None,
            child_process_count=int(data.get("active_child_lease_count", 0) or 0),
            child_process_limit=max(1, int(child_process_limit or 1)),
            active_child_lease_count=int(data.get("active_child_lease_count", 0) or 0),
            waiting_request_count=int(data.get("waiting_request_count", 0) or 0),
            saturation_events_total=int(counters.get("saturation_events_total", 0) or 0),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "active_child_lease_count": self.active_child_lease_count,
            "child_process_count": self.child_process_count,
            "child_process_limit": self.child_process_limit,
            "cpu_utilization": self.cpu_utilization,
            "gpu_memory_pressure": self.gpu_memory_pressure,
            "gpu_telemetry_known": self.gpu_telemetry_known,
            "gpu_utilization": self.gpu_utilization,
            "memory_pressure": self.memory_pressure,
            "saturation_events_total": self.saturation_events_total,
            "swap_pressure": self.swap_pressure,
            "waiting_request_count": self.waiting_request_count,
        }


@dataclass(frozen=True)
class LaneReservation:
    """Capacity protected for a lane when other lanes request resources."""

    cpu_slots: int = 0
    memory_mb: int = 0

    def validate(self, *, lane: str = "") -> None:
        if isinstance(self.cpu_slots, bool) or not isinstance(self.cpu_slots, int):
            raise ResourceConfigurationError(f"lane {lane!r} cpu_slots must be an integer")
        if isinstance(self.memory_mb, bool) or not isinstance(self.memory_mb, int):
            raise ResourceConfigurationError(f"lane {lane!r} memory_mb must be an integer")
        if self.cpu_slots < 0 or self.memory_mb < 0:
            raise ResourceConfigurationError(f"lane {lane!r} reservations cannot be negative")

    def to_dict(self) -> Dict[str, int]:
        return {"cpu_slots": self.cpu_slots, "memory_mb": self.memory_mb}


def _normalise_reservations(
    reservations: Mapping[str, Union[LaneReservation, Mapping[str, Any], int]],
) -> Dict[str, LaneReservation]:
    result: Dict[str, LaneReservation] = {}
    for raw_lane, raw_value in dict(reservations).items():
        lane = raw_lane.value if isinstance(raw_lane, ResourceLane) else str(raw_lane).strip()
        if not lane:
            raise ResourceConfigurationError("reservation lane names must be non-empty")
        if isinstance(raw_value, LaneReservation):
            reservation = raw_value
        elif isinstance(raw_value, int) and not isinstance(raw_value, bool):
            reservation = LaneReservation(cpu_slots=raw_value)
        elif isinstance(raw_value, Mapping):
            reservation = LaneReservation(
                cpu_slots=int(raw_value.get("cpu_slots", 0)),
                memory_mb=int(raw_value.get("memory_mb", 0)),
            )
        else:
            raise ResourceConfigurationError(f"invalid reservation for lane {lane!r}")
        reservation.validate(lane=lane)
        result[lane] = reservation
    return result


def _default_memory_mb() -> int:
    configured = os.environ.get(DEFAULT_MEMORY_ENV)
    if configured:
        return int(configured)
    try:
        import psutil  # type: ignore[import-not-found]

        # Leave memory for the OS and non-scheduled supervisors.
        return max(1, int(psutil.virtual_memory().total // (1024 * 1024) * 0.80))
    except Exception:
        return 16 * 1024


def _default_gpu_memory_mb() -> Optional[int]:
    configured = os.environ.get(DEFAULT_GPU_MEMORY_ENV)
    if configured:
        return int(configured)
    return None


def default_scheduler_state_path() -> Path:
    configured = os.environ.get(DEFAULT_STATE_ENV)
    if configured:
        return Path(configured).expanduser().resolve()
    uid = getattr(os, "getuid", lambda: 0)()
    return Path(tempfile.gettempdir()) / f"ipfs-datasets-resource-scheduler-{uid}.json"


@dataclass
class ResourceSchedulerConfig:
    """Host-level capacity, reservation, and lease-recovery policy."""

    total_cpu_slots: int = field(
        default_factory=lambda: int(os.environ.get(DEFAULT_CPU_ENV, "20"))
    )
    total_memory_mb: int = field(default_factory=_default_memory_mb)
    total_gpu_memory_mb: Optional[int] = field(default_factory=_default_gpu_memory_mb)
    reserved_memory_mb: int = 0
    reserved_gpu_memory_mb: int = 0
    lane_reservations: Mapping[
        str, Union[LaneReservation, Mapping[str, Any], int]
    ] = field(
        default_factory=lambda: {
            lane: LaneReservation(cpu_slots=slots)
            for lane, slots in DEFAULT_LANE_CPU_RESERVATIONS.items()
        }
    )
    state_path: Union[str, os.PathLike[str]] = field(default_factory=default_scheduler_state_path)
    lease_ttl_seconds: float = 120.0
    poll_interval_seconds: float = 0.05
    auto_renew_leases: bool = True
    max_memory_percent: Optional[float] = None
    max_swap_percent: Optional[float] = None
    max_gpu_memory_percent: Optional[float] = None
    require_known_gpu_for_gpu_work: bool = True
    resource_pressure_sampler: Optional[ResourcePressureSampler] = field(
        default=None,
        compare=False,
        repr=False,
    )

    def reservations(self) -> Dict[str, LaneReservation]:
        return _normalise_reservations(self.lane_reservations)

    def validate(self) -> None:
        if isinstance(self.total_cpu_slots, bool) or not isinstance(self.total_cpu_slots, int):
            raise ResourceConfigurationError("total_cpu_slots must be an integer")
        if isinstance(self.total_memory_mb, bool) or not isinstance(self.total_memory_mb, int):
            raise ResourceConfigurationError("total_memory_mb must be an integer")
        if self.total_cpu_slots <= 0 or self.total_memory_mb <= 0:
            raise ResourceConfigurationError("total CPU and memory capacities must be positive")
        if self.total_gpu_memory_mb is not None and (
            isinstance(self.total_gpu_memory_mb, bool)
            or not isinstance(self.total_gpu_memory_mb, int)
            or self.total_gpu_memory_mb <= 0
        ):
            raise ResourceConfigurationError("total_gpu_memory_mb must be a positive integer or None")
        if (
            isinstance(self.reserved_memory_mb, bool)
            or not isinstance(self.reserved_memory_mb, int)
            or self.reserved_memory_mb < 0
        ):
            raise ResourceConfigurationError("reserved_memory_mb must be a non-negative integer")
        if (
            isinstance(self.reserved_gpu_memory_mb, bool)
            or not isinstance(self.reserved_gpu_memory_mb, int)
            or self.reserved_gpu_memory_mb < 0
        ):
            raise ResourceConfigurationError("reserved_gpu_memory_mb must be a non-negative integer")
        if self.reserved_memory_mb >= self.total_memory_mb:
            raise ResourceConfigurationError("reserved_memory_mb must be below total_memory_mb")
        if (
            self.total_gpu_memory_mb is not None
            and self.reserved_gpu_memory_mb >= self.total_gpu_memory_mb
        ):
            raise ResourceConfigurationError(
                "reserved_gpu_memory_mb must be below total_gpu_memory_mb"
            )
        if not math.isfinite(float(self.lease_ttl_seconds)) or self.lease_ttl_seconds <= 0:
            raise ResourceConfigurationError("lease_ttl_seconds must be positive and finite")
        if not math.isfinite(float(self.poll_interval_seconds)) or self.poll_interval_seconds <= 0:
            raise ResourceConfigurationError("poll_interval_seconds must be positive and finite")
        for name in ("max_memory_percent", "max_swap_percent", "max_gpu_memory_percent"):
            value = getattr(self, name)
            if value is None:
                continue
            if (
                isinstance(value, bool)
                or not math.isfinite(float(value))
                or float(value) < 0.0
                or float(value) > 100.0
            ):
                raise ResourceConfigurationError(f"{name} must be between 0 and 100 or None")
        reservations = self.reservations()
        if sum(item.cpu_slots for item in reservations.values()) > self.total_cpu_slots:
            raise ResourceConfigurationError("CPU lane reservations exceed total_cpu_slots")
        usable_memory = self.total_memory_mb - self.reserved_memory_mb
        if sum(item.memory_mb for item in reservations.values()) > usable_memory:
            raise ResourceConfigurationError("memory lane reservations exceed total_memory_mb")

    def persisted_dict(self) -> Dict[str, Any]:
        return {
            "total_cpu_slots": self.total_cpu_slots,
            "total_memory_mb": self.total_memory_mb,
            "total_gpu_memory_mb": self.total_gpu_memory_mb,
            "reserved_memory_mb": self.reserved_memory_mb,
            "reserved_gpu_memory_mb": self.reserved_gpu_memory_mb,
            "lane_reservations": {
                lane: reservation.to_dict()
                for lane, reservation in sorted(self.reservations().items())
            },
            "max_memory_percent": self.max_memory_percent,
            "max_swap_percent": self.max_swap_percent,
            "max_gpu_memory_percent": self.max_gpu_memory_percent,
            "require_known_gpu_for_gpu_work": self.require_known_gpu_for_gpu_work,
        }


def _owner_birth_marker(pid: int) -> str:
    """Return a stable process birth marker, guarding against PID reuse."""

    try:
        # Linux field 22 is the start time in clock ticks since boot.  The
        # comm field can contain spaces, hence split only after its final ')'.
        stat_text = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
        return stat_text[stat_text.rfind(")") + 2 :].split()[19]
    except Exception:
        try:
            import psutil  # type: ignore[import-not-found]

            return f"{psutil.Process(pid).create_time():.6f}"
        except Exception:
            return ""


def _owner_is_alive(pid: int, marker: str) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        pass
    except OSError:
        return False
    return not marker or _owner_birth_marker(pid) == marker


@dataclass(frozen=True)
class ResourceLeaseToken:
    """Serializable authority for allocating work below a parent lease."""

    lease_id: str
    lease_key: str
    state_path: str


class _CombinedCancellationSignal:
    def __init__(
        self,
        scheduler: "GlobalResourceScheduler",
        lease_id: str,
        external: Optional[CancellationSignal] = None,
    ) -> None:
        self._scheduler = scheduler
        self._lease_id = lease_id
        self._external = external

    def is_set(self) -> bool:
        return bool(
            (self._external is not None and self._external.is_set())
            or self._scheduler.is_cancelled(self._lease_id, missing_is_cancelled=True)
        )

    def wait(self, timeout: Optional[float] = None) -> bool:
        deadline = None if timeout is None else time.monotonic() + max(0.0, timeout)
        while not self.is_set():
            if deadline is not None and time.monotonic() >= deadline:
                return False
            time.sleep(min(0.02, max(0.0, deadline - time.monotonic())) if deadline else 0.02)
        return True


class ResourceLease:
    """An idempotently releasable root or nested resource lease."""

    def __init__(self, scheduler: "GlobalResourceScheduler", record: Mapping[str, Any]) -> None:
        self._scheduler = scheduler
        self.lease_id = str(record["lease_id"])
        self.lease_key = str(record["lease_key"])
        self.lane = str(record["lane"])
        self.cpu_slots = int(record["cpu_slots"])
        self.memory_mb = int(record["memory_mb"])
        self.gpu_memory_mb = int(record.get("gpu_memory_mb", 0))
        self.requires_gpu = bool(record.get("requires_gpu", False))
        self.parent_lease_id = record.get("parent_lease_id") or None
        self.owner_pid = int(record["owner_pid"])
        self.acquired_at = float(record["acquired_at"])
        self.wait_seconds = float(record.get("wait_seconds", 0.0))
        self._released = False
        self._stop_heartbeat = threading.Event()
        self._heartbeat_thread: Optional[threading.Thread] = None
        if scheduler.config.auto_renew_leases:
            interval = max(0.001, min(30.0, scheduler.config.lease_ttl_seconds / 3.0))
            self._heartbeat_thread = threading.Thread(
                target=self._heartbeat_loop,
                args=(interval,),
                name=f"resource-lease-{self.lease_id[:8]}",
                daemon=True,
            )
            self._heartbeat_thread.start()

    @property
    def token(self) -> ResourceLeaseToken:
        return ResourceLeaseToken(self.lease_id, self.lease_key, str(self._scheduler.state_path))

    @property
    def released(self) -> bool:
        return self._released

    @property
    def cancelled(self) -> bool:
        return self._scheduler.is_cancelled(self.lease_id, missing_is_cancelled=True)

    @property
    def cancellation_signal(self) -> CancellationSignal:
        return _CombinedCancellationSignal(self._scheduler, self.lease_id)

    def combined_cancellation_signal(
        self, external: Optional[CancellationSignal]
    ) -> CancellationSignal:
        return _CombinedCancellationSignal(self._scheduler, self.lease_id, external)

    def _heartbeat_loop(self, interval: float) -> None:
        while not self._stop_heartbeat.wait(interval):
            try:
                if not self._scheduler.renew(self.lease_id, self.lease_key):
                    return
            except ResourceSchedulerError:
                # A transient state-file error must not crash application
                # work.  The next interval retries; expiry remains fail-safe.
                continue

    def renew(self) -> bool:
        return self._scheduler.renew(self.lease_id, self.lease_key)

    heartbeat = renew

    def cancel(self) -> bool:
        return self._scheduler.cancel(self.lease_id, self.lease_key)

    def acquire_child(
        self,
        *,
        cpu_slots: int = 1,
        memory_mb: int = 0,
        gpu_memory_mb: int = 0,
        requires_gpu: bool = False,
        lane: Optional[Union[str, ResourceLane]] = None,
        timeout: Optional[float] = None,
        cancel_event: Optional[CancellationSignal] = None,
        request_id: str = "",
    ) -> "ResourceLease":
        return self._scheduler.acquire(
            lane=lane or self.lane,
            cpu_slots=cpu_slots,
            memory_mb=memory_mb,
            gpu_memory_mb=gpu_memory_mb,
            requires_gpu=requires_gpu,
            parent_lease=self,
            timeout=timeout,
            cancel_event=cancel_event,
            request_id=request_id,
        )

    child = acquire_child

    def release(self) -> bool:
        if self._released:
            return False
        self._stop_heartbeat.set()
        released = self._scheduler.release(self.lease_id, self.lease_key)
        self._released = True
        return released

    def __enter__(self) -> "ResourceLease":
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        self.release()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "lease_id": self.lease_id,
            "lane": self.lane,
            "cpu_slots": self.cpu_slots,
            "memory_mb": self.memory_mb,
            "gpu_memory_mb": self.gpu_memory_mb,
            "requires_gpu": self.requires_gpu,
            "parent_lease_id": self.parent_lease_id,
            "owner_pid": self.owner_pid,
            "acquired_at": self.acquired_at,
            "wait_seconds": self.wait_seconds,
            "released": self.released,
            "cancelled": self.cancelled,
        }


_PATH_LOCKS: Dict[str, threading.RLock] = {}
_PATH_LOCKS_GUARD = threading.Lock()


def _path_lock(path: Path) -> threading.RLock:
    key = str(path)
    with _PATH_LOCKS_GUARD:
        return _PATH_LOCKS.setdefault(key, threading.RLock())


class GlobalResourceScheduler:
    """One process-safe scheduler shared by all host-local runtime lanes."""

    def __init__(self, config: Optional[ResourceSchedulerConfig] = None) -> None:
        self.config = config or ResourceSchedulerConfig()
        self.config.validate()
        self.state_path = Path(self.config.state_path).expanduser().resolve()
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.lock_path = self.state_path.with_name(f"{self.state_path.name}.lock")
        self._thread_lock = _path_lock(self.state_path)
        # Validate or initialise eagerly so configuration mistakes fail before
        # a worker enters a long wait.
        with self._locked_state():
            pass

    def _new_state(self) -> Dict[str, Any]:
        lanes = self.config.reservations()
        return {
            "schema_version": RESOURCE_SCHEDULER_SCHEMA_VERSION,
            "config": self.config.persisted_dict(),
            "next_sequence": 1,
            "leases": {},
            "waiters": {},
            "metrics": {
                "acquisitions_total": 0,
                "releases_total": 0,
                "cancellations_total": 0,
                "timeouts_total": 0,
                "recoveries_total": 0,
                "recovered_leases_total": 0,
                "saturation_events_total": 0,
                "wait_seconds_total": 0.0,
                "wait_seconds_max": 0.0,
                "wait_samples": [],
                "lanes": {
                    lane: {
                        "acquisitions_total": 0,
                        "cancellations_total": 0,
                        "timeouts_total": 0,
                        "wait_seconds_total": 0.0,
                        "wait_seconds_max": 0.0,
                        "wait_count": 0,
                    }
                    for lane in lanes
                },
            },
        }

    @contextmanager
    def _locked_state(self, *, persist: bool = True) -> Iterator[Dict[str, Any]]:
        with self._thread_lock:
            # Lock a stable sibling inode and atomically replace the JSON state
            # after fsync.  Locking the JSON inode itself would be unsafe:
            # another process could already have the pre-replace inode open.
            with self.lock_path.open("a+", encoding="utf-8") as lock_handle:
                if fcntl is None:  # pragma: no cover
                    raise SchedulerStateError("process-safe file locking is unavailable")
                fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
                temporary_path: Optional[Path] = None
                try:
                    try:
                        raw = self.state_path.read_text(encoding="utf-8").strip()
                    except FileNotFoundError:
                        raw = ""
                    if raw:
                        try:
                            state = json.loads(raw)
                        except (TypeError, ValueError) as exc:
                            raise SchedulerStateError(
                                f"resource scheduler state is corrupt: {self.state_path}"
                            ) from exc
                    else:
                        state = self._new_state()
                    self._validate_state_configuration(state)
                    yield state
                    if not persist:
                        return
                    temporary_path = self.state_path.with_name(
                        f".{self.state_path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp"
                    )
                    with temporary_path.open("x", encoding="utf-8") as state_handle:
                        json.dump(state, state_handle, sort_keys=True, separators=(",", ":"))
                        state_handle.flush()
                        os.fsync(state_handle.fileno())
                    os.replace(temporary_path, self.state_path)
                    temporary_path = None
                    try:
                        directory_fd = os.open(self.state_path.parent, os.O_RDONLY)
                        try:
                            os.fsync(directory_fd)
                        finally:
                            os.close(directory_fd)
                    except OSError:
                        pass
                finally:
                    if temporary_path is not None:
                        try:
                            temporary_path.unlink()
                        except FileNotFoundError:
                            pass
                    fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)

    def _validate_state_configuration(self, state: Dict[str, Any]) -> None:
        if state.get("schema_version") != RESOURCE_SCHEDULER_SCHEMA_VERSION:
            raise SchedulerStateError("unsupported resource scheduler state schema")
        expected = self.config.persisted_dict()
        if state.get("config") != expected:
            if state.get("leases") or state.get("waiters"):
                raise ResourceConfigurationError(
                    "scheduler capacity differs from active shared state at "
                    f"{self.state_path}"
                )
            state.clear()
            state.update(self._new_state())

    @staticmethod
    def _descendants(state: Mapping[str, Any], lease_id: str) -> set[str]:
        result = {lease_id}
        changed = True
        while changed:
            changed = False
            for child_id, record in state.get("leases", {}).items():
                if record.get("parent_lease_id") in result and child_id not in result:
                    result.add(child_id)
                    changed = True
        return result

    def _recover_stale_locked(self, state: Dict[str, Any], now: float) -> list[str]:
        stale_roots: list[str] = []
        for lease_id, record in list(state["leases"].items()):
            expired = float(record.get("expires_at", 0.0)) <= now
            owner_dead = not _owner_is_alive(
                int(record.get("owner_pid", 0)), str(record.get("owner_birth_marker", ""))
            )
            if expired or owner_dead:
                stale_roots.append(lease_id)
        recovered: set[str] = set()
        for lease_id in stale_roots:
            recovered.update(self._descendants(state, lease_id))
        for lease_id in recovered:
            state["leases"].pop(lease_id, None)

        for waiter_id, waiter in list(state["waiters"].items()):
            if not _owner_is_alive(
                int(waiter.get("owner_pid", 0)), str(waiter.get("owner_birth_marker", ""))
            ):
                state["waiters"].pop(waiter_id, None)

        if recovered:
            metrics = state["metrics"]
            metrics["recoveries_total"] += 1
            metrics["recovered_leases_total"] += len(recovered)
        return sorted(recovered)

    def recover_stale_leases(self) -> list[str]:
        with self._locked_state() as state:
            return self._recover_stale_locked(state, time.time())

    @staticmethod
    def _root_usage(state: Mapping[str, Any]) -> tuple[int, int, int, Dict[str, Dict[str, int]]]:
        cpu = 0
        memory = 0
        gpu_memory = 0
        lanes: Dict[str, Dict[str, int]] = {}
        for record in state["leases"].values():
            if record.get("parent_lease_id"):
                continue
            lane = str(record["lane"])
            usage = lanes.setdefault(lane, {"cpu_slots": 0, "memory_mb": 0, "gpu_memory_mb": 0})
            usage["cpu_slots"] += int(record["cpu_slots"])
            usage["memory_mb"] += int(record["memory_mb"])
            usage["gpu_memory_mb"] += int(record.get("gpu_memory_mb", 0))
            cpu += int(record["cpu_slots"])
            memory += int(record["memory_mb"])
            gpu_memory += int(record.get("gpu_memory_mb", 0))
        return cpu, memory, gpu_memory, lanes

    def _pressure_snapshot(self) -> ResourceSnapshot:
        sampler = self.config.resource_pressure_sampler or collect_resource_snapshot
        value = sampler()
        if isinstance(value, ResourceSnapshot):
            return value
        payload = dict(value)
        allowed = set(ResourceSnapshot.__dataclass_fields__)
        return ResourceSnapshot(**{key: item for key, item in payload.items() if key in allowed})

    @staticmethod
    def _pressure_reason(snapshot: ResourceSnapshot, waiter: Mapping[str, Any], config: ResourceSchedulerConfig) -> str:
        if (
            config.max_memory_percent is not None
            and snapshot.memory_percent is not None
            and snapshot.memory_percent >= float(config.max_memory_percent)
        ):
            return "memory_pressure"
        if (
            config.max_swap_percent is not None
            and snapshot.swap_percent is not None
            and snapshot.swap_percent > float(config.max_swap_percent)
        ):
            return "swap_pressure"
        gpu_work = bool(waiter.get("requires_gpu")) or int(waiter.get("gpu_memory_mb", 0)) > 0
        if gpu_work and config.require_known_gpu_for_gpu_work:
            known_gpu = (
                snapshot.gpu_telemetry_available is True
                and (snapshot.cuda_available is not False)
                and (
                    snapshot.gpu_device_count > 0
                    or snapshot.gpu_memory_percent is not None
                    or snapshot.gpu_memory_used_bytes is not None
                )
            )
            if not known_gpu:
                return "gpu_telemetry_unknown"
        if (
            gpu_work
            and config.max_gpu_memory_percent is not None
            and snapshot.gpu_memory_percent is None
            and config.require_known_gpu_for_gpu_work
        ):
            return "gpu_memory_telemetry_unknown"
        if (
            config.max_gpu_memory_percent is not None
            and snapshot.gpu_memory_percent is not None
            and snapshot.gpu_memory_percent >= float(config.max_gpu_memory_percent)
        ):
            return "gpu_memory_pressure"
        return ""

    def _pressure_allows(self, waiter: Mapping[str, Any]) -> tuple[bool, str]:
        if (
            self.config.max_memory_percent is None
            and self.config.max_swap_percent is None
            and self.config.max_gpu_memory_percent is None
            and not waiter.get("requires_gpu")
            and int(waiter.get("gpu_memory_mb", 0)) <= 0
        ):
            return True, ""
        try:
            snapshot = self._pressure_snapshot()
        except Exception:
            if bool(waiter.get("requires_gpu")) or int(waiter.get("gpu_memory_mb", 0)) > 0:
                return False, "pressure_telemetry_unknown"
            return True, ""
        reason = self._pressure_reason(snapshot, waiter, self.config)
        return not reason, reason

    def _observed_gpu_capacity_mb(self) -> Optional[int]:
        try:
            snapshot = self._pressure_snapshot()
        except Exception:
            return None
        total = snapshot.gpu_memory_total_bytes
        if isinstance(total, int) and total > 0:
            return max(1, total // (1024 * 1024))
        return None

    def _root_can_grant(self, state: Mapping[str, Any], waiter: Mapping[str, Any]) -> bool:
        used_cpu, used_memory, used_gpu_memory, lane_usage = self._root_usage(state)
        requested_lane = str(waiter["lane"])
        reservations = self.config.reservations()
        protected_cpu = 0
        protected_memory = 0
        for lane, reservation in reservations.items():
            if lane == requested_lane:
                continue
            usage = lane_usage.get(lane, {})
            protected_cpu += max(0, reservation.cpu_slots - int(usage.get("cpu_slots", 0)))
            protected_memory += max(0, reservation.memory_mb - int(usage.get("memory_mb", 0)))
        usable_memory = self.config.total_memory_mb - self.config.reserved_memory_mb
        static_allows = (
            used_cpu + int(waiter["cpu_slots"]) + protected_cpu
            <= self.config.total_cpu_slots
            and used_memory + int(waiter["memory_mb"]) + protected_memory
            <= usable_memory
        )
        if not static_allows:
            return False
        requested_gpu = int(waiter.get("gpu_memory_mb", 0))
        if requested_gpu > 0:
            total_gpu = self.config.total_gpu_memory_mb or self._observed_gpu_capacity_mb()
            if total_gpu is None:
                if self.config.require_known_gpu_for_gpu_work:
                    return False
            elif used_gpu_memory + requested_gpu > total_gpu - self.config.reserved_gpu_memory_mb:
                return False
        pressure_allows, _ = self._pressure_allows(waiter)
        return pressure_allows

    @staticmethod
    def _child_can_grant(state: Mapping[str, Any], waiter: Mapping[str, Any]) -> bool:
        parent_id = str(waiter["parent_lease_id"])
        parent = state["leases"].get(parent_id)
        if parent is None or parent.get("cancelled"):
            return False
        child_cpu = child_memory = 0
        child_gpu_memory = 0
        for record in state["leases"].values():
            if record.get("parent_lease_id") == parent_id:
                child_cpu += int(record["cpu_slots"])
                child_memory += int(record["memory_mb"])
                child_gpu_memory += int(record.get("gpu_memory_mb", 0))
        return (
            child_cpu + int(waiter["cpu_slots"]) <= int(parent["cpu_slots"])
            and child_memory + int(waiter["memory_mb"]) <= int(parent["memory_mb"])
            and child_gpu_memory + int(waiter.get("gpu_memory_mb", 0))
            <= int(parent.get("gpu_memory_mb", 0))
        )

    def _can_grant(self, state: Mapping[str, Any], waiter: Mapping[str, Any]) -> bool:
        if waiter.get("parent_lease_id"):
            return self._child_can_grant(state, waiter)
        return self._root_can_grant(state, waiter)

    def _is_fair_turn(self, state: Mapping[str, Any], waiter: Mapping[str, Any]) -> bool:
        # Skip an older waiter only when it cannot currently use capacity.
        # This avoids head-of-line blocking between independently reserved lanes.
        scheduling_domain = waiter.get("parent_lease_id")
        for other in sorted(state["waiters"].values(), key=lambda item: item["sequence"]):
            # Nested envelopes do not compete with the global root pool or
            # with children of another parent, so fairness is scoped to the
            # capacity domain the waiter can actually consume.
            if other.get("parent_lease_id") != scheduling_domain:
                continue
            if other["waiter_id"] == waiter["waiter_id"]:
                return True
            if self._can_grant(state, other):
                return False
        return True

    @staticmethod
    def _lane_metrics(state: Dict[str, Any], lane: str) -> Dict[str, Any]:
        metrics = state["metrics"]["lanes"].setdefault(
            lane,
            {
                "acquisitions_total": 0,
                "cancellations_total": 0,
                "timeouts_total": 0,
                "wait_seconds_total": 0.0,
                "wait_seconds_max": 0.0,
                "wait_count": 0,
            },
        )
        # Forward-fill fields when opening state written by an earlier build
        # of the same schema during a rolling process restart.
        metrics.setdefault("wait_count", 0)
        return metrics

    def _record_wait(self, state: Dict[str, Any], lane: str, wait_seconds: float) -> None:
        metrics = state["metrics"]
        wait_seconds = max(0.0, float(wait_seconds))
        metrics["wait_seconds_total"] += wait_seconds
        metrics["wait_seconds_max"] = max(metrics["wait_seconds_max"], wait_seconds)
        samples = metrics.setdefault("wait_samples", [])
        samples.append(wait_seconds)
        del samples[:-4096]
        lane_metrics = self._lane_metrics(state, lane)
        lane_metrics["wait_count"] += 1
        lane_metrics["wait_seconds_total"] += wait_seconds
        lane_metrics["wait_seconds_max"] = max(lane_metrics["wait_seconds_max"], wait_seconds)

    @staticmethod
    def _normalise_lane(lane: Union[str, ResourceLane]) -> str:
        value = lane.value if isinstance(lane, ResourceLane) else str(lane).strip()
        if not value:
            raise ResourceConfigurationError("lane must be non-empty")
        return value

    def _parent_authority(
        self, parent: Optional[Union[ResourceLease, ResourceLeaseToken, str]]
    ) -> tuple[Optional[str], Optional[str]]:
        if parent is None:
            return None, None
        if isinstance(parent, ResourceLease):
            if parent._scheduler.state_path != self.state_path:
                raise ResourceConfigurationError("parent lease belongs to another scheduler")
            return parent.lease_id, parent.lease_key
        if isinstance(parent, ResourceLeaseToken):
            if Path(parent.state_path).resolve() != self.state_path:
                raise ResourceConfigurationError("parent token belongs to another scheduler")
            return parent.lease_id, parent.lease_key
        return str(parent), None

    def acquire(
        self,
        lane: Union[str, ResourceLane],
        *,
        cpu_slots: int = 1,
        memory_mb: int = 0,
        gpu_memory_mb: int = 0,
        requires_gpu: bool = False,
        parent_lease: Optional[Union[ResourceLease, ResourceLeaseToken, str]] = None,
        parent: Optional[Union[ResourceLease, ResourceLeaseToken, str]] = None,
        timeout: Optional[float] = None,
        cancel_event: Optional[CancellationSignal] = None,
        request_id: str = "",
        owner_pid: Optional[int] = None,
    ) -> ResourceLease:
        """Wait for and return a root or nested lease.

        Child resources are bounded by, but do not add to, the parent's
        global allocation.  ``parent`` is an alias for ``parent_lease``.
        Cancellation and timeouts remove the durable waiter before raising.
        """

        lane_value = self._normalise_lane(lane)
        if isinstance(cpu_slots, bool) or not isinstance(cpu_slots, int) or cpu_slots <= 0:
            raise ResourceConfigurationError("cpu_slots must be a positive integer")
        if isinstance(memory_mb, bool) or not isinstance(memory_mb, int) or memory_mb < 0:
            raise ResourceConfigurationError("memory_mb must be a non-negative integer")
        if (
            isinstance(gpu_memory_mb, bool)
            or not isinstance(gpu_memory_mb, int)
            or gpu_memory_mb < 0
        ):
            raise ResourceConfigurationError("gpu_memory_mb must be a non-negative integer")
        if timeout is not None and (not math.isfinite(float(timeout)) or timeout < 0):
            raise ResourceConfigurationError("timeout must be non-negative and finite")
        if parent is not None and parent_lease is not None:
            raise ResourceConfigurationError("specify only one of parent and parent_lease")
        parent_id, parent_key = self._parent_authority(parent_lease or parent)
        if not parent_id:
            reservations = self.config.reservations()
            maximum_cpu = self.config.total_cpu_slots - sum(
                reservation.cpu_slots
                for reserved_lane, reservation in reservations.items()
                if reserved_lane != lane_value
            )
            maximum_memory = self.config.total_memory_mb - sum(
                reservation.memory_mb
                for reserved_lane, reservation in reservations.items()
                if reserved_lane != lane_value
            ) - self.config.reserved_memory_mb
            if cpu_slots > maximum_cpu or memory_mb > maximum_memory:
                raise ResourceUnavailableError(
                    "request exceeds capacity available to its reservation lane"
                )
            if gpu_memory_mb > 0:
                maximum_gpu_memory = (
                    None
                    if self.config.total_gpu_memory_mb is None
                    else self.config.total_gpu_memory_mb - self.config.reserved_gpu_memory_mb
                )
                if maximum_gpu_memory is not None and gpu_memory_mb > maximum_gpu_memory:
                    raise ResourceUnavailableError(
                        "GPU memory request exceeds configured GPU capacity"
                    )

        pid = int(owner_pid if owner_pid is not None else os.getpid())
        birth_marker = _owner_birth_marker(pid)
        waiter_id = uuid.uuid4().hex
        started_wall = time.time()
        started_mono = time.monotonic()
        deadline = None if timeout is None else started_mono + float(timeout)
        terminal: Optional[str] = None
        granted_record: Optional[Dict[str, Any]] = None

        while granted_record is None and terminal is None:
            now_wall = time.time()
            now_mono = time.monotonic()
            externally_cancelled = bool(cancel_event is not None and cancel_event.is_set())
            with self._locked_state() as state:
                self._recover_stale_locked(state, now_wall)
                if waiter_id not in state["waiters"]:
                    if parent_id:
                        parent_record = state["leases"].get(parent_id)
                        if parent_record is None:
                            raise LeaseNotFoundError(f"parent lease {parent_id!r} is not active")
                        if parent_key and parent_record.get("lease_key") != parent_key:
                            raise LeaseNotFoundError("parent lease authority does not match")
                        if cpu_slots > int(parent_record["cpu_slots"]) or memory_mb > int(
                            parent_record["memory_mb"]
                        ):
                            raise ResourceUnavailableError("child request exceeds parent lease capacity")
                        if gpu_memory_mb > int(parent_record.get("gpu_memory_mb", 0)):
                            raise ResourceUnavailableError(
                                "child GPU memory request exceeds parent lease capacity"
                            )
                    sequence = int(state["next_sequence"])
                    state["next_sequence"] = sequence + 1
                    state["waiters"][waiter_id] = {
                        "waiter_id": waiter_id,
                        "sequence": sequence,
                        "lane": lane_value,
                        "cpu_slots": cpu_slots,
                        "memory_mb": memory_mb,
                        "gpu_memory_mb": gpu_memory_mb,
                        "requires_gpu": bool(requires_gpu or gpu_memory_mb > 0),
                        "parent_lease_id": parent_id,
                        "owner_pid": pid,
                        "owner_birth_marker": birth_marker,
                        "created_at": started_wall,
                        "request_id": str(request_id)[:256],
                        "saturation_recorded": False,
                    }
                waiter = state["waiters"][waiter_id]
                parent_record = state["leases"].get(parent_id) if parent_id else None
                parent_cancelled = bool(parent_id and (parent_record is None or parent_record.get("cancelled")))
                timed_out = deadline is not None and now_mono >= deadline
                can_grant_now = self._can_grant(state, waiter) and self._is_fair_turn(
                    state, waiter
                )
                if (
                    not externally_cancelled
                    and not parent_cancelled
                    and not can_grant_now
                    and not waiter.get("saturation_recorded")
                ):
                    waiter["saturation_recorded"] = True
                    state["metrics"]["saturation_events_total"] += 1
                if externally_cancelled or parent_cancelled:
                    state["waiters"].pop(waiter_id, None)
                    wait_seconds = now_mono - started_mono
                    self._record_wait(state, lane_value, wait_seconds)
                    state["metrics"]["cancellations_total"] += 1
                    self._lane_metrics(state, lane_value)["cancellations_total"] += 1
                    terminal = "cancelled"
                elif timed_out and not can_grant_now:
                    state["waiters"].pop(waiter_id, None)
                    wait_seconds = now_mono - started_mono
                    self._record_wait(state, lane_value, wait_seconds)
                    state["metrics"]["timeouts_total"] += 1
                    self._lane_metrics(state, lane_value)["timeouts_total"] += 1
                    terminal = "timeout"
                elif can_grant_now:
                    state["waiters"].pop(waiter_id, None)
                    lease_id = uuid.uuid4().hex
                    lease_key = uuid.uuid4().hex
                    wait_seconds = now_mono - started_mono
                    granted_record = {
                        "lease_id": lease_id,
                        "lease_key": lease_key,
                        "sequence": waiter["sequence"],
                        "lane": lane_value,
                        "cpu_slots": cpu_slots,
                        "memory_mb": memory_mb,
                        "gpu_memory_mb": gpu_memory_mb,
                        "requires_gpu": bool(requires_gpu or gpu_memory_mb > 0),
                        "parent_lease_id": parent_id,
                        "owner_pid": pid,
                        "owner_birth_marker": birth_marker,
                        "acquired_at": now_wall,
                        "heartbeat_at": now_wall,
                        "expires_at": now_wall + self.config.lease_ttl_seconds,
                        "request_id": str(request_id)[:256],
                        "cancelled": False,
                        "wait_seconds": wait_seconds,
                    }
                    state["leases"][lease_id] = granted_record
                    self._record_wait(state, lane_value, wait_seconds)
                    state["metrics"]["acquisitions_total"] += 1
                    self._lane_metrics(state, lane_value)["acquisitions_total"] += 1

            if terminal is None and granted_record is None:
                wait_for = self.config.poll_interval_seconds
                if deadline is not None:
                    wait_for = min(wait_for, max(0.0, deadline - time.monotonic()))
                if cancel_event is not None and hasattr(cancel_event, "wait"):
                    try:
                        cancel_event.wait(wait_for)  # type: ignore[attr-defined]
                    except (TypeError, ValueError):
                        time.sleep(wait_for)
                else:
                    time.sleep(wait_for)

        if terminal == "cancelled":
            raise LeaseCancelledError("resource lease request was cancelled")
        if terminal == "timeout":
            raise LeaseTimeoutError("timed out waiting for a resource lease")
        assert granted_record is not None
        return ResourceLease(self, granted_record)

    acquire_lease = acquire

    def try_acquire(self, lane: Union[str, ResourceLane], **kwargs: Any) -> Optional[ResourceLease]:
        kwargs["timeout"] = 0.0
        try:
            return self.acquire(lane, **kwargs)
        except LeaseTimeoutError:
            return None

    def renew(self, lease_id: str, lease_key: Optional[str] = None) -> bool:
        now = time.time()
        with self._locked_state() as state:
            self._recover_stale_locked(state, now)
            record = state["leases"].get(lease_id)
            if record is None:
                return False
            if lease_key and record.get("lease_key") != lease_key:
                raise LeaseNotFoundError("lease authority does not match")
            record["heartbeat_at"] = now
            record["expires_at"] = now + self.config.lease_ttl_seconds
            return True

    heartbeat = renew

    def cancel(self, lease_id: str, lease_key: Optional[str] = None) -> bool:
        with self._locked_state() as state:
            record = state["leases"].get(lease_id)
            if record is None:
                return False
            if lease_key and record.get("lease_key") != lease_key:
                raise LeaseNotFoundError("lease authority does not match")
            changed = False
            for descendant in self._descendants(state, lease_id):
                child = state["leases"].get(descendant)
                if child is not None and not child.get("cancelled"):
                    child["cancelled"] = True
                    changed = True
            if changed:
                state["metrics"]["cancellations_total"] += 1
                self._lane_metrics(state, str(record["lane"]))["cancellations_total"] += 1
            return changed

    cancel_lease = cancel

    def is_cancelled(self, lease_id: str, *, missing_is_cancelled: bool = False) -> bool:
        # This is the hot polling path used by subprocess supervision.  Read
        # under the process lock but avoid an fsync/replace on every poll.
        with self._locked_state(persist=False) as state:
            record = state["leases"].get(lease_id)
            if record is None:
                return missing_is_cancelled
            stale = float(record.get("expires_at", 0.0)) <= time.time() or not _owner_is_alive(
                int(record.get("owner_pid", 0)), str(record.get("owner_birth_marker", ""))
            )
            return stale or bool(record.get("cancelled"))

    def release(self, lease_id: str, lease_key: Optional[str] = None) -> bool:
        with self._locked_state() as state:
            record = state["leases"].get(lease_id)
            if record is None:
                return False
            if lease_key and record.get("lease_key") != lease_key:
                raise LeaseNotFoundError("lease authority does not match")
            released = self._descendants(state, lease_id)
            for descendant in released:
                state["leases"].pop(descendant, None)
            state["metrics"]["releases_total"] += len(released)
            return True

    release_lease = release

    @staticmethod
    def _percentile(samples: list[float], percentile: float) -> float:
        if not samples:
            return 0.0
        values = sorted(float(value) for value in samples)
        index = max(0, min(len(values) - 1, math.ceil(percentile * len(values)) - 1))
        return values[index]

    def snapshot(self) -> Dict[str, Any]:
        """Return source-free capacity, saturation, lane, and wait telemetry."""

        with self._locked_state() as state:
            self._recover_stale_locked(state, time.time())
            cpu, memory, gpu_memory, lane_usage = self._root_usage(state)
            reservations = self.config.reservations()
            lane_names = sorted(set(reservations) | set(lane_usage) | set(state["metrics"]["lanes"]))
            lanes: Dict[str, Any] = {}
            for lane in lane_names:
                usage = lane_usage.get(
                    lane, {"cpu_slots": 0, "memory_mb": 0, "gpu_memory_mb": 0}
                )
                reserved = reservations.get(lane, LaneReservation())
                metrics = dict(self._lane_metrics(state, lane))
                count = int(metrics["wait_count"])
                metrics["wait_seconds_mean"] = (
                    float(metrics["wait_seconds_total"]) / count if count else 0.0
                )
                lanes[lane] = {
                    "reservation": reserved.to_dict(),
                    "allocated": dict(usage),
                    "telemetry": metrics,
                }
            metrics = state["metrics"]
            samples = [float(value) for value in metrics.get("wait_samples", [])]
            active_children = sum(
                1 for record in state["leases"].values() if record.get("parent_lease_id")
            )
            return {
                "schema_version": RESOURCE_SCHEDULER_SCHEMA_VERSION,
                "state_path": str(self.state_path),
                "capacity": {
                    "cpu_slots": self.config.total_cpu_slots,
                    "memory_mb": self.config.total_memory_mb,
                    "usable_memory_mb": self.config.total_memory_mb
                    - self.config.reserved_memory_mb,
                    "reserved_memory_mb": self.config.reserved_memory_mb,
                    "gpu_memory_mb": self.config.total_gpu_memory_mb,
                    "usable_gpu_memory_mb": (
                        None
                        if self.config.total_gpu_memory_mb is None
                        else self.config.total_gpu_memory_mb
                        - self.config.reserved_gpu_memory_mb
                    ),
                    "reserved_gpu_memory_mb": self.config.reserved_gpu_memory_mb,
                },
                "allocated": {"cpu_slots": cpu, "memory_mb": memory},
                "allocated_gpu_memory_mb": gpu_memory,
                "available": {
                    "cpu_slots": self.config.total_cpu_slots - cpu,
                    "memory_mb": self.config.total_memory_mb
                    - self.config.reserved_memory_mb
                    - memory,
                    "gpu_memory_mb": (
                        None
                        if self.config.total_gpu_memory_mb is None
                        else self.config.total_gpu_memory_mb
                        - self.config.reserved_gpu_memory_mb
                        - gpu_memory
                    ),
                },
                "active_lease_count": len(state["leases"]),
                "active_root_lease_count": len(state["leases"]) - active_children,
                "active_child_lease_count": active_children,
                "waiting_request_count": len(state["waiters"]),
                "saturation": {
                    "saturated": cpu >= self.config.total_cpu_slots
                    or memory >= self.config.total_memory_mb - self.config.reserved_memory_mb
                    or (
                        self.config.total_gpu_memory_mb is not None
                        and gpu_memory
                        >= self.config.total_gpu_memory_mb - self.config.reserved_gpu_memory_mb
                    )
                    or bool(state["waiters"]),
                    "cpu_saturated": cpu >= self.config.total_cpu_slots,
                    "memory_saturated": memory
                    >= self.config.total_memory_mb - self.config.reserved_memory_mb,
                    "gpu_memory_saturated": (
                        False
                        if self.config.total_gpu_memory_mb is None
                        else gpu_memory
                        >= self.config.total_gpu_memory_mb - self.config.reserved_gpu_memory_mb
                    ),
                    "events_total": int(metrics["saturation_events_total"]),
                },
                "wait_time_seconds": {
                    "count": len(samples),
                    "total": float(metrics["wait_seconds_total"]),
                    "mean": float(metrics["wait_seconds_total"]) / len(samples)
                    if samples
                    else 0.0,
                    "max": float(metrics["wait_seconds_max"]),
                    "p50": self._percentile(samples, 0.50),
                    "p95": self._percentile(samples, 0.95),
                    "p99": self._percentile(samples, 0.99),
                },
                "counters": {
                    key: value
                    for key, value in metrics.items()
                    if key not in {"lanes", "wait_samples"} and not key.startswith("wait_seconds")
                },
                "lanes": lanes,
            }

    telemetry = snapshot
    telemetry_snapshot = snapshot

    def pressure_summary(
        self,
        *,
        resource_snapshot: ResourceSnapshot | Mapping[str, Any] | None = None,
        child_process_limit: int = 64,
    ) -> Dict[str, Any]:
        """Return normalized pressure evidence for adaptive parallelism."""

        scheduler_snapshot = self.snapshot()
        if resource_snapshot is None:
            try:
                resource_snapshot = self._pressure_snapshot()
            except Exception:
                return SchedulerPressureSummary.from_scheduler_snapshot(
                    scheduler_snapshot,
                    child_process_limit=child_process_limit,
                ).to_dict()
        return SchedulerPressureSummary.from_resource_snapshot(
            resource_snapshot,
            child_process_limit=child_process_limit,
            scheduler_snapshot=scheduler_snapshot,
        ).to_dict()

    adaptive_pressure_summary = pressure_summary

    def active_leases(self) -> list[Dict[str, Any]]:
        """Return redacted active lease records (never returns authority keys)."""

        with self._locked_state() as state:
            self._recover_stale_locked(state, time.time())
            return [
                {key: value for key, value in record.items() if key != "lease_key"}
                for record in sorted(state["leases"].values(), key=lambda item: item["sequence"])
            ]

    def reset(self, *, force: bool = False) -> None:
        """Clear idle telemetry/state; refuse to discard active work by default."""

        with self._locked_state() as state:
            self._recover_stale_locked(state, time.time())
            if (state["leases"] or state["waiters"]) and not force:
                raise ResourceSchedulerError("cannot reset a scheduler with active work")
            state.clear()
            state.update(self._new_state())


_GLOBAL_SCHEDULERS: Dict[str, GlobalResourceScheduler] = {}
_GLOBAL_SCHEDULERS_LOCK = threading.Lock()


def get_global_resource_scheduler(
    config: Optional[ResourceSchedulerConfig] = None,
) -> GlobalResourceScheduler:
    """Return the process-local facade for the shared host state file."""

    effective = config or ResourceSchedulerConfig()
    key = str(Path(effective.state_path).expanduser().resolve())
    with _GLOBAL_SCHEDULERS_LOCK:
        scheduler = _GLOBAL_SCHEDULERS.get(key)
        if scheduler is None:
            scheduler = GlobalResourceScheduler(effective)
            _GLOBAL_SCHEDULERS[key] = scheduler
        elif scheduler.config.persisted_dict() != effective.persisted_dict():
            raise ResourceConfigurationError(
                f"a differently configured scheduler already owns {key} in this process"
            )
        return scheduler


def configure_global_resource_scheduler(
    config: ResourceSchedulerConfig,
) -> GlobalResourceScheduler:
    """Install and return a configured global scheduler facade."""

    scheduler = GlobalResourceScheduler(config)
    key = str(scheduler.state_path)
    with _GLOBAL_SCHEDULERS_LOCK:
        _GLOBAL_SCHEDULERS[key] = scheduler
    return scheduler


def acquire_resource_lease(
    lane: Union[str, ResourceLane], **kwargs: Any
) -> ResourceLease:
    """Convenience entry point used by Hammer, Lean, validation, and Codex."""

    return get_global_resource_scheduler().acquire(lane, **kwargs)


__all__ = [
    "RESOURCE_SCHEDULER_SCHEMA_VERSION",
    "DEFAULT_LANE_CPU_RESERVATIONS",
    "ResourceLane",
    "LaneReservation",
    "ResourceSchedulerConfig",
    "SchedulerPressureSummary",
    "ResourceLeaseToken",
    "ResourceLease",
    "GlobalResourceScheduler",
    "ResourceSchedulerError",
    "ResourceConfigurationError",
    "ResourceUnavailableError",
    "LeaseTimeoutError",
    "LeaseCancelledError",
    "LeaseNotFoundError",
    "SchedulerStateError",
    "default_scheduler_state_path",
    "get_global_resource_scheduler",
    "configure_global_resource_scheduler",
    "acquire_resource_lease",
]
