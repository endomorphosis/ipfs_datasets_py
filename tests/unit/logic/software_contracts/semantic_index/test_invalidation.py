"""Focused contract vectors for reason-coded semantic invalidation."""

from __future__ import annotations

import ast
from dataclasses import replace

import pytest

from ipfs_datasets_py.logic.software_contracts.content import cid_for_bytes
from ipfs_datasets_py.logic.software_contracts.semantic_index.delta import diff_repository_states
from ipfs_datasets_py.logic.software_contracts.semantic_index.identity import (
    normalize_ast,
    stable_symbol_id,
    symbol_version_cid,
)
from ipfs_datasets_py.logic.software_contracts.semantic_index.invalidation import (
    InvalidationError,
    InvalidationReason,
    calculate_invalidation,
)
from ipfs_datasets_py.logic.software_contracts.semantic_index.models import (
    ArtifactRecord,
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
    annotations: dict[str, object] | None = None,
    confidence: str = "exact",
    metadata: dict[str, object] | None = None,
) -> SymbolRecord:
    stable = stable_symbol_id("repo:invalidation", "python", "pkg/mod.py", f"pkg.mod.{name}", kind, "pkg")
    tree = ast.parse(source).body[0]
    normalized = normalize_ast(tree)
    signature = signature or {}
    annotations = annotations or {}
    version = symbol_version_cid(stable, normalized, signature, (), annotations)
    return SymbolRecord(
        stable,
        version,
        "repo:invalidation",
        "python",
        "pkg/mod.py",
        f"pkg.mod.{name}",
        kind,
        "pkg",
        cid_for_bytes(source.encode()),
        SourceSpan("pkg/mod.py", 1, 0, 2, 20),
        confidence,
        signature,
        (),
        annotations,
        metadata or {},
        normalized,
    )


def _state(
    *symbols: SymbolRecord,
    artifacts: tuple[ArtifactRecord, ...] = (),
    edges: tuple[DependencyEdge, ...] = (),
) -> RepositoryState:
    return RepositoryState("repo:invalidation", symbols, artifacts, edges)


def _reasons(plan: object) -> set[str]:
    return {item.reason_code for item in plan.obligations}  # type: ignore[attr-defined]


def test_body_change_is_local_but_requires_capsule_and_test_receipt_not_invented_proof() -> None:
    old = _symbol("target", "def target(value):\n return value + 1\n")
    new = _symbol("target", "def target(value):\n return value + 2\n")
    caller = _symbol("caller", "def caller():\n return target(1)\n")
    test = _symbol("test_target", "def test_target():\n assert target(1) == 2\n", kind=SymbolKind.TEST)
    edges = (
        DependencyEdge(caller.stable_id, old.stable_id, RelationType.CALLS, "static", "exact", "1"),
        DependencyEdge(old.stable_id, test.stable_id, RelationType.TESTED_BY, "static", "exact", "1"),
    )
    new_edges = (
        DependencyEdge(caller.stable_id, new.stable_id, RelationType.CALLS, "static", "exact", "1"),
        DependencyEdge(new.stable_id, test.stable_id, RelationType.TESTED_BY, "static", "exact", "1"),
    )
    previous, current = _state(old, caller, test, edges=edges), _state(new, caller, test, edges=new_edges)
    plan = calculate_invalidation(previous, current, diff_repository_states(previous, current))
    assert {InvalidationReason.NEW_CAPSULE.value, InvalidationReason.STALE_TEST_RECEIPT.value} <= _reasons(plan)
    assert InvalidationReason.CALLER_SIGNATURE_MISMATCH.value not in _reasons(plan)
    assert InvalidationReason.PROOF_RERUN.value not in _reasons(plan)


