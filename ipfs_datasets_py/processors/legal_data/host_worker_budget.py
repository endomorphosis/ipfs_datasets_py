"""Live CPU, RAM, and swap budget for parallel legal-index work.

Thread pools are the right tool for stages that already hold a
multi-tens-of-GiB index in this process: a process pool would duplicate
it. Tokenization is different. It runs *before* the inverted index
exists, each worker holds one partition/chunk of source text, and the
GIL makes threads useless. Use :func:`tokenize_process_pool_size` for
that path.

Default thread-pool worker count is computed from unused cores, available
RAM, and a half-machine cap. Swap is a weak signal on its own; admission
uses a combined RAM+CPU+swap score and only collapses to 1 when that
joint pressure is high or RAM headroom is gone.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

MIN_AVAILABLE_BYTES = 2 * 1024 * 1024 * 1024
BYTES_PER_WORKER = 2 * 1024 * 1024 * 1024
COMBINED_COLLAPSE = 0.85
COMBINED_SCALE_START = 0.50
MEM_WEIGHT = 0.45
CPU_WEIGHT = 0.40
SWAP_WEIGHT = 0.15
TOKENIZE_BYTES_PER_WORKER = 768 * 1024 * 1024
TOKENIZE_RAM_FRACTION = 0.45
TOKENIZE_CPU_RESERVE = 1
TOKENIZE_HARD_CAP = 32
TOKENIZE_WORKERS_ENV = "LEGAL_TOKENIZE_WORKERS"


@dataclass(frozen=True, slots=True)
class HostPressureSnapshot:
    """Point-in-time host load used by :func:`host_worker_pressure`."""

    nproc: int
    load1: float
    mem_available: int
    mem_total: int
    swap_free: int | None
    swap_total: int | None = None


def _read_proc(path: str) -> str:
    return Path(path).read_text(encoding="ascii", errors="replace")


def heuristic_worker_cap(nproc: int) -> int:
    """Leave half the cores for the OS and existing runtime threads."""

    n = max(1, int(nproc))
    return max(1, n // 2)


def _ratio(used_or_load: float, total: float) -> float:
    if total <= 0:
        return 0.0
    return max(0.0, min(1.0, float(used_or_load) / float(total)))


def combined_pressure(snapshot: HostPressureSnapshot) -> tuple[float, dict[str, float]]:
    """Weighted RAM + CPU + swap pressure in ``[0, 1]``.

    Swap is only 15% of the score so a full swap file with free RAM and
    idle CPU does not collapse the pool.
    """

    nproc = max(1, int(snapshot.nproc))
    cpu = _ratio(float(snapshot.load1), float(nproc))
    mem_total = int(snapshot.mem_total)
    mem_available = int(snapshot.mem_available)
    mem = 0.0
    if mem_total > 0:
        mem = _ratio(mem_total - mem_available, mem_total)
    swap = 0.0
    if snapshot.swap_total and snapshot.swap_total > 0 and snapshot.swap_free is not None:
        swap = _ratio(int(snapshot.swap_total) - int(snapshot.swap_free), int(snapshot.swap_total))
    score = MEM_WEIGHT * mem + CPU_WEIGHT * cpu + SWAP_WEIGHT * swap
    score = max(0.0, min(1.0, score))
    return score, {"cpu": cpu, "mem": mem, "swap": swap, "score": score}


def read_host_pressure_snapshot() -> HostPressureSnapshot:
    """Read ``/proc`` load, RAM, and swap without allocating workers."""

    nproc = os.cpu_count() or 1
    try:
        load1 = float(_read_proc("/proc/loadavg").split()[0])
    except (OSError, ValueError, IndexError):
        load1 = 0.0

    mem_available = 0
    mem_total = 0
    swap_free: int | None = None
    swap_total: int | None = None
    try:
        fields: dict[str, int] = {}
        for line in _read_proc("/proc/meminfo").splitlines():
            name, rest = line.split(":", 1)
            fields[name] = int(rest.split()[0]) * 1024
        mem_available = int(fields.get("MemAvailable") or fields.get("MemFree") or 0)
        mem_total = int(fields.get("MemTotal") or 0)
        swap_total_bytes = int(fields.get("SwapTotal") or 0)
        if swap_total_bytes > 0:
            swap_total = swap_total_bytes
            swap_free = int(fields.get("SwapFree") or 0)
    except (OSError, ValueError):
        pass
    return HostPressureSnapshot(
        nproc=max(1, int(nproc)),
        load1=float(load1),
        mem_available=int(mem_available),
        mem_total=int(mem_total),
        swap_free=swap_free,
        swap_total=swap_total,
    )


def host_worker_pressure(
    snapshot: HostPressureSnapshot | None = None,
) -> tuple[int, str]:
    """Return ``(max_workers, reason)`` from combined RAM+CPU+swap pressure.

    Always at least 1 so required work can finish serially. Idle size is
    ``min(unused_cores, available_RAM / 2GiB, nproc // 2)``.
    """

    snap = snapshot or read_host_pressure_snapshot()
    nproc = max(1, int(snap.nproc))
    load1 = max(0.0, float(snap.load1))
    mem_available = int(snap.mem_available)
    score, parts = combined_pressure(snap)

    if mem_available and mem_available < MIN_AVAILABLE_BYTES:
        return 1, "host_memory_headroom"
    if score >= COMBINED_COLLAPSE:
        return 1, "host_combined_pressure"

    unused = max(1, int(nproc - load1))
    by_mem = max(1, mem_available // BYTES_PER_WORKER) if mem_available else 1
    cap = heuristic_worker_cap(nproc)
    workers = min(unused, by_mem, cap)
    if score >= COMBINED_SCALE_START:
        scale = (COMBINED_COLLAPSE - score) / (COMBINED_COLLAPSE - COMBINED_SCALE_START)
        workers = max(1, int(workers * max(0.0, min(1.0, scale))))
    return max(1, workers), "admitted"


def cpu_memory_worker_limit(
    requested: int | None = None,
    snapshot: HostPressureSnapshot | None = None,
) -> int:
    """Cap a thread pool against live CPU, RAM, and swap pressure."""

    admitted, _reason = host_worker_pressure(snapshot)
    if requested is None:
        return max(1, admitted)
    want = max(1, int(requested))
    return max(1, min(want, admitted))


def cgroup_memory_limit_bytes() -> int | None:
    """Return the cgroup memory cap when one is set, else ``None``."""

    for path in (
        Path("/sys/fs/cgroup/memory.max"),
        Path("/sys/fs/cgroup/memory.high"),
        Path("/sys/fs/cgroup/memory/memory.limit_in_bytes"),
    ):
        try:
            raw = path.read_text(encoding="ascii", errors="replace").strip()
        except OSError:
            continue
        if not raw or raw == "max":
            continue
        try:
            value = int(raw)
        except ValueError:
            continue
        if value > 0:
            return value
    return None


@dataclass(frozen=True, slots=True)
class TokenizePoolPlan:
    """Process-pool sizing for corpus tokenization (not a live index)."""

    workers: int
    reason: str
    cpu_count: int
    mem_available_bytes: int
    per_task_budget_bytes: int
    ram_fraction: float = TOKENIZE_RAM_FRACTION
    start_method: str = "spawn"

    def to_dict(self) -> dict[str, int | str | float]:
        return {
            "cpu_count": self.cpu_count,
            "mem_available_bytes": self.mem_available_bytes,
            "per_task_budget_bytes": self.per_task_budget_bytes,
            "ram_fraction": self.ram_fraction,
            "reason": self.reason,
            "start_method": self.start_method,
            "workers": self.workers,
        }


def tokenize_process_pool_size(
    snapshot: HostPressureSnapshot | None = None,
    *,
    per_task_budget: int = TOKENIZE_BYTES_PER_WORKER,
    requested: int | None = None,
) -> TokenizePoolPlan:
    """Admit a spawn process pool for per-document / per-partition tokenize.

    Unlike :func:`host_worker_pressure`, this may use more than half the
    cores: workers do not share a materialized index. RAM still wins. A
    cgroup memory.max, if present, caps MemAvailable. ``LEGAL_TOKENIZE_WORKERS``
    pins the count when set to a positive integer.
    """

    live = snapshot is None
    snap = snapshot or read_host_pressure_snapshot()
    nproc = max(1, int(snap.nproc))
    mem_available = int(snap.mem_available)
    if live:
        cgroup = cgroup_memory_limit_bytes()
        if cgroup is not None:
            mem_available = min(mem_available, cgroup) if mem_available else cgroup
    score, _parts = combined_pressure(snap)
    budget = max(1, int(per_task_budget))
    reason = "admitted"
    if mem_available and mem_available < MIN_AVAILABLE_BYTES:
        workers = 1
        reason = "host_memory_headroom"
    elif score >= COMBINED_COLLAPSE:
        workers = 1
        reason = "host_combined_pressure"
    else:
        cpu_cap = max(1, nproc - TOKENIZE_CPU_RESERVE)
        mem_cap = max(1, int((mem_available * TOKENIZE_RAM_FRACTION) / budget)) if mem_available else 1
        workers = min(cpu_cap, mem_cap, TOKENIZE_HARD_CAP)
        if score >= COMBINED_SCALE_START:
            scale = (COMBINED_COLLAPSE - score) / (COMBINED_COLLAPSE - COMBINED_SCALE_START)
            workers = max(1, int(workers * max(0.0, min(1.0, scale))))
    env_raw = os.environ.get(TOKENIZE_WORKERS_ENV, "").strip()
    if env_raw.isdigit() and int(env_raw) > 0:
        workers = min(int(env_raw), TOKENIZE_HARD_CAP, max(1, nproc))
        reason = "env_override"
    if requested is not None:
        workers = min(max(1, int(requested)), TOKENIZE_HARD_CAP, max(1, nproc))
        reason = "requested"
    workers = max(1, int(workers))
    return TokenizePoolPlan(
        workers=workers,
        reason=reason,
        cpu_count=nproc,
        mem_available_bytes=int(mem_available),
        per_task_budget_bytes=budget,
    )
