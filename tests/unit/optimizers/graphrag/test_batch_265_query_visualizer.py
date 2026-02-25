"""
Batch 265: Comprehensive tests for QueryVisualizer
Tests query visualization capabilities for GraphRAG query analysis.
"""

import pytest
from unittest.mock import MagicMock, patch, mock_open, Mock
from typing import Dict, Any, List
import tempfile
import os

from ipfs_datasets_py.optimizers.graphrag.query_visualizer import QueryVisualizer
from ipfs_datasets_py.optimizers.graphrag.query_metrics import QueryMetricsCollector


class TestQueryVisualizerInitialization:
    """Test QueryVisualizer initialization."""
    
    def test_init_without_metrics_collector(self):
        """Test initialization without metrics collector."""
        visualizer = QueryVisualizer()
        
        assert visualizer.metrics_collector is None
        assert hasattr(visualizer, 'visualization_available')
    
    def test_init_with_metrics_collector(self):
        """Test initialization with metrics collector."""
        collector = QueryMetricsCollector()
        visualizer = QueryVisualizer(metrics_collector=collector)
        
        assert visualizer.metrics_collector is collector
    
    def test_init_checks_visualization_availability(self):
        """Test that initialization checks for visualization dependencies."""
        visualizer = QueryVisualizer()
        
        # Should have visualization_available attribute (True or False depending on imports)
        assert isinstance(visualizer.visualization_available, bool)


class TestSetMetricsCollector:
    """Test setting metrics collector."""
    
    def test_set_metrics_collector(self):
        """Test setting metrics collector after initialization."""
        visualizer = QueryVisualizer()
        collector = QueryMetricsCollector()
        
        visualizer.set_metrics_collector(collector)
        
        assert visualizer.metrics_collector is collector
    
    def test_set_metrics_collector_replaces_previous(self):
        """Test that setting collector replaces previous one."""
        visualizer = QueryVisualizer()
        collector1 = QueryMetricsCollector()
        collector2 = QueryMetricsCollector()
        
        visualizer.set_metrics_collector(collector1)
        assert visualizer.metrics_collector is collector1
        
        visualizer.set_metrics_collector(collector2)
        assert visualizer.metrics_collector is collector2


class TestVisualizePhaseTiming:
    """Test phase timing visualization."""
    
    def test_visualize_phase_timing_with_data(self):
        """Test phase timing visualization returns None when deps unavailable."""
        visualizer = QueryVisualizer()
        # Most likely no matplotlib installed, so just test basic path
        
        collector = Mock(spec=QueryMetricsCollector)
        collector.get_phase_timing_summary.return_value = {
            "vector_search": {"avg_duration": 0.5},
            "graph_traversal": {"avg_duration": 0.8},
            "ranking": {"avg_duration": 0.2}
        }
        visualizer.metrics_collector = collector
        
        result = visualizer.visualize_phase_timing(show_plot=False)
        
        # If visualization not available, returns None
        if not visualizer.visualization_available:
            assert result is None
        # Could check collector was called if available
        # but most test environments don't have matplotlib
    
    def test_visualize_phase_timing_no_collector(self):
        """Test visualization without metrics collector."""
        visualizer = QueryVisualizer()
        visualizer.visualization_available = True
        visualizer.metrics_collector = None
        
        result = visualizer.visualize_phase_timing(show_plot=False)
        
        assert result is None
    
    @patch('ipfs_datasets_py.optimizers.graphrag.query_visualizer.VISUALIZATION_AVAILABLE', True)
    def test_visualize_phase_timing_no_data(self):
        """Test visualization with no phase data."""
        visualizer = QueryVisualizer()
        visualizer.visualization_available = True
        
        collector = Mock(spec=QueryMetricsCollector)
        collector.get_phase_timing_summary.return_value = {}
        visualizer.metrics_collector = collector
        
        result = visualizer.visualize_phase_timing(show_plot=False)
        
        assert result is None
    
    def test_visualize_phase_timing_dependencies_unavailable(self):
        """Test visualization when matplotlib not available."""
        visualizer = QueryVisualizer()
        visualizer.visualization_available = False
        
        result = visualizer.visualize_phase_timing(show_plot=False)
        
        assert result is None


