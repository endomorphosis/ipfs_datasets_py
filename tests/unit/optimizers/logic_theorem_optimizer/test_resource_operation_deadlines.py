"""Resource operation deadlines using genuine private scheduler state and locks.

These repository tests use normal package imports. Source generation and import
provenance are checked by the invoking owner, outside pytest fixtures.
No production database, provider, bootstrap, model weights or Lean admission.
"""
import fcntl
import json
import threading
import time

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import resource_scheduler as sdk
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_daemon_resources import DaemonResourceReservation, DaemonResourceError


def scheduler(tmp_path, *, auto_renew=False):
    return sdk.GlobalResourceScheduler(sdk.ResourceSchedulerConfig(
        state_path=tmp_path/'scheduler.json',total_cpu_slots=1,total_memory_mb=4,
        total_child_process_slots=1,reserved_memory_mb=0,lane_reservations={},
        auto_renew_leases=auto_renew,poll_interval_seconds=0.005))


def hold_lock(lock,ready,release):
    with lock:
        ready.set()
        assert release.wait(2)


def test_default_none_preserves_real_grant_release_and_state_schema(tmp_path):
    current=scheduler(tmp_path)
    assert sdk.resource_operation_deadline() is None
    root=current.acquire('proof',cpu_slots=1,memory_mb=1,timeout=0)
    child=root.acquire_child(cpu_slots=1,memory_mb=1,timeout=0)
    assert child.parent_lease_id==root.lease_id
    assert child.release() and root.release()
    state=json.loads(current.state_path.read_text())
    assert state['leases']=={} and state['waiters']=={}
    assert 'operation_deadline' not in state['config']


def test_context_restores_and_nested_scope_cannot_extend_original_clock():
    now=time.monotonic()
    with sdk.resource_admission_deadline(work_deadline_monotonic=now+1,native_deadline_monotonic=now+2):
        original=sdk.resource_operation_deadline()
        with pytest.raises(sdk.ResourceConfigurationError):
            with sdk.resource_admission_deadline(work_deadline_monotonic=now+1.1,native_deadline_monotonic=now+2):
                pass
        assert sdk.resource_operation_deadline() is original
    assert sdk.resource_operation_deadline() is None


def test_expired_scope_and_stopped_cleanup_never_grant(tmp_path):
    current=scheduler(tmp_path);now=time.monotonic()
    with pytest.raises(sdk.ResourceAdmissionDeadlineError):
        with sdk.resource_admission_deadline(work_deadline_monotonic=now-0.1,native_deadline_monotonic=now+1):
            current.acquire('proof',memory_mb=1)
    with sdk.resource_cleanup_deadline(native_deadline_monotonic=now+1):
        with pytest.raises(sdk.ResourceConfigurationError):
            current.acquire('proof',memory_mb=1)
    assert current.active_leases()==[]


def test_real_contended_thread_lock_obeys_productive_scope(tmp_path):
    current=scheduler(tmp_path);ready=threading.Event();release=threading.Event()
    worker=threading.Thread(target=hold_lock,args=(current._thread_lock,ready,release))
    worker.start();assert ready.wait(1)
    started=time.monotonic()
    try:
        with pytest.raises(sdk.ResourceAdmissionDeadlineError):
            with sdk.resource_admission_deadline(work_deadline_monotonic=started+0.05,native_deadline_monotonic=started+1):
                current.active_leases()
        assert time.monotonic()-started<0.5
    finally:
        release.set();worker.join(1);assert not worker.is_alive()
    assert current.active_leases()==[]


def test_real_flock_contention_on_currentness_probe_is_bounded(tmp_path):
    current=scheduler(tmp_path)
    with current.lock_path.open('a+') as blocker:
        fcntl.flock(blocker,fcntl.LOCK_EX)
        started=time.monotonic()
        try:
            with pytest.raises(sdk.ResourceAdmissionDeadlineError):
                with sdk.resource_admission_deadline(work_deadline_monotonic=started+0.05,native_deadline_monotonic=started+1):
                    current.active_leases()
            assert time.monotonic()-started<0.5
        finally:
            fcntl.flock(blocker,fcntl.LOCK_UN)
    assert current.active_leases()==[]


def test_genuine_queued_request_is_retired_under_original_cleanup_clock(tmp_path):
    current=scheduler(tmp_path);occupied=current.acquire('proof',memory_mb=1,timeout=0)
    started=time.monotonic()
    try:
        with pytest.raises(sdk.ResourceAdmissionDeadlineError) as caught:
            with sdk.resource_admission_deadline(work_deadline_monotonic=started+0.04,native_deadline_monotonic=started+1):
                current.acquire('proof',memory_mb=1,timeout=None)
        assert caught.value.resource_admission_cleanup_pending is False
        state=json.loads(current.state_path.read_text())
        assert state['waiters']=={} and set(state['leases'])=={occupied.lease_id}
    finally:
        occupied.release()


