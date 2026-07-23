"""Resource-aware dependency scheduling for the LegalIR optimization pipeline.

This module is the coordination boundary between the logical pipeline and the
host-global resource scheduler.  It deliberately knows *which* stages may run
and their dependencies, but it does not know how a trainer, prover, model
service, validator, or merge implementation performs its work.  Callers inject
those operations as handlers and receive the acquired :class:`ResourceLease`
on the task payload when nested work needs to charge solver children to the
same envelope.

The canonical pipeline is represented explicitly::

    trainer -> immutable snapshot -> hammer ---------+
                                  -> leanstral -------+-> codex
                                                        -> validation
                                                        -> persistence -> merge

Different immutable revisions can be scheduled by one scheduler at the same
time.  Trainer, persistence, and merge are nevertheless protected by a
process-safe canonical-write lock shared by every scheduler using the same
global resource state.  This is intentionally stronger than lane
reservations: reservations protect capacity, they are not mutexes.
"""

from __future__ import annotations

import math
import os
import threading
import time
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from types import MappingProxyType
from typing import Any, Callable, Final, Iterable, Mapping, MutableMapping, Sequence

try:  # pragma: no cover - supported production deployments are POSIX.
    import fcntl
except ImportError:  # pragma: no cover
    fcntl = None  # type: ignore[assignment]

from ipfs_datasets_py.optimizers.logic_theorem_optimizer.resource_scheduler import (
    GlobalResourceScheduler,
    LeaseTimeoutError,
    ResourceLane,
    ResourceLease,
    get_global_resource_scheduler,
)


PIPELINE_STAGE_SCHEDULER_SCHEMA_VERSION: Final = "legal-ir-pipeline-stage-scheduler-v1"


class PipelineSchedulerError(RuntimeError):
    """Base error for malformed DAGs and invalid stage transitions."""


class DuplicateTaskError(PipelineSchedulerError, ValueError):
    """A task identifier was submitted more than once."""


class UnknownDependencyError(PipelineSchedulerError, ValueError):
    """A task refers to a dependency that is not in the scheduler."""


class PipelineCycleError(PipelineSchedulerError, ValueError):
    """The submitted task graph contains a dependency cycle."""


class InvalidTaskTransitionError(PipelineSchedulerError):
    """A task was completed, failed, or cancelled from an invalid state."""


class PipelineExecutionError(PipelineSchedulerError):
    """One or more stage handlers failed while executing the pipeline."""

    def __init__(self, failures: Mapping[str, BaseException]) -> None:
        self.failures = dict(failures)
        detail = ", ".join(
            f"{task_id}: {type(error).__name__}: {error}"
            for task_id, error in sorted(self.failures.items())
        )
        super().__init__(f"pipeline stage execution failed ({detail})")


class PipelineStage(str, Enum):
    """Stable stage names used in queue metrics and persisted diagnostics."""

    CANONICAL_TRAINER = "canonical_trainer"
    SNAPSHOT_EVALUATION = "snapshot_evaluation"
    HAMMER = "hammer"
    LEANSTRAL_SERVICE = "leanstral_service"
    CODEX_GENERATION = "codex_generation"
    VALIDATION = "validation"
    PERSISTENCE = "persistence"
    MERGE = "merge"

    # Readable compatibility aliases for callers that use the shorter names.
    TRAINER = CANONICAL_TRAINER
    LEANSTRAL = LEANSTRAL_SERVICE
    CODEX = CODEX_GENERATION


class StageStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    BLOCKED = "blocked"
    CANCELLED = "cancelled"


_TERMINAL_STATUSES: Final = frozenset(
    {StageStatus.SUCCEEDED, StageStatus.FAILED, StageStatus.BLOCKED, StageStatus.CANCELLED}
)
_CANONICAL_WRITE_STAGES: Final = frozenset(
    {PipelineStage.CANONICAL_TRAINER, PipelineStage.PERSISTENCE, PipelineStage.MERGE}
)


def _non_negative_int(value: Any, *, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} must be a non-negative integer")
    return value


def _non_negative_float(value: Any, *, name: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a finite non-negative number")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a finite non-negative number") from exc
    if not math.isfinite(result) or result < 0.0:
        raise ValueError(f"{name} must be a finite non-negative number")
    return result


def _ratio(value: Any, *, name: str) -> float:
    result = _non_negative_float(value, name=name)
    if result > 1.0:
        if result <= 100.0:
            result /= 100.0
        else:
            raise ValueError(f"{name} must be between 0 and 1 (or 0 and 100 percent)")
    return result


