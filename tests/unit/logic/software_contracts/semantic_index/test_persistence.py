"""Persistence invariants for the incremental semantic-index store."""

from __future__ import annotations

import json
import subprocess
import sys
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
from ipfs_datasets_py.logic.software_contracts.content import canonical_dag_json_bytes


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


def test_roots_reject_noncanonical_records_and_states_from_another_repository(tmp_path: Path) -> None:
    store = LocalSemanticIndexStore(tmp_path)
    foreign = store.store_state(state("repository-b"))
    root_path = store._root_path("repository-a")
    root_path.write_bytes(canonical_dag_json_bytes({
        "schema": "ipfs-datasets.software-contracts.semantic-index-root@1",
        "repository_id": "repository-a",
        "state_cid": foreign,
    }))
    with pytest.raises(SemanticIndexPersistenceError, match="another repository"):
        store.current_root("repository-a")
    with pytest.raises(SemanticIndexPersistenceError, match="another repository"):
        store.compare_and_swap_root("repository-a", None, foreign)

    own = store.store_state(state("repository-a"))
    root_path.write_bytes(json.dumps({
        "schema": "ipfs-datasets.software-contracts.semantic-index-root@1",
        "repository_id": "repository-a",
        "state_cid": own,
    }, indent=2).encode())
    with pytest.raises(SemanticIndexPersistenceError, match="root is invalid"):
        store.current_root("repository-a")


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


def test_root_cas_is_process_safe_for_distinct_subprocess_writers(tmp_path: Path) -> None:
    store = LocalSemanticIndexStore(tmp_path)
    old = store.store_state(state("repo", "1"))
    successors = [store.store_state(state("repo", version)) for version in ("2", "3")]
    store.compare_and_swap_root("repo", None, old)
    program = """
from pathlib import Path
import sys
from ipfs_datasets_py.logic.software_contracts.semantic_index.persistence import LocalSemanticIndexStore, RootConflictError
store = LocalSemanticIndexStore(Path(sys.argv[1]))
try:
    store.compare_and_swap_root('repo', sys.argv[2], sys.argv[3])
except RootConflictError:
    print('conflict')
else:
    print('success')
"""
    processes = [
        subprocess.Popen(
            [sys.executable, "-c", program, str(tmp_path), old, successor],
            cwd=Path.cwd(), text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        for successor in successors
    ]
    results = [process.communicate(timeout=15) for process in processes]
    assert [process.returncode for process in processes] == [0, 0]
    assert sorted(stdout.strip() for stdout, _ in results) == ["conflict", "success"]
    assert store.current_root("repo") in successors


@pytest.mark.parametrize(
    ("point", "visible_new"),
    [
        ("before_object_write", False),
        ("after_object_write", False),
        ("before_transition_write", False),
        ("after_transition_write", False),
        ("before_root_replace", False),
        ("after_root_replace", True),
    ],
)
def test_interruption_boundaries_recover_only_the_last_visible_root(
    tmp_path: Path, point: str, visible_new: bool
) -> None:
    stable = LocalSemanticIndexStore(tmp_path)
    old = stable.store_state(state("repo", "1"))
    stable.compare_and_swap_root("repo", None, old)

    def interrupt(actual: str) -> None:
        if actual == point:
            raise InterruptedError(point)

    interrupted = LocalSemanticIndexStore(tmp_path, interruption_hook=interrupt)
    if point.endswith("object_write"):
        with pytest.raises(InterruptedError):
            interrupted.store_state(state("repo", "2"))
    else:
        new = interrupted.store_state(state("repo", "2"))
        with pytest.raises(InterruptedError):
            interrupted.compare_and_swap_root("repo", old, new)
    recovered = LocalSemanticIndexStore(tmp_path)
    recovered.recover("repo")
    expected = old if point.endswith("object_write") else (new if visible_new else old)
    assert recovered.current_root("repo") == expected


def test_corrupt_transition_fails_closed(tmp_path: Path) -> None:
    store = LocalSemanticIndexStore(tmp_path)
    store.transitions_root.mkdir(exist_ok=True)
    store._transition_path("repo").write_bytes(b"not canonical")
    with pytest.raises(SemanticIndexPersistenceError, match="transition"):
        store.recover()


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


class _RootBackend(_Backend):
    def __init__(self) -> None:
        super().__init__()
        self.roots: dict[str, str] = {}
    def get_root(self, repository_id: str) -> str | None:
        return self.roots.get(repository_id)
    def compare_and_swap_root(self, repository_id: str, expected: str | None, new: str) -> bool:
        if self.roots.get(repository_id) != expected:
            return False
        self.roots[repository_id] = new
        return True


def test_injected_backend_needs_no_daemon_and_verifies_cids() -> None:
    backend = _Backend()
    store = IpfsKitSemanticIndexStore(backend)
    item = state("repo")
    assert store.load_state(store.store_state(item)) == item
    with pytest.raises(BackendCapabilityError):
        store.current_root("repo")


def test_injected_backend_enforces_repository_root_binding() -> None:
    backend = _RootBackend()
    store = IpfsKitSemanticIndexStore(backend)
    own = store.store_state(state("repository-a"))
    assert store.compare_and_swap_root("repository-a", None, own) == own
    foreign = store.store_state(state("repository-b"))
    backend.roots["repository-a"] = foreign
    with pytest.raises(SemanticIndexPersistenceError, match="another repository"):
        store.current_root("repository-a")
    with pytest.raises(SemanticIndexPersistenceError, match="another repository"):
        store.compare_and_swap_root("repository-a", None, foreign)
