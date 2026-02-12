"""
Performance Benchmarking Suite for Neurosymbolic Reasoning

This module provides comprehensive benchmarks for:
- TDFOL proving performance
- CEC integration overhead  
- Modal logic prover speed
- Parser performance
"""

import time
import statistics
from typing import List, Callable
from dataclasses import dataclass

from ipfs_datasets_py.logic.TDFOL.tdfol_core import (
    Predicate,
    BinaryFormula,
    LogicOperator,
    TemporalFormula,
    DeonticFormula,
    TemporalOperator,
    DeonticOperator,
)
from ipfs_datasets_py.logic.integration import NeurosymbolicReasoner


@dataclass
class BenchmarkResult:
    """Result of a benchmark run."""
    name: str
    iterations: int
    times_ms: List[float]
    mean_ms: float
    median_ms: float
    
    def __str__(self):
        return (
            f"{self.name}: {self.mean_ms:.3f}ms avg ({self.iterations} iterations)"
        )


class PerformanceBenchmark:
    """Performance benchmarking suite."""
    
    def __init__(self):
        self.results: List[BenchmarkResult] = []
    
    def run_benchmark(self, name: str, func: Callable, iterations: int = 100):
        """Run a benchmark."""
        times_ms = []
        
        for _ in range(iterations):
            start = time.perf_counter()
            func()
            end = time.perf_counter()
            times_ms.append((end - start) * 1000)
        
        result = BenchmarkResult(
            name=name,
            iterations=iterations,
            times_ms=times_ms,
            mean_ms=statistics.mean(times_ms),
            median_ms=statistics.median(times_ms),
        )
        
        self.results.append(result)
        print(f"✓ {result}")
        return result


def run_all_benchmarks():
    """Run all performance benchmarks."""
    print("Neurosymbolic Reasoning Performance Benchmarks")
    print("=" * 70)
    
    benchmark = PerformanceBenchmark()
    
    # Parsing benchmarks
    print("\n1. Parsing Benchmarks:")
    reasoner = NeurosymbolicReasoner()
    benchmark.run_benchmark("Parse simple (P)", lambda: reasoner.parse("P", format="tdfol"), 1000)
    benchmark.run_benchmark("Parse implication (P->Q)", lambda: reasoner.parse("P -> Q", format="tdfol"), 1000)
    
    # Proving benchmarks
    print("\n2. Proving Benchmarks:")
    p = Predicate("P", ())
    q = Predicate("Q", ())
    reasoner1 = NeurosymbolicReasoner()
    reasoner1.add_knowledge(p)
    reasoner1.add_knowledge(BinaryFormula(LogicOperator.IMPLIES, p, q))
    benchmark.run_benchmark("Prove Modus Ponens", lambda: reasoner1.prove(q, timeout_ms=1000), 50)
    
    print("\n" + "=" * 70)
    print(f"Total benchmarks: {len(benchmark.results)}")
    print("Benchmark complete!")


if __name__ == "__main__":
    run_all_benchmarks()
