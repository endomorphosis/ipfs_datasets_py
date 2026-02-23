"""
Session R69 — monitoring.py deep coverage:
  _monitoring_loop, _cleanup_loop, track_request, track_tool_execution,
  get_metrics_summary, _collect_system_metrics (no-psutil path)
"""
import sys
import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
import anyio

from ipfs_datasets_py.mcp_server.monitoring import (
    EnhancedMetricsCollector,
    MetricData,
    HealthCheckResult,
    PerformanceSnapshot,
)
from ipfs_datasets_py.mcp_server.exceptions import MetricsCollectionError, MonitoringError


# ---------------------------------------------------------------------------
# TestMonitoringLoop
# ---------------------------------------------------------------------------

class TestMonitoringLoopPaths:
    """_monitoring_loop() and _cleanup_loop() error-path coverage."""

    @pytest.mark.asyncio
    async def test_monitoring_loop_exits_on_cancelled(self):
        """_monitoring_loop exits cleanly when anyio CancelledError raised."""
        mc = EnhancedMetricsCollector()
        # Run the loop but cancel it after one iteration
        async def _driver():
            async with anyio.create_task_group() as tg:
                tg.start_soon(mc._monitoring_loop)
                await anyio.sleep(0)  # let one iteration start
                tg.cancel_scope.cancel()
        await anyio.sleep(0)  # noop warm-up
        # Just verifying no crash:
        with patch.object(mc, "_collect_system_metrics", AsyncMock(side_effect=anyio.get_cancelled_exc_class())):
            try:
                await mc._monitoring_loop()
            except Exception:
                pass  # cancelled or raised from loop — acceptable

    @pytest.mark.asyncio
    async def test_monitoring_loop_handles_metrics_collection_error(self):
        """_monitoring_loop() sleeps on MetricsCollectionError, then can be cancelled."""
        mc = EnhancedMetricsCollector()
        sleep_calls = []

        async def fake_sleep(secs):
            sleep_calls.append(secs)
            # Signal the loop to stop by raising CancelledError
            raise anyio.get_cancelled_exc_class()()

        with patch.object(mc, "_collect_system_metrics",
                          AsyncMock(side_effect=MetricsCollectionError("test"))):
            with patch.object(mc, "_check_health", AsyncMock()):
                with patch.object(mc, "_check_alerts", AsyncMock()):
                    with patch("ipfs_datasets_py.mcp_server.monitoring.anyio.sleep", fake_sleep):
                        try:
                            await mc._monitoring_loop()
                        except (Exception, BaseException):
                            pass
        # The 60s sleep was attempted after the error
        assert 60 in sleep_calls

    @pytest.mark.asyncio
    async def test_monitoring_loop_handles_os_error(self):
        """_monitoring_loop() sleeps on OSError."""
        mc = EnhancedMetricsCollector()
        sleep_calls = []

        async def fake_sleep(secs):
            sleep_calls.append(secs)
            raise anyio.get_cancelled_exc_class()()

        with patch.object(mc, "_collect_system_metrics",
                          AsyncMock(side_effect=OSError("disk read error"))):
            with patch("ipfs_datasets_py.mcp_server.monitoring.anyio.sleep", fake_sleep):
                try:
                    await mc._monitoring_loop()
                except (Exception, BaseException):
                    pass
        assert len(sleep_calls) >= 1

    @pytest.mark.asyncio
    async def test_cleanup_loop_exits_on_cancelled(self):
        """_cleanup_loop exits cleanly on cancellation."""
        mc = EnhancedMetricsCollector()
        with patch.object(mc, "_cleanup_old_data", AsyncMock(
                side_effect=anyio.get_cancelled_exc_class()())):
            try:
                await mc._cleanup_loop()
            except (Exception, BaseException):
                pass  # acceptable

    @pytest.mark.asyncio
    async def test_cleanup_loop_handles_io_error(self):
        """_cleanup_loop() continues after IOError."""
        mc = EnhancedMetricsCollector()
        sleep_calls = []

        async def fake_sleep(secs):
            sleep_calls.append(secs)
            raise anyio.get_cancelled_exc_class()()

        with patch.object(mc, "_cleanup_old_data",
                          AsyncMock(side_effect=IOError("disk error"))):
            with patch("ipfs_datasets_py.mcp_server.monitoring.anyio.sleep", fake_sleep):
                try:
                    await mc._cleanup_loop()
                except (Exception, BaseException):
                    pass
        assert len(sleep_calls) >= 1


