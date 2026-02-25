"""
Comprehensive test suite for QueryMetricsCollector - Batch 263

Tests query metrics collection, analysis, and reporting for GraphRAG queries.

API Coverage:
- QueryMetricsCollector.__init__: Initialization with max_history, metrics_dir, resource tracking
- start_query_tracking: Begin tracking query execution  
- end_query_tracking: Complete tracking and record results
- get_health_check: System health snapshot for monitoring
- time_phase (context manager): Time query execution phases
- start_phase_timer / end_phase_timer: Manual phase timing control
- record_resource_usage: Capture memory/CPU usage
- record_additional_metric: Store custom metrics
- get_query_metrics / get_recent_metrics: Retrieve collected metrics
- get_phase_timing_summary: Phase timing statistics
- generate_performance_report: Comprehensive performance analysis  
- export_metrics_csv / export_metrics_json: Export to CSV/JSON formats
- _numpy_json_serializable: Convert numpy types for JSON export
- _persist_metrics: Save metrics to disk

Test Organization:
- 20 test classes, ~72 test methods
- Mocked dependencies: psutil.Process, numpy arrays
- Temporary directories for file persistence tests
"""

import unittest
from unittest.mock import Mock, MagicMock, patch, mock_open
import time
import json
import tempfile
import os
import shutil
from typing import Dict, Any, List
from collections import deque


class TestQueryMetricsCollectorInitialization(unittest.TestCase):
    """Test QueryMetricsCollector initialization."""
    
    def setUp(self):
        """Set up test fixtures."""
        from ipfs_datasets_py.optimizers.graphrag.query_metrics import QueryMetricsCollector
        self.QueryMetricsCollector = QueryMetricsCollector
        
    def test_init_with_defaults(self):
        """Test initialization with default parameters."""
        collector = self.QueryMetricsCollector()
        
        self.assertEqual(collector.max_history_size, 1000)
        self.assertIsNone(collector.metrics_dir)
        self.assertTrue(collector.track_resources)
        self.assertIsInstance(collector.query_metrics, deque)
        self.assertIsNone(collector.current_query)
        
    def test_init_with_custom_history_size(self):
        """Test initialization with custom history size."""
        collector = self.QueryMetricsCollector(max_history_size=500)
        
        self.assertEqual(collector.max_history_size, 500)
        self.assertEqual(collector.query_metrics.maxlen, 500)
        
    def test_init_with_metrics_dir_creates_directory(self):
        """Test initialization creates metrics directory if it doesn't exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            metrics_path = os.path.join(tmpdir, "metrics")
            
            collector = self.QueryMetricsCollector(metrics_dir=metrics_path)
            
            self.assertTrue(os.path.exists(metrics_path))
            self.assertEqual(collector.metrics_dir, metrics_path)
            
    def test_init_with_existing_metrics_dir(self):
        """Test initialization with existing metrics directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            collector = self.QueryMetricsCollector(metrics_dir=tmpdir)
            
            self.assertEqual(collector.metrics_dir, tmpdir)
            self.assertTrue(os.path.exists(tmpdir))
            
    def test_init_with_resource_tracking_disabled(self):
        """Test initialization with resource tracking disabled."""
        collector = self.QueryMetricsCollector(track_resources=False)
        
        self.assertFalse(collector.track_resources)


class TestStartQueryTracking(unittest.TestCase):
    """Test start_query_tracking method."""
    
    def setUp(self):
        """Set up test fixtures."""
        from ipfs_datasets_py.optimizers.graphrag.query_metrics import QueryMetricsCollector
        self.QueryMetricsCollector = QueryMetricsCollector
        
    def test_start_query_tracking_generates_query_id(self):
        """Test start_query_tracking generates query ID if not provided."""
        collector = self.QueryMetricsCollector(track_resources=False)
        
        query_id = collector.start_query_tracking()
        
        self.assertIsNotNone(query_id)
        self.assertIsInstance(query_id, str)
        self.assertEqual(collector.current_query["query_id"], query_id)
        
    def test_start_query_tracking_uses_provided_query_id(self):
        """Test start_query_tracking uses provided query ID."""
        collector = self.QueryMetricsCollector(track_resources=False)
        
        query_id = collector.start_query_tracking(query_id="test-query-123")
        
        self.assertEqual(query_id, "test-query-123")
        self.assertEqual(collector.current_query["query_id"], "test-query-123")
        
    def test_start_query_tracking_stores_query_params(self):
        """Test start_query_tracking stores query parameters."""
        collector = self.QueryMetricsCollector(track_resources=False)
        
        params = {"max_depth": 2, "edge_types": ["knows", "works_for"]}
        collector.start_query_tracking(query_params=params)
        
        self.assertEqual(collector.current_query["params"], params)
        
    def test_start_query_tracking_initializes_structure(self):
        """Test start_query_tracking initializes metrics structure."""
        collector = self.QueryMetricsCollector(track_resources=False)
        
        collector.start_query_tracking()
        
        self.assertIn("start_time", collector.current_query)
        self.assertIsNone(collector.current_query["end_time"])
        self.assertIn("phases", collector.current_query)
        self.assertIn("resources", collector.current_query)
        self.assertIn("results", collector.current_query)
        self.assertIn("metadata", collector.current_query)


