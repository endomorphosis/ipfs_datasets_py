"""Isolated owned-scheduler controls for fresh authenticated lease cadence.

No shared scheduler/configuration is changed. Root executes these controls;
they establish cancellation/authentication and isolated durable IO behavior,
not native CUDA or performance qualification. Scheduler methods are not patched.
"""
from contextlib import contextmanager
from dataclasses import FrozenInstanceError
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import threading
import time

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import authenticated_lease_heartbeat as subject
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import resource_scheduler as resources


def _pressure():
    return {}


@pytest.fixture
def owned(tmp_path):
    config = resources.ResourceSchedulerConfig(total_cpu_slots=4, total_memory_mb=1024,
        total_gpu_memory_mb=None, total_unified_memory_mb=1024, total_child_process_slots=4,
        lane_reservations={}, state_path=tmp_path / 'state.json', lease_ttl_seconds=120.0,
        auto_renew_leases=False, require_known_gpu_for_gpu_work=False, resource_pressure_sampler=_pressure)
    scheduler = resources.GlobalResourceScheduler(config)
    root = scheduler.acquire('validation', cpu_slots=2, memory_mb=64, timeout=0)
    child = root.acquire_child(cpu_slots=1, memory_mb=16, timeout=0)
    try:
        yield scheduler, root, child
    finally:
        child.release()
        root.release()


def _raw(scheduler):
    return scheduler.state_path.read_bytes()


def _state(scheduler):
    return json.loads(_raw(scheduler))


@contextmanager
def _edit(scheduler, mutation):
    # Corruption/race controls affect only this test-owned namespace and are
    # restored before the actual lease owners perform ordinary release.
    before = _state(scheduler)
    with scheduler._locked_state() as state:
        mutation(state)
    try:
        yield
    finally:
        with scheduler._locked_state() as state:
            state.clear()
            state.update(before)


def _set_due(state, lease):
    now = time.time()
    state['leases'][lease.lease_id]['heartbeat_at'] = now - 60
    state['leases'][lease.lease_id]['expires_at'] = now + 60


@contextmanager
def _observe_durable_calls():
    previous, events = sys.getprofile(), []
    names = {id(os.fsync): 'fsync', id(os.replace): 'replace'}
    def observe(frame, event, arg):
        if event == 'c_call' and id(arg) in names:
            events.append(names[id(arg)])
        if previous is not None:
            previous(frame, event, arg)
    try:
        sys.setprofile(observe)
        yield events
    finally:
        sys.setprofile(previous)


def _after_read(helper, callback):
    previous, fired = sys.getprofile(), False
    code = subject.AuthenticatedLeaseHeartbeat._read_current.__code__
    def observe(frame, event, arg):
        nonlocal fired
        if event == 'return' and frame.f_code is code and frame.f_locals.get('self') is helper and not fired:
            # _read_current returns after the lock context has closed. Entering
            # the real isolated writer here cannot deadlock the old read lock.
            fired = True
            callback()
        if previous is not None:
            previous(frame, event, arg)
    try:
        sys.setprofile(observe)
        return helper.check()
    finally:
        sys.setprofile(previous)


def test_nondue_poll_authenticates_fresh_state_without_durable_writes(owned):
    scheduler, root, child = owned
    helper = subject.AuthenticatedLeaseHeartbeat(child)
    before = _raw(scheduler)
    with _observe_durable_calls() as events:
        assert helper.check() is False
        assert helper.check() is False
    assert events == [] and _raw(scheduler) == before
    assert child._heartbeat_thread is None
    assert helper.inference_implementation['success_or_revision_cached'] is False
    assert helper.inference_implementation['parent_renewal_or_release_performed'] is False


def test_due_poll_changes_only_own_times_and_uses_existing_durable_sequence(owned):
    scheduler, root, child = owned
    helper = subject.AuthenticatedLeaseHeartbeat(child)
    with _edit(scheduler, lambda state: _set_due(state, child)):
        before = _state(scheduler)
        with _observe_durable_calls() as events:
            assert helper.check() is True
        after = _state(scheduler)
        assert events == ['fsync', 'replace', 'fsync']
        before_child, after_child = before['leases'][child.lease_id], after['leases'][child.lease_id]
        assert after_child['heartbeat_at'] > before_child['heartbeat_at']
        assert after_child['expires_at'] == after_child['heartbeat_at'] + 120.0
        after_child = {**after_child, 'heartbeat_at': before_child['heartbeat_at'], 'expires_at': before_child['expires_at']}
        assert after_child == before_child
        after['leases'][child.lease_id] = after_child
        assert after == before
        with _observe_durable_calls() as events:
            assert helper.check() is False
        assert events == []


