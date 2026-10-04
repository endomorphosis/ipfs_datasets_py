"""Authored adapter controls plus isolated native reservation contention."""
from dataclasses import replace
from types import SimpleNamespace

import pytest

from ipfs_datasets_py.logic.security_ir import bounded_header_checker as module
from ipfs_datasets_py.logic.backends.codebase_process import BoundedStdinObservation
from ipfs_datasets_py.logic.ir_core.protocols import ExecutionBounds


class Signal:
    cancelled = False
    error = False

    def is_set(self):
        if self.error:
            raise OSError("authored status failure")
        return self.cancelled


class Child:
    def __init__(self, parent):
        self.parent = parent
        self.signal = Signal()

    def combined_cancellation_signal(self, external):
        return self.signal

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.parent.release_count += 1


class Parent(module.ResourceLease):
    def __init__(self):
        self.signal = Signal()
        self.requests = []
        self.children = []
        self.release_count = 0
        self.on_acquire = lambda: None

    def combined_cancellation_signal(self, external):
        return self.signal

    def acquire_child(self, **request):
        self.requests.append(request)
        self.on_acquire()
        child = Child(self)
        self.children.append(child)
        return child


@pytest.fixture
def setup(monkeypatch):
    parent = Parent()
    clock = SimpleNamespace(now=100.0)
    monkeypatch.setattr(module, "time", SimpleNamespace(monotonic=lambda: clock.now))
    monkeypatch.setattr(module, "_supported_platform", lambda: None)
    monkeypatch.setattr(module.shutil, "which", lambda exe: "/usr/bin/true")
    calls = []

    def execute(argv, text, **kwargs):
        calls.append((argv, text, kwargs))
        return BoundedStdinObservation(stdout="Z3 version 4.15.3\n" if argv[-1] == "-version" else "unsat\n")

    monkeypatch.setattr(module, "run_bounded_stdin_tool", execute)
    return SimpleNamespace(parent=parent, clock=clock, calls=calls, execute=execute,
        make=lambda **kwargs: module.bounded_header_runner("z3", parent_lease=parent,
            remaining_seconds=kwargs.pop("remaining_seconds", lambda: 20.0), **kwargs),
        bounds=ExecutionBounds(timeout_ms=5000, max_memory_bytes=128*1024**2,
            max_output_bytes=65536, max_steps=1234))


def test_same_script_bounded_version_and_query_share_native_child(setup):
    runner = setup.make()
    script = "; preserve\n(check-sat)\n"
    result = runner(script, setup.bounds)
    assert result.stdout == "unsat\n" and result.solver_version == "Z3 version 4.15.3"
    assert setup.calls[1][1] == script
    assert setup.calls[1][0][-3:] == ["-in", "-smt2", "rlimit=1234"]
    assert len(setup.parent.requests) == setup.parent.release_count == 1
    request = setup.parent.requests[0]
    assert request["cpu_slots"] == request["child_process_slots"] == 1
    assert request["memory_mb"] == 128 and request["lane"] == module.ResourceLane.VALIDATION
    for _, _, call in setup.calls:
        limits = call["limits"]
        assert limits.memory_bytes == limits.resident_memory_bytes == 128*1024**2
        assert limits.max_output_bytes == 65536 and limits.max_input_bytes == 1048576
        assert limits.timeout_seconds == 5.0
    runner(script, setup.bounds)
    assert len(setup.calls) == 3  # Version is cached only in this factory.
    setup.make()(script, setup.bounds)
    assert len(setup.calls) == 5


def test_version_time_reduces_query_budget(setup, monkeypatch):
    def execute(*args, **kwargs):
        answer = setup.execute(*args, **kwargs)
        if args[0][-1] == "-version":
            setup.clock.now += 1.25
        return answer
    monkeypatch.setattr(module, "run_bounded_stdin_tool", execute)
    setup.make()("(check-sat)", setup.bounds)
    assert setup.calls[0][2]["limits"].timeout_seconds == 5
    assert setup.calls[1][2]["limits"].timeout_seconds == 3.75


