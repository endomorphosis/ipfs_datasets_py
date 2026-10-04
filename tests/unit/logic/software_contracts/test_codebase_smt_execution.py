"""Real bounded subprocess faults at the conditional-SMT adapter boundary."""
from dataclasses import replace
import json
import os
from pathlib import Path
import shutil
import signal
import sys
import threading
import time
from types import SimpleNamespace

import pytest

from ipfs_datasets_py.logic.ir_core.protocols import ExecutionBounds
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import resource_scheduler as schedulers
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.proof_resource_safety import ProofHostResources

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "benchmarks"))
import bench_codebase_smt_execution as fixtures

pytestmark = pytest.mark.skipif(not sys.platform.startswith("linux"), reason="qualified Linux prlimit/procfs boundary")


@pytest.fixture
def admitted(tmp_path):
    healthy = ProofHostResources(8, 8192, 8192)
    pressure = [healthy]
    owner = schedulers.GlobalResourceScheduler(schedulers.ResourceSchedulerConfig.for_proof_host(
        state_path=tmp_path / "resources.json", proof_resource_sampler=lambda: pressure[0],
        lane_reservations={}, auto_renew_leases=False, poll_interval_seconds=.005, proof_backoff_seconds=.01))
    with owner.acquire("orchestration", cpu_slots=1, memory_mb=1024, child_process_slots=3, timeout=0) as parent:
        yield owner, parent, pressure, healthy
        assert owner.snapshot()["active_lease_count"] == 1
        assert owner.snapshot()["waiting_request_count"] == 0
    assert owner.snapshot()["active_lease_count"] == 0


@pytest.fixture
def module():
    from ipfs_datasets_py.logic.software_contracts import codebase_smt_execution
    return codebase_smt_execution


@pytest.fixture
def native_fixture(tmp_path):
    def create(mode="clean", verdict="unsat"):
        return fixtures.write_solver_fixture(tmp_path / mode, mode, verdict=verdict)
    yield create
    # Defensive cleanup of only our retained PID+birth records on regression.
    for directory in tmp_path.iterdir():
        if directory.is_dir():
            for record in fixtures.live_retained_processes(directory):
                try:
                    os.kill(record["pid"], signal.SIGKILL)
                except ProcessLookupError:
                    pass


def invoke(module, parent, executable, *, source=fixtures.SMT_FIXTURE, timeout_ms=3000,
           memory_mb=256, output_bytes=4096, cancel=None, outer_seconds=10):
    runner = module.make_codebase_smt_runner("z3", str(executable), parent_lease=parent,
        cancel_event=cancel, deadline=time.monotonic() + outer_seconds)
    return runner(source, ExecutionBounds(timeout_ms=timeout_ms, max_memory_bytes=memory_mb * 1024**2,
                                         max_output_bytes=output_bytes))


def receipt(error_or_output):
    return error_or_output.execution.to_dict()


@pytest.mark.parametrize("verdict,artifact", [("sat", "model"), ("unsat", "unsat_core")])
def test_success_uses_three_distinct_same_parent_children_and_clean_receipts(module, admitted, native_fixture,
                                                                           monkeypatch, verdict, artifact):
    owner, parent, _, _ = admitted
    path = native_fixture(verdict=verdict)
    original = module.run_bounded_stdin_tool
    leases = []
    def observed(*args, **kwargs):
        children = [row for row in owner.active_leases() if row.get("parent_lease_id") == parent.lease_id]
        assert len(children) == 1
        assert owner.snapshot()["active_root_lease_count"] == 1
        leases.append(children[0]["lease_id"])
        return original(*args, **kwargs)
    monkeypatch.setattr(module, "run_bounded_stdin_tool", observed)
    result = invoke(module, parent, path)
    value = receipt(result)
    assert value["schema"] == "codebase-smt-execution@1" and value["status"] == "completed"
    assert [phase["kind"] for phase in value["phases"]] == ["version", "verdict", artifact]
    assert len(set(leases)) == 3
    assert [row["kind"] for row in fixtures.recorded_phases(path.parent)] == ["version", "verdict", "artifact"]
    for phase in value["phases"]:
        assert phase["returncode"] == 0 and phase["workspace_cleaned"]
        assert all(phase[name] is False for name in ("timed_out", "cancelled", "output_truncated", "resource_exhausted", "unavailable"))
        assert phase["limits"]["memory_bytes"] == phase["limits"]["resident_memory_bytes"] == 256 * 1024**2
        assert phase["limits"]["timeout_ms"] <= 3000