def _stage(value: PipelineStage | str) -> PipelineStage:
    if isinstance(value, PipelineStage):
        return value
    text = str(value or "").strip().lower()
    aliases = {
        "trainer": PipelineStage.CANONICAL_TRAINER,
        "canonical_training": PipelineStage.CANONICAL_TRAINER,
        "snapshot": PipelineStage.SNAPSHOT_EVALUATION,
        "immutable_snapshot": PipelineStage.SNAPSHOT_EVALUATION,
        "leanstral": PipelineStage.LEANSTRAL_SERVICE,
        "codex": PipelineStage.CODEX_GENERATION,
        "generation": PipelineStage.CODEX_GENERATION,
        "state_persistence": PipelineStage.PERSISTENCE,
    }
    try:
        return aliases.get(text, PipelineStage(text))
    except ValueError as exc:
        raise ValueError(f"unknown pipeline stage {value!r}") from exc


@dataclass(frozen=True, slots=True)
class StageResourceRequest:
    """All globally-accounted resources required by one admitted stage.

    ``unified_memory_mb`` is an explicit allocation from the accelerator's
    shared CPU/GPU memory pool; it is not inferred from ordinary RAM or device
    memory.  ``child_process_slots`` reserves the coordinator and every direct
    child it may launch.  Nested solver leases consume their parent's envelope
    rather than being counted twice globally.
    """

    cpu_slots: int = 1
    memory_mb: int = 0
    unified_memory_mb: int = 0
    gpu_memory_mb: int = 0
    child_process_slots: int = 1
    requires_gpu: bool = False

    def __post_init__(self) -> None:
        for name in (
            "cpu_slots",
            "memory_mb",
            "unified_memory_mb",
            "gpu_memory_mb",
            "child_process_slots",
        ):
            _non_negative_int(getattr(self, name), name=name)
        if self.cpu_slots < 1:
            raise ValueError("cpu_slots must be at least one")
        if not isinstance(self.requires_gpu, bool):
            raise ValueError("requires_gpu must be a bool")
        if self.gpu_memory_mb > 0 and not self.requires_gpu:
            object.__setattr__(self, "requires_gpu", True)

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any] | None) -> "StageResourceRequest":
        data = dict(value or {})
        if "ram_mb" in data and "memory_mb" not in data:
            data["memory_mb"] = data.pop("ram_mb")
        if "child_processes" in data and "child_process_slots" not in data:
            data["child_process_slots"] = data.pop("child_processes")
        allowed = set(cls.__dataclass_fields__)
        return cls(**{key: item for key, item in data.items() if key in allowed})

    def to_dict(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}


# Older planning drafts called this StageResources.  Keep it as a real alias so
# isinstance checks and serialization remain unsurprising.
StageResources = StageResourceRequest


@dataclass(frozen=True, slots=True)
class PipelineTask:
    """One dependency-bound unit of stage work."""

    task_id: str
    stage: PipelineStage | str
    dependencies: tuple[str, ...] = ()
    resources: StageResourceRequest | Mapping[str, Any] = field(
        default_factory=StageResourceRequest
    )
    canonical_write: bool | None = None
    payload: Any = None
    revision: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        task_id = str(self.task_id or "").strip()
        if not task_id or len(task_id) > 256:
            raise ValueError("task_id must be non-empty and at most 256 characters")
        object.__setattr__(self, "task_id", task_id)
        object.__setattr__(self, "stage", _stage(self.stage))
        dependencies = tuple(str(item or "").strip() for item in self.dependencies)
        if any(not item for item in dependencies):
            raise ValueError("dependencies must contain non-empty task identifiers")
        if task_id in dependencies:
            raise PipelineCycleError(f"task {task_id!r} cannot depend on itself")
        if len(set(dependencies)) != len(dependencies):
            raise ValueError("dependencies must be unique")
        object.__setattr__(self, "dependencies", dependencies)
        if not isinstance(self.resources, StageResourceRequest):
            object.__setattr__(self, "resources", StageResourceRequest.from_mapping(self.resources))
        inferred_write = self.stage in _CANONICAL_WRITE_STAGES
        if self.canonical_write is not None and not isinstance(self.canonical_write, bool):
            raise ValueError("canonical_write must be a bool or None")
        # Canonical stages cannot opt out of the safety boundary.
        object.__setattr__(self, "canonical_write", bool(self.canonical_write or inferred_write))
        object.__setattr__(self, "revision", str(self.revision or "").strip())
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata or {})))

    def to_dict(self, *, include_payload: bool = False) -> dict[str, Any]:
        result = {
            "canonical_write": self.canonical_write,
            "dependencies": list(self.dependencies),
            "metadata": dict(self.metadata),
            "resources": self.resources.to_dict(),
            "revision": self.revision,
            "stage": self.stage.value,
            "task_id": self.task_id,
        }
        if include_payload:
            result["payload"] = self.payload
        return result


StageTask = PipelineTask
PipelineWorkItem = PipelineTask


