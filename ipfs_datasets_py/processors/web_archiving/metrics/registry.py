"""Rolling metrics registry for web archiving provider operations.

This module tracks provider-level metrics that feed throughput-aware orchestration
and fallback policy decisions.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Deque, Dict, List, Optional, Tuple


DEFAULT_WINDOWS_SECONDS: Tuple[int, ...] = (300, 900, 3600)


@dataclass(frozen=True)
class ProviderEvent:
    """Single provider operation event captured by the registry."""

    timestamp: float
    provider: str
    operation: str
    success: bool
    latency_ms: float
    items_processed: int
    quality_score: Optional[float] = None
    error_type: Optional[str] = None


class MetricsRegistry:
    """Thread-safe rolling metrics registry for provider operations.

    The registry stores timestamped events and computes rolling snapshots for
    standard windows (5m/15m/60m) or a caller-provided window.
    """

    def __init__(self, default_windows_seconds: Tuple[int, ...] = DEFAULT_WINDOWS_SECONDS):
        self._lock = threading.RLock()
        self._events: Dict[Tuple[str, str], Deque[ProviderEvent]] = defaultdict(deque)
        self._windows = tuple(sorted(set(int(w) for w in default_windows_seconds if int(w) > 0)))
        if not self._windows:
            raise ValueError("default_windows_seconds must contain positive values")

    def record_event(
        self,
        provider: str,
        operation: str,
        success: bool,
        latency_ms: float,
        items_processed: int = 1,
        quality_score: Optional[float] = None,
        error_type: Optional[str] = None,
        timestamp: Optional[float] = None,
    ) -> None:
        """Record a provider operation event.

        Args:
            provider: Provider identifier.
            operation: Operation name such as search/fetch/archive.
            success: True if operation succeeded.
            latency_ms: End-to-end operation latency.
            items_processed: Count of result items/documents from this event.
            quality_score: Optional quality score in [0.0, 1.0].
            error_type: Optional error classifier when success is False.
            timestamp: Optional epoch seconds for deterministic testing.
        """
        if not provider:
            raise ValueError("provider must be non-empty")
        if not operation:
            raise ValueError("operation must be non-empty")
        if latency_ms < 0:
            raise ValueError("latency_ms must be >= 0")
        if items_processed < 0:
            raise ValueError("items_processed must be >= 0")
        if quality_score is not None and not 0.0 <= quality_score <= 1.0:
            raise ValueError("quality_score must be in [0.0, 1.0]")

        ts = float(timestamp if timestamp is not None else time.time())
        event = ProviderEvent(
            timestamp=ts,
            provider=provider,
            operation=operation,
            success=bool(success),
            latency_ms=float(latency_ms),
            items_processed=int(items_processed),
            quality_score=quality_score,
            error_type=error_type,
        )

        key = (provider, operation)
        with self._lock:
            queue = self._events[key]
            queue.append(event)
            self._prune_locked(queue, now_ts=ts)

    def snapshot(
        self,
        provider: str,
        operation: str,
        window_seconds: int,
        now_ts: Optional[float] = None,
    ) -> Dict[str, float]:
        """Return rolling metrics snapshot for one provider+operation+window."""
        if window_seconds <= 0:
            raise ValueError("window_seconds must be > 0")
        now = float(now_ts if now_ts is not None else time.time())
        key = (provider, operation)

        with self._lock:
            queue = self._events.get(key)
            if not queue:
                return self._empty_snapshot(provider, operation, window_seconds)

            self._prune_locked(queue, now_ts=now)
            events = [e for e in queue if e.timestamp >= now - window_seconds]

        return self._build_snapshot(provider, operation, window_seconds, events)

    def snapshots_for_all_windows(
        self,
        provider: str,
        operation: str,
        now_ts: Optional[float] = None,
    ) -> Dict[str, Dict[str, float]]:
        """Return snapshots for each configured rolling window."""
        out: Dict[str, Dict[str, float]] = {}
        for window in self._windows:
            label = f"{window}s"
            out[label] = self.snapshot(provider, operation, window_seconds=window, now_ts=now_ts)
        return out

    def provider_operation_keys(self) -> List[Tuple[str, str]]:
        """List all provider+operation keys currently tracked."""
        with self._lock:
            return list(self._events.keys())

    def reset(self) -> None:
        """Clear all recorded metrics."""
        with self._lock:
            self._events.clear()

    def _prune_locked(self, queue: Deque[ProviderEvent], now_ts: float) -> None:
        """Prune old events outside the largest tracked window.

        Caller must hold self._lock.
        """
        max_window = self._windows[-1]
        min_ts = now_ts - max_window
        while queue and queue[0].timestamp < min_ts:
            queue.popleft()

    @staticmethod
    def _empty_snapshot(provider: str, operation: str, window_seconds: int) -> Dict[str, float]:
        return {
            "provider": provider,
            "operation": operation,
            "window_seconds": float(window_seconds),
            "total_requests": 0.0,
            "successes": 0.0,
            "failures": 0.0,
            "success_rate": 0.0,
            "avg_latency_ms": 0.0,
            "p95_latency_ms": 0.0,
            "items_processed": 0.0,
            "throughput_items_per_sec": 0.0,
            "avg_quality_score": 0.0,
        }

    @staticmethod
    def _build_snapshot(
        provider: str,
        operation: str,
        window_seconds: int,
        events: List[ProviderEvent],
    ) -> Dict[str, float]:
        if not events:
            return MetricsRegistry._empty_snapshot(provider, operation, window_seconds)

        total = float(len(events))
        successes = float(sum(1 for e in events if e.success))
        failures = total - successes
        latencies = sorted(e.latency_ms for e in events)
        p95_index = max(0, int(round(0.95 * (len(latencies) - 1))))
        items = float(sum(e.items_processed for e in events))
        quality_values = [e.quality_score for e in events if e.quality_score is not None]

        return {
            "provider": provider,
            "operation": operation,
            "window_seconds": float(window_seconds),
            "total_requests": total,
            "successes": successes,
            "failures": failures,
            "success_rate": successes / total if total else 0.0,
            "avg_latency_ms": sum(latencies) / total,
            "p95_latency_ms": latencies[p95_index],
            "items_processed": items,
            "throughput_items_per_sec": items / float(window_seconds),
            "avg_quality_score": (
                sum(quality_values) / float(len(quality_values)) if quality_values else 0.0
            ),
        }


__all__ = [
    "DEFAULT_WINDOWS_SECONDS",
    "ProviderEvent",
    "MetricsRegistry",
]
