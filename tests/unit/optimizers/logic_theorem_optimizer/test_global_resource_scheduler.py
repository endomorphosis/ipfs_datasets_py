"""Tests for the host-global nested CPU/memory lease scheduler."""

from __future__ import annotations

import multiprocessing
import os
import threading
import time
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.hammers.models import (
    HammerPolicy,
    TranslationRecord,
    TranslationStatus,
    TranslationTarget,
)
from ipfs_datasets_py.logic.hammers.policy import PortfolioPolicy, SolverBudget
from ipfs_datasets_py.logic.hammers.portfolio import (
    PortfolioAttemptSpec,
    SolverPortfolio,
    SolverProcessOutcome,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.resource_scheduler import (
    GlobalResourceScheduler,
    LaneReservation,
    LeaseCancelledError,
    LeaseTimeoutError,
    ResourceConfigurationError,
    ResourceSchedulerConfig,
    ResourceUnavailableError,
)


def _config(
    state_path: Path,
    *,
    cpu: int = 4,
    memory: int = 400,
    reservations=None,
    ttl: float = 5.0,
    auto_renew: bool = False,
) -> ResourceSchedulerConfig:
    return ResourceSchedulerConfig(
        total_cpu_slots=cpu,
        total_memory_mb=memory,
        lane_reservations=reservations or {},
        state_path=state_path,
        lease_ttl_seconds=ttl,
        poll_interval_seconds=0.005,
        auto_renew_leases=auto_renew,
    )


def _holding_worker(state_path: str, ready, release) -> None:
    scheduler = GlobalResourceScheduler(
        _config(Path(state_path), cpu=1, memory=100, reservations={"hammer_lean": 1})
    )
    with scheduler.acquire("hammer_lean", cpu_slots=1, memory_mb=100, timeout=1):
        ready.set()
        release.wait(5)


def _crashing_worker(state_path: str, connection) -> None:
    scheduler = GlobalResourceScheduler(
        _config(Path(state_path), cpu=1, memory=100, reservations={"hammer_lean": 1}, ttl=60)
    )
    lease = scheduler.acquire("hammer_lean", cpu_slots=1, memory_mb=100, timeout=1)
    connection.send(lease.lease_id)
    connection.close()
    os._exit(0)


def test_configuration_rejects_overcommitted_lane_reservations(tmp_path):
    config = _config(
        tmp_path / "scheduler.json",
        cpu=2,
        reservations={"hammer_lean": 2, "validation": 1},
    )
    with pytest.raises(ResourceConfigurationError, match="reservations exceed"):
        GlobalResourceScheduler(config)


def test_lane_reservations_preserve_capacity_for_each_runtime_lane(tmp_path):
    scheduler = GlobalResourceScheduler(
        _config(
            tmp_path / "scheduler.json",
            reservations={"hammer_lean": 2, "validation": 2},
        )
    )
    hammer = scheduler.acquire("hammer_lean", cpu_slots=2, timeout=0)
    try:
        # Hammer cannot consume the two validation slots, even while idle.
        assert scheduler.try_acquire("hammer_lean", cpu_slots=1) is None
        validation = scheduler.acquire("validation", cpu_slots=2, timeout=0)
        try:
            snapshot = scheduler.snapshot()
            assert snapshot["allocated"]["cpu_slots"] == 4
            assert snapshot["lanes"]["hammer_lean"]["reservation"]["cpu_slots"] == 2
            assert snapshot["lanes"]["validation"]["allocated"]["cpu_slots"] == 2
        finally:
            validation.release()
    finally:
        hammer.release()


def test_cpu_and_memory_are_both_authoritative(tmp_path):
    scheduler = GlobalResourceScheduler(
        _config(
            tmp_path / "scheduler.json",
            cpu=3,
            memory=100,
            reservations={"codex": LaneReservation(cpu_slots=3, memory_mb=100)},
        )
    )
    lease = scheduler.acquire("codex", cpu_slots=1, memory_mb=80, timeout=0)
    try:
        assert scheduler.try_acquire("codex", cpu_slots=1, memory_mb=21) is None
        second = scheduler.acquire("codex", cpu_slots=2, memory_mb=20, timeout=0)
        second.release()
    finally:
        lease.release()
    with pytest.raises(ResourceUnavailableError):
        scheduler.acquire("codex", cpu_slots=4, timeout=0)


def test_nested_leases_use_parent_envelope_without_global_double_counting(tmp_path):
    scheduler = GlobalResourceScheduler(
        _config(tmp_path / "scheduler.json", reservations={"hammer_lean": 4})
    )
    parent = scheduler.acquire("hammer_lean", cpu_slots=2, memory_mb=100, timeout=0)
    first = parent.acquire_child(cpu_slots=1, memory_mb=60, timeout=0)
    second = parent.acquire_child(cpu_slots=1, memory_mb=40, timeout=0)
    try:
        snapshot = scheduler.snapshot()
        assert snapshot["allocated"] == {"cpu_slots": 2, "memory_mb": 100}
        assert snapshot["active_root_lease_count"] == 1
        assert snapshot["active_child_lease_count"] == 2
        # The parent has two CPU slots and both are charged to solver children.
        with pytest.raises(LeaseTimeoutError):
            parent.acquire_child(cpu_slots=1, timeout=0)
    finally:
        first.release()
        second.release()
        parent.release()


def test_child_request_larger_than_parent_fails_immediately(tmp_path):
    scheduler = GlobalResourceScheduler(
        _config(tmp_path / "scheduler.json", reservations={"hammer_lean": 4})
    )
    with scheduler.acquire("hammer_lean", cpu_slots=2, memory_mb=50, timeout=0) as parent:
        with pytest.raises(ResourceUnavailableError, match="parent lease"):
            parent.acquire_child(cpu_slots=3, memory_mb=1, timeout=0)
        with pytest.raises(ResourceUnavailableError, match="parent lease"):
            parent.acquire_child(cpu_slots=1, memory_mb=51, timeout=0)


def test_waiting_acquisition_is_cancellable_and_waiter_is_removed(tmp_path):
    scheduler = GlobalResourceScheduler(
        _config(tmp_path / "scheduler.json", cpu=1, reservations={"validation": 1})
    )
    held = scheduler.acquire("validation", timeout=0)
    cancellation = threading.Event()
    result = []

    def wait_for_lease() -> None:
        try:
            scheduler.acquire("validation", timeout=2, cancel_event=cancellation)
        except Exception as exc:  # captured for assertion in the owning thread
            result.append(exc)

    thread = threading.Thread(target=wait_for_lease)
    thread.start()
    deadline = time.monotonic() + 1
    while scheduler.snapshot()["waiting_request_count"] != 1 and time.monotonic() < deadline:
        time.sleep(0.005)
    cancellation.set()
    thread.join(1)
    held.release()

    assert not thread.is_alive()
    assert len(result) == 1 and isinstance(result[0], LeaseCancelledError)
    snapshot = scheduler.snapshot()
    assert snapshot["waiting_request_count"] == 0
    assert snapshot["counters"]["cancellations_total"] >= 1


def test_cancelling_parent_propagates_to_children_and_future_nested_work(tmp_path):
    scheduler = GlobalResourceScheduler(
        _config(tmp_path / "scheduler.json", reservations={"hammer_lean": 4})
    )
    parent = scheduler.acquire("hammer_lean", cpu_slots=2, timeout=0)
    child = parent.acquire_child(cpu_slots=1, timeout=0)
    assert parent.cancel() is True
    assert child.cancellation_signal.is_set()
    with pytest.raises(LeaseCancelledError):
        parent.acquire_child(cpu_slots=1, timeout=0)
    parent.release()  # Revokes children but keeps their live capacity charged.
    assert scheduler.snapshot()["active_lease_count"] == 2
    child.release()
    assert scheduler.snapshot()["active_lease_count"] == 0


def test_expired_live_lease_is_revoked_until_owner_acknowledges_completion(tmp_path):
    scheduler = GlobalResourceScheduler(
        _config(
            tmp_path / "scheduler.json",
            cpu=1,
            reservations={"orchestration": 1},
            ttl=0.03,
        )
    )
    abandoned = scheduler.acquire("orchestration", timeout=0)
    time.sleep(0.05)
    recovered = scheduler.recover_stale_leases()
    assert abandoned.lease_id not in recovered
    assert abandoned.cancelled
    assert scheduler.snapshot()["active_lease_count"] == 1
    assert scheduler.try_acquire("orchestration") is None
    abandoned.release()
    replacement = scheduler.acquire("orchestration", timeout=0)
    replacement.release()


@pytest.mark.skipif(os.name != "posix", reason="process-safe scheduler uses POSIX file locks")
def test_unrelated_processes_share_one_capacity_limit(tmp_path):
    context = multiprocessing.get_context("fork")
    ready = context.Event()
    release = context.Event()
    state_path = tmp_path / "scheduler.json"
    process = context.Process(target=_holding_worker, args=(str(state_path), ready, release))
    process.start()
    try:
        assert ready.wait(2)
        scheduler = GlobalResourceScheduler(
            _config(state_path, cpu=1, memory=100, reservations={"hammer_lean": 1})
        )
        assert scheduler.try_acquire("hammer_lean") is None
        assert scheduler.snapshot()["active_root_lease_count"] == 1
    finally:
        release.set()
        process.join(2)
        if process.is_alive():
            process.terminate()
            process.join(2)
    assert process.exitcode == 0


@pytest.mark.skipif(os.name != "posix", reason="process recovery requires a process owner")
def test_dead_process_lease_is_recovered_without_waiting_for_ttl(tmp_path):
    context = multiprocessing.get_context("fork")
    parent_connection, child_connection = context.Pipe(duplex=False)
    state_path = tmp_path / "scheduler.json"
    process = context.Process(target=_crashing_worker, args=(str(state_path), child_connection))
    process.start()
    lease_id = parent_connection.recv()
    process.join(2)
    assert process.exitcode == 0

    scheduler = GlobalResourceScheduler(
        _config(
            state_path,
            cpu=1,
            memory=100,
            reservations={"hammer_lean": 1},
            ttl=60,
        )
    )
    # Construction/snapshot performs recovery transactionally.
    snapshot = scheduler.snapshot()
    assert snapshot["active_lease_count"] == 0
    assert snapshot["counters"]["recovered_leases_total"] >= 1
    assert all(record["lease_id"] != lease_id for record in scheduler.active_leases())


def test_saturation_and_wait_time_telemetry_are_exposed(tmp_path):
    scheduler = GlobalResourceScheduler(
        _config(tmp_path / "scheduler.json", cpu=1, reservations={"codex": 1})
    )
    with scheduler.acquire("codex", timeout=0):
        assert scheduler.try_acquire("codex") is None
        saturated = scheduler.snapshot()
        assert saturated["saturation"]["cpu_saturated"] is True
        assert saturated["saturation"]["events_total"] >= 1
    telemetry = scheduler.telemetry()
    assert telemetry["wait_time_seconds"]["count"] >= 2
    assert telemetry["wait_time_seconds"]["max"] >= 0
    assert telemetry["lanes"]["codex"]["telemetry"]["timeouts_total"] == 1


def test_solver_portfolio_charges_each_solver_to_one_parent_lease(tmp_path):
    scheduler = GlobalResourceScheduler(
        _config(tmp_path / "scheduler.json", cpu=2, reservations={"hammer_lean": 2})
    )
    executable = tmp_path / "z3"
    executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    executable.chmod(0o755)
    policy = PortfolioPolicy(
        hammer_policy=HammerPolicy(
            timeout_seconds=5,
            memory_mb=50,
            allowed_solvers=["z3"],
        ),
        solver_budgets={"z3": SolverBudget(timeout_seconds=5, memory_mb=50)},
        executable_overrides={"z3": str(executable)},
        max_parallel_processes=2,
        cancel_on_first_conclusive=False,
    )
    observed = []

    def runner(command, *, budget, cancel_event=None):
        snapshot = scheduler.snapshot()
        observed.append(
            (
                snapshot["allocated"]["cpu_slots"],
                snapshot["allocated"]["memory_mb"],
                snapshot["active_child_lease_count"],
            )
        )
        time.sleep(0.02)
        return SolverProcessOutcome(command=command, stdout="unknown\n")

    portfolio = SolverPortfolio(
        policy,
        process_runner=runner,
        version_prober=lambda *_: None,
        resource_scheduler=scheduler,
        resource_wait_timeout_seconds=1,
    )
    attempts = [
        PortfolioAttemptSpec(
            translation=TranslationRecord(
                translation_id=f"translation-{index}",
                request_id="request-1",
                target=TranslationTarget.SMTLIB,
                status=TranslationStatus.SUPPORTED,
                source_construct="goal",
                translated_text="(assert true)",
            ),
            solver_name="z3",
        )
        for index in range(2)
    ]
    result = portfolio.run("request-1", attempts)

    assert len(result.attempts) == 2
    assert observed
    # The two child solver leases stay inside the 2 CPU / 100 MiB portfolio
    # envelope.  They are not counted as another 2 CPU / 100 MiB globally.
    assert all(cpu == 2 and memory == 100 for cpu, memory, _ in observed)
    assert max(children for _, _, children in observed) == 2
    assert result.resource_telemetry["portfolio_cpu_slots"] == 2
    assert scheduler.snapshot()["active_lease_count"] == 0


# Same-namespace capacity growth preserves the original persisted policy so
# already-running facades can continue heartbeat, cancellation and release.
def _child_capacity_expansion_case(tmp_path):
    import json

    config = ResourceSchedulerConfig(
        state_path=tmp_path / "child-capacity.json",
        total_cpu_slots=4,
        total_memory_mb=400,
        total_child_process_slots=16, lane_reservations={},
        lease_ttl_seconds=60,
        poll_interval_seconds=0.005,
        auto_renew_leases=False,
    )
    scheduler = GlobalResourceScheduler(config)
    held = scheduler.acquire(
        "validation", cpu_slots=1, memory_mb=100,
        child_process_slots=16, timeout=0,
        request_id="test:child-capacity:retained",
    )
    return scheduler, held, lambda: json.loads(config.state_path.read_text())


def _stable_capacity_lease_record(record):
    return {key: value for key, value in record.items()
            if key not in {"heartbeat_at", "expires_at"}}


def test_child_capacity_expansion_preserves_live_facade_and_allows_sibling(tmp_path):
    scheduler, held, read = _child_capacity_expansion_case(tmp_path)
    sibling = None
    try:
        before = read()
        assert scheduler.try_acquire("validation", cpu_slots=1,
            memory_mb=100, child_process_slots=1) is None
        scheduler.expand_child_process_capacity(expected_current=16, new_total=32)
        after = read()
        assert after["config"] == before["config"]
        assert after["config"]["total_child_process_slots"] == 16
        assert after["leases"] == before["leases"]
        assert after["waiters"] == before["waiters"] == {}
        assert scheduler.config.total_child_process_slots == 16
        assert held.renew() is True
        assert held.cancelled is False
        assert _stable_capacity_lease_record(read()["leases"][held.lease_id]) == _stable_capacity_lease_record(before["leases"][held.lease_id])
        # A separate facade must use the same persisted base policy and state.
        peer = GlobalResourceScheduler(scheduler.config)
        sibling = peer.acquire("validation", cpu_slots=1, memory_mb=100,
            child_process_slots=1, timeout=0)
        snapshot = peer.snapshot()
        assert snapshot["capacity"]["child_process_slots"] == 32
        assert snapshot["allocated_child_process_slots"] == 17
        assert snapshot["available"]["child_process_slots"] == 15
        assert snapshot["capacity"]["cpu_slots"] == 4
        assert snapshot["capacity"]["memory_mb"] == 400
        assert snapshot["allocated"] == {"cpu_slots": 2, "memory_mb": 200}
        assert _stable_capacity_lease_record(read()["leases"][held.lease_id]) == _stable_capacity_lease_record(before["leases"][held.lease_id])
    finally:
        if sibling is not None:
            sibling.release()
        held.release()
    assert read()["leases"] == {}
    assert GlobalResourceScheduler(scheduler.config).snapshot()["capacity"]["child_process_slots"] == 32


@pytest.mark.parametrize("expected,new_total", [
    (True, 32), (16, True), (0, 32), (-1, 32),
    ("16", 32), (16, "32"), (16, 16), (16, 8),
])
def test_child_capacity_expansion_rejects_invalid_or_nonincreasing_change(tmp_path, expected, new_total):
    scheduler, held, read = _child_capacity_expansion_case(tmp_path)
    try:
        before = read()
        with pytest.raises(ResourceConfigurationError):
            scheduler.expand_child_process_capacity(expected_current=expected, new_total=new_total)
        assert read() == before
        assert held.cancelled is False
    finally:
        held.release()


def test_child_capacity_expansion_stale_compare_and_swap_keeps_actual_policy(tmp_path):
    scheduler, held, read = _child_capacity_expansion_case(tmp_path)
    try:
        scheduler.expand_child_process_capacity(expected_current=16, new_total=32)
        before = read()
        peer = GlobalResourceScheduler(scheduler.config)
        with pytest.raises(ResourceConfigurationError):
            peer.expand_child_process_capacity(expected_current=16, new_total=64)
        assert read() == before
        assert peer.snapshot()["capacity"]["child_process_slots"] == 32
        assert held.renew() is True
    finally:
        held.release()


def test_child_capacity_expansion_does_not_change_cpu_memory_or_other_policy(tmp_path):
    from dataclasses import replace

    scheduler, held, read = _child_capacity_expansion_case(tmp_path)
    try:
        scheduler.expand_child_process_capacity(expected_current=16, new_total=32)
        before = read()
        for changed in (replace(scheduler.config, total_cpu_slots=8),
                        replace(scheduler.config, total_memory_mb=800)):
            with pytest.raises(ResourceConfigurationError):
                GlobalResourceScheduler(changed)
            assert read() == before
        for cpu, memory in ((5, 0), (1, 401)):
            with pytest.raises(ResourceUnavailableError):
                scheduler.acquire("validation", cpu_slots=cpu,
                    memory_mb=memory, child_process_slots=1, timeout=0)
            assert read() == before
    finally:
        held.release()


def test_child_capacity_expansion_uses_effective_limit_for_oversize_and_saturation(tmp_path):
    scheduler, held, read = _child_capacity_expansion_case(tmp_path)
    rest = None
    try:
        scheduler.expand_child_process_capacity(expected_current=16, new_total=32)
        with pytest.raises(ResourceUnavailableError):
            scheduler.acquire("validation", child_process_slots=33, timeout=0)
        assert read()["waiters"] == {}
        rest = scheduler.acquire("validation", cpu_slots=1, memory_mb=1,
            child_process_slots=16, timeout=0)
        snapshot = scheduler.snapshot()
        assert snapshot["allocated_child_process_slots"] == 32
        assert snapshot["available"]["child_process_slots"] == 0
        assert snapshot["saturation"]["child_process_slots_saturated"] is True
        assert scheduler.try_acquire("validation", child_process_slots=1) is None
        assert read()["waiters"] == {}
    finally:
        if rest is not None:
            rest.release()
        held.release()


def test_child_capacity_expansion_compare_and_swap_is_atomic_between_facades(tmp_path):
    scheduler, held, read = _child_capacity_expansion_case(tmp_path)
    barrier = threading.Barrier(2)
    outcomes = []

    def expand():
        peer = GlobalResourceScheduler(scheduler.config)
        barrier.wait(timeout=5)
        try:
            peer.expand_child_process_capacity(expected_current=16, new_total=32)
        except ResourceConfigurationError:
            outcomes.append("stale")
        else:
            outcomes.append("expanded")

    threads = [threading.Thread(target=expand) for _ in range(2)]
    try:
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=5)
        assert not any(thread.is_alive() for thread in threads)
        assert sorted(outcomes) == ["expanded", "stale"]
        assert scheduler.snapshot()["capacity"]["child_process_slots"] == 32
        assert len(read()["leases"]) == 1
        assert held.renew() is True
    finally:
        for thread in threads:
            thread.join(timeout=5)
        held.release()


