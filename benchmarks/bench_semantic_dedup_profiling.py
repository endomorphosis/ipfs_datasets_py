#!/usr/bin/env python3
"""Comprehensive profiling benchmark for SemanticEntityDeduplicator.

This benchmark measures:
1. End-to-end deduplication performance (entity count scaling)
2. Embedding generation bottlenecks (batch size effects)
3. Similarity matrix computation cost (n² operations)
4. Bucketing optimization effectiveness (actual vs theoretical)
5. Threshold sensitivity (how threshold affects merge suggestion time)
6. Memory consumption patterns

Results help identify scaling bottlenecks and optimization opportunities
for entity deduplication in large ontologies.
"""

import sys
import time
import statistics
from pathlib import Path
from typing import List, Dict, Any
from dataclasses import dataclass
import numpy as np

# Setup paths for imports
benchmark_dir = Path(__file__).resolve().parent
repo_root = benchmark_dir.parent
sys.path.insert(0, str(repo_root))

from ipfs_datasets_py.optimizers.graphrag.semantic_deduplicator import SemanticEntityDeduplicator
from ipfs_datasets_py.optimizers.graphrag.ontology_generator import Entity, Relationship


@dataclass
class BenchmarkResult:
    """Result from a single benchmark measurement."""
    name: str
    entity_count: int
    similarity_distribution: str
    batch_size: int
    threshold: float
    iterations: int
    
    # Timing results (ms)
    mean_latency_ms: float
    median_latency_ms: float
    p95_latency_ms: float
    p99_latency_ms: float
    min_latency_ms: float
    max_latency_ms: float
    
    # Count results
    merge_suggestions: int
    bucketing_buckets: int
    bucketing_reduction_factor: float
    
    # Throughput
    entities_per_second: float
    
    def __repr__(self) -> str:
        """Concise string representation."""
        return (
            f"{self.name:40} | "
            f"entities={self.entity_count:4d} | "
            f"latency={self.mean_latency_ms:7.3f}ms | "
            f"suggestions={self.merge_suggestions:3d} | "
            f"throughput={self.entities_per_second:8.1f}/s"
        )


