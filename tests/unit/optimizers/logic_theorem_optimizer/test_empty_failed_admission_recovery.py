"""Explicit empty-failure recovery in private test ledgers, never host state.

The existing fixture models a deceased owner explicitly. The production-owner
case creates an actual private native admission refusal; no worker is started.
These tests assert resource accounting, never successful validation or Lean.
"""
import json
import os

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_resource_recovery as recovery
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import resource_scheduler as native
from tests.unit.optimizers.logic_theorem_optimizer.test_autoencoder_daemon_resources import setup
from tests.unit.optimizers.logic_theorem_optimizer.test_autoencoder_resource_recovery import retained
from tests.unit.optimizers.logic_theorem_optimizer.test_validation_run_resources import private_control, _owner


def empty_failure(setup, monkeypatch):
    """Explicit private historical-record fixture; never the campaign ledger."""
    ledger, args, data = retained(setup, monkeypatch)
    (args['attempt_directory'] / 'failure.json').unlink()
    row = data['reservations'][args['reservation_id']]
    row.update(retention_reason='scheduler_admission_failed', scheduler_lane='validation',
               workload='canonical_validation')
    args.update(expected_record_sha256=recovery._digest(row), expected_artifacts=[])
    ledger.write_text(json.dumps(data))
    return ledger, args, data


def call(ledger, args, capacity_policy='require_capacity'):
    return recovery.reconcile_retained_reservation(ledger, **args,
        capacity_policy=capacity_policy, allow_empty_failed_admission=True)


def test_actual_private_validation_refusal_is_bound_empty_and_can_be_explicitly_closed(
        private_control, monkeypatch):
    attempt, _, _, options = private_control['prepare'](cpu_slots=5)
    owner = _owner(private_control, options)
    with pytest.raises(native.ResourceUnavailableError):
        owner.open()
    ledger = private_control['ledger']
    before = json.loads(ledger.read_bytes())
    row = before['reservations'][owner.reservation_id]
    assert row['status'] == 'retained' and row['retention_reason'] == 'scheduler_admission_failed'
    assert row['child'] is None and not any(attempt.iterdir())
    scheduler_before = private_control['scheduler'].state_path.read_bytes()
    # Only this private observation models the original owner as already dead.
    # Do not kill the test process or change its real native ownership.
    original_process = recovery.resources._process
    monkeypatch.setattr(recovery.resources, '_process',
        lambda pid: None if pid == row['owner_pid'] else original_process(pid))
    receipt = recovery.reconcile_retained_reservation(ledger, roots=[private_control['root']],
        reservation_id=owner.reservation_id, expected_record_sha256=recovery._digest(row),
        attempt_directory=attempt, expected_artifacts=[], artifacts_durable=True,
        allow_empty_failed_admission=True)
    after = json.loads(ledger.read_bytes())
    released = after['reservations'][owner.reservation_id]
    assert receipt['allow_empty_failed_admission'] is True and receipt['artifacts'] == []
    assert receipt['admitted'] is receipt['outputs_deleted'] is receipt['automatic_expiry'] is False
    assert released['status'] == 'released' and released['final_attempt_bytes'] == 0
    assert released['final_total_charged_bytes'] == 0 and not any(attempt.iterdir())
    assert all(released[key] == value for key, value in row.items()
               if key not in {'status', 'artifacts_durable_asserted'})
    assert after['reservations']['foreign-retained'] == before['reservations']['foreign-retained']
    assert private_control['scheduler'].state_path.read_bytes() == scheduler_before


def test_default_still_rejects_an_empty_failed_admission_without_writing(setup, monkeypatch):
    ledger, args, _ = empty_failure(setup, monkeypatch)
    before = ledger.read_bytes()
    with pytest.raises(recovery.resources.DaemonResourceError, match='durable artifact inventory'):
        recovery.reconcile_retained_reservation(ledger, **args)
    assert ledger.read_bytes() == before and not any(args['attempt_directory'].iterdir())


@pytest.mark.parametrize('value', [None, 0, 1, '', 'true', [], {}])
def test_opt_in_requires_an_exact_bool_before_resource_access(monkeypatch, value):
    monkeypatch.setattr(recovery.resources, 'DaemonResourceReservation',
        lambda *a, **k: pytest.fail('invalid opt-in reached resource access'))
    with pytest.raises(recovery.resources.DaemonResourceError, match='opt-in'):
        recovery.reconcile_retained_reservation('/not-accessed/ledger', roots=[],
            reservation_id='not-accessed', expected_record_sha256='not-accessed',
            attempt_directory='/not-accessed/attempt', expected_artifacts=[],
            artifacts_durable=True, allow_empty_failed_admission=value)