@pytest.mark.parametrize("damage", [
    "boolean-total", "decrease", "base-total", "base-policy", "extra", "missing", "digest",
])
def test_child_capacity_expansion_rejects_tampered_capacity_metadata(tmp_path, damage):
    from copy import deepcopy
    import hashlib
    import json

    scheduler, held, read = _child_capacity_expansion_case(tmp_path)
    scheduler.expand_child_process_capacity(expected_current=16, new_total=32)
    valid = read()
    damaged = deepcopy(valid)
    metadata = damaged["child_process_capacity"]
    if damage == "boolean-total":
        metadata["total_child_process_slots"] = True
    elif damage == "decrease":
        metadata["total_child_process_slots"] = 8
    elif damage == "base-total":
        metadata["base_total_child_process_slots"] = 8
    elif damage == "base-policy":
        metadata["base_config_sha256"] = "0" * 64
    elif damage == "extra":
        metadata["other_policy_authority"] = True
    elif damage == "missing":
        del metadata["base_config_sha256"]
    else:
        metadata["capacity_sha256"] = "0" * 64
    if damage != "digest":
        commitment = {key: value for key, value in metadata.items() if key != "capacity_sha256"}
        metadata["capacity_sha256"] = hashlib.sha256(json.dumps(
            commitment, sort_keys=True, separators=(",", ":"), allow_nan=False,
        ).encode()).hexdigest()
    try:
        scheduler.config.state_path.write_text(json.dumps(damaged))
        with pytest.raises(ResourceConfigurationError):
            GlobalResourceScheduler(scheduler.config)
        assert read() == damaged
    finally:
        # Restore the authored valid fixture before releasing its real test lease.
        scheduler.config.state_path.write_text(json.dumps(valid))
        held.release()


