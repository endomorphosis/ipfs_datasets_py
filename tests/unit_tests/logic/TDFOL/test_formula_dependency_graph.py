"""
Tests for TDFOL Formula Dependency Graph module.

Covers FormulaDependencyGraph, DependencyNode, DependencyEdge,
CircularDependencyError, FormulaType, DependencyType, and
convenience functions (analyze_proof_dependencies, find_proof_chain).

Session 32 — targeting 0%→90%+ coverage of formula_dependency_graph.py.
"""

from __future__ import annotations

import json
import tempfile
import os
from pathlib import Path
from typing import List

import pytest

from ipfs_datasets_py.logic.TDFOL import (
    BinaryFormula,
    Constant,
    DeonticFormula,
    DeonticOperator,
    LogicOperator,
    Predicate,
    TemporalFormula,
    TemporalOperator,
    UnaryFormula,
)
from ipfs_datasets_py.logic.TDFOL.formula_dependency_graph import (
    CircularDependencyError,
    DependencyEdge,
    DependencyNode,
    DependencyType,
    FormulaDependencyGraph,
    FormulaType,
    analyze_proof_dependencies,
    find_proof_chain,
)
from ipfs_datasets_py.logic.TDFOL.tdfol_core import TDFOLKnowledgeBase
from ipfs_datasets_py.logic.TDFOL.tdfol_prover import ProofResult, ProofStatus, ProofStep

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _pred(name: str, arg: str = "a") -> Predicate:
    return Predicate(name, [Constant(arg)])


def _make_proof_result(goal, premises, step_formula=None):
    """Build a minimal ProofResult with one proof step."""
    step_formula = step_formula or goal
    step = ProofStep(
        formula=step_formula,
        justification="test",
        rule_name="TestRule",
        premises=list(premises),
    )
    return ProofResult(
        status=ProofStatus.PROVED,
        formula=goal,
        proof_steps=[step],
        time_ms=1.0,
        method="test",
        message="ok",
    )


# ---------------------------------------------------------------------------
# FormulaType and DependencyType enums
# ---------------------------------------------------------------------------

class TestFormulaTypeEnum:
    def test_all_values_exist(self):
        assert FormulaType.AXIOM.value == "axiom"
        assert FormulaType.THEOREM.value == "theorem"
        assert FormulaType.DERIVED.value == "derived"
        assert FormulaType.PREMISE.value == "premise"
        assert FormulaType.GOAL.value == "goal"
        assert FormulaType.LEMMA.value == "lemma"

    def test_count(self):
        assert len(FormulaType) == 6


class TestDependencyTypeEnum:
    def test_values_exist(self):
        assert DependencyType.DIRECT.value == "direct"
        assert DependencyType.TRANSITIVE.value == "transitive"
        assert DependencyType.SUPPORT.value == "support"


# ---------------------------------------------------------------------------
# DependencyNode
# ---------------------------------------------------------------------------

class TestDependencyNode:
    def test_basic_construction(self):
        p = _pred("P")
        node = DependencyNode(formula=p, node_type=FormulaType.AXIOM)
        assert node.formula == p
        assert node.node_type == FormulaType.AXIOM
        assert node.name is None
        assert node.metadata == {}

    def test_with_name_and_metadata(self):
        p = _pred("P")
        node = DependencyNode(formula=p, node_type=FormulaType.THEOREM,
                              name="myThm", metadata={"source": "test"})
        assert node.name == "myThm"
        assert node.metadata["source"] == "test"

    def test_hash_based_on_formula(self):
        p = _pred("P")
        n1 = DependencyNode(formula=p, node_type=FormulaType.AXIOM)
        n2 = DependencyNode(formula=p, node_type=FormulaType.THEOREM)
        assert hash(n1) == hash(n2)
        assert {n1, n2} == {n1}  # same formula → same set entry

    def test_equality(self):
        p = _pred("P")
        q = _pred("Q")
        n1 = DependencyNode(formula=p, node_type=FormulaType.AXIOM)
        n2 = DependencyNode(formula=p, node_type=FormulaType.DERIVED)
        n3 = DependencyNode(formula=q, node_type=FormulaType.AXIOM)
        assert n1 == n2
        assert n1 != n3
        assert n1 != "not_a_node"

    def test_to_dict(self):
        p = _pred("P")
        node = DependencyNode(formula=p, node_type=FormulaType.AXIOM,
                              name="ax1", metadata={"k": "v"})
        d = node.to_dict()
        assert d["formula"] == str(p)
        assert d["type"] == "axiom"
        assert d["name"] == "ax1"
        assert d["metadata"] == {"k": "v"}

    def test_to_dict_no_name(self):
        p = _pred("P")
        node = DependencyNode(formula=p, node_type=FormulaType.DERIVED)
        d = node.to_dict()
        assert d["name"] is None
        assert d["metadata"] == {}


