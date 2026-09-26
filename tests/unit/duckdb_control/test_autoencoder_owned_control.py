"""Durable owned invocation control with real registry/journal/CAS fixtures.

The shared child fixture serializes a synthetic changed compact state. It never
runs daemon training, proves a theorem or supplies native qualification. Tests
dispatch the gateway directly: no listener, remote service or download starts.
"""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path
import threading

import pytest

from ipfs_datasets_py.duckdb_control import autoencoder_owned_control as control_module
from ipfs_datasets_py.duckdb_control.autoencoder_quack import (
    RegistryQuackGateway, RegistryTransportError, WorkerScope, _envelope,
)
from ipfs_datasets_py.duckdb_control.autoencoder_registry import AutoencoderRegistry
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_daemon_invocation_contracts as contracts
from tests.unit.optimizers.logic_theorem_optimizer.test_autoencoder_daemon_invocation import (
    _explicit_weight_reference, journal_for, prepare, setup,
)


def _ref(prepared):
    return {key: prepared["request"][key] for key in ("sha256", "bytes")}


@pytest.fixture(autouse=True)
def close_controllers(setup):
    setup.controllers = []
    yield
    for controller in reversed(setup.controllers):
        controller.close()


def _control(case, prepared, *, registry=None, worker="submitter-a", run_id="owned-run", assignments=None):
    controller = control_module.OwnedInvocationControl(
        case.registry if registry is None else registry,
        worker_id=worker, prepared_invocations={run_id: prepared} if assignments is None else assignments)
    case.controllers.append(controller)
    return controller


def _resolution(control, operation_id, run_id, reference):
    result = control.resolve(operation_id, run_id, reference)
    assert result["admitted"] is False
    assert result["wire_operation_id"] == operation_id
    assert result["resolution"] == ("missing" if result["receipt"] is None else "committed")
    return result["receipt"]


def _gateway(control):
    return RegistryQuackGateway(control.registry, WorkerScope(control.worker_id, control.run_ids),
                                enable_prototype=True, owned_control=control)


def _wire(command, prepared_handle, operation_id="submit-once", run_id="owned-run", **extra):
    return _envelope(command, {"run_id": run_id, "request_artifact": _ref(prepared_handle), **extra}, operation_id)


def _assert_no_execution(case):
    assert case.child.calls == ["describe"]
    assert case.registry.get_run("owned-run")["status"] == "queued"
    assert case.registry.get_run("owned-run")["lease"] is None
    assert not list(case.output.glob("attempt-*"))


def _second_prepared(case):
    output = case.campaign / "other-owned-invocation"
    output.mkdir()
    return prepare(case, run_id="other-owned-run", output_directory=output,
                   daemon_argv=["--run-id", "other-owned-run", "--max-cycles", "1"])


def test_submission_is_durable_idempotent_and_execution_requires_explicit_owner_drain(setup):
    prepared = prepare(setup)
    control = _control(setup, prepared)
    initial_head = setup.registry.resolve_head("english-0", "best")
    assert control.read("owned-run", _ref(prepared))["status"] == "not_submitted"
    assert _resolution(control, "submit-once", "owned-run", _ref(prepared)) is None
    submitted = control.submit("submit-once", "owned-run", _ref(prepared))
    assert submitted == control.submit("submit-once", "owned-run", _ref(prepared))
    assert submitted == _resolution(control, "submit-once", "owned-run", _ref(prepared))
    assert control.read("owned-run", _ref(prepared))["status"] == "accepted"
    assert submitted["admitted"] is False
    _assert_no_execution(setup)
    outcome = control.execute_pending(max_workers=1)
    assert outcome["admitted"] is False
    assert len(outcome["results"]) == 1
    current = control.read("owned-run", _ref(prepared))
    assert current["status"] == "completed"
    assert current["completion"]["status"] == "completed"
    assert current["completion"]["promoted"] is False
    assert current["current_artifact_availability_checked"] is False
    assert setup.child.calls == ["describe", "execute", "verify"]
    version = setup.registry.get_version(current["completion"]["version_id"])
    assert version["parent_version_id"] == setup.spec.base_version_id
    assert version["metadata"]["result"]["evaluation_matches_final"] is False
    assert setup.registry.resolve_head("english-0", "best") == initial_head
    assert setup.registry.pending_outbox("huggingface") == []
    before = list(setup.child.calls)
    control.execute_pending(max_workers=1)
    assert setup.child.calls == before
    assert _resolution(control, "submit-once", "owned-run", _ref(prepared)) == submitted