@pytest.mark.parametrize('inventory', [None, (), {}, '', False, 0, [{'path': 'marker'}]])
def test_empty_opt_in_rejects_falsey_substitutes_and_nonempty_inventory(monkeypatch, inventory):
    monkeypatch.setattr(recovery.resources, 'DaemonResourceReservation',
        lambda *a, **k: pytest.fail('invalid inventory reached resource access'))
    with pytest.raises(recovery.resources.DaemonResourceError, match='exact empty inventory list'):
        recovery.reconcile_retained_reservation('/not-accessed/ledger', roots=[],
            reservation_id='not-accessed', expected_record_sha256='not-accessed',
            attempt_directory='/not-accessed/attempt', expected_artifacts=inventory,
            artifacts_durable=True, allow_empty_failed_admission=True)


@pytest.mark.parametrize('field', ['native_lease_id', 'resource_lease', 'lease_id', 'native_grant',
    'owner_birth', 'validation_request_sha256', 'scheduler_state_path', 'scheduler_policy_sha256',
    'process_scope', 'outputs', 'legacy_engine_launch_sha256'])
def test_empty_mode_rejects_custody_or_output_field_presence_even_none(setup, monkeypatch, field):
    ledger, args, data = empty_failure(setup, monkeypatch)
    row = data['reservations'][args['reservation_id']]
    row[field] = None
    args['expected_record_sha256'] = recovery._digest(row)
    ledger.write_text(json.dumps(data)); before = ledger.read_bytes()
    with pytest.raises(recovery.resources.DaemonResourceError, match='custody, outputs or other history'):
        call(ledger, args)
    assert ledger.read_bytes() == before


@pytest.mark.parametrize('fault', ['wrong_reason', 'wrong_lane', 'wrong_workload', 'child',
    'prior_child', 'external_charge', 'already_durable', 'live_owner', 'wrong_record',
    'wrong_inode', 'active', 'empty_directory', 'new_file', 'no_durability'])
def test_empty_mode_refuses_ambiguous_history_or_actual_entries(setup, monkeypatch, fault):
    ledger, args, data = empty_failure(setup, monkeypatch)
    row = data['reservations'][args['reservation_id']]
    if fault == 'wrong_reason': row['retention_reason'] = 'context_failed'
    elif fault == 'wrong_lane': row['scheduler_lane'] = 'hammer_lean'
    elif fault == 'wrong_workload': row['workload'] = 'canonical_trainer'
    elif fault == 'child': row['child'] = {'pid': 99999998, 'birth': '123'}
    elif fault == 'prior_child': row['prior_children'] = [{'pid': 99999998, 'birth': '123'}]
    elif fault == 'external_charge': row['external_charges'] = {'external': 1}
    elif fault == 'already_durable': row['artifacts_durable_asserted'] = True
    elif fault == 'live_owner': row['owner_pid'] = os.getpid()
    elif fault == 'wrong_inode': row['attempt_directory']['inode'] += 1
    elif fault == 'active': row['status'] = 'active'
    elif fault == 'empty_directory': (args['attempt_directory'] / 'logs').mkdir()
    elif fault == 'new_file': (args['attempt_directory'] / 'marker').write_bytes(b'not validation')
    elif fault == 'no_durability': args['artifacts_durable'] = False
    args['expected_record_sha256'] = '0' * 64 if fault == 'wrong_record' else recovery._digest(row)
    ledger.write_text(json.dumps(data)); before = ledger.read_bytes()
    with pytest.raises(recovery.resources.DaemonResourceError):
        call(ledger, args)
    assert ledger.read_bytes() == before


def test_reused_original_pid_blocks_empty_recovery_even_with_other_birth(setup, monkeypatch):
    ledger, args, data = empty_failure(setup, monkeypatch)
    row = data['reservations'][args['reservation_id']]
    monkeypatch.setattr(recovery.resources, '_process',
        lambda pid: {'pid': pid, 'birth': 'different', 'state': 'S'} if pid == row['owner_pid'] else None)
    before = ledger.read_bytes()
    with pytest.raises(recovery.resources.DaemonResourceError, match='owner PID still exists'):
        call(ledger, args)
    assert ledger.read_bytes() == before


@pytest.mark.parametrize('capacity_policy,census_number',
    [('require_capacity', 1), ('administrative_closeout', 1), ('administrative_closeout', 2)])