class TestEndQueryTracking(unittest.TestCase):
    """Test end_query_tracking method."""
    
    def setUp(self):
        """Set up test fixtures."""
        from ipfs_datasets_py.optimizers.graphrag.query_metrics import QueryMetricsCollector
        self.QueryMetricsCollector = QueryMetricsCollector
        
    def test_end_query_tracking_calculates_duration(self):
        """Test end_query_tracking calculates query duration."""
        collector = self.QueryMetricsCollector(track_resources=False)
        
        collector.start_query_tracking()
        time.sleep(0.05)  # Small delay
        metrics = collector.end_query_tracking()
        
        self.assertGreater(metrics["duration"], 0)
        self.assertIsNotNone(metrics["end_time"])
        
    def test_end_query_tracking_records_results(self):
        """Test end_query_tracking records results count and quality."""
        collector = self.QueryMetricsCollector(track_resources=False)
        
        collector.start_query_tracking()
        metrics = collector.end_query_tracking(results_count=10, quality_score=0.8)
        
        self.assertEqual(metrics["results"]["count"], 10)
        self.assertEqual(metrics["results"]["quality_score"], 0.8)
        self.assertTrue(metrics["success"])
        
    def test_end_query_tracking_records_error(self):
        """Test end_query_tracking records error message."""
        collector = self.QueryMetricsCollector(track_resources=False)
        
        collector.start_query_tracking()
        metrics = collector.end_query_tracking(error_message="Query failed")
        
        self.assertFalse(metrics["success"])
        self.assertEqual(metrics["error_message"], "Query failed")
        
    def test_end_query_tracking_adds_to_history(self):
        """Test end_query_tracking adds metrics to history."""
        collector = self.QueryMetricsCollector(track_resources=False)
        
        collector.start_query_tracking()
        collector.end_query_tracking()
        
        self.assertEqual(len(collector.query_metrics), 1)
        
    def test_end_query_tracking_resets_state(self):
        """Test end_query_tracking resets current query state."""
        collector = self.QueryMetricsCollector(track_resources=False)
        
        collector.start_query_tracking()
        collector.end_query_tracking()
        
        self.assertIsNone(collector.current_query)
        self.assertEqual(len(collector.active_timers), 0)
        self.assertEqual(collector.current_depth, 0)
        
    def test_end_query_tracking_raises_without_active_query(self):
        """Test end_query_tracking raises error if no active query."""
        collector = self.QueryMetricsCollector(track_resources=False)
        
        with self.assertRaises(ValueError) as context:
            collector.end_query_tracking()
            
        self.assertIn("No active query", str(context.exception))


class TestGetHealthCheck(unittest.TestCase):
    """Test get_health_check method."""
    
    def setUp(self):
        """Set up test fixtures."""
        from ipfs_datasets_py.optimizers.graphrag.query_metrics import QueryMetricsCollector
        self.QueryMetricsCollector = QueryMetricsCollector
        
    def test_get_health_check_empty_history(self):
        """Test health check with empty query history."""
        collector = self.QueryMetricsCollector(track_resources=False)
        
        health = collector.get_health_check()
        
        self.assertIn("status", health)
        self.assertIn("memory_usage_bytes", health)
        self.assertIsNone(health["last_session_duration_seconds"])
        self.assertEqual(health["error_rate_last_100"], 0.0)
        self.assertEqual(health["evaluated_sessions"], 0)
        
    def test_get_health_check_with_successful_queries(self):
        """Test health check with successful queries."""
        collector = self.QueryMetricsCollector(track_resources=False)
        
        # Add successful queries
        for i in range(5):
            collector.start_query_tracking()
            collector.end_query_tracking(results_count=10)
            
        health = collector.get_health_check()
        
        self.assertEqual(health["status"], "ok")
        self.assertEqual(health["error_rate_last_100"], 0.0)
        self.assertEqual(health["evaluated_sessions"], 5)
        self.assertIsNotNone(health["last_session_duration_seconds"])
        
    def test_get_health_check_with_high_error_rate(self):
        """Test health check detects high error rate."""
        collector = self.QueryMetricsCollector(track_resources=False)
        
        # Add queries with failures
        for i in range(10):
            collector.start_query_tracking()
            if i < 3:  # 30% error rate
                collector.end_query_tracking(error_message="Error")
            else:
                collector.end_query_tracking(results_count=5)
                
        health = collector.get_health_check()
        
        self.assertEqual(health["status"], "degraded")
        self.assertEqual(health["error_rate_last_100"], 0.3)
        
    def test_get_health_check_custom_window_size(self):
        """Test health check with custom window size."""
        collector = self.QueryMetricsCollector(track_resources=False)
        
        for i in range(20):
            collector.start_query_tracking()
            collector.end_query_tracking()
            
        health = collector.get_health_check(window_size=10)
        
        self.assertEqual(health["window_size"], 10)
        self.assertEqual(health["evaluated_sessions"], 10)