# ---------------------------------------------------------------------------
# DependencyEdge
# ---------------------------------------------------------------------------

class TestDependencyEdge:
    def _make_edge(self, src_name="P", tgt_name="Q"):
        src_node = DependencyNode(formula=_pred(src_name), node_type=FormulaType.PREMISE)
        tgt_node = DependencyNode(formula=_pred(tgt_name), node_type=FormulaType.DERIVED)
        return DependencyEdge(source=src_node, target=tgt_node,
                              rule_name="Rule1", justification="j",
                              edge_type=DependencyType.DIRECT)

    def test_basic_construction(self):
        edge = self._make_edge()
        assert edge.rule_name == "Rule1"
        assert edge.justification == "j"
        assert edge.edge_type == DependencyType.DIRECT

    def test_hash_based_on_source_target(self):
        e1 = self._make_edge("P", "Q")
        e2 = self._make_edge("P", "Q")
        assert hash(e1) == hash(e2)
        assert {e1, e2} == {e1}

    def test_equality(self):
        e1 = self._make_edge("P", "Q")
        e2 = self._make_edge("P", "Q")
        e3 = self._make_edge("P", "R")
        assert e1 == e2
        assert e1 != e3
        assert e1 != "not_an_edge"

    def test_to_dict(self):
        edge = self._make_edge("P", "Q")
        d = edge.to_dict()
        assert "source" in d
        assert "target" in d
        assert d["rule"] == "Rule1"
        assert d["justification"] == "j"
        assert d["type"] == "direct"


# ---------------------------------------------------------------------------
# CircularDependencyError
# ---------------------------------------------------------------------------

class TestCircularDependencyError:
    def test_construction_with_cycle(self):
        p = _pred("P")
        q = _pred("Q")
        err = CircularDependencyError([p, q, p])
        assert err.cycle == [p, q, p]
        assert "Circular dependency" in str(err)

    def test_custom_message(self):
        err = CircularDependencyError([], message="custom message")
        assert str(err) == "custom message"


# ---------------------------------------------------------------------------
# FormulaDependencyGraph — Initialization
# ---------------------------------------------------------------------------

