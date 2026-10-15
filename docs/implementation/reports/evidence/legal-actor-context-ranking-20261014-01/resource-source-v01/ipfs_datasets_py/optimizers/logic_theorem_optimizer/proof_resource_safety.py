"""Cheap Linux resource probes for conservative proof-work admission.

These probes never import GPU runtimes or launch commands. Reservations and
live memory checks complement, but do not replace, worker memory limits.
"""
from __future__ import annotations

import math
import os
from dataclasses import dataclass, field
from pathlib import Path

MIB = 1024 * 1024
MAX_PRESSURE_CGROUP_SAMPLES = 8


@dataclass(frozen=True, slots=True)
class PressureReading:
    """One optional PSI reading; absence never masquerades as observed zero."""

    avg10: float | None
    status: str

    def __post_init__(self) -> None:
        if type(self.status) is not str or self.status not in {"observed", "unavailable", "malformed"}:
            raise ValueError("invalid PSI reading status")
        if self.status == "observed":
            if (type(self.avg10) not in {int, float} or not math.isfinite(self.avg10)
                    or not 0 <= self.avg10 <= 100):
                raise ValueError("observed PSI must be a finite percentage")
        elif self.avg10 is not None:
            raise ValueError("unobserved PSI cannot carry a percentage")

    @property
    def effective_percent(self) -> float:
        # Preserve the pre-existing optional-PSI fallback used for admission.
        return 0.0 if self.avg10 is None else self.avg10

    def to_dict(self) -> dict:
        self.__post_init__()
        return {"avg10": self.avg10, "status": self.status}


@dataclass(frozen=True, slots=True)
class PressureScopeSample:
    scope: str
    depth: int | None
    memory: PressureReading
    cpu: PressureReading
    io: PressureReading

    def __post_init__(self) -> None:
        if type(self.scope) is not str or not ((self.scope == "host" and self.depth is None)
                or (self.scope == "cgroup" and type(self.depth) is int
                    and 0 <= self.depth < MAX_PRESSURE_CGROUP_SAMPLES)):
            raise ValueError("bounded anonymous PSI scope required")
        if any(type(value) is not PressureReading for value in (self.memory, self.cpu, self.io)):
            raise ValueError("exact immutable PSI readings required")

    def to_dict(self) -> dict:
        self.__post_init__()
        return dict(scope=self.scope, depth=self.depth, memory=self.memory.to_dict(),
                    cpu=self.cpu.to_dict(), io=self.io.to_dict())


@dataclass(frozen=True, slots=True)
class ProofPressureSources:
    """Bounded attribution only; it cannot modify admission or its accounting.

    Memory and I/O record ``full avg10``; CPU records ``some avg10``.
    Depth zero names the selected visible cgroup, never a host pathname.
    All further ancestors are still sampled for the original aggregate gate.
    """

    samples: tuple[PressureScopeSample, ...]
    omitted_cgroup_scopes: int = 0
    omitted_maxima: tuple[float | None, float | None, float | None] = (None, None, None)

    def __post_init__(self) -> None:
        if (type(self.samples) is not tuple or not 1 <= len(self.samples) <= 1 + MAX_PRESSURE_CGROUP_SAMPLES
                or any(type(row) is not PressureScopeSample for row in self.samples)):
            raise ValueError("bounded immutable PSI sample population required")
        for position, row in enumerate(self.samples):
            row.__post_init__()
            if (row.scope, row.depth) != (("host", None) if position == 0 else ("cgroup", position - 1)):
                raise ValueError("PSI samples must retain host then contiguous cgroup depths")
        if (type(self.omitted_cgroup_scopes) is not int
                or not 0 <= self.omitted_cgroup_scopes <= 2**53 - 1
                or (self.omitted_cgroup_scopes and len(self.samples) != 1 + MAX_PRESSURE_CGROUP_SAMPLES)):
            raise ValueError("invalid omitted cgroup scope count")
        if type(self.omitted_maxima) is not tuple or len(self.omitted_maxima) != 3:
            raise ValueError("three immutable omitted PSI maxima required")
        for value in self.omitted_maxima:
            if value is not None and (type(value) not in {int, float}
                    or not math.isfinite(value) or not 0 <= value <= 100):
                raise ValueError("invalid omitted PSI percentage")
        if not self.omitted_cgroup_scopes and any(value is not None for value in self.omitted_maxima):
            raise ValueError("unomitted scopes cannot carry omitted PSI maxima")

    def to_dict(self) -> dict:
        self.__post_init__()
        return dict(schema="proof-pressure-sources@1", samples=[row.to_dict() for row in self.samples],
                    omitted_cgroup_scopes=self.omitted_cgroup_scopes,
                    omitted_maxima=dict(zip(("memory", "cpu", "io"), self.omitted_maxima)))


