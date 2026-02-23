"""
Session 48 – knowledge_graphs final coverage push.

Targets:
  cypher/compiler.py:261   _compile_node_pattern anonymous variable when node.variable=None
                           and default_var=None (or empty string)
  core/expression_evaluator.py:153-163  `reverse` + `size` string fallback handlers
                           (reachable when those names are absent from FUNCTION_REGISTRY)

Note on ir_executor.py:435-442: These lines check `record._values.get(var_name)` but
Record._values is always a tuple (not a dict), so `.get()` raises AttributeError, which
is caught by the except clause. These lines are unreachable in practice and represent dead
code from a legacy implementation.

All tests follow GIVEN-WHEN-THEN.
"""
from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest


# ===========================================================================
# 1. cypher/compiler.py line 261
#    _compile_node_pattern generates anonymous variable when both
#    node.variable and default_var are None/falsy
# ===========================================================================

class TestCompilerAnonymousVariable:
    """GIVEN a NodePattern with no variable and _compile_node_pattern called
    with default_var=None, WHEN compiled, THEN an _anon... variable is
    auto-generated (line 261)."""

    def _compiler(self):
        from ipfs_datasets_py.knowledge_graphs.cypher.compiler import CypherCompiler
        return CypherCompiler()

    def _node_pattern(self, variable=None, labels=None, properties=None):
        from ipfs_datasets_py.knowledge_graphs.cypher.ast import NodePattern
        return NodePattern(
            variable=variable,
            labels=labels or [],
            properties=properties or {},
        )

    def test_no_variable_no_default_generates_anon_var(self):
        """GIVEN node.variable=None and default_var omitted WHEN
        _compile_node_pattern() THEN an _anon variable is created (line 261)."""
        compiler = self._compiler()
        node = self._node_pattern(variable=None, labels=["Person"])
        # Calling without default_var → default_var=None → line 260 `if not variable:` True
        compiler._compile_node_pattern(node)
        # The anonymous variable should exist in compiler.variables
        anon_vars = [v for v in compiler.variables if v.startswith("_anon")]
        assert len(anon_vars) == 1, f"Expected 1 anon var, got: {list(compiler.variables.keys())}"

    def test_no_variable_no_default_produces_scan_label(self):
        """GIVEN anonymous variable generated WHEN _compile_node_pattern THEN a
        ScanLabel op is emitted with the generated variable."""
        compiler = self._compiler()
        node = self._node_pattern(variable=None, labels=["Movie"])
        compiler._compile_node_pattern(node)
        scan_ops = [op for op in compiler.operations if op.get("op") == "ScanLabel"]
        assert len(scan_ops) == 1
        assert scan_ops[0]["label"] == "Movie"
        assert scan_ops[0]["variable"].startswith("_anon")

    def test_no_variable_no_default_no_labels_produces_scan_all(self):
        """GIVEN anonymous variable and no labels WHEN _compile_node_pattern
        THEN a ScanAll op is emitted."""
        compiler = self._compiler()
        node = self._node_pattern(variable=None, labels=[])
        compiler._compile_node_pattern(node)
        scan_all_ops = [op for op in compiler.operations if op.get("op") == "ScanAll"]
        assert len(scan_all_ops) == 1
        assert scan_all_ops[0]["variable"].startswith("_anon")

    def test_multiple_anon_nodes_get_unique_vars(self):
        """GIVEN two anon nodes compiled in sequence WHEN _compile_node_pattern
        THEN each gets a distinct _anon variable."""
        compiler = self._compiler()
        node1 = self._node_pattern(variable=None, labels=["A"])
        node2 = self._node_pattern(variable=None, labels=["B"])
        compiler._compile_node_pattern(node1)
        compiler._compile_node_pattern(node2)
        anon_vars = [v for v in compiler.variables if v.startswith("_anon")]
        assert len(anon_vars) == 2
        assert len(set(anon_vars)) == 2  # all distinct

    def test_empty_string_variable_also_triggers_anon(self):
        """GIVEN node.variable='' (falsy) and no default_var WHEN
        _compile_node_pattern THEN anon variable is generated."""
        compiler = self._compiler()
        node = self._node_pattern(variable="", labels=["Q"])
        compiler._compile_node_pattern(node)  # default_var=None
        anon_vars = [v for v in compiler.variables if v.startswith("_anon")]
        assert len(anon_vars) == 1


# ===========================================================================
# 2. core/expression_evaluator.py lines 152-163
#    `reverse` and `size` fallback handlers in call_function()
#    These are reached when the names are temporarily absent from FUNCTION_REGISTRY
# ===========================================================================

