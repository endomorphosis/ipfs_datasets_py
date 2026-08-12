"""Public semantic-index facade contract tests."""

from __future__ import annotations

import inspect
import shutil
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.software_contracts.semantic_index import (
    IncrementalSemanticIndex,
    calculate_invalidation,
    diff_repository_states,
    explain_impact,
    explain_symbol,
    scan_repository,
)
from ipfs_datasets_py.logic.software_contracts.semantic_index.models import RelationType, RepositoryState
from ipfs_datasets_py.logic.software_contracts.semantic_index.persistence import LocalSemanticIndexStore


FIXTURES = Path(__file__).resolve().parents[4] / "fixtures" / "software_contracts" / "incremental_semantic_index"


def test_package_exports_exact_public_api() -> None:
    import ipfs_datasets_py.logic.software_contracts.semantic_index as api

    assert api.__all__ == [
        "IncrementalSemanticIndex", "scan_repository", "diff_repository_states",
        "calculate_invalidation", "explain_symbol", "explain_impact", "watch_repository",
    ]
    assert list(inspect.signature(scan_repository).parameters) == ["repo_path", "previous_state"]


def test_functional_api_scans_and_composes_deterministically(tmp_path) -> None:
    source = tmp_path / "module.py"
    source.write_text("def value() -> int:\n    return 1\n", encoding="utf-8")
    previous = scan_repository(tmp_path)
    current = scan_repository(tmp_path, previous)

    assert current == previous
    delta = diff_repository_states(previous, current)
    assert delta.previous_state_cid == previous.state_cid
    assert calculate_invalidation(previous, current, delta).obligations == ()
    symbol_id = next(symbol.stable_id for symbol in current.symbols if symbol.qualified_name == "module.value")
    assert explain_symbol(current, symbol_id).symbol.stable_id == symbol_id
    assert symbol_id in explain_impact(current, symbol_id).changed_symbol_ids


def test_facade_retains_state_and_persists_only_when_explicitly_requested(tmp_path) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    (repository / "module.py").write_text("value = 1\n", encoding="utf-8")
    store_root = tmp_path / "store"
    store = LocalSemanticIndexStore(store_root)
    index = IncrementalSemanticIndex(store=store)
    before = sorted(path.relative_to(store_root) for path in store_root.rglob("*"))

    state = index.scan_repository(repository)
    assert index.current_state == state
    assert sorted(path.relative_to(store_root) for path in store_root.rglob("*")) == before

    state_cid = index.store_state(state)
    assert index.load_state(state_cid) == state
    assert index.current_root(state.repository_id) is None
    assert index.publish_state(state) == state_cid
    assert index.current_root(state.repository_id) == state_cid


def test_facade_requires_explicit_persistence_capability() -> None:
    index = IncrementalSemanticIndex()
    with pytest.raises(RuntimeError, match="explicitly injected"):
        index.store_state(RepositoryState("repository"))


def test_public_scan_unifies_pytest_identity_and_commits_resolved_graph(tmp_path) -> None:
    """scan_repository alone returns the resolved public graph required by ISI-036."""
    repository = tmp_path / "repository"
    shutil.copytree(FIXTURES / "pytest_identity" / "v1", repository)
    state = scan_repository(repository)

    tests = [item for item in state.symbols if item.kind == "test"]
    fixtures = [item for item in state.symbols if item.kind == "fixture"]
    assert tests and fixtures
    # One identity per logical binding: never a parallel function for a test/fixture QN.
    for item in (*tests, *fixtures):
        clones = [symbol for symbol in state.symbols if symbol.qualified_name == item.qualified_name]
        assert len(clones) == 1
        assert clones[0].kind in {"test", "fixture"}

    service = next(item for item in state.symbols if item.qualified_name == "pkg.service.service")
    test = next(item for item in state.symbols if item.qualified_name == "tests.test_service.test_service")
    assert any(
        edge.relation == RelationType.CALLS.value
        and edge.source_id == test.stable_id
        and edge.target_id == service.stable_id
        and edge.metadata.get("resolution") == "definite"
        for edge in state.edges
    )
    assert not any(
        edge.relation == RelationType.CALLS.value
        and edge.source_id == test.stable_id
        and edge.target_id.startswith("lexical:")
        and "service" in edge.target_id
        for edge in state.edges
    )

    # Autouse, usefixtures, and scoped same-named fixtures.
    unit_test = next(
        item for item in state.symbols
        if item.kind == "test" and item.qualified_name.endswith(".test_unit_shared")
    )
    unit_shared = next(
        item for item in fixtures
        if "unit" in item.module_path
        and (
            item.metadata.get("fixture_name") == "shared"
            or item.qualified_name.endswith(".shared")
        )
    )
    uses = [
        edge for edge in state.edges
        if edge.relation == RelationType.USES_FIXTURE.value and edge.source_id == unit_test.stable_id
    ]
    assert any(edge.target_id == unit_shared.stable_id for edge in uses)

    # Marker values participate in the test version projection.
    assert "pytest" in test.annotations
    markers = test.annotations["pytest"].get("markers") or test.annotations["pytest"].get("function_markers")
    assert markers
    assert any("timeout" in str(marker) for marker in markers)

    # Round-trip durability of the committed public state.
    restored = RepositoryState.from_dict(state.to_dict())
    assert restored == state

    # Facade path commits the same resolved state.
    index = IncrementalSemanticIndex()
    via_facade = index.scan_repository(repository)
    assert via_facade.state_cid == state.state_cid