@dataclass(frozen=True, slots=True)
class PipelineSchedulerSignals:
    """Measured demand, service rate, correctness pressure, and host pressure."""

    ready_depth_by_stage: Mapping[PipelineStage | str, int] = field(default_factory=dict)
    service_rate_by_stage: Mapping[PipelineStage | str, float] = field(default_factory=dict)
    nested_solver_children: int = 0
    validation_backlog: int = 0
    validation_capacity: int = 4
    conflict_rate: float = 0.0
    memory_pressure: float = 0.0
    gpu_memory_pressure: float = 0.0
    accepted_patches_per_hour: float = 0.0
    cpu_pressure: float = 0.0
    unified_memory_pressure: float = 0.0
    swap_pressure: float = 0.0
    child_process_count: int = 0
    child_process_limit: int = 64
    disjoint_codex_scopes: int = 0
    accepted_patch_target_per_hour: float = 0.0

    def __post_init__(self) -> None:
        ready: dict[PipelineStage, int] = {}
        for name, value in dict(self.ready_depth_by_stage or {}).items():
            ready[_stage(name)] = _non_negative_int(value, name=f"ready_depth_by_stage.{name}")
        rates: dict[PipelineStage, float] = {}
        for name, value in dict(self.service_rate_by_stage or {}).items():
            rates[_stage(name)] = _non_negative_float(value, name=f"service_rate_by_stage.{name}")
        object.__setattr__(self, "ready_depth_by_stage", MappingProxyType(ready))
        object.__setattr__(self, "service_rate_by_stage", MappingProxyType(rates))
        for name in (
            "nested_solver_children",
            "validation_backlog",
            "validation_capacity",
            "child_process_count",
            "child_process_limit",
            "disjoint_codex_scopes",
        ):
            _non_negative_int(getattr(self, name), name=name)
        if self.child_process_limit < 1:
            raise ValueError("child_process_limit must be at least one")
        for name in (
            "conflict_rate",
            "memory_pressure",
            "gpu_memory_pressure",
            "cpu_pressure",
            "unified_memory_pressure",
            "swap_pressure",
        ):
            object.__setattr__(self, name, _ratio(getattr(self, name), name=name))
        for name in ("accepted_patches_per_hour", "accepted_patch_target_per_hour"):
            object.__setattr__(self, name, _non_negative_float(getattr(self, name), name=name))

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any] | None) -> "PipelineSchedulerSignals":
        data = dict(value or {})
        aliases = {
            "ready_queue_depth": "ready_depth_by_stage",
            "completion_rate_by_stage": "service_rate_by_stage",
            "nested_child_count": "nested_solver_children",
            "merge_conflict_rate": "conflict_rate",
            "accepted_patch_throughput_per_hour": "accepted_patches_per_hour",
            "disjoint_codex_scope_count": "disjoint_codex_scopes",
        }
        for old, new in aliases.items():
            if new not in data and old in data:
                data[new] = data[old]
        allowed = set(cls.__dataclass_fields__)
        return cls(**{key: item for key, item in data.items() if key in allowed})

    def to_dict(self) -> dict[str, Any]:
        result = {
            name: getattr(self, name)
            for name in self.__dataclass_fields__
            if name not in {"ready_depth_by_stage", "service_rate_by_stage"}
        }
        result["ready_depth_by_stage"] = {
            stage.value: depth for stage, depth in sorted(self.ready_depth_by_stage.items(), key=lambda x: x[0].value)
        }
        result["service_rate_by_stage"] = {
            stage.value: rate for stage, rate in sorted(self.service_rate_by_stage.items(), key=lambda x: x[0].value)
        }
        return result


@dataclass(frozen=True, slots=True)
class StageConcurrencyLimits:
    """Maximum concurrently admitted coordinators for every stage."""

    canonical_trainer: int = 1
    snapshot_evaluation: int = 2
    hammer: int = 2
    leanstral_service: int = 1
    codex_generation: int = 6
    validation: int = 4
    persistence: int = 1
    merge: int = 1

    def __post_init__(self) -> None:
        for name in self.__dataclass_fields__:
            _non_negative_int(getattr(self, name), name=name)
        if self.canonical_trainer != 1:
            raise ValueError("canonical trainer concurrency must be exactly one")
        if self.leanstral_service > 1:
            raise ValueError("Leanstral service concurrency cannot exceed one")
        if self.persistence > 1 or self.merge > 1:
            raise ValueError("canonical persistence and merge concurrency cannot exceed one")

    def for_stage(self, stage: PipelineStage | str) -> int:
        return int(getattr(self, _stage(stage).value))

    def __getitem__(self, stage: PipelineStage | str) -> int:
        """Allow limits to be consumed as a stage-keyed read-only mapping."""

        return self.for_stage(stage)

    def to_dict(self) -> dict[str, int]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}


