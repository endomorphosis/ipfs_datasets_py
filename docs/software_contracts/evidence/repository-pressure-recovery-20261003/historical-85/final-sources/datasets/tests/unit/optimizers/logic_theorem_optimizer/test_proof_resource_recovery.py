"""Injected pressure/clock controls for the real shared scheduler owner.

These are deterministic protocol controls, not actual external-load tests.
"""
from dataclasses import replace
import json
import threading
import time

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import resource_scheduler as mod
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.proof_resource_safety import ProofHostResources


HEALTHY = ProofHostResources(8, 8192, 8192)


def config(path, sampler, **overrides):
    values = dict(state_path=path, total_cpu_slots=8, total_memory_mb=8192,
        total_child_process_slots=8, lane_reservations={"validation": 1},
        proof_safety_enabled=True, proof_resource_sampler=sampler,
        proof_backoff_seconds=2, proof_recovery_enabled=True,
        proof_recovery_samples=2, proof_recovery_interval_seconds=1,
        proof_recovery_grants=3, poll_interval_seconds=.005, auto_renew_leases=False)
    values.update(overrides)
    return mod.ResourceSchedulerConfig(**values)


@pytest.fixture
def owners(tmp_path, monkeypatch):
    clock, observed = [1000.0], [HEALTHY]
    monkeypatch.setattr(mod.time, "time", lambda: clock[0])
    def sample():
        if isinstance(observed[0], Exception):
            raise observed[0]
        return observed[0]
    cfg = config(tmp_path / "scheduler.json", sample)
    first, second = mod.GlobalResourceScheduler(cfg), mod.GlobalResourceScheduler(cfg)
    yield first, second, clock, observed
    assert first.snapshot()["active_lease_count"] == 0
    assert first.snapshot()["waiting_request_count"] == 0


def pressure_then_healthy(owners):
    first, _, clock, observed = owners
    observed[0] = replace(HEALTHY, memory_stall_percent=90)
    assert first.try_acquire("hammer", memory_mb=64) is None
    observed[0] = HEALTHY
    clock[0] += 2
    assert first.try_acquire("hammer", memory_mb=64) is None


def finish_settling(owners):
    first, _, clock, _ = owners
    pressure_then_healthy(owners)
    clock[0] += 1
    with first.acquire("validation", memory_mb=64, timeout=0):
        pass
    assert first.snapshot()["proof_recovery"]["phase"] == "paced"


@pytest.mark.parametrize("values", [
    {"proof_recovery_enabled": 1}, {"proof_safety_enabled": False},
    {"proof_recovery_samples": 0}, {"proof_recovery_samples": True},
    {"proof_recovery_samples": 1025}, {"proof_recovery_grants": -1},
    {"proof_recovery_grants": 1.5}, {"proof_recovery_interval_seconds": 0},
    {"proof_recovery_interval_seconds": True}, {"proof_recovery_interval_seconds": float("nan")},
    {"proof_recovery_interval_seconds": float("inf")}, {"proof_recovery_interval_seconds": 3601},
])
def test_configuration_is_explicit_and_bounded(tmp_path, values):
    with pytest.raises(mod.ResourceConfigurationError):
        mod.GlobalResourceScheduler(config(tmp_path / "s.json", lambda: HEALTHY, **values))


def test_disabled_legacy_active_state_preserves_admission(tmp_path):
    cfg = config(tmp_path / "s.json", lambda: HEALTHY, proof_recovery_enabled=False,
                 proof_recovery_interval_seconds=.25, proof_recovery_grants=4)
    first = mod.GlobalResourceScheduler(cfg)
    with first.acquire("hammer", memory_mb=64, timeout=0):
        state = json.loads(first.state_path.read_text())
        for key in tuple(state["config"]):
            if key.startswith("proof_recovery_"):
                state["config"].pop(key)
        first.state_path.write_text(json.dumps(state))
        second = mod.GlobalResourceScheduler(cfg)
        with second.acquire("hammer", memory_mb=64, timeout=0):
            assert second.snapshot()["active_root_lease_count"] == 2
        assert second.snapshot()["proof_recovery"] == {}


