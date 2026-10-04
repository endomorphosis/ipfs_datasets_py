"""The native harness preserves exact shared policy or refuses before mutation."""
import json
import os
from pathlib import Path
import sys
import time

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import resource_scheduler as scheduler

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "benchmarks"))
import bench_smt_operation_control as benchmark


def write_state(path, state):
    path.write_text(json.dumps(state, sort_keys=True, separators=(",", ":")))


def fixture_state(tmp_path, *, extras=True, recovery=False, foreign=False):
    """Build private state only; no real shared pool or host sampler is changed."""
    config = scheduler.ResourceSchedulerConfig(state_path=tmp_path / "pool.json",
        total_cpu_slots=4, total_memory_mb=9830, total_child_process_slots=4,
        lane_reservations={"validation": scheduler.LaneReservation(cpu_slots=1)},
        proof_safety_enabled=True, proof_memory_headroom_mb=2458,
        auto_renew_leases=False)
    owner = scheduler.GlobalResourceScheduler(config)
    state = json.loads(owner.state_path.read_text())
    if extras:
        state["config"].update(benchmark._DISABLED_RECOVERY_FIELDS)
    if recovery:
        state["proof_recovery"] = {}
    if foreign:
        now, pid = time.time(), os.getppid()
        common = {"lane": "validation", "cpu_slots": 1, "memory_mb": 64,
            "gpu_memory_mb": 0, "unified_memory_mb": 0, "child_process_slots": 1,
            "requires_gpu": False, "parent_lease_id": None, "owner_pid": pid,
            "owner_birth_marker": scheduler._owner_birth_marker(pid),
            "owner_boot_id": scheduler._owner_boot_id(), "request_id": "foreign:fixture",
            "foreign_metadata": {"retain": ["all", "fields"]}}
        state["leases"]["foreign-lease"] = {**common, "lease_id": "foreign-lease",
            "lease_key": "foreign-secret", "sequence": 1, "acquired_at": now, "heartbeat_at": now,
            "expires_at": now + 120, "cancelled": False, "wait_seconds": 0.0}
        state["waiters"]["foreign-waiter"] = {**common, "waiter_id": "foreign-waiter",
            "sequence": 2, "created_at": now, "saturation_recorded": False}
        state["next_sequence"] = 3
    write_state(owner.state_path, state)
    return owner.state_path, state


@pytest.mark.parametrize("extras,recovery", [(False, False), (False, True), (True, False), (True, True)])
def test_exact_saved_policy_round_trips_with_real_sampler_and_foreign_fields(tmp_path, extras, recovery):
    path, state = fixture_state(tmp_path, extras=extras, recovery=recovery, foreign=True)
    before = path.read_bytes()
    config, metadata = benchmark.pinned_config(state["config"], path)
    assert benchmark._config_bytes(config.persisted_dict()) == benchmark._config_bytes(state["config"])
    assert config.proof_resource_sampler is scheduler.collect_proof_host_resources
    assert config.resource_pressure_sampler is None
    owner = benchmark.guarded_owner(config, state["config"])
    assert owner.snapshot()["active_lease_count"] == 1
    assert owner.snapshot()["waiting_request_count"] == 1
    assert path.read_bytes() == before
    assert json.loads(path.read_text())["leases"] == state["leases"]
    assert json.loads(path.read_text())["waiters"] == state["waiters"]
    assert metadata["production_recovery_policy_imported"] is False
    assert metadata["mode"] == ("reviewed_disabled_recovery_metadata" if extras else "native_config")
    # Caller changes after construction cannot change owned config or its pin.
    state["config"]["total_cpu_slots"] = 1000
    assert config.total_cpu_slots == 4 and owner.snapshot()["active_lease_count"] == 1
    assert path.read_bytes() == before


@pytest.mark.parametrize("change", [
    {"proof_recovery_enabled": True}, {"proof_recovery_enabled": 0},
    {"proof_recovery_samples": 2.0}, {"proof_recovery_samples": True},
    {"proof_recovery_samples": 3}, {"proof_recovery_grants": 4.0},
    {"proof_recovery_grants": 5}, {"proof_recovery_interval_seconds": 0.5},
    {"proof_recovery_interval_seconds": "0.25"},
    {"proof_recovery_interval_seconds": float("nan")},
    {"unknown_policy": False}, {"proof_recovery_other": False},
    {"proof_safety_enabled": False}, {"proof_safety_enabled": 1},
])
def test_unknown_enabled_revised_or_wrong_typed_policy_refuses_without_state_write(tmp_path, change):
    path, state = fixture_state(tmp_path)
    state["config"].update(change)
    write_state(path, state)
    before = path.read_bytes()
    with pytest.raises(scheduler.ResourceConfigurationError):
        benchmark.pinned_config(state["config"], path)
    assert path.read_bytes() == before


@pytest.mark.parametrize("missing", [*benchmark._DISABLED_RECOVERY_FIELDS, "total_cpu_slots", "max_waiting_requests"])
def test_partial_metadata_or_incomplete_native_configuration_refuses(tmp_path, missing):
    path, state = fixture_state(tmp_path)
    del state["config"][missing]
    write_state(path, state)
    before = path.read_bytes()
    with pytest.raises(scheduler.ResourceConfigurationError):
        benchmark.pinned_config(state["config"], path)
    assert path.read_bytes() == before


