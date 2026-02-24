"""Tests for performance profiling tools."""

import pytest
import time
from ipfs_datasets_py.optimizers.common.performance_profiler import (
    PerformanceProfiler,
    BenchmarkTimer,
    profile_decorator,
    benchmark,
)


def slow_function(n: int) -> int:
    """Function that takes time proportional to n."""
    total = 0
    for i in range(n):
        total += i ** 2
    return total


def fast_function(n: int) -> int:
    """Fast function."""
    return sum(i ** 2 for i in range(n))


class TestPerformanceProfiler:
    """Test PerformanceProfiler."""
    
    def test_profile_function(self):
        """Test profiling a function."""
        profiler = PerformanceProfiler()
        result = profiler.profile_function(slow_function, 1000)
        
        assert result > 0
        assert len(profiler.get_stats()) > 0
    
    def test_get_stats(self):
        """Test getting profiling statistics."""
        profiler = PerformanceProfiler()
        profiler.profile_function(slow_function, 1000)
        
        stats = profiler.get_stats(top_n=5)
        
        assert isinstance(stats, list)
        assert len(stats) > 0
        # Each stat should be tuple of (name, time, calls)
        for name, time_val, calls in stats:
            assert isinstance(name, str)
            assert isinstance(time_val, float)
            assert isinstance(calls, int)
    
    def test_get_hotspots(self):
        """Test identifying hotspots."""
        profiler = PerformanceProfiler()
        profiler.profile_function(slow_function, 5000)
        
        hotspots = profiler.get_hotspots(threshold_percent=0.0, top_n=5)
        
        assert isinstance(hotspots, list)
        # Should have at least one hotspot
        assert len(hotspots) > 0
        
        # Each hotspot should be (name, time, percent)
        for name, time_val, percent in hotspots:
            assert isinstance(name, str)
            assert isinstance(time_val, float)
            assert isinstance(percent, float)
            assert 0 <= percent <= 100
    
    def test_generate_report(self):
        """Test generating a profiling report."""
        profiler = PerformanceProfiler()
        profiler.profile_function(slow_function, 1000)
        
        report = profiler.generate_report()
        
        assert isinstance(report, str)
        assert "PERFORMANCE PROFILING REPORT" in report
        assert "TOP FUNCTIONS" in report
        assert "HOTSPOTS" in report
    
    def test_multiple_profile_calls(self):
        """Test profiling multiple functions."""
        profiler = PerformanceProfiler()
        
        # Profile multiple functions
        result1 = profiler.profile_function(fast_function, 100)
        result2 = profiler.profile_function(slow_function, 100)
        
        assert result1 > 0
        assert result2 > 0
        
        # Should have stats for both
        stats = profiler.get_stats(top_n=10)
        assert len(stats) > 0


class TestBenchmarkTimer:
    """Test BenchmarkTimer context manager."""
    
    def test_timer_context_manager(self):
        """Test using timer as context manager."""
        timer = BenchmarkTimer("test operation")
        
        with timer:
            time.sleep(0.1)
        
        assert timer.elapsed >= 0.09  # Allow small variance
        assert timer.start_time is not None
        assert timer.end_time is not None
    
    def test_timer_elapsed(self):
        """Test elapsed property."""
        timer = BenchmarkTimer()
        
        with timer:
            time.sleep(0.05)
        
        assert 0.04 < timer.elapsed < 0.15  # Allow variance
    
    def test_timer_str_representation(self):
        """Test string representation."""
        timer = BenchmarkTimer("my operation")
        
        with timer:
            time.sleep(0.01)
        
        str_repr = str(timer)
        assert "my operation" in str_repr
        assert "s" in str_repr  # seconds indicator
    
    def test_timer_without_context(self):
        """Test timer without context manager."""
        timer = BenchmarkTimer()
        assert timer.elapsed == 0.0


class TestProfileDecorator:
    """Test profile_decorator."""
    
    def test_decorator_without_profiling(self):
        """Test decorator with profiling disabled."""
        @profile_decorator(profile_func=False)
        def test_func(x):
            return x * 2
        
        result = test_func(5)
        assert result == 10
    
    def test_decorator_with_profiling(self, capsys):
        """Test decorator with profiling enabled."""
        @profile_decorator(profile_func=True)
        def test_func(x):
            time.sleep(0.01)
            return x * 2
        
        result = test_func(5)
        assert result == 10
        
        captured = capsys.readouterr()
        assert "PERFORMANCE PROFILING REPORT" in captured.out
    
    def test_decorator_preserves_function(self):
        """Test that decorator preserves function properties."""
        @profile_decorator(profile_func=False)
        def documented_func(x):
            """This function has documentation."""
            return x
        
        assert documented_func.__doc__ is not None
        assert "documentation" in documented_func.__doc__.lower()


class TestBenchmarkContextManager:
    """Test benchmark context manager."""
    
    def test_benchmark_context(self, capsys):
        """Test benchmark context manager."""
        with benchmark("test operation"):
            time.sleep(0.05)
        
        captured = capsys.readouterr()
        assert "test operation" in captured.out
        assert "s" in captured.out
    
    def test_benchmark_timing(self):
        """Test benchmark measures time correctly."""
        with benchmark("operation") as timer:
            time.sleep(0.05)
        
        assert 0.04 < timer.elapsed < 0.15


class TestProfileResultIntegration:
    """Integration tests combining components."""
    
    def test_profile_and_benchmark(self, capsys):
        """Test profiler with benchmarking."""
        profiler = PerformanceProfiler()
        
        with benchmark("profiling slow function"):
            result = profiler.profile_function(slow_function, 500)
        
        assert result > 0
        
        report = profiler.generate_report(top_n=5)
        assert len(report) > 100  # Report should be substantial
    
    def test_compare_functions_timing(self):
        """Test comparing timing of different functions."""
        input_size = 10000  # Increased from 1000 for more reliable timing
        
        # Time fast function
        with benchmark("fast_function") as timer_fast:
            fast_function(input_size)
        
        # Time slow function (10x more work)
        with benchmark("slow_function") as timer_slow:
            slow_function(input_size * 10)
        
        # Slow function should take more time
        assert timer_slow.elapsed > timer_fast.elapsed
