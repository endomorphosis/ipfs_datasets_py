"""Generic prover launch admission against real, isolated shared schedulers.

Pressure samples are synthetic; these tests neither exhaust host resources nor
change the user's scheduler. Small real processes exercise cleanup ordering.
"""
from dataclasses import replace
from pathlib import Path
import sys
import threading
import time
from types import SimpleNamespace

import pytest

from ipfs_datasets_py.logic.backends import resource_admission as admission
from ipfs_datasets_py.logic.backends import process as lifecycle
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import resource_scheduler as schedulers
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.proof_resource_safety import ProofHostResources


MIB = 1024 * 1024


@pytest.fixture
def owner(tmp_path):
    healthy = ProofHostResources(8, 8192, 8192, pid_task_limit=8192, available_pid_tasks=8192)
    current = [healthy]

    def sample():
        if isinstance(current[0], Exception):
            raise current[0]
        return current[0]

    config = schedulers.ResourceSchedulerConfig.for_proof_host(
        state_path=tmp_path / "admission-pool.json",
        proof_resource_sampler=sample,
        total_cpu_slots=2,
        total_memory_mb=1024,
        total_child_process_slots=2,
        proof_memory_headroom_mb=64,
        lane_reservations={},
        auto_renew_leases=False,
        proof_backoff_seconds=0.025,
        poll_interval_seconds=0.002,
    )
    return schedulers.GlobalResourceScheduler(config), healthy, current


class Recorder:
    def __init__(self, action=None):
        self.calls = []
        self.action = action

    def execute(self, invocation, cancellation=None):
        self.calls.append((invocation, cancellation))
        if self.action is not None:
            return self.action(invocation, cancellation)
        return lifecycle.RawProcessResult(returncode=0, stdout=b"checked\n")


def request(**limits):
    return lifecycle.ToolRunRequest(
        argv=("synthetic-prover",),
        limits=lifecycle.ToolRunLimits(**{"memory_bytes": 64 * MIB, "timeout_seconds": 2, **limits}),
    )


def make_runner(tmp_path, owner, recorder, **options):
    return admission.ResourceAdmittedToolRunner(
        scheduler=owner[0], executor=recorder, workspace_root=tmp_path / "runs", **options
    )


def assert_idle(scheduler):
    state = scheduler.snapshot()
    assert state["active_lease_count"] == 0
    assert state["waiting_request_count"] == 0


def until(predicate, timeout=2):
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() >= deadline:
            raise AssertionError("bounded wait expired")
        time.sleep(0.003)


def test_construction_and_discovery_do_not_touch_scheduler(tmp_path, monkeypatch):
    def forbidden():
        raise AssertionError("inert construction/probe accessed admission")

    monkeypatch.setattr(admission, "get_global_resource_scheduler", forbidden)
    runner = admission.ResourceAdmittedToolRunner(workspace_root=tmp_path / "runs")
    assert isinstance(runner, lifecycle.BoundedToolRunner)
    assert runner.probe(sys.executable).available
    assert not (tmp_path / "runs").exists()


def test_default_owner_is_safe_and_lease_covers_executor_and_workspace_cleanup(owner, tmp_path, monkeypatch):
    scheduler, _, _ = owner
    monkeypatch.setattr(admission, "get_global_resource_scheduler", lambda: scheduler)
    observations = []

    def execute(invocation, signal):
        state = scheduler.snapshot()
        assert state["active_root_lease_count"] == 1
        assert state["allocated"]["memory_mb"] == 64
        assert state["allocated_child_process_slots"] == 1
        assert invocation.cwd.is_dir()
        assert not signal.is_set()
        observations.append(invocation.cwd)
        return lifecycle.RawProcessResult(returncode=0)

    original_release = scheduler.release

    def release(*args, **kwargs):
        assert observations and not observations[0].exists()
        return original_release(*args, **kwargs)

    monkeypatch.setattr(scheduler, "release", release)
    runner = admission.ResourceAdmittedToolRunner(executor=Recorder(execute), workspace_root=tmp_path / "runs")
    result = runner.run(request())
    assert result.ok and result.workspace_cleaned
    assert scheduler.config.proof_safety_enabled
    assert_idle(scheduler)


