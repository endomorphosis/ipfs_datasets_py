"""Native parallel lease accounting and serialized current-source guards."""
import threading
import time

import pytest

from ipfs_datasets_py.logic.software_contracts import codebase_parallel_resources as parallel
from ipfs_datasets_py.logic.software_contracts import codebase_ir as structural
from ipfs_datasets_py.logic.software_contracts import codebase_source_training as source
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import resource_scheduler as schedulers


@pytest.fixture(scope="module")
def native(tmp_path_factory):
    duckdb = pytest.importorskip("duckdb")
    from ipfs_datasets_py.duckdb_control.codebase_catalog import CodebaseCatalog
    from ipfs_datasets_py.logic.software_contracts.cache import ImmutableCAS
    from ipfs_datasets_py.logic.software_contracts.duckdb_ast_store import DuckDBASTStore
    from ipfs_datasets_py.logic.software_contracts.duckdb_ingest import DuckDBASTIngestor

    root = tmp_path_factory.mktemp("parallel-codebase-resources")
    repository = root / "repository"
    repository.mkdir()
    (repository / "unit.py").write_text("def step(n: int) -> int:\n    return n + 1\n")
    connection = duckdb.connect(str(root / "source.duckdb"), config={"threads": 1, "memory_limit": "64MB"})
    store = DuckDBASTStore(connection=connection)
    artifacts = ImmutableCAS(root / "artifacts")
    index = structural.RepositoryCodebaseIndex(
        ingestor=DuckDBASTIngestor(store=store), artifacts=artifacts,
        catalog=CodebaseCatalog(store, artifacts),
    )
    scheduler = schedulers.GlobalResourceScheduler(schedulers.ResourceSchedulerConfig(
        state_path=root / "resources.json", total_cpu_slots=3,
        total_memory_mb=1536, total_child_process_slots=3,
        lane_reservations={}, auto_renew_leases=False, poll_interval_seconds=.005,
    ))
    head = index.prepare_current(repository, repository_id="test:parallel-resources",
        operation_id="initial", expected_head=None, scheduler=scheduler).head
    yield dict(index=index, repository=repository, head=head, scheduler=scheduler)
    _idle(scheduler)
    connection.close()


def _idle(scheduler):
    state = scheduler.snapshot()
    assert state["active_lease_count"] == state["waiting_request_count"] == 0


def _resources(native, **changes):
    arguments = dict(workers=2, worker_memory_mb=512, control_memory_mb=512,
                     scheduler=native["scheduler"], admission_timeout_seconds=1,
                     timeout_seconds=5)
    arguments.update(changes)
    return parallel.parallel_codebase_resources(native["index"], native["repository"],
                                                native["head"], **arguments)


def test_two_worker_children_overlap_source_observation_without_extra_root(native, monkeypatch):
    original_observe = native["index"].observe_current
    original_snapshot = structural.snapshot_repository
    monitor_lock = threading.Lock()
    active_observations = [0]
    observation_peak = [0]
    observed_states = []
    passed_memory = []

    def tracked_observe(*args, **kwargs):
        passed_memory.append(kwargs["memory_mb"])
        with monitor_lock:
            active_observations[0] += 1
            observation_peak[0] = max(observation_peak[0], active_observations[0])
        try:
            time.sleep(.005)
            return original_observe(*args, **kwargs)
        finally:
            with monitor_lock:
                active_observations[0] -= 1

    def tracked_snapshot(*args, **kwargs):
        observed_states.append(native["scheduler"].snapshot())
        return original_snapshot(*args, **kwargs)

    monkeypatch.setattr(native["index"], "observe_current", tracked_observe)
    monkeypatch.setattr(structural, "snapshot_repository", tracked_snapshot)
    ready = threading.Barrier(3)
    release = threading.Event()
    errors = []
    children = []
    with _resources(native) as (lease, signal, remaining, observe):
        assert (lease.cpu_slots, lease.memory_mb, lease.child_process_slots) == (3, 1536, 3)

        def run():
            try:
                with lease.acquire_child(lane=schedulers.ResourceLane.TRAINER,
                        cpu_slots=1, memory_mb=512, child_process_slots=1,
                        timeout=remaining(), cancel_event=signal) as child:
                    children.append(child)
                    ready.wait(3)
                    assert release.wait(3)
                    assert observe().head == native["head"]
            except BaseException as error:
                errors.append(error)

        threads = [threading.Thread(target=run) for _ in range(2)]
        for thread in threads:
            thread.start()
        try:
            ready.wait(3)
            state = native["scheduler"].snapshot()
            assert state["active_lease_count"] == 3
            assert state["active_root_lease_count"] == 1
            assert state["allocated"]["memory_mb"] == 1536
            assert observe().head == native["head"]
        finally:
            release.set()
            for thread in threads:
                thread.join(4)
        assert not any(thread.is_alive() for thread in threads)
        assert not errors
        assert all(child.released for child in children)
        assert native["scheduler"].snapshot()["active_lease_count"] == 1
    assert observation_peak[0] == 1
    assert passed_memory and set(passed_memory) == {512}
    assert any(state["active_lease_count"] == 4 for state in observed_states)
    assert all(state["active_root_lease_count"] == 1
               and state["allocated"]["memory_mb"] == 1536 for state in observed_states)
    _idle(native["scheduler"])


