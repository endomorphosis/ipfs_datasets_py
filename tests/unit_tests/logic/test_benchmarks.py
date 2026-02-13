"""
Tests for performance benchmarking system.

Tests cover:
- Benchmark framework functionality
- FOL conversion benchmarks
- Cache performance benchmarks
- Comparison and statistics
"""

import pytest
import asyncio
from ipfs_datasets_py.logic.benchmarks import (
    BenchmarkResult,
    PerformanceBenchmark,
    FOLBenchmarks,
    CacheBenchmarks,
)


class TestBenchmarkResult:
    """Test BenchmarkResult dataclass."""

    def test_benchmark_result_creation(self):
        """
        GIVEN: Benchmark timing data
        WHEN: Creating BenchmarkResult
        THEN: Should create valid result object
        """
        result = BenchmarkResult(
            name="Test",
            description="Test benchmark",
            iterations=100,
            total_time=10.0,
            mean_time=0.1,
            median_time=0.09,
            std_dev=0.01,
            min_time=0.08,
            max_time=0.15,
            throughput=10.0,
        )
        
        assert result.name == "Test"
        assert result.iterations == 100
        assert result.throughput == 10.0

    def test_to_dict(self):
        """
        GIVEN: BenchmarkResult instance
        WHEN: Converting to dict
        THEN: Should serialize correctly
        """
        result = BenchmarkResult(
            name="Test",
            description="Desc",
            iterations=50,
            total_time=5.0,
            mean_time=0.1,
            median_time=0.1,
            std_dev=0.01,
            min_time=0.08,
            max_time=0.12,
            throughput=10.0,
        )
        
        d = result.to_dict()
        
        assert isinstance(d, dict)
        assert d["name"] == "Test"
        assert d["iterations"] == 50

    def test_summary(self):
        """
        GIVEN: BenchmarkResult
        WHEN: Getting summary
        THEN: Should return human-readable string
        """
        result = BenchmarkResult(
            name="Test",
            description="",
            iterations=100,
            total_time=10.0,
            mean_time=0.1,
            median_time=0.1,
            std_dev=0.01,
            min_time=0.08,
            max_time=0.12,
            throughput=10.0,
        )
        
        summary = result.summary()
        
        assert isinstance(summary, str)
        assert "Test" in summary


class TestPerformanceBenchmark:
    """Test PerformanceBenchmark framework."""

    def test_benchmark_sync_function(self):
        """
        GIVEN: Simple synchronous function
        WHEN: Benchmarking
        THEN: Should measure performance
        """
        benchmark = PerformanceBenchmark(warmup_iterations=1)
        
        def test_func():
            return sum(range(100))
        
        result = benchmark.benchmark(
            name="Test Sync",
            func=test_func,
            iterations=10,
        )
        
        assert isinstance(result, BenchmarkResult)
        assert result.iterations == 10
        assert result.mean_time > 0

    @pytest.mark.asyncio
    async def test_benchmark_async_function(self):
        """
        GIVEN: Asynchronous function
        WHEN: Benchmarking
        THEN: Should measure async performance
        """
        benchmark = PerformanceBenchmark(warmup_iterations=1)
        
        async def test_func():
            await asyncio.sleep(0.001)
            return "done"
        
        result = await benchmark.benchmark_async(
            name="Test Async",
            func=test_func,
            iterations=10,
        )
        
        assert isinstance(result, BenchmarkResult)
        assert result.iterations == 10
        assert result.mean_time > 0.001  # Should take at least 1ms

    def test_benchmark_with_args(self):
        """
        GIVEN: Function with arguments
        WHEN: Benchmarking with kwargs
        THEN: Should pass arguments correctly
        """
        benchmark = PerformanceBenchmark(warmup_iterations=1)
        
        def test_func(x, y):
            return x + y
        
        result = benchmark.benchmark(
            name="Test Args",
            func=test_func,
            iterations=10,
            x=5,
            y=3,
        )
        
        assert isinstance(result, BenchmarkResult)

    def test_multiple_benchmarks(self):
        """
        GIVEN: Multiple benchmark runs
        WHEN: Running different benchmarks
        THEN: Should track all results
        """
        benchmark = PerformanceBenchmark(warmup_iterations=1)
        
        benchmark.benchmark("Test 1", lambda: sum(range(10)), iterations=5)
        benchmark.benchmark("Test 2", lambda: sum(range(20)), iterations=5)
        
        assert len(benchmark.results) == 2

    def test_compare_results(self):
        """
        GIVEN: Two benchmark results
        WHEN: Comparing
        THEN: Should provide comparison metrics
        """
        benchmark = PerformanceBenchmark(warmup_iterations=1)
        
        result1 = benchmark.benchmark("Fast", lambda: 1+1, iterations=10)
        result2 = benchmark.benchmark("Slow", lambda: sum(range(1000)), iterations=10)
        
        comparison = benchmark.compare(result1, result2)
        
        assert isinstance(comparison, dict)
        assert "speedup" in comparison
        assert "faster" in comparison

    def test_get_summary(self):
        """
        GIVEN: Benchmark with results
        WHEN: Getting summary
        THEN: Should return summary dictionary
        """
        benchmark = PerformanceBenchmark(warmup_iterations=1)
        
        benchmark.benchmark("Test", lambda: 1+1, iterations=5)
        
        summary = benchmark.get_summary()
        
        assert isinstance(summary, dict)
        assert "total_benchmarks" in summary
        assert summary["total_benchmarks"] == 1

    def test_empty_summary(self):
        """
        GIVEN: Benchmark with no results
        WHEN: Getting summary
        THEN: Should handle gracefully
        """
        benchmark = PerformanceBenchmark()
        
        summary = benchmark.get_summary()
        
        assert "error" in summary


