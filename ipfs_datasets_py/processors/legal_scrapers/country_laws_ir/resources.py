"""Admit country-IR workers from live memory, disk, and GPU headroom.

The caller keeps at most ``Admission.workers`` builds in flight. Zero workers
means pause and sleep ``backoff_seconds`` instead of starting another country.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class GpuSnapshot:
    index: int
    memory_free_mib: int
    memory_total_mib: int


@dataclass(frozen=True)
class HostSnapshot:
    """One host reading for admission.

    ``mem_available_gib`` is raw Linux MemAvailable. ``schedulable_gib`` adds
    ZFS ARC above arc_c_min. A negative schedulable value means the caller
    did not measure the ARC, and admission then uses the raw figure. The
    under-6 GiB pause keeps using the raw figure.
    """

    mem_available_gib: float
    disk_free_gib: float
    gpus: tuple[GpuSnapshot, ...]
    schedulable_gib: float = -1.0


@dataclass(frozen=True)
class Admission:
    workers: int
    devices: tuple[str, ...]
    backoff_s: float
    reason: str


def job_slots(corpus_rows: int) -> int:
    """How many admission slots one country consumes.

    Unknown size costs one slot. A corpus of at least 150_000 rows costs two.
    A million-row corpus costs four, so it can share a wide pool instead of
    waiting until every other country has finished.
    """

    rows = int(corpus_rows or 0)
    if rows >= 1_000_000:
        return 4
    if rows >= 150_000:
        return 2
    return 1


def can_admit(used_slots: int, limit: int, cost: int) -> bool:
    if limit <= 0 or cost <= 0:
        return False
    return used_slots + cost <= limit


def backoff_seconds(base: float, pressure: int) -> float:
    """Double the pause on each refused admission, and cap it at two minutes."""

    if base <= 0:
        return 0.0
    steps = min(max(int(pressure), 0), 4)
    return min(120.0, float(base) * (2**steps))


def assign_device(devices: tuple[str, ...], inflight: tuple[str, ...]) -> str:
    if not devices:
        return "cpu"
    counts = {device: inflight.count(device) for device in devices}
    return min(devices, key=lambda device: (counts[device], devices.index(device)))


def admission_budget_gib(snap: HostSnapshot) -> float:
    """RAM the slot formula may use.

    Probe sets ``schedulable_gib`` to MemAvailable plus evictable ZFS ARC.
    Callers that only fill ``mem_available_gib`` leave the ARC unmeasured.
    """

    if snap.schedulable_gib >= 0:
        return snap.schedulable_gib
    return snap.mem_available_gib


def admit_parallelism(
    snap: HostSnapshot,
    *,
    ceiling: int,
    per_worker_gib: float = 6.0,
    reserve_gib: float = 8.0,
    gpu_free_mib: int = 3072,
    disk_pause_gib: float = 20.0,
    disk_slow_gib: float = 40.0,
) -> Admission:
    """Return how many country builds may start, and which devices they may use.

    The slot count uses schedulable RAM, so evictable ZFS ARC counts as room.
    The pause under 6 GiB uses raw MemAvailable. ARC shrink is not instant,
    and MemAbort keeps that same raw floor.
    """

    ceiling = max(0, int(ceiling))
    budget = admission_budget_gib(snap)
    if snap.disk_free_gib >= 0 and snap.disk_free_gib < disk_pause_gib:
        return Admission(0, (), 15.0, "disk")
    if snap.mem_available_gib >= 0 and snap.mem_available_gib < 6.0:
        return Admission(0, (), 15.0, "memory")

    if budget < 0:
        ram_slots = 1
    else:
        ram_slots = int((budget - reserve_gib) // per_worker_gib)
        if budget < 12.0:
            ram_slots = min(ram_slots, 1)
        ram_slots = max(0, ram_slots)

    usable = tuple(
        f"cuda:{gpu.index}"
        for gpu in snap.gpus
        if gpu.memory_free_mib >= gpu_free_mib
    )
    if snap.gpus and not usable:
        return Admission(0, (), 10.0, "gpu")
    if not snap.gpus:
        devices: tuple[str, ...] = ("cpu",)
        device_slots = 4
    else:
        devices = usable
        # Encode stays one-at-a-time per GPU. The extra slots overlap
        # download, normalize, and search-graph builds while RAM is free.
        device_slots = len(usable) * 4

    if snap.disk_free_gib >= 0 and snap.disk_free_gib < disk_slow_gib:
        device_slots = min(device_slots, 1)
        ram_slots = min(ram_slots, 1)

    workers = min(ceiling, ram_slots, device_slots)
    if workers <= 0:
        return Admission(0, (), 15.0, "budget")
    return Admission(workers, devices, 0.0, "ok")


def probe_host(anchor: Path | None = None) -> HostSnapshot:
    """Read RAM, free space on ``anchor``, and ``nvidia-smi`` memory.

    The snapshot keeps raw MemAvailable and a schedulable budget. The budget
    adds ZFS ARC above arc_c_min. MemAbort does not read that budget.
    """

    from .mem import mem_available_gib, schedulable_gib

    root = anchor or Path.home()
    try:
        disk = shutil.disk_usage(root).free / (1024**3)
    except OSError:
        disk = -1.0
    available = mem_available_gib()
    return HostSnapshot(
        mem_available_gib=available,
        disk_free_gib=disk,
        gpus=tuple(_gpu_snapshots()),
        schedulable_gib=schedulable_gib(available),
    )


def _gpu_snapshots() -> list[GpuSnapshot]:
    try:
        raw = subprocess.check_output(
            [
                "nvidia-smi",
                "--query-gpu=index,memory.free,memory.total",
                "--format=csv,noheader,nounits",
            ],
            text=True,
            timeout=5,
            stderr=subprocess.DEVNULL,
        )
    except (OSError, subprocess.SubprocessError, ValueError):
        return []
    found: list[GpuSnapshot] = []
    for line in raw.splitlines():
        parts = [part.strip() for part in line.split(",")]
        if len(parts) != 3:
            continue
        try:
            found.append(GpuSnapshot(int(parts[0]), int(parts[1]), int(parts[2])))
        except ValueError:
            continue
    return found
