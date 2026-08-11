"""Public semantic-index facade contract tests."""

from __future__ import annotations

import inspect

import pytest

from ipfs_datasets_py.logic.software_contracts.semantic_index import (
    IncrementalSemanticIndex,
    calculate_invalidation,
    diff_repository_states,
    explain_impact,
    explain_symbol,
    scan_repository,
)
from ipfs_datasets_py.logic.software_contracts.semantic_index.models import RepositoryState
from ipfs_datasets_py.logic.software_contracts.semantic_index.persistence import LocalSemanticIndexStore


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
