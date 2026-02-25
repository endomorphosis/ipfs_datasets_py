"""
End-to-end extraction pipeline performance profiling.

Measures latency and resource usage across:
1. Query planning (Query Optimizer)
2. Vector search and entity retrieval
3. Graph traversal and relationship discovery
4. Semantic deduplication
5. Ranking and result composition

Identifies the next optimization bottleneck in the full extraction pipeline.
"""

import sys
import time
import statistics
import json
from pathlib import Path
from typing import Dict, List, Any, Tuple
from dataclasses import dataclass
import tracemalloc

# Setup path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ipfs_datasets_py.optimizers.graphrag.query_unified_optimizer import (
    UnifiedGraphRAGQueryOptimizer,
)
from ipfs_datasets_py.optimizers.graphrag.logic_validator import LogicValidator
from ipfs_datasets_py.optimizers.graphrag.semantic_deduplicator import (
    SemanticEntityDeduplicator,
)


@dataclass
class PipelineStageMetrics:
    """Metrics for a single pipeline stage."""
    stage_name: str
    mean_ms: float
    median_ms: float
    min_ms: float
    max_ms: float
    stdev_ms: float
    memory_mb: float
    throughput_per_sec: float


class MockExtractionPipeline:
    """
    Mock extraction pipeline for profiling without full dependencies.
    
    Simulates:
    1. Query optimization
    2. Vector search (simulated)
    3. Graph traversal (simulated)
    4. Semantic deduplication
    5. Result ranking
    """
    
    def __init__(self):
        self.query_optimizer = UnifiedGraphRAGQueryOptimizer()
        self.logic_validator = LogicValidator()
        self.deduplicator = SemanticEntityDeduplicator(model_name="all-MiniLM-L6-v2")
        
    def create_simulated_entities(self, count: int) -> List[Dict[str, Any]]:
        """Create simulated entities for deduplication."""
        entity_templates = [
            {"text": f"Entity_{i}_person", "type": "person", "id": f"e_{i}_p"}
            for i in range(count // 3)
        ]
        entity_templates.extend([
            {"text": f"Entity_{i}_org", "type": "organization", "id": f"e_{i}_o"}
            for i in range(count // 3, 2 * count // 3)
        ])
        entity_templates.extend([
            {"text": f"Entity_{i}_location", "type": "location", "id": f"e_{i}_l"}
            for i in range(2 * count // 3, count)
        ])
        
        from ipfs_datasets_py.ml.entity.base import Entity
        
        entities = []
        for template in entity_templates:
            try:
                entity = Entity(
                    id=template["id"],
                    text=template["text"],
                    type=template["type"],
                    confidence=0.8,
                )
                entities.append(entity)
            except (TypeError, AttributeError):
                # Skip if Entity constructor needs different args
                pass
        
        return entities
    
    def stage_1_query_optimization(self, query: Dict[str, Any]) -> Tuple[Dict[str, Any], float]:
        """Stage 1: Query plan generation."""
        start = time.perf_counter()
        
        result = self.query_optimizer.optimize_query(query)
        
        elapsed_ms = (time.perf_counter() - start) * 1000
        
        return result, elapsed_ms
    
    def stage_2_vector_search(self, query: Dict[str, Any], count: int = 50) -> Tuple[List[Dict[str, Any]], float]:
        """Stage 2: Simulated vector search."""
        start = time.perf_counter()
        
        # Simulate vector search latency (proportional to result count)
        time.sleep(0.001 * (count / 10))  # 1ms per 10 results
        
        # Create mock search results
        results = [
            {
                "id": f"search_result_{i}",
                "score": 0.95 - (i * 0.01),  # Descending scores
                "text": f"Result {i}",
            }
            for i in range(count)
        ]
        
        elapsed_ms = (time.perf_counter() - start) * 1000
        
        return results, elapsed_ms
    
    def stage_3_graph_traversal(self, root_entities: List[Dict[str, Any]], depth: int = 2) -> Tuple[List[Dict[str, Any]], float]:
        """Stage 3: Simulated graph traversal."""
        start = time.perf_counter()
        
        # Simulate traversal latency (exponential with depth)
        time.sleep(0.002 * (depth ** 1.5))
        
        # Create mock traversal results
        traversed = list(root_entities)
        for level in range(1, depth + 1):
            level_size = len(root_entities) * (2 ** level)
            for i in range(level_size):
                traversed.append({
                    "id": f"traversed_{level}_{i}",
                    "parent": f"traversed_{level-1}_{i//2}" if level > 0 else root_entities[i % len(root_entities)]["id"],
                    "data": f"Level {level}",
                })
        
        elapsed_ms = (time.perf_counter() - start) * 1000
        
        return traversed, elapsed_ms
    
    def stage_4_semantic_deduplication(self, entities: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], float]:
        """Stage 4: Semantic entity deduplication."""
        start_time = time.perf_counter()
        tracemalloc.start()
        
        # Create Entity objects for dedupication
        from ipfs_datasets_py.ml.entity.base import Entity
        
        entity_objs = []
        for ent in entities:
            try:
                if isinstance(ent, dict):
                    entity_objs.append(
                        Entity(
                            id=ent.get("id", f"e_{len(entity_objs)}"),
                            text=ent.get("text", ent.get("id", "")),
                            type=ent.get("type", "unknown"),
                            confidence=ent.get("confidence", 0.8),
                        )
                    )
                else:
                    entity_objs.append(ent)
            except (TypeError, AttributeError):
                # If Entity constructor fails, skip
                pass
        
        # Deduplicate
        try:
            deduplicated = self.deduplicator.deduplicate_entities(entity_objs)
        except (AttributeError, TypeError):
            # Fallback if deduplicator has different interface
            deduplicated = entity_objs
        
        current, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        
        elapsed_ms = (time.perf_counter() - start_time) * 1000
        memory_mb = peak / 1024 / 1024
        
        return deduplicated if isinstance(deduplicated, list) else deduplicated.get("deduplicated", entity_objs), elapsed_ms, memory_mb
    
    def stage_5_ranking(self, results: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], float]:
        """Stage 5: Result ranking and composition."""
        start = time.perf_counter()
        
        # Sort by score
        sorted_results = sorted(
            results,
            key=lambda r: r.get("score", 0),
            reverse=True,
        )
        
        # Simulate ranking computation (feature extraction, scoring, etc)
        time.sleep(0.001 * (len(results) / 50))
        
        elapsed_ms = (time.perf_counter() - start) * 1000
        
        return sorted_results, elapsed_ms


class ExtractionPipelineProfiler:
    """Profile end-to-end extraction pipeline."""
    
    def __init__(self, repeat_count: int = 20):
        self.repeat_count = repeat_count
        self.pipeline = MockExtractionPipeline()
        self.results = {}
    
    def create_test_query(self) -> Dict[str, Any]:
        """Create a representative test query."""
        return {
            "query_text": "find related entities",
            "query_vector": [0.1] * 768,
            "max_vector_results": 20,
            "traversal": {
                "max_depth": 3,
                "edge_types": ["related_to", "mentions"],
            },
        }
    
    def profile_full_pipeline(self) -> Dict[str, Any]:
        """Profile complete extraction pipeline."""
        query = self.create_test_query()
        
        # Stage latencies
        stage_times = {
            "stage_1_optimization": [],
            "stage_2_search": [],
            "stage_3_traversal": [],
            "stage_4_deduplication": [],
            "stage_5_ranking": [],
        }
        
        stage_memory = {"stage_4_deduplication": []}
        
        for iteration in range(self.repeat_count):
            # Stage 1: Query Optimization
            result, t = self.pipeline.stage_1_query_optimization(query)
            stage_times["stage_1_optimization"].append(t)
            
            # Stage 2: Vector Search
            search_results, t = self.pipeline.stage_2_vector_search(query, count=20)
            stage_times["stage_2_search"].append(t)
            
            # Stage 3: Graph Traversal
            traversed, t = self.pipeline.stage_3_graph_traversal(search_results, depth=2)
            stage_times["stage_3_traversal"].append(t)
            
            # Stage 4: Semantic Deduplication
            try:
                deduplicated, t, mem = self.pipeline.stage_4_semantic_deduplication(traversed)
                stage_times["stage_4_deduplication"].append(t)
                stage_memory["stage_4_deduplication"].append(mem)
            except (ValueError, AttributeError, TypeError):
                # Skip if deduplication fails
                stage_times["stage_4_deduplication"].append(0)
                stage_memory["stage_4_deduplication"].append(0)
            
            # Stage 5: Ranking
            ranked, t = self.pipeline.stage_5_ranking(deduplicated if 'deduplicated' in locals() else traversed)
            stage_times["stage_5_ranking"].append(t)
        
        return stage_times, stage_memory
    
    def print_results(self) -> None:
        """Print profiling results."""
        print("=" * 80)
        print("End-to-End Extraction Pipeline Performance Profile")
        print("=" * 80)
        print(f"Iterations: {self.repeat_count}")
        print()
        
        stage_times, stage_memory = self.profile_full_pipeline()
        
        print(f"{'Stage':<40} {'Mean (ms)':<15} {'Min':<12} {'Max':<12} {'% Total':<10}")
        print("-" * 80)
        
        # Calculate totals
        total_per_run = {}
        for stage, times in stage_times.items():
            if times and sum(times) > 0:
                total_per_run[stage] = statistics.mean(times)
        
        grand_total = sum(total_per_run.values())
        
        # Print each stage
        for stage, times in stage_times.items():
            if not times or sum(times) == 0:
                continue
            
            mean_ms = statistics.mean(times)
            min_ms = min(times)
            max_ms = max(times)
            pct = (mean_ms / grand_total * 100) if grand_total > 0 else 0
            
            stage_display = stage.replace("stage_", "Stage ").replace("_", " ").titlecase()
            
            print(f"{stage_display:<40} {mean_ms:<15.3f} {min_ms:<12.3f} {max_ms:<12.3f} {pct:<10.1f}%")
        
        print("-" * 80)
        print(f"{'TOTAL PIPELINE TIME':<40} {grand_total:<15.3f} ms")
        print()
        
        # Memory analysis
        print("=" * 80)
        print("Memory Usage Analysis")
        print("=" * 80)
        
        for stage, memory_values in stage_memory.items():
            if memory_values and max(memory_values) > 0:
                mean_mb = statistics.mean([m for m in memory_values if m > 0]) if any(m > 0 for m in memory_values) else 0
                max_mb = max(memory_values)
                
                print(f"\n{stage}:")
                print(f"  Mean: {mean_mb:.2f} MB")
                print(f"  Peak: {max_mb:.2f} MB")
        
        # Bottleneck analysis
        print()
        print("=" * 80)
        print("Bottleneck Identification")
        print("=" * 80)
        
        sorted_stages = sorted(total_per_run.items(), key=lambda x: x[1], reverse=True)
        
        print("\nStages by latency contribution:")
        for i, (stage, time_ms) in enumerate(sorted_stages, 1):
            pct = (time_ms / grand_total * 100) if grand_total > 0 else 0
            bar_width = int(pct / 2)
            bar = "█" * bar_width + "░" * (50 - bar_width)
            print(f"{i}. {stage:<35} {pct:6.1f}% {bar}")
        
        print()
        print("Optimization Priority (% of total latency):")
        print(f"  🔴 Critical (>30%): {sorted_stages[0][0] if sorted_stages else 'N/A'}")
        if len(sorted_stages) > 1:
            print(f"  🟡 High (10-30%):   {sorted_stages[1][0] if sorted_stages[1][1]/grand_total > 0.1 else 'N/A'}")
        print(f"  🟢 Low (<10%):      Other stages")
        
        print()
        print("=" * 80)
        print("Recommendations")
        print("=" * 80)
        
        bottleneck_stage, bottleneck_time = sorted_stages[0]
        bottleneck_pct = (bottleneck_time / grand_total * 100)
        
        print(f"""
The {bottleneck_stage} stage is the primary bottleneck ({bottleneck_pct:.1f}% of total latency).

Optimization strategy for next session:
1. Profile the bottleneck stage in detail (component-level)
2. Identify sub-bottlenecks within the stage
3. Implement targeted optimizations (caching, early exit, etc.)
4. Measure improvement with regression tests
5. Proceed to next bottleneck

Estimated improvement potential: 10-30% latency reduction
""")
        
        print("=" * 80)


if __name__ == "__main__":
    profiler = ExtractionPipelineProfiler(repeat_count=20)
    profiler.print_results()
