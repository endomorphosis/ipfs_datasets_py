#!/usr/bin/env python3
"""
Example 2: Proof Caching Performance Demo

This example demonstrates the dramatic performance improvement from
proof caching using CID (Content ID) hashing for O(1) lookups.

Demonstrates:
- First call: compute proof (slow)
- Second call: cache hit (very fast, ~0.1ms)
- Cache statistics
- Performance comparison across provers
- Cost savings for LLM-based proving
"""

import sys
import time
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

def measure_time(func):
    """Decorator to measure execution time."""
    def wrapper(*args, **kwargs):
        start = time.time()
        result = func(*args, **kwargs)
        elapsed = (time.time() - start) * 1000  # Convert to ms
        return result, elapsed
    return wrapper

def main():
    print("=" * 70)
    print("Example 2: Proof Caching Performance Demonstration")
    print("=" * 70)
    print()
    
    from ipfs_datasets_py.logic.external_provers import (
        Z3ProverBridge,
        Z3_AVAILABLE,
        get_available_provers
    )
    from ipfs_datasets_py.logic.external_provers.proof_cache import get_global_cache
    from ipfs_datasets_py.logic.TDFOL import parse_tdfol
    
    # Check available provers
    available = get_available_provers()
    print(f"Available provers: {', '.join(available)}")
    print()
    
    if not Z3_AVAILABLE:
        print("❌ Z3 not available. Install with: pip install z3-solver")
        return
    
    # Get global cache
    cache = get_global_cache()
    
    # Clear cache to start fresh
    cache.clear()
    print("✓ Cache cleared for clean test")
    print()
    
    # Test formulas
    formulas = [
        ("P -> P", "Simple tautology"),
        ("P & Q -> P", "Conjunction elimination"),
        ("forall x. P(x) -> P(x)", "Universal tautology"),
        ("(P -> Q) & (Q -> R) -> (P -> R)", "Hypothetical syllogism"),
        ("P | ~P", "Law of excluded middle"),
    ]
    
    # Test with Z3
    print("Testing with Z3 SMT Solver")
    print("=" * 70)
    print()
    
    prover_cached = Z3ProverBridge(enable_cache=True)
    prover_uncached = Z3ProverBridge(enable_cache=False)
    
    total_uncached = 0
    total_cached_first = 0
    total_cached_second = 0
    
    for formula_str, description in formulas:
        formula = parse_tdfol(formula_str)
        
        print(f"Formula: {formula_str}")
        print(f"Description: {description}")
        print("-" * 70)
        
        # Test 1: Without cache
        @measure_time
        def prove_uncached():
            return prover_uncached.prove(formula)
        
        result1, time1 = prove_uncached()
        total_uncached += time1
        print(f"Without cache: {time1:.3f}ms")
        
        # Test 2: With cache (first call - cache miss)
        @measure_time
        def prove_cached_first():
            return prover_cached.prove(formula)
        
        result2, time2 = prove_cached_first()
        total_cached_first += time2
        print(f"With cache (1st call - MISS): {time2:.3f}ms")
        
        # Test 3: With cache (second call - cache hit!)
        @measure_time
        def prove_cached_second():
            return prover_cached.prove(formula)
        
        result3, time3 = prove_cached_second()
        total_cached_second += time3
        speedup = time1 / time3 if time3 > 0 else float('inf')
        print(f"With cache (2nd call - HIT): {time3:.3f}ms (⚡ {speedup:.0f}x faster!)")
        
        print()
    
    # Summary
    print("=" * 70)
    print("PERFORMANCE SUMMARY")
    print("=" * 70)
    print()
    
    print(f"Total time without cache: {total_uncached:.2f}ms")
    print(f"Total time with cache (first calls): {total_cached_first:.2f}ms")
    print(f"Total time with cache (second calls): {total_cached_second:.2f}ms")
    print()
    
    avg_speedup = total_uncached / total_cached_second if total_cached_second > 0 else float('inf')
    print(f"Average speedup from caching: {avg_speedup:.0f}x")
    print()
    
    # Cache statistics
    stats = cache.get_stats()
    print("CACHE STATISTICS")
    print("=" * 70)
    print(f"Total requests: {stats['total_requests']}")
    print(f"Cache hits: {stats['hits']}")
    print(f"Cache misses: {stats['misses']}")
    print(f"Hit rate: {stats['hit_rate']:.1%}")
    print(f"Cache size: {stats['cache_size']}/{stats['maxsize']}")
    print()
    
    # Cost analysis for LLM-based proving
    print("=" * 70)
    print("COST ANALYSIS (if using LLM-based prover)")
    print("=" * 70)
    print()
    print("Assumptions:")
    print("  - LLM call cost: $0.01 per request")
    print("  - LLM call time: ~2000ms per request")
    print()
    
    num_formulas = len(formulas)
    llm_time_uncached = num_formulas * 2000  # ms
    llm_time_cached = num_formulas * 2000 + num_formulas * 0.1  # First calls + cache hits
    llm_cost_uncached = num_formulas * 2 * 0.01  # Two calls per formula
    llm_cost_cached = num_formulas * 0.01  # Only first calls cost money
    
    print(f"Without cache:")
    print(f"  - Total time: ~{llm_time_uncached}ms ({llm_time_uncached/1000:.1f}s)")
    print(f"  - Total cost: ${llm_cost_uncached:.2f}")
    print()
    print(f"With cache:")
    print(f"  - Total time: ~{llm_time_cached:.1f}ms ({llm_time_cached/1000:.1f}s)")
    print(f"  - Total cost: ${llm_cost_cached:.2f}")
    print()
    print(f"Savings with cache:")
    print(f"  - Time saved: ~{llm_time_uncached - llm_time_cached:.0f}ms ({(llm_time_uncached - llm_time_cached)/1000:.1f}s)")
    print(f"  - Cost saved: ${llm_cost_uncached - llm_cost_cached:.2f} ({(llm_cost_uncached - llm_cost_cached)/llm_cost_uncached*100:.0f}%)")
    print()
    
    # Key takeaways
    print("=" * 70)
    print("KEY TAKEAWAYS")
    print("=" * 70)
    print()
    print("1. ⚡ Cached lookups are ~100-1000x faster (O(1) hash lookup)")
    print("2. 💰 Caching saves significant API costs for LLM-based proving")
    print("3. 🎯 Cache hit rate improves with repeated queries")
    print("4. 📈 Performance scales well with large problem sets")
    print("5. 🔒 CID-based keys ensure deterministic, collision-resistant hashing")
    print()
    print("Recommendation: Always enable caching in production!")
    print("=" * 70)


if __name__ == "__main__":
    main()
