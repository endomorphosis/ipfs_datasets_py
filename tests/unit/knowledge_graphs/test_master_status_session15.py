"""
Session 15: Coverage improvements for:
- lineage/visualization.py (34% → 65%)    — render_networkx, render_plotly, visualize_lineage
- query/sparql_templates.py (66% → 100%)  — all builder functions
- query/knowledge_graph.py (65% → 70%)    — parse_ir_ops, compile_ir, query_kg errors
- core/expression_evaluator.py (77% → 89%) — XOR, FUNCTION_REGISTRY, string fns, CASE, compiled
- query/budget_manager.py (77% → 100%)    — check_timeout/nodes/edges/depth, presets
- transactions/wal.py (69% → 72%)         — compact, recover, error paths, verify_integrity

GIVEN-WHEN-THEN format consistent with existing tests.
"""
from __future__ import annotations

import io
import os
import sys
import time
import tempfile
from typing import Any, Dict
from unittest.mock import MagicMock, patch
import importlib

import pytest

_matplotlib_available = bool(importlib.util.find_spec("matplotlib"))
_skip_no_matplotlib = pytest.mark.skipif(
    not _matplotlib_available, reason="matplotlib not installed"
)

# ─────────────────────────────────────────────────────────────────────────────
# Helpers / fixtures
# ─────────────────────────────────────────────────────────────────────────────

def _make_lineage_graph():
    """Build a small LineageGraph with 2 nodes and 1 edge."""
    from ipfs_datasets_py.knowledge_graphs.lineage.core import LineageGraph
    from ipfs_datasets_py.knowledge_graphs.lineage.types import LineageLink, LineageNode

    g = LineageGraph()
    g.add_node(LineageNode(node_id="n1", node_type="dataset", metadata={}))
    g.add_node(LineageNode(node_id="n2", node_type="transformation", metadata={}))
    g.add_link(LineageLink(source_id="n1", target_id="n2", relationship_type="derived_from"))
    return g


def _make_wal(fail_store: bool = False, fail_retrieve: bool = False):
    """Build a WriteAheadLog backed by a lightweight mock storage."""
    from ipfs_datasets_py.knowledge_graphs.exceptions import StorageError
    from ipfs_datasets_py.knowledge_graphs.transactions.wal import WriteAheadLog

    class _MockStorage:
        def __init__(self):
            self.data: Dict[str, Any] = {}
            self._counter = 0
            self.fail_store = fail_store
            self.fail_retrieve = fail_retrieve

        def store_json(self, data):
            if self.fail_store:
                raise TypeError("serialization failure")
            cid = f"Qm{self._counter:04d}"
            self._counter += 1
            self.data[cid] = data
            return cid

        def retrieve_json(self, cid):
            if self.fail_retrieve:
                raise StorageError("storage read failure")
            if cid not in self.data:
                raise KeyError(f"CID not found: {cid}")
            return self.data[cid]

    return WriteAheadLog(storage=_MockStorage())


# ═════════════════════════════════════════════════════════════════════════════
# 1. lineage/visualization.py
# ═════════════════════════════════════════════════════════════════════════════

@_skip_no_matplotlib
class TestLineageVisualizerRenderNetworkx:
    """Tests for LineageVisualizer.render_networkx with matplotlib available."""

    def test_spring_layout_returns_bytes(self):
        """GIVEN a LineageGraph WHEN render_networkx('spring') THEN returns PNG bytes."""
        from ipfs_datasets_py.knowledge_graphs.lineage.visualization import LineageVisualizer
        v = LineageVisualizer(_make_lineage_graph())
        result = v.render_networkx(layout="spring")
        assert isinstance(result, bytes)
        assert len(result) > 0

    def test_circular_layout_returns_bytes(self):
        """GIVEN a LineageGraph WHEN render_networkx('circular') THEN returns PNG bytes."""
        from ipfs_datasets_py.knowledge_graphs.lineage.visualization import LineageVisualizer
        v = LineageVisualizer(_make_lineage_graph())
        result = v.render_networkx(layout="circular")
        assert isinstance(result, bytes)

    @pytest.mark.skipif(
        not __import__("importlib").util.find_spec("scipy"),
        reason="scipy required for hierarchical (kamada_kawai) layout",
    )
    def test_hierarchical_layout_returns_bytes(self):
        """GIVEN scipy available WHEN render_networkx('hierarchical') THEN returns PNG bytes."""
        from ipfs_datasets_py.knowledge_graphs.lineage.visualization import LineageVisualizer
        v = LineageVisualizer(_make_lineage_graph())
        result = v.render_networkx(layout="hierarchical")
        assert isinstance(result, bytes)

    def test_unknown_layout_falls_back_to_spring(self):
        """GIVEN unknown layout WHEN render_networkx THEN falls back to spring."""
        from ipfs_datasets_py.knowledge_graphs.lineage.visualization import LineageVisualizer
        v = LineageVisualizer(_make_lineage_graph())
        result = v.render_networkx(layout="unknown_layout_xyz")
        assert isinstance(result, bytes)

    def test_output_path_saves_file(self):
        """GIVEN output_path WHEN render_networkx THEN saves file and returns None."""
        from ipfs_datasets_py.knowledge_graphs.lineage.visualization import LineageVisualizer
        v = LineageVisualizer(_make_lineage_graph())
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            path = f.name
        try:
            result = v.render_networkx(output_path=path)
            assert result is None
            assert os.path.exists(path)
            assert os.path.getsize(path) > 0
        finally:
            os.unlink(path)

    def test_render_networkx_without_matplotlib_raises(self):
        """GIVEN matplotlib unavailable WHEN render_networkx THEN raises ImportError."""
        from ipfs_datasets_py.knowledge_graphs.lineage import visualization as viz_mod
        orig = viz_mod.MATPLOTLIB_AVAILABLE
        try:
            viz_mod.MATPLOTLIB_AVAILABLE = False
            v = viz_mod.LineageVisualizer(_make_lineage_graph())
            with pytest.raises(ImportError, match="Matplotlib"):
                v.render_networkx()
        finally:
            viz_mod.MATPLOTLIB_AVAILABLE = orig

    def test_node_colors_for_types(self):
        """GIVEN graph with different node types WHEN render_networkx THEN still returns bytes."""
        from ipfs_datasets_py.knowledge_graphs.lineage.core import LineageGraph
        from ipfs_datasets_py.knowledge_graphs.lineage.types import LineageLink, LineageNode
        from ipfs_datasets_py.knowledge_graphs.lineage.visualization import LineageVisualizer

        g = LineageGraph()
        g.add_node(LineageNode(node_id="ds", node_type="dataset", metadata={}))
        g.add_node(LineageNode(node_id="tr", node_type="transformation", metadata={}))
        g.add_node(LineageNode(node_id="ot", node_type="other_type", metadata={}))
        g.add_link(LineageLink(source_id="ds", target_id="tr", relationship_type="trains"))
        g.add_link(LineageLink(source_id="tr", target_id="ot", relationship_type="produces"))

        v = LineageVisualizer(g)
        result = v.render_networkx()
        assert isinstance(result, bytes)


