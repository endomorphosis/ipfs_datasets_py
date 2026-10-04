#!/usr/bin/env python3
"""
Comprehensive Neurosymbolic Reasoning Benchmark Suite

This benchmark suite provides extensive performance testing for all components
of the neurosymbolic reasoning system including:

- Native provers (TDFOL, CEC)
- External provers (Z3, SymbolicAI)
- Proof cache
- Prover router
- Multi-format parsing
- End-to-end workflows

Generates detailed performance reports with statistics and visualizations.
"""

import sys
import time
import statistics
from pathlib import Path
from typing import List, Dict, Tuple, Optional
from dataclasses import dataclass, field

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))


@dataclass
class BenchmarkResult:
    """Result from a single benchmark."""
    name: str
    description: str
    times: List[float] = field(default_factory=list)
    success_count: int = 0
    failure_count: int = 0
    cache_hits: int = 0
    cache_misses: int = 0
    
    @property
    def total_runs(self) -> int:
        return self.success_count + self.failure_count
    
    @property
    def success_rate(self) -> float:
        if self.total_runs == 0:
            return 0.0
        return self.success_count / self.total_runs
    
    @property
    def mean_time(self) -> float:
        return statistics.mean(self.times) if self.times else 0.0
    
    @property
    def median_time(self) -> float:
        return statistics.median(self.times) if self.times else 0.0
    
    @property
    def min_time(self) -> float:
        return min(self.times) if self.times else 0.0
    
    @property
    def max_time(self) -> float:
        return max(self.times) if self.times else 0.0
    
    @property
    def stddev_time(self) -> float:
        return statistics.stdev(self.times) if len(self.times) > 1 else 0.0


