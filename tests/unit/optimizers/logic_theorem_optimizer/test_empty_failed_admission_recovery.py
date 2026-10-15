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
