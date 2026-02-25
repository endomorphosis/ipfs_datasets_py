"""
Prometheus metrics export for circuit breaker and structured logging.

This module provides Prometheus-format metric collection and export for the MCP++
observability infrastructure. It tracks circuit breaker state transitions, call latencies,
failure rates, and logging performance.

Example:
    >>> from ipfs_datasets_py.logic.observability.metrics_prometheus import (
    ...     PrometheusMetricsCollector
    ... )
    >>> collector = PrometheusMetricsCollector()
    >>> collector.record_circuit_breaker_call("payment_api", 0.025, success=True)
    >>> collector.record_circuit_breaker_state("payment_api", "open", timestamp=1708949100.0)
    >>> metrics_text = collector.export_prometheus_format()
    >>> print(metrics_text)
"""

import time
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum
from statistics import median, quantiles
from threading import RLock
from typing import Dict, List, Optional, Set, Tuple


class CircuitBreakerState(str, Enum):
    """Valid circuit breaker states for metrics."""
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass
class CallMetrics:
    """Aggregated metrics for a single circuit breaker or component."""
    total_calls: int = 0
    successful_calls: int = 0
    failed_calls: int = 0
    latencies: List[float] = field(default_factory=list)
    state_transitions: List[Tuple[float, str]] = field(default_factory=list)  # (timestamp, state)
    last_failure_time: Optional[float] = None
    current_state: str = "closed"


