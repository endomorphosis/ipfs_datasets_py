"""Pinned native tools execute bounded mathematical examples and replay receipts."""
import json
import os
from pathlib import Path
import re
import subprocess
import time

import pytest

from ipfs_datasets_py.logic.ir_core.protocols import ExecutionBounds
from ipfs_datasets_py.logic.software_contracts.codebase_smt_execution import (
    CodebaseSmtExecutionError, make_codebase_smt_runner, validate_execution_receipt,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.proof_resource_safety import ProofHostResources
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.resource_scheduler import (
    GlobalResourceScheduler, ResourceSchedulerConfig,
)


@pytest.fixture(scope="module", params=[("z3", True), ("z3", False), ("cvc5", True), ("cvc5", False)],
                ids=["z3-sat", "z3-unsat", "cvc5-sat", "cvc5-unsat"])
def native_observation(request, tmp_path_factory):
    solver, sat = request.param
    admission = json.loads(Path(os.environ["CODEBASE_NATIVE_ADMISSION_PATH"]).read_text())
    executable = admission["native_solver_targets"][solver]["path"]
    source = """(set-option :produce-models true)
(set-option :produce-unsat-cores true)
(set-logic QF_LIA)
(declare-const n Int)
(assert (! (= n 7) :named seven))
""" + ("" if sat else "(assert (! (= n 8) :named eight))\n") + "(check-sat)\n(get-model)\n(get-unsat-core)\n"
    root = tmp_path_factory.mktemp(solver + ("-sat" if sat else "-unsat"))
    owner = GlobalResourceScheduler(ResourceSchedulerConfig.for_proof_host(
        state_path=root / "resources.json",
        proof_resource_sampler=lambda: ProofHostResources(8, 8192, 8192),
        lane_reservations={}, auto_renew_leases=False,
    ))
    bounds = ExecutionBounds(timeout_ms=5000, max_memory_bytes=128 * 1024**2,
                             max_output_bytes=256 * 1024)
    with owner.acquire("validation", cpu_slots=1, memory_mb=512,
                       child_process_slots=1, timeout=2) as parent:
        runner = make_codebase_smt_runner(solver, executable, parent_lease=parent,
                                         deadline=time.monotonic() + 10)
        raw = runner(source, bounds)
        assert owner.snapshot()["active_lease_count"] == 1
    assert owner.snapshot()["active_lease_count"] == 0
    assert owner.snapshot()["waiting_request_count"] == 0
    record = {"solver": solver, "satisfiable": sat, "executable": executable,
              "smtlib": source, "bounds": bounds.to_dict(), "execution": raw.execution.to_dict(),
              "scheduler_drained": True, "repository_proof_authority": False}
    destination = Path(os.environ["CODEBASE_NATIVE_TEST_ARTIFACT_DIR"]) / (solver + ("-sat.json" if sat else "-unsat.json"))
    with destination.open("x") as stream:
        json.dump(record, stream, indent=2)
        stream.write("\n")
    return record, raw, bounds


def replay(observation, execution):
    record, raw, bounds = observation
    return validate_execution_receipt(execution, solver=record["solver"],
        executable=record["executable"], smtlib=record["smtlib"], bounds=bounds, raw=raw)


def test_pinned_solver_observes_known_math_with_clean_bounded_phases(native_observation):
    record, raw, _ = native_observation
    value = raw.execution.to_dict()
    sat = record["satisfiable"]
    assert raw.returncode == 0 and raw.stdout.splitlines()[0] == ("sat" if sat else "unsat")
    assert [phase["kind"] for phase in value["phases"]] == ["version", "verdict", "model" if sat else "unsat_core"]
    for phase in value["phases"]:
        assert phase["returncode"] == 0 and phase["workspace_cleaned"]
        assert not any(phase[name] for name in ("timed_out", "cancelled", "unavailable",
                                               "resource_exhausted", "output_truncated"))
        assert phase["limits"]["memory_bytes"] == 128 * 1024**2
        assert phase["limits"]["resident_memory_bytes"] == 128 * 1024**2
        assert 0 < phase["limits"]["timeout_ms"] <= 5000
    if sat:
        assert re.search(r"\(define-fun n \(\) Int 7\)", " ".join(raw.stdout.split()))
    else:
        assert "seven" in raw.stdout and "eight" in raw.stdout
    assert value["policy"]["kernel_aggregate_memory_limit"] is False
    replay(native_observation, raw.execution)


def test_historical_native_receipt_replay_launches_nothing(native_observation, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("historical receipt replay launched a process")
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    replay(native_observation, native_observation[1].execution)


def test_changed_input_and_relaxed_limits_reject_historical_receipt(native_observation):
    value = native_observation[1].execution.to_dict()
    value["input_sha256"] = "0" * 64
    with pytest.raises(CodebaseSmtExecutionError):
        replay(native_observation, value)
    value = native_observation[1].execution.to_dict()
    value["phases"][-1]["limits"]["memory_bytes"] = 256 * 1024**2
    with pytest.raises(CodebaseSmtExecutionError):
        replay(native_observation, value)