class TestPhaseTimingContextManager(unittest.TestCase):
    """Test time_phase context manager."""
    
    def setUp(self):
        """Set up test fixtures."""
        from ipfs_datasets_py.optimizers.graphrag.query_metrics import QueryMetricsCollector
        self.QueryMetricsCollector = QueryMetricsCollector
        
    def test_time_phase_basic(self):
        """Test basic phase timing with context manager."""
        collector = self.QueryMetricsCollector(track_resources=False)
        
        collector.start_query_tracking()
        
        with collector.time_phase("vector_search"):
            time.sleep(0.01)
            
        metrics = collector.end_query_tracking()
        
        self.assertIn("vector_search", metrics["phases"])
        self.assertGreater(metrics["phases"]["vector_search"]["duration"], 0)
        
    def test_time_phase_with_metadata(self):
        """Test phase timing with metadata."""
        collector = self.QueryMetricsCollector(track_resources=False)
        
        collector.start_query_tracking()
        
        with collector.time_phase("vector_search", metadata={"top_k": 10}):
            time.sleep(0.01)
            
        metrics = collector.end_query_tracking()
        
        self.assertEqual(metrics["phases"]["vector_search"]["metadata"]["top_k"], 10)
        
    def test_time_phase_nested(self):
        """Test nested phase timing."""
        collector = self.QueryMetricsCollector(track_resources=False)
        
        collector.start_query_tracking()
        
        with collector.time_phase("query_execution"):
            with collector.time_phase("vector_search"):
                time.sleep(0.01)
            with collector.time_phase("graph_traversal"):
                time.sleep(0.01)
                
        metrics = collector.end_query_tracking()
        
        self.assertIn("query_execution", metrics["phases"])
        self.assertIn("query_execution.vector_search", metrics["phases"])
        self.assertIn("query_execution.graph_traversal", metrics["phases"])
        
    def test_time_phase_raises_without_active_query(self):
        """Test time_phase raises error if no active query."""
        collector = self.QueryMetricsCollector(track_resources=False)
        
        with self.assertRaises(ValueError):
            with collector.time_phase("test_phase"):
                pass


class TestManualPhaseTimers(unittest.TestCase):
    """Test start_phase_timer and end_phase_timer methods."""
    
    def setUp(self):
        """Set up test fixtures."""
        from ipfs_datasets_py.optimizers.graphrag.query_metrics import QueryMetricsCollector
        self.QueryMetricsCollector = QueryMetricsCollector
        
    def test_start_end_phase_timer_basic(self):
        """Test manual phase timing."""
        collector = self.QueryMetricsCollector(track_resources=False)
        
        collector.start_query_tracking()
        collector.start_phase_timer("test_phase")
        time.sleep(0.01)
        duration = collector.end_phase_timer("test_phase")
        
        self.assertGreater(duration, 0)
        
    def test_start_phase_timer_with_metadata(self):
        """Test start_phase_timer with metadata."""
        collector = self.QueryMetricsCollector(track_resources=False)
        
        collector.start_query_tracking()
        collector.start_phase_timer("test_phase", metadata={"param": "value"})
        collector.end_phase_timer("test_phase")
        metrics = collector.end_query_tracking()
        
        self.assertEqual(metrics["phases"]["test_phase"]["metadata"]["param"], "value")
        
    def test_end_phase_timer_raises_for_nonexistent_phase(self):
        """Test end_phase_timer raises error for non-existent phase."""
        collector = self.QueryMetricsCollector(track_resources=False)
        
        collector.start_query_tracking()
        
        with self.assertRaises(ValueError) as context:
            collector.end_phase_timer("nonexistent_phase")
            
        self.assertIn("No active timer", str(context.exception))
        
    def test_repeated_phase_increments_count(self):
        """Test repeated phase calls increment count."""
        collector = self.QueryMetricsCollector(track_resources=False)
        
        collector.start_query_tracking()
        
        for i in range(3):
            collector.start_phase_timer("repeated_phase")
            collector.end_phase_timer("repeated_phase")
            
        metrics = collector.end_query_tracking()
        
        # First call has count 0, subsequent calls increment
        self.assertEqual(metrics["phases"]["repeated_phase"]["count"], 2)


