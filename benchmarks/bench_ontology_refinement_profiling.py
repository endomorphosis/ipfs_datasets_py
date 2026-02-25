#!/usr/bin/env python3
"""Profiling benchmark for OntologyMediator refinement cycle performance.

This benchmark measures:
1. Single round refinement time (generator + critic overhead)
2. Multi-round convergence time and termination patterns
3. Refinement strategy effectiveness (rule-based, LLM, agentic)
4. Score evolution and convergence characteristics
5. Scaling with ontology size and document complexity

Results help identify bottlenecks in the refinement feedback loop
and guide decisions on round limits and convergence thresholds.
"""

import sys
import time
import statistics
from pathlib import Path
from typing import List, Dict, Any
from dataclasses import dataclass
import numpy as np

# Setup imports
benchmark_dir = Path(__file__).resolve().parent
repo_root = benchmark_dir.parent
sys.path.insert(0, str(repo_root))

from ipfs_datasets_py.optimizers.graphrag import (
    OntologyMediator,
    OntologyGenerator,
    OntologyCritic,
    OntologyGenerationContext,
)


@dataclass
class RefinementBenchmarkResult:
    """Result from a refinement cycle benchmark."""
    name: str
    strategy: str  # rule_based, llm, agentic
    initial_entity_count: int
    rounds_completed: int
    converged: bool
    
    # Timing results (ms)
    mean_round_latency_ms: float
    total_time_ms: float
    min_round_latency_ms: float
    max_round_latency_ms: float
    
    # Score progression
    initial_score: float
    final_score: float
    score_improvement: float
    
    # Throughput
    entities_per_second: float
    
    def __repr__(self) -> str:
        """Concise string representation."""
        return (
            f"{self.name:45} | "
            f"strategy={self.strategy:8} | "
            f"rounds={self.rounds_completed:2d} | "
            f"time={self.total_time_ms:7.1f}ms | "
            f"score={self.initial_score:.3f}→{self.final_score:.3f}"
        )


class SyntheticOntologyDataGenerator:
    """Generate synthetic ontology data for benchmarking."""
    
    def __init__(self, seed: int = 42):
        """Initialize with optional seed."""
        np.random.seed(seed)
    
    def generate_extraction_result(
        self,
        entity_count: int,
        relationship_density: float = 0.1,
        quality_level: str = "moderate"
    ) -> Dict[str, Any]:
        """Generate mock extraction result.
        
        Args:
            entity_count: Number of entities to generate
            relationship_density: Fraction of possible relationships (0.0-1.0)
            quality_level: 'poor', 'moderate', or 'good' (affects initial errors)
        
        Returns:
            Mock extraction result with entities and relationships
        """
        entities = []
        for i in range(entity_count):
            entity_type = np.random.choice(
                ["Person", "Organization", "Location", "Product", "Process"]
            )
            confidence = np.random.uniform(0.6, 0.99)
            
            # Adjust confidence based on quality level
            if quality_level == "poor":
                confidence *= 0.7
            elif quality_level == "good":
                confidence = min(0.99, confidence + 0.1)
            
            entities.append({
                "id": f"entity_{i}",
                "text": f"{entity_type}_{i}",
                "type": entity_type,
                "confidence": confidence,
            })
        
        # Generate relationships
        relationships = []
        max_relationships = int(entity_count * (entity_count - 1) / 2 * relationship_density)
        
        for _ in range(min(max_relationships, entity_count * 3)):  # Cap at 3x entities
            source_idx = np.random.randint(0, entity_count)
            target_idx = np.random.randint(0, entity_count)
            
            if source_idx != target_idx:
                relationships.append({
                    "id": f"rel_{source_idx}_{target_idx}",
                    "source_id": f"entity_{source_idx}",
                    "target_id": f"entity_{target_idx}",
                    "type": np.random.choice(
                        ["related_to", "works_for", "located_in", "part_of"]
                    ),
                })
        
        return {
            "entities": entities,
            "relationships": relationships,
            "text": "Synthetic ontology data for benchmarking refinement cycles.",
        }


