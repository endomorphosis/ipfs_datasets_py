"""Public SMT launch admission and fail-closed conversion of native results.

Real scheduler accounting uses private state files and synthetic host samples.
Explicit fake lifecycle runners test unsafe observations without native load.
"""
from dataclasses import replace
import importlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import time
from types import SimpleNamespace

import pytest

from ipfs_datasets_py.logic.backends import process
from ipfs_datasets_py.logic.backends import resource_admission
from ipfs_datasets_py.logic.backends.smt import admitted
from ipfs_datasets_py.logic.backends.smt.compiler import SmtFeature, SmtObligation, SmtQueryMode, term_true
from ipfs_datasets_py.logic.backends.smt.differential import SmtRawSolverOutput
from ipfs_datasets_py.logic.backends.registry import BackendRunnerOutput
from ipfs_datasets_py.logic.ir_core.claims import FrozenMap
from ipfs_datasets_py.logic.ir_core.protocols import BackendRequest, ExecutionBounds, QueryKind
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import resource_scheduler as schedulers
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.proof_resource_safety import ProofHostResources


MIB = 1024**2
ROOT = Path(__file__).resolve().parents[4]
CONCLUSIVE = {"proved", "disproved", "satisfied", "violated", "sat", "unsat", "satisfiable", "unsatisfiable"}


@pytest.fixture
def owner(tmp_path):
    healthy = ProofHostResources(8, 8192, 8192, pid_task_limit=8192, available_pid_tasks=8192)
    current = [healthy]

    def sample():
        if isinstance(current[0], Exception):
            raise current[0]
        return current[0]

    config = schedulers.ResourceSchedulerConfig.for_proof_host(
        state_path=tmp_path / "smt-pool.json", proof_resource_sampler=sample,
        total_cpu_slots=2, total_memory_mb=1024, total_child_process_slots=2,
        proof_memory_headroom_mb=64, lane_reservations={}, auto_renew_leases=False,
        proof_backoff_seconds=0.025, poll_interval_seconds=0.002,
    )
    return schedulers.GlobalResourceScheduler(config), healthy, current


def bounds(**kwargs):
    return ExecutionBounds(**{"timeout_ms": 1000, "max_memory_bytes": 128 * MIB,
                              "max_output_bytes": 4096, **kwargs})


def obligation():
    return SmtObligation(obligation_id="obl:smt-admission", goal=term_true(), features=(SmtFeature.EQUALITY,),
                         query_mode=SmtQueryMode.THEOREM_BY_NEGATION)


def registry_request(solver="z3", **limits):
    return BackendRequest(
        request_id="request:smt-admission", claim_id="claim:smt-admission",
        declaration_id="declaration:smt-admission", claim_digest="1" * 64,
        obligation_id="obl:smt-admission", obligation_digest="2" * 64,
        assumption_ids=(), logic_family="first_order", query_kind=QueryKind.THEOREM_PROOF,
        requested_backend_id=solver, bounds=bounds(**limits),
        payload=FrozenMap({"encoding": "smtlib2", "source":
                          "(set-logic QF_UF)\n(assert false)\n(check-sat)\n"}),
    )


def backend_type(solver, surface):
    prefix = "Z3" if solver == "z3" else "CVC5"
    suffix = "Backend" if surface == "registry" else "SoftwareVerificationBackend"
    return getattr(admitted, prefix + suffix)


def invoke(backend, surface, solver="z3", *, cancellation=None, **limits):
    value = registry_request(solver, **limits) if surface == "registry" else obligation()
    options = {"cancellation": cancellation} if cancellation is not None else {}
    if surface == "sv":
        options["bounds"] = bounds(**limits)
    return backend.run(value, **options)


def result_status(outcome, surface):
    return (outcome[1] if surface == "registry" else outcome.result).status.value


def assert_idle(scheduler):
    state = scheduler.snapshot()
    assert state["active_lease_count"] == state["waiting_request_count"] == 0


def until(predicate, timeout=2):
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() >= deadline:
            raise AssertionError("bounded test wait expired")
        time.sleep(0.003)


def is_version(argv):
    return any(arg in {"-version", "--version"} for arg in argv)


