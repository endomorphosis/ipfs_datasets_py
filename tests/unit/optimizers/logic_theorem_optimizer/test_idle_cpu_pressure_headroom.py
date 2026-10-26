"""Explicit CPU threshold changes on real private scheduler metadata.

Only host telemetry is an injected, declared unit-test observation. Scheduler
locking, typed policy validation, pin binding and atomic persistence remain the
production implementation. No shared host state, inference or proof job runs.
"""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import time

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import existing_resource_scheduler as existing
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import resource_scheduler as native


def read(path):
    return json.loads(path.read_bytes())


def write(path, state):
    path.write_text(json.dumps(state, sort_keys=True, indent=2) + "\n")


@pytest.fixture
def private(tmp_path, monkeypatch):
    path = tmp_path / "private-native-scheduler.json"
    native.GlobalResourceScheduler(native.ResourceSchedulerConfig(
        state_path=path, total_cpu_slots=4, total_memory_mb=4096,
        total_child_process_slots=4, lane_reservations={"validation": {"cpu_slots": 1, "memory_mb": 0}},
        proof_safety_enabled=True, proof_memory_headroom_mb=512,
        proof_backoff_seconds=0.0, auto_renew_leases=False))
    state = read(path)
    state["next_sequence"] = 99
    state["metrics"]["acquisitions_total"] = 37
    state["metrics"]["timeouts_total"] = 11
    state["last_proof_refusal"] = {"historical": True, "reason": "preserve-private-refusal"}
    state["proof_backoff"] = {"until": 1.0, "reason": "preserve-expired-private-pressure"}
    state["retained_extension"] = {"task_history": ["never-reset"], "opaque_budget": 17}
    write(path, state)
    sentinel = tmp_path / "preserved-private-evidence"
    sentinel.write_bytes(b"retain this evidence")
    settings = {"sample": lambda: native.ProofHostResources(8, 8192, 8192,
        cpu_stall_percent=55.0, pid_task_limit=500, available_pid_tasks=400)}
    source = Path(native.__file__).with_name("proof_resource_safety.py")
    source_sha = hashlib.sha256(source.read_bytes()).hexdigest()
    calls = []
    def declared_private_telemetry(config):
        calls.append(config.persisted_dict())
        return settings["sample"](), source_sha
    monkeypatch.setattr(existing, "_native_capacity_host", declared_private_telemetry)
    return path, existing.policy_sha256(state["config"]), state, settings, calls, sentinel


def test_default_plan_preserves_state_history_files_and_global_facades(private):
    path, expected, state, _, calls, sentinel = private
    before, globals_before = path.read_bytes(), dict(native._GLOBAL_SCHEDULERS)
    report = existing.expand_idle_cpu_pressure_headroom(path, expected, 65)
    assert report["schema"] == "native-idle-cpu-pressure-headroom-plan/v1"
    assert report["status"] == "ready_explicit_policy_rebind"
    assert report["applied"] is report["admitted"] is report["qualified"] is report["resource_allocation_performed"] is False
    assert report["previous_cpu_stall_percent"] == 50.0
    assert type(report["requested_cpu_stall_percent"]) is float and report["requested_cpu_stall_percent"] == 65.0
    assert report["changed_policy_fields"] == ["proof_cpu_stall_percent"]
    assert report["next_policy"] == {**state["config"], "proof_cpu_stall_percent": 65.0}
    assert report["next_policy_sha256"] == existing.policy_sha256(report["next_policy"])
    assert report["pressure"] == {"memory_full": 0.0, "cpu_some": 55.0, "io_full": 0.0}
    assert len(calls) == 1
    assert path.read_bytes() == before
    assert sentinel.read_bytes() == b"retain this evidence"
    assert native._GLOBAL_SCHEDULERS == globals_before


