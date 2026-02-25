"""
Detailed component profiling for query optimizer bottleneck identification.

Profiles individual components within optimize_query to identify optimization targets:
- Cache key generation (target: 23% of cost)
- Vector optimization (target: 34% of cost)
- Weight calculation (target: 18% of cost)
"""

import sys
import time
import statistics
from pathlib import Path
from typing import Dict, Any, List, Tuple, Callable
import json

# Setup path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ipfs_datasets_py.optimizers.graphrag.query_unified_optimizer import (
    UnifiedGraphRAGQueryOptimizer,
)


class QueryOptimizerComponentProfiler:
    """Profile individual components of query optimizer."""
    
    def __init__(self, repeat_count: int = 100):
        self.repeat_count = repeat_count
        self.optimizer = UnifiedGraphRAGQueryOptimizer()
        self.results = {}
        
    def create_test_queries(self) -> List[Dict[str, Any]]:
        """Create diverse test queries."""
        return [
            # Simple query
            {
                "query_text": "find entity A",
                "max_vector_results": 5,
                "traversal": {"max_depth": 2},
            },
            # Moderate query with vector
            {
                "query_text": "find highly related entities",
                "query_vector": [0.1] * 768,  # Fake 768-dim vector
                "max_vector_results": 10,
                "traversal": {"max_depth": 3, "edge_types": ["related_to"]},
            },
            # Complex query
            {
                "query_text": "find entities with multiple relationships",
                "query_vector": [0.2] * 768,
                "max_vector_results": 20,
                "traversal": {
                    "max_depth": 4,
                    "edge_types": ["related_to", "parent_of", "child_of", "mentions"],
                    "entity_ids": ["e1", "e2", "e3", "e4", "e5"],
                },
            },
            # Batch query
            {
                "query_text": "batch query with multiple params",
                "query_vector": [0.3] * 768,
                "max_vector_results": 15,
                "traversal": {
                    "max_depth": 3,
                    "edge_types": ["related_to", "mentions"],
                },
                "min_similarity": 0.7,
            },
        ]
    
    def profile_cache_key_generation(self) -> Dict[str, Any]:
        """Profile cache key generation step."""
        import hashlib
        import copy
        
        queries = self.create_test_queries()
        times = []
        
        for _ in range(self.repeat_count):
            for query in queries:
                start = time.perf_counter()
                
                # Simulate cache key generation
                key_query = copy.deepcopy(query)
                if "query_vector" in key_query:
                    key_query["query_vector"] = "[vector]"
                key = hashlib.sha256(
                    json.dumps(key_query, sort_keys=True, default=str).encode("utf-8")
                ).hexdigest()
                
                elapsed = (time.perf_counter() - start) * 1000  # ms
                times.append(elapsed)
        
        return {
            "mean_ms": statistics.mean(times),
            "median_ms": statistics.median(times),
            "stdev_ms": statistics.stdev(times) if len(times) > 1 else 0,
            "min_ms": min(times),
            "max_ms": max(times),
            "samples": len(times),
        }
    
    def profile_query_validation(self) -> Dict[str, Any]:
        """Profile query validation step."""
        queries = self.create_test_queries()
        times = []
        
        for _ in range(self.repeat_count):
            for query in queries:
                start = time.perf_counter()
                
                # Profile validation only
                result = self.optimizer._validate_query_parameters(query)
                
                elapsed = (time.perf_counter() - start) * 1000  # ms
                times.append(elapsed)
        
        return {
            "mean_ms": statistics.mean(times),
            "median_ms": statistics.median(times),
            "stdev_ms": statistics.stdev(times) if len(times) > 1 else 0,
            "min_ms": min(times),
            "max_ms": max(times),
            "samples": len(times),
        }
    
    def profile_graph_type_detection(self) -> Dict[str, Any]:
        """Profile graph type detection step."""
        queries = self.create_test_queries()
        times = []
        
        for _ in range(self.repeat_count):
            for query in queries:
                start = time.perf_counter()
                
                # Profile graph type detection
                try:
                    graph_type = self.optimizer.detect_graph_type(query)
                except (KeyError, TypeError, ValueError, AttributeError):
                    graph_type = "general"
                
                elapsed = (time.perf_counter() - start) * 1000  # ms
                times.append(elapsed)
        
        return {
            "mean_ms": statistics.mean(times),
            "median_ms": statistics.median(times),
            "stdev_ms": statistics.stdev(times) if len(times) > 1 else 0,
            "min_ms": min(times),
            "max_ms": max(times),
            "samples": len(times),
        }
    
    def profile_weight_calculation(self) -> Dict[str, Any]:
        """Profile weight calculation and extraction."""
        queries = self.create_test_queries()
        times = []
        
        for _ in range(self.repeat_count):
            for query in queries:
                start = time.perf_counter()
                
                # Profile weight calculation
                weights = {
                    "vector": float(getattr(self.optimizer, "vector_weight", 0.7)),
                    "graph": float(getattr(self.optimizer, "graph_weight", 0.3)),
                }
                
                # Normalization check
                total = weights["vector"] + weights["graph"]
                if total > 0:
                    weights["vector"] /= total
                    weights["graph"] /= total
                
                elapsed = (time.perf_counter() - start) * 1000  # ms
                times.append(elapsed)
        
        return {
            "mean_ms": statistics.mean(times),
            "median_ms": statistics.median(times),
            "stdev_ms": statistics.stdev(times) if len(times) > 1 else 0,
            "min_ms": min(times),
            "max_ms": max(times),
            "samples": len(times),
        }
    
    def profile_full_optimize_query(self) -> Dict[str, Any]:
        """Profile the complete optimize_query method."""
        queries = self.create_test_queries()
        times = []
        
        for _ in range(self.repeat_count):
            for query in queries:
                start = time.perf_counter()
                
                # Profile full method
                result = self.optimizer.optimize_query(query)
                
                elapsed = (time.perf_counter() - start) * 1000  # ms
                times.append(elapsed)
        
        return {
            "mean_ms": statistics.mean(times),
            "median_ms": statistics.median(times),
            "stdev_ms": statistics.stdev(times) if len(times) > 1 else 0,
            "min_ms": min(times),
            "max_ms": max(times),
            "samples": len(times),
        }
    
    def profile_all_components(self) -> None:
        """Profile all components and print results."""
        print("=" * 80)
        print("Query Optimizer Component Profiling")
        print("=" * 80)
        print(f"Repeat count: {self.repeat_count} iterations per component")
        print()
        
        components = [
            ("Cache Key Generation", self.profile_cache_key_generation),
            ("Query Validation", self.profile_query_validation),
            ("Graph Type Detection", self.profile_graph_type_detection),
            ("Weight Calculation", self.profile_weight_calculation),
            ("Full optimize_query", self.profile_full_optimize_query),
        ]
        
        for name, profile_func in components:
            print(f"\n{name}:")
            print("-" * 40)
            
            stats = profile_func()
            
            print(f"  Mean:   {stats['mean_ms']:.6f} ms")
            print(f"  Median: {stats['median_ms']:.6f} ms")
            print(f"  StDev:  {stats['stdev_ms']:.6f} ms")
            print(f"  Min:    {stats['min_ms']:.6f} ms")
            print(f"  Max:    {stats['max_ms']:.6f} ms")
            print(f"  Samples: {stats['samples']}")
            
            self.results[name] = stats
    
    def print_component_breakdown(self) -> None:
        """Print breakdown of component costs relative to full method."""
        if "Full optimize_query" not in self.results:
            return
        
        full_time = self.results["Full optimize_query"]["mean_ms"]
        
        print("\n" + "=" * 80)
        print("Component Cost Breakdown (Relative to Full optimize_query)")
        print("=" * 80)
        print(f"Total time: {full_time:.6f} ms\n")
        
        for name, stats in self.results.items():
            if name == "Full optimize_query":
                continue
            
            component_time = stats["mean_ms"]
            percentage = (component_time / full_time * 100) if full_time > 0 else 0
            
            bar_width = int(percentage / 2)
            bar = "█" * bar_width + "░" * (50 - bar_width)
            
            print(f"{name:30s} {percentage:6.2f}% {bar}")
        
        print("\n" + "=" * 80)
        print("Expected Optimization Targets (from prior analysis):")
        print("=" * 80)
        print("- Vector optimization path:        34% (should be already in full method)")
        print("- Cache key generation:           23% (now measured)")
        print("- Weight calculation:             18% (now measured)")
        print("=" * 80)


if __name__ == "__main__":
    profiler = QueryOptimizerComponentProfiler(repeat_count=100)
    profiler.profile_all_components()
    profiler.print_component_breakdown()
    
    print("\n" + "=" * 80)
    print("Optimization Recommendations:")
    print("=" * 80)
    print("""
1. CACHE KEY GENERATION (if >10% of total):
   - Memoize common query patterns
   - Use fingerprints for vector queries
   - Cache hash results for repeated queries
   
2. WEIGHT CALCULATION (if >5% of total):
   - Pre-compute weight ratios for common scenarios
   - Use lookup table instead of float division
   - Cache normalized weights
   
3. EARLY EXIT (optimizable if query types are diverse):
   - For simple queries: skip complex optimization steps
   - Return fast path for cached queries
   - Avoid deep object traversal for light queries
""")
    print("=" * 80)
