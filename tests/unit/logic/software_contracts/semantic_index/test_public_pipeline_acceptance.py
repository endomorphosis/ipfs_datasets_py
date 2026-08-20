"""Public scan/diff/invalidate pipeline acceptance without hand-authored edges.

Every case copies a fixture repository, scans with the public API, diffs, and
calculates invalidation.  Tests must not construct ``DependencyEdge`` values
or mutate returned states to create the expected result.
"""

from __future__ import annotations

from pathlib import Path
import shutil

import pytest

from ipfs_datasets_py.logic.software_contracts.semantic_index import (
    calculate_invalidation,
    diff_repository_states,
    scan_repository,
)
from ipfs_datasets_py.logic.software_contracts.semantic_index.delta import classify_symbol_change
from ipfs_datasets_py.logic.software_contracts.semantic_index.explain import explain_impact
from ipfs_datasets_py.logic.software_contracts.semantic_index.invalidation import (
    InvalidationError,
    InvalidationReason,
)
from ipfs_datasets_py.logic.software_contracts.semantic_index.models import (
    RelationType,
    RepositoryState,
    RepositoryStateDelta,
)


FIXTURES = Path(__file__).parents[4] / "fixtures" / "software_contracts" / "incremental_semantic_index"


def _copy_version(name: str, version: str, destination: Path) -> None:
    shutil.copytree(FIXTURES / name / version, destination)


def _pair(tmp_path: Path, name: str) -> tuple[RepositoryState, RepositoryState]:
    repository = tmp_path / "repository"
    _copy_version(name, "v1", repository)
    previous = scan_repository(repository)
    shutil.rmtree(repository)
    _copy_version(name, "v2", repository)
    return previous, scan_repository(repository, previous)


def _symbol(state: RepositoryState, qualified_name: str):
    return next(item for item in state.symbols if item.qualified_name == qualified_name)


def _plan(previous: RepositoryState, current: RepositoryState):
    return calculate_invalidation(previous, current, diff_repository_states(previous, current))


def _has_obligation(plan: object, reason: InvalidationReason, subject_id: str | None = None) -> bool:
    for item in plan.obligations:  # type: ignore[attr-defined]
        if item.reason_code != reason.value:
            continue
        if subject_id is None or item.subject_id == subject_id:
            return True
    return False


def test_body_only_invalidates_relevant_test_without_unrelated_callers(tmp_path: Path) -> None:
    previous, current = _pair(tmp_path, "body_test_impact")
    target_before, target_current = _symbol(previous, "module.target"), _symbol(current, "module.target")
    test_current = _symbol(current, "tests.test_target.test_target")
    caller_current = _symbol(current, "module.caller")
    facets = classify_symbol_change(
        target_before, target_current, previous_edges=previous.edges, current_edges=current.edges
    )
    assert "body" in facets
    assert "signature" not in facets
    plan = _plan(previous, current)
    assert _has_obligation(plan, InvalidationReason.STALE_TEST_RECEIPT, test_current.stable_id)
    assert not _has_obligation(plan, InvalidationReason.CALLER_SIGNATURE_MISMATCH, caller_current.stable_id)
    assert not any(item.reason_code == InvalidationReason.PROOF_RERUN.value for item in plan.obligations)
    assert any(edge.relation == RelationType.TESTED_BY.value for edge in current.edges)


def test_signature_change_invalidates_callers(tmp_path: Path) -> None:
    previous, current = _pair(tmp_path, "signature_callers")
    service_before, service_current = _symbol(previous, "module.service"), _symbol(current, "module.service")
    caller_current = _symbol(current, "module.caller")
    facets = classify_symbol_change(
        service_before, service_current, previous_edges=previous.edges, current_edges=current.edges
    )
    assert "signature" in facets
    assert "schema" not in facets  # ordinary function annotations are not schema
    plan = _plan(previous, current)
    assert _has_obligation(plan, InvalidationReason.CALLER_SIGNATURE_MISMATCH, caller_current.stable_id)


