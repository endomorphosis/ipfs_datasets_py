"""
Session 39 — Additional tests for monitoring.py covering previously-uncovered methods.

Covers:
- EnhancedMetricsCollector.register_health_check() / _check_health()
- EnhancedMetricsCollector._calculate_request_rate/error_rate/avg_response_time()
- EnhancedMetricsCollector._check_alerts()
- P2PMetricsCollector.track_peer_discovery()
- P2PMetricsCollector.track_workflow_execution()
- P2PMetricsCollector.track_bootstrap_operation()
- P2PMetricsCollector.get_dashboard_data()
"""
import asyncio
import pytest
from unittest.mock import Mock, patch
from collections import deque
from datetime import datetime

from ipfs_datasets_py.mcp_server.monitoring import (
    EnhancedMetricsCollector,
    HealthCheckResult,
    P2PMetricsCollector,
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


# ---------------------------------------------------------------------------
# EnhancedMetricsCollector.register_health_check / _check_health
# ---------------------------------------------------------------------------

class TestRegisterHealthCheck:
    """Tests for register_health_check() and _check_health()."""

    def test_register_stores_function(self):
        """register_health_check() stores the check function by name."""
        collector = _make_collector()
        fn = lambda: HealthCheckResult(component="db", status="healthy", message="ok")
        collector.register_health_check("database", fn)
        assert "database" in collector.health_check_registry

    def test_register_overwrites_existing(self):
        """register_health_check() overwrites a previously registered check."""
        collector = _make_collector()
        fn1 = lambda: HealthCheckResult(component="svc", status="healthy", message="v1")
        fn2 = lambda: HealthCheckResult(component="svc", status="warning", message="v2")
        collector.register_health_check("svc", fn1)
        collector.register_health_check("svc", fn2)
        assert collector.health_check_registry["svc"] is fn2

    def test_check_health_runs_sync_check(self):
        """_check_health() executes a synchronous health check and stores the result."""
        collector = _make_collector()

        def healthy_check():
            return HealthCheckResult(component="cache", status="healthy", message="All good")

        collector.register_health_check("cache", healthy_check)
        _run(collector._check_health())
        assert "cache" in collector.health_checks
        result = collector.health_checks["cache"]
        assert result.status == "healthy"

    def test_check_health_runs_async_check(self):
        """_check_health() executes an async health check."""
        collector = _make_collector()

        async def async_healthy():
            return HealthCheckResult(component="ipfs", status="healthy", message="running")

        collector.register_health_check("ipfs", async_healthy)
        _run(collector._check_health())
        assert collector.health_checks["ipfs"].status == "healthy"

    def test_check_health_catches_exception_as_critical(self):
        """_check_health() converts a raised exception to a 'critical' result."""
        collector = _make_collector()

        def broken_check():
            raise RuntimeError("connection refused")

        collector.register_health_check("broken", broken_check)
        _run(collector._check_health())
        assert "broken" in collector.health_checks
        assert collector.health_checks["broken"].status == "critical"

    def test_check_health_handles_non_healthcheckresult_return(self):
        """_check_health() treats non-HealthCheckResult returns as healthy."""
        collector = _make_collector()

        def non_standard_check():
            return {"ok": True}  # Not a HealthCheckResult

        collector.register_health_check("misc", non_standard_check)
        _run(collector._check_health())
        assert "misc" in collector.health_checks
        assert collector.health_checks["misc"].status == "healthy"


# ---------------------------------------------------------------------------
# EnhancedMetricsCollector._calculate_* helpers
# ---------------------------------------------------------------------------

class TestCalculateHelpers:
    """Tests for _calculate_request_rate, _calculate_error_rate, _calculate_avg_response_time."""

    def test_error_rate_zero_when_no_requests(self):
        """_calculate_error_rate() returns 0.0 when request_count==0."""
        collector = _make_collector()
        assert collector._calculate_error_rate() == 0.0

    def test_error_rate_computed_correctly(self):
        """_calculate_error_rate() returns error_count / request_count."""
        collector = _make_collector()
        collector.request_count = 10
        collector.error_count = 3
        assert abs(collector._calculate_error_rate() - 0.3) < 1e-9

    def test_avg_response_time_zero_when_no_requests(self):
        """_calculate_avg_response_time() returns 0.0 when request_times is empty."""
        collector = _make_collector()
        assert collector._calculate_avg_response_time() == 0.0

    def test_avg_response_time_computed_correctly(self):
        """_calculate_avg_response_time() returns mean of request_times."""
        collector = _make_collector()
        collector.request_times = deque([100.0, 200.0, 300.0])
        avg = collector._calculate_avg_response_time()
        assert abs(avg - 200.0) < 1e-9

    def test_request_rate_zero_when_no_snapshots(self):
        """_calculate_request_rate() returns 0.0 when no performance snapshots exist."""
        collector = _make_collector()
        assert collector._calculate_request_rate() == 0.0


# ---------------------------------------------------------------------------
# EnhancedMetricsCollector._check_alerts
# ---------------------------------------------------------------------------

class TestCheckAlerts:
    """Tests for _check_alerts()."""

    def test_check_alerts_no_alert_when_healthy(self):
        """_check_alerts() adds nothing to alerts when all metrics are below thresholds."""
        collector = _make_collector()
        # Defaults: 0 CPU, 0 memory, 0 errors — all below thresholds
        _run(collector._check_alerts())
        assert len(collector.alerts) == 0

    def test_check_alerts_cpu_high_adds_alert(self):
        """_check_alerts() adds a cpu_high alert when CPU% exceeds threshold."""
        collector = _make_collector()
        collector.system_metrics['cpu_percent'] = 99.0
        collector.alert_thresholds['cpu_percent'] = 80.0
        _run(collector._check_alerts())
        types = [a['type'] for a in collector.alerts]
        assert 'cpu_high' in types

    def test_check_alerts_memory_high_adds_alert(self):
        """_check_alerts() adds a memory_high alert when memory% exceeds threshold."""
        collector = _make_collector()
        collector.system_metrics['memory_percent'] = 95.0
        collector.alert_thresholds['memory_percent'] = 85.0
        _run(collector._check_alerts())
        types = [a['type'] for a in collector.alerts]
        assert 'memory_high' in types

    def test_check_alerts_high_error_rate_adds_alert(self):
        """_check_alerts() adds an error_rate_high alert when error rate exceeds threshold."""
        collector = _make_collector()
        collector.request_count = 100
        collector.error_count = 60  # 60% error rate
        collector.alert_thresholds['error_rate'] = 0.05
        _run(collector._check_alerts())
        types = [a['type'] for a in collector.alerts]
        assert 'error_rate_high' in types


# ---------------------------------------------------------------------------
# P2PMetricsCollector.track_peer_discovery
# ---------------------------------------------------------------------------

class TestTrackPeerDiscovery:
    """Tests for P2PMetricsCollector.track_peer_discovery()."""

    def _make_p2p(self) -> P2PMetricsCollector:
        base = _make_collector()
        return P2PMetricsCollector(base_collector=base)

    def test_increments_total_discoveries(self):
        """track_peer_discovery() always increments total_discoveries."""
        p2p = self._make_p2p()
        p2p.track_peer_discovery("dht", 5, success=True)
        p2p.track_peer_discovery("mdns", 0, success=False)
        assert p2p.peer_discovery_metrics['total_discoveries'] == 2

    def test_success_increments_successful(self):
        """track_peer_discovery(success=True) increments successful_discoveries."""
        p2p = self._make_p2p()
        p2p.track_peer_discovery("dht", 3, success=True)
        assert p2p.peer_discovery_metrics['successful_discoveries'] == 1
        assert p2p.peer_discovery_metrics['failed_discoveries'] == 0

    def test_failure_increments_failed(self):
        """track_peer_discovery(success=False) increments failed_discoveries."""
        p2p = self._make_p2p()
        p2p.track_peer_discovery("mdns", 0, success=False)
        assert p2p.peer_discovery_metrics['failed_discoveries'] == 1

    def test_peers_counted_by_source_on_success(self):
        """track_peer_discovery() adds peers_found to peers_by_source on success."""
        p2p = self._make_p2p()
        p2p.track_peer_discovery("dht", 10, success=True)
        p2p.track_peer_discovery("dht", 5, success=True)
        assert p2p.peer_discovery_metrics['peers_by_source']['dht'] == 15

    def test_peers_not_counted_on_failure(self):
        """track_peer_discovery() does NOT count peers when success=False."""
        p2p = self._make_p2p()
        p2p.track_peer_discovery("dht", 10, success=False)
        assert p2p.peer_discovery_metrics['peers_by_source']['dht'] == 0

    def test_duration_appended_when_provided(self):
        """track_peer_discovery() appends duration_ms when provided."""
        p2p = self._make_p2p()
        p2p.track_peer_discovery("bootstrap", 2, success=True, duration_ms=150.0)
        assert 150.0 in p2p.peer_discovery_metrics['discovery_times']


# ---------------------------------------------------------------------------
# P2PMetricsCollector.track_workflow_execution
# ---------------------------------------------------------------------------

class TestTrackWorkflowExecution:
    """Tests for P2PMetricsCollector.track_workflow_execution()."""

    def _make_p2p(self) -> P2PMetricsCollector:
        base = _make_collector()
        return P2PMetricsCollector(base_collector=base)

    def test_running_increments_active(self):
        """track_workflow_execution('running') increments active_workflows."""
        p2p = self._make_p2p()
        p2p.track_workflow_execution("wf1", "running")
        assert p2p.workflow_metrics['active_workflows'] == 1

    def test_completed_increments_completed_decrements_active(self):
        """track_workflow_execution('completed') increments completed and decrements active."""
        p2p = self._make_p2p()
        p2p.track_workflow_execution("wf1", "running")
        p2p.track_workflow_execution("wf1", "completed", execution_time_ms=1000.0)
        assert p2p.workflow_metrics['completed_workflows'] == 1
        assert p2p.workflow_metrics['active_workflows'] == 0

    def test_failed_increments_failed_decrements_active(self):
        """track_workflow_execution('failed') increments failed and decrements active."""
        p2p = self._make_p2p()
        p2p.track_workflow_execution("wf1", "running")
        p2p.track_workflow_execution("wf1", "failed", execution_time_ms=500.0)
        assert p2p.workflow_metrics['failed_workflows'] == 1
        assert p2p.workflow_metrics['active_workflows'] == 0

    def test_active_not_negative(self):
        """active_workflows never goes below zero."""
        p2p = self._make_p2p()
        # Complete without prior running
        p2p.track_workflow_execution("wf1", "completed")
        assert p2p.workflow_metrics['active_workflows'] == 0

    def test_total_workflows_always_incremented(self):
        """total_workflows is incremented for every call regardless of status."""
        p2p = self._make_p2p()
        p2p.track_workflow_execution("wf1", "running")
        p2p.track_workflow_execution("wf1", "completed")
        p2p.track_workflow_execution("wf2", "failed")
        assert p2p.workflow_metrics['total_workflows'] == 3


# ---------------------------------------------------------------------------
# P2PMetricsCollector.track_bootstrap_operation
# ---------------------------------------------------------------------------

class TestTrackBootstrapOperation:
    """Tests for P2PMetricsCollector.track_bootstrap_operation()."""

    def _make_p2p(self) -> P2PMetricsCollector:
        base = _make_collector()
        return P2PMetricsCollector(base_collector=base)

    def test_success_increments_total_and_successful(self):
        """track_bootstrap_operation(success=True) increments totals."""
        p2p = self._make_p2p()
        p2p.track_bootstrap_operation("dht", success=True, duration_ms=200.0)
        assert p2p.bootstrap_metrics['total_bootstrap_attempts'] == 1
        assert p2p.bootstrap_metrics['successful_bootstraps'] == 1
        assert p2p.bootstrap_metrics['failed_bootstraps'] == 0

    def test_failure_increments_failed(self):
        """track_bootstrap_operation(success=False) increments failed count."""
        p2p = self._make_p2p()
        p2p.track_bootstrap_operation("relay", success=False)
        assert p2p.bootstrap_metrics['failed_bootstraps'] == 1


# ---------------------------------------------------------------------------
# P2PMetricsCollector.get_dashboard_data
# ---------------------------------------------------------------------------

class TestGetDashboardData:
    """Tests for P2PMetricsCollector.get_dashboard_data()."""

    def _make_p2p(self) -> P2PMetricsCollector:
        base = _make_collector()
        return P2PMetricsCollector(base_collector=base)

    def test_returns_dict(self):
        """get_dashboard_data() returns a dict."""
        p2p = self._make_p2p()
        data = p2p.get_dashboard_data()
        assert isinstance(data, dict)

    def test_has_peer_discovery_key(self):
        """get_dashboard_data() contains 'peer_discovery' section."""
        p2p = self._make_p2p()
        assert "peer_discovery" in p2p.get_dashboard_data()

    def test_has_workflows_key(self):
        """get_dashboard_data() contains 'workflows' section."""
        p2p = self._make_p2p()
        assert "workflows" in p2p.get_dashboard_data()

    def test_has_bootstrap_key(self):
        """get_dashboard_data() contains 'bootstrap' section."""
        p2p = self._make_p2p()
        assert "bootstrap" in p2p.get_dashboard_data()

    def test_metrics_reflected_in_dashboard(self):
        """get_dashboard_data() shows updated metrics after tracking calls."""
        p2p = self._make_p2p()
        p2p.track_peer_discovery("dht", 5, success=True)
        data = p2p.get_dashboard_data(force_refresh=True)
        # Dashboard uses 'total' key (not 'total_discoveries')
        assert data["peer_discovery"]["total"] == 1
