"""Strict facade and parented deadlines with genuine private resource owners.

No host-global facade, fake lease/token, altered admission sampler, provider,
production database, bootstrap or subprocess is used. Source generation and
normal import provenance belong to the invoking owner. A pending timeout stays
pending after an independent later empty-state observation.
"""
from contextlib import contextmanager
import fcntl
import json
import os
import threading
import time

import pytest
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import resource_scheduler as sdk
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import existing_resource_scheduler as existing
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_daemon_resources as disk
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import parented_phase_resources as parented


def _state(private):
    return json.loads(private['path'].read_bytes())


def _ledger(private):
    return json.loads(private['ledger'].read_bytes())


def _remember(private, lease):
    assert type(lease) is sdk.ResourceLease
    private['leases'].append(lease)
    return lease


@contextmanager
def _work(private, seconds=0.2):
    deadline = time.monotonic() + seconds
    assert deadline < private['native_deadline']
    with sdk.resource_admission_deadline(work_deadline_monotonic=deadline,
                                        native_deadline_monotonic=private['native_deadline']):
        yield deadline


@contextmanager
def _block_thread(lock):
    ready, release = threading.Event(), threading.Event()
    failures = []
    def hold():
        try:
            with lock:
                ready.set()
                assert release.wait(2), 'private lock holder exceeded its finite scope'
        except BaseException as error:
            failures.append(error)
    worker = threading.Thread(target=hold, name='private-sdk-thread-contention')
    worker.start()
    try:
        assert ready.wait(1), 'private lock holder did not become ready'
        yield
    finally:
        release.set()
        worker.join(1)
        assert not worker.is_alive(), 'private lock holder did not close'
        assert failures == []