@pytest.mark.parametrize("nested", [False, True], ids=["root", "child"])
@pytest.mark.parametrize("changes,reason", [
    ({"available_memory_mb": 32}, "proof_memory_headroom"),
    ({"cpu_stall_percent": 90}, "proof_cpu_stall"),
    ({"memory_stall_percent": 8}, "proof_memory_stall"),
    ({"io_stall_percent": 25}, "proof_io_stall"),
    ({"available_pid_tasks": 0}, "proof_pid_headroom"),
    (None, "proof_resource_telemetry_unknown"),
])
def test_external_pressure_blocks_launch_then_recovers(owner, tmp_path, changes, reason, nested):
    scheduler, healthy, current = owner
    parent = scheduler.acquire("orchestration", cpu_slots=2, memory_mb=256,
                               child_process_slots=2, timeout=0) if nested else None
    recorder = Recorder()
    options = {"parent_lease": parent} if nested else {"scheduler": scheduler}
    runner = admission.ResourceAdmittedToolRunner(executor=recorder, workspace_root=tmp_path / "runs", **options)
    current[0] = replace(healthy, **changes) if changes is not None else OSError("synthetic telemetry failure")
    results = []
    worker = threading.Thread(target=lambda: results.append(runner.run(request())))
    worker.start()
    try:
        until(lambda: scheduler.snapshot()["proof_backoff"].get("reason") == reason)
        assert not recorder.calls
        assert not (tmp_path / "runs").exists()
        assert scheduler.snapshot()["active_lease_count"] == int(nested)
        current[0] = healthy
        worker.join(3)
        assert not worker.is_alive()
        assert len(results) == 1 and results[0].ok
        assert len(recorder.calls) == 1
        assert scheduler.snapshot()["active_lease_count"] == int(nested)
    finally:
        current[0] = healthy
        worker.join(3)
        if parent is not None:
            parent.release()
    assert_idle(scheduler)


def test_admission_deadline_expires_without_workspace_or_launch(owner, tmp_path):
    scheduler, healthy, current = owner
    current[0] = replace(healthy, cpu_stall_percent=90)
    recorder = Recorder()
    result = make_runner(tmp_path, owner, recorder).run(request(timeout_seconds=0.04))
    assert result.timed_out and not result.ok
    assert not recorder.calls
    assert not (tmp_path / "runs").exists()
    assert_idle(scheduler)


def test_admission_wait_is_subtracted_from_execution_deadline(owner, tmp_path):
    scheduler, healthy, current = owner
    current[0] = replace(healthy, cpu_stall_percent=90)
    recorder = Recorder()
    results = []
    runner = make_runner(tmp_path, owner, recorder)
    worker = threading.Thread(target=lambda: results.append(runner.run(request(timeout_seconds=1))))
    worker.start()
    try:
        until(lambda: scheduler.snapshot()["waiting_request_count"] == 1)
        time.sleep(0.08)
        current[0] = healthy
        worker.join(2)
        assert len(results) == 1 and results[0].ok
        assert 0 < recorder.calls[0][0].limits.timeout_seconds < 0.96
    finally:
        current[0] = healthy
        worker.join(2)
    assert_idle(scheduler)


@pytest.mark.parametrize("shape", ["is_set", "is_cancelled", "cancelled"])
def test_pre_cancelled_signal_shapes_do_not_launch(owner, tmp_path, shape):
    signal = type("Signal", (), {shape: True if shape == "cancelled" else lambda self: True})()
    recorder = Recorder()
    result = make_runner(tmp_path, owner, recorder).run(request(), cancellation=signal)
    assert result.cancelled and not result.ok
    assert not recorder.calls
    assert not (tmp_path / "runs").exists()
    assert_idle(owner[0])


