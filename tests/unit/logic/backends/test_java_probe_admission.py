"""JVM discovery crosses actual private admission; no workstation load is changed."""
from dataclasses import replace
from pathlib import Path
import json
import os
import subprocess
import sys
import textwrap
import threading
import time
from types import SimpleNamespace

import pytest

from ipfs_datasets_py.logic.backends import process, resource_admission
from ipfs_datasets_py.logic.backends.installers import state_model as java
from ipfs_datasets_py.logic.backends.smt import operation_budget as budget
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import resource_scheduler as schedulers
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.proof_resource_safety import ProofHostResources

BANNER = 'openjdk version "17.0.12" 2024-07-16\nOpenJDK Runtime Environment fixture'
MIB = 1024**2
REAL_EXECUTE = process.SubprocessExecutor.execute


@pytest.fixture
def host(tmp_path, monkeypatch):
    healthy = ProofHostResources(8, 8192, 8192, pid_task_limit=8192, available_pid_tasks=8192)
    current = [healthy]
    def sample():
        if isinstance(current[0], Exception):
            raise current[0]
        return current[0]
    owner = schedulers.GlobalResourceScheduler(schedulers.ResourceSchedulerConfig.for_proof_host(
        state_path=tmp_path / "probe-pool.json", proof_resource_sampler=sample,
        total_cpu_slots=2, total_memory_mb=1024, total_child_process_slots=2,
        proof_memory_headroom_mb=64, lane_reservations={}, auto_renew_leases=False,
        proof_backoff_seconds=.025, poll_interval_seconds=.002))
    monkeypatch.setattr(resource_admission, "get_global_resource_scheduler", lambda: owner)
    monkeypatch.setattr(java, "resolve_java_executable", lambda value=None: (sys.executable, "argument"))
    calls, workspaces = [], []
    action = [lambda invocation, signal: process.RawProcessResult(returncode=0, stderr=BANNER)]
    def execute(self, invocation, cancellation=None):
        state = owner.snapshot()
        assert state["active_lease_count"] > 0
        assert state["allocated"]["memory_mb"] >= 256
        assert invocation.cwd.is_dir()
        assert not cancellation.is_set()
        calls.append((invocation, cancellation, state))
        workspaces.append(invocation.cwd)
        return action[0](invocation, cancellation)
    monkeypatch.setattr(process.SubprocessExecutor, "execute", execute)
    yield SimpleNamespace(owner=owner, healthy=healthy, current=current, calls=calls,
                          action=action, workspaces=workspaces)
    state = owner.snapshot()
    assert state["active_lease_count"] == state["waiting_request_count"] == 0
    assert all(not path.exists() for path in workspaces)
    assert java._JAVA_PROBE_OPERATION.get() is None


def probe(**kwargs):
    return java.probe_java_runtime(java_executable=sys.executable, minimum_major=11, **kwargs)


def until(predicate, timeout=2):
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() >= deadline:
            pytest.fail("bounded fixture wait expired")
        time.sleep(.003)


def test_success_wire_preserved_and_rss_reserved_before_virtual_address_cap(host, monkeypatch):
    for variable in java.JAVA_OPTION_ENV_VARS:
        monkeypatch.setenv(variable, "-Xmx999g -javaagent:injected.jar")
    result = probe()
    assert result.to_dict() == dict(executable=sys.executable, source="argument", minimum_major=11,
        banner=BANNER, major=17, usable=True, reason_code=None)
    invocation, signal, state = host.calls[0]
    assert state["active_root_lease_count"] == 1
    assert state["allocated"]["memory_mb"] == 256
    assert state["allocated_child_process_slots"] == 1
    assert invocation.runtime == process.ToolRuntime.JVM
    assert invocation.argv == (str(Path(sys.executable).resolve()), "-Xms16m", "-Xmx128m", "-Xss1m", "-XX:+UseSerialGC",
        "-XX:ActiveProcessorCount=1", "-XX:MaxMetaspaceSize=128m", "-XX:ReservedCodeCacheSize=64m",
        "-XX:-UsePerfData", "-version")
    assert invocation.limits.resident_memory_bytes == 256*MIB
    assert invocation.limits.memory_bytes == 4096*MIB
    assert 0 < invocation.limits.timeout_seconds <= 10
    assert invocation.limits.cpu_seconds <= 10
    assert invocation.limits.max_output_bytes == 65536
    assert invocation.limits.max_workspace_bytes == MIB
    assert invocation.limits.max_input_bytes == 1024
    assert not any(variable in invocation.environment for variable in java.JAVA_OPTION_ENV_VARS)
    assert invocation.environment["PATH"] == os.environ["PATH"]
    # Releasing a lease ends its cancellation lifetime, after the usable result.
    assert signal.is_set()