def test_admission_wait_is_separate_from_query_execution_budget(setup):
    setup.parent.on_acquire = lambda: setattr(setup.clock, "now", 106.0)
    setup.make()("(check-sat)", setup.bounds)
    assert setup.parent.requests[0]["timeout"] == 20.
    assert [row[2]["limits"].timeout_seconds for row in setup.calls] == [5., 5.]
    assert setup.parent.release_count == 1


def test_admission_time_still_consumes_aggregate_deadline(setup):
    setup.parent.on_acquire = lambda: setattr(setup.clock, "now", 106.0)
    with pytest.raises(module.LeaseTimeoutError):
        setup.make(remaining_seconds=lambda: 6.)("(check-sat)", setup.bounds)
    assert setup.calls == [] and setup.parent.release_count == 1


@pytest.mark.parametrize("profile,expected", [(None, 30.), ("local-benchmark@1", 90.)])
def test_admission_profile_default_preserves_query_cap(setup, monkeypatch, profile, expected):
    if profile is None:
        monkeypatch.delenv("IPFS_DATASETS_PROOF_RESOURCE_PROFILE", raising=False)
    else:
        monkeypatch.setenv("IPFS_DATASETS_PROOF_RESOURCE_PROFILE", profile)
    setup.make(remaining_seconds=lambda: 120.)("(check-sat)", setup.bounds)
    assert setup.parent.requests[0]["timeout"] == expected
    assert all(row[2]["limits"].timeout_seconds == 5. for row in setup.calls)


def test_unknown_admission_profile_cannot_start_solver(setup, monkeypatch):
    monkeypatch.setenv("IPFS_DATASETS_PROOF_RESOURCE_PROFILE", "unknown-profile")
    with pytest.raises(ValueError, match="unknown"):
        setup.make()("(check-sat)", setup.bounds)
    assert setup.parent.requests == setup.calls == []


def test_actual_admission_timeout_keeps_original_native_observation(setup):
    failure = module.LeaseTimeoutError("authored pressure refusal",
        admission_observation={"schema": "resource-admission-observation@1", "primary_gate": "memory_pressure"})

    def refuse():
        raise failure

    setup.parent.on_acquire = refuse
    with pytest.raises(module.LeaseTimeoutError) as caught:
        setup.make()("(check-sat)", setup.bounds)
    assert caught.value is failure
    assert caught.value.header_checker_diagnostic == dict(schema="bounded-header-checker-failure@1",
        phase="child_admission", reason="admission_timeout")
    assert setup.calls == [] and setup.parent.release_count == 0


def test_deadline_after_success_refuses_and_cleans_child(setup, monkeypatch):
    def execute(*args, **kwargs):
        result = setup.execute(*args, **kwargs)
        setup.clock.now += 5.1
        return result
    monkeypatch.setattr(module, "run_bounded_stdin_tool", execute)
    with pytest.raises(module.LeaseTimeoutError) as caught:
        setup.make()("(check-sat)", setup.bounds)
    assert caught.value.header_checker_diagnostic == dict(schema="bounded-header-checker-failure@1",
        phase="version_probe", reason="deadline")
    assert setup.parent.release_count == 1 and len(setup.calls) == 1


def test_aggregate_deadline_cannot_be_extended_by_callback(setup):
    runner = setup.make(remaining_seconds=lambda: 2.0)
    setup.clock.now += 2.1
    for _ in range(2):
        with pytest.raises(module.LeaseTimeoutError):
            runner("(check-sat)", setup.bounds)
    assert not setup.parent.requests  # Failed remaining() also releases the adapter lock.


@pytest.mark.parametrize("field,value", [
    ("returncode", 1), ("returncode", None), ("unavailable", True),
    ("error", "secret must not appear"), ("output_truncated", True),
    ("resource_exhausted", True), ("process_tree_terminated", True),
    ("workspace_cleaned", False),
])
def test_process_refusals_never_become_solver_results(setup, monkeypatch, field, value):
    monkeypatch.setattr(module, "run_bounded_stdin_tool", lambda *a, **k:
        replace(BoundedStdinObservation(stdout="unsat\n"), **{field: value}))
    with pytest.raises(module.BoundedHeaderCheckerError) as error:
        setup.make()("(check-sat)", setup.bounds)
    assert "secret" not in str(error.value) and setup.parent.release_count == 1


@pytest.mark.parametrize("field,exception", [("cancelled", module.LeaseCancelledError),
                                           ("timed_out", module.LeaseTimeoutError)])