def test_submit_reply_loss_and_owner_restart_recover_same_submission_before_execution(setup):
    prepared = prepare(setup)
    control = _control(setup, prepared)
    observed = []
    def lost_reply():
        observed.append(control.submit("submit-once", "owned-run", _ref(prepared)))
        raise ConnectionError("synthetic transport reply lost after durable submit")
    with pytest.raises(ConnectionError):
        lost_reply()
    _assert_no_execution(setup)
    control.close()
    setup.registry.close()
    with AutoencoderRegistry(setup.database, setup.cas, clock=lambda: setup.clock[0]) as registry:
        restarted = _control(setup, prepared, registry=registry)
        assert _resolution(restarted, "submit-once", "owned-run", _ref(prepared)) == observed[0]
        assert restarted.submit("submit-once", "owned-run", _ref(prepared)) == observed[0]
        assert restarted.read("owned-run", _ref(prepared))["status"] == "accepted"
        restarted.execute_pending(max_workers=1)
        assert restarted.read("owned-run", _ref(prepared))["status"] == "completed"
        assert setup.child.calls == ["describe", "execute", "verify"]
        restarted.close()


@pytest.mark.parametrize("change", ["sha256", "bytes", "extra-path", "different-operation"])
def test_submission_cannot_change_exact_request_or_allocate_another_operation_for_same_run(setup, change):
    prepared = prepare(setup)
    control = _control(setup, prepared)
    submitted = control.submit("submit-once", "owned-run", _ref(prepared))
    descriptor = _ref(prepared)
    operation_id = "submit-once"
    if change == "sha256":
        descriptor["sha256"] = "0" * 64
    elif change == "bytes":
        descriptor["bytes"] += 1
    elif change == "extra-path":
        descriptor["path"] = prepared["request"]["path"]
    else:
        operation_id = "second-operation"
    with pytest.raises(ValueError):
        control.submit(operation_id, "owned-run", descriptor)
    assert _resolution(control, "submit-once", "owned-run", _ref(prepared)) == submitted
    _assert_no_execution(setup)


@pytest.mark.parametrize("failure", ["execute", "verify"])
def test_failed_attempt_is_quarantined_and_duplicate_drain_does_not_rerun(setup, failure):
    prepared = prepare(setup)
    control = _control(setup, prepared)
    submitted = control.submit("submit-once", "owned-run", _ref(prepared))
    setup.child.failure_mode = failure
    control.execute_pending(max_workers=1)
    current = control.read("owned-run", _ref(prepared))
    assert current["status"] == "failed"
    assert current["completion"]["command"] == "FailRun"
    assert current["completion"]["status"] == "failed"
    assert setup.registry.get_run("owned-run")["status"] == "failed"
    with journal_for(prepared) as journal:
        assert journal.get_metadata("quarantine") is not None
        assert "complete" not in journal.operations()
    before = list(setup.child.calls)
    setup.child.failure_mode = None
    control.execute_pending(max_workers=1)
    assert setup.child.calls == before
    assert _resolution(control, "submit-once", "owned-run", _ref(prepared)) == submitted
    assert setup.registry.pending_outbox("huggingface") == []


def test_concurrent_duplicate_submission_and_read_during_execution_do_not_duplicate_attempt(setup):
    prepared = prepare(setup)
    control = _control(setup, prepared)
    submitted = control.submit("submit-once", "owned-run", _ref(prepared))
    entered, release = threading.Event(), threading.Event()
    def pause_fixture(launch, request, result):
        entered.set()
        assert release.wait(10), "test failed to release explicitly synthetic child"
    setup.child.execute_hook = pause_fixture
    with ThreadPoolExecutor(max_workers=3) as pool:
        first = pool.submit(control.execute_pending, max_workers=1)
        try:
            assert entered.wait(10)
            reading = pool.submit(control.read, "owned-run", _ref(prepared)).result(timeout=2)
            assert reading["status"] == "running"
            assert pool.submit(control.submit, "submit-once", "owned-run", _ref(prepared)).result(timeout=2) == submitted
            second = pool.submit(control.execute_pending, max_workers=1)
            with pytest.raises(control_module.OwnedInvocationControlError, match="already active"):
                second.result(timeout=2)
        finally:
            release.set()
        first.result(timeout=15)
    assert setup.child.calls.count("execute") == setup.child.calls.count("verify") == 1
    assert control.read("owned-run", _ref(prepared))["status"] == "completed"


