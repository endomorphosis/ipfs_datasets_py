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
    parent.release()  # Cascades even if a child owner did not release explicitly.
    assert scheduler.snapshot()["active_lease_count"] == 0


def test_expired_lease_is_recovered_after_interrupted_owner(tmp_path):
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
    assert abandoned.lease_id in recovered
    assert scheduler.snapshot()["active_lease_count"] == 0
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