@pytest.mark.parametrize("result", [
    {"returncode": 1}, {"returncode": None}, {"timed_out": True}, {"cancelled": True},
    {"resource_exhausted": True}, {"output_truncated": True}, {"process_tree_terminated": True},
    {"error": "cleanup/launch failure"},
], ids=["nonzero", "no-exit", "timeout", "cancelled", "memory", "truncated", "tree-stopped", "error"])
@pytest.mark.parametrize("route", ["read", "probe"])
def test_unsafe_native_result_cannot_validate_java_even_with_valid_banner(host, result, route):
    host.action[0] = lambda *args: process.RawProcessResult(**{"returncode": 0, "stderr": BANNER, **result})
    if route == "read":
        assert java.read_java_version_banner(sys.executable) == (None, None)
    else:
        actual = probe()
        assert not actual.usable and actual.reason_code == "java_probe_failed"
        assert actual.banner is None and actual.major is None
    assert len(host.calls) == 1


@pytest.mark.parametrize("field", ["unavailable", "workspace_limit_exceeded", "workspace_cleaned"])
def test_lifecycle_failures_withhold_valid_banner(host, monkeypatch, field):
    original = resource_admission.ResourceAdmittedToolRunner.run
    def failed(self, *args, **kwargs):
        result = original(self, *args, **kwargs)
        return replace(result, **{field: field != "workspace_cleaned"})
    monkeypatch.setattr(resource_admission.ResourceAdmittedToolRunner, "run", failed)
    assert java.read_java_version_banner(sys.executable) == (None, None)
    assert len(host.calls) == 1


def test_combined_stdout_stderr_limit_is_not_two_independent_allowances(host):
    host.action[0] = lambda *args: process.RawProcessResult(returncode=0,
        stdout="x"*40000, stderr=BANNER + "y"*40000)
    assert not probe().usable


@pytest.mark.parametrize("error", [OSError("synthetic missing executable"), process.ToolProcessError("bad launch")])
def test_launch_exception_withholds_identity_and_drains_owner(host, error):
    def fail(*args):
        raise error
    host.action[0] = fail
    assert java.read_java_version_banner(sys.executable) == (None, None)


@pytest.mark.parametrize("route", ["tlc", "apalache", "registry-tlc", "registry-apalache"])
def test_default_constructor_and_registry_discovery_actually_use_admission(host, monkeypatch, route):
    from ipfs_datasets_py.logic.backends import registry
    from ipfs_datasets_py.logic.backends.tla import runners
    monkeypatch.setattr(runners, "_production_executable_finder", lambda name: None)
    if route.startswith("registry"):
        selected = registry.default_backend_registry()
        assert not host.calls
        assert not selected.is_available("tla_tlc" if route.endswith("tlc") else "apalache")
    else:
        cls = runners.TLCBackend if route == "tlc" else runners.ApalacheBackend
        selected = cls(lazy_install=False, which=lambda name: None)
        assert not selected.is_available()
    assert len(host.calls) == 1


@pytest.mark.parametrize("changes,reason", [
    ({"available_memory_mb": 32}, "proof_memory_headroom"),
    ({"cpu_stall_percent": 90}, "proof_cpu_stall"),
    ({"available_pid_tasks": 0}, "proof_pid_headroom"),
    (None, "proof_resource_telemetry_unknown"),
])
def test_external_pressure_then_cancel_never_launches_or_leaks_waiter(host, changes, reason):
    host.current[0] = replace(host.healthy, **changes) if changes else OSError("unavailable telemetry")
    event, outcomes = threading.Event(), []
    worker = threading.Thread(target=lambda: outcomes.append(probe(timeout=2, cancellation=event)))
    worker.start()
    try:
        until(lambda: host.owner.snapshot()["proof_backoff"].get("reason") == reason)
        assert not host.calls
        event.set()
        worker.join(3)
        assert not worker.is_alive() and len(outcomes) == 1
        assert not outcomes[0].usable and outcomes[0].banner is None
    finally:
        event.set(); worker.join(3)