class Recorder:
    def __init__(self, action=None):
        self.calls = []
        self.action = action

    def execute(self, invocation, cancellation=None):
        self.calls.append((invocation, cancellation))
        if self.action is not None:
            return self.action(invocation, cancellation)
        return process.RawProcessResult(returncode=0,
            stdout="fixture-solver/1\n" if is_version(invocation.argv) else "unsat\n")


class ResultRunner(process.BoundedToolRunner):
    """Trusted fake boundary for observations unavailable on executor results."""
    def __init__(self, changed=None, action=None):
        super().__init__(executor=Recorder())
        self.changed = changed or {}
        self.action = action
        self.calls = []

    def run(self, request, **kwargs):
        self.calls.append(request)
        result = process.ToolRunResult(
            interface_version=process.BOUNDED_TOOL_RUNNER_VERSION,
            runtime=request.runtime, command=request.argv, returncode=0,
            stdout="fixture-solver/1\n" if is_version(request.argv) else "unsat\n",
            stderr="", elapsed_seconds=0.001, output_files={}, pid=123,
        )
        if self.action is not None:
            return self.action(request, result)
        return replace(result, **self.changed) if not is_version(request.argv) else result


@pytest.mark.parametrize("solver", ["z3", "cvc5"])
@pytest.mark.parametrize("surface", ["registry", "sv"])
@pytest.mark.parametrize("changed", [
    {"timed_out": True}, {"cancelled": True}, {"resource_exhausted": True},
    {"output_truncated": True}, {"unavailable": True}, {"workspace_cleaned": False},
    {"workspace_limit_exceeded": True}, {"error": "execution cleanup failed"},
    {"returncode": 7}, {"returncode": None}, {"process_tree_terminated": True},
], ids=["timeout", "cancel", "resource", "truncated", "unavailable", "unclean", "workspace", "error", "nonzero", "no-exit", "tree-killed"])
def test_unsafe_unsat_prefix_never_becomes_proof_or_launches_version(solver, surface, changed):
    runner = ResultRunner(changed)
    backend = backend_type(solver, surface)(tool_runner=runner, availability_probe=lambda: True)
    outcome = invoke(backend, surface, solver)
    assert result_status(outcome, surface) not in CONCLUSIVE
    assert len(runner.calls) == 1 and not is_version(runner.calls[0].argv)


@pytest.mark.parametrize("solver", ["z3", "cvc5"])
@pytest.mark.parametrize("surface", ["registry", "sv"])
def test_clean_query_and_version_keep_finite_native_caps_and_exact_budget(owner, tmp_path, solver, surface):
    scheduler, _, _ = owner
    seen = []

    def record(invocation, signal):
        state = scheduler.snapshot()
        assert state["active_root_lease_count"] == 1
        assert state["allocated"]["memory_mb"] == 128
        assert state["allocated_child_process_slots"] == 1
        assert invocation.limits.memory_bytes == invocation.limits.resident_memory_bytes == 128 * MIB
        assert 0 < invocation.limits.timeout_seconds <= 1
        assert not signal.is_set()
        seen.append(scheduler.active_leases()[0]["lease_id"])
        return process.RawProcessResult(returncode=0,
            stdout="fixture-solver/1\n" if is_version(invocation.argv) else "unsat\n")

    recorder = Recorder(record)
    tool = resource_admission.ResourceAdmittedToolRunner(
        scheduler=scheduler, executor=recorder, workspace_root=tmp_path / "runs")
    backend = backend_type(solver, surface)(tool_runner=tool, availability_probe=lambda: True)
    outcome = invoke(backend, surface, solver)
    assert result_status(outcome, surface) == "proved"
    assert [is_version(call[0].argv) for call in recorder.calls] == [False, True]
    assert len(set(seen)) == 2
    assert not list((tmp_path / "runs").glob("logic-tool-*"))
    assert_idle(scheduler)


@pytest.mark.parametrize("surface", ["registry", "sv"])
def test_combined_stream_budget_cannot_hide_unsat_prefix(surface):
    runner = ResultRunner({"stdout": "unsat\n" + ";" * 80, "stderr": "x" * 80})
    backend = backend_type("z3", surface)(tool_runner=runner, availability_probe=lambda: True)
    outcome = invoke(backend, surface, max_output_bytes=128)
    assert result_status(outcome, surface) not in CONCLUSIVE
    assert len(runner.calls) == 1


