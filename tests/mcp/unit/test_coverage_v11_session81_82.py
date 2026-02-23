"""
Session X81: monitoring._check_alerts CPU/memory/error_rate/response_time thresholds
Session X82: p2p_service_manager.stop() P2PServiceError + Exception paths

v11 coverage-hardening sessions. 24 new tests.
"""
from __future__ import annotations

import pytest
import sys
from unittest.mock import MagicMock, patch, AsyncMock

pytestmark = pytest.mark.asyncio

# ─────────────────────────── X81 ────────────────────────────

class TestCheckAlertsCpu:
    """_check_alerts CPU threshold trigger."""

    def _make_mon(self):
        from ipfs_datasets_py.mcp_server.monitoring import EnhancedMetricsCollector
        m = EnhancedMetricsCollector()
        m.alert_thresholds = {'cpu_percent': 80.0, 'memory_percent': 85.0,
                               'error_rate': 0.05, 'response_time_ms': 5000.0}
        m.alerts = []
        m.system_metrics = {}
        return m

    @pytest.mark.asyncio
    async def test_cpu_below_threshold_no_alert(self):
        m = self._make_mon()
        m.system_metrics['cpu_percent'] = 50.0
        m.system_metrics['memory_percent'] = 40.0
        with patch.object(m, '_calculate_error_rate', return_value=0.0), \
             patch.object(m, '_calculate_avg_response_time', return_value=100.0):
            await m._check_alerts()
        types = [a['type'] for a in m.alerts]
        assert 'cpu_high' not in types

    @pytest.mark.asyncio
    async def test_cpu_above_threshold_triggers_warning(self):
        m = self._make_mon()
        m.system_metrics['cpu_percent'] = 95.0
        m.system_metrics['memory_percent'] = 40.0
        with patch.object(m, '_calculate_error_rate', return_value=0.0), \
             patch.object(m, '_calculate_avg_response_time', return_value=100.0):
            await m._check_alerts()
        types = [a['type'] for a in m.alerts]
        assert 'cpu_high' in types

    @pytest.mark.asyncio
    async def test_cpu_alert_has_severity_warning(self):
        m = self._make_mon()
        m.system_metrics['cpu_percent'] = 99.0
        m.system_metrics['memory_percent'] = 0.0
        with patch.object(m, '_calculate_error_rate', return_value=0.0), \
             patch.object(m, '_calculate_avg_response_time', return_value=0.0):
            await m._check_alerts()
        cpu_alerts = [a for a in m.alerts if a['type'] == 'cpu_high']
        assert len(cpu_alerts) >= 1
        assert cpu_alerts[0]['severity'] == 'warning'

    @pytest.mark.asyncio
    async def test_cpu_alert_has_timestamp(self):
        m = self._make_mon()
        m.system_metrics['cpu_percent'] = 90.0
        m.system_metrics['memory_percent'] = 0.0
        with patch.object(m, '_calculate_error_rate', return_value=0.0), \
             patch.object(m, '_calculate_avg_response_time', return_value=0.0):
            await m._check_alerts()
        cpu_alerts = [a for a in m.alerts if a['type'] == 'cpu_high']
        assert 'timestamp' in cpu_alerts[0]

    @pytest.mark.asyncio
    async def test_cpu_at_threshold_no_alert(self):
        m = self._make_mon()
        m.system_metrics['cpu_percent'] = 80.0  # exactly at threshold → no alert
        m.system_metrics['memory_percent'] = 0.0
        with patch.object(m, '_calculate_error_rate', return_value=0.0), \
             patch.object(m, '_calculate_avg_response_time', return_value=0.0):
            await m._check_alerts()
        types = [a['type'] for a in m.alerts]
        assert 'cpu_high' not in types


class TestCheckAlertsMemory:
    """_check_alerts memory threshold trigger."""

    def _make_mon(self):
        from ipfs_datasets_py.mcp_server.monitoring import EnhancedMetricsCollector
        m = EnhancedMetricsCollector()
        m.alert_thresholds = {'cpu_percent': 80.0, 'memory_percent': 85.0,
                               'error_rate': 0.05, 'response_time_ms': 5000.0}
        m.alerts = []
        m.system_metrics = {}
        return m

    @pytest.mark.asyncio
    async def test_memory_above_threshold_triggers_warning(self):
        m = self._make_mon()
        m.system_metrics['cpu_percent'] = 0.0
        m.system_metrics['memory_percent'] = 92.0
        with patch.object(m, '_calculate_error_rate', return_value=0.0), \
             patch.object(m, '_calculate_avg_response_time', return_value=0.0):
            await m._check_alerts()
        types = [a['type'] for a in m.alerts]
        assert 'memory_high' in types

    @pytest.mark.asyncio
    async def test_memory_below_threshold_no_alert(self):
        m = self._make_mon()
        m.system_metrics['cpu_percent'] = 0.0
        m.system_metrics['memory_percent'] = 50.0
        with patch.object(m, '_calculate_error_rate', return_value=0.0), \
             patch.object(m, '_calculate_avg_response_time', return_value=0.0):
            await m._check_alerts()
        types = [a['type'] for a in m.alerts]
        assert 'memory_high' not in types

    @pytest.mark.asyncio
    async def test_memory_alert_severity_warning(self):
        m = self._make_mon()
        m.system_metrics['cpu_percent'] = 0.0
        m.system_metrics['memory_percent'] = 98.0
        with patch.object(m, '_calculate_error_rate', return_value=0.0), \
             patch.object(m, '_calculate_avg_response_time', return_value=0.0):
            await m._check_alerts()
        mem_alerts = [a for a in m.alerts if a['type'] == 'memory_high']
        assert mem_alerts[0]['severity'] == 'warning'


