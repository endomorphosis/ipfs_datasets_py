"""Prometheus-compatible metrics for MCP++ servers.

Provides lightweight counters and histograms for observability. Uses
prometheus_client if available, otherwise provides a standalone /metrics
endpoint with Prometheus text format output.

Metrics exported:
- mcppp_requests_total{method, status} — Total JSON-RPC/HTTP requests
- mcppp_request_duration_seconds{method} — Request latency histogram
- mcppp_dag_events_total — Total events in EventDAG (hot + compacted)
- mcppp_dag_compaction_epochs_total — Number of compacted epochs
- mcppp_p2p_peers_connected — Currently connected P2P peers
- mcppp_p2p_messages_total{direction} — P2P messages sent/received
- mcppp_ucan_delegations_total — Registered UCAN delegations
- mcppp_ucan_revocations_total — Revoked delegations
- mcppp_rate_limit_rejected_total — Requests rejected by rate limiter

Module: ipfs_accelerate_py.mcplusplus_module.metrics
"""

from __future__ import annotations

import logging
import threading
import time
from collections import defaultdict
from typing import Any, Dict, List, Optional

logger = logging.getLogger("ipfs_datasets.mcp_server.metrics")


class Counter:
    """Thread-safe counter metric."""

    def __init__(self, name: str, help_text: str, labels: Optional[List[str]] = None):
        self.name = name
        self.help_text = help_text
        self.labels = labels or []
        self._values: Dict[tuple, float] = defaultdict(float)
        self._lock = threading.Lock()

    def inc(self, amount: float = 1.0, **label_values) -> None:
        key = tuple(label_values.get(l, "") for l in self.labels)
        with self._lock:
            self._values[key] += amount

    def get(self, **label_values) -> float:
        key = tuple(label_values.get(l, "") for l in self.labels)
        return self._values.get(key, 0.0)

    def collect(self) -> List[str]:
        """Return Prometheus text format lines."""
        lines = [
            f"# HELP {self.name} {self.help_text}",
            f"# TYPE {self.name} counter",
        ]
        with self._lock:
            for key, value in self._values.items():
                if self.labels:
                    label_str = ",".join(f'{l}="{v}"' for l, v in zip(self.labels, key))
                    lines.append(f"{self.name}{{{label_str}}} {value}")
                else:
                    lines.append(f"{self.name} {value}")
        return lines


class Gauge:
    """Thread-safe gauge metric."""

    def __init__(self, name: str, help_text: str, labels: Optional[List[str]] = None):
        self.name = name
        self.help_text = help_text
        self.labels = labels or []
        self._values: Dict[tuple, float] = defaultdict(float)
        self._lock = threading.Lock()

    def set(self, value: float, **label_values) -> None:
        key = tuple(label_values.get(l, "") for l in self.labels)
        with self._lock:
            self._values[key] = value

    def inc(self, amount: float = 1.0, **label_values) -> None:
        key = tuple(label_values.get(l, "") for l in self.labels)
        with self._lock:
            self._values[key] += amount

    def dec(self, amount: float = 1.0, **label_values) -> None:
        key = tuple(label_values.get(l, "") for l in self.labels)
        with self._lock:
            self._values[key] -= amount

    def get(self, **label_values) -> float:
        key = tuple(label_values.get(l, "") for l in self.labels)
        return self._values.get(key, 0.0)

    def collect(self) -> List[str]:
        lines = [
            f"# HELP {self.name} {self.help_text}",
            f"# TYPE {self.name} gauge",
        ]
        with self._lock:
            for key, value in self._values.items():
                if self.labels:
                    label_str = ",".join(f'{l}="{v}"' for l, v in zip(self.labels, key))
                    lines.append(f"{self.name}{{{label_str}}} {value}")
                else:
                    lines.append(f"{self.name} {value}")
        return lines