@pytest.mark.parametrize("surface", ["registry", "sv"])
@pytest.mark.parametrize("failure", [{"timed_out": True}, {"cancelled": True}, {"output_truncated": True}, {"returncode": 7}])
def test_failed_version_phase_cannot_preserve_prior_unsat_success(surface, failure):
    runner = ResultRunner(action=lambda request, result: replace(result, **failure) if is_version(request.argv) else result)
    backend = backend_type("z3", surface)(tool_runner=runner, availability_probe=lambda: True)
    outcome = invoke(backend, surface)
    assert result_status(outcome, surface) not in CONCLUSIVE
    assert [is_version(call.argv) for call in runner.calls] == [False, True]


@pytest.mark.parametrize("surface", ["registry", "sv"])
def test_cancellation_between_query_and_version_launches_no_followup(surface):
    event = threading.Event()

    def query_then_cancel(request, result):
        event.set()
        return result

    runner = ResultRunner(action=query_then_cancel)
    backend = backend_type("z3", surface)(tool_runner=runner, availability_probe=lambda: True)
    outcome = invoke(backend, surface, cancellation=event)
    assert result_status(outcome, surface) not in CONCLUSIVE
    assert len(runner.calls) == 1


@pytest.mark.parametrize("surface", ["registry", "sv"])
def test_constructor_cancellation_is_honored_before_launch(surface):
    event = threading.Event()
    event.set()
    runner = ResultRunner()
    backend = backend_type("z3", surface)(tool_runner=runner, availability_probe=lambda: True, cancellation=event)
    outcome = invoke(backend, surface)
    assert result_status(outcome, surface) not in CONCLUSIVE
    assert not runner.calls


@pytest.mark.parametrize("surface", ["registry", "sv"])
def test_single_deadline_includes_query_and_version(surface, monkeypatch):
    clock = [100.0]
    monkeypatch.setattr(admitted, "time", SimpleNamespace(monotonic=lambda: clock[0]))

    def consume(request, result):
        if is_version(request.argv):
            assert 0 < request.limits.timeout_seconds <= 0.61
            clock[0] += 0.7
        else:
            clock[0] += 0.4
        return result

    runner = ResultRunner(action=consume)
    backend = backend_type("z3", surface)(tool_runner=runner, availability_probe=lambda: True)
    outcome = invoke(backend, surface)
    assert result_status(outcome, surface) not in CONCLUSIVE
    assert [is_version(call.argv) for call in runner.calls] == [False, True]


@pytest.mark.parametrize("surface", ["registry", "sv"])
def test_exhausted_query_deadline_prevents_version(surface, monkeypatch):
    clock = [100.0]
    monkeypatch.setattr(admitted, "time", SimpleNamespace(monotonic=lambda: clock[0]))

    def late(request, result):
        clock[0] += 2
        return result

    runner = ResultRunner(action=late)
    backend = backend_type("z3", surface)(tool_runner=runner, availability_probe=lambda: True)
    assert result_status(invoke(backend, surface), surface) not in CONCLUSIVE
    assert len(runner.calls) == 1


@pytest.mark.parametrize("solver", ["z3", "cvc5"])
def test_solver_version_is_cached_only_without_legacy_subprocess_fallback(solver, monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: pytest.fail("legacy version subprocess"))
    runner = ResultRunner()
    backend = backend_type(solver, "sv")(tool_runner=runner, availability_probe=lambda: True)
    assert backend.solver_version() == "" and not runner.calls
    assert result_status(invoke(backend, "sv", solver), "sv") == "proved"
    assert backend.solver_version() == "fixture-solver/1"
    assert len(runner.calls) == 2