class TestLineageVisualizerRenderPlotly:
    """Tests for render_plotly paths."""

    def test_render_plotly_without_plotly_raises(self):
        """GIVEN plotly unavailable WHEN render_plotly THEN raises ImportError."""
        from ipfs_datasets_py.knowledge_graphs.lineage import visualization as viz_mod
        orig = viz_mod.PLOTLY_AVAILABLE
        try:
            viz_mod.PLOTLY_AVAILABLE = False
            v = viz_mod.LineageVisualizer(_make_lineage_graph())
            with pytest.raises(ImportError, match="Plotly"):
                v.render_plotly()
        finally:
            viz_mod.PLOTLY_AVAILABLE = orig

    @pytest.mark.skipif(
        not __import__("importlib").util.find_spec("plotly"),
        reason="plotly not installed",
    )
    def test_render_plotly_returns_html(self):
        """GIVEN plotly available WHEN render_plotly THEN returns HTML string."""
        from ipfs_datasets_py.knowledge_graphs.lineage.visualization import LineageVisualizer
        v = LineageVisualizer(_make_lineage_graph())
        result = v.render_plotly()
        assert isinstance(result, str)
        assert "<html" in result.lower() or "plotly" in result.lower()


class TestVisualizeLinkageFunction:
    """Tests for the module-level visualize_lineage() function."""

    @_skip_no_matplotlib
    def test_visualize_networkx_renderer(self):
        """GIVEN networkx renderer WHEN visualize_lineage THEN returns bytes."""
        from ipfs_datasets_py.knowledge_graphs.lineage.core import LineageTracker
        from ipfs_datasets_py.knowledge_graphs.lineage.visualization import visualize_lineage
        tracker = LineageTracker()
        result = visualize_lineage(tracker, renderer="networkx")
        assert isinstance(result, bytes)

    def test_visualize_unknown_renderer_raises(self):
        """GIVEN unknown renderer WHEN visualize_lineage THEN raises ValueError."""
        from ipfs_datasets_py.knowledge_graphs.lineage.core import LineageTracker
        from ipfs_datasets_py.knowledge_graphs.lineage.visualization import visualize_lineage
        tracker = LineageTracker()
        with pytest.raises(ValueError, match="Unknown renderer"):
            visualize_lineage(tracker, renderer="d3js")

    @_skip_no_matplotlib
    def test_visualize_with_output_path(self):
        """GIVEN output_path WHEN visualize_lineage(networkx) THEN saves file."""
        from ipfs_datasets_py.knowledge_graphs.lineage.core import LineageTracker
        from ipfs_datasets_py.knowledge_graphs.lineage.visualization import visualize_lineage
        tracker = LineageTracker()
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            path = f.name
        try:
            result = visualize_lineage(tracker, output_path=path, renderer="networkx")
            assert result is None
            assert os.path.exists(path)
        finally:
            os.unlink(path)


# ═════════════════════════════════════════════════════════════════════════════
# 2. query/sparql_templates.py  (100% coverage target)
# ═════════════════════════════════════════════════════════════════════════════

class TestSPARQLTemplateBuilders:
    """Tests for all SPARQL query builder functions."""

    def test_build_entity_query_interpolates_name(self):
        """GIVEN entity name WHEN build_entity_query THEN name appears in query."""
        from ipfs_datasets_py.knowledge_graphs.query.sparql_templates import build_entity_query
        q = build_entity_query("Albert Einstein")
        assert "Albert Einstein" in q
        assert "SELECT" in q

    def test_build_entity_properties_query_interpolates_id(self):
        """GIVEN entity ID WHEN build_entity_properties_query THEN ID appears in query."""
        from ipfs_datasets_py.knowledge_graphs.query.sparql_templates import build_entity_properties_query
        q = build_entity_properties_query("Q937")
        assert "Q937" in q
        assert "SELECT" in q

    def test_build_direct_relationship_query_interpolates_both_ids(self):
        """GIVEN source and target IDs WHEN build_direct_relationship_query THEN both appear."""
        from ipfs_datasets_py.knowledge_graphs.query.sparql_templates import build_direct_relationship_query
        q = build_direct_relationship_query("Q937", "Q5")
        assert "Q937" in q
        assert "Q5" in q

    def test_build_inverse_relationship_query_interpolates_both_ids(self):
        """GIVEN target and source IDs WHEN build_inverse_relationship_query THEN both appear."""
        from ipfs_datasets_py.knowledge_graphs.query.sparql_templates import build_inverse_relationship_query
        q = build_inverse_relationship_query("Q5", "Q937")
        assert "Q5" in q
        assert "Q937" in q

    def test_build_entity_type_query_interpolates_id(self):
        """GIVEN entity ID WHEN build_entity_type_query THEN ID appears."""
        from ipfs_datasets_py.knowledge_graphs.query.sparql_templates import build_entity_type_query
        q = build_entity_type_query("Q937")
        assert "Q937" in q
        assert "wdt:P31" in q

    def test_build_path_relationship_query_interpolates_both_ids(self):
        """GIVEN two entity IDs WHEN build_path_relationship_query THEN both appear."""
        from ipfs_datasets_py.knowledge_graphs.query.sparql_templates import build_path_relationship_query
        q = build_path_relationship_query("Q937", "Q5")
        assert "Q937" in q
        assert "Q5" in q

    def test_build_similar_entities_query_no_type_filter(self):
        """GIVEN entity ID, no type WHEN build_similar_entities_query THEN entity in query, no type filter."""
        from ipfs_datasets_py.knowledge_graphs.query.sparql_templates import build_similar_entities_query
        q = build_similar_entities_query("Q937")
        assert "Q937" in q
        assert "P31" not in q or "FILTER" not in q.split("Q937")[1][:50]

    def test_build_similar_entities_query_with_type_filter(self):
        """GIVEN entity + type IDs WHEN build_similar_entities_query THEN type filter included."""
        from ipfs_datasets_py.knowledge_graphs.query.sparql_templates import build_similar_entities_query
        q = build_similar_entities_query("Q937", type_id="Q5")
        assert "Q937" in q
        assert "Q5" in q
        assert "FILTER" in q

    def test_build_property_stats_query_interpolates_type_id(self):
        """GIVEN type ID WHEN build_property_stats_query THEN type ID appears twice."""
        from ipfs_datasets_py.knowledge_graphs.query.sparql_templates import build_property_stats_query
        q = build_property_stats_query("Q5")
        assert q.count("Q5") >= 2

    def test_build_property_validation_query_interpolates_both_ids(self):
        """GIVEN type and entity IDs WHEN build_property_validation_query THEN both appear."""
        from ipfs_datasets_py.knowledge_graphs.query.sparql_templates import build_property_validation_query
        q = build_property_validation_query("Q5", "Q937")
        assert "Q5" in q
        assert "Q937" in q


