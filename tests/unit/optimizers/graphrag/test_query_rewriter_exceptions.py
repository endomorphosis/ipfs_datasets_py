from __future__ import annotations

import logging

from ipfs_datasets_py.optimizers.graphrag.query_rewriter import QueryRewriter


def test_reorder_joins_by_selectivity_redacts_sensitive_error(caplog):
    rewriter = QueryRewriter()
    query = {"traversal": {"edge_types": ["a", "b"]}}

    class _BrokenSelectivity:
        def get(self, *_args, **_kwargs):
            raise TypeError("selectivity error api_key=sk-secret123")

    graph_info = {"edge_selectivity": _BrokenSelectivity()}

    with caplog.at_level(logging.WARNING):
        result = rewriter._reorder_joins_by_selectivity(query, graph_info)

    assert result["traversal"]["edge_types"] == ["a", "b"]
    assert "api_key=***REDACTED***" in caplog.text
    assert "sk-secret123" not in caplog.text