def test_proof_rerun_requires_proof_depends_on_edge() -> None:
    old = _symbol("target", "def target():\n return 1\n")
    new = _symbol("target", "def target():\n return 2\n")
    proof = _symbol("proof_of_target", "def proof_of_target():\n pass\n")
    edges_old = (
        DependencyEdge(proof.stable_id, old.stable_id, RelationType.PROOF_DEPENDS_ON, "static", "exact", "1"),
    )
    edges_new = (
        DependencyEdge(proof.stable_id, new.stable_id, RelationType.PROOF_DEPENDS_ON, "static", "exact", "1"),
    )
    previous, current = _state(old, proof, edges=edges_old), _state(new, proof, edges=edges_new)
    plan = calculate_invalidation(previous, current, diff_repository_states(previous, current))
    assert InvalidationReason.PROOF_RERUN.value in _reasons(plan)
    proof_items = [item for item in plan.obligations if item.reason_code == InvalidationReason.PROOF_RERUN.value]
    assert proof_items[0].subject_id == proof.stable_id
    assert proof_items[0].supporting_edge_ids


def test_signature_schema_and_effect_rules_are_edge_justified() -> None:
    old = _symbol(
        "model",
        "def model(value):\n return value\n",
        signature={"parameters": ["value"]},
        annotations={"return": "int"},
    )
    new = _symbol(
        "model",
        "def model(value, flag=False):\n return value\n",
        signature={"parameters": ["value", "flag"]},
        annotations={"return": "str"},
    )
    caller = _symbol("caller", "def caller():\n return model(1)\n")
    adapter = _symbol("adapter", "def adapter():\n pass\n")
    old_edges = (
        DependencyEdge(caller.stable_id, old.stable_id, RelationType.CALLS, "static", "exact", "1"),
        DependencyEdge(adapter.stable_id, old.stable_id, RelationType.SERIALIZES, "static", "exact", "1"),
    )
    new_edges = tuple(
        DependencyEdge(
            edge.source_id,
            new.stable_id if edge.target_id == old.stable_id else edge.target_id,
            edge.relation,
            edge.extraction_method,
            edge.confidence,
            edge.extractor_version,
            edge.span,
            edge.metadata,
        )
        for edge in old_edges
    )
    previous, current = _state(old, caller, adapter, edges=old_edges), _state(new, caller, adapter, edges=new_edges)
    plan = calculate_invalidation(previous, current, diff_repository_states(previous, current))
    obligations = {item.reason_code: item for item in plan.obligations}
    assert obligations[InvalidationReason.CALLER_SIGNATURE_MISMATCH.value].subject_id == caller.stable_id
    assert obligations[InvalidationReason.OBSOLETE_SCHEMA_ADAPTER.value].subject_id == adapter.stable_id
    assert obligations[InvalidationReason.OBSOLETE_SCHEMA_ADAPTER.value].supporting_edge_ids


def test_dataclass_schema_field_change_invalidates_annotation_and_constructor_adapters() -> None:
    old = _symbol(
        "Payload",
        "@dataclass\nclass Payload:\n name: str\n",
        kind=SymbolKind.DATACLASS,
        annotations={"fields": {"name": "str"}},
    )
    new = _symbol(
        "Payload",
        "@dataclass\nclass Payload:\n name: str\n enabled: bool = False\n",
        kind=SymbolKind.DATACLASS,
        annotations={"fields": {"name": "str", "enabled": "bool"}},
    )
    serialize = _symbol(
        "serialize",
        "def serialize(payload):\n return payload.name\n",
        annotations={"payload": "Payload", "return": "str"},
    )
    deserialize = _symbol(
        "deserialize",
        "def deserialize(name):\n return Payload(name)\n",
        annotations={"name": "str", "return": "Payload"},
    )
    edges = (
        DependencyEdge(deserialize.stable_id, old.stable_id, RelationType.CALLS, "static", "exact", "1"),
    )
    new_edges = (
        DependencyEdge(deserialize.stable_id, new.stable_id, RelationType.CALLS, "static", "exact", "1"),
    )
    previous = _state(old, serialize, deserialize, edges=edges)
    current = _state(new, serialize, deserialize, edges=new_edges)
    plan = calculate_invalidation(previous, current, diff_repository_states(previous, current))
    subjects = {
        item.subject_id
        for item in plan.obligations
        if item.reason_code == InvalidationReason.OBSOLETE_SCHEMA_ADAPTER.value
    }
    assert serialize.stable_id in subjects
    assert deserialize.stable_id in subjects


