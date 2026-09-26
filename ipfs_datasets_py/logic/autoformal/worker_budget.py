"""Choose how many ingest workers fit the machine right now.

The DuckDB owner stays single-writer. This budget only limits how many
parse and compile processes run beside it.
"""
from __future__ import annotations

import os


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
    per_worker_mb: int = 400,
    reserve_mb: int = 512,
) -> int:
    """Return how many worker processes to run on this machine."""

    cpus = int(cpu_count if cpu_count is not None else (os.cpu_count() or 1))
    cpus = max(1, cpus)
    if load_average is None:
        try:
            load_average = float(os.getloadavg()[0])
        except OSError:
            load_average = 0.0
    if available_mb is None:
        available_mb = available_memory_mb()
    cpu_room = max(1, cpus - int(max(0.0, float(load_average) - 1.0)))
    if available_mb <= reserve_mb:
        mem_room = 1
    else:
        mem_room = max(1, (int(available_mb) - reserve_mb) // max(1, per_worker_mb))
    return max(1, min(cpus, cpu_room, mem_room))