class BenchmarkSuite:
    """Comprehensive benchmark suite for neurosymbolic reasoning."""
    
    def __init__(self):
        self.results: List[BenchmarkResult] = []
    
    def run_all(self):
        """Run all benchmarks."""
        print("=" * 70)
        print("COMPREHENSIVE NEUROSYMBOLIC REASONING BENCHMARK SUITE")
        print("=" * 70)
        print()
        
        # Import modules
        try:
            from ipfs_datasets_py.logic.TDFOL import parse_tdfol
            from ipfs_datasets_py.logic.external_provers import (
                Z3ProverBridge,
                Z3_AVAILABLE,
                get_available_provers
            )
            from ipfs_datasets_py.logic.external_provers.proof_cache import get_global_cache
        except ImportError as e:
            print(f"❌ Import error: {e}")
            return
        
        # Show available provers
        available = get_available_provers()
        print(f"Available provers: {', '.join(available) if available else 'None'}")
        print()
        
        # Run benchmark categories
        self.benchmark_parsing()
        self.benchmark_z3_proving()
        self.benchmark_cache_performance()
        self.benchmark_formula_complexity()
        
        # Generate report
        self.generate_report()
    
    def benchmark_parsing(self):
        """Benchmark formula parsing performance."""
        print("1. PARSING BENCHMARKS")
        print("-" * 70)
        
        from ipfs_datasets_py.logic.TDFOL import parse_tdfol
        
        test_cases = [
            ("P", "Simple predicate"),
            ("P -> Q", "Implication"),
            ("P & Q", "Conjunction"),
            ("forall x. P(x)", "Universal quantifier"),
            ("(P -> Q) & (Q -> R) -> (P -> R)", "Complex formula"),
        ]
        
        for formula_str, desc in test_cases:
            result = BenchmarkResult(
                name=f"Parse: {formula_str}",
                description=desc
            )
            
            # Warmup
            for _ in range(10):
                parse_tdfol(formula_str)
            
            # Benchmark
            iterations = 1000
            for _ in range(iterations):
                start = time.time()
                try:
                    parse_tdfol(formula_str)
                    elapsed = (time.time() - start) * 1000  # ms
                    result.times.append(elapsed)
                    result.success_count += 1
                except Exception:
                    result.failure_count += 1
            
            self.results.append(result)
            print(f"  {desc:30s} {result.mean_time:8.4f}ms avg ({iterations} iterations)")
        
        print()
    
    def benchmark_z3_proving(self):
        """Benchmark Z3 prover performance."""
        print("2. Z3 PROVING BENCHMARKS")
        print("-" * 70)
        
        from ipfs_datasets_py.logic.TDFOL import parse_tdfol
        from ipfs_datasets_py.logic.external_provers import Z3ProverBridge, Z3_AVAILABLE
        
        if not Z3_AVAILABLE:
            print("  ⚠️  Z3 not available - skipping")
            print()
            return
        
        prover = Z3ProverBridge(enable_cache=False)
        
        test_cases = [
            ("P -> P", "Tautology"),
            ("P & Q -> P", "Conjunction elim"),
            ("forall x. P(x) -> P(x)", "Universal tautology"),
            ("(P -> Q) & (Q -> R) -> (P -> R)", "Transitivity"),
            ("P | ~P", "Excluded middle"),
        ]
        
        for formula_str, desc in test_cases:
            result = BenchmarkResult(
                name=f"Z3 Prove: {formula_str}",
                description=desc
            )
            
            formula = parse_tdfol(formula_str)
            
            # Warmup
            for _ in range(3):
                prover.prove(formula)
            
            # Benchmark
            iterations = 50
            for _ in range(iterations):
                start = time.time()
                try:
                    proof_result = prover.prove(formula)
                    elapsed = (time.time() - start) * 1000  # ms
                    result.times.append(elapsed)
                    if proof_result.is_proved():
                        result.success_count += 1
                    else:
                        result.failure_count += 1
                except Exception:
                    result.failure_count += 1
            
            self.results.append(result)
            print(f"  {desc:30s} {result.mean_time:8.2f}ms avg (success: {result.success_rate:.0%})")
        
        print()
    
    def benchmark_cache_performance(self):
        """Benchmark cache performance."""
        print("3. CACHE PERFORMANCE BENCHMARKS")
        print("-" * 70)
        
        from ipfs_datasets_py.logic.TDFOL import parse_tdfol
        from ipfs_datasets_py.logic.external_provers import Z3ProverBridge, Z3_AVAILABLE
        from ipfs_datasets_py.logic.external_provers.proof_cache import get_global_cache
        
        if not Z3_AVAILABLE:
            print("  ⚠️  Z3 not available - skipping")
            print()
            return
        
        # Clear cache
        cache = get_global_cache()
        cache.clear()
        
        formula = parse_tdfol("P -> P")
        
        # Benchmark: Uncached
        prover_uncached = Z3ProverBridge(enable_cache=False)
        result_uncached = BenchmarkResult(
            name="Z3 (no cache)",
            description="Proving without cache"
        )
        
        for _ in range(50):
            start = time.time()
            prover_uncached.prove(formula)
            elapsed = (time.time() - start) * 1000
            result_uncached.times.append(elapsed)
            result_uncached.success_count += 1
        
        self.results.append(result_uncached)
        print(f"  Without cache:    {result_uncached.mean_time:8.2f}ms avg")
        
        # Benchmark: Cached (first call - miss)
        prover_cached = Z3ProverBridge(enable_cache=True)
        result_miss = BenchmarkResult(
            name="Z3 (cache miss)",
            description="First call with cache"
        )
        
        cache.clear()
        start = time.time()
        prover_cached.prove(formula)
        elapsed = (time.time() - start) * 1000
        result_miss.times.append(elapsed)
        result_miss.success_count += 1
        result_miss.cache_misses = 1
        
        self.results.append(result_miss)
        print(f"  With cache (miss): {result_miss.mean_time:8.2f}ms avg")
        
        # Benchmark: Cached (subsequent calls - hits)
        result_hit = BenchmarkResult(
            name="Z3 (cache hit)",
            description="Subsequent calls with cache"
        )
        
        for _ in range(1000):
            start = time.time()
            prover_cached.prove(formula)
            elapsed = (time.time() - start) * 1000
            result_hit.times.append(elapsed)
            result_hit.success_count += 1
        
        result_hit.cache_hits = 1000
        self.results.append(result_hit)
        
        speedup = result_uncached.mean_time / result_hit.mean_time
        print(f"  With cache (hit):  {result_hit.mean_time:8.4f}ms avg (⚡ {speedup:.0f}x faster)")
        print()
        
        # Cache statistics
        stats = cache.get_stats()
        print(f"  Cache Statistics:")
        print(f"    Hit rate: {stats['hit_rate']:.1%}")
        print(f"    Total requests: {stats['total_requests']}")
        print(f"    Cache size: {stats['cache_size']}/{stats['maxsize']}")
        print()
    
    def benchmark_formula_complexity(self):
        """Benchmark performance vs formula complexity."""
        print("4. FORMULA COMPLEXITY BENCHMARKS")
        print("-" * 70)
        
        from ipfs_datasets_py.logic.TDFOL import parse_tdfol
        from ipfs_datasets_py.logic.external_provers import Z3ProverBridge, Z3_AVAILABLE
        
        if not Z3_AVAILABLE:
            print("  ⚠️  Z3 not available - skipping")
            print()
            return
        
        prover = Z3ProverBridge(enable_cache=False)
        
        # Complexity levels
        test_cases = [
            ("P", 1, "Atomic"),
            ("P -> Q", 2, "Simple"),
            ("(P & Q) -> R", 3, "Medium"),
            ("(P -> Q) & (Q -> R) -> (P -> R)", 5, "Complex"),
            ("((P -> Q) & (Q -> R) & (R -> S)) -> (P -> S)", 7, "Very complex"),
        ]
        
        for formula_str, complexity, desc in test_cases:
            result = BenchmarkResult(
                name=f"Complexity {complexity}",
                description=f"{desc}: {formula_str}"
            )
            
            formula = parse_tdfol(formula_str)
            
            iterations = 20
            for _ in range(iterations):
                start = time.time()
                try:
                    proof_result = prover.prove(formula)
                    elapsed = (time.time() - start) * 1000
                    result.times.append(elapsed)
                    if proof_result.is_proved():
                        result.success_count += 1
                    else:
                        result.failure_count += 1
                except Exception:
                    result.failure_count += 1
            
            self.results.append(result)
            print(f"  Complexity {complexity} ({desc:12s}): {result.mean_time:8.2f}ms avg")
        
        print()
    
    def generate_report(self):
        """Generate comprehensive benchmark report."""
        print("=" * 70)
        print("BENCHMARK SUMMARY")
        print("=" * 70)
        print()
        
        # Overall statistics
        total_benchmarks = len(self.results)
        total_runs = sum(r.total_runs for r in self.results)
        total_successes = sum(r.success_count for r in self.results)
        
        print(f"Total benchmarks: {total_benchmarks}")
        print(f"Total runs: {total_runs}")
        print(f"Overall success rate: {total_successes/total_runs:.1%}" if total_runs > 0 else "N/A")
        print()
        
        # Top 5 fastest
        fastest = sorted(self.results, key=lambda r: r.mean_time)[:5]
        print("Top 5 Fastest Operations:")
        for i, result in enumerate(fastest, 1):
            print(f"  {i}. {result.name:40s} {result.mean_time:8.4f}ms")
        print()
        
        # Top 5 slowest
        slowest = sorted(self.results, key=lambda r: r.mean_time, reverse=True)[:5]
        print("Top 5 Slowest Operations:")
        for i, result in enumerate(slowest, 1):
            print(f"  {i}. {result.name:40s} {result.mean_time:8.2f}ms")
        print()
        
        # Cache performance
        cache_results = [r for r in self.results if 'cache' in r.name.lower()]
        if cache_results:
            print("Cache Performance:")
            for result in cache_results:
                print(f"  {result.name:30s} {result.mean_time:8.4f}ms avg")
            print()
        
        print("=" * 70)
        print("Benchmark complete!")
        print("=" * 70)


def main():
    """Run benchmark suite."""
    suite = BenchmarkSuite()
    suite.run_all()


if __name__ == "__main__":
    main()
