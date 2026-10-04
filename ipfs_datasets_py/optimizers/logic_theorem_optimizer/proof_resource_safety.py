"""Cheap Linux resource probes for conservative proof-work admission.

These probes never import GPU runtimes or launch commands. Reservations and
live memory checks complement, but do not replace, worker memory limits.
"""
from __future__ import annotations

import math
import os
from dataclasses import dataclass
from pathlib import Path

MIB = 1024 * 1024


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


def _psi(path: Path, kind: str) -> float:
    try:
        for line in path.read_text().splitlines():
            parts = line.split()
            if parts[0] == kind:
                value = float(dict(part.split("=") for part in parts[1:])["avg10"])
                if math.isfinite(value) and 0 <= value <= 100:
                    return value
    except (OSError, ValueError, KeyError, IndexError):
        pass
    return 0.0


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
    memory_stall = _psi(proc_root / "pressure/memory", "full")
    cpu_stall = _psi(proc_root / "pressure/cpu", "some")
    io_stall = _psi(proc_root / "pressure/io", "full")
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
        memory_stall = max(memory_stall, _psi(current / "memory.pressure", "full"))
        cpu_stall = max(cpu_stall, _psi(current / "cpu.pressure", "some"))
        io_stall = max(io_stall, _psi(current / "io.pressure", "full"))
        if current == cgroup_root:
            break
        current = current.parent
    if total <= 0 or available < 0:
        raise ValueError("invalid host memory telemetry")
    return ProofHostResources(max(1, cpu), max(1, total // MIB), available // MIB,
                              memory_stall, cpu_stall, io_stall,
                              min((limit for limit, _ in pid_budgets), default=None),
                              min((available for _, available in pid_budgets), default=None))
