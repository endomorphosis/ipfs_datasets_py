from __future__ import annotations

import pytest


def _make_optimizer(cache_ttl: float = 60.0):
    from ipfs_datasets_py.optimizers.graphrag.query_planner import (
        GraphRAGQueryOptimizer,
    )

    return GraphRAGQueryOptimizer(cache_ttl=cache_ttl)


def _make_key(optimizer) -> str:
    return optimizer.get_query_key(
        query_vector=[0.1, 0.2, 0.3],
        max_vector_results=3,
        max_traversal_depth=2,
        edge_types=["rel"],
        min_similarity=0.4,
    )


def test_clear_cache_removes_entries() -> None:
    optimizer = _make_optimizer()
    key = _make_key(optimizer)

    optimizer.add_to_cache(key, {"ok": True})
    assert optimizer.is_in_cache(key) is True

    optimizer.clear_cache()

    assert optimizer.query_cache == {}
    assert optimizer.is_in_cache(key) is False


def test_cache_entry_expires_after_ttl(monkeypatch) -> None:
    optimizer = _make_optimizer(cache_ttl=10.0)
    key = _make_key(optimizer)

    monkeypatch.setattr(
        "ipfs_datasets_py.optimizers.graphrag.query_planner.time.time",
        lambda: 1000.0,
    )

    optimizer.add_to_cache(key, {"value": [1, 2, 3]})
    assert optimizer.is_in_cache(key) is True

    monkeypatch.setattr(
        "ipfs_datasets_py.optimizers.graphrag.query_planner.time.time",
        lambda: 1011.0,
    )

    assert optimizer.is_in_cache(key) is False
    assert key not in optimizer.query_cache