@pytest.mark.parametrize('mutation', ['new_file', 'empty_directory', 'replace_inode'])
def test_actual_empty_attempt_stays_empty_and_bound_through_every_census(
        setup, monkeypatch, capacity_policy, census_number, mutation):
    ledger, args, _ = empty_failure(setup, monkeypatch)
    attempt = args['attempt_directory']
    holder = recovery if capacity_policy == 'administrative_closeout' else recovery.resources.DaemonResourceReservation
    name = '_administrative_census' if capacity_policy == 'administrative_closeout' else '_account'
    original = getattr(holder, name)
    calls = 0
    def mutate(helper, state, **kwargs):
        nonlocal calls
        report = original(helper, state, **kwargs)
        calls += 1
        if calls == census_number:
            if mutation == 'new_file': (attempt / 'new').write_bytes(b'changed')
            elif mutation == 'empty_directory': (attempt / 'logs').mkdir()
            else:
                attempt.rename(attempt.with_name('old-failed'))
                attempt.mkdir()
        return report
    monkeypatch.setattr(holder, name, mutate)
    before = ledger.read_bytes()
    with pytest.raises(recovery.resources.DaemonResourceError):
        call(ledger, args, capacity_policy)
    assert ledger.read_bytes() == before


def test_empty_default_capacity_cutoff_keeps_the_entire_claim_charged(setup, monkeypatch):
    ledger, args, _ = empty_failure(setup, monkeypatch)
    _, roots, _, _ = setup
    (roots[1] / 'unrelated.bin').write_bytes(b'x' * 95_000)
    before = ledger.read_bytes()
    with pytest.raises(recovery.resources.DaemonResourceError, match='capacity'):
        call(ledger, args)
    assert ledger.read_bytes() == before and not any(args['attempt_directory'].iterdir())


@pytest.mark.parametrize('capacity_policy', ['require_capacity', 'administrative_closeout'])
def test_one_empty_claim_releases_only_after_full_capacity_observation(setup, monkeypatch, capacity_policy):
    ledger, args, data = empty_failure(setup, monkeypatch)
    factory, _, _, scheduler = setup
    with factory(storage_bytes=500) as foreign:
        pass
    before = json.loads(ledger.read_bytes())
    scheduler_before = scheduler.snapshot()
    receipt = call(ledger, args, capacity_policy)
    after = json.loads(ledger.read_bytes())
    assert receipt['allow_empty_failed_admission'] is True and receipt['artifacts'] == []
    assert receipt['admitted'] is False and after['limit_bytes'] == before['limit_bytes']
    assert receipt['full_claim_accounting']['outstanding_full_reservations_bytes'] == 10_500
    assert receipt['final_accounting']['outstanding_full_reservations_bytes'] == 500
    assert after['reservations'][foreign.reservation_id] == before['reservations'][foreign.reservation_id]
    row = after['reservations'][args['reservation_id']]
    assert row['status'] == 'released' and row['final_attempt_bytes'] == row['final_total_charged_bytes'] == 0
    original = data['reservations'][args['reservation_id']]
    assert all(row[key] == value for key, value in original.items()
               if key not in {'status', 'artifacts_durable_asserted'})
    assert scheduler.snapshot() == scheduler_before and not any(args['attempt_directory'].iterdir())
    with pytest.raises(recovery.resources.DaemonResourceError, match='identity changed'):
        call(ledger, args, capacity_policy)


def test_nonempty_recovery_keeps_the_opt_in_absent_from_its_receipt(setup, monkeypatch):
    ledger, args, _ = retained(setup, monkeypatch)
    receipt = recovery.reconcile_retained_reservation(ledger, **args)
    assert 'allow_empty_failed_admission' not in receipt


# The legacy proof below is an explicit authored historical-evidence fixture.
# Genuine private native refusal and failed retention produce the reserved row;
# the old launcher traceback/source declarations are authored profile inputs, not
# a claim that this test reexecuted the historical host launcher or its timeout.
import hashlib as unopened_hashlib
from copy import deepcopy as unopened_copy