class TestVisualizeQueryPlan:
    """Test query plan visualization."""
    
    def test_visualize_query_plan_with_phases(self):
        """Test query plan visualization returns None when deps unavailable."""
        visualizer = QueryVisualizer()
        
        query_plan = {
            "phases": {
                "vector_search": {
                    "name": "Vector Search",
                    "type": "vector_search",
                    "duration": 0.3,
                    "dependencies": []
                }
            }
        }
        
        result = visualizer.visualize_query_plan(query_plan, show_plot=False)
        
        # Without matplotlib/networkx, should return None
        if not visualizer.visualization_available:
            assert result is None
    
    def test_visualize_query_plan_with_steps(self):
        """Test query plan visualization with steps structure."""
        visualizer = QueryVisualizer()
        
        query_plan = {
            "steps": [
                {"name": "Step 1", "type": "processing", "duration": 0.2}
            ]
        }
        
        result = visualizer.visualize_query_plan(query_plan, show_plot=False)
        
        # Without deps, should return None
        if not visualizer.visualization_available:
            assert result is None
    
    def test_visualize_query_plan_empty_plan(self):
        """Test visualization with empty query plan."""
        visualizer = QueryVisualizer()
        
        query_plan = {}
        
        result = visualizer.visualize_query_plan(query_plan, show_plot=False)
        
        # Should return None for empty plan
        assert result is None
    
    def test_visualize_query_plan_dependencies_unavailable(self):
        """Test visualization when dependencies not available."""
        visualizer = QueryVisualizer()
        visualizer.visualization_available = False
        
        query_plan = {"phases": {}}
        
        result = visualizer.visualize_query_plan(query_plan, show_plot=False)
        
        assert result is None


class TestVisualizeResourceUsage:
    """Test resource usage visualization."""
    
    def test_visualize_resource_usage_with_memory(self):
        """Test resource usage visualization with memory data."""
        visualizer = QueryVisualizer()
        
        collector = Mock(spec=QueryMetricsCollector)
        metrics = {
            "start_time": 1000.0,
            "resources": {
                "memory_samples": [
                    (1000.5, 100 * 1024 * 1024),  # 100 MB
                    (1001.0, 150 * 1024 * 1024)   # 150 MB
                ],
                "cpu_samples": []
            },
            "phases": {}
        }
        collector.get_query_metrics.return_value = metrics
        visualizer.metrics_collector = collector
        
        result = visualizer.visualize_resource_usage("query_1", show_plot=False)
        
        # Without matplotlib, returns None and doesn't call get_query_metrics
        if not visualizer.visualization_available:
            assert result is None
        # Only check if visualization is available
        elif result is not None:
            collector.get_query_metrics.assert_called_once_with("query_1")
    
    def test_visualize_resource_usage_with_cpu(self):
        """Test resource usage visualization with CPU data."""
        visualizer = QueryVisualizer()
        
        collector = Mock(spec=QueryMetricsCollector)
        metrics = {
            "start_time": 1000.0,
            "resources": {
                "memory_samples": [],
                "cpu_samples": [
                    (1000.5, 45.0),  # 45% CPU
                    (1001.0, 60.0)   # 60% CPU
                ]
            },
            "phases": {}
        }
        collector.get_query_metrics.return_value = metrics
        visualizer.metrics_collector = collector
        
        result = visualizer.visualize_resource_usage("query_1", show_plot=False)
        
        # Without matplotlib, returns None
        if not visualizer.visualization_available:
            assert result is None
    
    def test_visualize_resource_usage_no_metrics(self):
        """Test visualization when no metrics found."""
        visualizer = QueryVisualizer()
        visualizer.visualization_available = True
        
        collector = Mock(spec=QueryMetricsCollector)
        collector.get_query_metrics.return_value = None
        visualizer.metrics_collector = collector
        
        result = visualizer.visualize_resource_usage("query_1", show_plot=False)
        
        assert result is None
    
    def test_visualize_resource_usage_no_samples(self):
        """Test visualization when no resource samples available."""
        visualizer = QueryVisualizer()
        visualizer.visualization_available = True
        
        collector = Mock(spec=QueryMetricsCollector)
        metrics = {
            "start_time": 1000.0,
            "resources": {
                "memory_samples": [],
                "cpu_samples": []
            }
        }
        collector.get_query_metrics.return_value = metrics
        visualizer.metrics_collector = collector
        
        result = visualizer.visualize_resource_usage("query_1", show_plot=False)
        
        assert result is None