@pytest.mark.parametrize("recovery", [None, False, [], 0, "", {"phase": "settling"}])
def test_foreign_recovery_must_be_absent_or_exact_empty_dict(tmp_path, recovery):
    path, state = fixture_state(tmp_path)
    state["proof_recovery"] = recovery
    write_state(path, state)
    before = path.read_bytes()
    config, _ = benchmark.pinned_config(state["config"], path)
    with pytest.raises(scheduler.ResourceConfigurationError, match="foreign proof recovery"):
        benchmark.guarded_owner(config, state["config"])
    assert path.read_bytes() == before


@pytest.mark.parametrize("operation", ["snapshot", "active_leases", "recover_stale_leases", "acquire"])
@pytest.mark.parametrize("mutation", ["recovery", "capacity", "numeric_type"])
def test_every_state_lock_refuses_later_drift_before_foreign_state_changes(tmp_path, operation, mutation):
    path, state = fixture_state(tmp_path, foreign=True)
    config, _ = benchmark.pinned_config(state["config"], path)
    owner = benchmark.guarded_owner(config, state["config"])
    if mutation == "recovery":
        state["proof_recovery"] = {"phase": "paced"}
    elif mutation == "numeric_type":
        state["config"]["proof_recovery_samples"] = 2.0
    else:
        state["config"]["total_cpu_slots"] += 1
    write_state(path, state)
    before = path.read_bytes()
    with pytest.raises(scheduler.ResourceConfigurationError):
        if operation == "acquire":
            owner.acquire("validation", cpu_slots=1, memory_mb=64, child_process_slots=1, timeout=0)
        else:
            getattr(owner, operation)()
    assert path.read_bytes() == before


@pytest.mark.parametrize("missing", [False, True])
@pytest.mark.parametrize("opened", [False, True])
def test_missing_or_empty_state_is_never_recreated(tmp_path, missing, opened):
    path, state = fixture_state(tmp_path)
    config, _ = benchmark.pinned_config(state["config"], path)
    owner = benchmark.guarded_owner(config, state["config"]) if opened else None
    if missing:
        path.unlink()
    else:
        path.write_bytes(b" \n")
    with pytest.raises(scheduler.ResourceConfigurationError, match="recreation"):
        if opened:
            owner.snapshot()
        else:
            benchmark.guarded_owner(config, state["config"])
    assert not path.exists() if missing else path.read_bytes() == b" \n"


def test_mutated_local_facade_cannot_adopt_matching_external_config_drift(tmp_path):
    path, state = fixture_state(tmp_path)
    config, _ = benchmark.pinned_config(state["config"], path)
    owner = benchmark.guarded_owner(config, state["config"])
    config.total_cpu_slots = 5
    state["config"]["total_cpu_slots"] = 5
    write_state(path, state)
    before = path.read_bytes()
    with pytest.raises(scheduler.ResourceConfigurationError, match="configuration drift"):
        owner.snapshot()
    assert path.read_bytes() == before


def test_install_retains_complete_policy_and_foreign_work_before_default_registration(tmp_path, monkeypatch):
    path, state = fixture_state(tmp_path, foreign=True)
    pin = tmp_path / "saved.json"
    benchmark.write(pin, {"schema": benchmark.saved.PIN_SCHEMA, "state_path": str(path),
        "config": state["config"], "allow_foreign_work": True})
    before = path.read_bytes()
    monkeypatch.setattr(scheduler, "_GLOBAL_SCHEDULERS", {})
    original = scheduler.default_resource_scheduler_config
    monkeypatch.setattr(scheduler, "default_resource_scheduler_config", original)
    owner, envelope = benchmark.install_saved_owner(pin)
    assert scheduler.get_global_resource_scheduler() is owner
    assert owner._benchmark_pool_compatibility["mode"] == "reviewed_disabled_recovery_metadata"
    assert envelope["config"] == state["config"]
    assert path.read_bytes() == before


def test_failed_install_does_not_register_or_replace_default_owner(tmp_path, monkeypatch):
    path, state = fixture_state(tmp_path)
    pin = tmp_path / "saved.json"
    benchmark.write(pin, {"schema": benchmark.saved.PIN_SCHEMA, "state_path": str(path),
        "config": state["config"], "allow_foreign_work": True})
    state["proof_recovery"] = {"phase": "paced"}
    write_state(path, state)
    before = path.read_bytes()
    registry = {}
    original = scheduler.default_resource_scheduler_config
    monkeypatch.setattr(scheduler, "_GLOBAL_SCHEDULERS", registry)
    monkeypatch.setattr(scheduler, "default_resource_scheduler_config", original)
    with pytest.raises(scheduler.ResourceConfigurationError):
        benchmark.install_saved_owner(pin)
    assert scheduler.default_resource_scheduler_config is original and registry == {}
    assert path.read_bytes() == before