class Histogram:
    """Thread-safe histogram metric with pre-defined buckets."""

    DEFAULT_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)

    def __init__(self, name: str, help_text: str, labels: Optional[List[str]] = None,
                 buckets: Optional[tuple] = None):
        self.name = name
        self.help_text = help_text
        self.labels = labels or []
        self.buckets = buckets or self.DEFAULT_BUCKETS
        self._counts: Dict[tuple, Dict[float, int]] = defaultdict(
            lambda: {b: 0 for b in self.buckets}
        )
        self._sums: Dict[tuple, float] = defaultdict(float)
        self._totals: Dict[tuple, int] = defaultdict(int)
        self._lock = threading.Lock()

    def observe(self, value: float, **label_values) -> None:
        key = tuple(label_values.get(l, "") for l in self.labels)
        with self._lock:
            self._sums[key] += value
            self._totals[key] += 1
            for bucket in self.buckets:
                if value <= bucket:
                    self._counts[key][bucket] += 1

    def collect(self) -> List[str]:
        lines = [
            f"# HELP {self.name} {self.help_text}",
            f"# TYPE {self.name} histogram",
        ]
        with self._lock:
            for key in self._totals:
                label_str = ""
                if self.labels:
                    label_str = ",".join(f'{l}="{v}"' for l, v in zip(self.labels, key))

                cumulative = 0
                for bucket in self.buckets:
                    cumulative += self._counts[key].get(bucket, 0)
                    le_label = f'le="{bucket}"'
                    full_label = f"{label_str},{le_label}" if label_str else le_label
                    lines.append(f"{self.name}_bucket{{{full_label}}} {cumulative}")

                inf_label = f"{label_str},le=\"+Inf\"" if label_str else 'le="+Inf"'
                lines.append(f"{self.name}_bucket{{{inf_label}}} {self._totals[key]}")

                sum_label = f"{{{label_str}}}" if label_str else ""
                lines.append(f"{self.name}_sum{sum_label} {self._sums[key]}")
                lines.append(f"{self.name}_count{sum_label} {self._totals[key]}")
        return lines


# ---------------------------------------------------------------------------
# Global Metrics Registry
# ---------------------------------------------------------------------------

class MetricsRegistry:
    """Singleton registry for all MCP++ metrics."""

    def __init__(self):
        # Request metrics
        self.requests_total = Counter(
            "mcppp_requests_total",
            "Total MCP++ requests processed",
            labels=["method", "status"],
        )
        self.request_duration = Histogram(
            "mcppp_request_duration_seconds",
            "Request processing duration in seconds",
            labels=["method"],
        )

        # DAG metrics
        self.dag_events_total = Gauge(
            "mcppp_dag_events_total",
            "Total events in EventDAG (hot + compacted)",
        )
        self.dag_hot_events = Gauge(
            "mcppp_dag_hot_events",
            "Events currently in hot tier (memory)",
        )
        self.dag_compaction_epochs = Gauge(
            "mcppp_dag_compaction_epochs_total",
            "Number of compacted epochs on disk",
        )

        # P2P metrics
        self.p2p_peers_connected = Gauge(
            "mcppp_p2p_peers_connected",
            "Currently connected P2P peers",
        )
        self.p2p_messages_total = Counter(
            "mcppp_p2p_messages_total",
            "P2P messages sent and received",
            labels=["direction"],
        )

        # UCAN metrics
        self.ucan_delegations_total = Gauge(
            "mcppp_ucan_delegations_total",
            "Registered UCAN delegations",
        )
        self.ucan_revocations_total = Gauge(
            "mcppp_ucan_revocations_total",
            "Revoked UCAN delegations",
        )

        # Rate limiter metrics
        self.rate_limit_rejected = Counter(
            "mcppp_rate_limit_rejected_total",
            "Requests rejected by rate limiter",
        )

        # Uptime
        self._start_time = time.time()
        self.uptime_seconds = Gauge(
            "mcppp_uptime_seconds",
            "Server uptime in seconds",
        )

    def collect_all(self) -> str:
        """Collect all metrics in Prometheus text exposition format."""
        self.uptime_seconds.set(time.time() - self._start_time)

        lines = []
        for attr in dir(self):
            obj = getattr(self, attr)
            if isinstance(obj, (Counter, Gauge, Histogram)):
                lines.extend(obj.collect())
                lines.append("")

        return "\n".join(lines) + "\n"


# Singleton
_METRICS: Optional[MetricsRegistry] = None
_METRICS_LOCK = threading.Lock()


def get_metrics() -> MetricsRegistry:
    """Get the global metrics registry (thread-safe singleton)."""
    global _METRICS
    if _METRICS is None:
        with _METRICS_LOCK:
            if _METRICS is None:
                _METRICS = MetricsRegistry()
    return _METRICS