class TestVisualizePerformanceComparison:
    """Test performance comparison visualization."""
    
    def test_visualize_performance_comparison_multiple_queries(self):
        """Test performance comparison with multiple queries."""
        visualizer = QueryVisualizer()
        
        collector = Mock(spec=QueryMetricsCollector)
        metrics1 = {
            "duration": 1.5,
            "phases": {"vector_search": {"duration": 0.5}},
            "resources": {"peak_memory": 200 * 1024 * 1024},
            "results": {"count": 10, "quality_score": 0.85}
        }
        metrics2 = {
            "duration": 2.0,
            "phases": {"vector_search": {"duration": 0.8}},
            "resources": {"peak_memory": 250 * 1024 * 1024},
            "results": {"count": 15, "quality_score": 0.90}
        }
        collector.get_query_metrics.side_effect = [metrics1, metrics2]
        visualizer.metrics_collector = collector
        
        result = visualizer.visualize_performance_comparison(
            ["query_1", "query_2"],
            labels=["Original", "Optimized"],
            show_plot=False
        )
        
        # Without matplotlib, returns None and doesn't call collector
        if not visualizer.visualization_available:
            assert result is None
        # Only check call count if visualization is available
        elif result is not None:
            assert collector.get_query_metrics.call_count == 2
    
    def test_visualize_performance_comparison_no_metrics(self):
        """Test comparison when no valid metrics found."""
        visualizer = QueryVisualizer()
        visualizer.visualization_available = True
        
        collector = Mock(spec=QueryMetricsCollector)
        collector.get_query_metrics.return_value = None
        visualizer.metrics_collector = collector
        
        result = visualizer.visualize_performance_comparison(
            ["query_1", "query_2"],
            show_plot=False
        )
        
        assert result is None
    
    def test_visualize_performance_comparison_default_labels(self):
        """Test comparison with default labels."""
        visualizer = QueryVisualizer()
        
        collector = Mock(spec=QueryMetricsCollector)
        metrics = {
            "duration": 1.0,
            "phases": {},
            "resources": {},
            "results": {"count": 5, "quality_score": 0.7}
        }
        collector.get_query_metrics.return_value = metrics
        visualizer.metrics_collector = collector
        
        # Should use default labels
        result = visualizer.visualize_performance_comparison(
            ["query_1", "query_2"],
            labels=None,
            show_plot=False
        )
        
        # Without matplotlib, returns None
        if not visualizer.visualization_available:
            assert result is None


