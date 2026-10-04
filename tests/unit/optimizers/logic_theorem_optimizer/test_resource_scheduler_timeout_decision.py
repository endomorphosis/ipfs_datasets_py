"""Actual timeout-branch evidence without pressure probes, proofs or models.

Only host samples/clocks are injected. The real file-backed scheduler decides,
persists waiters/leases and metrics, and releases its process lock normally.
"""
from __future__ import annotations

import json
import threading
import time
from dataclasses import replace
from types import SimpleNamespace

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import resource_scheduler as module
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.proof_resource_safety import ProofHostResources
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.resource_scheduler import (
    GlobalResourceScheduler,
    LeaseCancelledError,
    LeaseTimeoutError,
    ResourceSchedulerConfig,
)


HEALTHY = ProofHostResources(8, 1000, 1000, pid_task_limit=500, available_pid_tasks=400)
STALLED = replace(HEALTHY, memory_stall_percent=2.5)


class Samples:
    def __init__(self, *values):
        self.values = values
        self.calls = 0

    def __call__(self):
        assert self.calls < len(self.values), "unexpected additional proof sample"
        value = self.values[self.calls]
        self.calls += 1
        if isinstance(value, Exception):
            raise value
        return value


def scheduler(tmp_path, samples, *, proof_safety=True, backoff=2.0):
    return GlobalResourceScheduler(ResourceSchedulerConfig(
        total_cpu_slots=6, total_memory_mb=800, total_child_process_slots=6,
        proof_memory_headroom_mb=200, proof_safety_enabled=proof_safety,
        proof_resource_sampler=samples, proof_backoff_seconds=backoff,
        state_path=tmp_path / "resources.json", lane_reservations={},
        auto_renew_leases=False, poll_interval_seconds=0.005,
    ))


def closed_state(native):
    return json.loads(native.state_path.read_text())


def timed_out(native, **kwargs):
    with pytest.raises(LeaseTimeoutError) as caught:
        native.acquire("hammer", cpu_slots=1, memory_mb=100, timeout=0, **kwargs)
    return caught.value


def assert_timeout_decision(error, *, request, parent=None, proof_safety=True):
    decision = error.timeout_decision
    assert decision["schema"] == "resource-lease-timeout-decision@1"
    assert decision["decision_scope"] == "actual_terminal_timeout_branch"
    assert decision["clock_scope"] == "acquire_process_local_monotonic_clock"
    assert decision["timed_out"] is True
    assert decision["can_grant_now"] is False
    assert decision["externally_cancelled"] is False
    assert decision["parent_cancelled"] is False
    assert decision["proof_safety_enabled"] is proof_safety
    assert decision["cycle_monotonic_time"] >= decision["deadline_monotonic"]
    assert decision["elapsed_seconds"] >= 0
    assert decision["request_id"] == request[:256]
    assert decision["lane"] == "hammer"
    assert decision["lane_truncated"] is False
    assert decision["parent_lease_id"] == parent
    assert len(decision["waiter_id"]) == 32
    assert isinstance(decision["sequence"], int)
    assert decision["exact_blocking_predicate"] is None
    assert decision["exact_blocking_cause"] is None
    return decision


def test_legacy_exception_and_independent_copied_descriptors():
    legacy = LeaseTimeoutError("legacy message")
    assert legacy.args == ("legacy message",)
    assert str(legacy) == "legacy message"
    assert isinstance(legacy, TimeoutError)
    assert legacy.admission_observation is None
    assert legacy.timeout_decision is None
    original = {"nested": [1]}
    error = LeaseTimeoutError("copied", admission_observation=original,
                              timeout_decision=original)
    original["nested"][0] = 2
    assert error.admission_observation == error.timeout_decision == {"nested": [1]}
    error.admission_observation["nested"][0] = 3
    assert error.timeout_decision == {"nested": [1]}


@pytest.mark.parametrize("child", [False, True])
def test_root_and_child_timeout_describe_actual_branch_and_keep_parent(tmp_path, child):
    samples = Samples(HEALTHY, HEALTHY, STALLED) if child else Samples(STALLED)
    native = scheduler(tmp_path, samples)
    parent = native.acquire("hammer", cpu_slots=2, memory_mb=300, timeout=0) if child else None
    request = "own-request-" * 30
    try:
        error = timed_out(native, parent=parent, request_id=request)
        decision = assert_timeout_decision(error, request=request,
                                          parent=parent.lease_id if parent else None)
        history = error.proof_refusal_observation
        assert history["historical"] is True
        assert history["waiter_id"] == decision["waiter_id"]
        assert history["sequence"] == decision["sequence"]
        assert history["request_id"] == decision["request_id"]
        assert history["parent_lease_id"] == decision["parent_lease_id"]
        assert samples.calls == (3 if child else 1)
        state = closed_state(native)
        assert state["waiters"] == {}
        assert len(state["leases"]) == (1 if child else 0)
        assert state["metrics"]["timeouts_total"] == 1
        assert "timeout_decision" not in state
    finally:
        if parent:
            parent.release()
    assert closed_state(native)["leases"] == {}