def test_ledger_flock_wait_uses_same_work_clock_without_native_grant(tmp_path):
    storage=tmp_path/'storage';storage.mkdir()
    reservation=DaemonResourceReservation(tmp_path/'ledger.json',roots=(storage,),
        storage_bytes=1024,memory_mb=1,timeout_seconds=1,ledger_lock_timeout_seconds=1)
    with reservation.lock_path.open('a+') as blocker:
        fcntl.flock(blocker,fcntl.LOCK_EX)
        started=time.monotonic()
        try:
            with pytest.raises((sdk.ResourceAdmissionDeadlineError,DaemonResourceError)):
                with sdk.resource_admission_deadline(work_deadline_monotonic=started+0.05,native_deadline_monotonic=started+1):
                    with reservation._locked():
                        pytest.fail('contended disk ledger admitted after work deadline')
            assert time.monotonic()-started<0.5
        finally:
            fcntl.flock(blocker,fcntl.LOCK_UN)
    assert not reservation.ledger_path.exists()


def test_try_acquire_keeps_legacy_timeout_none(tmp_path):
    current=scheduler(tmp_path);occupied=current.acquire('proof',memory_mb=1,timeout=0)
    try:
        assert current.try_acquire('proof',memory_mb=1) is None
        assert set(json.loads(current.state_path.read_text())['leases'])=={occupied.lease_id}
    finally:
        occupied.release()


def test_real_contended_try_acquire_preserves_pending_cleanup(tmp_path):
    current=scheduler(tmp_path)
    with current.lock_path.open('a+') as blocker:
        fcntl.flock(blocker,fcntl.LOCK_EX)
        now=time.monotonic()
        try:
            with pytest.raises(sdk.ResourceAdmissionDeadlineError) as caught:
                with sdk.resource_admission_deadline(work_deadline_monotonic=now+0.04,native_deadline_monotonic=now+0.10):
                    current.try_acquire('proof',memory_mb=1)
            assert caught.value.resource_admission_cleanup_pending is True
            assert caught.value.resource_admission_scheduler is current
            assert caught.value.resource_admission_waiter_id
        finally:
            fcntl.flock(blocker,fcntl.LOCK_UN)
    # A fresh read does not retroactively reclassify the retained unknown error.
    assert caught.value.resource_admission_cleanup_pending is True
    assert current.active_leases()==[]


def test_heartbeat_start_failure_retains_unknown_thread_custody(tmp_path,monkeypatch):
    current=scheduler(tmp_path,auto_renew=True)
    def fail_thread_start(_thread):
        raise RuntimeError('injected heartbeat start failure')
    monkeypatch.setattr(threading.Thread,'start',fail_thread_start)
    now=time.monotonic()
    with pytest.raises(RuntimeError,match='injected heartbeat start failure') as caught:
        with sdk.resource_admission_deadline(work_deadline_monotonic=now+0.5,native_deadline_monotonic=now+1):
            current.acquire('proof',memory_mb=1)
    assert caught.value.resource_admission_cleanup_pending is True
    actual=caught.value.resource_admission_owned_lease
    assert type(actual) is sdk.ResourceLease and actual.released is False
    assert actual._heartbeat_start_attempted is True and actual._heartbeat_start_returned is False
    assert actual._heartbeat_thread.ident is None
    # Native grant retirement alone cannot prove attempted thread startup closed.
    assert current.active_leases()==[]
    assert json.loads(current.state_path.read_text())['waiters']=={}


def test_late_heartbeat_start_is_not_returned_as_productive_lease(tmp_path,monkeypatch):
    current=scheduler(tmp_path,auto_renew=True);original=sdk.ResourceLease._start_heartbeat
    def start_then_delay(lease):
        original(lease)
        time.sleep(0.06)
    monkeypatch.setattr(sdk.ResourceLease,'_start_heartbeat',start_then_delay)
    now=time.monotonic()
    with pytest.raises(sdk.ResourceAdmissionDeadlineError) as caught:
        with sdk.resource_admission_deadline(work_deadline_monotonic=now+0.03,native_deadline_monotonic=now+1):
            current.acquire('proof',memory_mb=1)
    actual=caught.value.resource_admission_owned_lease
    assert type(actual) is sdk.ResourceLease and actual.released is True
    assert actual._heartbeat_thread is not None and not actual._heartbeat_thread.is_alive()
    assert actual._heartbeat_start_attempted is True and actual._heartbeat_start_returned is True
    assert caught.value.resource_admission_cleanup_pending is False
    assert current.active_leases()==[]
