"""Bounded refusal evidence from the real file-backed resource scheduler.

Host samples are injected; admission, leases, fairness, process locks and
durable JSON writes use the production scheduler. No proofs or models run.
"""
from __future__ import annotations

import json
import threading
import time
from dataclasses import replace
from pathlib import Path
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


class Samples:
    def __init__(self, *samples: ProofHostResources | Exception) -> None:
        self.samples = samples
        self.calls = 0

    def __call__(self) -> ProofHostResources:
        assert self.calls < len(self.samples), "unexpected additional pressure sample"
        sample = self.samples[self.calls]
        self.calls += 1
        if isinstance(sample, Exception):
            raise sample
        return sample


def scheduler(
    tmp_path: Path, sampler, *, backoff: float = 2.0, proof_safety: bool = True,
) -> GlobalResourceScheduler:
    return GlobalResourceScheduler(ResourceSchedulerConfig(
        total_cpu_slots=6,
        total_memory_mb=800,
        total_child_process_slots=6,
        proof_memory_headroom_mb=200,
        proof_safety_enabled=proof_safety,
        proof_resource_sampler=sampler,
        proof_backoff_seconds=backoff,
        state_path=tmp_path / "resources.json",
        lane_reservations={},
        auto_renew_leases=False,
        poll_interval_seconds=0.005,
    ))


def closed_state(native: GlobalResourceScheduler) -> dict:
    # Reopen the durable file after the public operation has released its lock.
    with native.state_path.open(encoding="utf-8") as handle:
        return json.load(handle)


def refused(native: GlobalResourceScheduler, **kwargs) -> LeaseTimeoutError:
    with pytest.raises(LeaseTimeoutError, match="^timed out waiting for a resource lease$") as caught:
        native.acquire("hammer", cpu_slots=1, memory_mb=100, timeout=0, **kwargs)
    assert isinstance(caught.value, TimeoutError)
    return caught.value


@pytest.mark.parametrize("field,threshold,reason", [
    ("memory_stall_percent", 2.0, "proof_memory_stall"),
    ("cpu_stall_percent", 50.0, "proof_cpu_stall"),
    ("io_stall_percent", 10.0, "proof_io_stall"),
])
def test_threshold_equality_refuses_with_the_actual_single_sample(
    tmp_path, field, threshold, reason,
):
    sample = replace(HEALTHY, **{field: threshold})
    samples = Samples(sample)
    native = scheduler(tmp_path, samples)
    error = refused(native, request_id="threshold-equality")
    observation = error.proof_refusal_observation
    assert samples.calls == 1
    assert observation["sample"][field] == threshold
    assert observation["thresholds"][field] == threshold
    assert observation["reason"] == reason
    assert observation["gate"] == "envelope"
    assert observation["historical"] is True
    state = closed_state(native)
    assert state["last_proof_refusal"] == observation
    assert state["proof_backoff"]["reason"] == reason
    assert state["waiters"] == state["leases"] == {}
    assert state["metrics"]["timeouts_total"] == 1


@pytest.mark.parametrize("gate,reason,calls", [
    ("envelope", "proof_io_stall", 1),
    ("request_pressure", "proof_memory_stall", 2),
])
def test_existing_gate_reason_precedence_is_preserved(tmp_path, gate, reason, calls):
    all_stalled = replace(HEALTHY, memory_stall_percent=2, cpu_stall_percent=50, io_stall_percent=10)
    samples = Samples(all_stalled) if calls == 1 else Samples(HEALTHY, all_stalled)
    error = refused(scheduler(tmp_path, samples))
    assert error.proof_refusal_observation["gate"] == gate
    assert error.proof_refusal_observation["reason"] == reason
    assert samples.calls == calls


@pytest.mark.parametrize("child", [False, True])
def test_second_gate_records_its_own_refusing_sample_for_roots_and_children(tmp_path, child):
    sample = replace(HEALTHY, memory_stall_percent=3.25)
    samples = Samples(*(HEALTHY, HEALTHY, HEALTHY, sample) if child else (HEALTHY, sample))
    native = scheduler(tmp_path, samples)
    parent = native.acquire("hammer", cpu_slots=2, memory_mb=300, timeout=0) if child else None
    try:
        error = refused(native, parent=parent, request_id="second-gate")
        observation = error.proof_refusal_observation
        assert samples.calls == (4 if child else 2)
        assert observation["gate"] == "request_pressure"
        assert observation["sample"]["memory_stall_percent"] == 3.25
        assert observation["backoff_until"] is None
        assert observation["demand"] == {"requested_memory_mb": 100}
        assert observation["parent_lease_id"] == (parent.lease_id if child else None)
        assert closed_state(native)["last_proof_refusal"] == observation
    finally:
        if parent is not None:
            parent.release()
    state = closed_state(native)
    assert state["leases"] == state["waiters"] == {}
    assert state["metrics"]["acquisitions_total"] == state["metrics"]["releases_total"]


@pytest.mark.parametrize("second", [False, True])
def test_telemetry_exceptions_keep_sample_unknown_and_make_no_reprobe(tmp_path, second):
    samples = Samples(HEALTHY, OSError("unavailable")) if second else Samples(OSError("unavailable"))
    native = scheduler(tmp_path, samples)
    error = refused(native)
    observation = error.proof_refusal_observation
    assert observation["reason"] == "proof_resource_telemetry_unknown"
    assert observation["sample"] is None
    assert observation["error_type"] == "OSError"
    assert observation["gate"] == ("request_pressure" if second else "envelope")
    assert samples.calls == (2 if second else 1)
    assert closed_state(native)["last_proof_refusal"] == observation


