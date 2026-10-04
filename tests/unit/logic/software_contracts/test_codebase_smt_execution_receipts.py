"""Native execution receipts cannot hide changed scripts, phases or limits."""
from dataclasses import replace
import shutil
import time

import pytest

from ipfs_datasets_py.logic.ir_core.protocols import ExecutionBounds
from ipfs_datasets_py.logic.software_contracts.codebase_smt_execution import (
    CodebaseSmtExecutionError, make_codebase_smt_runner, validate_execution_receipt,
)
from ipfs_datasets_py.logic.software_contracts.codebase_integer_profile import _native_executable
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.proof_resource_safety import ProofHostResources
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.resource_scheduler import GlobalResourceScheduler, ResourceSchedulerConfig

SCRIPT = """(set-option :produce-models true)
(set-option :produce-unsat-cores true)
(set-logic QF_UFLIA)
(declare-const n Int)
(assert (! (> n 0) :named positive))
(assert (<= n 0))
(check-sat)
(get-model)
(get-unsat-core)
"""


@pytest.fixture(scope="module")
def native_receipt(tmp_path_factory):
    discovered = shutil.which("z3")
    if discovered is None:
        pytest.skip("native Z3 unavailable")
    executable, _ = _native_executable(discovered)
    root = tmp_path_factory.mktemp("receipt-native")
    owner = GlobalResourceScheduler(ResourceSchedulerConfig.for_proof_host(
        state_path=root / "resources.json", proof_resource_sampler=lambda: ProofHostResources(8, 8192, 8192),
        lane_reservations={}, auto_renew_leases=False))
    bounds = ExecutionBounds(timeout_ms=5000, max_memory_bytes=128 * 1024 * 1024, max_output_bytes=256 * 1024)
    with owner.acquire("validation", cpu_slots=1, memory_mb=512, child_process_slots=1, timeout=2) as parent:
        runner = make_codebase_smt_runner("z3", executable, parent_lease=parent, deadline=time.monotonic() + 10)
        raw = runner(SCRIPT, bounds)
    assert owner.snapshot()["active_lease_count"] == 0
    return raw, bounds, executable


def replay(native_receipt, value, **kwargs):
    raw, bounds, executable = native_receipt
    options = dict(solver="z3", executable=executable, smtlib=SCRIPT, bounds=bounds, raw=raw)
    options.update(kwargs)
    return validate_execution_receipt(value, **options)


def test_native_receipt_replays_without_any_process_launch(native_receipt, monkeypatch):
    import subprocess
    raw, _, _ = native_receipt
    def forbidden(*args, **kwargs):
        pytest.fail("historical execution receipt replay launched a subprocess")
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    replay(native_receipt, raw.execution)
    data = raw.execution.to_dict()
    assert [phase["kind"] for phase in data["phases"]] == ["version", "verdict", "unsat_core"]
    assert raw.returncode == 0 and "(error" not in raw.stdout
    assert data["policy"]["kernel_aggregate_memory_limit"] is False
    data["phases"][0]["argv"][0] = "changed"
    assert raw.execution.to_dict()["phases"][0]["argv"][0] != "changed"


@pytest.mark.parametrize("field,value", [
    ("schema", "other@1"), ("status", "failed"), ("solver", "cvc5"),
    ("executable", "/invented"), ("input_sha256", "0" * 64),
    ("elapsed_ms", True), ("elapsed_ms", 5001), ("unexpected", "field"),
])
def test_receipt_identity_and_status_changes_are_rejected(native_receipt, field, value):
    data = native_receipt[0].execution.to_dict()
    data[field] = value
    with pytest.raises(CodebaseSmtExecutionError):
        replay(native_receipt, data)


@pytest.mark.parametrize("field,value", [
    ("kind", "model"), ("argv", ["/bin/true"]), ("input_sha256", "0" * 64),
    ("returncode", 1), ("returncode", True), ("timed_out", True), ("cancelled", True),
    ("unavailable", True), ("resource_exhausted", True), ("output_truncated", True),
    ("workspace_cleaned", False), ("process_tree_terminated", True),
    ("error", "cleanup failed"), ("stderr", "unexpected warning"),
    ("stdout", "sat\n()\n"), ("elapsed_ms", -1), ("unexpected", "field"),
])
def test_failed_or_rebound_native_phase_never_replays_as_completed(native_receipt, field, value):
    data = native_receipt[0].execution.to_dict()
    data["phases"][-1][field] = value
    with pytest.raises(ValueError):
        replay(native_receipt, data)


@pytest.mark.parametrize("field,value", [
    ("timeout_ms", 5001), ("memory_bytes", 512 * 1024 * 1024),
    ("resident_memory_bytes", 512 * 1024 * 1024), ("max_output_bytes", 1024 * 1024),
    ("max_workspace_bytes", 64 * 1024 * 1024), ("max_file_bytes", 1),
    ("max_input_bytes", True), ("cpu_seconds", 500), ("termination_grace_ms", 2000),
])
def test_phase_limits_cannot_be_relaxed_in_historical_execution(native_receipt, field, value):
    data = native_receipt[0].execution.to_dict()
    data["phases"][-1]["limits"][field] = value
    with pytest.raises(CodebaseSmtExecutionError):
        replay(native_receipt, data)


def test_missing_artifact_or_changed_raw_result_fails_receipt_replay(native_receipt):
    raw = native_receipt[0]
    data = raw.execution.to_dict()
    data["phases"].pop()
    with pytest.raises(CodebaseSmtExecutionError, match="artifact phase"):
        replay(native_receipt, data)
    with pytest.raises(CodebaseSmtExecutionError):
        replay(native_receipt, raw.execution, raw=replace(raw, stdout="sat\n()\n"))
    with pytest.raises(CodebaseSmtExecutionError):
        replay(native_receipt, raw.execution, smtlib=SCRIPT.replace("(<= n 0)", "(<= n 1)"))
    data = raw.execution.to_dict()
    data["policy"]["kernel_aggregate_memory_limit"] = True
    with pytest.raises(CodebaseSmtExecutionError):
        replay(native_receipt, data)


@pytest.mark.parametrize("name", ["fresh_child_per_phase", "deadline_includes_admission",
                                  "kernel_aggregate_memory_limit", "historical_execution_attested"])
def test_policy_boolean_types_cannot_be_replaced_by_equal_integers(native_receipt, name):
    data = native_receipt[0].execution.to_dict()
    data["policy"][name] = int(data["policy"][name])
    with pytest.raises(CodebaseSmtExecutionError):
        replay(native_receipt, data)