@pytest.mark.parametrize("solver", ["z3", "cvc5"])
@pytest.mark.parametrize("surface", ["registry", "sv"])
def test_explicit_legacy_callable_runner_keeps_compatibility_without_new_root(monkeypatch, solver, surface):
    monkeypatch.setattr(resource_admission, "get_global_resource_scheduler", lambda: pytest.fail("raw injection double charged"))
    calls = []

    def raw(*args):
        calls.append(args)
        result_class = BackendRunnerOutput if surface == "registry" else SmtRawSolverOutput
        return result_class(stdout="unsat\n", solver_version="trusted-fixture/1")

    backend = backend_type(solver, surface)(runner=raw, availability_probe=lambda: True)
    assert result_status(invoke(backend, surface, solver), surface) == "proved"
    assert len(calls) == 1


@pytest.mark.parametrize("surface", ["registry", "sv"])
def test_actual_parent_children_are_not_double_charged(owner, surface):
    scheduler, _, _ = owner
    with scheduler.acquire("orchestration", cpu_slots=2, memory_mb=256,
                           child_process_slots=2, timeout=0) as parent:
        allocated = scheduler.snapshot()["allocated"]
        seen = []

        def record(invocation, signal):
            state = scheduler.snapshot()
            assert state["active_root_lease_count"] == 1
            assert state["active_child_lease_count"] == 1
            assert state["allocated"] == allocated
            seen.extend(row["parent_lease_id"] for row in scheduler.active_leases() if row["parent_lease_id"])
            return process.RawProcessResult(returncode=0,
                stdout="fixture-solver/1\n" if is_version(invocation.argv) else "unsat\n")

        tool = resource_admission.ResourceAdmittedToolRunner(parent_lease=parent, executor=Recorder(record))
        backend = backend_type("z3", surface)(tool_runner=tool, availability_probe=lambda: True)
        assert result_status(invoke(backend, surface), surface) == "proved"
        assert seen == [parent.lease_id] * 2
        assert not parent.released and scheduler.snapshot()["active_lease_count"] == 1
    assert_idle(scheduler)


@pytest.mark.parametrize("changes,reason", [
    ({"available_memory_mb": 32}, "proof_memory_headroom"),
    ({"cpu_stall_percent": 90}, "proof_cpu_stall"),
    ({"available_pid_tasks": 0}, "proof_pid_headroom"),
    (None, "proof_resource_telemetry_unknown"),
])
def test_external_pressure_defers_native_query_and_recovers(owner, changes, reason):
    scheduler, healthy, current = owner
    current[0] = replace(healthy, **changes) if changes is not None else OSError("unknown host resources")
    recorder = Recorder()
    tool = resource_admission.ResourceAdmittedToolRunner(scheduler=scheduler, executor=recorder)
    backend = admitted.Z3SoftwareVerificationBackend(tool_runner=tool, availability_probe=lambda: True)
    results = []
    worker = threading.Thread(target=lambda: results.append(invoke(backend, "sv", timeout_ms=2000)))
    worker.start()
    try:
        until(lambda: scheduler.snapshot()["proof_backoff"].get("reason") == reason)
        assert not recorder.calls
        current[0] = healthy
        worker.join(3)
        assert not worker.is_alive() and len(results) == 1
        assert result_status(results[0], "sv") == "proved"
    finally:
        current[0] = healthy
        worker.join(3)
    assert_idle(scheduler)


@pytest.mark.parametrize("surface", ["registry", "sv"])
def test_pressure_after_query_prevents_version_and_prior_unsat_promotion(owner, surface):
    scheduler, healthy, current = owner

    def pressurize(invocation, signal):
        current[0] = replace(healthy, memory_stall_percent=8)
        return process.RawProcessResult(returncode=0, stdout="unsat\n")

    recorder = Recorder(pressurize)
    tool = resource_admission.ResourceAdmittedToolRunner(scheduler=scheduler, executor=recorder)
    backend = backend_type("z3", surface)(tool_runner=tool, availability_probe=lambda: True)
    assert result_status(invoke(backend, surface, timeout_ms=80), surface) not in CONCLUSIVE
    assert len(recorder.calls) == 1
    assert scheduler.snapshot()["proof_backoff"]["reason"] == "proof_memory_stall"
    assert_idle(scheduler)


