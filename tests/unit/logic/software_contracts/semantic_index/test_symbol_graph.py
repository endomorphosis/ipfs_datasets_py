"""Contract tests for bounded typed-symbol-graph resolution and traversal."""

from __future__ import annotations

from ipfs_datasets_py.logic.software_contracts.semantic_index.identity import (
    stable_symbol_id,
    symbol_version_cid,
)
from ipfs_datasets_py.logic.software_contracts.semantic_index.python_analysis import analyze_python_source
from ipfs_datasets_py.logic.software_contracts.semantic_index.models import (
    DependencyEdge,
    RelationType,
    SymbolKind,
    SymbolRecord,
)
from ipfs_datasets_py.logic.software_contracts.semantic_index.symbol_graph import (
    STATUS_DEFINITE,
    STATUS_FINITE_MAY,
    STATUS_UNRESOLVED,
    build_symbol_graph,
)


def _facts(source: str):
    analysis = analyze_python_source(source, "pkg/example.py", "repo:example")
    return analysis.symbol_records, analysis.edges


def _reissue(symbol: SymbolRecord, *, kind: SymbolKind | None = None, qualified_name: str | None = None) -> SymbolRecord:
    """Recompute a verified SymbolRecord when identity fields change."""
    kind_value = kind if kind is not None else SymbolKind(symbol.kind)
    qn = qualified_name if qualified_name is not None else symbol.qualified_name
    stable = stable_symbol_id(
        symbol.repository_id, symbol.language, symbol.module_path, qn, kind_value, symbol.namespace,
    )
    # Thaw frozen fields for version construction.
    def thaw(value):
        if isinstance(value, dict) or hasattr(value, "items") and not isinstance(value, (str, bytes)):
            try:
                return {k: thaw(v) for k, v in dict(value).items()}
            except Exception:
                pass
        if isinstance(value, tuple):
            return [thaw(v) for v in value]
        return value

    signature = thaw(symbol.signature)
    annotations = thaw(symbol.annotations)
    metadata = thaw(symbol.metadata)
    normalized = thaw(symbol.normalized_ast)
    version = symbol_version_cid(
        stable, normalized, signature, tuple(symbol.decorators), annotations,
        extractor_name=symbol.extractor_name, extractor_version=symbol.extractor_version,
        property_role=symbol.property_role,
    )
    return SymbolRecord(
        stable, version, symbol.repository_id, symbol.language, symbol.module_path,
        qn, kind_value, symbol.namespace, symbol.source_cid, symbol.span, symbol.confidence,
        signature, tuple(symbol.decorators), annotations, metadata, normalized,
        symbol.extractor_name, symbol.extractor_version, symbol.property_role,
    )


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
    assert edge.metadata["resolution"] == STATUS_DEFINITE
    assert edge.span is not None
    assert edge.extraction_method and edge.extractor_version
    assert edge.confidence in {"exact", "conservative"}


def test_ambiguity_and_unresolved_targets_are_retained_and_lower_confidence() -> None:
    symbols, _ = _facts("def caller(): pass\ndef spare(): pass\n")
    source = next(item for item in symbols if item.qualified_name.endswith(".caller"))
    # Two verified symbols can share a bare qualified_name only when their
    # module paths differ; both then match lexical:thing as a finite may-set.
    def with_path_and_qn(item: SymbolRecord, module_path: str, qn: str) -> SymbolRecord:
        kind_value = SymbolKind(item.kind)
        stable = stable_symbol_id(
            item.repository_id, item.language, module_path, qn, kind_value, item.namespace,
        )

        def thaw(value):
            if hasattr(value, "items") and not isinstance(value, (str, bytes)):
                try:
                    return {k: thaw(v) for k, v in dict(value).items()}
                except Exception:
                    return value
            if isinstance(value, tuple):
                return [thaw(v) for v in value]
            return value

        signature = thaw(item.signature)
        annotations = thaw(item.annotations)
        metadata = thaw(item.metadata)
        normalized = thaw(item.normalized_ast)
        version = symbol_version_cid(
            stable, normalized, signature, tuple(item.decorators), annotations,
            extractor_name=item.extractor_name, extractor_version=item.extractor_version,
            property_role=item.property_role,
        )
        return SymbolRecord(
            stable, version, item.repository_id, item.language, module_path, qn, kind_value,
            item.namespace, item.source_cid, item.span, item.confidence, signature,
            tuple(item.decorators), annotations, metadata, normalized,
            item.extractor_name, item.extractor_version, item.property_role,
        )

    base = [item for item in symbols if item.qualified_name.endswith((".caller", ".spare"))]
    aliases = (
        with_path_and_qn(base[0], "pkg/one.py", "thing"),
        with_path_and_qn(base[1], "pkg/two.py", "thing"),
    )
    modules = tuple(item for item in symbols if item.kind == "module")
    graph = build_symbol_graph(aliases + modules, edges=(
        DependencyEdge(source.stable_id, "lexical:thing", RelationType.CALLS, "lexical", "exact", "1"),
        DependencyEdge(source.stable_id, "lexical:missing", RelationType.CALLS, "lexical", "exact", "1"),
    ))
    outgoing = graph.outgoing(source.stable_id)
    assert any(
        item.target_id == "lexical:missing"
        and item.metadata["resolution"] == STATUS_UNRESOLVED
        and item.confidence == "conservative"
        for item in outgoing
    )
    may_edges = [item for item in outgoing if item.metadata.get("resolution") == STATUS_FINITE_MAY]
    assert len(may_edges) == 2 and {item.confidence for item in may_edges} == {"conservative"}


