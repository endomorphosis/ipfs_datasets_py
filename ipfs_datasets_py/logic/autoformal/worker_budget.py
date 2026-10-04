"""Choose how many workers fit the machine right now.

A 20-CPU host with about 45 GB free finished 20 compiler processes and 20
one-epoch autoencoder processes at the same time. Compiler workers were about
41 MB. Autoencoder workers were about 760–813 MB. The budget therefore uses
the CPU count whenever free memory can hold that width. Existing load does
not shrink it: that same host was already near load 8 and still completed a
full CPU-width batch. The DuckDB owner stays single-writer.
"""
from __future__ import annotations

import os

# Measured resident size, rounded up so a worker is not packed against the reserve.
COMPILER_WORKER_MB = 64
AUTOENCODER_WORKER_MB = 1024


def available_memory_mb() -> int:
    """Approximate free memory in megabytes. Zero when it cannot be read."""

    try:
        with open("/proc/meminfo", encoding="utf-8") as handle:
            for line in handle:
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) // 1024
    except (OSError, ValueError, IndexError):
        return 0
    return 0


def worker_budget(
    *,
    cpu_count: int | None = None,
    load_average: float | None = None,
    available_mb: int | None = None,
    per_worker_mb: int | None = None,
    reserve_mb: int = 512,
    kind: str = "compiler",
) -> int:
    """Return how many worker processes to run on this machine.

    ``kind`` is ``compiler`` or ``autoencoder``. ``load_average`` is accepted
    and ignored: a full-width run completed while the host was already busy.
    """

    del load_average
    cpus = max(1, int(cpu_count if cpu_count is not None else (os.cpu_count() or 1)))
    if per_worker_mb is None:
        per_worker_mb = AUTOENCODER_WORKER_MB if kind == "autoencoder" else COMPILER_WORKER_MB
    if available_mb is None:
        available_mb = available_memory_mb()
    if int(available_mb) <= reserve_mb:
        mem_room = 1
    else:
        mem_room = max(1, (int(available_mb) - reserve_mb) // max(1, int(per_worker_mb)))
    return max(1, min(cpus, mem_room))


def resolve_worker_count(
    requested: int | None = None,
    *,
    maximum: int = 32,
    kind: str = "compiler",
) -> int:
    """Use an explicit count, or the current CPU and memory budget.

    Zero and None mean automatic. The result stays inside 1..maximum.
    """

    if requested is None or int(requested) == 0:
        count = worker_budget(kind=kind)
    else:
        count = int(requested)
    if count < 1:
        raise ValueError("worker count must be positive")
    return min(count, int(maximum))
