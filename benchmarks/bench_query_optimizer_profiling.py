"""Profiling benchmark for UnifiedGraphRAGQueryOptimizer under load.

This benchmark measures performance characteristics of the query optimization pipeline
including:
- Query validation and parameter normalization
- Graph type detection
- Vector optimization tuning
- Budget allocation
- Cache key generation
- Overall end-to-end optimization latency

Designed to identify hotspots before the planned modularization/split of the
2,114-line query_unified_optimizer.py file.
"""

from __future__ import annotations

import time
import json
import statistics
import sys
from pathlib import Path
from typing import Dict, List, Any
from dataclasses import dataclass

# Add workspace to path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ipfs_datasets_py.optimizers.graphrag.query_unified_optimizer import UnifiedGraphRAGQueryOptimizer  # noqa: E402


@dataclass
class ProfilingResult:
    """Results from a profiling measurement."""
    test_name: str
    iterations: int
    total_ms: float
    mean_ms: float
    median_ms: float
    min_ms: float
    max_ms: float
    std_dev_ms: float
    throughput_per_sec: float
    
    def __str__(self) -> str:
        return (
            f"{self.test_name:50s} | "
            f"mean={self.mean_ms:8.3f}ms | "
            f"median={self.median_ms:8.3f}ms | "
            f"min={self.min_ms:8.3f}ms | "
            f"max={self.max_ms:8.3f}ms | "
            f"σ={self.std_dev_ms:6.3f}ms | "
            f"throughput={self.throughput_per_sec:8.1f}/s"
        )