class OntologyRefinementProfiler:
    """Profile OntologyMediator refinement cycle performance."""
    
    def __init__(self):
        """Initialize profiler."""
        self.data_generator = SyntheticOntologyDataGenerator()
        self.results: List[RefinementBenchmarkResult] = []
    
    def benchmark_single_round_overhead(self, entity_counts: List[int] = None) -> List[RefinementBenchmarkResult]:
        """Benchmark single-round refinement overhead (generator + critic).
        
        Measures: What's the cost of one generate→critique cycle?
        """
        if entity_counts is None:
            entity_counts = [50, 100, 200]
        
        print("\n" + "=" * 100)
        print("BENCHMARK: Single Round Refinement Overhead")
        print("=" * 100)
        
        results = []
        
        for entity_count in entity_counts:
            print(f"\nProfiling single round with {entity_count} entities...")
            
            ontology_data = self.data_generator.generate_extraction_result(
                entity_count,
                relationship_density=0.05,
                quality_level="moderate"
            )
            
            generator = OntologyGenerator()
            critic = OntologyCritic()
            mediator = OntologyMediator(
                generator=generator,
                critic=critic,
                max_rounds=1,
                convergence_threshold=0.01
            )
            
            context = OntologyGenerationContext(
                text=ontology_data["text"],
                domain="general",
            )
            
            start = time.time()
            state = mediator.run_refinement_cycle(ontology_data, context)
            elapsed = (time.time() - start) * 1000
            
            result = RefinementBenchmarkResult(
                name=f"Single Round ({entity_count} entities)",
                strategy="rule_based",
                initial_entity_count=entity_count,
                rounds_completed=state.current_round,
                converged=state.converged,
                mean_round_latency_ms=elapsed,
                total_time_ms=elapsed,
                min_round_latency_ms=elapsed,
                max_round_latency_ms=elapsed,
                initial_score=0.5,  # Mock initial score
                final_score=state.critic_scores[-1].overall if state.critic_scores else 0.5,
                score_improvement=0.0,  # Would require tracking
                entities_per_second=entity_count / (elapsed / 1000),
            )
            
            results.append(result)
            self.results.append(result)
            print(f"  {result}")
        
        return results
    
    def benchmark_convergence_patterns(
        self,
        entity_count: int = 100,
        max_rounds: int = 10
    ) -> List[RefinementBenchmarkResult]:
        """Benchmark multi-round convergence patterns.
        
        Measures: How do score and time evolve across refinement rounds?
        """
        print("\n" + "=" * 100)
        print(f"BENCHMARK: Convergence Patterns ({entity_count} entities, {max_rounds} max rounds)")
        print("=" * 100)
        
        results = []
        qualities = ["poor", "moderate", "good"]
        
        for quality in qualities:
            print(f"\nProfiling {quality} initial quality ({max_rounds} rounds)...")
            
            ontology_data = self.data_generator.generate_extraction_result(
                entity_count,
                relationship_density=0.1,
                quality_level=quality
            )
            
            generator = OntologyGenerator()
            critic = OntologyCritic()
            mediator = OntologyMediator(
                generator=generator,
                critic=critic,
                max_rounds=max_rounds,
                convergence_threshold=0.01
            )
            
            context = OntologyGenerationContext(
                text=ontology_data["text"],
                domain="general",
            )
            
            start = time.time()
            state = mediator.run_refinement_cycle(ontology_data, context)
            elapsed = (time.time() - start) * 1000
            
            initial_score = state.critic_scores[0].overall if state.critic_scores else 0.5
            final_score = state.critic_scores[-1].overall if state.critic_scores else 0.5
            
            result = RefinementBenchmarkResult(
                name=f"Convergence: {quality.capitalize()}",
                strategy="rule_based",
                initial_entity_count=entity_count,
                rounds_completed=state.current_round,
                converged=state.converged,
                mean_round_latency_ms=elapsed / max(1, state.current_round),
                total_time_ms=elapsed,
                min_round_latency_ms=elapsed / max(1, state.current_round),
                max_round_latency_ms=elapsed / max(1, state.current_round),
                initial_score=initial_score,
                final_score=final_score,
                score_improvement=final_score - initial_score,
                entities_per_second=entity_count / (elapsed / 1000),
            )
            
            results.append(result)
            self.results.append(result)
            print(f"  {result}")
        
        return results
    
    def benchmark_strategy_comparison(
        self,
        entity_count: int = 100,
        iterations: int = 2
    ) -> List[RefinementBenchmarkResult]:
        """Benchmark different refinement strategies.
        
        Measures: How do different strategies (rule-based, LLM, agentic) perform?
        """
        print("\n" + "=" * 100)
        print(f"BENCHMARK: Strategy Comparison ({entity_count} entities)")
        print("=" * 100)
        
        strategies = ["rule_based"]  # llm and agentic require LLM backend
        results = []
        
        for strategy in strategies:
            print(f"\nProfiling {strategy} strategy ({iterations} iterations)...")
            
            latencies = []
            scores = []
            
            for i in range(iterations):
                ontology_data = self.data_generator.generate_extraction_result(
                    entity_count,
                    relationship_density=0.1,
                    quality_level="moderate"
                )
                
                generator = OntologyGenerator()
                critic = OntologyCritic()
                mediator = OntologyMediator(
                    generator=generator,
                    critic=critic,
                    max_rounds=5,
                    convergence_threshold=0.01
                )
                
                context = OntologyGenerationContext(
                    text=ontology_data["text"],
                    domain="general",
                )
                
                start = time.time()
                state = mediator.run_refinement_cycle(ontology_data, context)
                elapsed = (time.time() - start) * 1000
                latencies.append(elapsed)
                
                final_score = state.critic_scores[-1].overall if state.critic_scores else 0.5
                scores.append(final_score)
            
            result = RefinementBenchmarkResult(
                name=f"Strategy: {strategy.capitalize()}",
                strategy=strategy,
                initial_entity_count=entity_count,
                rounds_completed=5,
                converged=False,
                mean_round_latency_ms=statistics.mean(latencies) / 5,
                total_time_ms=statistics.mean(latencies),
                min_round_latency_ms=min(latencies) / 5,
                max_round_latency_ms=max(latencies) / 5,
                initial_score=0.65,
                final_score=statistics.mean(scores),
                score_improvement=statistics.mean(scores) - 0.65,
                entities_per_second=entity_count / (statistics.mean(latencies) / 1000),
            )
            
            results.append(result)
            self.results.append(result)
            print(f"  {result}")
        
        return results
    
    def print_summary(self):
        """Print summary of all benchmark results."""
        if not self.results:
            print("No results to summarize")
            return
        
        print("\n" + "=" * 100)
        print("ONTOLOGY REFINEMENT PROFILING SUMMARY")
        print("=" * 100)
        
        # Group by category
        categories = {}
        for result in self.results:
            category = result.name.split("(")[0].strip() if "(" in result.name else result.name.split(":")[0]
            if category not in categories:
                categories[category] = []
            categories[category].append(result)
        
        for category, results in categories.items():
            print(f"\n{category}")
            print("-" * 100)
            for result in sorted(results, key=lambda r: r.total_time_ms):
                print(f"  {result}")


def main():
    """Run all refinement profiling benchmarks."""
    
    print("\nOntology Refinement Cycle Profiling Suite")
    print("=" * 100)
    print("This benchmark measures performance of ontology refinement across")
    print("various entity counts, quality levels, and refinement strategies.")
    print()
    
    profiler = OntologyRefinementProfiler()
    
    try:
        # Run benchmarks
        profiler.benchmark_single_round_overhead(entity_counts=[50, 100, 200])
        profiler.benchmark_convergence_patterns(entity_count=100, max_rounds=5)
        profiler.benchmark_strategy_comparison(entity_count=100, iterations=1)
        
        # Print summary
        profiler.print_summary()
        
        return 0
        
    except Exception as e:
        print(f"\nError during profiling: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
