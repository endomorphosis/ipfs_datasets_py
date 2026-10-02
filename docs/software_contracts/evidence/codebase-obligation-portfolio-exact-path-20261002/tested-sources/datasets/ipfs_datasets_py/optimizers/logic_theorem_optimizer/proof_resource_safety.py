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

    def __post_init__(self) -> None:
        for name in ("cpu_slots", "total_memory_mb", "available_memory_mb"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{name} must be a non-negative integer")
        if self.cpu_slots == 0 or self.total_memory_mb == 0:
            raise ValueError("CPU and total memory capacity must be positive")
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


def collect_proof_host_resources(
    proc_root: Path = Path("/proc"), cgroup_root: Path = Path("/sys/fs/cgroup"),
) -> ProofHostResources:
    """Respect affinity and visible cgroup-v2 ancestor limits.

    Missing memory telemetry raises rather than inventing a safe capacity.
    PSI and cgroup files are optional on systems without these facilities.
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
    memory_stall = _psi(proc_root / "pressure/memory", "full")
    cpu_stall = _psi(proc_root / "pressure/cpu", "some")
    io_stall = _psi(proc_root / "pressure/io", "full")
    while True:
        try:
            quota, period = (current / "cpu.max").read_text().split()
            if quota != "max":
                cpu = min(cpu, max(1, int(quota) // int(period)))
        except (OSError, ValueError, ZeroDivisionError):
            pass
        # memory.high is the throttling boundary; avoid crossing it as well
        # as the hard OOM boundary memory.max.
        for name in ("memory.high", "memory.max"):
            try:
                limit = (current / name).read_text().strip()
                if limit != "max":
                    limit_bytes = int(limit)
                    used = int((current / "memory.current").read_text())
                    total = min(total, limit_bytes)
                    available = min(available, max(0, limit_bytes - used))
            except (OSError, ValueError):
                pass
        memory_stall = max(memory_stall, _psi(current / "memory.pressure", "full"))
        cpu_stall = max(cpu_stall, _psi(current / "cpu.pressure", "some"))
        io_stall = max(io_stall, _psi(current / "io.pressure", "full"))
        if current == cgroup_root:
            break
        current = current.parent
    if total <= 0 or available < 0:
        raise ValueError("invalid host memory telemetry")
    return ProofHostResources(max(1, cpu), max(1, total // MIB), available // MIB,
                              memory_stall, cpu_stall, io_stall)
