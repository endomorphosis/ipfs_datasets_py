# TDFOL Performance Profiler

Comprehensive performance profiling infrastructure for TDFOL (Temporal Deontic First-Order Logic) operations. This module provides production-ready profiling tools for identifying bottlenecks, tracking memory usage, running benchmarks, and generating detailed reports.

**Phase 12 Task 12.1** - Performance Optimization Infrastructure

## 🎯 Overview

The TDFOL Performance Profiler enables:

1. **CPU Profiling** - Profile TDFOL operations with cProfile
2. **Bottleneck Identification** - Automatically detect slow functions and O(n³) operations
3. **Memory Profiling** - Track memory usage, detect leaks, identify peak consumption
4. **Benchmark Suite** - Standard benchmarks for regression testing
5. **Report Generation** - HTML, JSON, and text reports with visualizations
6. **CI/CD Integration** - Ready for continuous performance monitoring

## 📦 Features

### 1. cProfile Integration (3h)

- **Decorators**: `@profile_this` and `@memory_profile_this` for easy profiling
- **Function Profiling**: Profile any function with detailed statistics
- **Prover Profiling**: Specialized profiling for TDFOL prover operations
- **Context Managers**: `ProfileBlock` for profiling code blocks
- **Multiple Formats**: Export to text, pstats, JSON

```python
from ipfs_datasets_py.logic.TDFOL.performance_profiler import profile_this

@profile_this
def expensive_operation(n):
    return sum(i**2 for i in range(n))

result = expensive_operation(100000)
# Automatically prints profiling stats
```

### 2. Bottleneck Identification (3h)

- **Automatic Detection**: Identify slow functions (>1ms, >10ms, >100ms, >1s)
- **O(n³) Detection**: Find operations with excessive calls
- **Severity Levels**: CRITICAL, HIGH, MEDIUM, LOW
- **Recommendations**: Actionable suggestions for each bottleneck
- **Complexity Estimation**: Estimated algorithmic complexity (O(n), O(n²), O(n³))

```python
profiler = PerformanceProfiler()
stats = profiler.profile_function(expensive_op, runs=10)

bottlenecks = profiler.identify_bottlenecks(stats.profile_data)
for b in bottlenecks[:5]:
    print(f"{b.severity.value}: {b.function}")
    print(f"  Time: {b.time:.3f}s ({b.calls} calls)")
    print(f"  Fix: {b.recommendation}")
```

### 3. Memory Profiling (3h)

- **Memory Tracking**: Track memory usage with tracemalloc
- **Leak Detection**: Automatically detect memory leaks (>5MB growth)
- **Peak Memory**: Track peak memory consumption
- **Allocation Tracking**: Count allocations and deallocations
- **Top Allocators**: Identify functions allocating most memory

```python
profiler = PerformanceProfiler(enable_memory=True)
mem_stats = profiler.memory_profile(memory_intensive_func, arg1, arg2)

print(f"Peak: {mem_stats.peak_mb:.1f}MB")
print(f"Growth: {mem_stats.growth_mb:.1f}MB")
if mem_stats.has_leak:
    print("⚠ Possible memory leak detected!")
```

### 4. Benchmark Suite (1h)

- **Standard Benchmarks**: 10+ standard formulas (simple to complex)
- **Regression Detection**: Compare against baseline performance
- **Pass/Fail**: Benchmarks must meet performance thresholds
- **Regression Tracking**: Track performance over time
- **CI/CD Ready**: JSON output for automated testing

```python
profiler = PerformanceProfiler(baseline_path="baseline.json")
results = profiler.run_benchmark_suite()

print(f"Pass rate: {results.pass_rate:.1%}")
print(f"Regressions: {results.regressions}")

for bench in results.benchmarks:
    if not bench.passed:
        print(f"Failed: {bench.name} ({bench.time_ms:.1f}ms)")
```

## 🚀 Quick Start

### Installation

The profiler is part of the TDFOL module:

```bash
# Already installed with TDFOL
cd ipfs_datasets_py
pip install -e .
```

### Basic Usage

```python
from ipfs_datasets_py.logic.TDFOL.performance_profiler import PerformanceProfiler

# Initialize profiler
profiler = PerformanceProfiler(
    output_dir="profiling_results",
    enable_memory=True,
    enable_cprofile=True
)

# Profile a function
def my_operation(n):
    return sum(i**2 for i in range(n))

stats = profiler.profile_function(my_operation, 10000, runs=10)
print(f"Mean time: {stats.mean_time_ms:.2f}ms")

# Generate report
profiler.generate_report(format=ReportFormat.HTML)
```