def test_pressure_recovery_uses_remaining_deadline(host):
    host.current[0] = replace(host.healthy, cpu_stall_percent=90)
    outcomes = []
    worker = threading.Thread(target=lambda: outcomes.append(probe(timeout=1)))
    worker.start()
    try:
        until(lambda: host.owner.snapshot()["waiting_request_count"] == 1)
        time.sleep(.04)
        host.current[0] = host.healthy
        worker.join(2)
        assert not worker.is_alive() and outcomes[0].usable
        assert 0 < host.calls[0][0].limits.timeout_seconds < .98
    finally:
        host.current[0] = host.healthy; worker.join(3)


def test_local_queue_deadline_returns_failure_without_native_work(host):
    host.current[0] = replace(host.healthy, cpu_stall_percent=90)
    assert not probe(timeout=.03).usable
    assert not host.calls


def test_parent_child_ownership_does_not_double_charge_or_release_parent(host, monkeypatch):
    monkeypatch.setattr(resource_admission, "get_global_resource_scheduler", lambda: pytest.fail("nested run acquired global owner"))
    with host.owner.acquire("orchestration", cpu_slots=1, memory_mb=256, child_process_slots=1, timeout=0) as parent:
        assert probe(parent_lease=parent).usable
        state = host.calls[0][2]
        assert state["active_root_lease_count"] == 1 and state["active_lease_count"] == 2
        assert state["allocated"]["memory_mb"] == 256
        assert state["allocated_child_process_slots"] == 1
        assert host.owner.snapshot()["active_lease_count"] == 1


@pytest.mark.parametrize("shape", ["is_set", "is_cancelled", "cancelled"])
def test_precancel_shapes_do_not_resolve_or_launch(host, monkeypatch, shape):
    event = type("Stop", (), {shape: True if shape == "cancelled" else lambda self: True})()
    monkeypatch.setattr(java, "resolve_java_executable", lambda *args: pytest.fail("resolved after pre-cancel"))
    assert not probe(cancellation=event).usable
    assert not host.calls


def test_observed_transient_cancel_stays_latched_after_event_cleared(host):
    event = threading.Event()
    def stopped(invocation, signal):
        event.set()
        assert signal.is_set()
        event.clear()
        return process.RawProcessResult(returncode=0, stderr=BANNER)
    host.action[0] = stopped
    assert not probe(cancellation=event).usable
    assert not event.is_set()
    host.action[0] = lambda *args: process.RawProcessResult(returncode=0, stderr=BANNER)
    assert probe().usable


@pytest.fixture
def fakeclock(monkeypatch):
    now = [100.0]
    module = SimpleNamespace(monotonic=lambda: now[0])
    monkeypatch.setattr(java, "time", module)
    monkeypatch.setattr(budget, "time", module)
    monkeypatch.setattr(resource_admission, "time", module)
    return now


@pytest.mark.parametrize("phase", ["resolution", "native", "normalization"])
def test_one_local_deadline_withholds_late_success(host, fakeclock, monkeypatch, phase):
    if phase == "resolution":
        def resolve(value=None):
            fakeclock[0] += .11
            return sys.executable, "argument"
        monkeypatch.setattr(java, "resolve_java_executable", resolve)
    elif phase == "native":
        def late(*args):
            fakeclock[0] += .11
            return process.RawProcessResult(returncode=0, stderr=BANNER)
        host.action[0] = late
    else:
        original = java._java_runtime_observation
        def late(*args):
            fakeclock[0] += .11
            return original(*args)
        monkeypatch.setattr(java, "_java_runtime_observation", late)
    result = probe(timeout=.1)
    assert not result.usable and result.banner is None
    assert len(host.calls) == (0 if phase == "resolution" else 1)


def test_resolution_and_native_share_original_deadline_not_fresh_timeouts(host, fakeclock, monkeypatch):
    def resolve(value=None):
        fakeclock[0] += .4
        return sys.executable, "argument"
    monkeypatch.setattr(java, "resolve_java_executable", resolve)
    assert probe(timeout=1).usable
    assert 0 < host.calls[0][0].limits.timeout_seconds <= .601
    assert host.calls[0][0].limits.cpu_seconds == pytest.approx(.6)