class TestCheckAlertsErrorRate:
    """_check_alerts error-rate threshold trigger."""

    def _make_mon(self):
        from ipfs_datasets_py.mcp_server.monitoring import EnhancedMetricsCollector
        m = EnhancedMetricsCollector()
        m.alert_thresholds = {'cpu_percent': 80.0, 'memory_percent': 85.0,
                               'error_rate': 0.05, 'response_time_ms': 5000.0}
        m.alerts = []
        m.system_metrics = {'cpu_percent': 0.0, 'memory_percent': 0.0}
        return m

    @pytest.mark.asyncio
    async def test_error_rate_above_threshold_triggers_critical(self):
        m = self._make_mon()
        with patch.object(m, '_calculate_error_rate', return_value=0.15), \
             patch.object(m, '_calculate_avg_response_time', return_value=0.0):
            await m._check_alerts()
        types = [a['type'] for a in m.alerts]
        assert 'error_rate_high' in types

    @pytest.mark.asyncio
    async def test_error_rate_alert_is_critical(self):
        m = self._make_mon()
        with patch.object(m, '_calculate_error_rate', return_value=0.20), \
             patch.object(m, '_calculate_avg_response_time', return_value=0.0):
            await m._check_alerts()
        err_alerts = [a for a in m.alerts if a['type'] == 'error_rate_high']
        assert err_alerts[0]['severity'] == 'critical'

    @pytest.mark.asyncio
    async def test_error_rate_below_threshold_no_alert(self):
        m = self._make_mon()
        with patch.object(m, '_calculate_error_rate', return_value=0.02), \
             patch.object(m, '_calculate_avg_response_time', return_value=0.0):
            await m._check_alerts()
        types = [a['type'] for a in m.alerts]
        assert 'error_rate_high' not in types


class TestCheckAlertsResponseTime:
    """_check_alerts response-time threshold trigger."""

    def _make_mon(self):
        from ipfs_datasets_py.mcp_server.monitoring import EnhancedMetricsCollector
        m = EnhancedMetricsCollector()
        m.alert_thresholds = {'cpu_percent': 80.0, 'memory_percent': 85.0,
                               'error_rate': 0.05, 'response_time_ms': 5000.0}
        m.alerts = []
        m.system_metrics = {'cpu_percent': 0.0, 'memory_percent': 0.0}
        return m

    @pytest.mark.asyncio
    async def test_response_time_above_threshold_triggers_warning(self):
        m = self._make_mon()
        with patch.object(m, '_calculate_error_rate', return_value=0.0), \
             patch.object(m, '_calculate_avg_response_time', return_value=8000.0):
            await m._check_alerts()
        types = [a['type'] for a in m.alerts]
        assert 'response_time_high' in types

    @pytest.mark.asyncio
    async def test_response_time_alert_severity_warning(self):
        m = self._make_mon()
        with patch.object(m, '_calculate_error_rate', return_value=0.0), \
             patch.object(m, '_calculate_avg_response_time', return_value=9000.0):
            await m._check_alerts()
        rt_alerts = [a for a in m.alerts if a['type'] == 'response_time_high']
        assert rt_alerts[0]['severity'] == 'warning'

    @pytest.mark.asyncio
    async def test_response_time_below_threshold_no_alert(self):
        m = self._make_mon()
        with patch.object(m, '_calculate_error_rate', return_value=0.0), \
             patch.object(m, '_calculate_avg_response_time', return_value=100.0):
            await m._check_alerts()
        types = [a['type'] for a in m.alerts]
        assert 'response_time_high' not in types