def unopened_raw(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def unopened_commit(args, proof):
    args['proof_raw'] = unopened_raw(proof)
    args['expected_proof_sha256'] = unopened_hashlib.sha256(args['proof_raw']).hexdigest()


def unopened_fixture(private_control, monkeypatch):
    c = private_control
    attempt, _, original_request, options = c['prepare'](cpu_slots=5)
    owner = _owner(c, options)
    def fail_retention(reason):
        raise recovery.resources.DaemonResourceError('authored private retention-write failure')
    monkeypatch.setattr(owner, '_retain', fail_retention)
    with pytest.raises(native.ResourceUnavailableError):
        owner.open()
    state = json.loads(c['ledger'].read_bytes())
    row = state['reservations'][owner.reservation_id]
    assert row['status'] == 'reserved' and row['child'] is None and row['prior_children'] == []
    assert not any(attempt.iterdir()) and owner.to_dict()['resource_lease'] is None
    request = unopened_copy(original_request)
    request['process_scope'] = 'sampled_birth_bound_descendants'
    source_root = '/authored/reviewed-source'
    source_pins = {
        'scripts/ops/legal_ir/run_owned_validation.py':
            '497e92a85709d1bb49385f85385ddcfef5b83c68820fa7479c9aa728e102e938',
        'ipfs_datasets_py/optimizers/logic_theorem_optimizer/validation_run_resources.py':
            '1cf169b22c944c878e1e622ce45e5f381ca831aaa40f4b1186082cae2383f429',
        'ipfs_datasets_py/optimizers/logic_theorem_optimizer/autoencoder_daemon_resources.py':
            '0cf17951048015d4ce01817c0bfdd74394a161cd5e7999b01a29f18f358e666a',
        'ipfs_datasets_py/optimizers/logic_theorem_optimizer/resource_scheduler.py':
            '2c00683202b4a783b5050329caa24a411f83788010baba86d9380123bae7d083',
    }
    request['source_sha256'] = {source_root + '/' + key: value for key, value in source_pins.items()}
    request_raw = unopened_raw(request)
    digest = unopened_hashlib.sha256(request_raw).hexdigest()
    failure = dict(schema='owned-validation-result/v1', request_sha256=digest,
        executed_checks=[], returncode=None, completed=False, admitted=False, Lean_admitted=False,
        resource_scope='cooperative_sampled_birth_bound_descendants_and_owned_attempt',
        model_weights_downloaded=False, authority_granted=False, error_type='LeaseTimeoutError',
        error='timed out waiting for a resource lease', elapsed_seconds=0.1,
        watchdog_errors=[], received_signals=[], process_observation=None, process_cleanup_error=None)
    reserved = owner.to_dict()
    reserved['process_observation'] = None
    terminal = dict(schema='owned-validation-failure-terminal/v1', request_sha256=digest,
        completed=False, admitted=False, Lean_admitted=False, failure=failure, reservation=reserved,
        process_cleanup_error=None, owner_exit_error=None)
    close = dict(schema='parent-replay-files-responsible-abnormal-controller-close/v1',
        controller_pid=99999997, controller_birth='authored-birth', argv=['authored-controller'],
        closed_at_utc='2026-10-21T00:15:23+00:00', recorded_at_utc='2026-10-21T00:15:12+00:00',
        request_sha256=digest, storage_reservation_id=owner.reservation_id,
        storage_bytes_fully_charged=row['storage_bytes'], storage_status_preserved='reserved',
        storage_reconciled=False, tests_executed=0, native_resource_lease_recorded=None,
        pidfd_exit_observed=True, controller_PID_absent_after_original_exec_reap=True,
        source_lock_descriptor_closed=True, original_exec_session_exit_code=137,
        inspection_sha256='1' * 64, peer_review='authored private review',
        post_signal_observation_error=None, signal='SIGKILL via exact pidfd',
        source_release_scope='authored abnormal closeout, no normal release')
    base = source_root + '/ipfs_datasets_py/optimizers/logic_theorem_optimizer/'
    launcher = source_root + '/scripts/ops/legal_ir/run_owned_validation.py'
    frames = [(launcher, 336, '<module>'), (launcher, 188, 'main'),
        (base + 'validation_run_resources.py', 273, 'open'),
        (base + 'autoencoder_daemon_resources.py', 486, '__enter__'),
        (base + 'autoencoder_daemon_resources.py', 500, '_acquire_native_lease'),
        (base + 'resource_scheduler.py', 2318, 'acquire')]
    trace = 'Traceback (most recent call last):\n' + ''.join(
        '  File "' + path + '", line ' + str(line) + ', in ' + function + '\n'
        for path, line, function in frames)
    trace += ('ipfs_datasets_py.optimizers.logic_theorem_optimizer.resource_scheduler.'
              'LeaseTimeoutError: timed out waiting for a resource lease\n')
    proof = dict(schema='empty-unopened-validation-proof/v1',
        profile='pinned-owned-validation-open-refusal-497e92a8/v1',
        request_raw_utf8=request_raw.decode(), terminal_raw_utf8=unopened_raw(terminal).decode(),
        stderr_utf8=trace, controller_closeout_raw_utf8=unopened_raw(close).decode())
    args = dict(roots=[c['root']], reservation_id=owner.reservation_id,
        expected_record_sha256=recovery._digest(row), attempt_directory=attempt,
        artifacts_durable=True)
    unopened_commit(args, proof)
    actual_process = recovery.resources._process
    # Exact fixture-only deceased-owner observation, never kill/adopt the test process.
    monkeypatch.setattr(recovery.resources, '_process',
        lambda pid: None if pid in (row['owner_pid'], close['controller_pid']) else actual_process(pid))
    return c['ledger'], args, proof, row


def unopened_call(ledger, args, policy='require_capacity'):
    return recovery.reconcile_empty_unopened_validation_reservation_v1(
        ledger, **args, capacity_policy=policy)


@pytest.mark.parametrize('policy', ['require_capacity', 'administrative_closeout'])
def test_reviewed_unopened_profile_closes_only_actual_private_reserved_storage(private_control, monkeypatch, policy):
    ledger, args, _, original = unopened_fixture(private_control, monkeypatch)
    before = json.loads(ledger.read_bytes())
    scheduler_before = private_control['scheduler'].state_path.read_bytes()
    receipt = unopened_call(ledger, args, policy)
    after = json.loads(ledger.read_bytes())
    row = after['reservations'][args['reservation_id']]
    assert receipt['schema'] == 'explicit-empty-unopened-reserved-reconciliation/v1'
    assert receipt['previous_status'] == 'reserved' and row['status'] == 'released'
    assert receipt['fresh_global_inventory_count'] == 2
    assert receipt['full_claim_accounting']['outstanding_full_reservations_bytes'] - receipt['final_accounting']['outstanding_full_reservations_bytes'] == original['storage_bytes']
    assert receipt['actual_postwrite_census_required'] is True
    for key in ('new_resource_lease_acquired', 'new_reservation_created', 'outputs_deleted',
                'automatic_expiry', 'admitted', 'validation_qualification_claimed',
                'historical_native_release_established', 'cap_changed'):
        assert receipt[key] is False
    assert receipt['proof']['new_original_native_terminal_created'] is False
    assert receipt['opening_scheduler_observation']['matching_leases'] == 0
    assert receipt['prewrite_scheduler_observation']['matching_waiters'] == 0
    assert 'retention_reason' not in row and row['final_attempt_bytes'] == row['final_total_charged_bytes'] == 0
    assert all(row[k] == v for k, v in original.items() if k not in ('status', 'artifacts_durable_asserted'))
    assert after['reservations']['foreign-retained'] == before['reservations']['foreign-retained']
    assert private_control['scheduler'].state_path.read_bytes() == scheduler_before
    assert not any(args['attempt_directory'].iterdir())
    released = ledger.read_bytes()
    with pytest.raises(recovery.resources.DaemonResourceError):
        unopened_call(ledger, args, policy)
    assert ledger.read_bytes() == released


def test_default_retained_recovery_still_refuses_reviewed_reserved_profile(private_control, monkeypatch):
    ledger, args, _, _ = unopened_fixture(private_control, monkeypatch)
    before = ledger.read_bytes()
    with pytest.raises(recovery.resources.DaemonResourceError, match='retained reservation identity'):
        recovery.reconcile_retained_reservation(ledger, roots=args['roots'],
            reservation_id=args['reservation_id'], expected_record_sha256=args['expected_record_sha256'],
            attempt_directory=args['attempt_directory'], expected_artifacts=[], artifacts_durable=True,
            allow_empty_failed_admission=True)
    assert ledger.read_bytes() == before


@pytest.mark.parametrize('fault', ['outer_hash', 'profile', 'unknown_producer', 'open_returned_trace',
    'unknown_exception', 'missing_trace', 'executed_check', 'completed', 'owner_exit_error',
    'native_lease', 'process_observation', 'storage_reconciled', 'controller_not_reaped',
    'source_not_closed', 'wrong_original_record', 'wrong_request_pin', 'extra_proof_field',
    'missing_failure_field', 'missing_closeout_field', 'duplicate_json', 'nonfinite_json'])
def test_unopened_profile_requires_complete_independently_pinned_original_evidence(private_control, monkeypatch, fault):
    ledger, args, proof, _ = unopened_fixture(private_control, monkeypatch)
    terminal = json.loads(proof['terminal_raw_utf8'])
    close = json.loads(proof['controller_closeout_raw_utf8'])
    request = json.loads(proof['request_raw_utf8'])
    if fault == 'profile': proof['profile'] = 'unknown'
    elif fault == 'unknown_producer':
        request['source_sha256'][next(iter(request['source_sha256']))] = '0' * 64
    elif fault == 'open_returned_trace': proof['stderr_utf8'] = proof['stderr_utf8'].replace('line 188', 'line 217')
    elif fault == 'unknown_exception': proof['stderr_utf8'] = proof['stderr_utf8'].replace('LeaseTimeoutError', 'RuntimeError')
    elif fault == 'missing_trace': proof['stderr_utf8'] = ''
    elif fault == 'executed_check': terminal['failure']['executed_checks'] = ['unknown execution']
    elif fault == 'completed': terminal['failure']['completed'] = True
    elif fault == 'owner_exit_error': terminal['owner_exit_error'] = 'unknown'
    elif fault == 'native_lease': terminal['reservation']['resource_lease'] = {'released': True}
    elif fault == 'process_observation': terminal['reservation']['process_observation'] = {'live_processes': 0}
    elif fault == 'storage_reconciled': close['storage_reconciled'] = True
    elif fault == 'controller_not_reaped': close['original_exec_session_exit_code'] = None
    elif fault == 'source_not_closed': close['source_lock_descriptor_closed'] = False
    elif fault == 'wrong_original_record': terminal['reservation']['record']['owner_pid'] += 1
    elif fault == 'wrong_request_pin': terminal['request_sha256'] = '0' * 64
    elif fault == 'extra_proof_field': proof['operator_says_safe'] = True
    elif fault == 'missing_failure_field': del terminal['failure']['process_observation']
    elif fault == 'missing_closeout_field': del close['native_resource_lease_recorded']
    proof.update(request_raw_utf8=unopened_raw(request).decode(),
        terminal_raw_utf8=unopened_raw(terminal).decode(), controller_closeout_raw_utf8=unopened_raw(close).decode())
    unopened_commit(args, proof)
    if fault == 'outer_hash': args['expected_proof_sha256'] = '0' * 64
    elif fault == 'duplicate_json':
        args['proof_raw'] = args['proof_raw'][:-1] + b',"schema":"empty-unopened-validation-proof/v1"}'
        args['expected_proof_sha256'] = unopened_hashlib.sha256(args['proof_raw']).hexdigest()
    elif fault == 'nonfinite_json':
        args['proof_raw'] = args['proof_raw'][:-1] + b',"unreviewed":NaN}'
        args['expected_proof_sha256'] = unopened_hashlib.sha256(args['proof_raw']).hexdigest()
    before = ledger.read_bytes()
    with pytest.raises(recovery.resources.DaemonResourceError):
        unopened_call(ledger, args)
    assert ledger.read_bytes() == before


@pytest.mark.parametrize('field', ['retention_reason', 'native_lease_id', 'resource_lease', 'lease_id',
    'native_grant', 'owner_birth', 'validation_request_sha256', 'scheduler_state_path',
    'scheduler_policy_sha256', 'process_scope', 'outputs', 'legacy_engine_launch_sha256'])
def test_unopened_reserved_mode_rejects_history_field_presence_even_none(private_control, monkeypatch, field):
    ledger, args, proof, _ = unopened_fixture(private_control, monkeypatch)
    body = json.loads(ledger.read_bytes())
    body['reservations'][args['reservation_id']][field] = None
    terminal = json.loads(proof['terminal_raw_utf8'])
    terminal['reservation']['record'][field] = None
    proof['terminal_raw_utf8'] = unopened_raw(terminal).decode()
    args['expected_record_sha256'] = recovery._digest(body['reservations'][args['reservation_id']])
    unopened_commit(args, proof)
    ledger.write_bytes(unopened_raw(body)); before = ledger.read_bytes()
    with pytest.raises(recovery.resources.DaemonResourceError, match='custody, outputs or other history'):
        unopened_call(ledger, args)
    assert ledger.read_bytes() == before


@pytest.mark.parametrize('fault', ['live_owner', 'reused_owner', 'live_controller', 'new_file',
    'empty_subdirectory', 'inode_replacement', 'missing_ledger_lock', 'wrong_policy', 'wrong_roots'])
def test_unopened_recovery_refuses_actual_ambiguous_current_custody(private_control, monkeypatch, fault):
    ledger, args, proof, row = unopened_fixture(private_control, monkeypatch)
    if fault in ('live_owner', 'reused_owner', 'live_controller'):
        pid = 99999997 if fault == 'live_controller' else row['owner_pid']
        monkeypatch.setattr(recovery.resources, '_process', lambda p:
            {'pid': p, 'birth': 'different-birth' if fault == 'reused_owner' else 'original-birth'} if p == pid else None)
    elif fault == 'new_file': (args['attempt_directory'] / 'new').write_bytes(b'preserve')
    elif fault == 'empty_subdirectory': (args['attempt_directory'] / 'logs').mkdir()
    elif fault == 'inode_replacement':
        args['attempt_directory'].rename(args['attempt_directory'].with_name('old'))
        args['attempt_directory'].mkdir()
    elif fault == 'missing_ledger_lock': ledger.with_name(ledger.name + '.lock').unlink()
    elif fault == 'wrong_policy':
        request = json.loads(proof['request_raw_utf8']); request['expected_scheduler_policy_sha256'] = '0' * 64
        proof['request_raw_utf8'] = unopened_raw(request).decode()
        request_sha = unopened_hashlib.sha256(proof['request_raw_utf8'].encode()).hexdigest()
        terminal = json.loads(proof['terminal_raw_utf8']); terminal['request_sha256'] = request_sha
        terminal['failure']['request_sha256'] = request_sha
        close = json.loads(proof['controller_closeout_raw_utf8']); close['request_sha256'] = request_sha
        proof['terminal_raw_utf8'] = unopened_raw(terminal).decode()
        proof['controller_closeout_raw_utf8'] = unopened_raw(close).decode(); unopened_commit(args, proof)
    elif fault == 'wrong_roots': args['roots'] = []
    before = ledger.read_bytes()
    with pytest.raises((recovery.resources.DaemonResourceError, native.ResourceSchedulerError, OSError)):
        unopened_call(ledger, args)
    assert ledger.read_bytes() == before


@pytest.mark.parametrize('kind', ['lease', 'waiter'])
def test_unopened_exact_scheduler_request_presence_blocks_without_persist_or_secrets(private_control, monkeypatch, kind):
    ledger, args, _, row = unopened_fixture(private_control, monkeypatch)
    scheduler = private_control['scheduler']; original = scheduler.state_path.read_bytes()
    body = json.loads(original)
    body['leases' if kind == 'lease' else 'waiters']['authored-owned'] = dict(
        lease_id='authored-owned', lease_key='private-secret', request_id='validation:' + args['reservation_id'],
        lane='validation', owner_pid=row['owner_pid'], owner_birth_marker=native._owner_birth_marker(row['owner_pid']),
        owner_boot_id=native._owner_boot_id(), parent_lease_id=None, acquired_at=1, heartbeat_at=1,
        expires_at=1, cancelled=False, cpu_slots=1, memory_mb=1, gpu_memory_mb=0,
        unified_memory_mb=0, child_process_slots=0, metadata={'authority_token': 'private-secret'})
    scheduler.state_path.write_bytes(unopened_raw(body)); selected_state = scheduler.state_path.read_bytes()
    before = ledger.read_bytes()
    try:
        with pytest.raises(recovery.resources.DaemonResourceError, match="scheduler request is still present"):
            unopened_call(ledger, args)
        assert ledger.read_bytes() == before and scheduler.state_path.read_bytes() == selected_state
    finally:
        scheduler.state_path.write_bytes(original)


@pytest.mark.parametrize('policy,census_number', [('require_capacity', 1), ('require_capacity', 2),
    ('administrative_closeout', 1), ('administrative_closeout', 2)])
@pytest.mark.parametrize('mutation', ['new_file', 'empty_subdirectory', 'live_owner',
    'selected_memory', 'foreign_memory', 'projected_body', 'disk_selected', 'disk_foreign'])
def test_unopened_every_census_preserves_empty_dead_and_full_disk_CAS(private_control, monkeypatch, policy, census_number, mutation):
    ledger, args, _, row = unopened_fixture(private_control, monkeypatch)
    holder = recovery if policy == 'administrative_closeout' else recovery.resources.DaemonResourceReservation
    name = '_administrative_census' if policy == 'administrative_closeout' else '_account'
    original = getattr(holder, name); calls = 0; actual_changed = None
    def change(helper, state, **kwargs):
        nonlocal calls, actual_changed
        value = original(helper, state, **kwargs); calls += 1
        if calls == census_number:
            if mutation == 'new_file': (args['attempt_directory'] / 'new').write_bytes(b'preserved')
            elif mutation == 'empty_subdirectory': (args['attempt_directory'] / 'logs').mkdir()
            elif mutation == 'live_owner': monkeypatch.setattr(recovery.resources, '_process', lambda p: {'pid': p, 'birth': 'reused'} if p == row['owner_pid'] else None)
            elif mutation in ('selected_memory', 'projected_body'):
                state['reservations'][args['reservation_id']]['memory_mb'] += 1
            elif mutation == 'foreign_memory': state['reservations']['foreign-retained']['storage_bytes'] += 1
            else:
                disk = json.loads(ledger.read_bytes())
                key = args['reservation_id'] if mutation == 'disk_selected' else 'foreign-retained'
                disk['reservations'][key]['storage_bytes'] += 1
                ledger.write_bytes(unopened_raw(disk)); actual_changed = ledger.read_bytes()
        return value
    monkeypatch.setattr(holder, name, change)
    before = ledger.read_bytes()
    with pytest.raises(recovery.resources.DaemonResourceError):
        unopened_call(ledger, args, policy)
    assert ledger.read_bytes() == (actual_changed if actual_changed is not None else before)
    if actual_changed is not None:
        # Restore only test-authored outside-lock drift for the fixture's own teardown.
        ledger.write_bytes(before)


@pytest.mark.parametrize('write_completed', [False, True])
def test_unopened_one_atomic_write_error_requires_readback_without_retry(private_control, monkeypatch, write_completed):
    ledger, args, _, _ = unopened_fixture(private_control, monkeypatch)
    original = recovery.resources.DaemonResourceReservation._write; calls = 0
    def fail(helper, body):
        nonlocal calls
        calls += 1
        if write_completed: original(helper, body)
        raise OSError('authored atomic-write ambiguity')
    monkeypatch.setattr(recovery.resources.DaemonResourceReservation, '_write', fail)
    before = ledger.read_bytes()
    with pytest.raises(OSError, match='atomic-write ambiguity'):
        unopened_call(ledger, args)
    assert calls == 1
    after = json.loads(ledger.read_bytes())
    assert after['reservations'][args['reservation_id']]['status'] == ('released' if write_completed else 'reserved')
    assert after['reservations']['foreign-retained'] == json.loads(before)['reservations']['foreign-retained']
    assert not any(args['attempt_directory'].iterdir())


def test_unopened_recovery_never_calls_native_admission_recovery_or_persistence(private_control, monkeypatch):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import existing_resource_scheduler as existing
    ledger, args, _, _ = unopened_fixture(private_control, monkeypatch)
    scheduler_before = private_control['scheduler'].state_path.read_bytes()
    def forbidden(*a, **k):
        pytest.fail('administrative unopened recovery invoked native persistent operation')
    with monkeypatch.context() as guard:
        for name in ('acquire', 'renew', 'release', 'cancel', 'snapshot', '_recover_stale_locked',
                     'recover_stale_leases', '_observe_recovery'):
            guard.setattr(native.GlobalResourceScheduler, name, forbidden)
        guard.setattr(existing._PinnedGlobalResourceScheduler, '_persist_locked_state', forbidden)
        receipt = unopened_call(ledger, args)
    assert private_control['scheduler'].state_path.read_bytes() == scheduler_before
    assert receipt['new_resource_lease_acquired'] is False
    assert 'private-secret' not in json.dumps(receipt)


@pytest.mark.parametrize('field,value', [('artifacts_durable', False), ('artifacts_durable', 1),
    ('reservation_id', ''), ('reservation_id', '0' * 31), ('expected_record_sha256', 'not-a-hash'),
    ('ledger_lock_timeout_seconds', True), ('ledger_lock_timeout_seconds', -1),
    ('ledger_lock_timeout_seconds', 31), ('ledger_lock_timeout_seconds', float('inf'))])
def test_unopened_invalid_scalars_refuse_before_live_resource_access(monkeypatch, field, value):
    args = dict(roots=['/never-accessed/root'], reservation_id='a' * 32,
        expected_record_sha256='b' * 64, attempt_directory='/never-accessed/root/attempt',
        proof_raw=b'{}', expected_proof_sha256=unopened_hashlib.sha256(b'{}').hexdigest(),
        artifacts_durable=True)
    args[field] = value
    monkeypatch.setattr(recovery.resources, 'DaemonResourceReservation',
        lambda *a, **k: pytest.fail('invalid scalar reached resource helper'))
    with pytest.raises(recovery.resources.DaemonResourceError):
        recovery.reconcile_empty_unopened_validation_reservation_v1('/never-accessed/ledger', **args)