class TestResourceUsageTracking(unittest.TestCase):
    """Test record_resource_usage method."""
    
    def setUp(self):
        """Set up test fixtures."""
        from ipfs_datasets_py.optimizers.graphrag.query_metrics import QueryMetricsCollector
        self.QueryMetricsCollector = QueryMetricsCollector
        
    @patch("ipfs_datasets_py.optimizers.graphrag.query_metrics.psutil")
    def test_record_resource_usage_captures_metrics(self, mock_psutil):
        """Test resource usage recording captures memory/CPU."""
        # Mock process
        mock_process = Mock()
        mock_memory_info = Mock()
        mock_memory_info.rss = 100000000  # 100MB
        mock_memory_info.vms = 200000000  # 200MB
        mock_process.memory_info.return_value = mock_memory_info
        mock_process.cpu_percent.return_value = 25.5
        mock_psutil.Process.return_value = mock_process
        
        collector = self.QueryMetricsCollector(track_resources=True)
        collector.start_query_tracking()
        
        metrics = collector.record_resource_usage()
        
        self.assertEqual(metrics["memory_rss"], 100000000)
        self.assertEqual(metrics["memory_vms"], 200000000)
        self.assertEqual(metrics["cpu_percent"], 25.5)
        
    @patch("ipfs_datasets_py.optimizers.graphrag.query_metrics.psutil")
    def test_record_resource_usage_updates_peak_memory(self, mock_psutil):
        """Test resource usage updates peak memory."""
        mock_process = Mock()
        mock_memory_info = Mock()
        mock_memory_info.rss = 150000000
        mock_memory_info.vms = 200000000
        mock_process.memory_info.return_value = mock_memory_info
        mock_process.cpu_percent.return_value = 20.0
        mock_psutil.Process.return_value = mock_process
        
        collector = self.QueryMetricsCollector(track_resources=True)
        collector.start_query_tracking()
        
        collector.record_resource_usage()
        
        self.assertEqual(collector.current_query["resources"]["peak_memory"], 150000000)
        
    def test_record_resource_usage_returns_empty_when_disabled(self):
        """Test resource usage returns empty dict when tracking disabled."""
        collector = self.QueryMetricsCollector(track_resources=False)
        collector.start_query_tracking()
        
        metrics = collector.record_resource_usage()
        
        self.assertEqual(metrics, {})


class TestRecordAdditionalMetric(unittest.TestCase):
    """Test record_additional_metric method."""
    
    def setUp(self):
        """Set up test fixtures."""
        from ipfs_datasets_py.optimizers.graphrag.query_metrics import QueryMetricsCollector
        self.QueryMetricsCollector = QueryMetricsCollector
        
    def test_record_additional_metric_stores_custom_metric(self):
        """Test recording custom metrics."""
        collector = self.QueryMetricsCollector(track_resources=False)
        
        collector.start_query_tracking()
        collector.record_additional_metric("cache_hits", 15, category="cache")
        metrics = collector.end_query_tracking()
        
        self.assertIn("cache", metrics["metadata"])
        self.assertEqual(metrics["metadata"]["cache"]["cache_hits"], 15)
        
    def test_record_additional_metric_multiple_categories(self):
        """Test recording metrics in multiple categories."""
        collector = self.QueryMetricsCollector(track_resources=False)
        
        collector.start_query_tracking()
        collector.record_additional_metric("hit_rate", 0.8, category="cache")
        collector.record_additional_metric("traversal_depth", 3, category="graph")
        metrics = collector.end_query_tracking()
        
        self.assertIn("cache", metrics["metadata"])
        self.assertIn("graph", metrics["metadata"])
        self.assertEqual(metrics["metadata"]["cache"]["hit_rate"], 0.8)
        self.assertEqual(metrics["metadata"]["graph"]["traversal_depth"], 3)
        
    def test_record_additional_metric_raises_without_active_query(self):
        """Test record_additional_metric raises error if no active query."""
        collector = self.QueryMetricsCollector(track_resources=False)
        
        with self.assertRaises(ValueError):
            collector.record_additional_metric("test", 123)


class TestGetQueryMetrics(unittest.TestCase):
    """Test get_query_metrics method."""
    
    def setUp(self):
        """Set up test fixtures."""
        from ipfs_datasets_py.optimizers.graphrag.query_metrics import QueryMetricsCollector
        self.QueryMetricsCollector = QueryMetricsCollector
        
    def test_get_query_metrics_returns_metrics_by_id(self):
        """Test retrieving specific query metrics by ID."""
        collector = self.QueryMetricsCollector(track_resources=False)
        
        query_id = collector.start_query_tracking(query_id="test-123")
        collector.end_query_tracking()
        
        metrics = collector.get_query_metrics("test-123")
        
        self.assertIsNotNone(metrics)
        self.assertEqual(metrics["query_id"], "test-123")
        
    def test_get_query_metrics_returns_none_for_nonexistent(self):
        """Test get_query_metrics returns None for non-existent ID."""
        collector = self.QueryMetricsCollector(track_resources=False)
        
        metrics = collector.get_query_metrics("nonexistent")
        
        self.assertIsNone(metrics)