def test_backoff_timeout_has_actual_decision_and_null_own_refusal(tmp_path, monkeypatch):
    samples = Samples(STALLED)
    native = scheduler(tmp_path, samples)
    monkeypatch.setattr(module, "time", SimpleNamespace(
        time=lambda: 1000.0, monotonic=time.monotonic, sleep=time.sleep,
    ))
    first = timed_out(native, request_id="first")
    second = timed_out(native, request_id="second")
    one = assert_timeout_decision(first, request="first")
    two = assert_timeout_decision(second, request="second")
    assert one["waiter_id"] != two["waiter_id"]
    assert second.proof_refusal_observation is None
    assert samples.calls == 1
    state = closed_state(native)
    assert state["last_proof_refusal"] == first.proof_refusal_observation
    assert state["last_proof_refusal"]["waiter_id"] != two["waiter_id"]
    assert state["waiters"] == state["leases"] == {}
    assert state["metrics"]["timeouts_total"] == 2


def test_capacity_only_timeout_keeps_held_lease_and_does_not_sample(tmp_path):
    samples = Samples()
    native = scheduler(tmp_path, samples, proof_safety=False)
    with native.acquire("hammer", cpu_slots=6, memory_mb=100, timeout=0) as held:
        error = timed_out(native, request_id="capacity")
        assert_timeout_decision(error, request="capacity", proof_safety=False)
        assert error.proof_refusal_observation is None
        state = closed_state(native)
        assert set(state["leases"]) == {held.lease_id}
        assert state["waiters"] == {}
        assert state["metrics"]["timeouts_total"] == 1
        assert samples.calls == 0
    assert closed_state(native)["leases"] == {}


def test_unknown_sample_is_separate_from_actual_timeout_branch(tmp_path):
    samples = Samples(OSError("missing telemetry"))
    native = scheduler(tmp_path, samples)
    error = timed_out(native, request_id="unknown-sample")
    assert_timeout_decision(error, request="unknown-sample")
    assert error.proof_refusal_observation["reason"] == "proof_resource_telemetry_unknown"
    assert error.proof_refusal_observation["sample"] is None
    assert error.proof_refusal_observation["error_type"] == "OSError"
    assert samples.calls == 1
    assert closed_state(native)["waiters"] == {}


def test_diagnostic_lane_is_bounded_without_changing_actual_state_lane(tmp_path):
    samples = Samples(STALLED)
    native = scheduler(tmp_path, samples)
    lane = "arbitrary-lane-" * 30
    with pytest.raises(LeaseTimeoutError) as caught:
        native.acquire(lane, cpu_slots=1, memory_mb=100, timeout=0)
    decision = caught.value.timeout_decision
    assert decision["lane"] == lane[:128]
    assert decision["lane_truncated"] is True
    assert decision["waiter_id"] == caught.value.proof_refusal_observation["waiter_id"]
    state = closed_state(native)
    assert state["metrics"]["lanes"][lane]["timeouts_total"] == 1
    assert lane[:128] not in state["metrics"]["lanes"]
    assert state["leases"] == state["waiters"] == {}
    assert samples.calls == 1


def test_actual_timeout_uses_only_original_clock_and_grant_calls(tmp_path, monkeypatch):
    samples = Samples(STALLED)
    native = scheduler(tmp_path, samples)
    calls = {"wall": 0, "monotonic": 0, "grant": 0, "fairness": 0}
    def wall():
        calls["wall"] += 1
        return 1000.0
    def monotonic():
        calls["monotonic"] += 1
        return 10.0
    def no_sleep(_):
        pytest.fail("a timeout0 branch must not sleep")
    original_grant = native._can_grant
    original_fairness = native._is_fair_turn
    def grant(*args, **kwargs):
        calls["grant"] += 1
        return original_grant(*args, **kwargs)
    def fairness(*args, **kwargs):
        calls["fairness"] += 1
        return original_fairness(*args, **kwargs)
    monkeypatch.setattr(native, "_can_grant", grant)
    monkeypatch.setattr(native, "_is_fair_turn", fairness)
    monkeypatch.setattr(module, "time", SimpleNamespace(time=wall, monotonic=monotonic, sleep=no_sleep))
    error = timed_out(native, request_id="clock-count")
    decision = assert_timeout_decision(error, request="clock-count")
    assert calls == {"wall": 3, "monotonic": 2, "grant": 1, "fairness": 0}
    assert samples.calls == 1
    assert decision["cycle_wall_time"] == 1000.0
    assert decision["cycle_monotonic_time"] == decision["deadline_monotonic"] == 10.0
    assert decision["elapsed_seconds"] == 0.0


