"""
Tests for TDFOL Formula Dependency Graph

Tests cover:
- Dependency extraction from proofs
- DAG construction and validation
- Cycle detection
- Topological sorting
- Critical path finding
- Unused axiom detection
- Redundant formula detection
- GraphViz DOT export
- JSON export
- Adjacency matrix export
- Knowledge base integration
"""

import json
import tempfile
from pathlib import Path
from typing import List

import pytest

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
from ipfs_datasets_py.logic.TDFOL.tdfol_core import (
    BinaryFormula,
    LogicOperator,
    Predicate,
    TDFOLKnowledgeBase,
    Variable,
    create_implication,
)
from ipfs_datasets_py.logic.TDFOL.tdfol_prover import ProofResult, ProofStatus, ProofStep


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def simple_formulas():
    """Create simple test formulas."""
    # GIVEN: Basic predicates for testing
    p = Predicate("P", ())
    q = Predicate("Q", ())
    r = Predicate("R", ())
    return p, q, r


@pytest.fixture
def implication_formulas():
    """Create implication formulas for testing."""
    # GIVEN: P(x), Q(x), P(x) → Q(x)
    x = Variable("x")
    p = Predicate("P", (x,))
    q = Predicate("Q", (x,))
    p_implies_q = create_implication(p, q)
    return p, q, p_implies_q


@pytest.fixture
def simple_kb(simple_formulas):
    """Create a simple knowledge base."""
    # GIVEN: Knowledge base with axioms and theorems
    p, q, r = simple_formulas
    kb = TDFOLKnowledgeBase()
    kb.add_axiom(p, "axiom_p")
    kb.add_axiom(q, "axiom_q")
    kb.add_theorem(r, "theorem_r")
    return kb


@pytest.fixture
def linear_proof_result(simple_formulas):
    """Create a linear proof result: P → Q → R."""
    # GIVEN: Linear proof chain P → Q → R
    p, q, r = simple_formulas
    
    step1 = ProofStep(
        formula=p,
        justification="Axiom",
        rule_name="Axiom",
        premises=[]
    )
    
    step2 = ProofStep(
        formula=q,
        justification="Modus Ponens",
        rule_name="ModusPonens",
        premises=[p]
    )
    
    step3 = ProofStep(
        formula=r,
        justification="Modus Ponens",
        rule_name="ModusPonens",
        premises=[q]
    )
    
    return ProofResult(
        status=ProofStatus.PROVED,
        formula=r,
        proof_steps=[step1, step2, step3],
        time_ms=10.0,
        method="forward_chaining"
    )


@pytest.fixture
def branching_proof_result(simple_formulas):
    """Create a branching proof result: P, Q → R."""
    # GIVEN: Branching proof where R depends on both P and Q
    p, q, r = simple_formulas
    
    step1 = ProofStep(
        formula=p,
        justification="Axiom",
        rule_name="Axiom",
        premises=[]
    )
    
    step2 = ProofStep(
        formula=q,
        justification="Axiom",
        rule_name="Axiom",
        premises=[]
    )
    
    step3 = ProofStep(
        formula=r,
        justification="Conjunction Introduction",
        rule_name="ConjunctionIntro",
        premises=[p, q]
    )
    
    return ProofResult(
        status=ProofStatus.PROVED,
        formula=r,
        proof_steps=[step1, step2, step3],
        time_ms=15.0,
        method="forward_chaining"
    )


# ============================================================================
# Dependency Node and Edge Tests
# ============================================================================


def test_dependency_node_creation(simple_formulas):
    """Test creating dependency nodes."""
    # GIVEN: A formula
    p, _, _ = simple_formulas
    
    # WHEN: Creating a dependency node
    node = DependencyNode(
        formula=p,
        node_type=FormulaType.AXIOM,
        name="axiom_p"
    )
    
    # THEN: Node has correct attributes
    assert node.formula == p
    assert node.node_type == FormulaType.AXIOM
    assert node.name == "axiom_p"
    assert isinstance(node.metadata, dict)


def test_dependency_node_hash(simple_formulas):
    """Test dependency node hashing."""
    # GIVEN: Two nodes with the same formula
    p, _, _ = simple_formulas
    node1 = DependencyNode(formula=p, node_type=FormulaType.AXIOM)
    node2 = DependencyNode(formula=p, node_type=FormulaType.THEOREM)
    
    # WHEN: Using nodes in a set
    node_set = {node1, node2}
    
    # THEN: Only one node is stored (same formula)
    assert len(node_set) == 1