class TestFormulaDependencyGraphInit:
    def test_empty_init(self):
        g = FormulaDependencyGraph()
        assert len(g.nodes) == 0
        assert len(g.edges) == 0

    def test_init_from_kb_axioms(self):
        kb = TDFOLKnowledgeBase()
        p = _pred("P")
        q = _pred("Q")
        kb.add_axiom(p)
        kb.add_axiom(q)
        g = FormulaDependencyGraph(kb=kb)
        assert p in g.nodes
        assert q in g.nodes
        assert g.nodes[p].node_type == FormulaType.AXIOM
        assert g.nodes[q].node_type == FormulaType.AXIOM

    def test_init_from_kb_theorems(self):
        kb = TDFOLKnowledgeBase()
        t = _pred("T")
        kb.add_theorem(t)
        g = FormulaDependencyGraph(kb=kb)
        assert g.nodes[t].node_type == FormulaType.THEOREM

    def test_init_from_kb_definitions(self):
        kb = TDFOLKnowledgeBase()
        d = _pred("D")
        kb.definitions["mydef"] = d
        g = FormulaDependencyGraph(kb=kb)
        assert d in g.nodes
        assert g.nodes[d].node_type == FormulaType.DERIVED
        assert g.nodes[d].name == "mydef"

    def test_init_from_proof_result(self):
        p = _pred("P")
        q = _pred("Q")
        result = _make_proof_result(q, [p])
        g = FormulaDependencyGraph(proof_result=result)
        assert q in g.nodes
        assert g.nodes[q].node_type == FormulaType.GOAL

    def test_init_from_both_kb_and_proof(self):
        p = _pred("P")
        q = _pred("Q")
        kb = TDFOLKnowledgeBase()
        kb.add_axiom(p)
        result = _make_proof_result(q, [p])
        g = FormulaDependencyGraph(kb=kb, proof_result=result)
        assert p in g.nodes
        assert q in g.nodes
        assert g.nodes[p].node_type == FormulaType.AXIOM


# ---------------------------------------------------------------------------
# FormulaDependencyGraph — add_formula and add_proof
# ---------------------------------------------------------------------------

class TestFormulaDependencyGraphAddFormula:
    def test_add_single_formula_no_deps(self):
        g = FormulaDependencyGraph()
        p = _pred("P")
        g.add_formula(p, [], "Rule1")
        assert p in g.nodes
        assert len(g.edges) == 0

    def test_add_formula_with_dependency(self):
        g = FormulaDependencyGraph()
        p = _pred("P")
        q = _pred("Q")
        g.add_formula(q, [p], "Rule1", "justification")
        assert p in g.nodes
        assert q in g.nodes
        assert len(g.edges) == 1
        edge = list(g.edges)[0]
        assert edge.source.formula == p
        assert edge.target.formula == q
        assert edge.rule_name == "Rule1"

    def test_add_formula_creates_premise_node(self):
        g = FormulaDependencyGraph()
        p = _pred("P")
        q = _pred("Q")
        g.add_formula(q, [p], "Rule1")
        assert g.nodes[p].node_type == FormulaType.PREMISE

    def test_add_formula_respects_existing_node_type(self):
        g = FormulaDependencyGraph()
        p = _pred("P")
        q = _pred("Q")
        # Pre-add p as AXIOM
        g.nodes[p] = DependencyNode(formula=p, node_type=FormulaType.AXIOM)
        g.add_formula(q, [p], "Rule1")
        # p should remain AXIOM
        assert g.nodes[p].node_type == FormulaType.AXIOM

    def test_add_formula_invalidates_topo_cache(self):
        g = FormulaDependencyGraph()
        p = _pred("P")
        q = _pred("Q")
        r = _pred("R")
        g.add_formula(q, [p], "R1")
        _ = g.topological_sort()
        assert g._topological_order is not None
        g.add_formula(r, [q], "R2")
        assert g._topological_order is None  # invalidated

    def test_add_proof_proved(self):
        p = _pred("P")
        q = _pred("Q")
        result = _make_proof_result(q, [p])
        g = FormulaDependencyGraph()
        g.add_proof(result)
        assert q in g.nodes
        assert p in g.nodes

    def test_add_proof_unproved_adds_warning_but_works(self):
        p = _pred("P")
        q = _pred("Q")
        step = ProofStep(formula=q, justification="step", rule_name="R", premises=[p])
        result = ProofResult(
            status=ProofStatus.DISPROVED, formula=q,
            proof_steps=[step], time_ms=1.0, method="t", message="no"
        )
        g = FormulaDependencyGraph()
        g.add_proof(result)  # Should not raise, just warn
        assert q in g.nodes

    def test_add_proof_no_steps(self):
        q = _pred("Q")
        result = ProofResult(
            status=ProofStatus.PROVED, formula=q,
            proof_steps=[], time_ms=1.0, method="t", message="ok"
        )
        g = FormulaDependencyGraph()
        g.add_proof(result)
        assert q in g.nodes
        assert len(g.edges) == 0