@pytest.mark.parametrize("stop", ["cancel", "timeout"])
def test_ambient_stop_raises_after_workspace_and_lease_cleanup(host, fakeclock, stop):
    event = threading.Event()
    def stopped(invocation, signal):
        if stop == "cancel":
            event.set(); assert signal.is_set(); event.clear()
        else:
            fakeclock[0] += .051
        return process.RawProcessResult(returncode=0, stderr=BANNER)
    host.action[0] = stopped
    expected = budget.ProofOperationCancelled if stop == "cancel" else budget.ProofOperationTimeout
    with pytest.raises(expected):
        with budget.proof_operation_scope(timeout_ms=50, cancellation=event):
            probe(timeout=2)
    assert host.owner.snapshot()["active_lease_count"] == 0
    assert all(not path.exists() for path in host.workspaces)
    assert budget.current_proof_operation() is None
    assert host.calls[0][0].limits.timeout_seconds <= .051


def test_local_timeout_does_not_poison_larger_ambient_budget(host, fakeclock):
    def stopped(*args):
        fakeclock[0] += .02
        return process.RawProcessResult(returncode=0, stderr=BANNER)
    host.action[0] = stopped
    with budget.proof_operation_scope(timeout_ms=1000) as operation:
        assert not probe(timeout=.01).usable
        operation.checkpoint("ambient remains live")
        host.action[0] = lambda *args: process.RawProcessResult(returncode=0, stderr=BANNER)
        assert probe().usable


@pytest.mark.parametrize("value", [0, -1, True, None, "1", float("inf"), float("nan"), 2**32, 10**1000])
@pytest.mark.parametrize("route", ["read", "probe"])
def test_invalid_timeouts_refused_before_any_launch(host, value, route):
    with pytest.raises(ValueError):
        if route == "read":
            java.read_java_version_banner(sys.executable, timeout=value)
        else:
            probe(timeout=value)
    assert not host.calls


@pytest.mark.parametrize("controls", [{"scheduler": object()}, {"parent_lease": object()}])
def test_invalid_owners_refused_without_native_work(host, controls):
    with pytest.raises(TypeError):
        probe(**controls)
    assert not host.calls


def test_invalid_owner_combination_refused(host):
    with host.owner.acquire("orchestration", cpu_slots=1, memory_mb=256, child_process_slots=1, timeout=0) as parent:
        with pytest.raises(schedulers.ResourceConfigurationError):
            probe(scheduler=host.owner, parent_lease=parent)
    assert not host.calls


def test_fatal_default_pool_configuration_does_not_fallback_to_raw_subprocess(host, monkeypatch):
    def fail():
        raise ValueError("foreign schema incompatibility fixture")
    monkeypatch.setattr(resource_admission, "get_global_resource_scheduler", fail)
    assert not probe().usable
    assert not host.calls


def test_old_reader_injection_signature_and_wire_are_preserved(host, monkeypatch):
    seen = []
    def read(executable, *, timeout=10.0):
        seen.append((executable, timeout))
        return 0, BANNER
    monkeypatch.setattr(java, "read_java_version_banner", read)
    assert probe().usable
    assert len(seen) == 1 and 0 < seen[0][1] <= 10
    assert not host.calls


def test_imports_do_not_load_admission_or_start_processes_or_install(tmp_path):
    source = textwrap.dedent('''
        import importlib.abc, sys
        sys.path.insert(0, ROOT)
        class Deny(importlib.abc.MetaPathFinder):
            def find_spec(self, fullname, path=None, target=None):
                if fullname.endswith(('resource_admission', 'resource_scheduler')):
                    raise AssertionError('eager admission import: ' + fullname)
        sys.meta_path.insert(0, Deny())
        def audit(event, args):
            if event in ('subprocess.Popen', 'os.system', 'os.posix_spawn'):
                raise AssertionError('import launched process')
        sys.addaudithook(audit)
        from ipfs_datasets_py.logic.backends.installers import state_model
        from ipfs_datasets_py.logic.backends.registry import default_backend_registry
        default_backend_registry()
        print('inert')
    ''').replace('ROOT', repr(str(Path(__file__).resolve().parents[4])))
    completed = subprocess.run([sys.executable, '-I', '-B', '-c', source], capture_output=True, text=True, timeout=15)
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == 'inert'


def test_direct_pathlike_and_explicit_scheduler_preserve_launch_contract(host, monkeypatch):
    monkeypatch.setattr(resource_admission, "get_global_resource_scheduler", lambda: pytest.fail("explicit owner ignored"))
    assert java.read_java_version_banner(Path(sys.executable), scheduler=host.owner) == (0, BANNER)
    assert host.calls[0][0].argv[0] == str(Path(sys.executable).resolve())