def test_constructor_and_checks_do_not_free_or_cancel_expired_unrelated_live_charges(owned):
    scheduler, root, child = owned
    unrelated = scheduler.acquire('validation', cpu_slots=1, memory_mb=32, timeout=0)
    try:
        def expire(state):
            state['leases'][unrelated.lease_id]['expires_at'] = time.time() - 1
        with _edit(scheduler, expire):
            before = _raw(scheduler)
            helper = subject.AuthenticatedLeaseHeartbeat(child)
            assert helper.check() is False
            assert _raw(scheduler) == before
            state = _state(scheduler)
            assert unrelated.lease_id in state['leases']
            assert state['leases'][unrelated.lease_id]['cancelled'] is False
            assert resources.GlobalResourceScheduler._root_usage(state)[:2] == (3, 96)
            with _edit(scheduler, lambda state: _set_due(state, child)):
                assert helper.check() is True
                state = _state(scheduler)
                assert unrelated.lease_id in state['leases']
                assert state['leases'][unrelated.lease_id]['cancelled'] is False
                assert resources.GlobalResourceScheduler._root_usage(state)[:2] == (3, 96)
    finally:
        unrelated.release()


@pytest.mark.parametrize('field,replacement', (('lease_key', ''), ('lease_id', ''),
                                             ('lease_key', 'wrong-key'), ('owner_pid', -1)))
def test_local_lease_authority_or_owner_changes_are_refused(owned, field, replacement):
    scheduler, root, child = owned
    helper = subject.AuthenticatedLeaseHeartbeat(child)
    before = getattr(child, field)
    try:
        setattr(child, field, replacement)
        with pytest.raises(ValueError):
            helper.check()
        with pytest.raises((ValueError, resources.LeaseNotFoundError)):
            subject.AuthenticatedLeaseHeartbeat(child)
    finally:
        setattr(child, field, before)


@pytest.mark.parametrize('target,field,replacement', (
    ('own', 'lease_key', 'wrong-key'), ('own', 'cancelled', True), ('own', 'release_requested', True),
    ('parent', 'cancelled', True), ('parent', 'release_requested', True),
    ('parent', 'expires_at', 0.0), ('own', 'expires_at', 0.0),
    ('parent', 'owner_birth_marker', 'nonmatching-birth-marker'),
    ('parent', 'owner_boot_id', '00000000-0000-0000-0000-000000000000'),
    ('parent', 'owner_pid', -1), ('own', 'cpu_slots', 2),
))
def test_fresh_authentication_and_complete_ancestry_refuse_without_helper_writes(owned, target, field, replacement):
    scheduler, root, child = owned
    helper = subject.AuthenticatedLeaseHeartbeat(child)
    identifier = child.lease_id if target == 'own' else root.lease_id
    def corrupt(state):
        state['leases'][identifier][field] = replacement
    with _edit(scheduler, corrupt):
        before = _raw(scheduler)
        with _observe_durable_calls() as events:
            with pytest.raises((ValueError, resources.LeaseCancelledError, resources.LeaseNotFoundError)):
                helper.check()
        assert events == [] and _raw(scheduler) == before


@pytest.mark.parametrize('mutation', ('missing_own', 'missing_parent', 'cycle', 'identifier_alias'))
def test_missing_or_cyclic_or_aliased_ancestry_is_never_admitted(owned, mutation):
    scheduler, root, child = owned
    helper = subject.AuthenticatedLeaseHeartbeat(child)
    def corrupt(state):
        if mutation == 'missing_own':
            del state['leases'][child.lease_id]
        elif mutation == 'missing_parent':
            del state['leases'][root.lease_id]
        elif mutation == 'cycle':
            state['leases'][root.lease_id]['parent_lease_id'] = child.lease_id
        else:
            state['leases'][root.lease_id]['lease_id'] = 'different-record-id'
    with _edit(scheduler, corrupt):
        with pytest.raises((ValueError, resources.LeaseCancelledError, resources.LeaseNotFoundError)):
            helper.check()