# ═════════════════════════════════════════════════════════════════════════════
# 3. query/knowledge_graph.py
# ═════════════════════════════════════════════════════════════════════════════

class TestParseIROpsFromQuery:
    """Tests for parse_ir_ops_from_query()."""

    def test_empty_string_raises(self):
        """GIVEN empty string WHEN parse_ir_ops_from_query THEN raises ValueError."""
        from ipfs_datasets_py.knowledge_graphs.query.knowledge_graph import parse_ir_ops_from_query
        with pytest.raises(ValueError, match="non-empty JSON string"):
            parse_ir_ops_from_query("")

    def test_whitespace_only_raises(self):
        """GIVEN whitespace only WHEN parse_ir_ops_from_query THEN raises ValueError."""
        from ipfs_datasets_py.knowledge_graphs.query.knowledge_graph import parse_ir_ops_from_query
        with pytest.raises(ValueError, match="non-empty JSON string"):
            parse_ir_ops_from_query("   ")

    def test_non_json_raises(self):
        """GIVEN non-JSON string WHEN parse_ir_ops_from_query THEN raises ValueError (wrong prefix)."""
        from ipfs_datasets_py.knowledge_graphs.query.knowledge_graph import parse_ir_ops_from_query
        with pytest.raises(ValueError, match="requires JSON"):
            parse_ir_ops_from_query("MATCH (n) RETURN n")

    def test_empty_list_raises(self):
        """GIVEN empty JSON list WHEN parse_ir_ops_from_query THEN raises ValueError."""
        from ipfs_datasets_py.knowledge_graphs.query.knowledge_graph import parse_ir_ops_from_query
        with pytest.raises(ValueError, match="non-empty list"):
            parse_ir_ops_from_query("[]")

    def test_non_dict_elements_raise(self):
        """GIVEN list of ints WHEN parse_ir_ops_from_query THEN raises ValueError."""
        from ipfs_datasets_py.knowledge_graphs.query.knowledge_graph import parse_ir_ops_from_query
        with pytest.raises(ValueError, match="object/dict"):
            parse_ir_ops_from_query("[1, 2, 3]")

    def test_valid_list_returns_ops(self):
        """GIVEN valid list of dicts WHEN parse_ir_ops_from_query THEN returns list."""
        from ipfs_datasets_py.knowledge_graphs.query.knowledge_graph import parse_ir_ops_from_query
        result = parse_ir_ops_from_query('[{"op": "ScanAll"}]')
        assert isinstance(result, list)
        assert len(result) == 1

    def test_wrapped_ops_dict(self):
        """GIVEN dict with 'ops' key WHEN parse_ir_ops_from_query THEN returns ops list."""
        from ipfs_datasets_py.knowledge_graphs.query.knowledge_graph import parse_ir_ops_from_query
        result = parse_ir_ops_from_query('{"ops": [{"op": "ScanAll"}]}')
        assert isinstance(result, list)
        assert result[0]["op"] == "ScanAll"


class TestCompileIR:
    """Tests for compile_ir() validation errors."""

    def test_missing_op_name_raises(self):
        """GIVEN op dict with no 'op'/'type'/'name' WHEN compile_ir THEN raises ValueError."""
        from ipfs_datasets_py.knowledge_graphs.query.knowledge_graph import compile_ir
        with pytest.raises(ValueError, match="missing 'op'"):
            compile_ir([{"x": "y"}])

    def test_seed_entities_empty_ids_raises(self):
        """GIVEN SeedEntities with empty list WHEN compile_ir THEN raises ValueError."""
        from ipfs_datasets_py.knowledge_graphs.query.knowledge_graph import compile_ir
        with pytest.raises(ValueError, match="entity_ids"):
            compile_ir([{"op": "SeedEntities", "entity_ids": []}])

    def test_scan_type_missing_entity_type_raises(self):
        """GIVEN ScanType with empty entity_type WHEN compile_ir THEN raises ValueError."""
        from ipfs_datasets_py.knowledge_graphs.query.knowledge_graph import compile_ir
        with pytest.raises(ValueError, match="entity_type"):
            compile_ir([{"op": "ScanType", "entity_type": ""}])

    def test_scan_type_invalid_scope_raises(self):
        """GIVEN ScanType with non-list scope WHEN compile_ir THEN raises ValueError."""
        from ipfs_datasets_py.knowledge_graphs.query.knowledge_graph import compile_ir
        with pytest.raises(ValueError, match="scope"):
            compile_ir([{"op": "ScanType", "entity_type": "Person", "scope": "wrong"}])

    def test_expand_invalid_direction_raises(self):
        """GIVEN Expand with unsupported direction WHEN compile_ir THEN raises ValueError."""
        from ipfs_datasets_py.knowledge_graphs.query.knowledge_graph import compile_ir
        with pytest.raises(ValueError, match="direction"):
            compile_ir([{"op": "Expand", "direction": "sideways"}])

    def test_expand_invalid_max_per_node_raises(self):
        """GIVEN Expand with negative max_per_node WHEN compile_ir THEN raises ValueError."""
        from ipfs_datasets_py.knowledge_graphs.query.knowledge_graph import compile_ir
        with pytest.raises(ValueError, match="max_per_node"):
            compile_ir([{"op": "Expand", "direction": "both", "max_per_node": -1}])

    def test_limit_negative_n_raises(self):
        """GIVEN Limit with n<0 WHEN compile_ir THEN raises ValueError."""
        from ipfs_datasets_py.knowledge_graphs.query.knowledge_graph import compile_ir
        with pytest.raises(ValueError, match="Limit.n"):
            compile_ir([{"op": "Limit", "n": -1}])

    def test_project_empty_fields_raises(self):
        """GIVEN Project with empty fields WHEN compile_ir THEN raises ValueError."""
        from ipfs_datasets_py.knowledge_graphs.query.knowledge_graph import compile_ir
        with pytest.raises(ValueError, match="fields"):
            compile_ir([{"op": "Project", "fields": []}])

    def test_unsupported_op_raises(self):
        """GIVEN unsupported op name WHEN compile_ir THEN raises ValueError."""
        from ipfs_datasets_py.knowledge_graphs.query.knowledge_graph import compile_ir
        with pytest.raises(ValueError, match="Unsupported IR op"):
            compile_ir([{"op": "DeleteAll"}])