def test_probe_does_not_release_unrelated_owner_lease(host):
    with host.owner.acquire("orchestration", cpu_slots=1, memory_mb=128, child_process_slots=1, timeout=0):
        assert probe().usable
        assert host.calls[0][2]["active_root_lease_count"] == 2
        assert host.calls[0][2]["allocated"]["memory_mb"] == 384
        assert host.owner.snapshot()["active_lease_count"] == 1


def test_cleanup_precedes_resource_release(host, monkeypatch):
    original = host.owner.release
    observations = []
    def release(*args, **kwargs):
        assert host.workspaces and all(not path.exists() for path in host.workspaces)
        observations.append(True)
        return original(*args, **kwargs)
    monkeypatch.setattr(host.owner, "release", release)
    assert probe().usable
    assert observations == [True]


def test_ambient_cancellation_while_queued_raises_typed_stop_and_drains(host):
    event, outcomes = threading.Event(), []
    host.current[0] = replace(host.healthy, cpu_stall_percent=90)
    def run():
        try:
            with budget.proof_operation_scope(timeout_ms=2000, cancellation=event):
                probe()
        except Exception as error:
            outcomes.append(error)
    worker = threading.Thread(target=run)
    worker.start()
    try:
        until(lambda: host.owner.snapshot()["waiting_request_count"] == 1)
        event.set(); worker.join(3)
        assert not worker.is_alive() and len(outcomes) == 1
        assert isinstance(outcomes[0], budget.ProofOperationCancelled)
        assert not host.calls
    finally:
        event.set(); worker.join(3)


def test_parallel_scopes_do_not_share_local_cancellation(host):
    first, second = threading.Event(), threading.Event()
    event, outcomes = threading.Event(), {}
    def execute(invocation, signal):
        if threading.current_thread().name == "cancelled-probe":
            first.set()
            assert second.wait(2)
            event.set(); assert signal.is_set(); event.clear()
        else:
            assert first.wait(2)
            second.set()
        return process.RawProcessResult(returncode=0, stderr=BANNER)
    host.action[0] = execute
    workers = [threading.Thread(name=name, target=lambda label=name: outcomes.setdefault(label,
        probe(cancellation=event if label == "cancelled-probe" else None)))
        for name in ("cancelled-probe", "healthy-probe")]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(3)
    assert all(not worker.is_alive() for worker in workers)
    assert not outcomes["cancelled-probe"].usable
    assert outcomes["healthy-probe"].usable


@pytest.mark.parametrize("cancel", [False, True], ids=["success", "cancel-after-banner"])
def test_real_local_process_cleanup_and_banner_withholding(host, tmp_path, monkeypatch, cancel):
    pidfile = tmp_path / "fixture.pid"
    executable = tmp_path / "java-fixture"
    executable.write_text("#!" + sys.executable + "\nimport os,time\n"
        + "open(" + repr(str(pidfile)) + ", 'w').write(str(os.getpid()))\n"
        + "print(" + repr(BANNER) + ", flush=True)\n"
        + ("time.sleep(10)\n" if cancel else ""))
    executable.chmod(0o755)
    monkeypatch.setattr(java, "resolve_java_executable", lambda value=None: (str(executable), "argument"))
    real_results = []
    def execute(self, invocation, cancellation=None):
        assert host.owner.snapshot()["active_lease_count"] == 1
        host.workspaces.append(invocation.cwd)
        result = REAL_EXECUTE(self, invocation, cancellation)
        real_results.append(result)
        return result
    monkeypatch.setattr(process.SubprocessExecutor, "execute", execute)
    event, outcomes = threading.Event(), []
    worker = threading.Thread(target=lambda: outcomes.append(probe(timeout=3, cancellation=event)))
    worker.start()
    try:
        until(pidfile.exists)
        if cancel:
            event.set()
        worker.join(4)
        assert not worker.is_alive() and len(outcomes) == 1 and len(real_results) == 1
        assert outcomes[0].usable is (not cancel)
        if cancel:
            assert outcomes[0].banner is None
            assert real_results[0].cancelled and real_results[0].process_tree_terminated
        assert not Path('/proc/' + pidfile.read_text()).exists()
    finally:
        event.set(); worker.join(4)
