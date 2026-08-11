"""Focused contract vectors for reason-coded semantic invalidation."""

from __future__ import annotations

import ast

import pytest

from ipfs_datasets_py.logic.software_contracts.content import cid_for_bytes
from ipfs_datasets_py.logic.software_contracts.semantic_index.delta import diff_repository_states
from ipfs_datasets_py.logic.software_contracts.semantic_index.identity import stable_symbol_id, symbol_version_cid
from ipfs_datasets_py.logic.software_contracts.semantic_index.invalidation import InvalidationError, InvalidationReason, calculate_invalidation
from ipfs_datasets_py.logic.software_contracts.semantic_index.models import ArtifactRecord, DependencyEdge, RepositoryState, RelationType, SymbolKind, SymbolRecord


def _symbol(name: str, source: str, *, kind: SymbolKind = SymbolKind.FUNCTION, signature: dict[str, object] | None = None, annotations: dict[str, object] | None = None, confidence: str = "exact") -> SymbolRecord:
    stable = stable_symbol_id("repo:invalidation", "python", "pkg/mod.py", f"pkg.mod.{name}", kind, "pkg")
    tree = ast.parse(source).body[0]
    return SymbolRecord(stable, symbol_version_cid(stable, tree, signature or {}, (), annotations or {}), "repo:invalidation", "python", "pkg/mod.py", f"pkg.mod.{name}", kind, "pkg", cid_for_bytes(source.encode()), None, confidence, signature or {}, (), annotations or {}, {})


def _state(*symbols: SymbolRecord, artifacts: tuple[ArtifactRecord, ...] = (), edges: tuple[DependencyEdge, ...] = ()) -> RepositoryState:
    return RepositoryState("repo:invalidation", symbols, artifacts, edges)


def _reasons(plan: object) -> set[str]:
    return {item.reason_code for item in plan.obligations}  # type: ignore[attr-defined]


def test_body_change_is_local_but_requires_capsule_proof_and_test_receipt() -> None:
    old = _symbol("target", "def target(value):\n return value + 1\n")
    new = _symbol("target", "def target(value):\n return value + 2\n")
    caller = _symbol("caller", "def caller():\n return target(1)\n")
    test = _symbol("test_target", "def test_target():\n assert target(1) == 2\n", kind=SymbolKind.TEST)
    edges = (DependencyEdge(caller.stable_id, old.stable_id, RelationType.CALLS, "static", "exact", "1"), DependencyEdge(old.stable_id, test.stable_id, RelationType.TESTED_BY, "static", "exact", "1"))
    previous, current = _state(old, caller, test, edges=edges), _state(new, caller, test, edges=(DependencyEdge(caller.stable_id, new.stable_id, RelationType.CALLS, "static", "exact", "1"), DependencyEdge(new.stable_id, test.stable_id, RelationType.TESTED_BY, "static", "exact", "1")))
    plan = calculate_invalidation(previous, current, diff_repository_states(previous, current))
    assert {InvalidationReason.NEW_CAPSULE.value, InvalidationReason.PROOF_RERUN.value, InvalidationReason.STALE_TEST_RECEIPT.value} <= _reasons(plan)
    assert InvalidationReason.CALLER_SIGNATURE_MISMATCH.value not in _reasons(plan)


def test_signature_schema_and_effect_rules_are_edge_justified() -> None:
    old = _symbol("model", "def model(value):\n return value\n", signature={"parameters": ["value"]}, annotations={"return": "int"})
    new = _symbol("model", "def model(value, flag=False):\n return value\n", signature={"parameters": ["value", "flag"]}, annotations={"return": "str"})
    caller, adapter = _symbol("caller", "def caller():\n return model(1)\n"), _symbol("adapter", "def adapter():\n pass\n")
    old_edges = (DependencyEdge(caller.stable_id, old.stable_id, RelationType.CALLS, "static", "exact", "1"), DependencyEdge(adapter.stable_id, old.stable_id, RelationType.SERIALIZES, "static", "exact", "1"))
    new_edges = tuple(DependencyEdge(edge.source_id, new.stable_id if edge.target_id == old.stable_id else edge.target_id, edge.relation, edge.extraction_method, edge.confidence, edge.extractor_version, edge.span, edge.metadata) for edge in old_edges)
    previous, current = _state(old, caller, adapter, edges=old_edges), _state(new, caller, adapter, edges=new_edges)
    plan = calculate_invalidation(previous, current, diff_repository_states(previous, current))
    obligations = {item.reason_code: item for item in plan.obligations}
    assert obligations[InvalidationReason.CALLER_SIGNATURE_MISMATCH.value].subject_id == caller.stable_id
    assert obligations[InvalidationReason.OBSOLETE_SCHEMA_ADAPTER.value].subject_id == adapter.stable_id
    assert obligations[InvalidationReason.OBSOLETE_SCHEMA_ADAPTER.value].supporting_edge_ids


