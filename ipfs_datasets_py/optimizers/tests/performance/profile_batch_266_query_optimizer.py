"""Batch 266: Profile UnifiedGraphRAGQueryOptimizer under load.

Profiles optimize_query() and get_execution_plan() over a batch of synthetic
queries to identify hotspots before the planned query optimizer split.

Usage:
    python profile_batch_266_query_optimizer.py

Outputs:
    - profile_batch_266_query_optimizer.prof
    - profile_batch_266_query_optimizer.txt
"""

import cProfile
import pathlib
import pstats
import random
import sys
import time
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(pathlib.Path(__file__).parents[4]))

from ipfs_datasets_py.optimizers.graphrag.query_unified_optimizer import (
    UnifiedGraphRAGQueryOptimizer,
)


def build_queries(
    count: int,
    *,
    vector_size: int = 256,
    max_depth: int = 3,
) -> List[Dict[str, Any]]:
    """Build a deterministic set of synthetic GraphRAG queries.

    Args:
        count: Number of queries to generate.
        vector_size: Length of query_vector arrays.
        max_depth: Maximum traversal depth to include.

    Returns:
        List of query dicts.
    """
    if count < 0:
        raise ValueError("count must be >= 0")
    if vector_size <= 0:
        raise ValueError("vector_size must be > 0")
    if max_depth <= 0:
        raise ValueError("max_depth must be > 0")

    random.seed(42)
    queries: List[Dict[str, Any]] = []
    edge_pool = ["instance_of", "part_of", "created_by", "works_for", "located_in"]

    for idx in range(count):
        edge_types = edge_pool[: (idx % len(edge_pool)) + 1]
        vector = [random.random() for _ in range(vector_size)]
        queries.append(
            {
                "query_vector": vector,
                "max_vector_results": 5 + (idx % 5),
                "min_similarity": 0.4 + (idx % 3) * 0.1,
                "entity_ids": [f"entity_{i}" for i in range(idx % 6)],
                "traversal": {
                    "edge_types": edge_types,
                    "max_depth": min(max_depth, 2 + (idx % 3)),
                },
                "query_text": f"Find relationships for entity batch {idx}",
            }
        )

    return queries


def profile_query_optimizer(
    query_count: int = 120,
    vector_size: int = 256,
    warmup_count: int = 10,
    output_dir: Optional[pathlib.Path] = None,
) -> Dict[str, Any]:
    """Profile UnifiedGraphRAGQueryOptimizer for a batch of queries.

    Args:
        query_count: Number of profiled queries.
        vector_size: Length of the query vectors.
        warmup_count: Number of warmup queries to run before profiling.
        output_dir: Directory for .prof/.txt outputs.

    Returns:
        Dict with profiling metrics.
    """
    if query_count <= 0:
        raise ValueError("query_count must be > 0")
    if vector_size <= 0:
        raise ValueError("vector_size must be > 0")
    if warmup_count < 0:
        raise ValueError("warmup_count must be >= 0")

    optimizer = UnifiedGraphRAGQueryOptimizer()

    warmup_queries = build_queries(warmup_count, vector_size=64, max_depth=2)
    for query in warmup_queries:
        optimizer.optimize_query(query)

    queries = build_queries(query_count, vector_size=vector_size, max_depth=3)

    profiler = cProfile.Profile()
    start = time.perf_counter()
    profiler.enable()

    plans = []
    for query in queries:
        plan = optimizer.optimize_query(query)
        plans.append(plan)
        _ = optimizer.get_execution_plan(query)

    profiler.disable()
    elapsed_ms = (time.perf_counter() - start) * 1000

    metrics = {
        "query_count": query_count,
        "elapsed_ms": elapsed_ms,
        "avg_ms": elapsed_ms / max(1, query_count),
        "plan_count": len(plans),
    }

    if output_dir is not None:
        output_dir.mkdir(parents=True, exist_ok=True)
        prof_file = output_dir / "profile_batch_266_query_optimizer.prof"
        txt_file = output_dir / "profile_batch_266_query_optimizer.txt"

        profiler.dump_stats(str(prof_file))

        with open(txt_file, "w", encoding="utf-8") as handle:
            handle.write("=" * 72 + "\n")
            handle.write("BATCH 266: Query Optimizer Profile\n")
            handle.write("=" * 72 + "\n\n")
            handle.write(f"Queries: {metrics['query_count']}\n")
            handle.write(f"Elapsed ms: {metrics['elapsed_ms']:.2f}\n")
            handle.write(f"Avg ms/query: {metrics['avg_ms']:.2f}\n")
            handle.write(f"Plans generated: {metrics['plan_count']}\n\n")
            stats = pstats.Stats(profiler, stream=handle).sort_stats("cumulative")
            stats.print_stats(40)

    return metrics


def main() -> None:
    """Run the profiling script with default parameters."""
    output_dir = pathlib.Path(__file__).parent
    metrics = profile_query_optimizer(output_dir=output_dir)

    print("\nBatch 266 profiling complete")
    print(f"Queries: {metrics['query_count']}")
    print(f"Elapsed ms: {metrics['elapsed_ms']:.2f}")
    print(f"Avg ms/query: {metrics['avg_ms']:.2f}")
    print(f"Plans generated: {metrics['plan_count']}")
    print(f"Output dir: {output_dir}")


if __name__ == "__main__":
    main()