def test_completed_history_survives_missing_request_and_candidate_after_owner_restart(setup):
    prepared = prepare(setup)
    descriptor = _ref(prepared)
    control = _control(setup, prepared)
    submitted = control.submit("submit-once", "owned-run", descriptor)
    control.execute_pending(max_workers=1)
    completed = control.read("owned-run", descriptor)
    version = setup.registry.get_version(completed["completion"]["version_id"])
    setup.registry.artifact_path(version["artifact"]).unlink()
    Path(prepared["request"]["path"]).unlink()
    before = list(setup.child.calls)
    control.close()
    setup.registry.close()
    with AutoencoderRegistry(setup.database, setup.cas, clock=lambda: setup.clock[0]) as registry:
        restarted = _control(setup, prepared, registry=registry)
        assert _resolution(restarted, "submit-once", "owned-run", descriptor) == submitted
        history = restarted.read("owned-run", descriptor)
        assert history["completion"] == completed["completion"]
        assert history["status"] == "completed"
        assert history["current_artifact_availability_checked"] is False
        restarted.execute_pending(max_workers=1)
        assert setup.child.calls == before
        restarted.close()


def test_ambiguous_committed_completion_recovers_without_reexecuting_or_opening_missing_artifacts(setup, monkeypatch):
    prepared = prepare(setup)
    descriptor = _ref(prepared)
    control = _control(setup, prepared)
    submitted = control.submit("submit-once", "owned-run", descriptor)
    real_complete, real_resolve = setup.registry.complete_run, setup.registry.resolve_operation
    committed = []
    def lose_completion_reply(*args, **kwargs):
        committed.append(real_complete(*args, **kwargs))
        raise OSError("synthetic lost completion response")
    def temporarily_unavailable(operation_id, command, payload):
        if committed and command == "CompleteRun":
            raise OSError("synthetic completion lookup outage")
        return real_resolve(operation_id, command, payload)
    monkeypatch.setattr(setup.registry, "complete_run", lose_completion_reply)
    monkeypatch.setattr(setup.registry, "resolve_operation", temporarily_unavailable)
    outcome = control.execute_pending(max_workers=1)
    assert outcome["results"][0]["status"] == "recovery_required"
    assert setup.registry.get_run("owned-run")["status"] == "completed"
    assert len(committed) == 1
    with journal_for(prepared) as journal:
        pending = journal.pending()["complete"]
        assert pending["receipt"] is None
    version = setup.registry.get_version(committed[0]["version_id"])
    setup.registry.artifact_path(version["artifact"]).unlink()
    Path(prepared["request"]["path"]).unlink()
    before = list(setup.child.calls)
    control.close()
    setup.registry.close()
    with AutoencoderRegistry(setup.database, setup.cas, clock=lambda: setup.clock[0]) as registry:
        restarted = _control(setup, prepared, registry=registry)
        assert _resolution(restarted, "submit-once", "owned-run", descriptor) == submitted
        assert restarted.read("owned-run", descriptor)["status"] == "recovery_required"
        recovered = restarted.execute_pending(max_workers=1)["results"][0]
        assert recovered["status"] == "completed"
        assert recovered["completion"] == committed[0]
        assert recovered["current_artifact_availability_checked"] is False
        assert setup.child.calls == before == ["describe", "execute", "verify"]
        restarted.close()


def test_durable_start_without_coordinator_outcome_is_not_an_implicit_retry(setup, monkeypatch):
    prepared = prepare(setup)
    control = _control(setup, prepared)
    control.submit("submit-once", "owned-run", _ref(prepared))
    original = control_module.run_owned_daemon_invocation
    calls = []
    def stop_before_coordinator(*args, **kwargs):
        calls.append("interrupted")
        raise OSError("synthetic interruption after durable start before coordinator entry")
    monkeypatch.setattr(control_module, "run_owned_daemon_invocation", stop_before_coordinator)
    outcome = control.execute_pending(max_workers=1)
    assert outcome["results"][0]["status"] == "recovery_required"
    monkeypatch.setattr(control_module, "run_owned_daemon_invocation", original)
    control.execute_pending(max_workers=1)
    assert control.read("owned-run", _ref(prepared))["status"] == "recovery_required"
    assert calls == ["interrupted"]
    _assert_no_execution(setup)


