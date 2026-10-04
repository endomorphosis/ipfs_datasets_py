from __future__ import annotations

import pytest


class _DummyHierarchy:
    def __init__(self):
        self.category_connections = {}

    def get_related_categories(self, category, max_distance=1):
        return []

    def calculate_category_depth(self, category):
        return 0


def test_expand_query_handles_typed_vector_search_error_with_tracer() -> None:
    from ipfs_datasets_py.optimizers.graphrag.wikipedia_optimizer import WikipediaQueryExpander

    class _Tracer:
        def __init__(self):
            self.errors = []

        def log_error(self, message, trace_id):
            self.errors.append((message, trace_id))

        def log_query_expansion(self, trace_id, query_text, expansions):
            return None

    class _VectorStore:
        def search(self, *args, **kwargs):
            raise RuntimeError("search failed")

    tracer = _Tracer()
    expander = WikipediaQueryExpander(tracer=tracer)
    result = expander.expand_query(
        query_vector=[0.1, 0.2],
        query_text="test query",
        vector_store=_VectorStore(),
        category_hierarchy=_DummyHierarchy(),
        trace_id="t1",
    )

    assert result["has_expansions"] is False
    assert tracer.errors
    assert "Topic expansion error" in tracer.errors[0][0]
    assert tracer.errors[0][1] == "t1"


def test_expand_query_does_not_swallow_base_exception() -> None:
    from ipfs_datasets_py.optimizers.graphrag.wikipedia_optimizer import WikipediaQueryExpander

    class _VectorStore:
        def search(self, *args, **kwargs):
            raise KeyboardInterrupt()

    expander = WikipediaQueryExpander()

    with pytest.raises(KeyboardInterrupt):
        expander.expand_query(
            query_vector=[0.1, 0.2],
            query_text="test query",
            vector_store=_VectorStore(),
            category_hierarchy=_DummyHierarchy(),
            trace_id="t2",
        )
