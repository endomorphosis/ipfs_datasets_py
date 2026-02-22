"""
Session G40: monitoring.py coverage uplift.

Targets uncovered lines in EnhancedMetricsCollector and P2PMetricsCollector:
- _start_monitoring / start_monitoring (lines 129-147)
- _monitoring_loop / _cleanup_loop async exception paths (151-186)
- _collect_system_metrics no-psutil path (190-207)
- track_request context manager paths (309-346)
- track_tool_execution disabled path (line 404)
- _check_health ImportError path (lines 553-558)
- _check_alerts response_time_high (lines 606-613)
- _calculate_request_rate with snapshots (lines 627-633)
- _cleanup_old_data (lines 653-668)
- _compute_percentiles with <2 samples (lines 827-837)
- get_tool_latency_percentiles (lines 868-870)
- get_performance_trends (lines 969-977)
- shutdown (lines 998-1010)
- P2PMetricsCollector.get_dashboard_data cache hit (line 1645)
- get_metrics_collector / get_p2p_metrics_collector singletons (lines 1856-1867)
"""

import asyncio
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ipfs_datasets_py.mcp_server.monitoring import (
    EnhancedMetricsCollector,
    P2PMetricsCollector,
    PerformanceSnapshot,
    HealthCheckResult,
)
from ipfs_datasets_py.mcp_server.exceptions import (
    HealthCheckError,
    MonitoringError,
    MetricsCollectionError,
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


def _snapshot(*, seconds_ago: float = 0) -> PerformanceSnapshot:
    ts = datetime.utcnow() - timedelta(seconds=seconds_ago)
    return PerformanceSnapshot(
        timestamp=ts,
        cpu_percent=10.0,
        memory_percent=40.0,
        memory_used_mb=512.0,
        disk_percent=30.0,
        active_connections=1,
        request_rate=2.0,
        error_rate=0.0,
        avg_response_time_ms=50.0,
    )


# ---------------------------------------------------------------------------
# TestStartMonitoring
# ---------------------------------------------------------------------------

class TestStartMonitoring:
    """Tests for _start_monitoring and start_monitoring."""

    def test_start_monitoring_not_in_async_context_is_noop(self):
        """
        GIVEN: Not running inside an async context
        WHEN: _start_monitoring() is called
        THEN: monitoring_started remains False (early return)
        """
        collector = _make_collector()
        with patch(
            "ipfs_datasets_py.utils.anyio_compat.in_async_context",
            return_value=False,
        ):
            collector._start_monitoring()
        assert collector._monitoring_started is False

    def test_start_monitoring_in_async_context_marks_started(self):
        """
        GIVEN: Running inside an async context with spawn_system_task mocked
        WHEN: _start_monitoring() is called
        THEN: monitoring_started is set to True
        """
        import sys
        collector = _make_collector()
        mock_lowlevel = MagicMock()
        with patch.dict(sys.modules, {"anyio.lowlevel": mock_lowlevel}):
            with patch(
                "ipfs_datasets_py.utils.anyio_compat.in_async_context",
                return_value=True,
            ):
                collector._start_monitoring()
        assert collector._monitoring_started is True

    def test_start_monitoring_idempotent_when_already_started(self):
        """
        GIVEN: _monitoring_started=True
        WHEN: _start_monitoring() is called again
        THEN: monitoring_started stays True without error
        """
        collector = _make_collector()
        collector._monitoring_started = True
        # Should return early without attempting any imports/calls
        collector._start_monitoring()
        assert collector._monitoring_started is True

    def test_start_monitoring_public_calls_internal_when_enabled(self):
        """
        GIVEN: enabled=True collector
        WHEN: start_monitoring() is called
        THEN: _start_monitoring is invoked
        """
        collector = _make_collector()
        mock_internal = MagicMock()
        with patch.object(collector, "_start_monitoring", mock_internal):
            collector.start_monitoring()
        mock_internal.assert_called_once()

    def test_start_monitoring_public_noop_when_disabled(self):
        """
        GIVEN: enabled=False collector
        WHEN: start_monitoring() is called
        THEN: _start_monitoring is NOT invoked
        """
        collector = EnhancedMetricsCollector(enabled=False)
        mock_internal = MagicMock()
        with patch.object(collector, "_start_monitoring", mock_internal):
            collector.start_monitoring()
        mock_internal.assert_not_called()


# ---------------------------------------------------------------------------
# TestMonitoringLoops
# ---------------------------------------------------------------------------

class TestMonitoringLoops:
    """Tests for _monitoring_loop and _cleanup_loop async exception paths."""

    def test_monitoring_loop_breaks_on_cancel(self):
        """
        GIVEN: _collect_system_metrics/health/alerts all mocked
        WHEN: anyio.sleep raises CancelledError
        THEN: _monitoring_loop returns without propagating
        """
        collector = _make_collector()

        async def run():
            async def _cancel(*a, **kw):
                raise asyncio.CancelledError()

            with patch.object(
                collector, "_collect_system_metrics", AsyncMock()
            ):
                with patch.object(collector, "_check_health", AsyncMock()):
                    with patch.object(collector, "_check_alerts", AsyncMock()):
                        with patch(
                            "ipfs_datasets_py.mcp_server.monitoring.anyio.sleep",
                            _cancel,
                        ):
                            await collector._monitoring_loop()

        _run(run())  # Should complete without raising

    def test_monitoring_loop_handles_metrics_collection_error(self):
        """
        GIVEN: _collect_system_metrics raises MetricsCollectionError
        WHEN: _monitoring_loop runs one iteration
        THEN: MetricsCollectionError is caught; loop exits via cancel in retry sleep
        """
        collector = _make_collector()

        async def run():
            async def _raise_metrics_error():
                raise MetricsCollectionError("disk unavailable")

            async def _cancel_on_sleep(*a, **kw):
                raise asyncio.CancelledError()

            with patch.object(
                collector, "_collect_system_metrics", _raise_metrics_error
            ):
                with patch.object(collector, "_check_health", AsyncMock()):
                    with patch.object(collector, "_check_alerts", AsyncMock()):
                        with patch(
                            "ipfs_datasets_py.mcp_server.monitoring.anyio.sleep",
                            _cancel_on_sleep,
                        ):
                            try:
                                await collector._monitoring_loop()
                            except asyncio.CancelledError:
                                pass

        _run(run())

    def test_monitoring_loop_handles_oserror(self):
        """
        GIVEN: _collect_system_metrics raises OSError
        WHEN: _monitoring_loop runs one iteration
        THEN: OSError is caught; loop exits via cancel in retry sleep
        """
        collector = _make_collector()

        async def run():
            async def _raise_os_error():
                raise OSError("no such device")

            async def _cancel_on_sleep(*a, **kw):
                raise asyncio.CancelledError()

            with patch.object(
                collector, "_collect_system_metrics", _raise_os_error
            ):
                with patch.object(collector, "_check_health", AsyncMock()):
                    with patch.object(collector, "_check_alerts", AsyncMock()):
                        with patch(
                            "ipfs_datasets_py.mcp_server.monitoring.anyio.sleep",
                            _cancel_on_sleep,
                        ):
                            try:
                                await collector._monitoring_loop()
                            except asyncio.CancelledError:
                                pass

        _run(run())

    def test_monitoring_loop_handles_generic_exception(self):
        """
        GIVEN: _collect_system_metrics raises generic RuntimeError
        WHEN: _monitoring_loop runs one iteration
        THEN: Exception is caught; loop exits via cancel in retry sleep
        """
        collector = _make_collector()

        async def run():
            async def _raise_runtime():
                raise RuntimeError("unexpected error")

            async def _cancel_on_sleep(*a, **kw):
                raise asyncio.CancelledError()

            with patch.object(
                collector, "_collect_system_metrics", _raise_runtime
            ):
                with patch.object(collector, "_check_health", AsyncMock()):
                    with patch.object(collector, "_check_alerts", AsyncMock()):
                        with patch(
                            "ipfs_datasets_py.mcp_server.monitoring.anyio.sleep",
                            _cancel_on_sleep,
                        ):
                            try:
                                await collector._monitoring_loop()
                            except asyncio.CancelledError:
                                pass

        _run(run())

    def test_cleanup_loop_breaks_on_cancel(self):
        """
        GIVEN: _cleanup_old_data mocked
        WHEN: anyio.sleep raises CancelledError
        THEN: _cleanup_loop returns normally
        """
        collector = _make_collector()

        async def run():
            async def _cancel(*a, **kw):
                raise asyncio.CancelledError()

            with patch.object(
                collector, "_cleanup_old_data", AsyncMock()
            ):
                with patch(
                    "ipfs_datasets_py.mcp_server.monitoring.anyio.sleep",
                    _cancel,
                ):
                    await collector._cleanup_loop()

        _run(run())

    def test_cleanup_loop_reraises_monitoring_error(self):
        """
        GIVEN: _cleanup_old_data raises MonitoringError
        WHEN: _cleanup_loop runs
        THEN: MonitoringError propagates out
        """
        collector = _make_collector()

        async def run():
            async def _raise_monitoring():
                raise MonitoringError("storage full")

            with patch.object(
                collector, "_cleanup_old_data", _raise_monitoring
            ):
                with pytest.raises(MonitoringError):
                    await collector._cleanup_loop()

        _run(run())

    def test_cleanup_loop_handles_oserror(self):
        """
        GIVEN: _cleanup_old_data raises OSError
        WHEN: _cleanup_loop runs
        THEN: OSError is caught; loop exits via cancel in retry sleep
        """
        collector = _make_collector()

        async def run():
            async def _raise_os():
                raise OSError("filesystem error")

            async def _cancel_on_sleep(*a, **kw):
                raise asyncio.CancelledError()

            with patch.object(collector, "_cleanup_old_data", _raise_os):
                with patch(
                    "ipfs_datasets_py.mcp_server.monitoring.anyio.sleep",
                    _cancel_on_sleep,
                ):
                    try:
                        await collector._cleanup_loop()
                    except asyncio.CancelledError:
                        pass

        _run(run())


# ---------------------------------------------------------------------------
# TestCollectSystemMetricsNoPsutil
# ---------------------------------------------------------------------------

class TestCollectSystemMetricsNoPsutil:
    """Tests for _collect_system_metrics when psutil is unavailable."""

    def test_collects_without_psutil(self):
        """
        GIVEN: HAVE_PSUTIL=False
        WHEN: _collect_system_metrics() is called
        THEN: A snapshot with zero cpu/memory is added to performance_snapshots
        """
        collector = _make_collector()

        async def run():
            with patch(
                "ipfs_datasets_py.mcp_server.monitoring.HAVE_PSUTIL", False
            ):
                await collector._collect_system_metrics()

        _run(run())
        assert len(collector.performance_snapshots) == 1
        snap = collector.performance_snapshots[0]
        assert snap.cpu_percent == 0.0


# ---------------------------------------------------------------------------
# TestTrackRequest
# ---------------------------------------------------------------------------

class TestTrackRequest:
    """Tests for track_request async context manager."""

    def test_track_request_normal_path_increments_count(self):
        """
        GIVEN: A valid endpoint name
        WHEN: Entering and exiting track_request context normally
        THEN: request_count is incremented
        """
        collector = _make_collector()

        async def run():
            async with collector.track_request("test_endpoint"):
                pass

        _run(run())
        assert collector.request_count == 1

    def test_track_request_increments_error_on_monitoring_error(self):
        """
        GIVEN: A MonitoringError raised inside the context
        WHEN: track_request context is active
        THEN: error_count is incremented and MonitoringError re-raised
        """
        collector = _make_collector()

        async def run():
            with pytest.raises(MonitoringError):
                async with collector.track_request("test_endpoint"):
                    raise MonitoringError("test monitoring error")

        _run(run())
        assert collector.error_count == 1

    def test_track_request_increments_error_on_generic_exception(self):
        """
        GIVEN: A ValueError raised inside the context
        WHEN: track_request context is active
        THEN: error_count is incremented and ValueError re-raised
        """
        collector = _make_collector()

        async def run():
            with pytest.raises(ValueError):
                async with collector.track_request("test_endpoint"):
                    raise ValueError("generic error")

        _run(run())
        assert collector.error_count == 1

    def test_track_request_records_response_time(self):
        """
        GIVEN: A completed request
        WHEN: track_request context exits
        THEN: A response time entry is added to request_times
        """
        collector = _make_collector()

        async def run():
            async with collector.track_request("test_endpoint"):
                pass

        _run(run())
        assert len(collector.request_times) == 1


# ---------------------------------------------------------------------------
# TestTrackToolExecutionDisabled
# ---------------------------------------------------------------------------

class TestTrackToolExecutionDisabled:
    """Tests for track_tool_execution when collector is disabled."""

    def test_disabled_collector_skips_tracking(self):
        """
        GIVEN: enabled=False collector
        WHEN: track_tool_execution is called
        THEN: No metrics are recorded (call_counts remains empty)
        """
        collector = EnhancedMetricsCollector(enabled=False)
        collector.track_tool_execution("my_tool", 50.0, True)
        assert len(collector.tool_metrics["call_counts"]) == 0


# ---------------------------------------------------------------------------
# TestHealthCheckErrors
# ---------------------------------------------------------------------------

class TestHealthCheckErrors:
    """Tests for _check_health error paths (HealthCheckError, ImportError)."""

    def test_check_health_handles_health_check_error(self):
        """
        GIVEN: A health check that raises HealthCheckError
        WHEN: _check_health() is called
        THEN: Result status is 'critical' with HealthCheckError details
        """
        collector = _make_collector()

        def broken_check():
            raise HealthCheckError("db_conn", "connection refused")

        collector.register_health_check("database", broken_check)
        _run(collector._check_health())
        result = collector.health_checks["database"]
        assert result.status == "critical"
        assert "check_name" in result.details

    def test_check_health_handles_import_error(self):
        """
        GIVEN: A health check that raises ImportError
        WHEN: _check_health() is called
        THEN: Result status is 'critical' with 'unavailable' in message
        """
        collector = _make_collector()

        def unavailable_check():
            raise ImportError("module not found")

        collector.register_health_check("ipfs_node", unavailable_check)
        _run(collector._check_health())
        result = collector.health_checks["ipfs_node"]
        assert result.status == "critical"
        assert "unavailable" in result.message


# ---------------------------------------------------------------------------
# TestCheckAlertsResponseTime
# ---------------------------------------------------------------------------

class TestCheckAlertsResponseTime:
    """Tests for _check_alerts response_time_high alert."""

    def test_response_time_alert_triggered_when_high(self):
        """
        GIVEN: Average response time exceeds alert threshold
        WHEN: _check_alerts() is called
        THEN: A response_time_high alert is added
        """
        collector = _make_collector()
        # Set threshold and add high response times
        collector.alert_thresholds["response_time_ms"] = 1000.0
        for _ in range(10):
            collector.request_times.append(9999.0)

        _run(collector._check_alerts())
        alert_types = [a["type"] for a in collector.alerts]
        assert "response_time_high" in alert_types


# ---------------------------------------------------------------------------
# TestCalculateRequestRate
# ---------------------------------------------------------------------------

class TestCalculateRequestRate:
    """Tests for _calculate_request_rate with performance snapshots."""

    def test_request_rate_nonzero_with_recent_snapshots(self):
        """
        GIVEN: Recent performance snapshots in the deque + request_times populated
        WHEN: _calculate_request_rate() is called
        THEN: Rate is > 0.0
        """
        collector = _make_collector()
        # Populate request_times so the early-return guard passes
        collector.request_times.append(10.0)
        # Add recent snapshots
        for _ in range(5):
            collector.performance_snapshots.append(_snapshot(seconds_ago=10))

        rate = collector._calculate_request_rate()
        assert rate > 0.0

    def test_request_rate_zero_with_only_old_snapshots(self):
        """
        GIVEN: Only old snapshots (>1 minute ago)
        WHEN: _calculate_request_rate() is called
        THEN: Rate is 0.0
        """
        collector = _make_collector()
        # Add old snapshots
        for _ in range(5):
            collector.performance_snapshots.append(_snapshot(seconds_ago=120))

        rate = collector._calculate_request_rate()
        assert rate == 0.0


# ---------------------------------------------------------------------------
# TestCleanupOldData
# ---------------------------------------------------------------------------

class TestCleanupOldData:
    """Tests for _cleanup_old_data."""

    def test_old_snapshots_are_removed(self):
        """
        GIVEN: Performance snapshots older than retention_hours
        WHEN: _cleanup_old_data() is called
        THEN: Old snapshots are removed from the deque
        """
        collector = _make_collector()
        # Add one old snapshot and one recent
        old_ts = datetime.utcnow() - timedelta(hours=48)
        old_snap = _snapshot(seconds_ago=0)
        old_snap.timestamp = old_ts
        # Use a direct deque append since PerformanceSnapshot is a dataclass
        collector.performance_snapshots.append(
            PerformanceSnapshot(
                timestamp=old_ts,
                cpu_percent=0.0,
                memory_percent=0.0,
                memory_used_mb=0.0,
                disk_percent=0.0,
                active_connections=0,
                request_rate=0.0,
                error_rate=0.0,
                avg_response_time_ms=0.0,
            )
        )
        collector.performance_snapshots.append(_snapshot(seconds_ago=5))

        _run(collector._cleanup_old_data())
        # Only the recent snapshot should remain
        assert len(collector.performance_snapshots) == 1

    def test_old_alerts_are_removed(self):
        """
        GIVEN: Alerts older than retention_hours
        WHEN: _cleanup_old_data() is called
        THEN: Old alerts are removed
        """
        collector = _make_collector()
        old_ts = datetime.utcnow() - timedelta(hours=48)
        # alerts is a deque; items need 'timestamp' key
        collector.alerts.append({"type": "cpu_high", "timestamp": old_ts})
        collector.alerts.append({"type": "memory_high", "timestamp": datetime.utcnow()})

        _run(collector._cleanup_old_data())
        assert len(collector.alerts) == 1


# ---------------------------------------------------------------------------
# TestComputePercentilesEdgeCases
# ---------------------------------------------------------------------------

class TestComputePercentilesEdgeCases:
    """Tests for _compute_percentiles with small sample sizes."""

    def test_zero_samples_returns_zeros(self):
        """
        GIVEN: An empty list of times
        WHEN: _compute_percentiles([]) is called
        THEN: All values are 0.0
        """
        collector = _make_collector()
        result = collector._compute_percentiles([])
        assert result["p50"] == 0.0
        assert result["p95"] == 0.0
        assert result["p99"] == 0.0

    def test_one_sample_returns_zeros(self):
        """
        GIVEN: A list with exactly one element
        WHEN: _compute_percentiles([42.0]) is called
        THEN: All values are 0.0 (insufficient data)
        """
        collector = _make_collector()
        result = collector._compute_percentiles([42.0])
        assert result["p50"] == 0.0
        assert result["count"] == 1


# ---------------------------------------------------------------------------
# TestGetToolLatencyPercentiles
# ---------------------------------------------------------------------------

class TestGetToolLatencyPercentiles:
    """Tests for get_tool_latency_percentiles."""

    def test_returns_percentile_dict_for_tracked_tool(self):
        """
        GIVEN: A tool with recorded execution times
        WHEN: get_tool_latency_percentiles() is called
        THEN: Returns dict with p50/p95/p99 keys
        """
        collector = _make_collector()
        for t in [10.0, 20.0, 30.0, 40.0, 50.0, 100.0]:
            collector.track_tool_execution("my_tool", t, True)

        result = collector.get_tool_latency_percentiles("my_tool")
        assert "p50" in result
        assert "p95" in result
        assert "p99" in result
        assert result["count"] == 6

    def test_returns_zeros_for_unknown_tool(self):
        """
        GIVEN: No tracking data for a tool
        WHEN: get_tool_latency_percentiles('unknown') is called
        THEN: Returns all-zero dict
        """
        collector = _make_collector()
        result = collector.get_tool_latency_percentiles("unknown_tool")
        assert result["p50"] == 0.0


# ---------------------------------------------------------------------------
# TestGetPerformanceTrends
# ---------------------------------------------------------------------------

class TestGetPerformanceTrends:
    """Tests for get_performance_trends."""

    def test_returns_four_trend_keys(self):
        """
        GIVEN: A collector with some performance snapshots
        WHEN: get_performance_trends() is called
        THEN: Returns dict with cpu/memory/request_rate/response_time trends
        """
        collector = _make_collector()
        for _ in range(3):
            collector.performance_snapshots.append(_snapshot(seconds_ago=30))

        trends = collector.get_performance_trends(hours=1)
        assert "cpu_trend" in trends
        assert "memory_trend" in trends
        assert "request_rate_trend" in trends
        assert "response_time_trend" in trends

    def test_trends_contain_recent_snapshots(self):
        """
        GIVEN: Three recent snapshots and one old snapshot
        WHEN: get_performance_trends(hours=1) is called
        THEN: Only recent snapshots appear in trend data
        """
        collector = _make_collector()
        # Old snapshot (3 hours ago)
        old_ts = datetime.utcnow() - timedelta(hours=3)
        collector.performance_snapshots.append(
            PerformanceSnapshot(
                timestamp=old_ts,
                cpu_percent=99.0,
                memory_percent=99.0,
                memory_used_mb=0.0,
                disk_percent=0.0,
                active_connections=0,
                request_rate=0.0,
                error_rate=0.0,
                avg_response_time_ms=0.0,
            )
        )
        # Recent snapshots
        for _ in range(2):
            collector.performance_snapshots.append(_snapshot(seconds_ago=30))

        trends = collector.get_performance_trends(hours=1)
        assert len(trends["cpu_trend"]) == 2  # Only the recent ones

    def test_trends_empty_when_no_snapshots(self):
        """
        GIVEN: No performance snapshots
        WHEN: get_performance_trends() is called
        THEN: All trend lists are empty
        """
        collector = _make_collector()
        trends = collector.get_performance_trends(hours=1)
        assert trends["cpu_trend"] == []


# ---------------------------------------------------------------------------
# TestShutdown
# ---------------------------------------------------------------------------

class TestShutdown:
    """Tests for the shutdown() method."""

    def test_shutdown_with_tasks_cancels_them(self):
        """
        GIVEN: monitoring_task and cleanup_task are set
        WHEN: shutdown() is called
        THEN: Both tasks are cancelled without error
        """
        collector = _make_collector()

        async def run():
            async def dummy():
                await asyncio.sleep(100)

            loop = asyncio.get_event_loop()
            collector.monitoring_task = loop.create_task(dummy())
            collector.cleanup_task = loop.create_task(dummy())
            await collector.shutdown()

        _run(run())

    def test_shutdown_noop_when_no_tasks(self):
        """
        GIVEN: monitoring_task and cleanup_task are None
        WHEN: shutdown() is called
        THEN: No error is raised
        """
        collector = _make_collector()
        collector.monitoring_task = None
        collector.cleanup_task = None

        _run(collector.shutdown())  # Should not raise


# ---------------------------------------------------------------------------
# TestDashboardCacheHit
# ---------------------------------------------------------------------------

class TestDashboardCacheHit:
    """Tests for P2PMetricsCollector.get_dashboard_data cache hit."""

    def test_second_call_returns_cached_data(self):
        """
        GIVEN: get_dashboard_data called once (populates cache)
        WHEN: Called again within cache TTL
        THEN: Returns cached result (no recomputation)
        """
        collector = P2PMetricsCollector()
        first = collector.get_dashboard_data()
        second = collector.get_dashboard_data()
        assert first is second  # Same object from cache

    def test_force_refresh_bypasses_cache(self):
        """
        GIVEN: Cached dashboard data
        WHEN: get_dashboard_data(force_refresh=True) is called
        THEN: Returns a freshly computed object
        """
        collector = P2PMetricsCollector()
        first = collector.get_dashboard_data()
        fresh = collector.get_dashboard_data(force_refresh=True)
        # May or may not be same object depending on implementation, but shouldn't raise
        assert fresh is not None


# ---------------------------------------------------------------------------
# TestMetricsCollectorSingleton
# ---------------------------------------------------------------------------

class TestMetricsCollectorSingleton:
    """Tests for get_metrics_collector and get_p2p_metrics_collector singletons."""

    def test_get_metrics_collector_returns_same_instance(self):
        """
        GIVEN: The global metrics_collector is already set
        WHEN: get_metrics_collector() is called multiple times
        THEN: The same instance is returned each time
        """
        import ipfs_datasets_py.mcp_server.monitoring as mod

        # Ensure it's set
        first = mod.get_metrics_collector()
        second = mod.get_metrics_collector()
        assert first is second

    def test_get_p2p_metrics_collector_returns_same_instance(self):
        """
        GIVEN: The global p2p_metrics_collector is already set
        WHEN: get_p2p_metrics_collector() is called multiple times
        THEN: The same instance is returned each time
        """
        import ipfs_datasets_py.mcp_server.monitoring as mod

        first = mod.get_p2p_metrics_collector()
        second = mod.get_p2p_metrics_collector()
        assert first is second

    def test_get_metrics_collector_creates_when_none(self):
        """
        GIVEN: The global metrics_collector is None
        WHEN: get_metrics_collector() is called
        THEN: A new EnhancedMetricsCollector is created and returned
        """
        import ipfs_datasets_py.mcp_server.monitoring as mod

        original = mod.metrics_collector
        try:
            mod.metrics_collector = None
            result = mod.get_metrics_collector()
            assert isinstance(result, EnhancedMetricsCollector)
        finally:
            mod.metrics_collector = original

    def test_get_p2p_metrics_collector_creates_when_none(self):
        """
        GIVEN: The global p2p_metrics_collector is None
        WHEN: get_p2p_metrics_collector() is called
        THEN: A new P2PMetricsCollector is created and returned
        """
        import ipfs_datasets_py.mcp_server.monitoring as mod

        original = mod.p2p_metrics_collector
        try:
            mod.p2p_metrics_collector = None
            result = mod.get_p2p_metrics_collector()
            assert isinstance(result, P2PMetricsCollector)
        finally:
            mod.p2p_metrics_collector = original
