"""Contract vectors for semantic repository-state comparison."""

from __future__ import annotations

import ast
import pytest

from ipfs_datasets_py.logic.software_contracts.content import cid_for_bytes
from ipfs_datasets_py.logic.software_contracts.semantic_index.delta import (
    RepositoryStateDeltaError,
    classify_symbol_change,
    diff_repository_states,
)
from ipfs_datasets_py.logic.software_contracts.semantic_index.identity import (
    normalize_ast,
    stable_symbol_id,
    symbol_version_cid,
)
from ipfs_datasets_py.logic.software_contracts.semantic_index.models import (
    DependencyEdge,
    RepositoryState,
    RelationType,
    SourceSpan,
    SymbolKind,
    SymbolRecord,
)


def _symbol(
    name: str,
    source: str,
    *,
    kind: SymbolKind = SymbolKind.FUNCTION,
    signature: dict[str, object] | None = None,
    decorators: tuple[str, ...] = (),
    annotations: dict[str, object] | None = None,
    metadata: dict[str, object] | None = None,
    confidence: str = "exact",
    line: int = 1,
    module_path: str = "pkg/mod.py",
    namespace: str = "pkg",
) -> SymbolRecord:
    stable = stable_symbol_id(
        "repo:delta", "python", module_path, f"{namespace}.{name}", kind, namespace
    )
    tree = ast.parse(source).body[0]
    normalized = normalize_ast(tree)
    signature = signature or {}
    annotations = annotations or {}
    version = symbol_version_cid(stable, normalized, signature, decorators, annotations)
    return SymbolRecord(
        stable,
        version,
        "repo:delta",
        "python",
        module_path,
        f"{namespace}.{name}",
        kind,
        namespace,
        cid_for_bytes(source.encode()),
        SourceSpan(module_path, line, 0, line + 1, 20),
        confidence,
        signature,
        decorators,
        annotations,
        metadata or {},
        normalized,
    )


def _state(*symbols: SymbolRecord, edges: tuple[DependencyEdge, ...] = ()) -> RepositoryState:
    return RepositoryState("repo:delta", symbols, (), edges)


def test_formatting_and_span_only_changes_are_semantically_unchanged() -> None:
    old = _symbol("answer", "def answer(value):\n    return value + 1\n")
    new = _symbol("answer", "\n\ndef answer(value):\n\treturn value + 1\n", line=3)
    old_edge = DependencyEdge(old.stable_id, "lexical:helper", RelationType.CALLS, "lexical", "exact", "1", old.span)
    new_edge = DependencyEdge(new.stable_id, "lexical:helper", RelationType.CALLS, "lexical", "exact", "1", new.span)

    delta = diff_repository_states(_state(old, edges=(old_edge,)), _state(new, edges=(new_edge,)))

    assert delta.unchanged_symbol_ids == (old.stable_id,)
    assert not delta.modified_symbol_ids
    assert not delta.added_edge_ids and not delta.deleted_edge_ids


def test_body_only_edit_stays_local() -> None:
    old = _symbol("answer", "def answer(value):\n    return value + 1\n")
    changed = _symbol("answer", "def answer(value):\n    return value + 2\n")
    untouched = _symbol("other", "def other():\n    return 1\n")
    delta = diff_repository_states(_state(old, untouched), _state(changed, untouched))

    assert delta.modified_symbol_ids == (old.stable_id,)
    assert delta.unchanged_symbol_ids == (untouched.stable_id,)
    assert classify_symbol_change(old, changed) == ("body",)


def test_body_and_signature_retain_both_facets() -> None:
    old = _symbol(
        "answer",
        "def answer(value):\n    return value + 1\n",
        signature={"parameters": ["value"]},
    )
    new = _symbol(
        "answer",
        "def answer(value, flag=False):\n    return value + 2\n",
        signature={"parameters": ["value", "flag"]},
    )
    facets = classify_symbol_change(old, new)
    assert "body" in facets
    assert "signature" in facets


def test_function_and_method_annotations_are_not_schema_changes() -> None:
    old_fn = _symbol(
        "answer",
        "def answer(value: int) -> int:\n    return value\n",
        annotations={"value": "int", "return": "int"},
    )
    new_fn = _symbol(
        "answer",
        "def answer(value: str) -> str:\n    return value\n",
        annotations={"value": "str", "return": "str"},
    )
    assert "schema" not in classify_symbol_change(old_fn, new_fn)

    old_method = _symbol(
        "method",
        "def method(self, value: int) -> int:\n    return value\n",
        kind=SymbolKind.METHOD,
        annotations={"value": "int", "return": "int"},
    )
    new_method = _symbol(
        "method",
        "def method(self, value: str) -> str:\n    return value\n",
        kind=SymbolKind.METHOD,
        annotations={"value": "str", "return": "str"},
    )
    assert "schema" not in classify_symbol_change(old_method, new_method)

    old_dc = _symbol(
        "Payload",
        "@dataclass\nclass Payload:\n    name: str\n",
        kind=SymbolKind.DATACLASS,
        annotations={"fields": {"name": "str"}},
    )
    new_dc = _symbol(
        "Payload",
        "@dataclass\nclass Payload:\n    name: str\n    enabled: bool = False\n",
        kind=SymbolKind.DATACLASS,
        annotations={"fields": {"name": "str", "enabled": "bool"}},
    )
    assert "schema" in classify_symbol_change(old_dc, new_dc)