### Profiling TDFOL Prover

```python
from ipfs_datasets_py.logic.TDFOL.tdfol_prover import TDFOLProver
from ipfs_datasets_py.logic.TDFOL.tdfol_parser import parse_tdfol
from ipfs_datasets_py.logic.TDFOL.performance_profiler import PerformanceProfiler

# Create prover and formula
prover = TDFOLProver(kb)
formula = parse_tdfol("∀x. (P(x) → Q(x))")

# Profile proving
profiler = PerformanceProfiler()
stats = profiler.profile_prover(prover, formula, runs=20)

print(f"Proving time: {stats.mean_time_ms:.2f}ms")
if not stats.meets_threshold:
    print("⚠ Warning: Proving too slow!")
    
    # Find bottlenecks
    bottlenecks = profiler.identify_bottlenecks(stats.profile_data)
    for b in bottlenecks[:3]:
        print(f"  {b.function}: {b.recommendation}")
```

## 📊 API Reference

### PerformanceProfiler

Main profiling interface.

#### Methods

**`__init__(output_dir, enable_memory=True, enable_cprofile=True, baseline_path=None)`**

Initialize profiler.

**`profile_function(func, *args, runs=10, **kwargs) -> ProfilingStats`**

Profile a function with cProfile.

- `func`: Function to profile
- `*args, **kwargs`: Function arguments
- `runs`: Number of profiling runs (default: 10)
- Returns: `ProfilingStats` with timing and call data

**`profile_prover(prover, formula, runs=10, method="prove") -> ProfilingStats`**

Profile TDFOL prover operations.

- `prover`: TDFOLProver instance
- `formula`: Formula to prove
- `runs`: Number of proving runs
- `method`: Prover method name ("prove", "forward_chain", etc.)
- Returns: `ProfilingStats`

**`identify_bottlenecks(profile_data, top_n=20, min_time=0.001) -> List[Bottleneck]`**

Identify performance bottlenecks.

- `profile_data`: pstats.Stats object from profiling
- `top_n`: Number of bottlenecks to return
- `min_time`: Minimum time threshold (seconds)
- Returns: List of `Bottleneck` objects sorted by severity

**`memory_profile(func, *args, **kwargs) -> MemoryStats`**

Profile memory usage.

- `func`: Function to profile
- `*args, **kwargs`: Function arguments
- Returns: `MemoryStats` with memory usage data

**`run_benchmark_suite(custom_benchmarks=None) -> BenchmarkResults`**

Run standard benchmark suite.

- `custom_benchmarks`: Optional custom benchmarks
- Returns: `BenchmarkResults` with all results

**`generate_report(output_path=None, format=ReportFormat.HTML, ...) -> str`**

Generate comprehensive profiling report.

- `output_path`: Output file path (auto-generated if None)
- `format`: Report format (TEXT, JSON, HTML)
- `include_bottlenecks`: Include bottleneck analysis
- `include_memory`: Include memory profiling
- `include_benchmarks`: Include benchmark results
- Returns: Path to generated report

### Decorators

**`@profile_this(enabled=True, sort_key='cumulative', top_n=20, print_stats=True)`**

Decorator for profiling functions.

```python
@profile_this
def expensive_function(n):
    return sum(i**2 for i in range(n))
```

**`@memory_profile_this`**

Decorator for memory profiling.

```python
@memory_profile_this
def memory_intensive():
    data = [i for i in range(1000000)]
    return len(data)
```

### Context Manager

**`ProfileBlock(name, profiler=None, enable_cprofile=True, enable_memory=True)`**

Context manager for profiling code blocks.

```python
with ProfileBlock("data_processing", profiler):
    # Code to profile
    result = process_data(data)
```

### Data Classes

**`ProfilingStats`**

- `function_name`: Function name
- `mean_time`, `median_time`, `min_time`, `max_time`: Timing stats (seconds)
- `std_dev`: Standard deviation
- `runs`: Number of runs
- `mean_time_ms`: Mean time in milliseconds
- `meets_threshold`: Whether performance meets threshold

**`Bottleneck`**

- `function`: Function name (module:line:function)
- `time`: Cumulative time (seconds)
- `calls`: Number of calls
- `time_per_call`: Average time per call
- `severity`: BottleneckSeverity (CRITICAL, HIGH, MEDIUM, LOW)
- `recommendation`: How to fix
- `complexity_estimate`: Estimated complexity (O(n), O(n²), O(n³))