def test_terminal_signals_propagate(setup, monkeypatch, field, exception):
    monkeypatch.setattr(module, "run_bounded_stdin_tool", lambda *a, **k:
        replace(BoundedStdinObservation(), **{field: True}))
    with pytest.raises(exception):
        setup.make()("(check-sat)", setup.bounds)
    assert setup.parent.release_count == 1


def test_status_read_failure_uses_process_cancellation_path(setup, monkeypatch):
    observed = []
    def execute(*args, **kwargs):
        setup.parent.children[-1].signal.error = True
        observed.append(kwargs["cancellation"].is_set())
        return BoundedStdinObservation(cancelled=True)
    monkeypatch.setattr(module, "run_bounded_stdin_tool", execute)
    with pytest.raises(module.LeaseCancelledError):
        setup.make()("(check-sat)", setup.bounds)
    assert observed == [True] and setup.parent.release_count == 1


def test_combined_output_bound_includes_both_streams(setup, monkeypatch):
    monkeypatch.setattr(module, "run_bounded_stdin_tool", lambda *a, **k:
        BoundedStdinObservation(stdout="x"*40000, stderr="y"*40000))
    with pytest.raises(module.BoundedHeaderCheckerError, match="combined"):
        setup.make()("(check-sat)", setup.bounds)
    assert setup.parent.release_count == 1


@pytest.mark.parametrize("version", ["", "v\nextra", "v"*1025])
def test_version_missing_or_unbounded_refuses(setup, monkeypatch, version):
    monkeypatch.setattr(module, "run_bounded_stdin_tool", lambda *a, **k:
        BoundedStdinObservation(stdout=version))
    with pytest.raises(module.BoundedHeaderCheckerError, match="version"):
        setup.make()("(check-sat)", setup.bounds)


@pytest.mark.parametrize("script", ["", "\x00", "x"*1048577, "\u00e9"*600000], ids=["empty", "nul", "oversize-ascii", "oversize-utf8"])
def test_input_bounds_refuse_before_admission(setup, script):
    with pytest.raises(module.BoundedHeaderCheckerError):
        setup.make()(script, setup.bounds)
    assert setup.parent.requests == setup.calls == []


@pytest.mark.parametrize("change", [{"max_memory_bytes":129*1024**2}, {"max_output_bytes":65537}])
def test_unsupported_larger_profile_refuses(setup, change):
    with pytest.raises(module.BoundedHeaderCheckerError):
        setup.make()("(check-sat)", replace(setup.bounds, **change))
    assert not setup.parent.requests


def test_parent_cancellation_refuses_before_admission(setup):
    runner = setup.make()
    setup.parent.signal.cancelled = True
    with pytest.raises(module.LeaseCancelledError):
        runner("(check-sat)", setup.bounds)
    assert setup.parent.requests == setup.calls == []


def test_explicit_platform_refusal(monkeypatch):
    monkeypatch.setattr(module, "sys", SimpleNamespace(platform="darwin"))
    with pytest.raises(module.BoundedHeaderCheckerError, match="Linux"):
        module._supported_platform()


def test_fake_lease_cannot_request_required_profile():
    with pytest.raises(TypeError, match="native"):
        module.bounded_header_runner("z3", parent_lease=object(), remaining_seconds=lambda: 1)


def test_default_bounds_are_outside_explicit_header_profile(setup):
    with pytest.raises(module.BoundedHeaderCheckerError, match="profile"):
        setup.make()("(check-sat)", ExecutionBounds())
    assert not setup.parent.requests


@pytest.mark.parametrize("value", [True, float("inf"), float("nan"), "1"])
def test_invalid_remaining_value_refuses(setup, value):
    with pytest.raises(module.BoundedHeaderCheckerError):
        setup.make(remaining_seconds=lambda: value)