class PrometheusMetricsCollector:
    """Collects and exports circuit breaker and logging metrics in Prometheus format."""

    def __init__(self, max_latency_samples: int = 1000):
        """
        Initialize the Prometheus metrics collector.

        Args:
            max_latency_samples: Maximum number of latency samples to keep per component.
                                Older samples are discarded if exceeded.
        """
        self._lock = RLock()
        self._metrics: Dict[str, CallMetrics] = defaultdict(CallMetrics)
        self._log_metrics: Dict[str, Dict[str, int]] = defaultdict(lambda: {
            "total_entries": 0,
            "error_entries": 0,
            "warning_entries": 0,
            "info_entries": 0,
            "debug_entries": 0,
        })
        self._max_latency_samples = max_latency_samples

    def record_circuit_breaker_call(
        self,
        component: str,
        latency: float,
        success: bool,
        timestamp: Optional[float] = None
    ) -> None:
        """
        Record a single circuit breaker call.

        Args:
            component: Name of the circuit breaker component (e.g., "payment_api").
            latency: Call latency in seconds.
            success: Whether the call succeeded.
            timestamp: Optional timestamp (defaults to current time).
        """
        with self._lock:
            metrics = self._metrics[component]
            metrics.total_calls += 1
            if success:
                metrics.successful_calls += 1
            else:
                metrics.failed_calls += 1
                metrics.last_failure_time = timestamp or time.time()

            # Keep only the most recent max_latency_samples
            if len(metrics.latencies) >= self._max_latency_samples:
                metrics.latencies.pop(0)
            metrics.latencies.append(latency)

    def record_circuit_breaker_state(
        self,
        component: str,
        state: str,
        timestamp: Optional[float] = None
    ) -> None:
        """
        Record a circuit breaker state transition.

        Args:
            component: Name of the circuit breaker component.
            state: New state ("closed", "open", or "half_open").
            timestamp: Optional timestamp (defaults to current time).
        """
        with self._lock:
            ts = timestamp or time.time()
            metrics = self._metrics[component]
            metrics.current_state = state
            metrics.state_transitions.append((ts, state))

            # Keep only the most recent 100 transitions
            if len(metrics.state_transitions) > 100:
                metrics.state_transitions.pop(0)

    def record_log_entry(
        self,
        component: str,
        level: str = "info"
    ) -> None:
        """
        Record a structured log entry.

        Args:
            component: Name of the component logging the entry.
            level: Log level ("debug", "info", "warning", "error").
        """
        with self._lock:
            metrics = self._log_metrics[component]
            metrics["total_entries"] += 1
            level_key = f"{level.lower()}_entries"
            if level_key in metrics:
                metrics[level_key] += 1

    def get_latency_percentiles(
        self,
        component: str,
        percentiles: Optional[List[int]] = None
    ) -> Dict[str, float]:
        """
        Get latency percentiles for a component.

        Args:
            component: Name of the component.
            percentiles: List of percentiles (0-100). Defaults to [50, 95, 99].

        Returns:
            Dictionary mapping percentile names (e.g., "p50", "p95") to latency values.
        """
        if percentiles is None:
            percentiles = [50, 95, 99]

        with self._lock:
            metrics = self._metrics[component]
            if not metrics.latencies:
                return {f"p{p}": 0.0 for p in percentiles}

            # Sort and compute quantiles
            sorted_latencies = sorted(metrics.latencies)
            if len(sorted_latencies) == 1:
                return {f"p{p}": sorted_latencies[0] for p in percentiles}

            # Use quantiles function for multiple percentiles
            try:
                quantile_values = quantiles(sorted_latencies, n=100)
                result = {}
                for p in percentiles:
                    idx = min(p - 1, len(quantile_values) - 1) if p <= 100 else len(quantile_values) - 1
                    result[f"p{p}"] = quantile_values[idx] if idx >= 0 else sorted_latencies[0]
                return result
            except (StatisticsError, ValueError):
                # Fallback for very small samples
                return {f"p{p}": median(sorted_latencies) for p in percentiles}

    def get_failure_rate(self, component: str) -> float:
        """
        Get the failure rate for a component.

        Args:
            component: Name of the component.

        Returns:
            Failure rate as a percentage (0-100).
        """
        with self._lock:
            metrics = self._metrics[component]
            if metrics.total_calls == 0:
                return 0.0
            return (metrics.failed_calls / metrics.total_calls) * 100.0

    def get_success_rate(self, component: str) -> float:
        """
        Get the success rate for a component.

        Args:
            component: Name of the component.

        Returns:
            Success rate as a percentage (0-100).
        """
        return 100.0 - self.get_failure_rate(component)

    def get_metrics_summary(self, component: str) -> Dict:
        """
        Get a summary of all metrics for a component.

        Args:
            component: Name of the component.

        Returns:
            Dictionary with all available metrics.
        """
        with self._lock:
            metrics = self._metrics[component]
            avg_latency = (
                sum(metrics.latencies) / len(metrics.latencies)
                if metrics.latencies else 0.0
            )
            return {
                "component": component,
                "total_calls": metrics.total_calls,
                "successful_calls": metrics.successful_calls,
                "failed_calls": metrics.failed_calls,
                "success_rate": self.get_success_rate(component),
                "failure_rate": self.get_failure_rate(component),
                "avg_latency": avg_latency,
                "min_latency": min(metrics.latencies) if metrics.latencies else 0.0,
                "max_latency": max(metrics.latencies) if metrics.latencies else 0.0,
                "current_state": metrics.current_state,
                "last_failure_time": metrics.last_failure_time,
                "latency_percentiles": self.get_latency_percentiles(component),
            }

    def export_prometheus_format(self) -> str:
        """
        Export all metrics in Prometheus text format.

        Returns:
            Metrics in Prometheus exposition format.
        """
        lines = []
        lines.append("# HELP circuit_breaker_calls_total Total calls to circuit breaker")
        lines.append("# TYPE circuit_breaker_calls_total counter")

        with self._lock:
            for component, metrics in self._metrics.items():
                lines.append(
                    f'circuit_breaker_calls_total{{component="{component}"}} {metrics.total_calls}'
                )

            lines.append("")
            lines.append("# HELP circuit_breaker_calls_success Successful calls to circuit breaker")
            lines.append("# TYPE circuit_breaker_calls_success counter")
            for component, metrics in self._metrics.items():
                lines.append(
                    f'circuit_breaker_calls_success{{component="{component}"}} {metrics.successful_calls}'
                )

            lines.append("")
            lines.append("# HELP circuit_breaker_calls_failed Failed calls to circuit breaker")
            lines.append("# TYPE circuit_breaker_calls_failed counter")
            for component, metrics in self._metrics.items():
                lines.append(
                    f'circuit_breaker_calls_failed{{component="{component}"}} {metrics.failed_calls}'
                )

            lines.append("")
            lines.append("# HELP circuit_breaker_failure_rate Failure rate percentage")
            lines.append("# TYPE circuit_breaker_failure_rate gauge")
            for component in self._metrics.keys():
                rate = self.get_failure_rate(component)
                lines.append(f'circuit_breaker_failure_rate{{component="{component}"}} {rate:.2f}')

            lines.append("")
            lines.append("# HELP circuit_breaker_latency_seconds Call latency in seconds")
            lines.append("# TYPE circuit_breaker_latency_seconds histogram")
            for component, metrics in self._metrics.items():
                if metrics.latencies:
                    avg = sum(metrics.latencies) / len(metrics.latencies)
                    lines.append(
                        f'circuit_breaker_latency_seconds_sum{{component="{component}"}} {sum(metrics.latencies):.4f}'
                    )
                    lines.append(
                        f'circuit_breaker_latency_seconds_count{{component="{component}"}} {len(metrics.latencies)}'
                    )
                    lines.append(
                        f'circuit_breaker_latency_seconds_avg{{component="{component}"}} {avg:.4f}'
                    )

            lines.append("")
            lines.append("# HELP circuit_breaker_state Current circuit breaker state")
            lines.append("# TYPE circuit_breaker_state gauge")
            state_map = {CircuitBreakerState.CLOSED.value: 0, "open": 1, "half_open": 2}
            for component, metrics in self._metrics.items():
                state_num = state_map.get(metrics.current_state, 0)
                lines.append(
                    f'circuit_breaker_state{{component="{component}",state="{metrics.current_state}"}} {state_num}'
                )

            lines.append("")
            lines.append("# HELP log_entries_total Total log entries recorded")
            lines.append("# TYPE log_entries_total counter")
            for component, metrics in self._log_metrics.items():
                lines.append(
                    f'log_entries_total{{component="{component}"}} {metrics["total_entries"]}'
                )

            lines.append("")
            lines.append("# HELP log_entries_by_level Log entries by level")
            lines.append("# TYPE log_entries_by_level counter")
            for component, metrics in self._log_metrics.items():
                for level in ["debug", "info", "warning", "error"]:
                    key = f"{level}_entries"
                    count = metrics.get(key, 0)
                    lines.append(
                        f'log_entries_by_level{{component="{component}",level="{level}"}} {count}'
                    )

        return "\n".join(lines)

    def get_components(self) -> Set[str]:
        """Get all registered component names."""
        with self._lock:
            return set(self._metrics.keys())

    def reset_component(self, component: str) -> None:
        """Reset all metrics for a component."""
        with self._lock:
            if component in self._metrics:
                del self._metrics[component]
            if component in self._log_metrics:
                del self._log_metrics[component]

    def reset_all(self) -> None:
        """Reset all metrics."""
        with self._lock:
            self._metrics.clear()
            self._log_metrics.clear()


# Global singleton instance
_default_collector: Optional[PrometheusMetricsCollector] = None


def get_prometheus_collector() -> PrometheusMetricsCollector:
    """
    Get or create the default Prometheus metrics collector singleton.

    Returns:
        Global PrometheusMetricsCollector instance.
    """
    global _default_collector
    if _default_collector is None:
        _default_collector = PrometheusMetricsCollector()
    return _default_collector


# StatisticsError import
try:
    from statistics import StatisticsError
except ImportError:
    class StatisticsError(ValueError):
        """Fallback for statistics errors."""
        pass