def test_cancellation_while_waiting_removes_waiter_without_launch(owner, tmp_path):
    scheduler, healthy, current = owner
    current[0] = replace(healthy, cpu_stall_percent=90)
    cancel = threading.Event()
    recorder = Recorder()
    results = []
    runner = make_runner(tmp_path, owner, recorder)
    worker = threading.Thread(target=lambda: results.append(runner.run(request(), cancellation=cancel)))
    worker.start()
    try:
        until(lambda: scheduler.snapshot()["waiting_request_count"] == 1)
        cancel.set()
        worker.join(2)
        assert len(results) == 1 and results[0].cancelled
        assert not recorder.calls
    finally:
        cancel.set()
        worker.join(3)
    assert_idle(scheduler)


@pytest.mark.parametrize("executor_acknowledges", [False, True])
def test_parent_ownership_is_not_double_charged_and_cancel_reaches_executor(owner, tmp_path, monkeypatch, executor_acknowledges):
    scheduler, _, _ = owner

    def forbidden():
        raise AssertionError("child allocated an unrelated root")

    monkeypatch.setattr(admission, "get_global_resource_scheduler", forbidden)
    with scheduler.acquire("orchestration", cpu_slots=2, memory_mb=256,
                           child_process_slots=2, timeout=0) as parent:
        allocated = scheduler.snapshot()["allocated"]

        def execute(invocation, signal):
            state = scheduler.snapshot()
            assert state["active_lease_count"] == 2
            assert state["active_root_lease_count"] == 1
            assert state["allocated"] == allocated
            assert not signal.is_set()
            parent.cancel()
            assert signal.is_set()
            return lifecycle.RawProcessResult(
                returncode=None if executor_acknowledges else 0,
                cancelled=executor_acknowledges,
            )

        runner = admission.ResourceAdmittedToolRunner(parent_lease=parent, executor=Recorder(execute))
        result = runner.run(request())
        assert result.cancelled
        assert not parent.released
        assert scheduler.snapshot()["active_lease_count"] == 1
    assert_idle(scheduler)


def test_workspace_preparation_consumes_deadline_without_native_launch(owner, tmp_path, monkeypatch):
    recorder = Recorder()
    runner = make_runner(tmp_path, owner, recorder)
    original_write = runner._write_inputs
    clock = [100.0]
    monkeypatch.setattr(admission, "time", SimpleNamespace(monotonic=lambda: clock[0]))

    def delayed_write(*args, **kwargs):
        clock[0] += 2
        return original_write(*args, **kwargs)

    monkeypatch.setattr(runner, "_write_inputs", delayed_write)
    result = runner.run(request(timeout_seconds=1))
    assert result.timed_out and not result.ok
    assert clock[0] == 102.0
    assert result.workspace_cleaned and not recorder.calls
    assert_idle(owner[0])


def test_late_executor_success_does_not_bypass_shared_deadline(owner, tmp_path, monkeypatch):
    clock = [100.0]
    monkeypatch.setattr(admission, "time", SimpleNamespace(monotonic=lambda: clock[0]))

    def late(*args):
        clock[0] += 2
        return lifecycle.RawProcessResult(returncode=0)

    result = make_runner(tmp_path, owner, Recorder(late)).run(request(timeout_seconds=1))
    assert result.timed_out and not result.ok
    assert result.elapsed_seconds >= 2
    assert_idle(owner[0])


@pytest.mark.parametrize("state", ["released", "cancelled", "foreign"])
def test_inactive_or_foreign_parent_refuses_without_new_lease(owner, state):
    scheduler, _, _ = owner
    parent = scheduler.acquire("orchestration", memory_mb=128, child_process_slots=1, timeout=0)
    recorder = Recorder()
    original_pid = parent.owner_pid
    try:
        if state == "released":
            parent.release()
        elif state == "cancelled":
            parent.cancel()
        else:
            parent.owner_pid = -1
        before = scheduler.snapshot()["active_lease_count"]
        result = admission.ResourceAdmittedToolRunner(parent_lease=parent, executor=recorder).run(request())
        assert result.cancelled and not recorder.calls
        assert scheduler.snapshot()["active_lease_count"] == before
    finally:
        parent.owner_pid = original_pid
        parent.release()
    assert_idle(scheduler)


