"""Fail-closed resource guards for long-running knowledge-graph benchmarks.

The large synthetic profile is intentionally difficult to run accidentally:
callers must opt in explicitly, pass a host-capacity preflight, and remain
inside runtime RSS / available-memory / disk-space ceilings.
"""

from __future__ import annotations

import os
import shutil
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

try:  # pragma: no cover - psutil is present in supported benchmark envs
    import psutil
except ImportError:  # pragma: no cover
    psutil = None  # type: ignore[assignment]


TRUE_VALUES = frozenset({"1", "true", "yes", "on"})
GIB = 1024**3


class BenchmarkSafetyError(RuntimeError):
    """Raised before a benchmark can exhaust an unapproved host resource."""


def env_enabled(name: str, environ: Mapping[str, str] | None = None) -> bool:
    env = os.environ if environ is None else environ
    return str(env.get(name, "")).strip().lower() in TRUE_VALUES


def _gib_setting(
    name: str,
    default: float,
    *,
    environ: Mapping[str, str] | None = None,
) -> int:
    env = os.environ if environ is None else environ
    raw = str(env.get(name, "")).strip()
    try:
        value = float(raw) if raw else float(default)
    except ValueError as exc:
        raise BenchmarkSafetyError(f"{name} must be a number of GiB") from exc
    if value <= 0:
        raise BenchmarkSafetyError(f"{name} must be greater than zero")
    return int(value * GIB)


@dataclass(frozen=True, slots=True)
class ResourceSnapshot:
    available_memory_bytes: int
    process_rss_bytes: int
    free_disk_bytes: int


def snapshot_resources(path: Path | str) -> ResourceSnapshot:
    """Capture the resources relevant to bounded benchmark execution."""
    target = Path(path)
    target.mkdir(parents=True, exist_ok=True)
    disk = shutil.disk_usage(target)
    if psutil is not None:
        memory = psutil.virtual_memory()
        available = int(memory.available)
        rss = int(psutil.Process().memory_info().rss)
    else:  # Fail closed if portable memory accounting is unavailable.
        raise BenchmarkSafetyError(
            "psutil is required for long-profile memory safety checks"
        )
    return ResourceSnapshot(
        available_memory_bytes=available,
        process_rss_bytes=rss,
        free_disk_bytes=int(disk.free),
    )


@dataclass(frozen=True, slots=True)
class ResourceLimits:
    min_available_start_bytes: int
    min_available_runtime_bytes: int
    min_free_disk_bytes: int
    max_process_rss_bytes: int

    @classmethod
    def for_synthetic_large(
        cls, *, environ: Mapping[str, str] | None = None
    ) -> ResourceLimits:
        return cls(
            min_available_start_bytes=_gib_setting(
                "KG_LOAD_MIN_AVAILABLE_GIB", 64, environ=environ
            ),
            min_available_runtime_bytes=_gib_setting(
                "KG_LOAD_ABORT_AVAILABLE_GIB", 8, environ=environ
            ),
            min_free_disk_bytes=_gib_setting(
                "KG_LOAD_MIN_FREE_DISK_GIB", 100, environ=environ
            ),
            max_process_rss_bytes=_gib_setting(
                "KG_LOAD_MAX_RSS_GIB", 48, environ=environ
            ),
        )

    @classmethod
    def for_day_soak(
        cls, *, environ: Mapping[str, str] | None = None
    ) -> ResourceLimits:
        return cls(
            min_available_start_bytes=_gib_setting(
                "KG_SOAK_MIN_AVAILABLE_GIB", 16, environ=environ
            ),
            min_available_runtime_bytes=_gib_setting(
                "KG_SOAK_ABORT_AVAILABLE_GIB", 4, environ=environ
            ),
            min_free_disk_bytes=_gib_setting(
                "KG_SOAK_MIN_FREE_DISK_GIB", 20, environ=environ
            ),
            max_process_rss_bytes=_gib_setting(
                "KG_SOAK_MAX_RSS_GIB", 8, environ=environ
            ),
        )


class ResourceGuard:
    """Preflight and periodically enforce a set of resource limits."""

    def __init__(
        self,
        path: Path | str,
        limits: ResourceLimits,
        *,
        label: str,
    ) -> None:
        self.path = Path(path)
        self.limits = limits
        self.label = label

    def preflight(self) -> ResourceSnapshot:
        snap = snapshot_resources(self.path)
        failures = []
        if snap.available_memory_bytes < self.limits.min_available_start_bytes:
            failures.append(
                "available memory "
                f"{snap.available_memory_bytes / GIB:.1f} GiB < required "
                f"{self.limits.min_available_start_bytes / GIB:.1f} GiB"
            )
        if snap.free_disk_bytes < self.limits.min_free_disk_bytes:
            failures.append(
                f"free disk {snap.free_disk_bytes / GIB:.1f} GiB < required "
                f"{self.limits.min_free_disk_bytes / GIB:.1f} GiB"
            )
        if failures:
            raise BenchmarkSafetyError(
                f"{self.label} resource preflight failed: " + "; ".join(failures)
            )
        self.check()
        return snap

    def check(self) -> ResourceSnapshot:
        snap = snapshot_resources(self.path)
        failures = []
        if snap.process_rss_bytes > self.limits.max_process_rss_bytes:
            failures.append(
                f"process RSS {snap.process_rss_bytes / GIB:.1f} GiB > ceiling "
                f"{self.limits.max_process_rss_bytes / GIB:.1f} GiB"
            )
        if snap.available_memory_bytes < self.limits.min_available_runtime_bytes:
            failures.append(
                "available memory "
                f"{snap.available_memory_bytes / GIB:.1f} GiB < abort floor "
                f"{self.limits.min_available_runtime_bytes / GIB:.1f} GiB"
            )
        if snap.free_disk_bytes < self.limits.min_free_disk_bytes:
            failures.append(
                f"free disk {snap.free_disk_bytes / GIB:.1f} GiB < floor "
                f"{self.limits.min_free_disk_bytes / GIB:.1f} GiB"
            )
        if failures:
            raise BenchmarkSafetyError(
                f"{self.label} runtime resource ceiling reached: "
                + "; ".join(failures)
            )
        return snap


def synthetic_large_guard(
    work_dir: Path | str,
    *,
    environ: Mapping[str, str] | None = None,
) -> ResourceGuard:
    """Require explicit approval and return a preflighted large-load guard."""
    if not env_enabled("KG_LOAD_SYNTHETIC_LARGE", environ):
        raise BenchmarkSafetyError(
            "synthetic_large requires explicit opt-in: "
            "set KG_LOAD_SYNTHETIC_LARGE=1"
        )
    guard = ResourceGuard(
        work_dir,
        ResourceLimits.for_synthetic_large(environ=environ),
        label="synthetic_large",
    )
    guard.preflight()
    return guard


def day_soak_guard(
    work_dir: Path | str,
    *,
    environ: Mapping[str, str] | None = None,
) -> ResourceGuard:
    """Require explicit approval and return a preflighted 24-hour guard."""
    if not env_enabled("KG_SOAK_24H", environ):
        raise BenchmarkSafetyError(
            "day/24h soak requires explicit opt-in: set KG_SOAK_24H=1"
        )
    guard = ResourceGuard(
        work_dir,
        ResourceLimits.for_day_soak(environ=environ),
        label="day/24h soak",
    )
    guard.preflight()
    return guard
