"""
Tests for TDFOL Performance Dashboard MCP Tool

Author: TDFOL Team
Date: 2026-02-19
"""

import json
import pytest
from unittest.mock import Mock, patch

from ipfs_datasets_py.mcp_server.tools.dashboard_tools import tdfol_performance_tool


class TestGetTDFOLMetrics:
    """Tests for get_tdfol_metrics tool."""
    
    def test_get_metrics_success(self):
        """GIVEN dashboard with metrics WHEN get_tdfol_metrics called THEN returns data"""
        with patch.object(tdfol_performance_tool, 'TDFOL_AVAILABLE', True):
            with patch.object(tdfol_performance_tool, '_get_dashboard') as mock_dashboard:
                with patch.object(tdfol_performance_tool, '_get_collector') as mock_collector:
                    dashboard_mock = Mock()
                    dashboard_mock.get_statistics.return_value = {'total_proofs': 100}
                    dashboard_mock.proof_metrics = [Mock()] * 100
                    dashboard_mock.get_uptime.return_value = 3600
                    mock_dashboard.return_value = dashboard_mock
                    
                    collector_mock = Mock()
                    collector_mock.get_statistics.return_value = {
                        'timing': {}, 'memory': {}, 'counters': {}, 'gauges': {}, 'histograms': {}
                    }
                    collector_mock.get_uptime.return_value = 3600
                    mock_collector.return_value = collector_mock
                    
                    result = tdfol_performance_tool.get_tdfol_metrics()
                    
                    assert 'dashboard_stats' in result
                    assert 'collector_stats' in result
    
    def test_get_metrics_not_available(self):
        """GIVEN TDFOL unavailable WHEN called THEN returns error"""
        with patch.object(tdfol_performance_tool, 'TDFOL_AVAILABLE', False):
            result = tdfol_performance_tool.get_tdfol_metrics()
            assert 'error' in result


class TestProfileOperation:
    """Tests for profile_tdfol_operation tool."""
    
    def test_profile_success(self):
        """GIVEN valid formula WHEN profile_tdfol_operation called THEN returns timing"""
        with patch.object(tdfol_performance_tool, 'TDFOL_AVAILABLE', True):
            with patch.object(tdfol_performance_tool, '_get_profiler') as mock_profiler:
                with patch('ipfs_datasets_py.mcp_server.tools.dashboard_tools.tdfol_performance_tool.TDFOLParser'):
                    with patch('ipfs_datasets_py.mcp_server.tools.dashboard_tools.tdfol_performance_tool.TDFOLProver'):
                        stats_mock = Mock()
                        stats_mock.mean_time_ms = 45.2
                        stats_mock.median_time = 0.043
                        stats_mock.min_time = 0.040
                        stats_mock.max_time = 0.050
                        stats_mock.std_dev = 0.003
                        stats_mock.total_time = 0.452
                        stats_mock.calls_per_run = 100.0
                        stats_mock.meets_threshold = True
                        stats_mock.function_name = "prove"
                        stats_mock.profile_data = None
                        
                        profiler_mock = Mock()
                        profiler_mock.profile_prover.return_value = stats_mock
                        profiler_mock.identify_bottlenecks.return_value = []
                        mock_profiler.return_value = profiler_mock
                        
                        result = tdfol_performance_tool.profile_tdfol_operation("P → Q", runs=10)
                        
                        assert 'timing' in result
                        assert result['timing']['mean_time_ms'] == 45.2


class TestExportStatistics:
    """Tests for export_tdfol_statistics tool."""
    
    def test_export_json(self):
        """GIVEN stats WHEN export as json THEN returns valid JSON"""
        with patch.object(tdfol_performance_tool, 'TDFOL_AVAILABLE', True):
            with patch.object(tdfol_performance_tool, '_get_dashboard') as mock_dash:
                with patch.object(tdfol_performance_tool, '_get_collector') as mock_coll:
                    dashboard_mock = Mock()
                    dashboard_mock.start_time = 12345.0
                    dashboard_mock.get_uptime.return_value = 3600
                    dashboard_mock.get_statistics.return_value = {}
                    mock_dash.return_value = dashboard_mock
                    
                    collector_mock = Mock()
                    collector_mock.export_dict.return_value = {}
                    mock_coll.return_value = collector_mock
                    
                    result = tdfol_performance_tool.export_tdfol_statistics(format="json")
                    
                    assert 'json_string' in result
                    json.loads(result['json_string'])  # Validate JSON


class TestCompareStrategies:
    """Tests for compare_tdfol_strategies tool."""
    
    def test_compare_finds_best(self):
        """GIVEN multiple strategies WHEN compared THEN identifies best"""
        with patch.object(tdfol_performance_tool, 'TDFOL_AVAILABLE', True):
            with patch.object(tdfol_performance_tool, 'profile_tdfol_operation') as mock_profile:
                def profile_se(*args, **kwargs):
                    s = kwargs.get('strategy')
                    return {'timing': {'mean_time_ms': 30.0 if s == 'modal' else 50.0}}
                
                mock_profile.side_effect = profile_se
                
                result = tdfol_performance_tool.compare_tdfol_strategies(
                    formula_str="P",
                    strategies=['forward', 'modal']
                )
                
                assert result['best_strategy']['name'] == 'modal'


class TestRegressionCheck:
    """Tests for check_tdfol_performance_regression tool."""
    
    def test_no_regression(self):
        """GIVEN performance within threshold WHEN checked THEN no regression"""
        with patch.object(tdfol_performance_tool, 'TDFOL_AVAILABLE', True):
            with patch.object(tdfol_performance_tool, '_get_profiler') as mock_prof:
                with patch.object(tdfol_performance_tool, '_get_collector') as mock_coll:
                    prof_mock = Mock()
                    prof_mock.baseline = {'prove': 45.0}
                    mock_prof.return_value = prof_mock
                    
                    coll_mock = Mock()
                    coll_mock.get_statistics.return_value = {
                        'timing': {'prove': {'mean': 44.0}}
                    }
                    mock_coll.return_value = coll_mock
                    
                    result = tdfol_performance_tool.check_tdfol_performance_regression()
                    
                    assert result['regressions_found'] is False


class TestResetMetrics:
    """Tests for reset_tdfol_metrics tool."""
    
    def test_reset_success(self):
        """GIVEN metrics exist WHEN reset called THEN clears metrics"""
        with patch.object(tdfol_performance_tool, 'TDFOL_AVAILABLE', True):
            with patch('ipfs_datasets_py.mcp_server.tools.dashboard_tools.tdfol_performance_tool.PerformanceDashboard'):
                with patch('ipfs_datasets_py.mcp_server.tools.dashboard_tools.tdfol_performance_tool.reset_global_collector'):
                    with patch.object(tdfol_performance_tool, 'get_global_collector'):
                        old_dash = Mock()
                        old_dash.proof_metrics = [Mock()] * 50
                        tdfol_performance_tool._dashboard = old_dash
                        
                        result = tdfol_performance_tool.reset_tdfol_metrics()
                        
                        assert result['success'] is True
                        assert result['metrics_cleared'] == 50


class TestToolRegistration:
    """Tests for tool registration."""
    
    def test_get_tools_count(self):
        """GIVEN tool module WHEN get_tools called THEN returns 8 tools"""
        tools = tdfol_performance_tool.get_tools()
        assert len(tools) == 8
        
        for tool in tools:
            assert 'name' in tool
            assert 'function' in tool
            assert tool['category'] == 'dashboard_tools'


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
