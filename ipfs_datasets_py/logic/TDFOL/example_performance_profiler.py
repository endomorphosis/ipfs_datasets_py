"""
Example Usage: TDFOL Performance Profiler

This example demonstrates all features of the TDFOL Performance Profiler:
1. Function profiling with decorators
2. Prover operation profiling
3. Bottleneck identification
4. Memory profiling
5. Benchmark suite
6. Report generation

Author: TDFOL Team
Date: 2026-02-18
Phase: 12 (Performance Optimization)
Task: 12.1 (Profiling Infrastructure)
"""

import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from ipfs_datasets_py.logic.TDFOL.performance_profiler import (
    PerformanceProfiler,
    ProfileBlock,
    ReportFormat,
    profile_this,
    memory_profile_this,
    THRESHOLD_SIMPLE_FORMULA,
    THRESHOLD_COMPLEX_FORMULA,
)


# ============================================================================
# Example 1: Using Decorators for Simple Profiling
# ============================================================================

def example_1_decorators():
    """Example 1: Profile functions with decorators."""
    print("\n" + "="*80)
    print("Example 1: Using @profile_this and @memory_profile_this decorators")
    print("="*80 + "\n")
    
    @profile_this
    def fibonacci(n):
        """Calculate Fibonacci number (inefficient recursive version)."""
        if n <= 1:
            return n
        return fibonacci(n-1) + fibonacci(n-2)
    
    @memory_profile_this
    def allocate_large_list(size):
        """Allocate large list to demonstrate memory profiling."""
        return [i ** 2 for i in range(size)]
    
    # Profile CPU-intensive operation
    print("Profiling fibonacci(20)...")
    result = fibonacci(20)
    print(f"Result: {result}")
    
    # Profile memory-intensive operation
    print("\nProfiling memory allocation...")
    data = allocate_large_list(100000)
    print(f"Allocated {len(data)} elements")


# ============================================================================
# Example 2: Profiling TDFOL Prover Operations
# ============================================================================

def example_2_prover_profiling():
    """Example 2: Profile TDFOL prover operations."""
    print("\n" + "="*80)
    print("Example 2: Profiling TDFOL Prover Operations")
    print("="*80 + "\n")
    
    # Create mock prover for demonstration
    class MockProver:
        """Mock prover for demonstration."""
        
        def prove(self, formula):
            """Mock prove method."""
            # Simulate some work
            result = sum(i ** 2 for i in range(1000))
            return True
        
        def forward_chain(self, formula):
            """Mock forward chaining."""
            result = [i for i in range(500)]
            return result
    
    class MockFormula:
        """Mock formula."""
        def __str__(self):
            return "∀x. (P(x) → Q(x))"
    
    # Initialize profiler
    profiler = PerformanceProfiler(
        output_dir="profiling_results",
        enable_memory=True,
        enable_cprofile=True
    )
    
    # Create prover and formula
    prover = MockProver()
    formula = MockFormula()
    
    # Profile proving operation
    print(f"Profiling: {formula}")
    stats = profiler.profile_prover(prover, formula, runs=10, method="prove")
    
    print(f"\nProving Statistics:")
    print(f"  Mean time: {stats.mean_time_ms:.2f}ms")
    print(f"  Min time: {stats.min_time * 1000:.2f}ms")
    print(f"  Max time: {stats.max_time * 1000:.2f}ms")
    print(f"  Std dev: {stats.std_dev * 1000:.2f}ms")
    print(f"  Runs: {stats.runs}")
    print(f"  Meets threshold: {stats.meets_threshold}")
    
    if stats.mean_time_ms < THRESHOLD_SIMPLE_FORMULA:
        print(f"  ✓ Excellent! Under {THRESHOLD_SIMPLE_FORMULA}ms threshold")
    elif stats.mean_time_ms < THRESHOLD_COMPLEX_FORMULA:
        print(f"  ✓ Good! Under {THRESHOLD_COMPLEX_FORMULA}ms threshold")
    else:
        print(f"  ✗ Warning: Exceeds {THRESHOLD_COMPLEX_FORMULA}ms threshold")


# ============================================================================
# Example 3: Bottleneck Identification
# ============================================================================