# ---------------------------------------------------------------------------
# get_dependencies / get_dependents
# ---------------------------------------------------------------------------

class TestGetDependencies:
    def setup_method(self):
        self.p = _pred("P")
        self.q = _pred("Q")
        self.r = _pred("R")
        self.g = FormulaDependencyGraph()
        self.g.add_formula(self.q, [self.p], "R1")
        self.g.add_formula(self.r, [self.q], "R2")

    def test_get_direct_dependencies(self):
        deps = self.g.get_dependencies(self.q)
        assert self.p in deps

    def test_get_dependencies_of_root(self):
        deps = self.g.get_dependencies(self.p)
        assert deps == []

    def test_get_direct_dependents(self):
        deps = self.g.get_dependents(self.p)
        assert self.q in deps

    def test_get_dependents_of_leaf(self):
        deps = self.g.get_dependents(self.r)
        assert deps == []

    def test_get_all_dependencies_transitive(self):
        all_deps = self.g.get_all_dependencies(self.r)
        assert self.p in all_deps
        assert self.q in all_deps
        assert self.r not in all_deps

    def test_get_all_dependencies_excludes_self(self):
        all_deps = self.g.get_all_dependencies(self.q)
        assert self.q not in all_deps

    def test_get_all_dependents_transitive(self):
        all_deps = self.g.get_all_dependents(self.p)
        assert self.q in all_deps
        assert self.r in all_deps
        assert self.p not in all_deps

    def test_get_all_dependents_empty_for_missing_formula(self):
        x = _pred("X")
        result = self.g.get_all_dependents(x)
        assert result == set()

    def test_get_all_dependencies_empty_for_missing_formula(self):
        x = _pred("X")
        result = self.g.get_all_dependencies(x)
        assert result == set()

    def test_get_all_dependencies_diamond_graph_no_duplicates(self):
        # Diamond: p→q, p→r, q→s, r→s — s has two paths to p
        p = _pred("P")
        q = _pred("Q")
        r = _pred("R")
        s = _pred("S")
        g = FormulaDependencyGraph()
        g.add_formula(q, [p], "R1")
        g.add_formula(r, [p], "R2")
        g.add_formula(s, [q, r], "R3")
        all_deps = g.get_all_dependencies(s)
        # p should appear only once even though two paths lead to it
        assert p in all_deps
        assert q in all_deps
        assert r in all_deps
        assert s not in all_deps

    def test_get_all_dependents_diamond_graph_no_duplicates(self):
        # Diamond: p→q, p→r, q→s, r→s — p has two paths to s
        p = _pred("P")
        q = _pred("Q")
        r = _pred("R")
        s = _pred("S")
        g = FormulaDependencyGraph()
        g.add_formula(q, [p], "R1")
        g.add_formula(r, [p], "R2")
        g.add_formula(s, [q, r], "R3")
        all_deps = g.get_all_dependents(p)
        # s should appear only once even though two paths go through it
        assert q in all_deps
        assert r in all_deps
        assert s in all_deps
        assert p not in all_deps


# ---------------------------------------------------------------------------
# Cycle Detection and Topological Sort
# ---------------------------------------------------------------------------

