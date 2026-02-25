"""Tests for query visualization module extraction."""

import pytest
import sys
from unittest.mock import Mock, MagicMock, patch

# Import the helper
from ipfs_datasets_py.optimizers.graphrag.query_visualization import QueryVisualizationHelper


class TestQueryVisualizationHelper:
    """Test visualization helper delegation methods."""

    def test_visualize_query_plan_no_visualizer(self):
        """Should handle missing visualizer gracefully."""
        result = QueryVisualizationHelper.visualize_query_plan(
            visualizer=None,
            metrics_collector=Mock(),
        )
        assert result is None

    def test_visualize_query_plan_no_metrics_collector(self):
        """Should handle missing metrics collector gracefully."""
        result = QueryVisualizationHelper.visualize_query_plan(
            visualizer=Mock(),
            metrics_collector=None,
        )
        assert result is None

    def test_visualize_query_plan_with_query_id(self):
        """Should retrieve metrics and delegate to visualizer."""
        metrics = {
            "phases": {"optimize": 0.5},
            "duration": 1.0,
            "params": {"query_type": "fact_verification"},
        }
        
        mock_visualizer = Mock()
        mock_visualizer.visualize_query_plan.return_value = Mock()
        
        mock_metrics_collector = Mock()
        mock_metrics_collector.get_query_metrics.return_value = metrics
        
        result = QueryVisualizationHelper.visualize_query_plan(
            visualizer=mock_visualizer,
            metrics_collector=mock_metrics_collector,
            query_id="query_123",
        )
        
        assert result is not None
        mock_metrics_collector.get_query_metrics.assert_called_once_with("query_123")
        mock_visualizer.visualize_query_plan.assert_called_once()

    def test_visualize_query_plan_missing_metrics(self):
        """Should return None if metrics not found."""
        mock_visualizer = Mock()
        mock_metrics_collector = Mock()
        mock_metrics_collector.get_query_metrics.return_value = None
        mock_metrics_collector.get_recent_metrics.return_value = []
        
        result = QueryVisualizationHelper.visualize_query_plan(
            visualizer=mock_visualizer,
            metrics_collector=mock_metrics_collector,
            query_id="nonexistent",
        )
        
        assert result is None

    def test_visualize_query_plan_uses_recent_query(self):
        """Should use most recent query ID if not specified."""
        metrics = {
            "phases": {},
            "duration": 1.0,
            "params": {},
        }
        
        mock_visualizer = Mock()
        mock_visualizer.visualize_query_plan.return_value = Mock()
        
        mock_metrics_collector = Mock()
        mock_metrics_collector.get_recent_metrics.return_value = [{"query_id": "recent_query"}]
        mock_metrics_collector.get_query_metrics.return_value = metrics
        
        result = QueryVisualizationHelper.visualize_query_plan(
            visualizer=mock_visualizer,
            metrics_collector=mock_metrics_collector,
            last_query_id=None,
        )
        
        assert result is not None
        mock_metrics_collector.get_recent_metrics.assert_called_once()

    def test_visualize_metrics_dashboard_no_visualizer(self):
        """Should handle missing visualizer gracefully."""
        result = QueryVisualizationHelper.visualize_metrics_dashboard(
            visualizer=None,
            metrics_collector=Mock(),
        )
        assert result is None

    def test_visualize_metrics_dashboard_creates_output_file(self):
        """Should generate default output file if not provided."""
        mock_visualizer = Mock()
        
        metrics_dir = "/tmp/metrics"
        mock_metrics_collector = Mock()
        mock_metrics_collector.metrics_dir = metrics_dir
        
        result = QueryVisualizationHelper.visualize_metrics_dashboard(
            visualizer=mock_visualizer,
            metrics_collector=mock_metrics_collector,
        )
        
        # Should have created a file path
        assert result is not None
        assert metrics_dir in result
        assert "dashboard_" in result
        mock_visualizer.export_dashboard_html.assert_called_once()

    def test_visualize_performance_comparison_no_visualizer(self):
        """Should handle missing visualizer gracefully."""
        result = QueryVisualizationHelper.visualize_performance_comparison(
            visualizer=None,
            metrics_collector=Mock(),
        )
        assert result is None

    def test_visualize_performance_comparison_uses_recent_queries(self):
        """Should use recent queries if IDs not specified."""
        mock_visualizer = Mock()
        mock_visualizer.visualize_performance_comparison.return_value = Mock()
        
        mock_metrics_collector = Mock()
        mock_metrics_collector.get_recent_metrics.return_value = [
            {"query_id": "q1"},
            {"query_id": "q2"},
            {"query_id": "q3"},
        ]
        
        result = QueryVisualizationHelper.visualize_performance_comparison(
            visualizer=mock_visualizer,
            metrics_collector=mock_metrics_collector,
        )
        
        assert result is not None
        mock_visualizer.visualize_performance_comparison.assert_called_once()
        call_kwargs = mock_visualizer.visualize_performance_comparison.call_args[1]
        assert call_kwargs["query_ids"] == ["q1", "q2", "q3"]

    def test_visualize_resource_usage_no_visualizer(self):
        """Should handle missing visualizer gracefully."""
        result = QueryVisualizationHelper.visualize_resource_usage(
            visualizer=None,
            metrics_collector=Mock(),
        )
        assert result is None

    def test_visualize_resource_usage_with_query_id(self):
        """Should delegate to visualizer with specified query ID."""
        mock_visualizer = Mock()
        mock_visualizer.visualize_resource_usage.return_value = Mock()
        
        mock_metrics_collector = Mock()
        
        result = QueryVisualizationHelper.visualize_resource_usage(
            visualizer=mock_visualizer,
            metrics_collector=mock_metrics_collector,
            query_id="query_456",
        )
        
        assert result is not None
        mock_visualizer.visualize_resource_usage.assert_called_once()
        call_kwargs = mock_visualizer.visualize_resource_usage.call_args[1]
        assert call_kwargs["query_id"] == "query_456"

    def test_visualize_query_patterns_no_visualizer(self):
        """Should handle missing visualizer gracefully."""
        result = QueryVisualizationHelper.visualize_query_patterns(
            visualizer=None,
        )
        assert result is None

    def test_visualize_query_patterns_with_limit(self):
        """Should delegate to visualizer with specified limit."""
        mock_visualizer = Mock()
        mock_visualizer.visualize_query_patterns.return_value = Mock()
        
        result = QueryVisualizationHelper.visualize_query_patterns(
            visualizer=mock_visualizer,
            limit=20,
        )
        
        assert result is not None
        call_kwargs = mock_visualizer.visualize_query_patterns.call_args[1]
        assert call_kwargs["limit"] == 20
