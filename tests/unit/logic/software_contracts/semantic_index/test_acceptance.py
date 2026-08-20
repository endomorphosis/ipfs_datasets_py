"""End-to-end acceptance matrix for semantic-index mutations and persistence.

Each compact fixture is copied before scanning so the test never mutates the
fixture corpus.  Cases exercise only the public scan / diff / invalidation /
explanation / persistence APIs.  This module must not construct
``DependencyEdge`` values or mutate returned states to manufacture expected
graph results.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import shutil
import threading

from ipfs_datasets_py.logic.software_contracts.semantic_index import (
    calculate_invalidation,
    diff_repository_states,
    explain_impact,
    explain_symbol,
    scan_repository,
)
from ipfs_datasets_py.logic.software_contracts.semantic_index.delta import classify_symbol_change
from ipfs_datasets_py.logic.software_contracts.semantic_index.invalidation import InvalidationReason
from ipfs_datasets_py.logic.software_contracts.semantic_index.models import RelationType, RepositoryState
from ipfs_datasets_py.logic.software_contracts.semantic_index.persistence import LocalSemanticIndexStore, RootConflictError


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


def _single(tmp_path: Path, name: str) -> tuple[Path, RepositoryState]:
    repository = tmp_path / "repository"
    _copy_version(name, "v1", repository)
    return repository, scan_repository(repository)


def _symbol(state: RepositoryState, qualified_name: str):
    return next(item for item in state.symbols if item.qualified_name == qualified_name)


def _plan(previous: RepositoryState, current: RepositoryState):
    return calculate_invalidation(previous, current, diff_repository_states(previous, current))


def _has_obligation(plan: object, reason: InvalidationReason, subject_id: str) -> bool:
    return any(item.reason_code == reason.value and item.subject_id == subject_id for item in plan.obligations)  # type: ignore[attr-defined]


def test_formatting_and_unrelated_edit_fixtures_preserve_stable_identity_and_bound_delta(tmp_path: Path) -> None:
    formatting_before, formatting_after = _pair(tmp_path / "formatting", "formatting_identity")
    old, new = _symbol(formatting_before, "module.stable"), _symbol(formatting_after, "module.stable")
    assert (old.stable_id, old.version_cid) == (new.stable_id, new.version_cid)
    assert diff_repository_states(formatting_before, formatting_after).unchanged_symbol_ids == tuple(
        item.stable_id for item in formatting_before.symbols
    )

    unrelated_before, unrelated_after = _pair(tmp_path / "unrelated", "unrelated_edit")
    stable_before, stable_after = _symbol(unrelated_before, "module.stable"), _symbol(unrelated_after, "module.stable")
    changed_before, changed_after = _symbol(unrelated_before, "module.changed"), _symbol(unrelated_after, "module.changed")
    delta = diff_repository_states(unrelated_before, unrelated_after)
    assert (stable_before.stable_id, stable_before.version_cid) == (stable_after.stable_id, stable_after.version_cid)
    assert changed_before.stable_id in delta.modified_symbol_ids
    assert classify_symbol_change(changed_before, changed_after) == ("body",)
    # Unrelated function edits remain bounded: only the changed symbol is modified.
    assert stable_before.stable_id in delta.unchanged_symbol_ids
    assert set(delta.modified_symbol_ids) == {changed_before.stable_id}


def test_body_and_signature_fixtures_emit_exact_test_and_caller_obligations(tmp_path: Path) -> None:
    before, current = _pair(tmp_path / "body", "body_test_impact")
    target_before, target_current = _symbol(before, "module.target"), _symbol(current, "module.target")
    test_current = _symbol(current, "tests.test_target.test_target")
    caller_current = _symbol(current, "module.caller")
    facets = classify_symbol_change(
        target_before, target_current, previous_edges=before.edges, current_edges=current.edges
    )
    assert "body" in facets
    assert "signature" not in facets
    plan = _plan(before, current)
    assert any(edge.relation == RelationType.TESTED_BY.value for edge in current.edges)
    assert _has_obligation(plan, InvalidationReason.STALE_TEST_RECEIPT, test_current.stable_id)
    assert not _has_obligation(plan, InvalidationReason.CALLER_SIGNATURE_MISMATCH, caller_current.stable_id)

    before, current = _pair(tmp_path / "signature", "signature_callers")
    service_before, service_current = _symbol(before, "module.service"), _symbol(current, "module.service")
    caller_current = _symbol(current, "module.caller")
    facets = classify_symbol_change(
        service_before, service_current, previous_edges=before.edges, current_edges=current.edges
    )
    assert "signature" in facets
    plan = _plan(before, current)
    assert any(
        edge.relation == RelationType.CALLS.value
        and edge.source_id == caller_current.stable_id
        and edge.target_id == service_current.stable_id
        for edge in current.edges
    )
    assert _has_obligation(plan, InvalidationReason.CALLER_SIGNATURE_MISMATCH, caller_current.stable_id)
    impact = explain_impact(current, service_current.stable_id)
    assert caller_current.stable_id in impact.changed_symbol_ids


def test_schema_and_exception_fixtures_emit_edge_justified_recovery_obligations(tmp_path: Path) -> None:
    before, current = _pair(tmp_path / "schema", "dataclass_schema")
    payload_before, payload_current = _symbol(before, "module.Payload"), _symbol(current, "module.Payload")
    serializer_current = _symbol(current, "module.serialize")
    deserializer_current = _symbol(current, "module.deserialize")
    facets = classify_symbol_change(
        payload_before, payload_current, previous_edges=before.edges, current_edges=current.edges
    )
    assert "schema" in facets
    plan = _plan(before, current)
    # Adapter invalidation is edge-justified through recorded schema/adapter
    # evidence on the public graph (calls/state/schema facets), not by
    # manufacturing SERIALIZES/DESERIALIZES edges in the test.
    assert _has_obligation(plan, InvalidationReason.OBSOLETE_SCHEMA_ADAPTER, serializer_current.stable_id)
    assert _has_obligation(plan, InvalidationReason.OBSOLETE_SCHEMA_ADAPTER, deserializer_current.stable_id)

    before, current = _pair(tmp_path / "exceptions", "exception_recovery")
    service_before, service_current = _symbol(before, "module.service"), _symbol(current, "module.service")
    recovery_current = _symbol(current, "module.recover")
    facets = classify_symbol_change(
        service_before, service_current, previous_edges=before.edges, current_edges=current.edges
    )
    assert "exceptions" in facets
    plan = _plan(before, current)
    assert _has_obligation(plan, InvalidationReason.EXCEPTION_RECOVERY_STALE, recovery_current.stable_id)


def test_fixture_config_and_lockfile_fixtures_invalidate_receipts(tmp_path: Path) -> None:
    before, current = _pair(tmp_path / "fixture", "fixture_config")
    test = next(
        item for item in current.symbols if item.kind == "test" and item.qualified_name.endswith("test_database")
    )
    fixture = next(item for item in current.symbols if item.kind == "fixture" and item.qualified_name.endswith("database"))
    delta = diff_repository_states(before, current)
    plan = calculate_invalidation(before, current, delta)
    assert any(edge.relation == RelationType.CONFIGURED_BY.value and edge.source_id == test.stable_id for edge in current.edges)
    assert fixture.stable_id in delta.modified_symbol_ids
    assert any(edge.relation == RelationType.USES_FIXTURE.value and edge.target_id == fixture.stable_id for edge in current.edges)
    assert delta.modified_artifact_ids
    assert _has_obligation(plan, InvalidationReason.STALE_TEST_RECEIPT, test.stable_id)

    before, current = _pair(tmp_path / "lock", "lock_environment")
    delta = diff_repository_states(before, current)
    plan = calculate_invalidation(before, current, delta)
    lock = next(item for item in current.artifacts if item.path == "requirements.txt")
    assert lock.artifact_id in delta.modified_artifact_ids
    assert _has_obligation(plan, InvalidationReason.ENVIRONMENT_RECEIPT_STALE, lock.artifact_id)


def test_dynamic_and_monkey_patch_fixtures_remain_honestly_opaque(tmp_path: Path) -> None:
    _repo, dynamic = _single(tmp_path / "dynamic", "dynamic_import")
    loader = _symbol(dynamic, "module.load")
    assert loader.confidence == "conservative"
    assert any(
        edge.relation == RelationType.CALLS.value and edge.confidence == "conservative"
        for edge in dynamic.edges
        if edge.source_id == loader.stable_id
    )
    explanation = explain_symbol(dynamic, loader.stable_id)
    assert explanation.symbol.stable_id == loader.stable_id
    assert explanation.outgoing_edges or explanation.limitations

    _repo, patched = _single(tmp_path / "patched", "monkey_patch")
    target, method = _symbol(patched, "module.Target"), _symbol(patched, "module.Target.method")
    assert target.confidence == method.confidence == "opaque"
    assert "monkey_patch" in method.metadata["confidence_reasons"]


def test_deletion_rename_and_identical_root_fixtures_are_deterministic(tmp_path: Path) -> None:
    before, current = _pair(tmp_path / "rename", "deletion_rename")
    old_name, new_name = _symbol(before, "module.old_name"), _symbol(current, "module.new_name")
    deleted = _symbol(before, "module.deleted")
    delta = diff_repository_states(before, current)
    assert {old_name.stable_id, deleted.stable_id} <= set(delta.deleted_symbol_ids)
    assert new_name.stable_id in delta.added_symbol_ids
    assert any(
        candidate["previous_symbol_id"] == old_name.stable_id
        and candidate["current_symbol_id"] == new_name.stable_id
        and candidate["confidence"] == "heuristic"
        for candidate in delta.rename_candidates
    )

    # Identical repository bytes on the same path yield an identical state root
    # for two cold scans (determinism).  Filesystem repository identity is
    # path-bound, so separate temporary copies legitimately differ.
    repository, first = _single(tmp_path / "identical", "identical_roots")
    second = scan_repository(repository)
    assert first.state_cid == second.state_cid
    assert diff_repository_states(first, second).delta_cid == diff_repository_states(first, first).delta_cid


def test_persistence_fixture_recovers_interruption_and_serializes_concurrent_writers(tmp_path: Path) -> None:
    before, current = _pair(tmp_path / "persistence", "persistence_recovery")
    store = LocalSemanticIndexStore(tmp_path / "store")
    old, successor = store.store_state(before), store.store_state(current)
    store.compare_and_swap_root(before.repository_id, None, old)
    interrupted = store.roots_root / ".root-interrupted"
    interrupted.write_bytes(b"partial")
    assert store.current_root(before.repository_id) == old
    assert store.recover(before.repository_id) == (interrupted,)
    assert store.current_root(before.repository_id) == old

    alternate = store.store_state(replace(current, extractor_version="fixture-alternate"))
    outcomes: list[str] = []
    barrier = threading.Barrier(2)

    def publish(candidate: str) -> None:
        barrier.wait()
        try:
            outcomes.append(store.compare_and_swap_root(before.repository_id, old, candidate))
        except RootConflictError:
            outcomes.append("conflict")

    threads = [threading.Thread(target=publish, args=(candidate,)) for candidate in (successor, alternate)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sorted(outcomes).count("conflict") == 1
    assert store.current_root(before.repository_id) in {successor, alternate}


def test_acceptance_module_does_not_construct_dependency_edges() -> None:
    """Public end-to-end acceptance must not hand-author dependency edges."""
    source = Path(__file__).read_text(encoding="utf-8")
    # Build the needle without embedding the forbidden constructor call text.
    edge_type = "Dependency" + "Edge"
    assert f"{edge_type}(" not in source
    assert f"import {edge_type}" not in source
    assert f"models import {edge_type}" not in source