def test_apply_changes_only_cpu_policy_preserves_all_history_and_requires_new_pin(private):
    path, expected, state, _, _, sentinel = private
    stale = existing.open_existing_scheduler(path, expected)
    report = existing.expand_idle_cpu_pressure_headroom(path, expected, 65, apply=True)
    after = read(path)
    assert report["applied"] is True and report["status"] == "applied_requires_explicit_policy_rebind"
    assert after == {**state, "config": {**state["config"], "proof_cpu_stall_percent": 65.0}}
    assert report["preserved_control_sha256"] == existing.policy_sha256({key: value for key, value in state.items() if key != "config"})
    assert after["proof_backoff"] == state["proof_backoff"]
    assert sentinel.read_bytes() == b"retain this evidence"
    with pytest.raises(existing.ExistingResourceSchedulerError, match="policy changed"):
        stale.active_leases()
    with pytest.raises(existing.ExistingResourceSchedulerError, match="exact stored"):
        existing.open_existing_scheduler(path, expected)
    fresh = existing.open_existing_scheduler(path, report["next_policy_sha256"])
    assert fresh.config.persisted_dict() == after["config"]
    assert fresh.active_leases() == []


@pytest.mark.parametrize("activity", ["leases", "waiters", "proof_recovery", "proof_backoff"])
def test_active_native_control_state_holds_dry_run_and_refuses_apply_without_recovery(private, activity):
    path, _, state, _, calls, _ = private
    state = deepcopy(state)
    if activity in {"leases", "waiters"}:
        state[activity] = {"retained": {"owner_pid": os.getpid(), "lane": "validation",
            "cpu_slots": 1, "memory_mb": 64, "child_process_slots": 1}}
    elif activity == "proof_recovery":
        state["config"]["proof_recovery_enabled"] = True
        state[activity] = {"phase": "settling", "healthy_samples": 0,
            "next_sample_at": time.time() + 60, "next_grant_at": 0.0,
            "grants_remaining": state["config"]["proof_recovery_grants"]}
    else:
        state[activity] = {"until": time.time() + 60, "reason": "private-active-pressure"}
    write(path, state)
    expected, before = existing.policy_sha256(state["config"]), path.read_bytes()
    report = existing.expand_idle_cpu_pressure_headroom(path, expected, 65)
    assert report["status"] == "held_native_activity" and report["applied"] is False
    assert report["resource_allocation_performed"] is False
    with pytest.raises(existing.ExistingResourceSchedulerError, match="idle scheduler required"):
        existing.expand_idle_cpu_pressure_headroom(path, expected, 65, apply=True)
    assert not calls and path.read_bytes() == before


@pytest.mark.parametrize("value", [True, None, "65", 49.0, 50.0, float("nan"), float("inf"), 76, 10 ** 400])
def test_cpu_threshold_must_be_plain_finite_strictly_increasing_and_at_most_seventy_five(private, value):
    path, expected, _, _, calls, _ = private
    before = path.read_bytes()
    with pytest.raises(existing.ExistingResourceSchedulerError):
        existing.expand_idle_cpu_pressure_headroom(path, expected, value, apply=True)
    assert path.read_bytes() == before and not calls


@pytest.mark.parametrize("profile", ["disabled_safety", "named_profile"])
def test_disabled_safety_or_named_proof_profile_cannot_be_changed(private, profile):
    path, _, state, _, calls, _ = private
    state = deepcopy(state)
    if profile == "disabled_safety":
        state["config"]["proof_safety_enabled"] = False
    else:
        state["config"].update(proof_resource_profile=native.LOCAL_BENCHMARK_PROOF_PROFILE,
            proof_memory_stall_percent=10.0, proof_memory_headroom_mb=1024,
            proof_recovery_enabled=True, proof_recovery_grants=1)
    write(path, state)
    before = path.read_bytes()
    with pytest.raises(existing.ExistingResourceSchedulerError):
        existing.expand_idle_cpu_pressure_headroom(path, existing.policy_sha256(state["config"]), 65, apply=True)
    assert path.read_bytes() == before and not calls


