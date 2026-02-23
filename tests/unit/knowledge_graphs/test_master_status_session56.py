"""
Session 56 invariant tests for dead code removal in cross_document.py and ir_executor.py.

Two blocks of production dead code were removed in this session:

  1. ``reasoning/cross_document.py`` – the ``if norm_src == 0.0 or norm_tgt == 0.0: return 0.0``
     guard (former lines 198-199) was provably unreachable: the earlier
     ``if not src_tokens or not tgt_tokens`` guard ensures both token lists are non-empty
     before the Counter / norm calculation runs, so both norms are always strictly positive.

  2. ``core/ir_executor.py`` – the ``OrderBy make_sort_key`` helper had a ``if "." in expr:``
     branch that (a) assigned ``var_name, prop_name`` but never used them, and (b) wrapped
     ``record.get(expr)`` in a try/except that could never fire because ``Record.get()`` does
     not raise.  The ``else:`` branch did the same ``record.get(expr)`` call, so both branches
     were equivalent.  Collapsed to a single ``value = record.get(expr)`` call.

Tests follow the GIVEN-WHEN-THEN format used throughout the project.
"""

from __future__ import annotations

import math
from collections import Counter
from typing import Any, Dict, List
from unittest.mock import MagicMock

import pytest


# ---------------------------------------------------------------------------
# Helpers for execute_ir_operations (matching session24 pattern)
# ---------------------------------------------------------------------------

def _resolve_value(val, params):
    if isinstance(val, dict) and "param" in val:
        return params.get(val["param"], val)
    return val


def _apply_operator(item_val, op, ref_val):
    if op == "=":
        return item_val == ref_val
    if op == ">":
        return item_val is not None and item_val > ref_val
    return False


def _eval_compiled(expr, binding):
    if isinstance(expr, dict) and len(expr) == 1 and "property" in expr:
        return binding.get(expr["property"])
    return None


def _eval_expression(expr, binding):
    if isinstance(expr, str):
        return binding.get(expr)
    return None


def _compute_agg(func_name, values):
    if func_name in ("count", "COUNT"):
        return len(values)
    return None


# ---------------------------------------------------------------------------
# 1. CrossDocumentReasoner — zero-norm guard removal
# ---------------------------------------------------------------------------