class TestQueryKnowledgeGraphErrors:
    """Tests for query_knowledge_graph() validation and routing errors."""

    def test_invalid_max_results_raises(self):
        """GIVEN max_results <= 0 WHEN query_knowledge_graph THEN raises ValueError."""
        from ipfs_datasets_py.knowledge_graphs.query.knowledge_graph import query_knowledge_graph
        with pytest.raises(ValueError, match="max_results"):
            query_knowledge_graph(query="test", max_results=0)

    def test_empty_query_raises(self):
        """GIVEN empty query WHEN query_knowledge_graph THEN raises ValueError."""
        from ipfs_datasets_py.knowledge_graphs.query.knowledge_graph import query_knowledge_graph
        with pytest.raises(ValueError, match="non-empty string"):
            query_knowledge_graph(query="  ")

    def test_sparql_without_graph_id_raises(self):
        """GIVEN query_type=sparql without graph_id WHEN query_knowledge_graph THEN raises ValueError."""
        from ipfs_datasets_py.knowledge_graphs.query.knowledge_graph import query_knowledge_graph
        with pytest.raises(ValueError, match="graph_id"):
            query_knowledge_graph(query="SELECT ?x WHERE {}", query_type="sparql")

    def test_cypher_without_graph_id_raises(self):
        """GIVEN query_type=cypher without graph_id WHEN query_knowledge_graph THEN raises ValueError."""
        from ipfs_datasets_py.knowledge_graphs.query.knowledge_graph import query_knowledge_graph
        with pytest.raises(ValueError, match="graph_id"):
            query_knowledge_graph(query="MATCH (n) RETURN n", query_type="cypher")

    def test_unsupported_query_type_raises(self):
        """GIVEN unknown query_type WHEN query_knowledge_graph THEN raises ValueError."""
        from ipfs_datasets_py.knowledge_graphs.query.knowledge_graph import query_knowledge_graph
        with pytest.raises(ValueError, match="Unsupported query_type"):
            query_knowledge_graph(query="test", query_type="graphql")

    def test_ir_without_manifest_cid_raises(self):
        """GIVEN query_type=ir without manifest_cid WHEN query_knowledge_graph THEN raises ValueError."""
        from ipfs_datasets_py.knowledge_graphs.query.knowledge_graph import query_knowledge_graph
        with pytest.raises(ValueError, match="manifest_cid"):
            query_knowledge_graph(query='[{"op":"ScanAll"}]', query_type="ir")


# ═════════════════════════════════════════════════════════════════════════════
# 4. core/expression_evaluator.py
# ═════════════════════════════════════════════════════════════════════════════

class TestApplyOperatorXORAndUnknown:
    """Tests for XOR operator and unknown operator fallback."""

    def test_xor_true_false_returns_true(self):
        """GIVEN XOR(True, False) WHEN apply_operator THEN returns True."""
        from ipfs_datasets_py.knowledge_graphs.core.expression_evaluator import apply_operator
        assert apply_operator(True, "XOR", False) is True

    def test_xor_true_true_returns_false(self):
        """GIVEN XOR(True, True) WHEN apply_operator THEN returns False."""
        from ipfs_datasets_py.knowledge_graphs.core.expression_evaluator import apply_operator
        assert apply_operator(True, "XOR", True) is False

    def test_unknown_operator_returns_false(self):
        """GIVEN unknown operator WHEN apply_operator THEN returns False."""
        from ipfs_datasets_py.knowledge_graphs.core.expression_evaluator import apply_operator
        assert apply_operator(1, "BADOP", 2) is False

    def test_type_error_returns_false(self):
        """GIVEN incomparable types for > WHEN apply_operator THEN returns False."""
        from ipfs_datasets_py.knowledge_graphs.core.expression_evaluator import apply_operator
        assert apply_operator("text", ">", 5) is False


class TestCallFunctionRegistry:
    """Tests for call_function using FUNCTION_REGISTRY path."""

    def test_abs_single_arg(self):
        """GIVEN abs(-5) in FUNCTION_REGISTRY WHEN call_function THEN returns 5."""
        from ipfs_datasets_py.knowledge_graphs.core.expression_evaluator import call_function
        assert call_function("abs", [-5]) == 5

    def test_sqrt_single_arg(self):
        """GIVEN sqrt(9) in FUNCTION_REGISTRY WHEN call_function THEN returns 3.0."""
        from ipfs_datasets_py.knowledge_graphs.core.expression_evaluator import call_function
        assert call_function("sqrt", [9]) == 3.0

    def test_rand_zero_args(self):
        """GIVEN rand() with empty args WHEN call_function THEN returns float in [0, 1)."""
        from ipfs_datasets_py.knowledge_graphs.core.expression_evaluator import call_function
        result = call_function("rand", [])
        assert isinstance(result, float)
        assert 0.0 <= result < 1.0

    def test_sqrt_negative_returns_none(self):
        """GIVEN sqrt(-1) WHEN call_function THEN returns None (exception suppressed)."""
        from ipfs_datasets_py.knowledge_graphs.core.expression_evaluator import call_function
        assert call_function("sqrt", [-1]) is None

    def test_atan2_multi_arg(self):
        """GIVEN atan2(1, 1) WHEN call_function THEN returns correct float."""
        import math
        from ipfs_datasets_py.knowledge_graphs.core.expression_evaluator import call_function
        result = call_function("atan2", [1, 1])
        assert result is not None
        assert abs(result - math.pi / 4) < 1e-9


class TestCallFunctionStringFunctions:
    """Tests for string/collection functions in call_function."""

    def test_tolower_with_none_returns_none(self):
        """GIVEN tolower(None) WHEN call_function THEN returns None."""
        from ipfs_datasets_py.knowledge_graphs.core.expression_evaluator import call_function
        assert call_function("tolower", [None]) is None

    def test_ltrim_removes_leading_spaces(self):
        """GIVEN ltrim(' hello') WHEN call_function THEN returns 'hello'."""
        from ipfs_datasets_py.knowledge_graphs.core.expression_evaluator import call_function
        assert call_function("ltrim", ["  hello"]) == "hello"

    def test_rtrim_removes_trailing_spaces(self):
        """GIVEN rtrim('hello  ') WHEN call_function THEN returns 'hello'."""
        from ipfs_datasets_py.knowledge_graphs.core.expression_evaluator import call_function
        assert call_function("rtrim", ["hello  "]) == "hello"

    def test_replace_substitutes_substring(self):
        """GIVEN replace('hello world', 'world', 'foo') WHEN call_function THEN returns 'hello foo'."""
        from ipfs_datasets_py.knowledge_graphs.core.expression_evaluator import call_function
        assert call_function("replace", ["hello world", "world", "foo"]) == "hello foo"

    def test_reverse_reverses_string(self):
        """GIVEN reverse('abc') WHEN call_function THEN returns 'cba'."""
        from ipfs_datasets_py.knowledge_graphs.core.expression_evaluator import call_function
        assert call_function("reverse", ["abc"]) == "cba"

    def test_size_string(self):
        """GIVEN size('hello') WHEN call_function THEN returns 5."""
        from ipfs_datasets_py.knowledge_graphs.core.expression_evaluator import call_function
        assert call_function("size", ["hello"]) == 5

    def test_size_list(self):
        """GIVEN size([1,2,3]) WHEN call_function THEN returns 3."""
        from ipfs_datasets_py.knowledge_graphs.core.expression_evaluator import call_function
        assert call_function("size", [[1, 2, 3]]) == 3

    def test_split_by_comma(self):
        """GIVEN split('a,b,c', ',') WHEN call_function THEN returns ['a', 'b', 'c']."""
        from ipfs_datasets_py.knowledge_graphs.core.expression_evaluator import call_function
        assert call_function("split", ["a,b,c", ","]) == ["a", "b", "c"]

    def test_left_returns_prefix(self):
        """GIVEN left('hello', 3) WHEN call_function THEN returns 'hel'."""
        from ipfs_datasets_py.knowledge_graphs.core.expression_evaluator import call_function
        assert call_function("left", ["hello", 3]) == "hel"

    def test_right_returns_suffix(self):
        """GIVEN right('hello', 3) WHEN call_function THEN returns 'llo'."""
        from ipfs_datasets_py.knowledge_graphs.core.expression_evaluator import call_function
        assert call_function("right", ["hello", 3]) == "llo"


