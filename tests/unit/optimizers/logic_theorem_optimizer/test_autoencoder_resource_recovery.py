"""Explicit one-record recovery; original resource ownership is never adopted."""
import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_resource_recovery as recovery
from tests.unit.optimizers.logic_theorem_optimizer.test_autoencoder_daemon_resources import setup


def disposition_case(setup, monkeypatch, scope="isolated_process_group_only"):
    """Private real ledger/recovery API; custody labels are explicit test data.

    These tests qualify storage-history inspection, never a real native lease
    release. The existing fixture supplies its own real private scheduler.
    """
    _, roots, _, scheduler = setup
    ledger = roots[1] / 'control' / 'disk.json'
    ledger.parent.mkdir()
    def factory(**kwargs):
        return recovery.resources.DaemonResourceReservation(ledger, roots=roots,
            storage_bytes=kwargs.pop('storage_bytes', 10_000),
            memory_mb=kwargs.pop('memory_mb', 128), **kwargs)
    ledger, args, before = retained((factory, roots, ledger, scheduler), monkeypatch)
    row = before['reservations'][args['reservation_id']]
    row.update(validation_request_sha256='a' * 64, scheduler_lane='validation',
        workload='canonical_validation', owner_birth='123', native_lease_id='b' * 32,
        scheduler_policy_sha256='c' * 64,
        scheduler_state_path=str(roots[1] / 'never-opened-native-state.json'),
        process_scope=scope, child=None, prior_children=[],
        outputs={name: str(args['attempt_directory'] / name)
                 for name in ('pytest', 'tmp', 'cache', 'db', 'exports', 'logs')})
    ledger.write_text(json.dumps(before))
    args['expected_record_sha256'] = recovery._digest(row)
    previous = args['expected_record_sha256']
    recovery.reconcile_retained_reservation(ledger, **args)
    current = json.loads(ledger.read_bytes())['reservations'][args['reservation_id']]
    call = dict(roots=roots, reservation_id=args['reservation_id'],
        expected_request_sha256='a' * 64, attempt_directory=args['attempt_directory'],
        expected_record_sha256=recovery._digest(current),
        expected_previous_record_sha256=previous, process_scope=scope)
    return ledger, call, current