def example_3_bottleneck_detection():
    """Example 3: Identify performance bottlenecks."""
    print("\n" + "="*80)
    print("Example 3: Bottleneck Identification")
    print("="*80 + "\n")
    
    def nested_loops_o_n2(n):
        """O(n²) operation."""
        total = 0
        for i in range(n):
            for j in range(n):
                total += i * j
        return total
    
    def nested_loops_o_n3(n):
        """O(n³) operation (bottleneck!)."""
        total = 0
        for i in range(n):
            for j in range(n):
                for k in range(n):
                    total += i + j + k
        return total
    
    # Initialize profiler
    profiler = PerformanceProfiler(output_dir="profiling_results")
    
    # Profile both functions
    print("Profiling O(n²) operation...")
    stats_n2 = profiler.profile_function(nested_loops_o_n2, 100, runs=3)
    
    print("Profiling O(n³) operation...")
    stats_n3 = profiler.profile_function(nested_loops_o_n3, 50, runs=3)
    
    # Identify bottlenecks
    print("\nBottlenecks in O(n²) operation:")
    bottlenecks_n2 = profiler.identify_bottlenecks(stats_n2.profile_data, top_n=5)
    for i, b in enumerate(bottlenecks_n2[:3], 1):
        print(f"\n{i}. {b.function}")
        print(f"   Time: {b.time:.4f}s ({b.calls} calls)")
        print(f"   Time/call: {b.time_per_call*1000:.3f}ms")
        print(f"   Severity: {b.severity.value}")
        print(f"   Recommendation: {b.recommendation}")
        if b.complexity_estimate:
            print(f"   Complexity: {b.complexity_estimate}")
    
    print("\n" + "-"*80)
    print("\nBottlenecks in O(n³) operation:")
    bottlenecks_n3 = profiler.identify_bottlenecks(stats_n3.profile_data, top_n=5)
    for i, b in enumerate(bottlenecks_n3[:3], 1):
        print(f"\n{i}. {b.function}")
        print(f"   Time: {b.time:.4f}s ({b.calls} calls)")
        print(f"   Time/call: {b.time_per_call*1000:.3f}ms")
        print(f"   Severity: {b.severity.value}")
        print(f"   Recommendation: {b.recommendation}")
        if b.complexity_estimate:
            print(f"   Complexity: {b.complexity_estimate}")


# ============================================================================
# Example 4: Memory Profiling
# ============================================================================

def example_4_memory_profiling():
    """Example 4: Profile memory usage and detect leaks."""
    print("\n" + "="*80)
    print("Example 4: Memory Profiling")
    print("="*80 + "\n")
    
    def memory_efficient(n):
        """Memory efficient - uses generator."""
        return sum(i ** 2 for i in range(n))
    
    def memory_intensive(n):
        """Memory intensive - creates full list."""
        data = [i ** 2 for i in range(n)]
        return sum(data)
    
    def potential_leak(n):
        """Simulates potential memory leak."""
        leaky_data = []
        for i in range(n):
            leaky_data.append([j for j in range(1000)])
        return len(leaky_data)
    
    # Initialize profiler
    profiler = PerformanceProfiler(
        output_dir="profiling_results",
        enable_memory=True
    )
    
    # Profile memory efficient function
    print("Profiling memory-efficient function...")
    mem_stats_efficient = profiler.memory_profile(memory_efficient, 100000)
    
    print(f"\nMemory Efficient Function:")
    print(f"  Peak memory: {mem_stats_efficient.peak_mb:.2f}MB")
    print(f"  Memory growth: {mem_stats_efficient.growth_mb:.2f}MB")
    print(f"  Allocations: {mem_stats_efficient.allocations}")
    print(f"  Leak detected: {mem_stats_efficient.has_leak}")
    
    # Profile memory intensive function
    print("\n" + "-"*80)
    print("\nProfiling memory-intensive function...")
    mem_stats_intensive = profiler.memory_profile(memory_intensive, 100000)
    
    print(f"\nMemory Intensive Function:")
    print(f"  Peak memory: {mem_stats_intensive.peak_mb:.2f}MB")
    print(f"  Memory growth: {mem_stats_intensive.growth_mb:.2f}MB")
    print(f"  Allocations: {mem_stats_intensive.allocations}")
    print(f"  Leak detected: {mem_stats_intensive.has_leak}")
    
    # Profile potential leak
    print("\n" + "-"*80)
    print("\nProfiling function with potential leak...")
    mem_stats_leak = profiler.memory_profile(potential_leak, 100)
    
    print(f"\nPotential Leak Function:")
    print(f"  Peak memory: {mem_stats_leak.peak_mb:.2f}MB")
    print(f"  Memory growth: {mem_stats_leak.growth_mb:.2f}MB")
    print(f"  Allocations: {mem_stats_leak.allocations}")
    print(f"  Leak detected: {mem_stats_leak.has_leak}")
    
    if mem_stats_leak.has_leak:
        print(f"  ⚠ WARNING: Possible memory leak detected!")
        print(f"  Top allocators:")
        for loc, size_mb in mem_stats_leak.top_allocators[:3]:
            print(f"    - {loc}: {size_mb:.2f}MB")