def test_healthy_final_cycle_grants_after_deadline_without_extra_calls(tmp_path, monkeypatch):
    samples = Samples(HEALTHY, HEALTHY)
    native = scheduler(tmp_path, samples)
    calls = {"wall": 0, "monotonic": 0, "fairness": 0}
    def wall():
        calls["wall"] += 1
        return 1000.0
    def monotonic():
        values = (10.0, 11.0)
        assert calls["monotonic"] < len(values), "unexpected extra clock probe"
        result = values[calls["monotonic"]]
        calls["monotonic"] += 1
        return result
    def no_sleep(_):
        pytest.fail("a healthy final cycle must grant directly")
    original_fairness = native._is_fair_turn
    def fairness(*args, **kwargs):
        calls["fairness"] += 1
        return original_fairness(*args, **kwargs)
    with monkeypatch.context() as patch:
        patch.setattr(native, "_is_fair_turn", fairness)
        patch.setattr(module, "time", SimpleNamespace(time=wall, monotonic=monotonic, sleep=no_sleep))
        lease = native.acquire("hammer", cpu_slots=1, memory_mb=100, timeout=0.1)
    try:
        assert lease.wait_seconds == 1.0
        assert calls == {"wall": 3, "monotonic": 2, "fairness": 1}
        assert samples.calls == 2
        assert closed_state(native)["metrics"]["timeouts_total"] == 0
    finally:
        lease.release()
    assert closed_state(native)["leases"] == closed_state(native)["waiters"] == {}


def test_cancellation_wins_at_deadline_without_timeout_descriptor(tmp_path):
    samples = Samples(STALLED)
    native = scheduler(tmp_path, samples)
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(LeaseCancelledError) as caught:
        native.acquire("hammer", cpu_slots=1, memory_mb=100, timeout=0, cancel_event=cancel)
    assert not isinstance(caught.value, LeaseTimeoutError)
    assert not hasattr(caught.value, "timeout_decision")
    assert samples.calls == 1  # Existing grant evaluation still precedes cancellation.
    state = closed_state(native)
    assert state["metrics"]["timeouts_total"] == 0
    assert state["metrics"]["cancellations_total"] == 1
    assert state["waiters"] == state["leases"] == {}


def test_own_historical_refusal_is_not_final_rival_fairness_cause(tmp_path):
    cancelled = threading.Event()
    observed = threading.Event()
    current_calls = [0]
    older_errors = []
    def sample():
        if threading.current_thread().name == "older-timeout-decision":
            observed.set()
            return replace(HEALTHY, memory_stall_percent=3.5)
        current_calls[0] += 1
        return STALLED if current_calls[0] == 1 else HEALTHY
    native = scheduler(tmp_path, sample, backoff=0)
    def older():
        try:
            native.acquire("hammer", cpu_slots=1, memory_mb=100, timeout=2,
                           cancel_event=cancelled, request_id="older")
        except Exception as exc:
            older_errors.append(exc)
    contender = threading.Thread(target=older, name="older-timeout-decision")
    contender.start()
    try:
        assert observed.wait(1)
        assert native.snapshot()["waiting_request_count"] == 1
        with pytest.raises(LeaseTimeoutError) as caught:
            native.acquire("hammer", cpu_slots=1, memory_mb=100,
                           timeout=0.04, request_id="current")
        own = caught.value.proof_refusal_observation
        decision = assert_timeout_decision(caught.value, request="current")
        assert own["request_id"] == "current"
        assert own["waiter_id"] == decision["waiter_id"]
        assert own["historical"] is True
        assert own["sample"]["memory_stall_percent"] == 2.5
        assert current_calls[0] >= 5
    finally:
        cancelled.set()
        contender.join(2)
    assert not contender.is_alive()
    assert len(older_errors) == 1 and isinstance(older_errors[0], LeaseCancelledError)
    state = closed_state(native)
    assert state["last_proof_refusal"]["request_id"] == "older"
    assert state["last_proof_refusal"]["waiter_id"] != decision["waiter_id"]
    assert state["waiters"] == state["leases"] == {}
    assert state["metrics"]["timeouts_total"] == state["metrics"]["cancellations_total"] == 1