def test_child_capacity_expansion_preserves_exact_readonly_lease_inspection(tmp_path):
    scheduler, held, read = _child_capacity_expansion_case(tmp_path)
    try:
        scheduler.expand_child_process_capacity(expected_current=16, new_total=32)
        before = read()
        observed = scheduler.inspect_lease(
            held.lease_id, expected_request_id="test:child-capacity:retained",
            expected_lane="validation", expected_owner_pid=os.getpid(),
        )
        assert observed["read_only"] is True
        assert observed["binding_verified"] is True
        assert observed["status"] == "present"
        assert observed["descendant_count"] == 0
        assert read() == before
        assert held.renew() is True
    finally:
        held.release()



def _proof_child_capacity_expansion_case(tmp_path, monkeypatch):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import resource_scheduler as native
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import existing_resource_scheduler as existing
    import json

    host = native.ProofHostResources(
        cpu_slots=4, total_memory_mb=400, available_memory_mb=300,
        pid_task_limit=10000, available_pid_tasks=10000,
    )
    # Every observation stays inside this authored fixture; no host sampling.
    config = ResourceSchedulerConfig(
        state_path=tmp_path / "proof-child-capacity.json",
        total_cpu_slots=4, total_memory_mb=400, total_child_process_slots=16, lane_reservations={},
        lease_ttl_seconds=60, poll_interval_seconds=0.005, auto_renew_leases=False,
        proof_safety_enabled=True, proof_resource_profile="local-benchmark@1",
        proof_recovery_enabled=True, proof_recovery_grants=1,
        proof_memory_stall_percent=10.0,
        proof_memory_headroom_mb=100, proof_resource_sampler=lambda: host,
    )
    scheduler = GlobalResourceScheduler(config)
    held = scheduler.acquire("validation", cpu_slots=1, memory_mb=100,
        child_process_slots=16, timeout=0)
    monkeypatch.setattr(existing, "_native_capacity_host", lambda config: (host, "1" * 64))
    return scheduler, held, host, existing, lambda: json.loads(config.state_path.read_text())