def test_supplied_parent_keeps_the_same_global_reservation(native):
    owner = native["scheduler"]
    with owner.acquire("orchestration", cpu_slots=3, memory_mb=1536,
                       child_process_slots=3, timeout=0) as parent:
        allocation = owner.snapshot()["allocated"]
        with _resources(native, scheduler=None, parent_lease=parent) as (lease, _, _, observe):
            assert lease.parent_lease_id == parent.lease_id
            assert observe().head == native["head"]
            assert owner.snapshot()["allocated"] == allocation
            assert owner.snapshot()["active_root_lease_count"] == 1
        assert lease.released and not parent.released
        assert owner.snapshot()["active_lease_count"] == 1
    _idle(owner)


@pytest.mark.parametrize("pre_cancelled", [False, True])
def test_external_cancellation_cleans_reservation_and_waiters(native, pre_cancelled):
    event = threading.Event()
    if pre_cancelled:
        event.set()
    with pytest.raises(schedulers.LeaseCancelledError):
        with _resources(native, cancel_event=event) as (_, signal, remaining, _):
            event.set()
            assert signal.is_set()
            remaining()
    _idle(native["scheduler"])


def test_parent_cancellation_reaches_both_live_worker_children(native):
    ready = threading.Barrier(3)
    release = threading.Event()
    errors = []
    children = []
    with pytest.raises(schedulers.LeaseCancelledError):
        with _resources(native) as (lease, signal, remaining, _):
            def run():
                try:
                    with lease.acquire_child(lane=schedulers.ResourceLane.TRAINER,
                            cpu_slots=1, memory_mb=512, child_process_slots=1,
                            timeout=remaining(), cancel_event=signal) as child:
                        children.append(child)
                        ready.wait(3)
                        assert release.wait(3)
                        assert child.combined_cancellation_signal(signal).is_set()
                except BaseException as error:
                    errors.append(error)

            threads = [threading.Thread(target=run) for _ in range(2)]
            for thread in threads:
                thread.start()
            try:
                ready.wait(3)
                assert lease.cancel()
                assert signal.is_set()
                state = native["scheduler"].snapshot()
                assert state["allocated"]["memory_mb"] == 1536
            finally:
                release.set()
                for thread in threads:
                    thread.join(4)
            assert not any(thread.is_alive() for thread in threads)
            assert not errors and len(children) == 2
            assert all(child.released for child in children)
            remaining()
    _idle(native["scheduler"])


def test_source_change_at_exit_fails_and_releases_root(native):
    path = native["repository"] / "unit.py"
    original = path.read_bytes()
    try:
        with pytest.raises(structural.StaleCodebaseError):
            with _resources(native):
                path.write_bytes(original + b"\n# source changed\n")
    finally:
        path.write_bytes(original)
    _idle(native["scheduler"])


def test_expired_overall_deadline_releases_root(native):
    with pytest.raises(schedulers.LeaseTimeoutError):
        with _resources(native, timeout_seconds=.1) as (_, _, remaining, _):
            time.sleep(remaining() + .01)
    _idle(native["scheduler"])


@pytest.mark.parametrize("changes", [
    {"workers": 0}, {"workers": 9}, {"workers": True}, {"workers": 2.0},
    {"worker_memory_mb": 511}, {"worker_memory_mb": True},
    {"control_memory_mb": 511}, {"control_memory_mb": 512.0},
    {"timeout_seconds": 0}, {"timeout_seconds": 601},
    {"timeout_seconds": float("nan")}, {"timeout_seconds": True},
    {"admission_timeout_seconds": -1}, {"admission_timeout_seconds": float("inf")},
    {"limits": {}},
    {"limits": source.CodebaseFeatureTrainingLimits(max_ancestry_bytes=128 * 1024 * 1024)},
])
def test_invalid_controls_reject_before_admission(native, monkeypatch, changes):
    def forbidden(*args, **kwargs):
        pytest.fail("invalid parallel controls accessed resource admission")
    monkeypatch.setattr(parallel, "acquire_codebase_resources", forbidden)
    with pytest.raises(source.CodebaseFeatureTrainingError):
        with _resources(native, **changes):
            pytest.fail("invalid parallel controls entered")
    _idle(native["scheduler"])
