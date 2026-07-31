"""Latency histograms and resource sampling for load receipts (KGP-029)."""

from __future__ import annotations

import math
import os
import resource
import sys
import threading
import time
import tracemalloc
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

JSONDict = Dict[str, Any]

# Fixed latency histogram bucket edges in milliseconds.
DEFAULT_LATENCY_BUCKETS_MS: Tuple[float, ...] = (
    0.1,
    0.25,
    0.5,
    1.0,
    2.5,
    5.0,
    10.0,
    25.0,
    50.0,
    100.0,
    250.0,
    500.0,
    1000.0,
    2500.0,
    5000.0,
    10000.0,
)


@dataclass
class LatencyHistogram:
    """Streaming latency histogram with percentile helpers."""

    buckets_ms: Sequence[float] = field(
        default_factory=lambda: list(DEFAULT_LATENCY_BUCKETS_MS)
    )
    _samples_ms: List[float] = field(default_factory=list)
    _counts: List[int] = field(default_factory=list)
    _overflow: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def __post_init__(self) -> None:
        edges = sorted(float(b) for b in self.buckets_ms)
        if not edges:
            raise ValueError("buckets_ms must be non-empty")
        self.buckets_ms = edges
        self._counts = [0] * len(edges)

    def observe(self, latency_ms: float) -> None:
        if latency_ms < 0 or math.isnan(latency_ms) or math.isinf(latency_ms):
            return
        with self._lock:
            self._samples_ms.append(float(latency_ms))
            placed = False
            for i, edge in enumerate(self.buckets_ms):
                if latency_ms <= edge:
                    self._counts[i] += 1
                    placed = True
                    break
            if not placed:
                self._overflow += 1

    def extend(self, samples_ms: Iterable[float]) -> None:
        for s in samples_ms:
            self.observe(s)

    def merge(self, other: "LatencyHistogram") -> None:
        """Absorb all samples from *other* into this histogram."""
        with other._lock:
            samples = list(other._samples_ms)
        self.extend(samples)

    def samples(self) -> List[float]:
        """Return a copy of raw latency samples (milliseconds)."""
        with self._lock:
            return list(self._samples_ms)

    @property
    def count(self) -> int:
        with self._lock:
            return len(self._samples_ms)

    def percentile(self, p: float) -> float:
        """Nearest-rank percentile on recorded samples (milliseconds)."""
        if not 0.0 <= p <= 100.0:
            raise ValueError("percentile must be in [0, 100]")
        with self._lock:
            if not self._samples_ms:
                return 0.0
            ordered = sorted(self._samples_ms)
        if p == 0:
            return ordered[0]
        if p == 100:
            return ordered[-1]
        # Nearest-rank method.
        k = max(1, int(math.ceil((p / 100.0) * len(ordered))))
        return ordered[min(len(ordered), k) - 1]

    def summary(self) -> JSONDict:
        with self._lock:
            samples = list(self._samples_ms)
            counts = list(self._counts)
            overflow = self._overflow
            edges = list(self.buckets_ms)
        n = len(samples)
        if n == 0:
            return {
                "count": 0,
                "sum_ms": 0.0,
                "mean_ms": 0.0,
                "min_ms": 0.0,
                "max_ms": 0.0,
                "p50_ms": 0.0,
                "p95_ms": 0.0,
                "p99_ms": 0.0,
                "buckets_ms": edges,
                "bucket_counts": counts,
                "overflow": overflow,
            }
        total = sum(samples)
        ordered = sorted(samples)
        return {
            "count": n,
            "sum_ms": total,
            "mean_ms": total / n,
            "min_ms": ordered[0],
            "max_ms": ordered[-1],
            "p50_ms": self.percentile(50),
            "p95_ms": self.percentile(95),
            "p99_ms": self.percentile(99),
            "buckets_ms": edges,
            "bucket_counts": counts,
            "overflow": overflow,
        }

    def to_json_dict(self) -> JSONDict:
        return self.summary()


@dataclass(frozen=True, slots=True)
class ResourceSnapshot:
    """Point-in-time process resource sample."""

    timestamp: float
    cpu_user_s: float
    cpu_system_s: float
    rss_bytes: int
    max_rss_bytes: int
    heap_bytes: int
    open_fds: int
    threads: int

    def to_json_dict(self) -> JSONDict:
        return {
            "timestamp": self.timestamp,
            "cpu_user_s": self.cpu_user_s,
            "cpu_system_s": self.cpu_system_s,
            "rss_bytes": self.rss_bytes,
            "max_rss_bytes": self.max_rss_bytes,
            "heap_bytes": self.heap_bytes,
            "open_fds": self.open_fds,
            "threads": self.threads,
        }


def _count_open_fds() -> int:
    """Best-effort open file-descriptor count (Linux /proc, else -1)."""
    try:
        return len(os.listdir(f"/proc/{os.getpid()}/fd"))
    except OSError:
        try:
            soft, _hard = resource.getrlimit(resource.RLIMIT_NOFILE)
            # No portable FD count; return soft limit as unavailable sentinel 0
            # only when we truly cannot sample.
            _ = soft
            return -1
        except Exception:
            return -1