def test_dependency_edge_creation(simple_formulas):
    """Test creating dependency edges."""
    # GIVEN: Two formulas with dependency
    p, q, _ = simple_formulas
    node_p = DependencyNode(formula=p, node_type=FormulaType.AXIOM)
    node_q = DependencyNode(formula=q, node_type=FormulaType.DERIVED)
    
    # WHEN: Creating an edge
    edge = DependencyEdge(
        source=node_p,
        target=node_q,
        rule_name="ModusPonens",
        justification="From P derive Q"
    )
    
    # THEN: Edge has correct attributes
    assert edge.source == node_p
    assert edge.target == node_q
    assert edge.rule_name == "ModusPonens"
    assert edge.edge_type == DependencyType.DIRECT


# ============================================================================
# Graph Construction Tests
# ============================================================================


def test_empty_graph_creation():
    """Test creating an empty dependency graph."""
    # GIVEN: No inputs
    # WHEN: Creating an empty graph
    graph = FormulaDependencyGraph()
    
    # THEN: Graph is empty
    assert len(graph.nodes) == 0
    assert len(graph.edges) == 0
    assert graph._topological_order is None


def test_graph_from_kb(simple_kb, simple_formulas):
    """Test creating graph from knowledge base."""
    # GIVEN: A knowledge base with axioms and theorems
    # WHEN: Creating graph from KB
    graph = FormulaDependencyGraph(kb=simple_kb)
    
    # THEN: Graph contains all KB formulas
    assert len(graph.nodes) == 3
    
    p, q, r = simple_formulas
    assert p in graph.nodes
    assert q in graph.nodes
    assert r in graph.nodes
    
    assert graph.nodes[p].node_type == FormulaType.AXIOM
    assert graph.nodes[q].node_type == FormulaType.AXIOM
    assert graph.nodes[r].node_type == FormulaType.THEOREM


def test_graph_from_proof(linear_proof_result, simple_formulas):
    """Test creating graph from proof result."""
    # GIVEN: A linear proof result
    # WHEN: Creating graph from proof
    graph = FormulaDependencyGraph(proof_result=linear_proof_result)
    
    # THEN: Graph contains proof steps
    p, q, r = simple_formulas
    assert p in graph.nodes
    assert q in graph.nodes
    assert r in graph.nodes
    
    # Check dependencies
    assert q in graph.get_dependents(p)
    assert r in graph.get_dependents(q)


def test_add_formula_manually(simple_formulas):
    """Test adding formulas manually."""
    # GIVEN: An empty graph and formulas
    graph = FormulaDependencyGraph()
    p, q, r = simple_formulas
    
    # WHEN: Adding formulas with dependencies
    graph.add_formula(p, [], "Axiom", node_type=FormulaType.AXIOM)
    graph.add_formula(q, [p], "ModusPonens", "From P")
    graph.add_formula(r, [q], "ModusPonens", "From Q")
    
    # THEN: Graph contains formulas and edges
    assert len(graph.nodes) == 3
    assert len(graph.edges) == 2
    
    assert q in graph.get_dependents(p)
    assert r in graph.get_dependents(q)


# ============================================================================
# Dependency Query Tests
# ============================================================================


def test_get_dependencies(linear_proof_result, simple_formulas):
    """Test getting direct dependencies."""
    # GIVEN: A linear proof graph
    graph = FormulaDependencyGraph(proof_result=linear_proof_result)
    p, q, r = simple_formulas
    
    # WHEN: Getting dependencies
    p_deps = graph.get_dependencies(p)
    q_deps = graph.get_dependencies(q)
    r_deps = graph.get_dependencies(r)
    
    # THEN: Dependencies are correct
    assert len(p_deps) == 0  # P has no dependencies (axiom)
    assert p in q_deps       # Q depends on P
    assert q in r_deps       # R depends on Q


def test_get_dependents(linear_proof_result, simple_formulas):
    """Test getting dependents."""
    # GIVEN: A linear proof graph
    graph = FormulaDependencyGraph(proof_result=linear_proof_result)
    p, q, r = simple_formulas
    
    # WHEN: Getting dependents
    p_deps = graph.get_dependents(p)
    q_deps = graph.get_dependents(q)
    r_deps = graph.get_dependents(r)
    
    # THEN: Dependents are correct
    assert q in p_deps       # P is used to derive Q
    assert r in q_deps       # Q is used to derive R
    assert len(r_deps) == 0  # R has no dependents (final goal)