def test_child_capacity_expansion_retains_healthy_native_host_gate(tmp_path, monkeypatch):
    scheduler, held, host, existing, read = _proof_child_capacity_expansion_case(tmp_path, monkeypatch)
    try:
        before = read()
        change = scheduler.expand_child_process_capacity(expected_current=16, new_total=32)
        proof = change["proof_safety_check"]
        assert proof["pid_tasks_required"] == 544
        assert proof["available_pid_tasks"] == host.available_pid_tasks
        assert proof["memory_mb_required"] == 200
        assert proof["proof_source_sha256"] == "1" * 64
        after = read()
        assert after["config"] == before["config"]
        assert after["leases"] == before["leases"]
        assert after["metrics"] == before["metrics"]
        assert after["proof_backoff"] == before["proof_backoff"]
        assert after.get("proof_recovery") == before.get("proof_recovery")
    finally:
        held.release()


@pytest.mark.parametrize("damage", [
    "pid-unknown", "pid-headroom", "memory-headroom", "memory-pressure",
    "cpu-pressure", "io-pressure", "wrong-type", "unknown-observation",
])
def test_child_capacity_expansion_native_host_refusal_preserves_state(tmp_path, monkeypatch, damage):
    from dataclasses import replace

    scheduler, held, host, existing, read = _proof_child_capacity_expansion_case(tmp_path, monkeypatch)
    if damage == "pid-unknown":
        bad = replace(host, pid_task_limit=None, available_pid_tasks=None)
    elif damage == "pid-headroom":
        bad = replace(host, available_pid_tasks=543)
    elif damage == "memory-headroom":
        bad = replace(host, available_memory_mb=199)
    elif damage == "memory-pressure":
        bad = replace(host, memory_stall_percent=scheduler.config.proof_memory_stall_percent)
    elif damage == "cpu-pressure":
        bad = replace(host, cpu_stall_percent=scheduler.config.proof_cpu_stall_percent)
    elif damage == "io-pressure":
        bad = replace(host, io_stall_percent=scheduler.config.proof_io_stall_percent)
    elif damage == "wrong-type":
        bad = object()
    else:
        def unavailable(config):
            raise existing.ExistingResourceSchedulerError("authored unknown observation")
        monkeypatch.setattr(existing, "_native_capacity_host", unavailable)
        bad = None
    if damage != "unknown-observation":
        monkeypatch.setattr(existing, "_native_capacity_host", lambda config: (bad, "1" * 64))
    try:
        before = read()
        with pytest.raises(ResourceConfigurationError):
            scheduler.expand_child_process_capacity(expected_current=16, new_total=32)
        assert read() == before
        assert held.cancelled is False
    finally:
        held.release()