# ============================================================================
# Example 5: Benchmark Suite
# ============================================================================

def example_5_benchmark_suite():
    """Example 5: Run standard benchmark suite."""
    print("\n" + "="*80)
    print("Example 5: Running Benchmark Suite")
    print("="*80 + "\n")
    
    # Initialize profiler with baseline
    profiler = PerformanceProfiler(
        output_dir="profiling_results",
        baseline_path="profiling_results/baseline.json"
    )
    
    # Run benchmark suite
    print("Running standard benchmark suite...")
    results = profiler.run_benchmark_suite()
    
    print(f"\nBenchmark Suite Results:")
    print(f"  Total benchmarks: {len(results.benchmarks)}")
    print(f"  Passed: {results.passed}")
    print(f"  Failed: {results.failed}")
    print(f"  Pass rate: {results.pass_rate:.1%}")
    print(f"  Regressions: {results.regressions}")
    print(f"  Total time: {results.total_time_ms:.2f}ms")
    print(f"  Timestamp: {results.timestamp}")
    
    # Show individual benchmark results
    print("\nIndividual Benchmark Results:")
    print("-"*80)
    for bench in results.benchmarks:
        status = "✓ PASS" if bench.passed else "✗ FAIL"
        print(f"\n{status} {bench.name}")
        print(f"  Formula: {bench.formula}")
        print(f"  Time: {bench.time_ms:.2f}ms")
        if bench.memory_mb > 0:
            print(f"  Memory: {bench.memory_mb:.2f}MB")
        
        if bench.baseline_time_ms:
            print(f"  Baseline: {bench.baseline_time_ms:.2f}ms")
            if bench.regression_pct:
                if bench.regression_pct > 0:
                    print(f"  Regression: +{bench.regression_pct:.1f}% (slower)")
                else:
                    print(f"  Improvement: {abs(bench.regression_pct):.1f}% (faster)")


# ============================================================================
# Example 6: Report Generation
# ============================================================================

def example_6_report_generation():
    """Example 6: Generate comprehensive profiling reports."""
    print("\n" + "="*80)
    print("Example 6: Report Generation")
    print("="*80 + "\n")
    
    # Initialize profiler
    profiler = PerformanceProfiler(output_dir="profiling_results")
    
    # Run some profiling operations
    print("Running profiling operations...")
    
    def sample_operation(n):
        """Compute the sum of squares from 0 to n-1 (used for profiling benchmarks)."""
        return sum(i ** 2 for i in range(n))
    
    profiler.profile_function(sample_operation, 1000, runs=5)
    profiler.profile_function(sample_operation, 5000, runs=5)
    
    # Generate reports in different formats
    print("\nGenerating reports...")
    
    # Text report
    text_report = profiler.generate_report(
        format=ReportFormat.TEXT,
        include_bottlenecks=True,
        include_memory=True
    )
    print(f"✓ Text report: {text_report}")
    
    # JSON report
    json_report = profiler.generate_report(
        format=ReportFormat.JSON,
        include_bottlenecks=True,
        include_memory=True
    )
    print(f"✓ JSON report: {json_report}")
    
    # HTML report
    html_report = profiler.generate_report(
        format=ReportFormat.HTML,
        include_bottlenecks=True,
        include_memory=True
    )
    print(f"✓ HTML report: {html_report}")
    
    print("\nReports generated successfully!")
    print(f"View reports in: profiling_results/")


# ============================================================================
# Example 7: Context Manager for Profiling Blocks
# ============================================================================

