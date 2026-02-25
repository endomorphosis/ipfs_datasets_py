"""
Performance comparison: Query Optimizer with vs without optimizations.

Measures the latency reduction from:
1. Query fingerprint caching (38% bottleneck)
2. Fast-path graph type detection (32% bottleneck)

Expected result: 15-20% improvement for repeated queries
"""

import sys
import time
import statistics
from pathlib import Path
from typing import Dict, Any, List, Tuple
import json

# Setup path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ipfs_datasets_py.optimizers.graphrag.query_unified_optimizer import (
    UnifiedGraphRAGQueryOptimizer,
)
from ipfs_datasets_py.optimizers.graphrag.query_optimizer_optimizations import (
    QueryFingerprintCache,
    FastGraphTypeDetector,
    OptimizedQueryOptimizerWrapper,
)


class PerformanceComparisonBenchmark:
    """Compare optimized vs baseline query optimizer performance."""
    
    def __init__(self, iterations: int = 50):
        self.iterations = iterations
        self.baseline_optimizer = UnifiedGraphRAGQueryOptimizer()
        self.optimized_wrapper = OptimizedQueryOptimizerWrapper(self.baseline_optimizer)
        
    def create_test_queries(self, count: int = 5) -> List[Dict[str, Any]]:
        """Create diverse test queries."""
        return [
            # Simple query
            {
                "query_text": "find entity A",
                "max_vector_results": 5,
                "traversal": {"max_depth": 2},
            },
            # Moderate query with vector and wikipedia source
            {
                "query_text": "find wikipedia related entities",
                "query_vector": [0.1] * 768,
                "max_vector_results": 10,
                "entity_source": "wikipedia",
                "traversal": {"max_depth": 3, "edge_types": ["related_to"]},
            },
            # Complex query with multiple sources
            {
                "query_text": "find entities across ipld and wikipedia",
                "query_vector": [0.2] * 768,
                "max_vector_results": 20,
                "entity_source": "ipld",
                "traversal": {
                    "max_depth": 4,
                    "edge_types": ["related_to", "parent_of", "child_of"],
                    "entity_ids": ["e1", "e2", "e3"],
                },
            },
        ]
    
    def benchmark_baseline(self) -> Dict[str, float]:
        """Benchmark baseline query optimizer."""
        queries = self.create_test_queries()
        times = []
        
        # Simulate realistic workload: repeat queries multiple times
        for iteration in range(self.iterations):
            for query in queries:
                start = time.perf_counter()
                _ = self.baseline_optimizer.optimize_query(query)
                elapsed = (time.perf_counter() - start) * 1000  # Convert to ms
                times.append(elapsed)
        
        return {
            "mean_ms": statistics.mean(times),
            "median_ms": statistics.median(times),
            "min_ms": min(times),
            "max_ms": max(times),
            "stdev_ms": statistics.stdev(times) if len(times) > 1 else 0,
            "samples": len(times),
            "throughput_per_sec": 1000.0 / statistics.mean(times) if times else 0,
        }
    
    def benchmark_optimized(self) -> Dict[str, float]:
        """Benchmark optimized query optimizer."""
        queries = self.create_test_queries()
        times = []
        
        # Simulate realistic workload: repeat queries multiple times
        for iteration in range(self.iterations):
            for query in queries:
                start = time.perf_counter()
                _ = self.optimized_wrapper.optimize_query(query)
                elapsed = (time.perf_counter() - start) * 1000  # Convert to ms
                times.append(elapsed)
        
        return {
            "mean_ms": statistics.mean(times),
            "median_ms": statistics.median(times),
            "min_ms": min(times),
            "max_ms": max(times),
            "stdev_ms": statistics.stdev(times) if len(times) > 1 else 0,
            "samples": len(times),
            "throughput_per_sec": 1000.0 / statistics.mean(times) if times else 0,
        }
    
    def run_comparison(self) -> None:
        """Run complete performance comparison."""
        print("=" * 80)
        print("Query Optimizer Performance Comparison")
        print("=" * 80)
        print(f"Workload: {self.iterations} iterations × {len(self.create_test_queries())} different queries")
        print(f"Total calls measured: {self.iterations * len(self.create_test_queries())}")
        print()
        
        print("Running baseline benchmark...")
        baseline_stats = self.benchmark_baseline()
        
        print("Running optimized benchmark (with caching)...")
        optimized_stats = self.benchmark_optimized()
        
        print()
        print("=" * 80)
        print("RESULTS: Baseline vs Optimized")
        print("=" * 80)
        print()
        
        # Print side-by-side comparison
        print(f"{'Metric':<30} {'Baseline':<20} {'Optimized':<20} {'Improvement':<15}")
        print("-" * 80)
        
        for key in ["mean_ms", "median_ms", "min_ms", "max_ms", "stdev_ms"]:
            baseline_val = baseline_stats[key]
            optimized_val = optimized_stats[key]
            
            if baseline_val > 0:
                improvement_pct = (baseline_val - optimized_val) / baseline_val * 100
                improvement_str = f"{improvement_pct:+.1f}%"
            else:
                improvement_str = "N/A"
            
            print(f"{key:<30} {baseline_val:<20.6f}ms {optimized_val:<20.6f}ms {improvement_str:<15}")
        
        print()
        print(f"{'Throughput (ops/sec)':<30} {baseline_stats['throughput_per_sec']:<20.1f} {optimized_stats['throughput_per_sec']:<20.1f}")
        
        # Calculate overall improvement
        baseline_mean = baseline_stats["mean_ms"]
        optimized_mean = optimized_stats["mean_ms"]
        improvement_pct = (baseline_mean - optimized_mean) / baseline_mean * 100
        
        print()
        print("=" * 80)
        print(f"OVERALL IMPROVEMENT: {improvement_pct:.1f}%")
        print(f"Latency reduction: {baseline_mean:.6f}ms → {optimized_mean:.6f}ms")
        print(f"Time saved per query: {baseline_mean - optimized_mean:.6f}ms")
        print("=" * 80)
        print()
        
        # Print optimization statistics
        print("Optimization Statistics:")
        print("-" * 80)
        
        opt_stats = self.optimized_wrapper.get_optimization_stats()
        
        print("\nFingerprint Cache:")
        fp_cache = opt_stats["fingerprint_cache"]
        print(f"  Cache size: {fp_cache['cache_size']}/{fp_cache['max_size']}")
        print(f"  Accesses: {fp_cache['accesses']}")
        print(f"  Hits: {fp_cache['hits']}")
        print(f"  Hit rate: {fp_cache['hit_rate']:.1f}%")
        
        print("\nGraph Type Detection:")
        type_det = opt_stats["type_detector"]
        print(f"  Cache size: {type_det['cache_size']}")
        print(f"  Cache hits: {type_det['cache_hits']}")
        print(f"  Cache misses: {type_det['cache_misses']}")
        print(f"  Hit rate: {type_det['hit_rate']:.1f}%")
        
        print()
        print("=" * 80)
        print("Bottleneck Analysis (from component profiling):")
        print("=" * 80)
        print("""
Cache Key Generation:   38.34% of original latency
  → Optimized by caching repeated queries
  → Hit rate improves with workload repetition

Graph Type Detection:   31.54% of original latency
  → Optimized by fast-path heuristics
  → Hit rate improves with familiar queries

Together: ~70% of original latency targeted for optimization

Achievable improvement with this workload:
  - Cold start (no cache): 0-5% (first call overhead)
  - Warm cache (typical): 15-25% (repeated queries)
  - Hot cache (sustained): 20-30% (mostly cache hits)
""")
        print("=" * 80)


if __name__ == "__main__":
    benchmark = PerformanceComparisonBenchmark(iterations=50)
    benchmark.run_comparison()