def test_child_capacity_expansion_pressure_summary_uses_effective_process_limit(tmp_path, monkeypatch):
    scheduler, held, read = _child_capacity_expansion_case(tmp_path)
    try:
        scheduler.expand_child_process_capacity(expected_current=16, new_total=32)
        def unavailable():
            raise RuntimeError("authored no telemetry; use existing scheduler fallback")
        monkeypatch.setattr(scheduler, "_pressure_snapshot", unavailable)
        summary = scheduler.pressure_summary()
        assert summary["child_process_limit"] == 32
        assert summary["child_process_count"] == 16
    finally:
        held.release()



def _idle_capacity_overlay_rebind_case(tmp_path, monkeypatch):
    """Reuse typed unit telemetry and the actual source digest, never sample host."""
    import hashlib
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import resource_scheduler as native

    scheduler, held, host, existing, read = _proof_child_capacity_expansion_case(tmp_path, monkeypatch)
    try:
        proof_source = Path(native.__file__).with_name("proof_resource_safety.py")
        proof_digest = hashlib.sha256(proof_source.read_bytes()).hexdigest()
        monkeypatch.setattr(existing, "_native_capacity_host", lambda config: (host, proof_digest))
    finally:
        assert held.release() is True
    return scheduler, existing, read, proof_digest


