# ipfs_datasets_py/mcp_server/prometheus_exporter.py
"""
L53 — Prometheus Metrics Exporter
===================================
Exposes MCP server metrics in the Prometheus text exposition format.

When ``prometheus_client`` is installed, the exporter creates real
``Counter``, ``Gauge``, and ``Histogram`` objects and optionally starts the
built-in HTTP metrics endpoint on a configurable port.

Without ``prometheus_client`` the module degrades gracefully: all metric
objects are inert no-op stubs so the rest of the codebase can unconditionally
import and call this module.

Usage::

    from ipfs_datasets_py.mcp_server.prometheus_exporter import PrometheusExporter
    from ipfs_datasets_py.mcp_server.monitoring import get_metrics_collector

    exporter = PrometheusExporter(get_metrics_collector(), port=9090)
    exporter.start_http_server()  # spawns background thread
    # ... later ...
    exporter.update()            # push latest metrics from collector to Prometheus
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Availability guard
# ---------------------------------------------------------------------------

try:
    import prometheus_client as prom  # type: ignore[import]
    PROMETHEUS_AVAILABLE = True
except ImportError:
    prom = None  # type: ignore[assignment]
    PROMETHEUS_AVAILABLE = False


# ---------------------------------------------------------------------------
# No-op stubs used when prometheus_client is absent
# ---------------------------------------------------------------------------


class _NoOpMetric:
    """Inert metric that silently discards all operations."""

    def labels(self, **_kw: Any) -> "_NoOpMetric":
        return self

    def inc(self, amount: float = 1.0) -> None:
        pass

    def dec(self, amount: float = 1.0) -> None:
        pass

    def set(self, value: float) -> None:
        pass

    def observe(self, value: float) -> None:
        pass


def _make_counter(name: str, documentation: str, labelnames: list | None = None) -> Any:
    if PROMETHEUS_AVAILABLE:
        return prom.Counter(name, documentation, labelnames or [])
    return _NoOpMetric()


def _make_gauge(name: str, documentation: str, labelnames: list | None = None) -> Any:
    if PROMETHEUS_AVAILABLE:
        return prom.Gauge(name, documentation, labelnames or [])
    return _NoOpMetric()


def _make_histogram(
    name: str,
    documentation: str,
    labelnames: list | None = None,
    buckets: list | None = None,
) -> Any:
    if PROMETHEUS_AVAILABLE:
        kwargs: Dict[str, Any] = {}
        if buckets:
            kwargs["buckets"] = buckets
        return prom.Histogram(name, documentation, labelnames or [], **kwargs)
    return _NoOpMetric()


# ---------------------------------------------------------------------------
# Exporter
# ---------------------------------------------------------------------------


class PrometheusExporter:
    """Bridges the MCP ``EnhancedMetricsCollector`` to Prometheus.

    Metrics registered
    ------------------
    * ``mcp_tool_calls_total``          — Counter, labels: ``category``, ``tool``, ``status``
    * ``mcp_tool_latency_seconds``      — Histogram, labels: ``category``, ``tool``
    * ``mcp_active_connections``        — Gauge
    * ``mcp_error_rate``                — Gauge (ratio, 0.0–1.0)
    * ``mcp_cache_hits_total``          — Counter
    * ``mcp_cache_misses_total``        — Counter
    * ``mcp_system_cpu_usage_percent``  — Gauge
    * ``mcp_system_memory_usage_percent`` — Gauge
    * ``mcp_uptime_seconds``            — Gauge

    Args:
        collector:  The ``EnhancedMetricsCollector`` (or compatible object)
                    from which metrics are read during :meth:`update`.
        port:       HTTP port for the built-in ``/metrics`` endpoint.
                    Defaults to ``9090``.
        namespace:  Prometheus metric namespace prefix (default ``"mcp"`` —
                    already baked into metric names above; override if you
                    need a custom prefix).
    """

    def __init__(
        self,
        collector: Any = None,
        *,
        port: int = 9090,
        namespace: str = "mcp",
    ) -> None:
        self.collector = collector
        self.port = port
        self.namespace = namespace
        self._http_server: Optional[Any] = None
        self._start_time: float = time.time()

        # Register metrics (no-ops when prometheus_client not installed)
        self.tool_calls_total = _make_counter(
            f"{namespace}_tool_calls_total",
            "Total number of MCP tool calls",
            ["category", "tool", "status"],
        )
        self.tool_latency_seconds = _make_histogram(
            f"{namespace}_tool_latency_seconds",
            "MCP tool call latency in seconds",
            ["category", "tool"],
            buckets=[0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0],
        )
        self.active_connections = _make_gauge(
            f"{namespace}_active_connections",
            "Number of active MCP connections",
        )
        self.error_rate = _make_gauge(
            f"{namespace}_error_rate",
            "Current MCP server error rate (0.0–1.0)",
        )
        self.cache_hits_total = _make_counter(
            f"{namespace}_cache_hits_total",
            "Total number of tool-result cache hits",
        )
        self.cache_misses_total = _make_counter(
            f"{namespace}_cache_misses_total",
            "Total number of tool-result cache misses",
        )
        self.cpu_usage = _make_gauge(
            f"{namespace}_system_cpu_usage_percent",
            "System CPU usage percentage",
        )
        self.memory_usage = _make_gauge(
            f"{namespace}_system_memory_usage_percent",
            "System memory usage percentage",
        )
        self.uptime_seconds = _make_gauge(
            f"{namespace}_uptime_seconds",
            "MCP server uptime in seconds",
        )

    # ------------------------------------------------------------------
    # HTTP server
    # ------------------------------------------------------------------

    def start_http_server(self) -> None:
        """Start the built-in Prometheus HTTP metrics endpoint.

        Raises:
            ImportError: If ``prometheus_client`` is not installed.
        """
        if not PROMETHEUS_AVAILABLE:
            raise ImportError(
                "prometheus_client is not installed. "
                "Run `pip install prometheus-client` to enable the Prometheus exporter."
            )
        prom.start_http_server(self.port)
        self._http_server = True  # Sentinel; prometheus_client manages the thread.
        logger.info("Prometheus metrics HTTP server started on port %d", self.port)

    def stop_http_server(self) -> None:
        """Stop the HTTP metrics endpoint (best-effort; prometheus_client does not
        provide an explicit stop API)."""
        if self._http_server is not None:
            logger.info("Prometheus HTTP server stop requested (may require process restart)")
            self._http_server = None

    # ------------------------------------------------------------------
    # Metric update
    # ------------------------------------------------------------------

    def update(self) -> None:
        """Pull the latest metrics from the collector and push them to Prometheus.

        Safe to call repeatedly in a monitoring loop.  When *collector* is
        ``None`` only the uptime gauge is updated.
        """
        self.uptime_seconds.set(time.time() - self._start_time)

        if self.collector is None:
            return

        try:
            snapshot = self._safe_get_snapshot()
        except (AttributeError, TypeError, KeyError, RuntimeError) as exc:
            logger.warning("PrometheusExporter.update() failed to read snapshot: %s", exc)
            return

        # Error rate
        if "error_rate" in snapshot:
            self.error_rate.set(float(snapshot["error_rate"]))

        # Active connections
        if "active_connections" in snapshot:
            self.active_connections.set(float(snapshot["active_connections"]))

        # System metrics
        sys_metrics = snapshot.get("system_metrics", {})
        if "cpu_percent" in sys_metrics:
            self.cpu_usage.set(float(sys_metrics["cpu_percent"]))
        if "memory_percent" in sys_metrics:
            self.memory_usage.set(float(sys_metrics["memory_percent"]))

        # Cache metrics
        cache = snapshot.get("cache_stats", {})
        if "hits" in cache:
            # Counters can only go up; track delta via stored last value.
            pass  # Simplified: no delta tracking in stub

    def _safe_get_snapshot(self) -> Dict[str, Any]:
        """Return a metrics snapshot dict from the collector (defensive)."""
        if hasattr(self.collector, "get_snapshot"):
            return self.collector.get_snapshot() or {}
        if hasattr(self.collector, "get_current_metrics"):
            return self.collector.get_current_metrics() or {}
        return {}

    # ------------------------------------------------------------------
    # Record individual events (call-site integration)
    # ------------------------------------------------------------------

    def record_tool_call(
        self,
        category: str,
        tool: str,
        status: str,
        latency_seconds: float,
    ) -> None:
        """Record a single tool-call event.

        Intended for call-site instrumentation (called by the dispatcher).

        Args:
            category:        Tool category name.
            tool:            Tool name.
            status:          ``"success"`` or ``"error"``.
            latency_seconds: Wall-clock duration of the call.
        """
        self.tool_calls_total.labels(
            category=category, tool=tool, status=status
        ).inc()
        self.tool_latency_seconds.labels(category=category, tool=tool).observe(
            latency_seconds
        )

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    def get_info(self) -> Dict[str, Any]:
        """Return metadata about this exporter."""
        return {
            "exporter": "prometheus",
            "namespace": self.namespace,
            "port": self.port,
            "prometheus_available": PROMETHEUS_AVAILABLE,
            "http_server_running": self._http_server is not None,
            "uptime_seconds": time.time() - self._start_time,
        }