def test_active_shared_configuration_cannot_disable_recovery(owners):
    first, _, _, _ = owners
    with first.acquire("hammer", memory_mb=64, timeout=0):
        with pytest.raises(mod.ResourceConfigurationError, match="active shared state"):
            mod.GlobalResourceScheduler(replace(first.config, proof_recovery_enabled=False))


def test_idle_recovery_cannot_be_erased_by_a_different_client_configuration(owners):
    first, _, _, _ = owners
    pressure_then_healthy(owners)
    assert first.snapshot()["active_lease_count"] == first.snapshot()["waiting_request_count"] == 0
    with pytest.raises(mod.ResourceConfigurationError, match="active shared state"):
        mod.GlobalResourceScheduler(replace(first.config, proof_recovery_enabled=False))
    assert first.snapshot()["proof_recovery"]["healthy_samples"] == 1


def test_idle_recovery_requires_explicit_force_to_reset(owners):
    first, _, _, _ = owners
    pressure_then_healthy(owners)
    with pytest.raises(mod.ResourceSchedulerError, match="pressure recovery"):
        first.reset()
    assert first.snapshot()["proof_recovery"]["healthy_samples"] == 1


@pytest.mark.parametrize("value,enabled", [(None, False), ("0", False), ("1", True)])
def test_default_owner_environment_selects_the_shared_policy(tmp_path, monkeypatch, value, enabled):
    monkeypatch.setattr(mod, "collect_proof_host_resources", lambda: HEALTHY)
    monkeypatch.delenv("IPFS_DATASETS_PROOF_RESOURCE_SAFETY", raising=False)
    monkeypatch.setenv(mod.DEFAULT_STATE_ENV, str(tmp_path / "environment.json"))
    if value is None:
        monkeypatch.delenv(mod.DEFAULT_PROOF_RECOVERY_ENV, raising=False)
    else:
        monkeypatch.setenv(mod.DEFAULT_PROOF_RECOVERY_ENV, value)
    owner = mod.get_global_resource_scheduler()
    assert owner.config.proof_recovery_enabled is enabled
    assert owner.config.proof_safety_enabled
    assert owner.config.persisted_dict()["proof_recovery_enabled"] is enabled
    assert owner is mod.get_global_resource_scheduler()
    with owner.acquire("hammer", memory_mb=64, timeout=0):
        monkeypatch.setenv(mod.DEFAULT_PROOF_RECOVERY_ENV, "0" if enabled else "1")
        with pytest.raises(mod.ResourceConfigurationError, match="differently configured"):
            mod.get_global_resource_scheduler()


@pytest.mark.parametrize("value", ["", "true", "false", "yes", "2", " 1", "1 "])
def test_malformed_environment_fails_before_sampling(monkeypatch, value):
    monkeypatch.setenv(mod.DEFAULT_PROOF_RECOVERY_ENV, value)
    monkeypatch.setattr(mod, "collect_proof_host_resources", lambda: pytest.fail("must not sample"))
    with pytest.raises(mod.ResourceConfigurationError, match="exactly 0 or 1"):
        mod.default_resource_scheduler_config()


def test_environment_cannot_enable_recovery_without_safety(monkeypatch):
    monkeypatch.setenv(mod.DEFAULT_PROOF_RECOVERY_ENV, "1")
    monkeypatch.setenv("IPFS_DATASETS_PROOF_RESOURCE_SAFETY", "0")
    with pytest.raises(mod.ResourceConfigurationError, match="requires proof safety"):
        mod.default_resource_scheduler_config()


def test_backwards_clock_does_not_create_a_fresh_healthy_sample(owners):
    first, _, clock, _ = owners
    pressure_then_healthy(owners)
    clock[0] -= 10
    assert first.try_acquire("hammer", memory_mb=64) is None
    assert first.snapshot()["proof_recovery"]["healthy_samples"] == 1