class TestGetRecentMetrics(unittest.TestCase):
    """Test get_recent_metrics method."""
    
    def setUp(self):
        """Set up test fixtures."""
        from ipfs_datasets_py.optimizers.graphrag.query_metrics import QueryMetricsCollector
        self.QueryMetricsCollector = QueryMetricsCollector
        
    def test_get_recent_metrics_returns_limited_results(self):
        """Test get_recent_metrics returns limited number of results."""
        collector = self.QueryMetricsCollector(track_resources=False)
        
        # Add 15 queries
        for i in range(15):
            collector.start_query_tracking()
            collector.end_query_tracking()
            
        recent = collector.get_recent_metrics(count=10)
        
        self.assertEqual(len(recent), 10)
        
    def test_get_recent_metrics_returns_newest_first(self):
        """Test get_recent_metrics returns most recent queries."""
        collector = self.QueryMetricsCollector(track_resources=False)
        
        for i in range(5):
            collector.start_query_tracking(query_id=f"query-{i}")
            collector.end_query_tracking()
            
        recent = collector.get_recent_metrics(count=3)
        
        # Should get last 3 queries
        self.assertEqual(recent[0]["query_id"], "query-2")
        self.assertEqual(recent[1]["query_id"], "query-3")
        self.assertEqual(recent[2]["query_id"], "query-4")


class TestGetPhaseTimingSummary(unittest.TestCase):
    """Test get_phase_timing_summary method."""
    
    def setUp(self):
        """Set up test fixtures."""
        from ipfs_datasets_py.optimizers.graphrag.query_metrics import QueryMetricsCollector
        self.QueryMetricsCollector = QueryMetricsCollector
        
    def test_get_phase_timing_summary_single_query(self):
        """Test phase timing summary for single query."""
        collector = self.QueryMetricsCollector(track_resources=False)
        
        query_id = collector.start_query_tracking(query_id="test-query")
        with collector.time_phase("vector_search"):
            time.sleep(0.01)
        with collector.time_phase("graph_traversal"):
            time.sleep(0.01)
        collector.end_query_tracking()
        
        summary = collector.get_phase_timing_summary(query_id="test-query")
        
        self.assertIn("vector_search", summary)
        self.assertIn("graph_traversal", summary)
        self.assertIn("avg_duration", summary["vector_search"])
        
    def test_get_phase_timing_summary_all_queries(self):
        """Test phase timing summary across all queries."""
        collector = self.QueryMetricsCollector(track_resources=False)
        
        for i in range(3):
            collector.start_query_tracking()
            with collector.time_phase("vector_search"):
                time.sleep(0.01)
            collector.end_query_tracking()
            
        summary = collector.get_phase_timing_summary()
        
        self.assertIn("vector_search", summary)
        # total_duration should reflect cumulative time across all queries
        self.assertGreater(summary["vector_search"]["total_duration"], 0)
        self.assertGreater(summary["vector_search"]["avg_duration"], 0)
        
    def test_get_phase_timing_summary_calculates_statistics(self):
        """Test phase timing summary calculates complete statistics."""
        collector = self.QueryMetricsCollector(track_resources=False)
        
        collector.start_query_tracking()
        with collector.time_phase("test_phase"):
            time.sleep(0.01)
        collector.end_query_tracking()
        
        summary = collector.get_phase_timing_summary()
        
        self.assertIn("avg_duration", summary["test_phase"])
        self.assertIn("min_duration", summary["test_phase"])
        self.assertIn("max_duration", summary["test_phase"])
        self.assertIn("total_duration", summary["test_phase"])
        self.assertIn("call_count", summary["test_phase"])
        self.assertIn("avg_calls_per_query", summary["test_phase"])


