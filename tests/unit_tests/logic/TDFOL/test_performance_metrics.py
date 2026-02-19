"""
Tests for unified Performance Metrics module (Phase 1 Task 1.4).

This module tests the consolidated MetricsCollector that replaces duplicated
functionality from performance_profiler.py and performance_dashboard.py.
"""

import pytest
import time
from unittest.mock import Mock, patch
from ipfs_datasets_py.logic.TDFOL.performance_metrics import (
    MetricsCollector,
    TimingResult,
    MemoryResult,
    StatisticalSummary,
    get_global_collector,
    reset_global_collector
)


class TestMetricsCollectorTiming:
    """Tests for timing operations."""
    
    def test_context_manager_timing(self):
        """Test timing with context manager."""
        # GIVEN a metrics collector
        collector = MetricsCollector()
        
        # WHEN timing an operation with context manager
        with collector.time("test_operation"):
            time.sleep(0.01)  # Sleep 10ms
        
        # THEN timing should be recorded
        stats = collector.get_timing_stats("test_operation")
        assert stats is not None
        assert stats.count == 1
        assert 9 < stats.mean < 20  # Should be around 10ms (with tolerance)
        assert len(collector.timing_results) == 1
        assert collector.timing_results[0].name == "test_operation"
    
    def test_start_stop_timer(self):
        """Test manual start/stop timer."""
        # GIVEN a metrics collector
        collector = MetricsCollector()
        
        # WHEN using start/stop timer
        collector.start_timer("manual_op")
        time.sleep(0.005)  # Sleep 5ms
        duration_ms = collector.stop_timer("manual_op")
        
        # THEN timing should be recorded
        assert 4 < duration_ms < 15  # Should be around 5ms
        stats = collector.get_timing_stats("manual_op")
        assert stats.count == 1
    
    def test_stop_timer_without_start_raises_error(self):
        """Test that stopping non-existent timer raises error."""
        # GIVEN a metrics collector
        collector = MetricsCollector()
        
        # WHEN stopping a timer that wasn't started
        # THEN should raise KeyError
        with pytest.raises(KeyError, match="Timer 'nonexistent' was not started"):
            collector.stop_timer("nonexistent")
    
    def test_timed_decorator(self):
        """Test timing decorator."""
        # GIVEN a metrics collector and decorated function
        collector = MetricsCollector()
        
        @collector.timed("decorated_op")
        def slow_function():
            time.sleep(0.01)
            return 42
        
        # WHEN calling the decorated function
        result = slow_function()
        
        # THEN function should return correct result and be timed
        assert result == 42
        stats = collector.get_timing_stats("decorated_op")
        assert stats.count == 1
        assert stats.mean > 9  # At least 9ms
    
    def test_multiple_timing_samples(self):
        """Test statistical aggregation of multiple timing samples."""
        # GIVEN a metrics collector
        collector = MetricsCollector()
        
        # WHEN recording multiple timings
        for i in range(100):
            with collector.time("repeated_op"):
                time.sleep(0.001)  # 1ms
        
        # THEN statistics should be calculated correctly
        stats = collector.get_timing_stats("repeated_op")
        assert stats.count == 100
        assert stats.mean > 0.5  # At least 0.5ms
        assert stats.p95 > stats.p50  # P95 should be higher than median
        assert stats.p99 > stats.p95  # P99 should be higher than P95


class TestMetricsCollectorMemory:
    """Tests for memory profiling operations."""
    
    def test_track_memory_context_manager(self):
        """Test memory tracking with context manager."""
        # GIVEN a metrics collector
        collector = MetricsCollector()
        
        # WHEN tracking memory of an operation
        with collector.track_memory("memory_test"):
            # Allocate some memory
            data = [0] * 100000  # Should allocate some MB
            _ = data  # Keep reference
        
        # THEN memory usage should be recorded
        stats = collector.get_memory_stats("memory_test", "delta_mb")
        assert stats is not None
        assert stats.count == 1
        # Memory should have been allocated (delta > 0)
        # Note: Actual values depend on Python implementation
        assert len(collector.memory_results) == 1
        assert collector.memory_results[0].name == "memory_test"
    
    def test_memory_tracking_multiple_samples(self):
        """Test multiple memory tracking samples."""
        # GIVEN a metrics collector
        collector = MetricsCollector()
        
        # WHEN tracking memory multiple times
        for i in range(10):
            with collector.track_memory("repeated_memory"):
                data = [i] * 1000
                _ = data
        
        # THEN statistics should be available
        stats = collector.get_memory_stats("repeated_memory", "peak_mb")
        assert stats is not None
        assert stats.count == 10
        assert stats.mean >= 0  # Should have some memory usage
    
    def test_record_memory_directly(self):
        """Test direct memory recording."""
        # GIVEN a metrics collector
        collector = MetricsCollector()
        
        # WHEN recording memory directly
        collector.record_memory(
            name="manual_memory",
            current_mb=10.5,
            peak_mb=12.3,
            delta_mb=2.1
        )
        
        # THEN memory should be recorded
        stats = collector.get_memory_stats("manual_memory", "delta_mb")
        assert stats.count == 1
        assert abs(stats.mean - 2.1) < 0.01
        
        stats_peak = collector.get_memory_stats("manual_memory", "peak_mb")
        assert abs(stats_peak.mean - 12.3) < 0.01