class TestCheckAlertsAllFour:
    """All four alerts fire simultaneously."""

    @pytest.mark.asyncio
    async def test_all_four_alerts_fire(self):
        from ipfs_datasets_py.mcp_server.monitoring import EnhancedMetricsCollector
        m = EnhancedMetricsCollector()
        m.alert_thresholds = {'cpu_percent': 80.0, 'memory_percent': 85.0,
                               'error_rate': 0.05, 'response_time_ms': 5000.0}
        m.alerts = []
        m.system_metrics = {'cpu_percent': 95.0, 'memory_percent': 92.0}
        with patch.object(m, '_calculate_error_rate', return_value=0.20), \
             patch.object(m, '_calculate_avg_response_time', return_value=9000.0):
            await m._check_alerts()
        types_set = {a['type'] for a in m.alerts}
        assert types_set == {'cpu_high', 'memory_high', 'error_rate_high', 'response_time_high'}

    @pytest.mark.asyncio
    async def test_no_alerts_when_all_healthy(self):
        from ipfs_datasets_py.mcp_server.monitoring import EnhancedMetricsCollector
        m = EnhancedMetricsCollector()
        m.alert_thresholds = {'cpu_percent': 80.0, 'memory_percent': 85.0,
                               'error_rate': 0.05, 'response_time_ms': 5000.0}
        m.alerts = []
        m.system_metrics = {'cpu_percent': 10.0, 'memory_percent': 20.0}
        with patch.object(m, '_calculate_error_rate', return_value=0.01), \
             patch.object(m, '_calculate_avg_response_time', return_value=50.0):
            await m._check_alerts()
        assert m.alerts == []


# ─────────────────────────── X82 ────────────────────────────

class TestP2PServiceManagerStop:
    """p2p_service_manager.stop() P2PServiceError + Exception paths."""

    def _make_mgr(self):
        import importlib
        mod = importlib.import_module(
            'ipfs_datasets_py.mcp_server.p2p_service_manager'
        )
        mgr = object.__new__(mod.P2PServiceManager)
        mgr._runtime = None
        mgr._env_backup = {}
        mgr._mcplusplus_available = False
        mgr._workflow_scheduler = None
        mgr._peer_registry = None
        mgr._has_advanced_features = False
        return mgr, mod

    def test_stop_returns_true_when_no_runtime(self):
        mgr, mod = self._make_mgr()
        assert mgr.stop() is True

    def test_stop_calls_cleanup_mcplusplus_first(self):
        mgr, mod = self._make_mgr()
        runtime = MagicMock()
        runtime.stop.return_value = True
        mgr._runtime = runtime
        with patch.object(mgr, '_cleanup_mcplusplus_features') as cleanup, \
             patch.object(mgr, '_restore_env'):
            mgr.stop()
        cleanup.assert_called_once()

    def test_stop_success_returns_true(self):
        mgr, mod = self._make_mgr()
        runtime = MagicMock()
        runtime.stop.return_value = True
        mgr._runtime = runtime
        with patch.object(mgr, '_cleanup_mcplusplus_features'), \
             patch.object(mgr, '_restore_env'):
            result = mgr.stop()
        assert result is True

    def test_stop_p2p_service_error_returns_false(self):
        mgr, mod = self._make_mgr()
        P2PServiceError = mod.P2PServiceError
        runtime = MagicMock()
        runtime.stop.side_effect = P2PServiceError("stop error")
        mgr._runtime = runtime
        with patch.object(mgr, '_cleanup_mcplusplus_features'), \
             patch.object(mgr, '_restore_env'):
            result = mgr.stop()
        assert result is False

    def test_stop_p2p_service_error_calls_restore_env(self):
        mgr, mod = self._make_mgr()
        P2PServiceError = mod.P2PServiceError
        runtime = MagicMock()
        runtime.stop.side_effect = P2PServiceError("stop error")
        mgr._runtime = runtime
        with patch.object(mgr, '_cleanup_mcplusplus_features'), \
             patch.object(mgr, '_restore_env') as restore:
            mgr.stop()
        restore.assert_called_once()

    def test_stop_generic_exception_returns_false(self):
        mgr, mod = self._make_mgr()
        runtime = MagicMock()
        runtime.stop.side_effect = RuntimeError("unexpected")
        mgr._runtime = runtime
        with patch.object(mgr, '_cleanup_mcplusplus_features'), \
             patch.object(mgr, '_restore_env'):
            result = mgr.stop()
        assert result is False

    def test_stop_generic_exception_calls_restore_env(self):
        mgr, mod = self._make_mgr()
        runtime = MagicMock()
        runtime.stop.side_effect = OSError("disk error")
        mgr._runtime = runtime
        with patch.object(mgr, '_cleanup_mcplusplus_features'), \
             patch.object(mgr, '_restore_env') as restore:
            mgr.stop()
        restore.assert_called_once()

    def test_stop_runtime_stop_false_returns_false(self):
        mgr, mod = self._make_mgr()
        runtime = MagicMock()
        runtime.stop.return_value = False
        mgr._runtime = runtime
        with patch.object(mgr, '_cleanup_mcplusplus_features'), \
             patch.object(mgr, '_restore_env'):
            result = mgr.stop()
        assert result is False