def test_public_namespaces_are_lazy_and_constructors_do_not_touch_shared_pool():
    source = r'''
import importlib, json, sys
sys.path.insert(0, sys.argv[1])
prefix = "ipfs_datasets_py.logic.backends."
def audit(event, args):
    if event == "subprocess.Popen":
        raise AssertionError("SMT import or constructor launched a process")
    if event == "open" and ("resource-scheduler" in str(args[0]) or ".symai" in str(args[0])):
        raise AssertionError("SMT import or constructor touched runtime state")
sys.addaudithook(audit)
packages = [importlib.import_module(prefix + solver) for solver in ("z3", "cvc5")]
assert prefix + "smt.admitted" not in sys.modules
assert not any(prefix + solver + ".compiler" in sys.modules for solver in ("z3", "cvc5"))
from ipfs_datasets_py.logic.backends import resource_admission
def forbidden():
    raise AssertionError("constructor requested global pool")
resource_admission.get_global_resource_scheduler = forbidden
for package, stem in zip(packages, ("Z3", "CVC5")):
    for suffix in ("Backend", "SoftwareVerificationBackend"):
        cls = getattr(package, stem + suffix)
        assert cls.__module__ == prefix + "smt.admitted"
        adapter = cls()
        assert isinstance(adapter._transport.runner, resource_admission.ResourceAdmittedToolRunner)
        assert adapter._transport.runner.cpu_slots == adapter._transport.runner.child_process_slots == 1
    assert getattr(package, stem + "Compiler").__module__ == package.__name__ + ".compiler"
print(json.dumps({"public_defaults": 4, "launches": 0}))
'''
    result = subprocess.run([sys.executable, "-I", "-B", "-c", source, str(ROOT)],
                            capture_output=True, text=True, timeout=20, check=False)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout.strip().splitlines()[-1]) == {"public_defaults": 4, "launches": 0}


@pytest.mark.parametrize("solver", ["z3", "cvc5"])
@pytest.mark.parametrize("surface", ["registry", "v2"])
def test_actual_default_dispatch_owns_each_native_launch(owner, monkeypatch, solver, surface):
    from ipfs_datasets_py.logic.backends.registry import default_backend_registry
    from ipfs_datasets_py.logic.backends.smt.execution_v2 import (
        SmtExecutionEngineV2, SmtExecutionMode, SmtExecutionRequestV2,
    )
    scheduler, _, _ = owner
    monkeypatch.setattr(resource_admission, "get_global_resource_scheduler", lambda: scheduler)
    monkeypatch.setattr(shutil, "which", lambda executable, *args, **kwargs: sys.executable)
    leases = []

    def execute(executor, invocation, cancellation=None):
        rows = scheduler.active_leases()
        assert len(rows) == 1
        assert rows[0]["cpu_slots"] == rows[0]["child_process_slots"] == 1
        assert rows[0]["memory_mb"] == 128
        leases.append(rows[0]["lease_id"])
        return process.RawProcessResult(returncode=0,
            stdout="fixture-solver/1\n" if is_version(invocation.argv) else "unsat\n")

    monkeypatch.setattr(process.SubprocessExecutor, "execute", execute)
    if surface == "registry":
        registry = default_backend_registry()
        outcome = registry.run(registry_request(solver))
        assert result_status(outcome, "registry") == "proved", outcome
    else:
        engine = SmtExecutionEngineV2()
        adapter = getattr(engine, solver)
        assert type(adapter) is backend_type(solver, "sv")
        result = engine.execute(SmtExecutionRequestV2(
            request_id="request:smt-default-v2", obligation=obligation(), provider=solver,
            mode=SmtExecutionMode.PINNED_SOLVER, bounds=bounds()))
        assert result.disposition.value == "proved"
    assert len(leases) == len(set(leases)) == 2
    assert_idle(scheduler)


@pytest.mark.parametrize("surface", ["registry", "sv"])
def test_input_limit_refuses_before_any_native_lifecycle(surface):
    runner = ResultRunner()
    backend = backend_type("z3", surface)(tool_runner=runner, availability_probe=lambda: True,
                                          max_input_bytes=16)
    assert result_status(invoke(backend, surface), surface) not in CONCLUSIVE
    assert not runner.calls