@pytest.mark.parametrize("mode", ["stdout_flood", "stderr_flood", "artifact_flood"])
def test_valid_verdict_prefix_cannot_hide_real_output_truncation(module, admitted, native_fixture, mode):
    path = native_fixture(mode)
    with pytest.raises(module.CodebaseSmtExecutionError) as raised:
        invoke(module, admitted[1], path, output_bytes=512)
    value = receipt(raised.value)
    assert value["status"] == "failed"
    assert any(phase["output_truncated"] for phase in value["phases"])
    assert all(len(phase[stream].encode()) <= 4096 if phase["kind"] == "version" else
               len(phase[stream].encode()) <= 512 for phase in value["phases"] for stream in ("stdout", "stderr"))
    assert all(phase["workspace_cleaned"] for phase in value["phases"])


@pytest.mark.parametrize("mode", ["nonzero", "mismatch"])
def test_verdict_cannot_promote_nonzero_or_disagreeing_artifact_phase(module, admitted, native_fixture, mode):
    path = native_fixture(mode)
    with pytest.raises(module.CodebaseSmtExecutionError) as raised:
        invoke(module, admitted[1], path)
    value = receipt(raised.value)
    assert value["status"] == "failed"
    assert value["phases"][-1]["returncode"] == (7 if mode == "nonzero" else 0)
    assert all(phase["workspace_cleaned"] for phase in value["phases"])


@pytest.mark.parametrize("mode", ["version_sleep", "blocked_stdin", "descendant_cancel"])
def test_real_inflight_cancellation_drains_phase_and_separate_session(module, admitted, native_fixture, mode):
    path = native_fixture(mode)
    source = ";" + "x" * (200 * 1024) + "\n" + fixtures.SMT_FIXTURE if mode == "blocked_stdin" else fixtures.SMT_FIXTURE
    started = time.monotonic()
    with pytest.raises(schedulers.LeaseCancelledError) as raised:
        invoke(module, admitted[1], path, source=source, cancel=fixtures.ReadyCancellation(path.parent))
    value = receipt(raised.value)
    assert time.monotonic() - started < 3
    assert (path.parent / "ready.json").exists()
    assert any(phase["cancelled"] and phase["process_tree_terminated"] for phase in value["phases"])
    assert all(phase["workspace_cleaned"] for phase in value["phases"])
    assert fixtures.live_retained_processes(path.parent) == []
    if mode == "version_sleep":
        assert [row["kind"] for row in fixtures.recorded_phases(path.parent)] == ["version"]
    if mode == "descendant_cancel":
        assert (path.parent / "child.json").exists()


def test_slow_stdin_timeout_uses_total_call_budget_without_hanging_writer(module, admitted, native_fixture):
    path = native_fixture("blocked_stdin")
    started = time.monotonic()
    with pytest.raises(module.CodebaseSmtExecutionError) as raised:
        invoke(module, admitted[1], path, timeout_ms=500,
               source=";" + "x" * (200 * 1024) + "\n" + fixtures.SMT_FIXTURE)
    assert time.monotonic() - started < 2
    assert any(phase["timed_out"] for phase in receipt(raised.value)["phases"])
    assert fixtures.live_retained_processes(path.parent) == []


@pytest.mark.parametrize("mode,memory_mb", [("as_exhaustion", 256), ("rss_exhaustion", 128)])
def test_real_memory_exhaustion_never_becomes_a_verdict(module, admitted, native_fixture, mode, memory_mb):
    path = native_fixture(mode)
    with pytest.raises(module.CodebaseSmtExecutionError) as raised:
        invoke(module, admitted[1], path, memory_mb=memory_mb)
    phases = receipt(raised.value)["phases"]
    assert phases[-1]["returncode"] != 0
    if mode == "rss_exhaustion":
        assert phases[-1]["resource_exhausted"] and phases[-1]["process_tree_terminated"]
    else:
        assert "MemoryError" in phases[-1]["stderr"]
    assert not phases[-1]["timed_out"]
    assert all(phase["workspace_cleaned"] for phase in phases)
    assert fixtures.live_retained_processes(path.parent) == []


