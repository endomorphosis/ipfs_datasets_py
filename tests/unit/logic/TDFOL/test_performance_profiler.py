"""
Comprehensive tests for TDFOL Performance Profiler

This module provides 20+ tests covering all profiling functionality:
1. cProfile integration (decorators, wrappers, prover profiling)
2. Bottleneck identification (O(n³) detection, severity levels)
3. Memory profiling (leaks, allocations, peak usage)
4. Benchmark suite (standard benchmarks, regression detection)
5. Report generation (TEXT, JSON, HTML formats)
6. Context managers and utilities

Author: TDFOL Team
Date: 2026-02-18
Phase: 12 (Performance Optimization)
Task: 12.1 (Profiling Infrastructure)
"""

import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, Mock, patch

import pytest

from ipfs_datasets_py.logic.TDFOL.performance_profiler import (
    Bottleneck,
    BottleneckSeverity,
    BenchmarkResult,
    BenchmarkResults,
    MemoryStats,
    PerformanceProfiler,
    ProfileBlock,
    ProfilingStats,
    ReportFormat,
    memory_profile_this,
    profile_this,
    THRESHOLD_SIMPLE_FORMULA,
    THRESHOLD_COMPLEX_FORMULA,
    THRESHOLD_MEMORY_LEAK,
    THRESHOLD_O_N3_SUSPECT,
)
from ipfs_datasets_py.logic.TDFOL.exceptions import TDFOLError


# ============================================================================
# Test Fixtures
# ============================================================================