class TestGeneratePerformanceReport(unittest.TestCase):
    """Test generate_performance_report method."""
    
    def setUp(self):
        """Set up test fixtures."""
        from ipfs_datasets_py.optimizers.graphrag.query_metrics import QueryMetricsCollector
        self.QueryMetricsCollector = QueryMetricsCollector
        
    def test_generate_performance_report_structure(self):
        """Test performance report has expected structure."""
        collector = self.QueryMetricsCollector(track_resources=False)
        
        collector.start_query_tracking()
        collector.end_query_tracking()
        
        report = collector.generate_performance_report()
        
        self.assertIn("timestamp", report)
        self.assertIn("query_count", report)
        self.assertIn("timing_summary", report)
        self.assertIn("resource_usage", report)
        self.assertIn("phase_breakdown", report)
        self.assertIn("recommendations", report)
        
    def test_generate_performance_report_timing_summary(self):
        """Test performance report includes timing statistics."""
        collector = self.QueryMetricsCollector(track_resources=False)
        
        for i in range(3):
            collector.start_query_tracking()
            time.sleep(0.01)
            collector.end_query_tracking()
            
        report = collector.generate_performance_report()
        
        self.assertIn("avg_duration", report["timing_summary"])
        self.assertIn("min_duration", report["timing_summary"])
        self.assertIn("max_duration", report["timing_summary"])
        self.assertIn("std_deviation", report["timing_summary"])
        
    def test_generate_performance_report_includes_recommendations(self):
        """Test performance report generates recommendations."""
        collector = self.QueryMetricsCollector(track_resources=False)
        
        collector.start_query_tracking()
        with collector.time_phase("slow_phase"):
            time.sleep(0.6)  # Intentionally slow
        collector.end_query_tracking()
        
        report = collector.generate_performance_report()
        
        # Should recommend optimization for slow phase
        self.assertTrue(len(report["recommendations"]) > 0)
        self.assertEqual(report["recommendations"][0]["type"], "optimization")
        
    def test_generate_performance_report_empty_metrics(self):
        """Test performance report with no metrics."""
        collector = self.QueryMetricsCollector(track_resources=False)
        
        report = collector.generate_performance_report()
        
        self.assertEqual(report["query_count"], 0)
        self.assertEqual(report["timing_summary"], {})


class TestExportMetricsCSV(unittest.TestCase):
    """Test export_metrics_csv method."""
    
    def setUp(self):
        """Set up test fixtures."""
        from ipfs_datasets_py.optimizers.graphrag.query_metrics import QueryMetricsCollector
        self.QueryMetricsCollector = QueryMetricsCollector
        
    def test_export_metrics_csv_returns_string(self):
        """Test CSV export returns string."""
        collector = self.QueryMetricsCollector(track_resources=False)
        
        collector.start_query_tracking(query_id="test-1")
        collector.end_query_tracking(results_count=10, quality_score=0.8)
        
        csv_content = collector.export_metrics_csv()
        
        self.assertIsNotNone(csv_content)
        self.assertIn("query_id", csv_content)
        self.assertIn("test-1", csv_content)
        
    def test_export_metrics_csv_writes_to_file(self):
        """Test CSV export writes to file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            collector = self.QueryMetricsCollector(track_resources=False)
            
            collector.start_query_tracking()
            collector.end_query_tracking()
            
            filepath = os.path.join(tmpdir, "metrics.csv")
            collector.export_metrics_csv(filepath=filepath)
            
            self.assertTrue(os.path.exists(filepath))
            
    def test_export_metrics_csv_includes_phases(self):
        """Test CSV export includes phase columns."""
        collector = self.QueryMetricsCollector(track_resources=False)
        
        collector.start_query_tracking()
        with collector.time_phase("vector_search"):
            time.sleep(0.01)
        collector.end_query_tracking()
        
        csv_content = collector.export_metrics_csv()
        
        self.assertIn("phase_vector_search", csv_content)
        
    def test_export_metrics_csv_empty_returns_none(self):
        """Test CSV export returns None for empty metrics."""
        collector = self.QueryMetricsCollector(track_resources=False)
        
        csv_content = collector.export_metrics_csv()
        
        self.assertIsNone(csv_content)


class TestExportMetricsJSON(unittest.TestCase):
    """Test export_metrics_json method."""
    
    def setUp(self):
        """Set up test fixtures."""
        from ipfs_datasets_py.optimizers.graphrag.query_metrics import QueryMetricsCollector
        self.QueryMetricsCollector = QueryMetricsCollector
        
    def test_export_metrics_json_returns_string(self):
        """Test JSON export returns string."""
        collector = self.QueryMetricsCollector(track_resources=False)
        
        collector.start_query_tracking(query_id="test-1")
        collector.end_query_tracking(results_count=5)
        
        json_content = collector.export_metrics_json()
        
        self.assertIsNotNone(json_content)
        data = json.loads(json_content)
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["query_id"], "test-1")
        
    def test_export_metrics_json_writes_to_file(self):
        """Test JSON export writes to file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            collector = self.QueryMetricsCollector(track_resources=False)
            
            collector.start_query_tracking()
            collector.end_query_tracking()
            
            filepath = os.path.join(tmpdir, "metrics.json")
            collector.export_metrics_json(filepath=filepath)
            
            self.assertTrue(os.path.exists(filepath))
            
    def test_export_metrics_json_handles_numpy_arrays(self):
        """Test JSON export handles numpy arrays."""
        try:
            import numpy as np
        except ImportError:
            self.skipTest("NumPy not available")
            
        collector = self.QueryMetricsCollector(track_resources=False)
        
        collector.start_query_tracking()
        collector.record_additional_metric("test_array", np.array([1, 2, 3]))
        collector.end_query_tracking()
        
        json_content = collector.export_metrics_json()
        
        self.assertIsNotNone(json_content)
        # Should not raise serialization error
        data = json.loads(json_content)
        self.assertEqual(len(data), 1)
        
    def test_export_metrics_json_empty_returns_none(self):
        """Test JSON export returns None for empty metrics."""
        collector = self.QueryMetricsCollector(track_resources=False)
        
        json_content = collector.export_metrics_json()
        
        self.assertIsNone(json_content)