def test_native_reservation_wait_recovers_without_renewing_aggregate_deadline(tmp_path, monkeypatch, record_property):
    """Real scheduler/Z3 and elapsed time; no induced or claimed host PSI recovery."""
    import json
    import os
    import shutil
    import threading
    import time
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.resource_scheduler import (
        GlobalResourceScheduler, ResourceSchedulerConfig,
    )

    z3 = shutil.which("z3")
    assert z3 is not None, "native reservation control requires installed Z3"
    monkeypatch.delenv("IPFS_DATASETS_PROOF_RESOURCE_PROFILE", raising=False)
    # This isolated accounting ledger models reservation contention only. It
    # deliberately has no host-pressure sampler or production profile label.
    scheduler = GlobalResourceScheduler(ResourceSchedulerConfig(
        state_path=tmp_path / "scheduler.json", total_cpu_slots=1,
        total_memory_mb=256, total_child_process_slots=1, lane_reservations={},
        auto_renew_leases=False, poll_interval_seconds=.05))
    observations = []

    class ObservedRunner(module.BoundedToolRunner):
        def run(self, request, **kwargs):
            invoked = time.monotonic()
            result = super().run(request, **kwargs)
            observations.append((invoked, request.limits.timeout_seconds, result))
            return result

    monkeypatch.setattr(module, "BoundedToolRunner", ObservedRunner)
    bounds = ExecutionBounds(timeout_ms=5000, max_steps=100000,
        max_memory_bytes=128 * 1024**2, max_output_bytes=65536)
    release_errors = []
    with scheduler.acquire(lane=module.ResourceLane.SNAPSHOT_EVALUATION,
            cpu_slots=1, memory_mb=256, child_process_slots=1, timeout=1.) as parent:
        blocker = parent.acquire_child(lane=module.ResourceLane.VALIDATION,
            cpu_slots=1, memory_mb=128, child_process_slots=1, timeout=1.)
        started = time.monotonic()
        runner = module.bounded_header_runner(z3, parent_lease=parent,
            remaining_seconds=lambda: 20.)

        def release_reservation():
            try:
                blocker.release()
            except Exception as error:
                release_errors.append(error)

        timer = threading.Timer(6., release_reservation)
        timer.start()
        try:
            result = runner("(set-logic QF_LIA)\n(assert false)\n(check-sat)\n", bounds)
            recovered_at = time.monotonic() - started
            assert result.stdout.strip() == "unsat" and result.solver_version.startswith("Z3 version")
            assert len(observations) == 2 and 5. < recovered_at < 20.
            assert observations[0][0] - started > 5.
            assert all(0 < seconds <= 5. for _, seconds, _ in observations)
            assert sum(row[2].elapsed_seconds for row in observations) < 5.
            assert all(row[2].workspace_cleaned and row[2].returncode == 0 for row in observations)
            assert scheduler.snapshot()["active_child_lease_count"] == 0
            # Reuse this runner after another reservation occupies its slot.
            # A callback returning 20 again cannot renew its captured deadline.
            with parent.acquire_child(lane=module.ResourceLane.VALIDATION,
                    cpu_slots=1, memory_mb=128, child_process_slots=1, timeout=1.):
                with pytest.raises(module.LeaseTimeoutError) as failure:
                    runner("(check-sat)\n", bounds)
            expired_at = time.monotonic() - started
            assert 19.5 <= expired_at < 25.
            assert failure.value.admission_observation is not None
            assert failure.value.header_checker_diagnostic == dict(
                schema="bounded-header-checker-failure@1", phase="child_admission", reason="admission_timeout")
            assert len(observations) == 2  # No process launched by the refused second acquisition.
        finally:
            timer.cancel()
            timer.join(timeout=2.)
            blocker.release()
        assert not timer.is_alive() and not release_errors
    assert scheduler.snapshot()["active_lease_count"] == scheduler.snapshot()["waiting_request_count"] == 0
    for _, _, observed in observations:
        assert type(observed.pid) is int
        with pytest.raises(ProcessLookupError):
            os.kill(observed.pid, 0)
    record_property("controlled_native_contention", json.dumps(dict(
        real_scheduler=True, real_z3=True, simulated_clock=False, host_pressure_recovery_claimed=False,
        scheduled_reservation_release_seconds=6., recovery_elapsed_seconds=recovered_at,
        first_process_started_after_seconds=observations[0][0] - started,
        execution_limits_seconds=[row[1] for row in observations],
        aggregate_deadline_seconds=20., aggregate_expired_after_seconds=expired_at,
        remaining_leases=0, remaining_waiters=0, observed_processes_gone=len(observations))))
