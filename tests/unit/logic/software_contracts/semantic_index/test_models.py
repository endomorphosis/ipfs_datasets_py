"""Focused contract vectors for semantic-index models and identities."""

from __future__ import annotations

import ast

import pytest

from ipfs_datasets_py.logic.software_contracts.content import cid_for_bytes
from ipfs_datasets_py.logic.software_contracts.semantic_index.identity import stable_symbol_id, symbol_version_cid
from ipfs_datasets_py.logic.software_contracts.semantic_index.models import AnalysisConfidence, ArtifactRecord, DependencyEdge, ImpactExplanation, InvalidationObligation, InvalidationPlan, RelationType, RepositoryState, RepositoryStateDelta, SemanticIndexModelError, SourceSpan, SymbolExplanation, SymbolKind, SymbolRecord


def _symbol(*, span: SourceSpan | None = None) -> SymbolRecord:
    stable = stable_symbol_id("repo:example", "python", "pkg/mod.py", "pkg.mod.answer", SymbolKind.FUNCTION, "pkg")
    version = symbol_version_cid(stable, ast.parse("def answer(value: int) -> int:\n    return value + 1\n").body[0], {"parameters": ["value"], "return": "int"}, ["public"], {"value": "int", "return": "int"})
    return SymbolRecord(stable, version, "repo:example", "python", "pkg/mod.py", "pkg.mod.answer", SymbolKind.FUNCTION, "pkg", cid_for_bytes(b"source"), span, AnalysisConfidence.EXACT, {"parameters": ["value"]}, ["public"], {"return": "int"})


def test_stable_identity_excludes_spans_bodies_and_formatting() -> None:
    left = stable_symbol_id("repo:example", "python", "pkg\\mod.py", "pkg.mod.answer", "function", "pkg")
    right = stable_symbol_id("repo:example", "python", "pkg/mod.py", "pkg.mod.answer", "function", "pkg")
    assert left == right
    assert left != stable_symbol_id("repo:other", "python", "pkg/mod.py", "pkg.mod.answer", "function", "pkg")
    assert left != stable_symbol_id("repo:example", "python", "pkg/mod.py", "pkg.mod.answer", "method", "pkg")


def test_version_identity_normalizes_positions_but_binds_semantics() -> None:
    stable = stable_symbol_id("repo:example", "python", "pkg/mod.py", "pkg.mod.answer", "function", "pkg")
    first = ast.parse("\n\ndef answer(value: int) -> int:\n    return value + 1\n").body[0]
    second = ast.parse("def answer(value: int) -> int:\n\treturn value + 1\n").body[0]
    assert symbol_version_cid(stable, first) == symbol_version_cid(stable, second)
    changed = ast.parse("def answer(value: int) -> int:\n    return value + 2\n").body[0]
    assert symbol_version_cid(stable, first) != symbol_version_cid(stable, changed)


def test_durable_records_sort_and_round_trip() -> None:
    span = SourceSpan("pkg/mod.py", 1, 0, 2, 18)
    symbol = _symbol(span=span)
    edge = DependencyEdge(symbol.stable_id, "artifact:database", RelationType.CALLS, "lexical", "conservative", "1", span)
    artifact = ArtifactRecord("artifact:database", "external", "config/db.json")
    state = RepositoryState("repo:example", [symbol], [artifact], [edge])
    assert RepositoryState.from_dict(state.to_dict()) == state
    assert state.to_dict()["symbols"][0]["span"] == span.to_dict()


def test_closed_models_reject_unknown_fields_and_enum_values() -> None:
    with pytest.raises(SemanticIndexModelError):
        ArtifactRecord("a", "x", "x", confidence="guess")
    value = ArtifactRecord("a", "x", "x").to_dict()
    value["extra"] = True
    with pytest.raises(SemanticIndexModelError):
        ArtifactRecord.from_dict(value)