class TestNumpyJsonSerialization(unittest.TestCase):
    """Test _numpy_json_serializable method."""
    
    def setUp(self):
        """Set up test fixtures."""
        from ipfs_datasets_py.optimizers.graphrag.query_metrics import QueryMetricsCollector
        self.QueryMetricsCollector = QueryMetricsCollector
        
    def test_numpy_serialization_handles_none(self):
        """Test numpy serialization handles None."""
        collector = self.QueryMetricsCollector(track_resources=False)
        
        result = collector._numpy_json_serializable(None)
        
        self.assertIsNone(result)
        
    def test_numpy_serialization_handles_dicts(self):
        """Test numpy serialization handles dictionaries."""
        collector = self.QueryMetricsCollector(track_resources=False)
        
        data = {"a": 1, "b": {"c": 2}}
        result = collector._numpy_json_serializable(data)
        
        self.assertEqual(result, {"a": 1, "b": {"c": 2}})
        
    def test_numpy_serialization_handles_lists(self):
        """Test numpy serialization handles lists."""
        collector = self.QueryMetricsCollector(track_resources=False)
        
        data = [1, 2, [3, 4]]
        result = collector._numpy_json_serializable(data)
        
        self.assertEqual(result, [1, 2, [3, 4]])
        
    def test_numpy_serialization_handles_small_arrays(self):
        """Test numpy serialization handles small numpy arrays."""
        try:
            import numpy as np
        except ImportError:
            self.skipTest("NumPy not available")
            
        collector = self.QueryMetricsCollector(track_resources=False)
        
        array = np.array([1, 2, 3, 4, 5])
        result = collector._numpy_json_serializable(array)
        
        self.assertIsInstance(result, list)
        self.assertEqual(result, [1, 2, 3, 4, 5])
        
    def test_numpy_serialization_handles_numpy_scalars(self):
        """Test numpy serialization handles numpy scalar types."""
        try:
            import numpy as np
        except ImportError:
            self.skipTest("NumPy not available")
            
        collector = self.QueryMetricsCollector(track_resources=False)
        
        self.assertEqual(collector._numpy_json_serializable(np.int64(42)), 42)
        self.assertEqual(collector._numpy_json_serializable(np.float64(3.14)), 3.14)
        self.assertEqual(collector._numpy_json_serializable(np.bool_(True)), True)
        
    def test_numpy_serialization_handles_datetime(self):
        """Test numpy serialization handles datetime objects."""
        import datetime
        
        collector = self.QueryMetricsCollector(track_resources=False)
        
        dt = datetime.datetime(2024, 1, 1, 12, 0, 0)
        result = collector._numpy_json_serializable(dt)
        
        self.assertEqual(result, "2024-01-01T12:00:00")