def test_healthy_samples_are_spaced_shared_and_survive_reopening(owners):
    first, second, clock, _ = owners
    pressure_then_healthy(owners)
    for _ in range(8):
        assert second.try_acquire("hammer", memory_mb=64) is None
    reopened = mod.GlobalResourceScheduler(first.config)
    assert reopened.snapshot()["proof_recovery"]["healthy_samples"] == 1
    clock[0] += .9
    assert reopened.try_acquire("hammer", memory_mb=64) is None
    clock[0] += .1
    with reopened.acquire("hammer", memory_mb=64, timeout=0):
        assert first.snapshot()["proof_recovery"]["grants_remaining"] == 2
    assert second.try_acquire("hammer", memory_mb=64) is None


def test_paced_grants_include_last_interval_before_full_recovery(owners):
    first, second, clock, _ = owners
    finish_settling(owners)
    for remaining in (2, 1, 0):
        with first.acquire("hammer", memory_mb=64, timeout=0):
            pass
        assert second.snapshot()["proof_recovery"]["grants_remaining"] == remaining
        assert second.try_acquire("hammer", memory_mb=64) is None
        clock[0] += 1
    with second.acquire("hammer", memory_mb=64, timeout=0):
        with first.acquire("hammer", memory_mb=64, timeout=0):
            assert first.snapshot()["proof_recovery"] == {}


def test_child_and_root_share_pacing_without_double_accounting(owners):
    first, second, clock, _ = owners
    with first.acquire("orchestration", cpu_slots=3, memory_mb=1024, timeout=0) as parent:
        finish_settling(owners)
        with parent.acquire_child(cpu_slots=1, memory_mb=64, timeout=0):
            snap = second.snapshot()
            assert snap["active_root_lease_count"] == 1
            assert snap["active_child_lease_count"] == 1
            assert snap["allocated"]["cpu_slots"] == 3
            assert second.try_acquire("hammer", memory_mb=64) is None
        clock[0] += 1
        with second.acquire("hammer", memory_mb=64, timeout=0):
            assert first.try_acquire("hammer", memory_mb=64, parent=parent) is None


def test_validation_bypasses_only_extra_pacing(owners):
    first, second, clock, observed = owners
    pressure_then_healthy(owners)
    with second.acquire("validation", memory_mb=64, timeout=0):
        assert second.snapshot()["proof_recovery"]["healthy_samples"] == 1
    clock[0] += 1
    with first.acquire("hammer", memory_mb=64, timeout=0):
        before = first.snapshot()["proof_recovery"]
        with second.acquire("validation", memory_mb=64, timeout=0):
            assert first.snapshot()["proof_recovery"] == before
        observed[0] = replace(HEALTHY, cpu_stall_percent=90)
        assert second.try_acquire("validation", memory_mb=64) is None
        assert first.snapshot()["proof_backoff"]["reason"] == "proof_cpu_stall"


@pytest.mark.parametrize("failure,reason", [
    (OSError("unavailable"), "proof_resource_telemetry_unknown"),
    (replace(HEALTHY, memory_stall_percent=90), "proof_memory_stall"),
    (replace(HEALTHY, cpu_stall_percent=90), "proof_cpu_stall"),
    (replace(HEALTHY, io_stall_percent=90), "proof_io_stall"),
    (replace(HEALTHY, available_memory_mb=0), "proof_memory_headroom"),
])
def test_relapse_or_missing_telemetry_resets_shared_streak(owners, failure, reason):
    first, second, clock, observed = owners
    pressure_then_healthy(owners)
    clock[0] += .1
    observed[0] = failure
    assert second.try_acquire("hammer", memory_mb=64) is None
    assert first.snapshot()["proof_backoff"]["reason"] == reason
    assert first.snapshot()["proof_recovery"]["healthy_samples"] == 0
    observed[0] = HEALTHY
    clock[0] += 1.9
    assert second.try_acquire("hammer", memory_mb=64) is None
    clock[0] += .1
    assert second.try_acquire("hammer", memory_mb=64) is None
    assert first.snapshot()["proof_recovery"]["healthy_samples"] == 1


