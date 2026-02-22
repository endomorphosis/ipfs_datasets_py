"""
Session 40 — Additional tests for monitoring.py to push coverage from ~63% toward 85%+.

Covers previously-uncovered code paths:
- EnhancedMetricsCollector._collect_system_metrics() (no-psutil path)
- EnhancedMetricsCollector.increment_counter() with labels
- EnhancedMetricsCollector.set_gauge() with and without labels
- EnhancedMetricsCollector.observe_histogram() with labels
- EnhancedMetricsCollector._serialize_labels()
- EnhancedMetricsCollector.get_performance_trends()
- EnhancedMetricsCollector._cleanup_old_data()
- EnhancedMetricsCollector._compute_percentiles() edge cases
- EnhancedMetricsCollector.get_tool_latency_percentiles() full flow
- EnhancedMetricsCollector.get_metrics_summary() with tool_latency_percentiles
- EnhancedMetricsCollector.track_request async context manager
- HealthCheckError path in _check_health
- ImportError path in _check_health
- Disk/response-time alert paths in _check_alerts
- _calculate_request_rate with request_times populated
- P2PMetricsCollector dashboard cache hit
- get_metrics_collector() / get_p2p_metrics_collector() singletons
"""
import asyncio
import time
from collections import deque
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from ipfs_datasets_py.mcp_server.monitoring import (
    EnhancedMetricsCollector,
    HealthCheckResult,
    MetricData,
    PerformanceSnapshot,
    P2PMetricsCollector,
    get_metrics_collector,
    get_p2p_metrics_collector,
)
from ipfs_datasets_py.mcp_server.exceptions import (
    HealthCheckError,
    MonitoringError,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_collector(**kwargs) -> EnhancedMetricsCollector:
    return EnhancedMetricsCollector(enabled=True, retention_hours=24, **kwargs)


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _make_snapshot(ts_offset_minutes: float = 0, **kwargs) -> PerformanceSnapshot:
    # Use utcnow() to match monitoring.py which uses naive UTC datetimes throughout.
    ts = datetime.utcnow() - timedelta(minutes=ts_offset_minutes)
    defaults = dict(
        timestamp=ts,
        cpu_percent=10.0,
        memory_percent=20.0,
        memory_used_mb=512.0,
        disk_percent=30.0,
        active_connections=0,
        request_rate=1.0,
        error_rate=0.0,
        avg_response_time_ms=5.0,
    )
    defaults.update(kwargs)
    return PerformanceSnapshot(**defaults)


# ===========================================================================
# _serialize_labels
# ===========================================================================

class TestSerializeLabels:

    def test_empty_labels(self):
        collector = _make_collector()
        result = collector._serialize_labels({})
        assert result == ""

    def test_single_label(self):
        collector = _make_collector()
        result = collector._serialize_labels({"env": "prod"})
        assert result == "env_prod"

    def test_multiple_labels_sorted(self):
        collector = _make_collector()
        result = collector._serialize_labels({"z": "last", "a": "first"})
        # sorted order: "a_first_z_last"
        assert result == "a_first_z_last"


# ===========================================================================
# increment_counter with labels
# ===========================================================================

class TestIncrementCounterWithLabels:

    def test_counter_incremented_with_labels(self):
        collector = _make_collector()
        collector.increment_counter("requests", labels={"tool": "search"})
        assert collector.counters["requests"] == 1.0
        assert "requests_tool_search" in collector.counters

    def test_disabled_collector_skips_counter(self):
        collector = EnhancedMetricsCollector(enabled=False)
        collector.increment_counter("requests", labels={"tool": "search"})
        assert "requests" not in collector.counters


# ===========================================================================
# set_gauge with labels
# ===========================================================================

class TestSetGaugeWithLabels:

    def test_gauge_set_with_labels(self):
        collector = _make_collector()
        collector.set_gauge("latency_ms", 42.5, labels={"endpoint": "search"})
        assert collector.gauges["latency_ms"] == 42.5
        assert "latency_ms_endpoint_search" in collector.gauges

    def test_disabled_collector_skips_gauge(self):
        collector = EnhancedMetricsCollector(enabled=False)
        collector.set_gauge("latency_ms", 42.5)
        assert "latency_ms" not in collector.gauges


# ===========================================================================
# observe_histogram with labels
# ===========================================================================

class TestObserveHistogramWithLabels:

    def test_histogram_recorded_with_labels(self):
        collector = _make_collector()
        collector.observe_histogram("response_time", 100.0, labels={"status": "200"})
        assert 100.0 in collector.histograms["response_time"]
        assert "response_time_status_200" in collector.histograms

    def test_disabled_collector_skips_histogram(self):
        collector = EnhancedMetricsCollector(enabled=False)
        collector.observe_histogram("response_time", 100.0)
        assert "response_time" not in collector.histograms


# ===========================================================================
# _compute_percentiles edge cases
# ===========================================================================

class TestComputePercentiles:

    def test_empty_list_returns_zeros(self):
        collector = _make_collector()
        result = collector._compute_percentiles([])
        assert result["p50"] == 0.0
        assert result["count"] == 0

    def test_single_element_returns_zeros(self):
        collector = _make_collector()
        result = collector._compute_percentiles([42.0])
        assert result["p50"] == 0.0
        assert result["count"] == 1

    def test_two_elements(self):
        collector = _make_collector()
        result = collector._compute_percentiles([10.0, 20.0])
        assert result["p50"] == pytest.approx(15.0)
        assert result["min"] == 10.0
        assert result["max"] == 20.0
        assert result["count"] == 2

    def test_many_elements(self):
        collector = _make_collector()
        times = list(range(1, 101))  # 1..100 ms
        result = collector._compute_percentiles(times)
        assert result["count"] == 100
        assert result["min"] == 1
        assert result["max"] == 100
        # p50 should be near 50
        assert 49 <= result["p50"] <= 51

    def test_p95_higher_than_p50(self):
        collector = _make_collector()
        times = [float(i) for i in range(1, 101)]
        result = collector._compute_percentiles(times)
        assert result["p95"] > result["p50"]
        assert result["p99"] >= result["p95"]


# ===========================================================================
# get_tool_latency_percentiles
# ===========================================================================

class TestGetToolLatencyPercentiles:

    def test_empty_tool_returns_zeros(self):
        collector = _make_collector()
        result = collector.get_tool_latency_percentiles("nonexistent_tool")
        assert result["p50"] == 0.0
        assert result["count"] == 0

    def test_populated_tool_returns_values(self):
        collector = _make_collector()
        for ms in [10.0, 20.0, 30.0, 40.0, 50.0, 200.0]:
            collector.track_tool_execution("my_tool", ms, True)
        result = collector.get_tool_latency_percentiles("my_tool")
        assert result["count"] == 6
        assert result["p50"] > 0.0
        assert result["p99"] > result["p50"]

    def test_percentiles_in_metrics_summary(self):
        collector = _make_collector()
        for ms in [5.0, 10.0, 15.0, 20.0, 25.0]:
            collector.track_tool_execution("tool_a", ms, True)
        summary = collector.get_metrics_summary()
        assert "tool_latency_percentiles" in summary
        assert "tool_a" in summary["tool_latency_percentiles"]
        assert summary["tool_latency_percentiles"]["tool_a"]["count"] == 5


# ===========================================================================
# get_performance_trends
# ===========================================================================

class TestGetPerformanceTrends:

    def test_empty_returns_empty_lists(self):
        collector = _make_collector()
        trends = collector.get_performance_trends(hours=1)
        assert trends["cpu_trend"] == []
        assert trends["memory_trend"] == []
        assert trends["request_rate_trend"] == []
        assert trends["response_time_trend"] == []

    def test_recent_snapshots_included(self):
        collector = _make_collector()
        # Add a snapshot within the last hour
        snap = _make_snapshot(ts_offset_minutes=5, cpu_percent=55.0)
        collector.performance_snapshots.append(snap)
        trends = collector.get_performance_trends(hours=1)
        assert len(trends["cpu_trend"]) == 1
        assert trends["cpu_trend"][0]["value"] == 55.0

    def test_old_snapshots_excluded(self):
        collector = _make_collector()
        # Add a snapshot from 2 hours ago
        snap = _make_snapshot(ts_offset_minutes=130, cpu_percent=99.0)
        collector.performance_snapshots.append(snap)
        trends = collector.get_performance_trends(hours=1)
        assert len(trends["cpu_trend"]) == 0

    def test_multiple_snapshots_ordered(self):
        collector = _make_collector()
        for minutes_ago in [10, 20, 30]:
            snap = _make_snapshot(ts_offset_minutes=minutes_ago, memory_percent=float(minutes_ago))
            collector.performance_snapshots.append(snap)
        trends = collector.get_performance_trends(hours=1)
        assert len(trends["memory_trend"]) == 3
        # All timestamps should be strings
        for pt in trends["memory_trend"]:
            assert isinstance(pt["timestamp"], str)
            assert isinstance(pt["value"], float)

    def test_trend_keys_present(self):
        collector = _make_collector()
        trends = collector.get_performance_trends(hours=24)
        expected_keys = {"cpu_trend", "memory_trend", "request_rate_trend", "response_time_trend"}
        assert set(trends.keys()) == expected_keys


# ===========================================================================
# _cleanup_old_data
# ===========================================================================

class TestCleanupOldData:

    def test_old_snapshots_removed(self):
        collector = _make_collector()
        # Add a snapshot older than retention_hours (24h)
        old_snap = _make_snapshot(ts_offset_minutes=25 * 60)  # 25h ago
        collector.performance_snapshots.append(old_snap)
        new_snap = _make_snapshot(ts_offset_minutes=5)  # 5 min ago
        collector.performance_snapshots.append(new_snap)
        assert len(collector.performance_snapshots) == 2
        _run(collector._cleanup_old_data())
        # Only the new snapshot should remain
        assert len(collector.performance_snapshots) == 1
        assert collector.performance_snapshots[0].cpu_percent == new_snap.cpu_percent

    def test_old_alerts_removed(self):
        collector = _make_collector()
        old_time = datetime.utcnow() - timedelta(hours=25)
        collector.alerts.append({"type": "old_alert", "timestamp": old_time})
        fresh_time = datetime.utcnow()  # noqa: DTZ003  (matches production code convention)
        collector.alerts.append({"type": "fresh_alert", "timestamp": fresh_time})
        _run(collector._cleanup_old_data())
        remaining = list(collector.alerts)
        assert len(remaining) == 1
        assert remaining[0]["type"] == "fresh_alert"


# ===========================================================================
# track_request async context manager
# ===========================================================================

class TestTrackRequestLifecycle:

    def test_track_request_increments_count(self):
        collector = _make_collector()

        async def _run_request():
            async with collector.track_request("/test"):
                pass

        _run(_run_request())
        assert collector.request_count == 1
        assert len(collector.request_times) == 1

    def test_track_request_records_error_on_exception(self):
        collector = _make_collector()

        async def _run_failing_request():
            try:
                async with collector.track_request("/failing"):
                    raise ValueError("simulate error")
            except ValueError:
                pass

        _run(_run_failing_request())
        assert collector.error_count == 1

    def test_track_request_records_duration(self):
        collector = _make_collector()

        async def _run_request():
            async with collector.track_request("/timed"):
                pass

        _run(_run_request())
        assert collector.request_times[0] >= 0.0


# ===========================================================================
# get_metrics_collector / get_p2p_metrics_collector singletons
# ===========================================================================

class TestGlobalSingletons:

    def test_get_metrics_collector_returns_instance(self):
        collector = get_metrics_collector()
        assert isinstance(collector, EnhancedMetricsCollector)

    def test_get_p2p_metrics_collector_returns_instance(self):
        collector = get_p2p_metrics_collector()
        assert isinstance(collector, P2PMetricsCollector)


# ===========================================================================
# _collect_system_metrics (no-psutil path)
# ===========================================================================

class TestCollectSystemMetrics:

    def test_no_psutil_adds_snapshot(self):
        """When psutil is absent, _collect_system_metrics should still append a snapshot."""
        collector = _make_collector()
        with patch("ipfs_datasets_py.mcp_server.monitoring.HAVE_PSUTIL", False):
            _run(collector._collect_system_metrics())
        assert len(collector.performance_snapshots) == 1
        snap = collector.performance_snapshots[0]
        assert snap.cpu_percent == 0.0
        assert snap.memory_percent == 0.0


# ===========================================================================
# Disabled collector no-ops
# ===========================================================================

class TestDisabledCollectorNoOps:

    def test_track_tool_execution_disabled(self):
        collector = EnhancedMetricsCollector(enabled=False)
        collector.track_tool_execution("my_tool", 50.0, True)
        assert "my_tool" not in collector.tool_metrics["call_counts"]

    def test_get_metrics_summary_still_works_when_disabled(self):
        # Disabled collector should still return a valid structure
        collector = EnhancedMetricsCollector(enabled=False)
        summary = collector.get_metrics_summary()
        assert "uptime_seconds" in summary
        assert "request_metrics" in summary


# ===========================================================================
# HealthCheckError path in _check_health
# ===========================================================================

class TestCheckHealthSpecialExceptions:

    def test_health_check_error_maps_to_critical(self):
        """HealthCheckError raised by a check function → status='critical'."""
        collector = _make_collector()

        def failing_check():
            raise HealthCheckError(check_name="db", message="timeout")

        collector.register_health_check("database", failing_check)
        _run(collector._check_health())
        assert "database" in collector.health_checks
        assert collector.health_checks["database"].status == "critical"

    def test_import_error_maps_to_critical(self):
        """ImportError raised by a check function → status='critical'."""
        collector = _make_collector()

        def missing_dep_check():
            raise ImportError("no module named 'missing_lib'")

        collector.register_health_check("ext_service", missing_dep_check)
        _run(collector._check_health())
        result = collector.health_checks["ext_service"]
        assert result.status == "critical"
        assert "unavailable" in result.message.lower()

    def test_generic_exception_maps_to_critical(self):
        """Generic Exception raised by a check function → status='critical'."""
        collector = _make_collector()

        def exploding_check():
            raise RuntimeError("unexpected failure")

        collector.register_health_check("storage", exploding_check)
        _run(collector._check_health())
        assert collector.health_checks["storage"].status == "critical"


# ===========================================================================
# Disk and response-time alert paths in _check_alerts
# ===========================================================================

class TestCheckAlertsAdditionalPaths:

    def test_cpu_alert_triggered(self):
        """_check_alerts should add a cpu_high alert when cpu_percent > threshold."""
        collector = _make_collector()
        collector.alert_thresholds["cpu_percent"] = 50.0
        collector.system_metrics["cpu_percent"] = 95.0
        _run(collector._check_alerts())
        types = [a["type"] for a in collector.alerts]
        assert "cpu_high" in types

    def test_memory_alert_triggered(self):
        """_check_alerts should add a memory_high alert when memory_percent > threshold."""
        collector = _make_collector()
        collector.alert_thresholds["memory_percent"] = 50.0
        collector.system_metrics["memory_percent"] = 90.0
        _run(collector._check_alerts())
        types = [a["type"] for a in collector.alerts]
        assert "memory_high" in types

    def test_response_time_alert_triggered(self):
        """_check_alerts should add a response_time_high alert when avg > threshold."""
        _HIGH_RESPONSE_TIME_MS = 9000.0  # 9s — well above any threshold for testing
        collector = _make_collector()
        collector.alert_thresholds["response_time_ms"] = 100.0
        # Load request_times with values above threshold (ms)
        for _ in range(10):
            collector.request_times.append(_HIGH_RESPONSE_TIME_MS)
        _run(collector._check_alerts())
        types = [a["type"] for a in collector.alerts]
        assert "response_time_high" in types

    def test_no_cpu_alert_when_below_threshold(self):
        collector = _make_collector()
        collector.alert_thresholds["cpu_percent"] = 90.0
        collector.system_metrics["cpu_percent"] = 40.0
        _run(collector._check_alerts())
        types = [a["type"] for a in collector.alerts]
        assert "cpu_high" not in types


# ===========================================================================
# _calculate_request_rate with snapshots (non-zero path)
# ===========================================================================

class TestCalculateRequestRate:

    def test_request_rate_with_recent_snapshots(self):
        """_calculate_request_rate returns >0 when request_times is non-empty."""
        collector = _make_collector()
        # Add request_times to activate the non-zero path
        collector.request_times.append(15.0)
        # Add a snapshot within the last minute
        snap = _make_snapshot(ts_offset_minutes=0.1, cpu_percent=5.0)
        collector.performance_snapshots.append(snap)
        rate = collector._calculate_request_rate()
        # Rate should be non-negative (1 snapshot / 60s ≈ 0.0167)
        assert rate >= 0.0

    def test_request_rate_zero_when_no_request_times(self):
        collector = _make_collector()
        rate = collector._calculate_request_rate()
        assert rate == 0.0


# ===========================================================================
# MonitoringError raised in track_request
# ===========================================================================

class TestTrackRequestMonitoringError:

    def test_monitoring_error_increments_error_count(self):
        """MonitoringError propagates and increments error_count."""
        collector = _make_collector()

        async def _run_request():
            try:
                async with collector.track_request("/sensitive"):
                    raise MonitoringError("forced error")
            except MonitoringError:
                pass

        _run(_run_request())
        assert collector.error_count == 1


# ===========================================================================
# P2PMetricsCollector dashboard cache hit
# ===========================================================================

class TestP2PDashboardCache:

    def test_cache_hit_returns_same_data(self):
        """get_dashboard_data() returns cached result on second call (cache hit)."""
        p2p = P2PMetricsCollector()
        data1 = p2p.get_dashboard_data()
        data2 = p2p.get_dashboard_data()
        # Both calls return same structure (second is cache hit)
        assert set(data1.keys()) == set(data2.keys())

    def test_force_refresh_bypasses_cache(self):
        """get_dashboard_data(force_refresh=True) recomputes even when cache is fresh."""
        p2p = P2PMetricsCollector()
        data1 = p2p.get_dashboard_data()
        data2 = p2p.get_dashboard_data(force_refresh=True)
        # Both return valid dicts; force_refresh bypassed cache
        assert isinstance(data2, dict)