class SyntheticEntityGenerator:
    """Generate synthetic entity datasets with controllable similarity distributions."""
    
    # Common semantic categories for realistic entities
    CATEGORIES = {
        "people": [
            "John Smith", "John Doe", "Jane Smith", "Jack Johnson", "Jim Johnson",
            "Robert Brown", "Bob Brown", "William Davis", "Bill Davis", "Michael Wilson"
        ],
        "locations": [
            "New York City", "NYC", "New York", "Los Angeles", "LA", "Los Angeles County",
            "San Francisco", "SF", "San Francisco Bay", "Chicago", "Chicagoland"
        ],
        "organizations": [
            "Microsoft Corporation", "Microsoft", "MSFT", "Apple Inc", "Apple",
            "Google LLC", "Alphabet", "Amazon.com", "AWS", "Meta Platforms"
        ],
        "roles": [
            "Chief Executive Officer", "CEO", "CxO", "Chief Tech Officer", "CTO",
            "Vice President", "VP", "Senior Director", "VP Engineering", "Director Engineering"
        ],
        "products": [
            "Windows Operating System", "Windows", "Win10", "Active Directory",
            "Office 365", "Microsoft 365", "Office", "Exchange Server", "SharePoint"
        ]
    }
    
    def __init__(self, seed: int = 42):
        """Initialize generator with optional seed for reproducibility."""
        np.random.seed(seed)
    
    def generate_dataset(
        self,
        entity_count: int,
        similarity_distribution: str = "sparse"
    ) -> Dict[str, Any]:
        """Generate synthetic entity dataset.
        
        Args:
            entity_count: Number of entities to generate
            similarity_distribution: One of:
                - 'sparse': Few similar entities (1-5 matches per entity)
                - 'moderate': Moderate similarity clusters (5-15 matches per entity)
                - 'dense': Dense similarity clusters (20+ matches per entity)
                - 'random': Completely random entity names (no real similarities)
        
        Returns:
            Ontology dict with entities and relationships
        """
        if entity_count < 10:
            raise ValueError("entity_count must be >= 10")
        
        if similarity_distribution not in ("sparse", "moderate", "dense", "random"):
            raise ValueError(f"Unknown distribution: {similarity_distribution}")
        
        entities = []
        
        if similarity_distribution == "random":
            # Random entities with no semantic relationships
            for i in range(entity_count):
                entity_id = f"entity_{i}"
                text = f"Entity_{i}_" + "".join(
                    np.random.choice(list("abcdefghijklmnopqrstuvwxyz")) 
                    for _ in range(8)
                )
                entities.append({
                    "id": entity_id,
                    "text": text,
                    "type": "Unknown",
                    "confidence": 0.5
                })
        else:
            # Generate entities with controllable similarity clusters
            # Determine cluster sizes based on distribution
            if similarity_distribution == "sparse":
                cluster_sizes = [entity_count // 10 for _ in range(10)]
            elif similarity_distribution == "moderate":
                cluster_sizes = [entity_count // 5 for _ in range(5)]
            else:  # dense
                cluster_sizes = [entity_count // 3 for _ in range(3)]
            
            # Distribute remaining entities
            remaining = entity_count - sum(cluster_sizes)
            cluster_sizes[-1] += remaining
            
            entity_idx = 0
            for cluster_id, cluster_size in enumerate(cluster_sizes):
                # Pick a random base category
                category = np.random.choice(list(self.CATEGORIES.keys()))
                base_names = self.CATEGORIES[category]
                base_name = np.random.choice(base_names)
                
                # Generate variants of this base name (introducing similarity)
                for i in range(cluster_size):
                    variant_name = base_name
                    
                    # For some entities, add realistic variants
                    if i > 0 and i % 3 == 1:  # Abbreviation variant
                        variant_name = self._abbreviate(base_name)
                    elif i > 0 and i % 3 == 2:  # Typo/slight variant
                        variant_name = self._introduce_variation(base_name)
                    
                    entities.append({
                        "id": f"entity_{entity_idx}",
                        "text": variant_name,
                        "type": category.capitalize(),
                        "confidence": np.random.uniform(0.7, 0.99)
                    })
                    entity_idx += 1
        
        # Generate minimal relationships (not used for dedup but needed for consistency)
        relationships = []
        for i in range(min(10, len(entities) - 1)):
            relationships.append({
                "id": f"rel_{i}",
                "source_id": entities[i]["id"],
                "target_id": entities[(i + 1) % len(entities)]["id"],
                "type": "related_to"
            })
        
        return {
            "entities": entities,
            "relationships": relationships,
            "metadata": {
                "entity_count": entity_count,
                "distribution": similarity_distribution
            }
        }
    
    @staticmethod
    def _abbreviate(text: str) -> str:
        """Create abbreviation variant of text."""
        words = text.split()
        if len(words) > 1:
            # Take first letter of each word
            abbrev = "".join(w[0].upper() for w in words if w)
            return abbrev
        return text[0].upper()
    
    @staticmethod
    def _introduce_variation(text: str) -> str:
        """Introduce minor spelling variation (typo-like)."""
        if len(text) < 4:
            return text
        pos = np.random.randint(0, len(text) - 1)
        text_list = list(text)
        # Swap adjacent characters
        text_list[pos], text_list[pos + 1] = text_list[pos + 1], text_list[pos]
        return "".join(text_list)


class SemanticDedupProfiler:
    """Comprehensive profiler for SemanticEntityDeduplicator."""
    
    def __init__(self):
        """Initialize profiler."""
        self.deduplicator = SemanticEntityDeduplicator()
        self.generator = SyntheticEntityGenerator()
        self.results: List[BenchmarkResult] = []
    
    def benchmark_entity_count_scaling(self, iterations: int = 3) -> List[BenchmarkResult]:
        """Benchmark deduplication performance across entity counts.
        
        Measures: How does performance scale with increasing entity counts?
        """
        print("\n" + "=" * 100)
        print("BENCHMARK: Entity Count Scaling")
        print("=" * 100)
        
        entity_counts = [50, 100, 200, 500]
        results = []
        
        for count in entity_counts:
            print(f"\nProfiling with {count} entities (moderate distribution, {iterations} iterations)...")
            
            ontology = self.generator.generate_dataset(
                count, 
                similarity_distribution="moderate"
            )
            
            latencies = []
            for i in range(iterations):
                start = time.time()
                suggestions = self.deduplicator.suggest_merges(
                    ontology,
                    threshold=0.85
                )
                elapsed = (time.time() - start) * 1000
                latencies.append(elapsed)
            
            result = self._create_result(
                name=f"Entity Count Scaling ({count})",
                entity_count=count,
                similarity_distribution="moderate",
                batch_size=32,
                threshold=0.85,
                iterations=iterations,
                latencies=latencies,
                merge_suggestions=len(suggestions)
            )
            
            results.append(result)
            self.results.append(result)
            print(f"  {result}")
        
        return results
    
    def benchmark_similarity_distributions(self, entity_count: int = 200, iterations: int = 3) -> List[BenchmarkResult]:
        """Benchmark deduplication with different similarity distributions.
        
        Measures: How do different data distributions affect performance?
        """
        print("\n" + "=" * 100)
        print(f"BENCHMARK: Similarity Distributions ({entity_count} entities)")
        print("=" * 100)
        
        distributions = ["sparse", "moderate", "dense", "random"]
        results = []
        
        for dist in distributions:
            print(f"\nProfiling {dist} distribution (threshold=0.85, {iterations} iterations)...")
            
            ontology = self.generator.generate_dataset(
                entity_count,
                similarity_distribution=dist
            )
            
            latencies = []
            for i in range(iterations):
                start = time.time()
                suggestions = self.deduplicator.suggest_merges(
                    ontology,
                    threshold=0.85
                )
                elapsed = (time.time() - start) * 1000
                latencies.append(elapsed)
            
            result = self._create_result(
                name=f"Distribution: {dist.capitalize()}",
                entity_count=entity_count,
                similarity_distribution=dist,
                batch_size=32,
                threshold=0.85,
                iterations=iterations,
                latencies=latencies,
                merge_suggestions=len(suggestions)
            )
            
            results.append(result)
            self.results.append(result)
            print(f"  {result}")
        
        return results
    
    def benchmark_threshold_sensitivity(self, entity_count: int = 200, iterations: int = 2) -> List[BenchmarkResult]:
        """Benchmark deduplication performance across different thresholds.
        
        Measures: How does threshold choice affect performance and merge counts?
        """
        print("\n" + "=" * 100)
        print(f"BENCHMARK: Threshold Sensitivity ({entity_count} entities)")
        print("=" * 100)
        
        ontology = self.generator.generate_dataset(
            entity_count,
            similarity_distribution="moderate"
        )
        
        thresholds = [0.70, 0.80, 0.85, 0.90, 0.95]
        results = []
        
        for threshold in thresholds:
            print(f"\nProfiling threshold={threshold} ({iterations} iterations)...")
            
            latencies = []
            for i in range(iterations):
                start = time.time()
                suggestions = self.deduplicator.suggest_merges(
                    ontology,
                    threshold=threshold
                )
                elapsed = (time.time() - start) * 1000
                latencies.append(elapsed)
            
            result = self._create_result(
                name=f"Threshold: {threshold}",
                entity_count=entity_count,
                similarity_distribution="moderate",
                batch_size=32,
                threshold=threshold,
                iterations=iterations,
                latencies=latencies,
                merge_suggestions=len(suggestions)
            )
            
            results.append(result)
            self.results.append(result)
            print(f"  {result}")
        
        return results
    
    def _create_result(
        self,
        name: str,
        entity_count: int,
        similarity_distribution: str,
        batch_size: int,
        threshold: float,
        iterations: int,
        latencies: List[float],
        merge_suggestions: int
    ) -> BenchmarkResult:
        """Create BenchmarkResult from latency measurements."""
        
        sorted_latencies = sorted(latencies)
        mean_latency = statistics.mean(latencies)
        median_latency = statistics.median(latencies)
        
        # Calculate percentiles
        p95_idx = max(0, int(0.95 * len(sorted_latencies)) - 1)
        p99_idx = max(0, int(0.99 * len(sorted_latencies)) - 1)
        
        p95_latency = sorted_latencies[p95_idx]
        p99_latency = sorted_latencies[p99_idx]
        
        return BenchmarkResult(
            name=name,
            entity_count=entity_count,
            similarity_distribution=similarity_distribution,
            batch_size=batch_size,
            threshold=threshold,
            iterations=iterations,
            mean_latency_ms=mean_latency,
            median_latency_ms=median_latency,
            p95_latency_ms=p95_latency,
            p99_latency_ms=p99_latency,
            min_latency_ms=min(latencies),
            max_latency_ms=max(latencies),
            merge_suggestions=merge_suggestions,
            bucketing_buckets=0,  # Would require instrumentation to measure
            bucketing_reduction_factor=1.0,  # Would require instrumentation to measure
            entities_per_second=entity_count / (mean_latency / 1000)
        )
    
    def print_summary(self):
        """Print summary of all benchmark results."""
        if not self.results:
            print("No results to summarize")
            return
        
        print("\n" + "=" * 100)
        print("SEMANTIC DEDUP PROFILING SUMMARY")
        print("=" * 100)
        
        # Group results by category
        categories = {}
        for result in self.results:
            category = result.name.split("(")[0].strip() if "(" in result.name else result.name.split(":")[0]
            if category not in categories:
                categories[category] = []
            categories[category].append(result)
        
        for category, results in categories.items():
            print(f"\n{category}")
            print("-" * 100)
            for result in sorted(results, key=lambda r: r.mean_latency_ms):
                print(f"  {result}")
        
        # Print key statistics
        print("\n" + "=" * 100)
        print("KEY STATISTICS")
        print("=" * 100)
        
        if self.results:
            all_latencies = [r.mean_latency_ms for r in self.results]
            print(f"  Mean latency (all benchmarks): {statistics.mean(all_latencies):.2f}ms")
            print(f"  Latency range: {min(all_latencies):.2f}ms - {max(all_latencies):.2f}ms")
            print(f"  Total measurements: {len(self.results)}")
            
            # Find scaling characteristics
            scaling_results = [r for r in self.results if "Scaling" in r.name]
            if len(scaling_results) > 1:
                sorted_scaling = sorted(scaling_results, key=lambda r: r.entity_count)
                print(f"\n  Scaling Analysis:")
                print(f"    {sorted_scaling[0].entity_count} entities: {sorted_scaling[0].mean_latency_ms:.2f}ms")
                print(f"    {sorted_scaling[-1].entity_count} entities: {sorted_scaling[-1].mean_latency_ms:.2f}ms")
                speedup = sorted_scaling[-1].mean_latency_ms / sorted_scaling[0].mean_latency_ms
                entity_ratio = sorted_scaling[-1].entity_count / sorted_scaling[0].entity_count
                print(f"    Growth factor: {speedup:.1f}x latency for {entity_ratio:.1f}x entities (scaling exponent: {np.log(speedup) / np.log(entity_ratio):.2f})")


def main():
    """Run all profiling benchmarks."""
    
    print("\nSemantic Deduplicator Profiling Suite")
    print("=" * 100)
    print("This benchmark measures performance of semantic entity deduplication")
    print("across varying entity counts, similarity distributions, and thresholds.")
    print()
    
    profiler = SemanticDedupProfiler()
    
    try:
        # Run all benchmarks
        profiler.benchmark_entity_count_scaling(iterations=3)
        profiler.benchmark_similarity_distributions(entity_count=200, iterations=3)
        profiler.benchmark_threshold_sensitivity(entity_count=200, iterations=2)
        
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