def test_idle_capacity_policy_rebind_without_overlay_keeps_baseline(tmp_path, monkeypatch):
    from copy import deepcopy

    scheduler, existing, read, proof_digest = _idle_capacity_overlay_rebind_case(tmp_path, monkeypatch)
    before = read()
    raw_before = scheduler.state_path.read_bytes()
    old_pin = existing.policy_sha256(before["config"])
    plan = existing.expand_idle_process_capacity(scheduler.state_path, old_pin, 64)
    assert scheduler.state_path.read_bytes() == raw_before
    assert plan["applied"] is False and plan["previous_process_slots"] == 16
    assert plan["previous_effective_process_slots"] == 16
    assert plan["child_capacity_metadata_migration"] == dict(
        state_key="child_process_capacity", previous_metadata=None, retirement_planned=False, retired=False)
    applied = existing.expand_idle_process_capacity(scheduler.state_path, old_pin, 64, apply=True)
    after = read()
    expected_policy = deepcopy(before["config"])
    expected_policy["total_child_process_slots"] = 64
    assert after["config"] == expected_policy
    assert {k: v for k, v in after.items() if k != "config"} == {
        k: v for k, v in before.items() if k != "config"}
    assert applied["proof_source_sha256"] == proof_digest and applied["applied"] is True
    assert applied["child_capacity_metadata_migration"]["retired"] is False
    reopened = existing.open_existing_scheduler(scheduler.state_path, applied["next_policy_sha256"])
    assert reopened.snapshot()["capacity"]["child_process_slots"] == 64


