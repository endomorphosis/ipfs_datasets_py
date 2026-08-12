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
) -> SymbolRecord:
    stable = stable_symbol_id(
        "repo:delta", "python", "pkg/mod.py", f"pkg.mod.{name}", kind, "pkg"
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
        "pkg/mod.py",
        f"pkg.mod.{name}",
        kind,
        "pkg",
        cid_for_bytes(source.encode()),
        SourceSpan("pkg/mod.py", line, 0, line + 1, 20),
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


def test_facets_distinguish_interface_effect_exception_schema_decorator_and_confidence() -> None:
    # Schema facet is reserved for schema-bearing kinds (dataclass/typed dict/enum).
    # Use a dataclass field surface so the closed facet vocabulary assertion still
    # proves schema is independently retained alongside signature/effects/etc.
    source = "@dataclass\nclass Model:\n    value: int\n"
    old = _symbol(
        "Model",
        source,
        kind=SymbolKind.DATACLASS,
        signature={"parameters": ["value"]},
        annotations={"fields": {"value": "int"}, "bases": []},
    )
    new = _symbol(
        "Model",
        source,
        kind=SymbolKind.DATACLASS,
        signature={"parameters": ["value", "flag"]},
        decorators=("public",),
        annotations={"fields": {"value": "str"}, "bases": []},
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

    assert facets == ("signature", "effects", "exceptions", "schema", "decorator", "confidence")


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
    # RepositoryState rejects replace() when symbol repository_ids disagree
    # with the state, so build an authentic foreign-repository state.
    source = "def answer():\n    return 1\n"
    foreign_stable = stable_symbol_id(
        "repo:other", "python", "pkg/mod.py", "pkg.mod.answer", SymbolKind.FUNCTION, "pkg"
    )
    tree = ast.parse(source).body[0]
    normalized = normalize_ast(tree)
    foreign_version = symbol_version_cid(foreign_stable, normalized, {}, (), {})
    foreign_symbol = SymbolRecord(
        foreign_stable,
        foreign_version,
        "repo:other",
        "python",
        "pkg/mod.py",
        "pkg.mod.answer",
        SymbolKind.FUNCTION,
        "pkg",
        cid_for_bytes(source.encode()),
        SourceSpan("pkg/mod.py", 1, 0, 2, 20),
        "exact",
        {},
        (),
        {},
        {},
        normalized,
    )
    other = RepositoryState("repo:other", (foreign_symbol,))
    with pytest.raises(RepositoryStateDeltaError, match="repository_id"):
        diff_repository_states(state, other)


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


def test_ordinary_function_annotations_are_not_schema_changes() -> None:
    old = _symbol(
        "answer",
        "def answer(value):\n    return value\n",
        annotations={"return": "int", "value": "int"},
    )
    new = _symbol(
        "answer",
        "def answer(value):\n    return value\n",
        annotations={"return": "str", "value": "str"},
    )
    facets = classify_symbol_change(old, new)
    assert "schema" not in facets