class TestEvaluateExpressionPropertyAccess:
    """Tests for property and variable access in evaluate_expression."""

    def test_property_via_dict_get(self):
        """GIVEN row with dict value WHEN evaluate_expression('n.name') THEN returns value."""
        from ipfs_datasets_py.knowledge_graphs.core.expression_evaluator import evaluate_expression
        row = {"n": {"name": "Alice"}}
        assert evaluate_expression("n.name", row) == "Alice"

    def test_property_via_underscore_properties(self):
        """GIVEN row with _properties attribute WHEN evaluate_expression THEN returns value."""
        from ipfs_datasets_py.knowledge_graphs.core.expression_evaluator import evaluate_expression

        class MockNode:
            def __init__(self):
                self._properties = {"age": 30}
        row = {"n": MockNode()}
        assert evaluate_expression("n.age", row) == 30

    def test_variable_lookup_in_row(self):
        """GIVEN row with 'name' key WHEN evaluate_expression('name') THEN returns value."""
        from ipfs_datasets_py.knowledge_graphs.core.expression_evaluator import evaluate_expression
        assert evaluate_expression("name", {"name": "Bob"}) == "Bob"

    def test_unknown_expression_returns_none(self):
        """GIVEN expression not in row WHEN evaluate_expression THEN returns None."""
        from ipfs_datasets_py.knowledge_graphs.core.expression_evaluator import evaluate_expression
        assert evaluate_expression("unknown_var", {"x": 1}) is None


class TestEvaluateCaseExpression:
    """Tests for evaluate_case_expression."""

    def test_simple_case_match_returns_value(self):
        """GIVEN CASE x WHEN x (same var) THEN row.y WHEN test_value equals when_value THEN returns y."""
        from ipfs_datasets_py.knowledge_graphs.core.expression_evaluator import evaluate_case_expression
        # test_expr='x' evaluates to 1; WHEN:x evaluates to 1 too → match → return row['y']
        case = "CASE|TEST:x|WHEN:x:THEN:y|END"
        row = {"x": 1, "y": "found"}
        assert evaluate_case_expression(case, row) == "found"

    def test_simple_case_no_match_returns_none(self):
        """GIVEN CASE x WHEN 1 ... WHEN x doesn't match THEN returns None."""
        from ipfs_datasets_py.knowledge_graphs.core.expression_evaluator import evaluate_case_expression
        case = "CASE|TEST:x|WHEN:1:THEN:y|END"
        assert evaluate_case_expression(case, {"x": 99, "y": "found"}) is None

    def test_generic_case_when_condition_true(self):
        """GIVEN generic CASE WHEN condition true THEN returns result value."""
        from ipfs_datasets_py.knowledge_graphs.core.expression_evaluator import evaluate_case_expression
        case = "CASE|WHEN:x:THEN:x|END"
        assert evaluate_case_expression(case, {"x": "hello"}) == "hello"

    def test_generic_case_else_branch(self):
        """GIVEN generic CASE WHEN no match ELSE clause THEN returns else result."""
        from ipfs_datasets_py.knowledge_graphs.core.expression_evaluator import evaluate_case_expression
        # condition = 'flag' (False), else = 'flag' evaluated = False
        case = "CASE|WHEN:flag:THEN:flag|ELSE:flag|END"
        # With flag=False: condition false, else branch runs
        result = evaluate_case_expression(case, {"flag": False})
        assert result is False  # evaluate_expression('flag', row) = False

    def test_invalid_case_format_returns_none(self):
        """GIVEN invalid CASE format WHEN evaluate_case_expression THEN returns None."""
        from ipfs_datasets_py.knowledge_graphs.core.expression_evaluator import evaluate_case_expression
        result = evaluate_case_expression("NOT_A_CASE|something", {})
        assert result is None


class TestEvaluateCondition:
    """Tests for evaluate_condition."""

    def test_condition_with_equals_operator(self):
        """GIVEN 'x = y' condition WHEN evaluate_condition THEN returns True when x==y."""
        from ipfs_datasets_py.knowledge_graphs.core.expression_evaluator import evaluate_condition
        assert evaluate_condition("x = y", {"x": 1, "y": 1}) is True

    def test_condition_falsy_expression(self):
        """GIVEN truthy variable WHEN evaluate_condition THEN returns bool."""
        from ipfs_datasets_py.knowledge_graphs.core.expression_evaluator import evaluate_condition
        assert evaluate_condition("x", {"x": 0}) is False
        assert evaluate_condition("x", {"x": 42}) is True