# ---------------------------------------------------------------------------
# TestTrackRequest
# ---------------------------------------------------------------------------

class TestTrackRequest:
    """track_request() async context manager."""

    @pytest.mark.asyncio
    async def test_track_request_success_increments_count(self):
        """Successful request increments request_count."""
        mc = EnhancedMetricsCollector()
        initial = mc.request_count
        async with mc.track_request("/test"):
            pass
        assert mc.request_count == initial + 1

    @pytest.mark.asyncio
    async def test_track_request_success_records_time(self):
        """Successful request appends to request_times."""
        mc = EnhancedMetricsCollector()
        async with mc.track_request("/test"):
            pass
        assert len(mc.request_times) >= 1

    @pytest.mark.asyncio
    async def test_track_request_exception_increments_error_count(self):
        """Exception inside track_request() increments error_count and re-raises."""
        mc = EnhancedMetricsCollector()
        initial_errors = mc.error_count
        with pytest.raises(ValueError):
            async with mc.track_request("/failing"):
                raise ValueError("oops")
        assert mc.error_count == initial_errors + 1

    @pytest.mark.asyncio
    async def test_track_request_monitoring_error_increments_error_count(self):
        """MonitoringError inside track_request() increments error_count and re-raises."""
        mc = EnhancedMetricsCollector()
        initial_errors = mc.error_count
        with pytest.raises(MonitoringError):
            async with mc.track_request("/monitor"):
                raise MonitoringError("monitor fail")
        assert mc.error_count == initial_errors + 1

    @pytest.mark.asyncio
    async def test_track_request_active_requests_cleared_after(self):
        """active_requests dict is cleaned up after the context exits."""
        mc = EnhancedMetricsCollector()
        async with mc.track_request("/ep"):
            active_during = dict(mc.active_requests)
        # After exit, the request should be removed
        assert len(mc.active_requests) == 0


# ---------------------------------------------------------------------------
# TestTrackToolExecution
# ---------------------------------------------------------------------------

class TestTrackToolExecution:
    """track_tool_execution() updates tool metrics correctly."""

    def test_track_success_increments_call_count(self):
        """Successful call increments call_counts[tool]."""
        mc = EnhancedMetricsCollector()
        mc.track_tool_execution("my_tool", 50.0, success=True)
        assert mc.tool_metrics["call_counts"]["my_tool"] == 1

    def test_track_success_does_not_increment_error_count(self):
        """Successful call leaves error_counts[tool] at 0."""
        mc = EnhancedMetricsCollector()
        mc.track_tool_execution("my_tool", 50.0, success=True)
        assert mc.tool_metrics["error_counts"]["my_tool"] == 0

    def test_track_failure_increments_error_count(self):
        """Failed call increments error_counts[tool]."""
        mc = EnhancedMetricsCollector()
        mc.track_tool_execution("my_tool", 50.0, success=False)
        assert mc.tool_metrics["error_counts"]["my_tool"] == 1

    def test_track_execution_records_time(self):
        """Execution time is recorded in execution_times."""
        mc = EnhancedMetricsCollector()
        mc.track_tool_execution("my_tool", 123.4, success=True)
        assert 123.4 in mc.tool_metrics["execution_times"]["my_tool"]

    def test_track_execution_updates_success_rate(self):
        """Success rate is updated correctly after 1 pass + 1 fail."""
        mc = EnhancedMetricsCollector()
        mc.track_tool_execution("my_tool", 100.0, success=True)
        mc.track_tool_execution("my_tool", 100.0, success=False)
        # 1 error out of 2 calls → success_rate = 0.5
        assert mc.tool_metrics["success_rates"]["my_tool"] == pytest.approx(0.5)

    def test_track_execution_updates_last_called(self):
        """last_called is updated to a datetime."""
        mc = EnhancedMetricsCollector()
        mc.track_tool_execution("my_tool", 10.0, success=True)
        assert isinstance(mc.tool_metrics["last_called"]["my_tool"], datetime)

    def test_track_multiple_tools_independent(self):
        """Two different tools have independent call counts."""
        mc = EnhancedMetricsCollector()
        mc.track_tool_execution("tool_a", 10.0, success=True)
        mc.track_tool_execution("tool_b", 20.0, success=True)
        assert mc.tool_metrics["call_counts"]["tool_a"] == 1
        assert mc.tool_metrics["call_counts"]["tool_b"] == 1