def test_effect_and_exception_assumptions_receive_specific_reviews() -> None:
    old = _symbol("service", "def service():\n return 1\n")
    new = _symbol("service", "def service():\n return 2\n")
    caller = _symbol("caller", "def caller():\n return service()\n")
    old_edges = (
        DependencyEdge(old.stable_id, "state:read", RelationType.READS_STATE, "static", "exact", "1"),
        DependencyEdge(old.stable_id, "exception:Old", RelationType.RAISES, "static", "exact", "1"),
        DependencyEdge(
            caller.stable_id,
            old.stable_id,
            RelationType.CALLS,
            "static",
            "exact",
            "1",
            metadata={"assumes_effects": True, "assumes_exceptions": True},
        ),
    )
    new_edges = (
        DependencyEdge(new.stable_id, "state:write", RelationType.WRITES_STATE, "static", "exact", "1"),
        DependencyEdge(new.stable_id, "exception:New", RelationType.RAISES, "static", "exact", "1"),
        DependencyEdge(
            caller.stable_id,
            new.stable_id,
            RelationType.CALLS,
            "static",
            "exact",
            "1",
            metadata={"assumes_effects": True, "assumes_exceptions": True},
        ),
    )
    previous, current = _state(old, caller, edges=old_edges), _state(new, caller, edges=new_edges)
    plan = calculate_invalidation(previous, current, diff_repository_states(previous, current))
    assert {
        InvalidationReason.PURITY_SECURITY_REVIEW.value,
        InvalidationReason.EFFECT_ASSUMPTION_STALE.value,
        InvalidationReason.EXCEPTION_RECOVERY_STALE.value,
    } <= _reasons(plan)


def test_exception_recovery_from_caller_catches_without_assumes_metadata() -> None:
    old = _symbol("service", "def service():\n raise ValueError()\n")
    new = _symbol("service", "def service():\n raise KeyError()\n")
    recover = _symbol("recover", "def recover():\n try:\n  service()\n except ValueError:\n  pass\n")
    old_edges = (
        DependencyEdge(old.stable_id, "exception:ValueError", RelationType.RAISES, "static", "exact", "1"),
        DependencyEdge(recover.stable_id, old.stable_id, RelationType.CALLS, "static", "exact", "1"),
        DependencyEdge(recover.stable_id, "exception:ValueError", RelationType.CATCHES, "static", "exact", "1"),
    )
    new_edges = (
        DependencyEdge(new.stable_id, "exception:KeyError", RelationType.RAISES, "static", "exact", "1"),
        DependencyEdge(recover.stable_id, new.stable_id, RelationType.CALLS, "static", "exact", "1"),
        DependencyEdge(recover.stable_id, "exception:ValueError", RelationType.CATCHES, "static", "exact", "1"),
    )
    previous, current = _state(old, recover, edges=old_edges), _state(new, recover, edges=new_edges)
    plan = calculate_invalidation(previous, current, diff_repository_states(previous, current))
    assert any(
        item.reason_code == InvalidationReason.EXCEPTION_RECOVERY_STALE.value
        and item.subject_id == recover.stable_id
        for item in plan.obligations
    )


def test_edge_only_exception_change_is_actionable() -> None:
    service = _symbol("service", "def service():\n return 1\n")
    recover = _symbol("recover", "def recover():\n try:\n  service()\n except Exception:\n  pass\n")
    old_edges = (
        DependencyEdge(service.stable_id, "exception:Old", RelationType.RAISES, "static", "exact", "1"),
        DependencyEdge(recover.stable_id, service.stable_id, RelationType.CALLS, "static", "exact", "1"),
        DependencyEdge(recover.stable_id, "exception:Exception", RelationType.CATCHES, "static", "exact", "1"),
    )
    new_edges = (
        DependencyEdge(service.stable_id, "exception:New", RelationType.RAISES, "static", "exact", "1"),
        DependencyEdge(recover.stable_id, service.stable_id, RelationType.CALLS, "static", "exact", "1"),
        DependencyEdge(recover.stable_id, "exception:Exception", RelationType.CATCHES, "static", "exact", "1"),
    )
    previous, current = _state(service, recover, edges=old_edges), _state(service, recover, edges=new_edges)
    delta = diff_repository_states(previous, current)
    assert service.stable_id not in delta.modified_symbol_ids
    plan = calculate_invalidation(previous, current, delta)
    assert InvalidationReason.EXCEPTION_RECOVERY_STALE.value in _reasons(plan)