@pytest.mark.parametrize("mode", ["cpu_equality", "memory_pressure", "io_pressure", "unknown_pid", "pid_shortage", "memory_shortage", "unknown_telemetry", "wrong_type"])
def test_cpu_headroom_keeps_native_memory_io_and_pid_guards(private, mode):
    path, expected, _, settings, _, _ = private
    values = dict(cpu_slots=8, total_memory_mb=8192, available_memory_mb=8192,
        cpu_stall_percent=55.0, pid_task_limit=500, available_pid_tasks=400)
    if mode == "cpu_equality": values["cpu_stall_percent"] = 65.0
    elif mode == "memory_pressure": values["memory_stall_percent"] = 2.0
    elif mode == "io_pressure": values["io_stall_percent"] = 10.0
    elif mode == "unknown_pid": values.update(pid_task_limit=None, available_pid_tasks=None)
    elif mode == "pid_shortage": values["available_pid_tasks"] = 0
    elif mode == "memory_shortage": values["available_memory_mb"] = 511
    if mode == "unknown_telemetry":
        def unknown():
            raise existing.ExistingResourceSchedulerError("declared private unknown host observation")
        settings["sample"] = unknown
    elif mode == "wrong_type": settings["sample"] = lambda: dict(values)
    else: settings["sample"] = lambda: native.ProofHostResources(**values)
    before = path.read_bytes()
    with pytest.raises(existing.ExistingResourceSchedulerError):
        existing.expand_idle_cpu_pressure_headroom(path, expected, 65, apply=True)
    assert path.read_bytes() == before


def test_native_state_changed_outside_lock_is_refused_without_overwriting_it(private):
    path, expected, state, settings, _, _ = private
    changed = deepcopy(state)
    changed["retained_extension"]["opaque_budget"] = 18
    def outside_writer():
        write(path, changed)
        return native.ProofHostResources(8, 8192, 8192, cpu_stall_percent=55.0,
            pid_task_limit=500, available_pid_tasks=400)
    settings["sample"] = outside_writer
    with pytest.raises(existing.ExistingResourceSchedulerError, match="outside lock"):
        existing.expand_idle_cpu_pressure_headroom(path, expected, 65, apply=True)
    assert read(path) == changed


def test_native_grant_at_fifty_five_pressure_needs_explicit_new_policy_binding(private):
    path, expected, _, settings, _, _ = private
    old = existing.open_existing_scheduler(path, expected)
    old.config.auto_renew_leases = False
    old.config.proof_resource_sampler = settings["sample"]
    with pytest.raises(native.LeaseTimeoutError):
        old.acquire("validation", cpu_slots=1, memory_mb=64, child_process_slots=1,
            timeout=0, request_id="private-old-fifty-percent-guard")
    after_refusal = read(path)
    assert after_refusal["leases"] == after_refusal["waiters"] == {}
    report = existing.expand_idle_cpu_pressure_headroom(path, expected, 65, apply=True)
    assert {k: v for k, v in read(path).items() if k != "config"} == {k: v for k, v in after_refusal.items() if k != "config"}
    fresh = existing.open_existing_scheduler(path, report["next_policy_sha256"])
    fresh.config.auto_renew_leases = False
    fresh.config.proof_resource_sampler = settings["sample"]
    lease = fresh.acquire("validation", cpu_slots=1, memory_mb=64, child_process_slots=1,
        timeout=0, request_id="private-explicit-sixty-five-percent-rebind")
    try:
        assert lease.child_process_slots == 1 and len(fresh.active_leases()) == 1
    finally:
        assert lease.release()
    assert fresh.active_leases() == []


@pytest.mark.parametrize("apply", [1, None, "true"])
def test_apply_flag_requires_actual_boolean(private, apply):
    path, expected, _, _, calls, _ = private
    before = path.read_bytes()
    with pytest.raises(existing.ExistingResourceSchedulerError, match="explicit bool"):
        existing.expand_idle_cpu_pressure_headroom(path, expected, 65, apply=apply)
    assert path.read_bytes() == before and not calls


def test_upper_bound_seventy_five_is_an_explicit_dry_run_not_an_allocation(private):
    path, expected, state, _, _, _ = private
    before = path.read_bytes()
    report = existing.expand_idle_cpu_pressure_headroom(path, expected, 75)
    assert report["next_policy"] == {**state["config"], "proof_cpu_stall_percent": 75.0}
    assert report["applied"] is report["resource_allocation_performed"] is False
    assert path.read_bytes() == before