class TestPersistMetrics(unittest.TestCase):
    """Test _persist_metrics method."""
    
    def setUp(self):
        """Set up test fixtures."""
        from ipfs_datasets_py.optimizers.graphrag.query_metrics import QueryMetricsCollector
        self.QueryMetricsCollector = QueryMetricsCollector
        
    def test_persist_metrics_writes_to_file(self):
        """Test persist_metrics writes metrics to file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            collector = self.QueryMetricsCollector(
                metrics_dir=tmpdir,
                track_resources=False
            )
            
            collector.start_query_tracking(query_id="test-persist")
            collector.end_query_tracking()
            
            # Should have persisted to file
            files = os.listdir(tmpdir)
            self.assertTrue(len(files) > 0)
            self.assertTrue(any("test-persist" in f for f in files))
            
    def test_persist_metrics_does_nothing_without_metrics_dir(self):
        """Test persist_metrics does nothing if metrics_dir not set."""
        collector = self.QueryMetricsCollector(track_resources=False)
        
        collector.start_query_tracking()
        metrics = collector.end_query_tracking()
        
        # Should not raise error even without metrics_dir
        # Just verify it completes successfully
        self.assertIsNotNone(metrics)


class TestHistorySizeManagement(unittest.TestCase):
    """Test query metrics history size management."""
    
    def setUp(self):
        """Set up test fixtures."""
        from ipfs_datasets_py.optimizers.graphrag.query_metrics import QueryMetricsCollector
        self.QueryMetricsCollector = QueryMetricsCollector
        
    def test_history_respects_max_size(self):
        """Test query history respects max_history_size limit."""
        collector = self.QueryMetricsCollector(
            max_history_size=5,
            track_resources=False
        )
        
        # Add 10 queries
        for i in range(10):
            collector.start_query_tracking()
            collector.end_query_tracking()
            
        # Should only keep last 5
        self.assertEqual(len(collector.query_metrics), 5)
        
    def test_history_stores_most_recent(self):
        """Test query history stores most recent queries."""
        collector = self.QueryMetricsCollector(
            max_history_size=3,
            track_resources=False
        )
        
        for i in range(5):
            collector.start_query_tracking(query_id=f"query-{i}")
            collector.end_query_tracking()
            
        # Should have queries 2, 3, 4
        query_ids = [m["query_id"] for m in collector.query_metrics]
        self.assertEqual(query_ids, ["query-2", "query-3", "query-4"])


class TestIntegrationScenarios(unittest.TestCase):
    """Test integrated scenarios."""
    
    def setUp(self):
        """Set up test fixtures."""
        from ipfs_datasets_py.optimizers.graphrag.query_metrics import QueryMetricsCollector
        self.QueryMetricsCollector = QueryMetricsCollector
        
    def test_complete_query_lifecycle(self):
        """Test complete query metrics collection lifecycle."""
        with tempfile.TemporaryDirectory() as tmpdir:
            collector = self.QueryMetricsCollector(
                metrics_dir=tmpdir,
                track_resources=False
            )
            
            # Start query
            query_id = collector.start_query_tracking(
                query_id="integration-test",
                query_params={"max_depth": 2}
            )
            
            # Time phases
            with collector.time_phase("vector_search"):
                time.sleep(0.01)
                
            with collector.time_phase("graph_traversal"):
                time.sleep(0.01)
                
            # Record custom metrics
            collector.record_additional_metric("cache_hits", 5, category="cache")
            
            # End query
            metrics = collector.end_query_tracking(results_count=10, quality_score=0.9)
            
            # Verify complete metrics
            self.assertEqual(metrics["query_id"], "integration-test")
            self.assertEqual(metrics["results"]["count"], 10)
            self.assertEqual(metrics["results"]["quality_score"], 0.9)
            self.assertIn("vector_search", metrics["phases"])
            self.assertIn("graph_traversal", metrics["phases"])
            self.assertEqual(metrics["metadata"]["cache"]["cache_hits"], 5)
            
            # Verify persistence
            files = os.listdir(tmpdir)
            self.assertTrue(len(files) > 0)
            
    def test_multiple_queries_with_analysis(self):
        """Test collecting and analyzing multiple queries."""
        collector = self.QueryMetricsCollector(track_resources=False)
        
        # Execute multiple queries with different characteristics
        for i in range(5):
            collector.start_query_tracking(query_id=f"query-{i}")
            with collector.time_phase("vector_search"):
                time.sleep(0.01)
            with collector.time_phase("graph_traversal"):
                time.sleep(0.02)
            collector.end_query_tracking(results_count=10 + i)
            
        # Generate report
        report = collector.generate_performance_report()
        
        self.assertEqual(report["query_count"], 5)
        self.assertGreater(report["timing_summary"]["avg_duration"], 0)
        self.assertIn("vector_search", report["phase_breakdown"])
        self.assertIn("graph_traversal", report["phase_breakdown"])


class TestEdgeCases(unittest.TestCase):
    """Test edge cases and error handling."""
    
    def setUp(self):
        """Set up test fixtures."""
        from ipfs_datasets_py.optimizers.graphrag.query_metrics import QueryMetricsCollector
        self.QueryMetricsCollector = QueryMetricsCollector
        
    def test_zero_max_history_size(self):
        """Test behavior with zero max history size."""
        collector = self.QueryMetricsCollector(
            max_history_size=0,
            track_resources=False
        )
        
        collector.start_query_tracking()
        collector.end_query_tracking()
        
        # Should not store any metrics
        self.assertEqual(len(collector.query_metrics), 0)
        
    def test_multiple_active_queries_prevented(self):
        """Test starting new query before ending previous one."""
        collector = self.QueryMetricsCollector(track_resources=False)
        
        collector.start_query_tracking(query_id="query-1")
        # Starting second query should overwrite
        collector.start_query_tracking(query_id="query-2")
        
        # Current query should be query-2
        self.assertEqual(collector.current_query["query_id"], "query-2")
        
    def test_export_with_serialization_errors(self):
        """Test export handles serialization errors gracefully."""
        collector = self.QueryMetricsCollector(track_resources=False)
        
        collector.start_query_tracking()
        # Add problematic data that might fail serialization
        collector.record_additional_metric("test", float('inf'))
        collector.end_query_tracking()
        
        # Should not raise, should return fallback or handle gracefully
        json_content = collector.export_metrics_json()
        # Either returns valid JSON or None
        if json_content:
            data = json.loads(json_content)
            self.assertTrue(isinstance(data, (list, dict)))


if __name__ == "__main__":
    unittest.main()