def test_get_all_dependencies(linear_proof_result, simple_formulas):
    """Test getting transitive dependencies."""
    # GIVEN: A linear proof graph P → Q → R
    graph = FormulaDependencyGraph(proof_result=linear_proof_result)
    p, q, r = simple_formulas
    
    # WHEN: Getting all dependencies of R
    r_all_deps = graph.get_all_dependencies(r)
    
    # THEN: R depends on both P and Q transitively
    assert p in r_all_deps
    assert q in r_all_deps
    assert len(r_all_deps) == 2


def test_get_all_dependents(linear_proof_result, simple_formulas):
    """Test getting transitive dependents."""
    # GIVEN: A linear proof graph P → Q → R
    graph = FormulaDependencyGraph(proof_result=linear_proof_result)
    p, q, r = simple_formulas
    
    # WHEN: Getting all dependents of P
    p_all_deps = graph.get_all_dependents(p)
    
    # THEN: P is used to derive both Q and R transitively
    assert q in p_all_deps
    assert r in p_all_deps
    assert len(p_all_deps) == 2


# ============================================================================
# Cycle Detection Tests
# ============================================================================


def test_detect_cycles_acyclic(linear_proof_result):
    """Test cycle detection on acyclic graph."""
    # GIVEN: A linear proof graph (acyclic)
    graph = FormulaDependencyGraph(proof_result=linear_proof_result)
    
    # WHEN: Detecting cycles
    cycles = graph.detect_cycles()
    
    # THEN: No cycles found
    assert len(cycles) == 0


def test_detect_cycles_with_cycle(simple_formulas):
    """Test cycle detection with circular dependency."""
    # GIVEN: A graph with a cycle P → Q → P
    graph = FormulaDependencyGraph()
    p, q, _ = simple_formulas
    
    graph.add_formula(q, [p], "Rule1")
    graph.add_formula(p, [q], "Rule2")  # Creates cycle
    
    # WHEN: Detecting cycles
    cycles = graph.detect_cycles()
    
    # THEN: Cycle is detected
    assert len(cycles) > 0


# ============================================================================
# Topological Sort Tests
# ============================================================================


def test_topological_sort_linear(linear_proof_result, simple_formulas):
    """Test topological sort on linear graph."""
    # GIVEN: A linear proof graph P → Q → R
    graph = FormulaDependencyGraph(proof_result=linear_proof_result)
    p, q, r = simple_formulas
    
    # WHEN: Computing topological order
    order = graph.topological_sort()
    
    # THEN: Order respects dependencies
    assert order.index(p) < order.index(q)
    assert order.index(q) < order.index(r)


def test_topological_sort_branching(branching_proof_result, simple_formulas):
    """Test topological sort on branching graph."""
    # GIVEN: A branching proof graph P, Q → R
    graph = FormulaDependencyGraph(proof_result=branching_proof_result)
    p, q, r = simple_formulas
    
    # WHEN: Computing topological order
    order = graph.topological_sort()
    
    # THEN: Dependencies come before dependents
    assert order.index(p) < order.index(r)
    assert order.index(q) < order.index(r)


def test_topological_sort_with_cycle(simple_formulas):
    """Test topological sort raises error on cycle."""
    # GIVEN: A graph with a cycle
    graph = FormulaDependencyGraph()
    p, q, _ = simple_formulas
    
    graph.add_formula(q, [p], "Rule1")
    graph.add_formula(p, [q], "Rule2")
    
    # WHEN/THEN: Topological sort raises CircularDependencyError
    with pytest.raises(CircularDependencyError):
        graph.topological_sort()


def test_topological_sort_caching(linear_proof_result):
    """Test topological sort result is cached."""
    # GIVEN: A graph
    graph = FormulaDependencyGraph(proof_result=linear_proof_result)
    
    # WHEN: Computing topological sort twice
    order1 = graph.topological_sort()
    order2 = graph.topological_sort()
    
    # THEN: Same object is returned (cached)
    assert order1 is order2


# ============================================================================
# Critical Path Tests
# ============================================================================