class TestMetricsCollectorCountersGauges:
    """Tests for counters, gauges, and histograms."""
    
    def test_increment_counter(self):
        """Test counter increment."""
        # GIVEN a metrics collector
        collector = MetricsCollector()
        
        # WHEN incrementing counters
        collector.increment_counter("requests")
        collector.increment_counter("requests")
        collector.increment_counter("requests", value=5)
        
        # THEN counter should have correct value
        assert collector.counters["requests"] == 7
    
    def test_set_gauge(self):
        """Test gauge setting."""
        # GIVEN a metrics collector
        collector = MetricsCollector()
        
        # WHEN setting gauge values
        collector.set_gauge("cpu_usage", 45.2)
        collector.set_gauge("memory_percent", 67.8)
        
        # THEN gauges should have correct values
        assert collector.gauges["cpu_usage"] == 45.2
        assert collector.gauges["memory_percent"] == 67.8
    
    def test_histogram_recording(self):
        """Test histogram value recording."""
        # GIVEN a metrics collector
        collector = MetricsCollector()
        
        # WHEN recording histogram values
        values = [10, 20, 30, 40, 50, 60, 70, 80, 90, 100]
        for v in values:
            collector.record_histogram("response_times", v)
        
        # THEN statistics should be calculated
        stats = collector.get_histogram_stats("response_times")
        assert stats.count == 10
        assert abs(stats.mean - 55) < 0.1  # Mean should be 55
        assert abs(stats.median - 55) < 0.1  # Median should be 55
        assert stats.min == 10
        assert stats.max == 100


class TestMetricsCollectorStatistics:
    """Tests for statistical calculations."""
    
    def test_statistical_summary_computation(self):
        """Test that statistical summary is computed correctly."""
        # GIVEN a metrics collector with known values
        collector = MetricsCollector()
        
        # WHEN recording values with known distribution
        values = list(range(1, 101))  # 1 to 100
        for v in values:
            collector.record_histogram("known_dist", float(v))
        
        # THEN statistics should match expected values
        stats = collector.get_histogram_stats("known_dist")
        assert stats.count == 100
        assert abs(stats.sum - 5050) < 1  # Sum of 1-100 is 5050
        assert abs(stats.mean - 50.5) < 0.1
        assert abs(stats.median - 50.5) < 0.1
        assert stats.min == 1
        assert stats.max == 100
        assert abs(stats.p50 - 50.5) < 1
        assert abs(stats.p95 - 95) < 2
        assert abs(stats.p99 - 99) < 2
    
    def test_percentile_calculation(self):
        """Test percentile calculation with edge cases."""
        # GIVEN a metrics collector
        collector = MetricsCollector()
        
        # WHEN recording a small number of values
        for v in [10, 20, 30]:
            collector.record_histogram("small_set", float(v))
        
        # THEN percentiles should be reasonable
        stats = collector.get_histogram_stats("small_set")
        assert stats.p50 == 20  # Median
        assert 20 <= stats.p95 <= 30  # Should be close to max
    
    def test_get_statistics_comprehensive(self):
        """Test comprehensive statistics export."""
        # GIVEN a metrics collector with various metrics
        collector = MetricsCollector()
        
        # Record timing
        with collector.time("op1"):
            pass
        
        # Record memory
        collector.record_memory("mem1", 10.0, 15.0, 5.0)
        
        # Record counter and gauge
        collector.increment_counter("count1", 5)
        collector.set_gauge("gauge1", 42.0)
        
        # Record histogram
        collector.record_histogram("hist1", 100.0)
        
        # WHEN getting comprehensive statistics
        stats = collector.get_statistics()
        
        # THEN all metric types should be included
        assert "timing" in stats
        assert "memory" in stats
        assert "counters" in stats
        assert "gauges" in stats
        assert "histograms" in stats
        assert "metadata" in stats
        
        assert "op1" in stats["timing"]
        assert "mem1" in stats["memory"]
        assert stats["counters"]["count1"] == 5
        assert stats["gauges"]["gauge1"] == 42.0
        assert "hist1" in stats["histograms"]