class TestCycleDetectionAndTopologicalSort:
    def test_no_cycles_in_dag(self):
        p = _pred("P")
        q = _pred("Q")
        g = FormulaDependencyGraph()
        g.add_formula(q, [p], "R1")
        cycles = g.detect_cycles()
        assert cycles == []

    def test_detect_simple_cycle(self):
        p = _pred("P")
        q = _pred("Q")
        g = FormulaDependencyGraph()
        g.add_formula(q, [p], "R1")
        g.add_formula(p, [q], "R2")  # creates cycle
        cycles = g.detect_cycles()
        assert len(cycles) >= 1

    def test_topological_sort_two_node_dag(self):
        p = _pred("P")
        q = _pred("Q")
        g = FormulaDependencyGraph()
        g.add_formula(q, [p], "R1")
        order = g.topological_sort()
        assert order.index(p) < order.index(q)

    def test_topological_sort_three_node_chain(self):
        p = _pred("P")
        q = _pred("Q")
        r = _pred("R")
        g = FormulaDependencyGraph()
        g.add_formula(q, [p], "R1")
        g.add_formula(r, [q], "R2")
        order = g.topological_sort()
        assert order.index(p) < order.index(q) < order.index(r)

    def test_topological_sort_raises_on_cycle(self):
        p = _pred("P")
        q = _pred("Q")
        g = FormulaDependencyGraph()
        g.add_formula(q, [p], "R1")
        g.add_formula(p, [q], "R2")
        with pytest.raises(CircularDependencyError):
            g.topological_sort()

    def test_topological_sort_cached(self):
        p = _pred("P")
        q = _pred("Q")
        g = FormulaDependencyGraph()
        g.add_formula(q, [p], "R1")
        order1 = g.topological_sort()
        order2 = g.topological_sort()
        assert order1 is order2  # same object from cache

    def test_topological_sort_empty_graph(self):
        g = FormulaDependencyGraph()
        order = g.topological_sort()
        assert order == []


# ---------------------------------------------------------------------------
# Path Finding
# ---------------------------------------------------------------------------

class TestPathFinding:
    def setup_method(self):
        self.p = _pred("P")
        self.q = _pred("Q")
        self.r = _pred("R")
        self.g = FormulaDependencyGraph()
        self.g.add_formula(self.q, [self.p], "R1")
        self.g.add_formula(self.r, [self.q], "R2")

    def test_find_critical_path_exists(self):
        path = self.g.find_critical_path(self.p, self.r)
        assert path is not None
        assert path[0] == self.p
        assert path[-1] == self.r

    def test_find_critical_path_direct(self):
        path = self.g.find_critical_path(self.p, self.q)
        assert path == [self.p, self.q]

    def test_find_critical_path_not_exists(self):
        path = self.g.find_critical_path(self.r, self.p)  # reverse
        assert path is None

    def test_find_critical_path_start_not_in_graph(self):
        x = _pred("X")
        path = self.g.find_critical_path(x, self.r)
        assert path is None

    def test_find_critical_path_end_not_in_graph(self):
        x = _pred("X")
        path = self.g.find_critical_path(self.p, x)
        assert path is None

    def test_find_all_paths_single_path(self):
        paths = self.g.find_all_paths(self.p, self.r)
        assert len(paths) == 1
        assert paths[0] == [self.p, self.q, self.r]

    def test_find_all_paths_max_length_excludes_long_paths(self):
        # max_length=2: path [p, q] has len=2 (OK), path [p, q, r] has len=3 (>2, excluded)
        paths = self.g.find_all_paths(self.p, self.r, max_length=2)
        assert paths == []

    def test_find_all_paths_max_length_includes_short_paths(self):
        # max_length=3: path [p, q] has len=2 ≤ 3, included
        paths = self.g.find_all_paths(self.p, self.q, max_length=3)
        assert len(paths) == 1

    def test_find_all_paths_multiple_paths(self):
        s = _pred("S")
        # p→r also via s: p→q→r and p→s→r
        self.g.add_formula(self.r, [s], "R3")
        self.g.add_formula(s, [self.p], "R4")
        paths = self.g.find_all_paths(self.p, self.r)
        assert len(paths) >= 2

    def test_find_all_paths_no_path(self):
        paths = self.g.find_all_paths(self.r, self.p)  # reverse
        assert paths == []

    def test_find_all_paths_start_not_in_graph(self):
        x = _pred("X")
        paths = self.g.find_all_paths(x, self.r)
        assert paths == []

    def test_find_all_paths_end_not_in_graph(self):
        x = _pred("X")
        paths = self.g.find_all_paths(self.p, x)
        assert paths == []