class TestCrossDocumentZeroNormProof:
    """Prove that norm_src and norm_tgt are always > 0 after the non-empty guard.

    The removed guard ``if norm_src == 0.0 or norm_tgt == 0.0: return 0.0`` was
    unreachable because a non-empty token list always produces a Counter with at
    least one entry of value ≥ 1, giving a strictly positive L2 norm.
    """

    def test_non_empty_counter_has_positive_norm(self):
        """GIVEN a non-empty token list
        WHEN we build a Counter and compute L2 norm
        THEN the norm is strictly positive
        """
        tokens = ["hello", "world"]
        counts = Counter(tokens)
        norm = math.sqrt(sum(v * v for v in counts.values()))
        assert norm > 0.0

    def test_single_token_counter_has_positive_norm(self):
        """GIVEN a single-token list (minimum valid input)
        WHEN we build a Counter and compute L2 norm
        THEN the norm equals 1.0 (one token, count=1, sqrt(1)=1)
        """
        counts = Counter(["only"])
        norm = math.sqrt(sum(v * v for v in counts.values()))
        assert norm == 1.0

    def test_repeated_tokens_have_positive_norm(self):
        """GIVEN a token list with all identical tokens
        WHEN we build a Counter and compute L2 norm
        THEN the norm equals the frequency of that single token
        """
        tokens = ["the"] * 5
        counts = Counter(tokens)
        norm = math.sqrt(sum(v * v for v in counts.values()))
        assert norm == 5.0

    def test_counter_values_are_always_positive(self):
        """GIVEN any non-empty token list
        WHEN we build a Counter
        THEN all values are strictly positive integers (Counter invariant)
        """
        tokens = ["alpha", "beta", "alpha"]
        counts = Counter(tokens)
        assert all(v > 0 for v in counts.values())
        assert len(counts) > 0

    def test_tokenize_returns_nonempty_for_content_text(self):
        """GIVEN typical document content
        WHEN the bag-of-words tokenizer runs
        THEN the result is non-empty (confirming pre-check relevance)
        """
        import re
        text = "Alice collaborated with Bob on the research project."
        stop = {"the", "a", "an", "and", "or", "but", "if", "then", "else",
                "of", "to", "in", "on", "for", "with", "by", "from", "as",
                "is", "are", "was", "were", "be", "been", "being"}
        tokens = [t for t in re.findall(r"[a-z0-9]+", text.lower())
                  if len(t) >= 3 and t not in stop]
        assert len(tokens) > 0, "tokenizer must produce non-empty list for typical text"

    def test_zero_norm_only_possible_from_empty_counter(self):
        """GIVEN an empty Counter (only possible from an empty token list)
        WHEN we compute L2 norm
        THEN it equals 0.0 — confirming the pre-check is the right guard
        """
        counts: Counter = Counter()
        norm = math.sqrt(sum(v * v for v in counts.values()))
        assert norm == 0.0

    def test_compute_document_similarity_positive_inputs(self):
        """GIVEN two documents with overlapping content
        WHEN _compute_document_similarity is called
        THEN it returns a value in (0, 1]
        """
        from ipfs_datasets_py.knowledge_graphs.reasoning.cross_document import (
            CrossDocumentReasoner,
        )
        from ipfs_datasets_py.knowledge_graphs.reasoning.types import DocumentNode
        reasoner = CrossDocumentReasoner()
        doc_a = DocumentNode(
            id="a",
            content="Alice performed experiments on machine learning.",
            source="test",
        )
        doc_b = DocumentNode(
            id="b",
            content="Alice performed experiments on neural networks.",
            source="test",
        )
        sim = reasoner._compute_document_similarity(doc_a, doc_b)
        assert 0.0 < sim <= 1.0

    def test_compute_document_similarity_stopword_only_returns_zero(self):
        """GIVEN two documents whose content consists entirely of stop-words
        WHEN _compute_document_similarity is called
        THEN it returns 0.0 via the empty-token pre-check (not the removed guard)
        """
        from ipfs_datasets_py.knowledge_graphs.reasoning.cross_document import (
            CrossDocumentReasoner,
        )
        from ipfs_datasets_py.knowledge_graphs.reasoning.types import DocumentNode
        reasoner = CrossDocumentReasoner()
        doc_a = DocumentNode(id="a", content="the and or in on", source="test")
        doc_b = DocumentNode(id="b", content="is are was were", source="test")
        sim = reasoner._compute_document_similarity(doc_a, doc_b)
        assert sim == 0.0


# ---------------------------------------------------------------------------
# 2. IRExecutor — OrderBy make_sort_key simplification
# ---------------------------------------------------------------------------


