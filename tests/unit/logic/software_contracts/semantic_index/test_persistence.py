"""Persistence invariants for the incremental semantic-index store."""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.software_contracts.semantic_index.models import (
    InvalidationPlan,
    RepositoryState,
    RepositoryStateDelta,
)
from ipfs_datasets_py.logic.software_contracts.semantic_index.persistence import (
    BackendCapabilityError,
    IpfsKitSemanticIndexStore,
    LocalSemanticIndexStore,
    RootConflictError,
    SemanticIndexPersistenceError,
)


def state(repository_id: str, version: str = "1") -> RepositoryState:
    return RepositoryState(repository_id=repository_id, extractor_version=version)


def test_local_store_round_trips_a_verified_state_and_root(tmp_path: Path) -> None:
    store = LocalSemanticIndexStore(tmp_path)
    first = state("repo")
    cid = store.store_state(first)
    assert store.load_state(cid) == first
    assert store.current_root("repo") is None
    assert store.compare_and_swap_root("repo", None, cid) == cid
    assert store.current_root("repo") == cid


def test_local_store_round_trips_deltas_and_plans_by_their_model_cids(tmp_path: Path) -> None:
    store = LocalSemanticIndexStore(tmp_path)
    previous = store.store_state(state("repo", "1"))
    current = store.store_state(state("repo", "2"))
    delta = RepositoryStateDelta(previous_state_cid=previous, current_state_cid=current)
    assert store.load_delta(store.store_delta(delta)) == delta
    plan = InvalidationPlan(previous_state_cid=previous, current_state_cid=current)
    assert store.load_plan(store.store_plan(plan)) == plan


def test_corrupt_immutable_object_and_root_are_rejected(tmp_path: Path) -> None:
    store = LocalSemanticIndexStore(tmp_path)
    cid = store.store_state(state("repo"))
    store.cas.path_for(cid).write_bytes(b"{}")
    with pytest.raises(SemanticIndexPersistenceError):
        store.load_state(cid)

    valid = LocalSemanticIndexStore(tmp_path / "valid")
    cid = valid.store_state(state("repo"))
    valid.compare_and_swap_root("repo", None, cid)
    valid._root_path("repo").write_bytes(b"{}")
    with pytest.raises(SemanticIndexPersistenceError):
        valid.current_root("repo")


def test_interrupted_root_publication_preserves_previous_root_and_recovers(tmp_path: Path) -> None:
    store = LocalSemanticIndexStore(tmp_path)
    old = store.store_state(state("repo", "1"))
    new = store.store_state(state("repo", "2"))
    store.compare_and_swap_root("repo", None, old)
    orphan = store.roots_root / ".root-interrupted"
    orphan.write_bytes(b"incomplete")
    assert store.current_root("repo") == old
    assert store.recover("repo") == (orphan,)
    assert not orphan.exists()
    assert store.current_root("repo") == old
    store.compare_and_swap_root("repo", old, new)


def test_root_cas_allows_one_distinct_racer_and_identical_writers_are_benign(tmp_path: Path) -> None:
    store = LocalSemanticIndexStore(tmp_path)
    old = store.store_state(state("repo", "1"))
    successors = [store.store_state(state("repo", version)) for version in ("2", "3")]
    store.compare_and_swap_root("repo", None, old)
    outcomes: list[str] = []

    def publish(cid: str) -> None:
        try:
            outcomes.append(store.compare_and_swap_root("repo", old, cid))
        except RootConflictError:
            outcomes.append("conflict")

    threads = [threading.Thread(target=publish, args=(cid,)) for cid in successors]
    for thread in threads: thread.start()
    for thread in threads: thread.join()
    assert sorted(outcomes).count("conflict") == 1
    assert store.current_root("repo") in successors
    chosen = store.current_root("repo")
    assert store.compare_and_swap_root("repo", old, chosen) == chosen


class _Backend:
    def __init__(self) -> None:
        self.blocks: dict[str, bytes] = {}
    def put_bytes(self, payload: bytes) -> str:
        from ipfs_datasets_py.logic.software_contracts.content import cid_for_structured
        import json
        cid = cid_for_structured(json.loads(payload))
        self.blocks[cid] = payload
        return cid
    def get_bytes(self, cid: str) -> bytes:
        return self.blocks[cid]


def test_injected_backend_needs_no_daemon_and_verifies_cids() -> None:
    backend = _Backend()
    store = IpfsKitSemanticIndexStore(backend)
    item = state("repo")
    assert store.load_state(store.store_state(item)) == item
    with pytest.raises(BackendCapabilityError):
        store.current_root("repo")