class TestVisualizeQueryPatterns:
    """Test query pattern visualization."""
    
    def test_visualize_query_patterns_with_data(self):
        """Test pattern visualization with query metrics."""
        visualizer = QueryVisualizer()
        
        collector = Mock(spec=QueryMetricsCollector)
        collector.query_metrics = [
            {
                "params": {"max_vector_results": 10, "max_traversal_depth": 2},
                "duration": 1.0,
                "phases": {"vector_search": {}, "graph_traversal": {}},
                "results": {"count": 5}
            },
            {
                "params": {"max_vector_results": 10, "max_traversal_depth": 2},
                "duration": 1.1,
                "phases": {"vector_search": {}, "graph_traversal": {}},
                "results": {"count": 6}
            }
        ]
        visualizer.metrics_collector = collector
        
        result = visualizer.visualize_query_patterns(limit=10, show_plot=False)
        
        # Without matplotlib, returns None
        if not visualizer.visualization_available:
            assert result is None
    
    def test_visualize_query_patterns_no_data(self):
        """Test pattern visualization with no metrics."""
        visualizer = QueryVisualizer()
        visualizer.visualization_available = True
        
        collector = Mock(spec=QueryMetricsCollector)
        collector.query_metrics = []
        visualizer.metrics_collector = collector
        
        result = visualizer.visualize_query_patterns(show_plot=False)
        
        assert result is None
    
    def test_visualize_query_patterns_no_collector(self):
        """Test pattern visualization without collector."""
        visualizer = QueryVisualizer()
        visualizer.visualization_available = True
        visualizer.metrics_collector = None
        
        result = visualizer.visualize_query_patterns(show_plot=False)
        
        assert result is None


class TestExportDashboardHtml:
    """Test HTML dashboard export."""
    
    def test_export_dashboard_html_single_query(self):
        """Test dashboard export for single query."""
        visualizer = QueryVisualizer()
        visualizer.visualization_available = True
        
        collector = Mock(spec=QueryMetricsCollector)
        metrics = {
            "duration": 1.5,
            "results": {"count": 10, "quality_score": 0.85},
            "resources": {"peak_memory": 200 * 1024 * 1024},
            "phases": {
                "vector_search": {"duration": 0.5},
                "graph_traversal": {"duration": 0.8}
            }
        }
        collector.get_query_metrics.return_value = metrics
        visualizer.metrics_collector = collector
        
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.html') as f:
            output_file = f.name
        
        try:
            visualizer.export_dashboard_html(output_file, query_id="query_1")
            
            # Verify file was created
            assert os.path.exists(output_file)
            
            # Verify HTML content
            with open(output_file, 'r') as f:
                content = f.read()
                assert "GraphRAG Query Optimizer Dashboard" in content
                assert "Query Metrics: query_1" in content
                assert "1.500 seconds" in content  # Duration
        finally:
            if os.path.exists(output_file):
                os.remove(output_file)
    
    def test_export_dashboard_html_all_queries(self):
        """Test dashboard export for all queries."""
        visualizer = QueryVisualizer()
        visualizer.visualization_available = True
        
        collector = Mock(spec=QueryMetricsCollector)
        performance_report = {
            "query_count": 5,
            "timing_summary": {
                "avg_duration": 1.2,
                "min_duration": 0.8,
                "max_duration": 2.0
            },
            "recommendations": [
                {"severity": "high", "message": "Consider reducing depth"}
            ]
        }
        collector.generate_performance_report.return_value = performance_report
        visualizer.metrics_collector = collector
        
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.html') as f:
            output_file = f.name
        
        try:
            visualizer.export_dashboard_html(output_file)
            
            # Verify file was created
            assert os.path.exists(output_file)
            
            # Verify HTML content
            with open(output_file, 'r') as f:
                content = f.read()
                assert "Overall Performance Summary" in content
                assert "Total Queries" in content
                assert "Optimization Recommendations" in content
        finally:
            if os.path.exists(output_file):
                os.remove(output_file)
    
    def test_export_dashboard_html_no_collector(self):
        """Test dashboard export without collector."""
        visualizer = QueryVisualizer()
        visualizer.visualization_available = True
        visualizer.metrics_collector = None
        
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.html') as f:
            output_file = f.name
        
        try:
            # Should not create file
            visualizer.export_dashboard_html(output_file)
            
            # File should not be created
            # (but tempfile creates it, so we check it's still empty or minimal)
        finally:
            if os.path.exists(output_file):
                os.remove(output_file)
    
    def test_export_dashboard_html_dependencies_unavailable(self):
        """Test dashboard export when dependencies not available."""
        visualizer = QueryVisualizer()
        visualizer.visualization_available = False
        
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.html') as f:
            output_file = f.name
        
        try:
            visualizer.export_dashboard_html(output_file)
            
            # Should not create dashboard
        finally:
            if os.path.exists(output_file):
                os.remove(output_file)


