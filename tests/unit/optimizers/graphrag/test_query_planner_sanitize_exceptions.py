from __future__ import annotations

import pytest


def test_sanitize_for_cache_handles_typed_str_conversion_error() -> None:
    from ipfs_datasets_py.optimizers.graphrag.query_planner import GraphRAGQueryOptimizer

    class BadString:
        def __str__(self) -> str:
            raise ValueError("bad str")

    optimizer = GraphRAGQueryOptimizer()
    value = optimizer._sanitize_for_cache(BadString())

    assert "Uncacheable object" in value


def test_sanitize_for_cache_does_not_swallow_base_exception() -> None:
    from ipfs_datasets_py.optimizers.graphrag.query_planner import GraphRAGQueryOptimizer

    class AbortSignal(BaseException):
        pass

    class BadString:
        def __str__(self) -> str:
            raise AbortSignal()

    optimizer = GraphRAGQueryOptimizer()

    with pytest.raises(AbortSignal):
        optimizer._sanitize_for_cache(BadString())