@pytest.mark.parametrize('change', ('own_cancel', 'parent_cancel', 'parent_expire', 'key'))
def test_due_writer_reauthenticates_cancellation_expiry_and_key_races(owned, change):
    scheduler, root, child = owned
    helper = subject.AuthenticatedLeaseHeartbeat(child)
    with _edit(scheduler, lambda state: _set_due(state, child)):
        def mutate_after_read():
            with scheduler._locked_state() as state:
                record = state['leases'][root.lease_id if change.startswith('parent') else child.lease_id]
                if change.endswith('cancel'):
                    record['cancelled'] = True
                elif change.endswith('expire'):
                    record['expires_at'] = 0.0
                else:
                    record['lease_key'] = 'changed-after-read'
        before_times = {key: _state(scheduler)['leases'][child.lease_id][key] for key in ('heartbeat_at', 'expires_at')}
        with pytest.raises((ValueError, resources.LeaseCancelledError, resources.LeaseNotFoundError)):
            _after_read(helper, mutate_after_read)
        after = _state(scheduler)['leases'][child.lease_id]
        assert {key: after[key] for key in before_times} == before_times


def test_peer_renewal_race_aborts_writer_without_reencoding_pretty_state(owned):
    scheduler, root, child = owned
    helper = subject.AuthenticatedLeaseHeartbeat(child)
    with _edit(scheduler, lambda state: _set_due(state, child)):
        observed = []
        def peer_renew():
            # Real unchanged scheduler method, followed by alternate ordinary
            # JSON whitespace, isolates accidental writer-normalization IO.
            assert child.renew() is True
            scheduler.state_path.write_text(json.dumps(_state(scheduler), indent=2), encoding='utf-8')
            observed.append(_raw(scheduler))
        assert _after_read(helper, peer_renew) is False
        assert observed and _raw(scheduler) == observed[0]


@pytest.mark.parametrize('fraction', (True, 1, 0.0, -.1, .50001, float('nan'), float('inf')))
def test_fraction_bounds_and_exact_types_refuse(owned, fraction):
    with pytest.raises(ValueError, match='renewal fraction'):
        subject.AuthenticatedLeaseHeartbeat(owned[2], renewal_fraction=fraction)


def test_frozen_helper_no_lazy_none_anchor_or_replacement_admission(owned):
    helper = subject.AuthenticatedLeaseHeartbeat(owned[2])
    with pytest.raises(FrozenInstanceError):
        helper._ancestry = None
    before = helper._ancestry
    try:
        object.__setattr__(helper, '_ancestry', None)
        with pytest.raises(ValueError, match='snapshot binding'):
            helper.check()
    finally:
        object.__setattr__(helper, '_ancestry', before)


def test_released_lease_and_other_thread_refuse(owned):
    scheduler, root, child = owned
    helper = subject.AuthenticatedLeaseHeartbeat(child)
    errors = []
    def other_thread():
        try:
            helper.check()
        except ValueError as error:
            errors.append(str(error))
    worker = threading.Thread(target=other_thread)
    worker.start()
    worker.join(5)
    assert not worker.is_alive() and len(errors) == 1
    child.release()
    with pytest.raises(ValueError):
        helper.check()


def test_exact_scheduler_objects_and_fixed_configuration_identity_are_required(owned):
    scheduler, root, child = owned
    helper = subject.AuthenticatedLeaseHeartbeat(child)
    original = child._scheduler
    try:
        child._scheduler = object()
        with pytest.raises(ValueError):
            helper.check()
        with pytest.raises(ValueError, match='exact ResourceLease'):
            subject.AuthenticatedLeaseHeartbeat(child)
    finally:
        child._scheduler = original
    original = scheduler.config.lease_ttl_seconds
    try:
        scheduler.config.lease_ttl_seconds = 121.0
        with pytest.raises(ValueError, match='snapshot binding|configuration binding'):
            helper.check()
    finally:
        scheduler.config.lease_ttl_seconds = original