class QueryOptimizerProfiler:
    """Profiling harness for query optimizer performance analysis."""
    
    def __init__(self):
        """Initialize profiler with optimizer instance."""
        self.optimizer = UnifiedGraphRAGQueryOptimizer()
        self.results: List[ProfilingResult] = []
    
    def create_test_query(self, complexity: str = "simple") -> Dict[str, Any]:
        """Create a test query of given complexity level."""
        base_query = {
            "query_type": "entity_search",
            "domain": "test",
            "session_id": "prof_test_123",
            "timestamp": 1708684800,
        }
        
        if complexity == "simple":
            return {
                **base_query,
                "query_text": "What is entity A?",
            }
        
        elif complexity == "moderate":
            return {
                **base_query,
                "query_text": "Relationships between entity A and entity B",
                "query_vector": [0.1] * 100,  # 100D embedding
                "vector_params": {
                    "top_k": 10,
                    "min_score": 0.5,
                },
                "traversal": {
                    "max_depth": 3,
                    "edge_types": ["related_to", "part_of"],
                },
                "max_vector_results": 20,
            }
        
        elif complexity == "complex":
            return {
                **base_query,
                "query_text": "Multi-hop reasoning: A influences B through C",
                "query_vector": [0.05] * 256,  # 256D embedding
                "vector_params": {
                    "top_k": 50,
                    "min_score": 0.3,
                },
                "traversal": {
                    "max_depth": 5,
                    "edge_types": ["related_to", "part_of", "influences", "contains"],
                },
                "max_vector_results": 100,
                "entity_importance_threshold": 0.4,
            }
        
        elif complexity == "heavy":
            # Large query with many parameters
            edge_types = ["related_to", "part_of", "influences", "contains", "causes", "affects"]
            return {
                **base_query,
                "query_text": "Complex multi-domain entity resolution and reasoning",
                "query_vector": [0.02] * 512,  # 512D embedding
                "vector_params": {
                    "top_k": 100,
                    "min_score": 0.1,
                },
                "traversal": {
                    "max_depth": 7,
                    "edge_types": edge_types * 2,  # 12 edge types
                },
                "max_vector_results": 200,
                "entity_importance_threshold": 0.2,
                "include_explanations": True,
                "reasoning_depth": 4,
            }
        
        return base_query
    
    def profile_operation(
        self,
        test_name: str,
        test_func,
        iterations: int = 100,
    ) -> ProfilingResult:
        """Profile a single operation across multiple iterations."""
        times_ms = []
        
        for _ in range(iterations):
            start = time.perf_counter()
            test_func()
            elapsed = time.perf_counter() - start
            times_ms.append(elapsed * 1000)
        
        total_ms = sum(times_ms)
        mean_ms = statistics.mean(times_ms)
        median_ms = statistics.median(times_ms)
        min_ms = min(times_ms)
        max_ms = max(times_ms)
        std_dev_ms = statistics.stdev(times_ms) if len(times_ms) > 1 else 0
        throughput_per_sec = (iterations / total_ms) * 1000 if total_ms > 0 else 0
        
        result = ProfilingResult(
            test_name=test_name,
            iterations=iterations,
            total_ms=total_ms,
            mean_ms=mean_ms,
            median_ms=median_ms,
            min_ms=min_ms,
            max_ms=max_ms,
            std_dev_ms=std_dev_ms,
            throughput_per_sec=throughput_per_sec,
        )
        
        self.results.append(result)
        return result
    
    def run_all_benchmarks(self) -> None:
        """Run comprehensive profiling suite."""
        print("\n" + "="*120)
        print("UnifiedGraphRAGQueryOptimizer Profiling Results")
        print("="*120 + "\n")
        
        # Warmup
        print("Warming up...")
        for _ in range(5):
            query = self.create_test_query("simple")
            try:
                self.optimizer.optimize_query(query)
            except:
                pass
        print("Warmup complete.\n")
        
        # 1. Simple query optimization baseline
        print("Testing simple queries...")
        query = self.create_test_query("simple")
        result = self.profile_operation(
            "Simple query optimization (baseline)",
            lambda: self.optimizer.optimize_query(query),
            iterations=100,
        )
        print(result)
        
        # 2. Moderate complexity queries (typical use case)
        print("Testing moderate queries...")
        query = self.create_test_query("moderate")
        result = self.profile_operation(
            "Moderate query optimization (typical)",
            lambda: self.optimizer.optimize_query(query),
            iterations=50,
        )
        print(result)
        
        # 3. Complex queries (rare but important)
        print("Testing complex queries...")
        query = self.create_test_query("complex")
        result = self.profile_operation(
            "Complex query optimization (high-depth)",
            lambda: self.optimizer.optimize_query(query),
            iterations=30,
        )
        print(result)
        
        # 4. Heavy queries (stress test)
        print("Testing heavy queries...")
        query = self.create_test_query("heavy")
        result = self.profile_operation(
            "Heavy query optimization (stress test)",
            lambda: self.optimizer.optimize_query(query),
            iterations=20,
        )
        print(result)
        
        # 5. Batch operations (multiple queries in sequence)
        print("Testing batch operations...")
        queries = [
            self.create_test_query("simple"),
            self.create_test_query("moderate"),
            self.create_test_query("complex"),
        ]
        
        def batch_optimize():
            for q in queries:
                try:
                    self.optimizer.optimize_query(q)
                except:
                    pass
        
        result = self.profile_operation(
            "Batch optimization (3 queries mixed complexity)",
            batch_optimize,
            iterations=30,
        )
        print(result)
        
        # 6. Repeated optimization of same query (cache path)
        print("Testing repeated optimization...")
        query = self.create_test_query("moderate")
        result = self.profile_operation(
            "Repeated moderate query optimization (cache))",
            lambda: self.optimizer.optimize_query(query),
            iterations=75,
        )
        print(result)
        
        # Summary
        self._print_summary()
    
    def _print_summary(self) -> None:
        """Print profiling summary."""
        if not self.results:
            return
        
        print("\n" + "="*120)
        print("Summary Statistics")
        print("="*120 + "\n")
        
        # Sort by mean latency
        sorted_results = sorted(self.results, key=lambda r: r.mean_ms)
        
        print("Ranked by latency (fastest to slowest):")
        print("-" * 120)
        for i, result in enumerate(sorted_results, 1):
            marker = "🚀" if i == 1 else "⚠️ " if i == len(sorted_results) else "  "
            print(f"{marker} {result}")
        
        # Overall statistics
        print("\n" + "-" * 120)
        overall_mean = statistics.mean(r.mean_ms for r in self.results)
        min_latency = min(r.mean_ms for r in self.results)
        max_latency = max(r.mean_ms for r in self.results)
        
        print(f"\nOverall Statistics:")
        print(f"  Fastest operation:  {min_latency:8.3f}ms")
        print(f"  Slowest operation:  {max_latency:8.3f}ms")
        print(f"  Average latency:    {overall_mean:8.3f}ms")
        print(f"  Variation range:    {(max_latency/min_latency):8.1f}x")
        
        # Identify slowest operations
        print(f"\nPerformance observations:")
        slowest = max(self.results, key=lambda r: r.mean_ms)
        fastest = min(self.results, key=lambda r: r.mean_ms)
        
        if slowest.mean_ms > fastest.mean_ms * 2:
            print(f"  ⚠️  {slowest.test_name} is {slowest.mean_ms/fastest.mean_ms:.1f}x slower than {fastest.test_name}")
        
        # Identify high variance operations
        high_variance = [r for r in self.results if r.std_dev_ms > r.mean_ms * 0.5]
        if high_variance:
            print(f"  ⚠️  High variance operations (σ > 50% mean):")
            for r in high_variance:
                print(f"      - {r.test_name}: σ={r.std_dev_ms:.3f}ms")
        
        print("\n" + "="*120 + "\n")


def main():
    """Run the profiling benchmark."""
    profiler = QueryOptimizerProfiler()
    profiler.run_all_benchmarks()


if __name__ == "__main__":
    main()