@pytest.mark.parametrize("raised", [OSError("execution failed"), RuntimeError("execution failed"), KeyboardInterrupt()])
def test_executor_exception_releases_after_workspace_cleanup(owner, tmp_path, monkeypatch, raised):
    scheduler, _, _ = owner
    workspaces = []

    def execute(invocation, signal):
        workspaces.append(invocation.cwd)
        raise raised

    original_release = scheduler.release

    def release(*args, **kwargs):
        assert workspaces and not workspaces[0].exists()
        return original_release(*args, **kwargs)

    monkeypatch.setattr(scheduler, "release", release)
    runner = make_runner(tmp_path, owner, Recorder(execute))
    if isinstance(raised, KeyboardInterrupt):
        with pytest.raises(KeyboardInterrupt):
            runner.run(request())
    else:
        result = runner.run(request())
        assert not result.ok and "execution failed" in result.error
    assert_idle(scheduler)


@pytest.mark.parametrize("flag", ["timed_out", "cancelled", "resource_exhausted", "output_truncated", "process_tree_terminated"])
def test_executor_failure_and_cleanup_flags_survive_admission(owner, tmp_path, flag):
    raw = lifecycle.RawProcessResult(returncode=7, **{flag: True})
    result = make_runner(tmp_path, owner, Recorder(lambda *args: raw)).run(request())
    assert result.returncode == 7
    assert getattr(result, flag)
    assert not result.ok
    assert_idle(owner[0])


@pytest.mark.parametrize("rss,expected", [(64 * MIB, 64), (64 * MIB + 1, 65)])
def test_jvm_reserves_rounded_rss_not_virtual_address_space(owner, tmp_path, rss, expected):
    scheduler, _, _ = owner

    def execute(invocation, signal):
        assert scheduler.snapshot()["allocated"]["memory_mb"] == expected
        assert invocation.limits.memory_bytes == 32 * 1024**3
        assert invocation.limits.resident_memory_bytes == rss
        return lifecycle.RawProcessResult(returncode=0)

    value = replace(request(memory_bytes=32 * 1024**3, resident_memory_bytes=rss), runtime=lifecycle.ToolRuntime.JVM)
    assert make_runner(tmp_path, owner, Recorder(execute)).run(value).ok
    assert_idle(scheduler)


@pytest.mark.parametrize("limits", [{"memory_bytes": None}, {"memory_bytes": 2048 * MIB},
                                   {"resident_memory_bytes": 2048 * MIB}])
def test_missing_or_oversized_memory_is_refused_not_silently_reduced(owner, tmp_path, limits):
    recorder = Recorder()
    result = make_runner(tmp_path, owner, recorder).run(request(**limits))
    assert result.resource_exhausted and not result.ok
    assert not recorder.calls
    assert not (tmp_path / "runs").exists()
    assert_idle(owner[0])


@pytest.mark.parametrize("option", ["cpu_slots", "child_process_slots"])
def test_oversized_profile_is_refused_before_launch(owner, tmp_path, option):
    recorder = Recorder()
    result = make_runner(tmp_path, owner, recorder, **{option: 3}).run(request())
    assert result.resource_exhausted and not result.ok
    assert not recorder.calls
    assert_idle(owner[0])


def test_child_oversize_does_not_release_parent(owner, tmp_path):
    scheduler, _, _ = owner
    with scheduler.acquire("orchestration", memory_mb=32, child_process_slots=1, timeout=0) as parent:
        recorder = Recorder()
        runner = admission.ResourceAdmittedToolRunner(parent_lease=parent, executor=recorder)
        result = runner.run(request())
        assert result.resource_exhausted and not recorder.calls
        assert not parent.released
        assert scheduler.snapshot()["active_lease_count"] == 1
    assert_idle(scheduler)


