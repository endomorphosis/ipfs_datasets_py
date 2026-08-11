"""Contract tests for bounded typed-symbol-graph resolution and traversal."""

from __future__ import annotations

from dataclasses import replace

from ipfs_datasets_py.logic.software_contracts.semantic_index.python_analysis import analyze_python_source
from ipfs_datasets_py.logic.software_contracts.semantic_index.models import DependencyEdge, RelationType, SymbolKind
from ipfs_datasets_py.logic.software_contracts.semantic_index.symbol_graph import build_symbol_graph


def _facts(source: str):
    analysis = analyze_python_source(source, "pkg/example.py", "repo:example")
    return analysis.symbol_records, analysis.edges


def test_resolves_unique_lexical_target_with_full_edge_provenance() -> None:
    symbols, edges = _facts("""
def target(): pass
def caller(): return target()
""")
    graph = build_symbol_graph(symbols, edges=edges)
    caller = next(item for item in symbols if item.qualified_name.endswith(".caller"))
    target = next(item for item in symbols if item.qualified_name.endswith(".target"))
    edge = next(item for item in graph.outgoing(caller.stable_id) if item.relation == "calls")
    assert edge.target_id == target.stable_id
    assert edge.metadata["resolution"] == "definite"
    assert edge.span is not None
    assert edge.extraction_method and edge.extractor_version and edge.confidence == "conservative"


def test_ambiguity_and_unresolved_targets_are_retained_and_lower_confidence() -> None:
    symbols, _ = _facts("def caller(): pass\ndef spare(): pass\n")
    source = next(item for item in symbols if item.qualified_name.endswith(".caller"))
    # Semantic inventories can contain finite aliases from independently
    # declared test/schema projections; their shared qualified target is a
    # may-set, never an arbitrary selected declaration.
    candidates = tuple(replace(item, qualified_name="pkg.example.thing") for item in symbols if item.qualified_name.endswith((".caller", ".spare"))) + tuple(item for item in symbols if item.kind == "module")
    graph = build_symbol_graph(candidates, edges=(
        DependencyEdge(source.stable_id, "lexical:thing", RelationType.CALLS, "lexical", "exact", "1"),
        DependencyEdge(source.stable_id, "lexical:missing", RelationType.CALLS, "lexical", "exact", "1"),
    ))
    outgoing = graph.outgoing(source.stable_id)
    assert any(item.target_id == "lexical:missing" and item.metadata["resolution"] == "unresolved" and item.confidence == "conservative" for item in outgoing)
    may_edges = [item for item in outgoing if item.metadata.get("resolution") == "finite_may"]
    assert len(may_edges) == 2 and {item.confidence for item in may_edges} == {"conservative"}


def test_traversal_is_deterministic_bounded_and_cycle_safe() -> None:
    symbols, edges = _facts("""
def a(): return b()
def b(): return a()
def test_b(): return b()
""")
    # Repository assembly overlays pytest facts and therefore identifies the
    # test symbol independently from Python's general function extraction.
    symbols = tuple(replace(item, kind=SymbolKind.TEST) if item.qualified_name.endswith(".test_b") else item for item in symbols)
    graph = build_symbol_graph(symbols, edges=edges)
    by_name = {item.qualified_name.rsplit(".", 1)[-1]: item.stable_id for item in symbols}
    assert graph.traverse(by_name["a"], max_depth=10) == graph.traverse(by_name["a"], max_depth=10)
    assert len(graph.traverse(by_name["a"], max_depth=10, max_nodes=2)) == 2
    tested = graph.outgoing(by_name["b"], relation=RelationType.TESTED_BY)
    assert tested and tested[0].target_id == by_name["test_b"]


def test_static_protocol_inheritance_emits_implements_edge() -> None:
    symbols, edges = _facts("""
class Interface(Protocol): pass
class Concrete(Interface): pass
""")
    graph = build_symbol_graph(symbols, edges=edges)
    concrete = next(item for item in symbols if item.qualified_name.endswith(".Concrete"))
    interface = next(item for item in symbols if item.qualified_name.endswith(".Interface"))
    implements = graph.outgoing(concrete.stable_id, relation=RelationType.IMPLEMENTS)
    assert len(implements) == 1
    assert implements[0].target_id == interface.stable_id
    assert implements[0].confidence == "exact"