def test_find_critical_path_linear(linear_proof_result, simple_formulas):
    """Test finding critical path in linear graph."""
    # GIVEN: A linear proof graph P → Q → R
    graph = FormulaDependencyGraph(proof_result=linear_proof_result)
    p, q, r = simple_formulas
    
    # WHEN: Finding path from P to R
    path = graph.find_critical_path(p, r)
    
    # THEN: Path is [P, Q, R]
    assert path is not None
    assert path == [p, q, r]


def test_find_critical_path_branching(branching_proof_result, simple_formulas):
    """Test finding critical path in branching graph."""
    # GIVEN: A branching proof graph P, Q → R
    graph = FormulaDependencyGraph(proof_result=branching_proof_result)
    p, q, r = simple_formulas
    
    # WHEN: Finding path from P to R
    path = graph.find_critical_path(p, r)
    
    # THEN: Path exists (P → R)
    assert path is not None
    assert p in path
    assert r in path


def test_find_critical_path_no_path(linear_proof_result, simple_formulas):
    """Test finding path when no path exists."""
    # GIVEN: A linear graph P → Q → R
    graph = FormulaDependencyGraph(proof_result=linear_proof_result)
    p, _, r = simple_formulas
    
    # WHEN: Finding path from R to P (backwards)
    path = graph.find_critical_path(r, p)
    
    # THEN: No path found
    assert path is None


def test_find_all_paths(simple_formulas):
    """Test finding all paths between formulas."""
    # GIVEN: A graph with multiple paths P → Q → R and P → R
    graph = FormulaDependencyGraph()
    p, q, r = simple_formulas
    
    graph.add_formula(q, [p], "Rule1")
    graph.add_formula(r, [q], "Rule2")
    graph.add_formula(r, [p], "Rule3")  # Alternative path
    
    # WHEN: Finding all paths from P to R
    paths = graph.find_all_paths(p, r)
    
    # THEN: Both paths are found
    assert len(paths) == 2
    assert [p, r] in paths or [p, q, r] in paths


# ============================================================================
# Analysis Tests
# ============================================================================


def test_find_unused_axioms(simple_kb, simple_formulas):
    """Test finding unused axioms."""
    # GIVEN: A KB with axioms but no derivations
    graph = FormulaDependencyGraph(kb=simple_kb)
    p, q, _ = simple_formulas
    
    # WHEN: Finding unused axioms
    unused = graph.find_unused_axioms()
    
    # THEN: All axioms are unused
    assert p in unused
    assert q in unused


def test_find_unused_axioms_with_derivations(simple_kb, simple_formulas):
    """Test finding unused axioms when some are used."""
    # GIVEN: A graph with one axiom used
    graph = FormulaDependencyGraph(kb=simple_kb)
    p, q, r = simple_formulas
    
    # Add derivation using P
    graph.add_formula(r, [p], "SomeRule")
    
    # WHEN: Finding unused axioms
    unused = graph.find_unused_axioms()
    
    # THEN: Only Q is unused
    assert q in unused
    assert p not in unused


def test_find_redundant_formulas(simple_formulas):
    """Test finding redundant formulas."""
    # GIVEN: A graph where Q depends on P
    graph = FormulaDependencyGraph()
    p, q, r = simple_formulas
    
    graph.add_formula(p, [], "Axiom", node_type=FormulaType.AXIOM)
    graph.add_formula(q, [p], "Rule1")
    graph.add_formula(r, [], "Axiom", node_type=FormulaType.AXIOM)
    
    # WHEN: Finding redundant formulas
    redundant = graph.find_redundant_formulas()
    
    # THEN: Q is redundant (depends on P)
    assert (q, p) in redundant


def test_get_statistics(linear_proof_result):
    """Test getting graph statistics."""
    # GIVEN: A proof graph
    graph = FormulaDependencyGraph(proof_result=linear_proof_result)
    
    # WHEN: Getting statistics
    stats = graph.get_statistics()
    
    # THEN: Statistics are correct
    assert stats["num_nodes"] == 3
    assert stats["num_edges"] == 2
    assert stats["has_cycles"] is False
    assert "node_types" in stats
    assert "edge_types" in stats


# ============================================================================
# Export Tests
# ============================================================================