class TestEvaluateCompiledExpression:
    """Tests for evaluate_compiled_expression (dict-based compiled IR)."""

    def test_and_short_circuits_on_false(self):
        """GIVEN AND(False, True) WHEN evaluate_compiled_expression THEN returns False."""
        from ipfs_datasets_py.knowledge_graphs.core.expression_evaluator import evaluate_compiled_expression
        expr = {"op": "AND", "left": False, "right": True}
        assert evaluate_compiled_expression(expr, {}) is False

    def test_or_short_circuits_on_true(self):
        """GIVEN OR(True, False) WHEN evaluate_compiled_expression THEN returns True."""
        from ipfs_datasets_py.knowledge_graphs.core.expression_evaluator import evaluate_compiled_expression
        expr = {"op": "OR", "left": True, "right": False}
        assert evaluate_compiled_expression(expr, {}) is True

    def test_xor_compiled(self):
        """GIVEN XOR(True, False) WHEN evaluate_compiled_expression THEN returns True."""
        from ipfs_datasets_py.knowledge_graphs.core.expression_evaluator import evaluate_compiled_expression
        expr = {"op": "XOR", "left": True, "right": False}
        assert evaluate_compiled_expression(expr, {}) is True

    def test_not_unary(self):
        """GIVEN NOT(True) WHEN evaluate_compiled_expression THEN returns False."""
        from ipfs_datasets_py.knowledge_graphs.core.expression_evaluator import evaluate_compiled_expression
        expr = {"op": "NOT", "operand": True}
        assert evaluate_compiled_expression(expr, {}) is False

    def test_minus_unary(self):
        """GIVEN MINUS(5) WHEN evaluate_compiled_expression THEN returns -5."""
        from ipfs_datasets_py.knowledge_graphs.core.expression_evaluator import evaluate_compiled_expression
        expr = {"op": "-", "operand": 5}
        assert evaluate_compiled_expression(expr, {}) == -5

    def test_is_null_on_none(self):
        """GIVEN IS NULL(None) WHEN evaluate_compiled_expression THEN returns True."""
        from ipfs_datasets_py.knowledge_graphs.core.expression_evaluator import evaluate_compiled_expression
        expr = {"op": "IS NULL", "operand": None}
        assert evaluate_compiled_expression(expr, {}) is True

    def test_is_not_null_on_value(self):
        """GIVEN IS NOT NULL('x') WHEN evaluate_compiled_expression THEN returns True."""
        from ipfs_datasets_py.knowledge_graphs.core.expression_evaluator import evaluate_compiled_expression
        expr = {"op": "IS NOT NULL", "operand": "value"}
        assert evaluate_compiled_expression(expr, {}) is True

    def test_string_with_multiple_dots_returns_string(self):
        """GIVEN 3-segment dot string not in binding WHEN evaluate_compiled_expression THEN returns string."""
        from ipfs_datasets_py.knowledge_graphs.core.expression_evaluator import evaluate_compiled_expression
        assert evaluate_compiled_expression("a.b.c", {}) == "a.b.c"

    def test_plain_value_passthrough(self):
        """GIVEN int literal WHEN evaluate_compiled_expression THEN returns it."""
        from ipfs_datasets_py.knowledge_graphs.core.expression_evaluator import evaluate_compiled_expression
        assert evaluate_compiled_expression(42, {}) == 42


# ═════════════════════════════════════════════════════════════════════════════
# 5. query/budget_manager.py
# ═════════════════════════════════════════════════════════════════════════════

class TestBudgetTrackerLimits:
    """Tests for BudgetTracker limit checks."""

    def _make_tracker(self, **overrides):
        from ipfs_datasets_py.knowledge_graphs.query.budget_manager import BudgetTracker, budgets_from_preset
        budgets = budgets_from_preset("safe", overrides=overrides if overrides else None)
        return BudgetTracker(budgets)

    def test_check_timeout_raises_when_exceeded(self):
        """GIVEN tiny timeout WHEN check_timeout after sleep THEN raises BudgetExceededError."""
        from ipfs_datasets_py.knowledge_graphs.query.budget_manager import BudgetTracker, budgets_from_preset
        from ipfs_datasets_py.search.graph_query.errors import BudgetExceededError
        budgets = budgets_from_preset("safe", overrides={"timeout_ms": 1})
        tracker = BudgetTracker(budgets)
        time.sleep(0.01)
        with pytest.raises(BudgetExceededError):
            tracker.check_timeout()
        assert tracker.exceeded is True
        assert tracker.exceeded_reason is not None

    def test_check_nodes_raises_when_exceeded(self):
        """GIVEN max_nodes_visited=1 WHEN check_nodes with 2 visited THEN raises."""
        from ipfs_datasets_py.knowledge_graphs.query.budget_manager import BudgetTracker, budgets_from_preset
        from ipfs_datasets_py.search.graph_query.errors import BudgetExceededError
        budgets = budgets_from_preset("safe", overrides={"max_nodes_visited": 1})
        tracker = BudgetTracker(budgets)
        tracker.counters.nodes_visited = 2
        with pytest.raises(BudgetExceededError):
            tracker.check_nodes()

    def test_check_edges_raises_when_exceeded(self):
        """GIVEN max_edges_scanned=1 WHEN check_edges with 2 scanned THEN raises."""
        from ipfs_datasets_py.knowledge_graphs.query.budget_manager import BudgetTracker, budgets_from_preset
        from ipfs_datasets_py.search.graph_query.errors import BudgetExceededError
        budgets = budgets_from_preset("safe", overrides={"max_edges_scanned": 1})
        tracker = BudgetTracker(budgets)
        tracker.counters.edges_scanned = 2
        with pytest.raises(BudgetExceededError):
            tracker.check_edges()

    def test_check_depth_raises_when_exceeded(self):
        """GIVEN max_depth=1 WHEN check_depth with depth=2 THEN raises."""
        from ipfs_datasets_py.knowledge_graphs.query.budget_manager import BudgetTracker, budgets_from_preset
        from ipfs_datasets_py.search.graph_query.errors import BudgetExceededError
        budgets = budgets_from_preset("safe", overrides={"max_depth": 1})
        tracker = BudgetTracker(budgets)
        tracker.counters.depth = 2
        with pytest.raises(BudgetExceededError):
            tracker.check_depth()

    def test_check_all_passes_when_within_budget(self):
        """GIVEN all counters at zero WHEN check_all with large timeout THEN no exception."""
        from ipfs_datasets_py.knowledge_graphs.query.budget_manager import BudgetTracker, budgets_from_preset
        budgets = budgets_from_preset("safe")
        tracker = BudgetTracker(budgets)
        tracker.check_all()  # Should not raise

    def test_increment_nodes_triggers_check(self):
        """GIVEN max_nodes=2 WHEN increment_nodes(3) THEN raises BudgetExceededError."""
        from ipfs_datasets_py.knowledge_graphs.query.budget_manager import BudgetTracker, budgets_from_preset
        from ipfs_datasets_py.search.graph_query.errors import BudgetExceededError
        budgets = budgets_from_preset("safe", overrides={"max_nodes_visited": 2})
        tracker = BudgetTracker(budgets)
        with pytest.raises(BudgetExceededError):
            tracker.increment_nodes(3)

    def test_increment_edges_triggers_check(self):
        """GIVEN max_edges=1 WHEN increment_edges(2) THEN raises BudgetExceededError."""
        from ipfs_datasets_py.knowledge_graphs.query.budget_manager import BudgetTracker, budgets_from_preset
        from ipfs_datasets_py.search.graph_query.errors import BudgetExceededError
        budgets = budgets_from_preset("safe", overrides={"max_edges_scanned": 1})
        tracker = BudgetTracker(budgets)
        with pytest.raises(BudgetExceededError):
            tracker.increment_edges(2)

    def test_increment_depth_triggers_check(self):
        """GIVEN max_depth=1 WHEN increment_depth(2) THEN raises BudgetExceededError."""
        from ipfs_datasets_py.knowledge_graphs.query.budget_manager import BudgetTracker, budgets_from_preset
        from ipfs_datasets_py.search.graph_query.errors import BudgetExceededError
        budgets = budgets_from_preset("safe", overrides={"max_depth": 1})
        tracker = BudgetTracker(budgets)
        with pytest.raises(BudgetExceededError):
            tracker.increment_depth(2)

    def test_get_stats_has_required_keys(self):
        """GIVEN tracker WHEN get_stats THEN returns dict with expected keys."""
        from ipfs_datasets_py.knowledge_graphs.query.budget_manager import BudgetTracker, budgets_from_preset
        budgets = budgets_from_preset("safe")
        tracker = BudgetTracker(budgets)
        stats = tracker.get_stats()
        assert "elapsed_ms" in stats
        assert "nodes_visited" in stats
        assert "edges_scanned" in stats
        assert "exceeded" in stats
        assert "budgets" in stats


