"""Bounded job queues, shared admission and real overlapping native checkers."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import shutil
import threading
import time

import pytest

from ipfs_datasets_py.logic.software_contracts import codebase_integer_workers as workers
from ipfs_datasets_py.logic.software_contracts import codebase_integer_profile as profile
from ipfs_datasets_py.logic.software_contracts.content import cid_for_structured
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import resource_scheduler as schedulers
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.proof_resource_safety import ProofHostResources

SOURCE = b"def increment(n: int) -> int:\n    return n + 1\n"
NATIVE = pytest.mark.skipif(not shutil.which("z3") or not shutil.which("cvc5"), reason="native Z3/CVC5 unavailable")


def jobs(count=4):
    return [workers.IntegerCheckJob(str(n), SOURCE,
        profile.IntegerOffsetContract("counter.py", "increment", "n", n + 1), "snapshot:fixture") for n in range(count)]


@pytest.fixture
def admitted(tmp_path):
    healthy = ProofHostResources(8, 8192, 8192)
    pressure = [healthy]
    owner = schedulers.GlobalResourceScheduler(schedulers.ResourceSchedulerConfig.for_proof_host(
        state_path=tmp_path / "resources.json", proof_resource_sampler=lambda: pressure[0],
        lane_reservations={}, auto_renew_leases=False, poll_interval_seconds=0.005,
        proof_backoff_seconds=0.02,
    ))
    with owner.acquire("orchestration", cpu_slots=2, memory_mb=1536,
                       child_process_slots=2, timeout=0) as parent:
        yield owner, parent, pressure, healthy
        state = owner.snapshot()
        assert state["active_lease_count"] == 1 and state["waiting_request_count"] == 0
    assert owner.snapshot()["active_lease_count"] == 0


@NATIVE
def test_real_native_work_overlaps_with_bounded_queue_and_ordered_results(admitted, monkeypatch):
    owner, parent, _, _ = admitted
    barrier = threading.Barrier(2)
    lock = threading.Lock()
    first_checks = set()
    intervals = []
    observations = []
    queue_peaks = []
    original = profile.run_bounded_stdin_tool
    allocated = owner.snapshot()["allocated"]
    class CountedExecutor(ThreadPoolExecutor):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            self.outstanding = 0
        def submit(self, *args, **kwargs):
            with lock:
                self.outstanding += 1
                queue_peaks.append(self.outstanding)
            future = super().submit(*args, **kwargs)
            def completed(_):
                with lock:
                    self.outstanding -= 1
            future.add_done_callback(completed)
            return future
    def observed(argv, text, **kwargs):
        if "(check-sat)" not in text:
            return original(argv, text, **kwargs)
        ident = threading.get_ident()
        with lock:
            first = ident not in first_checks
            first_checks.add(ident)
        if first:
            barrier.wait(timeout=5)
        state = owner.snapshot()
        assert state["allocated"] == allocated and state["active_root_lease_count"] == 1
        observations.append(state["active_lease_count"])
        started = time.monotonic()
        result = original(argv, text, **kwargs)
        with lock:
            intervals.append((started, time.monotonic(), ident))
        return result
    monkeypatch.setattr(workers, "ThreadPoolExecutor", CountedExecutor)
    monkeypatch.setattr(profile, "run_bounded_stdin_tool", observed)
    result = workers.run_integer_checks(jobs(), parent_lease=parent, max_workers=2)
    assert [row["job_id"] for row in result] == ["0", "1", "2", "3"]
    assert [row["status"] for row in result] == ["proved", "refuted", "refuted", "refuted"]
    assert max(queue_peaks) == 2
    assert max(observations) == 5  # owner, two admitted workers, two native descendants
    assert len(first_checks) == 2
    assert any(a[2] != b[2] and max(a[0], b[0]) < min(a[1], b[1])
               for a in intervals for b in intervals)
    for row in result:
        assert row["checks"]["compiled_cid"] == cid_for_structured(row["compiled"])
        assert all(item["version"] and item["workspace_cleaned"] for item in row["checks"]["solvers"])
        assert not row["checks"]["kernel_checked"]


@pytest.mark.parametrize("kind", ["empty", "generator", "too_many", "same_id", "same_identity", "foreign_job"])
def test_invalid_batches_never_start_a_worker(admitted, monkeypatch, kind):
    _, parent, _, _ = admitted
    batch = jobs(2)
    if kind == "empty": batch = []
    elif kind == "generator": batch = (item for item in batch)
    elif kind == "too_many": batch = jobs(65)
    elif kind == "same_id": batch[1] = replace(batch[1], job_id=batch[0].job_id)
    elif kind == "same_identity": batch[1] = replace(batch[0], job_id="different-name")
    else: batch[1] = batch[1].__dict__ if hasattr(batch[1], "__dict__") else {"job_id": "fake"}
    monkeypatch.setattr(workers, "ThreadPoolExecutor", lambda **kwargs: pytest.fail("invalid batch allocated threads"))
    with pytest.raises(workers.IntegerWorkerError):
        workers.run_integer_checks(batch, parent_lease=parent, max_workers=2)


@pytest.mark.parametrize("field,value", [("job_id", ""), ("job_id", " space "), ("job_id", "new\nline"),
    ("source", "text"), ("source", b"x" * 65537), ("contract", {}), ("revision", ""), ("revision", "x\x00")])
def test_job_records_are_closed_and_bounded(field, value):
    with pytest.raises(workers.IntegerWorkerError):
        replace(jobs(1)[0], **{field: value})


@pytest.mark.parametrize("option", [{"max_workers": True}, {"max_workers": 0}, {"max_workers": 33},
    {"timeout_seconds": True}, {"timeout_seconds": float("inf")}, {"timeout_seconds": 601},
    {"per_check_timeout_seconds": 0}, {"per_check_timeout_seconds": 121}, {"cancel_event": object()}])
def test_invalid_execution_limits_do_not_start_threads(admitted, monkeypatch, option):
    _, parent, _, _ = admitted
    monkeypatch.setattr(workers, "ThreadPoolExecutor", lambda **kwargs: pytest.fail("invalid bounds allocated threads"))
    arguments = dict(parent_lease=parent, max_workers=2)
    arguments.update(option)
    with pytest.raises(workers.IntegerWorkerError):
        workers.run_integer_checks(jobs(2), **arguments)


@pytest.mark.parametrize("cpu,memory,processes", [(1,1536,2), (2,1024,2), (2,1536,1)])
def test_parent_envelope_must_cover_every_worker(admitted, monkeypatch, cpu, memory, processes):
    _, parent, _, _ = admitted
    monkeypatch.setattr(workers, "ThreadPoolExecutor", lambda **kwargs: pytest.fail("insufficient envelope allocated threads"))
    with parent.acquire_child(cpu_slots=cpu, memory_mb=memory, child_process_slots=processes, timeout=0) as small:
        with pytest.raises(workers.IntegerWorkerError, match="parent requires"):
            workers.run_integer_checks(jobs(2), parent_lease=small, max_workers=2)


def test_unsupported_sources_return_explicit_ordered_records_without_checkers(admitted, monkeypatch):
    _, parent, _, _ = admitted
    batch = [replace(item, source=b"def increment(n):\n    return n + 1\n") for item in jobs(4)]
    monkeypatch.setattr(workers, "execute_integer_offset", lambda *args, **kwargs: pytest.fail("unsupported source ran checkers"))
    result = workers.run_integer_checks(batch, parent_lease=parent, max_workers=2)
    assert [row["job_id"] for row in result] == [item.job_id for item in batch]
    assert all(row["status"] == "unsupported" and row["checks"] is row["compiled"] is None
               and row["diagnostics"] for row in result)


def test_external_pressure_blocks_compilation_and_cleans_all_waiters(admitted, monkeypatch):
    owner, parent, pressure, healthy = admitted
    pressure[0] = replace(healthy, memory_stall_percent=10)
    monkeypatch.setattr(workers, "compile_integer_offset", lambda *args, **kwargs: pytest.fail("pressure allowed compilation"))
    with pytest.raises(schedulers.LeaseTimeoutError):
        workers.run_integer_checks(jobs(), parent_lease=parent, max_workers=2, timeout_seconds=0.1)
    assert owner.snapshot()["waiting_request_count"] == 0


@pytest.mark.parametrize("termination", ["cancel", "deadline", "failure"])
def test_batch_termination_signals_and_joins_all_active_workers(admitted, monkeypatch, termination):
    owner, parent, _, _ = admitted
    entered = threading.Barrier(2)
    external = threading.Event()
    finished = []
    def executing(compiled, *, cancel_event, **kwargs):
        try:
            entered.wait(timeout=2)
            if termination == "failure" and compiled.contract.offset == 1:
                raise RuntimeError("injected worker failure")
            if termination == "cancel":
                external.set()
            deadline = time.monotonic() + 3
            while not cancel_event.is_set() and time.monotonic() < deadline:
                external.wait(0.005)
            assert cancel_event.is_set(), "sibling work did not receive cancellation"
            raise schedulers.LeaseCancelledError("worker observed cancellation")
        finally:
            finished.append(compiled.contract.cid)
    monkeypatch.setattr(workers, "execute_integer_offset", executing)
    error = {"cancel": schedulers.LeaseCancelledError, "deadline": schedulers.LeaseTimeoutError,
             "failure": RuntimeError}[termination]
    with pytest.raises(error):
        workers.run_integer_checks(jobs(4), parent_lease=parent, max_workers=2, cancel_event=external,
                                   timeout_seconds=0.15 if termination == "deadline" else 3)
    assert len(finished) == 2  # unsubmitted jobs never start after termination
    assert owner.snapshot()["active_lease_count"] == 1
    assert not any(thread.name.startswith("integer-check") for thread in threading.enumerate())


def test_sibling_stop_signal_does_not_hide_original_worker_failure(admitted, monkeypatch):
    _, parent, _, _ = admitted
    original_wait = workers.wait
    def failed(*args, **kwargs):
        raise RuntimeError("primary checker failure")
    def cancelled_while_waiting(*args, **kwargs):
        original_wait(*args, **kwargs)
        raise schedulers.LeaseCancelledError("concurrent sibling stop")
    monkeypatch.setattr(workers, "compile_integer_offset", failed)
    monkeypatch.setattr(workers, "wait", cancelled_while_waiting)
    with pytest.raises(RuntimeError, match="primary checker failure"):
        workers.run_integer_checks(jobs(2), parent_lease=parent, max_workers=2)


@NATIVE
def test_pressure_recovery_resumes_native_work_without_new_root(admitted):
    owner, parent, pressure, healthy = admitted
    pressure[0] = replace(healthy, memory_stall_percent=10)
    outputs = []
    errors = []
    def run():
        try:
            outputs.extend(workers.run_integer_checks(jobs(2), parent_lease=parent, max_workers=2, timeout_seconds=5))
        except BaseException as error:
            errors.append(error)
    thread = threading.Thread(target=run)
    thread.start()
    try:
        deadline = time.monotonic() + 1
        while not owner.snapshot()["proof_backoff"] and time.monotonic() < deadline:
            time.sleep(0.005)
        state = owner.snapshot()
        assert state["proof_backoff"]["reason"] == "proof_memory_stall"
        assert state["active_lease_count"] == state["active_root_lease_count"] == 1
        assert not outputs
        pressure[0] = healthy
    finally:
        pressure[0] = healthy
        thread.join(6)
    assert not thread.is_alive() and not errors
    assert [item["status"] for item in outputs] == ["proved", "refuted"]