# ---------------------------------------------------------------------------
# Unused Axioms and Redundant Formulas
# ---------------------------------------------------------------------------

class TestUnusedAxiomsAndRedundantFormulas:
    def test_find_unused_axioms_all_used(self):
        p = _pred("P")
        q = _pred("Q")
        g = FormulaDependencyGraph()
        g.nodes[p] = DependencyNode(formula=p, node_type=FormulaType.AXIOM)
        g.add_formula(q, [p], "R1")
        unused = g.find_unused_axioms()
        assert p not in unused

    def test_find_unused_axioms_some_unused(self):
        p = _pred("P")
        q = _pred("Q")
        r = _pred("R")
        g = FormulaDependencyGraph()
        g.nodes[p] = DependencyNode(formula=p, node_type=FormulaType.AXIOM)
        g.nodes[r] = DependencyNode(formula=r, node_type=FormulaType.AXIOM)
        g.add_formula(q, [p], "R1")
        unused = g.find_unused_axioms()
        assert r in unused
        assert p not in unused

    def test_find_redundant_formulas(self):
        p = _pred("P")
        q = _pred("Q")
        r = _pred("R")
        g = FormulaDependencyGraph()
        g.add_formula(q, [p], "R1")
        g.add_formula(r, [q], "R2")
        # r depends on q which depends on p → r is redundant with respect to p
        redundant = g.find_redundant_formulas()
        assert len(redundant) >= 1
        # Some pair involving p should be there
        all_first = [pair[0] for pair in redundant]
        assert r in all_first or q in all_first

    def test_find_redundant_formulas_independent(self):
        p = _pred("P")
        q = _pred("Q")
        g = FormulaDependencyGraph()
        g.add_formula(p, [], "R1")
        g.add_formula(q, [], "R2")
        redundant = g.find_redundant_formulas()
        assert redundant == []


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------

class TestGetStatistics:
    def test_empty_graph_stats(self):
        g = FormulaDependencyGraph()
        stats = g.get_statistics()
        assert stats["num_nodes"] == 0
        assert stats["num_edges"] == 0
        assert stats["has_cycles"] is False

    def test_dag_stats(self):
        p = _pred("P")
        q = _pred("Q")
        g = FormulaDependencyGraph()
        g.add_formula(q, [p], "Rule1")
        stats = g.get_statistics()
        assert stats["num_nodes"] == 2
        assert stats["num_edges"] == 1
        assert stats["has_cycles"] is False

    def test_stats_with_kb(self):
        kb = TDFOLKnowledgeBase()
        p = _pred("P")
        kb.add_axiom(p)
        g = FormulaDependencyGraph(kb=kb)
        stats = g.get_statistics()
        assert stats["num_axioms"] == 1
        assert stats["num_theorems"] == 0

    def test_stats_counts_node_types(self):
        p = _pred("P")
        q = _pred("Q")
        g = FormulaDependencyGraph()
        g.add_formula(q, [p], "R1")
        stats = g.get_statistics()
        # p is premise, q is derived
        assert stats["node_types"].get("premise", 0) == 1
        assert stats["node_types"].get("derived", 0) == 1


# ---------------------------------------------------------------------------
# Export Methods
# ---------------------------------------------------------------------------