@pytest.mark.parametrize("after", ["version", "verdict"])
def test_new_external_pressure_prevents_next_native_phase(module, admitted, native_fixture, monkeypatch, after):
    _, parent, pressure, healthy = admitted
    path = native_fixture()
    original = module.run_bounded_stdin_tool
    calls = []
    def observed(*args, **kwargs):
        result = original(*args, **kwargs)
        kind = "version" if any(x in {"-version", "--version"} for x in args[0]) else "verdict"
        calls.append(kind)
        if kind == after:
            pressure[0] = replace(healthy, memory_stall_percent=10)
        return result
    monkeypatch.setattr(module, "run_bounded_stdin_tool", observed)
    with pytest.raises(module.CodebaseSmtExecutionError):
        invoke(module, parent, path, timeout_ms=600)
    assert calls == (["version"] if after == "version" else ["version", "verdict"])
    assert len(fixtures.recorded_phases(path.parent)) == len(calls)


def test_oversize_script_and_precancelled_parent_launch_nothing(module, admitted, native_fixture):
    path = native_fixture()
    with pytest.raises((module.CodebaseSmtExecutionError, ValueError)):
        invoke(module, admitted[1], path, source=";" + "x" * (256 * 1024))
    admitted[1].cancel()
    with pytest.raises(schedulers.LeaseCancelledError):
        invoke(module, admitted[1], path)
    assert fixtures.recorded_phases(path.parent) == []


@pytest.mark.parametrize("boundary", ["cancel", "deadline"])
def test_receipt_validation_cannot_return_after_cancellation_or_deadline(module, admitted, native_fixture,
                                                                       monkeypatch, boundary):
    path = native_fixture()
    event = threading.Event()
    original = module.validate_execution_receipt
    validated = []
    def validate_then_change(*args, **kwargs):
        original(*args, **kwargs)
        validated.append(True)
        if boundary == "cancel":
            event.set()
        else:
            # Advance only this helper's deadline clock after genuine completed
            # native phases and genuine validation; the scheduler/runner keep
            # their real clocks and no process is held past its actual budget.
            monkeypatch.setattr(module, "time", SimpleNamespace(monotonic=lambda: time.monotonic() + 20))
    monkeypatch.setattr(module, "validate_execution_receipt", validate_then_change)
    expected = schedulers.LeaseCancelledError if boundary == "cancel" else module.CodebaseSmtExecutionError
    with pytest.raises(expected) as raised:
        invoke(module, admitted[1], path, cancel=event)
    assert validated == [True]
    value = receipt(raised.value)
    assert value["status"] == "failed" and len(value["phases"]) == 3
    assert all(phase["returncode"] == 0 and phase["workspace_cleaned"] for phase in value["phases"])
    assert fixtures.live_retained_processes(path.parent) == []


@pytest.mark.parametrize("solver", ["z3", "cvc5"])
@pytest.mark.parametrize("sat", [True, False])
def test_actual_solvers_work_with_declared_128mib_default(module, admitted, solver, sat):
    discovered = shutil.which(solver)
    if discovered is None:
        pytest.skip(f"native {solver} unavailable")
    from ipfs_datasets_py.logic.software_contracts.codebase_integer_profile import _native_executable
    executable, _ = _native_executable(discovered)
    runner = module.make_codebase_smt_runner(solver, executable, parent_lease=admitted[1],
        cancel_event=None, deadline=time.monotonic() + 10)
    source = fixtures.SMT_FIXTURE.replace("(! false", "(! true") if sat else fixtures.SMT_FIXTURE
    result = runner(source, ExecutionBounds(timeout_ms=5000, max_memory_bytes=128 * 1024**2,
                                           max_output_bytes=256 * 1024))
    value = receipt(result)
    assert result.returncode == 0 and result.stdout.splitlines()[0] == ("sat" if sat else "unsat")
    assert [phase["kind"] for phase in value["phases"]] == ["version", "verdict", "model" if sat else "unsat_core"]
    assert all(phase["returncode"] == 0 and phase["workspace_cleaned"] for phase in value["phases"])
    assert all(phase["limits"]["memory_bytes"] == 128 * 1024**2 for phase in value["phases"])
