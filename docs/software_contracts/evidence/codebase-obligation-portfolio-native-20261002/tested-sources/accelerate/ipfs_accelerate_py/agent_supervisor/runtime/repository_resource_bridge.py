"""One shared native host envelope for supervised repository phases.

Supervisor leases retain local lane/policy bookkeeping. Only the existing
datasets GlobalResourceScheduler reserves shared host CPU/RAM/process capacity.
This additive CPU profile preserves native safety/backoff and validation reserve;
it does not implement a second host allocator or claim hard enforcement.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
import shutil
import threading
import time
import uuid

from .resource_scheduler import (
    LaneResourceRequirements, ResourceLeaseBudget, ResourceScheduler,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.resource_scheduler import (
    GlobalResourceScheduler, LeaseCancelledError, LeaseTimeoutError,
    ResourceLane, get_global_resource_scheduler,
)

SCHEMA = "repository-shared-host-envelope@1"
PROFILE = "cpu-shared-native-sampled@1"
MIB = 1024 * 1024
PHASES = {
    "scan": ResourceLane.ORCHESTRATION, "sql": ResourceLane.PERSISTENCE,
    "parquet": ResourceLane.PERSISTENCE, "semantic_index": ResourceLane.ORCHESTRATION,
    "inference": ResourceLane.ORCHESTRATION, "training": ResourceLane.TRAINER,
    "search": ResourceLane.HAMMER, "proof": ResourceLane.HAMMER_LEAN,
    "validation": ResourceLane.VALIDATION, "persistence": ResourceLane.PERSISTENCE,
    "cleanup": ResourceLane.VALIDATION,
}
LIMITATIONS = (
    "disk_is_local_declared_reservation_plus_free_space_sampling_not_shared_host_disk_authority",
    "queue_bytes_measure_bridge_request_metadata_not_retained_training_or_inference_payloads",
    "thread_limits_are_explicit_consumer_requirements_not_global_in_process_thread_enforcement",
    "cpu_ram_process_leases_are_admission_accounting_not_kernel_cgroups",
    "gpu_per_device_provider_admission_and_hard_enforcement_are_unsupported",
    "native_pressure_backoff_preserved_gradual_recovery_not_newly_qualified",
    "validation_reserve_is_global_only_training_can_occupy_its_entire_parent_envelope",
)


class RepositoryResourceError(ValueError):
    """The explicit finite CPU envelope or its native owner does not match."""


def _require(value, message):
    if not value:
        raise RepositoryResourceError(message)


def _integer(value, name, maximum, *, minimum=1):
    _require(type(value) is int and minimum <= value <= maximum,
             name + " must be a bounded exact integer")


def _raw(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


@dataclass(frozen=True)
class RepositoryResourceBudget:
    cpu_slots: int = 1
    memory_mb: int = 1024
    process_slots: int = 1
    threads_per_process: int = 1
    disk_bytes: int = 64 * MIB
    wall_time_ms: int = 120000
    maximum_queued_phases: int = 8
    maximum_queued_metadata_bytes: int = 65536
    maximum_phases: int = 128
    device: str = "cpu"
    enforcement: str = "sampled"

    def __post_init__(self):
        for name, maximum in (("cpu_slots", 1024), ("memory_mb", 2**24),
                ("process_slots", 1024), ("threads_per_process", 1024),
                ("disk_bytes", 2**40), ("wall_time_ms", 3600000),
                ("maximum_queued_phases", 256), ("maximum_queued_metadata_bytes", 4*MIB),
                ("maximum_phases", 4096)):
            _integer(getattr(self, name), name, maximum)
        _require(self.device == "cpu" and self.enforcement == "sampled",
                 "only explicit CPU sampled admission is supported")
        _require(self.cpu_slots >= self.process_slots * self.threads_per_process,
                 "CPU slots must cover declared concurrent process threads")


@dataclass(frozen=True)
class RepositoryPhaseDemand:
    phase: str
    cpu_slots: int = 1
    memory_mb: int = 512
    process_slots: int = 1
    threads_per_process: int = 1
    disk_bytes: int = 16 * MIB

    def __post_init__(self):
        _require(self.phase in PHASES, "explicit supported repository phase required")
        for name, maximum in (("cpu_slots", 1024), ("memory_mb", 2**24),
                ("process_slots", 1024), ("threads_per_process", 1024), ("disk_bytes", 2**40)):
            _integer(getattr(self, name), name, maximum)
        _require(self.cpu_slots >= self.process_slots * self.threads_per_process,
                 "phase CPU slots must cover declared concurrent process threads")


class _Cancellation:
    def __init__(self, parent):
        self.parent = parent

    def is_set(self):
        parent = self.parent
        external = parent.external_cancel
        return (parent._cancelled.is_set() or parent.native.cancelled
                or external is not None and external.is_set()
                or not any(lease is parent.supervisor_lease for lease in parent.supervisor.active_leases))

    def wait(self, timeout=None):
        deadline = None if timeout is None else time.monotonic() + max(0, timeout)
        while not self.is_set():
            if deadline is not None and time.monotonic() >= deadline:
                return False
            self.parent._cancelled.wait(.02 if deadline is None else min(.02, max(0, deadline-time.monotonic())))
        return True


class RepositoryPhaseLease:
    """Actual child authority; serialization deliberately excludes lease keys."""
    def __init__(self, parent, native, demand):
        self.parent, self.native, self.demand = parent, native, demand

    def native_options(self):
        """Pass these to existing datasets consumers; never add a scheduler."""
        return dict(parent_lease=self.native, cancel_event=self.parent.cancellation,
                    timeout_seconds=self.parent.remaining(), memory_mb=self.demand.memory_mb)

    def thread_environment(self):
        """For a bounded child launcher; this does not mutate process globals."""
        count = str(self.demand.threads_per_process)
        return {"CUDA_VISIBLE_DEVICES": "", "OMP_NUM_THREADS": count,
                "MKL_NUM_THREADS": count, "OPENBLAS_NUM_THREADS": count,
                "NUMEXPR_NUM_THREADS": count, "TOKENIZERS_PARALLELISM": "false"}


class RepositoryHostReservation:
    def __init__(self, *, supervisor, supervisor_lease, shared, native, budget,
                 repository_id, workspace, deadline, external_cancel):
        self.supervisor, self.supervisor_lease = supervisor, supervisor_lease
        self.shared, self.native, self.budget = shared, native, budget
        self.repository_id, self.workspace = repository_id, workspace
        self.deadline, self.external_cancel = deadline, external_cancel
        self._cancelled, self._condition = threading.Event(), threading.Condition(threading.RLock())
        self._queued, self._active, self._events = {}, {}, []
        self._phase_count = 0
        self._closed = False
        self.cancellation = _Cancellation(self)

    def remaining(self):
        if self._closed or self.cancellation.is_set():
            raise LeaseCancelledError("repository host envelope cancelled or released")
        value = self.deadline - time.monotonic()
        if value <= 0:
            raise LeaseTimeoutError("repository host envelope deadline expired")
        return value

    @contextmanager
    def phase(self, demand):
        _require(type(demand) is RepositoryPhaseDemand, "exact typed phase demand required")
        self.remaining()
        for name in ("cpu_slots", "memory_mb", "process_slots", "threads_per_process", "disk_bytes"):
            _require(getattr(demand, name) <= getattr(self.budget, name), "phase exceeds parent " + name)
        request_id = uuid.uuid4().hex
        row = asdict(demand)
        queued_bytes = len(_raw(row))
        started = time.monotonic()
        with self._condition:
            _require(self._phase_count < self.budget.maximum_phases, "phase history capacity exhausted")
            _require(len(self._queued) < self.budget.maximum_queued_phases, "local phase queue is full")
            _require(sum(item["bytes"] for item in self._queued.values()) + queued_bytes
                     <= self.budget.maximum_queued_metadata_bytes, "local queued metadata exceeds byte bound")
            self._phase_count += 1
            self._queued[request_id] = dict(demand=row, bytes=queued_bytes)
        child = None
        event = dict(request_id=request_id, demand=row, status="refused", queue_time_ms=0,
                     execution_time_ms=0, parent_lease_id=self.native.lease_id, child_lease_id=None)
        try:
            child = self.native.acquire_child(lane=PHASES[demand.phase], cpu_slots=demand.cpu_slots,
                memory_mb=demand.memory_mb, child_process_slots=demand.process_slots,
                timeout=self.remaining(), cancel_event=self.cancellation,
                request_id="repository-phase:" + request_id)
            event.update(child_lease_id=child.lease_id, queue_time_ms=int((time.monotonic()-started)*1000))
            self.remaining()
            with self._condition:
                reserved_disk = sum(item["disk_bytes"] for item in self._active.values())
                _require(reserved_disk + demand.disk_bytes <= self.budget.disk_bytes,
                         "local phase disk declarations exceed parent envelope")
                _require(shutil.disk_usage(self.workspace).free >= demand.disk_bytes,
                         "sampled workspace free space below phase declaration")
                self._queued.pop(request_id)
                self._active[request_id] = row
            execution_started = time.monotonic()
            try:
                yield RepositoryPhaseLease(self, child, demand)
                self.remaining()
                event["status"] = "completed"
            finally:
                event["execution_time_ms"] = int((time.monotonic()-execution_started)*1000)
        except BaseException as error:
            event.update(status="cancelled" if isinstance(error, LeaseCancelledError) else
                         "timed_out" if isinstance(error, LeaseTimeoutError) else "failed",
                         error_type=type(error).__name__)
            raise
        finally:
            if child is not None:
                child.release()
            with self._condition:
                self._queued.pop(request_id, None)
                self._active.pop(request_id, None)
                self._events.append(event)
                self._condition.notify_all()

    def cancel(self):
        self._cancelled.set()
        self.native.cancel()

    def close(self):
        if self._closed:
            return
        self.cancel()
        # Cooperating native consumers poll the supplied cancellation signal.
        # Retain reservations if they do not drain; never report cleanup while
        # releasing capacity under an unaccounted still-active phase.
        deadline = time.monotonic() + 5
        with self._condition:
            while self._queued or self._active:
                remaining = deadline-time.monotonic()
                _require(remaining > 0, "active phases did not drain; reservations retained pending cleanup")
                self._condition.wait(min(.05, remaining))
        self.native.release()
        self.supervisor.release(self.supervisor_lease)
        self._closed = True

    def receipt(self):
        leases = self.shared.active_leases()
        with self._condition:
            return dict(schema=SCHEMA, profile=PROFILE, repository_id=self.repository_id,
                supervisor_lease_id=self.supervisor_lease.lease_id,
                supervisor_role="local_lane_policy_bookkeeping_not_another_host_authority",
                host_authority=dict(owner="datasets.GlobalResourceScheduler",
                    state_path=str(self.shared.state_path),
                    policy_sha256=hashlib.sha256(_raw(self.shared.config.persisted_dict())).hexdigest(),
                    root_lease_id=self.native.lease_id),
                owned_active_root_count=sum(row["lease_id"] == self.native.lease_id and not row.get("parent_lease_id") for row in leases),
                shared_active_root_count=sum(not row.get("parent_lease_id") for row in leases),
                native_parent=self.native.to_dict(), budget=asdict(self.budget),
                active_phase_count=len(self._active), queued_phase_count=len(self._queued),
                queued_metadata_bytes=sum(row["bytes"] for row in self._queued.values()),
                events=json.loads(_raw(self._events)), closed=self._closed,
                validation_reserve=self.shared.config.reservations()["validation"].to_dict(),
                validation_reservation_scope="global_only_siblings_share_parent_envelope",
                limitations=list(LIMITATIONS), hard_enforcement=False,
                task_execution_authority=False, completion_authority=False)


class RepositoryResourceBridge:
    def __init__(self, supervisor):
        _require(type(supervisor) is ResourceScheduler, "actual supervisor resource owner required")
        self.supervisor = supervisor

    @contextmanager
    def reserve(self, *, repository_id, workspace, budget, cancel_event=None):
        _require(type(repository_id) is str and 0 < len(repository_id) <= 256,
                 "bounded repository identity required")
        _require(type(budget) is RepositoryResourceBudget, "explicit typed repository budget required")
        _require(cancel_event is None or callable(getattr(cancel_event, "is_set", None)),
                 "cancellation signal must provide callable is_set")
        workspace = Path(workspace).resolve(strict=True)
        _require(workspace.is_dir(), "existing workspace directory required")
        deadline = time.monotonic() + budget.wall_time_ms / 1000
        shared = get_global_resource_scheduler()
        _require(type(shared) is GlobalResourceScheduler and shared.config.proof_safety_enabled,
                 "existing native shared proof-safety authority required")
        reservations = shared.config.reservations()
        _require(shared.config.max_waiting_requests is not None and "validation" in reservations
                 and reservations["validation"].cpu_slots >= 1,
                 "bounded shared queue and protected validation capacity required")
        if cancel_event is not None and cancel_event.is_set():
            raise LeaseCancelledError("repository reservation cancelled before admission")
        requirement = LaneResourceRequirements(lane_id="repository:" + repository_id + ":" + uuid.uuid4().hex,
            stage="analysis", resource_class="cpu-medium", required_capabilities=("cpu",),
            memory_bytes=budget.memory_mb*MIB, disk_bytes=budget.disk_bytes,
            process_slots=budget.process_slots)
        local_budget = ResourceLeaseBudget(max_parallel=budget.process_slots,
            max_cpu_proof_concurrency=budget.process_slots, max_processes=budget.process_slots,
            wall_time_ms=budget.wall_time_ms, memory_bytes=budget.memory_mb*MIB, disk_bytes=budget.disk_bytes)
        decision, local = self.supervisor.acquire(requirement, budget=local_budget, path=workspace)
        _require(local is not None and decision.admitted, "supervisor lane policy refused repository envelope: " + decision.reason)
        native = None
        parent = None
        try:
            remaining = deadline-time.monotonic()
            if remaining <= 0:
                raise LeaseTimeoutError("repository envelope expired before shared admission")
            native = shared.acquire(ResourceLane.ORCHESTRATION, cpu_slots=budget.cpu_slots,
                memory_mb=budget.memory_mb, child_process_slots=budget.process_slots,
                timeout=remaining, cancel_event=cancel_event, request_id=requirement.lane_id)
            parent = RepositoryHostReservation(supervisor=self.supervisor, supervisor_lease=local,
                shared=shared, native=native, budget=budget, repository_id=repository_id,
                workspace=workspace, deadline=deadline, external_cancel=cancel_event)
            parent.remaining()
            yield parent
            parent.remaining()
        finally:
            if parent is not None:
                parent.close()
            else:
                if native is not None:
                    native.release()
                self.supervisor.release(local)


__all__ = ["RepositoryResourceBridge", "RepositoryResourceBudget", "RepositoryPhaseDemand",
           "RepositoryHostReservation", "RepositoryPhaseLease", "RepositoryResourceError", "SCHEMA", "PROFILE"]