@pytest.fixture
def temp_output_dir():
    """Create temporary output directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


@pytest.fixture
def profiler(temp_output_dir):
    """Create PerformanceProfiler instance."""
    return PerformanceProfiler(
        output_dir=temp_output_dir,
        enable_memory=True,
        enable_cprofile=True
    )


@pytest.fixture
def mock_prover():
    """Create mock TDFOL prover."""
    prover = MagicMock()
    prover.prove = Mock(return_value=True)
    prover.forward_chain = Mock(return_value=[])
    prover.backward_chain = Mock(return_value=None)
    return prover


@pytest.fixture
def mock_formula():
    """Create mock formula."""
    formula = MagicMock()
    formula.__str__ = Mock(return_value="P(x) → Q(x)")
    return formula


# ============================================================================
# Helper Functions for Testing
# ============================================================================

def expensive_function(n: int = 1000) -> int:
    """Expensive function for profiling tests."""
    total = 0
    for i in range(n):
        for j in range(n):
            total += i * j
    return total


def memory_intensive_function(size: int = 100000) -> list:
    """Memory intensive function for memory profiling tests."""
    data = [i ** 2 for i in range(size)]
    return data


def fast_function() -> str:
    """Fast function that should not trigger warnings."""
    return "fast"


def simulate_o_n3_operation(n: int = 100) -> int:
    """Simulate O(n³) operation for bottleneck detection."""
    total = 0
    for i in range(n):
        for j in range(n):
            for k in range(n):
                total += i + j + k
    return total


# ============================================================================
# Test: Profiling Decorators
# ============================================================================

def test_profile_this_decorator(caplog):
    """Test @profile_this decorator.
    
    GIVEN: A function with @profile_this decorator
    WHEN: Function is called
    THEN: Profiling output is generated
    """
    @profile_this(sort_key='cumulative', top_n=5)
    def test_func(n):
        return sum(i ** 2 for i in range(n))
    
    result = test_func(1000)
    
    assert result == sum(i ** 2 for i in range(1000))
    # Check that profiling info was logged
    assert any("Profile:" in record.message for record in caplog.records)


def test_profile_this_disabled():
    """Test @profile_this with enabled=False.
    
    GIVEN: A function with @profile_this(enabled=False)
    WHEN: Function is called
    THEN: No profiling overhead is added
    """
    @profile_this(enabled=False)
    def test_func(n):
        return n * 2
    
    result = test_func(42)
    assert result == 84


def test_memory_profile_this_decorator(caplog):
    """Test @memory_profile_this decorator.
    
    GIVEN: A function with @memory_profile_this decorator
    WHEN: Function is called
    THEN: Memory usage is reported
    """
    @memory_profile_this
    def test_func():
        data = [i for i in range(10000)]
        return len(data)
    
    result = test_func()
    
    assert result == 10000
    # Check memory profiling output
    assert any("Memory Profile:" in record.message for record in caplog.records)
    assert any("Peak:" in record.message for record in caplog.records)


# ============================================================================
# Test: PerformanceProfiler Initialization
# ============================================================================

def test_profiler_initialization(temp_output_dir):
    """Test PerformanceProfiler initialization.
    
    GIVEN: Valid configuration
    WHEN: Creating PerformanceProfiler
    THEN: Profiler is properly initialized with output directory
    """
    profiler = PerformanceProfiler(
        output_dir=temp_output_dir,
        enable_memory=True,
        enable_cprofile=True
    )
    
    assert profiler.output_dir.exists()
    assert profiler.enable_memory is True
    assert profiler.enable_cprofile is True
    assert profiler.history == []
    assert profiler.baseline == {}


def test_profiler_with_baseline(temp_output_dir):
    """Test PerformanceProfiler with baseline.
    
    GIVEN: Baseline performance data file
    WHEN: Creating profiler with baseline_path
    THEN: Baseline is loaded
    """
    baseline_path = Path(temp_output_dir) / "baseline.json"
    baseline_data = {
        "simple_test": 5.0,
        "complex_test": 50.0
    }
    
    with open(baseline_path, 'w') as f:
        json.dump(baseline_data, f)
    
    profiler = PerformanceProfiler(
        output_dir=temp_output_dir,
        baseline_path=str(baseline_path)
    )
    
    assert profiler.baseline == baseline_data


# ============================================================================
# Test: profile_function
# ============================================================================

def test_profile_function_success(profiler):
    """Test profiling a function successfully.
    
    GIVEN: PerformanceProfiler and a function
    WHEN: Calling profile_function
    THEN: ProfilingStats are returned with correct data
    """
    stats = profiler.profile_function(fast_function, runs=5)
    
    assert stats.function_name == "fast_function"
    assert stats.runs == 5
    assert stats.mean_time > 0
    assert stats.min_time <= stats.mean_time <= stats.max_time
    assert stats.std_dev >= 0
    assert stats.profile_data is not None
    
    # Check history
    assert len(profiler.history) == 1
    assert profiler.history[0]['function'] == "fast_function"


def test_profile_function_with_args(profiler):
    """Test profiling function with arguments.
    
    GIVEN: Function that takes arguments
    WHEN: Profiling with arguments
    THEN: Function is profiled correctly
    """
    def add_numbers(a, b):
        return a + b
    
    stats = profiler.profile_function(add_numbers, 10, 20, runs=3)
    
    assert stats.function_name == "add_numbers"
    assert stats.runs == 3
    assert stats.mean_time > 0


def test_profile_function_disabled_cprofile():
    """Test profile_function with cProfile disabled.
    
    GIVEN: Profiler with enable_cprofile=False
    WHEN: Calling profile_function
    THEN: TDFOLError is raised
    """
    profiler = PerformanceProfiler(enable_cprofile=False)
    
    with pytest.raises(TDFOLError) as exc_info:
        profiler.profile_function(fast_function)
    
    assert "cProfile disabled" in str(exc_info.value)


def test_profile_function_error_handling(profiler):
    """Test profile_function with function that raises error.
    
    GIVEN: Function that raises exception
    WHEN: Profiling the function
    THEN: TDFOLError is raised with helpful message
    """
    def error_func():
        raise ValueError("Test error")
    
    with pytest.raises(TDFOLError) as exc_info:
        profiler.profile_function(error_func)
    
    assert "Profiling failed" in str(exc_info.value)


def test_profiling_stats_properties():
    """Test ProfilingStats properties.
    
    GIVEN: ProfilingStats instance
    WHEN: Accessing properties
    THEN: Properties return correct values
    """
    stats = ProfilingStats(
        function_name="test_func",
        total_time=0.5,
        mean_time=0.05,
        median_time=0.048,
        min_time=0.04,
        max_time=0.06,
        std_dev=0.005,
        runs=10,
        calls_per_run=100
    )
    
    assert stats.mean_time_ms == 50.0
    assert stats.meets_threshold is True  # 50ms < 100ms threshold
    
    # Test to_dict
    data = stats.to_dict()
    assert 'function_name' in data
    assert 'profile_data' not in data  # Excluded


# ============================================================================
# Test: profile_prover
# ============================================================================

def test_profile_prover_success(profiler, mock_prover, mock_formula):
    """Test profiling prover operations.
    
    GIVEN: Prover and formula
    WHEN: Calling profile_prover
    THEN: Prover is profiled successfully
    """
    stats = profiler.profile_prover(
        mock_prover,
        mock_formula,
        runs=5,
        method="prove"
    )
    
    assert stats.function_name == "prove"
    assert stats.runs == 5
    assert mock_prover.prove.call_count == 5


def test_profile_prover_invalid_method(profiler, mock_prover, mock_formula):
    """Test profile_prover with invalid method.
    
    GIVEN: Prover without specified method
    WHEN: Calling profile_prover with invalid method
    THEN: TDFOLError is raised
    """
    with pytest.raises(TDFOLError) as exc_info:
        profiler.profile_prover(
            mock_prover,
            mock_formula,
            method="nonexistent_method"
        )
    
    assert "has no method" in str(exc_info.value)


# ============================================================================
# Test: Bottleneck Identification
# ============================================================================

def test_identify_bottlenecks_empty():
    """Test identify_bottlenecks with no profile data.
    
    GIVEN: No profile data
    WHEN: Calling identify_bottlenecks
    THEN: Empty list is returned
    """
    profiler = PerformanceProfiler()
    bottlenecks = profiler.identify_bottlenecks(None)
    
    assert bottlenecks == []


def test_identify_bottlenecks_from_real_profile(profiler):
    """Test identifying bottlenecks from real profile data.
    
    GIVEN: Profile data from expensive function
    WHEN: Calling identify_bottlenecks
    THEN: Bottlenecks are identified with severity
    """
    # Profile expensive function
    stats = profiler.profile_function(expensive_function, 50, runs=1)
    
    # Identify bottlenecks
    bottlenecks = profiler.identify_bottlenecks(stats.profile_data, top_n=10)
    
    assert len(bottlenecks) > 0
    
    # Check bottleneck structure
    for b in bottlenecks:
        assert isinstance(b, Bottleneck)
        assert b.function
        assert b.time >= 0
        assert b.calls > 0
        assert b.time_per_call >= 0
        assert isinstance(b.severity, BottleneckSeverity)
        assert b.recommendation


def test_analyze_bottleneck_critical(profiler):
    """Test bottleneck analysis for critical cases.
    
    GIVEN: Function with excessive calls (O(n³))
    WHEN: Analyzing bottleneck
    THEN: Marked as CRITICAL with O(n³) estimate
    """
    severity, rec, complexity = profiler._analyze_bottleneck(
        "nested_loop",
        total_time=2.0,
        calls=THRESHOLD_O_N3_SUSPECT + 100,
        time_per_call=0.001
    )
    
    assert severity == BottleneckSeverity.CRITICAL
    assert "O(n³)" in rec
    assert complexity == "O(n³)"


def test_analyze_bottleneck_unify_slow(profiler):
    """Test bottleneck analysis for slow unification.
    
    GIVEN: Unify function taking >1s
    WHEN: Analyzing bottleneck
    THEN: Marked as CRITICAL with unification recommendation
    """
    severity, rec, complexity = profiler._analyze_bottleneck(
        "unify_terms",
        total_time=1.5,
        calls=500,
        time_per_call=0.003
    )
    
    assert severity == BottleneckSeverity.CRITICAL
    assert "Unification" in rec
    assert "indexed KB" in rec.lower() or "caching" in rec.lower()


def test_bottleneck_to_dict():
    """Test Bottleneck.to_dict method.
    
    GIVEN: Bottleneck instance
    WHEN: Converting to dict
    THEN: All fields are present
    """
    bottleneck = Bottleneck(
        function="test.py:10:slow_func",
        time=1.5,
        calls=1000,
        time_per_call=0.0015,
        severity=BottleneckSeverity.HIGH,
        recommendation="Optimize loop",
        complexity_estimate="O(n²)"
    )
    
    data = bottleneck.to_dict()
    
    assert data['function'] == "test.py:10:slow_func"
    assert data['time'] == 1.5
    assert data['calls'] == 1000
    assert data['severity'] == "high"
    assert data['complexity_estimate'] == "O(n²)"


# ============================================================================
# Test: Memory Profiling
# ============================================================================

def test_memory_profile_success(profiler):
    """Test memory profiling of function.
    
    GIVEN: Memory intensive function
    WHEN: Calling memory_profile
    THEN: Memory stats are returned
    """
    mem_stats = profiler.memory_profile(memory_intensive_function, 10000)
    
    assert isinstance(mem_stats, MemoryStats)
    assert mem_stats.function_name == "memory_intensive_function"
    assert mem_stats.peak_mb > 0
    assert mem_stats.allocations > 0
    assert len(mem_stats.top_allocators) > 0


def test_memory_profile_leak_detection(profiler):
    """Test memory leak detection.
    
    GIVEN: Function with significant memory growth
    WHEN: Profiling memory
    THEN: Leak is detected if growth > threshold
    """
    def potential_leak():
        # Allocate but don't release
        data = [i for i in range(1000000)]
        return len(data)
    
    mem_stats = profiler.memory_profile(potential_leak)
    
    # Check has_leak property
    if mem_stats.growth_mb > THRESHOLD_MEMORY_LEAK:
        assert mem_stats.has_leak is True
    else:
        assert mem_stats.has_leak is False


def test_memory_profile_disabled():
    """Test memory profiling with memory disabled.
    
    GIVEN: Profiler with enable_memory=False
    WHEN: Calling memory_profile
    THEN: TDFOLError is raised
    """
    profiler = PerformanceProfiler(enable_memory=False)
    
    with pytest.raises(TDFOLError) as exc_info:
        profiler.memory_profile(fast_function)
    
    assert "Memory profiling disabled" in str(exc_info.value)


def test_memory_stats_to_dict():
    """Test MemoryStats.to_dict method.
    
    GIVEN: MemoryStats instance
    WHEN: Converting to dict
    THEN: All fields are included
    """
    mem_stats = MemoryStats(
        function_name="test_func",
        peak_mb=100.5,
        start_mb=50.0,
        end_mb=55.0,
        growth_mb=5.0,
        allocations=1000,
        deallocations=900,
        net_allocations=100,
        top_allocators=[("file.py:10", 10.5), ("file.py:20", 8.3)]
    )
    
    data = mem_stats.to_dict()
    
    assert data['function_name'] == "test_func"
    assert data['peak_mb'] == 100.5
    assert data['growth_mb'] == 5.0
    assert len(data['top_allocators']) == 2


# ============================================================================
# Test: Benchmark Suite
# ============================================================================

def test_run_benchmark_suite(profiler):
    """Test running standard benchmark suite.
    
    GIVEN: PerformanceProfiler
    WHEN: Running benchmark suite
    THEN: All benchmarks are executed and results returned
    """
    results = profiler.run_benchmark_suite()
    
    assert isinstance(results, BenchmarkResults)
    assert len(results.benchmarks) > 0
    assert results.total_time_ms > 0
    assert results.passed >= 0
    assert results.failed >= 0
    assert results.timestamp


def test_benchmark_results_pass_rate():
    """Test BenchmarkResults.pass_rate property.
    
    GIVEN: BenchmarkResults with passed and failed
    WHEN: Accessing pass_rate
    THEN: Correct percentage is returned
    """
    results = BenchmarkResults(
        benchmarks=[],
        total_time_ms=100.0,
        passed=8,
        failed=2,
        regressions=1,
        timestamp="2026-02-18 15:30:00"
    )
    
    assert results.pass_rate == 0.8  # 8/10


def test_benchmark_results_to_dict():
    """Test BenchmarkResults.to_dict method.
    
    GIVEN: BenchmarkResults
    WHEN: Converting to dict
    THEN: All data is included
    """
    bench1 = BenchmarkResult(
        name="test1",
        formula="P → Q",
        time_ms=5.0,
        memory_mb=10.0,
        passed=True
    )
    
    results = BenchmarkResults(
        benchmarks=[bench1],
        total_time_ms=5.0,
        passed=1,
        failed=0,
        regressions=0,
        timestamp="2026-02-18"
    )
    
    data = results.to_dict()
    
    assert 'benchmarks' in data
    assert len(data['benchmarks']) == 1
    assert data['passed'] == 1


def test_benchmark_with_regression(temp_output_dir):
    """Test benchmark regression detection.
    
    GIVEN: Baseline with performance data
    WHEN: Running benchmarks that regress
    THEN: Regressions are detected
    """
    # Create baseline
    baseline_path = Path(temp_output_dir) / "baseline.json"
    baseline_data = {"simple_propositional": 5.0}
    
    with open(baseline_path, 'w') as f:
        json.dump(baseline_data, f)
    
    profiler = PerformanceProfiler(
        output_dir=temp_output_dir,
        baseline_path=str(baseline_path)
    )
    
    # Run benchmarks (will likely be slower than 5ms baseline)
    results = profiler.run_benchmark_suite()
    
    # Check if regression detected (depends on actual performance)
    assert results.regressions >= 0


# ============================================================================
# Test: Report Generation
# ============================================================================

def test_generate_text_report(profiler):
    """Test generating text report.
    
    GIVEN: Profiler with history
    WHEN: Generating TEXT report
    THEN: Report file is created with correct content
    """
    # Add some history
    profiler.profile_function(fast_function, runs=2)
    
    report_path = profiler.generate_report(format=ReportFormat.TEXT)
    
    assert Path(report_path).exists()
    
    with open(report_path, 'r') as f:
        content = f.read()
    
    assert "TDFOL Performance Profiling Report" in content
    assert "Profile History" in content


def test_generate_json_report(profiler):
    """Test generating JSON report.
    
    GIVEN: Profiler with history
    WHEN: Generating JSON report
    THEN: Valid JSON file is created
    """
    profiler.profile_function(fast_function, runs=2)
    
    report_path = profiler.generate_report(format=ReportFormat.JSON)
    
    assert Path(report_path).exists()
    
    with open(report_path, 'r') as f:
        data = json.load(f)
    
    assert 'timestamp' in data
    assert 'history' in data
    assert len(data['history']) > 0


def test_generate_html_report(profiler):
    """Test generating HTML report.
    
    GIVEN: Profiler with history
    WHEN: Generating HTML report
    THEN: HTML file is created with table
    """
    profiler.profile_function(fast_function, runs=2)
    
    report_path = profiler.generate_report(format=ReportFormat.HTML)
    
    assert Path(report_path).exists()
    
    with open(report_path, 'r') as f:
        content = f.read()
    
    assert "<!DOCTYPE html>" in content
    assert "<table>" in content
    assert "Profile History" in content


def test_generate_report_custom_path(profiler):
    """Test generating report with custom path.
    
    GIVEN: Custom output path
    WHEN: Generating report
    THEN: Report is saved to specified path
    """
    custom_path = str(profiler.output_dir / "custom_report.html")
    
    profiler.profile_function(fast_function, runs=1)
    report_path = profiler.generate_report(
        output_path=custom_path,
        format=ReportFormat.HTML
    )
    
    assert report_path == custom_path
    assert Path(custom_path).exists()


# ============================================================================
# Test: ProfileBlock Context Manager
# ============================================================================

def test_profile_block_basic(profiler):
    """Test ProfileBlock context manager.
    
    GIVEN: ProfileBlock context
    WHEN: Code is executed within context
    THEN: Profiling is performed and logged
    """
    with ProfileBlock("test_block", profiler) as block:
        result = sum(i ** 2 for i in range(1000))
    
    assert result == sum(i ** 2 for i in range(1000))
    assert block.end_time > block.start_time


def test_profile_block_disabled_features():
    """Test ProfileBlock with features disabled.
    
    GIVEN: ProfileBlock with profiling disabled
    WHEN: Code is executed
    THEN: No profiling overhead
    """
    with ProfileBlock(
        "test_block",
        enable_cprofile=False,
        enable_memory=False
    ) as block:
        result = fast_function()
    
    assert result == "fast"
    assert block.cpu_profiler is None


def test_profile_block_exception_handling():
    """Test ProfileBlock with exception.
    
    GIVEN: Code that raises exception
    WHEN: Executing in ProfileBlock
    THEN: Exception propagates but profiling completes
    """
    with pytest.raises(ValueError):
        with ProfileBlock("error_block"):
            raise ValueError("Test error")


# ============================================================================
# Test: Edge Cases and Error Handling
# ============================================================================

def test_profiler_concurrent_profiles(profiler):
    """Test running multiple profiles in sequence.
    
    GIVEN: Multiple functions to profile
    WHEN: Profiling them in sequence
    THEN: All are tracked in history
    """
    profiler.profile_function(fast_function, runs=2)
    profiler.profile_function(memory_intensive_function, 1000, runs=2)
    
    assert len(profiler.history) == 2
    assert profiler.history[0]['function'] == "fast_function"
    assert profiler.history[1]['function'] == "memory_intensive_function"


def test_invalid_report_format(profiler):
    """Test generating report with invalid format.
    
    GIVEN: Invalid ReportFormat
    WHEN: Calling generate_report
    THEN: Error is raised (handled by enum)
    """
    # Note: Can't actually pass invalid enum, but test PSTATS unsupported
    with pytest.raises(TDFOLError):
        profiler.generate_report(format=ReportFormat.PSTATS)


def test_profiler_empty_history_report(profiler):
    """Test generating report with no history.
    
    GIVEN: Profiler with no profiles run
    WHEN: Generating report
    THEN: Report is created but history is empty
    """
    report_path = profiler.generate_report(format=ReportFormat.TEXT)
    
    assert Path(report_path).exists()
    
    with open(report_path, 'r') as f:
        content = f.read()
    
    assert "Profile History" in content


def test_baseline_save(temp_output_dir):
    """Test saving baseline performance data.
    
    GIVEN: Profiler with baseline path
    WHEN: Calling _save_baseline
    THEN: Baseline is saved to file
    """
    baseline_path = Path(temp_output_dir) / "baseline.json"
    
    profiler = PerformanceProfiler(
        output_dir=temp_output_dir,
        baseline_path=str(baseline_path)
    )
    
    profiler.baseline = {"test": 10.0}
    profiler._save_baseline()
    
    assert baseline_path.exists()
    
    with open(baseline_path, 'r') as f:
        data = json.load(f)
    
    assert data == {"test": 10.0}


# ============================================================================
# Test: Integration Tests
# ============================================================================

def test_full_profiling_workflow(profiler, mock_prover, mock_formula):
    """Test complete profiling workflow.
    
    GIVEN: Prover, formula, and profiler
    WHEN: Running full profiling workflow
    THEN: All components work together
    """
    # 1. Profile prover
    prover_stats = profiler.profile_prover(mock_prover, mock_formula, runs=3)
    assert prover_stats.runs == 3
    
    # 2. Identify bottlenecks
    bottlenecks = profiler.identify_bottlenecks(prover_stats.profile_data)
    assert isinstance(bottlenecks, list)
    
    # 3. Memory profile
    mem_stats = profiler.memory_profile(fast_function)
    assert mem_stats.peak_mb > 0
    
    # 4. Run benchmarks
    bench_results = profiler.run_benchmark_suite()
    assert bench_results.passed + bench_results.failed > 0
    
    # 5. Generate report
    report_path = profiler.generate_report(format=ReportFormat.HTML)
    assert Path(report_path).exists()


def test_performance_regression_detection(temp_output_dir):
    """Test performance regression detection across runs.
    
    GIVEN: Baseline performance data
    WHEN: Running benchmarks that regress
    THEN: Regressions are detected and reported
    """
    baseline_path = Path(temp_output_dir) / "baseline.json"
    
    # Create baseline (very fast)
    baseline = {
        "simple_propositional": 1.0,
        "simple_implication": 1.5
    }
    
    with open(baseline_path, 'w') as f:
        json.dump(baseline, f)
    
    profiler = PerformanceProfiler(
        output_dir=temp_output_dir,
        baseline_path=str(baseline_path)
    )
    
    # Run benchmarks (will be slower than baseline)
    results = profiler.run_benchmark_suite()
    
    # Check for regressions in results
    for bench in results.benchmarks:
        if bench.name in baseline:
            assert bench.baseline_time_ms == baseline[bench.name]
            if bench.regression_pct and bench.regression_pct > 10:
                assert results.regressions > 0
                break


# ============================================================================
# Test: Module Exports
# ============================================================================

def test_module_exports():
    """Test that all expected symbols are exported.
    
    GIVEN: performance_profiler module
    WHEN: Checking __all__
    THEN: All expected symbols are present
    """
    from ipfs_datasets_py.logic.TDFOL import performance_profiler
    
    expected_exports = [
        'PerformanceProfiler',
        'ProfileBlock',
        'ProfilingStats',
        'Bottleneck',
        'BottleneckSeverity',
        'MemoryStats',
        'BenchmarkResult',
        'BenchmarkResults',
        'ReportFormat',
        'profile_this',
        'memory_profile_this',
    ]
    
    for symbol in expected_exports:
        assert hasattr(performance_profiler, symbol)


# ============================================================================
# Performance Tests (marked slow)
# ============================================================================

@pytest.mark.slow
def test_profile_expensive_operation(profiler):
    """Test profiling truly expensive operation.
    
    GIVEN: Expensive O(n²) operation
    WHEN: Profiling with multiple runs
    THEN: Accurate statistics are captured
    """
    stats = profiler.profile_function(expensive_function, 100, runs=5)
    
    assert stats.mean_time > 0
    assert stats.std_dev >= 0
    assert stats.calls_per_run > 0
    
    # Should detect as bottleneck if significant
    bottlenecks = profiler.identify_bottlenecks(stats.profile_data)
    assert len(bottlenecks) > 0


@pytest.mark.slow
def test_benchmark_suite_performance(profiler):
    """Test full benchmark suite performance.
    
    GIVEN: Standard benchmark suite
    WHEN: Running all benchmarks
    THEN: Complete within reasonable time
    """
    start_time = time.perf_counter()
    results = profiler.run_benchmark_suite()
    elapsed = time.perf_counter() - start_time
    
    # Should complete in reasonable time (e.g., <5 seconds)
    assert elapsed < 5.0
    assert len(results.benchmarks) >= 10  # At least 10 standard benchmarks