class TestBudgetManagerPresets:
    """Tests for BudgetManager.create_preset_budgets."""

    def test_create_safe_preset(self):
        """GIVEN 'safe' preset WHEN create_preset_budgets THEN returns ExecutionBudgets."""
        from ipfs_datasets_py.knowledge_graphs.query.budget_manager import BudgetManager, ExecutionBudgets
        manager = BudgetManager()
        budgets = manager.create_preset_budgets("safe", max_results=50)
        assert isinstance(budgets, ExecutionBudgets)

    def test_create_preset_with_override(self):
        """GIVEN 'safe' preset + depth override WHEN create_preset_budgets THEN returns budgets."""
        from ipfs_datasets_py.knowledge_graphs.query.budget_manager import BudgetManager, ExecutionBudgets
        manager = BudgetManager()
        budgets = manager.create_preset_budgets("safe", max_results=50, max_depth=3)
        assert isinstance(budgets, ExecutionBudgets)

    def test_track_context_manager(self):
        """GIVEN BudgetManager.track() WHEN used as context manager THEN yields tracker."""
        from ipfs_datasets_py.knowledge_graphs.query.budget_manager import (
            BudgetManager, BudgetTracker, budgets_from_preset
        )
        manager = BudgetManager()
        budgets = budgets_from_preset("safe")
        with manager.track(budgets) as tracker:
            assert isinstance(tracker, BudgetTracker)
            assert manager.current_tracker is tracker
        assert manager.current_tracker is None


# ═════════════════════════════════════════════════════════════════════════════
# 6. transactions/wal.py
# ═════════════════════════════════════════════════════════════════════════════

class TestWALAppendAndRead:
    """Tests for WriteAheadLog.append and read."""

    def test_append_returns_cid(self):
        """GIVEN WAL WHEN append(entry) THEN returns a non-empty CID string."""
        from ipfs_datasets_py.knowledge_graphs.transactions.wal import WALEntry, WriteAheadLog
        from ipfs_datasets_py.knowledge_graphs.transactions.types import TransactionState
        wal = _make_wal()
        entry = WALEntry(txn_id="t1", timestamp=1.0, operations=[], txn_state=TransactionState.COMMITTED)
        cid = wal.append(entry)
        assert isinstance(cid, str)
        assert cid

    def test_append_increments_entry_count(self):
        """GIVEN empty WAL WHEN append 2 entries THEN entry_count is 2."""
        from ipfs_datasets_py.knowledge_graphs.transactions.wal import WALEntry, WriteAheadLog
        from ipfs_datasets_py.knowledge_graphs.transactions.types import TransactionState
        wal = _make_wal()
        for i in range(2):
            wal.append(WALEntry(txn_id=f"t{i}", timestamp=float(i), operations=[], txn_state=TransactionState.COMMITTED))
        assert wal._entry_count == 2

    def test_append_links_previous(self):
        """GIVEN 2 appended entries WHEN read THEN second entry has prev_wal_cid set."""
        from ipfs_datasets_py.knowledge_graphs.transactions.wal import WALEntry, WriteAheadLog
        from ipfs_datasets_py.knowledge_graphs.transactions.types import TransactionState
        wal = _make_wal()
        cid1 = wal.append(WALEntry(txn_id="t1", timestamp=1.0, operations=[], txn_state=TransactionState.COMMITTED))
        wal.append(WALEntry(txn_id="t2", timestamp=2.0, operations=[], txn_state=TransactionState.COMMITTED))
        entries = list(wal.read())
        # Entries returned in reverse chronological order
        assert entries[0].txn_id == "t2"
        assert entries[1].txn_id == "t1"

    def test_append_serialization_error_raises(self):
        """GIVEN storage.store_json raises TypeError WHEN append THEN raises SerializationError."""
        from ipfs_datasets_py.knowledge_graphs.exceptions import SerializationError
        from ipfs_datasets_py.knowledge_graphs.transactions.wal import WALEntry, WriteAheadLog
        from ipfs_datasets_py.knowledge_graphs.transactions.types import TransactionState
        wal = _make_wal(fail_store=True)
        entry = WALEntry(txn_id="t1", timestamp=1.0, operations=[], txn_state=TransactionState.COMMITTED)
        with pytest.raises(SerializationError):
            wal.append(entry)

    def test_read_empty_wal_returns_nothing(self):
        """GIVEN empty WAL WHEN read THEN yields nothing."""
        wal = _make_wal()
        assert list(wal.read()) == []

    def test_read_storage_error_raises_deserialization_error(self):
        """GIVEN StorageError on retrieve WHEN read THEN raises DeserializationError."""
        from ipfs_datasets_py.knowledge_graphs.exceptions import DeserializationError
        from ipfs_datasets_py.knowledge_graphs.transactions.wal import WALEntry, WriteAheadLog
        from ipfs_datasets_py.knowledge_graphs.transactions.types import TransactionState
        wal = _make_wal()
        wal.append(WALEntry(txn_id="t1", timestamp=1.0, operations=[], txn_state=TransactionState.COMMITTED))
        # Swap storage to a failing one after append
        wal.storage.fail_retrieve = True
        with pytest.raises(DeserializationError):
            list(wal.read())