@pytest.mark.parametrize("sample,reason,demand_field,required", [
    (replace(HEALTHY, available_memory_mb=299), "proof_memory_headroom", "additional_memory_mb", 100),
    (replace(HEALTHY, available_pid_tasks=47), "proof_pid_headroom", "pid_tasks_required", 48),
])
def test_refusal_retains_native_memory_and_pid_demand(tmp_path, sample, reason, demand_field, required):
    samples = Samples(sample)
    error = refused(scheduler(tmp_path, samples), child_process_slots=1)
    observation = error.proof_refusal_observation
    assert samples.calls == 1
    assert observation["reason"] == reason
    assert observation["proof_memory_headroom_mb"] == 200
    assert observation["demand"][demand_field] == required
    assert observation["sample"]["available_memory_mb"] == sample.available_memory_mb
    assert observation["sample"]["available_pid_tasks"] == sample.available_pid_tasks


def test_shared_backoff_does_not_sample_or_attribute_a_rivals_observation(tmp_path, monkeypatch):
    wall = [1000.0]
    monkeypatch.setattr(module, "time", SimpleNamespace(
        time=lambda: wall[0], monotonic=time.monotonic, sleep=time.sleep,
    ))
    samples = Samples(replace(HEALTHY, memory_stall_percent=2.5))
    native = scheduler(tmp_path, samples)
    first = refused(native, request_id="first" * 100).proof_refusal_observation
    second = refused(native, request_id="different-waiter").proof_refusal_observation
    assert samples.calls == 1
    assert second is None
    state = closed_state(native)
    assert state["last_proof_refusal"] == first
    assert len(first["request_id"]) == 256
    assert state["proof_backoff"]["until"] == 1002.0
    assert state["metrics"]["timeouts_total"] == 2
    assert state["waiters"] == state["leases"] == {}


def test_later_safe_admission_retains_closed_history_without_using_it_as_authority(tmp_path, monkeypatch):
    wall = [1000.0]
    monkeypatch.setattr(module, "time", SimpleNamespace(
        time=lambda: wall[0], monotonic=time.monotonic, sleep=time.sleep,
    ))
    samples = Samples(replace(HEALTHY, memory_stall_percent=2.5), HEALTHY, HEALTHY)
    native = scheduler(tmp_path, samples)
    error = refused(native, request_id="old-refusal")
    retained = closed_state(native)["last_proof_refusal"]
    # Caller mutation of copied evidence cannot alter persisted history.
    error.proof_refusal_observation["sample"]["memory_stall_percent"] = 99
    wall[0] = 1003.0
    with native.acquire("hammer", cpu_slots=1, memory_mb=100, timeout=0):
        assert native.snapshot()["last_proof_refusal"] == retained
    assert samples.calls == 3
    state = closed_state(native)
    assert state["proof_backoff"] == {}
    assert state["last_proof_refusal"] == retained
    projection = native.snapshot()
    projection["last_proof_refusal"]["sample"]["memory_stall_percent"] = 88
    assert closed_state(native)["last_proof_refusal"] == retained
    assert state["leases"] == state["waiters"] == {}


def test_timeout_keeps_its_own_refusal_when_fairness_examines_an_older_waiter(tmp_path):
    cancelled = threading.Event()
    observed = threading.Event()
    current_calls = [0]
    older_errors = []

    def sample():
        if threading.current_thread().name == "older-refusal":
            observed.set()
            return replace(HEALTHY, memory_stall_percent=3.5)
        current_calls[0] += 1
        # This request first refuses; on subsequent cycles it passes both
        # gates, while the genuine older waiter wins the fairness check.
        return replace(HEALTHY, memory_stall_percent=2.5) if current_calls[0] == 1 else HEALTHY

    native = scheduler(tmp_path, sample, backoff=0)

    def older():
        try:
            native.acquire("hammer", cpu_slots=1, memory_mb=100,
                timeout=2, cancel_event=cancelled, request_id="older")
        except Exception as exc:
            older_errors.append(exc)

    contender = threading.Thread(target=older, name="older-refusal")
    contender.start()
    try:
        assert observed.wait(1)
        assert native.snapshot()["waiting_request_count"] == 1
        with pytest.raises(LeaseTimeoutError) as caught:
            native.acquire("hammer", cpu_slots=1, memory_mb=100,
                timeout=0.04, request_id="current")
        own = caught.value.proof_refusal_observation
        assert own["request_id"] == "current"
        assert own["sample"]["memory_stall_percent"] == 2.5
        assert current_calls[0] >= 5  # own two gates plus older fairness gates
    finally:
        cancelled.set()
        contender.join(2)
    assert not contender.is_alive()
    assert len(older_errors) == 1 and isinstance(older_errors[0], LeaseCancelledError)
    state = closed_state(native)
    assert state["last_proof_refusal"]["request_id"] == "older"
    assert state["last_proof_refusal"]["waiter_id"] != own["waiter_id"]
    assert state["leases"] == state["waiters"] == {}
    assert state["metrics"]["timeouts_total"] == state["metrics"]["cancellations_total"] == 1


def test_disabled_proof_safety_does_not_sample_or_create_refusal_evidence(tmp_path):
    samples = Samples()
    native = scheduler(tmp_path, samples, proof_safety=False)
    with native.acquire("hammer", cpu_slots=1, memory_mb=100, timeout=0):
        assert native.snapshot()["last_proof_refusal"] is None
    assert samples.calls == 0
    assert "last_proof_refusal" not in closed_state(native)