@pytest.mark.parametrize("surface", ["registry", "sv"])
def test_oversize_memory_request_is_refused_without_shrinking(owner, surface):
    scheduler, _, _ = owner
    recorder = Recorder()
    tool = resource_admission.ResourceAdmittedToolRunner(scheduler=scheduler, executor=recorder)
    backend = backend_type("z3", surface)(tool_runner=tool, availability_probe=lambda: True)
    assert result_status(invoke(backend, surface, max_memory_bytes=1025 * MIB), surface) not in CONCLUSIVE
    assert not recorder.calls
    assert_idle(scheduler)


@pytest.mark.parametrize("surface", ["registry", "sv"])
def test_saturation_does_not_release_or_modify_foreign_owner(owner, surface):
    scheduler, _, _ = owner
    foreign = scheduler.acquire("foreign", cpu_slots=2, memory_mb=256, child_process_slots=2, timeout=0)
    try:
        before = scheduler.active_leases()
        recorder = Recorder()
        tool = resource_admission.ResourceAdmittedToolRunner(scheduler=scheduler, executor=recorder)
        backend = backend_type("z3", surface)(tool_runner=tool, availability_probe=lambda: True)
        assert result_status(invoke(backend, surface, timeout_ms=50), surface) not in CONCLUSIVE
        assert not recorder.calls
        assert scheduler.active_leases() == before
        assert not foreign.released
        assert scheduler.snapshot()["waiting_request_count"] == 0
    finally:
        foreign.release()
    assert_idle(scheduler)


@pytest.mark.parametrize("surface", ["registry", "sv"])
def test_lifecycle_cleanup_exception_releases_actual_reservation(owner, surface):
    scheduler, _, _ = owner

    def fail(invocation, signal):
        assert scheduler.snapshot()["active_lease_count"] == 1
        raise OSError("synthetic executor error")

    recorder = Recorder(fail)
    tool = resource_admission.ResourceAdmittedToolRunner(scheduler=scheduler, executor=recorder)
    backend = backend_type("z3", surface)(tool_runner=tool, availability_probe=lambda: True)
    assert result_status(invoke(backend, surface), surface) not in CONCLUSIVE
    assert len(recorder.calls) == 1
    assert_idle(scheduler)


@pytest.mark.parametrize("surface", ["registry", "sv"])
@pytest.mark.parametrize("kwargs", [
    {"tool_runner": ResultRunner(), "scheduler": object()},
    {"runner": lambda *args: None, "tool_runner": ResultRunner()},
    {"runner": lambda *args: None, "parent_lease": object()},
    {"tool_runner": object()}, {"max_input_bytes": 0}, {"max_input_bytes": True},
])
def test_ambiguous_ownership_and_invalid_input_caps_are_rejected(surface, kwargs):
    with pytest.raises((ValueError, TypeError)):
        backend_type("z3", surface)(**kwargs)


@pytest.mark.parametrize("solver", ["z3", "cvc5"])
@pytest.mark.parametrize("verdict,expected", [("unsat", "proved"), ("sat", "disproved")])
def test_both_artifact_requests_select_only_applicable_clean_phase(solver, verdict, expected):
    def respond(request, result):
        if is_version(request.argv):
            return result
        source = request.stdin
        if "(get-model)" in source:
            assert verdict == "sat" and "(get-unsat-core)" not in source
            return replace(result, stdout="sat\n(model)\n")
        if "(get-unsat-core)" in source:
            assert verdict == "unsat" and "(get-model)" not in source
            return replace(result, stdout="unsat\n()\n")
        return replace(result, stdout=verdict + "\n")

    runner = ResultRunner(action=respond)
    backend = backend_type(solver, "sv")(tool_runner=runner, availability_probe=lambda: True)
    requested = replace(obligation(), request_model=True, request_unsat_core=True)
    result = backend.run(requested, bounds=bounds())
    assert result_status(result, "sv") == expected
    assert len(runner.calls) == 3 and is_version(runner.calls[-1].argv)
    assert "(get-model)" not in runner.calls[0].stdin
    assert "(get-unsat-core)" not in runner.calls[0].stdin