def inspection_only(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('inspection attempted allocation, recovery, inventory, or write')
    monkeypatch.setattr(recovery.resources.DaemonResourceReservation, '_write', forbidden)
    monkeypatch.setattr(recovery.resources.DaemonResourceReservation, '_account', forbidden)
    monkeypatch.setattr(recovery.resources, 'get_global_resource_scheduler', forbidden)
    monkeypatch.setattr(recovery, '_administrative_census', forbidden)
    monkeypatch.setattr(recovery, '_durable_inventory', forbidden)
    monkeypatch.setattr(recovery, 'reconcile_retained_reservation', forbidden)


@pytest.mark.parametrize('scope', ['isolated_process_group_only', 'sampled_birth_bound_descendants'])
def test_storage_disposition_authenticates_original_release_without_native_authority(setup, monkeypatch, scope):
    ledger, call, _ = disposition_case(setup, monkeypatch, scope)
    before = ledger.read_bytes()
    inspection_only(monkeypatch)
    result = recovery.inspect_validation_disposition(ledger, **call)
    assert result['storage_release_established'] is True
    assert result['native_release_established'] is result['admitted'] is False
    assert result['state_written'] is result['recovery_performed'] is False
    assert result['native_lease_disposition'] is None
    assert result['release_evidence']['previous_record_sha256'] == call['expected_previous_record_sha256']
    assert result['release_evidence']['artifacts_reinventoried'] is False
    assert ledger.read_bytes() == before


def test_validation_inspection_default_stays_group_only(setup, monkeypatch):
    ledger, call, _ = disposition_case(setup, monkeypatch, 'sampled_birth_bound_descendants')
    selected = {key: call[key] for key in ('roots', 'reservation_id', 'expected_request_sha256', 'attempt_directory')}
    before = ledger.read_bytes()
    with pytest.raises(recovery.resources.DaemonResourceError, match='native lease custody'):
        recovery.inspect_validation_reservation(ledger, **selected)
    result = recovery.inspect_validation_reservation(ledger, **selected,
        process_scope='sampled_birth_bound_descendants')
    assert result['binding_verified'] is True and result['historical_release_established'] is False
    assert ledger.read_bytes() == before


@pytest.mark.parametrize('scope', [None, True, 1, 'tracked', 'isolated_process_group'])
def test_validation_inspection_rejects_undeclared_scope_before_path_access(monkeypatch, scope):
    def forbidden(*args, **kwargs):
        raise AssertionError('invalid scalar accessed state')
    monkeypatch.setattr(recovery.resources, 'DaemonResourceReservation', forbidden)
    with pytest.raises(recovery.resources.DaemonResourceError, match='process scope'):
        recovery.inspect_validation_reservation('/not-accessed/ledger', roots=['/not-accessed/root'],
            reservation_id='a' * 32, expected_request_sha256='b' * 64,
            attempt_directory='/not-accessed/root/attempt', process_scope=scope)


@pytest.mark.parametrize('fault', ['retained', 'status-only', 'unknown-schema', 'previous-hash',
    'current-hash', 'request-hash', 'wrong-scope', 'deleted-outputs', 'admission', 'boolean-release-time'])
def test_storage_disposition_refuses_ambiguous_or_foreign_history(setup, monkeypatch, fault):
    ledger, call, row = disposition_case(setup, monkeypatch)
    data = json.loads(ledger.read_bytes())
    row = data['reservations'][call['reservation_id']]
    if fault == 'retained': row['status'] = 'retained'
    elif fault == 'status-only': del row['explicit_reconciliation']
    elif fault == 'unknown-schema': row['explicit_reconciliation']['schema'] = 'unreviewed/v1'
    elif fault == 'previous-hash': call['expected_previous_record_sha256'] = '0' * 64
    elif fault == 'current-hash': call['expected_record_sha256'] = '0' * 64
    elif fault == 'request-hash': call['expected_request_sha256'] = '0' * 64
    elif fault == 'wrong-scope': call['process_scope'] = 'sampled_birth_bound_descendants'
    elif fault == 'deleted-outputs': row['explicit_reconciliation']['outputs_deleted'] = True
    elif fault == 'admission': row['explicit_reconciliation']['admitted'] = True
    elif fault == 'boolean-release-time': row['released_at'] = True
    ledger.write_text(json.dumps(data))
    if fault != 'current-hash': call['expected_record_sha256'] = recovery._digest(row)
    before = ledger.read_bytes()
    inspection_only(monkeypatch)
    try:
        result = recovery.inspect_validation_disposition(ledger, **call)
    except recovery.resources.DaemonResourceError:
        pass
    else:
        assert result['storage_release_established'] is False
    assert ledger.read_bytes() == before


def archive_disposition(ledger, call, *, historical_limit=None):
    data = json.loads(ledger.read_bytes())
    original = data['reservations'][call['reservation_id']]
    snapshot = json.loads(json.dumps(data))
    if historical_limit is not None: snapshot['limit_bytes'] = historical_limit
    directory = ledger.parent / 'ledger-archives' / 'private-test'
    directory.mkdir(parents=True)
    path = directory / 'ledger-before.private.json'
    raw = json.dumps(snapshot, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
    path.write_bytes(raw)
    field = original['explicit_reconciliation']
    original['explicit_reconciliation'] = {
        'schema': 'released-reconciliation-archive-pointer/v1',
        'reservation_id': call['reservation_id'], 'snapshot_path': str(path),
        'snapshot_sha256': hashlib.sha256(raw).hexdigest(),
        'original_record_sha256': recovery._digest(snapshot['reservations'][call['reservation_id']]),
        'original_field_sha256': recovery._digest(field)}
    ledger.write_text(json.dumps(data))
    call['expected_record_sha256'] = recovery._digest(original)
    return path


@pytest.mark.parametrize('historical_limit', [None, 80_000])
def test_storage_disposition_reconstructs_archived_history_without_reusing_old_cap(setup, monkeypatch, historical_limit):
    ledger, call, _ = disposition_case(setup, monkeypatch)
    path = archive_disposition(ledger, call, historical_limit=historical_limit)
    before, snapshot = ledger.read_bytes(), path.read_bytes()
    inspection_only(monkeypatch)
    result = recovery.inspect_validation_disposition(ledger, **call)
    assert result['storage_release_established'] is True
    assert result['release_evidence']['archive']['path'] == str(path)
    assert result['release_evidence']['historical_capacity_is_admission_authority'] is False
    assert ledger.read_bytes() == before and path.read_bytes() == snapshot


@pytest.mark.parametrize('fault', ['snapshot-hash', 'field-hash', 'record-hash', 'schema', 'roots',
    'nested-pointer', 'symlink', 'hardlink', 'fifo', 'oversize'])
def test_storage_disposition_refuses_unsafe_or_different_archive(setup, monkeypatch, fault):
    import hashlib
    ledger, call, _ = disposition_case(setup, monkeypatch)
    path = archive_disposition(ledger, call)
    data = json.loads(ledger.read_bytes())
    row = data['reservations'][call['reservation_id']]
    ref = row['explicit_reconciliation']
    if fault in {'snapshot-hash', 'field-hash', 'record-hash'}:
        key = {'snapshot-hash': 'snapshot_sha256', 'field-hash': 'original_field_sha256',
               'record-hash': 'original_record_sha256'}[fault]
        ref[key] = '0' * 64
    elif fault in {'schema', 'roots', 'nested-pointer'}:
        snapshot = json.loads(path.read_bytes())
        if fault == 'schema': snapshot['schema_version'] = 'foreign'
        elif fault == 'roots': snapshot['roots'] = []
        else:
            nested = snapshot['reservations'][call['reservation_id']]
            nested['explicit_reconciliation'] = dict(ref)
            ref['original_record_sha256'] = recovery._digest(nested)
            ref['original_field_sha256'] = recovery._digest(nested['explicit_reconciliation'])
        raw = json.dumps(snapshot).encode(); path.write_bytes(raw)
        ref['snapshot_sha256'] = hashlib.sha256(raw).hexdigest()
    elif fault == 'symlink':
        target = path.with_name('target.json'); path.rename(target); path.symlink_to(target)
    elif fault == 'hardlink': os.link(path, path.with_name('alias.json'))
    elif fault == 'fifo': path.unlink(); os.mkfifo(path)
    elif fault == 'oversize':
        with path.open('r+b') as stream: stream.truncate(16 * 1024 * 1024 + 1)
    ledger.write_text(json.dumps(data)); call['expected_record_sha256'] = recovery._digest(row)
    before = ledger.read_bytes()
    inspection_only(monkeypatch)
    with pytest.raises((recovery.resources.DaemonResourceError, OSError)):
        recovery.inspect_validation_disposition(ledger, **call)
    assert ledger.read_bytes() == before


@pytest.mark.parametrize('failed_filesystem', [False, True])
@pytest.mark.parametrize('scope', ['isolated_process_group_only', 'sampled_birth_bound_descendants'])
def test_storage_disposition_recognizes_selected_batch_history_only(setup, monkeypatch, failed_filesystem, scope):
    """Producer-shaped private history; no current native absence is asserted."""
    import hashlib
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_external_resource_recovery as failed
    ledger, call, _ = disposition_case(setup, monkeypatch, scope)
    data = json.loads(ledger.read_bytes()); row = data['reservations'][call['reservation_id']]
    selected = dict(reservation_id=call['reservation_id'],
        previous_record_sha256=call['expected_previous_record_sha256'], preserved_external_charges={})
    schema = 'explicit-retained-reservation-batch-reconciliation/v1'
    if failed_filesystem:
        document = failed.failed_filesystem_manifest(call['attempt_directory'])
        path = ledger.parent / 'failed-filesystem.json'
        raw = json.dumps(document, sort_keys=True, separators=(',', ':')).encode(); path.write_bytes(raw)
        pin = dict(path=str(path), bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())
        preserved = failed._failed_manifest(pin, call['attempt_directory'], call['roots'])
        schema = 'retained-failed-filesystem-batch-disposition/v1'
        selected.update(failed_filesystem_disposition=preserved,
            ordinary_artifact_durability_asserted=False, test_or_task_acceptance_asserted=False,
            native_absence=dict(current_policy_sha256='d' * 64, lease_id=row['native_lease_id'],
                request_id='validation:' + call['reservation_id'], status='absent',
                descendant_count=0, historical_release_established=False))
        row.update(artifacts_durable_asserted=False, final_attempt_bytes=preserved['apparent_bytes'],
            final_external_charged_bytes=0, final_total_charged_bytes=preserved['apparent_bytes'],
            attempt_exceeded_reservation=False)
    else:
        selected['artifacts'] = row['explicit_reconciliation']['artifacts']
    row['explicit_reconciliation'] = dict(schema=schema, selected_claim=selected, claim_count=1,
        batch_request_sha256='e' * 64, fresh_global_inventory_count=2,
        final_accounting_is_prewrite_projection=True, actual_postwrite_census_required=True,
        admitted=False, cap_changed=False, outputs_deleted=False)
    ledger.write_text(json.dumps(data)); call['expected_record_sha256'] = recovery._digest(row)
    before = ledger.read_bytes(); inspection_only(monkeypatch)
    result = recovery.inspect_validation_disposition(ledger, **call)
    assert result['storage_release_established'] is True
    assert result['release_evidence']['schema'] == schema
    assert result['native_release_established'] is result['admitted'] is False
    assert result['release_evidence']['test_or_task_acceptance_asserted'] is False
    assert ledger.read_bytes() == before


def test_storage_disposition_rechecks_row_after_original_binding_inspection(setup, monkeypatch):
    ledger, call, _ = disposition_case(setup, monkeypatch)
    original = recovery.inspect_validation_reservation
    observed = {}
    def concurrent_change(*args, **kwargs):
        report = original(*args, **kwargs)
        data = json.loads(ledger.read_bytes())
        data['reservations'][call['reservation_id']]['retention_reason'] = 'external fixture writer'
        ledger.write_text(json.dumps(data)); observed['bytes'] = ledger.read_bytes()
        return report
    monkeypatch.setattr(recovery, 'inspect_validation_reservation', concurrent_change)
    inspection_only(monkeypatch)
    with pytest.raises(recovery.resources.DaemonResourceError, match='between inspections'):
        recovery.inspect_validation_disposition(ledger, **call)
    assert ledger.read_bytes() == observed['bytes']


def test_storage_archive_parent_replacement_cannot_authenticate_history(setup, monkeypatch):
    ledger, call, _ = disposition_case(setup, monkeypatch)
    path = archive_disposition(ledger, call)
    real_open = recovery.os.open
    moved = path.parent.with_name('moved-private-test')
    changed = []
    def replace_after_open(name, flags, *args, **kwargs):
        descriptor = real_open(name, flags, *args, **kwargs)
        if name == path.parent.name and 'dir_fd' in kwargs and not changed:
            path.parent.rename(moved); path.parent.mkdir(); changed.append(True)
        return descriptor
    monkeypatch.setattr(recovery.os, 'open', replace_after_open)
    before = ledger.read_bytes(); inspection_only(monkeypatch)
    with pytest.raises(recovery.resources.DaemonResourceError, match='directory changed'):
        recovery.inspect_validation_disposition(ledger, **call)
    assert changed == [True] and ledger.read_bytes() == before


def retained(setup, monkeypatch):
    factory, roots, ledger, _ = setup
    attempt = roots[0] / 'failed'; attempt.mkdir()
    (attempt / 'failure.json').write_text('{"failed":true}\n')
    with factory() as owner:
        owner.check_usage(attempt)
    data = json.loads(ledger.read_bytes())
    record = data['reservations'][owner.reservation_id]
    # This test fixture emulates a deceased original owner without killing any process.
    record['owner_pid'] = 99999999
    ledger.write_text(json.dumps(data))
    args = dict(roots=roots, reservation_id=owner.reservation_id,
        expected_record_sha256=recovery._digest(record), attempt_directory=attempt,
        expected_artifacts=recovery._durable_inventory(attempt), artifacts_durable=True)
    return ledger, args, data


def test_recovery_releases_only_exact_dead_retained_claim_and_keeps_outputs(setup, monkeypatch):
    ledger, args, before = retained(setup, monkeypatch)
    factory, _, _, _ = setup
    with factory() as prior:
        pass
    previous = json.loads(ledger.read_bytes())['reservations'][prior.reservation_id]
    receipt = recovery.reconcile_retained_reservation(ledger, **args)
    after = json.loads(ledger.read_bytes())
    assert after['reservations'][prior.reservation_id] == previous
    row = after['reservations'][args['reservation_id']]
    assert row['status'] == 'released' and row['owner_pid'] == 99999999
    assert receipt['full_claim_accounting']['charged_bytes'] - receipt['final_accounting']['charged_bytes'] == row['storage_bytes']
    assert receipt['outputs_deleted'] is receipt['automatic_expiry'] is receipt['admitted'] is False
    assert receipt['schema'] == 'explicit-retained-reservation-reconciliation/v1'
    assert 'capacity_policy' not in receipt
    assert recovery._durable_inventory(args['attempt_directory']) == args['expected_artifacts']
    assert row['explicit_reconciliation'] == receipt
    with pytest.raises(recovery.resources.DaemonResourceError, match='identity changed'):
        recovery.reconcile_retained_reservation(ledger, **args)


@pytest.mark.parametrize('fault', ['live_owner', 'live_group', 'prior_live_group', 'wrong_record', 'wrong_artifact',
                                   'extra_artifact', 'wrong_inode', 'not_retained', 'external_charge', 'no_assertion'])
@pytest.mark.parametrize('capacity_policy', ['require_capacity', 'administrative_closeout'])
def test_recovery_refuses_ambiguous_or_changed_evidence(setup, monkeypatch, fault, capacity_policy):
    ledger, args, data = retained(setup, monkeypatch)
    row = data['reservations'][args['reservation_id']]
    if fault == 'live_owner': row['owner_pid'] = os.getpid()
    elif fault in {'live_group', 'prior_live_group'}:
        child = {'pid': 99999998, 'birth': '123'}
        if fault == 'live_group': row['child'] = child
        else: row['prior_children'] = [child]
        original = recovery.resources._group_usage
        monkeypatch.setattr(recovery.resources, '_group_usage', lambda c: {'live_processes': 1} if c == child else original(c))
    elif fault == 'wrong_record': args['expected_record_sha256'] = '0' * 64
    elif fault == 'wrong_artifact': args['expected_artifacts'][0]['sha256'] = '0' * 64
    elif fault == 'extra_artifact': (args['attempt_directory'] / 'extra').write_text('unlisted')
    elif fault == 'wrong_inode': row['attempt_directory']['inode'] += 1
    elif fault == 'not_retained': row['status'] = 'active'
    elif fault == 'external_charge': row['external_charges'] = {'external': 10}
    elif fault == 'no_assertion': args['artifacts_durable'] = False
    if fault != 'wrong_record': args['expected_record_sha256'] = recovery._digest(row)
    ledger.write_text(json.dumps(data)); unchanged = ledger.read_bytes()
    with pytest.raises(recovery.resources.DaemonResourceError):
        recovery.reconcile_retained_reservation(ledger, **args, capacity_policy=capacity_policy)
    assert ledger.read_bytes() == unchanged


def test_attempt_mutation_during_global_census_cannot_release_claim(setup, monkeypatch):
    ledger, args, _ = retained(setup, monkeypatch)
    original = recovery.resources.DaemonResourceReservation._account
    def mutate(helper, state, **kwargs):
        report = original(helper, state, **kwargs)
        (args['attempt_directory'] / 'failure.json').write_text('changed during census')
        return report
    monkeypatch.setattr(recovery.resources.DaemonResourceReservation, '_account', mutate)
    unchanged = ledger.read_bytes()
    with pytest.raises(recovery.resources.DaemonResourceError, match='changed during census'):
        recovery.reconcile_retained_reservation(ledger, **args)
    assert ledger.read_bytes() == unchanged


@pytest.mark.parametrize('alias', ['hardlink', 'symlink'])
@pytest.mark.parametrize('capacity_policy', ['require_capacity', 'administrative_closeout'])
def test_recovery_does_not_accept_aliased_artifact_inventory(setup, monkeypatch, alias, capacity_policy):
    ledger, args, _ = retained(setup, monkeypatch)
    source = args['attempt_directory'] / 'failure.json'
    target = args['attempt_directory'] / 'alias'
    if alias == 'hardlink': os.link(source, target)
    else: target.symlink_to(source)
    unchanged = ledger.read_bytes()
    with pytest.raises(recovery.resources.DaemonResourceError):
        recovery.reconcile_retained_reservation(ledger, **args, capacity_policy=capacity_policy)
    assert ledger.read_bytes() == unchanged


def observed_storage(setup, args, byte_count):
    """Use real small files inside test-local named roots, not fake accounting."""
    _, roots, _, _ = setup
    attempt_bytes = sum(row['bytes'] for row in args['expected_artifacts'])
    path = roots[1] / 'unrelated.bin'
    path.write_bytes(b'x' * (byte_count - attempt_bytes))
    return path


def foreign_claim(setup):
    factory, _, ledger, _ = setup
    with factory(storage_bytes=20_000) as prior:
        pass
    return prior.reservation_id, json.loads(ledger.read_bytes())['reservations'][prior.reservation_id]


def test_default_capacity_cutoff_remains_even_when_projected_release_would_fit(setup, monkeypatch):
    ledger, args, _ = retained(setup, monkeypatch)
    observed_storage(setup, args, 95_000)
    unchanged = ledger.read_bytes()
    with pytest.raises(recovery.resources.DaemonResourceError, match='capacity'):
        recovery.reconcile_retained_reservation(ledger, **args)
    assert ledger.read_bytes() == unchanged


@pytest.mark.parametrize('observed', [50_000, 95_000, 100_000, 110_000])
def test_explicit_administrative_census_reports_pre_and_projected_capacity(setup, monkeypatch, observed):
    ledger, args, before = retained(setup, monkeypatch)
    observed_storage(setup, args, observed)
    receipt = recovery.reconcile_retained_reservation(ledger, **args,
        capacity_policy='administrative_closeout')
    full, final = receipt['full_claim_accounting'], receipt['final_accounting']
    assert receipt['schema'] == 'explicit-retained-reservation-reconciliation/v2'
    assert receipt['capacity_policy'] == 'administrative_closeout'
    assert receipt['final_accounting_is_prewrite_projection'] is True
    assert receipt['actual_postwrite_census_required'] is True
    assert receipt['fresh_global_inventory_count'] == 2
    assert receipt['admitted'] is receipt['cap_changed'] is False
    assert receipt['new_reservation_created'] is receipt['new_resource_lease_acquired'] is False
    for accounting, expected_outstanding in [(full, 10_000), (final, 0)]:
        assert accounting['observed_apparent_bytes'] == observed
        assert accounting['outstanding_full_reservations_bytes'] == expected_outstanding
        assert accounting['additional_requested_bytes'] == 0
        assert accounting['charged_bytes'] == observed + expected_outstanding
        assert accounting['limit_bytes'] == 100_000
        assert accounting['over_limit_bytes'] == max(0, observed + expected_outstanding - 100_000)
        assert accounting['filesystem_free_shortfall_bytes'] == 0
        assert accounting['capacity_satisfied'] is (observed + expected_outstanding <= 100_000)
    after = json.loads(ledger.read_bytes())
    assert {key: value for key, value in after.items() if key != 'reservations'} == {
        key: value for key, value in before.items() if key != 'reservations'}
    assert after['reservations'][args['reservation_id']]['explicit_reconciliation'] == receipt


def test_administrative_closeout_preserves_foreign_claims_outputs_and_cap_above_capacity(setup, monkeypatch):
    ledger, args, _ = retained(setup, monkeypatch)
    prior_id, prior = foreign_claim(setup)
    observed_storage(setup, args, 110_000)
    before = json.loads(ledger.read_bytes())
    def forbidden(*args, **kwargs):
        raise AssertionError('administrative closeout must not enter or acquire a lease')
    monkeypatch.setattr(recovery.resources.DaemonResourceReservation, '__enter__', forbidden)
    _, _, _, scheduler = setup
    monkeypatch.setattr(scheduler, 'acquire', forbidden)
    scheduler_before = scheduler.snapshot()
    receipt = recovery.reconcile_retained_reservation(ledger, **args,
        capacity_policy='administrative_closeout')
    after = json.loads(ledger.read_bytes())
    assert after['reservations'][prior_id] == prior
    assert set(after['reservations']) == set(before['reservations'])
    assert after['limit_bytes'] == before['limit_bytes'] == 100_000
    assert after['roots'] == before['roots']
    assert receipt['full_claim_accounting']['outstanding_full_reservations_bytes'] == 30_000
    assert receipt['final_accounting']['outstanding_full_reservations_bytes'] == 20_000
    assert receipt['full_claim_accounting']['over_limit_bytes'] == 40_000
    assert receipt['final_accounting']['over_limit_bytes'] == 30_000
    assert receipt['outputs_deleted'] is receipt['automatic_expiry'] is False
    assert recovery._durable_inventory(args['attempt_directory']) == args['expected_artifacts']
    assert scheduler.snapshot() == scheduler_before


def test_new_admission_remains_refused_after_above_cap_administrative_closeout(setup, monkeypatch):
    ledger, args, _ = retained(setup, monkeypatch)
    observed_storage(setup, args, 110_000)
    recovery.reconcile_retained_reservation(ledger, **args, capacity_policy='administrative_closeout')
    unchanged = ledger.read_bytes()
    factory, _, _, scheduler = setup
    scheduler_before = scheduler.snapshot()
    with pytest.raises(recovery.resources.DaemonResourceError, match='capacity'):
        with factory(storage_bytes=1):
            pytest.fail('over-cap closeout must not authorize another reservation')
    assert ledger.read_bytes() == unchanged
    assert scheduler.snapshot() == scheduler_before


def test_administrative_closeout_reports_free_shortfall_without_allocating(setup, monkeypatch):
    ledger, args, _ = retained(setup, monkeypatch)
    prior_id, prior = foreign_claim(setup)
    monkeypatch.setattr(recovery.resources.shutil, 'disk_usage', lambda root: SimpleNamespace(free=0))
    receipt = recovery.reconcile_retained_reservation(ledger, **args,
        capacity_policy='administrative_closeout')
    assert receipt['full_claim_accounting']['filesystem_free_shortfall_bytes'] == 30_000
    assert receipt['final_accounting']['filesystem_free_shortfall_bytes'] == 20_000
    assert receipt['full_claim_accounting']['over_limit_bytes'] == 0
    assert receipt['final_accounting']['capacity_satisfied'] is False
    assert receipt['admitted'] is False
    assert json.loads(ledger.read_bytes())['reservations'][prior_id] == prior


@pytest.mark.parametrize('capacity_policy', [None, True, False, 1, '', 'relaxed', 'administrative_closeout '])
def test_invalid_policy_is_rejected_before_resource_helper_or_filesystem_access(monkeypatch, capacity_policy):
    def forbidden(*args, **kwargs):
        raise AssertionError('invalid policy must fail before any filesystem work')
    monkeypatch.setattr(recovery.resources, 'DaemonResourceReservation', forbidden)
    with pytest.raises(recovery.resources.DaemonResourceError, match='capacity policy'):
        recovery.reconcile_retained_reservation('/not-accessed/disk.json', roots=[],
            reservation_id='not-accessed', expected_record_sha256='not-accessed',
            attempt_directory='/not-accessed/attempt', expected_artifacts=[],
            capacity_policy=capacity_policy)


@pytest.mark.parametrize('census_number', [1, 2])
def test_administrative_closeout_refuses_attempt_mutation_during_either_census(setup, monkeypatch, census_number):
    ledger, args, _ = retained(setup, monkeypatch)
    original = recovery._administrative_census
    calls = 0
    def mutate(helper, state):
        nonlocal calls
        report = original(helper, state)
        calls += 1
        if calls == census_number:
            (args['attempt_directory'] / 'failure.json').write_text('changed during census')
        return report
    monkeypatch.setattr(recovery, '_administrative_census', mutate)
    unchanged = ledger.read_bytes()
    with pytest.raises(recovery.resources.DaemonResourceError, match='changed during'):
        recovery.reconcile_retained_reservation(ledger, **args, capacity_policy='administrative_closeout')
    assert ledger.read_bytes() == unchanged


@pytest.mark.parametrize('census_number', [1, 2])
def test_administrative_closeout_refuses_foreign_body_mutation_during_either_census(setup, monkeypatch, census_number):
    ledger, args, _ = retained(setup, monkeypatch)
    prior_id, _ = foreign_claim(setup)
    original = recovery._administrative_census
    calls = 0
    def mutate(helper, state):
        nonlocal calls
        report = original(helper, state)
        calls += 1
        if calls == census_number:
            state['reservations'][prior_id]['retention_reason'] = 'changed during census'
        return report
    monkeypatch.setattr(recovery, '_administrative_census', mutate)
    unchanged = ledger.read_bytes()
    with pytest.raises(recovery.resources.DaemonResourceError, match='reservation changed|accounting differs'):
        recovery.reconcile_retained_reservation(ledger, **args, capacity_policy='administrative_closeout')
    assert ledger.read_bytes() == unchanged


@pytest.mark.parametrize('census_number', [1, 2])
@pytest.mark.parametrize('field', ['storage_bytes', 'owner_pid', 'attempt_directory', 'retention_reason'])
def test_administrative_closeout_keeps_selected_record_bound_through_each_census(
        setup, monkeypatch, census_number, field):
    ledger, args, _ = retained(setup, monkeypatch)
    original = recovery._administrative_census
    calls = 0
    def mutate(helper, state):
        nonlocal calls
        report = original(helper, state)
        calls += 1
        if calls == census_number:
            row = state['reservations'][args['reservation_id']]
            if field in {'storage_bytes', 'owner_pid'}:
                row[field] += 1
            elif field == 'attempt_directory':
                row[field]['inode'] += 1
            else:
                row[field] = 'changed during census'
        return report
    monkeypatch.setattr(recovery, '_administrative_census', mutate)
    unchanged = ledger.read_bytes()
    with pytest.raises(recovery.resources.DaemonResourceError,
            match='reservation changed during census|accounting differs'):
        recovery.reconcile_retained_reservation(ledger, **args, capacity_policy='administrative_closeout')
    assert ledger.read_bytes() == unchanged


def test_administrative_closeout_refuses_selected_record_replacement_during_census(setup, monkeypatch):
    ledger, args, _ = retained(setup, monkeypatch)
    original = recovery._administrative_census
    def replace(helper, state):
        report = original(helper, state)
        state['reservations'][args['reservation_id']] = dict(state['reservations'][args['reservation_id']])
        return report
    monkeypatch.setattr(recovery, '_administrative_census', replace)
    unchanged = ledger.read_bytes()
    with pytest.raises(recovery.resources.DaemonResourceError, match='reservation changed during census'):
        recovery.reconcile_retained_reservation(ledger, **args, capacity_policy='administrative_closeout')
    assert ledger.read_bytes() == unchanged


def test_administrative_final_census_cannot_mutate_original_selected_record(setup, monkeypatch):
    ledger, args, _ = retained(setup, monkeypatch)
    original = recovery._administrative_census
    full_state = None
    def mutate(helper, state):
        nonlocal full_state
        report = original(helper, state)
        if full_state is None:
            full_state = state
        else:
            full_state['reservations'][args['reservation_id']]['storage_bytes'] += 1
        return report
    monkeypatch.setattr(recovery, '_administrative_census', mutate)
    unchanged = ledger.read_bytes()
    with pytest.raises(recovery.resources.DaemonResourceError, match='reservation changed during census'):
        recovery.reconcile_retained_reservation(ledger, **args, capacity_policy='administrative_closeout')
    assert ledger.read_bytes() == unchanged


@pytest.mark.parametrize('census_number', [1, 2])
@pytest.mark.parametrize('kind', ['owner', 'child', 'prior_child'])
def test_administrative_closeout_rechecks_process_absence_after_each_census(
        setup, monkeypatch, census_number, kind):
    ledger, args, data = retained(setup, monkeypatch)
    row = data['reservations'][args['reservation_id']]
    child = {'pid': 99999998, 'birth': '123'}
    if kind == 'child':
        row['child'] = child
    elif kind == 'prior_child':
        row['prior_children'] = [child]
    args['expected_record_sha256'] = recovery._digest(row)
    ledger.write_text(json.dumps(data))
    original_census = recovery._administrative_census
    original_process = recovery.resources._process
    original_group = recovery.resources._group_usage
    live = False
    calls = 0
    def observe(helper, state):
        nonlocal calls, live
        report = original_census(helper, state)
        calls += 1
        live = calls == census_number
        return report
    def process(pid):
        if kind == 'owner' and live and pid == row['owner_pid']:
            return {'pid': pid}
        return original_process(pid)
    def group(record):
        if kind != 'owner' and live and record == child:
            return {'available': True, 'live_processes': 1, 'rss_bytes': 0}
        return original_group(record)
    monkeypatch.setattr(recovery, '_administrative_census', observe)
    monkeypatch.setattr(recovery.resources, '_process', process)
    monkeypatch.setattr(recovery.resources, '_group_usage', group)
    unchanged = ledger.read_bytes()
    with pytest.raises(recovery.resources.DaemonResourceError, match='still exists|still alive'):
        recovery.reconcile_retained_reservation(ledger, **args, capacity_policy='administrative_closeout')
    assert ledger.read_bytes() == unchanged


def test_administrative_final_census_records_unrelated_apparent_growth(setup, monkeypatch):
    ledger, args, _ = retained(setup, monkeypatch)
    unrelated = observed_storage(setup, args, 20_000)
    original = recovery._administrative_census
    calls = 0
    def grow(helper, state):
        nonlocal calls
        report = original(helper, state)
        calls += 1
        if calls == 1:
            with unrelated.open('ab') as stream:
                stream.write(b'x' * 3_000)
        return report
    monkeypatch.setattr(recovery, '_administrative_census', grow)
    receipt = recovery.reconcile_retained_reservation(ledger, **args,
        capacity_policy='administrative_closeout')
    full, final = receipt['full_claim_accounting'], receipt['final_accounting']
    assert calls == 2
    assert full['observed_apparent_bytes'] == 20_000
    assert final['observed_apparent_bytes'] == 23_000
    assert full['outstanding_full_reservations_bytes'] - final['outstanding_full_reservations_bytes'] == 10_000
    assert full['charged_bytes'] - final['charged_bytes'] == 7_000


@pytest.mark.parametrize('capacity_policy', ['require_capacity', 'administrative_closeout'])
def test_durable_attempt_cannot_exceed_original_claim_in_either_policy(setup, monkeypatch, capacity_policy):
    ledger, args, _ = retained(setup, monkeypatch)
    (args['attempt_directory'] / 'failure.json').write_bytes(b'x' * 10_001)
    args['expected_artifacts'] = recovery._durable_inventory(args['attempt_directory'])
    unchanged = ledger.read_bytes()
    with pytest.raises(recovery.resources.DaemonResourceError, match='exceeds original reservation'):
        recovery.reconcile_retained_reservation(ledger, **args, capacity_policy=capacity_policy)
    assert ledger.read_bytes() == unchanged


@pytest.mark.parametrize('census_number', [1, 2])
def test_root_replacement_during_administrative_census_cannot_release_claim(setup, monkeypatch, census_number):
    ledger, args, _ = retained(setup, monkeypatch)
    original = recovery._administrative_census
    _, roots, _, _ = setup
    calls = 0
    def replace(helper, state):
        nonlocal calls
        report = original(helper, state)
        calls += 1
        if calls == census_number:
            roots[0].rename(roots[0].with_name('old-outputs'))
            roots[0].mkdir()
        return report
    monkeypatch.setattr(recovery, '_administrative_census', replace)
    unchanged = ledger.read_bytes()
    with pytest.raises(recovery.resources.DaemonResourceError):
        recovery.reconcile_retained_reservation(ledger, **args, capacity_policy='administrative_closeout')
    assert ledger.read_bytes() == unchanged


@pytest.mark.parametrize('write_completed', [False, True])
def test_administrative_atomic_write_error_is_not_rolled_back_or_retried(setup, monkeypatch, write_completed):
    ledger, args, _ = retained(setup, monkeypatch)
    original = recovery.resources.DaemonResourceReservation._write
    calls = 0
    def fail(helper, state):
        nonlocal calls
        calls += 1
        if write_completed:
            original(helper, state)
        raise OSError('primary atomic write failure')
    monkeypatch.setattr(recovery.resources.DaemonResourceReservation, '_write', fail)
    unchanged = ledger.read_bytes()
    with pytest.raises(OSError, match='primary atomic write failure'):
        recovery.reconcile_retained_reservation(ledger, **args, capacity_policy='administrative_closeout')
    assert calls == 1
    if write_completed:
        assert json.loads(ledger.read_bytes())['reservations'][args['reservation_id']]['status'] == 'released'
    else:
        assert ledger.read_bytes() == unchanged


# The opt-in manifest keeps full durability checks while bounding live metadata.
import hashlib


def inventory_manifest(args, path):
    body = dict(schema='retained-artifact-inventory/v1',
        attempt_directory=recovery.resources._root_identity(args['attempt_directory']),
        artifacts=args['expected_artifacts'])
    raw = (json.dumps(body, sort_keys=True, separators=(',', ':')) + '\n').encode()
    path.write_bytes(raw)
    return dict(path=str(path), bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())


def test_manifest_recovery_closes_large_inventory_without_raising_ledger_or_storage_caps(setup, monkeypatch):
    ledger, args, _ = retained(setup, monkeypatch)
    for index in range(40):
        (args['attempt_directory'] / (str(index).zfill(3) + '-' + 'receipt' * 20 + '.json')).write_text('{}\n')
    args['expected_artifacts'] = recovery._durable_inventory(args['attempt_directory'])
    _, roots, _, scheduler = setup
    manifest = inventory_manifest(args, roots[1] / 'complete-inventory.json')
    before = ledger.read_bytes()
    limit = len(before) + 4096
    monkeypatch.setattr(recovery.resources, 'MAX_LEDGER_BYTES', limit)
    with pytest.raises(recovery.resources.DaemonResourceError, match='ledger byte bound exceeded'):
        recovery.reconcile_retained_reservation(ledger, **args)
    assert ledger.read_bytes() == before
    scheduler_before = scheduler.snapshot()
    receipt = recovery.reconcile_retained_reservation(ledger, **args,
        artifact_inventory_manifest=manifest)
    assert receipt['schema'] == 'explicit-retained-reservation-reconciliation/v3'
    assert 'artifacts' not in receipt
    assert receipt['artifact_inventory_manifest'] == manifest
    assert receipt['artifact_manifest_schema'] == 'retained-artifact-inventory/v1'
    assert receipt['artifact_count'] == 41
    assert receipt['artifact_bytes'] == sum(row['bytes'] for row in args['expected_artifacts'])
    assert json.loads(Path(manifest['path']).read_bytes())['artifacts'] == args['expected_artifacts']
    after = json.loads(ledger.read_bytes())
    selected = after['reservations'][args['reservation_id']]
    assert selected['status'] == 'released' and selected['explicit_reconciliation'] == receipt
    assert len(ledger.read_bytes()) <= limit == recovery.resources.MAX_LEDGER_BYTES
    assert after['limit_bytes'] == 100_000 == recovery.resources.MAX_STORAGE_BYTES
    assert recovery._durable_inventory(args['attempt_directory']) == args['expected_artifacts']
    assert receipt['outputs_deleted'] is receipt['automatic_expiry'] is receipt['admitted'] is False
    assert scheduler.snapshot() == scheduler_before


@pytest.mark.parametrize('capacity_policy', ['require_capacity', 'administrative_closeout'],
                         ids=['ordinary-capacity', 'administrative-closeout'])
def test_manifest_recovery_retains_original_claim_accounting_and_other_reservations(setup, monkeypatch, capacity_policy):
    ledger, args, _ = retained(setup, monkeypatch)
    prior_id, previous = foreign_claim(setup)
    _, roots, _, scheduler = setup
    manifest = inventory_manifest(args, roots[1] / 'complete-inventory.json')
    before = json.loads(ledger.read_bytes()); scheduler_before = scheduler.snapshot()
    receipt = recovery.reconcile_retained_reservation(ledger, **args,
        capacity_policy=capacity_policy, artifact_inventory_manifest=manifest)
    after = json.loads(ledger.read_bytes())
    assert after['reservations'][prior_id] == previous
    assert set(after['reservations']) == set(before['reservations'])
    assert after['limit_bytes'] == before['limit_bytes']
    assert receipt['full_claim_accounting']['outstanding_full_reservations_bytes'] == 30_000
    assert receipt['final_accounting']['outstanding_full_reservations_bytes'] == 20_000
    if capacity_policy == 'administrative_closeout':
        assert receipt['capacity_policy'] == capacity_policy and receipt['cap_changed'] is False
        assert receipt['actual_postwrite_census_required'] is True
        assert receipt['fresh_global_inventory_count'] == 2
    assert scheduler.snapshot() == scheduler_before


@pytest.mark.parametrize('fault', ['extra-field', 'boolean-bytes', 'wrong-size', 'wrong-hash',
    'uppercase-hash', 'inside-attempt', 'outside-roots', 'wrong-inventory', 'duplicate-key'],
    ids=['extra-field', 'boolean-bytes', 'wrong-size', 'wrong-hash', 'uppercase-hash',
         'inside-attempt', 'outside-roots', 'wrong-inventory', 'duplicate-key'])
def test_manifest_recovery_refuses_ambiguous_or_incomplete_manifest(setup, monkeypatch, tmp_path, fault):
    ledger, args, _ = retained(setup, monkeypatch)
    _, roots, _, _ = setup
    manifest = inventory_manifest(args, roots[1] / 'complete-inventory.json')
    if fault == 'extra-field': manifest['grant'] = True
    elif fault == 'boolean-bytes': manifest['bytes'] = True
    elif fault == 'wrong-size': manifest['bytes'] += 1
    elif fault == 'wrong-hash': manifest['sha256'] = '0' * 64
    elif fault == 'uppercase-hash': manifest['sha256'] = 'A' * 64
    elif fault == 'inside-attempt':
        path = args['attempt_directory'] / 'failure.json'; raw = path.read_bytes()
        manifest = dict(path=str(path), bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())
    elif fault == 'outside-roots': manifest = inventory_manifest(args, tmp_path / 'outside-inventory.json')
    else:
        path = Path(manifest['path']); raw = path.read_bytes()
        if fault == 'wrong-inventory':
            value = json.loads(raw); value['artifacts'][0]['sha256'] = '0' * 64
            raw = json.dumps(value).encode()
        else: raw = b'{"schema":"retained-artifact-inventory/v1","schema":"duplicate"}'
        path.write_bytes(raw)
        manifest.update(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())
    unchanged = ledger.read_bytes()
    with pytest.raises(recovery.resources.DaemonResourceError, match='inventory manifest'):
        recovery.reconcile_retained_reservation(ledger, **args, artifact_inventory_manifest=manifest)
    assert ledger.read_bytes() == unchanged


@pytest.mark.parametrize('capacity_policy', ['require_capacity', 'administrative_closeout'],
                         ids=['ordinary-capacity', 'administrative-closeout'])
@pytest.mark.parametrize('mutation', ['different-bytes', 'equal-bytes-new-inode'],
                         ids=['different-bytes', 'equal-bytes-new-inode'])
def test_manifest_recovery_rechecks_durable_manifest_after_original_census(setup, monkeypatch,
        capacity_policy, mutation):
    ledger, args, _ = retained(setup, monkeypatch)
    _, roots, _, _ = setup
    manifest = inventory_manifest(args, roots[1] / 'complete-inventory.json')
    path = Path(manifest['path']); raw = path.read_bytes()
    name = '_account' if capacity_policy == 'require_capacity' else '_administrative_census'
    owner = recovery.resources.DaemonResourceReservation if name == '_account' else recovery
    original = getattr(owner, name); changed = False
    def mutate(*values, **kwargs):
        nonlocal changed
        result = original(*values, **kwargs)
        if not changed:
            changed = True
            if mutation == 'different-bytes': path.write_bytes(raw + b' ')
            else:
                replacement = path.with_suffix('.replacement'); replacement.write_bytes(raw)
                os.replace(replacement, path)
        return result
    monkeypatch.setattr(owner, name, mutate)
    unchanged = ledger.read_bytes()
    with pytest.raises(recovery.resources.DaemonResourceError, match='inventory manifest'):
        recovery.reconcile_retained_reservation(ledger, **args,
            capacity_policy=capacity_policy, artifact_inventory_manifest=manifest)
    assert ledger.read_bytes() == unchanged and changed


def test_manifest_recovery_preserves_default_capacity_refusal(setup, monkeypatch):
    ledger, args, _ = retained(setup, monkeypatch)
    _, roots, _, _ = setup
    manifest = inventory_manifest(args, roots[1] / 'complete-inventory.json')
    observed_storage(setup, args, 95_000)
    unchanged = ledger.read_bytes()
    with pytest.raises(recovery.resources.DaemonResourceError, match='capacity'):
        recovery.reconcile_retained_reservation(ledger, **args, artifact_inventory_manifest=manifest)
    assert ledger.read_bytes() == unchanged


@pytest.mark.parametrize('fault', ['live-owner', 'live-child', 'wrong-record', 'external-charge'],
                         ids=['live-owner', 'live-child', 'wrong-record', 'external-charge'])
def test_manifest_recovery_keeps_original_custody_and_record_gates(setup, monkeypatch, fault):
    ledger, args, data = retained(setup, monkeypatch)
    _, roots, _, _ = setup
    manifest = inventory_manifest(args, roots[1] / 'complete-inventory.json')
    row = data['reservations'][args['reservation_id']]
    if fault == 'live-owner': row['owner_pid'] = os.getpid()
    elif fault == 'live-child':
        child = dict(pid=99999998, birth='123');row['child'] = child
        original = recovery.resources._group_usage
        monkeypatch.setattr(recovery.resources, '_group_usage',
            lambda value: dict(live_processes=1) if value == child else original(value))
    elif fault == 'external-charge': row['external_charges'] = dict(external=10)
    args['expected_record_sha256'] = '0' * 64 if fault == 'wrong-record' else recovery._digest(row)
    ledger.write_text(json.dumps(data)); unchanged = ledger.read_bytes()
    with pytest.raises(recovery.resources.DaemonResourceError):
        recovery.reconcile_retained_reservation(ledger, **args, artifact_inventory_manifest=manifest)
    assert ledger.read_bytes() == unchanged