def test_idle_capacity_policy_rebind_retires_overlay_and_reopens_with_history(tmp_path, monkeypatch):
    from copy import deepcopy

    scheduler, existing, read, proof_digest = _idle_capacity_overlay_rebind_case(tmp_path, monkeypatch)
    scheduler.expand_child_process_capacity(expected_current=16, new_total=32)
    with scheduler._locked_state() as state:
        state["administrative_fixture_history"] = [{"event": "retain-before-idle-rebind", "ordinal": 7}]
        state["metrics"]["fixture_history_counter"] = 11
    before = read()
    raw_before = scheduler.state_path.read_bytes()
    old_pin = existing.policy_sha256(before["config"])
    plan = existing.expand_idle_process_capacity(scheduler.state_path, old_pin, 64)
    assert scheduler.state_path.read_bytes() == raw_before
    assert plan["previous_effective_process_slots"] == 32
    assert plan["child_capacity_metadata_migration"]["previous_metadata"] == before["child_process_capacity"]
    assert plan["child_capacity_metadata_migration"]["retirement_planned"] is True
    assert plan["child_capacity_metadata_migration"]["retired"] is False
    applied = existing.expand_idle_process_capacity(scheduler.state_path, old_pin, 64, apply=True)
    after = read()
    assert applied["proof_source_sha256"] == proof_digest
    assert applied["child_capacity_metadata_migration"]["retired"] is True
    assert "child_process_capacity" not in after
    expected_policy = deepcopy(before["config"])
    expected_policy["total_child_process_slots"] = 64
    assert after["config"] == expected_policy
    assert {k: v for k, v in after.items() if k != "config"} == {
        k: v for k, v in before.items() if k not in {"config", "child_process_capacity"}}
    assert after["metrics"] == before["metrics"]
    assert after["administrative_fixture_history"] == before["administrative_fixture_history"]
    with pytest.raises(existing.ExistingResourceSchedulerError, match="exact stored native policy"):
        existing.open_existing_scheduler(scheduler.state_path, old_pin)
    reopened = existing.open_existing_scheduler(scheduler.state_path, applied["next_policy_sha256"])
    assert reopened.config.total_child_process_slots == 64
    assert reopened.snapshot()["capacity"]["child_process_slots"] == 64