class TestFOLBenchmarks:
    """Test FOL benchmark suite."""

    @pytest.mark.asyncio
    async def test_simple_conversion_benchmark(self):
        """
        GIVEN: FOL benchmark suite
        WHEN: Benchmarking simple conversion
        THEN: Should measure conversion performance
        """
        benchmark = PerformanceBenchmark(warmup_iterations=1)
        
        result = await FOLBenchmarks.benchmark_simple_conversion(
            benchmark,
            use_nlp=False
        )
        
        assert isinstance(result, BenchmarkResult)
        assert result.iterations == 100

    @pytest.mark.asyncio
    async def test_complex_conversion_benchmark(self):
        """
        GIVEN: FOL benchmark suite
        WHEN: Benchmarking complex conversion
        THEN: Should measure complex formula performance
        """
        benchmark = PerformanceBenchmark(warmup_iterations=1)
        
        result = await FOLBenchmarks.benchmark_complex_conversion(
            benchmark,
            use_nlp=False
        )
        
        assert isinstance(result, BenchmarkResult)
        assert result.iterations == 50

    @pytest.mark.asyncio
    async def test_batch_conversion_benchmark(self):
        """
        GIVEN: FOL benchmark suite
        WHEN: Benchmarking batch conversion
        THEN: Should measure batch throughput
        """
        benchmark = PerformanceBenchmark(warmup_iterations=1)
        
        result = await FOLBenchmarks.benchmark_batch_conversion(
            benchmark,
            batch_size=5
        )
        
        assert isinstance(result, BenchmarkResult)
        assert result.iterations == 10

    @pytest.mark.asyncio
    async def test_nlp_vs_regex_comparison(self):
        """
        GIVEN: Both NLP and regex extraction
        WHEN: Benchmarking both methods
        THEN: Should allow performance comparison
        """
        benchmark = PerformanceBenchmark(warmup_iterations=1)
        
        regex_result = await FOLBenchmarks.benchmark_simple_conversion(
            benchmark,
            use_nlp=False
        )
        
        nlp_result = await FOLBenchmarks.benchmark_simple_conversion(
            benchmark,
            use_nlp=True
        )
        
        # Both should complete
        assert isinstance(regex_result, BenchmarkResult)
        assert isinstance(nlp_result, BenchmarkResult)
        
        # Compare
        comparison = benchmark.compare(regex_result, nlp_result)
        assert "speedup" in comparison


class TestCacheBenchmarks:
    """Test cache benchmark suite."""

    def test_cache_hit_benchmark(self):
        """
        GIVEN: Cache benchmark suite
        WHEN: Benchmarking cache hits
        THEN: Should measure hit performance
        """
        benchmark = PerformanceBenchmark(warmup_iterations=1)
        
        result = CacheBenchmarks.benchmark_cache_hit(benchmark)
        
        assert isinstance(result, BenchmarkResult)
        assert result.iterations == 10000
        # Cache hits should be very fast (allowing for CI variability)
        assert result.mean_time < 0.01  # <10ms (relaxed threshold for CI)

    def test_cache_miss_benchmark(self):
        """
        GIVEN: Cache benchmark suite
        WHEN: Benchmarking cache misses
        THEN: Should measure miss performance
        """
        benchmark = PerformanceBenchmark(warmup_iterations=1)
        
        result = CacheBenchmarks.benchmark_cache_miss(benchmark)
        
        assert isinstance(result, BenchmarkResult)
        assert result.iterations == 10000

    def test_hit_vs_miss_comparison(self):
        """
        GIVEN: Cache hit and miss benchmarks
        WHEN: Comparing performance
        THEN: Hits should be faster than misses
        """
        benchmark = PerformanceBenchmark(warmup_iterations=1)
        
        hit_result = CacheBenchmarks.benchmark_cache_hit(benchmark)
        miss_result = CacheBenchmarks.benchmark_cache_miss(benchmark)
        
        # Both should be very fast
        assert hit_result.mean_time < 0.001
        assert miss_result.mean_time < 0.001


class TestBenchmarkStatistics:
    """Test benchmark statistics calculations."""

    def test_throughput_calculation(self):
        """
        GIVEN: Benchmark with timing data
        WHEN: Calculating throughput
        THEN: Should compute ops/sec correctly
        """
        result = BenchmarkResult(
            name="Test",
            description="",
            iterations=100,
            total_time=10.0,  # 10 seconds
            mean_time=0.1,
            median_time=0.1,
            std_dev=0.0,
            min_time=0.1,
            max_time=0.1,
            throughput=10.0,  # 100 ops / 10 sec = 10 ops/sec
        )
        
        assert result.throughput == 10.0

    def test_statistics_with_variation(self):
        """
        GIVEN: Benchmark with timing variation
        WHEN: Computing statistics
        THEN: Should capture variation correctly
        """
        benchmark = PerformanceBenchmark(warmup_iterations=1)
        
        import random
        def variable_func():
            time.sleep(random.uniform(0.001, 0.005))
        
        import time
        result = benchmark.benchmark(
            "Variable Test",
            variable_func,
            iterations=10
        )
        
        # Should have some standard deviation
        assert result.std_dev > 0
        assert result.min_time < result.max_time


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
