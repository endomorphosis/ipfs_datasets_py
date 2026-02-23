"""
U75 — monitoring.py _check_health async path + P2PMetricsCollector alert thresholds
======================================================================================
Covers:
  * _check_health:
    - async check function (coroutine)
    - awaitable result (non-coroutine returning awaitable)
    - HealthCheckResult propagation (response_time_ms set)
    - non-HealthCheckResult return → assumed healthy
    - HealthCheckError → status='critical'
    - ImportError → status='critical', 'unavailable' in message
    - generic Exception → status='critical'

  * P2PMetricsCollector.get_alert_conditions:
    - peer discovery: below threshold (≤10 total) → no alert
    - peer discovery: failure_rate ≤ 30% → no alert
    - peer discovery: failure_rate > 30% → warning alert
    - workflow: total ≤ 5 → no alert
    - workflow: failure_rate ≤ 20% → no alert
    - workflow: failure_rate > 20% → warning alert
    - bootstrap: total ≤ 3 → no alert
    - bootstrap: failure_rate ≤ 50% → no alert
    - bootstrap: failure_rate > 50% → critical alert

  * P2PMetricsCollector._check_peer_discovery_alerts / _check_workflow_alerts /
    _check_bootstrap_alerts (direct calls for branch coverage)
"""
from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path
import sys
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from ipfs_datasets_py.mcp_server.monitoring import (
    EnhancedMetricsCollector,
    HealthCheckResult,
    P2PMetricsCollector,
)
from ipfs_datasets_py.mcp_server.exceptions import HealthCheckError


# ===========================================================================
# _check_health: async check function path
# ===========================================================================

class TestCheckHealthAsync:

    async def test_async_coroutine_check_function(self):
        """An async check function must be awaited and result stored."""
        col = EnhancedMetricsCollector(enabled=True)

        async def my_check():
            return HealthCheckResult(
                component="test_comp", status="healthy", message="ok"
            )

        col.register_health_check("comp_async", my_check)
        await col._check_health()

        assert "comp_async" in col.health_checks
        r = col.health_checks["comp_async"]
        assert r.status == "healthy"
        assert r.response_time_ms >= 0

    async def test_awaitable_result_from_sync_check(self):
        """A sync function that returns an awaitable must also be awaited."""
        col = EnhancedMetricsCollector(enabled=True)

        async def _coro():
            return HealthCheckResult(
                component="awaitable_comp", status="healthy", message="ok"
            )

        def sync_returning_awaitable():
            return _coro()

        col.register_health_check("awaitable_comp", sync_returning_awaitable)
        await col._check_health()

        assert col.health_checks["awaitable_comp"].status == "healthy"

    async def test_non_health_check_result_assumed_healthy(self):
        """A check returning None (not HealthCheckResult) → status='healthy'."""
        col = EnhancedMetricsCollector(enabled=True)

        def simple_check():
            return None  # not a HealthCheckResult

        col.register_health_check("simple", simple_check)
        await col._check_health()

        assert col.health_checks["simple"].status == "healthy"

    async def test_health_check_error_sets_critical(self):
        """HealthCheckError → stored as status='critical'."""
        col = EnhancedMetricsCollector(enabled=True)

        def failing_check():
            raise HealthCheckError("test", "database not reachable")

        col.register_health_check("db", failing_check)
        await col._check_health()

        r = col.health_checks["db"]
        assert r.status == "critical"
        assert "database not reachable" in r.message

    async def test_import_error_sets_critical_unavailable(self):
        """ImportError → status='critical', message contains 'unavailable'."""
        col = EnhancedMetricsCollector(enabled=True)

        def missing_dep_check():
            raise ImportError("torch not installed")

        col.register_health_check("ml", missing_dep_check)
        await col._check_health()

        r = col.health_checks["ml"]
        assert r.status == "critical"
        assert "unavailable" in r.message

    async def test_generic_exception_sets_critical(self):
        """A generic exception → status='critical'."""
        col = EnhancedMetricsCollector(enabled=True)

        def exploding_check():
            raise RuntimeError("exploded")

        col.register_health_check("explode", exploding_check)
        await col._check_health()

        r = col.health_checks["explode"]
        assert r.status == "critical"

    async def test_response_time_set_on_health_check_result(self):
        """response_time_ms is updated in place for HealthCheckResult returns."""
        col = EnhancedMetricsCollector(enabled=True)

        def timed_check():
            return HealthCheckResult(
                component="timed", status="healthy", message="ok",
                response_time_ms=0.0
            )

        col.register_health_check("timed", timed_check)
        await col._check_health()

        # response_time_ms should be updated by _check_health
        assert col.health_checks["timed"].response_time_ms >= 0


# ===========================================================================
# P2PMetricsCollector.get_alert_conditions — peer discovery
# ===========================================================================

class TestPeerDiscoveryAlerts:

    def _make_collector(self) -> P2PMetricsCollector:
        return P2PMetricsCollector()

    def test_below_minimum_sample_no_alert(self):
        """≤10 total discoveries → no alert regardless of failure count."""
        c = self._make_collector()
        c.peer_discovery_metrics["total_discoveries"] = 5
        c.peer_discovery_metrics["failed_discoveries"] = 5
        alerts = c._check_peer_discovery_alerts()
        assert alerts == []

    def test_failure_rate_at_threshold_no_alert(self):
        """30% failure rate (== threshold) → no alert."""
        c = self._make_collector()
        c.peer_discovery_metrics["total_discoveries"] = 100
        c.peer_discovery_metrics["failed_discoveries"] = 30
        alerts = c._check_peer_discovery_alerts()
        assert alerts == []

    def test_failure_rate_above_threshold_warning_alert(self):
        """31% failure rate → warning alert issued."""
        c = self._make_collector()
        c.peer_discovery_metrics["total_discoveries"] = 100
        c.peer_discovery_metrics["failed_discoveries"] = 31
        alerts = c._check_peer_discovery_alerts()
        assert len(alerts) == 1
        assert alerts[0]["type"] == "warning"
        assert alerts[0]["component"] == "peer_discovery"
        assert "31.0%" in alerts[0]["message"]

    def test_get_alert_conditions_includes_peer_discovery(self):
        """get_alert_conditions delegates to _check_peer_discovery_alerts."""
        c = self._make_collector()
        c.peer_discovery_metrics["total_discoveries"] = 100
        c.peer_discovery_metrics["failed_discoveries"] = 50
        alerts = c.get_alert_conditions()
        comps = [a["component"] for a in alerts]
        assert "peer_discovery" in comps