class TestMetricsCollectorExport:
    """Tests for export functionality."""
    
    def test_export_dict(self):
        """Test dictionary export for MCP integration."""
        # GIVEN a metrics collector with data
        collector = MetricsCollector()
        
        with collector.time("export_test"):
            pass
        
        collector.record_memory("mem_export", 5.0, 6.0, 1.0)
        
        # WHEN exporting as dictionary
        export = collector.export_dict()
        
        # THEN export should contain all data
        assert "statistics" in export
        assert "timing_results" in export
        assert "memory_results" in export
        
        # Should have recent results
        assert len(export["timing_results"]) > 0
        assert len(export["memory_results"]) > 0
        
        # Timing result should have required fields
        timing_result = export["timing_results"][0]
        assert "name" in timing_result
        assert "duration_ms" in timing_result
        assert "timestamp" in timing_result
        assert "datetime" in timing_result
    
    def test_reset_clears_all_data(self):
        """Test that reset clears all metrics."""
        # GIVEN a metrics collector with data
        collector = MetricsCollector()
        
        with collector.time("op"):
            pass
        collector.increment_counter("count", 10)
        collector.set_gauge("gauge", 50.0)
        
        # WHEN resetting
        collector.reset()
        
        # THEN all data should be cleared
        assert len(collector.timings) == 0
        assert len(collector.timing_results) == 0
        assert len(collector.memory_results) == 0
        assert len(collector.counters) == 0
        assert len(collector.gauges) == 0
        assert len(collector.histograms) == 0


class TestGlobalCollector:
    """Tests for global collector instance."""
    
    def test_get_global_collector(self):
        """Test getting global collector instance."""
        # GIVEN no setup
        # WHEN getting global collector
        collector = get_global_collector()
        
        # THEN should return a MetricsCollector instance
        assert isinstance(collector, MetricsCollector)
    
    def test_global_collector_singleton(self):
        """Test that global collector is a singleton."""
        # GIVEN two calls to get_global_collector
        # WHEN getting collector twice
        collector1 = get_global_collector()
        collector2 = get_global_collector()
        
        # THEN should return same instance
        assert collector1 is collector2
    
    def test_reset_global_collector(self):
        """Test resetting global collector."""
        # GIVEN a global collector with data
        collector1 = get_global_collector()
        with collector1.time("test"):
            pass
        
        # WHEN resetting global collector
        reset_global_collector()
        collector2 = get_global_collector()
        
        # THEN should get a new instance
        assert collector1 is not collector2
        assert len(collector2.timing_results) == 0


class TestDataModels:
    """Tests for data model classes."""
    
    def test_timing_result_to_dict(self):
        """Test TimingResult conversion to dict."""
        # GIVEN a TimingResult
        result = TimingResult(
            name="test_op",
            duration_ms=42.5,
            timestamp=1234567890.0,
            metadata={"key": "value"}
        )
        
        # WHEN converting to dict
        d = result.to_dict()
        
        # THEN should contain all fields
        assert d["name"] == "test_op"
        assert d["duration_ms"] == 42.5
        assert d["timestamp"] == 1234567890.0
        assert d["key"] == "value"
        assert "datetime" in d
    
    def test_memory_result_to_dict(self):
        """Test MemoryResult conversion to dict."""
        # GIVEN a MemoryResult
        result = MemoryResult(
            name="mem_op",
            current_mb=10.5,
            peak_mb=12.3,
            delta_mb=1.8,
            timestamp=1234567890.0,
            metadata={"source": "test"}
        )
        
        # WHEN converting to dict
        d = result.to_dict()
        
        # THEN should contain all fields
        assert d["name"] == "mem_op"
        assert d["current_mb"] == 10.5
        assert d["peak_mb"] == 12.3
        assert d["delta_mb"] == 1.8
        assert d["source"] == "test"
        assert "datetime" in d
    
    def test_statistical_summary_to_dict(self):
        """Test StatisticalSummary conversion to dict."""
        # GIVEN a StatisticalSummary
        summary = StatisticalSummary(
            count=100,
            sum=5050.0,
            mean=50.5,
            median=50.5,
            std_dev=28.9,
            min=1.0,
            max=100.0,
            p50=50.5,
            p95=95.0,
            p99=99.0,
            p999=99.9
        )
        
        # WHEN converting to dict
        d = summary.to_dict()
        
        # THEN should contain all fields
        assert d["count"] == 100
        assert d["mean"] == 50.5
        assert d["p95"] == 95.0
        assert d["p99"] == 99.0