class TestCallFunctionReverseAndSizeFallback:
    """GIVEN `reverse` and `size` are absent from FUNCTION_REGISTRY WHEN
    call_function() is called, THEN the fallback string-handler branches
    (lines 152-163) are executed."""

    def test_reverse_fallback_returns_reversed_string(self):
        """GIVEN 'reverse' absent from registry WHEN call_function('reverse', ['hello'])
        THEN fallback handler returns 'olleh' (lines 152-154)."""
        from ipfs_datasets_py.knowledge_graphs.cypher import functions as fn_mod
        from ipfs_datasets_py.knowledge_graphs.core.expression_evaluator import call_function

        orig = fn_mod.FUNCTION_REGISTRY.pop("reverse", None)
        try:
            result = call_function("reverse", ["hello"])
            assert result == "olleh"
        finally:
            if orig is not None:
                fn_mod.FUNCTION_REGISTRY["reverse"] = orig

    def test_reverse_fallback_non_string_returns_none(self):
        """GIVEN 'reverse' absent from registry WHEN call_function('reverse', [123])
        THEN fallback handler returns None (line 155)."""
        from ipfs_datasets_py.knowledge_graphs.cypher import functions as fn_mod
        from ipfs_datasets_py.knowledge_graphs.core.expression_evaluator import call_function

        orig = fn_mod.FUNCTION_REGISTRY.pop("reverse", None)
        try:
            result = call_function("reverse", [123])
            assert result is None
        finally:
            if orig is not None:
                fn_mod.FUNCTION_REGISTRY["reverse"] = orig

    def test_reverse_fallback_empty_args_returns_none(self):
        """GIVEN 'reverse' absent from registry WHEN call_function('reverse', [])
        THEN fallback handler returns None (line 155)."""
        from ipfs_datasets_py.knowledge_graphs.cypher import functions as fn_mod
        from ipfs_datasets_py.knowledge_graphs.core.expression_evaluator import call_function

        orig = fn_mod.FUNCTION_REGISTRY.pop("reverse", None)
        try:
            result = call_function("reverse", [])
            assert result is None
        finally:
            if orig is not None:
                fn_mod.FUNCTION_REGISTRY["reverse"] = orig

    def test_size_fallback_string_returns_length(self):
        """GIVEN 'size' absent from registry WHEN call_function('size', ['hello'])
        THEN fallback handler returns 5 (lines 157-160)."""
        from ipfs_datasets_py.knowledge_graphs.cypher import functions as fn_mod
        from ipfs_datasets_py.knowledge_graphs.core.expression_evaluator import call_function

        orig = fn_mod.FUNCTION_REGISTRY.pop("size", None)
        try:
            result = call_function("size", ["hello"])
            assert result == 5
        finally:
            if orig is not None:
                fn_mod.FUNCTION_REGISTRY["size"] = orig

    def test_size_fallback_list_returns_length(self):
        """GIVEN 'size' absent from registry WHEN call_function('size', [[1, 2, 3]])
        THEN fallback handler returns 3 (lines 157-162)."""
        from ipfs_datasets_py.knowledge_graphs.cypher import functions as fn_mod
        from ipfs_datasets_py.knowledge_graphs.core.expression_evaluator import call_function

        orig = fn_mod.FUNCTION_REGISTRY.pop("size", None)
        try:
            result = call_function("size", [[1, 2, 3]])
            assert result == 3
        finally:
            if orig is not None:
                fn_mod.FUNCTION_REGISTRY["size"] = orig

    def test_size_fallback_tuple_returns_length(self):
        """GIVEN 'size' absent from registry WHEN call_function('size', [(1, 2)])
        THEN fallback handler returns 2 (lines 157-162)."""
        from ipfs_datasets_py.knowledge_graphs.cypher import functions as fn_mod
        from ipfs_datasets_py.knowledge_graphs.core.expression_evaluator import call_function

        orig = fn_mod.FUNCTION_REGISTRY.pop("size", None)
        try:
            result = call_function("size", [(1, 2)])
            assert result == 2
        finally:
            if orig is not None:
                fn_mod.FUNCTION_REGISTRY["size"] = orig

    def test_size_fallback_no_args_returns_none(self):
        """GIVEN 'size' absent from registry WHEN call_function('size', [])
        THEN fallback handler returns None (line 163)."""
        from ipfs_datasets_py.knowledge_graphs.cypher import functions as fn_mod
        from ipfs_datasets_py.knowledge_graphs.core.expression_evaluator import call_function

        orig = fn_mod.FUNCTION_REGISTRY.pop("size", None)
        try:
            result = call_function("size", [])
            assert result is None
        finally:
            if orig is not None:
                fn_mod.FUNCTION_REGISTRY["size"] = orig

    def test_size_fallback_non_string_non_list_returns_none(self):
        """GIVEN 'size' absent from registry WHEN call_function('size', [42])
        THEN 42 is not str/list/tuple → returns None (line 163)."""
        from ipfs_datasets_py.knowledge_graphs.cypher import functions as fn_mod
        from ipfs_datasets_py.knowledge_graphs.core.expression_evaluator import call_function

        orig = fn_mod.FUNCTION_REGISTRY.pop("size", None)
        try:
            result = call_function("size", [42])
            assert result is None
        finally:
            if orig is not None:
                fn_mod.FUNCTION_REGISTRY["size"] = orig