def test_same_wire_operation_cannot_be_rebound_to_another_assigned_run(setup):
    first, second = prepare(setup), _second_prepared(setup)
    control = _control(setup, first, assignments={"owned-run": first, "other-owned-run": second})
    submitted = control.submit("same-wire-operation", "owned-run", _ref(first))
    with pytest.raises(ValueError):
        control.submit("same-wire-operation", "other-owned-run", _ref(second))
    assert _resolution(control, "same-wire-operation", "owned-run", _ref(first)) == submitted
    assert control.read("other-owned-run", _ref(second))["status"] == "not_submitted"
    assert setup.child.calls == ["describe", "describe"]


def test_two_workers_have_distinct_operation_namespaces_and_cannot_read_other_scope(setup):
    first, second = prepare(setup), _second_prepared(setup)
    left = _control(setup, first, worker="submitter-a")
    right = _control(setup, second, worker="submitter-b", run_id="other-owned-run")
    left_receipt = left.submit("same-wire-operation", "owned-run", _ref(first))
    right_receipt = right.submit("same-wire-operation", "other-owned-run", _ref(second))
    assert left_receipt["control_operation_id"] != right_receipt["control_operation_id"]
    right_gateway = _gateway(right)
    for command in ("SubmitOwnedInvocation", "ReadOwnedInvocation", "ResolveOwnedInvocation"):
        with pytest.raises(RegistryTransportError, match="assigned worker scope"):
            right_gateway.dispatch(_wire(command, first, operation_id="same-wire-operation"))
    assert _resolution(right, "same-wire-operation", "other-owned-run", _ref(second)) == right_receipt
    assert setup.child.calls == ["describe", "describe"]


def test_owner_can_drain_two_independent_same_base_invocations_without_head_changes(setup):
    first, second = prepare(setup), _second_prepared(setup)
    control = _control(setup, first, assignments={"owned-run": first, "other-owned-run": second})
    before_head = setup.registry.resolve_head("english-0", "best")
    control.submit("first", "owned-run", _ref(first))
    control.submit("second", "other-owned-run", _ref(second))
    overlap = threading.Barrier(2, timeout=8)
    entered_runs = set()
    entered_lock = threading.Lock()
    def require_both_in_execute(launch, request, result):
        with entered_lock:
            entered_runs.add(request["run_id"])
        # Each real owner invocation must reach its synthetic execute boundary
        # before either can proceed. Sequential scheduling cannot pass this.
        overlap.wait()
    setup.child.execute_hook = require_both_in_execute
    outcome = control.execute_pending(max_workers=2)
    assert entered_runs == {"owned-run", "other-owned-run"}
    assert len(outcome["results"]) == 2
    completed = [control.read(run, _ref(prepared)) for run, prepared in
                 (("owned-run", first), ("other-owned-run", second))]
    assert all(row["status"] == "completed" for row in completed)
    versions = [setup.registry.get_version(row["completion"]["version_id"]) for row in completed]
    assert versions[0]["version_id"] != versions[1]["version_id"]
    assert {version["parent_version_id"] for version in versions} == {setup.spec.base_version_id}
    assert setup.child.calls.count("execute") == setup.child.calls.count("verify") == 2
    assert setup.registry.resolve_head("english-0", "best") == before_head
    assert setup.registry.pending_outbox("huggingface") == []


def test_one_invocation_failure_does_not_cancel_the_other_submitted_run(setup):
    first, second = prepare(setup), _second_prepared(setup)
    control = _control(setup, first, assignments={"owned-run": first, "other-owned-run": second})
    control.submit("first", "owned-run", _ref(first))
    control.submit("second", "other-owned-run", _ref(second))
    def fail_only_first(launch, request, result):
        if request["run_id"] == "owned-run":
            raise OSError("synthetic execution failure for first run only")
    setup.child.execute_hook = fail_only_first
    outcome = control.execute_pending(max_workers=2)
    statuses = {row["run_id"]: row for row in outcome["results"]}
    assert statuses["owned-run"]["status"] == "failed"
    assert statuses["other-owned-run"]["status"] == "completed"
    assert statuses["owned-run"]["completion"]["command"] == "FailRun"
    assert statuses["other-owned-run"]["completion"]["command"] == "CompleteRun"
    with journal_for(first) as journal:
        assert journal.get_metadata("quarantine") is not None
        assert "complete" not in journal.operations()
    assert setup.child.calls.count("execute") == 2
    assert setup.child.calls.count("verify") == 1
    before = list(setup.child.calls)
    control.execute_pending(max_workers=2)
    assert setup.child.calls == before