**`MemoryStats`**

- `peak_mb`, `start_mb`, `end_mb`, `growth_mb`: Memory usage (MB)
- `allocations`, `deallocations`, `net_allocations`: Allocation counts
- `top_allocators`: List of (location, size_mb)
- `has_leak`: Whether leak suspected (growth > 5MB)

**`BenchmarkResults`**

- `benchmarks`: List of `BenchmarkResult`
- `total_time_ms`: Total suite time
- `passed`, `failed`: Pass/fail counts
- `regressions`: Number of regressions
- `pass_rate`: Pass percentage

## 📈 Performance Thresholds

The profiler uses these thresholds to determine performance:

| Metric | Threshold | Description |
|--------|-----------|-------------|
| Simple formula | 10ms | Simple propositional/quantified formulas |
| Complex formula | 100ms | Complex nested/temporal/deontic formulas |
| Parse + prove | 50ms | Full pipeline (parse + prove) |
| Cached result | 1ms | Cache hit should be <1ms |
| Memory overhead | 50MB | KB with 1000 formulas |
| Memory leak | 5MB | Growth >5MB may indicate leak |
| O(n³) suspect | 1000 calls | >1000 calls in nested loop |
| Cache hit rate | 80% | Should achieve >80% cache hits |

## 📋 Benchmark Suite

Standard benchmarks included:

1. **simple_propositional** - `P ∧ Q` (< 10ms)
2. **simple_implication** - `P → Q` (< 10ms)
3. **quantified_simple** - `∀x. P(x)` (< 20ms)
4. **quantified_complex** - `∀x. ∃y. (P(x) → Q(x, y))` (< 100ms)
5. **temporal_always** - `□P` (< 10ms)
6. **temporal_eventually** - `◊P` (< 10ms)
7. **temporal_until** - `P U Q` (< 100ms)
8. **deontic_obligation** - `O(P)` (< 10ms)
9. **deontic_permission** - `P(Q)` (< 10ms)
10. **mixed_temporal_deontic** - `□O(P) → ◊P` (< 100ms)

## 📊 Report Formats

### TEXT Report

Plain text report with profiling history:

```
================================================================================
TDFOL Performance Profiling Report
================================================================================
Generated: 2026-02-18 15:30:45
Output Dir: profiling_results

Profile History
--------------------------------------------------------------------------------
Total profiles: 5

Function: prove_formula
Timestamp: 2026-02-18 15:30:42
Mean time: 25.30ms
Runs: 10
...
```

### JSON Report

Machine-readable JSON for CI/CD:

```json
{
  "timestamp": "2026-02-18 15:30:45",
  "output_dir": "profiling_results",
  "history": [
    {
      "function": "prove_formula",
      "timestamp": "2026-02-18 15:30:42",
      "stats": {
        "mean_time": 0.02530,
        "runs": 10,
        ...
      }
    }
  ]
}
```

### HTML Report

Rich HTML report with tables and charts:

```html
<!DOCTYPE html>
<html>
<head>
    <title>TDFOL Performance Report</title>
    <style>...</style>
</head>
<body>
    <h1>TDFOL Performance Profiling Report</h1>
    <table>
        <tr>
            <th>Function</th>
            <th>Mean Time (ms)</th>
            <th>Runs</th>
        </tr>
        ...
    </table>
</body>
</html>
```

## 🔧 Advanced Usage

### Regression Testing in CI/CD

```python
import sys
from ipfs_datasets_py.logic.TDFOL.performance_profiler import (
    PerformanceProfiler,
    ReportFormat
)

# Initialize with baseline
profiler = PerformanceProfiler(
    output_dir="ci_profiling",
    baseline_path="baseline.json"
)

# Run benchmarks
results = profiler.run_benchmark_suite()

# Check for regressions
if results.regressions > 0:
    print(f"⚠ {results.regressions} performance regressions detected!")
    sys.exit(1)

# Generate report
profiler.generate_report(format=ReportFormat.JSON)
print(f"✓ All benchmarks passed ({results.pass_rate:.1%})")
```

### Custom Benchmarks

```python
custom_benchmarks = [
    {
        'name': 'my_custom_benchmark',
        'formula': '∀x. (Custom(x) → Result(x))',
        'threshold_ms': 50.0,
        'func': lambda: my_custom_operation()
    }
]

results = profiler.run_benchmark_suite(custom_benchmarks=custom_benchmarks)
```

### Profiling with Baseline Comparison

