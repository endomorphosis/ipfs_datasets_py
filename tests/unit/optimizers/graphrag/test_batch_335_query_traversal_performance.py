"""Batch 335: Query traversal performance benchmarks.

Validates basic performance characteristics for traversal query optimization
helpers to guard against major regressions.
"""

from __future__ import annotations

import time

from ipfs_datasets_py.optimizers.graphrag.traversal_optimizer import TraversalOptimizer


def _sample_query() -> dict:
    return {
        "query_text": "Find entities located in California and related to legal compliance",
        "traversal": {
            "edge_types": ["related_to", "located_in", "instance_of", "part_of"],
            "max_depth": 3,
        },
    }


def _sample_entity_scores(n: int = 200) -> dict[str, float]:
    return {f"e{i}": 0.4 + ((i % 6) * 0.1) for i in range(n)}


def test_optimize_wikipedia_traversal_performance() -> None:
    query = _sample_query()
    entity_scores = _sample_entity_scores(300)

    start = time.perf_counter()
    for _ in range(3000):
        result = TraversalOptimizer.optimize_wikipedia_traversal(query, entity_scores)
    elapsed_ms = (time.perf_counter() - start) * 1000

    assert isinstance(result, dict)
    assert "traversal" in result
    assert elapsed_ms < 5000, f"wikipedia traversal optimization too slow: {elapsed_ms:.0f}ms"


def test_optimize_ipld_traversal_performance() -> None:
    query = _sample_query()
    entity_scores = _sample_entity_scores(300)

    start = time.perf_counter()
    for _ in range(3000):
        result = TraversalOptimizer.optimize_ipld_traversal(query, entity_scores)
    elapsed_ms = (time.perf_counter() - start) * 1000

    assert isinstance(result, dict)
    assert "traversal" in result
    assert elapsed_ms < 5000, f"ipld traversal optimization too slow: {elapsed_ms:.0f}ms"