# ===========================================================================
# P2PMetricsCollector.get_alert_conditions — workflows
# ===========================================================================

class TestWorkflowAlerts:

    def _make_collector(self) -> P2PMetricsCollector:
        return P2PMetricsCollector()

    def test_below_minimum_sample_no_alert(self):
        """≤5 total workflows → no alert."""
        c = self._make_collector()
        c.workflow_metrics["completed_workflows"] = 2
        c.workflow_metrics["failed_workflows"] = 3
        alerts = c._check_workflow_alerts()
        assert alerts == []

    def test_failure_rate_at_threshold_no_alert(self):
        """20% failure rate (== threshold) → no alert."""
        c = self._make_collector()
        c.workflow_metrics["completed_workflows"] = 8
        c.workflow_metrics["failed_workflows"] = 2
        alerts = c._check_workflow_alerts()
        assert alerts == []

    def test_failure_rate_above_threshold_warning_alert(self):
        """21% failure rate → warning alert."""
        c = self._make_collector()
        c.workflow_metrics["completed_workflows"] = 79
        c.workflow_metrics["failed_workflows"] = 21
        alerts = c._check_workflow_alerts()
        assert len(alerts) == 1
        assert alerts[0]["type"] == "warning"
        assert alerts[0]["component"] == "workflows"
        assert "21.0%" in alerts[0]["message"]

    def test_get_alert_conditions_includes_workflow(self):
        c = self._make_collector()
        c.workflow_metrics["completed_workflows"] = 50
        c.workflow_metrics["failed_workflows"] = 50
        alerts = c.get_alert_conditions()
        comps = [a["component"] for a in alerts]
        assert "workflows" in comps


# ===========================================================================
# P2PMetricsCollector.get_alert_conditions — bootstrap
# ===========================================================================

class TestBootstrapAlerts:

    def _make_collector(self) -> P2PMetricsCollector:
        return P2PMetricsCollector()

    def test_below_minimum_sample_no_alert(self):
        """≤3 bootstrap attempts → no alert."""
        c = self._make_collector()
        c.bootstrap_metrics["total_bootstrap_attempts"] = 2
        c.bootstrap_metrics["failed_bootstraps"] = 2
        alerts = c._check_bootstrap_alerts()
        assert alerts == []

    def test_failure_rate_at_threshold_no_alert(self):
        """50% failure rate (== threshold) → no alert."""
        c = self._make_collector()
        c.bootstrap_metrics["total_bootstrap_attempts"] = 10
        c.bootstrap_metrics["failed_bootstraps"] = 5
        alerts = c._check_bootstrap_alerts()
        assert alerts == []

    def test_failure_rate_above_threshold_critical_alert(self):
        """51% failure rate → critical alert."""
        c = self._make_collector()
        c.bootstrap_metrics["total_bootstrap_attempts"] = 10
        c.bootstrap_metrics["failed_bootstraps"] = 6
        alerts = c._check_bootstrap_alerts()
        assert len(alerts) == 1
        assert alerts[0]["type"] == "critical"
        assert alerts[0]["component"] == "bootstrap"
        assert "60.0%" in alerts[0]["message"]

    def test_get_alert_conditions_includes_bootstrap(self):
        c = self._make_collector()
        c.bootstrap_metrics["total_bootstrap_attempts"] = 10
        c.bootstrap_metrics["failed_bootstraps"] = 9
        alerts = c.get_alert_conditions()
        comps = [a["component"] for a in alerts]
        assert "bootstrap" in comps

    def test_get_alert_conditions_empty_when_all_healthy(self):
        """No anomalies → empty list."""
        c = self._make_collector()
        alerts = c.get_alert_conditions()
        assert alerts == []

    def test_alert_has_timestamp_key(self):
        """Each alert dict must contain a 'timestamp' key."""
        c = self._make_collector()
        c.bootstrap_metrics["total_bootstrap_attempts"] = 10
        c.bootstrap_metrics["failed_bootstraps"] = 9
        alerts = c._check_bootstrap_alerts()
        assert "timestamp" in alerts[0]

    def test_multiple_alert_types_returned(self):
        """All three alert types can fire simultaneously."""
        c = self._make_collector()
        # Trigger peer discovery alert
        c.peer_discovery_metrics["total_discoveries"] = 100
        c.peer_discovery_metrics["failed_discoveries"] = 50
        # Trigger workflow alert
        c.workflow_metrics["completed_workflows"] = 50
        c.workflow_metrics["failed_workflows"] = 50
        # Trigger bootstrap alert
        c.bootstrap_metrics["total_bootstrap_attempts"] = 10
        c.bootstrap_metrics["failed_bootstraps"] = 9
        alerts = c.get_alert_conditions()
        comps = {a["component"] for a in alerts}
        assert comps == {"peer_discovery", "workflows", "bootstrap"}