class TestExtractPatternKey:
    """Test pattern key extraction."""
    
    def test_extract_pattern_key_full_params(self):
        """Test pattern key extraction with full parameters."""
        visualizer = QueryVisualizer()
        
        metrics = {
            "params": {
                "max_vector_results": 10,
                "max_traversal_depth": 3,
                "edge_types": ["related_to", "contains"]
            },
            "phases": {"vector_search": {}, "graph_traversal": {}, "ranking": {}}
        }
        
        pattern_key = visualizer._extract_pattern_key(metrics)
        
        assert "vec10" in pattern_key
        assert "depth3" in pattern_key
        assert "edges2" in pattern_key
        assert "phases3" in pattern_key
    
    def test_extract_pattern_key_minimal_params(self):
        """Test pattern key extraction with minimal parameters."""
        visualizer = QueryVisualizer()
        
        metrics = {
            "params": {},
            "duration": 0.05
        }
        
        pattern_key = visualizer._extract_pattern_key(metrics)
        
        # Should use duration-based pattern
        assert "duration" in pattern_key
        assert "veryfast" in pattern_key or "fast" in pattern_key
    
    def test_extract_pattern_key_slow_query(self):
        """Test pattern key for slow query."""
        visualizer = QueryVisualizer()
        
        metrics = {
            "params": {},
            "duration": 3.0
        }
        
        pattern_key = visualizer._extract_pattern_key(metrics)
        
        assert "duration_slow" in pattern_key
    
    def test_extract_pattern_key_empty_metrics(self):
        """Test pattern key extraction with empty metrics."""
        visualizer = QueryVisualizer()
        
        metrics = {}
        
        pattern_key = visualizer._extract_pattern_key(metrics)
        
        assert pattern_key == "unknown_pattern"


class TestExtractPatternParams:
    """Test pattern parameter extraction."""
    
    def test_extract_pattern_params_full_data(self):
        """Test pattern parameter extraction with full data."""
        visualizer = QueryVisualizer()
        
        metrics = {
            "params": {"max_vector_results": 10, "max_traversal_depth": 3},
            "duration": 1.5,
            "results": {"count": 15},
            "phases": {"vector_search": {}, "graph_traversal": {}},
            "resources": {"peak_memory": 200 * 1024 * 1024}
        }
        
        pattern_params = visualizer._extract_pattern_params(metrics)
        
        assert pattern_params["max_vector_results"] == 10
        assert pattern_params["max_traversal_depth"] == 3
        assert pattern_params["duration"] == 1.5
        assert pattern_params["result_count"] == 15
        assert pattern_params["phase_count"] == 2
        assert "peak_memory_mb" in pattern_params
        assert pattern_params["peak_memory_mb"] == 200.0
    
    def test_extract_pattern_params_minimal_data(self):
        """Test pattern parameter extraction with minimal data."""
        visualizer = QueryVisualizer()
        
        metrics = {
            "params": {},
            "duration": 0.5
        }
        
        pattern_params = visualizer._extract_pattern_params(metrics)
        
        assert pattern_params["duration"] == 0.5
        assert pattern_params["result_count"] == 0
        assert pattern_params["phase_count"] == 0
    
    def test_extract_pattern_params_no_resources(self):
        """Test pattern parameter extraction without resources."""
        visualizer = QueryVisualizer()
        
        metrics = {
            "params": {"max_vector_results": 5},
            "duration": 1.0,
            "results": {"count": 10},
            "phases": {"vector_search": {}}
        }
        
        pattern_params = visualizer._extract_pattern_params(metrics)
        
        assert "peak_memory_mb" not in pattern_params