def test_export_dot(linear_proof_result):
    """Test exporting to DOT format."""
    # GIVEN: A proof graph
    graph = FormulaDependencyGraph(proof_result=linear_proof_result)
    
    # WHEN: Exporting to DOT
    with tempfile.TemporaryDirectory() as tmpdir:
        output_path = Path(tmpdir) / "graph.dot"
        graph.export_dot(output_path)
        
        # THEN: DOT file is created
        assert output_path.exists()
        content = output_path.read_text()
        assert "digraph DependencyGraph" in content
        assert "rankdir=TB" in content


def test_export_dot_with_highlight(linear_proof_result, simple_formulas):
    """Test exporting DOT with highlighted path."""
    # GIVEN: A proof graph
    graph = FormulaDependencyGraph(proof_result=linear_proof_result)
    p, q, r = simple_formulas
    
    # WHEN: Exporting with highlighted path
    with tempfile.TemporaryDirectory() as tmpdir:
        output_path = Path(tmpdir) / "graph.dot"
        graph.export_dot(output_path, highlight_path=[p, q, r])
        
        # THEN: DOT file contains highlighting
        content = output_path.read_text()
        assert "color=red" in content


def test_to_json(linear_proof_result):
    """Test converting to JSON format."""
    # GIVEN: A proof graph
    graph = FormulaDependencyGraph(proof_result=linear_proof_result)
    
    # WHEN: Converting to JSON
    data = graph.to_json()
    
    # THEN: JSON structure is correct
    assert "nodes" in data
    assert "edges" in data
    assert "statistics" in data
    assert len(data["nodes"]) == 3
    assert len(data["edges"]) == 2


def test_export_json(linear_proof_result):
    """Test exporting to JSON file."""
    # GIVEN: A proof graph
    graph = FormulaDependencyGraph(proof_result=linear_proof_result)
    
    # WHEN: Exporting to JSON file
    with tempfile.TemporaryDirectory() as tmpdir:
        output_path = Path(tmpdir) / "graph.json"
        graph.export_json(output_path)
        
        # THEN: JSON file is created and valid
        assert output_path.exists()
        data = json.loads(output_path.read_text())
        assert "nodes" in data
        assert "edges" in data


def test_to_adjacency_matrix(linear_proof_result, simple_formulas):
    """Test converting to adjacency matrix."""
    # GIVEN: A linear proof graph P → Q → R
    graph = FormulaDependencyGraph(proof_result=linear_proof_result)
    p, q, r = simple_formulas
    
    # WHEN: Converting to adjacency matrix
    formulas, matrix = graph.to_adjacency_matrix()
    
    # THEN: Matrix is correct
    assert len(formulas) == 3
    assert len(matrix) == 3
    assert all(len(row) == 3 for row in matrix)
    
    # Find indices
    p_idx = formulas.index(p)
    q_idx = formulas.index(q)
    r_idx = formulas.index(r)
    
    # Check edges
    assert matrix[p_idx][q_idx] == 1  # P → Q
    assert matrix[q_idx][r_idx] == 1  # Q → R
    assert matrix[p_idx][r_idx] == 0  # No direct P → R


def test_export_adjacency_matrix(linear_proof_result):
    """Test exporting adjacency matrix to CSV."""
    # GIVEN: A proof graph
    graph = FormulaDependencyGraph(proof_result=linear_proof_result)
    
    # WHEN: Exporting to CSV
    with tempfile.TemporaryDirectory() as tmpdir:
        output_path = Path(tmpdir) / "matrix.csv"
        graph.export_adjacency_matrix(output_path)
        
        # THEN: CSV file is created
        assert output_path.exists()
        content = output_path.read_text()
        lines = content.strip().split('\n')
        assert len(lines) == 4  # Header + 3 rows


# ============================================================================
# Convenience Function Tests
# ============================================================================


def test_analyze_proof_dependencies(linear_proof_result):
    """Test convenience function for proof analysis."""
    # GIVEN: A proof result
    # WHEN: Analyzing dependencies
    with tempfile.TemporaryDirectory() as tmpdir:
        output_dir = Path(tmpdir)
        graph = analyze_proof_dependencies(linear_proof_result, output_dir)
        
        # THEN: Graph is created and files are exported
        assert isinstance(graph, FormulaDependencyGraph)
        assert (output_dir / "dependencies.dot").exists()
        assert (output_dir / "dependencies.json").exists()
        assert (output_dir / "dependencies.csv").exists()


