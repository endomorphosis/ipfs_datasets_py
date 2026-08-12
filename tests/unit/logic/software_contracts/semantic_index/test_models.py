"""Focused contract vectors for semantic-index models and identities."""

from __future__ import annotations

import ast

import pytest

from ipfs_datasets_py.logic.software_contracts.content import cid_for_bytes
from ipfs_datasets_py.logic.software_contracts.semantic_index.identity import normalize_ast, stable_symbol_id, symbol_version_cid
from ipfs_datasets_py.logic.software_contracts.semantic_index.models import AnalysisConfidence, ArtifactRecord, DependencyEdge, ImpactExplanation, InvalidationObligation, InvalidationPlan, RelationType, RepositoryState, RepositoryStateDelta, SemanticIndexModelError, SourceSpan, SymbolExplanation, SymbolKind, SymbolRecord, migrate_symbol_record_v1


def _symbol(*, span: SourceSpan | None = None) -> SymbolRecord:
    stable = stable_symbol_id("repo:example", "python", "pkg/mod.py", "pkg.mod.answer", SymbolKind.FUNCTION, "pkg")
    node = ast.parse("def answer(value: int) -> int:\n    return value + 1\n").body[0]
    version = symbol_version_cid(stable, node, {"parameters": ["value"], "return": "int"}, ["public"], {"value": "int", "return": "int"})
    return SymbolRecord(stable, version, "repo:example", "python", "pkg/mod.py", "pkg.mod.answer", SymbolKind.FUNCTION, "pkg", cid_for_bytes(b"source"), span, AnalysisConfidence.EXACT, {"parameters": ["value"], "return": "int"}, ["public"], {"value": "int", "return": "int"}, normalized_ast=node)


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


@pytest.mark.parametrize(
    "literal",
    [
        float("nan"),
        complex(float("nan"), 0.0),
        complex(0.0, float("nan")),
    ],
)
def test_normalize_ast_rejects_source_impossible_nan_literals(literal: object) -> None:
    with pytest.raises(SemanticIndexModelError, match="rejects NaN"):
        normalize_ast(literal)


def test_version_identity_preserves_decorator_order_and_repetitions() -> None:
    stable = stable_symbol_id("repo:example", "python", "pkg/mod.py", "pkg.mod.decorated", "function", "pkg")
    node = ast.parse("def decorated():\n    pass\n").body[0]
    first = symbol_version_cid(stable, node, decorators=("trace", "trace", "cache"))
    reordered = symbol_version_cid(stable, node, decorators=("cache", "trace", "trace"))
    assert first != reordered
    record = SymbolRecord(stable, first, "repo:example", "python", "pkg/mod.py", "pkg.mod.decorated", "function", "pkg", decorators=("trace", "trace", "cache"), normalized_ast=node)
    assert record.decorators == ("trace", "trace", "cache")


def test_symbol_and_state_identity_are_self_verifying_and_metadata_is_deeply_immutable() -> None:
    stable = stable_symbol_id("repo:example", "python", "pkg/mod.py", "pkg.mod.answer", "function", "pkg")
    node = ast.parse("def answer():\n    return 1\n").body[0]
    version = symbol_version_cid(stable, node, {"parameters": ["fixed"]})
    symbol = SymbolRecord(
        stable, version, "repo:example", "python", "pkg/mod.py", "pkg.mod.answer",
        "function", "pkg", signature={"parameters": ["fixed"]}, metadata={"nested": {"items": ["fixed"]}}, normalized_ast=node,
    )
    with pytest.raises(TypeError):
        symbol.metadata["nested"]["items"] = ()
    with pytest.raises(AttributeError):
        symbol.metadata["nested"]["items"].append("mutate")
    with pytest.raises(TypeError):
        symbol.signature["parameters"] = ()
    with pytest.raises(AttributeError):
        symbol.signature["parameters"].append("mutate")
    with pytest.raises(TypeError):
        symbol.annotations["return"] = "str"

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


def test_v2_requires_and_binds_every_version_projection() -> None:
    symbol = _symbol()
    baseline = symbol.to_dict()
    omitted = dict(baseline)
    omitted.pop("normalized_ast")
    with pytest.raises(SemanticIndexModelError, match="fields must be exactly"):
        SymbolRecord.from_dict(omitted)
    for field, replacement in (
        ("extractor_name", "forged-extractor"),
        ("extractor_version", "999"),
        ("semantic_index_schema", "ipfs-datasets.software-contracts.semantic-index@1"),
        ("property_role", "getter"),
        ("signature", {"parameters": ["forged"]}),
        ("decorators", ["public", "audit"]),
        ("annotations", {"return": "str"}),
        ("normalized_ast", normalize_ast(ast.parse("def answer(value):\n    return value + 2\n").body[0])),
    ):
        forged = dict(baseline)
        forged[field] = replacement
        with pytest.raises(SemanticIndexModelError):
            SymbolRecord.from_dict(forged)


def test_v1_is_restored_only_by_explicit_typed_migration() -> None:
    symbol = _symbol()
    legacy = symbol.to_dict()
    legacy["schema"] = "ipfs-datasets.software-contracts.semantic-symbol@1"
    legacy.pop("semantic_index_schema")
    legacy["normalized_ast"] = None
    with pytest.raises(SemanticIndexModelError):
        SymbolRecord.from_dict(legacy)
    migrated = migrate_symbol_record_v1(legacy, normalized_ast=symbol.normalized_ast)
    assert SymbolRecord.from_dict(migrated.to_dict()) == migrated
    with pytest.raises(SemanticIndexModelError, match="requires normalized_ast"):
        migrate_symbol_record_v1(legacy, normalized_ast=None)