class TestExportDot:
    def setup_method(self):
        self.p = _pred("P")
        self.q = _pred("Q")
        self.g = FormulaDependencyGraph()
        self.g.add_formula(self.q, [self.p], "Rule1", "justification")

    def test_export_dot_creates_file(self):
        with tempfile.NamedTemporaryFile(suffix=".dot", delete=False) as f:
            path = f.name
        try:
            self.g.export_dot(path)
            assert os.path.exists(path)
            content = Path(path).read_text()
            assert "digraph DependencyGraph" in content
        finally:
            if os.path.exists(path):
                os.unlink(path)

    def test_export_dot_with_clustering(self):
        with tempfile.NamedTemporaryFile(suffix=".dot", delete=False) as f:
            path = f.name
        try:
            self.g.export_dot(path, cluster_by_type=True)
            content = Path(path).read_text()
            assert "subgraph cluster_" in content
        finally:
            if os.path.exists(path):
                os.unlink(path)

    def test_export_dot_without_clustering(self):
        with tempfile.NamedTemporaryFile(suffix=".dot", delete=False) as f:
            path = f.name
        try:
            self.g.export_dot(path, cluster_by_type=False)
            content = Path(path).read_text()
            assert "subgraph cluster_" not in content
        finally:
            if os.path.exists(path):
                os.unlink(path)

    def test_export_dot_with_highlight_path(self):
        with tempfile.NamedTemporaryFile(suffix=".dot", delete=False) as f:
            path = f.name
        try:
            self.g.export_dot(path, highlight_path=[self.p, self.q])
            content = Path(path).read_text()
            assert "penwidth=3" in content
        finally:
            if os.path.exists(path):
                os.unlink(path)

    def test_export_dot_without_labels(self):
        with tempfile.NamedTemporaryFile(suffix=".dot", delete=False) as f:
            path = f.name
        try:
            self.g.export_dot(path, include_labels=False)
            content = Path(path).read_text()
            assert "Rule1" not in content
        finally:
            if os.path.exists(path):
                os.unlink(path)

    def test_export_dot_with_labels(self):
        with tempfile.NamedTemporaryFile(suffix=".dot", delete=False) as f:
            path = f.name
        try:
            self.g.export_dot(path, include_labels=True)
            content = Path(path).read_text()
            assert "Rule1" in content
        finally:
            if os.path.exists(path):
                os.unlink(path)

    def test_export_dot_accepts_path_object(self):
        with tempfile.NamedTemporaryFile(suffix=".dot", delete=False) as f:
            path = Path(f.name)
        try:
            self.g.export_dot(path)
            assert path.exists()
        finally:
            if path.exists():
                path.unlink()

    def test_export_dot_named_node(self):
        p = _pred("P")
        self.g.nodes[p].name = "axiom_p"
        with tempfile.NamedTemporaryFile(suffix=".dot", delete=False) as f:
            path = f.name
        try:
            self.g.export_dot(path)
            content = Path(path).read_text()
            assert "axiom_p" in content
        finally:
            if os.path.exists(path):
                os.unlink(path)


class TestExportJson:
    def setup_method(self):
        self.p = _pred("P")
        self.q = _pred("Q")
        self.g = FormulaDependencyGraph()
        self.g.add_formula(self.q, [self.p], "Rule1")

    def test_to_json_structure(self):
        data = self.g.to_json()
        assert "nodes" in data
        assert "edges" in data
        assert "statistics" in data
        assert len(data["nodes"]) == 2
        assert len(data["edges"]) == 1

    def test_to_json_node_fields(self):
        data = self.g.to_json()
        node = data["nodes"][0]
        assert "id" in node
        assert "formula" in node
        assert "type" in node

    def test_export_json_to_file(self):
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name
        try:
            self.g.export_json(path)
            with open(path) as f:
                loaded = json.load(f)
            assert len(loaded["nodes"]) == 2
        finally:
            if os.path.exists(path):
                os.unlink(path)

    def test_export_json_is_valid_json(self):
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name
        try:
            self.g.export_json(path)
            content = Path(path).read_text()
            parsed = json.loads(content)
            assert isinstance(parsed, dict)
        finally:
            if os.path.exists(path):
                os.unlink(path)