def test_traversal_is_deterministic_bounded_and_cycle_safe() -> None:
    symbols, edges = _facts("""
def a(): return b()
def b(): return a()
def test_b(): return b()
""")
    # Reissue the test binding as kind=test so tested_by derivation fires.
    symbols = tuple(
        _reissue(item, kind=SymbolKind.TEST) if item.qualified_name.endswith(".test_b") else item
        for item in symbols
    )
    # Remap edges that sourced from the old function identity onto the test identity.
    old_test = next(item for item in _facts("""
def a(): return b()
def b(): return a()
def test_b(): return b()
""")[0] if item.qualified_name.endswith(".test_b"))
    new_test = next(item for item in symbols if item.qualified_name.endswith(".test_b"))
    remapped = []
    for edge in edges:
        source = new_test.stable_id if edge.source_id == old_test.stable_id else edge.source_id
        target = new_test.stable_id if edge.target_id == old_test.stable_id else edge.target_id
        remapped.append(DependencyEdge(
            source, target, edge.relation, edge.extraction_method, edge.confidence,
            edge.extractor_version, edge.span, edge.metadata,
        ))
    graph = build_symbol_graph(symbols, edges=remapped)
    by_name = {item.qualified_name.rsplit(".", 1)[-1]: item.stable_id for item in symbols}
    assert graph.traverse(by_name["a"], max_depth=10) == graph.traverse(by_name["a"], max_depth=10)
    assert len(graph.traverse(by_name["a"], max_depth=10, max_nodes=2)) == 2
    tested = graph.outgoing(by_name["b"], relation=RelationType.TESTED_BY)
    assert tested and tested[0].target_id == by_name["test_b"]
    assert tested[0].metadata.get("resolution") == STATUS_DEFINITE


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


def test_fixture_lexical_targets_resolve_via_fixture_name_metadata() -> None:
    symbols, _ = _facts("""
def database():
    return 1

def test_db(database):
    pass
""")
    fixture = next(item for item in symbols if item.qualified_name.endswith(".database"))
    test = next(item for item in symbols if item.qualified_name.endswith(".test_db"))
    fixture = _reissue(fixture, kind=SymbolKind.FIXTURE)
    # Attach fixture_name metadata as the scanner does for aliased fixtures.
    def thaw(value):
        if hasattr(value, "items") and not isinstance(value, (str, bytes)):
            try:
                return {k: thaw(v) for k, v in dict(value).items()}
            except Exception:
                return value
        if isinstance(value, tuple):
            return [thaw(v) for v in value]
        return value

    meta = thaw(fixture.metadata)
    meta["fixture_name"] = "database"
    fixture = SymbolRecord(
        fixture.stable_id, fixture.version_cid, fixture.repository_id, fixture.language,
        fixture.module_path, fixture.qualified_name, fixture.kind, fixture.namespace,
        fixture.source_cid, fixture.span, fixture.confidence, thaw(fixture.signature),
        tuple(fixture.decorators), thaw(fixture.annotations), meta, thaw(fixture.normalized_ast),
        fixture.extractor_name, fixture.extractor_version, fixture.property_role,
    )
    test = _reissue(test, kind=SymbolKind.TEST)
    graph = build_symbol_graph(
        (fixture, test) + tuple(item for item in symbols if item.kind == "module"),
        edges=(DependencyEdge(test.stable_id, "pytest-fixture:database", RelationType.USES_FIXTURE, "pytest-static-parameter", "exact", "1"),),
    )
    outgoing = graph.outgoing(test.stable_id, relation=RelationType.USES_FIXTURE)
    assert len(outgoing) == 1
    assert outgoing[0].target_id == fixture.stable_id
    assert outgoing[0].metadata["resolution"] == STATUS_DEFINITE