def test_effect_and_exception_assumptions_receive_specific_reviews() -> None:
    old = _symbol("service", "def service():\n return 1\n")
    new = _symbol("service", "def service():\n return 2\n")
    caller = _symbol("caller", "def caller():\n return service()\n")
    old_edges = (
        DependencyEdge(old.stable_id, "state:read", RelationType.READS_STATE, "static", "exact", "1"),
        DependencyEdge(old.stable_id, "exception:Old", RelationType.RAISES, "static", "exact", "1"),
        DependencyEdge(caller.stable_id, old.stable_id, RelationType.CALLS, "static", "exact", "1", metadata={"assumes_effects": True, "assumes_exceptions": True}),
    )
    new_edges = (
        DependencyEdge(new.stable_id, "state:write", RelationType.WRITES_STATE, "static", "exact", "1"),
        DependencyEdge(new.stable_id, "exception:New", RelationType.RAISES, "static", "exact", "1"),
        DependencyEdge(caller.stable_id, new.stable_id, RelationType.CALLS, "static", "exact", "1", metadata={"assumes_effects": True, "assumes_exceptions": True}),
    )
    previous, current = _state(old, caller, edges=old_edges), _state(new, caller, edges=new_edges)
    plan = calculate_invalidation(previous, current, diff_repository_states(previous, current))
    assert {InvalidationReason.PURITY_SECURITY_REVIEW.value, InvalidationReason.EFFECT_ASSUMPTION_STALE.value, InvalidationReason.EXCEPTION_RECOVERY_STALE.value} <= _reasons(plan)


def test_fixture_environment_deletion_and_opaque_evidence_are_explicit() -> None:
    fixture = _symbol("fixture", "def fixture():\n return 1\n", kind=SymbolKind.FIXTURE)
    test = _symbol("test_x", "def test_x():\n assert True\n", kind=SymbolKind.TEST)
    lock_old = ArtifactRecord("artifact:lock", "dependency_lock", "poetry.lock", cid_for_bytes(b"old"))
    lock_new = ArtifactRecord("artifact:lock", "dependency_lock", "poetry.lock", cid_for_bytes(b"new"))
    deleted = _symbol("gone", "def gone():\n pass\n")
    edges = (DependencyEdge(test.stable_id, fixture.stable_id, RelationType.USES_FIXTURE, "static", "exact", "1"), DependencyEdge(test.stable_id, lock_old.artifact_id, RelationType.CONFIGURED_BY, "static", "exact", "1"), DependencyEdge(test.stable_id, deleted.stable_id, RelationType.CALLS, "dynamic", "opaque", "1", metadata={"resolution": "unresolved"}))
    previous = _state(fixture, test, deleted, artifacts=(lock_old,), edges=edges)
    current = _state(test, artifacts=(lock_new,), edges=(DependencyEdge(test.stable_id, fixture.stable_id, RelationType.USES_FIXTURE, "static", "exact", "1"), DependencyEdge(test.stable_id, lock_new.artifact_id, RelationType.CONFIGURED_BY, "static", "exact", "1")))
    plan = calculate_invalidation(previous, current, diff_repository_states(previous, current))
    assert {InvalidationReason.STALE_TEST_RECEIPT.value, InvalidationReason.ENVIRONMENT_RECEIPT_STALE.value, InvalidationReason.DELETED_SYMBOL_DEPENDENCY.value, InvalidationReason.RAW_SOURCE_REQUIRED.value} <= _reasons(plan)


def test_plan_is_deterministic_deduplicated_bounded_and_rejects_foreign_delta() -> None:
    old, new = _symbol("x", "def x():\n return 1\n"), _symbol("x", "def x():\n return 2\n")
    previous, current = _state(old), _state(new)
    delta = diff_repository_states(previous, current)
    assert calculate_invalidation(previous, current, delta) == calculate_invalidation(previous, current, delta)
    with pytest.raises(InvalidationError, match="max_obligations"):
        calculate_invalidation(previous, current, delta, max_obligations=0)
    with pytest.raises(InvalidationError, match="state CIDs"):
        calculate_invalidation(current, previous, delta)