def test_delta_plans_and_explanations_round_trip_and_verify_cids() -> None:
    symbol = _symbol()
    state = RepositoryState("repo:example", [symbol])
    delta = RepositoryStateDelta(state.state_cid, state.state_cid, unchanged_symbol_ids=[symbol.stable_id])
    obligation = InvalidationObligation(symbol.stable_id, "body_changed", "rebuild_capsule", "exact", old_identity=symbol.version_cid, new_identity=symbol.version_cid)
    plan = InvalidationPlan(state.state_cid, state.state_cid, [obligation])
    explanation = SymbolExplanation(symbol.stable_id, state.state_cid, symbol)
    impact = ImpactExplanation(state.state_cid, [symbol.stable_id], [obligation])
    assert RepositoryStateDelta.from_dict(delta.to_dict()) == delta
    assert InvalidationPlan.from_dict(plan.to_dict()) == plan
    assert SymbolExplanation.from_dict(explanation.to_dict()) == explanation
    assert ImpactExplanation.from_dict(impact.to_dict()) == impact


@pytest.mark.parametrize(
    "literal",
    [1.25, b"\x00semantic", complex(1.5, -2.0), Ellipsis],
)
def test_version_identity_encodes_non_dag_json_ast_constants(literal: object) -> None:
    stable = stable_symbol_id("repo:example", "python", "pkg/mod.py", "pkg.mod.literal", "constant", "pkg")
    node = ast.Constant(value=literal)
    version = symbol_version_cid(stable, node, decorators=("trace", "trace", "cache"))
    record = SymbolRecord(
        stable, version, "repo:example", "python", "pkg/mod.py",
        "pkg.mod.literal", "constant", "pkg", normalized_ast=node,
        decorators=("trace", "trace", "cache"),
    )
    assert SymbolRecord.from_dict(record.to_dict()) == record


def test_version_identity_preserves_decorator_order_and_repetitions() -> None:
    stable = stable_symbol_id("repo:example", "python", "pkg/mod.py", "pkg.mod.decorated", "function", "pkg")
    node = ast.parse("def decorated():\n    pass\n").body[0]
    first = symbol_version_cid(stable, node, decorators=("trace", "trace", "cache"))
    reordered = symbol_version_cid(stable, node, decorators=("cache", "trace", "trace"))
    assert first != reordered
    record = SymbolRecord(stable, first, "repo:example", "python", "pkg/mod.py", "pkg.mod.decorated", "function", "pkg", decorators=("trace", "trace", "cache"))
    assert record.decorators == ("trace", "trace", "cache")


def test_symbol_and_state_identity_are_self_verifying_and_metadata_is_deeply_immutable() -> None:
    stable = stable_symbol_id("repo:example", "python", "pkg/mod.py", "pkg.mod.answer", "function", "pkg")
    node = ast.parse("def answer():\n    return 1\n").body[0]
    version = symbol_version_cid(stable, node)
    symbol = SymbolRecord(
        stable, version, "repo:example", "python", "pkg/mod.py", "pkg.mod.answer",
        "function", "pkg", metadata={"nested": {"items": ["fixed"]}}, normalized_ast=node,
    )
    with pytest.raises(TypeError):
        symbol.metadata["nested"]["items"] = ()
    with pytest.raises(AttributeError):
        symbol.metadata["nested"]["items"].append("mutate")

    forged_kind = symbol.to_dict()
    forged_kind["kind"] = "method"
    with pytest.raises(SemanticIndexModelError, match="stable_id does not verify"):
        SymbolRecord.from_dict(forged_kind)
    forged_repository = symbol.to_dict()
    forged_repository["repository_id"] = "repo:forged"
    with pytest.raises(SemanticIndexModelError, match="stable_id does not verify"):
        SymbolRecord.from_dict(forged_repository)
    forged_version = symbol.to_dict()
    forged_version["version_cid"] = cid_for_bytes(b"old-version")
    with pytest.raises(SemanticIndexModelError, match="version_cid does not verify"):
        SymbolRecord.from_dict(forged_version)
    with pytest.raises(SemanticIndexModelError, match="RepositoryState repository_id"):
        RepositoryState("repo:other", [symbol])