def example_7_profile_block():
    """Example 7: Use ProfileBlock context manager."""
    print("\n" + "="*80)
    print("Example 7: ProfileBlock Context Manager")
    print("="*80 + "\n")
    
    profiler = PerformanceProfiler(output_dir="profiling_results")
    
    print("Profiling code block with context manager...")
    
    with ProfileBlock("data_processing", profiler):
        # Simulate data processing
        data = [i ** 2 for i in range(100000)]
        result = sum(data)
        filtered = [x for x in data if x % 2 == 0]
        final = sum(filtered)
    
    print(f"Completed! Final result: {final}")
    
    # Nested profiling
    print("\n" + "-"*80)
    print("\nNested profiling with multiple blocks...")
    
    with ProfileBlock("outer_operation", profiler):
        outer_data = []
        
        with ProfileBlock("inner_operation_1", profiler):
            inner1 = [i for i in range(50000)]
            outer_data.extend(inner1)
        
        with ProfileBlock("inner_operation_2", profiler):
            inner2 = [i ** 2 for i in range(50000)]
            outer_data.extend(inner2)
        
        total = sum(outer_data)
    
    print(f"Nested operations complete! Total: {total}")


# ============================================================================
# Example 8: Complete Workflow
# ============================================================================

def example_8_complete_workflow():
    """Example 8: Complete profiling workflow."""
    print("\n" + "="*80)
    print("Example 8: Complete Profiling Workflow")
    print("="*80 + "\n")
    
    # 1. Initialize profiler
    print("1. Initializing profiler...")
    profiler = PerformanceProfiler(
        output_dir="profiling_results",
        enable_memory=True,
        enable_cprofile=True,
        baseline_path="profiling_results/baseline.json"
    )
    
    # 2. Profile functions
    print("\n2. Profiling functions...")
    
    def operation_a(n):
        """Sum squares 0..n-1 in a generator (baseline for profiling comparison)."""
        return sum(i ** 2 for i in range(n))
    
    def operation_b(n):
        """Sum squares 0..n-1 via a list (alternative for profiling comparison)."""
        data = [i ** 2 for i in range(n)]
        return sum(data)
    
    stats_a = profiler.profile_function(operation_a, 10000, runs=5)
    stats_b = profiler.profile_function(operation_b, 10000, runs=5)
    
    print(f"   Operation A: {stats_a.mean_time_ms:.2f}ms")
    print(f"   Operation B: {stats_b.mean_time_ms:.2f}ms")
    
    # 3. Identify bottlenecks
    print("\n3. Identifying bottlenecks...")
    bottlenecks = profiler.identify_bottlenecks(stats_b.profile_data, top_n=3)
    print(f"   Found {len(bottlenecks)} bottlenecks")
    for b in bottlenecks[:2]:
        print(f"   - {b.function}: {b.time:.4f}s ({b.severity.value})")
    
    # 4. Memory profiling
    print("\n4. Profiling memory usage...")
    mem_stats = profiler.memory_profile(operation_b, 50000)
    print(f"   Peak memory: {mem_stats.peak_mb:.2f}MB")
    print(f"   Memory growth: {mem_stats.growth_mb:.2f}MB")
    print(f"   Leak detected: {mem_stats.has_leak}")
    
    # 5. Run benchmarks
    print("\n5. Running benchmark suite...")
    bench_results = profiler.run_benchmark_suite()
    print(f"   Benchmarks: {bench_results.passed}/{len(bench_results.benchmarks)} passed")
    print(f"   Pass rate: {bench_results.pass_rate:.1%}")
    print(f"   Regressions: {bench_results.regressions}")
    
    # 6. Generate reports
    print("\n6. Generating reports...")
    html_report = profiler.generate_report(format=ReportFormat.HTML)
    json_report = profiler.generate_report(format=ReportFormat.JSON)
    print(f"   HTML report: {html_report}")
    print(f"   JSON report: {json_report}")
    
    print("\n✓ Complete workflow finished successfully!")


# ============================================================================
# Main
# ============================================================================

def main():
    """Run all examples."""
    print("\n" + "="*80)
    print(" TDFOL Performance Profiler - Example Usage")
    print("="*80)
    
    examples = [
        ("Decorators", example_1_decorators),
        ("Prover Profiling", example_2_prover_profiling),
        ("Bottleneck Detection", example_3_bottleneck_detection),
        ("Memory Profiling", example_4_memory_profiling),
        ("Benchmark Suite", example_5_benchmark_suite),
        ("Report Generation", example_6_report_generation),
        ("ProfileBlock Context Manager", example_7_profile_block),
        ("Complete Workflow", example_8_complete_workflow),
    ]
    
    for name, example_func in examples:
        try:
            example_func()
        except Exception as e:
            print(f"\n✗ Error in {name}: {e}")
            import traceback
            traceback.print_exc()
    
    print("\n" + "="*80)
    print(" All examples completed!")
    print("="*80 + "\n")


if __name__ == "__main__":
    main()