@contextmanager
def _block(private, kind, *, ledger=False):
    if kind == 'thread':
        assert not ledger
        with _block_thread(private['creator']._thread_lock):
            yield
    else:
        assert kind == 'flock'
        path = private['ledger'].with_name(private['ledger'].name+'.lock') if ledger else private['creator'].lock_path
        with path.open('a+b') as held:
            fcntl.flock(held, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(held, fcntl.LOCK_UN)


def _wait_until(deadline):
    # A single real wait rather than a forged monotonic clock.
    threading.Event().wait(max(0, deadline-time.monotonic())+0.01)
    assert time.monotonic() >= deadline


@pytest.fixture
def private_scheduler(tmp_path, monkeypatch):
    def forbid_global(*args, **kwargs):
        pytest.fail('private strict path attempted the host-global scheduler')
    monkeypatch.setattr(sdk, 'get_global_resource_scheduler', forbid_global)
    monkeypatch.setattr(disk, 'get_global_resource_scheduler', forbid_global)
    before_globals = dict(sdk._GLOBAL_SCHEDULERS)
    original_native_deadline = time.monotonic()+8
    path = tmp_path/'scheduler.json'
    creator = sdk.GlobalResourceScheduler(sdk.ResourceSchedulerConfig(
        state_path=path, total_cpu_slots=2, total_memory_mb=128,
        total_gpu_memory_mb=None, total_unified_memory_mb=None,
        total_child_process_slots=8, lane_reservations={}, reserved_memory_mb=0,
        proof_safety_enabled=True, auto_renew_leases=False, poll_interval_seconds=0.005))
    policy = _state({'path':path})['config']
    assert policy['proof_safety_enabled'] is True
    expected = existing.policy_sha256(policy)
    facade = existing.open_existing_scheduler(path, expected)
    private = dict(path=path, creator=creator, facade=facade, policy=policy,
                   expected=expected, native_deadline=original_native_deadline,
                   leases=[], reservations=[], retained_errors=[], directory=tmp_path)
    try:
        yield private
    finally:
        failures = []
        # This is the fixture owner's original stopped-cleanup clock, created
        # before any fixture grant. It is never renewed or replaced on failure.
        try:
            with sdk.resource_cleanup_deadline(native_deadline_monotonic=original_native_deadline):
                for owner in reversed(private['reservations']):
                    if owner._entered and owner._record['status'] != 'released':
                        owner.release(artifacts_durable=True)
                for lease in reversed(private['leases']):
                    if not lease.released:
                        lease.release()
        except BaseException as error:
            failures.append(error)
        actual_leases = list(private['leases'])
        actual_leases += [owner._lease for owner in private['reservations'] if owner._lease is not None]
        for lease in actual_leases:
            worker = lease._heartbeat_thread
            if worker is not None and worker.ident is not None:
                worker.join(max(0, min(1, original_native_deadline-time.monotonic())))
                if worker.is_alive():
                    failures.append(AssertionError('actual private lease heartbeat remains live'))
        assert sdk._GLOBAL_SCHEDULERS == before_globals
        # These are genuine pending error objects from a blocked admission.
        # An independent later observation must not rewrite their uncertainty.
        for error in private['retained_errors']:
            assert error.resource_admission_cleanup_pending is True
        if private['retained_errors']:
            with (tmp_path/'pending-admission-observations.json').open('x') as stream:
                json.dump([dict(error_type=type(error).__name__, cleanup_pending=True,
                    waiter_id=error.resource_admission_waiter_id,
                    observed_waiter_present=error.resource_admission_waiter_id in _state(private)['waiters'],
                    reclassified_closed=False) for error in private['retained_errors']], stream)
        if failures:
            raise AssertionError('original-clock private fixture cleanup remains unresolved') from failures[0]
        state = _state(private)
        assert state['leases'] == {} and state['waiters'] == {}
        assert state['config'] == policy


@pytest.fixture
def private_parented(private_scheduler):
    private = private_scheduler
    root = private['directory']/'outputs'
    root.mkdir()
    bootstrap_attempt = root/'ledger-bootstrap'
    bootstrap_attempt.mkdir()
    attempt = root/'owned-attempt'
    attempt.mkdir()
    private.update(storage_root=root, ledger=private['directory']/'ledger.json', attempt=attempt)
    # Produce the existing ledger through a real strict base owner and genuine
    # native acquisition/finalization; no private JSON capability is authored.
    seed = disk.DaemonResourceReservation(private['ledger'], roots=(root,),
        storage_bytes=16384, memory_mb=4, cpu_slots=1, child_process_slots=1,
        timeout_seconds=0.5, scheduler_state_path=private['path'],
        expected_scheduler_policy_sha256=private['expected'])
    private['reservations'].append(seed)
    with _work(private, 1):
        with seed:
            seed.check_usage(bootstrap_attempt)
            seed.finalize(bootstrap_attempt, artifacts_durable=True)
        native_root = _remember(private, private['facade'].acquire(
            sdk.ResourceLane.HAMMER_LEAN, cpu_slots=2, memory_mb=32,
            child_process_slots=4, timeout=0.5))
        phase = _remember(private, native_root.acquire_child(cpu_slots=1,
            memory_mb=16, child_process_slots=2, timeout=0.5))
    private.update(root=native_root, phase=phase)
    return private


def _owner(private):
    owner = parented.ParentedPhaseResourceReservation(private['ledger'],
        roots=(private['storage_root'],), attempt_directory=private['attempt'],
        parent_lease=private['phase'], storage_bytes=16384, memory_mb=4,
        cpu_slots=1, child_process_slots=1, scheduler_state_path=private['path'],
        expected_scheduler_policy_sha256=private['expected'],
        timeout_seconds=private['native_deadline']-time.monotonic(),
        ledger_lock_timeout_seconds=1)
    private['reservations'].append(owner)
    return owner


@pytest.mark.parametrize('operation', ('open', 'currentness'))
@pytest.mark.parametrize('kind', ('thread', 'flock'))
def test_strict_facade_obeys_original_work_clock_under_real_contention(private_scheduler, operation, kind):
    private = private_scheduler
    before = private['path'].read_bytes()
    with _block(private, kind):
        started = time.monotonic()
        with pytest.raises(sdk.ResourceAdmissionDeadlineError):
            with _work(private, 0.1):
                if operation == 'open':
                    existing.open_existing_scheduler(private['path'], private['expected'])
                else:
                    private['facade'].active_leases()
        assert time.monotonic()-started < 1
    assert private['path'].read_bytes() == before


def test_strict_queued_admission_retires_waiter_under_original_native_clock(private_scheduler):
    private = private_scheduler
    occupied = _remember(private, private['facade'].acquire(sdk.ResourceLane.HAMMER_LEAN,
        cpu_slots=2, memory_mb=16, child_process_slots=1, timeout=0.5))
    with pytest.raises(sdk.ResourceAdmissionDeadlineError) as caught:
        with _work(private, 0.15):
            private['facade'].acquire(sdk.ResourceLane.HAMMER_LEAN,
                cpu_slots=1, memory_mb=4, child_process_slots=1, timeout=1)
    assert caught.value.resource_admission_scheduler is private['facade']
    assert caught.value.resource_admission_cleanup_pending is False
    state = _state(private)
    assert state['waiters'] == {} and set(state['leases']) == {occupied.lease_id}
    assert state['config'] == private['policy']


def test_strict_expired_cleanup_error_is_not_reclassified_by_later_readback(private_scheduler):
    private = private_scheduler
    with _block(private, 'flock'):
        now = time.monotonic()
        with pytest.raises(sdk.ResourceAdmissionDeadlineError) as caught:
            with sdk.resource_admission_deadline(work_deadline_monotonic=now+0.08,
                                                native_deadline_monotonic=now+0.16):
                private['facade'].try_acquire(sdk.ResourceLane.HAMMER_LEAN, memory_mb=4)
        error = caught.value
        assert error.resource_admission_cleanup_pending is True
        assert error.resource_admission_scheduler is private['facade']
        assert error.resource_admission_waiter_id
        private['retained_errors'].append(error)
    assert private['facade'].active_leases() == []
    assert _state(private)['waiters'] == {}
    assert error.resource_admission_cleanup_pending is True


def test_real_parented_owner_finalizes_without_releasing_ancestors(private_parented):
    private = private_parented
    with _work(private, 1):
        owner = _owner(private)
        with owner:
            actual = owner.native_lease
            assert type(actual) is sdk.ResourceLease
            assert actual.parent_lease_id == private['phase'].lease_id
            active = {row['lease_id']:row for row in private['facade'].active_leases()}
            assert set(active) == {private['root'].lease_id, private['phase'].lease_id, actual.lease_id}
            assert [row['lease_id'] for row in active.values() if row['parent_lease_id'] is None] == [private['root'].lease_id]
            assert _ledger(private)['reservations'][owner.reservation_id]['status'] == 'active'
            (private['attempt']/'evidence.txt').write_text('Genuine private parented fixture.\n')
            owner.finalize(private['attempt'], artifacts_durable=True)
    row = _ledger(private)['reservations'][owner.reservation_id]
    assert row['status'] == 'released' and row['artifacts_durable_asserted'] is True
    assert actual.released and not private['phase'].released and not private['root'].released
    assert set(_state(private)['leases']) == {private['root'].lease_id, private['phase'].lease_id}


def test_parented_enter_does_not_create_disk_claim_after_contended_work_deadline(private_parented):
    private = private_parented
    with _work(private, 1):
        owner = _owner(private)
    before = private['ledger'].read_bytes()
    with _block(private, 'flock', ledger=True):
        with pytest.raises(sdk.ResourceAdmissionDeadlineError):
            with _work(private, 0.1):
                owner.__enter__()
    assert not owner._entered and owner._record is None and owner._lease is None
    assert private['ledger'].read_bytes() == before
    assert set(_state(private)['leases']) == {private['root'].lease_id, private['phase'].lease_id}


def test_parented_native_wait_retains_full_disk_claim_until_explicit_original_clock_cleanup(private_parented):
    private = private_parented
    with _work(private, 1):
        competitor = _remember(private, private['phase'].acquire_child(cpu_slots=1,
            memory_mb=4, child_process_slots=1, timeout=0.5))
        owner = _owner(private)
    with pytest.raises(sdk.ResourceAdmissionDeadlineError) as caught:
        with _work(private, 0.3):
            owner.__enter__()
    assert caught.value.resource_admission_cleanup_pending is False
    assert owner._entered and owner._lease is None
    row = _ledger(private)['reservations'][owner.reservation_id]
    assert row['status'] in {'reserved', 'retained'}
    assert row['storage_bytes'] == 16384 and row['artifacts_durable_asserted'] is False
    assert owner._cleanup_error == 'ResourceAdmissionDeadlineError'
    assert _state(private)['waiters'] == {}
    assert set(_state(private)['leases']) == {private['root'].lease_id, private['phase'].lease_id, competitor.lease_id}
    with sdk.resource_cleanup_deadline(native_deadline_monotonic=private['native_deadline']):
        competitor.release()
        owner.release(artifacts_durable=True)
    assert _ledger(private)['reservations'][owner.reservation_id]['status'] == 'released'
    assert not private['root'].released and not private['phase'].released


def test_expired_parented_productive_finalize_requires_separate_original_native_cleanup(private_parented):
    private = private_parented
    with _work(private, 0.3) as deadline:
        owner = _owner(private)
        owner.__enter__()
        actual = owner._lease
        before = private['ledger'].read_bytes()
        _wait_until(deadline)
        with pytest.raises(sdk.ResourceAdmissionDeadlineError):
            owner.finalize(private['attempt'], artifacts_durable=True)
        assert private['ledger'].read_bytes() == before
        assert not actual.released
    row = _ledger(private)['reservations'][owner.reservation_id]
    assert row['status'] == 'active' and row['artifacts_durable_asserted'] is False
    with sdk.resource_cleanup_deadline(native_deadline_monotonic=private['native_deadline']):
        owner.release(artifacts_durable=True)
    assert actual.released and _ledger(private)['reservations'][owner.reservation_id]['status'] == 'released'
    assert not private['phase'].released and not private['root'].released


def test_revoked_parent_refuses_productive_finalize_but_allows_real_stopped_cleanup(private_parented):
    private = private_parented
    with _work(private, 1):
        owner = _owner(private)
        owner.__enter__()
        actual = owner._lease
        assert private['phase'].cancel()
        before = private['ledger'].read_bytes()
        with pytest.raises(disk.DaemonResourceError, match='revoked'):
            owner.finalize(private['attempt'], artifacts_durable=True)
        assert private['ledger'].read_bytes() == before and not actual.released
    with sdk.resource_cleanup_deadline(native_deadline_monotonic=private['native_deadline']):
        owner.release(artifacts_durable=True)
    assert actual.released and not private['phase'].released and not private['root'].released
    assert _ledger(private)['reservations'][owner.reservation_id]['status'] == 'released'


def test_parented_context_failure_retains_charge_after_native_child_stops(private_parented):
    private = private_parented
    with _work(private, 1):
        owner = _owner(private)
        with pytest.raises(RuntimeError, match='private productive failure'):
            with owner:
                actual = owner._lease
                raise RuntimeError('private productive failure')
    row = _ledger(private)['reservations'][owner.reservation_id]
    assert row['status'] == 'retained' and row['artifacts_durable_asserted'] is False
    assert actual.released and owner._cleanup_error is None
    assert set(_state(private)['leases']) == {private['root'].lease_id, private['phase'].lease_id}
    with sdk.resource_cleanup_deadline(native_deadline_monotonic=private['native_deadline']):
        owner.release(artifacts_durable=True)
    assert _ledger(private)['reservations'][owner.reservation_id]['status'] == 'released'


@pytest.mark.parametrize('boundary', ('queued_lstat', 'scandir_open'))
def test_parented_live_strict_inventory_retries_real_disappearance(private_parented, monkeypatch, boundary):
    private = private_parented
    with _work(private, 1):
        owner = _owner(private)
        owner.__enter__()
        attempt = private['attempt']
        (attempt/'retained.bin').write_bytes(b'kept123')
        child = attempt/'temporary'
        child.mkdir()
        before_ids = set(_state(private)['leases'])
        original_inventory, original_lstat, original_scandir = disk._inventory, type(attempt).lstat, os.scandir
        scans, deleted = [], []

        def strict_inventory(roots, *, strict=False):
            assert strict is True
            scans.append(True)
            return original_inventory(roots, strict=strict)

        def observed_lstat(path, *args, **kwargs):
            if boundary == 'queued_lstat' and path == child and not deleted:
                deleted.append(True)
                child.rmdir()
            return original_lstat(path, *args, **kwargs)

        def observed_scandir(path):
            if boundary == 'scandir_open' and str(path) == str(child) and not deleted:
                deleted.append(True)
                child.rmdir()
            return original_scandir(path)

        with monkeypatch.context() as changes:
            changes.setattr(disk, '_inventory', strict_inventory)
            changes.setattr(type(attempt), 'lstat', observed_lstat)
            changes.setattr(os, 'scandir', observed_scandir)
            usage = owner.check_usage(attempt)
        assert deleted == [True] and len(scans) == 2
        assert usage['attempt_bytes'] == 7 and not child.exists()
        assert set(_state(private)['leases']) == before_ids
        assert _state(private)['waiters'] == {}
        assert not owner.native_lease.released and not private['phase'].released
        owner.release(artifacts_durable=True)


def test_parented_live_strict_inventory_exhaustion_never_returns_partial_usage(private_parented, monkeypatch):
    private = private_parented
    with _work(private, 1):
        owner = _owner(private)
        owner.__enter__()
        attempt = private['attempt']
        (attempt/'retained.bin').write_bytes(b'kept123')
        child = attempt/'temporary'
        before_ids = set(_state(private)['leases'])
        previous_usage = owner._last_local_usage
        original_inventory, original_lstat = disk._inventory, type(attempt).lstat
        scans = []

        def strict_inventory(roots, *, strict=False):
            assert strict is True
            scans.append(True)
            child.mkdir()
            return original_inventory(roots, strict=strict)

        def observed_lstat(path, *args, **kwargs):
            if path == child and child.name in os.listdir(attempt):
                child.rmdir()
            return original_lstat(path, *args, **kwargs)

        with monkeypatch.context() as changes:
            changes.setattr(disk, '_inventory', strict_inventory)
            changes.setattr(type(attempt), 'lstat', observed_lstat)
            with pytest.raises(disk.DaemonResourceError) as caught:
                owner.check_usage(attempt)
        assert len(scans) == 3 and not child.exists()
        assert type(caught.value.__context__) is FileNotFoundError
        assert caught.value.__context__.filename == str(child)
        assert caught.value.__context__.errno == 2
        assert owner._last_local_usage is previous_usage
        assert set(_state(private)['leases']) == before_ids
        owner.release(artifacts_durable=True)


@pytest.mark.parametrize('replacement', (False, True))
def test_parented_live_strict_inventory_refuses_changed_root_between_scans(private_parented, monkeypatch, replacement):
    private = private_parented
    with _work(private, 1):
        owner = _owner(private)
        owner.__enter__()
        attempt = private['attempt']
        child = attempt/'temporary'
        child.mkdir()
        (attempt/'retained.bin').write_bytes(b'kept123')
        retired = attempt.with_name('retained-original-attempt')
        previous_usage = owner._last_local_usage
        original_inventory, original_scandir = disk._inventory, os.scandir
        scans, moved = [], []

        def strict_inventory(roots, *, strict=False):
            assert strict is True
            scans.append(True)
            return original_inventory(roots, strict=strict)

        def observed_scandir(path):
            if str(path) == str(child) and not moved:
                moved.append(True)
                attempt.rename(retired)
                if replacement:
                    attempt.mkdir()
            return original_scandir(path)

        try:
            with monkeypatch.context() as changes:
                changes.setattr(disk, '_inventory', strict_inventory)
                changes.setattr(os, 'scandir', observed_scandir)
                with pytest.raises((FileNotFoundError, disk.DaemonResourceError)):
                    owner.check_usage(attempt)
            assert moved == [True] and len(scans) == 1
            assert owner._last_local_usage is previous_usage
            assert (retired/'retained.bin').read_bytes() == b'kept123'
        finally:
            # Restore the original physical inode solely for private fixture
            # cleanup; the failed check remains failed and returns no usage.
            if moved:
                if replacement:
                    attempt.rmdir()
                retired.rename(attempt)
        owner.release(artifacts_durable=True)


def test_parented_live_strict_inventory_propagates_non_missing_errors_without_retry(private_parented, monkeypatch):
    import errno
    private = private_parented
    with _work(private, 1):
        owner = _owner(private)
        owner.__enter__()
        previous_usage = owner._last_local_usage
        before_ids = set(_state(private)['leases'])
        wrapped_io = disk.DaemonResourceError('noncanonical wrapped IO refusal')
        wrapped_io.__context__ = OSError(errno.EIO, 'private IO context')
        wrapped_missing = disk.DaemonResourceError('noncanonical wrapped missing refusal')
        wrapped_missing.__context__ = FileNotFoundError(errno.ENOENT, 'private missing context',
                                                       str(private['attempt']/'absent'))
        for error in (PermissionError(errno.EACCES, 'private permission refusal'),
                      OSError(errno.EIO, 'private IO refusal'), wrapped_io, wrapped_missing):
            calls = []

            def refused_inventory(roots, *, strict=False):
                assert strict is True
                calls.append(True)
                raise error

            with monkeypatch.context() as changes:
                changes.setattr(disk, '_inventory', refused_inventory)
                with pytest.raises(type(error)) as caught:
                    owner.check_usage(private['attempt'])
            assert caught.value is error and calls == [True]
            assert owner._last_local_usage is previous_usage
        assert set(_state(private)['leases']) == before_ids
        owner.release(artifacts_durable=True)


def test_parented_live_strict_inventory_retry_cannot_extend_original_work_deadline(private_parented, monkeypatch):
    private = private_parented
    with _work(private, 1):
        owner = _owner(private)
        owner.__enter__()
        attempt = private['attempt']
        child = attempt/'temporary'
        child.mkdir()
        previous_usage = owner._last_local_usage
        original_inventory, original_scandir = disk._inventory, os.scandir
        scans, deleted = [], []

        def observed_scandir(path):
            if str(path) == str(child) and not deleted:
                deleted.append(True)
                child.rmdir()
            return original_scandir(path)

        def delayed_strict_inventory(roots, *, strict=False):
            assert strict is True
            scans.append(True)
            try:
                return original_inventory(roots, strict=strict)
            except FileNotFoundError:
                threading.Event().wait(.04)
                raise

        with monkeypatch.context() as changes:
            changes.setattr(disk, '_inventory', delayed_strict_inventory)
            changes.setattr(os, 'scandir', observed_scandir)
            with _work(private, .02) as deadline:
                with pytest.raises(disk.DaemonResourceError, match='deadline expired'):
                    owner.check_usage(attempt)
                assert time.monotonic() >= deadline
        assert deleted == [True] and scans == [True]
        assert owner._last_local_usage is previous_usage
        owner.release(artifacts_durable=True)