DGX_SPARK_INITIAL_STAGE_LIMITS: Final = StageConcurrencyLimits()


@dataclass(slots=True)
class StageAdmission:
    """A running task together with its authoritative global resource lease."""

    task: PipelineTask
    lease: ResourceLease
    admitted_at: float
    effective_limit: int
    _canonical_lock: "_CanonicalWriteLock | None" = field(default=None, repr=False)

    @property
    def task_id(self) -> str:
        return self.task.task_id

    @property
    def cancellation_signal(self) -> Any:
        return self.lease.cancellation_signal

    def to_dict(self) -> dict[str, Any]:
        return {
            "admitted_at": self.admitted_at,
            "effective_limit": self.effective_limit,
            "lease": self.lease.to_dict(),
            "task": self.task.to_dict(),
        }


PipelineStageAdmission = StageAdmission


_CANONICAL_THREAD_LOCKS: dict[str, threading.Lock] = {}
_CANONICAL_THREAD_LOCKS_GUARD = threading.Lock()


class _CanonicalWriteLock:
    """Non-blocking process-safe lock held for a canonical callback's lifetime."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._file: Any = None
        self._thread_lock: threading.Lock | None = None

    def acquire(self) -> bool:
        key = str(self.path)
        with _CANONICAL_THREAD_LOCKS_GUARD:
            lock = _CANONICAL_THREAD_LOCKS.setdefault(key, threading.Lock())
        if not lock.acquire(blocking=False):
            return False
        self._thread_lock = lock
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._file = self.path.open("a+b")
            if fcntl is not None:
                try:
                    fcntl.flock(self._file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    self._file.close()
                    self._file = None
                    lock.release()
                    self._thread_lock = None
                    return False
            return True
        except Exception:
            lock.release()
            self._thread_lock = None
            raise

    def release(self) -> None:
        if self._file is not None:
            try:
                if fcntl is not None:
                    fcntl.flock(self._file.fileno(), fcntl.LOCK_UN)
            finally:
                self._file.close()
                self._file = None
        if self._thread_lock is not None:
            self._thread_lock.release()
            self._thread_lock = None


def _default_lane(stage: PipelineStage) -> str:
    if stage in {PipelineStage.CANONICAL_TRAINER, PipelineStage.HAMMER, PipelineStage.LEANSTRAL_SERVICE}:
        return ResourceLane.HAMMER_LEAN.value
    if stage is PipelineStage.CODEX_GENERATION:
        return ResourceLane.CODEX.value
    if stage in {PipelineStage.SNAPSHOT_EVALUATION, PipelineStage.VALIDATION}:
        return ResourceLane.VALIDATION.value
    return ResourceLane.ORCHESTRATION.value


class PipelineStageScheduler:
    """Admit and execute dependency-ready tasks under measured global pressure."""

    def __init__(
        self,
        resource_scheduler: GlobalResourceScheduler | None = None,
        signals: PipelineSchedulerSignals | Mapping[str, Any] | None = None,
        *,
        initial_limits: StageConcurrencyLimits = DGX_SPARK_INITIAL_STAGE_LIMITS,
        canonical_lock_path: str | os.PathLike[str] | None = None,
    ) -> None:
        self.resource_scheduler = resource_scheduler or get_global_resource_scheduler()
        self.initial_limits = initial_limits
        self.signals = (
            signals
            if isinstance(signals, PipelineSchedulerSignals)
            else PipelineSchedulerSignals.from_mapping(signals)
        )
        state_path = Path(self.resource_scheduler.state_path)
        self.canonical_lock_path = Path(canonical_lock_path or f"{state_path}.canonical-write.lock")
        self._tasks: dict[str, PipelineTask] = {}
        self._statuses: dict[str, StageStatus] = {}
        self._admissions: dict[str, StageAdmission] = {}
        self._results: dict[str, Any] = {}
        self._errors: dict[str, str] = {}
        self._submitted_at: dict[str, float] = {}
        self._finished_at: dict[str, float] = {}
        self._lock = threading.RLock()

    def update_signals(
        self, signals: PipelineSchedulerSignals | Mapping[str, Any]
    ) -> PipelineSchedulerSignals:
        normalized = (
            signals
            if isinstance(signals, PipelineSchedulerSignals)
            else PipelineSchedulerSignals.from_mapping(signals)
        )
        with self._lock:
            self.signals = normalized
        return normalized

    def submit(self, task: PipelineTask) -> PipelineTask:
        if not isinstance(task, PipelineTask):
            raise TypeError("task must be a PipelineTask")
        with self._lock:
            if task.task_id in self._tasks:
                raise DuplicateTaskError(f"duplicate task {task.task_id!r} is already submitted")
            missing = [item for item in task.dependencies if item not in self._tasks]
            if missing:
                raise UnknownDependencyError(
                    f"task {task.task_id!r} has an unknown dependency: {', '.join(missing)}"
                )
            self._tasks[task.task_id] = task
            self._statuses[task.task_id] = StageStatus.PENDING
            self._submitted_at[task.task_id] = time.time()
            try:
                self._validate_acyclic()
            except Exception:
                self._tasks.pop(task.task_id, None)
                self._statuses.pop(task.task_id, None)
                self._submitted_at.pop(task.task_id, None)
                raise
        return task

    def submit_many(self, tasks: Iterable[PipelineTask]) -> tuple[PipelineTask, ...]:
        batch = tuple(tasks)
        if any(not isinstance(task, PipelineTask) for task in batch):
            raise TypeError("all submitted tasks must be PipelineTask instances")
        identifiers = [task.task_id for task in batch]
        if len(set(identifiers)) != len(identifiers):
            raise DuplicateTaskError("task identifiers in a submission batch must be unique")
        with self._lock:
            conflicts = sorted(set(identifiers) & set(self._tasks))
            if conflicts:
                raise DuplicateTaskError(f"tasks already submitted: {', '.join(conflicts)}")
            known = set(self._tasks) | set(identifiers)
            missing = sorted(
                {dependency for task in batch for dependency in task.dependencies if dependency not in known}
            )
            if missing:
                raise UnknownDependencyError(f"unknown dependency identifiers: {', '.join(missing)}")
            now = time.time()
            for task in batch:
                self._tasks[task.task_id] = task
                self._statuses[task.task_id] = StageStatus.PENDING
                self._submitted_at[task.task_id] = now
            try:
                self._validate_acyclic()
            except Exception:
                for task in batch:
                    self._tasks.pop(task.task_id, None)
                    self._statuses.pop(task.task_id, None)
                    self._submitted_at.pop(task.task_id, None)
                raise
        return batch

    def _validate_acyclic(self) -> None:
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(task_id: str) -> None:
            if task_id in visiting:
                raise PipelineCycleError(f"dependency cycle includes task {task_id!r}")
            if task_id in visited:
                return
            visiting.add(task_id)
            for dependency in self._tasks[task_id].dependencies:
                visit(dependency)
            visiting.remove(task_id)
            visited.add(task_id)

        for task_id in self._tasks:
            visit(task_id)

    def _propagate_blocked(self) -> None:
        changed = True
        while changed:
            changed = False
            for task_id, task in self._tasks.items():
                if self._statuses[task_id] is not StageStatus.PENDING:
                    continue
                dependency_statuses = [self._statuses[item] for item in task.dependencies]
                if any(
                    status in {StageStatus.FAILED, StageStatus.BLOCKED, StageStatus.CANCELLED}
                    for status in dependency_statuses
                ):
                    self._statuses[task_id] = StageStatus.BLOCKED
                    self._errors[task_id] = "dependency did not succeed"
                    self._finished_at[task_id] = time.time()
                    changed = True

    def ready_tasks(self) -> tuple[PipelineTask, ...]:
        with self._lock:
            self._propagate_blocked()
            ready = [
                task
                for task_id, task in self._tasks.items()
                if self._statuses[task_id] is StageStatus.PENDING
                and all(self._statuses[item] is StageStatus.SUCCEEDED for item in task.dependencies)
            ]
            return tuple(sorted(ready, key=lambda item: (item.stage.value, self._submitted_at[item.task_id], item.task_id)))

    def _effective_limits(self) -> StageConcurrencyLimits:
        s = self.signals
        base = self.initial_limits.to_dict()
        pressure_factor = 1.0
        worst_memory = max(s.memory_pressure, s.unified_memory_pressure, s.gpu_memory_pressure)
        if worst_memory >= 0.90 or s.swap_pressure > 0.0:
            pressure_factor = min(pressure_factor, 0.25)
        elif worst_memory >= 0.82:
            pressure_factor = min(pressure_factor, 0.50)
        if s.cpu_pressure >= 0.90:
            pressure_factor = min(pressure_factor, 0.50)
        elif s.cpu_pressure >= 0.85:
            pressure_factor = min(pressure_factor, 0.75)
        children = max(s.child_process_count, s.nested_solver_children)
        child_pressure = children / max(1, s.child_process_limit)
        if child_pressure >= 0.90:
            pressure_factor = min(pressure_factor, 0.25)
        elif child_pressure >= 0.75:
            pressure_factor = min(pressure_factor, 0.50)

        # Trainer/write cardinality is an invariant.  Pressure controls whether
        # acquisition succeeds through the resource scheduler, not how many
        # canonical owners can exist.
        scalable = (
            "snapshot_evaluation",
            "hammer",
            "codex_generation",
            "validation",
        )
        for name in scalable:
            current = base[name]
            base[name] = 0 if current == 0 else max(1, math.floor(current * pressure_factor))

        base["validation"] = min(base["validation"], s.validation_capacity)
        if s.validation_backlog > max(1, base["validation"] * 2):
            # Stop generation from growing an already saturated validation
            # queue while preserving at least one repair/generation lane.
            base["codex_generation"] = min(base["codex_generation"], max(1, base["validation"] // 2))
        if s.disjoint_codex_scopes:
            base["codex_generation"] = min(base["codex_generation"], s.disjoint_codex_scopes)
        if s.conflict_rate >= 0.20:
            base["codex_generation"] = min(base["codex_generation"], 1)
        elif s.conflict_rate >= 0.10:
            base["codex_generation"] = max(1, math.floor(base["codex_generation"] * 0.5))
        if (
            s.accepted_patch_target_per_hour > 0
            and s.accepted_patches_per_hour < s.accepted_patch_target_per_hour * 0.25
            and s.validation_backlog > 0
        ):
            base["codex_generation"] = min(base["codex_generation"], 1)

        # When the runtime publishes queue/rate evidence, size each lane to
        # clear approximately one measurement window of ready work.  A zero
        # observed rate means the lane is stalled and should retain its full
        # pressure-safe capacity; a high per-worker rate avoids launching idle
        # coordinators.  Actual queue contents remain authoritative when no
        # metric for a stage has been published yet.
        demand_stages = (
            PipelineStage.SNAPSHOT_EVALUATION,
            PipelineStage.HAMMER,
            PipelineStage.LEANSTRAL_SERVICE,
            PipelineStage.CODEX_GENERATION,
            PipelineStage.VALIDATION,
        )
        for stage in demand_stages:
            if stage not in s.ready_depth_by_stage:
                continue
            depth = s.ready_depth_by_stage[stage]
            name = stage.value
            if depth == 0:
                base[name] = 0
                continue
            observed_rate = s.service_rate_by_stage.get(stage, 0.0)
            demanded = depth if observed_rate <= 0.0 else math.ceil(depth / observed_rate)
            base[name] = min(base[name], depth, max(1, demanded))

        # A healthy persistent service is a singleton and must never scale out.
        base["leanstral_service"] = min(1, base["leanstral_service"])
        return StageConcurrencyLimits(**base)

    @property
    def effective_limits(self) -> StageConcurrencyLimits:
        with self._lock:
            return self._effective_limits()

    def _running_by_stage(self) -> dict[PipelineStage, int]:
        counts = {stage: 0 for stage in PipelineStage}
        for admission in self._admissions.values():
            counts[admission.task.stage] += 1
        return counts

    def admit_ready(self, *, max_tasks: int | None = None) -> tuple[StageAdmission, ...]:
        if max_tasks is not None:
            _non_negative_int(max_tasks, name="max_tasks")
        admitted: list[StageAdmission] = []
        with self._lock:
            limits = self._effective_limits()
            running = self._running_by_stage()
            for task in self.ready_tasks():
                if max_tasks is not None and len(admitted) >= max_tasks:
                    break
                limit = limits.for_stage(task.stage)
                if limit <= 0 or running[task.stage] >= limit:
                    continue
                canonical_lock: _CanonicalWriteLock | None = None
                if task.canonical_write:
                    canonical_lock = _CanonicalWriteLock(self.canonical_lock_path)
                    if not canonical_lock.acquire():
                        continue
                request = task.resources
                try:
                    lease = self.resource_scheduler.try_acquire(
                        _default_lane(task.stage),
                        cpu_slots=request.cpu_slots,
                        memory_mb=request.memory_mb,
                        unified_memory_mb=request.unified_memory_mb,
                        gpu_memory_mb=request.gpu_memory_mb,
                        child_process_slots=request.child_process_slots,
                        requires_gpu=request.requires_gpu,
                        request_id=task.task_id,
                    )
                except Exception:
                    if canonical_lock is not None:
                        canonical_lock.release()
                    raise
                if lease is None:
                    if canonical_lock is not None:
                        canonical_lock.release()
                    continue
                admission = StageAdmission(
                    task=task,
                    lease=lease,
                    admitted_at=time.time(),
                    effective_limit=limit,
                    _canonical_lock=canonical_lock,
                )
                self._admissions[task.task_id] = admission
                self._statuses[task.task_id] = StageStatus.RUNNING
                running[task.stage] += 1
                admitted.append(admission)
        return tuple(admitted)

    schedule = admit_ready

    def _finish(
        self,
        task_id: str,
        status: StageStatus,
        *,
        result: Any = None,
        error: BaseException | str | None = None,
    ) -> PipelineTask:
        with self._lock:
            if task_id not in self._tasks:
                raise KeyError(task_id)
            if self._statuses[task_id] is not StageStatus.RUNNING:
                raise InvalidTaskTransitionError(
                    f"task {task_id!r} is {self._statuses[task_id].value}, not running"
                )
            admission = self._admissions.pop(task_id)
            self._statuses[task_id] = status
            self._finished_at[task_id] = time.time()
            if status is StageStatus.SUCCEEDED:
                self._results[task_id] = result
            elif error is not None:
                self._errors[task_id] = f"{type(error).__name__}: {error}" if isinstance(error, BaseException) else str(error)
            try:
                admission.lease.release()
            finally:
                if admission._canonical_lock is not None:
                    admission._canonical_lock.release()
            self._propagate_blocked()
            return admission.task

    def complete(self, task_id: str, result: Any = None) -> PipelineTask:
        return self._finish(task_id, StageStatus.SUCCEEDED, result=result)

    def fail(self, task_id: str, error: BaseException | str) -> PipelineTask:
        return self._finish(task_id, StageStatus.FAILED, error=error)

    def cancel(self, task_id: str, reason: str = "cancelled") -> PipelineTask:
        with self._lock:
            if task_id not in self._tasks:
                raise KeyError(task_id)
            status = self._statuses[task_id]
            if status is StageStatus.PENDING:
                self._statuses[task_id] = StageStatus.CANCELLED
                self._errors[task_id] = reason
                self._finished_at[task_id] = time.time()
                self._propagate_blocked()
                return self._tasks[task_id]
            if status is not StageStatus.RUNNING:
                raise InvalidTaskTransitionError(f"task {task_id!r} is already {status.value}")
            self._admissions[task_id].lease.cancel()
        return self._finish(task_id, StageStatus.CANCELLED, error=reason)

    def status(self, task_id: str) -> StageStatus:
        with self._lock:
            return self._statuses[task_id]

    def result(self, task_id: str) -> Any:
        with self._lock:
            if self._statuses.get(task_id) is not StageStatus.SUCCEEDED:
                raise InvalidTaskTransitionError(f"task {task_id!r} did not succeed")
            return self._results[task_id]

    @property
    def done(self) -> bool:
        with self._lock:
            self._propagate_blocked()
            return bool(self._tasks) and all(status in _TERMINAL_STATUSES for status in self._statuses.values())

    def run(
        self,
        handlers: Mapping[PipelineStage | str, Callable[[PipelineTask], Any]],
        *,
        timeout: float | None = None,
        poll_interval_seconds: float = 0.01,
        max_workers: int | None = None,
    ) -> dict[str, Any]:
        """Execute submitted tasks until terminal, raising on handler failure.

        Handlers receive the immutable task.  A handler that launches nested
        solver processes can obtain its active admission through
        :meth:`admission_for` and pass ``admission.lease`` as their parent.
        """

        normalized_handlers = {_stage(stage): handler for stage, handler in handlers.items()}
        missing_handlers = sorted(
            {task.stage.value for task in self._tasks.values() if task.stage not in normalized_handlers}
        )
        if missing_handlers:
            raise ValueError(f"missing handlers for stages: {', '.join(missing_handlers)}")
        if timeout is not None:
            _non_negative_float(timeout, name="timeout")
        poll_interval_seconds = _non_negative_float(
            poll_interval_seconds, name="poll_interval_seconds"
        )
        if poll_interval_seconds <= 0:
            raise ValueError("poll_interval_seconds must be positive")
        if not self._tasks:
            return {}
        worker_cap = max_workers or max(1, sum(self.initial_limits.to_dict().values()))
        started = time.monotonic()
        failures: dict[str, BaseException] = {}
        futures: MutableMapping[Future[Any], str] = {}
        with ThreadPoolExecutor(max_workers=worker_cap, thread_name_prefix="legal-ir-stage") as pool:
            while not self.done or futures:
                if timeout is not None and time.monotonic() - started >= timeout:
                    for task_id in tuple(self._admissions):
                        self.cancel(task_id, "pipeline execution timeout")
                    raise TimeoutError("pipeline execution timed out")
                for admission in self.admit_ready(max_tasks=max(0, worker_cap - len(futures))):
                    future = pool.submit(normalized_handlers[admission.task.stage], admission.task)
                    futures[future] = admission.task_id
                if not futures:
                    if self.done:
                        break
                    time.sleep(poll_interval_seconds)
                    continue
                completed, _ = wait(
                    tuple(futures), timeout=poll_interval_seconds, return_when=FIRST_COMPLETED
                )
                for future in completed:
                    task_id = futures.pop(future)
                    try:
                        self.complete(task_id, future.result())
                    except BaseException as exc:
                        if self.status(task_id) is StageStatus.RUNNING:
                            self.fail(task_id, exc)
                        failures[task_id] = exc
        if failures:
            raise PipelineExecutionError(failures)
        return dict(self._results)

    execute = run

    def admission_for(self, task_id: str) -> StageAdmission:
        with self._lock:
            return self._admissions[task_id]

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            self._propagate_blocked()
            effective = self._effective_limits()
            return {
                "active_admission_count": len(self._admissions),
                "canonical_write_active": any(
                    admission.task.canonical_write for admission in self._admissions.values()
                ),
                "effective_limits": effective.to_dict(),
                "initial_limits": self.initial_limits.to_dict(),
                "resource_scheduler": self.resource_scheduler.snapshot(),
                "schema_version": PIPELINE_STAGE_SCHEDULER_SCHEMA_VERSION,
                "signals": self.signals.to_dict(),
                "tasks": {
                    task_id: {
                        **task.to_dict(),
                        "error": self._errors.get(task_id, ""),
                        "finished_at": self._finished_at.get(task_id),
                        "status": self._statuses[task_id].value,
                        "submitted_at": self._submitted_at[task_id],
                    }
                    for task_id, task in sorted(self._tasks.items())
                },
            }

    telemetry = snapshot

    def close(self) -> None:
        """Cancel and release all active admissions; pending tasks are retained."""

        for task_id in tuple(self._admissions):
            try:
                self.cancel(task_id, "scheduler closed")
            except (InvalidTaskTransitionError, KeyError):
                continue

    def __enter__(self) -> "PipelineStageScheduler":
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        self.close()


def build_canonical_pipeline_dag(
    prefix: str = "cycle",
    *,
    revision: str = "",
    resources_by_stage: Mapping[
        PipelineStage | str, StageResourceRequest | Mapping[str, Any]
    ] | None = None,
    payload_by_stage: Mapping[PipelineStage | str, Any] | None = None,
) -> tuple[PipelineTask, ...]:
    """Build the canonical eight-stage, immutable-snapshot dependency DAG."""

    prefix = str(prefix or "").strip()
    if not prefix:
        raise ValueError("prefix must be non-empty")
    resources = {_stage(key): value for key, value in dict(resources_by_stage or {}).items()}
    payloads = {_stage(key): value for key, value in dict(payload_by_stage or {}).items()}

    def task(
        stage: PipelineStage,
        dependencies: Sequence[PipelineStage] = (),
        *,
        metadata: Mapping[str, Any] | None = None,
    ) -> PipelineTask:
        return PipelineTask(
            task_id=f"{prefix}:{stage.value}",
            stage=stage,
            dependencies=tuple(f"{prefix}:{item.value}" for item in dependencies),
            resources=resources.get(stage, StageResourceRequest()),
            payload=payloads.get(stage),
            revision=revision,
            metadata=metadata or {},
        )

    trainer = task(PipelineStage.CANONICAL_TRAINER)
    snapshot = task(
        PipelineStage.SNAPSHOT_EVALUATION,
        (PipelineStage.CANONICAL_TRAINER,),
        metadata={"immutable_input_required": True},
    )
    hammer = task(
        PipelineStage.HAMMER,
        (PipelineStage.SNAPSHOT_EVALUATION,),
        metadata={"verified_output_required": True},
    )
    leanstral = task(
        PipelineStage.LEANSTRAL_SERVICE,
        (PipelineStage.SNAPSHOT_EVALUATION,),
        metadata={
            "persistent_service": True,
            "service_health_does_not_confer_proof_trust": True,
        },
    )
    codex = task(
        PipelineStage.CODEX_GENERATION,
        (PipelineStage.HAMMER, PipelineStage.LEANSTRAL_SERVICE),
        metadata={"disjoint_write_scope_required": True},
    )
    validation = task(PipelineStage.VALIDATION, (PipelineStage.CODEX_GENERATION,))
    persistence = task(PipelineStage.PERSISTENCE, (PipelineStage.VALIDATION,))
    merge = task(PipelineStage.MERGE, (PipelineStage.PERSISTENCE,))
    return trainer, snapshot, hammer, leanstral, codex, validation, persistence, merge


canonical_pipeline_tasks = build_canonical_pipeline_dag


__all__ = [
    "PIPELINE_STAGE_SCHEDULER_SCHEMA_VERSION",
    "DGX_SPARK_INITIAL_STAGE_LIMITS",
    "DuplicateTaskError",
    "InvalidTaskTransitionError",
    "PipelineCycleError",
    "PipelineExecutionError",
    "PipelineSchedulerError",
    "PipelineSchedulerSignals",
    "PipelineStage",
    "PipelineStageAdmission",
    "PipelineStageScheduler",
    "PipelineTask",
    "PipelineWorkItem",
    "StageAdmission",
    "StageConcurrencyLimits",
    "StageResourceRequest",
    "StageResources",
    "StageStatus",
    "StageTask",
    "UnknownDependencyError",
    "build_canonical_pipeline_dag",
    "canonical_pipeline_tasks",
]