@pytest.mark.parametrize("option", ["cpu_slots", "child_process_slots"])
@pytest.mark.parametrize("value", [0, -1, True, 1.5, "1", None])
def test_invalid_profile_caps_reject_before_scheduler_access(monkeypatch, option, value):
    monkeypatch.setattr(admission, "get_global_resource_scheduler", lambda: pytest.fail("invalid profile accessed pool"))
    with pytest.raises(schedulers.ResourceConfigurationError):
        admission.ResourceAdmittedToolRunner(**{option: value})


def test_parent_and_scheduler_cannot_both_be_selected(owner):
    scheduler, _, _ = owner
    with scheduler.acquire("orchestration", memory_mb=128, child_process_slots=1, timeout=0) as parent:
        with pytest.raises(schedulers.ResourceConfigurationError):
            admission.ResourceAdmittedToolRunner(scheduler=scheduler, parent_lease=parent)
    assert_idle(scheduler)


@pytest.mark.parametrize("option", ["scheduler", "parent_lease"])
def test_foreign_authority_objects_are_rejected(option):
    with pytest.raises(TypeError):
        admission.ResourceAdmittedToolRunner(**{option: object()})


@pytest.mark.parametrize("backend,expected", [
    ("lean", (1, 1)), ("rocq", (1, 1)), ("isabelle", (3, 12)), ("tlc", (1, 1)),
])
def test_adapter_defaults_are_admitted_but_explicit_fake_runner_remains_compatible(monkeypatch, backend, expected):
    from ipfs_datasets_py.logic.backends.kernel.lean import LeanKernelBackend
    from ipfs_datasets_py.logic.backends.kernel.rocq import RocqKernelBackend
    from ipfs_datasets_py.logic.backends.kernel.isabelle import IsabelleKernelBackend
    from ipfs_datasets_py.logic.backends.tla.runners import TLCBackend

    constructors = {"lean": LeanKernelBackend, "rocq": RocqKernelBackend,
                    "isabelle": IsabelleKernelBackend, "tlc": TLCBackend}
    monkeypatch.setattr(admission, "get_global_resource_scheduler", lambda: pytest.fail("backend constructor accessed pool"))
    options = {"jvm_probe": lambda: True, "lazy_install": False} if backend == "tlc" else {}
    default = constructors[backend](**options)
    assert isinstance(default._runner, admission.ResourceAdmittedToolRunner)
    assert (default._runner.cpu_slots, default._runner.child_process_slots) == expected
    fake = lifecycle.BoundedToolRunner(executor=Recorder())
    explicit = constructors[backend](runner=fake, **options)
    assert explicit._runner is fake


@pytest.mark.parametrize("kind,workers", [("default", 1), ("plain", None), ("admitted", 2)])
def test_lean_worker_count_matches_actual_admission_profile(kind, workers):
    from ipfs_datasets_py.logic.backends.kernel.lean import LeanKernelBackend
    from ipfs_datasets_py.logic.ir_core.protocols import ExecutionBounds

    options = {}
    if kind == "plain":
        options["runner"] = lifecycle.BoundedToolRunner(executor=Recorder())
    elif kind == "admitted":
        options["runner"] = admission.ResourceAdmittedToolRunner(cpu_slots=workers, executor=Recorder())
    backend = LeanKernelBackend(**options)
    bounds = ExecutionBounds(max_memory_bytes=128 * MIB)
    value = backend._tool_request("theorem admission_worker : True := by trivial\n", bounds)
    argv = value.argv
    flags = [argument for argument in argv if argument.startswith("-j")]
    assert flags == ([] if workers is None else [f"-j{workers}"])
    if workers is None:
        assert value.limits.memory_bytes == bounds.max_memory_bytes
        assert value.limits.resident_memory_bytes is None
        assert not value.environment
    else:
        assert value.limits.resident_memory_bytes == bounds.max_memory_bytes
        assert bounds.max_memory_bytes < value.limits.memory_bytes < 64 * 1024**3
        assert "-s65536" in argv
        assert value.environment["LEAN_STACK_SIZE_KB"] == "65536"
        assert value.environment["LEAN_NUM_THREADS"] == str(workers)
        assert value.environment["LEAN_MAIN_USE_THREAD"] == "0"