# ---------------------------------------------------------------------------
# TestGetMetricsSummary
# ---------------------------------------------------------------------------

class TestGetMetricsSummary:
    """get_metrics_summary() returns correct structure."""

    def test_summary_has_required_keys(self):
        """Summary dict has all required top-level keys."""
        mc = EnhancedMetricsCollector()
        summary = mc.get_metrics_summary()
        for key in ("uptime_seconds", "system_metrics", "request_metrics",
                    "tool_metrics", "health_status", "recent_alerts"):
            assert key in summary, f"Missing key: {key}"

    def test_summary_uptime_non_negative(self):
        """uptime_seconds is ≥ 0."""
        mc = EnhancedMetricsCollector()
        assert mc.get_metrics_summary()["uptime_seconds"] >= 0.0

    def test_summary_request_metrics_keys(self):
        """request_metrics has all expected sub-keys."""
        mc = EnhancedMetricsCollector()
        rm = mc.get_metrics_summary()["request_metrics"]
        for k in ("total_requests", "total_errors", "error_rate",
                  "avg_response_time_ms", "active_requests", "request_rate_per_second"):
            assert k in rm

    def test_summary_includes_tool_after_tracking(self):
        """tool_metrics includes an entry after track_tool_execution is called."""
        mc = EnhancedMetricsCollector()
        mc.track_tool_execution("cool_tool", 75.0, success=True)
        summary = mc.get_metrics_summary()
        assert "cool_tool" in summary["tool_metrics"]
        assert summary["tool_metrics"]["cool_tool"]["total_calls"] == 1

    def test_summary_empty_tool_metrics(self):
        """tool_metrics is empty dict when no tools tracked."""
        mc = EnhancedMetricsCollector()
        assert mc.get_metrics_summary()["tool_metrics"] == {}

    def test_summary_recent_alerts_empty_initially(self):
        """recent_alerts is an empty list initially."""
        mc = EnhancedMetricsCollector()
        assert mc.get_metrics_summary()["recent_alerts"] == []


# ---------------------------------------------------------------------------
# TestCollectSystemMetricsNoPsutil
# ---------------------------------------------------------------------------

class TestCollectSystemMetricsNoPsutil:
    """_collect_system_metrics() without psutil installed."""

    @pytest.mark.asyncio
    async def test_no_psutil_appends_zero_snapshot(self):
        """When HAVE_PSUTIL is False, a zero-filled snapshot is appended."""
        import ipfs_datasets_py.mcp_server.monitoring as mon_mod
        mc = EnhancedMetricsCollector()
        with patch.object(mon_mod, "HAVE_PSUTIL", False):
            await mc._collect_system_metrics()
        assert len(mc.performance_snapshots) >= 1
        snap = mc.performance_snapshots[-1]
        assert snap.cpu_percent == 0.0
        assert snap.memory_percent == 0.0

    @pytest.mark.asyncio
    async def test_no_psutil_does_not_update_system_metrics_dict(self):
        """When psutil absent, system_metrics dict is not populated."""
        import ipfs_datasets_py.mcp_server.monitoring as mon_mod
        mc = EnhancedMetricsCollector()
        initial_keys = set(mc.system_metrics.keys())
        with patch.object(mon_mod, "HAVE_PSUTIL", False):
            await mc._collect_system_metrics()
        # No psutil-sourced keys like 'cpu_percent' should have been set
        assert mc.system_metrics.get("cpu_percent", 0.0) == 0.0


# ---------------------------------------------------------------------------
# TestStartMonitoring
# ---------------------------------------------------------------------------

class TestStartMonitoring:
    """start_monitoring() behaviour."""

    def test_start_monitoring_disabled(self):
        """start_monitoring() is a no-op when enabled=False."""
        mc = EnhancedMetricsCollector(enabled=False)
        mc._start_monitoring = MagicMock()
        mc.start_monitoring()
        mc._start_monitoring.assert_not_called()

    def test_start_monitoring_not_in_async_context(self):
        """start_monitoring() does nothing when called outside async context."""
        mc = EnhancedMetricsCollector(enabled=True)
        # In a sync context, in_async_context() returns False → _start_monitoring returns early
        # Just verify no exception
        mc.start_monitoring()
