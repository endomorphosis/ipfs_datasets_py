"""Real local flock/scheduler contention; no global leases or daemon jobs."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import fcntl
import json
import os
import threading

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_daemon_resources as resources
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.resource_scheduler import LeaseTimeoutError
from tests.unit.optimizers.logic_theorem_optimizer.test_autoencoder_daemon_resources import setup


@contextmanager
def held_lock(path):
    """Hold an independent real descriptor, with an idempotent early unlock."""
    descriptor = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    locked = True
    def unlock():
        nonlocal locked
        if locked:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
            locked = False
    try:
        yield unlock
    finally:
        unlock()
        os.close(descriptor)


def observe_real_contention(monkeypatch, path, count):
    """Observe actual kernel refusal, without delaying or replacing flock."""
    info = path.stat()
    identity = info.st_dev, info.st_ino
    real_flock = fcntl.flock
    seen, mutex, blocked = set(), threading.Lock(), threading.Event()
    def flock(descriptor, operation):
        try:
            return real_flock(descriptor, operation)
        except BlockingIOError:
            current = os.fstat(descriptor)
            if (current.st_dev, current.st_ino) == identity:
                with mutex:
                    seen.add(threading.get_ident())
                    if len(seen) >= count:
                        blocked.set()
            raise
    monkeypatch.setattr(fcntl, "flock", flock)
    return blocked


def scheduler_calls(monkeypatch, scheduler):
    original, calls, mutex = scheduler.acquire, [], threading.Lock()
    def acquire(*args, **kwargs):
        with mutex:
            calls.append((args, dict(kwargs)))
        return original(*args, **kwargs)
    monkeypatch.setattr(scheduler, "acquire", acquire)
    return calls


def test_two_simultaneous_reservations_wait_for_same_real_ledger_without_waiting_for_scheduler(setup, monkeypatch):
    factory, roots, ledger, scheduler = setup
    original_config = scheduler.config.persisted_dict()
    calls = scheduler_calls(monkeypatch, scheduler)
    reservations = [factory(timeout_seconds=0, ledger_lock_timeout_seconds=1) for _ in range(2)]
    try:
        with held_lock(reservations[0].lock_path) as unlock:
            blocked = observe_real_contention(monkeypatch, reservations[0].lock_path, 2)
            with ThreadPoolExecutor(max_workers=2) as pool:
                futures = [pool.submit(reservation.__enter__) for reservation in reservations]
                try:
                    assert blocked.wait(3), "both threads must actually contend before unlocking"
                    assert all(not future.done() for future in futures)
                    assert calls == []
                finally:
                    unlock()
                assert [future.result(timeout=5) for future in futures] == reservations
        assert len(calls) == 2 and all(call[1]["timeout"] == 0 for call in calls)
        assert all(call[0] == (resources.SCHEDULER_LANE,) for call in calls)
        assert scheduler.snapshot()["allocated"]["cpu_slots"] == 2
        saved = json.loads(ledger.read_text())["reservations"]
        assert set(saved) == {reservation.reservation_id for reservation in reservations}
        assert all(row["status"] == "active" for row in saved.values())
        assert reservations[0].check_usage(roots[0])["outstanding_full_reservations_bytes"] == 20_000
        assert scheduler.config.persisted_dict() == original_config
    finally:
        for reservation in reservations:
            if reservation.to_dict()["record"] is not None:
                reservation.release(artifacts_durable=True)
    assert scheduler.snapshot()["allocated"]["cpu_slots"] == 0
    assert all(row["status"] == "released" for row in json.loads(ledger.read_text())["reservations"].values())


@pytest.mark.parametrize("options", [
    {}, {"ledger_lock_timeout_seconds": None}, {"ledger_lock_timeout_seconds": 0},
    {"ledger_lock_timeout_seconds": 0.03},
    {"timeout_seconds": 0.5, "ledger_lock_timeout_seconds": 0},
])
def test_held_lock_times_out_without_ledger_or_scheduler_admission(setup, monkeypatch, options):
    factory, _, ledger, scheduler = setup
    calls = scheduler_calls(monkeypatch, scheduler)
    reservation = factory(**options)
    with held_lock(reservation.lock_path):
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(reservation.__enter__)
            with pytest.raises(resources.DaemonResourceError, match="disk ledger lock unavailable"):
                future.result(timeout=2)
    assert calls == [] and not ledger.exists()
    assert reservation.to_dict()["status"] == "not_entered"
    assert scheduler.snapshot()["allocated"]["cpu_slots"] == 0


@pytest.mark.parametrize("explicit_none", [False, True])
def test_unspecified_lock_budget_inherits_legacy_positive_scheduler_timeout(setup, monkeypatch, explicit_none):
    factory, _, _, scheduler = setup
    calls = scheduler_calls(monkeypatch, scheduler)
    options = {"ledger_lock_timeout_seconds": None} if explicit_none else {}
    reservation = factory(timeout_seconds=0.5, **options)
    try:
        with held_lock(reservation.lock_path) as unlock:
            blocked = observe_real_contention(monkeypatch, reservation.lock_path, 1)
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(reservation.__enter__)
                try:
                    assert blocked.wait(2)
                finally:
                    unlock()
                assert future.result(timeout=3) is reservation
        assert calls[0][1]["timeout"] == 0.5
    finally:
        if reservation.to_dict()["record"] is not None:
            reservation.release(artifacts_durable=True)


@pytest.mark.parametrize("value", [True, False, -0.01, 60.01, float("nan"), float("inf"), -float("inf"), "1"])
def test_invalid_explicit_lock_budgets_rejected_before_files_or_admission(setup, monkeypatch, value):
    factory, _, ledger, scheduler = setup
    calls = scheduler_calls(monkeypatch, scheduler)
    with pytest.raises(resources.DaemonResourceError, match="ledger_lock_timeout_seconds"):
        factory(ledger_lock_timeout_seconds=value)
    assert calls == [] and not ledger.exists() and not ledger.with_name(ledger.name + ".lock").exists()


def test_explicit_bounds_and_legacy_large_timeout_are_preserved(setup):
    factory, _, ledger, _ = setup
    assert factory(ledger_lock_timeout_seconds=0).ledger_lock_timeout_seconds == 0
    assert factory(ledger_lock_timeout_seconds=60).ledger_lock_timeout_seconds == 60
    inherited = factory(timeout_seconds=61)
    assert inherited.timeout_seconds == inherited.ledger_lock_timeout_seconds == 61
    assert not ledger.exists()


def test_separate_lock_budget_does_not_raise_capacity_or_wait_for_scheduler(setup, monkeypatch):
    factory, _, ledger, scheduler = setup
    calls = scheduler_calls(monkeypatch, scheduler)
    original_config = scheduler.config.persisted_dict()
    with factory(cpu_slots=4, ledger_lock_timeout_seconds=1) as occupied:
        denied = factory(timeout_seconds=0, ledger_lock_timeout_seconds=1)
        try:
            with pytest.raises(LeaseTimeoutError, match="timed out waiting"):
                denied.__enter__()
            assert scheduler.snapshot()["allocated"]["cpu_slots"] == 4
            assert scheduler.config.persisted_dict() == original_config
            assert all(call[1]["timeout"] == 0 for call in calls)
            row = json.loads(ledger.read_text())["reservations"][denied.reservation_id]
            assert row["status"] == "retained" and row["retention_reason"] == "scheduler_admission_failed"
        finally:
            if denied.to_dict()["record"] is not None:
                denied.release(artifacts_durable=True)
            occupied.release(artifacts_durable=True)
    assert scheduler.snapshot()["allocated"]["cpu_slots"] == 0


def test_actual_owner_factory_selects_five_second_lock_and_zero_scheduler_budget(setup):
    _, roots, ledger, _ = setup
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_daemon_invocation import _reservation
    reservation = _reservation({"ledger_path": str(ledger), "roots": [str(root) for root in roots],
        "storage_bytes": 10_000, "memory_mb": 128, "cpu_slots": 1})
    assert type(reservation) is resources.DaemonResourceReservation
    assert reservation.ledger_lock_timeout_seconds == 5
    assert reservation.timeout_seconds == 0
    assert not ledger.exists()