def test_managed_lean_native_request_reserves_requested_residency(owner):
    from ipfs_datasets_py.logic.backends.kernel.lean import LeanKernelBackend
    from ipfs_datasets_py.logic.ir_core.protocols import ExecutionBounds

    scheduler, _, _ = owner

    def execute(invocation, signal):
        assert scheduler.snapshot()["allocated"] == {"cpu_slots": 2, "memory_mb": 128}
        assert invocation.limits.resident_memory_bytes == 128 * MIB
        assert invocation.limits.memory_bytes > scheduler.config.total_memory_mb * MIB
        return lifecycle.RawProcessResult(returncode=0)

    runner = admission.ResourceAdmittedToolRunner(scheduler=scheduler, cpu_slots=2, executor=Recorder(execute))
    backend = LeanKernelBackend(runner=runner)
    value = backend._tool_request("theorem admission_residency : True := by trivial\n",
                                  ExecutionBounds(max_memory_bytes=128 * MIB))
    assert runner.run(value).ok
    assert_idle(scheduler)


@pytest.mark.parametrize("kind,workers", [("default", 1), ("plain", None), ("admitted", 2)])
def test_tlc_worker_count_matches_actual_admission_profile(monkeypatch, kind, workers):
    from ipfs_datasets_py.logic.backends.tla.compiler import GeneratedTLAArtifacts, TLACompileBounds
    from ipfs_datasets_py.logic.backends.tla.runners import TLCBackend

    options = {}
    if kind == "plain":
        options["runner"] = lifecycle.BoundedToolRunner(executor=Recorder())
    elif kind == "admitted":
        options["runner"] = admission.ResourceAdmittedToolRunner(cpu_slots=workers, executor=Recorder())
    backend = TLCBackend(executable="synthetic-tlc", jvm_probe=lambda: True, lazy_install=False, **options)
    captured = []

    def record(value, **kwargs):
        captured.append(value)
        return lifecycle.ToolRunResult(
            interface_version=lifecycle.BOUNDED_TOOL_RUNNER_VERSION,
            runtime=value.runtime, command=value.argv, returncode=0,
            stdout="Model checking completed. No error has been found.\n",
            stderr="", elapsed_seconds=0, output_files={},
        )

    monkeypatch.setattr(backend._runner, "run", record)
    artifacts = GeneratedTLAArtifacts(
        module_name="AdmissionWorkers",
        model_text="---- MODULE AdmissionWorkers ----\nVARIABLE x\nInit == x = 0\nNext == UNCHANGED x\nSafety == x = 0\n====\n",
        tlc_config_text="INIT Init\nNEXT Next\nINVARIANT Safety\n",
        apalache_config_text="INIT Init\nNEXT Next\nINVARIANT Safety\n",
        source_map=(), losses=(), bounds=TLACompileBounds(max_steps=2),
        source_document_id="test:admission-workers", source_kind="state_transition",
        safety_properties=("Safety",), liveness_properties=(), fairness_limitations=(),
    )
    backend.check(artifacts)
    argv = captured[0].argv
    assert ("-workers" in argv) is (workers is not None)
    if workers is not None:
        assert argv[argv.index("-workers") + 1] == str(workers)


@pytest.mark.parametrize("error", [OSError("telemetry unreadable"), ValueError("telemetry malformed")])
def test_default_owner_initialization_failure_refuses_without_launch(tmp_path, monkeypatch, error):
    def unavailable():
        raise error

    monkeypatch.setattr(admission, "get_global_resource_scheduler", unavailable)
    recorder = Recorder()
    runner = admission.ResourceAdmittedToolRunner(executor=recorder, workspace_root=tmp_path / "runs")
    result = runner.run(request())
    assert result.resource_exhausted and not result.ok
    assert not recorder.calls and not (tmp_path / "runs").exists()