```python
# First run - establish baseline
profiler = PerformanceProfiler(
    output_dir="profiling_results",
    baseline_path="baseline.json"
)

results = profiler.run_benchmark_suite()
profiler._save_baseline()  # Save current performance as baseline

# Later runs - compare against baseline
profiler2 = PerformanceProfiler(
    output_dir="profiling_results",
    baseline_path="baseline.json"
)

results2 = profiler2.run_benchmark_suite()

# Check for regressions
for bench in results2.benchmarks:
    if bench.regression_pct and bench.regression_pct > 10:
        print(f"Regression: {bench.name} is {bench.regression_pct:.1f}% slower")
```

## 🧪 Testing

The profiler includes 20+ comprehensive tests:

```bash
# Run all profiler tests
pytest tests/unit/logic/TDFOL/test_performance_profiler.py -v

# Run specific test
pytest tests/unit/logic/TDFOL/test_performance_profiler.py::test_profile_function_success

# Run with coverage
pytest tests/unit/logic/TDFOL/test_performance_profiler.py --cov=ipfs_datasets_py.logic.TDFOL.performance_profiler
```

## 📚 Examples

See `example_performance_profiler.py` for 8 comprehensive examples:

1. Using decorators for simple profiling
2. Profiling TDFOL prover operations
3. Bottleneck identification
4. Memory profiling and leak detection
5. Running benchmark suite
6. Generating reports (TEXT, JSON, HTML)
7. ProfileBlock context manager
8. Complete workflow

```bash
# Run examples
python ipfs_datasets_py/logic/TDFOL/example_performance_profiler.py
```

## 🔗 Integration

### With Performance Dashboard

```python
from ipfs_datasets_py.logic.TDFOL.performance_profiler import PerformanceProfiler
from ipfs_datasets_py.logic.TDFOL.performance_dashboard import PerformanceDashboard

# Profile operations
profiler = PerformanceProfiler()
stats = profiler.profile_prover(prover, formula)

# Send to dashboard
dashboard = PerformanceDashboard()
dashboard.record_metric("proving_time", stats.mean_time_ms)
```

### With Optimization Module

```python
from ipfs_datasets_py.logic.TDFOL.performance_profiler import PerformanceProfiler
from ipfs_datasets_py.logic.TDFOL.tdfol_optimization import OptimizedProver

# Profile standard prover
profiler = PerformanceProfiler()
stats_standard = profiler.profile_prover(standard_prover, formula)

# Profile optimized prover
stats_optimized = profiler.profile_prover(optimized_prover, formula)

# Compare
speedup = stats_standard.mean_time / stats_optimized.mean_time
print(f"Speedup: {speedup:.1f}x faster")
```

## 🐛 Troubleshooting

### Issue: "cProfile disabled" error

**Solution**: Enable cProfile when creating profiler:

```python
profiler = PerformanceProfiler(enable_cprofile=True)
```

### Issue: "Memory profiling disabled" error

**Solution**: Enable memory profiling:

```python
profiler = PerformanceProfiler(enable_memory=True)
```

### Issue: Profiling shows no bottlenecks

**Solution**: Increase profiling runs or lower min_time threshold:

```python
stats = profiler.profile_function(func, runs=100)
bottlenecks = profiler.identify_bottlenecks(stats.profile_data, min_time=0.0001)
```

### Issue: Memory leak false positives

**Solution**: Python's garbage collector may delay deallocation. Run multiple times:

```python
# Warm up
for _ in range(3):
    func()

# Then profile
mem_stats = profiler.memory_profile(func)
```

## 🚦 Best Practices

1. **Profile with multiple runs** (10-20) for accurate statistics
2. **Use decorators** for persistent profiling in development
3. **Check bottlenecks** after profiling to identify optimization targets
4. **Track baselines** for regression detection in CI/CD
5. **Memory profile** operations that allocate large data structures
6. **Generate reports** regularly to track performance over time
7. **Set realistic thresholds** based on your use case
8. **Profile in production-like environment** for accurate results

## 📄 License

Part of IPFS Datasets Python project. See LICENSE file.

## 🤝 Contributing

See CONTRIBUTING.md for contribution guidelines.

## 📞 Support

- Issues: GitHub Issues
- Docs: `docs/TDFOL/`
- Examples: `example_performance_profiler.py`

---

**Author**: TDFOL Team  
**Date**: 2026-02-18  
**Phase**: 12 (Performance Optimization)  
**Task**: 12.1 (Profiling Infrastructure)