def test_facets_distinguish_interface_effect_exception_schema_decorator_and_confidence() -> None:
    old = _symbol(
        "Model",
        "@dataclass\nclass Model:\n    value: int\n",
        kind=SymbolKind.DATACLASS,
        signature={"parameters": ["value"]},
        annotations={"fields": {"value": "int"}},
    )
    new = _symbol(
        "Model",
        "@dataclass\nclass Model:\n    value: str\n",
        kind=SymbolKind.DATACLASS,
        signature={"parameters": ["value", "flag"]},
        decorators=("public",),
        annotations={"fields": {"value": "str"}},
        confidence="conservative",
    )
    old_edges = (
        DependencyEdge(old.stable_id, "state:x", RelationType.READS_STATE, "lexical", "exact", "1"),
        DependencyEdge(old.stable_id, "exception:Old", RelationType.RAISES, "direct_raise", "exact", "1"),
    )
    new_edges = (
        DependencyEdge(new.stable_id, "state:y", RelationType.WRITES_STATE, "lexical", "exact", "1"),
        DependencyEdge(new.stable_id, "exception:New", RelationType.RAISES, "direct_raise", "exact", "1"),
    )

    facets = classify_symbol_change(old, new, previous_edges=old_edges, current_edges=new_edges)

    assert "signature" in facets
    assert "effects" in facets
    assert "exceptions" in facets
    assert "schema" in facets
    assert "decorator" in facets
    assert "confidence" in facets


def test_edge_only_delta_records_added_and_deleted_edges() -> None:
    symbol = _symbol("service", "def service():\n    return 1\n")
    old_edge = DependencyEdge(symbol.stable_id, "exception:Old", RelationType.RAISES, "direct_raise", "exact", "1")
    new_edge = DependencyEdge(symbol.stable_id, "exception:New", RelationType.RAISES, "direct_raise", "exact", "1")
    previous, current = _state(symbol, edges=(old_edge,)), _state(symbol, edges=(new_edge,))
    delta = diff_repository_states(previous, current)

    assert symbol.stable_id not in delta.modified_symbol_ids
    assert old_edge.edge_id in delta.deleted_edge_ids
    assert new_edge.edge_id in delta.added_edge_ids
    assert classify_symbol_change(symbol, symbol, previous_edges=(old_edge,), current_edges=(new_edge,)) == (
        "exceptions",
    )


def test_deleted_and_unambiguous_heuristic_rename_candidates_are_deterministic() -> None:
    old = _symbol("old_name", "def old_name(value):\n    return value\n", signature={"parameters": ["value"]})
    new = _symbol("new_name", "def new_name(value):\n    return value\n", signature={"parameters": ["value"]})
    first = diff_repository_states(_state(old), _state(new))
    second = diff_repository_states(_state(old), _state(new))

    assert first.deleted_symbol_ids == (old.stable_id,)
    assert first.added_symbol_ids == (new.stable_id,)
    assert first.rename_candidates == second.rename_candidates
    assert first.rename_candidates[0]["previous_symbol_id"] == old.stable_id
    assert first.rename_candidates[0]["current_symbol_id"] == new.stable_id
    assert first.rename_candidates[0]["confidence"] == "heuristic"


def test_identical_states_have_empty_delta_and_stable_cid() -> None:
    symbol = _symbol("answer", "def answer():\n    return 1\n")
    state = _state(symbol)
    first = diff_repository_states(state, state)
    second = diff_repository_states(state, state)

    assert first.delta_cid == second.delta_cid
    assert first.added_symbol_ids == first.deleted_symbol_ids == first.modified_symbol_ids == ()
    assert first.added_artifact_ids == first.deleted_artifact_ids == first.modified_artifact_ids == ()
    assert first.added_edge_ids == first.deleted_edge_ids == ()
    assert first.unchanged_symbol_ids == (symbol.stable_id,)


def test_comparison_rejects_cross_repository_states() -> None:
    state = _state(_symbol("answer", "def answer():\n    return 1\n"))
    other = RepositoryState("repo:other", (), (), ())
    with pytest.raises(RepositoryStateDeltaError, match="repository_id"):
        diff_repository_states(state, other)