@pytest.mark.parametrize("bad", [
    {"stdout": "sat\n(model)\n"}, {"stdout": "unsat\n(error \"bad artifact\")\n"},
    {"stdout": "unsat\n()\n", "returncode": 1}, {"stdout": "unsat\n()\n", "cancelled": True},
    {"stdout": "unsat\n()\n", "output_truncated": True}, {"stdout": "unsat\n"},
    {"stdout": "unsat\n()\n", "stderr": "unexpected warning"},
])
def test_invalid_second_artifact_phase_never_preserves_query_unsat(bad):
    def respond(request, result):
        return replace(result, **bad) if "(get-unsat-core)" in request.stdin else result

    runner = ResultRunner(action=respond)
    backend = admitted.Z3SoftwareVerificationBackend(tool_runner=runner, availability_probe=lambda: True)
    outcome = backend.run(replace(obligation(), request_model=True, request_unsat_core=True), bounds=bounds())
    assert result_status(outcome, "sv") not in CONCLUSIVE
    assert len(runner.calls) == 2 and not any(is_version(call.argv) for call in runner.calls)


@pytest.mark.parametrize("surface", ["registry", "sv"])
@pytest.mark.parametrize("stdout,stderr", [
    ("unsat\nsat\n", ""), ("unsat\n(error \"ignored tail\")\n", ""),
    ("(error \"ignored prefix\")\nunsat\n", ""), ("unsat\n", "warning"),
    ("unsat\nunfinished (", ""),
])
def test_native_single_verdict_protocol_rejects_diagnostics_and_tail(surface, stdout, stderr):
    runner = ResultRunner({"stdout": stdout, "stderr": stderr})
    backend = backend_type("z3", surface)(tool_runner=runner, availability_probe=lambda: True)
    assert result_status(invoke(backend, surface), surface) not in CONCLUSIVE
    assert len(runner.calls) == 1


@pytest.mark.parametrize("source", [
    "(set-option :parallel.enable true)\n(check-sat)\n",
    "(set-option :smt.threads 8)\n(check-sat)\n",
    "(check-sat)\n(check-sat)\n", "(push 1)\n(check-sat)\n",
    "(check-sat)\n(set-option :timeout 100)\n",
    "(set-option :timeout nope)\n(check-sat)\n",
])
def test_registry_refuses_scripts_that_escape_single_process_query_profile(source):
    runner = ResultRunner()
    backend = admitted.Z3Backend(tool_runner=runner, availability_probe=lambda: True)
    request = replace(registry_request(), payload=FrozenMap({"encoding": "smtlib2", "source": source}))
    assert result_status(backend.run(request), "registry") not in CONCLUSIVE
    assert not runner.calls


def test_real_output_flood_rejects_unsat_and_releases_private_pool(owner, tmp_path):
    scheduler, _, _ = owner
    executable = tmp_path / "fake-smt"
    executable.write_text("#!" + sys.executable + "\nimport sys\nsys.stdout.write('unsat\\n' + 'x' * 131072)\nsys.stdout.flush()\n")
    executable.chmod(0o700)
    observed = []

    class Observe(resource_admission.ResourceAdmittedToolRunner):
        def run(self, request, **kwargs):
            result = super().run(request, **kwargs)
            observed.append(result)
            return result

    runner = Observe(scheduler=scheduler, workspace_root=tmp_path / "runs")
    backend = admitted.Z3SoftwareVerificationBackend(executable=str(executable),
        tool_runner=runner, availability_probe=lambda: True)
    result = backend.run(obligation(), bounds=bounds(max_output_bytes=128))
    assert result_status(result, "sv") not in CONCLUSIVE
    assert len(observed) == 1 and observed[0].pid
    assert observed[0].output_truncated and observed[0].workspace_cleaned
    assert not Path(f"/proc/{observed[0].pid}").exists()
    assert not list((tmp_path / "runs").glob("logic-tool-*"))
    assert_idle(scheduler)


def test_artifact_and_version_share_remaining_deadline(monkeypatch):
    clock = [100.0]
    monkeypatch.setattr(admitted, "time", SimpleNamespace(monotonic=lambda: clock[0]))

    def respond(request, result):
        if is_version(request.argv):
            assert 0 < request.limits.timeout_seconds <= 0.31
            clock[0] += 0.4
        elif "(get-unsat-core)" in request.stdin:
            assert 0 < request.limits.timeout_seconds <= 0.61
            clock[0] += 0.3
            result = replace(result, stdout="unsat\n()\n")
        else:
            clock[0] += 0.4
        return result

    runner = ResultRunner(action=respond)
    backend = admitted.Z3SoftwareVerificationBackend(tool_runner=runner, availability_probe=lambda: True)
    result = backend.run(replace(obligation(), request_unsat_core=True), bounds=bounds())
    assert result_status(result, "sv") not in CONCLUSIVE
    assert len(runner.calls) == 3