class TestExportAdjacencyMatrix:
    def setup_method(self):
        self.p = _pred("P")
        self.q = _pred("Q")
        self.g = FormulaDependencyGraph()
        self.g.add_formula(self.q, [self.p], "Rule1")

    def test_to_adjacency_matrix_size(self):
        formulas, matrix = self.g.to_adjacency_matrix()
        assert len(formulas) == 2
        assert len(matrix) == 2
        assert len(matrix[0]) == 2

    def test_to_adjacency_matrix_edge_present(self):
        formulas, matrix = self.g.to_adjacency_matrix()
        idx_p = formulas.index(self.p)
        idx_q = formulas.index(self.q)
        assert matrix[idx_p][idx_q] == 1

    def test_to_adjacency_matrix_no_reverse_edge(self):
        formulas, matrix = self.g.to_adjacency_matrix()
        idx_p = formulas.index(self.p)
        idx_q = formulas.index(self.q)
        assert matrix[idx_q][idx_p] == 0

    def test_export_adjacency_matrix_creates_csv(self):
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as f:
            path = f.name
        try:
            self.g.export_adjacency_matrix(path)
            assert os.path.exists(path)
            content = Path(path).read_text()
            assert "," in content
        finally:
            if os.path.exists(path):
                os.unlink(path)

    def test_export_adjacency_matrix_empty_graph(self):
        g = FormulaDependencyGraph()
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as f:
            path = f.name
        try:
            g.export_adjacency_matrix(path)
            content = Path(path).read_text()
            assert content.strip() == ","  # header row with no entries
        finally:
            if os.path.exists(path):
                os.unlink(path)


# ---------------------------------------------------------------------------
# Convenience Functions
# ---------------------------------------------------------------------------

class TestAnalyzeProofDependencies:
    def test_returns_graph(self):
        p = _pred("P")
        q = _pred("Q")
        result = _make_proof_result(q, [p])
        g = analyze_proof_dependencies(result)
        assert isinstance(g, FormulaDependencyGraph)
        assert len(g.nodes) >= 1

    def test_with_output_dir(self):
        p = _pred("P")
        q = _pred("Q")
        result = _make_proof_result(q, [p])
        with tempfile.TemporaryDirectory() as tmpdir:
            g = analyze_proof_dependencies(result, output_dir=tmpdir)
            files = set(os.listdir(tmpdir))
            assert "dependencies.dot" in files
            assert "dependencies.json" in files
            assert "dependencies.csv" in files
        assert isinstance(g, FormulaDependencyGraph)

    def test_without_output_dir(self):
        q = _pred("Q")
        result = ProofResult(
            status=ProofStatus.PROVED, formula=q,
            proof_steps=[], time_ms=1.0, method="t", message="ok"
        )
        g = analyze_proof_dependencies(result)
        assert g is not None


class TestFindProofChain:
    def test_chain_exists(self):
        p = _pred("P")
        q = _pred("Q")
        kb = TDFOLKnowledgeBase()
        kb.add_axiom(p)
        result = _make_proof_result(q, [p])
        chain = find_proof_chain(p, q, kb, [result])
        assert chain is not None
        assert chain[0] == p
        assert chain[-1] == q

    def test_chain_not_exists(self):
        p = _pred("P")
        q = _pred("Q")
        r = _pred("R")
        kb = TDFOLKnowledgeBase()
        kb.add_axiom(p)
        result = _make_proof_result(q, [p])
        chain = find_proof_chain(p, r, kb, [result])
        assert chain is None

    def test_multiple_proof_results(self):
        p = _pred("P")
        q = _pred("Q")
        r = _pred("R")
        kb = TDFOLKnowledgeBase()
        result1 = _make_proof_result(q, [p])
        result2 = _make_proof_result(r, [q])
        chain = find_proof_chain(p, r, kb, [result1, result2])
        assert chain is not None
        assert p in chain
        assert r in chain
