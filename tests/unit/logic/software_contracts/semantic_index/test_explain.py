"""Contract tests for honest, bounded semantic-index explanations."""

from __future__ import annotations

from dataclasses import replace

import pytest

from ipfs_datasets_py.logic.software_contracts.semantic_index.explain import (
    UnknownSymbolError,
    explain_impact,
    explain_symbol,
)
from ipfs_datasets_py.logic.software_contracts.semantic_index.models import (
    ArtifactRecord,
    DependencyEdge,
    RelationType,
    RepositoryState,
)
from ipfs_datasets_py.logic.software_contracts.semantic_index.python_analysis import (
    analyze_python_source,
)


def _state(source: str = """
def a(): return b()
def b(): return a()
def caller(): return a()
""") -> tuple[RepositoryState, dict[str, str]]:
    analysis = analyze_python_source(source, "pkg/example.py", "repo:example")
    names = {
        item.qualified_name.rsplit(".", 1)[-1]: item.stable_id
        for item in analysis.symbol_records
    }
    return RepositoryState("repo:example", analysis.symbol_records, edges=analysis.edges), names


def test_unknown_symbol_is_a_typed_lookup_error() -> None:
    state, _ = _state()
    with pytest.raises(UnknownSymbolError) as error:
        explain_symbol(state, "missing:symbol")
    assert error.value.symbol_id == "missing:symbol"
    assert error.value.state_cid == state.state_cid


def test_symbol_explanation_retains_sorted_direct_edge_facts() -> None:
    state, names = _state()
    result = explain_symbol(state, names["a"])
    assert result.symbol_id == names["a"]
    assert tuple(edge.edge_id for edge in result.outgoing_edges) == tuple(
        sorted(edge.edge_id for edge in result.outgoing_edges)
    )
    assert result.outgoing_edges[0].extraction_method
    assert result.outgoing_edges[0].span is not None


def test_impact_is_stable_cycle_safe_and_reports_truncation() -> None:
    state, names = _state()
    first = explain_impact(state, names["a"], max_depth=10, max_nodes=10)
    second = explain_impact(state, names["a"], max_depth=10, max_nodes=10)
    assert first == second
    assert set(first.changed_symbol_ids) >= {names["a"], names["b"], names["caller"]}
    limited = explain_impact(state, names["a"], max_depth=0)
    assert "truncated:max_depth:0" in limited.limitations


def test_opaque_paths_require_raw_source() -> None:
    state, names = _state()
    opaque = replace(
        state.symbols[0], confidence="opaque", metadata={"confidence_reasons": ["runtime_codegen"]}
    )
    state = RepositoryState(state.repository_id, [opaque, *state.symbols[1:]], state.artifacts, state.edges)
    direct = explain_symbol(state, opaque.stable_id)
    assert f"raw_source_required:{opaque.stable_id}" in direct.limitations
    impacted = explain_impact(state, opaque.stable_id)
    assert f"raw_source_required:{opaque.stable_id}" in impacted.limitations
    assert f"confidence_reason:{opaque.stable_id}:runtime_codegen" in direct.limitations


def test_file_and_artifact_inputs_expand_to_stable_symbol_membership() -> None:
    state, names = _state()
    artifact = ArtifactRecord("artifact:pkg/example.py", "python", "pkg/example.py")
    state = RepositoryState(state.repository_id, state.symbols, [artifact], state.edges)
    by_path = explain_impact(state, "pkg/example.py")
    by_artifact = explain_impact(state, artifact.artifact_id)
    assert names["a"] in by_path.changed_symbol_ids
    assert set(by_path.changed_symbol_ids).issubset(by_artifact.changed_symbol_ids)
    assert artifact.artifact_id in by_artifact.changed_symbol_ids


def test_opaque_edge_on_an_impact_path_requires_raw_source() -> None:
    state, names = _state()
    edge = DependencyEdge(
        names["caller"], names["a"], RelationType.CALLS, "dynamic", "opaque", "1"
    )
    state = RepositoryState(state.repository_id, state.symbols, state.artifacts, [*state.edges, edge])
    impact = explain_impact(state, names["a"])
    assert f"raw_source_required:{edge.edge_id}" in impact.limitations


def test_identical_byte_files_do_not_cross_contaminate_path_impact() -> None:
    """Shared source CIDs must not pull symbols from a different path."""
    analysis_a = analyze_python_source("def shared():\n    return 1\n", "pkg/a.py", "repo:example")
    analysis_b = analyze_python_source("def shared():\n    return 1\n", "pkg/b.py", "repo:example")
    symbols = (*analysis_a.symbol_records, *analysis_b.symbol_records)
    # Force identical source CIDs across distinct paths.
    shared_cid = symbols[0].source_cid
    from dataclasses import replace as dc_replace

    symbols = tuple(
        dc_replace(item, source_cid=shared_cid) if item.source_cid != shared_cid else item
        for item in symbols
    )
    state = RepositoryState("repo:example", symbols, edges=())
    impact_a = explain_impact(state, "pkg/a.py")
    impact_b = explain_impact(state, "pkg/b.py")
    ids_a = {item.stable_id for item in symbols if item.module_path == "pkg/a.py"}
    ids_b = {item.stable_id for item in symbols if item.module_path == "pkg/b.py"}
    assert ids_a & set(impact_a.changed_symbol_ids)
    assert not (ids_b & set(impact_a.changed_symbol_ids))
    assert ids_b & set(impact_b.changed_symbol_ids)
    assert not (ids_a & set(impact_b.changed_symbol_ids))