def test_exception_recovery_invalidation_from_public_scan(tmp_path: Path) -> None:
    previous, current = _pair(tmp_path, "exception_recovery")
    service_before, service_current = _symbol(previous, "module.service"), _symbol(current, "module.service")
    recover_current = _symbol(current, "module.recover")
    facets = classify_symbol_change(
        service_before, service_current, previous_edges=previous.edges, current_edges=current.edges
    )
    assert "exceptions" in facets
    plan = _plan(previous, current)
    assert _has_obligation(plan, InvalidationReason.EXCEPTION_RECOVERY_STALE, recover_current.stable_id)


def test_dataclass_field_change_invalidates_adapters(tmp_path: Path) -> None:
    previous, current = _pair(tmp_path, "dataclass_schema")
    payload_before, payload_current = _symbol(previous, "module.Payload"), _symbol(current, "module.Payload")
    serialize = _symbol(current, "module.serialize")
    deserialize = _symbol(current, "module.deserialize")
    facets = classify_symbol_change(
        payload_before, payload_current, previous_edges=previous.edges, current_edges=current.edges
    )
    assert "schema" in facets
    plan = _plan(previous, current)
    assert _has_obligation(plan, InvalidationReason.OBSOLETE_SCHEMA_ADAPTER, serialize.stable_id)
    assert _has_obligation(plan, InvalidationReason.OBSOLETE_SCHEMA_ADAPTER, deserialize.stable_id)


def test_fixture_config_invalidates_test_receipts(tmp_path: Path) -> None:
    previous, current = _pair(tmp_path, "fixture_config")
    test = next(
        item for item in current.symbols if item.kind == "test" and item.qualified_name.endswith("test_database")
    )
    plan = _plan(previous, current)
    assert _has_obligation(plan, InvalidationReason.STALE_TEST_RECEIPT, test.stable_id)
    assert any(edge.relation == RelationType.USES_FIXTURE.value for edge in current.edges)
    assert any(edge.relation == RelationType.CONFIGURED_BY.value for edge in current.edges)


def test_lock_environment_invalidates_receipts(tmp_path: Path) -> None:
    previous, current = _pair(tmp_path, "lock_environment")
    delta = diff_repository_states(previous, current)
    lock = next(item for item in current.artifacts if item.path == "requirements.txt")
    assert lock.artifact_id in delta.modified_artifact_ids
    plan = calculate_invalidation(previous, current, delta)
    assert _has_obligation(plan, InvalidationReason.ENVIRONMENT_RECEIPT_STALE, lock.artifact_id)


def test_fabricated_delta_with_matching_state_cids_is_rejected(tmp_path: Path) -> None:
    previous, current = _pair(tmp_path, "body_test_impact")
    real = diff_repository_states(previous, current)
    fabricated = RepositoryStateDelta(
        previous_state_cid=real.previous_state_cid,
        current_state_cid=real.current_state_cid,
        modified_symbol_ids=(),
        unchanged_symbol_ids=tuple(item.stable_id for item in current.symbols),
    )
    with pytest.raises(InvalidationError, match="recomputed|fabricated"):
        calculate_invalidation(previous, current, fabricated)


def test_no_proof_rerun_without_proof_depends_on_edge(tmp_path: Path) -> None:
    previous, current = _pair(tmp_path, "signature_callers")
    plan = _plan(previous, current)
    assert not any(edge.relation == RelationType.PROOF_DEPENDS_ON.value for edge in current.edges)
    assert not any(item.reason_code == InvalidationReason.PROOF_RERUN.value for item in plan.obligations)


def test_impact_path_membership_and_relation_direction(tmp_path: Path) -> None:
    previous, current = _pair(tmp_path, "signature_callers")
    service = _symbol(current, "module.service")
    caller = _symbol(current, "module.caller")
    impact = explain_impact(current, service.stable_id)
    assert caller.stable_id in impact.changed_symbol_ids
    # Incoming dependents only: service does not list unrelated production leaves.
    by_path = explain_impact(current, "module.py")
    assert service.stable_id in by_path.changed_symbol_ids
    assert caller.stable_id in by_path.changed_symbol_ids