@pytest.mark.parametrize("workers", [False, True, 0, 5, 1.5])
def test_worker_count_is_owner_bounded_and_invalid_values_do_not_execute(setup, workers):
    prepared = prepare(setup)
    control = _control(setup, prepared)
    control.submit("submit-once", "owned-run", _ref(prepared))
    with pytest.raises(ValueError):
        control.execute_pending(max_workers=workers)
    _assert_no_execution(setup)


def test_owned_gateway_is_closed_to_raw_mutations_and_caller_execution_controls(setup):
    prepared = prepare(setup)
    control = _control(setup, prepared)
    gateway = _gateway(control)
    for command, payload in (("ClaimRun", {"run_id": "owned-run"}),
                             ("RenewLease", {"lease": {}}),
                             ("CompleteRun", {"lease": {}, "artifact": {}, "result": {"admitted": False}}),
                             ("ReadRun", {"run_id": "owned-run"})):
        with pytest.raises(RegistryTransportError):
            gateway.dispatch(_envelope(command, payload, "raw-bypass"))
    for extra in ({"max_workers": 4}, {"worker_id": "another-worker"}, {"prepared": prepared},
                  {"timeout_seconds": 999}, {"lease_seconds": 999}):
        with pytest.raises(RegistryTransportError, match="closed command schema"):
            gateway.dispatch(_wire("SubmitOwnedInvocation", prepared, **extra))
    submitted = gateway.dispatch(_wire("SubmitOwnedInvocation", prepared))
    resolution = gateway.dispatch(_wire("ResolveOwnedInvocation", prepared))
    assert resolution["receipt"] == submitted and resolution["resolution"] == "committed"
    assert gateway.dispatch(_wire("ReadOwnedInvocation", prepared, operation_id="read"))["status"] == "accepted"
    _assert_no_execution(setup)


@pytest.mark.parametrize("command", ["SubmitOwnedInvocation", "ReadOwnedInvocation", "ResolveOwnedInvocation"])
def test_owned_gateway_rejects_unassigned_run_and_wrong_request_before_execution(setup, command):
    prepared = prepare(setup)
    gateway = _gateway(_control(setup, prepared))
    with pytest.raises(RegistryTransportError, match="assigned worker scope"):
        gateway.dispatch(_wire(command, prepared, run_id=setup.spec.run_id))
    altered = deepcopy(prepared)
    altered["request"]["sha256"] = "0" * 64
    with pytest.raises(ValueError):
        gateway.dispatch(_wire(command, altered))
    _assert_no_execution(setup)


@pytest.mark.parametrize("kind", ["v1", "v2", "v3", "registered-training-job"])
def test_generic_gateway_cannot_mutate_registered_coordinator_owned_runs(setup, kind):
    changes = {}
    if kind == "v2":
        changes["sparse_shadow"] = True
    elif kind == "v3":
        changes["arrow_feature_weights"] = _explicit_weight_reference(setup)
    prepared = prepare(setup, **changes)
    run_id = setup.spec.run_id if kind == "registered-training-job" else "owned-run"
    gateway = RegistryQuackGateway(setup.registry, WorkerScope("raw-worker", frozenset({run_id})), enable_prototype=True)
    before = setup.registry.get_run(run_id)
    for command, payload in (("ClaimRun", {"run_id": run_id}),
        ("RenewLease", {"lease": {"run_id": run_id, "worker_id": "raw-worker"}}),
        ("CompleteRun", {"lease": {"run_id": run_id, "worker_id": "raw-worker"},
                         "artifact": {}, "result": {"admitted": False}})):
        with pytest.raises(RegistryTransportError):
            gateway.dispatch(_envelope(command, payload, "raw-" + command))
    assert setup.registry.get_run(run_id) == before
    assert setup.child.calls == ["describe"]