def test_artifact_stream_bytes_count_toward_version_budget():
    def respond(request, result):
        if "(get-unsat-core)" in request.stdin:
            assert request.limits.max_output_bytes == 14
            return replace(result, stdout="unsat\n()\n")
        if is_version(request.argv):
            assert request.limits.max_output_bytes == 5
        return result

    runner = ResultRunner(action=respond)
    backend = admitted.Z3SoftwareVerificationBackend(tool_runner=runner, availability_probe=lambda: True)
    result = backend.run(replace(obligation(), request_unsat_core=True), bounds=bounds(max_output_bytes=20))
    assert result_status(result, "sv") not in CONCLUSIVE
    assert len(runner.calls) == 3


def test_shared_adapter_keeps_concurrent_cancellation_contexts_separate(owner):
    scheduler, _, _ = owner
    barrier = threading.Barrier(2)
    events = {name: threading.Event() for name in ("cancel-one", "clean-one")}
    outcomes = {}
    failures = []
    active = []

    def respond(invocation, signal):
        if not is_version(invocation.argv):
            active.append(scheduler.snapshot()["active_root_lease_count"])
            barrier.wait(timeout=2)
            if threading.current_thread().name == "cancel-one":
                events["cancel-one"].set()
        return process.RawProcessResult(returncode=0,
            stdout="fixture-solver/1\n" if is_version(invocation.argv) else "unsat\n")

    recorder = Recorder(respond)
    tool = resource_admission.ResourceAdmittedToolRunner(scheduler=scheduler, executor=recorder)
    backend = admitted.Z3SoftwareVerificationBackend(tool_runner=tool, availability_probe=lambda: True)

    def worker(name):
        try:
            outcomes[name] = backend.run(obligation(), bounds=bounds(timeout_ms=3000), cancellation=events[name])
        except BaseException as error:
            failures.append(error)

    workers = [threading.Thread(name=name, target=worker, args=(name,)) for name in events]
    for thread in workers:
        thread.start()
    for thread in workers:
        thread.join(4)
    assert not any(thread.is_alive() for thread in workers) and not failures
    assert max(active) == 2
    assert result_status(outcomes["cancel-one"], "sv") not in CONCLUSIVE
    assert result_status(outcomes["clean-one"], "sv") == "proved"
    assert len(recorder.calls) == 3
    assert_idle(scheduler)


@pytest.mark.parametrize("solver", ["z3", "cvc5"])
def test_public_sv_trims_executable_for_query_and_version_like_legacy(solver):
    package = importlib.import_module("ipfs_datasets_py.logic.backends." + solver)
    class_name = ("Z3" if solver == "z3" else "CVC5") + "SoftwareVerificationBackend"
    runner = ResultRunner()
    backend = getattr(package, class_name)(executable=" \t" + solver + "\n ",
        tool_runner=runner, availability_probe=lambda: True)
    assert result_status(invoke(backend, "sv", solver), "sv") == "proved"
    assert len(runner.calls) == 2
    assert [request.argv[0] for request in runner.calls] == [solver, solver]
    assert [is_version(request.argv) for request in runner.calls] == [False, True]
    assert backend._executable == solver


@pytest.mark.parametrize("solver", ["z3", "cvc5"])
@pytest.mark.parametrize("executable", [None, "", " \t\n ", False])
def test_public_sv_preserves_invalid_executable_rejection(solver, executable):
    package = importlib.import_module("ipfs_datasets_py.logic.backends." + solver)
    legacy = importlib.import_module(package.__name__ + ".compiler")
    class_name = ("Z3" if solver == "z3" else "CVC5") + "SoftwareVerificationBackend"
    for module in (package, legacy):
        with pytest.raises(ValueError, match="executable must be a non-empty string"):
            getattr(module, class_name)(executable=executable, availability_probe=lambda: True)