def test_cleanup_failure_is_not_returned_as_successfully_cleaned_admission_refusal(owner, tmp_path, monkeypatch):
    original_cleanup = lifecycle.tempfile.TemporaryDirectory.cleanup
    retained = []

    def blocked_cleanup(temporary):
        retained.append(temporary)
        raise PermissionError("synthetic workspace cleanup denied")

    runner = make_runner(tmp_path, owner, Recorder())
    try:
        with monkeypatch.context() as patch:
            patch.setattr(lifecycle.tempfile.TemporaryDirectory, "cleanup", blocked_cleanup)
            with pytest.raises(PermissionError, match="cleanup denied"):
                runner.run(request())
        assert retained and Path(retained[0].name).is_dir()
        assert_idle(owner[0])
    finally:
        for temporary in retained:
            original_cleanup(temporary)


def test_invalid_request_rejected_before_admission(owner, tmp_path, monkeypatch):
    monkeypatch.setattr(owner[0], "acquire", lambda *args, **kwargs: pytest.fail("invalid request entered pool"))
    recorder = Recorder()
    with pytest.raises(lifecycle.ToolProcessError):
        make_runner(tmp_path, owner, recorder).run(replace(request(), argv=("bad\x00argument",)))
    assert not recorder.calls


def test_admission_error_text_and_argv_are_redacted(owner, tmp_path, monkeypatch):
    secret = "test-only-private-value"

    def refuse(*args, **kwargs):
        raise schedulers.ResourceUnavailableError(secret)

    monkeypatch.setattr(owner[0], "acquire", refuse)
    recorder = Recorder()
    value = replace(request(), argv=("synthetic-prover", "--token", secret), secrets=(secret,))
    result = make_runner(tmp_path, owner, recorder).run(value)
    assert result.resource_exhausted
    assert secret not in str(result.to_dict())
    assert not recorder.calls


def test_concurrent_workers_respect_capacity_and_preserve_foreign_owner(owner, tmp_path):
    scheduler, _, _ = owner
    lock = threading.Lock()
    active = 0
    maximum = 0
    seen = []

    def execute(invocation, signal):
        nonlocal active, maximum
        with lock:
            active += 1
            maximum = max(maximum, active)
            seen.append(scheduler.snapshot()["active_root_lease_count"])
        try:
            time.sleep(0.025)
            return lifecycle.RawProcessResult(returncode=0)
        finally:
            with lock:
                active -= 1

    with scheduler.acquire("orchestration", cpu_slots=1, memory_mb=32,
                           child_process_slots=1, timeout=0) as foreign:
        runner = make_runner(tmp_path, owner, Recorder(execute))
        results = []
        workers = [threading.Thread(target=lambda: results.append(runner.run(request()))) for _ in range(5)]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(4)
        assert all(not worker.is_alive() for worker in workers)
        assert len(results) == 5 and all(result.ok for result in results)
        assert maximum == 1 and seen == [2] * 5
        leases = scheduler.active_leases()
        assert len(leases) == 1 and leases[0]["lease_id"] == foreign.lease_id
        assert not foreign.cancelled and not foreign.released
    assert_idle(scheduler)


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux bounded native lifecycle")
def test_real_tool_timeout_stops_process_and_cleans_workspace_before_release(owner, tmp_path, monkeypatch):
    scheduler, _, _ = owner
    original_release = scheduler.release
    roots = tmp_path / "runs"

    def release(*args, **kwargs):
        assert not list(roots.glob("logic-tool-*"))
        return original_release(*args, **kwargs)

    monkeypatch.setattr(scheduler, "release", release)
    runner = admission.ResourceAdmittedToolRunner(scheduler=scheduler, workspace_root=roots)
    value = lifecycle.ToolRunRequest(
        argv=(sys.executable, "-c", "import os,time; print(os.getpid(),flush=True); time.sleep(30)"),
        limits=lifecycle.ToolRunLimits(memory_bytes=128 * MIB, timeout_seconds=0.2),
    )
    result = runner.run(value)
    assert result.timed_out and result.process_tree_terminated
    assert result.workspace_cleaned and not result.ok
    assert result.pid is not None and not Path(f"/proc/{result.pid}").exists()
    assert_idle(scheduler)