def test_cancel_and_timeout_do_not_spend_recovery_credit(owners):
    first, _, _, _ = owners
    finish_settling(owners)
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(mod.LeaseCancelledError):
        first.acquire("hammer", memory_mb=64, timeout=1, cancel_event=cancel)
    assert first.snapshot()["proof_recovery"]["grants_remaining"] == 3
    with first.acquire("hammer", memory_mb=64, timeout=0):
        before = first.snapshot()["proof_recovery"]
        started = time.monotonic()
        with pytest.raises(mod.LeaseTimeoutError):
            first.acquire("hammer", memory_mb=64, timeout=.03)
        assert time.monotonic() - started < 1
        assert first.snapshot()["proof_recovery"] == before


def test_fairness_queries_do_not_spend_grants_or_accelerate_samples(owners):
    first, _, clock, _ = owners
    pressure_then_healthy(owners)
    waiter = dict(lane="hammer", cpu_slots=1, memory_mb=64, parent_lease_id=None)
    with first._locked_state() as state:
        for _ in range(20):
            assert not first._can_grant(state, waiter)
        assert state["proof_recovery"]["healthy_samples"] == 1
    clock[0] += 1
    with first._locked_state() as state:
        for _ in range(20):
            assert first._can_grant(state, waiter)
        assert state["proof_recovery"]["grants_remaining"] == 3
    with first.acquire("hammer", memory_mb=64, timeout=0):
        assert first.snapshot()["proof_recovery"]["grants_remaining"] == 2


def test_pressure_observed_during_fairness_cannot_be_bypassed(owners, monkeypatch):
    first, _, _, observed = owners
    finish_settling(owners)
    def fairness(state, waiter):
        observed[0] = replace(HEALTHY, memory_stall_percent=90)
        assert not first._can_grant(state, dict(waiter, waiter_id="older"))
        return True
    monkeypatch.setattr(first, "_is_fair_turn", fairness)
    assert first.try_acquire("hammer", memory_mb=64) is None
    assert first.snapshot()["proof_recovery"]["healthy_samples"] == 0


def test_validation_cannot_bypass_fairness_refusal_with_zero_backoff(tmp_path, monkeypatch):
    observed = [HEALTHY]
    scheduler = mod.GlobalResourceScheduler(config(tmp_path / "s.json", lambda: observed[0],
                                                   proof_backoff_seconds=0))
    def fairness(state, waiter):
        observed[0] = replace(HEALTHY, memory_stall_percent=90)
        assert not scheduler._can_grant(state, dict(waiter, waiter_id="older"))
        return True
    monkeypatch.setattr(scheduler, "_is_fair_turn", fairness)
    assert scheduler.try_acquire("validation", memory_mb=64) is None
    assert scheduler.snapshot()["proof_backoff"]["reason"] == "proof_memory_stall"
    assert scheduler.snapshot()["active_lease_count"] == 0


@pytest.mark.parametrize("change", [
    {"healthy_samples": -1}, {"healthy_samples": True},
    {"next_sample_at": float("nan")}, {"next_grant_at": -1},
    {"phase": []}, {"phase": "unexpected"}, {"grants_remaining": 1025},
    {"grants_remaining": 0}, {"healthy_samples": 2}, {"extra": "field"},
])
def test_invalid_persisted_recovery_state_refuses(owners, change):
    first, _, _, _ = owners
    pressure_then_healthy(owners)
    original = first.state_path.read_text()
    state = json.loads(original)
    state["proof_recovery"].update(change)
    first.state_path.write_text(json.dumps(state))
    try:
        with pytest.raises(mod.SchedulerStateError):
            mod.GlobalResourceScheduler(first.config)
    finally:
        first.state_path.write_text(original)