def _rss_bytes() -> int:
    try:
        # Linux: VmRSS in kB from /proc/self/status
        with open("/proc/self/status", "r", encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("VmRSS:"):
                    parts = line.split()
                    return int(parts[1]) * 1024
    except OSError:
        pass
    # Fallback: ru_maxrss is peak; on Linux it is kB, on macOS bytes.
    usage = resource.getrusage(resource.RUSAGE_SELF)
    rss = int(usage.ru_maxrss)
    if sys.platform == "darwin":
        return rss
    return rss * 1024


def _max_rss_bytes() -> int:
    usage = resource.getrusage(resource.RUSAGE_SELF)
    rss = int(usage.ru_maxrss)
    if sys.platform == "darwin":
        return rss
    return rss * 1024


def _heap_bytes() -> int:
    if tracemalloc.is_tracing():
        current, _peak = tracemalloc.get_traced_memory()
        return int(current)
    # Approximate with Python allocator stats when available.
    try:
        import gc

        return int(sum(sys.getsizeof(o) for o in gc.get_objects()[:0]))  # always 0
    except Exception:
        return 0


def sample_resources(*, enable_tracemalloc: bool = False) -> ResourceSnapshot:
    """Capture CPU, RSS, heap, and open-FD counters for the current process."""
    if enable_tracemalloc and not tracemalloc.is_tracing():
        tracemalloc.start()
    usage = resource.getrusage(resource.RUSAGE_SELF)
    heap = 0
    if tracemalloc.is_tracing():
        heap, _ = tracemalloc.get_traced_memory()
    return ResourceSnapshot(
        timestamp=time.time(),
        cpu_user_s=float(usage.ru_utime),
        cpu_system_s=float(usage.ru_stime),
        rss_bytes=_rss_bytes(),
        max_rss_bytes=_max_rss_bytes(),
        heap_bytes=int(heap),
        open_fds=_count_open_fds(),
        threads=threading.active_count(),
    )


@dataclass
class OperationCounters:
    """Queue / conflict / error / IPFS / cache counters for a run."""

    operations_total: int = 0
    operations_ok: int = 0
    operations_error: int = 0
    conflicts: int = 0
    queue_wait_ms_total: float = 0.0
    queue_depth_peak: int = 0
    cache_hits: int = 0
    cache_misses: int = 0
    cache_bytes: int = 0
    ipfs_bytes: int = 0
    ipfs_fetches: int = 0
    ipfs_puts: int = 0
    bytes_written: int = 0
    bytes_read: int = 0
    recovery_attempts: int = 0
    recovery_successes: int = 0
    recovery_ms_total: float = 0.0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def record_op(
        self,
        *,
        ok: bool,
        conflict: bool = False,
        queue_wait_ms: float = 0.0,
        queue_depth: int = 0,
    ) -> None:
        with self._lock:
            self.operations_total += 1
            if ok:
                self.operations_ok += 1
            else:
                self.operations_error += 1
            if conflict:
                self.conflicts += 1
            self.queue_wait_ms_total += float(queue_wait_ms)
            if queue_depth > self.queue_depth_peak:
                self.queue_depth_peak = queue_depth

    def record_storage(
        self,
        *,
        cache_hits: int = 0,
        cache_misses: int = 0,
        cache_bytes: int = 0,
        ipfs_bytes: int = 0,
        ipfs_fetches: int = 0,
        ipfs_puts: int = 0,
        bytes_written: int = 0,
        bytes_read: int = 0,
    ) -> None:
        with self._lock:
            self.cache_hits += cache_hits
            self.cache_misses += cache_misses
            self.cache_bytes += cache_bytes
            self.ipfs_bytes += ipfs_bytes
            self.ipfs_fetches += ipfs_fetches
            self.ipfs_puts += ipfs_puts
            self.bytes_written += bytes_written
            self.bytes_read += bytes_read

    def record_recovery(self, *, ok: bool, recovery_ms: float) -> None:
        with self._lock:
            self.recovery_attempts += 1
            if ok:
                self.recovery_successes += 1
            self.recovery_ms_total += float(recovery_ms)

    def to_json_dict(self) -> JSONDict:
        with self._lock:
            return {
                "operations_total": self.operations_total,
                "operations_ok": self.operations_ok,
                "operations_error": self.operations_error,
                "conflicts": self.conflicts,
                "queue_wait_ms_total": self.queue_wait_ms_total,
                "queue_depth_peak": self.queue_depth_peak,
                "cache_hits": self.cache_hits,
                "cache_misses": self.cache_misses,
                "cache_bytes": self.cache_bytes,
                "ipfs_bytes": self.ipfs_bytes,
                "ipfs_fetches": self.ipfs_fetches,
                "ipfs_puts": self.ipfs_puts,
                "bytes_written": self.bytes_written,
                "bytes_read": self.bytes_read,
                "recovery_attempts": self.recovery_attempts,
                "recovery_successes": self.recovery_successes,
                "recovery_ms_total": self.recovery_ms_total,
                "recovery_ms_mean": (
                    self.recovery_ms_total / self.recovery_attempts
                    if self.recovery_attempts
                    else 0.0
                ),
            }


def directory_byte_size(path: os.PathLike[str] | str) -> int:
    """Sum file sizes under *path* (0 if missing)."""
    root = os.fspath(path)
    total = 0
    if not os.path.isdir(root):
        if os.path.isfile(root):
            try:
                return os.path.getsize(root)
            except OSError:
                return 0
        return 0
    for dirpath, _dirnames, filenames in os.walk(root):
        for name in filenames:
            fp = os.path.join(dirpath, name)
            try:
                total += os.path.getsize(fp)
            except OSError:
                continue
    return total


def throughput(ops: int, elapsed_s: float) -> float:
    if elapsed_s <= 0:
        return 0.0
    return float(ops) / float(elapsed_s)