@dataclass(frozen=True)
class ProofHostResources:
    cpu_slots: int
    total_memory_mb: int
    available_memory_mb: int
    memory_stall_percent: float = 0.0
    cpu_stall_percent: float = 0.0
    io_stall_percent: float = 0.0
    # Linux PID controllers count kernel tasks (including threads), not just
    # the scheduler's child-process envelopes. None preserves unknown telemetry.
    pid_task_limit: int | None = None
    available_pid_tasks: int | None = None
    # Optional provenance must not affect equality, scheduler configuration or
    # scalar admission. Unknown/custom metadata is ignored by the observer.
    pressure_sources: ProofPressureSources | None = field(default=None, compare=False, repr=False)

    def __post_init__(self) -> None:
        for name in ("cpu_slots", "total_memory_mb", "available_memory_mb"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{name} must be a non-negative integer")
        if self.cpu_slots == 0 or self.total_memory_mb == 0:
            raise ValueError("CPU and total memory capacity must be positive")
        if (self.pid_task_limit is None) != (self.available_pid_tasks is None):
            raise ValueError("PID task limit and availability must be supplied together")
        for name in ("pid_task_limit", "available_pid_tasks"):
            value = getattr(self, name)
            if value is not None and (type(value) is not int or value < 0):
                raise ValueError(f"{name} must be a non-negative integer or None")
        if self.pid_task_limit is not None and self.available_pid_tasks > self.pid_task_limit:
            raise ValueError("available PID tasks exceed the observed limit")
        for name in ("memory_stall_percent", "cpu_stall_percent", "io_stall_percent"):
            value = getattr(self, name)
            if isinstance(value, bool) or not math.isfinite(value) or not 0 <= value <= 100:
                raise ValueError(f"{name} must be finite and between 0 and 100")


def _psi_reading(path: Path, kind: str) -> PressureReading:
    status = "unavailable"
    try:
        for line in path.read_text().splitlines():
            parts = line.split()
            if parts[0] == kind:
                value = float(dict(part.split("=") for part in parts[1:])["avg10"])
                if math.isfinite(value) and 0 <= value <= 100:
                    return PressureReading(value, "observed")
                status = "malformed"
    except OSError:
        status = "unavailable"
    except (ValueError, KeyError, IndexError):
        status = "malformed"
    return PressureReading(None, status)


def _psi(path: Path, kind: str) -> float:
    """Compatibility scalar surface, with the original optional-read fallback."""
    return _psi_reading(path, kind).effective_percent


def _task_counter_text(path: Path, *, optional: bool = False) -> str | None:
    """Read small kernel counters; known unreadable/malformed data fails closed."""
    try:
        with path.open("r", encoding="ascii") as stream:
            value = stream.read(4097)
    except FileNotFoundError:
        if optional:
            return None
        raise
    if len(value) > 4096:
        raise ValueError("PID task telemetry exceeds its byte bound")
    return value.strip()


def _task_integer(value: str) -> int:
    if not value or not value.isascii() or not value.isdecimal():
        raise ValueError("invalid PID task telemetry")
    return int(value)


def _cgroup_pid_budget(current: Path) -> tuple[int, int] | None:
    raw = _task_counter_text(current / "pids.max", optional=True)
    if raw is None or raw == "max":
        return None
    limit = _task_integer(raw)
    used = _task_integer(_task_counter_text(current / "pids.current"))
    # A controller can be lowered below current usage without killing tasks.
    return limit, max(0, limit - used)


def _host_pid_budget(proc_root: Path) -> tuple[int, int] | None:
    raw = _task_counter_text(proc_root / "sys/kernel/threads-max", optional=True)
    if raw is None:
        return None
    limit = _task_integer(raw)
    if limit == 0:
        raise ValueError("host kernel task limit must be positive")
    load = _task_counter_text(proc_root / "loadavg")
    fields = load.split()
    if len(fields) != 5 or len(fields[3].split("/")) != 2:
        raise ValueError("invalid host kernel task count")
    running, current = (_task_integer(value) for value in fields[3].split("/"))
    if running > current:
        raise ValueError("invalid runnable kernel task count")
    return limit, max(0, limit - current)


def _memory_counter_text(path: Path, *, optional: bool = False) -> str | None:
    """Distinguish absent controls from unreadable kernel memory counters."""
    try:
        with path.open("r", encoding="ascii") as stream:
            value = stream.read(4097)
    except FileNotFoundError:
        if optional:
            return None
        raise
    if len(value) > 4096:
        raise ValueError("memory telemetry exceeds its byte bound")
    return value.strip()


def _memory_integer(value: str) -> int:
    if not value or not value.isascii() or not value.isdecimal():
        raise ValueError("invalid memory telemetry")
    return int(value)


def _cgroup_memory_budget(current: Path) -> tuple[int, int] | None:
    """Use the tightest visible v2 boundary, requiring its current usage.

    Missing controls and explicit ``max`` are optional/unlimited. A present
    unreadable or malformed control is unknown, and finite boundaries cannot
    be discarded when their shared usage counter is unavailable. The caller
    propagates these errors to the scheduler's existing telemetry backoff.
    """
    limits = []
    for name in ("memory.high", "memory.max"):
        raw = _memory_counter_text(current / name, optional=True)
        if raw is not None and raw != "max":
            limits.append(_memory_integer(raw))
    if not limits:
        return None
    limit = min(limits)
    used = _memory_integer(_memory_counter_text(current / "memory.current"))
    return limit, max(0, limit - used)


def collect_proof_host_resources(
    proc_root: Path = Path("/proc"), cgroup_root: Path = Path("/sys/fs/cgroup"),
) -> ProofHostResources:
    """Respect affinity and visible cgroup-v2 ancestor limits.

    Missing host memory telemetry raises rather than inventing a safe capacity.
    PSI and absent cgroup controls are optional on systems without these
    facilities. Present memory controls must be readable and well-formed;
    finite memory.high/max boundaries require readable, well-formed usage at
    every visible ancestor. A failed probe prevents proof-work admission.
    Visible cgroup PID limits and host threads-max/loadavg counts provide cheap
    kernel-task headroom. A known finite limit with unreadable/malformed usage
    raises instead of silently dropping the constraint. RLIMIT_NPROC is not
    reported as free capacity: it needs a complete real-UID thread census and
    privilege/namespace handling, which this cheap sampler does not perform.
    """
    values = {}
    for line in (proc_root / "meminfo").read_text().splitlines():
        key, value = line.split(":", 1)
        values[key] = int(value.split()[0]) * 1024
    total = values["MemTotal"]
    available = values["MemAvailable"]
    cpu = len(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else (os.cpu_count() or 1)
    current = cgroup_root
    try:
        for line in (proc_root / "self/cgroup").read_text().splitlines():
            if line.startswith("0::"):
                relative = line[3:].lstrip("/")
                if ".." not in Path(relative).parts:
                    candidate = cgroup_root / relative
                    if candidate.is_dir():
                        current = candidate
                break
    except OSError:
        pass
    pid_budgets = []
    host_pid_budget = _host_pid_budget(proc_root)
    if host_pid_budget is not None:
        pid_budgets.append(host_pid_budget)
    host_readings = (_psi_reading(proc_root / "pressure/memory", "full"),
                     _psi_reading(proc_root / "pressure/cpu", "some"),
                     _psi_reading(proc_root / "pressure/io", "full"))
    memory_stall, cpu_stall, io_stall = (row.effective_percent for row in host_readings)
    samples = [PressureScopeSample("host", None, *host_readings)]
    depth, omitted_scopes = 0, 0
    omitted_maxima = [None, None, None]
    while True:
        pid_budget = _cgroup_pid_budget(current)
        if pid_budget is not None:
            pid_budgets.append(pid_budget)
        try:
            quota, period = (current / "cpu.max").read_text().split()
            if quota != "max":
                cpu = min(cpu, max(1, int(quota) // int(period)))
        except (OSError, ValueError, ZeroDivisionError):
            pass
        # memory.high is the throttling boundary; avoid crossing it as well
        # as the hard OOM boundary memory.max.
        memory_budget = _cgroup_memory_budget(current)
        if memory_budget is not None:
            limit_bytes, available_bytes = memory_budget
            total = min(total, limit_bytes)
            available = min(available, available_bytes)
        readings = (_psi_reading(current / "memory.pressure", "full"),
                    _psi_reading(current / "cpu.pressure", "some"),
                    _psi_reading(current / "io.pressure", "full"))
        memory_stall = max(memory_stall, readings[0].effective_percent)
        cpu_stall = max(cpu_stall, readings[1].effective_percent)
        io_stall = max(io_stall, readings[2].effective_percent)
        if depth < MAX_PRESSURE_CGROUP_SAMPLES:
            samples.append(PressureScopeSample("cgroup", depth, *readings))
        else:
            omitted_scopes += 1
            for position, row in enumerate(readings):
                if row.avg10 is not None:
                    previous = omitted_maxima[position]
                    omitted_maxima[position] = row.avg10 if previous is None else max(previous, row.avg10)
        depth += 1
        if current == cgroup_root:
            break
        current = current.parent
    if total <= 0 or available < 0:
        raise ValueError("invalid host memory telemetry")
    return ProofHostResources(max(1, cpu), max(1, total // MIB), available // MIB,
                              memory_stall, cpu_stall, io_stall,
                              min((limit for limit, _ in pid_budgets), default=None),
                              min((available for _, available in pid_budgets), default=None),
                              pressure_sources=ProofPressureSources(tuple(samples), omitted_scopes, tuple(omitted_maxima)))
