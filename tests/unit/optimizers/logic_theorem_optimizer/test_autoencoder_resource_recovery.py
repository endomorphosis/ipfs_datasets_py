"""Explicit one-record recovery; original resource ownership is never adopted."""
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_resource_recovery as recovery
from tests.unit.optimizers.logic_theorem_optimizer.test_autoencoder_daemon_resources import setup


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


def _released_metadata_pin(path, value):
    """Create or rewrite test-local retained metadata, not an artifact payload."""
    import hashlib
    raw = (json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False) + '\n').encode()
    with path.open('wb') as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    path.chmod(0o600)
    descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    return {'path': str(path), 'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}


def released_relocation(setup, monkeypatch, kind='batch'):
    """Private metadata-protocol fixtures, with safely absent selected PIDs.

    Original closeout APIs create the ordinary/batch receipt shapes, but the
    synthetic native fields below do not qualify host, model or legal outcomes.
    """
    _, roots, _, _ = setup
    if kind == 'batch':
        for name in ('third-root', 'fourth-root'):
            path = roots[0].parent / name
            path.mkdir()
            roots.append(path)
    ledger, old_args, _ = retained(setup, monkeypatch)
    for index in range(24):
        (old_args['attempt_directory'] / ('item-%02d.json' % index)).write_text('{}\n')
    old_args['expected_artifacts'] = recovery._durable_inventory(old_args['attempt_directory'])
    if kind == 'batch':
        from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_external_resource_recovery
        claim = {key: old_args[key] for key in ('reservation_id', 'expected_record_sha256',
                                               'attempt_directory', 'expected_artifacts')}
        claim['attempt_directory'] = str(claim['attempt_directory'])
        claim.update(allow_empty_failed_admission=False,
                     conservative_named_roots_external_disposition=None)
        autoencoder_external_resource_recovery.reconcile_retained_reservations_batch(
            ledger, roots=roots, claims=[claim], artifacts_durable=True)
    else:
        recovery.reconcile_retained_reservation(ledger, **old_args,
            capacity_policy='administrative_closeout' if kind == 'ordinary-v2' else 'require_capacity')
    state = json.loads(ledger.read_bytes())
    row = state['reservations'][old_args['reservation_id']]
    # Literal historical custody stays opaque: relocation may neither infer nor
    # resolve UNKNOWN, or change null, boolean, integer and finite-float values.
    row['retained_native_outcome'] = {'provider_outcome': 'UNKNOWN', 'native_lease_id': None,
        'provider_completed': False, 'native_disposition_known': True,
        'attempt_number': 1, 'finite_value': 1.0}
    ledger.write_text(json.dumps(state, sort_keys=True, separators=(',', ':')) + '\n')
    archive = _released_metadata_pin(roots[1] / 'released-original-row.json', row)
    manifest = _released_metadata_pin(roots[1] / 'retained-artifacts.json', {
        'schema': 'retained-artifact-inventory/v1', 'attempt_directory': row['attempt_directory'],
        'artifacts': old_args['expected_artifacts']})
    args = dict(roots=roots, reservation_id=row['reservation_id'],
        expected_record_sha256=recovery._digest(row),
        artifact_inventory_manifest=manifest, released_record_archive=archive)
    return ledger, args, state


@pytest.mark.parametrize('kind', ['ordinary-v1', 'ordinary-v2', 'batch'])
def test_released_artifact_externalization_preserves_complete_history_and_never_releases_resources(
        setup, monkeypatch, kind):
    import copy
    ledger, args, before = released_relocation(setup, monkeypatch, kind)
    factory, _, _, scheduler = setup
    with factory() as other:
        pass
    before = json.loads(ledger.read_bytes())
    scheduler_before = scheduler.snapshot()
    def forbidden(*unused, **keywords):
        raise AssertionError('metadata relocation cannot census, acquire or enter')
    monkeypatch.setattr(recovery.resources, '_inventory', forbidden)
    monkeypatch.setattr(recovery, '_durable_inventory', forbidden)
    monkeypatch.setattr(recovery, '_administrative_census', forbidden)
    monkeypatch.setattr(recovery.resources, 'get_global_resource_scheduler', forbidden)
    monkeypatch.setattr(recovery.resources.DaemonResourceReservation, '__enter__', forbidden)
    monkeypatch.setattr(recovery.resources.DaemonResourceReservation, '_account', forbidden)
    result = recovery.externalize_released_reconciliation_artifacts_v1(ledger, **args)
    after = json.loads(ledger.read_bytes())
    rid = args['reservation_id']
    old, new = before['reservations'][rid], after['reservations'][rid]
    assert recovery._digest({k: v for k, v in old.items() if k != 'explicit_reconciliation'}) == recovery._digest(
        {k: v for k, v in new.items() if k != 'explicit_reconciliation'})
    expected = copy.deepcopy(old['explicit_reconciliation'])
    target = expected['selected_claim'] if kind == 'batch' else expected
    artifacts = target.pop('artifacts')
    target.update(artifact_inventory_manifest=args['artifact_inventory_manifest'], artifact_count=len(artifacts),
                  artifact_bytes=sum(row['bytes'] for row in artifacts),
                  artifact_manifest_schema='retained-artifact-inventory/v1')
    expected['schema'] = ('explicit-retained-reservation-batch-reconciliation/v2' if kind == 'batch'
                          else 'explicit-retained-reservation-reconciliation/v3')
    expected['artifact_metadata_relocation'] = new['explicit_reconciliation']['artifact_metadata_relocation']
    assert recovery._digest(new['explicit_reconciliation']) == recovery._digest(expected)
    assert recovery._digest(json.loads(Path(args['released_record_archive']['path']).read_bytes())) == recovery._digest(old)
    assert recovery._digest({k: v for k, v in after['reservations'].items() if k != rid}) == recovery._digest(
        {k: v for k, v in before['reservations'].items() if k != rid})
    assert {k: v for k, v in after.items() if k != 'reservations'} == {
        k: v for k, v in before.items() if k != 'reservations'}
    assert result['state_written'] is True and result['atomic_ledger_write_count'] == 1
    assert result['hot_ledger_metadata_bytes_removed'] > 0
    assert result['current_process_absence_observed_only'] is True
    assert result['ledger_bytes_after'] < result['ledger_bytes_before']
    assert result['disk_promises_released'] == 0
    for field in ('global_census_performed', 'status_changed', 'new_reservation_created',
                  'new_resource_lease_acquired', 'native_cleanup_performed',
                  'historical_native_release_established', 'qualification_claimed', 'admitted',
                  'outputs_deleted', 'cap_changed'):
        assert result[field] is False
    assert scheduler.snapshot() == scheduler_before


def test_released_artifact_externalization_same_refs_are_read_only_and_changed_refs_refuse(setup, monkeypatch):
    ledger, args, before = released_relocation(setup, monkeypatch)
    first = recovery.externalize_released_reconciliation_artifacts_v1(ledger, **args)
    raw = ledger.read_bytes()
    def forbidden(*unused, **keywords):
        raise AssertionError('idempotent readback must not write')
    monkeypatch.setattr(recovery.resources.DaemonResourceReservation, '_write', forbidden)
    again = recovery.externalize_released_reconciliation_artifacts_v1(ledger, **args)
    assert ledger.read_bytes() == raw and again['state_written'] is False
    assert again['idempotent_readback'] is True and again['atomic_ledger_write_count'] == 0
    assert again['current_record_sha256'] == first['current_record_sha256']
    assert again['relocated_at'] == first['relocated_at']
    manifest = json.loads(Path(args['artifact_inventory_manifest']['path']).read_bytes())
    args['artifact_inventory_manifest'] = _released_metadata_pin(
        Path(args['artifact_inventory_manifest']['path']).with_name('different-identical-manifest.json'), manifest)
    with pytest.raises(recovery.resources.DaemonResourceError, match='references changed'):
        recovery.externalize_released_reconciliation_artifacts_v1(ledger, **args)
    assert ledger.read_bytes() == raw


@pytest.mark.parametrize('status', ['active', 'retained', 'reserved'])
def test_released_artifact_externalization_never_accepts_charged_rows(setup, monkeypatch, status):
    ledger, args, state = released_relocation(setup, monkeypatch)
    state['reservations'][args['reservation_id']]['status'] = status
    ledger.write_text(json.dumps(state))
    before = ledger.read_bytes()
    with pytest.raises(recovery.resources.DaemonResourceError, match='only durable released'):
        recovery.externalize_released_reconciliation_artifacts_v1(ledger, **args)
    assert ledger.read_bytes() == before


@pytest.mark.parametrize('damage', ['float-cap', 'float-root-inode'])
def test_released_artifact_externalization_refuses_typed_storage_scope_drift(setup, monkeypatch, damage):
    ledger, args, state = released_relocation(setup, monkeypatch)
    if damage == 'float-cap': state['limit_bytes'] = float(state['limit_bytes'])
    else: state['roots'][0]['inode'] = float(state['roots'][0]['inode'])
    ledger.write_text(json.dumps(state))
    before = ledger.read_bytes()
    with pytest.raises(recovery.resources.DaemonResourceError, match='typed original ledger roots and cap'):
        recovery.externalize_released_reconciliation_artifacts_v1(ledger, **args)
    assert ledger.read_bytes() == before


@pytest.mark.parametrize('kind', ['owner', 'child', 'prior-child'])
def test_released_artifact_externalization_refuses_live_original_custody(setup, monkeypatch, kind):
    ledger, args, state = released_relocation(setup, monkeypatch)
    row = state['reservations'][args['reservation_id']]
    group = {'pid': 99999998, 'birth': '123'}
    if kind != 'owner':
        if kind == 'child': row['child'] = group
        else: row['prior_children'] = [group]
        ledger.write_text(json.dumps(state))
        args['released_record_archive'] = _released_metadata_pin(
            Path(args['released_record_archive']['path']), row)
        args['expected_record_sha256'] = recovery._digest(row)
        original = recovery.resources._group_usage
        monkeypatch.setattr(recovery.resources, '_group_usage',
            lambda child: {'live_processes': 1} if child == group else original(child))
    else:
        original = recovery.resources._process
        monkeypatch.setattr(recovery.resources, '_process',
            lambda pid: {'pid': pid} if pid == row['owner_pid'] else original(pid))
    before = ledger.read_bytes()
    with pytest.raises(recovery.resources.DaemonResourceError, match='still exists|still alive'):
        recovery.externalize_released_reconciliation_artifacts_v1(ledger, **args)
    assert ledger.read_bytes() == before


def test_released_artifact_externalization_rechecks_owner_absence_before_write(setup, monkeypatch):
    ledger, args, state = released_relocation(setup, monkeypatch)
    owner_pid = state['reservations'][args['reservation_id']]['owner_pid']
    original_read = recovery._released_artifact_reference
    original_process = recovery.resources._process
    alive = False
    def read(reference, helper, attempt):
        nonlocal alive
        value = original_read(reference, helper, attempt)
        alive = True
        return value
    monkeypatch.setattr(recovery, '_released_artifact_reference', read)
    monkeypatch.setattr(recovery.resources, '_process',
        lambda pid: {'pid': pid} if alive and pid == owner_pid else original_process(pid))
    before = ledger.read_bytes()
    with pytest.raises(recovery.resources.DaemonResourceError, match='owner PID still exists'):
        recovery.externalize_released_reconciliation_artifacts_v1(ledger, **args)
    assert alive and ledger.read_bytes() == before


@pytest.mark.parametrize('field,replacement', [
    ('provider_completed', 0), ('native_disposition_known', 1),
    ('attempt_number', 1.0), ('finite_value', 1), ('native_lease_id', False)])
def test_released_artifact_externalization_refuses_typed_archive_drift(setup, monkeypatch, field, replacement):
    ledger, args, state = released_relocation(setup, monkeypatch)
    archive = json.loads(Path(args['released_record_archive']['path']).read_bytes())
    archive['retained_native_outcome'][field] = replacement
    args['released_record_archive'] = _released_metadata_pin(Path(args['released_record_archive']['path']), archive)
    before = ledger.read_bytes()
    with pytest.raises(recovery.resources.DaemonResourceError, match='archive digest differs'):
        recovery.externalize_released_reconciliation_artifacts_v1(ledger, **args)
    assert ledger.read_bytes() == before


@pytest.mark.parametrize('damage', ['manifest-hash', 'archive-hash', 'missing-archive', 'wrong-task',
    'wrong-attempt', 'missing-artifact', 'reordered-artifacts', 'boolean-artifact-bytes',
    'duplicate-artifact', 'archive-missing-receipt', 'descriptor-boolean-bytes'])
def test_released_artifact_externalization_refuses_incomplete_or_wrong_evidence(setup, monkeypatch, damage):
    ledger, args, state = released_relocation(setup, monkeypatch)
    manifest_path, archive_path = (Path(args[key]['path']) for key in
        ('artifact_inventory_manifest', 'released_record_archive'))
    manifest = json.loads(manifest_path.read_bytes())
    archive = json.loads(archive_path.read_bytes())
    if damage == 'manifest-hash': args['artifact_inventory_manifest']['sha256'] = '0' * 64
    elif damage == 'archive-hash': args['released_record_archive']['sha256'] = '0' * 64
    elif damage == 'missing-archive': archive_path.unlink()
    elif damage == 'wrong-task': archive['reservation_id'] = 'f' * 32
    elif damage == 'wrong-attempt': manifest['attempt_directory']['inode'] += 1
    elif damage == 'missing-artifact': manifest['artifacts'].pop()
    elif damage == 'reordered-artifacts': manifest['artifacts'].reverse()
    elif damage == 'boolean-artifact-bytes': manifest['artifacts'][0]['bytes'] = False
    elif damage == 'duplicate-artifact': manifest['artifacts'].append(manifest['artifacts'][0])
    elif damage == 'archive-missing-receipt': archive.pop('explicit_reconciliation')
    elif damage == 'descriptor-boolean-bytes': args['artifact_inventory_manifest']['bytes'] = True
    if damage in ('wrong-task', 'archive-missing-receipt'):
        args['released_record_archive'] = _released_metadata_pin(archive_path, archive)
    if damage in ('wrong-attempt', 'missing-artifact', 'reordered-artifacts',
                  'boolean-artifact-bytes', 'duplicate-artifact'):
        args['artifact_inventory_manifest'] = _released_metadata_pin(manifest_path, manifest)
    before = ledger.read_bytes()
    with pytest.raises(recovery.resources.DaemonResourceError):
        recovery.externalize_released_reconciliation_artifacts_v1(ledger, **args)
    assert ledger.read_bytes() == before


@pytest.mark.parametrize('key', ['artifact_inventory_manifest', 'released_record_archive'])
@pytest.mark.parametrize('alias', ['hardlink', 'symlink', 'traversal', 'outside-roots'])
def test_released_artifact_externalization_refuses_aliased_or_unowned_locations(setup, monkeypatch, key, alias):
    ledger, args, state = released_relocation(setup, monkeypatch)
    source = Path(args[key]['path'])
    created_alias = None
    try:
        if alias == 'hardlink':
            target = source.with_suffix('.alias')
            os.link(source, target)
            created_alias = target
        elif alias == 'symlink':
            target = source.with_suffix('.symlink')
            target.symlink_to(source)
            created_alias = target
            args[key]['path'] = str(target)
        elif alias == 'traversal': args[key]['path'] = str(source.parent) + '/sub/../' + source.name
        else:
            outside = source.parent.parent / ('outside-' + source.name)
            args[key] = _released_metadata_pin(outside, json.loads(source.read_bytes()))
        before = ledger.read_bytes()
        with pytest.raises(recovery.resources.DaemonResourceError):
            recovery.externalize_released_reconciliation_artifacts_v1(ledger, **args)
        assert ledger.read_bytes() == before
    finally:
        # Authored teardown of only this test's link, after its refusal checks.
        if created_alias is not None:
            created_alias.unlink()
            assert not os.path.lexists(created_alias)
            assert source.stat().st_nlink == 1


@pytest.mark.parametrize('key', ['artifact_inventory_manifest', 'released_record_archive'])
def test_released_artifact_externalization_rechecks_metadata_before_atomic_write(setup, monkeypatch, key):
    ledger, args, state = released_relocation(setup, monkeypatch)
    original = recovery._released_artifact_reference
    changed = False
    def mutate(reference, helper, attempt):
        nonlocal changed
        value = original(reference, helper, attempt)
        if not changed and reference['path'] == args[key]['path']:
            changed = True
            with Path(reference['path']).open('ab') as stream:
                stream.write(b' ')
        return value
    monkeypatch.setattr(recovery, '_released_artifact_reference', mutate)
    before = ledger.read_bytes()
    with pytest.raises(recovery.resources.DaemonResourceError):
        recovery.externalize_released_reconciliation_artifacts_v1(ledger, **args)
    assert changed and ledger.read_bytes() == before


def test_released_artifact_externalization_checks_actual_disk_cas_not_only_loaded_row(setup, monkeypatch):
    ledger, args, state = released_relocation(setup, monkeypatch)
    original = recovery._released_artifact_reference
    changed = False
    def mutate(reference, helper, attempt):
        nonlocal changed
        value = original(reference, helper, attempt)
        if not changed:
            changed = True
            other_writer = json.loads(ledger.read_bytes())
            other_writer['reservations'][args['reservation_id']]['owner_pid'] += 1
            ledger.write_text(json.dumps(other_writer))
        return value
    monkeypatch.setattr(recovery, '_released_artifact_reference', mutate)
    writes = []
    monkeypatch.setattr(recovery.resources.DaemonResourceReservation, '_write', lambda *a: writes.append(a))
    with pytest.raises(recovery.resources.DaemonResourceError, match='on-disk.*changed'):
        recovery.externalize_released_reconciliation_artifacts_v1(ledger, **args)
    assert changed and writes == []
    assert 'artifacts' in json.loads(ledger.read_bytes())['reservations'][args['reservation_id']][
        'explicit_reconciliation']['selected_claim']


@pytest.mark.parametrize('write_completed', [False, True])
def test_released_artifact_externalization_write_error_is_not_retried_or_rolled_back(
        setup, monkeypatch, write_completed):
    ledger, args, state = released_relocation(setup, monkeypatch)
    original = recovery.resources.DaemonResourceReservation._write
    writes = []
    def fail(helper, value):
        writes.append(value)
        if write_completed:
            original(helper, value)
        raise OSError('selected original atomic write failed')
    monkeypatch.setattr(recovery.resources.DaemonResourceReservation, '_write', fail)
    before = ledger.read_bytes()
    with pytest.raises(OSError, match='atomic write failed'):
        recovery.externalize_released_reconciliation_artifacts_v1(ledger, **args)
    assert len(writes) == 1
    if not write_completed:
        assert ledger.read_bytes() == before
    else:
        assert json.loads(ledger.read_bytes())['reservations'][args['reservation_id']][
            'explicit_reconciliation']['schema'] == 'explicit-retained-reservation-batch-reconciliation/v2'
        again = recovery.externalize_released_reconciliation_artifacts_v1(ledger, **args)
        assert again['idempotent_readback'] is True and len(writes) == 1