def test_find_proof_chain(simple_kb, simple_formulas):
    """Test finding proof chain between formulas."""
    # GIVEN: KB and proof results
    p, q, r = simple_formulas
    
    # Create proof results
    proof1 = ProofResult(
        status=ProofStatus.PROVED,
        formula=q,
        proof_steps=[
            ProofStep(p, "Axiom", "Axiom", []),
            ProofStep(q, "From P", "Rule1", [p])
        ]
    )
    
    proof2 = ProofResult(
        status=ProofStatus.PROVED,
        formula=r,
        proof_steps=[
            ProofStep(q, "From previous", "Previous", []),
            ProofStep(r, "From Q", "Rule2", [q])
        ]
    )
    
    # WHEN: Finding proof chain
    chain = find_proof_chain(p, r, simple_kb, [proof1, proof2])
    
    # THEN: Chain is found
    assert chain is not None
    assert p in chain
    assert r in chain


# ============================================================================
# Integration Tests
# ============================================================================


def test_complex_proof_graph(simple_formulas):
    """Test complex graph with multiple branches and merges."""
    # GIVEN: Complex proof structure
    #     P → Q ↘
    #             → R → S
    #     T → U ↗
    graph = FormulaDependencyGraph()
    p, q, r = simple_formulas
    
    # Create additional formulas
    s = Predicate("S", ())
    t = Predicate("T", ())
    u = Predicate("U", ())
    
    # Build graph
    graph.add_formula(p, [], "Axiom", node_type=FormulaType.AXIOM)
    graph.add_formula(t, [], "Axiom", node_type=FormulaType.AXIOM)
    graph.add_formula(q, [p], "Rule1")
    graph.add_formula(u, [t], "Rule2")
    graph.add_formula(r, [q, u], "Rule3")  # Merge point
    graph.add_formula(s, [r], "Rule4")
    
    # WHEN: Analyzing graph
    stats = graph.get_statistics()
    order = graph.topological_sort()
    path_p_s = graph.find_critical_path(p, s)
    path_t_s = graph.find_critical_path(t, s)
    
    # THEN: Analysis is correct
    assert stats["num_nodes"] == 6
    assert len(order) == 6
    assert path_p_s is not None
    assert path_t_s is not None
    assert p in path_p_s
    assert t in path_t_s
    assert s in path_p_s
    assert s in path_t_s


def test_multiple_proofs_integration(simple_kb, simple_formulas):
    """Test adding multiple proofs to same graph."""
    # GIVEN: Multiple proof results
    p, q, r = simple_formulas
    
    proof1 = ProofResult(
        status=ProofStatus.PROVED,
        formula=q,
        proof_steps=[
            ProofStep(p, "Axiom", "Axiom", []),
            ProofStep(q, "From P", "Rule1", [p])
        ]
    )
    
    proof2 = ProofResult(
        status=ProofStatus.PROVED,
        formula=r,
        proof_steps=[
            ProofStep(q, "Previous", "Previous", []),
            ProofStep(r, "From Q", "Rule2", [q])
        ]
    )
    
    # WHEN: Adding both proofs
    graph = FormulaDependencyGraph(kb=simple_kb)
    graph.add_proof(proof1)
    graph.add_proof(proof2)
    
    # THEN: Graph contains all formulas and relationships
    assert len(graph.nodes) >= 3
    assert q in graph.get_dependents(p)
    assert r in graph.get_dependents(q)


def test_export_all_formats(linear_proof_result):
    """Test exporting in all supported formats."""
    # GIVEN: A proof graph
    graph = FormulaDependencyGraph(proof_result=linear_proof_result)
    
    # WHEN: Exporting in all formats
    with tempfile.TemporaryDirectory() as tmpdir:
        tmppath = Path(tmpdir)
        
        graph.export_dot(tmppath / "graph.dot")
        graph.export_json(tmppath / "graph.json")
        graph.export_adjacency_matrix(tmppath / "matrix.csv")
        
        # THEN: All files are created
        assert (tmppath / "graph.dot").exists()
        assert (tmppath / "graph.json").exists()
        assert (tmppath / "matrix.csv").exists()
        
        # Verify content is valid
        dot_content = (tmppath / "graph.dot").read_text()
        assert "digraph" in dot_content
        
        json_data = json.loads((tmppath / "graph.json").read_text())
        assert "nodes" in json_data
        
        csv_content = (tmppath / "matrix.csv").read_text()
        assert len(csv_content.split('\n')) > 1