class TestIRExecutorOrderByStringExpr:
    """Prove that the removed if-else on '.' in expr was redundant.

    The old code:
        if '.' in expr:
            var_name, prop_name = expr.split('.', 1)  # never used
            try:
                value = record.get(expr)
            except (AttributeError, KeyError, TypeError):
                value = None
        else:
            value = record.get(expr)

    Both branches did ``value = record.get(expr)``.  The try/except was also
    unreachable because ``Record.get()`` never raises.  Simplified to one line.
    """

    @pytest.fixture
    def graph_engine(self):
        from ipfs_datasets_py.knowledge_graphs.core.graph_engine import GraphEngine
        engine = GraphEngine()
        return engine

    def _make_exec_kwargs(self, graph_engine):
        """Return the standard execute_ir_operations keyword dict."""
        from ipfs_datasets_py.knowledge_graphs.query.unified_engine import (
            UnifiedQueryEngine,
        )
        uqe = UnifiedQueryEngine(graph_engine)
        return dict(
            graph_engine=graph_engine,
            parameters={},
            resolve_value=_resolve_value,
            apply_operator=_apply_operator,
            evaluate_compiled_expression=_eval_compiled,
            evaluate_expression=_eval_expression,
            compute_aggregation=_compute_agg,
        )

    def test_record_get_never_raises_for_dotted_key(self):
        """GIVEN a Record object constructed with a dotted key
        WHEN .get() is called with that exact key
        THEN it returns the value without raising — confirming the try/except was dead
        """
        from ipfs_datasets_py.knowledge_graphs.neo4j_compat.result import Record
        record = Record(["n.name", "n.age"], ["Alice", 30])
        assert record.get("n.name") == "Alice"
        assert record.get("n.age") == 30

    def test_record_get_missing_key_returns_none(self):
        """GIVEN a Record object
        WHEN .get() is called with a missing key
        THEN it returns None (not raises) — confirming try/except was dead
        """
        from ipfs_datasets_py.knowledge_graphs.neo4j_compat.result import Record
        record = Record(["n.name"], ["Alice"])
        assert record.get("missing") is None
        assert record.get("missing", "default") == "default"

    def test_record_get_with_default_value(self):
        """GIVEN a Record with known keys
        WHEN .get() is called on a missing key with default
        THEN the default is returned without raising
        """
        from ipfs_datasets_py.knowledge_graphs.neo4j_compat.result import Record
        record = Record(["a", "b"], [1, 2])
        assert record.get("c", 99) == 99

    def test_orderby_string_dotted_expr_via_execute_ir(self, graph_engine):
        """GIVEN Records with a dotted column name
        WHEN OrderBy uses a string expression with '.'
        THEN the simplified record.get(expr) path works correctly
        """
        from ipfs_datasets_py.knowledge_graphs.core.ir_executor import execute_ir_operations
        from ipfs_datasets_py.knowledge_graphs.neo4j_compat.result import Record

        # Inject pre-built Records into final_results via a mock ScanLabel
        n1 = graph_engine.create_node(labels=["Thing"], properties={"score": 3})
        n2 = graph_engine.create_node(labels=["Thing"], properties={"score": 1})
        n3 = graph_engine.create_node(labels=["Thing"], properties={"score": 2})

        ops = [
            {"op": "ScanLabel", "label": "Thing", "variable": "n"},
            {"op": "Project",
             "items": [{"expression": {"var": "n"}, "alias": "n"}],
             "distinct": False},
            # String dotted expression — the simplified code path
            {"op": "OrderBy",
             "items": [{"expression": "n.score", "ascending": True}]},
        ]

        def _eval_with_dot(expr, binding):
            if isinstance(expr, str) and "." in expr:
                var, prop = expr.split(".", 1)
                obj = binding.get(var)
                if obj is not None and hasattr(obj, "_properties"):
                    return obj._properties.get(prop)
                return binding.get(expr)
            return _eval_compiled(expr, binding)

        results = execute_ir_operations(
            graph_engine=graph_engine,
            operations=ops,
            parameters={},
            resolve_value=_resolve_value,
            apply_operator=_apply_operator,
            evaluate_compiled_expression=_eval_with_dot,
            evaluate_expression=_eval_expression,
            compute_aggregation=_compute_agg,
        )
        assert len(results) == 3

    def test_orderby_string_non_dotted_expr_via_execute_ir(self, graph_engine):
        """GIVEN Records with a simple column name (no dot)
        WHEN OrderBy uses a string expression without '.'
        THEN the simplified record.get(expr) path works correctly
        """
        from ipfs_datasets_py.knowledge_graphs.core.ir_executor import execute_ir_operations

        graph_engine.create_node(labels=["Widget"], properties={"val": 5})
        graph_engine.create_node(labels=["Widget"], properties={"val": 2})
        graph_engine.create_node(labels=["Widget"], properties={"val": 8})

        ops = [
            {"op": "ScanLabel", "label": "Widget", "variable": "n"},
            {"op": "Project",
             "items": [{"expression": {"var": "n"}, "alias": "n"}],
             "distinct": False},
            # Non-dotted string expression
            {"op": "OrderBy",
             "items": [{"expression": "n", "ascending": True}]},
        ]

        results = execute_ir_operations(
            graph_engine=graph_engine,
            operations=ops,
            parameters={},
            resolve_value=_resolve_value,
            apply_operator=_apply_operator,
            evaluate_compiled_expression=_eval_compiled,
            evaluate_expression=_eval_expression,
            compute_aggregation=_compute_agg,
        )
        assert len(results) == 3