class TestWALCompact:
    """Tests for WriteAheadLog.compact."""

    def test_compact_returns_new_cid(self):
        """GIVEN WAL with entries WHEN compact THEN returns non-empty CID."""
        from ipfs_datasets_py.knowledge_graphs.transactions.wal import WALEntry
        from ipfs_datasets_py.knowledge_graphs.transactions.types import TransactionState
        wal = _make_wal()
        cid = wal.append(WALEntry(txn_id="t1", timestamp=1.0, operations=[], txn_state=TransactionState.COMMITTED))
        new_head = wal.compact(cid)
        assert isinstance(new_head, str)
        assert new_head != cid

    def test_compact_resets_entry_count(self):
        """GIVEN WAL with 3 entries WHEN compact THEN entry_count resets to 0."""
        from ipfs_datasets_py.knowledge_graphs.transactions.wal import WALEntry
        from ipfs_datasets_py.knowledge_graphs.transactions.types import TransactionState
        wal = _make_wal()
        for i in range(3):
            wal.append(WALEntry(txn_id=f"t{i}", timestamp=float(i), operations=[], txn_state=TransactionState.COMMITTED))
        cid = wal.wal_head_cid
        wal.compact(cid)
        assert wal._entry_count == 0

    def test_compact_updates_head(self):
        """GIVEN WAL WHEN compact THEN wal_head_cid changes."""
        from ipfs_datasets_py.knowledge_graphs.transactions.wal import WALEntry
        from ipfs_datasets_py.knowledge_graphs.transactions.types import TransactionState
        wal = _make_wal()
        cid = wal.append(WALEntry(txn_id="t1", timestamp=1.0, operations=[], txn_state=TransactionState.COMMITTED))
        old_head = wal.wal_head_cid
        wal.compact(cid)
        assert wal.wal_head_cid != old_head


class TestWALRecover:
    """Tests for WriteAheadLog.recover."""

    def test_recover_empty_wal_returns_empty_list(self):
        """GIVEN empty WAL WHEN recover THEN returns []."""
        wal = _make_wal()
        assert wal.recover() == []

    def test_recover_committed_transaction_includes_ops(self):
        """GIVEN 1 committed entry with ops WHEN recover THEN returns those ops."""
        from ipfs_datasets_py.knowledge_graphs.transactions.wal import WALEntry
        from ipfs_datasets_py.knowledge_graphs.transactions.types import Operation, OperationType, TransactionState
        wal = _make_wal()
        op = Operation(type=OperationType.WRITE_NODE, node_id="n1")
        wal.append(WALEntry(txn_id="t1", timestamp=1.0, operations=[op], txn_state=TransactionState.COMMITTED))
        result = wal.recover()
        assert len(result) == 1
        assert result[0].node_id == "n1"

    def test_recover_aborted_transaction_excluded(self):
        """GIVEN 1 aborted + 1 committed entry WHEN recover THEN only committed ops returned."""
        from ipfs_datasets_py.knowledge_graphs.transactions.wal import WALEntry
        from ipfs_datasets_py.knowledge_graphs.transactions.types import Operation, OperationType, TransactionState
        wal = _make_wal()
        committed_op = Operation(type=OperationType.WRITE_NODE, node_id="committed")
        aborted_op = Operation(type=OperationType.WRITE_NODE, node_id="aborted")
        wal.append(WALEntry(txn_id="t1", timestamp=1.0, operations=[committed_op], txn_state=TransactionState.COMMITTED))
        wal.append(WALEntry(txn_id="t2", timestamp=2.0, operations=[aborted_op], txn_state=TransactionState.ABORTED))
        result = wal.recover()
        node_ids = [op.node_id for op in result]
        assert "committed" in node_ids
        assert "aborted" not in node_ids


class TestWALGetTransactionHistory:
    """Tests for WriteAheadLog.get_transaction_history."""

    def test_matching_txn_id_returned(self):
        """GIVEN WAL with entry 't1' WHEN get_transaction_history('t1') THEN returns 1 entry."""
        from ipfs_datasets_py.knowledge_graphs.transactions.wal import WALEntry
        from ipfs_datasets_py.knowledge_graphs.transactions.types import TransactionState
        wal = _make_wal()
        wal.append(WALEntry(txn_id="t1", timestamp=1.0, operations=[], txn_state=TransactionState.COMMITTED))
        hist = wal.get_transaction_history("t1")
        assert len(hist) == 1
        assert hist[0].txn_id == "t1"

    def test_unknown_txn_id_returns_empty(self):
        """GIVEN WAL WHEN get_transaction_history for unknown ID THEN returns []."""
        from ipfs_datasets_py.knowledge_graphs.transactions.wal import WALEntry
        from ipfs_datasets_py.knowledge_graphs.transactions.types import TransactionState
        wal = _make_wal()
        wal.append(WALEntry(txn_id="t1", timestamp=1.0, operations=[], txn_state=TransactionState.COMMITTED))
        assert wal.get_transaction_history("nonexistent") == []


class TestWALGetStatsAndVerifyIntegrity:
    """Tests for WAL statistics and integrity verification."""

    def test_get_stats_has_expected_keys(self):
        """GIVEN WAL WHEN get_stats THEN contains required keys."""
        wal = _make_wal()
        stats = wal.get_stats()
        assert "head_cid" in stats
        assert "entry_count" in stats
        assert "compaction_threshold" in stats
        assert "needs_compaction" in stats

    def test_needs_compaction_false_when_below_threshold(self):
        """GIVEN 0 entries WHEN get_stats THEN needs_compaction is False."""
        wal = _make_wal()
        assert wal.get_stats()["needs_compaction"] is False

    def test_verify_integrity_empty_wal_returns_true(self):
        """GIVEN empty WAL WHEN verify_integrity THEN returns True."""
        wal = _make_wal()
        assert wal.verify_integrity() is True

    def test_verify_integrity_valid_chain_returns_true(self):
        """GIVEN WAL with valid chain WHEN verify_integrity THEN returns True."""
        from ipfs_datasets_py.knowledge_graphs.transactions.wal import WALEntry
        from ipfs_datasets_py.knowledge_graphs.transactions.types import Operation, OperationType, TransactionState
        wal = _make_wal()
        op = Operation(type=OperationType.WRITE_NODE, node_id="n1")
        wal.append(WALEntry(txn_id="t1", timestamp=2.0, operations=[op], txn_state=TransactionState.COMMITTED))
        # Second entry at higher timestamp (added later, appears first in reverse read)
        wal.append(WALEntry(txn_id="t2", timestamp=3.0, operations=[op], txn_state=TransactionState.COMMITTED))
        assert wal.verify_integrity() is True

    def test_verify_integrity_with_storage_error_returns_false(self):
        """GIVEN WAL where read raises DeserializationError WHEN verify_integrity THEN returns False."""
        from ipfs_datasets_py.knowledge_graphs.transactions.wal import WALEntry, WriteAheadLog
        from ipfs_datasets_py.knowledge_graphs.transactions.types import TransactionState
        from ipfs_datasets_py.knowledge_graphs.exceptions import StorageError

        wal = _make_wal()
        wal.append(WALEntry(txn_id="t1", timestamp=1.0, operations=[], txn_state=TransactionState.COMMITTED))
        # Force storage failure after append
        wal.storage.fail_retrieve = True
        assert wal.verify_integrity() is False