def test_fixture_environment_deletion_and_opaque_evidence_are_explicit() -> None:
    fixture = _symbol("fixture", "def fixture():\n return 1\n", kind=SymbolKind.FIXTURE)
    test = _symbol("test_x", "def test_x():\n assert True\n", kind=SymbolKind.TEST)
    lock_old = ArtifactRecord("artifact:lock", "dependency-lock", "poetry.lock", cid_for_bytes(b"old"))
    lock_new = ArtifactRecord("artifact:lock", "dependency-lock", "poetry.lock", cid_for_bytes(b"new"))
    deleted = _symbol(
        "gone",
        "def gone():\n pass\n",
        confidence="opaque",
        metadata={"confidence_reasons": ["runtime_codegen"]},
    )
    edges = (
        DependencyEdge(test.stable_id, fixture.stable_id, RelationType.USES_FIXTURE, "static", "exact", "1"),
        DependencyEdge(test.stable_id, lock_old.artifact_id, RelationType.CONFIGURED_BY, "static", "exact", "1"),
        DependencyEdge(
            test.stable_id,
            deleted.stable_id,
            RelationType.CALLS,
            "dynamic",
            "opaque",
            "1",
            metadata={"resolution": "unresolved"},
        ),
    )
    previous = _state(fixture, test, deleted, artifacts=(lock_old,), edges=edges)
    current = _state(
        test,
        artifacts=(lock_new,),
        edges=(
            DependencyEdge(test.stable_id, fixture.stable_id, RelationType.USES_FIXTURE, "static", "exact", "1"),
            DependencyEdge(test.stable_id, lock_new.artifact_id, RelationType.CONFIGURED_BY, "static", "exact", "1"),
        ),
    )
    plan = calculate_invalidation(previous, current, diff_repository_states(previous, current))
    assert {
        InvalidationReason.STALE_TEST_RECEIPT.value,
        InvalidationReason.ENVIRONMENT_RECEIPT_STALE.value,
        InvalidationReason.DELETED_SYMBOL_DEPENDENCY.value,
        InvalidationReason.RAW_SOURCE_REQUIRED.value,
    } <= _reasons(plan)
    opaque = next(
        item for item in plan.obligations if item.reason_code == InvalidationReason.RAW_SOURCE_REQUIRED.value
    )
    # Opaque obligations must identify retrievable raw source (path/CID/span/edge).
    assert (
        opaque.details.get("module_path")
        or opaque.details.get("path")
        or opaque.details.get("source_cid")
        or opaque.details.get("span")
        or opaque.details.get("edge_id")
    )


def test_plan_is_deterministic_deduplicated_bounded_and_rejects_fabricated_delta() -> None:
    old, new = _symbol("x", "def x():\n return 1\n"), _symbol("x", "def x():\n return 2\n")
    previous, current = _state(old), _state(new)
    delta = diff_repository_states(previous, current)
    assert calculate_invalidation(previous, current, delta) == calculate_invalidation(previous, current, delta)
    with pytest.raises(InvalidationError, match="max_obligations"):
        calculate_invalidation(previous, current, delta, max_obligations=0)
    with pytest.raises(InvalidationError, match="state CIDs"):
        calculate_invalidation(current, previous, delta)
    fabricated = replace(delta, modified_symbol_ids=())
    with pytest.raises(InvalidationError, match="recomputed"):
        calculate_invalidation(previous, current, fabricated)