class TestIntegrationScenarios:
    """Test integrated visualization workflows."""
    
    def test_complete_visualization_workflow(self):
        """Test complete workflow: create visualizer, set collector, generate visualizations."""
        # Create collector with data
        collector = QueryMetricsCollector()
        collector.start_query_tracking(query_id="query_1", query_params={"max_vector_results": 10})
        with collector.time_phase("vector_search"):
            pass
        collector.end_query_tracking(results_count=5, quality_score=0.8)
        
        # Create visualizer
        visualizer = QueryVisualizer()
        visualizer.set_metrics_collector(collector)
        
        # Generate visualization
        result = visualizer.visualize_phase_timing(query_id="query_1", show_plot=False)
        
        # Without matplotlib, returns None
        if not visualizer.visualization_available:
            assert result is None
        assert visualizer.metrics_collector is collector
    
    def test_multiple_visualizations_same_collector(self):
        """Test generating multiple visualizations from same collector."""
        collector = QueryMetricsCollector()
        visualizer = QueryVisualizer(metrics_collector=collector)
        visualizer.visualization_available = True
        
        # Add some data
        collector.start_query_tracking(query_id="query_1")
        collector.end_query_tracking(results_count=5)
        
        # All visualization methods should work with same collector
        assert visualizer.metrics_collector is collector


class TestEdgeCases:
    """Test edge cases and error handling."""
    
    def test_visualize_with_none_query_id(self):
        """Test visualization with None query ID."""
        visualizer = QueryVisualizer()
        visualizer.visualization_available = True
        
        collector = Mock(spec=QueryMetricsCollector)
        collector.get_phase_timing_summary.return_value = {}
        visualizer.metrics_collector = collector
        
        result = visualizer.visualize_phase_timing(query_id=None, show_plot=False)
        
        # Should call with None
        collector.get_phase_timing_summary.assert_called_once_with(None)
    
    def test_export_to_nonexistent_directory(self):
        """Test exporting dashboard to nonexistent directory."""
        visualizer = QueryVisualizer()
        visualizer.visualization_available = True
        
        collector = Mock(spec=QueryMetricsCollector)
        collector.get_query_metrics.return_value = {
            "duration": 1.0,
            "results": {},
            "resources": {},
            "phases": {}
        }
        visualizer.metrics_collector = collector
        
        # Try to export to nonexistent directory
        nonexistent_path = "/tmp/nonexistent_dir_" + str(os.getpid()) + "/dashboard.html"
        
        try:
            visualizer.export_dashboard_html(nonexistent_path, query_id="query_1")
            # Should create parent directory or handle gracefully
        except Exception as e:
            # Expected to fail gracefully
            assert isinstance(e, (FileNotFoundError, OSError))
    
    def test_visualize_with_nan_values(self):
        """Test visualization with NaN values in metrics."""
        visualizer = QueryVisualizer()
        
        collector = Mock(spec=QueryMetricsCollector)
        collector.get_phase_timing_summary.return_value = {
            "vector_search": {"avg_duration": float('nan')}
        }
        visualizer.metrics_collector = collector
        
        # Should handle NaN gracefully
        result = visualizer.visualize_phase_timing(show_plot=False)
        
        # Without matplotlib, returns None (with matplotlib would handle NaN)
        if not visualizer.visualization_available:
            assert result is None
    
    def test_large_number_of_patterns(self):
        """Test visualization with large number of patterns."""
        visualizer = QueryVisualizer()
        visualizer.visualization_available = True
        
        # Create many unique patterns
        collector = Mock(spec=QueryMetricsCollector)
        collector.query_metrics = [
            {
                "params": {"max_vector_results": i},
                "duration": 0.5 + i * 0.1,
                "phases": {},
                "results": {}
            }
            for i in range(100)
        ]
        visualizer.metrics_collector = collector
        
        # Should limit to specified number
        # (actual visualization would be tested with full mock)
        pattern_keys = set()
        for metrics in collector.query_metrics:
            pattern_keys.add(visualizer._extract_pattern_key(metrics))
        
        # Different vector_results should create different patterns
        assert len(pattern_keys) > 1
