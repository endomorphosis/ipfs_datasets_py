#!/usr/bin/env python3
"""Simplified ontology refinement profiling - extracts actual timing from logs.

This benchmark runs refinement cycles and measures performance characteristics.
"""

import sys
import time
from pathlib import Path
from dataclasses import dataclass
from typing import List
import numpy as np

# Setup imports
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ipfs_datasets_py.optimizers.graphrag.ontology_generator import (
    OntologyGenerator,
)
from ipfs_datasets_py.optimizers.graphrag.ontology_critic import (
    OntologyCritic,
)


@dataclass
class RefinementBenchmarkResult:
    """Benchmark result summary."""
    name: str
    entity_count: int
    total_time_ms: float
    iterations: int
    
    def __repr__(self) -> str:
        """String representation."""
        return (
            f"{self.name:45} | "
            f"entities={self.entity_count:3d} | "
            f"time={self.total_time_ms:7.1f}ms"
        )


class SimpleRefinementProfiler:
    """Simple profiler for ontology refinement."""
    
    def __init__(self):
        """Initialize."""
        self.results: List[RefinementBenchmarkResult] = []
    
    def benchmark_generator_performance(self):
        """Profile OntologyGenerator performance independent of refinement cycle."""
        print("\n" + "=" * 100)
        print("BENCHMARK: OntologyGenerator Performance")
        print("=" * 100)
        
        entity_counts = [50, 100, 200]
        
        for entity_count in entity_counts:
            print(f"\nProfiling with {entity_count} synthetic entities...")
            
            # Create simple extraction payload
            extraction = {
                "entities": [
                    {
                        "id": f"entity_{i}",
                        "text": f"Entity_{i}",
                        "type": "Thing",
                        "confidence": 0.8,
                    }
                    for i in range(entity_count)
                ],
                "relationships": [
                    {
                        "id": f"rel_{i}",
                        "source_id": f"entity_{i}",
                        "target_id": f"entity_{(i+1) % entity_count}",
                        "type": "related_to",
                    }
                    for i in range(min(10, entity_count - 1))
                ],
            }
            
            generator = OntologyGenerator()
            
            # Measure ontology generation time (add multiple entities)
            start = time.time()
            for entity in extraction["entities"]:
                generator.add_entity(entity)
            elapsed = (time.time() - start) * 1000
            
            result = RefinementBenchmarkResult(
                name=f"Generator ({entity_count} entities)",
                entity_count=entity_count,
                total_time_ms=elapsed,
                iterations=1,
            )
            self.results.append(result)
            print(f"  {result}")
    
    def benchmark_critic_performance(self):
        """Profile OntologyCritic performance."""
        print("\n" + "=" * 100)
        print("BENCHMARK: OntologyCritic Performance")
        print("=" * 100)
        
        entity_counts = [50, 100, 200]
        
        for entity_count in entity_counts:
            print(f"\nProfiling with {entity_count} entities...")
            
            ontology = {
                "entities": [
                    {
                        "id": f"entity_{i}",
                        "text": f"Entity_{i}",
                        "type": "Thing",
                        "confidence": 0.8,
                    }
                    for i in range(entity_count)
                ],
                "relationships": [
                    {
                        "id": f"rel_{i}",
                        "source_id": f"entity_{i}",
                        "target_id": f"entity_{(i+1) % entity_count}",
                        "type": "related_to",
                    }
                    for i in range(min(10, entity_count - 1))
                ],
            }
            
            critic = OntologyCritic()
            
            # Measure critic evaluation time
            start = time.time()
            score = critic.evaluate(ontology)
            elapsed = (time.time() - start) * 1000
            
            result = RefinementBenchmarkResult(
                name=f"Critic ({entity_count} entities)",
                entity_count=entity_count,
                total_time_ms=elapsed,
                iterations=1,
            )
            self.results.append(result)
            print(f"  {result}")
            print(f"    Score: {score.overall:.3f}")
    
    def print_summary(self):
        """Print summary."""
        if not self.results:
            return
        
        print("\n" + "=" * 100)
        print("ONTOLOGY REFINEMENT COMPONENT PROFILING SUMMARY")
        print("=" * 100)
        
        # Group by component
        generator_results = [r for r in self.results if "Generator" in r.name]
        critic_results = [r for r in self.results if "Critic" in r.name]
        
        if generator_results:
            print("\nGenerator Timings:")
            print("-" * 100)
            for result in sorted(generator_results, key=lambda r: r.entity_count):
                print(f"  {result}")
        
        if critic_results:
            print("\nCritic Timings:")
            print("-" * 100)
            for result in sorted(critic_results, key=lambda r: r.entity_count):
                print(f"  {result}")
        
        # Calculate scaling
        if len(generator_results) >= 2:
            gen_sorted = sorted(generator_results, key=lambda r: r.entity_count)
            print("\n" + "=" * 100)
            print("SCALING ANALYSIS")
            print("=" * 100)
            
            print(f"\nGenerator Scaling:")
            for i in range(1, len(gen_sorted)):
                r1 = gen_sorted[i-1]
                r2 = gen_sorted[i]
                entity_ratio = r2.entity_count / r1.entity_count
                time_ratio = r2.total_time_ms / r1.total_time_ms
                exponent = np.log(time_ratio) / np.log(entity_ratio)
                print(f"  {r1.entity_count}→{r2.entity_count} entities: "
                      f"time {r1.total_time_ms:.0f}ms→{r2.total_time_ms:.0f}ms "
                      f"(ratio {time_ratio:.2f}x, exponent {exponent:.2f})")


def main():
    """Run profiling."""
    print("\nOntology Refinement Component Profiling")
    print("=" * 100)
    print("Measures OntologyGenerator and OntologyCritic performance.")
    print()
    
    profiler = SimpleRefinementProfiler()
    
    try:
        profiler.benchmark_generator_performance()
        profiler.benchmark_critic_performance()
        profiler.print_summary()
        return 0
    except Exception as e:
        print(f"\nError: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