@pytest.mark.parametrize('alias', ('_OWNER_ALIVE', '_LOCKED_STATE', '_due', 'inference_implementation'))
def test_helper_alias_replacement_refuses_before_state_work(owned, monkeypatch, alias):
    helper = subject.AuthenticatedLeaseHeartbeat(owned[2])
    monkeypatch.setattr(subject, alias, lambda *args, **kwargs: True)
    with pytest.raises(ValueError, match='helper binding'):
        helper.check()


def test_helper_default_mutation_and_code_replacement_refuse(owned, monkeypatch):
    helper = subject.AuthenticatedLeaseHeartbeat(owned[2])
    with monkeypatch.context() as temporary:
        temporary.setitem(subject.AuthenticatedLeaseHeartbeat.__init__.__kwdefaults__, 'renewal_fraction', .5)
        with pytest.raises(ValueError, match='method binding'):
            helper.check()
    with monkeypatch.context() as temporary:
        replacement = lambda record, now, interval: False
        temporary.setattr(subject._due, '__code__', replacement.__code__)
        with pytest.raises(ValueError, match='helper binding'):
            helper.check()


@pytest.mark.parametrize('size', (1, 17))
def test_callable_wrapper_cycle_and_oversized_chain_refuse_boundedly(size):
    functions = [(lambda: None) for _ in range(size)]
    for left, right in zip(functions, functions[1:]):
        left.__wrapped__ = right
    if size == 1:
        functions[0].__wrapped__ = functions[0]
    with pytest.raises(ValueError, match='bounded acyclic callable'):
        subject._fingerprint(functions[0])


def test_keyword_default_fingerprint_retains_exact_numeric_type():
    def function(*, enabled=True):
        return enabled
    original = subject._fingerprint(function)
    function.__kwdefaults__['enabled'] = 1
    assert not subject._same_callable(function, original)


@pytest.mark.parametrize('field', ('persisted_dict', 'lane_reservations', 'state_path'))
def test_configuration_conversion_callbacks_refuse_before_execution(owned, field):
    scheduler, root, child = owned
    helper = subject.AuthenticatedLeaseHeartbeat(child)
    invoked = []
    class ExoticMapping(dict):
        def items(self):
            invoked.append('items')
            return super().items()
    class ExoticPath(str):
        def __str__(self):
            invoked.append('str')
            return super().__str__()
    existed = field in vars(scheduler.config)
    original = getattr(scheduler.config, field)
    replacement = ((lambda: invoked.append('persisted_dict')) if field == 'persisted_dict'
                   else ExoticMapping() if field == 'lane_reservations' else ExoticPath('unused'))
    try:
        setattr(scheduler.config, field, replacement)
        with pytest.raises(ValueError):
            helper.check()
        with pytest.raises(ValueError):
            subject.AuthenticatedLeaseHeartbeat(child)
        assert invoked == []
    finally:
        if existed:
            setattr(scheduler.config, field, original)
        else:
            delattr(scheduler.config, field)


def test_scheduler_class_alias_replacement_is_rejected_without_method_patch(owned, monkeypatch):
    helper = subject.AuthenticatedLeaseHeartbeat(owned[2])
    monkeypatch.setattr(resources, 'GlobalResourceScheduler', object)
    with pytest.raises(ValueError, match='class/method binding'):
        helper.check()


def test_current_helper_source_drift_refuses_in_temporary_copy(owned, tmp_path, monkeypatch):
    path = tmp_path / 'authenticated_copy.py'
    path.write_bytes(Path(subject.__file__).read_bytes())
    name = subject.__package__ + '._authenticated_control_copy'
    specification = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(specification)
    monkeypatch.setitem(sys.modules, name, module)
    specification.loader.exec_module(module)
    helper = module.AuthenticatedLeaseHeartbeat(owned[2])
    assert helper.check() is False
    path.write_bytes(path.read_bytes() + b'\n# drift only in temporary control source\n')
    with pytest.raises(ValueError, match='dependency source changed'):
        helper.check()


def test_descriptor_mutation_does_not_change_following_policy_and_scheduler_source_is_frozen():
    descriptor = subject.inference_implementation()
    descriptor['scheduler_source_sha256'] = '0' * 64
    assert subject.inference_implementation()['scheduler_source_sha256'] == subject.SCHEDULER_SHA256
    assert hashlib.sha256(Path(resources.__file__).read_bytes()).hexdigest() == subject.SCHEDULER_SHA256