def test_idle_capacity_policy_rebind_refuses_values_not_above_effective_overlay(tmp_path, monkeypatch):
    scheduler, existing, read, proof_digest = _idle_capacity_overlay_rebind_case(tmp_path, monkeypatch)
    scheduler.expand_child_process_capacity(expected_current=16, new_total=32)
    before = scheduler.state_path.read_bytes()
    old_pin = existing.policy_sha256(read()["config"])
    def no_host_sample(config):
        pytest.fail("nonincreasing effective capacity reached host sampling")
    monkeypatch.setattr(existing, "_native_capacity_host", no_host_sample)
    for requested in (24, 32):
        with pytest.raises(existing.ExistingResourceSchedulerError, match="strictly exceed effective capacity"):
            existing.expand_idle_process_capacity(scheduler.state_path, old_pin, requested, apply=True)
        assert scheduler.state_path.read_bytes() == before


def test_idle_capacity_policy_rebind_refuses_malformed_overlay_without_write(tmp_path, monkeypatch):
    scheduler, existing, read, proof_digest = _idle_capacity_overlay_rebind_case(tmp_path, monkeypatch)
    scheduler.expand_child_process_capacity(expected_current=16, new_total=32)
    old_pin = existing.policy_sha256(read()["config"])
    with scheduler._locked_state() as state:
        state["child_process_capacity"]["capacity_sha256"] = "0" * 64
    before = scheduler.state_path.read_bytes()
    def no_host_sample(config):
        pytest.fail("malformed overlay reached host sampling")
    monkeypatch.setattr(existing, "_native_capacity_host", no_host_sample)
    with pytest.raises(ResourceConfigurationError, match="capacity consistency seal differs"):
        existing.expand_idle_process_capacity(scheduler.state_path, old_pin, 64, apply=True)
    assert scheduler.state_path.read_bytes() == before