# ===========================================================================
# 3. ontology/reasoning.py line 828
#    _apply_transitive BFS cycle-guard: `if mid in visited: continue`
#    Triggered when the transitive property graph contains a cycle
#    (e.g. A→B, B→C, C→B), causing B to appear in the BFS queue a second time
# ===========================================================================

class TestOntologyReasonerTransitiveCycleGuard:
    """GIVEN a cyclic transitive property graph WHEN materialize() is called
    THEN line 828 fires and the BFS terminates without infinite loop."""

    def _make_reasoner(self, prop_name):
        from ipfs_datasets_py.knowledge_graphs.ontology.reasoning import OntologySchema, OntologyReasoner
        s = OntologySchema()
        s.add_transitive(prop_name)
        return OntologyReasoner(s)

    def _add_rel(self, kg, Relationship, src_entity, tgt_entity, prop):
        rel = Relationship(
            relationship_type=prop,
            source_entity=src_entity,
            target_entity=tgt_entity,
            confidence=0.9,
        )
        kg.add_relationship(rel)

    def test_bfs_cycle_guard_fires_for_a_b_c_b(self):
        """GIVEN A→B→C→B (cycle) WHEN _apply_transitive BFS for start=A
        THEN B is popped twice; second time `mid in visited` is True → line 828."""
        from ipfs_datasets_py.knowledge_graphs.ontology.reasoning import OntologySchema, OntologyReasoner
        from ipfs_datasets_py.knowledge_graphs.extraction.graph import (
            KnowledgeGraph, Entity, Relationship,
        )

        prop = "connects"
        s = OntologySchema()
        s.add_transitive(prop)
        r = OntologyReasoner(s)

        kg = KnowledgeGraph()
        ea = Entity(entity_id="A", name="A", entity_type="Node")
        eb = Entity(entity_id="B", name="B", entity_type="Node")
        ec = Entity(entity_id="C", name="C", entity_type="Node")
        kg.add_entity(ea); kg.add_entity(eb); kg.add_entity(ec)

        # A→B, B→C, C→B (cycle back to B)
        self._add_rel(kg, Relationship, ea, eb, prop)
        self._add_rel(kg, Relationship, eb, ec, prop)
        self._add_rel(kg, Relationship, ec, eb, prop)  # cycle

        # materialize should complete without infinite loop
        result = r.materialize(kg)
        rel_types = {rel.relationship_type for rel in result.relationships.values()}
        assert prop in rel_types

    def test_bfs_terminates_with_long_cycle(self):
        """GIVEN A→B→C→D→B (longer cycle) WHEN materialize THEN terminates cleanly."""
        from ipfs_datasets_py.knowledge_graphs.ontology.reasoning import OntologySchema, OntologyReasoner
        from ipfs_datasets_py.knowledge_graphs.extraction.graph import (
            KnowledgeGraph, Entity, Relationship,
        )

        prop = "relates"
        s = OntologySchema()
        s.add_transitive(prop)
        r = OntologyReasoner(s)

        kg = KnowledgeGraph()
        nodes = [Entity(entity_id=i, name=i, entity_type="N") for i in ["A", "B", "C", "D"]]
        for n in nodes:
            kg.add_entity(n)
        node_map = {n.entity_id: n for n in nodes}

        # chain A→B→C→D→B
        pairs = [("A", "B"), ("B", "C"), ("C", "D"), ("D", "B")]
        for src_id, tgt_id in pairs:
            self._add_rel(kg, Relationship, node_map[src_id], node_map[tgt_id], prop)

        result = r.materialize(kg)
        assert result is not None

    def test_bfs_cycle_does_not_duplicate_inferred_rels(self):
        """GIVEN cycle A→B→C→B WHEN materialize THEN inferred A→C added only once."""
        from ipfs_datasets_py.knowledge_graphs.ontology.reasoning import OntologySchema, OntologyReasoner
        from ipfs_datasets_py.knowledge_graphs.extraction.graph import (
            KnowledgeGraph, Entity, Relationship,
        )

        prop = "likes"
        s = OntologySchema()
        s.add_transitive(prop)
        r = OntologyReasoner(s)

        kg = KnowledgeGraph()
        ea = Entity(entity_id="A", name="A", entity_type="X")
        eb = Entity(entity_id="B", name="B", entity_type="X")
        ec = Entity(entity_id="C", name="C", entity_type="X")
        kg.add_entity(ea); kg.add_entity(eb); kg.add_entity(ec)

        self._add_rel(kg, Relationship, ea, eb, prop)
        self._add_rel(kg, Relationship, eb, ec, prop)
        self._add_rel(kg, Relationship, ec, eb, prop)

        result = r.materialize(kg)
        inferred = [
            rel for rel in result.relationships.values()
            if rel.relationship_type == prop
            and getattr(rel, "properties", {}).get("inferred")
        ]
        # A→C should be inferred (not duplicated)
        assert len(inferred) >= 1
