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
    try:
        unchanged = ledger.read_bytes()
        with pytest.raises(recovery.resources.DaemonResourceError):
            recovery.reconcile_retained_reservation(ledger, **args, capacity_policy=capacity_policy)
        assert ledger.read_bytes() == unchanged
    finally:
        # This alias was created by this test; retain the source and refusal evidence.
        target.unlink()
        assert source.stat().st_nlink == 1


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


@pytest.mark.parametrize('empty_failed_admission', [False, True],
    ids=['retained-artifact', 'empty-failed-admission'])
@pytest.mark.parametrize('expire_census', [False, True], ids=['nonexpired', 'expired-census'])
def test_recovery_census_cannot_commit_after_cleanup_deadline(
        setup, monkeypatch, empty_failed_admission, expire_census):
    ledger, args, _ = retained(setup, monkeypatch)
    prior_id, prior = foreign_claim(setup)
    if empty_failed_admission:
        # Fictional producer-shaped unit fixture for the pre-open H failure;
        # this does not adopt any real retained claim or native lifecycle.
        (args['attempt_directory'] / 'failure.json').unlink()
        data = json.loads(ledger.read_bytes())
        row = data['reservations'][args['reservation_id']]
        row.update(retention_reason='scheduler_admission_failed',
            scheduler_lane='validation', workload='canonical_validation',
            child=None, prior_children=[], artifacts_durable_asserted=False)
        assert set(row) == set('artifacts_durable_asserted attempt_directory child '
            'child_process_slots cpu_slots created_at external_charges last_usage '
            'memory_mb owner_pid prior_children reservation_id retention_reason '
            'scheduler_lane status storage_bytes workload'.split())
        ledger.write_text(json.dumps(data))
        args.update(expected_record_sha256=recovery._digest(row),
            expected_artifacts=[], allow_empty_failed_admission=True)
    unchanged = ledger.read_bytes()
    before = json.loads(unchanged)
    native = recovery.resources.native_deadlines
    clock = [0.0]
    census_calls, write_attempts, write_commits = [], [], []
    original_account = recovery.resources.DaemonResourceReservation._account
    original_write = recovery.resources.DaemonResourceReservation._write

    def census_crosses_deadline(helper, state, **kwargs):
        report = original_account(helper, state, **kwargs)
        census_calls.append(True)
        clock[0] = 241.0 if expire_census else 239.0
        return report

    def observe_original_write(helper, state):
        write_attempts.append(state['reservations'][args['reservation_id']]['status'])
        result = original_write(helper, state)
        write_commits.append(state['reservations'][args['reservation_id']]['status'])
        return result

    # Fixtures finish before the clock shim; shared stdlib time stays real.
    monkeypatch.setattr(native, 'time', SimpleNamespace(monotonic=lambda: clock[0]))
    monkeypatch.setattr(recovery.resources.DaemonResourceReservation, '_account', census_crosses_deadline)
    monkeypatch.setattr(recovery.resources.DaemonResourceReservation, '_write', observe_original_write)
    deadline_error = receipt = None
    try:
        with native.resource_cleanup_deadline(native_deadline_monotonic=240.0):
            receipt = recovery.reconcile_retained_reservation(ledger, **args)
    except native.ResourceAdmissionDeadlineError as error:
        deadline_error = error
    actual = ledger.read_bytes()
    after = json.loads(actual)
    selected = after['reservations'][args['reservation_id']]
    diagnostic = dict(empty_failed_admission=empty_failed_admission,
        expire_census=expire_census, clock=clock[0], selected_status=selected['status'],
        census_count=len(census_calls), write_attempts=write_attempts,
        write_commits=write_commits, ledger_changed=actual != unchanged,
        foreign_changed=after['reservations'][prior_id] != prior,
        deadline_error=None if deadline_error is None else type(deadline_error).__name__)
    assert census_calls == [True], diagnostic
    assert after['reservations'][prior_id] == prior, diagnostic
    assert set(after['reservations']) == set(before['reservations']), diagnostic
    assert after['roots'] == before['roots'] and after['limit_bytes'] == before['limit_bytes'], diagnostic
    if expire_census:
        assert deadline_error is not None, diagnostic
        assert actual == unchanged, diagnostic
        assert selected == before['reservations'][args['reservation_id']], diagnostic
        assert write_commits == [], diagnostic
    else:
        assert deadline_error is None, diagnostic
        assert selected['status'] == 'released' and write_commits == ['released'], diagnostic
        assert receipt['schema'] == 'explicit-retained-reservation-reconciliation/v1', diagnostic
        assert 'capacity_policy' not in receipt, diagnostic
        assert receipt['outputs_deleted'] is receipt['automatic_expiry'] is receipt['admitted'] is False
        assert recovery._durable_inventory(args['attempt_directory']) == args['expected_artifacts']


@pytest.mark.parametrize('empty_failed_admission', [False, True],
    ids=['retained-artifact', 'empty-failed-admission'])
@pytest.mark.parametrize('expire_fsync', [False, True], ids=['nonexpired', 'expired-temp-fsync'])
def test_recovery_cannot_replace_ledger_after_temporary_file_fsync_deadline(
        setup, monkeypatch, empty_failed_admission, expire_fsync):
    ledger, args, _ = retained(setup, monkeypatch)
    prior_id, prior = foreign_claim(setup)
    if empty_failed_admission:
        # Fictional producer-shaped unit fixture; no real claim is adopted.
        (args['attempt_directory'] / 'failure.json').unlink()
        data = json.loads(ledger.read_bytes())
        row = data['reservations'][args['reservation_id']]
        row.update(retention_reason='scheduler_admission_failed',
            scheduler_lane='validation', workload='canonical_validation',
            child=None, prior_children=[], artifacts_durable_asserted=False)
        assert set(row) == set('artifacts_durable_asserted attempt_directory child '
            'child_process_slots cpu_slots created_at external_charges last_usage '
            'memory_mb owner_pid prior_children reservation_id retention_reason '
            'scheduler_lane status storage_bytes workload'.split())
        ledger.write_text(json.dumps(data))
        args.update(expected_record_sha256=recovery._digest(row),
            expected_artifacts=[], allow_empty_failed_admission=True)
    unchanged = ledger.read_bytes()
    before = json.loads(unchanged)
    native = recovery.resources.native_deadlines
    real_os, real_tempfile = recovery.resources.os, recovery.resources.tempfile
    clock, temporary, temporary_fsyncs, replacements = [239.0], {}, [], []

    def observe_temporary_file(*positional, **keywords):
        stream = real_tempfile.NamedTemporaryFile(*positional, **keywords)
        info = real_os.fstat(stream.fileno())
        temporary.update(path=Path(stream.name), identity=(info.st_dev, info.st_ino))
        return stream

    def expire_after_real_temporary_fsync(descriptor):
        result = real_os.fsync(descriptor)
        info = real_os.fstat(descriptor)
        if (info.st_dev, info.st_ino) == temporary.get('identity'):
            temporary_fsyncs.append(True)
            clock[0] = 241.0 if expire_fsync else 239.0
        return result

    def observe_original_replace(source, destination):
        replacements.append((Path(source), Path(destination), clock[0]))
        return real_os.replace(source, destination)

    # Bind only the owning modules; shared stdlib clock/fsync/replace stay real.
    monkeypatch.setattr(native, 'time', SimpleNamespace(monotonic=lambda: clock[0]))
    monkeypatch.setattr(recovery.resources, 'tempfile',
        SimpleNamespace(NamedTemporaryFile=observe_temporary_file))
    monkeypatch.setattr(recovery.resources, 'os', SimpleNamespace(**{
        **vars(real_os), 'fsync': expire_after_real_temporary_fsync,
        'replace': observe_original_replace}))
    deadline_error = receipt = None
    try:
        with native.resource_cleanup_deadline(native_deadline_monotonic=240.0):
            receipt = recovery.reconcile_retained_reservation(ledger, **args)
    except native.ResourceAdmissionDeadlineError as error:
        deadline_error = error
    actual = ledger.read_bytes()
    after = json.loads(actual)
    selected = after['reservations'][args['reservation_id']]
    diagnostic = dict(empty_failed_admission=empty_failed_admission,
        expire_fsync=expire_fsync, clock=clock[0], temporary_fsyncs=temporary_fsyncs,
        replace_count=len(replacements), selected_status=selected['status'],
        ledger_changed=actual != unchanged, foreign_changed=after['reservations'][prior_id] != prior,
        deadline_error=None if deadline_error is None else type(deadline_error).__name__)
    assert temporary_fsyncs == [True], diagnostic
    assert 'path' in temporary and not temporary['path'].exists(), diagnostic
    assert after['reservations'][prior_id] == prior, diagnostic
    assert set(after['reservations']) == set(before['reservations']), diagnostic
    assert after['roots'] == before['roots'] and after['limit_bytes'] == before['limit_bytes'], diagnostic
    if expire_fsync:
        assert deadline_error is not None, diagnostic
        assert replacements == [], diagnostic
        assert actual == unchanged, diagnostic
        assert selected == before['reservations'][args['reservation_id']], diagnostic
    else:
        assert deadline_error is None and len(replacements) == 1, diagnostic
        assert replacements[0][1] == ledger and replacements[0][2] == 239.0, diagnostic
        assert selected['status'] == 'released', diagnostic
        assert receipt['schema'] == 'explicit-retained-reservation-reconciliation/v1', diagnostic
        assert 'capacity_policy' not in receipt, diagnostic
        assert receipt['outputs_deleted'] is receipt['automatic_expiry'] is receipt['admitted'] is False
        assert recovery._durable_inventory(args['attempt_directory']) == args['expected_artifacts']



# Explicit fictional recorded custody. These controls inspect real private JSON
# files and locks; they create no scheduler/native grant or process observation.
def _validation_inspection_scope_fixture(tmp_path, recorded_scope):
    root = tmp_path / "inspection-root"
    root.mkdir()
    attempt = root / "attempt"
    attempt.mkdir()
    ledger = tmp_path / "inspection-ledger.json"
    lock = ledger.with_name(ledger.name + ".lock")
    lock.write_bytes(b"existing private inspection lock\n")
    scheduler = tmp_path / "scheduler-must-remain-absent.json"
    reservation_id, request_pin = "1" * 32, "2" * 64
    row = {
        "reservation_id": reservation_id, "status": "retained", "storage_bytes": 1,
        "owner_pid": os.getpid(), "owner_birth": "5", "external_charges": {},
        "scheduler_lane": "validation", "workload": "canonical_validation",
        "validation_request_sha256": request_pin,
        "attempt_directory": recovery.resources._root_identity(attempt),
        "native_lease_id": "3" * 32, "scheduler_policy_sha256": "4" * 64,
        "scheduler_state_path": str(scheduler), "process_scope": recorded_scope,
        "outputs": {name: str(attempt / name) for name in
                    ("pytest", "tmp", "cache", "db", "exports", "logs")},
        "artifacts_durable_asserted": False, "child": None, "prior_children": [],
    }
    foreign_id = "f" * 32
    foreign = {"reservation_id": foreign_id, "status": "retained", "storage_bytes": 7,
               "owner_pid": os.getpid(), "external_charges": {}}
    value = {"schema": recovery.resources.SCHEMA,
             "roots": [recovery.resources._root_identity(root)],
             "limit_bytes": recovery.resources.MAX_STORAGE_BYTES,
             "reservations": {reservation_id: row, foreign_id: foreign}}
    ledger.write_text(json.dumps(value, sort_keys=True))
    args = dict(roots=[root], reservation_id=reservation_id,
                expected_request_sha256=request_pin, attempt_directory=attempt)
    return ledger, lock, scheduler, args, value


def _forbid_validation_inspection_side_effects(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("record inspection cannot admit, write or sample processes")
    owner = recovery.resources.DaemonResourceReservation
    for name in ("__enter__", "_acquire_native_lease", "_write"):
        monkeypatch.setattr(owner, name, forbidden)
    monkeypatch.setattr(recovery.resources, "_process", forbidden)
    monkeypatch.setattr(recovery.resources, "_group_usage", forbidden)


@pytest.mark.parametrize("recorded_scope, explicit", [
    ("isolated_process_group_only", False),
    ("isolated_process_group_only", True),
    ("sampled_birth_bound_descendants", True),
], ids=["default-group", "explicit-group", "explicit-tracked"])
def test_validation_inspection_matches_exact_recorded_process_scope_without_admission(
        tmp_path, monkeypatch, recorded_scope, explicit):
    ledger, lock, scheduler, args, value = _validation_inspection_scope_fixture(
        tmp_path, recorded_scope)
    before, lock_before = ledger.read_bytes(), lock.read_bytes()
    _forbid_validation_inspection_side_effects(monkeypatch)
    offered = {"process_scope": recorded_scope} if explicit else {}
    report = recovery.inspect_validation_reservation(ledger, **args, **offered)
    assert report["binding_verified"] is True and report["present"] is True
    assert report["custody"]["process_scope"] == recorded_scope
    assert report["record_sha256"] == recovery._digest(value["reservations"][args["reservation_id"]])
    assert report["native_lease_disposition"] is None
    assert report["historical_release_established"] is report["admitted"] is False
    assert report["state_written"] is report["recovery_performed"] is False
    report["custody"]["outputs"]["logs"] = "/fictional-mutated-return"
    assert ledger.read_bytes() == before and lock.read_bytes() == lock_before
    assert not scheduler.exists()


@pytest.mark.parametrize("recorded_scope, offered_scope", [
    ("isolated_process_group_only", "sampled_birth_bound_descendants"),
    ("sampled_birth_bound_descendants", "isolated_process_group_only"),
])
def test_validation_inspection_refuses_cross_scope_record_substitution(
        tmp_path, monkeypatch, recorded_scope, offered_scope):
    ledger, lock, scheduler, args, _ = _validation_inspection_scope_fixture(
        tmp_path, recorded_scope)
    before, lock_before = ledger.read_bytes(), lock.read_bytes()
    _forbid_validation_inspection_side_effects(monkeypatch)
    with pytest.raises(recovery.resources.DaemonResourceError, match="native lease custody"):
        recovery.inspect_validation_reservation(ledger, **args, process_scope=offered_scope)
    assert ledger.read_bytes() == before and lock.read_bytes() == lock_before
    assert not scheduler.exists()


@pytest.mark.parametrize("scope", [None, False, True, 0, "", "isolated_process_group",
                                   "unrestricted", ["sampled_birth_bound_descendants"]],
                         ids=["none", "false", "true", "zero", "empty", "wrong-group",
                              "unrestricted", "list"])
def test_validation_inspection_rejects_forged_scope_before_owner_access(monkeypatch, scope):
    constructor_calls = []
    def forbidden_constructor(*args, **kwargs):
        constructor_calls.append(True)
        raise AssertionError("invalid scope reached owner construction")
    monkeypatch.setattr(recovery.resources, "DaemonResourceReservation", forbidden_constructor)
    with pytest.raises(recovery.resources.DaemonResourceError, match="process scope"):
        recovery.inspect_validation_reservation("/fictional-never-opened/ledger.json",
            roots=["/fictional-never-opened/root"], reservation_id="1" * 32,
            expected_request_sha256="2" * 64,
            attempt_directory="/fictional-never-opened/root/attempt", process_scope=scope)
    assert constructor_calls == []


@pytest.mark.parametrize("fault", ["request", "lease", "policy", "birth", "output",
                                   "prior-child", "boolean-child"])
def test_validation_inspection_tracked_scope_keeps_original_custody_guards(
        tmp_path, monkeypatch, fault):
    scope = "sampled_birth_bound_descendants"
    ledger, lock, scheduler, args, value = _validation_inspection_scope_fixture(tmp_path, scope)
    row = value["reservations"][args["reservation_id"]]
    if fault == "request": row["validation_request_sha256"] = "a" * 64
    elif fault == "lease": row["native_lease_id"] = True
    elif fault == "policy": row["scheduler_policy_sha256"] = "b" * 63
    elif fault == "birth": row["owner_birth"] = False
    elif fault == "output": row["outputs"]["logs"] = "/fictional-foreign-output"
    elif fault == "prior-child": row["prior_children"] = [{"pid": 1, "birth": "1"}]
    else: row["child"] = {"pid": True, "birth": "1"}
    ledger.write_text(json.dumps(value, sort_keys=True))
    before, lock_before = ledger.read_bytes(), lock.read_bytes()
    _forbid_validation_inspection_side_effects(monkeypatch)
    with pytest.raises(recovery.resources.DaemonResourceError):
        recovery.inspect_validation_reservation(ledger, **args, process_scope=scope)
    assert ledger.read_bytes() == before and lock.read_bytes() == lock_before
    assert not scheduler.exists()


def test_validation_inspection_absent_tracked_record_never_claims_native_release(
        tmp_path, monkeypatch):
    ledger, lock, scheduler, args, value = _validation_inspection_scope_fixture(
        tmp_path, "sampled_birth_bound_descendants")
    value["reservations"].pop(args["reservation_id"])
    ledger.write_text(json.dumps(value, sort_keys=True))
    before, lock_before = ledger.read_bytes(), lock.read_bytes()
    _forbid_validation_inspection_side_effects(monkeypatch)
    report = recovery.inspect_validation_reservation(ledger, **args,
        process_scope="sampled_birth_bound_descendants")
    assert report["present"] is report["binding_verified"] is False
    assert report["custody"] is report["native_lease_disposition"] is None
    assert report["historical_release_established"] is report["admitted"] is False
    assert report["state_written"] is report["recovery_performed"] is False
    assert ledger.read_bytes() == before and lock.read_bytes() == lock_before
    assert not scheduler.exists()


@pytest.mark.parametrize('capacity_policy', ['require_capacity', 'administrative_closeout'])
@pytest.mark.parametrize('sampled_scope', [False, True], ids=['isolated-group', 'sampled-descendants'])
@pytest.mark.parametrize('live_child', [False, True], ids=['dead-child', 'live-child'])
def test_recovery_requires_process_scope_evidence_for_sampled_nonleader_child(
        setup, monkeypatch, capacity_policy, sampled_scope, live_child):
    ledger, args, data = retained(setup, monkeypatch)
    prior_id, prior = foreign_claim(setup)
    data = json.loads(ledger.read_bytes())
    row = data['reservations'][args['reservation_id']]
    child = {'pid': 99999998, 'birth': '123'}
    scope = 'sampled_birth_bound_descendants' if sampled_scope else 'isolated_process_group_only'
    row.update(child=child, owner_birth='456', native_lease_id='a' * 32,
        process_scope=scope, scheduler_policy_sha256='b' * 64,
        scheduler_state_path=str(args['attempt_directory'].parent / 'fixture-scheduler.json'),
        validation_request_sha256='c' * 64, scheduler_lane='validation',
        workload='canonical_validation', retention_reason='context_failed',
        outputs={name: str(args['attempt_directory'] / name)
                 for name in ('pytest', 'tmp', 'cache', 'db', 'exports', 'logs')})
    # Fictional producer-shaped custody, never an observation of a real claim.
    assert len(row) == 24 and row['owner_pid'] == 99999999
    args['expected_record_sha256'] = recovery._digest(row)
    ledger.write_text(json.dumps(data))
    unchanged = ledger.read_bytes()
    real_path = recovery.resources.Path
    child_process = dict(pid=child['pid'], birth=child['birth'], state='S',
        parent_pid=99999999, group_pid=child['pid'] - 1 if sampled_scope else child['pid'],
        rss_bytes=4096)
    process_calls = []

    def fixture_process(pid):
        process_calls.append(pid)
        return dict(child_process) if pid == child['pid'] and live_child else None

    def fixture_process_paths(value):
        text = os.fspath(value)
        if text == '/proc/self/stat':
            return SimpleNamespace(is_file=lambda: True)
        if text == '/proc':
            return SimpleNamespace(iterdir=lambda: [SimpleNamespace(name=str(child['pid']))])
        return real_path(value)

    # Patch only resource-module seams; stdlib Path and real /proc stay untouched.
    # The real _group_usage runs against an explicit one-PID process-census fixture.
    monkeypatch.setattr(recovery.resources, '_process', fixture_process)
    monkeypatch.setattr(recovery.resources, 'Path', fixture_process_paths)
    group = recovery.resources._group_usage(child)
    assert group['live_processes'] == (1 if live_child and not sampled_scope else 0)
    assert (recovery.resources._process(child['pid']) is not None) is live_child
    error = receipt = None
    try:
        receipt = recovery.reconcile_retained_reservation(ledger, **args, capacity_policy=capacity_policy)
    except recovery.resources.DaemonResourceError as failure:
        error = failure
    after_raw = ledger.read_bytes()
    after = json.loads(after_raw)
    selected = after['reservations'][args['reservation_id']]
    diagnostic = dict(capacity_policy=capacity_policy, process_scope=scope, live_child=live_child,
        child_group_pid=child_process['group_pid'], child_pid=child['pid'],
        actual_group_live_count=group['live_processes'], selected_status=selected['status'],
        ledger_changed=after_raw != unchanged, foreign_changed=after['reservations'][prior_id] != prior,
        process_calls=process_calls, error=None if error is None else str(error))
    assert after['reservations'][prior_id] == prior, diagnostic
    assert recovery._durable_inventory(args['attempt_directory']) == args['expected_artifacts']
    if sampled_scope or live_child:
        # This API profile has no complete sampled descendant inventory/proof.
        # A dead known PID alone cannot authorize closure of unresolved custody.
        assert error is not None, diagnostic
        assert after_raw == unchanged and selected == row, diagnostic
        assert receipt is None, diagnostic
    else:
        assert error is None and selected['status'] == 'released', diagnostic
        assert receipt['schema'] == ('explicit-retained-reservation-reconciliation/v2'
            if capacity_policy == 'administrative_closeout' else
            'explicit-retained-reservation-reconciliation/v1'), diagnostic
        if capacity_policy == 'administrative_closeout':
            assert receipt['capacity_policy'] == capacity_policy, diagnostic
        else:
            assert 'capacity_policy' not in receipt, diagnostic
        assert receipt['outputs_deleted'] is receipt['automatic_expiry'] is receipt['admitted'] is False


@pytest.mark.parametrize('capacity_policy', ['require_capacity', 'administrative_closeout'])
@pytest.mark.parametrize('scope', [
    'sampled_birth_bound_descendants', None, False, True, 0, '',
    'arbitrary_process_tree', [], {}, 'isolated_process_group',
], ids=['sampled', 'none', 'false', 'true', 'zero', 'empty', 'unknown',
        'list', 'dict', 'request-group-spelling'])
def test_recovery_rejects_unsupported_explicit_scope_before_census_or_write(
        setup, monkeypatch, capacity_policy, scope):
    ledger, args, _ = retained(setup, monkeypatch)
    prior_id, prior = foreign_claim(setup)
    data = json.loads(ledger.read_bytes())
    row = data['reservations'][args['reservation_id']]
    row['process_scope'] = scope
    args['expected_record_sha256'] = recovery._digest(row)
    ledger.write_text(json.dumps(data))
    unchanged = ledger.read_bytes()
    artifact = args['attempt_directory'] / 'failure.json'
    artifact_before = artifact.read_bytes()
    forbidden_calls = []

    def forbidden(*positional, **keywords):
        forbidden_calls.append(True)
        raise AssertionError('unsupported retained scope reached inventory, accounting or write')

    # Establish real private claims before forbidding all productive census and
    # write seams. A malformed scope must refuse without starting those steps.
    monkeypatch.setattr(recovery, '_durable_inventory', forbidden)
    monkeypatch.setattr(recovery, '_administrative_census', forbidden)
    monkeypatch.setattr(recovery.resources, '_inventory', forbidden)
    monkeypatch.setattr(recovery.resources.DaemonResourceReservation, '_account', forbidden)
    monkeypatch.setattr(recovery.resources.DaemonResourceReservation, '_write', forbidden)
    with pytest.raises(recovery.resources.DaemonResourceError, match='process scope'):
        recovery.reconcile_retained_reservation(ledger, **args, capacity_policy=capacity_policy)
    assert forbidden_calls == []
    assert ledger.read_bytes() == unchanged
    assert json.loads(ledger.read_bytes())['reservations'][prior_id] == prior
    assert artifact.read_bytes() == artifact_before


# Fictional original-owned documents below exercise only the administrative
# recovery contract. No historical process, scheduler grant or actual claim is
# reconstructed by these unit fixtures.
import hashlib as _sampled_hashlib
from contextlib import contextmanager as _sampled_contextmanager
from copy import deepcopy as _sampled_copy


def _sampled_wire(value):
    return (json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False) + '\n').encode()


def _sampled_sha(raw):
    return _sampled_hashlib.sha256(raw).hexdigest()


def _sampled_validation_fixture(setup, monkeypatch):
    ledger, args, _ = retained(setup, monkeypatch)
    prior_id, prior = foreign_claim(setup)
    data = json.loads(ledger.read_bytes())
    row = data['reservations'][args['reservation_id']]
    attempt = args['attempt_directory']
    outputs = {name: str(attempt / name) for name in ('pytest', 'tmp', 'cache', 'db', 'exports', 'logs')}
    scheduler_path = str(attempt.parent / 'fictional-original-scheduler.json')
    producer_path = str(Path(recovery.__file__).resolve().parents[3] / 'scripts/ops/legal_ir/run_owned_validation.py')
    producer = '"""Fictional original validation CLI witness; never executed."""\n'
    producer_sha = _sampled_sha(producer.encode())
    request = dict(schema='owned-validation-request/v1', argv=['/fictional/python', '-B', '-m', 'pytest'],
        cwd=str(Path(recovery.__file__).resolve().parents[3]), selected_checks=['fictional-owning-case'],
        source_sha256={producer_path: producer_sha}, timeout_seconds=120,
        storage_bytes=row['storage_bytes'], memory_mb=row['memory_mb'], cpu_slots=row['cpu_slots'],
        child_process_slots=row['child_process_slots'], attempt_directory=str(attempt), outputs=outputs,
        declared_external_writable_paths=[], process_scope='sampled_birth_bound_descendants',
        scheduler_state_path=scheduler_path, expected_scheduler_policy_sha256='b' * 64,
        roots=[str(root) for root in args['roots']])
    request_sha = _sampled_sha(_sampled_wire(request))
    row.update(owner_birth='456', child={'pid': 99999998, 'birth': '123'}, prior_children=[],
        native_lease_id='a' * 32, scheduler_lane='validation', workload='canonical_validation',
        scheduler_policy_sha256='b' * 64, scheduler_state_path=scheduler_path,
        validation_request_sha256=request_sha, process_scope=request['process_scope'], outputs=outputs,
        retention_reason='context_failed')
    ledger.write_text(json.dumps(data))
    observation = dict(scope=request['process_scope'],
        group_rss=dict(available=True, live_processes=0, rss_bytes=0),
        live_processes=0, rss_bytes=0,
        observed_identities=[dict(pid=99999998, birth_ticks=123, parent_pid=row['owner_pid'],
            process_group_id=99999998, session_id=99999998),
            dict(pid=99999997, birth_ticks=124, parent_pid=99999998,
            process_group_id=99999996, session_id=99999996)],
        out_of_group_live_identities=[], tracking_error='')
    lease = dict(lease_id=row['native_lease_id'], owner_pid=row['owner_pid'], lane='validation',
        parent_lease_id=None, cpu_slots=row['cpu_slots'], memory_mb=row['memory_mb'],
        child_process_slots=row['child_process_slots'], requires_gpu=False, released=True, cancelled=True,
        acquired_at=1.0, gpu_memory_mb=0, unified_memory_mb=0, wait_seconds=0.0)
    lifecycle = dict(schema='owned-validation-source-custody-lifecycle/v1', request_sha256=request_sha,
        producer=dict(path=producer_path, sha256=producer_sha),
        owner=dict(pid=row['owner_pid'], birth=row['owner_birth']), reservation_id=args['reservation_id'],
        resource_request_id='validation:' + args['reservation_id'], ledger_path=str(ledger),
        scheduler=dict(state_path=scheduler_path, policy_sha256='b' * 64,
            lane='validation', workload='canonical_validation'),
        attempt_directory=str(attempt), outputs=outputs,
        budgets={key: row[key] for key in ('cpu_slots', 'memory_mb', 'child_process_slots', 'storage_bytes')},
        process_scope=request['process_scope'], owner_child_attached=True,
        events={key: True for key in ('owner_open_attempted', 'owner_open_returned', 'child_launch_attempted',
            'child_created', 'barrier_release_attempted', 'barrier_released', 'owner_exit_handling_completed')},
        native_grant=dict(status='acquired', exact_native_timeout=False, timeout_decision=None),
        source_guards=dict(request_unchanged=True, source_pins_unchanged=True,
            owner_identity_unchanged=True, errors=[]),
        storage=dict(status='retained', release_authorized=False, cleanup_error=None))
    terminal = dict(schema='owned-validation-failure-terminal/v1', request_sha256=request_sha,
        completed=False, admitted=False, Lean_admitted=False, owner_exit_error=None,
        process_cleanup_error=None, source_custody_lifecycle=lifecycle,
        failure=dict(schema='owned-validation-result/v1', request_sha256=request_sha, completed=False,
            executed_checks=request['selected_checks'], returncode=1, admitted=False, Lean_admitted=False,
            authority_granted=False, model_weights_downloaded=False, process_observation=observation,
            process_cleanup_error=None, watchdog_errors=[], received_signals=[], elapsed_seconds=1.0,
            error='fictional owning check failed', error_type='RuntimeError',
            resource_scope='cooperative_sampled_birth_bound_descendants_and_owned_attempt'),
        reservation=dict(schema=recovery.resources.SCHEMA, reservation_id=args['reservation_id'],
            ledger_path=str(ledger), scheduler_lane='validation', workload='canonical_validation',
            status='retained', record=_sampled_copy(row), resource_lease=lease,
            process_observation=observation, cleanup_error=None, roots=data['roots'],
            storage_limit_bytes=data['limit_bytes']))
    custody = dict(original_terminal=terminal, owner_pid=row['owner_pid'], owner_birth=row['owner_birth'],
        returncode=1, errors=[], storage_status='retained', retained_storage_bytes=row['storage_bytes'],
        actual_observed_identity_count=2, storage_artifacts_durable_asserted=False,
        storage_released_and_durable=False)
    custody.update({key: True for key in ('genuine_wait_completed', 'actual_a0b_terminal_cleanup_verified',
        'all_observed_identities_gone', 'owner_identity_gone', 'child_reaped',
        'original_native_compute_closed', 'original_source_exit_lifecycle_closed')})
    parent = dict(schema='sampled-recovery-owned-validation-observation/v1', source_closed=True,
        source_drift=[], owner_returncode=1, request_sha256=request_sha,
        owner_pid=row['owner_pid'], original_owner_custody=custody)
    state = dict(leases={}, waiters={})
    process_table, calls, lock_depth = {}, [], [0]

    class Scheduler:
        state_path = Path(scheduler_path)

        @_sampled_contextmanager
        def _locked_state(self, *, persist=True, strict_existing=False, allow_reconfigure=False):
            assert persist is False and strict_existing is True and allow_reconfigure is False
            calls.append('scheduler-read-enter')
            before = _sampled_copy(state)
            lock_depth[0] += 1
            try:
                yield state
            finally:
                lock_depth[0] -= 1
                assert state == before, 'inspection must never mutate scheduler state'
                calls.append('scheduler-read-exit')

        def inspect_lease(self, lease_id, **expected):
            assert lease_id == row['native_lease_id']
            assert expected['expected_request_id'] == 'validation:' + args['reservation_id']
            assert expected['expected_lane'] == 'validation'
            assert expected['expected_owner_pid'] == row['owner_pid']
            assert expected.get('expected_owner_birth_marker') == row['owner_birth']
            calls.append('lease-read')
            own = state['leases'].get(lease_id)
            descendants = [value for value in state['leases'].values()
                           if value.get('parent_lease_id') == lease_id]
            return dict(schema='exact-resource-lease-inspection/v1', read_only=True,
                lease_id=lease_id, expected_request_id=expected['expected_request_id'],
                expected_lane=expected['expected_lane'], expected_owner_pid=expected['expected_owner_pid'],
                expected_owner_birth_marker=expected['expected_owner_birth_marker'], observed_at=1.0,
                status='absent' if own is None else 'present', lease=own, descendants=descendants,
                descendant_count=len(descendants), live_descendant_count=len(descendants),
                binding_verified=None if own is None else True,
                owner_birth_binding_verified=None if own is None else True,
                historical_release_status=None)

    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import existing_resource_scheduler as scheduler_owner

    def open_scheduler(path, policy, *, inspection_only=False):
        assert str(path) == scheduler_path and policy == 'b' * 64 and inspection_only is True
        calls.append('scheduler-open-inspection-only')
        return Scheduler()

    monkeypatch.setattr(scheduler_owner, 'open_existing_scheduler', open_scheduler)
    monkeypatch.setattr(recovery.resources, '_process',
        lambda pid: _sampled_copy(process_table.get(pid)))
    def forbid_new_admission(*args, **kwargs):
        raise AssertionError('administrative profile cannot enter a reservation or acquire a grant')
    monkeypatch.setattr(recovery.resources.DaemonResourceReservation, '__enter__', forbid_new_admission)
    monkeypatch.setattr(recovery.resources.DaemonResourceReservation, '_acquire_native_lease', forbid_new_admission)
    case = dict(ledger=ledger, args=args, row=row, request=request, terminal=terminal, parent=parent,
        producer=producer, process_table=process_table, scheduler_state=state, scheduler_calls=calls,
        prior_id=prior_id, prior=prior, scheduler_lock_depth=lock_depth)
    _sampled_seal(case)
    return case


def _sampled_seal(case):
    """Independently pin every fictional original document and its envelope."""
    request_raw = _sampled_wire(case['request'])
    terminal_raw = _sampled_wire(case['terminal'])
    stdout_raw = case.get('stdout_override', terminal_raw)
    parent_raw = _sampled_wire(case['parent'])
    proof = dict(schema='sampled-validation-recovery-proof/v1',
        request_raw_utf8=request_raw.decode(), terminal_raw_utf8=terminal_raw.decode(),
        stdout_raw_utf8=stdout_raw.decode(),
        parent_closeout_raw_utf8=parent_raw.decode(), producer_source_utf8=case['producer'],
        provenance='original_parent_popen_verified_closeout/v1')
    case['proof'] = proof
    case['args'].update(expected_record_sha256=recovery._digest(case['row']),
        proof_raw=_sampled_wire(proof), expected_proof_sha256=_sampled_sha(_sampled_wire(proof)),
        expected_request_sha256=_sampled_sha(request_raw), expected_terminal_sha256=_sampled_sha(terminal_raw),
        expected_stdout_sha256=_sampled_sha(stdout_raw),
        expected_parent_closeout_sha256=_sampled_sha(parent_raw),
        expected_producer_sha256=_sampled_sha(case['producer'].encode()))


def _sampled_assert_unchanged(case, before):
    assert case['ledger'].read_bytes() == before
    assert json.loads(before)['reservations'][case['prior_id']] == case['prior']
    assert recovery._durable_inventory(case['args']['attempt_directory']) == case['args']['expected_artifacts']


def _sampled_inspect(case):
    native = recovery.resources.native_deadlines
    if native.resource_operation_deadline() is not None:
        return recovery.inspect_sampled_validation_recovery_v1(case['ledger'], **case['args'])
    with native.resource_cleanup_deadline(
            native_deadline_monotonic=recovery.resources.time.monotonic() + 240):
        return recovery.inspect_sampled_validation_recovery_v1(case['ledger'], **case['args'])


def _sampled_reconcile(case, capacity_policy):
    native = recovery.resources.native_deadlines
    if native.resource_operation_deadline() is not None:
        return recovery.reconcile_sampled_validation_reservation_v1(
            case['ledger'], **case['args'], capacity_policy=capacity_policy)
    with native.resource_cleanup_deadline(
            native_deadline_monotonic=recovery.resources.time.monotonic() + 240):
        return recovery.reconcile_sampled_validation_reservation_v1(
            case['ledger'], **case['args'], capacity_policy=capacity_policy)


@pytest.mark.parametrize('operation', ['inspect', 'reconcile'])
def test_sampled_profile_requires_original_cleanup_deadline_without_opening_owner(
        setup, monkeypatch, operation):
    case = _sampled_validation_fixture(setup, monkeypatch)
    before = case['ledger'].read_bytes()
    assert recovery.resources.native_deadlines.resource_operation_deadline() is None
    def forbidden(*args, **kwargs):
        raise AssertionError('missing cleanup deadline reached owner construction')
    monkeypatch.setattr(recovery.resources, 'DaemonResourceReservation', forbidden)
    call = (recovery.inspect_sampled_validation_recovery_v1 if operation == 'inspect' else
            recovery.reconcile_sampled_validation_reservation_v1)
    with pytest.raises(recovery.resources.DaemonResourceError):
        call(case['ledger'], **case['args'])
    _sampled_assert_unchanged(case, before)


def test_sampled_readiness_inspects_without_admission_census_or_write(setup, monkeypatch):
    case = _sampled_validation_fixture(setup, monkeypatch)
    before = case['ledger'].read_bytes()
    def forbidden(*args, **kwargs):
        raise AssertionError('readiness cannot allocate, globally account or write')
    monkeypatch.setattr(recovery.resources.DaemonResourceReservation, '__enter__', forbidden)
    monkeypatch.setattr(recovery.resources.DaemonResourceReservation, '_acquire_native_lease', forbidden)
    monkeypatch.setattr(recovery.resources.DaemonResourceReservation, '_account', forbidden)
    monkeypatch.setattr(recovery.resources.DaemonResourceReservation, '_write', forbidden)
    monkeypatch.setattr(recovery, '_administrative_census', forbidden)
    report = _sampled_inspect(case)
    assert report['schema'] == 'sampled-validation-recovery-readiness/v1' and report['ready'] is True
    assert report['state_written'] is report['recovery_performed'] is report['admitted'] is False
    assert report['capacity_not_assessed'] is True
    assert case['scheduler_calls'] and case['scheduler_state'] == dict(leases={}, waiters={})
    _sampled_assert_unchanged(case, before)


@pytest.mark.parametrize('capacity_policy', ['require_capacity', 'administrative_closeout'])
def test_sampled_recovery_releases_only_witness_bound_claim_and_preserves_artifacts(
        setup, monkeypatch, capacity_policy):
    case = _sampled_validation_fixture(setup, monkeypatch)
    before = json.loads(case['ledger'].read_bytes())
    receipt = _sampled_reconcile(case, capacity_policy)
    after = json.loads(case['ledger'].read_bytes())
    selected = after['reservations'][case['args']['reservation_id']]
    assert selected['status'] == 'released' and selected['artifacts_durable_asserted'] is True
    assert after['reservations'][case['prior_id']] == case['prior']
    assert set(after['reservations']) == set(before['reservations'])
    assert after['roots'] == before['roots'] and after['limit_bytes'] == before['limit_bytes']
    assert receipt['outputs_deleted'] is receipt['admitted'] is False
    assert receipt['schema'] == 'explicit-sampled-validation-reservation-reconciliation/v1'
    assert receipt['process_scope'] == 'sampled_birth_bound_descendants'
    assert receipt['sampled_custody_proof']['historical_evidence_selected_by_caller'] is True
    assert receipt['sampled_custody_proof']['cryptographic_execution_attestation'] is False
    assert recovery._durable_inventory(case['args']['attempt_directory']) == case['args']['expected_artifacts']
    assert case['scheduler_state'] == dict(leases={}, waiters={})


@pytest.mark.parametrize('capacity_policy', ['require_capacity', 'administrative_closeout'])
@pytest.mark.parametrize('identity', ['owner', 'leader', 'out-of-group-descendant', 'reused-descendant'])
def test_sampled_recovery_rechecks_every_observed_pid_including_nonleader_and_reuse(
        setup, monkeypatch, capacity_policy, identity):
    case = _sampled_validation_fixture(setup, monkeypatch)
    pid, birth = ((99999999, '456') if identity == 'owner' else
                  (99999998, '123') if identity == 'leader' else (99999997, '124'))
    case['process_table'][pid] = dict(pid=pid, birth='999' if identity == 'reused-descendant' else birth,
        state='S', parent_pid=99999998, group_pid=99999996, rss_bytes=4096)
    before = case['ledger'].read_bytes()
    with pytest.raises(recovery.resources.DaemonResourceError):
        _sampled_reconcile(case, capacity_policy)
    _sampled_assert_unchanged(case, before)


@pytest.mark.parametrize('capacity_policy', ['require_capacity', 'administrative_closeout'])
@pytest.mark.parametrize('damage', ['root-lease', 'duplicate-request-lease', 'request-waiter',
                                   'orphan-child', 'orphan-grandchild'])
def test_sampled_recovery_refuses_remaining_scheduler_request_or_lease_ancestry(
        setup, monkeypatch, capacity_policy, damage):
    case = _sampled_validation_fixture(setup, monkeypatch)
    original = case['row']['native_lease_id']
    request_id = 'validation:' + case['args']['reservation_id']
    if damage == 'root-lease':
        case['scheduler_state']['leases'][original] = dict(lease_id=original, request_id=request_id)
    elif damage == 'duplicate-request-lease':
        case['scheduler_state']['leases']['c' * 32] = dict(lease_id='c' * 32, request_id=request_id)
    elif damage == 'request-waiter':
        case['scheduler_state']['waiters']['d' * 32] = dict(request_id=request_id)
    else:
        case['scheduler_state']['leases']['c' * 32] = dict(lease_id='c' * 32,
            parent_lease_id=original, request_id='fictional-descendant-request')
        if damage == 'orphan-grandchild':
            case['scheduler_state']['leases']['d' * 32] = dict(lease_id='d' * 32,
                parent_lease_id='c' * 32, request_id='fictional-grandchild-request')
    before = case['ledger'].read_bytes()
    with pytest.raises(recovery.resources.DaemonResourceError):
        _sampled_reconcile(case, capacity_policy)
    _sampled_assert_unchanged(case, before)


@pytest.mark.parametrize('capacity_policy', ['require_capacity', 'administrative_closeout'])
@pytest.mark.parametrize('damage', ['missing-observations', 'live-observation', 'tracking-error',
    'native-not-released', 'parent-not-closed', 'parent-errors', 'source-drift', 'wrong-request',
    'wrong-record', 'false-provenance', 'producer-bytes', 'terminal-pin', 'parent-pin', 'proof-pin',
    'stdout-pin', 'stdout-rebind', 'stdout-duplicate', 'outer-reservation-id',
    'reservation-root-identity', 'source-guard-bool', 'native-grant-bool', 'observation-count'])
def test_sampled_recovery_refuses_forged_or_incomplete_original_closeout(
        setup, monkeypatch, capacity_policy, damage):
    case = _sampled_validation_fixture(setup, monkeypatch)
    observation = case['terminal']['reservation']['process_observation']
    if damage == 'missing-observations': observation['observed_identities'] = []
    elif damage == 'live-observation': observation['live_processes'] = 1
    elif damage == 'tracking-error': observation['tracking_error'] = 'fictional unresolved ancestry'
    elif damage == 'native-not-released': case['terminal']['reservation']['resource_lease']['released'] = False
    elif damage == 'parent-not-closed': case['parent']['source_closed'] = False
    elif damage == 'parent-errors': case['parent']['original_owner_custody']['errors'] = ['unresolved']
    elif damage == 'source-drift': case['parent']['source_drift'] = ['fictional-owner.py']
    elif damage == 'wrong-request': case['terminal']['request_sha256'] = 'f' * 64
    elif damage == 'wrong-record': case['terminal']['reservation']['record']['storage_bytes'] += 1
    elif damage == 'outer-reservation-id':
        case['terminal']['reservation']['reservation_id'] = 'f' * 32
    elif damage == 'reservation-root-identity':
        case['terminal']['reservation']['roots'][0]['inode'] += 1
    elif damage == 'source-guard-bool':
        case['terminal']['source_custody_lifecycle']['source_guards']['request_unchanged'] = 1
    elif damage == 'native-grant-bool':
        case['terminal']['source_custody_lifecycle']['native_grant']['exact_native_timeout'] = 0
    elif damage == 'observation-count':
        case['parent']['original_owner_custody']['actual_observed_identity_count'] = 1
    elif damage == 'stdout-rebind':
        substituted = _sampled_copy(case['terminal'])
        substituted['request_sha256'] = 'f' * 64
        case['stdout_override'] = _sampled_wire(substituted)
    elif damage == 'stdout-duplicate':
        case['stdout_override'] = _sampled_wire(case['terminal']) * 2
    _sampled_seal(case)
    if damage == 'false-provenance':
        case['proof']['provenance'] = 'caller_asserted_only'
        case['args']['proof_raw'] = _sampled_wire(case['proof'])
        case['args']['expected_proof_sha256'] = _sampled_sha(case['args']['proof_raw'])
    elif damage == 'producer-bytes':
        case['proof']['producer_source_utf8'] += '# changed\n'
        case['args']['proof_raw'] = _sampled_wire(case['proof'])
        case['args']['expected_proof_sha256'] = _sampled_sha(case['args']['proof_raw'])
    elif damage in ('terminal-pin', 'parent-pin', 'proof-pin', 'stdout-pin'):
        key = dict(**{'terminal-pin': 'expected_terminal_sha256',
                     'parent-pin': 'expected_parent_closeout_sha256', 'proof-pin': 'expected_proof_sha256',
                     'stdout-pin': 'expected_stdout_sha256'})[damage]
        case['args'][key] = 'f' * 64
    before = case['ledger'].read_bytes()
    with pytest.raises(recovery.resources.DaemonResourceError):
        _sampled_reconcile(case, capacity_policy)
    _sampled_assert_unchanged(case, before)


@pytest.mark.parametrize('capacity_policy', ['require_capacity', 'administrative_closeout'])
@pytest.mark.parametrize('expire', [False, True], ids=['nonexpired', 'expired-after-census'])
def test_sampled_recovery_cannot_commit_after_census_cleanup_deadline(
        setup, monkeypatch, capacity_policy, expire):
    case = _sampled_validation_fixture(setup, monkeypatch)
    before = case['ledger'].read_bytes()
    clock, census_calls = [239.0], []
    native = recovery.resources.native_deadlines
    monkeypatch.setattr(native, 'time', SimpleNamespace(monotonic=lambda: clock[0]))
    original_account = recovery.resources.DaemonResourceReservation._account
    original_admin = recovery._administrative_census
    def account(helper, state, **kwargs):
        result = original_account(helper, state, **kwargs)
        census_calls.append(True)
        clock[0] = 241.0 if expire else 239.0
        return result
    def admin(helper, state):
        result = original_admin(helper, state)
        census_calls.append(True)
        clock[0] = 241.0 if expire else 239.0
        return result
    monkeypatch.setattr(recovery.resources.DaemonResourceReservation, '_account', account)
    monkeypatch.setattr(recovery, '_administrative_census', admin)
    if expire:
        with pytest.raises(native.ResourceAdmissionDeadlineError):
            with native.resource_cleanup_deadline(native_deadline_monotonic=240.0):
                _sampled_reconcile(case, capacity_policy)
        _sampled_assert_unchanged(case, before)
    else:
        with native.resource_cleanup_deadline(native_deadline_monotonic=240.0):
            _sampled_reconcile(case, capacity_policy)
        assert json.loads(case['ledger'].read_bytes())['reservations'][case['args']['reservation_id']]['status'] == 'released'
    assert census_calls


@pytest.mark.parametrize('capacity_policy', ['require_capacity', 'administrative_closeout'])
@pytest.mark.parametrize('expire', [False, True], ids=['nonexpired', 'expired-temp-fsync'])
def test_sampled_recovery_cannot_replace_after_temporary_file_fsync_cleanup_deadline(
        setup, monkeypatch, capacity_policy, expire):
    case = _sampled_validation_fixture(setup, monkeypatch)
    before = case['ledger'].read_bytes()
    native, real_os, real_tempfile = recovery.resources.native_deadlines, recovery.resources.os, recovery.resources.tempfile
    clock, temporary, fsyncs, replacements = [239.0], {}, [], []
    def create(*args, **kwargs):
        stream = real_tempfile.NamedTemporaryFile(*args, **kwargs)
        info = real_os.fstat(stream.fileno())
        temporary.update(path=Path(stream.name), identity=(info.st_dev, info.st_ino))
        return stream
    def fsync(descriptor):
        result = real_os.fsync(descriptor)
        info = real_os.fstat(descriptor)
        if (info.st_dev, info.st_ino) == temporary.get('identity'):
            fsyncs.append(True)
            clock[0] = 241.0 if expire else 239.0
        return result
    def replace(source, destination):
        replacements.append((Path(source), Path(destination)))
        return real_os.replace(source, destination)
    monkeypatch.setattr(native, 'time', SimpleNamespace(monotonic=lambda: clock[0]))
    monkeypatch.setattr(recovery.resources, 'tempfile', SimpleNamespace(NamedTemporaryFile=create))
    monkeypatch.setattr(recovery.resources, 'os', SimpleNamespace(**{**vars(real_os), 'fsync': fsync, 'replace': replace}))
    if expire:
        with pytest.raises(native.ResourceAdmissionDeadlineError):
            with native.resource_cleanup_deadline(native_deadline_monotonic=240.0):
                _sampled_reconcile(case, capacity_policy)
        _sampled_assert_unchanged(case, before)
        assert replacements == []
    else:
        with native.resource_cleanup_deadline(native_deadline_monotonic=240.0):
            _sampled_reconcile(case, capacity_policy)
        assert json.loads(case['ledger'].read_bytes())['reservations'][case['args']['reservation_id']]['status'] == 'released'
        assert len(replacements) == 1
    assert fsyncs == [True] and not temporary['path'].exists()


@pytest.mark.parametrize('capacity_policy', ['require_capacity', 'administrative_closeout'])
@pytest.mark.parametrize('damage', ['selected-memory', 'foreign-on-disk', 'artifact'])
def test_sampled_recovery_refuses_selected_foreign_or_artifact_mutation_during_census(
        setup, monkeypatch, capacity_policy, damage):
    case = _sampled_validation_fixture(setup, monkeypatch)
    before = case['ledger'].read_bytes()
    before_value = json.loads(before)
    expected_disk = _sampled_copy(before_value)
    selected_id = case['args']['reservation_id']
    artifact = case['args']['attempt_directory'] / 'failure.json'
    artifact_before = artifact.read_bytes()
    calls = []
    original_account = recovery.resources.DaemonResourceReservation._account
    original_admin = recovery._administrative_census

    def change(state):
        calls.append(True)
        if damage == 'selected-memory':
            state['reservations'][selected_id]['retention_reason'] = 'fictional census mutation'
        elif damage == 'foreign-on-disk':
            expected_disk['reservations'][case['prior_id']]['created_at'] += 1
            case['ledger'].write_text(json.dumps(expected_disk))
        else:
            artifact.write_bytes(b'fictional artifact changed during census\n')

    def account(helper, state, **kwargs):
        report = original_account(helper, state, **kwargs)
        change(state)
        return report

    def admin(helper, state):
        report = original_admin(helper, state)
        change(state)
        return report

    monkeypatch.setattr(recovery.resources.DaemonResourceReservation, '_account', account)
    monkeypatch.setattr(recovery, '_administrative_census', admin)
    with pytest.raises(recovery.resources.DaemonResourceError):
        _sampled_reconcile(case, capacity_policy)
    assert calls == [True]
    actual = json.loads(case['ledger'].read_bytes())
    assert actual == expected_disk
    assert actual['reservations'][selected_id] == before_value['reservations'][selected_id]
    assert actual['reservations'][selected_id]['status'] == 'retained'
    assert set(actual['reservations']) == set(before_value['reservations'])
    assert artifact.read_bytes() == (b'fictional artifact changed during census\n'
        if damage == 'artifact' else artifact_before)
    assert case['scheduler_lock_depth'] == [0]


@pytest.mark.parametrize('capacity_policy', ['require_capacity', 'administrative_closeout'])
@pytest.mark.parametrize('write_completed', [False, True], ids=['before-write', 'after-write'])
def test_sampled_recovery_keeps_scheduler_lock_through_single_atomic_write_and_never_retries(
        setup, monkeypatch, capacity_policy, write_completed):
    case = _sampled_validation_fixture(setup, monkeypatch)
    before = case['ledger'].read_bytes()
    original_write = recovery.resources.DaemonResourceReservation._write
    writes = []

    def fail(helper, state):
        assert case['scheduler_lock_depth'][0] == 1
        writes.append(state['reservations'][case['args']['reservation_id']]['status'])
        if write_completed:
            original_write(helper, state)
        raise OSError('fictional atomic-write acknowledgement failure')

    monkeypatch.setattr(recovery.resources.DaemonResourceReservation, '_write', fail)
    with pytest.raises(OSError, match='acknowledgement'):
        _sampled_reconcile(case, capacity_policy)
    assert writes == ['released']
    assert case['scheduler_lock_depth'] == [0]
    after = json.loads(case['ledger'].read_bytes())
    assert after['reservations'][case['prior_id']] == case['prior']
    assert after['reservations'][case['args']['reservation_id']]['status'] == (
        'released' if write_completed else 'retained')
    if not write_completed:
        assert case['ledger'].read_bytes() == before
    assert recovery._durable_inventory(case['args']['attempt_directory']) == case['args']['expected_artifacts']


@pytest.mark.parametrize('capacity_policy', ['require_capacity', 'administrative_closeout'])
@pytest.mark.parametrize('damage', ['none', 'proof-provenance', 'previous-record'])
def test_sampled_released_disposition_is_read_only_and_requires_original_provenance(
        setup, monkeypatch, capacity_policy, damage):
    case = _sampled_validation_fixture(setup, monkeypatch)
    previous_sha = case['args']['expected_record_sha256']
    _sampled_reconcile(case, capacity_policy)
    data = json.loads(case['ledger'].read_bytes())
    row = data['reservations'][case['args']['reservation_id']]
    if damage == 'proof-provenance':
        row['explicit_reconciliation']['sampled_custody_proof']['cryptographic_execution_attestation'] = True
    elif damage == 'previous-record':
        row['explicit_reconciliation']['previous_record_sha256'] = 'f' * 64
    if damage != 'none':
        case['ledger'].write_text(json.dumps(data))
    before = case['ledger'].read_bytes()
    arguments = dict(roots=case['args']['roots'], reservation_id=case['args']['reservation_id'],
        expected_request_sha256=case['args']['expected_request_sha256'],
        attempt_directory=case['args']['attempt_directory'], expected_record_sha256=recovery._digest(row),
        expected_previous_record_sha256=previous_sha, process_scope='sampled_birth_bound_descendants')
    if damage == 'none':
        report = recovery.inspect_validation_disposition(case['ledger'], **arguments)
        assert report['storage_release_established'] is True
        assert report['native_release_established'] is False
        assert report['state_written'] is report['recovery_performed'] is report['admitted'] is False
    else:
        with pytest.raises(recovery.resources.DaemonResourceError):
            recovery.inspect_validation_disposition(case['ledger'], **arguments)
    assert case['ledger'].read_bytes() == before
    assert data['reservations'][case['prior_id']] == case['prior']
    assert recovery._durable_inventory(case['args']['attempt_directory']) == case['args']['expected_artifacts']


@pytest.mark.parametrize('capacity_policy', ['require_capacity', 'administrative_closeout'])
@pytest.mark.parametrize('identity', ['sampled-pid', 'request-waiter'])
@pytest.mark.parametrize('stage', ['after-census', 'prewrite-inventory'])
def test_sampled_recovery_rechecks_late_pid_and_request_before_final_commit(
        setup, monkeypatch, capacity_policy, identity, stage):
    case = _sampled_validation_fixture(setup, monkeypatch)
    before = case['ledger'].read_bytes()
    original_account = recovery.resources.DaemonResourceReservation._account
    original_admin = recovery._administrative_census
    original_inventory = recovery._durable_inventory
    calls, fired = dict(census=0, inventory=0), []

    def appear():
        fired.append(True)
        if identity == 'sampled-pid':
            case['process_table'][99999997] = dict(pid=99999997, birth='124', state='S',
                parent_pid=99999998, group_pid=99999996, rss_bytes=4096)
        else:
            case['scheduler_state']['waiters']['e' * 32] = dict(
                request_id='validation:' + case['args']['reservation_id'])

    def after_census():
        calls['census'] += 1
        if stage == 'after-census' and calls['census'] == 1:
            appear()

    def account(helper, state, **kwargs):
        report = original_account(helper, state, **kwargs)
        after_census()
        return report

    def admin(helper, state):
        report = original_admin(helper, state)
        after_census()
        return report

    def inventory(attempt):
        result = original_inventory(attempt)
        calls['inventory'] += 1
        if stage == 'prewrite-inventory' and not fired:
            # Observe the actual lock boundary instead of assuming an inventory
            # call ordinal. A PID appears inside the final scheduler guard. A
            # waiter appears after the last census while still outside its
            # scheduler lock, keeping the fake facade's integrity check valid.
            guarded = case['scheduler_lock_depth'][0] == 1
            final_census = calls['census'] == (2 if capacity_policy == 'administrative_closeout' else 1)
            if (identity == 'sampled-pid' and guarded) or (
                    identity == 'request-waiter' and final_census and not guarded):
                appear()
        return result

    monkeypatch.setattr(recovery.resources.DaemonResourceReservation, '_account', account)
    monkeypatch.setattr(recovery, '_administrative_census', admin)
    monkeypatch.setattr(recovery, '_durable_inventory', inventory)
    with pytest.raises(recovery.resources.DaemonResourceError):
        _sampled_reconcile(case, capacity_policy)
    assert fired == [True]
    assert case['scheduler_lock_depth'] == [0]
    _sampled_assert_unchanged(case, before)


@pytest.mark.parametrize('capacity_policy', ['require_capacity', 'administrative_closeout'])
def test_sampled_recovery_distinguishes_successful_command_from_failed_cli_finalization(
        setup, monkeypatch, capacity_policy):
    case = _sampled_validation_fixture(setup, monkeypatch)
    case['terminal']['failure']['returncode'] = 0
    case['terminal']['failure']['error'] = 'fictional finalization failure after successful command'
    case['terminal']['failure']['error_type'] = 'DaemonResourceError'
    assert case['parent']['owner_returncode'] == case['parent']['original_owner_custody']['returncode'] == 1
    _sampled_seal(case)
    receipt = _sampled_reconcile(case, capacity_policy)
    after = json.loads(case['ledger'].read_bytes())
    assert after['reservations'][case['args']['reservation_id']]['status'] == 'released'
    assert after['reservations'][case['prior_id']] == case['prior']
    assert receipt['schema'] == 'explicit-sampled-validation-reservation-reconciliation/v1'
    assert receipt['native_release_performed'] is receipt['admitted'] is False
    assert recovery._durable_inventory(case['args']['attempt_directory']) == case['args']['expected_artifacts']


@pytest.mark.parametrize('capacity_policy', ['require_capacity', 'administrative_closeout'])
def test_sampled_recovery_requires_parent_cli_and_custody_returncodes_to_agree(
        setup, monkeypatch, capacity_policy):
    case = _sampled_validation_fixture(setup, monkeypatch)
    case['parent']['original_owner_custody']['returncode'] = 2
    assert case['parent']['owner_returncode'] == 1
    _sampled_seal(case)
    before = case['ledger'].read_bytes()
    with pytest.raises(recovery.resources.DaemonResourceError):
        _sampled_reconcile(case, capacity_policy)
    _sampled_assert_unchanged(case, before)


# These are explicitly FICTIONAL historical Root custody documents. The real
# temporary ledger/artifacts and unchanged sampled engine are exercised; no
# genuine Popen/native grant or production claim is manufactured by this fixture.
def _reviewed_producer_sampled_fixture(setup, monkeypatch):
    case = _sampled_validation_fixture(setup, monkeypatch)
    request, row, terminal = case['request'], case['row'], case['terminal']
    # Existing setup uses a deliberately small test-local ledger limit. Keep
    # this private fixture large enough for the exact historical64MiB promise;
    # this does not change the production ledger, policy, cap or admission.
    local_limit = 100_000_000
    monkeypatch.setattr(recovery.resources, 'MAX_STORAGE_BYTES', local_limit)
    data = json.loads(case['ledger'].read_bytes())
    data['limit_bytes'] = local_limit
    budgets = dict(storage_bytes=64 * 1024**2, memory_mb=1536, cpu_slots=1, child_process_slots=2)
    row.update(budgets)
    data['reservations'][case['args']['reservation_id']] = row
    request.update(budgets, schema='owned-validation-request/v4',
        live_inventory_profile=dict(schema='owned-validation-live-census/v1', max_complete_resamples=1))
    plan_path = str(case['args']['attempt_directory'].parent / 'fictional-reviewed-plan.json')
    request['source_sha256'][plan_path] = 'c' * 64
    request_raw = _sampled_wire(request)
    request_sha = _sampled_sha(request_raw)
    row['validation_request_sha256'] = request_sha
    terminal['request_sha256'] = terminal['failure']['request_sha256'] = request_sha
    terminal['source_custody_lifecycle']['request_sha256'] = request_sha
    terminal['source_custody_lifecycle']['budgets'] = dict(budgets)
    terminal['reservation']['record'] = _sampled_copy(row)
    terminal['reservation']['resource_lease'].update(
        {key: budgets[key] for key in ('memory_mb', 'cpu_slots', 'child_process_slots')})
    terminal['reservation']['storage_limit_bytes'] = local_limit
    terminal['reservation']['live_inventory_profile'] = dict(schema='owned-validation-live-census/v1',
        request_sha256=request_sha, live_exception_active=False, complete_resamples_observed=0,
        max_complete_resamples=1, resample_limit_scope='per_logical_live_census')
    root = Path(terminal['source_custody_lifecycle']['producer']['path']).parents[3]
    source_owners = [dict(canonical_root=str(path), cooperative=True,
        lock_path=str(path / 'workspace/control-plane/source-leases/source.lock'), mode='read',
        schema_version='autoencoder-source-lease/v1', waited_seconds=0.001)
        for path in (root, root.parent / 'ipfs_accelerate')]
    parent = dict(schema='legal-phase8-reviewed-producer-pytest-actual-owner-closeout/v1',
        original_terminal=terminal, owner_pid=row['owner_pid'], owner_birth=int(row['owner_birth']),
        returncode=1, completed=False, errors=[], cleanup_errors=[],
        actual_observed_identity_count=len(terminal['reservation']['process_observation']['observed_identities']),
        opening_source_READs=_sampled_copy(source_owners), closing_source_READs=_sampled_copy(source_owners),
        closing_source_READ_elapsed_seconds=0.05, closing_source_READ_window_seconds=3.0,
        elapsed_seconds=150.0, storage_status='retained', retained_storage_bytes=row['storage_bytes'],
        plan=dict(path=plan_path, bytes=100, sha256='c' * 64),
        request=dict(path=str(case['args']['attempt_directory'].parent / 'fictional-reviewed-request.json'),
            bytes=len(request_raw), sha256=request_sha))
    parent.update({key: True for key in ('genuine_wait_completed', 'actual_a0b_terminal_cleanup_verified',
        'all_observed_identities_gone', 'owner_identity_gone', 'child_reaped', 'original_native_compute_closed',
        'original_source_exit_lifecycle_closed', 'source_READ_closed', 'source_custody_closed', 'source_pins_unchanged',
        'parent_source_READ_closed_before_Popen', 'attempt_precreated_empty_before_original_owner',
        'closing_source_READ_absolute_window_satisfied')})
    parent.update({key: False for key in ('automatic_retry_authorized',
        'kill_signal_or_manual_reservation_release_performed', 'new_resource_owner_implementation_created',
        'source_qualification_or_native_Lean_or_semantic_claimed', 'storage_artifacts_durable_asserted',
        'storage_released_and_durable', 'unknown_wait_no_replay', 'closing_source_READ_clock_renewed')})
    case['parent'] = parent
    case['ledger'].write_text(json.dumps(data))
    _sampled_seal(case)
    return case


def test_reviewed_producer_sampled_readiness_keeps_original_engine_read_only(setup, monkeypatch):
    case = _reviewed_producer_sampled_fixture(setup, monkeypatch)
    before = case['ledger'].read_bytes()
    def forbidden(*args, **kwargs):
        raise AssertionError('readiness cannot grant, account, mutate or reconcile')
    monkeypatch.setattr(recovery.resources.DaemonResourceReservation, '_account', forbidden)
    monkeypatch.setattr(recovery.resources.DaemonResourceReservation, '_write', forbidden)
    monkeypatch.setattr(recovery, '_administrative_census', forbidden)
    report = _sampled_inspect(case)
    assert report['ready'] is True and report['capacity_not_assessed'] is True
    assert report['state_written'] is report['recovery_performed'] is report['admitted'] is False
    assert report['native_release_performed'] is report['historical_release_invented'] is False
    assert case['scheduler_calls'] and case['scheduler_state'] == dict(leases={}, waiters={})
    _sampled_assert_unchanged(case, before)


@pytest.mark.parametrize('capacity_policy', ['require_capacity', 'administrative_closeout'])
def test_reviewed_producer_sampled_storage_closeout_preserves_history_and_foreign_claims(
        setup, monkeypatch, capacity_policy):
    case = _reviewed_producer_sampled_fixture(setup, monkeypatch)
    before = json.loads(case['ledger'].read_bytes())
    receipt = _sampled_reconcile(case, capacity_policy)
    after = json.loads(case['ledger'].read_bytes())
    selected = after['reservations'][case['args']['reservation_id']]
    assert selected['status'] == 'released' and selected['artifacts_durable_asserted'] is True
    assert after['reservations'][case['prior_id']] == before['reservations'][case['prior_id']]
    assert after['limit_bytes'] == before['limit_bytes']
    assert set(after['reservations']) == set(before['reservations'])
    assert receipt['outputs_deleted'] is receipt['admitted'] is False
    assert receipt['sampled_custody_proof']['original_failure_preserved'] is True
    assert receipt['sampled_custody_proof']['cryptographic_execution_attestation'] is False
    assert receipt['sampled_custody_proof']['original_command_returncode'] == 1
    assert receipt['sampled_custody_proof']['original_cli_returncode'] == 1
    assert recovery._durable_inventory(case['args']['attempt_directory']) == case['args']['expected_artifacts']


@pytest.mark.parametrize('damage', [
    'v4-extra', 'v4-max2', 'v4-bool', 'v4-schema', 'parent-extra', 'parent-schema',
    'owner-pid', 'owner-birth-string', 'owner-birth-wrong', 'cli-zero', 'command-zero',
    'barrier-not-released', 'native-open', 'source-open', 'source-drift', 'child-not-reaped',
    'no-genuine-wait', 'wrong-observed-count', 'parent-error', 'parent-cleanup-error',
    'storage-released', 'storage-durable', 'source-clock-exhausted', 'source-clock-renewed',
    'closing-source-root', 'closing-source-mode', 'opening-source-cooperative',
    'request-bytes', 'request-hash', 'plan-hash', 'wrong-budget',
    'missing-live-receipt', 'active-live', 'resampled-live', 'live-request', 'live-bool',
])
def test_reviewed_producer_sampled_refuses_changed_original_bindings_before_owner_access(
        setup, monkeypatch, damage):
    case = _reviewed_producer_sampled_fixture(setup, monkeypatch)
    parent, request, terminal = case['parent'], case['request'], case['terminal']
    live = terminal['reservation']['live_inventory_profile']
    if damage == 'v4-extra': request['live_inventory_profile']['extra'] = False
    elif damage == 'v4-max2': request['live_inventory_profile']['max_complete_resamples'] = 2
    elif damage == 'v4-bool': request['live_inventory_profile']['max_complete_resamples'] = True
    elif damage == 'v4-schema': request['live_inventory_profile']['schema'] = 'unknown/v1'
    elif damage == 'parent-extra': parent['extra'] = False
    elif damage == 'parent-schema': parent['schema'] = 'unknown/v1'
    elif damage == 'owner-pid': parent['owner_pid'] += 1
    elif damage == 'owner-birth-string': parent['owner_birth'] = str(parent['owner_birth'])
    elif damage == 'owner-birth-wrong': parent['owner_birth'] += 1
    elif damage == 'cli-zero': parent['returncode'] = 0
    elif damage == 'command-zero': terminal['failure']['returncode'] = 0
    elif damage == 'barrier-not-released': terminal['source_custody_lifecycle']['events']['barrier_released'] = False
    elif damage == 'native-open': parent['original_native_compute_closed'] = False
    elif damage == 'source-open': parent['source_custody_closed'] = False
    elif damage == 'source-drift': parent['source_pins_unchanged'] = False
    elif damage == 'child-not-reaped': parent['child_reaped'] = False
    elif damage == 'no-genuine-wait': parent['genuine_wait_completed'] = False
    elif damage == 'wrong-observed-count': parent['actual_observed_identity_count'] += 1
    elif damage == 'parent-error': parent['errors'] = [{'stage': 'uncertain'}]
    elif damage == 'parent-cleanup-error': parent['cleanup_errors'] = ['uncertain']
    elif damage == 'storage-released': parent['storage_released_and_durable'] = True
    elif damage == 'storage-durable': parent['storage_artifacts_durable_asserted'] = True
    elif damage == 'source-clock-exhausted': parent['closing_source_READ_elapsed_seconds'] = 3.0
    elif damage == 'source-clock-renewed': parent['closing_source_READ_clock_renewed'] = True
    elif damage == 'closing-source-root': parent['closing_source_READs'][1]['canonical_root'] = '/other'
    elif damage == 'closing-source-mode': parent['closing_source_READs'][0]['mode'] = 'write'
    elif damage == 'opening-source-cooperative': parent['opening_source_READs'][0]['cooperative'] = False
    elif damage == 'request-bytes': parent['request']['bytes'] += 1
    elif damage == 'request-hash': parent['request']['sha256'] = '0' * 64
    elif damage == 'plan-hash': parent['plan']['sha256'] = '0' * 64
    elif damage == 'wrong-budget':
        request['timeout_seconds'] = 121
        # Preserve every fictional request join so this reaches the exact120
        # historical budget predicate, rather than an earlier stale hash guard.
        changed_raw = _sampled_wire(request)
        changed_sha = _sampled_sha(changed_raw)
        case['row']['validation_request_sha256'] = changed_sha
        terminal['request_sha256'] = terminal['failure']['request_sha256'] = changed_sha
        terminal['source_custody_lifecycle']['request_sha256'] = changed_sha
        live['request_sha256'] = changed_sha
        terminal['reservation']['record'] = _sampled_copy(case['row'])
        parent['request'].update(bytes=len(changed_raw), sha256=changed_sha)
        data = json.loads(case['ledger'].read_bytes())
        data['reservations'][case['args']['reservation_id']] = case['row']
        case['ledger'].write_text(json.dumps(data))
    elif damage == 'missing-live-receipt': del terminal['reservation']['live_inventory_profile']
    elif damage == 'active-live': live['live_exception_active'] = True
    elif damage == 'resampled-live': live['complete_resamples_observed'] = 1
    elif damage == 'live-request': live['request_sha256'] = '0' * 64
    elif damage == 'live-bool': live['max_complete_resamples'] = True
    else: raise AssertionError(damage)
    _sampled_seal(case)
    before = case['ledger'].read_bytes()
    def forbidden(*args, **kwargs):
        raise AssertionError('invalid historical profile reached owner construction')
    monkeypatch.setattr(recovery.resources, 'DaemonResourceReservation', forbidden)
    with pytest.raises(recovery.resources.DaemonResourceError):
        _sampled_inspect(case)
    assert case['ledger'].read_bytes() == before
    assert case['scheduler_calls'] == []


@pytest.mark.parametrize('damage', ['live-observed-pid', 'native-request', 'artifact-change'])
def test_reviewed_producer_sampled_keeps_current_native_process_and_artifact_guards(
        setup, monkeypatch, damage):
    case = _reviewed_producer_sampled_fixture(setup, monkeypatch)
    if damage == 'live-observed-pid':
        pid = case['terminal']['reservation']['process_observation']['observed_identities'][1]['pid']
        case['process_table'][pid] = SimpleNamespace(pid=pid)
    elif damage == 'native-request':
        case['scheduler_state']['waiters']['foreign-looking-key'] = {
            'request_id': 'validation:' + case['args']['reservation_id']}
    else:
        (case['args']['attempt_directory'] / 'failure.json').write_text('changed artifact')
    before = case['ledger'].read_bytes()
    with pytest.raises(recovery.resources.DaemonResourceError):
        _sampled_reconcile(case, 'administrative_closeout')
    assert case['ledger'].read_bytes() == before
    assert json.loads(before)['reservations'][case['prior_id']] == case['prior']


# Explicitly FICTIONAL original custody documents exercise the new parser shape
# and the existing real private ledger/artifact engine. The test-only selector
# patch does not claim that this tiny fictional producer is genuine07b or that
# any Popen/native grant occurred. Genuine07b buffers remain separate evidence.
def _before_barrier_capacity_fixture(setup, monkeypatch):
    case = _reviewed_producer_sampled_fixture(setup, monkeypatch)
    monkeypatch.setattr(recovery, '_REVIEWED_BEFORE_BARRIER_PRODUCER_SHA256',
        _sampled_sha(case['producer'].encode()))
    terminal, parent = case['terminal'], case['parent']
    observation = terminal['reservation']['process_observation']
    case['extra_identity'] = _sampled_copy(observation['observed_identities'][1])
    observation['observed_identities'] = observation['observed_identities'][:1]
    parent['actual_observed_identity_count'] = 1
    terminal['source_custody_lifecycle']['events'].update(
        barrier_release_attempted=False, barrier_released=False)
    terminal['failure'].update(returncode=None, executed_checks=[],
        error_type='DaemonResourceError', error='storage reservation capacity exceeded')
    _sampled_seal(case)
    return case


def _before_barrier_rebind_fictional_request(case):
    # Rebind every document and ledger join when changing an original request;
    # this ensures a wrong-budget control reaches the exact120 predicate.
    changed_raw = _sampled_wire(case['request'])
    changed_sha = _sampled_sha(changed_raw)
    terminal, row = case['terminal'], case['row']
    row['validation_request_sha256'] = changed_sha
    terminal['request_sha256'] = terminal['failure']['request_sha256'] = changed_sha
    terminal['source_custody_lifecycle']['request_sha256'] = changed_sha
    terminal['reservation']['live_inventory_profile']['request_sha256'] = changed_sha
    terminal['reservation']['record'] = _sampled_copy(row)
    case['parent']['request'].update(bytes=len(changed_raw), sha256=changed_sha)
    data = json.loads(case['ledger'].read_bytes())
    data['reservations'][case['args']['reservation_id']] = row
    case['ledger'].write_text(json.dumps(data))


def test_before_barrier_capacity_readiness_keeps_original_engine_read_only(setup, monkeypatch):
    case = _before_barrier_capacity_fixture(setup, monkeypatch)
    before = case['ledger'].read_bytes()
    def forbidden(*args, **kwargs):
        raise AssertionError('readiness cannot account, write, reconcile or grant')
    monkeypatch.setattr(recovery.resources.DaemonResourceReservation, '_account', forbidden)
    monkeypatch.setattr(recovery.resources.DaemonResourceReservation, '_write', forbidden)
    monkeypatch.setattr(recovery, '_administrative_census', forbidden)
    report = _sampled_inspect(case)
    assert report['ready'] is True and report['capacity_not_assessed'] is True
    assert report['state_written'] is report['recovery_performed'] is report['admitted'] is False
    assert report['native_release_performed'] is report['historical_release_invented'] is False
    assert report['proof']['original_command_returncode'] is None
    assert report['proof']['original_cli_returncode'] == 1
    assert report['proof']['original_failure_profile'] == 'reviewed-before-barrier-capacity-refusal/v1'
    assert report['proof']['original_command_dispatch'] == 'original_barrier_never_attempted'
    _sampled_assert_unchanged(case, before)


@pytest.mark.parametrize('capacity_policy', ['require_capacity', 'administrative_closeout'])
def test_before_barrier_capacity_storage_closeout_preserves_closed_failure_and_foreign_claims(
        setup, monkeypatch, capacity_policy):
    case = _before_barrier_capacity_fixture(setup, monkeypatch)
    before = json.loads(case['ledger'].read_bytes())
    original = _sampled_copy(case['row'])
    foreign_artifact = case['args']['roots'][1] / 'foreign-before-barrier-evidence.txt'
    foreign_artifact.write_bytes(b'preserve this unrelated real artifact')
    foreign_body = foreign_artifact.read_bytes()
    foreign_identity = tuple(getattr(foreign_artifact.stat(), key) for key in
        ('st_dev', 'st_ino', 'st_mode', 'st_nlink'))
    receipt = _sampled_reconcile(case, capacity_policy)
    after = json.loads(case['ledger'].read_bytes())
    row = after['reservations'][case['args']['reservation_id']]
    assert row['status'] == 'released' and row['artifacts_durable_asserted'] is True
    assert all(row.get(k) == value for k, value in original.items()
        if k not in ('status', 'artifacts_durable_asserted'))
    assert after['reservations'][case['prior_id']] == before['reservations'][case['prior_id']]
    assert after['limit_bytes'] == before['limit_bytes']
    assert set(after['reservations']) == set(before['reservations'])
    assert receipt['outputs_deleted'] is receipt['admitted'] is receipt['native_release_performed'] is False
    assert receipt['sampled_custody_proof']['original_failure_preserved'] is True
    assert receipt['sampled_custody_proof']['cryptographic_execution_attestation'] is False
    assert receipt['sampled_custody_proof']['original_command_returncode'] is None
    assert receipt['sampled_custody_proof']['original_command_dispatch'] == 'original_barrier_never_attempted'
    assert foreign_artifact.read_bytes() == foreign_body
    assert tuple(getattr(foreign_artifact.stat(), key) for key in
        ('st_dev', 'st_ino', 'st_mode', 'st_nlink')) == foreign_identity
    assert recovery._durable_inventory(case['args']['attempt_directory']) == case['args']['expected_artifacts']


@pytest.mark.parametrize('damage', [
    'unreviewed-producer', 'command-returned', 'bool-command-returned', 'checks-executed',
    'wrong-error-type', 'wrong-error-text', 'failure-extra', 'lifecycle-extra', 'signals',
    'watchdog', 'barrier-attempted', 'barrier-released', 'missing-event', 'extra-event',
    'nonboolean-event', 'owner-not-opened', 'child-not-created', 'owner-exit-incomplete',
    'unattached-child', 'no-native-grant', 'native-not-released', 'additional-observed-child',
    'parent-schema', 'parent-error', 'source-open', 'native-open', 'child-not-reaped',
    'no-genuine-wait', 'source-drift', 'clock-renewed', 'clock-exhausted', 'wrong-budget',
    'active-live', 'resampled-live', 'wrong-observed-count', 'request-bytes', 'elapsed-zero',
])
def test_before_barrier_capacity_refuses_changed_historical_frames_before_owner_access(
        setup, monkeypatch, damage):
    case = _before_barrier_capacity_fixture(setup, monkeypatch)
    terminal, parent = case['terminal'], case['parent']
    failure, lifecycle = terminal['failure'], terminal['source_custody_lifecycle']
    events = lifecycle['events']
    if damage == 'unreviewed-producer':
        # Every fictional document hash still agrees: only the known-selector
        # predicate is changed, rather than an earlier broken digest join.
        monkeypatch.setattr(recovery, '_REVIEWED_BEFORE_BARRIER_PRODUCER_SHA256', 'f' * 64)
    elif damage == 'command-returned': failure['returncode'] = 1
    elif damage == 'bool-command-returned': failure['returncode'] = False
    elif damage == 'checks-executed': failure['executed_checks'] = case['request']['selected_checks']
    elif damage == 'wrong-error-type': failure['error_type'] = 'RuntimeError'
    elif damage == 'wrong-error-text': failure['error'] = 'another capacity observation'
    elif damage == 'failure-extra': failure['unselected'] = True
    elif damage == 'lifecycle-extra': lifecycle['unselected'] = True
    elif damage == 'signals': failure['received_signals'] = [15]
    elif damage == 'watchdog': failure['watchdog_errors'] = ['unresolved']
    elif damage == 'barrier-attempted': events['barrier_release_attempted'] = True
    elif damage == 'barrier-released': events['barrier_released'] = True
    elif damage == 'missing-event': del events['child_created']
    elif damage == 'extra-event': events['unknown_event'] = False
    elif damage == 'nonboolean-event': events['owner_open_returned'] = 1
    elif damage == 'owner-not-opened': events['owner_open_returned'] = False
    elif damage == 'child-not-created': events['child_created'] = False
    elif damage == 'owner-exit-incomplete': events['owner_exit_handling_completed'] = False
    elif damage == 'unattached-child': lifecycle['owner_child_attached'] = False
    elif damage == 'no-native-grant': lifecycle['native_grant']['status'] = 'unknown'
    elif damage == 'native-not-released': terminal['reservation']['resource_lease']['released'] = False
    elif damage == 'additional-observed-child':
        terminal['reservation']['process_observation']['observed_identities'].append(case['extra_identity'])
        parent['actual_observed_identity_count'] = 2
    elif damage == 'parent-schema': parent['schema'] = 'sampled-recovery-owned-validation-observation/v1'
    elif damage == 'parent-error': parent['errors'] = [{'stage': 'uncertain'}]
    elif damage == 'source-open': parent['source_custody_closed'] = False
    elif damage == 'native-open': parent['original_native_compute_closed'] = False
    elif damage == 'child-not-reaped': parent['child_reaped'] = False
    elif damage == 'no-genuine-wait': parent['genuine_wait_completed'] = False
    elif damage == 'source-drift': parent['source_pins_unchanged'] = False
    elif damage == 'clock-renewed': parent['closing_source_READ_clock_renewed'] = True
    elif damage == 'clock-exhausted': parent['closing_source_READ_elapsed_seconds'] = 3.0
    elif damage == 'wrong-budget':
        case['request']['timeout_seconds'] = 121
        _before_barrier_rebind_fictional_request(case)
    elif damage == 'active-live': terminal['reservation']['live_inventory_profile']['live_exception_active'] = True
    elif damage == 'resampled-live': terminal['reservation']['live_inventory_profile']['complete_resamples_observed'] = 1
    elif damage == 'wrong-observed-count': parent['actual_observed_identity_count'] = 2
    elif damage == 'request-bytes': parent['request']['bytes'] += 1
    elif damage == 'elapsed-zero': failure['elapsed_seconds'] = 0
    else: raise AssertionError(damage)
    _sampled_seal(case)
    before = case['ledger'].read_bytes()
    def forbidden(*args, **kwargs):
        raise AssertionError('invalid before-barrier evidence reached owner construction')
    monkeypatch.setattr(recovery.resources, 'DaemonResourceReservation', forbidden)
    with pytest.raises(recovery.resources.DaemonResourceError):
        _sampled_inspect(case)
    assert case['ledger'].read_bytes() == before and case['scheduler_calls'] == []


@pytest.mark.parametrize('damage', ['live-owner', 'live-child', 'native-request', 'native-descendant', 'artifact-change', 'current-record-change', 'foreign-record-during-census'])
def test_before_barrier_capacity_keeps_current_native_process_and_artifact_guards(
        setup, monkeypatch, damage):
    case = _before_barrier_capacity_fixture(setup, monkeypatch)
    if damage == 'live-owner':
        pid = case['row']['owner_pid']
        case['process_table'][pid] = SimpleNamespace(pid=pid)
    elif damage == 'live-child':
        pid = case['row']['child']['pid']
        case['process_table'][pid] = SimpleNamespace(pid=pid)
    elif damage == 'native-request':
        case['scheduler_state']['waiters']['unselected-key'] = {'request_id': 'validation:' + case['args']['reservation_id']}
    elif damage == 'native-descendant':
        case['scheduler_state']['leases']['e' * 32] = {'parent_lease_id': case['row']['native_lease_id']}
    elif damage == 'current-record-change':
        data = json.loads(case['ledger'].read_bytes())
        data['reservations'][case['args']['reservation_id']]['retention_reason'] = 'external change'
        case['ledger'].write_text(json.dumps(data))
    elif damage == 'foreign-record-during-census':
        original_census = recovery._administrative_census
        injected = []
        def mutate_foreign(helper, state):
            report = original_census(helper, state)
            if not injected:
                changed = json.loads(case['ledger'].read_bytes())
                changed['reservations'][case['prior_id']]['retention_reason'] = 'external foreign change'
                case['ledger'].write_text(json.dumps(changed))
                injected.append(_sampled_copy(changed['reservations'][case['prior_id']]))
            return report
        monkeypatch.setattr(recovery, '_administrative_census', mutate_foreign)
    else:
        (case['args']['attempt_directory'] / 'failure.json').write_text('changed artifact')
    before = case['ledger'].read_bytes()
    with pytest.raises(recovery.resources.DaemonResourceError):
        _sampled_reconcile(case, 'administrative_closeout')
    if damage == 'foreign-record-during-census':
        after = json.loads(case['ledger'].read_bytes())
        assert injected and after['reservations'][case['prior_id']] == injected[0]
        assert after['reservations'][case['args']['reservation_id']] == json.loads(before)['reservations'][case['args']['reservation_id']]
        assert after['limit_bytes'] == json.loads(before)['limit_bytes']
    else:
        assert case['ledger'].read_bytes() == before
        assert json.loads(before)['reservations'][case['prior_id']] == case['prior']


@pytest.mark.parametrize('shape', ['unchanged-postbarrier', 'undispatched-frame-with-open-barrier'])
def test_before_barrier_capacity_does_not_broaden_existing_postbarrier_profile(
        setup, monkeypatch, shape):
    case = _reviewed_producer_sampled_fixture(setup, monkeypatch)
    before = case['ledger'].read_bytes()
    if shape == 'unchanged-postbarrier':
        report = _sampled_inspect(case)
        assert report['ready'] is True
        assert report['proof']['original_command_returncode'] == 1
        assert 'original_failure_profile' not in report['proof']
        _sampled_assert_unchanged(case, before)
    else:
        case['terminal']['failure'].update(returncode=None, executed_checks=[],
            error_type='DaemonResourceError', error='storage reservation capacity exceeded')
        _sampled_seal(case)
        def forbidden(*args, **kwargs):
            raise AssertionError('open-barrier None result reached owner construction')
        monkeypatch.setattr(recovery.resources, 'DaemonResourceReservation', forbidden)
        with pytest.raises(recovery.resources.DaemonResourceError):
            _sampled_inspect(case)
        assert case['ledger'].read_bytes() == before and case['scheduler_calls'] == []


@pytest.mark.parametrize('write_completed', [False, True])
def test_before_barrier_capacity_receipt_write_failure_is_not_retried_or_rolled_back(
        setup, monkeypatch, write_completed):
    case = _before_barrier_capacity_fixture(setup, monkeypatch)
    original_write = recovery.resources.DaemonResourceReservation._write
    calls = []
    def fail(helper, state):
        calls.append('write')
        if write_completed:
            original_write(helper, state)
        raise OSError('selected before-barrier receipt write failure')
    monkeypatch.setattr(recovery.resources.DaemonResourceReservation, '_write', fail)
    before = case['ledger'].read_bytes()
    with pytest.raises(OSError, match='selected before-barrier receipt write failure'):
        _sampled_reconcile(case, 'administrative_closeout')
    assert calls == ['write']
    if write_completed:
        after = json.loads(case['ledger'].read_bytes())
        row = after['reservations'][case['args']['reservation_id']]
        assert row['status'] == 'released'
        assert row['explicit_reconciliation']['sampled_custody_proof']['original_command_returncode'] is None
        assert after['reservations'][case['prior_id']] == json.loads(before)['reservations'][case['prior_id']]
    else:
        assert case['ledger'].read_bytes() == before
    assert recovery._durable_inventory(case['args']['attempt_directory']) == case['args']['expected_artifacts']


# Fictional captured H documents exercise the finite parser; the producer hash
# selector is patched only for this authored fixture, never in production.
def _H16_V4_deadline_fixture(setup, monkeypatch):
    case = _sampled_validation_fixture(setup, monkeypatch)
    monkeypatch.setattr(recovery, '_REVIEWED_H16_V4_PRODUCER_SHA256', _sampled_sha(case['producer'].encode()))
    monkeypatch.setattr(recovery.resources, 'MAX_STORAGE_BYTES', 100_000_000)
    request, row, terminal, parent = case['request'], case['row'], case['terminal'], case['parent']
    budgets = dict(storage_bytes=16 * 1024**2, memory_mb=1536, cpu_slots=1, child_process_slots=2)
    request.update(budgets, schema='owned-validation-request/v4',
        live_inventory_profile=dict(schema='owned-validation-live-census/v1', max_complete_resamples=1))
    while len(request['source_sha256']) < 35:
        request['source_sha256'][str(case['args']['attempt_directory'].parent / ('fictional-buffer-' + str(len(request['source_sha256'])) + '.py'))] = 'c' * 64
    row.update(budgets)
    terminal['source_custody_lifecycle']['budgets'] = dict(budgets)
    terminal['reservation']['resource_lease'].update({key: budgets[key] for key in ('memory_mb', 'cpu_slots', 'child_process_slots')})
    terminal['reservation']['storage_limit_bytes'] = 100_000_000
    terminal['reservation']['process_observation']['observed_identities'] = terminal['reservation']['process_observation']['observed_identities'][:1]
    terminal['failure'].update(returncode=0, error_type='ValidationResourceError', error='validation run deadline exceeded')
    custody = parent['original_owner_custody']
    custody.update(retained_storage_bytes=budgets['storage_bytes'], actual_observed_identity_count=1)
    root = Path(terminal['source_custody_lifecycle']['producer']['path']).parents[3]
    owners = [dict(canonical_root=str(path), cooperative=True,
        lock_path=str(path / 'workspace/control-plane/source-leases/source.lock'), mode='read',
        schema_version='autoencoder-source-lease/v1', waited_seconds=0.001)
        for path in (root, root.parent / 'ipfs_accelerate')]
    parent.update(tag='postinstall276-live1', attempt_directory=request['attempt_directory'], source_pins=35,
        elapsed_seconds=174.0, tests_passed_not_inferred_from_owner_exit=True, cap_or_budget_changed=False,
        recovery_performed=False, parent_capture_bytes=1000, parent_capture_allowance_bytes=1024**2,
        actual_attempt_file_bytes=sum(x['bytes'] for x in case['args']['expected_artifacts']), source_receipts=owners)
    request_sha = _sampled_sha(_sampled_wire(request))
    row['validation_request_sha256'] = request_sha
    terminal['request_sha256'] = terminal['failure']['request_sha256'] = request_sha
    terminal['source_custody_lifecycle']['request_sha256'] = request_sha
    parent['request_sha256'] = request_sha
    terminal['reservation']['live_inventory_profile'] = dict(schema='owned-validation-live-census/v1',
        request_sha256=request_sha, live_exception_active=False, complete_resamples_observed=0,
        max_complete_resamples=1, resample_limit_scope='per_logical_live_census')
    terminal['reservation']['record'] = _sampled_copy(row)
    data = json.loads(case['ledger'].read_bytes())
    data['limit_bytes'] = 100_000_000
    data['reservations'][case['args']['reservation_id']] = row
    case['ledger'].write_text(json.dumps(data))
    _sampled_seal(case)
    return case


@pytest.mark.parametrize('operation', ['inspect', 'reconcile'])
def test_H16_V4_deadline_retains_completed_command_and_failed_owner(setup, monkeypatch, operation):
    case = _H16_V4_deadline_fixture(setup, monkeypatch)
    before = case['ledger'].read_bytes()
    if operation == 'inspect':
        report = _sampled_inspect(case)
        assert report['ready'] is True and report['state_written'] is False
        proof = report['proof']
        _sampled_assert_unchanged(case, before)
    else:
        report = _sampled_reconcile(case, 'administrative_closeout')
        proof = report['sampled_custody_proof']
        after = json.loads(case['ledger'].read_bytes())
        assert after['reservations'][case['args']['reservation_id']]['status'] == 'released'
        assert after['reservations'][case['prior_id']] == json.loads(before)['reservations'][case['prior_id']]
        assert report['outputs_deleted'] is report['native_release_performed'] is report['admitted'] is False
        assert recovery._durable_inventory(case['args']['attempt_directory']) == case['args']['expected_artifacts']
    assert proof['original_command_returncode'] == 0 and proof['original_cli_returncode'] == 1
    assert proof['original_failure_preserved'] is True
    assert proof['cryptographic_execution_attestation'] is proof['reconstructed_Popen_handle'] is False


@pytest.mark.parametrize('damage', [
    'producer', 'parent-extra', 'tag', 'pins', 'owner-zero', 'command-one', 'deadline-text',
    'capacity-error', 'bool-command', 'source-open', 'barrier-open', 'native-open',
    'live-active', 'live-resampled', 'source-owner', 'custody-extra',
])
def test_H16_V4_deadline_refuses_changed_finite_profile_before_owner_access(setup, monkeypatch, damage):
    case = _H16_V4_deadline_fixture(setup, monkeypatch)
    p, t = case['parent'], case['terminal']
    if damage == 'producer': monkeypatch.setattr(recovery, '_REVIEWED_H16_V4_PRODUCER_SHA256', 'f' * 64)
    elif damage == 'parent-extra': p['unselected'] = True
    elif damage == 'tag': p['tag'] = 'unselected-run'
    elif damage == 'pins': p['source_pins'] = 34
    elif damage == 'owner-zero': p['owner_returncode'] = p['original_owner_custody']['returncode'] = 0
    elif damage == 'command-one': t['failure']['returncode'] = 1
    elif damage == 'deadline-text': t['failure']['error'] = 'different finalization failure'
    elif damage == 'capacity-error': t['failure']['error_type'] = 'DaemonResourceError'
    elif damage == 'bool-command': t['failure']['returncode'] = False
    elif damage == 'source-open': p['source_closed'] = False
    elif damage == 'barrier-open': t['source_custody_lifecycle']['events']['barrier_released'] = False
    elif damage == 'native-open': p['original_owner_custody']['original_native_compute_closed'] = False
    elif damage == 'live-active': t['reservation']['live_inventory_profile']['live_exception_active'] = True
    elif damage == 'live-resampled': t['reservation']['live_inventory_profile']['complete_resamples_observed'] = 1
    elif damage == 'source-owner': p['source_receipts'][0]['cooperative'] = False
    elif damage == 'custody-extra': p['original_owner_custody']['unselected'] = True
    else: raise AssertionError(damage)
    _sampled_seal(case)
    before = case['ledger'].read_bytes()
    def forbidden(*args, **kwargs):
        raise AssertionError('invalid H16 V4 profile reached current owner construction')
    monkeypatch.setattr(recovery.resources, 'DaemonResourceReservation', forbidden)
    with pytest.raises(recovery.resources.DaemonResourceError):
        _sampled_inspect(case)
    assert case['ledger'].read_bytes() == before and case['scheduler_calls'] == []


def _direct_tool_quota_fixture(setup, monkeypatch, *, large_population=False, nested_population=False):
    """Fictional journal/producer DATA; never a real Tool/Popen/native attestation."""
    import base64
    if large_population:
        # Configure only this fresh private fixture, before its ledger or grants exist.
        assert not setup[2].exists()
        monkeypatch.setattr(recovery.resources, 'MAX_STORAGE_BYTES', 2_000_000)
    case = _sampled_validation_fixture(setup, monkeypatch)
    root = case['args']['roots'][0];attempt = case['args']['attempt_directory']
    if nested_population:
        for relative in ('proof/file', 'proof-next/file'):
            target = attempt / relative
            target.parent.mkdir()
            target.write_bytes(b'nested inventory order')
    promise = 1000000 if large_population else 100000
    (attempt/'overrun.bin').write_bytes(b'x'*(promise+1))
    if large_population:
        for number in range(4097): (attempt/('empty-%05d'%number)).write_bytes(b'')
    data = json.loads(case['ledger'].read_bytes());row = data['reservations'][case['args']['reservation_id']]
    row['storage_bytes'] = promise;case['request']['storage_bytes'] = promise
    request_raw = _sampled_wire(case['request']);request_sha = _sampled_sha(request_raw)
    row['validation_request_sha256'] = request_sha;case['row'] = row
    case['ledger'].write_text(json.dumps(data));terminal = case['terminal']
    terminal['request_sha256'] = request_sha;terminal['reservation']['record'] = _sampled_copy(row)
    life = terminal['source_custody_lifecycle'];life['request_sha256'] = request_sha;life['budgets']['storage_bytes'] = promise
    # This profile is one original attached child, not arbitrary history.
    terminal['reservation']['process_observation']['observed_identities'] = terminal['reservation']['process_observation']['observed_identities'][:1]
    failure = terminal['failure'];failure['request_sha256'] = request_sha;failure['returncode'] = 0
    failure['watchdog_errors'] = [recovery._DIRECT_TOOL_QUOTA_WATCHDOG]
    failure['error'] = 'validation cancelled: '+repr(failure['watchdog_errors']);failure['error_type'] = 'RuntimeError'
    failure['process_observation'] = _sampled_copy(terminal['reservation']['process_observation'])
    evidence = root/'direct-tool-evidence';evidence.mkdir()
    def store(name, raw):
        p=evidence/name;p.write_bytes(raw);p.chmod(0o600)
        return dict(path=str(p),bytes=len(raw),sha256=_sampled_sha(raw))
    stdout_raw=_sampled_wire(terminal);stderr_raw=b'Fictional quota owner EXIT1 traceback; never executed.\n'
    refs=dict(request=store('request.json',request_raw),stdout=store('owner.stdout',stdout_raw),
        stderr=store('owner.stderr',stderr_raw),producer=dict(path=life['producer']['path'],bytes=len(case['producer'].encode()),sha256=life['producer']['sha256']))
    prefix='exec env '+recovery._DIRECT_TOOL_VALIDATION_ENV+' '+case['request']['argv'][0]+' -I -B '+refs['producer']['path']+' --request '
    suffix=' --resource-ledger '+str(case['ledger'])+' > '+refs['stdout']['path']+' 2> '+refs['stderr']['path']
    launch_input=('const r=await tools.exec_command({cmd:'+json.dumps(prefix)+'+ref.path+'
        +json.dumps(' --expected-request-sha256 ')+'+ref.sha256+'+json.dumps(suffix)
        +',"yield_time_ms":1000,"max_output_tokens":1000});text(r);store("fictional",r);\n')
    # Explicit test-only source contract; never a real provider-source commitment.
    monkeypatch.setattr(recovery, '_DIRECT_TOOL_QUOTA_LAUNCH_INPUT_SHA256', _sampled_sha(launch_input.encode()))
    payloads=[dict(type='custom_tool_call',call_id='fixture-launch',name='exec',input=launch_input),
        dict(type='custom_tool_call_output',call_id='fixture-launch',output=[
            dict(type='input_text',text=json.dumps(dict(exit_code=0,output=json.dumps(refs['request'])+'\n'))),
            dict(type='input_text',text=json.dumps(dict(session_id=101,output='')))]),
        dict(type='custom_tool_call',call_id='fixture-wait',name='exec',input='tools.write_stdin({session_id:101,chars:"",yield_time_ms:1000,max_output_tokens:1000})'),
        dict(type='custom_tool_call_output',call_id='fixture-wait',output=[dict(type='input_text',text=json.dumps(dict(exit_code=1,output='')))])]
    entries=[];blocks=[];offset=0
    for number,payload in enumerate(payloads):
        raw=(_sampled_wire(dict(timestamp='fictional-%d'%number,type='response_item',payload=payload))+b'\n')
        entries.append(dict(bytes=len(raw),call_id=payload['call_id'],journal_byte_offset=offset,
            raw_record_base64=base64.b64encode(raw).decode(),sha256=_sampled_sha(raw),timestamp='fictional-%d'%number,type=payload['type']))
        offset+=len(raw);blocks.append(raw)
    journal_file=evidence/'fictional-journal.jsonl';journal_file.write_bytes(b''.join(blocks));journal_file.chmod(0o600);ji=journal_file.stat()
    journal=dict(schema='historical-original-Tool-invocation-wait-journal-DATA/v1',
        provenance='Existing local provider response journal; historical Tool DATA only',
        original_thread_id='fictional-engineering-fixture-never-executed',source_journal_path=str(journal_file),
        Tool_session_id=101,request_sha256=request_sha,reconstructed_Python_Popen=False,
        actual_a0b_parent_verification=False,source_native_or_storage_release_authority=False,
        retroactive_full367_qualification=False,records=entries,
        source_range=dict(offset=0,bytes=offset,device=ji.st_dev,inode=ji.st_ino,first_file_size=offset,last_file_size=offset,may_append=True,reread_exact=True))
    refs['tool_journal']=store('journal-DATA.json',_sampled_wire(journal))
    proof=dict(schema=recovery._DIRECT_TOOL_QUOTA_SCHEMA,provenance='selected_original_direct_Tool_DATA/v1',
        request_raw_utf8=request_raw.decode(),owner_stdout_raw_utf8=stdout_raw.decode(),
        owner_stderr_raw_utf8=stderr_raw.decode(),producer_source_utf8=case['producer'],
        tool_journal_raw_utf8=_sampled_wire(journal).decode(),refs=refs)
    inventory=recovery._durable_inventory(attempt);metadata=[]
    for p in sorted(attempt.rglob('*')):
        if p.is_dir():continue
        info=p.lstat();metadata.append(dict(path=str(p),ordinary_regular=True,
            identity={key:getattr(info,key)for key in ('st_dev','st_ino','st_mode','st_uid','st_gid','st_nlink','st_size','st_mtime_ns','st_ctime_ns')}))
    snapshot=dict(schema='native-full367-retained-inventory-and-selected-runtime-fresh-source/v1',Source_READ_closed=True,
        no_claim_or_artifact_mutation=True,all_entries_ordinary_regular=True,retained_file_entries=len(inventory),
        retained_apparent_bytes=sum(r['bytes']for r in inventory),retained_attempt_metadata_inventory=metadata,
        own_full367_reservation=dict(reservation_id=case['args']['reservation_id'],record=_sampled_copy(row)))
    proof_raw=_sampled_wire(proof);snapshot_raw=_sampled_wire(snapshot)
    case['direct_proof']=proof;case['direct_snapshot']=snapshot
    case['direct_args']=dict(roots=case['args']['roots'],reservation_id=case['args']['reservation_id'],
        expected_record_sha256=recovery._digest(row),attempt_directory=attempt,expected_artifacts=inventory,
        proof_raw=proof_raw,expected_proof_sha256=_sampled_sha(proof_raw),retained_snapshot_raw=snapshot_raw,
        expected_retained_snapshot_sha256=_sampled_sha(snapshot_raw),artifacts_durable=True,
        artifact_inventory_manifest=store('inventory.json',_sampled_wire(dict(schema='retained-artifact-inventory/v1',attempt_directory=row['attempt_directory'],artifacts=inventory))),
        evidence_archive=store('proof-archive.json',proof_raw))
    return case


def _direct_tool_quota_call(case):
    native=recovery.resources.native_deadlines
    if native.resource_operation_deadline() is not None:
        return recovery.reconcile_direct_tool_quota_validation_reservation_v1(case['ledger'],**case['direct_args'])
    with native.resource_cleanup_deadline(native_deadline_monotonic=recovery.resources.time.monotonic()+240):
        return recovery.reconcile_direct_tool_quota_validation_reservation_v1(case['ledger'],**case['direct_args'])


def test_direct_tool_quota_closeout_keeps_violation_and_descriptor_inventory(setup, monkeypatch):
    case=_direct_tool_quota_fixture(setup,monkeypatch);old=case['ledger'].read_bytes()
    receipt=_direct_tool_quota_call(case);after=json.loads(case['ledger'].read_bytes());row=after['reservations'][case['direct_args']['reservation_id']]
    assert row['status']=='released' and row['storage_bytes']==100000
    assert row['attempt_exceeded_reservation'] is True and row['final_attempt_bytes']>row['storage_bytes']
    assert after['reservations'][case['prior_id']]==case['prior']
    assert 'artifacts' not in receipt and receipt['artifact_count']==len(case['direct_args']['expected_artifacts'])
    assert receipt['artifact_inventory_manifest']==case['direct_args']['artifact_inventory_manifest']
    assert receipt['historical_Tool_custody']['reconstructed_Popen_handle'] is False
    assert receipt['historical_Tool_custody']['actual_a0b_parent_verification'] is False
    assert receipt['cap_changed'] is receipt['request_budget_changed'] is receipt['native_release_performed'] is False
    assert receipt['retroactive_qualification_claimed'] is receipt['admitted'] is False
    assert recovery._durable_inventory(case['args']['attempt_directory'])==case['direct_args']['expected_artifacts']


def test_direct_tool_quota_inventory_can_exceed_old4096_without_expanding_hot_ledger(setup, monkeypatch):
    case=_direct_tool_quota_fixture(setup,monkeypatch,large_population=True)
    initial=json.loads(case['ledger'].read_bytes())
    assert initial['limit_bytes']==recovery.resources.MAX_STORAGE_BYTES==2_000_000
    assert initial['reservations'][case['direct_args']['reservation_id']]['storage_bytes']==1_000_000
    before=len(case['ledger'].read_bytes());ceiling=before+16000
    monkeypatch.setattr(recovery.resources,'MAX_LEDGER_BYTES',ceiling)  # Smaller fictional metadata bound; never a production cap raise.
    receipt=_direct_tool_quota_call(case)
    assert receipt['artifact_count']>4096 and len(case['ledger'].read_bytes())<ceiling
    assert len(_sampled_wire(case['direct_args']['expected_artifacts']))>ceiling
    final=json.loads(case['ledger'].read_bytes())
    assert final['limit_bytes']==initial['limit_bytes']==recovery.resources.MAX_STORAGE_BYTES==2_000_000
    assert final['reservations'][case['direct_args']['reservation_id']]['storage_bytes']==initial['reservations'][case['direct_args']['reservation_id']]['storage_bytes']==1_000_000


@pytest.mark.parametrize('mutation',['fake-popen','nonquota-watchdog','body-failed','nochild','wrong-scheduler','live-owner','native-present','manifest-drift','journal-rewrite','tool-session','inventory-drop','foreign-during-census'])
def test_direct_tool_quota_refuses_unknown_or_unclosed_scope_without_write(setup,monkeypatch,mutation):
    case=_direct_tool_quota_fixture(setup,monkeypatch);before=case['ledger'].read_bytes();args=case['direct_args'];proof=case['direct_proof']
    terminal=json.loads(proof['owner_stdout_raw_utf8'])
    if mutation=='fake-popen':
        journal=json.loads(proof['tool_journal_raw_utf8']);journal['reconstructed_Python_Popen']=True
        raw=_sampled_wire(journal);proof['tool_journal_raw_utf8']=raw.decode();proof['refs']['tool_journal']['bytes']=len(raw);proof['refs']['tool_journal']['sha256']=_sampled_sha(raw)
    elif mutation=='tool-session':
        journal=json.loads(proof['tool_journal_raw_utf8']);journal['Tool_session_id']=102
        raw=_sampled_wire(journal);proof['tool_journal_raw_utf8']=raw.decode();proof['refs']['tool_journal']['bytes']=len(raw);proof['refs']['tool_journal']['sha256']=_sampled_sha(raw)
    elif mutation=='journal-rewrite':
        journal=json.loads(proof['tool_journal_raw_utf8']);p=Path(journal['source_journal_path']);raw=p.read_bytes();p.write_bytes(b'!'+raw[1:])
    elif mutation=='inventory-drop':args['expected_artifacts']=args['expected_artifacts'][:-1]
    elif mutation=='foreign-during-census':
        original=recovery._administrative_census
        def altered(helper,ledger):
            ledger['reservations'][case['prior_id']]['owner_pid']+=1
            return original(helper,ledger)
        monkeypatch.setattr(recovery,'_administrative_census',altered)
    elif mutation=='nonquota-watchdog':terminal['failure']['watchdog_errors'].append('unknown failure')
    elif mutation=='body-failed':terminal['failure']['returncode']=1
    elif mutation=='nochild':terminal['reservation']['record']['child']=None
    elif mutation=='wrong-scheduler':
        req=json.loads(proof['request_raw_utf8']);req['scheduler_state_path']+='.wrong'
        raw=_sampled_wire(req);proof['request_raw_utf8']=raw.decode();proof['refs']['request']['bytes']=len(raw);proof['refs']['request']['sha256']=_sampled_sha(raw)
    elif mutation=='live-owner':case['process_table'][case['row']['owner_pid']]={'birth':case['row']['owner_birth']}
    elif mutation=='native-present':case['scheduler_state']['leases'][case['row']['native_lease_id']]={'lease_id':case['row']['native_lease_id'],'request_id':'validation:'+case['row']['reservation_id'],'parent_lease_id':None}
    else:
        Path(args['artifact_inventory_manifest']['path']).write_bytes(b'{}')
    if mutation in ('nonquota-watchdog','body-failed','nochild'):
        raw=_sampled_wire(terminal);proof['owner_stdout_raw_utf8']=raw.decode();proof['refs']['stdout']['bytes']=len(raw);proof['refs']['stdout']['sha256']=_sampled_sha(raw)
    if mutation in ('fake-popen','tool-session','nonquota-watchdog','body-failed','nochild','wrong-scheduler'):
        raw=_sampled_wire(proof);args['proof_raw']=raw;args['expected_proof_sha256']=_sampled_sha(raw)
        Path(args['evidence_archive']['path']).write_bytes(raw);args['evidence_archive']['bytes']=len(raw);args['evidence_archive']['sha256']=_sampled_sha(raw)
    with pytest.raises((recovery.resources.DaemonResourceError,KeyError,TypeError)):
        _direct_tool_quota_call(case)
    assert case['ledger'].read_bytes()==before



def _direct_tool_quota_reseal_journal(case, mutate):
    """Rebind fictional journal bytes without granting real Tool provenance."""
    import base64
    journal = json.loads(case['direct_proof']['tool_journal_raw_utf8'])
    events = [json.loads(base64.b64decode(row['raw_record_base64'])) for row in journal['records']]
    mutate(events)
    raw_events = [_sampled_wire(event) + b'\n' for event in events]
    offset = 0
    for row, raw, event in zip(journal['records'], raw_events, events):
        row.update(journal_byte_offset=offset, bytes=len(raw), sha256=_sampled_sha(raw),
                   raw_record_base64=base64.b64encode(raw).decode())
        offset += len(raw)
    path = Path(journal['source_journal_path'])
    path.write_bytes(b''.join(raw_events))
    journal['source_range'].update(first_file_size=offset, last_file_size=offset, bytes=offset)
    encoded = _sampled_wire(journal)
    proof = case['direct_proof']
    proof['tool_journal_raw_utf8'] = encoded.decode()
    proof['refs']['tool_journal'].update(bytes=len(encoded), sha256=_sampled_sha(encoded))
    raw = _sampled_wire(proof)
    args = case['direct_args']
    args.update(proof_raw=raw, expected_proof_sha256=_sampled_sha(raw))
    archive = args['evidence_archive']
    Path(archive['path']).write_bytes(raw)
    archive.update(bytes=len(raw), sha256=_sampled_sha(raw))


def test_direct_tool_quota_rejects_wrong_ref_prefix_even_when_journal_and_tail_match(setup, monkeypatch):
    case = _direct_tool_quota_fixture(setup, monkeypatch)
    before = case['ledger'].read_bytes()
    def mutate(events):
        events[0]['payload']['input'] = 'ref={path:"/wrong/request",sha256:"wrong"};' + events[0]['payload']['input']
    _direct_tool_quota_reseal_journal(case, mutate)
    with pytest.raises(recovery.resources.DaemonResourceError, match='control source'):
        _direct_tool_quota_call(case)
    assert case['ledger'].read_bytes() == before


def test_direct_tool_journal_wrong_inode_closes_all_opened_descriptors(setup, monkeypatch):
    case = _direct_tool_quota_fixture(setup, monkeypatch)
    journal = json.loads(case['direct_proof']['tool_journal_raw_utf8'])
    journal['source_range']['inode'] += 1
    before = set(Path('/proc/self/fd').iterdir())
    with pytest.raises(recovery.resources.DaemonResourceError, match='journal identity'):
        with recovery._direct_tool_journal_descriptor(journal):
            pytest.fail('wrong journal identity opened')
    assert set(Path('/proc/self/fd').iterdir()) == before


def test_direct_tool_journal_named_replacement_during_range_read_is_refused(setup, monkeypatch):
    case = _direct_tool_quota_fixture(setup, monkeypatch)
    journal = json.loads(case['direct_proof']['tool_journal_raw_utf8'])
    path = Path(journal['source_journal_path'])
    original = recovery.os.pread
    replaced = []
    def replace_after_read(*args):
        value = original(*args)
        if not replaced:
            successor = path.with_name('fictional-journal-replacement.jsonl')
            successor.write_bytes(path.read_bytes())
            successor.replace(path)
            replaced.append(True)
        return value
    monkeypatch.setattr(recovery.os, 'pread', replace_after_read)
    before = case['ledger'].read_bytes()
    with pytest.raises(recovery.resources.DaemonResourceError, match='named entry replaced'):
        _direct_tool_quota_call(case)
    assert replaced == [True] and case['ledger'].read_bytes() == before


def test_direct_tool_journal_parent_alias_is_refused_without_open_leaf(setup, monkeypatch):
    case = _direct_tool_quota_fixture(setup, monkeypatch)
    journal = json.loads(case['direct_proof']['tool_journal_raw_utf8'])
    path = Path(journal['source_journal_path'])
    alias = path.parent.parent / 'journal-parent-alias'
    alias.symlink_to(path.parent, target_is_directory=True)
    journal['source_journal_path'] = str(alias / path.name)
    before = set(Path('/proc/self/fd').iterdir())
    try:
        with pytest.raises((OSError, recovery.resources.DaemonResourceError)):
            with recovery._direct_tool_journal_descriptor(journal):
                pytest.fail('journal parent alias accepted')
        assert set(Path('/proc/self/fd').iterdir()) == before
    finally:
        alias.unlink()


@pytest.mark.parametrize('mutation', ['none', 'fake-popen', 'lost-overrun', 'inline-artifacts', 'budget-reset', 'archive-inside-attempt'])
def test_direct_tool_quota_record_only_disposition_recognizes_exact_profile(setup, monkeypatch, mutation):
    case = _direct_tool_quota_fixture(setup, monkeypatch)
    _direct_tool_quota_call(case)
    data = json.loads(case['ledger'].read_bytes())
    row = data['reservations'][case['direct_args']['reservation_id']]
    receipt = row['explicit_reconciliation']
    if mutation == 'fake-popen': receipt['historical_Tool_custody']['reconstructed_Popen_handle'] = True
    elif mutation == 'lost-overrun': row['attempt_exceeded_reservation'] = False
    elif mutation == 'inline-artifacts': receipt['artifacts'] = case['direct_args']['expected_artifacts']
    elif mutation == 'budget-reset': receipt['original_storage_budget_bytes'] += 1
    elif mutation == 'archive-inside-attempt': receipt['artifact_inventory_manifest']['path'] = str(case['args']['attempt_directory'] / 'bad.json')
    case['ledger'].write_bytes(_sampled_wire(data))
    def inspect():
        return recovery.inspect_validation_disposition(case['ledger'],
            roots=case['args']['roots'], reservation_id=case['direct_args']['reservation_id'],
            expected_request_sha256=row['validation_request_sha256'],
            attempt_directory=case['args']['attempt_directory'],
            expected_record_sha256=recovery._digest(row),
            expected_previous_record_sha256=case['direct_args']['expected_record_sha256'],
            process_scope='sampled_birth_bound_descendants')
    if mutation == 'none':
        report = inspect()
        assert report['storage_release_established'] is True
        assert report['native_release_established'] is False
        assert report['release_evidence']['artifacts_reinventoried'] is False
        assert report['release_evidence']['test_or_task_acceptance_asserted'] is False
    else:
        with pytest.raises(recovery.resources.DaemonResourceError): inspect()


def test_direct_tool_quota_nested_inventory_uses_existing_Path_owner_order(setup, monkeypatch):
    case = _direct_tool_quota_fixture(setup, monkeypatch, nested_population=True)
    paths = [row['path'] for row in case['direct_args']['expected_artifacts']]
    assert paths == sorted(paths, key=Path)
    assert paths != sorted(paths)
    assert paths.index('proof/file') < paths.index('proof-next/file')
    receipt = _direct_tool_quota_call(case)
    post = json.loads(case['ledger'].read_bytes())['reservations'][case['direct_args']['reservation_id']]
    assert post['status'] == 'released' and post['artifacts_durable_asserted'] is True
    assert receipt['artifact_count'] == len(paths) and receipt['original_quota_violation_preserved'] is True
    assert recovery._durable_inventory(case['args']['attempt_directory']) == case['direct_args']['expected_artifacts']


@pytest.mark.parametrize('ordering', ['reversed', 'lexicographic'])
def test_direct_tool_quota_nested_inventory_refuses_reordering_without_write(setup, monkeypatch, ordering):
    case = _direct_tool_quota_fixture(setup, monkeypatch, nested_population=True)
    original = case['direct_args']['expected_artifacts']
    reordered = list(reversed(original)) if ordering == 'reversed' else sorted(original, key=lambda row: row['path'])
    assert reordered != original
    # Keep the detached descriptor consistent, so the negative tests input order itself.
    reference = case['direct_args']['artifact_inventory_manifest']
    manifest = json.loads(Path(reference['path']).read_bytes())
    manifest['artifacts'] = reordered
    raw = _sampled_wire(manifest)
    Path(reference['path']).write_bytes(raw)
    case['direct_args']['artifact_inventory_manifest'] = dict(path=reference['path'], bytes=len(raw), sha256=_sampled_sha(raw))
    case['direct_args']['expected_artifacts'] = reordered
    before = case['ledger'].read_bytes()
    with pytest.raises(recovery.resources.DaemonResourceError):
        _direct_tool_quota_call(case)
    assert case['ledger'].read_bytes() == before
    assert json.loads(before)['reservations'][case['direct_args']['reservation_id']]['status'] == 'retained'


def _sampled_source_held_v5_fixture(setup, monkeypatch):
    """Model the original failed command and closed Source reads with private controls."""
    case = _sampled_validation_fixture(setup, monkeypatch)
    monkeypatch.setattr(recovery, '_REVIEWED_SAMPLED_V5_PRODUCER_SHA256',
                        _sampled_sha(case['producer'].encode()), raising=False)
    request, row, terminal, parent = case['request'], case['row'], case['terminal'], case['parent']
    lifecycle, reservation = terminal['source_custody_lifecycle'], terminal['reservation']
    profile = {'schema': 'owned-validation-ordinary-scratch-live/v1'}
    request.update(schema='owned-validation-request/v5', ordinary_scratch_profile=profile)
    root = Path(request['cwd'])
    owner_dir = root / 'ipfs_datasets_py/optimizers/logic_theorem_optimizer'
    request['source_sha256'].update({str(owner_dir / name): 'c' * 64 for name in (
        'validation_run_resources.py', 'autoencoder_daemon_resources.py', 'resource_scheduler.py',
        'existing_resource_scheduler.py', 'proof_resource_safety.py')})
    request['source_sha256'][str(owner_dir / 'validation_run_resources.py')] = (
        '11e5110aa8dcf39c5b11c0bd06a6d02933052e917fa46bf6d53a5467107d6def')
    request_sha = _sampled_sha(_sampled_wire(request))
    row['validation_request_sha256'] = request_sha
    terminal['request_sha256'] = lifecycle['request_sha256'] = request_sha
    terminal['failure'].update(request_sha256=request_sha, error='validation command failed with returncode 1')
    reservation.update(record=_sampled_copy(row),
        enforcement='cooperative_admission_and_polled_usage_not_kernel_quota',
        ordinary_scratch_profile=dict(schema=profile['schema'], request_sha256=request_sha,
            ordinary_absences_observed=0, live_exception_active=False,
            unseen_leaf_ownership_attested=False, whole_census_resampling=False))
    parent.update(schema='source-held-owned-validation-v5-observation/v1', request_schema=request['schema'],
        ordinary_scratch_profile=_sampled_copy(profile), request_sha256=request_sha,
        state='ORIGINAL_OWNER_WAITED_SOURCE_CLOSED_STORAGE_SEPARATE',
        current_sampled_recovery_profile_qualified=False, automatic_retry_authorized=False,
        recovery_or_storage_release_authorized=False,
        native_and_source_exit_verified_before_parent_Source_close=True,
        original_source_READs=[dict(canonical_root=str(path), cooperative=True,
            lock_path=str(path / 'workspace/control-plane/source-leases/source.lock'), mode='read',
            schema_version='autoencoder-source-lease/v1', waited_seconds=0.001)
            for path in (root, root.parent / 'ipfs_accelerate')],
        actual_original_owner_argv=[request['argv'][0], '-B', lifecycle['producer']['path'],
            '--request', str(case['ledger'].parent / 'original-request.json'),
            '--expected-request-sha256', request_sha, '--resource-ledger', str(case['ledger'])])
    parent['original_owner_custody']['original_completed_result_verified'] = False
    ledger = json.loads(case['ledger'].read_bytes())
    ledger['reservations'][case['args']['reservation_id']] = row
    case['ledger'].write_text(json.dumps(ledger))
    _sampled_seal(case)
    return case


def test_sampled_source_held_v5_readiness_and_release_preserve_original_failure(setup, monkeypatch):
    case = _sampled_source_held_v5_fixture(setup, monkeypatch)
    before = case['ledger'].read_bytes()
    readiness = _sampled_inspect(case)
    assert readiness['ready'] is True
    assert readiness['state_written'] is readiness['recovery_performed'] is readiness['admitted'] is False
    _sampled_assert_unchanged(case, before)

    report = _sampled_reconcile(case, 'administrative_closeout')
    after = json.loads(case['ledger'].read_bytes())
    original = json.loads(before)
    selected = after['reservations'][case['args']['reservation_id']]
    assert selected['status'] == 'released' and selected['artifacts_durable_asserted'] is True
    assert after['reservations'][case['prior_id']] == original['reservations'][case['prior_id']]
    assert set(after['reservations']) == set(original['reservations'])
    assert after['roots'] == original['roots'] and after['limit_bytes'] == original['limit_bytes']
    assert report['native_release_performed'] is report['admitted'] is report['outputs_deleted'] is False
    assert case['scheduler_state'] == dict(leases={}, waiters={})
    assert recovery._durable_inventory(case['args']['attempt_directory']) == case['args']['expected_artifacts']
    for proof in (readiness['proof'], report['sampled_custody_proof']):
        assert proof['original_failure_profile'] == 'source-held-V5-retained-command-failure/v1'
        assert proof['original_command_returncode'] == proof['original_cli_returncode'] == 1
        assert proof['original_failure_preserved'] is True
        assert proof['cryptographic_execution_attestation'] is proof['reconstructed_Popen_handle'] is False


@pytest.mark.parametrize('path,value,error', [
    (('request', 'ordinary_scratch_profile'), {}, 'V5 request profile'),
    (('parent', 'schema'), 'sampled-recovery-owned-validation-observation/v1', 'V5 parent profile'),
    (('parent', 'source_closed'), False, 'Popen-verified parent closeout'),
    (('parent', 'source_drift'), ['/changed/source.py'], 'Popen-verified parent closeout'),
    (('parent', 'original_source_READs', 1, 'mode'), 'write', 'V5 Source READ owner'),
    (('parent', 'actual_original_owner_argv', 8), '/other/ledger.json', 'V5 owner invocation'),
    (('parent', 'native_and_source_exit_verified_before_parent_Source_close'), False, 'V5 parent profile'),
    (('parent', 'owner_pid'), 99999996, 'Popen-verified parent closeout'),
    (('parent', 'original_owner_custody', 'owner_birth'), '457', 'Popen-verified parent closeout'),
    (('parent', 'original_owner_custody', 'genuine_wait_completed'), False, 'Popen-verified parent closeout'),
    (('parent', 'original_owner_custody', 'child_reaped'), False, 'Popen-verified parent closeout'),
    (('parent', 'original_owner_custody', 'original_native_compute_closed'), False, 'Popen-verified parent closeout'),
    (('parent', 'original_owner_custody', 'original_terminal'), {}, 'Popen-verified parent closeout'),
    (('parent', 'original_owner_custody', 'storage_artifacts_durable_asserted'), True, 'Popen-verified parent closeout'),
    (('parent', 'original_owner_custody', 'storage_released_and_durable'), True, 'Popen-verified parent closeout'),
    (('parent', 'recovery_or_storage_release_authorized'), True, 'V5 parent profile'),
    (('terminal', 'failure', 'error'), 'unrelated failure', 'V5 retained command failure'),
    (('terminal', 'source_custody_lifecycle', 'owner_child_attached'), False, 'sampled lifecycle binding'),
    (('terminal', 'reservation', 'resource_lease', 'lease_id'), 'f' * 32, 'sampled native release binding'),
    (('terminal', 'reservation', 'resource_lease', 'released'), False, 'sampled native release binding'),
    (('terminal', 'reservation', 'resource_lease', 'gpu_memory_mb'), 1, 'V5 native release receipt'),
    (('terminal', 'reservation', 'ordinary_scratch_profile', 'live_exception_active'), True, 'V5 closed ordinary scratch'),
    (('terminal', 'reservation', 'ordinary_scratch_profile', 'ordinary_absences_observed'), True, 'V5 closed ordinary scratch'),
    (('terminal', 'reservation', 'ordinary_scratch_profile', 'request_sha256'), 'f' * 64, 'V5 closed ordinary scratch'),
])
def test_sampled_source_held_v5_rejects_resealed_wrong_custody_before_owner_access(
        setup, monkeypatch, path, value, error):
    case = _sampled_source_held_v5_fixture(setup, monkeypatch)
    target = case
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    _sampled_seal(case)
    before = case['ledger'].read_bytes()

    def forbidden(*args, **kwargs):
        raise AssertionError('invalid V5 custody reached current owner construction')

    monkeypatch.setattr(recovery.resources, 'DaemonResourceReservation', forbidden)
    with pytest.raises(recovery.resources.DaemonResourceError, match=error):
        _sampled_reconcile(case, 'administrative_closeout')
    assert case['scheduler_calls'] == []
    _sampled_assert_unchanged(case, before)


@pytest.mark.parametrize('damage,error', [
    ('parent-bytes', 'original parent closeout bytes differ'),
    ('producer-selection', 'V5 producer or source pins differ'),
    ('durability', 'explicit sampled artifact durability assertion required'),
    ('current-native', 'original sampled native lease or descendants remain'),
])
def test_sampled_source_held_v5_keeps_proof_and_live_release_guards(setup, monkeypatch, damage, error):
    case = _sampled_source_held_v5_fixture(setup, monkeypatch)
    if damage == 'parent-bytes':
        case['args']['expected_parent_closeout_sha256'] = 'f' * 64
    elif damage == 'producer-selection':
        monkeypatch.setattr(recovery, '_REVIEWED_SAMPLED_V5_PRODUCER_SHA256', 'f' * 64)
    elif damage == 'durability':
        case['args']['artifacts_durable'] = False
    else:
        lease_id = case['row']['native_lease_id']
        case['scheduler_state']['leases'][lease_id] = {'lease_id': lease_id}
    before = case['ledger'].read_bytes()
    with pytest.raises(recovery.resources.DaemonResourceError, match=error):
        _sampled_reconcile(case, 'administrative_closeout')
    _sampled_assert_unchanged(case, before)


@pytest.mark.parametrize('overrides', [{}, {'capacity_policy': 'require_capacity'}],
                         ids=['default', 'explicit-require-capacity'])
def test_sampled_source_held_v5_requires_explicit_administrative_closeout(
        setup, monkeypatch, overrides):
    from contextlib import nullcontext

    case = _sampled_source_held_v5_fixture(setup, monkeypatch)
    before = case['ledger'].read_bytes()

    def forbidden(*args, **kwargs):
        raise AssertionError('V5 capacity policy refusal reached live recovery')

    monkeypatch.setattr(recovery, '_sampled_open_scheduler', forbidden)
    monkeypatch.setattr(recovery, '_retained_reconciliation_engine', forbidden)
    native = recovery.resources.native_deadlines
    deadline = nullcontext()
    if native.resource_operation_deadline() is None:
        deadline = native.resource_cleanup_deadline(
            native_deadline_monotonic=recovery.resources.time.monotonic() + 240)
    with deadline, pytest.raises(recovery.resources.DaemonResourceError,
                                 match='original sampled V5 recovery requires administrative_closeout'):
        recovery.reconcile_sampled_validation_reservation_v1(
            case['ledger'], **case['args'], **overrides)
    assert case['scheduler_calls'] == []
    _sampled_assert_unchanged(case, before)


@pytest.mark.parametrize('error_text', [
    'validation command failed with returncode 0',
    'validation watchdog did not finish cleanly',
], ids=['zero-code-command-label', 'successful-body-watchdog-join'])
def test_sampled_source_held_v5_rejects_successful_body_finalization_failure_before_owner(
        setup, monkeypatch, error_text):
    case = _sampled_source_held_v5_fixture(setup, monkeypatch)
    case['terminal']['failure'].update(returncode=0, error_type='RuntimeError', error=error_text)
    case['parent']['original_owner_custody']['original_terminal'] = _sampled_copy(case['terminal'])
    _sampled_seal(case)
    before = case['ledger'].read_bytes()
    def forbidden(*args, **kwargs):
        raise AssertionError('unsupported V5 finalization failure reached a current resource owner')
    monkeypatch.setattr(recovery.resources, 'DaemonResourceReservation', forbidden)
    with pytest.raises(recovery.resources.DaemonResourceError, match='original V5 retained command failure differs'):
        _sampled_reconcile(case, 'administrative_closeout')
    assert case['scheduler_calls'] == []
    _sampled_assert_unchanged(case, before)


# Public source DATA captured from the real 280bf original CLI generation.
# It is never imported or executed. Process/native/Source custody below remains
# the explicit modeled historical premise of the original private-ledger fixture.
_SAMPLED_V5_PUBLIC_280_SOURCE_B85 = (
    'c-ri}Yj@k$wJ!W!zXDA@fQ%_xb{scR!j9Lml}4wI<s-@I?$Fl2fJjhcO#$2lX<0kfe}Cs?-7f$r$xeEzj=f_FSXlQp*StRS%RfC{'
    '*UQIev+{9Ken=MAtBb1qdh3fXzBpW$N%3(ppN(g$WVKw^t74LjFN*Q|I=PyyE|RJ&k}_Y-J`~A^d_J4N&#FxFa+1`mYMGxGNp)2g'
    '%i-46@x`o8>ilvshbk7!YFyOy_W80}FYvGFY+fW#psZF&p5R~gH8gga{Li{t<w><n##On>XXRy4u99lHl`qd`t7X2tP9{Y?F3L$>'
    'uIgd3ze>vDL$OTGm-ry5i%a--HpUuW7ddooayhGO=;RQ`w>4c>mr0gQ*Q@oi$g*U1xu}-Vg%UbKW2v{c<g?}ZB45^p{QDxWFXpo|'
    '`R70Ds+7Mk^VNm?UDe#k0-ix}*}_|+NIg3*^SS<OrP`>W6YBT+OiY`4a;<)@E|x_;nU&}2!R)fw+B!TqI8H{?SPw=C)0$=d;j*Z!'
    '`G=y{AHslOKI@aOPq((VCdD+V%Y0E^RI46#cK`$VIJ;b5j-Kp1efAapXOMg~Nb>o-y2^^n#p-(WQ$DYY{_a)+|C>#d)%Bw28SndY'
    'QO~Ms&ZY2w%Y0TB$*=i*UF<EF)v}iw-z1l?&yuqORsl9&KIV_pK7D;TE3ro~s2yz2{H%bUBu}Um_Fj$~fAhCf*aSS{WL75hLd*aR'
    '%lJ!9OJ8>wn!-`wdJK=U{i9d=hdohvjt^lj>s5AHO$y_q@JMInV!cWxvt==cBXW%sL|d{v$4v@{D6fl&7%iW%dN`d_i=ynoFZ!1k'
    '2mU(94qqL-dHs)n(eF10KOMY&eeier*P9<-AH4iqe~_fhv$UV&a2!^!O)hm0&kC560%i)^pmA`CA#Rnj>h=54893bgYmYxyBgg*h'
    'N9BB0zEA!%N}k|z{8p~r4<n;kJ^SARpNOs2HhX8)x|{$7S(jp_l4Wtep6APi=XF{9&l;vyP9Rru1tSy#!(-ADZ9RIT3+2-lP>r^U'
    'm`z~CXRy~s$vnS2o8(Eo+pBRHlj6gGe$2{>f8fCQ*CigttgQL3vG}Vm&kQusgFg0guAF&+iIYu=$)-~38TGnv6%&ulQna<jHtjbZ'
    'LY~6$MP8o6#9mz>Q5JMX%;&NILRsRJ3W9<2UDT3ZOlIfshiF60yGc>hm<911)))EHZ=TcehZn_1{=P@u=ig1;6>U>xP<%QqmbK{T'
    '2P_7yBUK*Gt9(*Z8?t$NJv=W~y|jkw>@tVrfjbn*LW(!mWLsZn+oGMvAD*Oemg29UHotz>{Q8@;ac$ORy<Q+`hm|p|TJgEPJT$z4'
    'u}XEdUXF|Ge4Q^RJ$ftJTFlBCrimV%q@oxvN_uJ$bu6i<`D6xES)6Ko(bRFpKN!8{hPZX-#4?fAn+ewh%MIaLysUdRO?I}Cb9?cX'
    'CGIWr(mGzk1hj6r@NoQ5i1V_Wq>p%y^PJBvFW0O546a<<grZC4-1GUM9XeTGF6y3Gwi*^WdtY4F)XxD-03PJgQ#pn*FU7SxEXpwu'
    '-d_LFS^D2)O0^<8w45#AYGG>TUKlSA_g)<H4YBuMFJJSozaRRy$ROFNp6~1gFCyItZ0W1W<svBP)e=@tpFZQwbiS@HdipWZ-s^H4'
    'roH0k)`QZwySl}_D-rJLy_d%ahtAlz#?|tA*KeHb5}R=b*Ua25HJ(>>p-M?Ah$k}}=ZhS6`gOJ}rt3PN_X^xI#4`c)JugOIFgJ|d'
    '|3d5n;6i_dZMR)ar^IERpTmWguL{_X`FUB@z`TCXUrV00tdjX`T8yv9K%Vn8FzYbG*F$7yy-~^2OBJZ&3-gPomur=D&+OYE`C<W0'
    'XY?pDyQ>ZcQySWb>cu56r&#4ENhSLayk@cdz~@Cy4{&wkqJUdGHT&74j?#?vhZ*ehOJvC5T&Az`;<73a3qEgj4pXZ$v@**?S1<%-'
    'T~n*o8iWokfH$rA9+{I46`kyyno}40LKntLdtxF6eV*o}7#6-0uewZUb*ATTB$`lL%y_A1v0N4Buwc_!F`pn^hs%tL6_YGq@RrTa'
    'u2)4(SJ8R}JD|kd9R#5HJTum+mc^`Iruk$t!`C?$ri%w^RuuvvT%MZ`=CjM$DqNG`1v4$`Wz%I*=x@aa(q{_J8D1md>fCDV!kWaO'
    'BmrWeIYVAUYIhF&df_5kPqAv4$+YipUt?9Q%QCcQ^75KL0$Oh!O}ql(8J<eBzEB-CurOAeu)}_nJPpp`7!EJ|_{!cI@W7slo9Hnx'
    'YCn+`w;qS!M|74abe6Z5;xKQ^S>HB3K}M@<e{gu4c89*9-XM{gWXq~r)mc@}uiaD9xNK&vuw1$qFxTFP`g<&~gA$MXeey%{^sBF)'
    'e{HV6y=?v4^#_;Qtkhomeiu@tPCFhMYdX77k<;*WJhB(2fw-LNkqaV|*z*^qbEnXXs?A_P_{<A3k&yV=+Zm|Zx9!?ZLT2>EpblP5'
    'dd8f(nknC@O;oHeZTd<(SUhUq^v%?i>T)Kfwa#XmOI7+4w0TbzIX;#9x#uq5Uy_~v#@)3@xvo2~rm^Z{eZhB;YC4@YS1!N{q{mcr'
    '<O`6Bf(oXS#8j&l<~`}Z17;&KBp9P0V<k$ABnxBJWK8JDymow{r7qwY<}f$)sFx1#D%wr^c4Y-Dz_Q5ldOVwnuUr8K4zChyY;B1Y'
    'ebV)6y8Uh1@5A&y+xhN!hxtW;WK|$b1q(E+R}&a;NJ<eO6KxgW5J?4^Od4)g&q%3o=v&;di&gStUKe}x6J}_4E7+y2t=IcM?Y;cR'
    '%h!9^(aWFretChsv$w?Zu3W=rn_O=z?w>BoOjoh@>)xB=qXbz1&ADee^b*8gW@wD(+!K6EodfbRn@_TNzAncX_DB3?3__WBaF#EZ'
    'GpJ`-z(rCQW@)a=DPS~Rd;}5!67yt^H^#U^g8+Vbvy~n1|FU=R?l}8tfA94x9){**CdGJ$dizYWG$~C%b_IJTLzS9-1bez#Rpo3f'
    'o^zKbMUHJ6uknjwo-d$(SzU~)a>8uvyc)mP&0OWMGnUzm#!w?wFUP7<LFL8Ud0rOs-)yyniIfv2?j)WqE{uJfWN>||`G+f+M7*r5'
    'uBdMxp<xn0ff_=i^SM=-{S26xX;$ac0!e0xdIz-_q(sloa9B9!i)8^61$xG9SntO9x-MWXSgg&eCEV-z@)~9X4l`_vvdVZf$br`v'
    'IUEnIaMDukTR7Z8fB)+@35vAeqowDc#aJk=prtxNt}FTVSppjY`9fkz5~@_#nWAznGd-+OarIIm{obEO&Dysp$7xjN&4(~uA^mCL'
    '_JxWqS_9pezXcg3IfmW90AzjJqCOxFABZm8bh&D9kr(-FS@%f0=6zDH=g89hW{U@cl^i7a5pk*b@vhf*SR}!5a!tFz(fKO2$r?3='
    'r~{FsOT_3TSC!B{N&Q=y8)9~PMEwd)0++I8p{&X&FlKNEWUUq)RW{l`TQszl&;z(d@epJ*@!3UHy&uufK|=OLpot}N)T@zdhc+*5'
    'pbl#)&KR-C#5wR0@!t;@)uL%j`(GHc+^AX8t-k#-d4X2E)iO`UK*@?F9(F$EGt~WZ#RFlrt>8cMT0Ofq$i>i{&lLAK@NXZ03Rci_'
    '*<(@_%f4<hQzx++ah&#<Y&wfr$@Uo8np)TjKo(F}912Ec{;uKUCpRubkWm*R^i}oL=AaB7QJ3&ov8dMg7VHY$3eZWur|=4c3oMg&'
    'b5H(I;t$+)`bIc}JNCRJyB1RY)dk)UvwDT5Pn_1t8umw8Cvat~^En*JZE7YF%_L{=*Z4wR2%>9z56G5@4%0P2P6$A>^&4Q+93DfP'
    '|DdoeXzub6Uh#tcqRV?*bY@$Y{{IYJg<Xrov2blXwhS)zOVll^Dde%msxny;Sr1uFGT{=CK>?^ub3XJ%tU7~hq1yD{kq?Nm;fD2o'
    'PXmPvu7^Y_`@q@dU7m<OcvF?J@|t0ylDN6uX|gz|)(!;uEB#ftyP=X+{nmCo2{UG_n?XHH)2E8rJhkMGP=VwxqhzP4F3rVqWvFMw'
    'V)LSmm4em&`l(eXOjQpx4zP&}G`J_}&XcEKKl|qSpTGSsKN|yaNQpVH%7kn8>b3hT^jC1YXK2@%!tJ^0Q(5$_8O~~PS=%3Y?0}*4'
    '>UEbFy2=Xue(bo0s--nDse{+VX>6Z5?FLrc+|&_fUmdUJ4_E?Fh0(%gikJs~f3tU(y?OD=-VtffH95%O<Y$st*2Bd$PFcQQReaqn'
    'GgkdNMWh%dP0#Wg5Z}xDA&Zva^QB+YLBn^_HkT=JIg6UXQCxvNf;W=5eB_-|Tp~BZXQf)s&XH&vmh8uto0}F^+U@Gv0cez<o7UrW'
    'wwTs1Nh=_St2$d;Kd#^|zJ%*?SwEgv=eUn9ifUP0X6i+{C6%*iL5G@7(AX4n_v#Oluh6#IQ*A#+1$dv13I4)!5?<?m2WJ4Kh$eGA'
    '%1dON^-LS&oHZ*|xBH#E2h`+i+b7L=lP^JFz2&A5uY^h^yPB;^xJG+a<-oLB4wN^AxFm^%mw%99-PMw3(3e3{ATtR}{WPD=K@=t{'
    'a76iGvPkSSC<lvH*lqlZ{2!O7#|LKad*pp`ARgMylJ18|u_(w{K<z_vJ#;tLP;abZWMe5u$cFQaHvbFg-<=v7`UhLK{TdmAV?Kwp'
    '8@2?~K3R{+SF3TaQ(;>9nlwprZBV;K{u;oA)8&m?9qs{cp}>3RRuOtE>0K49kW{G1=bxP3D6bYgVFT7`(1m2x+Y5AXAe_v0wG)-O'
    '@A@X|hN_o=Q)75oy4GgOsBQqa+UWRo&A2Uwk~c-SMW6<Y*`%k5fyL*!yg>YOA=!_FTXAOhh2F+YZ#FZqU?tqyY`MCCi`-PqTZ$&V'
    'i%xL;P#~lg?DZuNs)~jLDLf;z8G<#+eR4X?7kF}eM1&tDC|$xoA%}>*aPr~X8+rp%lds?)C^D0}QW=bsZ*uM=-uCi#8*v-rTN+aM'
    ')M*JJv1EW<>?f~<K{KTw!Jgq6dLFLX*e=ADNs3pASVIy3%zZ(gylTEuc$~@aJi&=7vIm8`Xj2(gFCsGj>AHLm5=1Gl5kX^xK81%f'
    'GRBKmD}0uo!udwi>Uxo}6~!pT8bs^0X%SJXbav?Z-(n)fb$RisPsM7P9w2opv~2RhuAzWASg=(U)i6a#+lJ(CJP%UTF0QuuHWiJ?'
    'TdN)#6_E=+iPzFIDS7qc_{I0hOnTijC8*_$ZHqw}UP`VBcDP=^PAYm$gBuwNG(+X#>M9LGY12%d`Wg|3#5H`Lp@s^t;8E8G)fZCe'
    '5o!z5sOK7i^wwmSabz+UruvF*!qIOjUI#!l<P*HonAhBmyGW|ChMT1A6nUfDqRoK~&G4EF6JL6Hs)%Z|7{5NfG55YnIz}OSLOdB?'
    'Qu^4A^iN$G$k*sGfm1R<4uNYko*JvIcn%mE9^oPrGbtH&`93q=o;toqiwZc@>rBnK_!c-<Qpjn>CbLVr^^lTf*V3?{`KemI$E}ZV'
    '#(9Z?B2Yi0j4_YG43{bXekA(hy})$>s<>FMYFS47X?E*u4U+~XeuHaMj*Bi}TdrQLvwB{w$ar=MJmT^?yFAl&L#d)tWu(bmIA`5h'
    'Tbhfarb~9rdT4f!IqVUgB*|?z8W~41{@dB;LI(@8mgCxq4arZ<i%NecZaTVh#9mq>|7YER%G@TN$}4QwzQCMq;a%su`ug|oKDxfJ'
    'YsRFSyj?xwe+Dic9*KWR-hX?zm;Lqd#hc^o<%_p3UhW_NBRkyt>D|$b*G*RH#j;?9ZO|pbs1&18Hmi_N?>6cvVs-Al`YQ;lKOVe$'
    '^XgW0<7Tw#-pX|C%CPPm+qadmJ#N|F()0M{-7i1x9SR%$efVbH$tSbT5A#My%dTUydBOE;`B=84W!e{G;)|8eUkSI`*I9W6%j-!R'
    'gfIjQIVF_!U@o*=EB!b9nf+JL0kX->b1UjbYWWCta7t}+M7`PSV7x}7g?K|QR5;SDur>Mau9aq8xAcpYc5-(E819f*#(9k%kULv3'
    'Uq*e`xYZc9&=1LuaTA5)zR2#l>nipmQ`qFei1X@Bf&S8RFr=yJM{ID~4GV332Au%5RyB{ZR`9ysGQ{{hQlCc3BlIuG`)W0)>%aJy'
    ';OJT8x<Cz(`m)7m5_W>oWspd9&n!z}q#vV^no*Qyn`*MGEArsPJr*0xJmTYKuf*{8?d{@cIQOB?+WjDT^6`@%Eg;e)eAMsM3)c;F'
    'q+DVn)4v_u2K_F5kGB<DMcrDPA8udVeZVOQRf2a5N@avp8{bk>tRx#|MFOg07!B|fhPC1a2-GM~k(Z2Nwm`?e$N6|%txJrBrEbb7'
    'Um&jVXk0BP<h;sJ`!urQ7S;Pgx@b@UHput$d2(Kq>seXM@zZ<(O~L+n`FfviNb6;O25(?qFnk`qm_SEa#D7x>`9d2yP&bm#E|rP|'
    '2fkWf6Wy0l`MCXrpJ8%QEQ_HW@V|*RJ7x}(J@{3<mtMDrg&oJELrHK?soSspL-#s1m3mkMDOCd=zwXDiRwlC3+=iiC()XHWCfK9}'
    'nx^y<+@jV4u_t4SVO`Ky6zX@LY!;joK3GAHOTK~;dyIdSO_|Q~b3e=ipQ32YRSt<N)MhNb3>u^N<o8DcHeS)AQ4;puHDzwEgEv06'
    'pyuGqWRILM727>s0(V!VtPSTsQ^W#IZxcx?GG4eWOW^ICeVt`>xj{vcU?fsIE9F{Rry-J)YB4J&kA*AwHc0@5RE-Zrb+d9jUlX0i'
    '6&2m!aD3qY*X6iaqOFU&0K|i^IjHxuNx=k(Y`{Yq_$?3MWrbQ7;pWYMuvxP4EDba9q13f2Jq{kAyBKR9w;99j=8Qn&k==<QM&pt_'
    'pxOSeRL5*3W2=g9D#HzE50d#(XC7VW9I=V1YOi!_JNk=;tviL)C!Q1e*_LI)<1+BOJqR|bFXCQ+EZVz49E1T8(1ATun^YtYTDTsy'
    'R7hH;*zEbdIs=9uF=?2*sEI|Y1&@)?U_snZSvDM3G~;AJ`V-qmHR6I{0h_`s$*GZ+cs0)rYhgGU{ARSP>Vyf(th$8ZlZeeASuOK1'
    'okci*eZ|>8HT2>vAHUBsjx;CK2`+AsbIbLc=r5KSuFf)QVK}A!;1_1+h}(7xikT(g6?;y%0v1DazOvY4>5&eB)eQHoZx|SPE>y9y'
    '_{e;Rx>iSOhN1z#0+2<m3kZ#ZvWw89X045UIdB<y$^SNO1v4(0FW^;0bJ)`~CukpI?LxJZd_l^Z0iz_}Ejl18M01=E6!)A<&n1&V'
    'XfwezH6$m=70^kR4+O3Gf^4_Sh<5z);=i(^<AcK&f8EP|{KxU$QNt1#Ks0e<xm*fWSUP|S7REB0V>jYP^+w})LpP@}*M&b>t_$%R'
    'ntc>D_XrV=KFXHM2Dny*x2Z2jZMn&#*~bh8TjHSvUz^^iF)!>-#=cgfc))5$%w^~0ycu{VG)F+~H<@7i(gs5oGZ>CM>DoJnC4jJh'
    'jX3`**i3(AGM9nZw#i1mFeW2JNJp9q#w<8Qt+aZ}rKzU*O`1~NujLFN5SM4=5A@VF*o0k|*tI|ExkRtGy1Ffi%1p1NsIA&JrHGqq'
    'TWUi%_MywB*M>Q<il_%z8Gj>WU*<j(?Tv&|Bxpt+Ssr}Sf@u3@kOj{)7#fe=wUB;-iW-dsA?Yh8(|GhoG&&BA8X%c{cqSs=$QEK~'
    'Yu++!4>@K?I6*VCIN3iCsvAaEWPqsJ46hL0lf1iS@PZDl7|-*%o=s;3BDc+}D;A;%MG<6-f;BTxW1dJmG<?fqUrjC0DW9(A$<eF7'
    'B^0@|T%)$<F~u@1hoW~yGF~qUzXvt|ivL)AQjjbp6@0j#G?Lj2RWeHv1qdI^p`E3p4w6P7)8LaY&p(ji>q-P{&Y8{TXu?#V89_Y_'
    '>yNaw8nK`@Q{>sVwdGsa5;1!FCU{n~lg-`u942L+qo<RMPRLO3B^)WF$F=ZzHZ0<UB<!bPRNCr`fTXDsJ&nXd-B=#L-Az}wi^qJH'
    'HrPMnVT+-VMeTdp5U+^bwD5qA1uHfMD&m|q1}BQZMCn6lMJD=DiSdZUrf5W~6aVMv;EmP*e3B5v;JV~zz;CUg*EmF<HDtXRy)(m5'
    'c9I_`6a`=Sq5UA*U~K=E>nlp7p`$?aP$kk!AEz87lK%I{ot;!dTX|uiWZIz3fa<o#DFbiL5!7p?aRBiw4Cz0^v@gL!RfQ){c29>j'
    'tpAFd?f3g?3WWdEMiU?hPfoqhpKXQQV&ST6j=RwXs4B%C6T0q5n_0rKj;2&89QpZ`A5*7ZjBMf?iFds5h9fF)LhafjD!ppVUY^8S'
    'x1*<8OJh%-G+AFQ-dSEZ?mc7T6e6`z({H&bTeHoy4Es8t)hq8<)N~GjSV!Ha!#hhHlI3jC>pNQw>ihP|cTc+<8CNZ0k<wOJ6M@^I'
    'u7?wEzE1l@VX#!RM8lehiNsk@1jzIuupQQzH3;6w!JD+-)HL0j`gHL%8aPb!BD}of)em^`)oR*=)S7fI-*2JB#Lx-oNBqJsPx?QU'
    '#H&gi4h*g{2r9l9E_w41aeaj3(o$B=i|L925oYHXD@FjuX7TZWANKWA`WxlT>B>_~V))8Oen-ZWa(!7W(KT4i4wm6Y<P4nb(l?D8'
    'LoBjhpMWc*wS!7T+Qq(#f@1Et`Kr>bci4`mFN^lCw8^RamPo2~nviGMRRf_Ffd3M=Vg_!39FI&Y`6;a~7sQ{UEKKo?XB<pN;sNn^'
    ')j4`zh6$?ZQY$BVs&=ziPv<IdxF@Hv?;Y1qx+DaKd`9YujPRf{0|P$ovM!2RI(|m-k}!N{{^EEkc{f035g{xZIA+0sXNBPv^z`XY'
    'wzH%Dzj66oX~vJI^**;_Yvc7u+7&B-UH$rbpnrlh>g*xiNaLhwy)n$vjE$5^K^X>#mOLhDx3T8QLm0g#E#adzw9;Y^#n5a@A#V%y'
    '(qRX@i-R?-#=L{<-8TT17X&aU=TQPI`=Qy=Oe7~f7{u8Ze#1PnjvlzA+OWKCGhIi6)9t^M)2&iDpvf<QbY;C)h*t{W2%USlpy$)m'
    '>dcb_by}V?kMyPRVmzgiW;*+bSv9ooL;zh#O_0XrWylmD>PSI_=I5m`K&eH6HM%TTIc{hUT!wFJ8*hUT8lk(BUH*H<STfynS??rl'
    '`?XLZseosp5#wPXQYk_*_lKm3Vp~?RT+OB|9&6-c<@=*teg=tlFkuf5^wvNTc8sy>tKZ25=uQ?ES6)9{mq;Xq#IB=z<q?n?N?p;q'
    '%s;@!!G#w578jJhBHh*b4}q}%?+3!R+vxty0$lIOrWd-5es_DEa29Pfve~9a=OQCZW9k{=LXKpSE7Ef)GjH9S_RuEVFxJHmrVF=N'
    '!h#`7e_)H0X?XfA5YE=!?$l~;(v?dy7~5Vos;lMvsg9L|bv3;^Pj*rJ<Afo4Gf;di#%ryI8J(OC#46w|D!T2=h*e{7%2Y%!Z!G-+'
    'GYNs1SfHd2mpn`ps;yNtv;y!@synzuVe5myr9#8m>L&lR_%z1=hrtcoMfm{)eqnz5KFJf_SC21%H$nzzjxH0LgF#yKSa1{j2g3$q'
    'RBG=yc%XyA2C1A8_-V}${4EwJ^=@2aqd~FY_JZf`)`CZ|ZRJKJ$w>=ZcJ#|=T#_u(#nux#rOov@^J#gJEM{fUP1mg8y&4t+d=Ui{'
    'I>9b0<Gb+6>Q5qz;dvwJ54=^f$~FnUk`y?OSi0)yYQxdhrOeG_!~00vwz~;Lm{&N(fhwR|ko)-5D%dcx_p=fub<w`PiMITd7_e*s'
    'rw)RI;F?BBdnl^~HetnMBj#Rvy`gB<c%6LdlP|N-U3F-oA+}Wo{94zei5qY2Kxx2HD{L8XQsOv5giCTWrcs$TFuXGu8TgAC5k-Ya'
    'i=GaQ{tQx+qo78KUC>mD?|Z{)L}=UQp7034C`<^HPR#t;1TI$^7V8twWl-=j)Q;`G7%VP4zxqKy!$4`vfw6Dlw0Wf^oiVpf-$ZL;'
    'cNE;a4Z*r59Kvq&{*v2)Y7^_r&Rg7o6n*GsE2p#b^-{j_d@0<kjI0b$+CbO~!tUufMe`xGp}=GY=|wf4n6emb1Q4BP^#v(=K4Z|W'
    '8L2Mjpeg2-CYWmi>1w{N@nFbs3gJh1P3{Dd8uZefO1E!wZ6BpW8wfP;wVK9L`*zgDnr7Gjs8RV|PAjdf4eleph7h}!HzMU#q>YGq'
    '75N7;i2Q4fA};<omp>@yB>%+xiQ)s1aFPF#=@;E?fxQdv3Vs1|i`|Mw0)2Gjls~HQ<d2-lWm?4}fxOI`So}nd_LNgR%4a;vQ<Ym&'
    'y}&tYj~*7&+iO3wcRHl@h2&aX3~NLb+*21dY%&afsaZE1O)yrpZFDqI&v(Kxt?sa?urg}-$eqUPz*L-W1#M%E)r9)+sPoti@Jsef'
    'lt3gCycWjAY_SR|xRpu9zF{3i#IjJBg)*6Dn<s|>wC`=rV48vZ@34qB`-OnoEoJzJr$X-D{!lE@8*;*aP-Nyn!zJZEgb5Z^XpIVd'
    'oR>m1ixGXu7U09MvYb`fLU!bT5SnSdn$3;em*e+n_0wiuSKE!+lLigAn;PvF%5u|&D*6)$qceM|PasaUeC4s8Xe;hX#5z$3Mw8KH'
    'm1Qup6LbU_jcjh=L|W?}n{5u4#bTb1iynJvp%d1rN)-u<$5S}E)eJ-fc~i3ik!Je#5rIw7duBs5Y;yD(w6@F;$mE1x^^5`Y42V_G'
    'AG<4Iyc@DT0?#c+jj6GTi|Vd6muOHlCJmju*BypG$a6_=v=d`wr!2ip-mBokP?xtXB|4YJQD#}gIQ@@a@Bg|7vey57w|8``te9Ps'
    '9@w?)zd@Di!Qnp|>xsI$$-0gYU%dR=-Ycl&;O$-~PYAyb3Nbo(cldHId%OSU2x|disl}u~8R-|{S9b93`0cx6i3L5njRT58vqXE`'
    'z;FT|@yhX=0sYYuwJS}Z@*>c?N>pzI_F`{M8euu0$IIDMpsNi;V2(ysh2av-yHM9}g@S&74{)9OUa!N&xK=bI-JM)@3SgEed1%EO'
    '%kip?1kN0PfUe5ynA|vVv5LgB^-O!9SPmm#Yy*#2Tjk`*<B@L-G8{|{YPr)|FD?JCcHi1T;%RG)SOl+pCfQTv>8}FvK@dcyg=^&E'
    'BA}7ouWo#`N<2BJ^gi{AIlWcITWSw>sq4pWp201jH%()>4kvqLXqqGGBdqOaXk&JLpXtT~GhSGoHS4=^#<_8{yUC7=S{WRi_5cX3'
    '+isFBfQAsA$>%Jj@ZE>tS`Ep^K9v~rAQn7`1rK7ugILh^(ZS)X{WmX&l|OuO{PO3`M1*hB4mG|#Jostf$Ok&wB<tUU*zh1WJctdS'
    'No<Jc^6Vlwv?N}<Ptm~@5E9*Z4&Rq!OD@=I;q3;PAE7Ra5)GD9cAu^<W()EylkQzt7u8(ybdr$-4(N9lA{vJM3HkVww)yH(MQlRv'
    'MU3by9XOB@@##cCp-nijD{Gk}Em6c~Lb?z3w>;!d%N+j4MD2tTkk$ABwetbB^FB~JC$sv!aPvrLUzrgFEnuCl8-R`68F~8v<N0}E'
    'JnLdUeazta7NRG`@GwDPKOk5#VILM1El_nbfyd-oGLYnDu|6X-3-am*LLq34I^`PC^8v*30mQR2h^N?sI#XF2P$qvs`k$*M#*Iu!'
    '1*DxE5lw(A^~0_H{SZWxo*eMMCorgs@cG-#o!~v2F*iNXp3i~<swE1y4obT%9hHF~vnwVu0X~8dPt}Rhvr`iWlwNm02}M*zXpn28'
    '6WI}wwegVRo=PN!=n3yh-A^@E;{@UtJah+2Q!GF3M5~zXZfHB>H-Jd8-=I|!KGUSpci^jPgt5SoBOA-ft=pE-<+gP_zb%^Xgqd~q'
    '03C>Et`;{>BafN%>@>5O$!GmR$bXW<za*W-2^qkHek@5!@6$S1nvriU4r?PTNn5Cd1;A-L#*O?vCd#D!f$wE!7nkqNRE)j{pZ$%_'
    'oU($?tW7PVm>L{rove=L1~jf#h2a}@<TgF(U0L)$61(>SE%)=I<pyG3nvinM^Zfvp`$q=Lb#K6tMQ%D`<(hQ-0VnrA9w%2gr1NoM'
    'vtvVq(q;aU(leRK1cQLD@Z}69`G3tMht|hzLZpGIzc~O;vI#dn0*{Uovdk^w@yH7iGNT7fNB9VLNbPUaBv@u!3(7A7PNk8TL>9cK'
    'Uw!rb>lTozjVGxe463ldkqNi-qu_kFZ6l~w>sMB1PL(MxSlxDeb@qa5qe;kE5Za-CAftg!<TG2=E8a>8a^tS)z)<K7AC&Q*Q5i4g'
    '$b5NDdf}d>jmJHj(C*UNvj+VKmHfY*O8!Aj{r`}fnhx544HQyN?5xynDydVaeGX-`7)C_XEX*$tislDJ^Y5f+W<HEZGvGrf{?fW<'
    'DicsW4`c!QET)?#R!p*2;szXvt#3^u6ioYeAA|~#J`TT=&<>j3`4z{t;VIrZAp9<`(?nWB&Axjnwb2VrUV<`ZG`$hZg$P0m_R)Ih'
    '*6w$j?o!=pu0Pl*ex<N0RAT6~-`FI7c4B|R>KNuUj29q&tGakJz8VpqI_MmzpyXNt2}xlti5H_(2$S{YqVCCEQUhO^VIcX4CH%Tr'
    '<V$pqtVg|cfTGcE+8;Cnz0%2@&#NoAEK8x}MWnm`F4MluXwanmi&!EW@nUXcmvAIcLxOkYsu3ZRBbuTuU5!+-GKourxyl9>N}v?n'
    'R2?9qg+EIy!E96Ic$+T4(pm*O@SrMxP?dikRe2o5se{U#PSb<V{Ew|OZ=}_h27N<tO>-AKB%XUvsGACPk-_bnh^r|TW_Aq$JWS%0'
    'zcO#`NYo^E6;84INhjHa0kuLdL$+u{+$8rzkpx`irBk}hvf8Et_85K$$3wxlNTBiYysD8U5?;@xGSlly(8U=i6z`*4x<xOR1%cGp'
    'C{%EwJe~DUgj#T}J8?#81xSvm?&|ef4f}Sz62SLzQ%Ltnv9v?z(KXdZ-je0{0DoL!U<bN(!K&mnb1q`{17*V_F)qX`*6b+xzJwW0'
    'J`_vb`nDgnd?{`iQD&412>v>g^B|*SMb}afRTif*jMZurl+33ZCWmI>NK?u(j9Ec<jhUltF>-IH*Ig2<txNK0E&Y9xXi!Th$W(|x'
    'Mi>vQI15i!&K<MF52NJC&eLaK;eWQ0U{;OD;qU@a)K?dIeStBVT+V85cu{;5DH+I?6sucRO4l+hyqU($s4p-90sB=b37_K;BtXr>'
    '(Th)HR)z5Er_HaQHNXDGG&oTryOC#4BVOVzEtq+?unl_)(&Y7mVdqU*JwxkY?fOmeu>!Ra%4eq>qegE6-BG*Q!uj>2^>A6Sbz<1E'
    '{g%3VUGQn0?Fmz*bAK?i9Ff9-ux<hg9XoOT&{>LJZDx!bNe9uA!&#lFyexg6SSa}-UW1f3IB6_tD*7(<us?A*Q{hP2(#{-t$euF~'
    '7C50%-B9=o%FJ@s3vw3Zbb5AeXyH~hzS=*;a8_6_*|e@yBwfV3u`Z<|YSl6n{uFqePUXZub$Amf9>}uAtEZSJ$_P5tT#~g(jOVZ;'
    'CdGJmna@M}L0n>zy|UWWk5Sm&33b*x-pYYNzj0DG`Z1ygB(}}aYkcg)g)UDtcDaLAp2XnFL&AcIU7j?6m%C%v6sD2bwjz)78W>2~'
    'cC=~3oxK&#%qXiO*;x7>I9UnxbT>_Lzu(l;1{89I@z4fAt^+NMGy@KFiq>`n(7vM}<AY8Z<>oEz!I7)Y9K;Ckg!paW`k&1q!ltKD'
    '4DLjtE{Be!hT&H5+gmY=amH&-6d-qEBXTEU>~yUM5%Ao8{R*!;aRIyg{y@bbHPo?VhF6^k>$ZZKaa5hRK9_DqJeQn%k+fC2rpzl8'
    'SGy+pzG<$|T!YhYm-NOONB1LCaYU2h*(yALon$6mRa027amT4Pq@26BYSFAbJbRABq!hfmHkQ!nKYdS%vU+bd&_UPRC>e-4J{6K~'
    'WHn6hBSrS4VaOwUA&~-OU;MjG%(hii2vC2MlVnw<lhKH-1ze`mj@5`7bc#4_laZuDdr@_$(@ti?wV#}ZCPXq>0T};i^;ak`PO9@v'
    'XfzwDhn<5VB=zhZu0vHanhDJOnqqqH#6*N`nW>kQhulOX33<|fKelt-6d`K&`iT|H9qd{xO-u21Y#ZM`SA%VYi!N}h6)u#k;UtZ4'
    'VBN-GULTDzUdJg>`Bmq6DG#Nl6dfn_s#?Csr5E3i^Aba&K)Bwxrj{HQaVEm#V8o5Hnf2#WSb&=Iu`5SL&xtWSD(%!5J6-BK!P%Yq'
    'QeL3QsLlKGHa(ZsM?5h-c0rb>rMt6drawOpJLz}>sBQ!~-_t=P@p8+U!j&Of5aL}L{_BpX0JmY4x~GPeqr=hh!QqR)?g>wahI3`H'
    '{NiB6Y?1C1r!B0o6c>WkcC%1+Y~UnRM*trwT#F^jh|b=N0rZxJ(B{J#>$eUUQKvQ#`P-aqHJUFqJ_46onf6;{sA5}=VWyI*Y|T{*'
    'p)+EziqCC#qt$&V76M_94@w1ADtJlLKDR=lJ;wAwr|_Utc+e?4=oGpmq&=t-9#jbrs)Pqs!h<T|KS-4jMc&a2nak^*Hn>6Fm-uai'
    'YCMSE52E*fmgpT1qj(U(g$Ul9WBhj#$eSWq9whPyiTpt#e~`%AP*NU*@&}>(K`4I^${&RC|5%~CE#lwh&0<{eX$%kG-sJR9$nJx<'
    '{vfXZhluM3e}4mKs!2lsGC97$T&8rrNVZx8y5O``F!K4ez<`l?`X(rQ=cNk6b!z<Z<nf26iM+{%)B-FHV&o~Qizc_`RImARK7&Up'
    'bE|{p_oakX93)qm*a$i!uq=?0aWpRlqvp84$rbiZQn#T`NGwDV1h6t=eSDUxznOlalUl)1BZOpsA^B_lg0tgpsUG;liSagd5Vf9A'
    'jeat?yUG7;WZ6}m=uE<-b|Rfg`k+MkV<{0@WOzbOlP{Q+)e^J3!J6Xi=s3CpEuC{Ex(-@`@d5&$-$YaZY&bSzU?=97?3|6k62n=|'
    'S0Z9B^uo*}2Iohr$1we;-^O|o$O741uc-3dC*M7Fy6jB)X@l^tJ~Ec2SsFCN{d<T9{3N2jz)v0doPFd381S#w0g%t7bi!Q0-K3L7'
    '@K;$67di>iQ!Rhc)FZ1D?TV--x=h}nl5IHXjg8*imxysEaYEPfAW%FA6rWF^*hKN|X_#MQ<;QIM4(XTgPvPy=q^Yr?n(eB7ZtZ28'
    'E_xF!aR4S^V<w^FRpIHZqMEAP2`esen~4u900wxo%G&s`V<=VHQ5r1M;Y{VXrRFH-ZS6LAwuX9G1d<xfdR#4vkoDEk9fqVPi&_|B'
    'l#61Z>5Bnk;KHEXlZo_x1*@)7Re$T&Qp{Z>m}cqaQ%EbHOjP+Y*)J!>qA2k`pft}!aga!8tSq7UP)-Xg#1#Y9Tcm{8+EC`%7|Q5r'
    '>L7rzX9fR*Q?g#o=38#gl0`m#k9P^-h!ZF5dU4?4Y4GfbvBbA<21x_h+M<5}tbeoTK37V+PkwBIw~}x&gY}k)`$QqifQtK$(x0B3'
    '653Dr3O>QZL&*ZnKEU}|%=2;4ONTgRkAZeO!EB3s2{e_bdUUH9il*yGLk$t!`(4r+G^HR2HCO`;ga+*`H=NGO3BBqW6A<9a%}U%A'
    'Gu{pP#NlaR(0esjhc)|TIZ=APBLnp!TU=b%WW$@zK4P|ag!4t}I!NCB{EwskmoHvtKkfh5@w-ELuY`1tdYhjZ^L487E`$ai#sF*S'
    'RXCSG>$ED(sLsx0vKsmF`~&G(u9(9H9(8PMRP5^`pdxXSQ5v_mkxr?&1a>03JfpT2>#Uwvs}L~~c1FcgaIuY86RKuXjORIK)GR)('
    'iY0ROXzar11)8KV-=a;$WRHxhffe_lKUh@r+4$Pv*p`*(d2Bshg)m9+m^X{*x?C7{MFK?E0X96LT9}_e(rF<(+9iG%B_WNnFV@Xq'
    '_AOoj9}E#~ZPDv14HB0UTBBw}c>E;&?~gk>DNzm>GJZ^xKtJGt)z!eJ#unAaKJg}suLNVzff5bCe&QQ{-^CSa8tSg$V;k(w(?B!*'
    '86(mvWms6w3RE?<&<3Bx34g4%-Z;sDESP=Yb0M~qW2#@HK418;UbYB8{#4WXVxT5;SE$x3M=-LX`jZ^i@D`d;ui@}t!R=OE1++s3'
    'KHZt=$)c-|+dU%Rnw@F+*!nKoYcn&OH{;gg!E^?!S3JMFvFpvB_}!=v-&S}*cI6&E;lEGq722iaNV~i5tQNl#JH8+C@Quxi)W)?S'
    'n0{98MFWNqAs#zB%Y}Ex?Y!qYc!)ta^H~{k9t;{^oh&cSkfuRrGo{mE8#c^sUX%Y5;TWmg6g4n)jRkP%(f)Nw>tK6TIXZ+-r(3;~'
    'QuV$ys-Hxi+QAI6nF&N|aY81Ld$E7`#t+BoN*O%@MF|QLCIVBUpJ!U<88MV}wvxExPPY9O{4LzwLDJH<n|_;0%T>;W?iiIQDtM-Y'
    '2;(ZrQpo-F#8p=c2pIe*{LWD3*)Q94Y;O6mLaV)2**T^2<9=y~TZ3MDCBt{Wu2v8)TnJ6Hy!VUctP;z$EXuh0JV3B5zug8k`ex3m'
    'Tg^1za{#$ZXo%}B<LkCh9mn3?G<mei3R{|GR*4(NK_Lw8np!?jR6Gr^Ew*5|t26kvh>)SW$bos+@?OSt&C)e_H{zFk)3Q*GhqQGV'
    'L+|3=(_Yo8Z&s!D({QI_OCOM8jQq!ux3b~D>l4;qH*E;1W-uGl&s@#8p;9nEaNhXMh08Hxlp{T#uvtO)>rRS#T$Ga>Z`=l>(}^<F'
    'G<ixJWn3-lZ>GA&Rpf+qHMaJr6K|tB;AixXWc!XQEleux)fQ<{FO>Yts36>wafJuwQ7;MExJ)+5_F@Pu9lh~aOFTCH6(}!xK3++g'
    'Mut8Qv{nvr)awWppc;+DY%*vhA5+qliB1t9D>gq1w%ouBq3p#;#NEF2M2%jbPX|de&F@E9`-p!>Fe9B~+O(yJ-BvMU11FKYJBawy'
    '+gLqCwZ*fo7#pKLB3+|O3pp@E!oKxEzFf_wu-<hxSuaVAn%D5rD#|f_UO$U&J{A}&w^$`VLWw>4X=U0GeHNL7L<T9NlQM4*c15bb'
    'vJX%G0J)<uf$G_;oB;37d6>w3Tc(lv@C4I5iOfLqXm7*fZu3~A%4R5YDK%y*YR**DB}<X)LOfj&c3_dumNjXV?X<@j&`J4?w;Vz|'
    'P>N&vD3HDeskKlxb3Lwa5Iz$Z09E2{4KAVQs4Azk5(@S*vy0vosB(G^#6~d2t8~JoME7=OL=7+1`lOCmiBwSq|7_>G=ic!bT6;Lm'
    'HKs1_q1iK{iub;yHt33YOc^`z5???~@}pjg<b#Z<!(pn@lc)+$p6s3uYuJ-3YF4TeaO}dQztPCGy#c!P{MlBB#~5GaOQ2bZTTmwH'
    '&XcEKKl|qSpTGSsKN~}{9ARaZp$c`s40qgc-#T>dYj&SCh6rK_y;aTpZ?UYhfTZO%`em|*SFUlI1!I`JdU5;$b&)`7DgFcMz~pIA'
    'XEjaEfJa$jTI`{Dh@ELQ^CTm)!7u*AYI$KEJ6~3C=`HJ^!Hu-5Vi0WeTgpVYq^1!0=%iL@Rs?Io+rOG-+!9r3mItl|*6KZ~IQZ(l'
    'ajaotS?pVrDibIA#2CbBe5aj=L7#dyFZHGqW4;ySO{ohZ{*E3KzoN0$2F+9Jvlmp&iBUtCCA0W&{>EdL^<(VSj_rco)GJ5t=9v=x'
    'rqt8Bw`8nhXxBN0(T0Kn1&dpM({>Fv)c8evi_QTEZBVxe?No8o+;0*<gRr$`>ARn-e_OuAtv&Tr?4!+7P;HQXN|}As#omH`)ttr<'
    '7{s%G!si+BMcGAFy&uuf0Xy5ULp>(SRosTV;(@G(xAzO#(pE*=KjfbLL2l;<(#7vXH__4mV-tUmo2`IKr=v%pf$?xheNd>L)`@Y6'
    'kF|G2CAb?-`@vTs?}Em<!Wz`RNmM%PO2rY{+=b>|U1#pyW9D{FGWYHr<NCz#R&SgoT?Q`>n`}E>lO^2_sT$<8+7eP=7St!vo;$A4'
    'HZgQY;FWb&-0K!O-<jK&{HIwALZKd=vUOiwuWS-p74U^nB*JyjyQ}`y*c57W`s!3Q1BMp#hvey3Up@cYV#dA_JqytJeth1QwmfqE'
    'SS8q{9Q)3S%*zG)`M|~`3V$X@a<$~)&Z~2m@Um=*?zD}Tfk!0EK1#@w5=V(Y2DDtpN~x|nYxEg1N`9(rk{f1{wAb}M@<`r2h2*Er'
    '9{DK~N46!6bcPgg?C3QteM1W3ty=|VH|<$30DH>_NHPPlyT<DpVM~fDi$+_S=Oh%S6$vRX=J^6uxCVdfdShARaNMno<K-YnhPR1*'
    'dQ?Po8&l{3*E#Xjw>vRyQQR9uZCfSX35-<dOl64WRHa)EU2I;g-6QPF75rWbufJy2Im;0W30FgU*`!+y@%_$D!s`v_%?#5jPhpd;'
    'm>syxNt_hA;)bucK363CEyEhWO#W6B3$iX~ZN7BX+ny9Tx*rwNo&ZFpUd>7%EEL+2qmgE@5U4a?CX1?GZL@KdDCRby#;{1dO(_Qi'
    'yiCG)sL*V_((TIDhC+?Xe@VLxlF=Ye0&NHh!}vn>{gwFKiJSGI8svFZqZiCyA~#+lwpvxHKH<Scdq>*5&n*D1=3VaXoa8Tx&vCgj'
    'v8!;l+4xEr*~T=rLsm4*hdHZ_5SOj66!FRKmWo31uMLy*Lv)U;TB7Rs<|Q-lS8qF_5D;7e_fr1EvBIA$PI${y;Y(%AeZ~lT3a3D<'
    'u<yqeixA$rH!$UU3liQKb;<u=V@$-T%k4d4A$Gt(q>Jo!4z7L-Rm`pSW+Ug<aQB-5NTgvq>XxI?G(At3T_X24U7Bt3ylLqBr*n3{'
    't*^V>WQ`u~${{=A;C}DE?H!PO@kCiK9h&UWPM79xnRs%-jY~LFoAj8yb>rfOBiyTy!!0Y|$8g>>eMJp5k(nZsf^uM{$HgT~kR!Wz'
    'PNPbG=?q@n=)I(Uk2XgXCJzPw-u3Ef<hGn>xMk9duuY9@LVJ6Chdf$enDg(;FFG;?C6z@rM_~rIWQ=OBR@wVvSppCLKkI6h3);A>'
    't_BJ1rI-W%pc&@bJr&he;56VvK~Y==LvM2J67SoD^sbHBhNAjTWzj%ij&t6{0>BtZyKV8YT<B$$Z19RYxDA?5lA(nN8K>qs(xzIa'
    'w{SwAoFi6U#eySRq9@ut-N^`{Jz9cI_5I$2PiUuu$1OMmK5dKj+UOKEwE@ii3igJoH)O}f&jXPfy6#xOhd)ugl^j%beBtamQ#V5I'
    'z5UCVb6{t5^1_Ua(l`;F^b~=Q^iYk*o`s!vO)#dQCFmd+SfHwOV+o>R1}*69pCV8tGUu`AahG;RN)kbx6dz_|q8+nRXj7>_H(_Qy'
    'R-13_X)I~2s>53Mygu~<bfY2G!kXia13I=oe~^YRYHb`<L9fJ<ethY|;SViw626<asL7h>#)t=Fd4rv72ToL1!@&2TM|#-NOa4|K'
    '^4wRtWRc0i?PpxOf`eIKo)t?pu>6+h6Lww(3ZX&i6$i{@*mz)Z$OfYVgz|EINx|s#HPit=mqih9ddwG#97w;xWy97)cO7)u&Zg@*'
    '_CvGGmT#Ztyl6E3eiM&jIph%k1w)*bC~6BHg!i*O$@H1+&WPquAZ;i{WK}u8cKaRPwp>xjm^@1KyO1?m^tT`CSHlvSC)Va7PeV1?'
    '%Sj)LH?j4xJ@6i>;vLrPR2Od=L8zbRE(_e30ckBjphR7I^-m)k#wp{3eZdj&wycA#VL>tIr`MOj2fh~%B6pPXjj{F$Idho1M0$7l'
    '{f(%Z{DLR$I65uAs|X;<<IkgbOmvWmlTe)s5y297L<_o{;p(=jgU301V3k{!$kR{Eho;Jx)KYZ@pOK^^qr37I+dgNOubv>ZOvm$b'
    'T%d^QtfV1EP~j6j{!{7P#E;u~J3Yg3PTYST=fy=?cfM`DToh7cwd4N9TRnQ;h1#mbnBNE+uC_jZ;}J{!IN<->VY&PLJ2a=+fH=pu'
    '*&glGomL6NEba9AFQX>*v}uPsT@!0)enGW+VouCr&@m7_C~a?j+W7N3#GZ#^&F$LT<IaTwilZw8#*P@K<NczQR3h$fR^t7#61I2)'
    ';x7`9_xr`+>FOod>zEfu-{?@i1HN*s;5=a#H-q$~N+ijr6q&TD6XeQ7EHMvxxJ8v>5*L_vSj6OVT|<$gTmu_EzfN%5Csj#bD}(jR'
    '*Zav^va}1UI(`cb4V%#q9CTELKnwETghGm7*7CFYtiCAf<YI<Q39dSZ1Fn{69GX{G-&0lN^%4ni@^=5#Kw59<z*Xb-82d-7XX0Mf'
    'x^A3`8b20+OhYkJpkRw)3EjTLfF)T6o!xrI8;MRsLW!+vie+N9DG`)@nC!3WEn~58GRN;Zmtvi;Gt6UpgwqGx6diA2Z$pnz4xOFN'
    'i$wGL$^OC6U4{2Wv8ZX%i;v_0ah@EpYrx^&i&x3&Vp*-vFW_GojWPV8+#)Q>a1bg8D|QI2x@&Y0tvm)aoM`B5BpqDm&{<&pwAXZF'
    'fM|P=XiK1|+&L;dRID?O1byB@Xa|v_*X5Rped-C-=v@#g%;7Qmla90wf&Dg!FLpxR+Of(;?F4V6NuRBD)nsrKA&H|d)N#}f?ebZZ'
    'QQx&Od8RYN(@b2V*p_^KZ|#Mf;k}~owGzRZa8C|l^wkQl;$9!Pj>vX30K<W>S8G&?aFs*Vp7LYLq;9`w0qm(y4eVe0m~*dS>-ON+'
    'Kz%S28(o<URF`%A7@X|&NDfBzCtA@68gwYqtujK{kP;i9o_9fBzqxg8C8Z06!L$K<+8+Yl7TiWJgd@un&Mu)@x1C^36(x<7qJR^b'
    '=i67E&yc}UcKMzf1IgD>6}eX-?VPF})?-xEEX{iGcrv`?ZV*F)`cf7jR}zJCz@7e#y%&6v6$Gd-@uLiA^5nSzk{^l`<UV4h{IuVI'
    'AuPyqK-<C3UH>zQbL_Ygn7XkL+^UkluvXihfO_lrX$3=K<;RvztPvo{Z1NWRHq|@KjCyo@aQNb{dz>0I+8V9oWPQ1)Rd+?060&Mb'
    'G}&L*jBJ8(a&-laKq)w{D5O37&#2e74R@{l_w4aW=+F=;V+3;*HRT6)d7bEY+auO~JZ-=(ZI}hC3Zmv=Bl`WVEV7Dib@>yp!Ci6}'
    'y05Mh`>A47Mv5JxjG&p~om7$DhG=>lC@_Qq0lSZ;jKEfr>R)6DWIaQvcOd@US8fJaZQ!As)j|F+R2`^f8QE}t>RpIMci(ap!)3mF'
    '51h8irh842fQv1n1BGA*N64E!8N|56eiUT7m;|tdNmdsKVFnhqEUSYogl(YTm_}57eByt|DpI?1bnWX^%vj67yQv5JxQ3l4WMJg~'
    ';NYv>$U6hM11jzF2Bcb?l_IE^_ChVyikMNQA7&>scste0X{n%^ew_JWs9XVoZC$`7Ha3UUe*NvUa7`W@lK4(WFYZPO&t3RGe;hIe'
    'm-OwoEk9A(Yi<Hm=>BPxc&AXuQ`6Q`FZ#jKt<C6~T%*CAD>Uc;)zyM#w-r#%1W4?L=xU~7;gjaD+Yn!k0oGU`GL=}sBj@KOa0nn6'
    'e|XZflqc<IXupbN*ub<dXYd>PnCJ=xR1(q)Aa#_GnsszJ_N*>Y|CFz54TgqLNkLCk5e;H`c4n{wOH_ff83@H<AHWac*&OfU#!4l('
    'g0*3^y;~VWwQNuqY{Mr$l$GwNF<GNzgPKov_+%iFV>gRXM9^;P=xF@l<d*QPU43{YK}rYd!I6Ah)w0U;5bg`O)Z`nn^{l{51%;)D'
    '9R$QOU;oJzfn-u}5fFu=hd<a6G2{4G+ipTvu(@lbgRJ+)k(;0=x)+AX^d}WTsvNMzO35H>E08o)l}NIUHOa+QPL+*c8iS_KY4Mpg'
    'ZgAi3H|;;34iICf(_%^Nnb}}$_JB2ODkiA*Y$~c3hC=39aJl|TWF_@GX4Y!1Dx3M%<#?XMCPjNJ^FFfMriVIiGSMzhaXv=kh#xq!'
    'Y1fZMg$E)HCm8qEVND_@E=ZL`?}JA`y$kPu_RWo?OhN%bvY%4ogKx$NR&>5zI-IHYM@R{+5N+L3xfjm%<f;JSOXc2SKBQK3piX*G'
    '%_n9&h_-J{{L?2Uz&Uzu@PiS;x-G^NI)Az{<M6=^I$zi1=+Ax3*i4sQBf?9(4n6l&PwbX_ln$|EOFe3O>|4w#*fekUXH7?4ehz0`'
    ')g0U@r#7vY&%@A#>Lu?}jI#PbJ1Lu$75}&-x{SZp=!=6t&SzefG(0WQn~4k5z)Fa(aapsHw`Vq%e|h@_dv;r=Cpn5pDhn(rN}R|c'
    'o??YN-YXomeuaHPQZziu_Kyzt{@Sz3(!88DH^oyz`|OGLay=77r=nY+fWLc<)SjS=1klZGh(YJG-`_GUlWJAuwzGXwqQ*k2c*sJi'
    'H*(DBkq6u~C1TtIG1`F~;lR*XSUm|;Z+c#c`ml4)cUYgxHRBT%rH);f^%IDZc(H917BxM3QfxmD@b7<Ih~$@ybo}c#HcoPGz!K|m'
    'pxSE1Dg_Q5Nfa-noGxZ$_{x)ofxVoZgV@0y1Gx~Uw<Q!SG$uSVw#hGppjox=fa(Ri3T$5>h?#IGsMm|d95o5(Qy?l~ACAXVRb7DC'
    '3N6pCZ6AV94C8Ffmy6%Lgv$}mOL?AQbO0Xi=ihwu^>fuLj$cJRCs9S<+<+ar810zAY*h&~fRK`{x{Om}x3LY>$aV~%N^#c;2wwM#'
    'zgSu%m=Gqt!b?yxM1pLW$iOWJ6aqb<G|eI8S+h2q=o3W=U{c%Uh4F{KZ>tQ&z};{{L<J}p&=BE{CnsKsB)4m>1icYU@#smvX>?l2'
    'W9f5zR6FWK93#(E5g8=RKw%DcTV08*{ci=A?u0F^@uZt@q*c#9F?{qRr;&11oOf)&#CbCr4^>&6U!u}`x&r!&C@_A7mRSVLb+B|;'
    '77eVnqjBo9gVlZtkXpGuhBf?i!_fNQMK4UV7i5o%mJH=FZHBNl7B#DuaAD@l>#QCx5jsk1D~+j?_<<JJ(3h%4b?_C&o{fHKY&y+;'
    'wCy_^LqEKUZU_120ks4H{~XXi7sN^9zS*#EF~Gk7&YvUU{3l@k#V7QSj`(LH{W&ZC$#DMsjoK0AuiKOlJcPg70{mI{eiGi#NB8r='
    '{Q{VNJ}9&Ww(;)(?MHWa9N%w{Yyk8dL;$p|m@r1*pGHnBcmoETshV#`T+<T>GRx(qELTiePBU)2^btDvg-38lfW3xY-3qVQgs%68'
    '#8m7Ib$Dl_LsFYG;<jln^>ZLT-V+Xx4Fl8x1xSGac^E(us^s4G!WYj&E7|g6b_QYi9}9g3*aw$QlNsO5=*1?Z;Gmni^fTiO<)pUg'
    'f->Y{O@%C)gEoVuHcmPg$^HhI6rGSKHbU5F%huTeM#DE`2i+ze;iT2e(nA#aH26sIHoDvR4RKYQ;Ofl`=MK3s>aijAQL3?CqHx#u'
    'ZT3bPX_F7t?$a{!-RQP9?%Ub7Svn6Gw?~^9x4n8+3ap~Zvh99mnNVepM9=3S;>looAlNPk{b+-><(FEtOv{6)B{*JZ)Knfbeh;)|'
    '+OGA!oOJGpcIt~J8tb$j>NJdW>fF)>&S?nFOQW0Wb`;8~3v#M3P9qSf4#KGmY^rfh<8i_<eA7>kYpTsM64mrhpr&21IlUPCPYr;|'
    'NT&t_<*lJlo3KL-=+FpqDEqDka6|tnu%V<+i-Cr2gc-^;NyO040~i{^3vGf64bRtxx$QTKOY0Jkroz!wG+L)%w2+#-%ZGgzWO85z'
    'HKT6JWQ2V6)@CA)57D|A7^N1q3~ZK8NR%c3Mi`bQ07Ge^P<r5#POdY&a2hZuJ)zE&<w7@=i94yA5~p9o(C8a2H7I!CGK=Ou3*pV0'
    '`O^%U!?|qYs4`u_DL)}prVoB;iH%LzknQ-AeoN-$8@17cy8uAmGXiA*JMWITdQrGYUsm-|AiF?4+Vz_OMkbC}us~BqPQ;N>S9^Gp'
    'UvK=3oNkm3^WI=5#o3iej{@lN=J&#R#A{!gQd=M{gGiNOph^QBmBCvh)1=-i23WGaH$h{s`H|vuU7%R;f}G`oNLF6&PDG=2(u`n<'
    '7Q3;Fkm$$cbODdOf9zN?VlX|F*qwvKPZ6hz`tY9vuXJNZJ^PLi-s{nHdY=>#)Z9uM0_zWl2HJ#GbqA=b?tz{HsLBeWG@z*>$W(Vh'
    '^Lo^d<z??pg<?9eMLyytTrK`?lS0~=v=E-E5EL6Vj=P42(5bSM=93$_>E8(_QNScxoOm~o#13cHfy@g5Bs#c=hN;;^k8|J=4RpkN'
    '07ujTjS?loWzSDTV08^F(gT>{hG2@nGnQiOR^9|j@e>0nx;ToP;U~JZ!XPX@#jsuq6);Po=gSJH)3PRW0v;7HUAEv3@0CSUg#rjA'
    '&WxX~S6Ma9xH_uHdc9ia<M-$)9CGw9dS~M&Z<LqYorM!)Y^RM=;*|8EdzEd#pCe;xZv4R*^`02jgiov$+2WrI^;9215!+&`<BSdr'
    'lK3dCec3Q7=fGGMHZHm;6kA_8dx4ia_3wLgAe~ah>Bf_h)6u}5bq#s?RX7p1`TmDd@@(h3=YkWyCLM*6@25r#j}duf;Usy@Ui&*#'
    'zj39c3>b~~wZ7jMeyEk4Cte#?%N1<Mg+FdQw%E@B-V!jSZ)S{C;%iSNRTmQyDq+fIx<3Bk#3>9LLw(N>lZ0M462&!Mj3XF2>q>8('
    '*<CI9@rgB`ry5<#75}W=DLyqOzv0H0h28a_PsB@OWz5IMaJuX%47ML2+GAaj`WvRFKX6w-L&9BP$`?`ET$Vr}geYY%t#~Nb92<9V'
    'Yv9Q+pUAKK->aU9<>tRn?TO@wW%iD7t^QH(8TTlQ_x_PmFIvo?swEL_B<YRqLrD~`kiZO?5<nRD0J*y<<I2<*vqi?x2*l}LT~vti'
    'UX=B^Ml%Lpb3hQCYf*Hz&HqvMbz79*#%_5wd{x<<v|*~2h6xH}E$H-F&@Bx~l>9p8Q|MTu?tN91P3B&4m!n~Re+1-Z1$sg(Y5-YM'
    '1p@B#_!7aYnNe&4Usg~W;aw{6gF$S+u9FupkN1Dw6G4D4IXrK%EJ$dn5psA}1?Z_bIUT7tNT#!oP^XtYn5ujBbf;#_=J9$}O{W9i'
    '#uo)~7jA?gfeF_M#R*!F!WcBTrMx8R3z3<a{e6eYo`fZ)knI9-cBd7_K_n7tu!iZ+p`Yda8au!=PPh%@miazemmuvSZ;$)Bn4OpS'
    'xCXJ~I>{#=P}ED#iq#dushFAv4p4kkaUNf!g#*U4rUmElEfMRQP}<+|JfB^{B|)1UWAdi;bvedUC1eY(@tuH6#_4-3uCB+tO&{~<'
    'AH(Zy=wm|GlZ2Di$hj0w^#5-|FgFEt8mAx%wybzkiU$th%?6mo)^q8|t{%tcL|?a6w-tjC6P^B{l~R~t(EQOOIGDFWcHSs3`T^Vd'
    '_s4cN8#7eFW7K<IV{7vF=S6q^+>q5Kyzt?{!SUnNZTzur{Bfl5bj#e#Gsf{bK|w}U|2S=&@ZsV*?GsvGFVYKY`tcb^=S4ZGCEcg*'
    'PHkeOR25AwEsQ*Bgd<A;QaJ*jyr{nFO*!LD$)Ti(a_XQ|GhnvJTmWShM5cJA-r51smlZD9Ai)$}z(=ghG3QJ``biMPgS6?a;G_(C'
    'snnSO_b4Pg;UJRQSgiO!qXh#;>0ettIrc&OGGfb8H%3UHrkAC9Be3q$FbbV6r}RGh3!@U9SCm=y@JrjNC@?y?Ea=t~Jw9S=5pdIV'
    '(C@n_<hY~Q(@P%%T+#s4Ca?HVI)kCyL!Z;NDBmG7n`J}3)npMr>K~gRa1gm~0w|Z_6?6|y1Be+*(Sw2Czesuc2xdIHTIRSkS(Xmu'
    ';|S=qd<~<)Ed-+(S2Skov^i>{<oUch1I`Gh1<uQdd|8Xm8cH9ApKrVG4JiB>3HzJl;Ny2D2)+Y+PX&G-(0gPOMK%o-=-`ZB-8b$#'
    '@u7&@LkwEh53!l*y-Mvtygl;@X=GcpM4!*mj@s)F8FGl!Stj7nJt3>x!0JJ|)DE^jSit_o6nQ0P4_uAZbbOwXQ&1RQzIVXfzAw0V'
    '6`^JaojqX1w<51Qzy+Pa-0^=7`bG#T{+_DF+HO@>SEzOs0~IUxgE8TUdq;bRzrHx$KX`NWX)xaJYuc`EJ!#Pc-H;Dt!-N#Ky&5(^'
    'p!Y5)H*X8&dN-mDgm;h%m)*rVOihl?_Mr)y;BFj&TQI8;Hnk_Z5l6Zg1uT!KtuVz@C1__W{y%$5IoJM5oQ;eqJ<^gIDa94QxdU(S'
    '8E9=?y8KK#VBt0}_e$7FtKU+e?TxjO3#`wiUKXp13gN0z!Vw`r7yu{#U=EKYp5T$_r51R9IuM&TGNa;k<XQ)b#l(<L2OZZ*mFou>'
    'Egqr4F{{}b7=!Oe^92}Rn)B26Ez1&A0_BBbK4qr4wsw{(fIK!Akd1a?{bgZ?^^e!#vi?3pZ!UVA2DVBMwyZ^4-mH13gKcR3`Ym)p'
    '0<s4QLNh57Kowq%uEeV94rI;qzV?LSaL?L%cZ<9spSU--y?Z*L<42XVl9!XHiUD;*1AzXg!^vmoFhnpUetjT<w8SQnI9d4>8KLQ('
    '<Z_}ImHLu_E7>pMBBvyphU#Bu&1B7CEpvn-@MJz-t@F95oBWdLav~x$YqC|%>Wb|`Z}(q4HiB1*DJ&os60;^Un_`--Ql%e7bnfdK'
    'ZmG$v9G<Na;dF?WsNNI8@;ytRq{cM)awcog45%1V;I9|SS-xD(pt-A@<#gq$s6b(rEJ(r-wgz+A)R@tVnD0b{2Ev564U2YShl)_i'
    'IrwilzCtMuJ0Px7c#xiU><Rikqh(L4a3?dIMd`K<k|F{FebAcFe0lzXp!=1ZJwF-n`N0p$53^-e0%a6{uXwceK_WFGd#4N%hO*n0'
    'gW`=QTt(dtzV%t{15)!KL<E(jj=DHh-aRv=Ffmm+(tiY>D;FEuk@(YH8x!KgS{<GaI2g1Km&F=(;P-em)-{=93Bf1ryU5tI5NOU('
    'eI2mvhG$#(+m!3evtr3mrBv1MX#cOrdxyUa68-nz_FupDVPJVq42`gM<~nhm?N04$=?o6&d-cS!QHmY+em0*k&h<<WxTA)qj>+L$'
    'ZsK)Sy<abA_FUy@t>IsBj^_a*<fE@0k0H0f5A>y7v*=nipF3B{-KWQ&B8l)ktmj3s=nZ$i>1%JXA*v~RGC$KdYE#~_2Q3?t>SK!s'
    'tWlEB$tXdDSsJtDsi#AakSZ`1`?w4Cd_-_}%Fp7}67B0N6WW+tW2XkpeM~?AwN8btJ!KPes#PgiI21fluvRc1eDk<Rl%5XBU$ZtH'
    'Z+GMS^ULIAzE}~6Gv9UM%p`Cz!O>(_FW^?u=O%fbzb_sm@K+){;DkeiWmp{w^RZr$p10Mlo1ctu{&we450RHHC%rF3t%*6T<cs8y'
    '0QAJdePCvhi3KM5QSt@9#e0Qc2Al}mN%__Wopw5mbvuiHn-1USV)G{x+?pAESXlnq_p(k@`(0NF2F=wr9_25{Nz3GS#FkUZ&CyMV'
    '5CkUN&KKV&Ukv|Qp=E-qSC=~Rm3Z@;$C&iisN8@T^n3VXdA>&ArML8^hofB1XmUnbHmN{z>>FRAH)WQKPkQP0wp8E@q(zmPW}KVR'
    'TV=S4d@N;2S<ANcezYoUY2QlGk#=l36Y=>uNtz>4_ZF~$)*u{Q6!XPM&Ck)hw{H*kj*hrGc#Kp_)XG)>d`1(k78;)nxe2}62DeY|'
    '#h3^5M-0B$l^}MkCLBY8&z6aP7JN;3vxOfhTRs~ViQQJdiD^GBiflLt=(C}hYQoZ_Zy$g7#t;lTNU;ToVumAfgRILNymQuQqvHV='
    '1Fnpidk1A&i62~K@XW9~S+LV>IQ{b+AxcoPV%N4y5VzoJQ@8B=I$4nZDwQJPA&-JR4f&(hvM87}r<+>zNlAmmdLze*pDcik0zWbo'
    'wY@1o<YwL$vm@|J@d@r5t`zz+nX&ib&o5rSM6c6TKA-2DVnIx#=kSq|<2DG0th#9?j_Gn;CLV!=3i5<RQAsPMXa?0T$l0t!JcZuQ'
    'Ksug?)xE8xGBhLm*QR(PM3`UId#Ox3)Y|LMD<r|B(-voL)8FT~ac}Jr^tjDGrFl77kR@h}>5lxCcdNuw-D)-VhKQkU=nZg6%z})X'
    '7b{#f8OBB@jGn=;2uMBA7ZrA+W9M@sd_5b@C~n#rSaIsIpdGyKRIh>$WoaFacsfu~it?onTZET>sG=$sh+=fw4H+9o8$^q@Sr<m#'
    '!^gLr^uqF}Ugjm-BK3;<W?f%!9RIf{vru8teA5Lt@B~34#gXi|oB8N;BSu`P`OcO(Tm|T#J}xldiI7ef7<I!60l0<A3Cs$oQYgsH'
    'k(Crg3XKZ?2BNAh&8dim$DA#Pgzd$ea)9C8AQBD}<2zxm>tUQTUo2<9YZ-P?*g%Cya!d*m5KpA9Y)^9-gTz`H-&)nQ5J9$RkO)3}'
    'kWA<6`ohT@9a{mA6!}if0uq8ZT0P?QCk``MRiX+#!4_LzY%>KCbFrJG$)li6L?E(Sz0nfKfPC&pLdgm*!=r51Q3rK0M7CL%A%ne9'
    'Lvw*DT-5RIAyS?YvRs)SJz_9<T=WAKOh-E9Q3BV;Y(*Yh3b|SYU7C+HE66Z?Qk}*-i;TR2lqv`P#CXSywC}smG>&;KzXE<M0u<a&'
    'g+^Fg2;8ro0+!(bqaT;c^@44IV(L(SLvT+z(mhtL0g*y$mZ9j=UrJHcRl})88&W8qfTt@y%&Ik|bLH~8LYHVar`qqgs3P^B`)`f~'
    '?3_$676~Z;LO8C_n8!=U62YhmSbyNS%6Fs34rKo5<aA&-#N(D4C@grfSQ7tT{Appry9;jvm5+KBY_T+(WOm%8k4+wRD-o*7m{x>D'
    'p6JJS1x(kYjG^4i33Gw*qX91N$(4W=_L)V&&~|)?D1GoVU%x|)ZUECeqUvF~nvHXiYj6yL8Vl8pFPU{4j3hGtSX6GlfSx<XDOeFg'
    'EYkXsK`t{)2g0{{byOoe_Akeyv(1u>CKp9{X23BPtB{jwn{7o_0axQASf{1da5;^+Gx?X1oaR`g$2`Y=qiTI{I~5aa=s5k9!NDC2'
    'b4qwt<(<b$|KXFssDrEn{!grI@ZFcm(P{~#5@dbOp(jH_MHC}YqD58KWb$Pj$%RnkM5+VQ095@F^BwABgJynpmZ;f>Lj>y$!``xV'
    '7}=sv-ja21x}MKto^BhcVZ-X!klOW8x+{`|m?~G#KOt}%`VJ6QT0G5?Xcp#}e)U!etGF7`h9HOf!2LyQwJo!Lqyv_b9o9^=F{C@w'
    '=oYYZnBr47bqShB5NN=rT*EJf13yPe;&IAlQEQNz-@|Nl{vOKO-;;BTsF-MN`tdC7<63bhQ~JVw0Z;5D4DD&_TDvG<&}Rj@KT|Sd'
    '-c0J`ccK}-lK=<o%_~xrk%o&IJBN<>G(5}&`efW>U+eXmj8me(;NA%`<IH-XK5UR~|CkOMm5qV?*M@2xKeed(ph<V$$QfzX_o?6J'
    '_-ZmTJro8-`C+7aYw0#XI&{yKAnbGZ_8-STAG~?{;`rxL#o9QaHf*jqQQEkH)hGsCqiS^x#0Y;2g=5|8pEfq~=HT7Y-r>>y@!lu}'
    'evu!(I(T#Z_d|GwUfM4YUh%tNE&FeOI?7(XIDT=ocYKt+{YUo8{+s<@UcAose|dXwczi@(+J#=cJ3h$v-y9vkc>Q{m?le_w7o8$)'
    'Ob5q@FWwyeba40!^gBEF>8IEGZ>WR)0r|^}%$>FWb}!(zM5lA4&*KOMKq4erSzKkpraAJ#y2;>vnb+?}JJrsg{~S`!6D&_$KmRlx'
    'G^_9X#GoeIPr4mCAzX#en&CUq=<H#pepOf{u2p0s-wsrTz;!6d2s=hmq7u77DZ^^46Bo8c-<4bmpTpPyB7{@O*aGzAGm+5AdWoDy'
    'bnO0$MkV3~N-BKB$YZUCeqsG+8B%cc;_u0QueV_*BYi82k1OHI8uU%s+3|}n3pjk?@=pScqv@*>->otBFko2TWRnZuJyc&y?Yrbx'
    'ST*Hw|52vf9DBGkce?s-yMNO#r?=TkH4mEi$L>b_v9F)I<(6~3kDhEmNp2w+Mm9;akR}v9!}S8{F_YX14>$vxz}49x3R*9k=+GBD'
    'o%$$&;pVizOF}}oslLg(`@U7|T1DHz2n3e`qb-t1nSeMY$9F8Ws4#H(2`2GHuP;7Tp=E9vyIR@FY+?wt?13`BPOVnkU3QG+KlvgM'
    'xbp>)-F7!CX9sDu9q~3!hQX10XtsqyvhSz{2?hzxK^<fy^~Dg48d^@8U0yPyFOrs96%RzejfOuUk1#Gq!~nBzvKgn@W2R0pbOXD('
    'KE)@aB}a#h)*!F{W#`lYVaw+nWxAfPMxR!}8d9>##SSDaHO{>%WoGlVD|XjdOdL%_J(7Q#J~B8M5ewBt>g5lbm(!?pV9jjbwj>Yn'
    'rFd1FUs-3JC_0y?zhLQlUIGZ`YVZtcw4`EraSxe|4U9Os5jEjxwEO*tQ&C67jJC+o3zHUfRf&qgwhk7xM(r#DiGW}@N*8d+XS%8M'
    'HdZfmnvp&*7{EXg1&et;E^HeqwzaJ?63W>aHe1o6w2L+9I+5-uq}<~7Bdy(Xj$cR8H*k{A^2I7{YZt7@&OpmW4SSQhhm=;FcH7)o'
    '#mL>J?<xyp!FFS4x&JH>b<;W++)8HLg5_|^Qd_ha8{Om^C^p^R+b1d1eI^-MflE+KOlR3DBXZC;659aBqmjFJLu_ofTid<8!(q3I'
    'psB8qV_Z1dQ@8rvoUQDtXFa8h(4I%qHdq_Mp;?`8dU>kti@}&bv%(=elq26YnJs&ap-pU)S%_jt>yQ;BaOap``V55La56c)djMKZ'
    '4PrZSe)~*-)OML(lW818B{cg(_&<x+l+=)RiA<_#nqV~BNf#ud`H&0qz1R}WNsD-Jr{s%acyPxBYk#Y`MDR{0&%BxJdq{>_h!{S)'
    'mdI;|T&#u-wV9h6odNJls<j6m%gq!W#n)gy4{a@7pNfa14vrZ?b5#-CAjcWPf@|+p1i5VL-Y<BwmgkR!<Rv|X5<aWYLG+-mWhmwM'
    'AS{1~7`eE<;4Lnh7?SI9?drojC*Hm2fihT7BT=417aPA+%oE}aI^n1SnvkiM15jvqPBqrAe5a&mRf{K;%ghbrq_sCgXN>&N&|k^s'
    ';+rQS%<8r_7!_|sm$&6EB0;CMx?4*^L0afAdx_&rk~Dgl#QrA+CZ#BAPmIj{(LQ(fR#VG9Qoq{k2;SSHjqdFBMwr3Z^n0X##$5Zl'
    '-WQFoejC$(O<e)m4G>2Y_W}H5K7n1PsKangX@`Xp%_TMS*Iy>=$0MTiP?wlUc~4qhkanNpwIrqrx!`)3?62xTb(9j<5ZK`OGpdaC'
    'Z<RgDF(jX3{e|8zP~RT;&{nGp28Q02Jh&Vk;|_DEyaX7QEKYZhOx<&YGAlCtdV;TZm=#w+7wW$W)erj5ZnfT7-W`!dxmKx2m*b7v'
    'JDO*P5~1H^RzB^_{NA&}8H?G`?>}Oe;shqjTgcB_E{{818jY95rvBozw(b7npX`p<>~65`grHcY-HHbyY611%(m#2KSzv+^bI@H`'
    ')L^NZY+fU}OV}P_72ev~!jKD$L;~VY!4DjIfxvZext$ftV~(BYIHJo~Fd0BXff!I3Tn{rT1Z_*JD}g;xUb$iNBU~|}6_Cg98ni?f'
    'D>QSsb$s|@|IOZEcDVO{-|Zb8XN;GasEEqxlW(^bP<*{DhoSv5o}{XdU!UH-ny0DJl^3u6u|W;_<l5>6I+O3edGWe)6((1|mC0&;'
    '+TVNq>L@WWDw7m_nDJk9F@k>r$+Z)mH9L`*mb6Qpu+M>&x6n!`p15hplW;0SuGV$)9mJAtC+$H`qDm*fH~N5I!jLe>ubQ5NcgJtv'
    '9rOH<!i(!iY#{u(x?IqQ2>*jW7C4d>{+gVb)x13T1*+LIXM0wnGED}MS4*l7QBh|I&Xg|+ggU_>P8>Rdr=l8Ur8-|N)^j`fism=}'
    '2(wWv>TH2{TFXoIkmpT3Hahoe|8Vc+@xkFg?gn?R>iZGuID$Xk;w|enVuPNK^UFmJlu0c*0{Aelw65^Y-tpfL4*%AnIuTVlD?e0Y'
    'o}5s9uU_o^a_}ZQ`uPQ6_QCpn_ub^r-|p-@E1r*w=V#yM-#&jbeezB5bi8x+=bfGJ&d$!BPoI60fBonD+wUfMem4I0+wY#`<7dxy'
    '&YphzbdpMBAUbT&4?8i%Ai0F0!A{q}Kz3$|IJS}e&~0F$kPAhfcGDW_-Aa@!Goy(&A}N}czehtN_Q^Ib60`_Kt#Zrc5`6`DXw{Jp'
    'hp9|6W!49~8aWo7kyhn@Nks42tSf`;Q!9;+QIk6xA~xKd5AjiCB8*9Z5j=mUQWuS}&*{#Sr(Zw&=J}t${SKBIT1x5i9V=X5)d6vX'
    '6{;sP+`seESdhWGOAdYZ6FWKXhjMgQ!H|n$_$C}A(c7(Wrl4iv@24l<>YHB1J~)dO8}tcZE_MQM>kWHS3QRg63ui=Gfp006l*L#*'
    'LTqWE^3$2=vt(3f({~0?2!|OF4d=1Rjfj1b2^AQPr+I{dlPO$uX+4py;(Z}&M^J*bQ246ELPj{ZXhYn*NclqbM-gm;rJE2=BZDyy'
    'RwqnTV~iSKlM5m2Lib%_<T?+Y603xHV8o5>B_*?`guO%HJ28cngFs~p7`QOtsx8T8o2NpkPzY&34qoWr*;eKeGyzC%V~ocpgkIYj'
    'E}tOjMj9sG{eUzqoSO8bmC)lOW%J;VBps{?;Ta#%gy?FS)nRBVwWuN+7!Sc27kQdsSf)MKANx+*p`qsGbx-bgjKZp_l}O#r_lS5W'
    '%!jo=5a4&zu1x}1Uj<d-kj~JkmQyxF^*uZ}qk83&pkzi_90&YuK_m!061Y8jd8XPw*_~P2pJxc+LFf5`JT@<39#z1g0<C*rTmyfQ'
    'f1F*eFFBcs#W8>V6e{gmeDjl?XWxGF=jZ(fO+hcrN+;h^WiH?S%}%znqyFE-?TwyKFWD`!7Wx(LNHHejYU!R-n<#w*W!eaUj{u-j'
    'WhG9oEI&_HybimsehKXP*E>7L@fMjIWaq^fh;eyY)hj5Qh>yMFfO^hR1P&)Qdi=;HdFrt9EBM3B^r#NI@Ojf0t4qkC3hh2OAc~Cp'
    '7b*@DHuv=N1w{jM25b7{;rqZI(uCK6I1=|h-p|&xAKQoWb`|29%EdmA-zW4vM(v>kF@e11*BFM2=TLkm8JAQ7B8B_oupKR3GQpan'
    '9F>#!S2ZDeEz|31T)+=coz6;284g3kq{``NI=!Nhf2pb$l&->;IzimNE<x&Bf$%q-eMG>(^u`&9V4+mO#2*?V*dXeTvwfIl7jH9l'
    'k(^p7p!jOGX=R|NPriP#^JgZTexC=))8wlJQEtRPE=)P}0$LW+ae__SK`Egdx|sSCN)I^?w9rc^HHV-9H$iN9S>s9Sr07tj%Y11N'
    '+F)%i0ibV9ZcU<;bXc^|n#pV5<4~!g5Qe@zfAsC26dT6mO#CkO?H;|PrBKS0PksUPClDj(4vaJ~%!&($81}y)M$YUIl(iL?1|3XY'
    '=xu8c%P3siv(=sg#e><OGB@@VRY`=W4_mAIakAmvI*^JF7(G~(PmTMk3n?=+*2R2Mn;IHN<@K+m_ggwI@?}Yx#1L2fhOPkFFxj@r'
    '^|60v0>-@wQzw=hNrrW9g3$gpdgyAwX+kBPaE8`SGIAP&&Cuu*j+J8?=IeS$ud-P=t%h*W1KV0%6M|7$RP~H5L0XB#>R4!qW_q;V'
    '?bVWDmE^xYaplY8ZnRZN{lzLrt!g_-?LbT8XX7NG1-1v;R1l~2>!(}6nX|uhG|J&zQhsypXWZZb8SRhie182jVfXLHxXsYTdgg0j'
    'gpSX^xHIgP!d~m<67qG21*(qWKwgQxif<`xS&vxa{;m@-f!g~U>-3NaNA2MmqOW!vwlyX}7dI8xh%|nUhd4LnjQ?|V@CIx4E*SiR'
    'g)CS1D&~WWL}rLE!~B$OoTtr3Le&Y|=K1B>Bu`e=`=Z=UdKry6BZATI4>9}pRWF?H&KwQpW#`#<)un-i4h)}aXC>&MsuFc@dMF!W'
    '6qndU62*<jzYUp3iSOc0z&e~90=&|r2JLTXb2SM)9fb^(^WM4y0l6og#E$hMl*Zn>?1%KA_5c*Zj8UzSQ*GX7b)i?)mP*8C(~c7E'
    'Q40X!>^7j?#tp6!ow1=14rq+~P1A}zWWcyY8F7rcbcA^O?zAU$UYtYI^&&4bZH>(^mX)4K{dxA`DJ4<e=woGd%a|}`AD&RsUw2_m'
    '2~sbz$lHqqwLzdavlhpYI0ngAu~~~uO?!^sU=f}2=ATd$-5IPoYq0@JCPg+7$zy9OKAJP$lI^&f8n5$dvAS;PRD+#!kaRX-_WMEA'
    'so1|l`_s5ty^PKwb&v9*kmp=`TQ_W&utLP{!%5_vwQdU|pS7v%w=B6NDoKo7?a_#coMSZ<kt|zlS<2!n`JXjV^66}BhTVivyBvCU'
    'hALk8V_^|9_JmRGt3s@oo4|#%jS1_9$(u^SLt_{}YGp|;Ep%12s4ZU_@X>~g=WMwwNH#$b>9SbiHbF0?mB?r&r5gd<AW)?l5SjnM'
    'yK%jm&FPJ(*|>6jgMMhColBOh@$T6!+d(&DM7E~hX4DgE!>wWFJA@RmhBl=9(0Fk%^_q)A)l0MKlW%qA2X#JG?Qkx;O#rp)hRWeX'
    ';<)U*4THw<tjqjEKAU4?lNgi8_~(s^pYyn|De8ot2GKI1Dv302Ju{D-Gk}H#C-Vs{>7dI}NbnQxuFV&42i!A6j!iwW<>5XVC`=fM'
    'Ly8G=RFDBGu%lLWQHw7wsuv^M&q-%{Pg2#GNy2T1&D8W=ptPgJXYkQuN|E09reyN;>R|a4y*$y~I*ks+F2s`XjGVO?H&gt<s5&<>'
    'Yk^mlZPyX9jbN_a>id1)D<M>+g!T!#D3D#F@guayJf*Tt<%Y95ug9}l&+b&qC%~T1F7vr?ZbA3b=Dz$T*=egD*Fs?_QLPH%2q(>Y'
    'e`3t$X|S-{pgqZY%i7|7r~swOmVbr^5#qfqFGZ`gb2LOwXmv`%O*p6LROY87V6%pi+Gk83i*PGWX%3yNF_|f9wo24w!NrM=q_B&<'
    '#Ia3P@kzTZklfAcOALLS&&oAvHSoSA&p&7ZeI%}HjP9$U%!$pFb5Gdeuq+E<T>++KRmoqM^||_qzfT8AYyi8|`<s9W%XCL>smFZx'
    'K9-z<1cY#eTS2VF1o+e%LqjsgUKFhOKo$-XW~4TfXNPsjqz(+VAPT<8rZiN$atCFGoq@41roLPmPw1_5Y)u{GCG+rx>q1W6;@T13'
    'x3sAnPG<J}9*u{{oL=T=8-dwbN{x&hRc($+bzaViJA;udmUQ#cU6@Vjy5j-kZ*^*e^UEsY{Jb8j#FKPYsK;fMAugcvbOIt#M&M!O'
    '1%QmVbpT{nlD`1?6;EWB%x9t$dTi+TD&8J@jWo<y7S&7H?Dhmm_u1UIFEv+TsG*zhPwDO<bKV9rrwDPBaYJhiW$k&Th7q;6k#fa!'
    '@$izn2p+ncP6-rO^OAwYK#eLedx$XrVLef!xKOgC0FV$nUcMY=lCm*9=_IcSKivMQm!Z+9S0!Q(t<y%AVO1l=Sil38Av8Pa(>e>V'
    '0;MAn>CMJGwdvT~&zZephICeNqWTOfMsYWI8=CCnu4Y;d!9`uZyCx^=UYxs%0=T#1uD%*QHglJk^hRYhWe`8vdvAm}A}mYnzMe^5'
    'x+dT-2+>HBBx;ACQi>+nU!x~fnDJ-yWWB$_P^i&w=@f@%b}u@OdbjL`_YiR69)PgusRbS!5r&k9ARbrg8O_OQ0}h=s!UNu$S#ZTj'
    '(vAmu6PFlmjL`cu#n=xnzb)F@rteJTDiPkX>(uO8OJyLoU@*jIb2bVr*OUnknVTKDsEhIYMFrP$CY2Y2Eks}MI5l%MKqz6&C$fg~'
    'C2X65VmO&+!iQST$+n<6P@4<|hgTv(JVm5#hUGRM!XPgzqufovPHybdF<LOr5mjVTpamZ|rE9j!8xqDRNK56Z{V;Zpe?_#{q?;8g'
    '!cfL4Q(YzqxTPp#tDD@%qEUIHrJ=-boh%pD78TvY>|dyLalVqKI)N{vQ$4*koR^gc?um-OG2smDg=}hE7zw2Q{jQA%E!G5hW{K{`'
    '3l>N8`RY?i*n4wNOgBD|>@sa$n_pH(z~1}jrnfj_d&LE1P<bgFd7uMz^vR&B4w5FQu4K^0_i0^;$Flux6QXXAn8<SyybbrUu%Q}j'
    'aLVo{&peCOdQmJt%;3rtQNT*(F;g&oW$34fi!<cl0U<CCRHg(@qoTp}ovgtJs6U+3HNGv^)q$}gkpvO&FuOTf`#>hat$`B)B9Y1('
    'e4FGMI6dk+DV@>W$fsKxT_OrIEjTx1+(Ns^`MO0vDw5yI(!P?^PHeP!W+EZRNQpWQDsrdHMH2tsm^6h#g&iRNiF-nFS)xTMd}{nD'
    'Ut6DFXDn8nrRkOgVp|lGfzC7KWtAGJ)KdziFbWiBpt%}P6(%tO3|MWvh6m!RB!FI36zz#S!yTQuNdp_hIRg4MF2uC$+PM|%#%y9='
    'R#&m)NhS^%R?cYPS182V9Xr_xWG)YEToZ{ov|k&cl)WZ{SjxklEjxh?%#1LGd2@rwZ1`1^&xs=3CZTF4;4!zPrj$0$jpz(6`9V<<'
    'qge&p+L%$sm-)r!mJuHgD7NQ_)YEC%ByAJe@O}cG;M%H4^yXwc!PGaj^fKw_DA^fm)vnHnBaW>|i1W1H0rj)P-q#q&au=B=Ks*b='
    'mIuo1#!<NS=%Rbt{GV}<LT!gGh)6CVl={>y#4_L-<7Rto7TI+b>&i5;>!%>N3Bx(qn~&OHPR_WFJY90s2a&!%Ntbn<g**|>GV_^<'
    '@f>lpa~tvNM?;FA<Wwhp?NXiF6{F5@(o=oHIS-R~|M>9ei1TBHj`=OH3hyK5k&(-&YaXLSBr+0Yf}j^9E9xdQ@|6+RX||82jVhwg'
    '315%)+ZN^gZ@$9GWKV5r+Q34~w8mv<KX$%hY{lI~9yOc0^ADW+ULLy}GZF;(p@G8=VM?6Y!pu}*GDriDKl01N6V%q9Ap?Q3pKQlT'
    'zJ=N8kxg+D6D8^PK1x;FNA%wx(?PO9nxb@jTT3Y-RZ+rt)W(gB6~~hmHLTqBw%iBX%51XDup!&iiE2vCXJ5RhDKksx8TAK1OSjFI'
    'U@RS6YQt5>NP(pCj;bU`gQO|xP`3m_Tk(`cUbdlz%tA>lwUFJw&p%~9zx&a8pS*nc>P7bJ{?Y!AulKT7d%y0#+=H&ci-TX@W^dm8'
    'k{$nyT4U~R^2^^|dk?K94&Ls)`SJCOBmdL?diB@r<%^d;?`1z9{IWOl<zWUPaX{gZe|h_A|1eM*kxSrI9`F6~w&893W#4AbV?w$D'
    '2^O1k$Z-8>Kae9W`EQ#hZ&D`^b+1k@z1qE|EkhzP@RNYyo*x<e9uJC>oC<cyn|H5YH|D2Gj09ClBtsQr#%9w=9m!aQm{RoGJop2P'
    'YC8Ae205l2n*$S-?;Vou;Vc_p8J+mv6?OgZIM>CbYep+aZj)cTZd&pMdQ+n|)b*8cNLw%rMAu;&u&@eUxwrx?qm*O1lFV)-BE(P|'
    '{Pw=M-qp2JC_uBTj=FvOH$mKZH<zMxV?;(%LN!X2o_1`Up`*lnT~pLtYXVGmi{!ydSmLwd0xLOu_XZiQYJGlzk<}|~cTu6Ke}*t<'
    '32>8F1eHA8ilqu-ZvSlyHip#ypbg8twE~%@&eH!bQyr=ylq}tIO*P3k4pdMer`5o<ZrZuk$QBvUFhnu*#uw}IJ+no`$x7zu+b7?B'
    'y-lbOa)kXjte@bV_7C<NQ2dPSN;}^~l8aU_`DH*-vgZZ0;yvnk-<uBMWyfAFVp42-o6X%z9oeH1Pen`9_KcvU0~7Uh;JVka{8F<t'
    'lQt0{RoQS1Wmi4gU8I6}VmMRadyrw+L4k{SZDMM3RIA&XdTXSnM*thPy_gg=Htljb^3B*bp0GCldi=e?nvP6wP5U-oFPF>=-hztD'
    'k6j`zp5KLrGf9;dxfE5_aAW!_`1?^1NO?Zry-CBDtF3Mh->zZjBFWkR7IZzpfJ5nUvdi1xCY0PPEM$ISirUt6vy2;`63;cPMcxg1'
    'ZQO(xYQwyY4$o1G<cyYBI)F<Bc7{Cp&&;!pw;)E?C09A`aE$l4PVl>xpQmS|w2X~&H@Tl#vlzl+DR{vmm~I2JG$0PNBeP>r@!SUT'
    '<g=x8P!tV;xn+up%U-;M#>w}5mB3z_&&Zm+o|9iMcDN!;RrvS=OfqL*pt_|`$i1hUY`Xp%G7ws(7B^{L<Ncz)8<GD68+sL5o1#>l'
    'EJEtTf*JXmj_k&%uYOB)&L-GD!K_V*$ZfJ~BoaB<MR>x~n{d9Q?s<#abK8E2!8mvT@#rn8nu2PEuu0WkVcc?zPo6E{6vHE82^aV)'
    '3ad_%qTFV1p(A(8IJ}gMo&nX-(`0#B=xz=}%5eLjv}(jXIZMlD5hJ1}^s)^ikWDJ=ZxPG><SW=?x_zDA;9k;1b<qM_87LPGxwnSY'
    ';oE26ie{bkC(#{;mmbJBOG$mT%msv_Ni9#->4ZeXfMRvfq($v}Cu}-t-h67~Nhd^G%YCng8fzm3HjltrRb-OeW4VE?EB)pz)M4s*'
    'M3VyJDviUOZbB*Lto&x!lC<ZVV|3Y-!lAb9@S~fpTMUDnHj<9v`3RjH(}~9PIMkTamil>HS#*WZq3KU(WV+ByybC^Vr#Uh6UhW!K'
    'B;Fgu3Bgl|h%dBPVHTP9fSF}&mnXpt9S}E>g4U0uTHCdIO)ipj5Jk>F>=XU4#-SpLE4mFEAW3iU+vvD4MK``!(4Mw8+HPwd&78K$'
    'lFK{Wwr|-tWA;R3TpDZDn?6{fY460ke6$bF8JZ!+s>GXAak~d4@Q19NTNdZ*dA>|kwozg{3GyFq3FH<;I1S;sNOU>q5WBq&6(*h%'
    'me99<S#ur%>^D-%t9<@m_5yf{YB7P<r8CjALg*4;6yEzzA69VvS6uN|RI@|T%<QhJD}9R4w<&u$t)LuXZOu7ZZj(0&6c`?5`$w<#'
    '4|@bn1abnpg;Ek_{rYh4ug+_Zv*RZvj*avm0Vqo)7SW2$=7wq%)0x2;K*<G~n*beKUh9QQy-PRV9sl~8PFO=mDt>n6gTD^4!&e7y'
    'UjO4?^!v@hPY17GAN*bZ_2$Rd2QUA&fhNvSW<wQIn(pbOi`#+HWaAJf#fL#+KA4r2{Qz?v+fObDwW+M*X^mh#)Fe?0@(-$A{=qe?'
    '$&|Gk;;dW{(;Z%~Wh}QPPRDgQ4o*j7vOtgT@K)0}iQbYbBm#Sd`*C3-*wbJSt)4MC5{WFXDGXxbdQ}N0Bb9MQ>(->VX={2lBT#~W'
    'at>DO;xsC;63}R8)I(qh39Ep}@I-|S4w8I|C<C0ma9eF>#Z|m~y-(We;TBbelKGnAqC{Q}5sRqYsVFO<PK{Wr#ER8a3tj@XmPzY7'
    'nK}xSp#1;MU0ZJ(Hx_=^uh2e8LKQW6*j+&BJOrpwWPxo0ySpeL7y~s?8)0KvkgPO8;QzinS00jwGb7tA`jX3tJmioZlIQk)a<_;%'
    'jeCk%*c>xs0v*?~k$``0Auo%63nLZW#X^_h9E2lUHlBzVpy_-h5tB7jYB)M=^_0#Rt%C5XaY^1jOHoKxo*QkhYl8yG;rMg$$ttU6'
    'R)oprxJjmk9M_>rZB#@QR`N|B2&iPb<V3=p5uOM`sMJPj$UZ;y6QeWwl@c#aYkP^(m0|0YlH40R(d;|K#N3S}nWLiyh4)-XjDa)_'
    'D~;;G|K0oGafL{+6W3tluvSbpv)8>OyEHG1ok(Di&2yXeKdQh3sy(a-$&2q`atF%%jdB!iszE578|%uhAW8#QKPLes;m7RE2<e;i'
    'wn9uADd{^T)VQgw%ICJ173^rje&k14pz=MbzdEL`u_3eg>E0iEm~P0G*4ZUHN_YZ;UhPH|WUa6qXd1elg1FdZm=j!N%aWUH36WQP'
    '<S@O-z{2&Xr4=XBhpT9rS<q4cfdg~D-NA{=SV<G;7wFcIaKe0Q(cua)hu_k%o{3w(3#aCBD-@DpNdzI|51YegF@A#tku6cQx2>q!'
    '@X4;f$T7SaX6^o4BYQyYbHlgw0YU92#)?1VsU$Y*$@dt&dC9x*1@UmZH&Hbo$PsTwFZ>n$%pza!JA1au%^9_ii0vTsA>4N(mL>*)'
    'D55luT+h02RJB}sa+)7j0ElpRI!eCa?On@^pc7YcQk520_QF{Sy}E+i-`_S|*_Dl{zoNYiOem)JnRMfsDS3PbJZpo*5tYiv^-j+9'
    '59^y7coMoeKm;T>g86|f$1HN5?ExZ~0h1slvkOY19P}(zeH+=24b#kW+{r^z`Iu6I8I{pbMN^T7qr6OqI2;Z-hD&b%?;ZO@LYYh7'
    'b-7E{wshRqx0KYCE@vBl-H(mT*CI=6h0jV1UwgLol3X3O?`J(Tt?NQgTnW11Z(=$5=8%VqGwYrVmp#|ijPJ*^nDtp8%~$nUM}n=)'
    's)S}nnKtI*7ypQv5!qGg56Jpfs6%iLfN!K@;?a~x{*#_;?=#>Poq2Mg6y-cq9BWR^ER)46>y;;_05y~689W>FN`ea{+-D<Aq}^pJ'
    'rzc5d<R=n{;&I>{l`T2gY~`e_S$58`yDfY%RArSGzwYfCy&>h{B^!aEgv#r$;75V~O?Z&B6I9!(d0hgFcecYltEL-y_W&MnHf;=-'
    'BR#h@u8UFe<X-En{`=L>?NwOruYR~_A(h~&($a3~PZq}bsiez`tBcG3zWV9)n;)+_cQN)T=*Q7v=Sc9vnPt7YcIt$_t`P`?<+m_+'
    'R;*&!sByuCUW{t_UbZe@;1F5%D@!6}a{Uf&{q#kWkuHJey00DS#n{=CfXBrjJq)YCy$^zV!l+Hto?2cjFh=vPpA%j&V@l(%n{%3s'
    '=rpD|^Uw?BaC7A-#25to_HC~V^{hMYi1%~t?KYpo;f_$KA0Wl;C~K-q2aEfk0p9nQGbBcU5x7N|MowTjhI6A0>yQ%|3b6jp4=<uD'
    '?)RJZ0ex!u$0#S&<Y|xa4t!{I@AJ=nr?`|m=OpigrXF^XYi~J3uX2Q&%e8m&8o(=Q2n86VA-*&}o2IQ~3vO;YYb#?2duPpLyn9=P'
    '@$MoSQUQsY5v7350U(1Ij&-n_;xihRQfa#(*l|J|4~jJ6=5?eUXO|T7k!lN1|6QuVA4V+sDw&)OR|x`L6EA2jjGbdmj30(fNTnAh'
    'G>&bzs)4nvfvHc8yfKv%sph&7%i%y*jdM8nTjIEl!aPWWdD_uCC+0xdm*<Q#(fB5ldAFTpbmm=xuZW>;`WzpvCMNi}W*X*_9HP%L'
    '+wVIJy<DMU70G&4$HFat_K|S2%P_UAy)3kBr$h&DjvUvuPCCC2=%v)ktp=q@pjy!H^DrAhP3Wk{rk56{OTI5^^f>dwP^rE4IFWRo'
    't**yTCqmD&-aV1!?hmxuJ*CC&f!4Z_ug<s`EUHMyL)$6Uvu2EmTi1#_v+e6cblX`BV^yGL)z0q^+grvD4tprIwz{r6uV{-Zh<fAW'
    '_{#9VD*v&%87(bwLP+eYA%z3%x6SUf-E9hX5q2J7KB=G8cCNioZGCS$%NK!el^{0=8)NfG62}&w#Yi@HI+Ad?y)+wzAu$V#aZi8w'
    'erltv_*F3+u8NeTOM;hDu_ny(bWxZEFv|F)tBWC5wri^+zQix5@Dg{BA+ZZ3oCUy{1QI7*ca6=*ozASv_;kg|nr>3_5<}$N%)A7Y'
    'WuHwHYdCb4^ms6{L&?<#0<sVbinKOABm@IB5hks@E~sh7W$|9o88w8mFv6`RFY;a0r;(P7R1p4;CFw)nQf*KYt4kUZW5>co#iWw&'
    'i=5H=o>wN=<o@qygrfe;I(?X>pV-t@qz8e*8Rj(iWfiy@h0rhzr`=)0py|noBzn$p1(1=9A@!(F;d?4&&&%yt=AGw2hK%(P(f<KI'
    '#Dae!<suwf;RpQp;??1|6ND(f#b2fZh7b53lgra?3?6Y#f`=SG<wzq$mNf8DE=eh>rV!O*1B><h_wAb7oVsvDf=$6@0r-*;C%02f'
    'H=2=(>y)7mb~^7SL)$Jek=E~M{9u+L%<u%}>kpfc`$mWT>OXJaUS3>X^>j#qm9Qts;`<;u27u{Nk}NjUFhKyhjxqlzk0?Lk87@r)'
    'B!?%9l)j=^<{rBR*305J=OnE+d^rL({QADZDjqe4{Nhk$&`%jmy}V3zuPU=bc|<luW?HO1sG#hKa6w8wHSYuKBz`!5pa#My`xF_U'
    'lax#7{%5@2XTw~KZ8oAahlIf=?tsJ@$_ax|au-(Gq3d9irD5J6*6DJfL#Z{x&+r{n2;o9qOlaBe!gStEpU)$qg7PLXRMUbG=BI;D'
    '#~zL}M$P_d5d;ryXfcF>Q+o3~S$8Qw?v0fC7Zn=)=>ZI$ze6d2DD41}zjBv{>WqdfSwlm-ZNrTbN#AsJxcxnI)c-!rPhV<y_ygY)'
    'xyyXR(sWvI3nY#i$B;3P32Elk^>+%c4vy$>0Xs|+olP1?l3+$GCzJmeo_~2cMtg;n(;ZWpmG~w8Qb^*6gN1onE}Sma=PsrJp_kDf'
    'R9P)JflW5eHvc>-%~C4Wq{G~)p52s4uJf^~<cdhAI=X4e(Z-u@4A;R7F_{4dak|^Q_TP<1&zKUMfo8@&Gh#E`+$c-3Ri7&LJAt|o'
    'Txvm=m%!qP9WQanjO<S;QS<d)pm7vjDa~ju%o9zS6p!k`eC!6(H!;^eB5lMFdJFA9IjQ_J{v+ykvYDIW6v{rXh0}`)=f%?-{U}0h'
    'JJ9oVAA>;P!)Z@lT17<ou(=aT#&mbO`2{{6K)gyo&tp{q{iUMDW~7MT5z}FR*nHaFp77nM{F3oF7FmPZ1+vc3W4tGE`K#AIKnl=&'
    '9RL6N$Dd|S&K7|xX{h^j_A*XL;wme5;S!ac^zRZ=op-Kp`oGQO#&&mm7v^3t*T3cVNQ-3d4#*`z(8-J&O_-!}d`?Y(NUax<qJDAn'
    'KR8Xm^w~VW{pWL&{8HjiNs9I;Loy0u*Lm+4iXHk)kdc@&<ZDLNSTcZFB6^R_Yq*BvoX>=QBQI^K%8j3EX`EahKJ&eWPl@~2nWQEb'
    'mbh_sluTWV@Nb<%fTw4Zk)rf2UqhIp|0)(m25+Ujkn=bWH50iOC~`+?{&~S<lmRACC2I{H#9~t{NR=o{(&@XrFXa`74aM2TJ2)V`'
    '*&IOTv%W)fQ`i(H56!uB;TN*cACstq77~FGG`C;s|MkGAw!i8eRE_^G9zZsgj{?EBhyO&ngMw?QE>%3FqOaA@r6<$xj65VG)JsI_'
    'z=+5_GYZ4=vSf6v0qp8A4WrmjF9D10h7!FH_lOse!VJyFw#XF5kjp@*vs)oWCz2^EF9K)Gdot&bn_;^4t(-d_Knf1pJO-1+ywujp'
    'TjceS;mA==j>i-mg|Bg#y-F81x%>HX)&4Dzt22<5<ZCt_HE5O({_vZDurnt4*#iKS%u2A2!S_pJ?PaE(1xNIdyNGEjMwu)h5n}RG'
    ';U$kw1bZ^xi-IyX4H8_kwxCp~wY2Od?<PiG0fc3*Ifd)o#m4I1lr3nM!f?eJ;vVck(CR-)it#ad;!CsaBLoNMVlzkXG0hlKQj@#e'
    '7FGILC-PS~Ha6Q&u&!`x0I5d#^g+7P9Q+3nlkN}Tm^J~s5ey~`&J9WeqEeYFk)=BHQ=;)qdcj^v3^YaZ*1{(#{v}YDKW>kA$Tkjz'
    'Rxg&<>`(cW(gY^HBgct|=6V$i214*jB&^&;rDigVjtZ?jE8I}If0fJGLCJp_jY2o&ti%Ak7OS@{bD0K_;jON|9K)$`5!Tw&4A*Qn'
    '`ah%YY8?'
)


def _sampled_v5_public_280_source_data():
    import base64
    import zlib

    # Bounded decompression keeps this immutable historical public source fixture
    # independent of the current working tree and any historical private mirror.
    assert len(_SAMPLED_V5_PUBLIC_280_SOURCE_B85) == 42108
    compressed = base64.b85decode(_SAMPLED_V5_PUBLIC_280_SOURCE_B85.encode('ascii'))
    assert len(compressed) == 33686
    decompressor = zlib.decompressobj()
    raw = decompressor.decompress(compressed, 182046)
    assert decompressor.eof and not decompressor.unconsumed_tail and not decompressor.unused_data
    assert len(raw) == 182045
    assert _sampled_sha(raw) == '280bf5bcb4d1cdc42ba91d5e1d71d6c867fb6e575833957eca7fc79d5e3228a4'
    return raw


def _sampled_source_held_v5_current_producer_fixture(setup, monkeypatch):
    # Preserve the product's real default selector. The legacy modeled fixture
    # temporarily sets its fictional source selector while constructing custody.
    # Restore only that selector; keep the explicit process/scheduler doubles.
    selected = recovery._REVIEWED_SAMPLED_V5_PRODUCER_SHA256
    assert selected == '280bf5bcb4d1cdc42ba91d5e1d71d6c867fb6e575833957eca7fc79d5e3228a4'
    case = _sampled_source_held_v5_fixture(setup, monkeypatch)
    monkeypatch.setattr(recovery, '_REVIEWED_SAMPLED_V5_PRODUCER_SHA256', selected)
    raw = _sampled_v5_public_280_source_data()
    producer_sha = _sampled_sha(raw)
    case['producer'] = raw.decode('utf-8')
    request, row, terminal, parent = case['request'], case['row'], case['terminal'], case['parent']
    lifecycle, reservation = terminal['source_custody_lifecycle'], terminal['reservation']
    request['source_sha256'][lifecycle['producer']['path']] = producer_sha
    request_sha = _sampled_sha(_sampled_wire(request))
    row['validation_request_sha256'] = request_sha
    terminal['request_sha256'] = lifecycle['request_sha256'] = request_sha
    lifecycle['producer']['sha256'] = producer_sha
    terminal['failure']['request_sha256'] = request_sha
    reservation['record'] = _sampled_copy(row)
    reservation['ordinary_scratch_profile']['request_sha256'] = request_sha
    parent['request_sha256'] = request_sha
    parent['actual_original_owner_argv'][6] = request_sha
    parent['original_owner_custody']['original_terminal'] = _sampled_copy(terminal)
    ledger = json.loads(case['ledger'].read_bytes())
    ledger['reservations'][case['args']['reservation_id']] = row
    case['ledger'].write_text(json.dumps(ledger))
    _sampled_seal(case)
    assert case['args']['expected_producer_sha256'] == selected
    return case


def test_sampled_source_held_v5_real_280_source_default_readiness_closeout_and_disposition(
        setup, monkeypatch):
    case = _sampled_source_held_v5_current_producer_fixture(setup, monkeypatch)
    original = case['ledger'].read_bytes()
    previous_sha = case['args']['expected_record_sha256']
    readiness = _sampled_inspect(case)
    assert readiness['ready'] is True
    assert readiness['state_written'] is readiness['recovery_performed'] is readiness['admitted'] is False
    assert readiness['native_release_performed'] is False
    _sampled_assert_unchanged(case, original)

    receipt = _sampled_reconcile(case, 'administrative_closeout')
    after = case['ledger'].read_bytes()
    data = json.loads(after)
    selected = data['reservations'][case['args']['reservation_id']]
    assert selected['status'] == 'released' and selected['artifacts_durable_asserted'] is True
    assert data['reservations'][case['prior_id']] == case['prior']
    assert set(data['reservations']) == set(json.loads(original)['reservations'])
    assert data['roots'] == json.loads(original)['roots']
    assert data['limit_bytes'] == json.loads(original)['limit_bytes']
    assert selected['explicit_reconciliation'] == receipt
    assert receipt['capacity_policy'] == 'administrative_closeout'
    assert receipt['cap_changed'] is receipt['new_reservation_created'] is receipt['new_resource_lease_acquired'] is False
    assert receipt['native_release_performed'] is receipt['admitted'] is receipt['outputs_deleted'] is False
    assert receipt['final_accounting_is_prewrite_projection'] is receipt['actual_postwrite_census_required'] is True
    assert receipt['fresh_global_inventory_count'] == 2
    for proof in (readiness['proof'], receipt['sampled_custody_proof']):
        assert proof['original_failure_profile'] == 'source-held-V5-retained-command-failure/v1'
        assert proof['original_command_returncode'] == proof['original_cli_returncode'] == 1
        assert proof['original_failure_preserved'] is True
        assert proof['cryptographic_execution_attestation'] is proof['reconstructed_Popen_handle'] is False

    disposition = recovery.inspect_validation_disposition(case['ledger'],
        roots=case['args']['roots'], reservation_id=case['args']['reservation_id'],
        expected_request_sha256=case['args']['expected_request_sha256'],
        attempt_directory=case['args']['attempt_directory'],
        expected_record_sha256=recovery._digest(selected),
        expected_previous_record_sha256=previous_sha,
        process_scope='sampled_birth_bound_descendants')
    assert disposition['storage_release_established'] is True
    assert disposition['native_release_established'] is False
    assert disposition['state_written'] is disposition['recovery_performed'] is disposition['admitted'] is False
    assert disposition['release_evidence']['test_or_task_acceptance_asserted'] is False
    assert disposition['release_evidence']['historical_capacity_is_admission_authority'] is False
    assert disposition['release_evidence']['artifacts_reinventoried'] is False
    assert case['ledger'].read_bytes() == after
    assert case['scheduler_state'] == dict(leases={}, waiters={})
    assert recovery._durable_inventory(case['args']['attempt_directory']) == case['args']['expected_artifacts']


def test_sampled_source_held_v5_real_280_source_rejects_old_81aa_selection_before_owner(
        setup, monkeypatch):
    case = _sampled_source_held_v5_current_producer_fixture(setup, monkeypatch)
    # All offered outer bytes/hashes and native/process premises are consistent.
    # An old historical producer selector must still refuse the new generation.
    monkeypatch.setattr(recovery, '_REVIEWED_SAMPLED_V5_PRODUCER_SHA256',
        '81aa6bd043793607e062af2b40a633a4c570266c363360ee0eb6e64fca26ffa1')
    before = case['ledger'].read_bytes()

    def forbidden(*args, **kwargs):
        raise AssertionError('wrong source generation reached current owner construction')

    monkeypatch.setattr(recovery.resources, 'DaemonResourceReservation', forbidden)
    with pytest.raises(recovery.resources.DaemonResourceError,
                       match='original Source-held V5 producer or source pins differ'):
        _sampled_reconcile(case, 'administrative_closeout')
    assert case['scheduler_calls'] == []
    _sampled_assert_unchanged(case, before)


# Source-held V4 is a distinct original transport, not a V5 evidence adaptation.
# The original producer bytes below are immutable DATA reused from the existing
# bounded280 fixture; historical process/Source custody is explicitly modeled.
def _sampled_source_held_v4_current_producer_fixture(setup, monkeypatch):
    case = _sampled_validation_fixture(setup, monkeypatch)
    raw = _sampled_v5_public_280_source_data()
    case['producer'] = raw.decode('utf-8')
    producer_sha = _sampled_sha(raw)
    request, row, terminal, parent = case['request'], case['row'], case['terminal'], case['parent']
    lifecycle, reservation = terminal['source_custody_lifecycle'], terminal['reservation']
    profile = {'schema': 'owned-validation-live-census/v1', 'max_complete_resamples': 1}
    request.update(schema='owned-validation-request/v4', live_inventory_profile=_sampled_copy(profile))
    request['source_sha256'][lifecycle['producer']['path']] = producer_sha
    owner_dir = Path(request['cwd']) / 'ipfs_datasets_py/optimizers/logic_theorem_optimizer'
    request['source_sha256'].update({str(owner_dir / name): 'c' * 64 for name in (
        'validation_run_resources.py', 'autoencoder_daemon_resources.py', 'resource_scheduler.py',
        'existing_resource_scheduler.py', 'proof_resource_safety.py')})
    request_sha = _sampled_sha(_sampled_wire(request))
    row['validation_request_sha256'] = request_sha
    terminal['request_sha256'] = lifecycle['request_sha256'] = request_sha
    lifecycle['producer']['sha256'] = producer_sha
    terminal['failure'].update(request_sha256=request_sha, error='validation command failed with returncode 1')
    reservation.update(record=_sampled_copy(row),
        enforcement='cooperative_admission_and_polled_usage_not_kernel_quota',
        live_inventory_profile=dict(profile, request_sha256=request_sha,
            complete_resamples_observed=0, live_exception_active=False, resample_limit_scope='per_logical_live_census'))
    parent.update(schema='source-held-owned-validation-v4-observation/v1', request_schema=request['schema'],
        live_inventory_profile=_sampled_copy(profile), request_sha256=request_sha,
        state='ORIGINAL_OWNER_WAITED_SOURCE_CLOSED_STORAGE_SEPARATE',
        current_sampled_recovery_profile_qualified=False, automatic_retry_authorized=False,
        recovery_or_storage_release_authorized=False,
        native_and_source_exit_verified_before_parent_Source_close=True,
        original_source_READs=[dict(canonical_root=str(path), cooperative=True,
            lock_path=str(path / 'workspace/control-plane/source-leases/source.lock'), mode='read',
            schema_version='autoencoder-source-lease/v1', waited_seconds=0.001)
            for path in (Path(request['cwd']), Path(request['cwd']).parent / 'ipfs_accelerate')],
        actual_original_owner_argv=[request['argv'][0], '-B', lifecycle['producer']['path'],
            '--request', str(case['ledger'].parent / 'original-request.json'),
            '--expected-request-sha256', request_sha, '--resource-ledger', str(case['ledger'])])
    parent['original_owner_custody']['original_completed_result_verified'] = False
    parent['original_owner_custody']['original_terminal'] = _sampled_copy(terminal)
    ledger = json.loads(case['ledger'].read_bytes())
    ledger['reservations'][case['args']['reservation_id']] = row
    case['ledger'].write_text(json.dumps(ledger))
    _sampled_seal(case)
    assert case['args']['expected_producer_sha256'] == '280bf5bcb4d1cdc42ba91d5e1d71d6c867fb6e575833957eca7fc79d5e3228a4'
    return case


def test_sampled_source_held_v4_real_280_readiness_closeout_and_disposition(setup, monkeypatch):
    # RED baseline uses ONLY existing public APIs/fixture helpers. Old d755 must
    # reach its authentic H16 profile refusal, never a missing-new-API TypeError.
    case = _sampled_source_held_v4_current_producer_fixture(setup, monkeypatch)
    before = case['ledger'].read_bytes()
    previous_sha = case['args']['expected_record_sha256']
    ready = _sampled_inspect(case)
    assert ready['ready'] is True and ready['state_written'] is ready['recovery_performed'] is False
    assert ready['native_release_performed'] is ready['admitted'] is False
    _sampled_assert_unchanged(case, before)
    receipt = _sampled_reconcile(case, 'administrative_closeout')
    after = json.loads(case['ledger'].read_bytes())
    released = after['reservations'][case['args']['reservation_id']]
    assert released['status'] == 'released' and released['artifacts_durable_asserted'] is True
    assert released['explicit_reconciliation'] == receipt
    assert after['reservations'][case['prior_id']] == case['prior']
    assert set(after['reservations']) == set(json.loads(before)['reservations'])
    assert after['roots'] == json.loads(before)['roots'] and after['limit_bytes'] == json.loads(before)['limit_bytes']
    assert receipt['capacity_policy'] == 'administrative_closeout'
    assert receipt['fresh_global_inventory_count'] == 2
    assert receipt['actual_postwrite_census_required'] is receipt['final_accounting_is_prewrite_projection'] is True
    assert all(receipt[key] is False for key in ('cap_changed', 'new_reservation_created',
        'new_resource_lease_acquired', 'native_release_performed', 'outputs_deleted', 'automatic_expiry', 'admitted'))
    for proof in (ready['proof'], receipt['sampled_custody_proof']):
        assert proof['original_failure_profile'] == 'source-held-V4-retained-command-failure/v1'
        assert proof['original_command_returncode'] == proof['original_cli_returncode'] == 1
        assert proof['original_failure_preserved'] is True
        assert proof['cryptographic_execution_attestation'] is proof['reconstructed_Popen_handle'] is False
    disposition = recovery.inspect_validation_disposition(case['ledger'], roots=case['args']['roots'],
        reservation_id=case['args']['reservation_id'], expected_request_sha256=case['args']['expected_request_sha256'],
        attempt_directory=case['args']['attempt_directory'], expected_record_sha256=recovery._digest(released),
        expected_previous_record_sha256=previous_sha, process_scope='sampled_birth_bound_descendants')
    assert disposition['storage_release_established'] is True and disposition['native_release_established'] is False
    assert disposition['state_written'] is disposition['recovery_performed'] is disposition['admitted'] is False
    assert case['scheduler_state'] == dict(leases={}, waiters={})
    assert recovery._durable_inventory(case['args']['attempt_directory']) == case['args']['expected_artifacts']


@pytest.mark.parametrize('path,value,error', [
    (('request', 'live_inventory_profile', 'max_complete_resamples'), True, 'V4 request profile'),
    (('parent', 'live_inventory_profile', 'max_complete_resamples'), True, 'Source-held V4 parent profile'),
    (('parent', 'current_sampled_recovery_profile_qualified'), 0, 'Source-held V4 parent profile'),
    (('parent', 'native_and_source_exit_verified_before_parent_Source_close'), False, 'Source-held V4 parent profile'),
    (('parent', 'original_source_READs', 1, 'mode'), 'write', 'Source-held V4 Source READ owner'),
    (('parent', 'actual_original_owner_argv', 8), '/other/ledger.json', 'Source-held V4 owner invocation'),
    (('parent', 'owner_pid'), 99999996, 'Popen-verified parent closeout'),
    (('parent', 'original_owner_custody', 'owner_birth'), '457', 'Popen-verified parent closeout'),
    (('parent', 'original_owner_custody', 'genuine_wait_completed'), False, 'Popen-verified parent closeout'),
    (('parent', 'original_owner_custody', 'child_reaped'), False, 'Popen-verified parent closeout'),
    (('parent', 'original_owner_custody', 'original_native_compute_closed'), False, 'Popen-verified parent closeout'),
    (('parent', 'original_owner_custody', 'original_terminal'), {}, 'Popen-verified parent closeout'),
    (('parent', 'original_owner_custody', 'storage_artifacts_durable_asserted'), True, 'Popen-verified parent closeout'),
    (('parent', 'source_closed'), False, 'Popen-verified parent closeout'),
    (('terminal', 'failure', 'error'), 'unrelated failure', 'Source-held V4 retained command failure'),
    (('terminal', 'failure', 'returncode'), 0, 'Source-held V4 retained command failure'),
    (('terminal', 'failure', 'received_signals'), [15], 'Source-held V4 retained command failure'),
    (('terminal', 'source_custody_lifecycle', 'owner_child_attached'), False, 'sampled lifecycle binding'),
    (('terminal', 'reservation', 'resource_lease', 'released'), False, 'sampled native release binding'),
    (('terminal', 'reservation', 'resource_lease', 'gpu_memory_mb'), 1, 'Source-held V4 native release receipt'),
    (('terminal', 'reservation', 'live_inventory_profile', 'request_sha256'), 'f' * 64, 'Source-held V4 closed live inventory'),
    (('terminal', 'reservation', 'live_inventory_profile', 'live_exception_active'), True, 'Source-held V4 closed live inventory'),
    (('terminal', 'reservation', 'live_inventory_profile', 'complete_resamples_observed'), 1, 'Source-held V4 closed live inventory'),
    (('terminal', 'reservation', 'live_inventory_profile', 'max_complete_resamples'), True, 'Source-held V4 closed live inventory'),
])
def test_sampled_source_held_v4_rejects_resealed_wrong_custody_before_owner_access(
        setup, monkeypatch, path, value, error):
    case = _sampled_source_held_v4_current_producer_fixture(setup, monkeypatch)
    target = case
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    _sampled_seal(case)
    before = case['ledger'].read_bytes()
    def forbidden(*args, **kwargs):
        raise AssertionError('invalid V4 custody reached current owner construction')
    monkeypatch.setattr(recovery.resources, 'DaemonResourceReservation', forbidden)
    with pytest.raises(recovery.resources.DaemonResourceError, match=error):
        _sampled_reconcile(case, 'administrative_closeout')
    assert case['scheduler_calls'] == []
    _sampled_assert_unchanged(case, before)


@pytest.mark.parametrize('overrides', [{}, {'capacity_policy': 'require_capacity'}],
                         ids=['default', 'explicit-require-capacity'])
def test_sampled_source_held_v4_requires_explicit_administrative_closeout(setup, monkeypatch, overrides):
    from contextlib import nullcontext
    case = _sampled_source_held_v4_current_producer_fixture(setup, monkeypatch)
    before = case['ledger'].read_bytes()
    def forbidden(*args, **kwargs):
        raise AssertionError('V4 policy refusal reached live scheduler or reconciliation')
    monkeypatch.setattr(recovery, '_sampled_open_scheduler', forbidden)
    monkeypatch.setattr(recovery, '_retained_reconciliation_engine', forbidden)
    native = recovery.resources.native_deadlines
    deadline = nullcontext()
    if native.resource_operation_deadline() is None:
        deadline = native.resource_cleanup_deadline(native_deadline_monotonic=recovery.resources.time.monotonic() + 240)
    with deadline, pytest.raises(recovery.resources.DaemonResourceError,
                                 match='original Source-held V4 recovery requires administrative_closeout'):
        recovery.reconcile_sampled_validation_reservation_v1(case['ledger'], **case['args'], **overrides)
    assert case['scheduler_calls'] == []
    _sampled_assert_unchanged(case, before)


@pytest.mark.parametrize('damage,error', [
    ('parent-bytes', 'original parent closeout bytes differ'),
    ('producer-selection', 'Source-held V4 producer or source pins differ'),
    ('durability', 'explicit sampled artifact durability assertion required'),
    ('current-native', 'original sampled native lease or descendants remain'),
])
def test_sampled_source_held_v4_keeps_hash_durability_and_current_native_guards(setup, monkeypatch, damage, error):
    case = _sampled_source_held_v4_current_producer_fixture(setup, monkeypatch)
    if damage == 'parent-bytes':
        case['args']['expected_parent_closeout_sha256'] = 'f' * 64
    elif damage == 'producer-selection':
        monkeypatch.setattr(recovery, '_REVIEWED_SAMPLED_SOURCE_HELD_V4_PRODUCER_SHA256', 'f' * 64)
    elif damage == 'durability':
        case['args']['artifacts_durable'] = False
    else:
        lease_id = case['row']['native_lease_id']
        case['scheduler_state']['leases'][lease_id] = {'lease_id': lease_id}
    before = case['ledger'].read_bytes()
    with pytest.raises(recovery.resources.DaemonResourceError, match=error):
        _sampled_reconcile(case, 'administrative_closeout')
    _sampled_assert_unchanged(case, before)


# Immutable captured source DATA for the two reviewed V5 producer/SDK pairs.
# These buffers are parsed as AST only: never imported or executed. All original
# process/native/Source custody in the private-ledger cases remains modeled.
_SAMPLED_V5_FINITE_PAIR_SOURCE_DATA = {
    'cli269': (
        'c-riJYj@kmwdi;K3MBaeGKOf$aoj`+yRKs^jcy&wS60%~rD|b8BqXt>03L$0t>*Z@-`S6O&j6q#JL##q&WS0^%%1n2{oY@E_Hf-S'
        'AD+#shh_CPSzNC!>*}km&p-eCXk8`c`^9`VnXQu5a^0-TX)?JiCvTeM-E4K4)K!^O#cKApOx_mr*;M?jtE8x=Nwcb##YLIa@2YY+'
        '+S)q4oHa>PTrK7T#9~=b%BI=ASk~(W{B=H?mx-uQ)vKgP;IHOdbas{e_qtvcNxe)ab+syH)m2%olKOnBSf0&R%VK$*Ov`3cR@0(d'
        'HKXKUl~m>1a+zE#;X~4tSK{B<1R%U93o*3m)vRg6AV)C2t@CAlmE`&PdbM7bd7jL!7WGmLp%MeZxini_^4s!aQ7oHM{(V_Am-E?~'
        '{PUkpUCG~9#p+W2t{duPA-;*~vWHhjm1cHP6?6U9O7+o*L8#yBGhR0J<y!q*T`tRFI;$?!huKxRwRLoOc$|!}vw@hUSk^orj+SLp'
        '&)=4V;YdtKtY>rb)#=vO*0elNnyOedm-T7@!_CA*-p{VqSL5BCM~}aR|76LRSyIgB^}D>hTCA?eKNj<*9PVu;;(xRAWOcnL2S)i&'
        'Zt7WG&#4ytZ&}QmGWoTbugm@AvR)2SqfK%p&RKF+id_(gub5Edbcn65W)+M`Olk-EGn<uSB*`w;g3-%)!*6PPE)D_BIGI%m7Vrv)'
        'X&HaXWf|%Li>_c6upgt>`N8Yw2S)?0Jco~BEt^$-RZmN!QFx}aYO!7=)7i3|h%0gp3xr3qx`0C}E>Y2xQ=To|v1W8WtrulA5WnzW'
        '+8puMVSe=d@a2oY{}29tdHCbuix-D~lYhPZ;l<&zzYen`U7n@Gq!8C(C639J9^qLj)}$0G1%2Q=sKyA6N>vYr!{`be?f+#!&DG3d'
        '{Q6ThpH**?&&J6ve22Dj@4g=!)tcGAO8CM@t!wqp>UA|07-U`XN+rwkVm&XG39ak0{O`3`TDgD(<eiuyPYkZffctu|t1A`fD}gn-'
        '7GgFPJ3bR<ZJf-DtFvj5G<$;vrZFwwX82=P)${`<M!&A$GUio7e@*zWp}aGqgMk?15Z20B7qM`%OI~cOrM}^)hgLQIWY)r?&Bt`u'
        'b_r<-CznNaAr|)CB_L(SE4-e|QXt9-mXr|&tasT+d@-F}h(EXwUUw6ts5vw895t84qpzRf^hcNFdul(x;nVN7;d0*yOjJKVFP9CE'
        '^DR^py#rPr&Ff;?U>~x3EFN8yt3ld`=j^Hw*8@%{poJ7(tm(FX&bGOqhi`XNahKx7kJ^hLw-<k%w(iZkYSs%t?P6z)r<R-B+k?}~'
        'j9qH#^>R|?7wcj<9bhT<wU||nSSI{*l5#cLl=Rd>>QGZ*^XW`rWxmx=&^B;IKNzE?j;MF%#uAd&hY9us>W##+c-0JSoa`JU=k=l|'
        'i{CBt(K=p=1?W6*;pzCZ;QO+dqz~wf)0)q&uGXvKOgy=82zf~6+SC2O6FOaAEt&yuTO&3(e^XvJIL=Hg09@qpBRPkvsQB3(mDNNb'
        '-ofy}S^AGEMW{dyEoTeyv=BCPAB<;5`%jPQh1mbEXD{g2-;VrOBujScCp$aAhe&rKj`X|8<H8v9-BRqFzI{f?`F!164)kZlz1P(w'
        'jC=Xz)|1k&yL!dFCsDl9`_GOKkDR#?#MSb8&+nXI@nM{aXJ&5Kn#}8_RJ9})gqxX9ibWw#`gOi6&(}>cACz!rkY*Ct_o5tsPSh|A'
        '|8qVCf(rdX9J}rE{2Zywiwp6f6{}Jl$Ks-@8$rB&N3A7ITh+;Yc3w`dCjvbeYeB4w6}}z;IqS_z-d+TtuCG{MxV;2b;yrV0S@QWp'
        'be-d;+#IgD7=&r?9IApVL7W1}ags{%U(lN6@-5vLxjcfZo0O$^#Zz;f0~{!>*l?7KQ+@>mxwx0<^P;?}tD}<c8{Wgz8Vv5tGSL7='
        'f>_tsYPA+j2ULKU)+`6&qz9mrol|q^LM?P<06O4>$cD7cOP&^#aZ#V;tk3k?jkybT#Ee3{iq)#T5F2(rE9X<d>*6uPYUMO97Ib9u'
        'v+Gsa;8V0-i4#!4>n<3e`8+rFs*%;KQKrRoI)mZ@D&xZ=AS-|Z5iT#x5A)g8Y!!yYv|z4Tz5IMxmbxt;AbqFAJ%eW?49*2(SJo&7'
        'I0?Z9nk(dWq)un%!xazF`W!%ul}v~J@ilhEdMra{rl_u|k-+uV)r2Qde1ltQ!VAG@1PNpHDNfjLlBR)GoQTUSetc;k4e`NVi4W0h'
        'U_d{SfIF{4uo2$nDc<GnC12)kx$4_S6Ckwujt8c<>2R<Ojs}p-G+);Bs>$nWe(m0p)@?JPitW;)5Nqu<)a{|h4sbkf`{euN(U)I7'
        '`O4gXd)tOL8xL%?3Dn;DVINeaZaZ8VYdQO1k<;*UJg_&W1-YE+nKP0}?DdP{xl_@Lf@TmPbmtjOB*=aab}|Kh+lFo;GGi<TcJLtS'
        '6?0&<W4==xsaP#-{E8=-KXo7ac5I5UoJHw`*^YA&q`yF$k5r-KQ+b{T?)LpT*%@v;Tnm+J*nvHbfsc&^$|7KT-8GjlfCpqiSaj?&'
        'kP3q`(TQxT)eF&{_}`4kh#U~cI7nD=jj<$QEJ((Jj?HJsXIh$4T*E@FO*0;(89YUM>CgsNiVawndC^Q}Gj8QFIO6gu#>SSGNY*D^'
        'ug<r>NrywRypMOjebQrnfgxFyKvIbf8a1n_m~e<o;l_wtxecOJfs;|ft>BE62nXB3fnBVUABv{j$Dd+__O^mU+S+<?@Z<iozdw7i'
        'pTB<g)Bev-fp+$`SiY5OaoDEU+lu<fhcee7_J7@fdHgy75<pY#c_BtA*j^%NjPEoO_>6-S=w&va=JR4*O)l+5R5B4v8Gkq{mdlxd'
        'vn<6!(v)Uxg5^{&x-Q=f6d^d~=^S2+Nev1CX!v0(KR)<*|L~XN{Ktd+7td)Lnv$88lNreEb4k*qxCHq-ab|K5sp(JROxLTrnoamS'
        '4QW~y(5F!hEy{VZ5aY|6a#B}QB4g+E<c;p;T_H}!GN0ib8o=t+L;+<i&!zLCD&@cVYAF^{E*QT_v|3ad#x~8x^QqQfJjux7<yHL-'
        '$M#-yj0~v2hN9E?+yZ8Q6GY5;-W2C0pv(&74r(({h@PLpv|!B_%TizzF*54IDw`DRrWAWYY;9gI#k*cCuf=MJ%PfvXRp)dV<iwlH'
        'LR=3maME1uD{;A5e*f#&39z)^fu`r5<%9)SqNgSSsw?^RaUu=^(1l2nBnXuCOi{j;h#nHCxN@nGeDAYyyYwweaT>t9^<dQ%;GYg^'
        'pG9m@2>4$979^D99QFbeknpw{o<I(75ifk`^VGm5FN)c+8K88{YtpReK+^nXvj<E{W(hPxDis><d1Duw#1tn%+6&Ik7qLy(ATb0P'
        'h@4%*vy)U+g6AalUuEiu$mubTE3^ny%UXr1uFeHvCf<O&Q-h=GM#pEfhPDto6R#*-f*cn<zpU#wWBi#Vs9zK~u>y*EHCFxL;l%^g'
        'V^8^xA&HEX16>ine6*++ZAaQ~VeoR}c1gEt`$h5;w0Ns!kxT?8E0=KD>6Xtx_Dg^>*4ozMKk`{UyEf3p$Xw49&bXl8-U=*Oi;>F_'
        'qo`Ppb(57ki9v*U+IO<;E&`D436M1n>k0%fpq@Bjj8OgEh{n4gT!J9SAw=-28mUb|88o7<;gModsqqcS6?_%MAnBcgCrmtGxqO=k'
        '@`qx7#9OCdgd_3BUR0>p0<6Efg!f_AtU&b%%Q{_)^N}`*crw<-TwKX*>?YxEk~8tw<WfBdJT!U-WY36)@fkoP1c9`5i6GP*8bho9'
        'L}gjgJmq6};+g!y$9tOxvn^}?A467QLvbh;f<|-8#lwCDvSqb|G`AQilO&OFP-~L2NkA?t2xyw}!4@%a2GxSl^xu&NNZ3%v`n;!s'
        'N(R+~ER}uX?D{TEgbiNSRjj@yn6M@sZg-h13aWDeLHbI!3J*6_(}Hgu$CEH&MzR@@!?ZP3#OA5RcZ4b=e;y}0ZLl;IOTa+R2-W6g'
        '6{{t7`>RJ5OtDl0kT{4#T!O+qNq2T1ef9Y3Cx80p+v02@kVA^ZfmJ6A-Ggh7m*rRDcF#bsb1q)b)e!4~ZOv%b@MCQ^@W=r}=r!oi'
        'FZAUVhQru(4S~fyGO>f##cAxEI{gNA+dR|}Vqaaa_6EcOsLG(>GFi;SzrEZ)%3nVHdH*#^&ow&8#m&zpvTR0+Ygn>ky{hTCS>`1A'
        'b*e}<N~)gaGr;ZT`;bR#(EZZIc+sFt>gICAF6U7-IIt_?jKGV;kB@wF$}6Bo=&sbu*##hNLzDf`GIP_+O1EBJ8vu<HFw=UN&KBp5'
        'SfrIehpQ%ETtBSETYM#+%VqO$USGgDx-9Eud6lbzbV~|nL4z(Joq)0_X6`l2k}pBGI#7K-1OfOEuL=BudlKI3VGm;fC5T3KJ@8AY'
        'ob^;2Xq+{x)Ub!WtOwNMYuzWVd7CXkV87*|;35{O<nLyyN<5<j1euvy%S>5Q@FR&Ny!-<d>#meM7h}ni5{OAb)Snl#xnPA+3mg%C'
        'm?RPz4a&)a7Iqt2q5b0$<oJS^`wnQILLd)qW{K~^v|N;EETGOInjX3bYorg>C~~lrA!N(_1)cw;7~icr8u=Gn_Wc3~gJZgfcpA2t'
        'XrHbpXsgwF*0D0~e1noCxi=u)LVFECh2!H5QXLur9HBtD^Qy2MOIlY20ip;M==_t@56Y?qZdgWA4SbL+xP!m|Gd42Y(?(S0xf`0K'
        '8;D*q2V!_y8frUcR4;%FHadR|8IHwB(xzaxD6qj|HXUeWV9|LlEf8<coc);1igSA`SQ=Bk*~Gwtgm7oG<?2#A<fdTW5;W;kbOQSa'
        '3?c5|U?^!&RW-y&!5zWF5QHet$?2$Az|9>X5`K^XcPah}8AJ@($cJ8UF&eQn#Y$WRg=SKhD--jimz)L(uf2TT#?%M5#VLhvo#qe{'
        'iwD?)anfEGI8!nbWEq}=<>8u??aa1JQ+P^v50L>d&jniYs`X06=Ule)7$*c|PYO=araY?NL?Harb@fJY5S4sJ7{{_ag{Ct$<_lUY'
        '_?DiE`wgnq^&%%NicyIqh*q(w5mBOaGU)kNIc0WTKD??a@0Mu+(xfb9lOOgB0nFiow5lM6DJwiS$bZ9qkgRt3Zkt|H?nJ&?&By?R'
        'Cj7`=OUtC>`P1X4-z76?bx)X}kt?>%lQOK7TovqSy$~m<9JEbtYzWW{k%ud*G!&(6D|PBiL>v^?(mV$V6+FS?z8$I-lIdZwg{jnY'
        'l|cGv63I9=2@6wvg)iaww-lZOfi&b7c+!a0+>4t?s=9`mq-_-WLHC7+13H?)GZ#j_Sa_<CYP1>^pMEgUzKJ@<A$)=~89h?^+K%;4'
        '4NUOYU@-wpG6o8Ppc!9{-BvV*m>OK+GUt_)gu5)yjnY%c_GnQH3iUcyE6!~N<%$A1P1xjiO&1OdS@tXm3#gy!<r_HqP%<ehU=#)R'
        'GwK-Y$ZEJ;(f4B>i&p^qB(UOQy=r6~{?i=R*;*``sPUV4Hs!qV0k-+-#X4{1^$L||SAs@dUguY5T5l*tRH}|tnX_@$2kS^vRgiSa'
        'fmt8T;Sq&B#+xLm?N%k@I7WXv2c2cGV$}-RJ3f%~)qJRQGk)pt$>FoK2Kvu>0hPLqzse_U&wjw1W8ppLd;0nJ-adT3U}(monzUUr'
        'rhhUQ50Cj@<o914?dN|vdiwG>fA;j%(`N_Af6tHhfBfb3(-&=8>cz4ofo;$v!2k+gDVqVL+q(@iiWtoO=YJ8*>JNv%ynKEm*l-vv'
        '*ju@Vt`zIOvVB`A+vA$;ExnE}fBE@`{Ug@V--T`Ft!y&8>@Yttx9l1=n-AQ;=8t7xnx}m_LAqGU{1tPnZJm{6uza4RLI_;IfKmcp'
        'PppOJYo-0Bzq0=mG=OX~^W2J>ky<uFJ&aPj3{gL9^-x}e(t=CSgbHT571k!--n7z$bwj&IsV8?2fME^^b(~_bfZW-N*)r<4#sy=%'
        'Lf<Dl#!D39`y!{~w!1itEMc1kBdn{t1iGbVV2DdIjOgIB85ZdJ3_KyoTGc)9TEXXf%V6VgiG5lz56fSG_SIrg*M9NO!PyhbbqNw6'
        ')w088Qk(>1$buu)BeOJxk#UU2YDIyYZG&WKSLDTsTP(JydAM=ARbse(cfZgK);`p%+YXWzADRqs0|6(&r(v&AxMrYZWfB`%{_Wr~'
        '81@-^ysy|U>fXBSaEJW%2}*%Q3EnFxg%MJ0d_zgG;%tZ%35brxYy>@FXe*uyh8p-Ow30E@7GT)-u$WBhbp^h#I85o~E0C-BG^v+U'
        'G+rgIeVo~73*kPMCK~8~E%^KSJh>>V^{guA(6m^HuEhCx_TqqaNb6;BCQ8J*fcv~?F%<(P7XM|<{DoF@fNZ3gT`3U>OnkMxM!YY*'
        '^5OWgondlWF3XXe@V|*PJEjhkBluO7ORL+X()Q!gt|V}#)a%#X(0z_gp&md$p=!Y5*KOQrVImpLZRpA+ZLf)E5{I+|)s+4MN7VYj'
        'XEG)j))jq0p)T`yv*4Q0#R^hfvPjI>BmARe%K5yw@ZBunE3n1{a)el+F@5Q!(-@Yc-5)a8@I;TtN!WJR<hi{8e(<RUwFX}#`)Guz'
        '$nNu{pza#rwZ;9<6|w-;+f?F;oHj1c6Hz)RTW1NbFt7+9j6_OjC0~pCGy-%|FJ|TRA)AtKBL`4Q(Rjw-X4PcAMm!BW%EKUcd_n!M'
        't4X;8T^9{OAP<bqfuo;IOF~Gf10G4oZ+QW)YLL3HnK%7GYRT5SG|IW5l(j244qTwyC~F^fDZ}mV3`gU!J%|x_<Dx#GUH`5`$D}1A'
        't%|QIg9B(!lIT)r9bMxbKEw#xtKHd;Zqagd&&BQ|%?b2u$F{+B$^2nw!7lYfJP4pg`!w)H$Pj^M_DXF6h%Z_gj@l|fE$7hf#k@Wf'
        '1V6;2A@rga7O<B142T9Q!g<Q`(WJ%|M-9?vq#M-{7Yq&9xmYE+G*T0<*12Ub3?qZzjD8hNu|T;6ixr=UY_epvEGBpt#r+#9%0_^}'
        'g0o`sCeO*!9HUN9bpxGSrr(Hvp~h%+mSYd2a~uz}Fb9X!wp)=`76Y%?Yq}NC7@F&q#}-S^bR<a4@Ysfif|1rjRjbPPM0coXb*xq>'
        '>hQ|}S=7D=rjao_yC$_uZDe8Q67rJ%Z9594Uot(ws~XpEpm9!6KSt7pdL`+Clq3U2O?q3jLskgqI1Lo_Tu93$lR)TF!L@ZH7s+MN'
        'k(UoRt@(^>KVXPEet!C2`Rn7uqo;q_&wu#)@&4<UEieMn#Fgc8D^z7^0LCPYr8b9Q#Fgr;%JY_Cp2tiVKC?_0;t<+x6gIaAVM8CK'
        '%OwR|r@-5kmxHw2q|xka28=DzP)ygRcd5(^+mn&46;}^v?U1<ay`3L2Ple_%sKYiD%uwoJP-7;hBX7F4jv)>pY+u9oUpbrURwi*7'
        'D7IBLvcOo35F#CGEEv<^Ahy!tEf=Sn>NlxMaa+q3fIwWHmOn63TVWG6T_V%|sO1tCZ}l}>Vqm7#QdC#%t5W!-+LqD~@_p!Y=(S>w'
        'cM;?OE8}kn*_XQ?xxX<BMS^PNv1P$0HHfxt25Rt3g`x4;-3w_asIbwP5y?;)nZ~_0qTX?!)DWE6+sEwjhPn_#TJws+_Ml;g3@2#1'
        '7AFUXEV`lSiWDHKG2JWJdXi4JbY9S|6_a_<G_&(r36b08^*dssFp8q!F-nrm2#7@@_0Xa%v3(8pfVcd7Jx^Xg|7(JtOUpG#dmf@M'
        '({jY4E0f83iSc{H0RZ+Ns!vPgg`|KF&XbO0HUp8&lDz;$gSqHu>4<}*63A5e6w8aZsQ7xv4x4i#v&ow<)pv%mr=k6knpVRX)Fz5N'
        '{kGP8YbX(=x37XHK|AW)jpkxe<^@<fN$-Rl7+;Jd1^BpOn`c8Ko+V*B1p{cOEdrpXnnxP(h5BGw0QXm2-OL~JaoVE)h`TL@To$$M'
        'WsAQeP}6Jy9dlM}b5w*iYjsX!$3$sEXn7|3UWsv!#5Qk4YY_kU_2Ek`0r)5`h{1g+&IG-+7NdqK`lKPr&9KaLL)l5bM^_Xm@Ll@_'
        'YXiRhTdu7r))oU5I1fZ3gY;oaP9o_)-tX+BGPITF28yZ;JPaUidzez-%{c`1TIo1|a2H1SpHVuL!9x|mlij`3Q6u($h20K^L$w5K'
        'Kef>U$jPHo?~}({A+uQVRJQxw=n4o*k;fQacdXScVP8j+t7JodD)N2mRKeIrz7c=N58iYbfa7Y{<x%N@F-Lh4>)rOA>Z}bT*=^Il'
        'TC}r#Zrpdqj8h2MMlHW(qHL`;;W8NOeAcYIYti665Xd@eHXS}$d`XtG#bD?hH39FN-ESZDxiYR;#6qQ=VNE!0hk71Py!ARAB8Gul'
        '(Hbp#!V3wjpb(I0Ltq=M5or*7k%KSku&rx+H}&nJXEbn`upqp>T=YHMe6^c4BDEHs>JK|GF%onf`Vm_A^-=x@oOoUH<pAe81EE5}'
        'Xi0|$k?R9MmzJ<{UY@Ve5n*<5xuOWb&@Ft<=;Kg-#lL~SJYRW&NpN3zPi3e)sn%EJ5=?`6b)XJ)B3IyK58JdJ4BlkDKLJxn>jYI0'
        'X&1)I6?yHb`?}V>_c)HGEsM6Vw9%<siYV2(O+Yj3sfpkYi2owBVmfXKJ|2ivv{PDLEs#D1UKsru&&Zh$*#o5U>I<;E3?oz?QYR&P'
        's!p>9r#A?g?#XGay<_@`j|9h%&rw{FV?5~GhykDW*%yT^9XliWNEo&=e|D^tyceK1ix6fF9JOG;vcj+mdh}=~-`P?B-@1J+H{<)$'
        'dd+R$+Bh7EyJ9t9s9!w^jE^a!-WJlWI8Lh8Tiq;8-$*GGlx~oq$s?3@6K$TngwbcxVm>-uD=qSnr)Fac`C6z#haB)84wAGQ>n?cj'
        'p%GwtfdK~PI?4dczH7Er6UhY+I&lu!ZkT4)(*hSo8<y2=u3@wo-Tsd<x>X_vQ27NSU0LNS;*|<;1jap7(X;94H0DWyGA+-TN7_<&'
        'KAuuYb3S_ySv9omgachjNsx}qOCeJPQU?smlAmYB1f>*3?9o-ZD&Rnq<FaVm*zq>#qG5D*)XRTIF_uj8T#`GnZogp>l5%)vi5N`-'
        'B9%f&=HUn>QKZW%m#f)1vBx@cv9kS9CO=uC4NS<w1FSWGg`I%!`s#Nw0lJlj#pTzJ))gR0=Ge7&ue<_MLa70*tKzLVIIz)7Z&5{Q'
        'E7D(_fA0wUzuytITSxbA=HPlqI=#?i^t<ch*jThv$!4n>orerHjj5-I3mK9{o=DH2%zSk}bh|d$im^U=FkQJr6Bcw?`U7jEOvTf0'
        '0e80kdZ$i(lLju;V5EE1QC%(LPj#(iSXa}!^JEXCKaLxsw*uw+a<bNPnDNPJ#=8KoC=c6N5es5)$&^Ph9V}e{nS=zJSOTXn9(l1$'
        'AhuTC&?<n365WYMR2+T5a4FYt(z?k%EjrCnz=3nac3Hg@3_q*izDtUP&eg+9K^p-9GzXIjO~C*zddSqo!QrSy8I{^6PJGZ#VOc6y'
        'MEtZ?Nc_zklzK0&anMAy;PDdQ-J>Nw#g3Khkt7!_sM*nlQNJWvrH`&BbW7XeIqPXzkt}9a&`j3^@J3CG0(>C`WSL-}o$*b0CHRxb'
        'W_Z>}x`DS#R^2wnSE2&P5KDuO?zXtPx|VsE?C?HPx9uJRcJm6SI8YUI5AqzJS`}Mn_GVTAr_TM`hiJ=Bi6OQvVAO#jAqdhq>2_tc'
        'f=yWd*bsBC8*a#(H4c*=eY9m}*;S7oT6|lT!>{!`nsMW;6DSopYKJWaPKp#q2ysbj##Acf0TyKjAtU}GLPTL9l%l7ZF`g_nDGKZq'
        '$pww2=)E_zMi_0|JQE%w7>5yol8KqE&A{bK!eTY?Oa_^b!G3J>#b9-|{2B%W8U|`x28=^1PMcR-;u-VU49#e5WR3!7x5Zi442Q56'
        'eZS;!Kxn+bWV}TkNY)2mw(5L#v0lm|&z8b{%23N7Y8w&uf?@ZxpQ8B@`%uATvh=c^PfcD-90b8S&zegV_IyI8ThmjW*PzYk78jTx'
        '3GQmXZs1}_cM7&6yhd|^2n4+~r_$`(+}j7~$PNS=Xswp<)P5axwYJr@8?_4GtMgh5YlG*Ao*{@`O9v72D&j$eyo&S#2t@j|1{N27'
        'T*x1obCP~S{zPuT2^Z-vnSRkd7BITtsh|R}wlJ)yC(wJ>Px-xaPkv8{T+ZvbCy<v}6RMx6*`890NBNCrd8%@2ssdP}Ztr1U-a+@B'
        'z11bPA0$`fVrV0x!98_VLnlMQFE!}~vkCf&cFhhK>d8*nr`4S{R#r+aKXRv099W9et)OnK6-;Oh4|>nd2!2U+i82t$6rP1iIa{oP'
        '0&b;}v0qpxB4Smln1wQ#W|t+05oq5#n!z*!cRyhEH~Sd_wOhjQw~v_b-hNvy!5VT(c2KD10L3NdKNJhhAhbk9G%hL@&4NcCkOlBD'
        'EG#EcHuH}34}@k~uV!;2_vPdbX#KQW*OhjI^rS@s?xse&fw0`vq4IbFZgl2I^$mojmPH=v3A*Bej9AB&#B6eWtnysU>;w!!#$%gW'
        'IFZ`Ahi0FnWx1FalX5^-T402As!~OY&7&n8-)IG*j=ZVa0jHV1xkq4|_nz5NBMv!O4O&NLB+%p(iw4GoX$5!}bYpiXjIt5wBjDbW'
        '*O;0cKUBBXxkR0!A!+FJjUKT011*>IK|3*Kc1qmK^o?>Z3=Mh95~5RWm}Q=~%+qi5;^5bP!E61$U-n-gD=lW<qz5*XgO?yuJv{n*'
        'E1amQn}l_I^z_+Z_n!+Ohp+Z~Swi?Q(8cKRm!oI<`KyDMuK|icmYPip)RA@(KCr`Ij$i$9EMq~BZ(@L=qFI7IE;Ee4$Fy@)lHng6'
        'Ub|BDDIWrTsu;ZC*bAdIafD@n9<OIFfd(7!z#NY)fZ-bLr%=PUTtVN82Cz><Z`9#x1QirXw?|jK9GK-z9$Egza=vOHfjdVHz*LzG'
        'lUo-q28fq!VCn;TI}C@h4J=}9k(0-dN7@=_IG7mJGN-i)E&H!-+uAJgq&0>wf>%G6<f*dsR}T4t5d@-zAX0U9Xe9Hi558C>o*YzK'
        'pZe9D(W>el(1Szj+qlazxTAU7GKOI|*&{>C97!Kx9XCT7v*+7Pw<ehJ-0G}V--{E@t+U-rcHF3y!O3Y0fZ)FECFw%o5X3XZoR}1P'
        '`yjYhOY*Ug#m3yT1@~;hJzH?k7IZZ_JbHfc@+p$?M^BHR{j?d2@O9b);;W;>9}kRtpyN%l{@t?;_iV#G+wh6lhIlT|K8!<0;>EjU'
        '9b5(>(VZ8feKoQ8f~^kPE`$6CO<7i;uskR8>E?2_K-)5D-u3RXo=cie5|V-f`kk4GmT7-PI{u_<z50NNE$E%F5xuzsC!|DtIe}5='
        'Vh(Iz9c!dHir7j>^TFYk7rE0?hyO97c8VFG*7!bZ=Y7=9yNKF3oi%UR%p<{bWqK5J1nYFo0PM(}k<$Axo}V_1XH(A4A5w69E21a*'
        '@DM^FJ0P)TtRH4T3lN=5#b>lE$s~GNtj{o-1zPnBM8UX5-Etk#^FD~@eGt#yK|J{g>P%%_fikH9%75N1!Ea=WA|P$#2+;%xsPAs|'
        '?-xNd8ORC$dj<w|BYgh$;a1^2+hcBeL3=()98k?sxG*s7wlq{02$@VVi3so`2+>lV7$ZA1!+>IOk0_xKRZ(<E(C|j~jL6!0N#RT-'
        'GKT00ok=}THCN*XLJOL@6H1e}A5NlG%{Di*jqzK8NRr*41qr@s)aV=V)eVHP0GA^>mXizH=F#P`buGUwobI@p^|b)a*qf`v%+ttY'
        'CM`S7EN1fCFbmmFlKYp$v#=nU_%MtmNf~@x154BMt;1k#Y$a(6)vy9^+J<ps|BP{+beQ>8c6N1HZl+@NE%@v<I&;cOG_wvhdoi^b'
        '%sN>e%>!sWtty6Z)R5b>sCRkM|H#<A_tA1ceYD(w?@L>xT=Rb42h05<2g`L|z_EpHddA8%@%Vk5-2eDExonV5*M-!MEgni&#d}Q8'
        'WF`{~27DDQXJV26WhOba8j}hUC#L=;2Run8eDEXiXfGj4-NK*8o{Ny_JzyHbN2o*We;XIUQrlXg{35}rbmS$@g7@glFQ0tX5u|G4'
        'MH&X3D(p5g;g<dsTo1Qz2&&cD${Nh6QpE+qZFhsSH(V=CLdt^B3H<{p4Rj)(*|J&DQA&UscU1?5KyP#}jQ@nfc*#c=%L|kX4=ias'
        'oY4eNm(HG*4ev$r|8^qzdolI@A~7{yw2TxKl27a{)NQM&Q>T3jVKh%8B57vz%e|oaUeNqI37UxxquFG1>G&@#d&W8e(Q_s%V6&KP'
        '8c8upUhxY!=A&;dqo|k;?J=+j5gUigWM~JC?|i^<X?O~6j$nS5*J&cPq2}1Vl-gj0CLckWG8#)*xDbiZ0%NqwT<HFw@h#PZCiuZY'
        'QIU#Wp%O!<!`3dT*@@kR#4$u^7zKj;R<LL`z8Dd{I?*{mKuJ&n2}#9TA}xlg5T@&^MKh46q!Dyw4vyqw;_#btQ7pkcvKbH33|OPR'
        'beOdVdc~VNpV#liV_C6~7b4yLqe_P|qd}YSFQSQPjTdthy@bPg8XUaCSB)_;IYd*mxvQ~CRwm=pK(4aPiV`RpHw8nmXyImw#h7g>'
        '9Pg4PSW>It0PaQQ_oDJoBPx#vaq1y5$J=x-Gyh}D%v*7_B|+aXxTbju?i0`53)D@4I%jaZM&xR8g}DtO5Dyb6<uA>bJK{A-Llw7J'
        '{=}PXh5@x)E<?I#h`5R7iJSzS^U^6<W>s(F1$!udu;C%oEi%yfWL`Hw60y~DrPTBq2$(p-g2H=LNVDk0vcw?u4KNjyC{Jg-V^<5x'
        'b;oz4Q31&z)m^hbYs9%-uQ>3%JQUJAlDBpwMs$tP&|0#($l%8nICg+(m)Mn}A<BhMzrbv8B_<`WVnc?KZz{3E$=h-XN8h%imWBMn'
        'aGi0=A^4kIu7mWF<)NisR9RTcaI97vq2xZ+Fex-Ejx?q$1D_Qz*O)oN79;nDD(;hDZC#;FYvrGlL<hBWoJ^SoGTeB?juZ1_<=ioA'
        'd_PWhcOE_d68^K51hZ;HE{ErMqFP-R%_aC`Qa!7`(PjCbQ!=0~DF#~s#b;S;yqU($fEQSRfc`3!gwL@E;-KbX@5No2RUusbsJ-}c'
        'd-2z%!U+@EjXixD(h|4n!OXh_eb`437jF=BJ8#SC8QKTy)NdLeD*y$feD=yQYK$f@9CezlIKLjZ9<IwrCl*_F*a2(MCqAunJjGJ!'
        '+#f_NN4Ri-ST_j?9lLSE&|Qi?ZKjVJatG0xqgj)yyevZ>St$M@4ngu8lr$D46+;($*iBr@lnp66`k4a_IdIm&3QlN%8?n8h%q(XW'
        'ps^sO)3c$0hFd{=esBcttYX7t*BU4%U4*=`E~Y|k)iD)nDrlTu_4uDAd<YZ`Wa;A7SI84(I2~##$vPy)cX1-7<z#kM%tPmaA2CT@'
        'S$*oy!0hgX2J2mKWx$|IoYalJkEjt6+a~CBeC)&xU7qOJ<xaHnBo?kb#4MPx%afMi<?h@yhG|8%osq|B4~$6Jwzp}^o4pmz%qT%2'
        'Z!B#OoUDX;x!aa_IBXkfOB8Yy<Dn}AxpuTL(hNAEQ?#@r5bZk}WIXE?quhL@y>R5}Fb89V_lo#!zxtodAi~C{(HPu`jJh1Uk~$2x'
        '3ctM-i!n~|niCa}JFz2jC*j!XS`NbDxqbL5UU%XK>>m0P<w@#L$Br6a4I(Vt3TDPpFmHS>T|l&!lzS1SReL7S%Yv&t6McVZ2WalW'
        'X}?E$V~L~N2t*vwWO%j+&)+ARNmoG%GdAu#)q#|27Z)v>z{9KOa7;?TtDzBxhW{CQT$D9>tAif0-d4_lVSKDex{=*5t&bGilZqh^'
        '?S)th@O|;$HePKDQYfJQCO63frjya|&;lk?X-_Z=L8pk*IvI&Nv=vnkn07K7f_`!uS`bNO1;Y48!M_8Baav#GEYWNMFHR1)kTkOk'
        '@f@m}(M(`wYxL>46%i5EWu{(I9yAk;B;-kl!`R7nQ-r9~>nBz)Pq3@8G&RNBv15GmTn)AoF1o>;TDVZIhLbcxf%Th%`FynUcs-Xy'
        '<yV~-mAsT1Q}kTeclGiOY(2N16cxBe3FdlZNF6yW;zWc=!SIW-nfB*nXn@-Du`5GH&xkQRD{a&myIrasQ+B65mlvoq?y|nT$;c)6'
        'h$W^+F39@0b+@+6^w-BBCmm}5HH;wTdzwWOFL%r-3=E<LLA*=De%-MYpgycxchr$Gba;Jyc=Yry`)ujZa<43spD$KS7wIl>+Cd6S'
        'b|DD1pN6t$2PYvIf%r&aC>ATjgS`_4=nWO2?Uyq)ZtX6jZf(Hxw>{ZvG+%0b1}?TT^|wk<MY<eAO(jLynyO}|GorAHuWf&&)m;b{'
        '0&b7@LIn~kcuCVfwLqcU$MjyNa4%E1mnq!K6#7R<yB8(gixTcd3HPFedr`uFkSHM<c}EjuF0FgoVg`9v?6)0M<DT`tXTATkSns$S'
        '#XSqoEO>j4@!yFdZ}VWe=g99l@_UZ_o+Iyyl5)?K-!tX+O!+-ie$SNu$1>$z9{(<F7NdesWAOm)j86}_?B28M_w4$A2)lmxx0m8h'
        'wQ=ZQB*&MK%M_m%NmjF?3oKhLW<I~>7%(zV-xPT7qEc?S4#c;+58pmY<V!Zf9>nHAj6B74;o>%w>a|$TXX2B}-0H;g`$C3P%#wGI'
        '*hmb9V_5(uBX3@GMlE22lXoySiQPs%BC#ThKmaS#*T*NRhMUP3dWjVrF+zy<XU<>C7n~D!L-D{Lj*Yjm14BJQh<-A-+wuQhXxSB<'
        '=uE;Wc0!p+dM`xyV+j#DczBGQCJTs^)f}^Y!P@-n@H)B-E#7m*x@H~Dcmamb?;^?owp<&Y*oiqOJ7;6C#%R{ilL)aF24P|nobw~#'
        '!A<|sH?dI!vOu=OWsu+Oe*4H7va{%?EzG-WWNb@2H)yc?ci<2BQCNMBpE~v_`^XJ2!oOM<Kz^6p2~h>N<4#(Gze+e%=_G_tHUEK2'
        '52R9bC=4dLP2QxEZE?|CJN<B1EXJ+a2@U0*p}1!#J{?1`iQwClFuwrc$E5oX$(Qd=;O#-u*w_%w_7y*Oj<QP@y@`}K5GG+`BBAF~'
        ';mNF`lB%0AD{kO6Gd?H>7@)%{q0whYQL3b)I9bBOxyo;g-C@q##_jNIE#MFfBqf^7q+XOE?W-d@3~@~swlLTzH;RGAFGdgpHw?-h'
        'sYvgZvFgiJ4YzL0#oUI2Y3E)(2DkFjSd}l5gKAnX$_m~CO!JHw2atr0mBoS&Wwfw@xMG6z=9Cay8}d9GhcbGUIuXFgvV#7BC0Va#'
        '^DQ@L$)cFNfwu(Xh$AKJT5-VTX|e2xk;FGJ21x_4wRwDjSpVk8eX0~spKNRfZ$;*0CiYt<?&C_B0Ts?2rawJ7#b`g_C-?*|4<-vR'
        '#~|*{VqQ$jK{|pZdnj<X<IJ`wmI9~JQjc%6LeX>`X{aL%_kNqS25l(_LLD{&2Z|2uBR4vqRZ}b)7z+@f%1t2dju~Ymx^ZwDDCoVK'
        't3#T7w45jd-;e=EkuNT<8`R;Q&)!3}cL?VT*fmRD{q*<O2hX0q$bUTeuj5~i<hv4*IqGA6VyxGx%DWJncsK@F$Ed=&1Ui>hNk(;c'
        'CX>`CmKSeP&hm~ZY(b+=Y>A5fd;~-!PBKd4^)}Kel~;nC$gj?@uf;lV=JhIsj9Aa8ND8X95ov;8rsZT_Kt|2-{i<97RS(K8@Ls@0'
        '3ezoGRgC(`s2EsL54ypkp3f%N2F13ldE~MEbOpl5#Y5gK!s~Kl+#LxZT_>>N2|^)y0#K(F+0m}?{Wu9plzp~tCRX2~1>nO7qOC0k'
        'LnT3?S}Zkcj|dM<(to_)*+~&|h$%y3Tm<|fK3GEy9BSxM9qbctq3B64CLO5J64;O1_~$MzNYkP2S{mEI?mP)J;hzaaTEz?t%UKDc'
        'rViZTqd2z5>Kcuc9LNf@?^`a!PI652YrylFAFHr~0rHm`?-vDX0&|6WO?(7JHdKG2!5X|mGaR+J{O`o;R=*2Khm81iXQm~K1|QdZ'
        'MB18z>1b@Vi;mjN%;v4QwRvJW1KKNE-@VxL<}dtS)P`>>ydit?44=^7r}hr*;dR8*J#==9iulA2Ll(ZVRgu!TjtHio)OyhfLkJ-r'
        'dmGDzPsh!y=XzL(iD4GADr7tuRK7Y{UfM&N293>>Oow#XVr`2C?Vm7?k$O!*0@E~50j3@uU!SxNwpEoQL-=^I)msTw?^>ezQN*b|'
        ')F7LwK(rJmqyo7U{fDpoaEz{$(j!n6LqUp#fRyMLxt4iG6eYd2B<{SEZGQ)U3lBF-I>z>4*d@|(g>#`dMkR_0-sxb3ag}5#Wd3^M'
        'iYqw;3^WRt8NxifuuI0~)(;D`x}nO!DVZOQONY2M@TFHX{Pt_GjJ#kYG}7|Q7t2}A+qEpKxcEGPur0gY7BTu}#;RNGINvh>xs7Xx'
        'YcAu<woe_y-n}$=u*nWvl4TN!8_Gdu2KP)UpT{bm2FMnhG2GJ`d^=dk5G*uc-m|QiAziaHP2P*xC4cDHD91wDx{RT+xb?ILT8+&D'
        'YJUw6I=1xzF2=}z94VC@2Z~Qfdfj#)q?p0%NPlxB<AzAVY~Ymm-G%EBVN?J<pORXE?RBSRGbyWS0WWTg(&<DgYT7KNjXJIr^*2*o'
        ';|g-ZvKm|Z(~GuI1Mo9?N3wm#g%&0j_Mk<2)Eg!LG600TGM@0jI_fP!9hXTa*;WjJt-}(3xA?PZuYh^Ui^)pzG}84s(^5HzquxZY'
        '075hpvq`6sVuDFiraDD{1Z*}7_S`}Y0q;dg#NDwC7@{}k(=2Jn`NJq_AF=NUW~6gen>H7**U4sVU?g&T0}&s48@s2lHh<fSkuj<f'
        '${JN#$jo2~hgO4Pxtg7e{ciH<dWmAxq7jW&QHt@?+FA6ou>fDW#VYwh)Y!+LR;C>uGiMUw3{u7*W!@kdiWGh2Z+HIyxuYO~>e;NC'
        '3fiCYFroRjOe6Jn7t%a&W*~XBx5ege(_Ey;W+ZbdwPq`7&s5YWOOYHxJY5kCU{TDL4N8>lw8!AkiTRDU97LQc!7(-pq^|*N&BA7a'
        '<JtznH+}#Rh<h}shF+t(I-gad;vhGN=q-V&r`LcFf-zqu6GkDrcPb-dcq!ILalA^T3L^N&JKsL>u0Kod#bs_Fb@>3)o)J;J*B1N0'
        'C*mPy?1V>rAt1>{gA~vQDpN<JRHY|T08e)JPDhP6lPm02iV|S%tkU0T=33t%hV<m|R*1%!Toy}#vmkCkm83hnkG^{R^^-q+^KEf9'
        '5#5r9l~o4;>Twz7xZ$z&7}{54K5I--uq9Zky7^bRtn&b;<#zf-vJX$LahsViOrAeIehRWkfojqJL%@LKX#!?_o}399Wd&)mN9HAV'
        'metIY48#T%d`4n<R*zjQYw_qUo1nrCrK>y%()lfAqFWSGa6URIRhpGSDDe8%=Q;I+AkF%Msu6qj21Fe6^nP%(VZ1H&tBJt)MxPjy'
        'IE|mQ6Q1;`r}I)Jy$JKIAZ?062+?==8R-=rYb|SETA#c?Fee6tFiB?7;nc<>mi1>C)sAg~-8L#m?&hfy{jSv4+xKMbV(8R4iqV#e'
        '0Rf8(zwNk&J8Esw-J^2>LI>2Xf+v+<n!8N`Xdt%EEPZ#A^>549xOJzViZ$9i1=R-Gr<B@9J?tIPuiDcX3Ig%$pQ3q=bWwg;*Kfx7'
        'Gb3XgGN^|{xr*9wcRY~w@aA?QTUx7V+lSndJ;=@MK>FBy=q`HNe{5p!@nI_<(&=dtXvBE9r93DEr*mOk<YS#(1_GzybQmlOSr@dz'
        '3QJIjCQ|7wE9EP+xe3jkn$Fz0#mvo&WbWKJ#<hu|qu#nox(+-XHrjTECTqF_QV`^_+8k0~6;zYx$Q@H?8yPw?@aj4{?hOl#@66+i'
        '_S3`$0aFh~*?O$5RW>rMD)0ph62)^cxUKxvI27t|`r=fz0)`ay`{dD=Uq1QDBF4Vtkp=MlFuv|eS{`|RtQure4r3=l=GB7ie8j;-'
        '41dNbxn9zA=k<k)c!@U!bJ|wTzysuEA0%i=3A2PB8E%)cQ)+0=9({t0k{>IZ<c66f?R~wAJd(FhA^CB$M}Ex2kzGk6ohbzjI|eOV'
        '-;#oO>qd^*ZD-bVz}_+(l1xYJzW%y~+mfQnqTW{KJqfvKMO@0ud9eTyu0fx=)>zg&9CIt<dO49J!^gzFJ<21xizxI0*E#;wH@h)i'
        'UfdgaZCf?n1&n}mmNG<gs@ffwF19Y#>0$kHEq*WA>aU%2&I<^I1iK-vY|^b3|9<Br!Sg2Y%?#2ipNm7fB68rWKz5R4#VxJ3K9wi@'
        '4c!{QNd8)u3)C)XX}&bo+n$yMm>-o=pCFJ*vzk=`v7l>50ZN+1f}_%Wku2(FwN1)V#F*O{HHKK?ZA>}9;bjtvhbp=)R=Qu=+la-e'
        '^q17j02&R(Nx%ak!!SOTV}H)g9lu#WRD-;)YW7V0CGy}UeAMbnjR`I$=sVK(b8ZFTYCq-P$w~gK=p2_S<5LBzP0Ck{k!>tfcgTvC'
        '^)OepHN<6SSc>>!_e(_~>DQJ;`aZfw7L=$szJ1Hg_tiU&zyt($z<rcIvaj$*^Ap}OMfg$}bC*8Cp1>*KE9~2G#XN+!?kt${ojD0_'
        '9CgWWuyIVpsLAae#zO270}&sxn;E$JK2$NY+7BBUzlMk39)LtDwxeb_I+~_u>9U9D{zIQ`+bnNd#{Th)-EV5^E)Q9&g}XAyju^P#'
        'xovxoNWO5RtU?DTJGj%uxm#vDIX2^BV`>v0leKP~-Ef$D<#M=XIs6#Lo2IR(Ato|YWTI1!Sm{Z5B^JoxT|A>v#lQ3pUfgQEq-~Ej'
        'k0^{53jVw6!D*$o9B;T~GKi2(tz<%Xe?td7S}n}=_xTs?83UZkqMidYBdBEXYOh!Mn{rtR8vei6^{QapxUAo037(~x0e{vW=Gna!'
        '^}E1rfRBt(TmnNMa%~dt>xA^Fjp>G>@=m4E09%d=I>j8oSfF-W<71i7OOT}SiW<0O?KjDgLWGo4^8#>FqtaVAu20SttKY?(BRae%'
        'x-H#N385`of?W;$(S&bkuZu@LI1@hY^7Y#27Pj>vi2Ic|8wzenj|<HMo*Ei<%;CddC^||`RCFkCPMs+m!E*2X(&HRB8NIA9BeOJa'
        'L@zl-ppl-c@!8X`)2Rvi6m&Qp1RV<$NY|Gj>SoXpo&94tszla2<~{D>&PYu}sMGT8Y=XFBR<Se{$MYdftjD1F+Md>$)~-6F^}rj`'
        'Fn~8&d@Zas-q@jI>(e`F_^j5(UKLoxUxx9m3%fsb_(}L?-VDiF=vI#hV|#;x><*l$o`%e~pa*=|(@OqE7V<P!d}M*hf#YX9yG+5X'
        'ug=OPC|G_=izyi|3k;!y(klv>(6I5rqL2+jMIg$n^%Xj!H`fA&__-|0fYD>ISQG;F8&tM9nqaO2CfoV>dJf~zB(r7PrztO-jep+w'
        'v)B$f#s3jgoK?VTGYvxL*<NI9W}7pD`ct4bU?cLnnqRx)4j)?r6jCOS6I~Y4Ci8fQp>efrk$GcnD)KZ0$=*(E%q6k?u`Tc(sOmlT'
        '>{M58n?Y!t<|zxjmjP}qfS?$b-u=_afpO|MZeQYxct_TWtzm^?&|j~w1ReN>KSbUrWgBCi6*T5BPl>ed@W&ewGx-%y+<Elcepe8H'
        'n8#m7{)~8#kQ0kenMJVJ9qvKbGfdq!HSo9)4Xk?W3TXPN`Oy^lqFAcQMKk1dq<2@bBHicAvejcmOL)AfCMB?#&Q2O^1Xe!L^FNiw'
        'P4u~&w$m#dr^Nl@I4#a~-SxKVa;~K2YWw|jsh+)WLTv#t);B_itD{eCJY=aq2kf7FZ1-?@i|#ZT5U2PyJEOgZ)5(FDwVhG_dE7>x'
        'ww-WiXuOAJ3xw{mIWdhvPe=41x4rdo{m*aVdmi>Rx1o3YowERnyel}y4o}mue$hfI_Pd)^@V=~A7jK04i}>UHetviwyrg;^_2T$z'
        '?W%W3PmblB$7*rYNl%JIlHwdalU7XvR2lmc)09VB2o#dIh;<j6m|U$JQKhWbf()NuCvfbOy292<Vg2mILGlVU?W|RYwt}D`HTt0w'
        '9aTl375v^5U5do26=(BVb6GaY<qU`t*mZCRTrEL4G_T)%hoC0wB_QDB)xq;jYH#tv)sr{i`-i({#=UAZY*>m08nYwQh-WG=*rHsD'
        'VPAp6l7xYGx0%sF!rPEwVygyynTTvk7}JlEgH^L-Y!)o$<PGIgY!Whtd5E82`NS~=!&`B-#fX3pot@3gMAQ4p!Qsf=g*RonXmHWX'
        '_h<ldk-R3;fTR7V&y&^VvR+?YihspyjOmZ$5g}HFoKOX`V!P0)w?;eB%4>kriMq~4(!uq1ofV{?wwi8r5bbsn?Qj&8Cr7!5@;<{%'
        'z~(I!?I3dX`n)o+rXEub)&-Hu<Q}7&^u%=#*lz>>V#n33J674a8{v&L>a)eJ8V!ykC~@2eJC3_UyL{4Q)VJ+S-s#-1G~-7U`jW+W'
        ')?c_AIxG5Js~|WNoXL@xeZ7LGcrX-HN94E~0mB7iuh$?HA&?{0pR!}hrEGs-1=v$fjo82THK$RDqdO44GSy(j2VJQQ)Q~lNa8C9{'
        'BqyWB69qID9Xc54Mj4^(kP;h2J?|5F{lkrOD=As1m`qoIPrISO+e~c?LUCki!O0{v?{^ZcrNX3<k`-_~^L+iP(+mh4rI#P5IUs)>'
        '6_I-Y@#NIasF{GEW@*BK>q+4y_kuAba4c2%ekG$&W;EzeIC`d&EGIw}6F*9TCc96JAo(FrK^h|frLV)57{ZL61JVxq?%JQpILD3|'
        'fhijcg<Dnp7eKYm32?NIomS8#RyMX|Vyyv!%r0*rZ&Ra#%&4!A509SyWuH=`Mtj4ZoUX4HjT$byDFLar1eN`DLy=8@Pp;nyLZD*G'
        'D;m;X{Lg@E>xTOR|2;>161p^q$|!=l@|yCUySzaR`<)T%Jf611E^S!_3j|{GuoC_5b{0s*E?E8oZ19%c2Jfq<#Qv%Xm9Zj+Fe7NL'
        'XeU)=uwgX44Fni0K!D+cDkE@Ir1%#|0tsg%<qk-n`@+otsV!*ec5#qD4Fv;)EMq&IpDGKH=x!-_F<cePH-geO$#kzvWN@KJFrZ*^'
        'a16BBZWf~whtVL@<unjW7<qM$5N5=}mUXq01?vWet!YGM;}gFjiAe3i;j^!IF()Ylou+{}$Bj67%mV}cCoaA^jdU`AI>6dKZGfW1'
        'S;bDpcorHdR)mZy!!S9agSR7GN=qfc4CBNHh05g+*wzDV#>OU>+ONKO9ERkDL*jPQdvPy{cy2@g`SXw|xTI~rt@(-KUh@!uK=-q8'
        ';@v{+PmM=Q6%2#5JG;@4T&2OS0UCG!VRb~a+X@J00w{LF=xU~5;iKlT+c3Tw1z017$P{7;8o9Wr1ce|N<F~s5OL)>94eeJ>hAoKJ'
        '<xKn*V@xza4wVG>LZCWKNKG=j0!G%9Ab%>>jShwep^}1@sO$}5T6X4Q2bLfLB{dMR#eM)k2+!tN7q<eH)CxcYZ+jOQg=*OVmN<sH'
        'ekdzFP-C&i$p(;5cIajRk|Q&VkVnv7>d0t(=j0CetUY~sBtlBF^zgMTts4n4JreJQc+_MGA3e)4Q-#9P(+&p2GK)VmSs<AdoE@TI'
        '_TmpRM9j(m)z+Kf6KtLuX&~#BIDC^Bi5`W)GJU2zNR<IL@04`Hwj4=Apg74kK$4rQj4E4O8k5H6xcNjHx0r7a+s+>?hhSsR&&wr}'
        'XJ&`7)f1#yTQ$bovvUT|ibA4UV7vZ_XeIRrW<oW0mDGIeYBDdxAq9Ob(LQq6riD5jGVT|axR?NPga*!P+VG(&TOi_ef_`s3_9SxS'
        'f>?=1AG`vpEPVdSHaC(o2^auLeoBr{w3$G#qKoy?p-i<sLW<D}LDwyXd*N(Pt_V=HROTJ#N9;vA>ZF(Td}{iGX#LjIzkR#_&ee0B'
        '9}E}PZJtl){%K&w<r6RHeBGd-KaDXbHC=uU5nkdj^x7kw*em%U9YM_wIBI$9SInx|wr+N_wyQ3ii#x6$2T#hWjjQGNaOgr+Naqy1'
        'tlr{D%4bzgKdulj!>={i;=qrKndc=fzE)t(L=_rAN^on~*1V$QnNQ?j-g$wM-PGtw&LWb^0%~%N6FJ3G0J!57!K8H&j0sTD=yiVZ'
        '`e^?z1FJ5s%V~R8v?O@WcD=&&jFC=_uRtmO9<*Y63|+*5Zf=4Mdf)xwmZ6zcyCRRBZIcpJ7FyLq8bW=LV@8iO;kG5=d1pM^OwKSf'
        'Bo@|40^m){3x)@Sd$L3FT!IW=l$SaTUBbs8MqIFMRAxvIcFXN20s8%q8zT7`MLPcVYdcPIVT2{t^8m5cibM+JI+7?_NEuzsQ1MkH'
        '3nTV&av|6bvKT0snckM6SVd=SnX!#_85o*X+YYEvkg34-B?K{JgMwzgSj<6^05$~-glsq-BB-VmY^&&ber?+jeB?0B#(KH&o0sBo'
        '6!)dN$iX`RF87nKzy9ip8Ws7kf}9hvqM+OaIdnPRF$1&JmB0ZQDcOQ$+#0)&ZGnw!!vF*dr<OzTx-I@}Ns+{Y5b9+sK}irX+OB|r'
        'TW072one~hP~=$?nvL`kqXc47+vtVj4}aGM4A{WEa6&{CP%a=Lf)kHMyfTv9p1BiP!dvlRci1*NE#$G}Iet_-97H@uo+%<SP?!;g'
        'IXG<fBzBI!Gq`lG*wQ+lbXy#0HS&)fKKg;vNwq33diG$(c{2$Q1*|EqK<ItG68IIO!1w?ywFuPfq3N(R8UVJZa_W-@tNj>3YUTbI'
        '+VD>uhSqNveK5^Ypgt~IGnB`)J%p{Xsd>E=4`#8v&YQ^+LPu$7rLmMUexOA)45g@1U3?W|&yId+96C*Ybe%gphJN@E-7Msv7pNr|'
        '@XrbQ=LT`oao_B)Z?S-XfjEB-hx4Bh^Dn-jfAoldW~4u7$3I$}KmVZijPloS$ulp)-%SJjS@Hd3ct1b7pC8;W5Yx{O3T*}3_;(2H'
        'hi`X0zF(GX5a>4;0nmD4!Z89r8#}(>Eiu?k(R_ErHNAj>XSuqP^~x#nX~v6}J^%y1@C<GlV6Wv=cZSz%i>~*FjH%c=)Zwio9irHz'
        'HEx@xQa?q+$2*DxWQPIj5d}yE0rFx1MX-|l+OsX57p-K=_u0w9;eV{?GlG0@$uybq-Sl2;QwnDN)TN&|&QO73i#}0?+*nf~jb_%R'
        'u++*)M<Y4hASOkx$P*hy*yzgE*&~dGugDIXO*+g;r<J7_QRL&qM~e5+U&n8-t6BxuY^FGO(2W7d4zUkhja3ND-O$(B8+D{kJ_Oyz'
        'WoFs<raJDM>9>hH4=A_Cn<=+FI4c#bqD`~yHnUWyGDo6ka}cp)Ff9;llY?QjLtFEUJzA>eEUF2P!;GrRW6JMLYo=|ecV(n=%V?)Q'
        'YocSFc859*M>=(0X(P^QD4ds$ZmRoHQBK_;rz*y2B*du`;nWRms^gl*{e)xjO+R{EQ>~VfQB7|Z)U<DGPR|GbV+TN`NT)^!${UA1'
        'ZHpahgbs~F4kg>wK-|zjO4v}8r^SMXZWJ?=AjycKpC({vEM90^xX|!=ZJ67BBfqph{%Fb_O?jjBaz+b@$@?@Mx<Mv0)2SI`TP7jo'
        'i?=podHfKqn+2oPtd<d*rB@_MGXO?7EK48^r4@zJ3qI-OI)ewNB?hI()S0|o=%q5_PU^1s_UkY-`bA3(3?6vQqPfpP@n+5ZX$H^X'
        'JT~#DGJS(ne#B6je(+0+ZETAT*&Scf@5x+z0~&s~O#sL{jzAfRop;N)deLx^KCkLWf$S6N(S~n27@2Xzf)&~TIUYv_tZw%tA8!1P'
        'oNkm3^UlIf^4*n@9y!qChu<sCBRu<3mD&;FG8m~c9H`QWj!MB>Bg>>p6#*>C-VZ@#uh~dZx^AFYE<j_sU?eMVbSK=Yoirm@qeE}('
        'Mo9F1a{2_1z5Cd)sKg+AC}VeKiJu})RrSMvW?t>qjC%GPAAHxN>GVEoL{Rf6=@3|dxM-klv8rwns;a-ECkLvsoG6XZRFTM3w~6NU'
        'pgWeAeKu7T)68c1keYC%_<L;vX=l+w@l=^nY?V0f84^MVWG~4lb@E|&t2l`qCefnA`vpntac7;7d7%J_PFzGo)oezObHXDU(Gl+;'
        'IHGoFlu;sF^87RutgeMbx(}wfVKBwtIhJDQQQjny;ztgo=*CgpEPkSkD-6WqV+^a1MZm;`UMy>Yot6!%6X2@wa@mZ#C|4Ry<qE(;'
        'oEd#xuk!jlCvXVJDqby%$r~^g4jFnFqqE~DZ<LqYU4;{4Zl|qF;?(p*_bT0hzedK=eDEh@z&$a*gm0|n+2Y>|^;KU&_HD7namE0$'
        'BtA>)T(->0xiA*M)=f8=Vyl&N7HF$e|GhUS(koS*?mQVg0}Y&6SCOZS!il)e^6$sV<DGAxFeQAAG781tpBp|rhUbwLC&}yf+CQPX'
        '#O0E5L1?^b^!vW>U9IFg(cX|)t|UdS_~U~|7W+BCI~=C;%M6}M^z3m`bzYEA4U;$1@TkFwQ&}7g)t*93V)Vi>SJ&}k9LCVuS1ff_'
        'ceSL?C)RqN>gZA~`)8d_ZfY!k%Zo27yZeDnxX{=c^RqFXK4%J??K6n>*wiTg7Rxit+#S#%;VvQN3)eQcCEy6bwd}3skG$v5xf8cW'
        'd>Iu}*?Rb$8X0dl{e5aLBzY{8b&RX^k6O>TSDDNGE2RoL)S#*-b~lpv#<rnEj91FQ47p-JDDDAJcjpvWrn#Igate)rl<vFB8e+Vc'
        'RkLnDjRDV`K#0z>$b;>&f0Se0=K9+(EKi58fZa+Orl7PeP#|kTuVz8BG(b_Zb<C#F(MH|*t|*<%oyJ{`y7~PPA}_0;CrF|OB1<Yq'
        'zyq3J!lat%#m4bv8Pl+Jsf-^i*!JrtdHU@5;MaY20(?g9d5dL<OiKeHhxe3&p7N8^o_bkwK6@`<df9^!+~Y?(4aIDptXK8<c}B<h'
        'vP9~_^$^5h!cBsHf>uaja2niFR+89)GZT}&?<m=qVTsXYyM#Eq=Qa32Br?=sBbL7q<E-Y_FaW}FY&Hx>=DTEF32qN)dpOtS?4p9t'
        'jbJ;jlVbW7SiR(|T)l&EDyHOt928&Hl*bovVMZ~nal^@di+x=aO#3^T7qctzNZ=s{pS<(tx|+bPV%~xv{=(ssVfh~N)Af*!=|h_R'
        'Ls7gf#+ab?B%x$AaxK}2{(pA}<~FBJ;}%4NEi0N7{ec7VW&^}x=e=}zSC3+Iysx{!ZN<Wf@u0u&#1y6*G&Oo4F6NCQJ8$F|eIMKT'
        '_mAytc4mlzCm{E{hTi1wPaEC&Q-`cJ!wVlB9v(kT-OeBC&L2iPPq)m&Jfk>1C&0)k@DJ101s^T0(;-Id8$?EdT|Yb%+<93|8;SR^'
        '-KmX?l&GT3q=h1n8t%w40I8gTk6zSR^`V^6p(IyQh;r&gsiuJ0oVh^MQ6Vz<n<}*(ps#A!uq=TTU4o8SR};#a0QeI_5NB!IU4cc('
        '2C0;p2<nkJJ2ntW?O3evK}QP~6s7-c4dmRj?rnsgrECl%ftps9s)S?RrQs-ax}K8z=oSVLomZ4d_HdzXR1}z<+!iqFiC!O`TO_z?'
        'nhl3;6mmFGWa*`^0c>d?)F$otNE(9y--FHZS(If!%;x!sUNu?8_xgt}FgS=jH-RXZTqK4kZi8SmmOO&YA77-t{3KR9f43}PYw|qJ'
        '<mX7xX<00014l^AW>VvvanR<hjhYwp`b<zpVp+s}d0Q+S9;_ksq44uv@4XQUe}>Hd=5g?$of!n*34D(gexIQCKqPWD4PfZR9e;P%'
        'ao>>+g}6OPpyk65nW@TEY7eCCiB?D>$D+ggd=7fl!Ei(&hfthl1{}Jh$m(`r^&npA4z`{x#QB62c@<<2T#eOoe43e~Qy4tHw}`oY'
        'SK;E7hnnqlb{{LgGxE9<xS&@scle(ZeIpbp{*FKcv>U<d8>(ITK*j2PZ!GxH{_FjtU!NWy9KL-0abmpR)v~?2@uEd9bW1*v4HHt_'
        '^l8{20=@S@xp`YK*Sq0$z}7*^U3L%FFf}PU+lD5ng8Sew+)S)S$kYK3BOd9VD_9m$TVaf;YT(IM^nd;ebFTdbDI4ig`dV{pC=^!#'
        '&Yke~o`TkvrORg801J+Rc~-(kTEh-_wl&s9Ca^w{dR4A2YY0~j91gnxfdicUgD5=Yc!F1AkXpg}(~J*qWJS3+@~jJv#f%}JW<B>w'
        ')f)x~Et;W0F{{<djL8q9`2viV=K8d@C0+t+0KZVq&xvSmtdpfG0F6x*WT(AIe_7cf{o^oP(%&cO%}tNvz)tSL=C$z1n~+D^*#_5d'
        '*nt;hK=vR)Xh&rnsKSHja;yq=AZwo2+GB>pBkLaB4f2M3<k8&p?dcUAKPsG+w498p7!XIa1knF@aq`JH3?djJy`Hg?79SEBC#!ge'
        'N@#p1sUBCuT3=A$O0rA1EHH_tA^O)@Gf8sT$Q+>%c(RzR*2UbEO@2XmIbjdY26a`lrY616tApnc4d<2eTx=jz;#K3!rjVwqQt3w_'
        'I`?%WUa9G<8l9~n!s!S!QG;EK<$IRyrp7Y)d?rcIj8HKsz+W$tvtqfNiSFJN#HTA$MHLiQ@q)+<L2qI$+d4CP;q^|~HBc;w+cEbO'
        'yHpsJoSgqglXt+y!2tLv6(7>mo+AOfXVC0v5$<#bt0>LZ1*Zssf!=CKXtBI_i=q3KnLT~U=>9;1>g{Y<R{}F~z*o51`XZqik*rg)'
        'ghJWv$w|>cV^dN0fNy<L{eYA_FpHp))Zq|E%DQK!1SY0PN7|3TcV%LOClY?Tdt-+9uy%)*LtG3zhs$y;PT+TNHP#KPV=;nHI&>pr'
        '<3@lwM~yWj-3_g_vbU+$S7+stLX{$@(d&c19Pc0foF)42zaG4J;fH~xH8CW@+L-IaHMTpopQST#LEoq^mX4B7+?&~azPQjUozXxI'
        'NgbiXSJcIex_+}>;Oe=;(?*AXg*BcBl#ma;ax8}23g2T(8!`{Ap3j}9<o3(sFOiJ!JZk1;xfqOgz8-38u@Q(V2Qoj?*XmH-a0DF('
        '65)}?L+nvf%uy+Uh*>JL<*mm{4<S{=T<q)4<oOuG-6=bZ=S$G9uguWK)EgN!K<;A<1kmVI*xFJyL8Drgf`wec6BX7<tOvb3?iIza'
        'Bed6SOvBr~`1$-Ic~&e|7{r<0I=(ZBc$mc1BvUUzt%A)>@}hWCK7_zu30uIiL4&1O9kKdY@5sPA>ekDTN;v<x)2v58OIOpu=L|J5'
        'r<Hu3Jm7$yP<bebSs-Es5&a<foJ!$cp~8R>K{qPj+F;PmfC09%`8OHxU2ZltnZnV`v0-W1XWz*_A@tksl9)7sZN18$qmh<L@9>dR'
        '$<4t`2O|hfsh`ikOFkd{vj)usg4d6_Vd<sf&NY|o6~w7CB_{)cN@s$y09&RC(>-v`b<5n#HAz@pQe*&yD5Rw~${Xs1gFJqqWOZg#'
        'BM@@z0lkV*!JAB3YhfUDpjqX+pQzw_3V{eZI%cne@qscG5Z_GJmg1<>3`6lCEuKPfcNu}!4s-CE?FD~Tq<aC|N4d1ya%r~>C}0C='
        'g|D#;ANRaP<?-$D>gtwqXL1ZpA~>0qs3bo^++H@dP2nVXSr+z^ugwq$wB0$r4Wf+y#^}HB3E{{}_$HZ^;O_u1=C~k^jH;`?8TFMR'
        'PO&l)IlwV^mn9t9X^*$i3a2MHFgJ{#=&5)=*ct8M9wysz%ZGN$$s1Ag<TT?y1e#b^6JTh>XUBkxT|f3P;uUHb#pc?&Wt7c9u0TH^'
        'qy<i;qOxv9IJLIzeKK{j93^ZSjVTbtpv=MO>ol<XVG?qQ5)<UWa><?JM}ZjeLRi}xcuv@G65+Vm8szr&$Z@SfYM<;ramX<YTup#R'
        '=P1_+B<{4~Nc{VopBxBHuJ;hCDI5}<<zik;%0c>%_d7eVN$K!p@9W)1frOo@6f+rc{#&raaX7n=z6rs>z+ro8YVc=OJDI@cM#xHF'
        ';Ib8;yKzKMWh-;}Im?Q8gy)w1;GC+Oroskr`7Vgbfp((pdHDEG!WYSN{SqwJXM$d2j;g4LoyQ%p(s`)oK$%vHGKNNsI#Q>lHin%-'
        'judH-mo^E>brRAtB!tyR{;8Ki&+p&~4H^NmxnFSo#?~t0f8Ava+;lc~s8(i-be14>1xU}(YIn?H8bL*f5A$_%Y2?>!mu?{!M~4fA'
        'Ss-pO_ZpSupivP8_<Qtpd9j9QkFT&~0HoD&hET_OKCLHtJ~Uc_3rAjXlR>(@Ewx6OG~=R~0YNr?rL1KljimrvLfMus7Z$LN{;j-V'
        'Y0sW>4hmEt-Wj8gxrDneD3Z%^z8I_ZdHu_)S4aD=UlTa-8CWHTN~Q<!4HsHbm+)moUFfYbM2uL@bI$OOSk44jY`J4~;aD&DvLGI3'
        'NxZ4ITF^il5RxSm%J`H+L^_PiKR29&7_*@aYYX6wZ6Ch<+K@)}5S^Fe{utg*Edq8r;JreEIRg*aH4-qCC_1Svl+2T=WRDGF7c19A'
        'S8||v0ddhloJ%P8YTc{^Kdo5%`E{~DrCBQF&_^^2a&MqUt7Tb|JP^eLJSHWAMtL6~YG|?$@17v?MhxwxAas``P=l0ARLD)>+z?PP'
        'p6QHS9)5cI>>0SatOR;1D6bPQq-SNCqPLhpccd?B=g3m=6ek{6CIA!(%D*LpCgs5b>;f&^D+uB=*vX`|>u`80@#x45C$u(YqAWMn'
        '8q{A^O{vQ~GELfF02Qh09O`H6HEDQ;pH_}5wg@i-3B>$c0muBtM#~SoOlaFTpJeSQFCr|ZXb?QxGTi%Cr#)H-b=tOQ0qUEiB;)oC'
        '4TDD8o$(0;_@c;7fNQ~BMx0&86v-iLJu{MV-1;Q5Lg~ngc6=QNyo!$?YwLgsr<n?*APaS51ySfnQ&80cffk&8L-r8k4FcM989<Et'
        'N4T-z8W;PjsKlGotY~c3V<)cTzsf2PRp##7p2N(ORU7gFIdE5OaJrGKkTsEKf*GCwRxBqaq-0|O>H-{tNoOJ6tZFJ&g|a=B=!rpk'
        '6hxc`z`vH|!WK9y%KsrH^h5R(*#|*6h?nGy#Y{kuP02BA6c-+P6tg%$C3$A%sKXK5w&WfLnjXm#YiE3enzoGy5>Z*gqC%haZrcIk'
        '<Ww93dve}v^^DUW$rEx_GYGxFmgKSACJe-Dv6rODgP_?42aUHzqlKb97>u@=24-QZjSy{<x<$sL0m<McXqiC`y$=#I77e;;2g$8P'
        '8z_H&RC|x5XiNOkd^p90FhAKMAEQ7sk$`2;0!~W&z@~bYvji*6Jkch{b2T8;97D?NK$EN#!&vGX=}e;q93ye%y_gtfMDY8Ljf7o^'
        'CiDSNDSL0aO<7&8%_rQ}P6f-V0zyM9m+J+|ae32#&xFY5h)f2gdCXAoVQN8jODRWkb(HG3j8J&Wv3tw6vwDrW?y3GBD_ZUDRR6;c'
        'J+1!p;N>yzp_WVs<<|lQPihnw;nor7GH%N{lsSThelLNOPiTB{ni<}LD8EsOa(J_3avc8CN|@tryq(2mJg{;)NSl(}4ocxCZi(95'
        'vK}|4GD6lY+W5BFWb`a!DS+gHxkBQo_pf_%Wi&7Q&Z0cfvI>o8#Gsk4{6Z2tknkj;2V+U$q!9cU%z@tl)@%73WWUKsB;(ITB`yva'
        '0mNvO5X-zduOGtNEOf8RcLBjW)EUU<V`%ws6aVk~Zo9ky4#T%g>Z#~=ER-Cdn=V^FFp5#=PpXeL9)kiQD1!&$uq?F>(&^0I&OeXk'
        'UdK8;rj7PHRfh!5bUC%A4$F@(q&t})F+|iOU=gKBLtBl}ZeS_==lg`;?o$jvYOZ+b`3?f)qY^CpB6+=9iU(kRO$yRPMg!r%6#~C5'
        '>Z(C2KQfECWFcAvoIrTut-68~*E+wn__>^k#r+owRY0CWX1g4pVYKl&&{aXVnWpzTgw$lVP|@?z!pli^q}18qd_AAH`B&J&x{Uy4'
        'N#08Y-*=JVm;s?I&t0#D>ZePz_xx#s?3F+}%M}x|5YU7A4af6H4ptFhWKtx9W$5#kVsMdp@~?7PZ%caxChNinh*2xAb{M&~EHS@k'
        'or0{$vlc}NH#>?UB)P7T>Y4J@H4O^@XgVbE8V;^)g(!JXY>BYBqaE7(FtS~Dj#gqhY@(vdq^)b8;~8gCiFpj)Nz2lP*+{If*~bT<'
        'kH-v<vM4;q5Iuhb<DbZ|9G+GW$~5xnGaSuAYL@dDe+^a;sed)b%|ajT0M(C2L0O%o8ObyqR$8j{k<&2xW{oKO2{EOJQMCngcP)NF'
        'hN%mX{5(vlE=YM(v%Q#Z@Ajgu-5&iV7%)<(>H9Nr7sN)0FB!M63&a<De?o7j#SC1QV$x?Nc+`Rs5hHd*s`Mgqe7kds0W+^r4TAa$'
        'Vuu~V%cp$9yt7aIn&O6LeI`R+V63UZ2?$S!VFPVPmTv!$X058EfTe<=IEAJb8Je|eMqBwwt=J4$M@-&L$EMMHR#tDvS|TAW(NRO{'
        'S*M5HxL*DJ_@~2{ubv+NG_Fb4BB&X%fICsTmdxrD;&_4LY%TC4{AP7hGZ>z>cJlJ@m)HA8uMdv*$Eo15>ErXmm&boQ65qh__u1id'
        'Dhon6c=hA!{Q1-4r?2;qU+1s>p8tIC^5EyEFY<$*UmYGDzs8n!rKi6fALa)yUmrhx@nW3rv;nrOo&%kdX2(ZQU%vkF@aShT?)>n_'
        'A7322!~qU7bio*#C+pzVe!vq3Z|7Lw$1w=(5Ro7&#AdQ%KmQZja9<V8oAFM)^QS+B7&46X8t2F!fvHU!!!|@BF4^Agcj;Ip6~1eR'
        'Iex4EfPrIl_{$hg(92x_MAw2eU^GI$HkkX;?oi4cb@)s-5~wB=2ngN7*aRYolVzeDNAnY*(CK;!oJ@4?{*FfFh%K0u-Hy-+Y5=ZA'
        '!)P58NDt!WXgM_4aFCI)Rpt8?dq)P{9d>s7>dR7GzHt5BEuX11-5=toHO77hY?U`T<m?V+8t_Vbg{VPKToIKLm~)TP>o-5QH$A^;'
        'm;&8wr`jh?=VNbc6JFKVr`+(!xehJ68(@+fNU|b_q+P1SV)D^?A>aVpphVYn_>FLPuB00RYb!5#4uZ*LDw4M;DRba~$ZltI+}|h1'
        'z1!8$q}_dY9rD(}<6zki^^_AZlZlW$7Bj|xD_L2Ptsz3p@pcNG88J%V@Ek5}=oH=5X4PhUvw*vEf4vEtXQs`1g1j+IG(ethZnxRv'
        '?5LYDolOmaB{_x6uTy*TJH2R(>vQsXAeP4G+UC5?^U1k^T3Lj&p<}H-c9G7uwAObNQW%*S%pZF2n5xAHl=zy@oLyZJql7V=1~%Y~'
        '$8B`{7HF(VIYtJ8+=b21NdqE^nIO(=a6=3k29^stic>TDSNZ3iQzI^VF{i*!>-lQ@an*Vu)t=n!)G0_Um7l7mzqve}yT`n6xDd@)'
        '{%Kl}!elr+Ngt^JHE7>X188Qg?9jHH8bKi!HD)Udnc<5__3<yUbptOaqw}<Sh9kJ8yuBo;(w${S=$bKh;pkC^!-&akPpOr*K(OVB'
        ';#~Gs#Br>d9!ir|onS_uJL7aAh@@P1mEOe4158S#g{b2dVA%vgU)!*v$e7C27`0oCL~$3%`zcvGnstYye^fr!;y>s5^+bJ{dY|ag'
        'Bf^BK9oKbWQqC}dF&Y$bRl~}`JVQzs>-mU$k-R7`iU|<sQ!wsDO_IuhJW7r)wTW-?>(}Z5Bm3X_3_@%hz-FtE=%4)en7tKLg0k^d'
        '<~Dd3M_Zf8+#`gCO-!^aMY@O-D>s{IR};JrW;g`PGm1F(){*q4<~ERAyQBB8K~J(Uc<*7d7W`Jd$c-q=8wl#d=1^g^ikN}Kl%1M0'
        'iA2DKL)0t>DJq*1b_h%)(J4+pI9G@xy{^QBFz;C0Oir1~`Ch{*wlchiPxf|qc6QvDTJC+m!@CjHh;?0>8*W{E`$AtOV-S-8^xoM%'
        'y9+aAK8>~|v}r*JMwq1uO{jCAAB*R?4e!I}FUI@ajt2_wrb4QbMQq>c@BzC6J}dMXFw!gGQ7)%uM1wj<0&!?$AOCEe==6#~blZ=Q'
        'bNRV&Y(z!ks-dtye4z5MAABc|DZ4gVUx)syf%1FnS#>UDZ{AN{Vw+X)4-o<!QPdB(m($sDK#2}<gUw3lIob>&);|sxVz%^IN{tj}'
        't1vmyiFf%p<p?6@Ok#bO*F4_wOKLY1|7YC_Ngv}Wp)JlVD=d9MkY$39>*(@%7teyVXnh~d7%th=C@_&ix?4OahXHeXGNnhi1wp^p'
        '*88F-9DMfsSuoiqn4KiUjj)W#m)TsHv;^Xya>$h7WGVVa3pDd0g8?=$WR3Q>BB?uu>mnwwn1`;BhNlAb;Q%L;(rHzb^Ea|A;&5xv'
        'M##F<HoTvKudFT}vfNhsgCvBPm;h{KY`^c43Org`;01YDdEQVeTxiD*x+U@9MUjUgfH6XvIB!5}OC>r0M|dYbBIn8(@Dp!k%rX3A'
        'THz~C8R<vU;Wy)oGBUYn-QD2zLa!q*y0c|i?TZi=^mKL@74Gqnx8*6a1H{|~sn!Y16?G(z0e{kJ)!%^wr3}$J6Jzsybg!L#)YP_*'
        ')vs<CK^kSe5q;9#35mBf>K^N#F-NZcHgheGT^r+oO&!1VOV!TGeiRR|K1<YNx~8m;p3c5Z;ui_|PH?z5&_pIu+9`!vfV<D&S>mMv'
        'iXSa!n*g}-y?7H1aizHa9Dqc}G2syv5F?g@l#nVg0B;{ndh69CWh&g3{DzzzCBh^7T$%Asl5_p3Pxa1W+Ov}US3I$=c8}zzpbz%n'
        '1nURACAT`?Ebom-q7=GR!^`=0@|59~fzaZ&T9uExGQaog;PBYF>OW$Yy4ePgwvf#`9*<i+8m*7TrryE0x82^sAMK6U>}{~#gdkg_'
        'T{$!MQ3vg>^a&k7TJoTDAm}2>5G>WaCqWONl8?%@ws5O%tVx$ojr)GvWL1Puw<`rX-7tqs))7{7b5%RUtM1bH%R=x2V79ilzCfMW'
        '3PONlfB_0`0QqYKNpV&xFDi1VBDW6Xn#dpx80<g*6OZytvYy-0QVw%IfbL*9N`4RzJNF{EU?4s$M$rnEG}<~odV273|0qA&|9`*i'
        'zdp_>ZBn8R%lYm%+bUmdvn{8gPtI<tVEp>%=3pMB#!#L<|N90Iis`jA3~-x1c=_~2ZxALgwUtXSKOXGAc>X#uQ&mB<$|*$uM6+-R'
        ';poLP0sCX*>%n(TrnbVf;sjy>ASyBmKvpqKFwUeI{sgK9qLVOK*P%5_!of(y_s+l~3{v%j!7QPB!SbzFW%@xc&*3k}uYNhE^+Ay;'
        '!G{z9@N;#wz=n_o0DdfBCM)<gJu|^PJN#LI**8~vR)M%yhIFf!2oI8@%^*iZvBX@I34~RGsY4Dm5I(Kc;OoVDZU;EQ^)23u)hHKD'
        'zJRnE%PaMf)=hmj2KW5nX#d&q;nCl3m-SS^`$52XE&g}~w2jw^o%?iBTrCRm9;i)+IR2DgQUiRsfBd(@qrdh5$B~O>)!TZ)x}X5O'
        '=TG;4K75(K{^=>E?h*U<?YGlEeY3OkxO_4xpPYSDeDh@YeD~|}(PZcBPdhu`o}HaNIe+|h@ztM-Z@!%t#o6SWZ@zt8OddbpIeYZY'
        'qiHH*M&e}?<FNBnXUUbAnmFk?KY*Q}I-cS{Hgr2!s02m~)9zYld{t>(0lV)c-(xsZF8O|(Jl^^CiRvAy=*&n%)Xs69c2)%_R~o7@'
        'RC$jq80lz~;tT~<V8Rop8t6oET`Dl}Fw(#$JbE%ElVR^z#lp5e1|)YiI9i*z9^5Fh5XK^i89aH6A0bul1jd~1>^}PH@z+oO^v$<o'
        't3^*Kk~|ZY9?*>)U8<4D0DQf-#>yP1hveXAYk947zD)SY*;y4sZYANDFiWDZn;9jTS?(WqztJzfbg*|eEjH;BdR$Je?XXJ7`-Oud'
        '3$$>Cm{m}V<r2<}{sbu|1(rXbnRey|I2*qcZ5R%yfjFGzCJ!QvMdnqep#1GK4BSk1tHS*RybAAygbrpxYZkLh(`qvuAosy9FJQh9'
        '{AeP(VC}X<XOYR67pqrlGh>cA%@$RHK#2WMi6k#hBe%q=VO|)1v8@9EH``tkvPc!}cnL8Tu}T=6x!FKfUy`{oZv_jkF!rIGJZn8j'
        '8|xu7&P!^i8jURo7UL>_EgQ~f7f?6gFfRKZaF{n^Z2jKK>-`>+dQ&5b2OCWE2%m64G*}{a$i_`=Dv@kF1!rDp-3kGS?6rPBbovfW'
        'wWzKK^0Y&!kGiI*;tvQTNoA~{Za7LGm0`a&3Lq(=00~n%1GQ}dHP2Lg@#PHR$}eI2CSZ{=YFi=-0xL-B4-3y!|0jDh>-f_OL6)$2'
        'u|O}ID^O|5&^Ri0&71N%g8=QbtMwJ-G`A?`uO1B{48KV?@9sSQ=IcK_8Mer024PY<`38ZxbobXgxnMEn|C{OiqW4pbTBVRxq=hbm'
        '6UlQzsutf#b%@djqD~hA@T2VE>WKb8;87PVd&93Vm}tY<nBy?)vHCS&<X`RVI5`Cj3WZxhs;jHIS&6y{H}<XrNSDWv0JX8%Ln9mI'
        'smo49;tv5JeA(H~UO%iZA{QXE$$o|y8P2Z&97b&J?WYF{C+1An^aFtMz!}nr*9khz?>@ZG*0Ucwhw^o0cI{M3D>B(W!S)cz1)RPx'
        '*IRK70jJ;|ax+P|q%uTtcsvf-(J>@b4i%-S?0c)b;8Cl<A!_;GK5_;t^^<E1j^{2%+wJ8_{-df2Fl)8XbqaR-x)NO9N-%%tv-glU'
        'DE;8fgh?n>G4ZE{QDPyot#f>cWarXcJtTTA`f0XtWniScU+wPviO{A$<}7)Xe3?KbS^me(Rw_mzdgkRgfi7)F;?N6Sp8E@mA8|3I'
        'TtbOC7zca^rkIrwPf{mSw?bWJp@C?F&|Cz7ZB1%TMgr}zX`wxn&%Q^YVn?A=y7u~E+s_mkM(B)xSNe62KGKpYCCn#V2>cU>>)=id'
        'B``#aa~M{#dO<?Y9MD<m2rdmgn7SD_turh`quAaw_7W%>%x+55*dq`nVV(wYwEABsTRz+aRlJ3W4|Vm(c(3}PGDA;L&Zmtjp>afB'
        '|C0=UOXp>=1g0^^^r9c|36LG5MFE;+4{wdYXf$E$L|h~Cu+B>mI^V_!U0FCTsKgV_)Vfhdfpf448hyh7`1h2M28;4pbzYCeMGqWn'
        '^-M6KvZ$LGK7zOti8Zj$6eVUQzWc^v$*@TB-yXTrV{$v(s<{4gRe)5r8>RNZrSZFQ5|9Gh6K$&q%lef)VYPC0J4d3dy71bzH=_<S'
        'Ahh4B`}x(Qgj~)Z!Z8E4u9+`^VHuwhN8Zos;%0I2Wrrn*j>Uz1$7dBvVGzv#N#fz2<E07G`w!ObK^BgZ;Q&Dmt@c`uwWuy%DuM_&'
        'e!aldKAO+?zpoEp0%Y%jffmGMxw2PY52_MbA&kpipZyb(#p5jV%esCu#-Ev;n*=U*vns09cwStcO^akzzbUJ|WRT;mb3_=!;b?UU'
        'S*)#e#C7FxO)#5us8-(<mj?1WQ$iCvIdKnB6~n-D=Oq1rEjDv|z`>*62G66|cYYH9hLcLzO?%`^e?y0>jp^yhWB{M{%0&o3J-yN*'
        'EtHFh71pvV_1KT_L*oU#3KK?+%4K5HKC4T;t2S4{hfSNOxK}L@ZFR3D|4dxr8j%?r0^xwfc-XeAKtl$UOYlMsjkR=`c>C?N7j<4<'
        'h_0JOQRP}2n?w8&{3hk+`P)aJoXR$8th8=9A;$deE&%a1*5n}dCR0{&M5rwcy~;f#*sxgiv@H2DwrY{3NxSllWWg#Ng<Aajr>F`>'
        'B-WaB=l~^=B0DfbZnKEm0Vh+V<&m1GJFd@-;^MqqUAGLXMbDWfy;YdQVNi6+=a;2Ft%p^LXyon&#XZW3Lf&(2<KA*$!U7R{3@4F$'
        ')_E+3nocx@{gx&dStXf=M%$5M(mXX4NGVw21z;&lRlZ9gq2cVDQ|q;4tatF)8Hjkr9}5eaktK}kUsWQx+*CYB+mIV`l)S7}!X^m4'
        '1X5X)OS7!1VQ9tDNa$o3*3Op85_uCy>r|C1I3{2l20j}G)n!MR<)lOO54?@*)ohL>4B2>ceT9B#qn$^Vz<BR$pW~prIW;q(x`$CO'
        's2$V0S(Fn917}Tb1YdJ_xCndA`BDwi{CxKtod8<hPX%4v%YF-h{knEk@DV94JAHH3I-hk_ye(#P@SWp1QRXdwR`i|b1zq7F^fGYI'
        '7zs0{x&!(rIDwW8NA(GAY1U^eWWYKau1y!v0Ngu-hD`%L@{l%D#qpCFHx{#Lrd&HffF0GUGZdd)R0U((&PjG9<0)ciEt!Z-+l3qy'
        'JV<BI)#H%nAAD6ZT6*=+eDWwy^sr8&Q?V-%Cp<%AEy@tVe^4aE4>4_l2g=s#FmJ=el?#42^sN#?AZ0klpos$NHCh{iKIReDZL2q$'
        'HAOR-%?9?MI+_Ube0EjL*|-IadfUhH=VYe~JnV&ve~D04SV~wltNg@R&C_6Iw?li8^^vvN`%newSN$2DM2PmbtQ4)<&egzH#w`tZ'
        ';oKf<q=M15%+$VP`dWm0acYxuZc~egA0%59NU~%QigYMr`t$-tH|?qfbT@0RFa!3iTBB40-dnW%6Fq>9#B~Ecm5_e>#HPw=BxG<{'
        'RV8az1W~f8<*%#eLj8o_n3X#`fju1khX4ypct;+ohxGP7l$3%DLgg^GjI4P9d~6L4Ih1~Bz@&I4D+duXU>ixZi+#wY3=E_oD&(e('
        'X%M<H2PJ}?f|)`bpK4`%!BUmD*il|`dSh+6P@s*zc0cenZAK2|38?O`zXRnV5T{oK=tjiqETu$7&Z;qIr3Nq8#9cun)2u1<z?To-'
        '!u%YcJDM>3R<|~|z9b?pE}D@vZK9__eXi;pVmUisr-CKQG2km&0a%H~i9e*FB!3p@m%qp%ncuh;SZwHW7104k4LHo$7Bx!Q?e<il'
        '?z6e^UTUhs5JR`WpVHg|8BVnG@^YCnJ4&(M8*m^Vc(q0mvAB^0)im+&(ycNLU7w$0<`qp#22%C5ioonC#<JAtg&N11k}VZg67sXj'
        'Lde%cn2qpBFMf^faEB~~HX=hCaOKxQXrDHE4C@9k#zK4`9zv6YKCZI@OaXVq{`I8HQ-_YM{hZYs<$!0I64iH55sG`k*U%&%_cYOJ'
        'FfQux-7_g!_u<@A7{GlU_w>`~k(qn6r5`vITEl^t<><W`7LZCs##<hk=%sIxO9K&&HA>RS_R6+Y4aP{YGR3^pi}mImIG~MxOV43y'
        '=J2A+s87pY_zVe3+)MhvBefDfM3^CEAqdx1T1Jm1@Axn}2A$HwLzF9Cs94FFq&+Y6CMGdj8KKW<3cepyf1CT-#&%}3Om^?sb0E9g'
        'QtAHA1O_*olTu*0#@y^c-0a{(T~6LCYVkbhQh0&!46*f&1DU`GL@D-sDj{4f#jz>TbCzf(_^8F4qzh^S(4+&tC}O|-6tXu_swU&3'
        'nB-M$)cX+7lN+aW0ve19h+8u)L4z+SrEAj58yv<*Nd4@I{lH_9enq6$D4S&wVJIuKDK29KZVAdr>n6`JcPd}BG?Z$+m*&DcqC7mv'
        '#|=^!r<GLIaReisPWhE#ysRv6Pn7?S8G_n(h>La3N&+c=zisD1jWq^YwODtffY=dzzlK;-oV~fnrW*|;xr~R`rkB+fu+P4E=q<|F'
        '-f_kZDg&d#5A?u}J{okzK~e?P7Y*7Gq&j!vq3nO#42zp3X0%%wFc!`+>rjn7I3@Fw$DYP&y(pJ&XX43Z-)qJ5m}!o`G~`oA#Tk5X'
        'hFLQ*m5z@RhU%<G_%~DbpMU=OA;=Hs_>6DMeRYBdAxi>Lck3l54-h;F91U0y!4i!G7*=F&o+c8ON41mO8Lo}|x}{@!L{oz><pzXX'
        '=oC4vJLIDjJ3`g=g`{>0-_3LIG8-c~>Ub!ZTjl7LIg5-%Q*q8<07yU4NRTf}G)o0vjX!0v)%-dqw&E;Jw`Abd1;ja2xtzVs&6!H?'
        'tO6rP1G^d#_>HeBj|7Hwu=;o*KJZhCNflI8&?oMUc65$nos2@<BZ0prB`@2aoe#_I%trQA{VtX!*o<@sz$t^vJ78k%ft~D}`YzRh'
        'gKK8b2%Xo~^cP;2!TcAa9kn`y9L378GR#{W$e2n+Z8j$gahr&$8-d5nlG^g7IxnI#x#W9=NsMk)sQA{jr9RKkhg*7lIEhR=L!^OD'
        'eJ*hu=kxKiyaxAHd7`&xbPeWL#jWS961%=L(xP3RVU@2fCs=*dCp~MAv#%3N$WvtA0R9#X)EcO_7tfrcXBR!w=KqX~6zV(lK!iI-'
        'u1~!}!~?FuZ+1Xxkv&(iu2ds?e%h!H;UF6J;ln<Nk~5woPnI0DLB#ea=@ODh1}qWHI`f&CS0Z9&=XT=52Sth`;FUAc>6c&vkN@cd'
        '&K-&YGvse{YTR&2@X6&5k6yn{&^j`7&2JD5^DYum(i693gmUi8J(+OwNk$VGdO?z+ZURbQ7-8LJ`+C~3T=YGm=g}_h5YGSR3!F^y'
        ')aIs*2z0rYxQy)2P8*77xtGYRW>a_mg>%d0wfkUtf&e{~Iph$eF`O;T>|!Q?lzH@#UtfFyY5f@x5WxG%ew=K`VvFAbnc^gqOw#QG'
        ';HtJ?<9~lhvt)zRlIixg=2AGlWI{PGj29UI#}iDp?A-RYJO|rKZL&>aL$=SSsw=ggLoUZ9Gi&G-^(TN^w@sR0s2$vD!&JveTPewN'
        'owzbf+7d<fOA2WXup>icOE$<PmJZVH;HMw+pMLqlDo>vM^89K3>%r@TA71R|&-Z^lc(yNwCJGLJewDxc<>&nPCy*M`aFd_^`ojBY'
        'b#eG=|K$%ap1$^*{@3%r<j<Zy`)NP_>G0?MvCj`v5E3U5&GFB#o*x_qYD44_aVwAae}2_c8ZR8$#CeQKS7E66aE>TNP&y3cwN3tE'
        '<K#_X3Z(AA^ity9X{uR35}BX470&$FIQMW-oP?s{l)U`q#f#RQqKT1IG>K#trAWQ``Lu~-8HGq*SZrSW%)*+^JGen!P)FxLNaZ^R'
        'WqXmljaJ4WzH?b!za7QHpZ3i{>hNu{wQHs&3&5Hhq@k{@goE0GZXg<lslWmd8aO|JmQu=5T}fg$;t^tq4Ssu5Uhiq>=nBwos-s@t'
        'q3sqE%YQA+7=h4~0WzgXPa8JQz))hoZqRG)T)cai38zk+lvT5CMjkv)xT%6cpOu#Y<mi`|KxozLi%amVUO~T$8dUu=2tJnxYVsWh'
        's2&B<@=<z6qW1rPb63{f)@_B~`778bk}<{DZPSG=AKX~UsC6xmlyn(Y!(mJ+=2#**q-e+E>c1Cf0}g-#+)GKx<R!5#v0Yp&XZ^l6'
        '4cHiB{{bIXdTSZ%pg;8fyXu8h4K}j0=LfCnHwjdb!9zMsy_+!~F8U%33qujP@a?<(>OF}?D9MWO^QUKj{@oFxKFAwZSnFAGIypVA'
        'U?(a@%%@)!Na)vY@>hnY6weD-#rrt$K{g#6Wk*piJSnliEtc-ZM)qVvQ_;|MJR_j#xQY7hFb%IE{bfhmOs{qb`Nl?XUD?|{t}Zme'
        'JX66G@VnDtC_sUVWPM(3XE$J0k1h4lo9c)Fa%^WgDgNC;$mJw=W5+1Y!TFoX_ewOK=xELOHr;QxBn;l;6qm~BA<oYqa)#59Dh;J4'
        's<d#Y;}!Dt$OokC&+lLN?8`MaH`}+X9b6=m{bw`u01^%*;ABk8;LakXwUx}D`9y8%x~}7vrz8svYtVPisEs@OLmkMaoyZ(JCe)79'
        '(xJOl+{%!h|9ic+;TD7pyY9yst#HWq`P7Aaw>dZ9K~&n+xtl-EtVIIhV#~7N!X$J7ZVW)*PIPuiD!z_^JZW!v8x&?k02kb1o{AS='
        'yUsE8{I=`X()AL(+52mZ>xBWY5y{q7{@^B=I4`hmi3xdhdhpuyUtx`oTrDZlarJ%)^(GiUL5^OJ*5*$t4^{hwRDOd+xwd5wrrZ47'
        '3p|l-{g_OVU1rZ2N8D}zPk4D}b2PT+8Pta45}5t#HEuxIdYknQlWIn8k@~elXz`Gryxh25>>i;=xPgBa!R%2}lx5~FbdYWd{TLWF'
        '7{(qVO}00SFwBu<439TTqeVQ^vx0tBa3W?(FZmz}M0Pd+vBlPy8`w*>{Xi=5D721ktiTa#_$K28)J%2rMD!S&npBPa&*Z(!Coz4G'
        'jDRY4ONqT&*rwoZdQl|n)f`nr!>~H6Sy2bs4!fGy7oT5v5`-9AxgXV06D=fT@i5M+KPIU^(i_OTGN>=17E@1eG+#horP|EBLrzMW'
        'mCwqT6e8CWr^{HB!{FPYM|YijyasixXzgHsSUX1t(ddZ7fH@tRpO3spmtzifJfTHfXp*KznOL4{d#tWVxHnJ|a!-YafUQ@yh)ioh'
        '^Z1Qv5_IYS-$b6!pg`s~jz^6llDH9>rx?bB|A^khXB4mTHmpFB-aoc631ccQeEy*Q;BSn>)>^tbW0xhBPnPW<@^6;>i6FRCTMdie'
        'Y*70<p{*S4gLulPfUzoglRj_vbminjGR|!mKklz*+pcFgN5K<`7J&cRNei4#gLp22F6RbBVXq^PiRYCii0$9*h`j;E4JYNt+4XxF'
        'g_9}P8z3u{V4|xvK$kc{;e8(T5hd4uK@ER_Ehi_MW|a3s8DNHfe6p{u)~+04ZCwLAY`><7LxIux^yK{I$ypzviJYDQVWCLl8h$=I'
        '{x<oU^6coz3f>Lv9|n}ASBvnAEw7bn6iDRU9stb+__^IVw*3@7R4==9%fm5PALe8sLlZv*^SQrHr)MuuU%&d#|M1_hPro^R_3HFr'
        '^4IIXzB>K-?*~}olrh^iafQ=;HE$Dk;4Rtk3iHJWPaBI5maBFAVCN2s_{j~THm!DLGAZ{x{3Kxy@&~pqe^ASQGNo0e&dLYT;qc*G'
        'me^BaIzFx5n$uCGXw2k}>}#r>n0-=@L=b=B3XiQhQgejS$mlp?B8yL$1~E^gsyN8V^V|g6nnas6lG>?63Hm2-rbid2Y9yll3Bjmm'
        'P9Q|A0z8K2K4oy&om~OS0C7eh`Q_}TimzXtptX9`!KOen-(y}B^Kx)5q7SD+F33Pgx$|_E>#Lx6F={Oxt=|h_7f{cLY!PxAHx#k3'
        '*d@jUCT!t@1pIR&d0G6w@PL6V=7t3KAY9RM@C3X7pUy`uVzOpT$Va!WzopYf>p^(EaY^1jNl}Pao*8ZK*9HZW!}Vw4lNDCYAPbXA'
        'ag$UJDXv42P%4WkEaaQs6HrMF$%uqGAUqMK&=X3<A^ZH)PK-|IS8}{GU)xHQE=*gsl}K)^qS;rP3Ar0lGDoEbh4)+rjDa`}D~{^H'
        'zwT`CxU5OB6PIA)uvSPl)8bx~U78lgK}0af>bcJP?-bwxy*(@o$qVnGatHGKjeHh$s(~w=8td|*AW8#QKO_MpVkNC+gfxBgX@L%w'
        '-XJqE$1RlD&$Y^D_Lmf_bfGu-P8O)_C-1Kg>1%Ar%znDF=N>*c<VyRmOLi3Z1SY*Wj3UTdW;yU_=yD6<Vv}i(aFI1PadadE=K7Ao'
        'uO|}=;?I;;oP0i9MdQSRj`|N=n49GaZd}Gn>cO}`w}ylhX0ZznSBN?MlCJfnx!GHHYwngp-07BtYoz;bv0aS1r%1~=ogyjcbSkPg'
        'Y}wf-xrRsWtlhtv$Qe-DZuqt~AgJDAtoSpYN@TO{y~OCvGd_iniRs;xM7{Yyu6Q+j?tkvTN#yHYbz~Q*Iis|R*bYJ);jWHY8W{va'
        '6S;B3U|84bY*H@1In@sr0ElqA-$}mU`gY1ZtUa^gs46Y4<b{(GUUUVwzkO_&Z5Ixv=86&3AjR|^$uN#o$=wm~thH*6s8p_JE4kO-'
        '&2Dbsi5p^zCLqBP%nw{SWRdgNZqWqujuNC~BA`UdLBmq@ZzJciVwxFut2{J?%@h;N_%@oUXbSD&ERW+Uc9(;n!?87icZPi;A}XeR'
        'ou87WBOQ<RB_(ym%UOqCH)A8SSfpvK@L7)GtM9f(lB?}<K4|#TeqG3oD?t~$C&s-e+cZ?1S@&eR^u6ZI_;yT-TAvxxd{K`zTF{kQ'
        'mGGHSs*hp!*&jk?L?SBv3|ZeE>JXd*;2WuYcr@ja|D++?`v7=F<2xBpigKTM9BWR^%#+0n>y<xD25KhH6L>b}l>`@vlV<}>q&{T}'
        'w<op8$WPQDHjfi$sBF>2rYlE%4U&6~-ED5iP?d|g_+{hJ=nW|kFFFVmB~)7f0)7<u--rjv4}xlIHLuoS_Re~`2gP(FOAg=(XVXUe'
        'c4Xwb#$`4uR=bz}tN!D~zo+MJxxe`KcnYZm=Y^hDefwi!jGu4m?D+in?4K{bJ2`!QUOmOwqu@73#m*7og)_H(aqX08luaWLG?q$X'
        '@GM)!a8TodbED{#^1XCj7T^$B_A|Fc%H-@VNd2@U$w(JLbKRA$^la|*O~CVF&mM-=;MoU3J#N<e@klkV6&R!W)K3Yom@#EyubV@<'
        '4CpkfJN3{C<uG&QD8v{Vw(Z;25XxD1JP_;W(%UV5a+f<op}vC@x1Fr1nhqAuKLxyRFK0-M03+}eVH!DsVdw6RsauDfz>tCUS2tcj'
        'S=?+Evn~46(#<G0Rqt`H@CrUOy7&3#rdwRf9deU5K~uN8$o*(JM6Ym#E8*Ibyjt)|DnbDUX$UXP&-!sM$$}fI!RpEw!d|Tz&39w3'
        'FyA$jA>TlxW`tJ2<^YgE49D79O|cn`@>c1%A=q(38+VE{;^tM-juRn8ZBpOE<L^sv@P`?Tb|sUu;VMC(YvKhhg|Tz2iSomc2`Tr&'
        'xX!Wfsn@`!tbuu-8hK+1H&V%UBbLLKt{UTVZnng6ADMZOCUd`{caF?~a4ruSXJTTTOonwkN#{UWf<;7EH-3(fE_y2XxMUjUk{qJX'
        'G28Qsp_eNZtRl&%%2>Gh&o&ZnA`DaCew3M(ZIr0+=E!wj8l>@ii&09g)M}8M1d0XiF}Jf3lp5_c*!1G!B;?yobslDZXxnO|Jx*FW'
        '%vRT6r;|nxv)(<D<?d&++C8Sl?w;1Vj;+p^87y9r4wtr3s$tD26SrS0@=W*dAEMh%V;Fk{YET^fX1iQ7ey}@3ske*Evh#|LsEnvL'
        'JPxl6e--(Uy_-?f5=Vr@rW%qtz<yk;_RG~GV;5oP5$2QHS#5{f`@F61O|^U$=vD}FgRn6+k3?~7;aP}eGe1WZF1L|xLt{wH0(0Cj'
        'UY1XFloh`!hQk$+lKhh3rIf7+^*mk_Y5{Z-e(B<3NR{o<>Ig6K!`{8bEo4ZnTnS?Va3+DoNtaz?!*11?RhXYzoU9rqbuTeQhGb?X'
        'pp2VrqFBSAv!utZnH_SjK4>5bv7kt6^+QB3P-;S@wU-;3OuBjT#-<Z$2+zU@QcGIoFGZh5TryBW*gxi^4{1-ONr|j3aY&4w3l$X;'
        'w|tl7jF!*5Ji#XQe+MHJjb~8xVdj2fRo5du2oz2`r@7r$hO3b^>ZW18+AbJ0J(`h7&uOm!GLkW*9yKX^kEQHcxgFzl@EpjHupT1%'
        'Kj4RG@K2;%giFi)fd3x7*#5YO5XCq6OJBh70so_SwqJF@BhE?ikmKh$(g=|y4tx|LDMr;4qI&FLG@H+-Gw!o*!W9WN1)Bw6CnHX7'
        'wV67ak#DZrhIg>jeb;N-cZP{HdrR{NUm3y-_h7z$x47O+{Is8c|K`ov@%eeffIP4gjs#hJ@70b1V0utX8k?zILjbvsG5^>eQGUWR'
        'T$&z`9G;9~`ig9sTkIBCFNxzEQfrOj%K@<AYCgd#7Bz<aVo+t!PYF!Dyi6ij<yoOTBMTxk%~l^&@a%{nAVpiv+F(`Uhr=hTC5*C7'
        'k?~WMatXu#3B~(lnzOl0W^`bXFxbQ$kT^p*VGv4g!b%%-9c;2x%p1fyolmqYHDmZ0mNA78&eg?)mgUNQ&fEUeVIWlSya^1|G$Mrg'
        'ek;_m`y-7}x4&2f!F@X#wV~jY(Yz$<E(OS)N~yn5q0TQJz+m}1JOvP?9YFF|>hkb9qvA^Tp&{0>VaABWZ+fv^e@q<pAKUrqa}5uF'
        'U^$V8%o3JQrv<k_<d`uG8N-l}rfyyPq~Pk{h;{<lwjb$i(m9d@Gh#WJ{JZe{)AKIcE2Nx1F+H;qzr?Q!NgQ#oFfYr5)1~@6#5f@I'
        'EZBnzs|7#cB>Bub|2!zoQYzM@-M904_9RDg9d^A+?h)y{j;?w#wDCzD!?iU-Ok#jRobG8_`zz(qQ>Mg8OEY7W8FA9y+$c+O>V2v-'
        '?g;8aaH$1dUIL2)cD%$PGqOLaM3c{V0*&LrmEw%%%ses4lj2c57<SEI`bo%j4@es!gkD2CP);iUjQ<F_ogC(>IEAuzOX2jQ!ddb3'
        'N<Ruv+XnPJ$zu=*yxnhTNEZPS-W~3QlF?u7Z+?Ky1Bh1<=y|9rpubd9*^E4*cffSmY!@Gv>pi|3l^-)6$0+I04}q+6^cdwNE`NUV'
        'Eu;VqyW#JX*WV3{oGk)X@}chi!SnDzB3D^{3g@Wgq<`m_>U?rNY2KTW#CE&Bb>Chv*T3ZcNQ-3d4#*`z(8+`wO_-!pd`_PL5nC?;'
        'Mg8dJJ=`W>`kXvn|M96xe#!BtBt^TEAQ`#2tI8d1u|tmp8Hp)FJ||R-IRls`qPN(*+G{w*{Y>aL^3s~BT=}`i%E@KnGv8_WlyH6>'
        'NNS>Ci6^FxlBjC|{;fI%czaF~Qk2H!s|Zv4zp_P<z*~7<$YGd=l8M|G$Z|(Y{&~S<lnEwKC2b9E#bT2!NZ+C?Nn`BtzLZz&4iw`Q'
        'uW&$EU$X_7&+Hb>P3}<W-8bjbgkMOuKPFK-EhGRV_}qS}|LX&zT3-2YP&EFVcmT<#d=Ln}zWjSK9BjCR>Qcl*%EnsUE)AJ}2jn5C'
        'My*7o3Pwcgnei|@&vQoC62Pv%rePMR{WHL#yP-rc#698#<Y9(}U0tLPbI4^N)Y+^MqZ7#|%LRc0zI*h|ANGYw?7J{zK7bT#b$GNU'
        'i+S#Q%caQ6Hq()!oa}ZnHVTVzn7vAZo5+54T(vC)a&-o>l6=jHMGczdgWq2=5O&5WKf48hl3EG+G5CIIuC2_}gW!nnBa5i6LX^q)'
        '0U;)j6<+e-M6gHWy~rqI;~>E?YYUzVwUm}U=F>#AmjPjEF(-4Ko7h<OLs^4nc^IxxL)?QE1g++qB%2?VCq7ooK0t7AE;e)I?&6Fg'
        'Pik_zo}x-Ws3L#4Yh$te0P6~m2540&pEgKWoP&QaV$#hP9MdXbH-N#!!MRRJKvXIv5^1VKJ0%+Lq-X4v#6VLdZ_Rv?;$H%V`Fgp#'
        'MYeG$bn$F_$^MiNF->6PJ2ISzXs-9of`Jfx5)mtRR%y~31V@FhJjmQosehHr=}Ad{>U7*N<*vj4yeU?nPMOQpHR;~!{L{|e8pm#}'
        '_0@C@2A%%{x(e2q'
        , 34972, 188196, '269eca283dbe83548602a102f31d81eed1232b85d1dfbeb861cde9d17edb0d4f'),
    'sdk11e': (
        'c-rlKYj@k$wcvOC3KUsuN;(uJyS-^Ehj)!)$+aem<&l-NxvB<%NKnEx39tZYS#>qPefHzLaSjN|O7HzJS#2T$IIn&7+3&M=9LHxx'
        '78Plef6Stv4o^>x4lhp5-bOc7S~O8w%%b$>rpj*8CX4E(tkRn-D({M{isoe%rO~u3rd0+nt93En**RP+qFFXwq*XSH?y9^=uNTl@'
        '-K^G49bIROvbc$wGAd!vRh56lZqug8maAqQUEJn%1plkk<!X`5cGBszTo+AV+>D~4gxN&%e38}nHGCiaeO)$bM02QNn%Cv0arCY#'
        'r&(P`<#nA^(05)IHO%lM%(l7BcFHQh$%}LWW0VURc@|A?^TiC-TCP{o^*zjdo~{=(lPt<Utrqz-Z{&1#XIVYXiW$IVXH}Irl_;If'
        'avUXHEbb!!Lz)+Ibm;v$ubSK4Ygof9(v9mVomM5xvdHdsYM3s~5+Pk>D}Wm<cpSaWa+q@!$)Nzy+<jU^>q3nI-KHyOuro`uWm&w8'
        '(&{>Is<gV_ZK_N)TSB+c|KHbnmDLC`911`H)BgK9UF7o|`udPnMYh<fr{yYx36#*F25?04s$2p9VP}@*Y|V42o4i>!(AQ}O6G~^x'
        'oE8Eo@Csj6>nSb+MuI-%UcicREAj$h24nsMTEh~fdU~5-w-xRt0Qx4YV06OBo!hc*bnl29^E6-V&eOVi8U6B0lP@zsuB6UjO0)Wx'
        'Um}7w_Y07l;WR!9<UCE+1q@ZeGS=8@)1=c|1gAoW89-;+2&}lyZgWI`K>M_65JA$a%3+q*8K8c)1AAWH;Tnx`5aY9Y9KCPKmDtjB'
        '1(Qh|fn>0TXK8W&EV@~z)r=OiuCnnCBHR>ugzl?sN&5_dTLCC@JV12Trp;R58P5~PMu6VygEoZ~Wh1}^_?gz(UY)~XOsi2;ukyuW'
        '1n1{d1LKVlxyy>r_oBRkErBzMFjHrDk=_Gf$2)Nx@6i4y$$X7%lO)QQqA?swK4d#P;u)aMz5M$&t#23kwfy;?by>*2muYh=|1N7D'
        'U<J?MbJ_bl;}d|k_zU);QGegp^3UcL06oKFARho?>~OzhHQ#kpX2rCeWmUqbB>@<h>uQQeqK**PL=*Wu(YPr(ITvqE(*g!KKmOl8'
        '9>2dx-oJWt{KH{1iDIOUv)zw?-ZKKtE*`q9ZuUMtk9Xd^`T70HtHaY|n|3eaot@K@pN_X`^n2Op<n2$#Z!gZyf9`6w0NmXL@>H*D'
        'n&-~h`O(SSLuzz>c=77ZR%8EL+;0Ew{Ot9~>2X*4vVsjnx>ZksGEHx3Ry-XAx7R0sz4-CGvzyiJeVxNm+7-B7J6*_?9KZbu+n>C9'
        '{XPMncliGJ;(c=Vm$%19iDrZHYhMTN-yCk&3AT9gZ{I*)KOFuwQT@GwR_~#g-@R~Nz`mWI(5vS!{^)6x938*Ac!RIMK}>xA<LQR|'
        'L1IqOz^>$^zWe!t$4K^n|HtIt{_qXGeSh}j`Kx2~^7qlR==uH&`5*I>cPDT03s@LEJ^Jzd@Vk@KlZ&5?`M=mt_V@R9&VIaj_v1zK'
        '_V5RKI*3>IKrNei6vfSQh5sS?g@4Sh@!w3PYWx$ZR2>g@{(OG+<2zX8*}G$0q@>)*iaCEmR5sqZI6r*#J#2#dQ1I}CSaL#4A~9HU'
        'yptTA{29Oj-vT+FmP??Q*`SIq_jmu4?#{11fAjl?zx@YHU}pyiBrxxv6ksJqIIgO)8XyrF9}#u2UJMU*BKQZ$>7kaH^zI;s`fbgU'
        'RehVUh!y6`yg~V84crLjpKEB5Rm7{uNSAkZKwycIBFkn2<bNcJjG`p~0>m^iVm_y~>ODWjf2uUEv*1ExFLIPQvh6Hcm35A+ZUA#%'
        '10yNYCH#Ate#)2Yr5KWD)ZDMcS3}@0(ExZ1FrY=5Hbde&$OFcC&HaiG)!ZWbWIy^gq8HJ(6FCO-5$6R#F8Yk4Kg8S&AiAy!9zk{|'
        '<__}f8rWKLjrb;KPDmhTjJyZ7o;EM3(>bgYo|uzDWU2BMNWk!2S&u<PDhBw`2!EX==SOF6Pk)a7$-my7y*@iVJ^PFP{r0=lvsd49'
        'Uw0tc;q&>7deL12o>$lL5SbB(P+7Xvn}uHjTc)w+$OQ-d#TbRdq8to0>=^v`&G>zC^8Wnz&jW5fuA2lTxQyYipB0O|_z+Ei1~@Nj'
        'kkJtI1gep-IfTjv_T~l1_b8pQm`>kkDE$!JNo<dY2IAepLd5)$aSvEV{yKW@t^(FJfX|0|7M^i&Tlp=>HB)Go&5Y5~d6QKe0q1T#'
        '{)^vC*A)uo&;vdjFQ|{9f#?QwXW7S*0l&N`M-Dj6-%FHIlA^XCt6xvW>mhE<fR>@gP`_vh^@~Pu_R0H?YN6(!AE|Mj(>M^2P?Ioz'
        '(=?3Vyj0_XcdZ6^f9(bLUbNX;8`Y+_X>o(9?JeqLLg=&!5EBJJ+EMg5hPmg{EIx=F903vr2hn;CPaY(}0x=w36Xr7sXsUaIaPvSY'
        'P>+Gy&FTS-R$l)nXa#`2c~vL3W%*&kNR8j|(=JGXK3Hc7X?DO7CyR7>JxinHAQ~j3ek4T1hr=<*+U4C~1I$BQB`(T>DZa`4{@44n'
        'xA9P%L_ET)CK~*N#Ftu)q92PK0m7UV$s>H!mys!M(Hf8yTj)yhxca`BCahhR)jbn|gGbQ+qm%RFS15J63}M*bO`=OMuE7WRt9ed#'
        '1?$V{qO3FPOEGocJ}LYrLikOD^<W@`^HHQ0C)PCuH4)AMoIucRYv7QH;Dw(b0Dm8tI|>uTBof_R#-V}YD?SQki3C#(7VWW!hyQH}'
        '=&>s_h`xr%P-gj*)zms`^b4R5pJUX`mMIE{I2?<Qu$cJ4p<ANWrEGA8%>yb$s40y=4S{<M@Yj$IF=H0V+L2tC)Usu3K_1fT=A#Kh'
        '{4Kz>TC8v2bfG}In%4=c@37oDS=|Gk0bv3nSJiOTZ}MpZT6$S!%S62xYrIZ`Ky3gNM;VhDZ4mG7vQp6A0fOjrXYpxqPt7lLVCJ6='
        '=-<GjUl15B<6V^4dFEFhYJfC@o50E{q?*LcvBP1s3!L7jv?1VWqZP`+$|lDPm4L(9&KId7#N}O$>{@Ofqs5hrX80N5*dnhP$DX5@'
        'K_Umef*);7&6>3obbzX%3G=><12nc=1d1hsn#|$ZBGr=g@W7FLEb*D-K_wF748@yoS@UxE9DEo5?QbzjV*nl&q50{j{eAm+ORSSf'
        'E$8RKYoHK@fCZ$dL3mSl;~I7daBVO4iE{KQ&H9gwVv7YmlQSB`c#OyNuQ3v6Kq7jd7d*_cHQm)BMFa~@7Iit;9kja|yC9oelo<cv'
        'MX;G@5U-p0?jMcM1#dFhQHvXG!I8X>jc9NZD>Q?0SpPdiJ7JDeHqgx^+TW394^Ws+9$>N;wctgYz|un^t|*@5Gg88tHN+1s&=WJ7'
        '`ElL{Z0r*$V0m{b`@ix{tsou6KzeFOyDVsDoh^W|fIbftefpt}uRJG!8VS4-TrSQ&rLfv{kwZTS+<#<+o_=WBEgY%Wb66_si)`T>'
        '*S9I0LYlXWI>Yg8_Gy;iz_bUyJ|58$y6^|7X2N2NZ~>rrmB3nP@_5F`N-&5I4h#_FbNx91mk>~OHUvFBNw4d2u?AIsXs<zRto+vA'
        'M`2|p_{CQvgAWjW=l5){zlP(H7lpMowB8Ae8+&43G>{o_CB{iS_M)748DIzME&Tp{>ljETfE^ioA&2*16v6?}kz_X1>G9}+JaMU~'
        'h9?+1xJPh_p1fd{lfPGo*~5$F@fIJ_0Vg630RI3?nk;a@nX^X!mC%a^pUNN)zO!I?{CVD<WgC_j#r){wOP<Zu(6d5nAdWG?&0rkH'
        'n+g=Ia$S$vgH{LB6PD@tQ?paqj2VvnK#n-{0%5jBSp*%J&<1^si*&Uje~=51dQmpD2M+Z(oy`nOLuhL+d6TXznrOXY-dW!-(UOCE'
        'IM3&0?4S3#sMjmBtNQkiy0d2kXWt$R(1-g!Xm!ss7oQ7^y24q%MTf63Z4<}T2O;$|etq)#EaE0G(`+%T6-g-8i-j}cY*A<Jsfp%o'
        ')RWU323BM4gEeir9UZvlUoGwxDF$fhmMT&_?C1xH5Go!-@Akx6hAm!0^lAT3-vj~KVi*EtBy@1C?1e3EEE!K(2xeoz@~l9EGiWEX'
        'EL-6pg0c+#^otuFY{n{yz#Y3sjHl<$A(0Rbe*;8zl}&S4G7&@Zw;%!h(FWQfmnGY3>R@s$0mmu@f>5)oU3`yJz=7z8?4Avw1G%#{'
        'IUGw|O`39`HFpQyZPon}I=v#@dnyS2h}a~(oZw%EWJ6Np*EW-L*&}`9szSoIgWRGlqa~<{em;N<*JjuCB}y7NL;PhL&TNd5y8b9&'
        'q6j-;&UM6r&mCjD)=rt%`6nQU+Gn>nO+lw43x{DgBKORQ?e|3)U6&w+-9fu_-Q1Q{-rSE_8vo@NLnjB|<Z~(g{PGJD4U9QhF4yF<'
        'A1P}&TNulAgI;?ISfPW$(GrXMNNAXD)XWL6E%q#;TOZ}y>-7wfutpJ&#pH;^WF`wjrds79>V$)Hgu_3ABcPm2BGN%d2k9^j;=n9u'
        'Z~y{DGmK%~G*H5xtHB&-^W=33<ah|{US$>ZwgmaAL@cplbjo6J|5Dha77OU-HUmlYI!ha9XvC`Ez`j8)sx^&~Hp)amz1=LzYZQyI'
        '!K%#RaF3%yJc)Pe6?wg3SPW)}Zp+0iTCa=%8J;b>ZO|({D{nx5SYVV<qhmH;DLSGBWFs`|R$^^1$!swnOH9)SfF!}aO_Bk=ABo5p'
        'A)G%Okx+{kYTjpUl^n@9EOuvkX#En<y}D19*Kl@L>x9IQ5l6KsN2z$I;u{ilYcP@U^awy@eM^78Dgn&*LUbQRA%ypI#(G!cYax4c'
        ';(9!t2x!6Xd`O(HC*SOkB18+;4gtyyV%kEz|K0w+-`uisW&xIuXek`XV;p#in9`%SmMX#LS16{YcbF9>an60RHQ|^slminWw=EB@'
        '3uK_>_7jj#e)kQ)${wTxvc6HQC3dt$p*8&0KNW3XZu@RM=SKa>^uq27Xl?<zukH%ZUm~9l?D3qoOhOYuLMQB(K5*x_N6vDRA?Obf'
        'Ak2t}2fI(P<%!`=qUVWxVNBR@aJvRA|G|t}Q6McBvO5nFqwGboYH2+ZLRG7^l&`uR$r90}cyDk+VPzNl>Y~0Jh))*4WaH^`7VFq@'
        '(Di1TZpifC9;mgJ@Y%%y00rlB5DWve$E`G6fA%+tFqVjYXUoQC2Wt|6irpV6?~V5Cp#J52h4EK#5I;gs$WA)HmBCwy2;SQA>lB26'
        'VoH<U@18}<ftHhq<cjWZ^8%-FQz5hN)d0B(e5s-d$LFW;WH9V*#h>?rAxwn=k$ekPo5C)Gu5Htnt?)NJF`yHkD(EEi63rd{w-hv+'
        '1)!oN$?nhUEM0`&NjawHmYLz#{*6kJN{LPl*))K_s0bu2mLb{?%6bd}_$r@y!g74=Mc@qCK%)3GFV>$#kiF<J0_itfW&yj}R}`<#'
        '@xdUf<u!!{lR$@E3tFV*d6u1^0d~z{_eNi|=@nl9pn2U=AUDu?AtdYgZ8Q~B$e`!>4QhO8#8TmS$B^}w(OAwY3CGpqsEPVcy|&_?'
        'Jnsiy0d}LjYM{p&B=x~?tb}n(3?~_UA|!E3?4E2A!dt@l#3z<dw16J&!Xvp)ywbcY2=8}v+9g1DyzA)Ew-u9~3PxW=W3o{b3HL2d'
        'j>aNhrcW4@VnZgStrkI1kjKjsku4is#@1WI<G^i6TTV#buLmxHK(9ObGo%Qm1S`u(ZGA!rI_#3Ggw&+uD!kQDq32H%#;BarwH%a9'
        'XVkyxtv29o$;87}SdtkbKh_o%3eRZURATQCTE-0wVyx{Tj=q-QS7aMn8XdQGv(>2-zszmaM2t<&cFYNdZ{VWt$bI5^B=M2u-16Gu'
        '+X`1~(G`54$Oerj$%Vf^4^^PKy1EcP6qmC69m#tja9BVQD`3my9TPgi)T@o;-fn!SUj%k{o?;o)V+Qk>zH8nf<?=E@al-Pq*gC@t'
        'Ck>V=C<nRrK<@F-3KOy~K&U<zEIb9<doFHhV!*<0SMv?`Fm_sGQ=zK(<Db#sb2wP*0nPB*VQETnUH^QJ{i*@?M<CgvuaN4%y-6Tp'
        'hwLY9OH_?U2!NRb3y-PB4{mhJ*x((7w!e48DgWa^g3+d}9R}law!m<)8@4;e6U`Uc&a04D(hbn-a5;xU_Lk|V1VeKc8Ifh77Fn@-'
        '8)Nvq7n}kenDf32jm|E;yl6JfBGjJ3=)9EB**!WW3gS+rU{5vN?=P`pHu&&t-2dPa?2Q54`@Pk!Zn!(v2fA`Sih6Xxx5IR?0m3MU'
        '5s_h+u9OH|QDEqaFslvlQx`!<^XGP8iWLM{2ciH~7$<r`{lSDHVh<$2)nFJ35bU6J(lxDv5&!u7PcH~A9CIl9@P|;$V-+{)yAt)8'
        '0Q2C}cy&afLH#{pVMD@0is%e~)1tIGvcs5-+{_Mn<dTFzJ4}Q8)y{i6TB<d?d}WP(H}k>4HG10vZLoMJ@KLhC?CqPr3j+0;B{mKZ'
        'R$<ZsZRM(m<y31TwJ@B<!Li#Su8P(UneJNx!KIRksjal)Ll+dIqb&EMNCvXCt^ea3<^fvWL)S1HrE7-aRaYO5ib*8MxE(o)tUHjM'
        '%3&){18Irtn$7O)lXBe7!d-0ahj2QxmSpKL!VzK{OiaB-e4y<kK9XaoKH_`Bx9L@U<Y(<yu2P{$q=YW+vJwU?xYHZloe*u*NTNuf'
        '0F6Wq3>ax6yM$i=(QP{8>Wx>eE0$fT(`v1p8({}xkK;Pa(%B*}GLMtPIjml_&_1t;@0-q5ZPY3CGLvnsNS@Ui7EDP(J<c7GU0@On'
        'dG&3xXk`mmlIN?JA|%JShTWRAVz1`Bjqnc-M-dTDiv?v}Vec1FIv!Tya4;5Cwrw*(^~Pp@UGh2)Z*|pnvx|>9<wEcJJrSA0(HeHG'
        'YS6g1<b5HWnsrPj3aYe>9^OX&+q*39ay;nQ;XAyP)4@nAxn5IukY<4cPjAZN-|{35Op{^9XO01G;P*?8ysj|=B!0ix5ch4vg*emD'
        'H;P;lL9b!ONqJfw)$S4~MBeLM716CuWIx$4wFQzd%<)0-b|deg*+*3hA|z{#qGvvMjadW-#&gg@`0?@sEPH^r!YBLXAIt~~4nCWg'
        'zKhT5y*?-d{8rs>l|SgVuKcmiXZi<SME9N<ac}+T<a}U#Ob5s43l9l<+Ojpe+Co+c(cuqgN5@Ww&;c#ld&pYxj1oW4rK)ZuNU^98'
        'w*bAT&*PN6M3{Qd9)ZGp6Llx}8h2l~2ZkFxy{HNp81C2?C>jyeVG)%k<UIp*;y6BAHM_YmVlZXdlguB(HH#^b7U6d&Sb*P^*%{Ey'
        'FQO#zpI7F`>sn-lQi-}28HU9It3r02V|uH+iDqTS{!&<OcBl6)of0==rzGfwQ7R)B$(Jc}O6?g*#7@ps)~?(L{8i(Nv>}*&tk}Ix'
        's~M~#U7%<bah5C-DmLKB$<y-g;IvsP<%MJ4v6!W)?g4t0v-{{S#c)YLwb{Bt)<F>Gkj0jC<x}6}?kUMfzUkvDQioeydUu0X<O($^'
        'tubSW#-$(%38`C*GjW58%z$cbBa@%E*_<N10aKabUPt8EVD>S-c6guokVesg3;ny(!BYOH7Hc$)Xh@LE8PN@Rjez!L;H8}%;VHkF'
        '=q|nVuF8;oq9f42GU@Z@1BGXkZXxTySyo#ds`piNRv4#P88noJKsov9=<xIuP#jb2f$W`eIC2dm)?=r;Lv+5c@U{_tZX`)lfwwc5'
        '2~KmG!Q>I-yow5AChXqaooff9D14G3F2ea>#I^Vt7q_;8Im|;%u_~)uB5C{)2p^z$=k;xiaVStt)P%p@q@!6K2x{1l-tk^(r1)ma'
        'X+arWMB4+e?azy4ifzc#?ro}V($*<D2-+As@S4vIIx<~rFYWwYUd+n7NL*DD^iv=$B2nPJ4I>uEHK{$=rO1l$vIO9u2YcXeE45tN'
        '!@o!SHU?B{Lra#aYGhQ-=D8VL8Vp|>i;rY<?_`-5gZ=UIkzU!b-TNcAbgS)rs;%UFKHboAm~BU3V8^AaE^4~z#+pe&C5<xfkWh**'
        'zrGeco}1$j6@BmD)((**$uM+opN!3gPrJ%$I%x^cN~UmU;8?bwkXSt-(#GKtgkUU}9s++5m$!f^ONbhjmty%>BM}YsuYl!-g=})I'
        '%e%+oZ1F{UGGYsOOL+x(_ZNcwHov*OOF4Vk=Qv%lf~Bn5`yx5QeM0$F=*i~50C~yLXavvrj$ndENxyjT_V!iuL;C5t$faCIl(-e0'
        'gF-GdD9=j~M5=VNK!4LknlJZQ*OF#viuYVE*CMTkbz6(m_>xFC4lq$)m~&g!Ky*9!uROXYnQoyH0CnT(eFD|1%evP?73<AAdJu$-'
        '*z2blC|h6<FNHPFl38Bk9pSV>6?X$k5s5HpB4^n8L{8?&>;;o!sBXLD#V5d<e;MxlO8D~xIK*KJ1?eTyDrta!EZ=#ZGQI_xjm5<r'
        'ws<;g>#;PBTj23+PlC9XDpp(QuLAduHVSSQB1hM-vnbVv#kRmHGZ#+@R!n)O2k^)hBKvDc+~_wG&LpDP*03iyJrN?(?a4mOe-DxI'
        '@GW`e{FKwvR_LCyk_|5%j!AC3{p~wxvsmt_7g|V1l8GK-FHPRK0Vynj;zM?SfJtrje$mzak)AXD<fsEo6acVPUq199Dymyobh$#`'
        'p~ok`En#UDhM+6iz8tK*W@*Y&G({qd=x5V0elqVspQ*}OX%ix6qzGn;?b7L`K=Z9XzOM^TmN`uX4Jr`{=5d>@>t^Fb^c23fQ}y*^'
        'fLpZ3nh|-?5&8B1C9}tHRiScx;lXcp-%1m@rPANF4nE?xW9LLbeSL&Qk*rx&Mrz5xGWKf~(s6G2T&!Dby`ovr0AYED+ppQ@@oW^e'
        '3>BOS!*Zm(XBv>U!mBXF2;L>1m$J%;s?4EWBLJC?S#3DeWc{2}c;={cQ91`Pwp`}Zs4mh~eOor;=uFkALFzB;gF08sEvB-;OvhP4'
        'HFn4ohJ((vL{lrnDm*XNE9kUX+^eOxt~zi6uVs3#yLc(+F^Bo3R4PZTR3y{6OBWw703<c~qm3I!ugSjvb4aiA1)f3{ic*TRkO6Gk'
        'KEqd@)L!|$cc#$gY$1t8*JZizS$)u@to*|G5kSOtQn}q71YI~!?oHZY)$BHiZZd{W0v;-_o2dmiE5R!|V;XdJ7>*sooMxutTx^WE'
        'Kxf|<(hA!#>5>c`im^y<YEBH@I~BD2{p$4W_^-#WR9_U?;16st^Ihmr5l?8V)Vk!&!M2`+`Bi0@w{^qNlb^xkjMb&23hmzGRIHMO'
        'Iay*=$ekHRfj85AC&To(d4ebGgi<nrVpm7apgS^VCy-5RyBUhc&Nh(A)4P05Q`(4S$Y0JByz6qdNUhR04By4*6Iuj(i>C4rMgcb%'
        '=3eT>HKmTq3n}3mTQB7rXX|Ox^j4zWUw@IM^--o()a_AIz@aa%^pQsXuJcB@5szO*@3Lwa#P$`3wD9WT`*ih^vfM=PIWC6G9DH{m'
        's@GLTyiVr!(!Ckv4jtfF{!Q6f?T{Fw+88;M$8K7^ZZ4y44RFv&B5lL<SY+N&SM*g1EA`DF<Y?>4)bU83^VEFD&wDm`iZ{C!`^E8?'
        'F+8nF1c!S1NQGZ3TEUQ;97j2s8u|t>1UGJ@4}ELc%Bo37biUL;vZYbPA~8xU#mK~=S15U0WTiEVG|bC*LHv|&u{cAT6z_|JGuK{E'
        'v}AJ~ahd-k+AsHCyyy<g)WV47MJjC+r;4JH3U$5Z8Z;BEsadx(+{!pwAO8%cxwW^>x_WH1=0MLb3ir79)J<%;hhf6UmyMLf76u6}'
        'KM?0+K9i-t%<5Gf$<i04bYUeBb}6`6^q5!B|HK%Hwctds_gZMuR%h+{SZ+C$z~+fr5U|xlu@LJSkFY7qm`;XS_Xsy~dqkGb2EBRK'
        'Ziq_>KBD2N{`Cb1Req>Tg!NsE(h&G8*07pIwoBcZWx;B5X&?_YUM0Z@4SnXhb0@|49+uf>zBBq@Lsv~>;GvL$C}WxyRuDvCvdD<W'
        'rw5zT38Q(BTT=dV&&pjQE(JRWO+^(eXP#JT5Kj%|R#o;TVW*L$1~DnCkSTVrbIMy>)KmbV9-B51Lz&?*6+6;Di6QBqYk!!jIw-Gy'
        'xG?%6)Wq}VY0|F}SfBB90Wcb_8<mwTA@W#v(^D-LI;)EQPh<}Z-0lDNxOJe02M*@$6_5uk4C$v03QY{ZW1DPyFdH`f72epXmMSH&'
        '$jj$3M`B@T(D$bqRhCApU;tqdB+h~IFI;}34V;=B8cT8Du1b?}iJ=$6Hn$Ekpw4iKC*Vm&fWvDbb#Ke&HNusOclZYldR`coG{z{5'
        'qgZX4p(LUtEf02E>e;L+e#J&*p`1?{Jv3sBL@dy{sI$z7ZQMii={OK(8qWSmo+&>vZy|qpk^8IY95nGg<{NvIZCx2I_zH+|*;y&u'
        'q{+*Z-_o=@`2^jG-a=^F3Al?|F`4}(9ark-mI6HXmqFIzlX|>o=1HZw{-<UOY8QfV+X3bRPONP^$VtI+!{>5Syq}vmV4VwT)%umx'
        'N53Ft34^);*ZNe=Rc%fAMAs8-8`l!{@lg2#+AmeAU_@(dv#7tMiw}0GdVMFCi4mF0q;E@LS&KQzqGj@G^3*6N!Deu8Et;ySpQvz|'
        '6;|TbkC01pNVcdWA`H_CR4s;RjT|bb!QJdl=&PWWs2Uhwhw4#CC^(ku&1$QsT!y)=R5t@<3kMFjm~*F<AcIf61k8NqQ#QL{=Ot_{'
        'fL<Q#KEDd^Z*!CoXo)lMoexbc@k@tT_LebxB+H>f9g%vJAHynYT2U5>^rm(u<Zq9gA&bHc<jlDf>RNF)e{-8h`dfM%>g~pFTc41l'
        'dLniVHf(3(7GR6VZb8l@*)8>hMQwCOnuD!&&Nz4dHjd~2g&W76JZ9s3E!*O-w>FbOZ~{P-<&r`K(^I!fvq83%bm5XwBm9d|!5otn'
        '^N#g)TAa9bmr)}Q6>{of{S$O8ESQQs&s?yN=<{rVI5Rxxfe+n%4*LZTk#aY}|CxOxeP`sam+TRv`~o9OAfu=)o3y2pcc_~;N^iC!'
        'hsgqyHhfP*@wX10S&Z0@_Mp?Drom@JOH7^i1fqw~p{%HY76djwVFzvrHDM(4g?XuhL<w0VJQ?8S){*$xshS71?-p_Xm#X1F&1vpv'
        'e-Ga^@Bt!tgKlG7rI6Mo<U9P1t#LQYS+w~r>p)t7;?6kGWhl_2Th={cI3~o@FS-rIo>{eBHioG<?%=e&>c)92;-_!FcMXpto$$C_'
        '8c$HrE*2yB701zW5-W8ou`a2jUWBR(w<j%=KA8ikDt{XiGwL;>f+q7IT0K3AwJftH#R}!Zr6~(@Q{gc|{sQVte*wU)G-<n7upDG-'
        '3%i!m-dw6ExnXCqM4_aE!K4uF*;{J4!PZ;vWamA%feE<7*PZxFAHX#!=gB<5iR!##rb;ye>8{vO{~<uW{iwekt=>pjMO=cI)yC8L'
        's57B*dv!;F_cM8TjIf7{u(`Z@DUC)5UyL*sY%rUR`?FYA=Kb$v=-%oab&JW)0g~s2FQAI3<~V2@q`o)X2+XVz|5Ed3m((DN@p?#D'
        '$cODhR;P^Eo`5-Uuh-W#G+H;CXx4VrD2Ux(M1{7)<xXn&M5pU<ba9hR+2L7oB}TDl$m>a6le@<>EgTN^rDQiqa(gqtM-W{BH--MT'
        '(unsF2Bt#F-OONfZk4t;;fOk2dDr+&UrzS73%#O7DEj^Gg+D(Qf6#fk?KYD-)pm{}Z0B=+7=cq1HynzT()%v+rbKa()t0lDTykC2'
        'uzg#n!Aa?Q+%4I6XKPI)EYKOVR$#ZvAHO<$f1Dg0zq@#|8E<)En>Xhxiu?r#AaktOOSXn97kD|J*IDzDSU<d&R~eQQ6id#_!bx%k'
        'U7-a*TL;NGVH*cS+wUc4j=f6ZkQixbo30RJ`kZNKyj{#1)m}!T%CJ(yV}=0Xe(=*nt0H;lmm6aS?2vW$;%evhN;~Ydb>kJ0?C8hy'
        '!|zT`PcC}jcJ)z%Ew8##LDC7g8sm>mSzPe@fbWa0m+YzACB*qQt)OMsbytGDbj)8Q`DW*i;4nRw!N>CJ=y?}m<tuNS5Afq?O()$E'
        'Gux8(bkL#4tVLI;*HG?NncgBuz+?r286H9^!2|tw0+O2chM`DVD=oVwQ(zfPFG3i2w<+f1u?2U}X3i7pJ$;j|w4&01w3tr!-W}QZ'
        'Vmd|azQCZ12L7Z9Uw*%QV-A~c^RT(+Tgcasld*$AC|#I0{4)692Ac84jxB7%WJ8|fp0nGyIX>Sc1E8Py@icq#E9^_Jz3C02+!Ngv'
        'n46AlGp2gb>!^~lB04cCpW-h*|JD{H(P360zQ^=pf7q+zF9J*F2%WhSysks)xr1H=&Dq<ypIa9)q$k0);eR>Kb=v&CfNcIZJf>k5'
        'YD4*HPJ9oC|K^Cn9*w)!g(*eswHe{@h(A5O?h5y%Zq?6BVc^zw)&*)9GB0cjv31l^2H|5=(XbZUX)E><fc74<2}SI%RrbMA)AyvB'
        'uE%K|Z58??+6Mywotyoa&ksC-Yfl=B=D8=>cD5>@%Ul8S61HR+X}2Zl3nJFkb?--ptUW4Rts_*8__OTHxaPF)vjO@q(oe!S|N9lT'
        'pgZaSeA@)K;nGEqn06~pM*;pR<K%<HNLX;0T<&y|ygorjU6c1l8F@btr`1d#WR(JUD$4XLNMzKp5uzPh3uG}_r!<jGEp<ICU2j{w'
        '=~<)58ohVvELpF%ZRO+nfjmh85;&qe3dI2Ka;dm&`V1B~v<tV33WpjpW{t$Iq8V7AvBP{Bo`jRarJa;)+q7fS0AkmUcdPdZObA!g'
        '>3vW84}aLE@O-Oa4&KV9z_@j7mAwlVBD40(six*HPxdQR_G%xYjtW}=cWeI|V7`i9?Ty!!2i5E(yb^I=R?n`hkXsN<ty{OUNTMNY'
        'Z7NpA?fV)0WpyjxYCI`{{OfV+qYB+OP!-iUJ;91s;uh><QZks3`d8Je>I5-gE0t-WMTN`(6M+@d0GC{F12-y_o?gb#!Yr{!PZj=%'
        '*Pi-~qV;uNsTz>p_TmHkEQkrUm#8@`I{#hH`c-tE$?S0Hv{?h-MD7+4@NcqemvWy_g{OKP9fJ^n$Oj^PjxNjfYK9c7tc?ChvXCVn'
        'aLAgSt<P9$d4_eX(AR}^Z!jN4Mv1c)pbcb#4jP?R<=q&-3mSD(rD94jPuv|!?>EC3JIecxBGxQJIhJnWmWTo*QfP0WXbxaqud-?|'
        '95X~b)sp~YKyL|~s%6n-?C&zh)I>5PJP_U+nPSU$4!burWen`zpA(K4ftfOuCoN{w##|xZ@n^<ni!L&l>Rn>YL}X>;?=3`lm16Q9'
        'q2gJImMn~j2qW^EE=?%;7IzZE19W%9$>`RoO#cGMYMIxRi;k0EVzdGcRJh2;Wy+lTZI*=SD<_7T2pndQC6drNN~LB)%vgmHBU`32'
        'p$_$x_#olj+H;w9;lS0}xg~ICAZKe)Up5x0JZEvF`X;RLlx`mSYbFM*F)I+%^K#8~R(WVoJ?L;Pdv0x~*0x^pL^-3KEJy0a<m^*k'
        'H*`PV71SuHHtmI{?x?(oD95|xv95wS24w09d*jU<6b?#kNJb&cq8WUnU?#Y^p#vpgi8;oQk0SdyaK~8|hmt(Ve+HKDdntRn8b!_v'
        '?(Qm(#leI0NO~9P3h!@H79hF_(WD~J3YNeyHik-$sS3YUHec6xPRl!0FEEXoYTex8Syz5`s<kV|bI-A=b_XcDx*yN7Y=wW=>opmd'
        'k?ji^k;}v4IQ}ljo2c?L<Oro%b}d_#)7zK03uHCGEVHzizpYj97BG%+JNIcY+gK=9n4SY?4HIfZWoNa%E2|G3xy<^PHxuM?LOt$y'
        'h=4!AUBAqBWONig1zDk33f9)bKMhpJpQ_tLB|@_gvRZ&@=1f*MbXneprD?FLrL`vR8D+w&2+m@{Zw&M#!<&PWZh;?>sX!@`R;D_g'
        '+|NKSUrjA5`CBF{YGb;^bb+GGedLt-Q38z@gFST}10PSqRp0ETIM;q!=Gw2Kck&F{sT|j2BSV$Qlxd47BZ*T`jF(PdC`rlyF%maw'
        'jK$GMkd8gq?~%2TKpKK(W6!Ds(uIn&YQcs`(ePKxDT(<;vgjHOksuWE-4b0#Qmv7u5googidHc0F8`dT`C?tUnKe~r>O;~$ftvHz'
        'B%V*p^<oxXGtuHh3Fi!WAZ4||)YndL*8UL{Fme&DI3q6Ktzv18D!9tz=gtO5c^uQmf~u1Ye5Hd`wvX1$GLT(mF@g6--=hr}2s+-s'
        ';S31x4}UoJfsW9_t*`ku%ZVj2J`sEh;Ou4+eyp@t%L1D!0Flc@jlTeKyv1_0@`9M4${pgbaZ@HJqy>|a(pQ)9A}unOJkJI8ox+px'
        'Plu-`M~4?DXKz`2?MTcgI$}jsX}5-Yyt%C~Xw$ERdN2ZDTiHU%4$o*4E;7TQU>$T|FiYDCJLzGW^~8l#38~qWZWX+{A0;*+A#FtT'
        'Ge(aIYVUbH?A_(6T;$VxYmtfad;~t*(77O5a*rkwf7G6BXfNz0jNucIbL(=E;&kMTo2p!|61)T)Th$9dxu1Th6LcGZ9F}$n+2IJR'
        'i}S-*-ya_(?_Zt0JKh9FHow)A&uF<jpol(BFs&_zmiAyL*%Jn~2mej-zReE;xg0i@qIbxmYtLkBq%vmN#>;Tbz=lHW_MjlG;epoX'
        'M`3NNeYD8!IFzcrCAIvzMXc==`BOFrt}%1IV`Au()7H1_Clv#XRM#xjz^Ybjk%1WGq^b0%V>%w-r(_`mh0N&+S?C_KN0Ep-<s963'
        '6_zb-Q%<m5x7fBNvv$acA|B>DAS1`JfQ>5`z7l#Ebtgp!;@-f~+f%}OwrGMJM<??rbp;)?WK}x9KpHKm)Rb$`0$MYo+8C6Upt(&O'
        'rz2&<5H+`V)m0yqlU}Owk0@0Nxxph;2x%;l?x_2E3=pB8gZ7OtL)O{il9yM~5VH+S9QIBo2vQKfo|zL4UJ0{y6Ym^|(GCKoH4h7='
        'rLcTBGq!;&!em>>#1?b>eV{K(iC9(n5)=Q4Sxb}#0T55w0#jd+O=H|~`X!_?4AVkXMw6F#h;k{C)FiR}>S=Bydhq(wUERpe4PjK*'
        'VP#T@zZlQ~jkJo%LSftN@l#gi^Ls{LHhBvdGpjKpmSjev*bD;3%o!fEcNp4g$R6H$X_z>FW12Yo=&+GtO_hT<nk*0Xk=84uF)EYO'
        '(nJGl+|wqIf9k~X?${pJ-IsBaKt}pq1s9p+y?;h}ztyXik3RMTwhJqKY3<t{51k1RPsnWs>$uL+#yurorK+DY^#n?kp#T}0kK+is'
        'j2*$->mBs#V5WMqYUQr(qkn~)OjqlqUcezUhEmVM%{U?@Sza5>)U%G!IHpyq5bn6`x8bg2!tLZ{wdRG&OTBGPla);6n`mpBl1vL5'
        'g+?^P1eg^c^QtV+R3iLqXt$w@t~S9w=gyR50{<sDxPB>x7LYeUf+LF$+rAe0b%pHh=)1jXIz@hm8iGl>y(rEeDXO^&NDZpGm?Iv?'
        'YeA57I66LY+m3~1eeuJ)qmy&3x7wi(akE@ey&U*#(>DS6<Kp<yP5*lI=j7Glt2f8Vo3kH|gPjoIXqNAOzIb!?_UP>G#b3@(E{-v('
        '<<;5I@g#n3yF8ZHIoiEch8JN#EHOe8(Cj9i-V>q93*mj1;RZtO7`wn+m8*fexF%!Lj^F+?qFosF`uzQyLtm55>R*1{hex^eP3TJ8'
        'aBGFr4SV$<=6Dr(L*m?1#l2WD3g}Zp7ZGmR%rptOl)c-4pfy8|ku?gT@niGbAe?xbJ8rnG(XoD~vi{mZB=nUC`fz!RY~u=6;<*t?'
        'V)o)8e5!#FJR+I|OjWT2aijr(^b?Jy)I^d(>EWlKZ#$FGSJC%bwj%Vu$%-}dYuX6R&@O`8)<9MlWV@C*^hB{&%F9$5Sx3K85PWxX'
        'w8vABO6pCOaprXzOWMS<>bGd}M*+W`m>LA(Wt6YxfD~|kLFcWL)%|!;-sIEqHO>)4nz7iUC|_dH_9!{ci}j}?1&<3}jN#7U#W|_q'
        'T1uJzF3_We6eHnCO>Xl#5Q-(lH*O4+9Ba5>nI-Do+(4rMb1mymxL$VI4X9gaxOP-ffdUibGn7%-bM41vOIDhB!lICz@T<#x4wLJ~'
        '&8_e=Sbac&3w1gQmSqGqn7<!#q)CGI9mUbtb}yl-EqzY>6QBCWpZx7kKO15^hd*QnAb`QAtV_27V&vKAG|Po^*@)fXDDrJ=6Y#xn'
        'Mpnma)>!%{f$3#~c$U}Gw4%rei9iO(n3w^kY-O+hTG|)Xq_m9zUdD`hbj{rO<nrKm`}+<;*+vL5vaAczl5<Qx$D~%}%F-4?v{SQ9'
        'YzAEvdv$(;_6w{Y=jhWWn^Z(WGi=5qW`#oZ6{31R+oXk=CI_rkYdF56SUfPbX%@kF#Ar!TXJz#v_IGG;eJoO2SYp4V{N$0qdLot$'
        '!b3R?1Dn)BP`f|aoGxTtWAK}fI%K__o;s#*19lS)#hpF~&QL)GB!uO`GbL5gu;A7IoOK<3MYWu%nukrFESL|n^s<n4ZPiK|`nElF'
        '>fG6r3>`h^E8ppBpFnM~U!?0|iU#2iAR@8%o>B5TyUm4#l8i5ae%EPL<y1Qage9jhl#w{eKbCf0WF{ck(g`^3N?+sv@SE%V@AD=n'
        'hY;Zjk(nU;PdFKX<07UT$wON%ccpl{#<=M~L{4To^$azErzJlpS+E`1EL{o|<H;GUFi4`#35+5(fo(Z^(%`grht8u}c_Sm;UhY`&'
        'CbKfDMLL&{<p*hiR?ZnBaXP>iqXW=4;Dob=1c#1z^Zqi!b}{EZ@nI{MckCgm(o1rkElR8^11hqLG{j!bsC03WPr@LpJ!WoE8{UdI'
        '5rliOmPKpO54LW0%lR(9GH}jQ7=Bs`dnwgr#Vc(XGpc1kt`!ewsmK--X$vFZnHxv%Z%d<+0lE!maBx+X4Hz|DQI+~MTe1{Rh$oXx'
        '(|OH4fiyJ*bRtC8h{5soYCUGeEMa^mbJ_BBKCbf_Y36N(Hkl@(UffGE&i2u=4?e?JA}{;&4R)4z5(RYY>cM1=pJM_LQsu5#0$}g_'
        'tE#a^GW{J60Eo%etME-WxOAU)L_5SVkSfV6TI)ww4*_kkB~b;d-nVQP9<jMwt~UiI>I{9RMX8a?)P2OE42$Z1F&#vv^`fCd)pDOK'
        'g1z0o_;v=%R-3Ti?`*Cv1?yl4Xmg1-WzdmP&IQu2uiyEmt7BUhKy-{Bdfa{Q*0foUf^SCrAA}N>a&fcu$q+X<@je=e-v4oQhCV=-'
        'a^%FU?mWF|a+EfrABrQz3pFn>f)3tlW`|mctl&KMmruYuUIXG0qbM0-<O@hPi)`SU5k&Ayz!_~^O0-#HOAt2j)FhMgytMchdL>b;'
        'qn|_j6AHf)cQgJYeq?fGV<MLV?U^V4#<CX*R(#NrcL_iyujGHGuMZf!Vkrm4I{K!kk?tSv%@7Op<E#FCSrpjm(O7x!4$Tv;dol^?'
        'up3--biSVW8~+!OtpGy-%>on8)0DfjYj^V(=tnL4F$7UrOTz)A?Gv6j*H26I8>{0jY?tbIchl1i)L8T_h~tOsezHiH*RvF_10LYN'
        'q;YLKqHUS-9z3GYB1Kn+lza?>pnFq=F(_ns<hPgZ1e^<-J#3Gmjshuq@nbDmlVK;}HMjjJBh*Rox;Q)cC%+r-+cNhNHrEVAI8H66'
        'iN0^Sz@)6K3n7LIj$(=32HR41XSLvtd0gvt^)dfgVwjc%5jGM4WmmnuJ2~2=w40cg2lKI18Hm8btG`?~;`TsAx|hDYq{dxap=?$Z'
        '%p8q;aA-@c{rfQ+SWu$k7;4v~mP4O_4EoLf@Yj*I`#QQDk5))#BW!7T{^^=mlTSa~w}H<ZG?%Z<K9c2uFJzEvhp}<E_fB^**vli6'
        'jH8oAIJ!lLHC55&4fF(S0qv34QTycRF(JFXSx)8=>ol{ExTSf94zwOyUf?mh>!&xECtsY&$b(C)EY?QsTI@aS#`u==l#C8~E{TX+'
        'bam=2p`jtM)w<)B4k85B$^!zv$HYjHV$YVJk<@lL=Sv_T|H!IxSDG56=?p7Erv;NDGMd+-h^;VA8huHBW|pGLyeD$Flc$kxxMM|g'
        'AZ|FsO-1GmzV;!^NEoAN^akQH+V%=yR>Jy2Hz3pM{-vPhawL5Ti4s@i^zML$mUrWwe{tk<cf_+dO3{mOQhac*i=6s~!MiPG$aQWq'
        '1yE0yv4<t2wC=k;8sy=_#{k(o8-FvJ(C604fA-8fNpBY(aVECICr~!(bDJfeiu+I)9!SPB35#qd`*0_rzVviQpQ^JYP$kq6zxA$#'
        'M__YuqD(u0B?&p^(*^g%2hIr{eegs}ZjJe33quXJ+Qd*NPq>Y02w4}ry^FyT;=kH9a)on@B%CLz%sE}^#xe%b9S7UB8{XZP3%R)x'
        '-O#7(ZSnBM;Z2vZdpl*rHpeI`E>oC~ifVd&^4E(W&yPVbd~^K6;nQs_#x5(syX(5-*H^xCjnSK&UHX7@Nv8*@J>f$@GrzvKrAS9U'
        '455vc-<tVWdjUS2dGN-3X(nQMm{>J=HloBKBC(>SmYgyEi)i=s1~~K$#u<@jym$Wo{hks?UUDZGO@nqVR5y^(6Z&~V-^n$IEhwwS'
        'by+Sz+^75{GGSLrPeD*~<I-Knwwgj8;YwQ5)w@f>`f&Ax8H#-Qf*O#yml^s#)<yae#1(Wgn!&GRk`#%FYzu@jU!SpsCxPw1bz^{|'
        'XVLTh7rz((@lA_7QzS9Mjz)wVzDRIUid;{mWpMd696mhq$fr`O434NvAxJHR93Pr&1~0d18Jc$x<i)Hi@W|d`Jsy$1P(*|~$!g@c'
        'lx2sUz@ib!%s`LVt5xZwn2=fR#JoItawTj;dLEf4*NW>`=S$}B2|~tWR2y(MBbo0bfn800tt+9Ngugu=no&023{^RDloc`zH!i)*'
        'Z_O`*>6|K>2xFjW*F)o7PfKGgynnDXv}55l4*b_(C`eSoX^GgD5az(d2SE9m(xrYBy+kHo48KU&*_r%(T{bC*6-ioM=M9FQCry<h'
        '*HKQ;_+e{FUYfE(qP#k^X3w~^gOE;6#~NL?l(kA-M>68`z489Si$U24Ku>I1`Zdo}0F+KQO>lGcj=!V!_FTEQO1(TJVAV^f#KSfD'
        '(78{6Zvs&OoO<@`!yW!*Mp<B#O7xQggS^8+X~_rXkyj)}T#>e-C-OoSOcp1`N-&pwL>tdkWEkW*5w~w;Mj>X)uS5<h+Ch3^)HXM1'
        'py)f|)KfdYoKf7N`^uO3P}b`j=QRq<<zn5yX)>;S>FiH?PC9PGO&d%R<&bYVb))7q`SG~UuL7jA_1K{SToM1{uo@PY@Pf51C%sAQ'
        'Tjc4B9B<*tr0ilyl;LW5dzG_Uqy1G>mBZ>#pC}%haLW>vsHILDnd1+%0rUMvbY0T_ZRlJXE1PCHWq$JA(f}P0`O=;Vyj@y$zCdrq'
        'f7U=Ow277S)QQ1uDxvqqv-{kDE?5k^6JQ#vl>WHDVRuV$8A)urigEQX#3jS4ivjJxP<WEe1lQt`Sl=-E_7NqtEdPW8{NrkAnFo_E'
        '^M-Q|h?~*;8KoNCqUwTM0>(-f8uqhFL=ZdMT}+`zSzR@U^W#4|2}_Z*$tSuh_=cj@9SMmI3famR3EVHAgB}(Kfh7~>iNp9vcehUQ'
        'ZKa<__donPOU{qZ-k$y({gZ#aJ$rq2dV2O3{rl~Ar)RIeABHcpWATI;^=c*~kE`pL4i&JBEM0a~8<p9Dba_5%F~$Q_l!J}}T_Uk9'
        '_n=bS>YsU0(j|sq>f4QO`Pj2zeM<gm%0xM!CvM{8a0{lE)7v#5-@!yckIKOg3|(wPB^@4C-V3D8I?I(2U)oTD33ms+>c2a!;u^hL'
        'w)PaOfS8-QM1eXfYV+AtJlmA0(JC!sR2tEJsz<8J4X5ACx{SCcDuZ|t$0^Ri-i8475c@EqOHvh3(yC?WNVmOWO=79sxPXq8flMHg'
        'k>0yk$0GZs*)ttGk^S<(KA#Vkx!;3_$a*dDO%*sWdFsLDWHug&K!!AP6oU|%{80=dwW*TwaPtzD`K3_LzuZDsAe6nvnIMs#VywLQ'
        'ZchoDI)jRe31m~#Em2SM3pyTpp~L6wJChOYzeUR#$%Dej5A)(W+UztN2|+R~3^R#N#Z0+D_fE5v^N-f-ogcGHPhJz$5{4>!@@9Q)'
        '+%>}SUt$3EGL?zE=l7~PUh$(_fhb!~Q@pgubuv|UdB3}V<FynOhv_$>iJg-7MIv4!16w3CrXE^}EW)1Jp%uVhiqzcYs@cWt!;~&X'
        'UAQouo@3DYJ<diml{UK_a{!~2qMKc=Yw0mnQ5rxKFaa<d<WR63Z)cJJatEbjR&Kc_Rc;JJCvsJfkywW#-gjO-@@%k~W0SvctDqtU'
        'o23I2lcK-OV?6W~Hc8rr7&aC$QARhjPKfcAZ!rm@9QigzEtkazQ#EH(EJx1<ikd${8isx1FX>L4(bwh*Yr_^~sP-a2%1R@RrFrCY'
        '5<hu%J1*;!mJ=~!&be{?{>Re`;f4vea8`B|sLK*;@4}(g0ZdBJKJ`hfGh_XiCK#`VocOwNrmR1p!Un;~={=x~7KqP2T-8Clf@s?b'
        '!351V?{P|oG0||aclgS;!}1$i)grHXS^J=NQi!8^`|Tw1mBK0Ds8Nn+#lL(86VE+7*)TEYZIcCL?Hq!T>#l72Vl6OmbRA=oUcTM<'
        'HxqG)JzF6HKCanfMp>F<V@Et|uj-!@dzP#g52ZvE{kwrG(kklofoGLq>;bLIkplO;NO;i^S1l71Nka~8eM%$GD!pHnsYSsKgqeTW'
        '+kWrka}SN{>6R5i3P#Ze-O_v-Y$+-H7m3ueBQ^I8)p5`VfZGILvaIRtR7G2`kA%KtVHVvAC@Tuz6Z{lD85uk*M3dOxG3I`1OvgVw'
        'Ql10t53u|P;#18!G9rPv&jUn&@oc?ZA^)S@ACV}XfCODnnC#V<eKN%=WRpQW!VN#bEc+?hjEb}n<|4e%`L`k-j=B4`jJIA6NDh}S'
        'F{<@Y-XY<z>}+Cs!+_6hr<WB?o(r~{)gI>>%|EqIr`OIRx)P?Aznq(<mRIM;hZpk4@n2t^x;B_mv|oO+?*^*|%q@2v<`$uNQxO*h'
        'BHtJD#kzI-WwYYnQnkdY$8JGGON>KGVIK!PP}DGZqU7AoQ}xh`KC0q+W_XZ5TSKiA0(YiO_ELGTB~fh!J1~m2zB72gx<#lg0S30E'
        'pjA|%%j_M6Zn_ftS+z@iiE@N5uodsOy`E(z#aHrq=;oVw;GFV9oCr)SV=C#X=v4^#k5bUg1$44Tqcj?gdMPlpGh$Zlyt40zR2(h)'
        '&QmhnB&>}nqSI1H(0ceytHNK;nu!V~&MCdxlB|X*4gN~bVmHXuI^t$ZhxSRg#U&@Xy)Dc3x<{Z+bFY+E-qaqggev}6Ephm_A!A=f'
        'M<r*z{IrtR489uu+d8_-QoLY_sto{KZ7AOZz^oS0_5BJc+1Q&dK!LnHi`ElCjA@yq>ChO4dsQaC<)vYMUQ~1FuMvf-XP7n0$uCgW'
        '6hTgwmt8Wi020p3U~d?PY6MgiWW{lF5!*BVTZesjW+Ltz^wBHr$YwhGg^7nR+>~J?-tLk*CUXYk=96hrAzz>~RSFG1!m1ciL1C}3'
        '97=#H@B5Dx+G9%JKxcIMR-6G+COKOgr3jFdU0|S>tkgl*T<R}RWb7sx;@2Cq!wll~buu+#@XCsTHS$=6uP24msyGy&Z3^^anv=a#'
        '9rNG;?^hVUlW1>6ydO`*w<hL1%blGhfkjc4>C3ns5_GOrT~w?BF+=!DrF<l-96o7hgH*393toJ+^Zx+wVj7$'
        , 16867, 76143, '11e5110aa8dcf39c5b11c0bd06a6d02933052e917fa46bf6d53a5467107d6def'),
    'sdk4df': (
        'c-rlKZF}3swcvOC3KV&sE$L8{oVIBzhxb{<k{fLm%U4#?W>qZ$k&uLI5?}$+vYL8-`<}NM%nW8gP?mf9Vg1~jiU8*A%$YOi{lsy6'
        'R%B6;uJZR;^yA^_$<g7($=U1Zwn~dtloqony}hln+jNyh^{TAW+bk;Yi>!)n$|_2uX<1CG3|?02V!X3+IG;zeY&uV?Y!=;D`6|7h'
        'Lxc5dxn9-Lbv7@H+h|orB@DW(^7q(nx>{w6<!T&V+~suy|5vAr<vg41q|<4+E>?MQJBo@DW)t1y^Q?ZT;rr<C>vEMwG>00dd0l=O'
        'M{lZfn$>kwUe{R#edlFS!wlcUY*%;LPFdx*d6CXxjB*Ym&!XvFKA*u_%k?t4et?<Zr0Y4&B#W{S%XvP{S86)Dv#g$G#SGxGv#d&-'
        'N|erKIgXOf=MNEpA<YXlI`n>>SF5|-Ygof9Y8uy3I;~2WWs%+Q)G%F|B|^H&mH;<e@Hl#%<uK<eQbPftx%;$;)`cDex=okRU}u(Q'
        'i?VnTrPX!5s?zFVcU5J&*#f$S{{OzttE@(l;ZOhqnD*b-={&#5p|5vYRb=y>dRi_sm_P{)Y5+%cQ<Vz<AneSdoUM5-^(tSjSJ2mK'
        '1`|qWi<}k$DDV<rR_iG)14e>A)Ly`faVzoyU<PCU16sopqk4LmVYe0TCII?2t6+4($ep{gUNyZVa@?f(eD@};S1+QUe_rK_43I0S'
        'Gnmq>{`u#Kpw0aP<YqXH_kx_K>AHZSDp<xEdtI&4=^cVoqr(iKGhGQ*TxWMVqCcR0TCEU4(yGc~me(1eezpU9Uf$yxjd2j;vw9r8'
        'U6o7O(sT)vNmqhou!d)8@$f9VU8mKI7PGFh@eU%~6ncd2t879041ik#D04hObk?S;wcr`g6URn?J~Rhy3M<M+fD7<5t+Ty4hr^gw'
        'qo`iy^Z5wQ&xaL^H$vntD?Z=z@)ouP&LqN2pWS)-0Dv9u#Bsbs`=2B?Yiye&QNEDIa47kZ?d-@iK%EEm_gz}w&GT#Z^S|n{P=7Dd'
        ')t&mgta*SXJcG|w?{ADx0NU~w?8Qp|{ZOkvS9bvD86E@m01#t``yK1~u2*GNOv_nTC45>EfN{C5rg$Xk2ysoCsOL$8o6^a-yg5w^'
        '7~uT)KYuuWdy%|-`Q7pNhtVX8kv7hD-vfHj2sFER=(2jX_x^dj^X9vs-k!WXJWaM~_f@>Jb9(aQ@m7s~s~VlW{_*(r#o75!UCriz'
        'ySqT1>UB-?+&McxI(dCajm{4*UVgXL*uRV0?cbcAy*fEP?rL9Fuz^Uo>M2mB=^f3Ar=#Ka>g2B%Kb&`Vv%Gt#b2v)7g6p-@g<8q+'
        '>mRZG$(vVi6S(sZ-yUDQP0s%E`uHemu0i#+uY<SW9d6eNw)pCIUqfHtAO1Db{k?=%Z=sjpeC51=eLFv)SI@utgQrn)bo}PxJAC~$'
        'V&dB$PB-ii5_5tEcBLlu?N1jxMza6gKP12V{nzyN?b#3KFOT)h-$u`(=lfr&|1m##bMhL$fQ8Z1qaV%>zdboUx%kPL|5y9T{{H^X'
        '*$)?Qez-_pAAV0y2l4U&sO2giMe%B}#Q!1sg@4Sh@xM%^YWx$ZR2>g@{&ar!!y8!T*_&frq@vu(l5hTmsBFA*aenyn&#(#lL%G8f'
        'x{?#RBogCFj(3uylRp7C;9DTa({cgyG8<I!<^Jv;)7_h^U%vkB$G`n=n83~s5J<SZf7F0g6ydn4%4&c_WPC)_#d<M3*oojDkkiA4'
        'XKHo_Z>V3_%vsfU`I4@}e37q^e_6wAg#6Dnw8$#DtH(%})m%<X!1rcCXASp*_s}w%4Fa=mCPl0lGG+I8^nl#e+%igUR!IC-GPhsX'
        'at}rS$f|Nzz^<-Fxc#v|#mC{C>-7}BfEy@-IUpyeXe<0N&)|~6rB2ggn$7173ZT<>z^bht#?;#xu|XC~hu0R~RyV}W0k@IUt({HZ'
        ')xu*Shq7K|%(c|{EqpgtYvoA-uLpM;@*+txsI&RaNHK0zf{Pc};J<pk%&Ng~tUm{A1c;m4XH3rlo!YTT!3uaVLcD1P=%j~$35*kK'
        '0)UFvZ@t|~_kQ!dlcb)Ps~T==JZK5=ba;*ufLUI{rA9vh4O3w16TUy`kseb$({t4S;siHeow<z8X97GYFe^BT1fcVdp22N>i>nL)'
        'oMwew2~WucIl+V8!vg4kop-7cyjFiYU)YO-?=+V%o~|oowB^+xxDUGNYd9OuM>Y)n-#9?A=5P+%_^vfHfsFQyrce8X%*+@FO1UbF'
        'd^#8+6(VRB8Jun8d})YLw1BBVbAe-iLnlzbZ=hSHIh?x?2~)kOQ4qYVELoPglK0sF(0&cOR-_B~?;`z>FV+hgl4rDfSjtyJ;4Gs7'
        'aF?*j^D<ox>F6T&H_mJBS3Web3_sbAzKQ5X^vy(#0e!@IL5D8-1xNoV2MB2Cx+-`C)t$^8B-b@Cw8=HzG-~EV{$<9<bpp7FY$tVk'
        '1M7q*=A`hNsPZLX5}wF<45(NP@S_p_I!n%v&R(DX6#bKby*_(&c6xgDm*)5DZ%@x&{+au_2bm6^-^{3&rfWDY)pa~XHWbKNmM)sj'
        '!Y>KUu^sZi1O8%+VqsAtI;c+>{P@lIZF2JV{P<4;ZauD73CM04!@qe}07(X{gxlYFQG;}bpeIndBp@~jUtWM@uZVrh-)AWI5Zp;%'
        'H^^L--s5rR`P0#3>G;d&xw{Hj+W<ZvHnZ@Ii`&X?L86&LGdM3zM@)b>0nXie{13koDgiy<v+<nz7#fIfKzEkC9~tn=i*n?E)BL@_'
        'Bb^kr1=;5HR9+8pYX-CoJ%;{8L+D>LLYq{#|LGQb4$UJyu5%g(0tr0{<2Oyi_{~c-9(dPkfcJARxc8#X-rA@(y-SN*RBGL!Hb#iJ'
        'O@Npv0Md@4Ut*Yh4p;m^<lqR9FgS?Tb9nMm5iAhE;Wc4ClYmwAU=VH|2u0~JP`g<@pwY_f|H`H-K;OKole@BfH({j4@AzpKq?Tz_'
        'X9?+afES+3)5Y~Hjgo_CkdWdbAtF8;j^XYq?*|)T9=cWHqAZx=n|#y%dVBUd9?D6?BfMNi$gQrq)hPM_Zae@8v#UrR;iJA6nZ7Mr'
        '1F}jBy3%)C{ZLF3)~l4&0~3LRN6`PHlk?-3C~vzL!mz!YM3-P(;~wCzh_9X7Ury&`ompSX)Oq`q*qeyhn~2_UAY%C_(u<RIO@a4@'
        'a{wn0Soa!k$VBeKUp@l<e&pLxl#i20y19%)1I1T-6v`3_rXDQXW8n_}w<Vg#F4G`=4e>&mAybdkr_NT*3!o3b#Hf{7q{w38a4a|?'
        'ANtXuThi)MHMqj&0cAp{DUCo4;r1BduOS^`#w?PuBegK4UsJ7xJfzj_dlQ8CTfnuPuW#XWp(wk&sS{M(!E)<l`2ctZgb9dTRl`xg'
        '&8NVOW@VKv68&P_;B_LRv;j~YWlRe6LA<-m>VWnR5JaCli%*LOYJQo+W&YuS{tI{XR|JO3co$`Lp81uB8X(Q!Ca|&!sU}_K*x@kR'
        'g`3`{v?1U%>S~lewKkp?ssM+xy_u()5SRDJiR;Z{w77E73_l|ro98v-*mGnvh~=PH@T0Axv1Y9p9iVDxym)Bi0FA8{F*Btg5PZ{y'
        'lQyIt5Bp5~pk|42hVtec*10(M9DEo5?Qb!0V*nmzq50{D{eAm+i>*^gt>)*!YoHJYg9W5#h47~C#x?8^;M!j7W98^mn)M$T#pZK*'
        're-vV@feTkKVu}&fJF2@FL;<?Yr4yMiU<~*ENXFJchKTu?1E};QDXeZi(m!uAYQL-cK={}E_ai89kp(wEp8+)WFs1!*ox+Ya<2Y2'
        'hIGO=O1Xk=Cei+mI(vY^bn*a`y{H8*+60y!5^+WLBqv>fTn+KZ7U=0Rn)z|w2W;#UDPVbjsrtY2O|2jq#Xx#$NV_bw6QpFgSh88d'
        '>Yn(@a{{Q5;Fa8RarPmF)vk*i`a$6SBP*Keho;@ak$QatOGSB+Z5!kIE`?J_^L9~ZIKIn1%<@~9_Tcm55iOw$e~@Y>%(jT}57{eJ'
        '57FfDjFFaL5FZ>EAjof;&k4AMfV#6G$ni;fU6=DUi1I^w4YIN7TYDeHzC!SeuSUi_K=fU7gk-6^hU1YJg|#)b-U+iCd$KPLkQs3m'
        '#wk4ZqMW=8TnG9s{Qhn07^q7CJ2Lh{4e!Aygae=>@oXs5<Iw|t;<A|<o?z_Y0l_6bdBLhC|DX@E=Pp*qTRx-%PDC64{thl_(!ImY'
        'oUNL_5_<8`Co-sm?<`myf1bBz*@mV?Uw-uQCC}z+=vg5(kYh}6GcFF}O$CBhxvs}-JFf%c3G;OPsoAM&#utwIK#e%`0%5jBUIbki'
        'pbdH#%+uwPEWs{7NC)eILp@GsGegr5+S*Irq$`UiT5tI7tREJr$-zCm$#2ToKks!>ua{_1@$DUTXU_)CzC9M85BGo2>YisVp9@A^'
        ';jB?BYEIk4G5tYEJdIzSygG}x3CuK`&uUE)iuHW%OgNj@S$k^Iyp4Kln!~_q%zdz?t+t~B*Zix+y&}N?O<YPuiiaKjAQ3{rgXrC!'
        'tYz4`YluGW|MBY}AX^uPpp1eJu9f{Sid&1v(;9-=7_dAmP~i;H$t=s3_=ixIp`U(n!-LIOr4YDd_vqs3xpPP)q~WiC$S$*K4ofCt'
        'D1QqH;Ey)Y4z(=RwxJH@ttD`*QXmL5JK4zhNCg~-zRMn15js#iYm>vV!qsF|4jRebL3dkpzl2V&NcNrz!5`5zNiQe(m%-T(*Z8G<'
        '$+_1fedCHkV%5dlqAa5Yh>HGu054qox~?yg)4&<xFH>=5W0aEhM*$T@*aUmt_!{{PvBvAh^7$(N0OYW-*6&Tz0?jPxJTdKiX#5<p'
        '{=O)q>k`<od$jR2wo2;o=bsIk9DtMGDDLOypOI*wx6xv;CU2dQ)|Rt|v0SgvUx!@P=%BEl)che53DfnLJArG9eG1T_2l?CU^$d`Z'
        'tgXx@i&d1#g78$!Tui9!mM5-05gdWWSjj$4$}g~Sz@i(N84Y$lB0r`vteXZ(*k(Pr0opuyl>#{)!n&7P1-&hRzaq1#Wy&p!`NIp*'
        'N6qKZ&s_$b=yjH^prPTVh6DQsxv17OM!M1}0_yE{US1<xj187$4u^Xj9pXv6*RROm1x?RL3+~GKELtxO*EpUnn{Ci2J}YlQewd>P'
        'chz`n!BQGuwi2z`uv%FgOcHH+8|}{Q^Crysvk@`1sG;V4ZnTmk<$=lOEDx<;0J>KX$>JK$&T`Er;1T<?X%`83s6Cs|<hWuY;pq{8'
        '%JNq8{jvlwKM3nSib4qQ>5S#B#MeUg=6LjZIuU50JvDK@o_xJOiV!VWIs_=M5Yy)R{cra7{pyyDGYee#h?e3yGRA=yh$%gKYl#wk'
        'enl`f{X$q^l5_6ktqI4Bp&Xb1xouf+T_6K3x1Rui@|&*#R`wtrkoApXEwQ65GOgja{;4$j<+knCb8hsXOfT%dfaVq;`!-$S`AgK('
        'fjyqnmPu$LBy_@d=>vC;dt@vp9)kV=2Ez1(`e^qlTb>x^B=!wZFN_I025wiO<v*BF%m1roLU!jtY?Qqy7A>tu!c?_dEB>m>kgO10'
        'vG>MpC|Y*eR~PlwKzy>$9c0t#a~A99a?tc<s%}X2-yW#7mhjod0RRPWZh$ci%pSMWF#WksA*?KseP_+aFCSf}6-LGGkF@osvFv!<'
        'R?zbj4&r<039pmRZ<X6-B5s>oew_j{P)upE``xoh*~NMi5ns{$ZC>CsZY#X3do}3ko#V9Xau0Gog{hDWqHm#kQ`ltCwQY@NEBsAQ'
        '4CsWXb~*{YM0JP%ExF5Q0jOwBvimc177V>pd`#ahLoO~ccuwV9=jqxE((rF;iWE&IVEX*|ksXDGq;<VW`$1WcfmvVXGmi_8ue~_g'
        'kiH~}PxE5^K|*nqYawvT*&++*;J%=!7V+N9KIAn85D@c+T?^f6cz@=zpaFKx!8t}>gdi1%3DLanDBJ_?1YxL~C=XOCRCt-+<hLjt'
        'rV(?H;~j%9Tts6vrzGrskE15~JN?@7mGZnFc$wXeyzMaT0cx@A#IH|;YqwbR$tH%q#kfy=Ec~Ql=EGfhxcrHi^LLr%{f<t%nC*^t'
        '9X<NCV$xF>=_`~>HcBnwzUAaJSj5ZpF^-DG$P{PRB0d`O%8}K$@-JiStzn(uwj^06q#CFPE`dM`J=s1KyQP^hOQCIjLI^tS;=zQ&'
        '(mYtIe5)J67?n5VCyspVjQY3ydmDIL{PVEo!eqwLj2rC>xpK7iFR^!sh93?LVyx{Tj=ogjZ?1xTW^~-z%~q$1RWrA-A!4kaw*6Dc'
        ')dLrGPo@^vdWnxLLzq`@-xkhdi>}}UO*UvWMK1jPd8h)-)s>s@p@eSwJ5teNa9BWSD`3l1BpRJy>eWVaZ#TZvFX11Zr&u`vnT|iE'
        'otrmEo5u{doiML1TW478lyXx$@ZhaIP<uSIT#D>4Dc#4M8LeP@Pk2{D446^wYQ7;_Yo|pvHLA)V|BME|gdMv+qRPH8Zkill*S}w4'
        'zZk*&5lFV^D<o!cZwg4*A=^~j9M!5p2!NRb3y)gI4{kK!*x((7w!gP`D*y8!!D!Rg4ud{CTVS~ChHZNBc>V>p^D1P)be;J+%+n$F'
        'zD4>WK{uXxMr2t;D9g`pqraaw3^LGxIq%ER=xqMWi`AxCgxZtKotF|iyGMsaL)`Hy>?yMQZ7Y_42Opk|`yV`ly)mGBzqi`e4H2e&'
        'psUuSsYe%lJJcK-AdGw%5g9iBDvrQq1%@7PwAuhabrFO#e{MUmSPp}Az++Ime4@qF?|3NQeZUDW2g8svVF#^KX6(js@ej}c_!Ys0'
        '{S#Fmes_zTSo>J|0w;eVz<l&cyp8vvLH#{0WJAJ3^8O5e)1tJE7l<(%wV56K$R#m@wo3=uww?F3XH{!>^~xIke&&ONt01=r+Mpdz'
        ';G<-NirhDS7X<n>b8PHNtX--D(#lm2Eo&o*)S_gKgJZW@T<zH%QuDVMf=kU4Q(L9+hc3vUM{D^<k#c%#TMEWG%mbvlk6puT<gOWp'
        'S6zKLA|{a_BZhhuS&`D6!eJ|$3rUIVnpN~{zj92}Vp=x#Lk!d`C0R0z7)@-2i7D5}2aSHjM{*3&N4_`gpkBd8eb#>E3Kg0}D(K=a'
        'Yi7WLJH5f(3DL#|Ni+!*&?wYE=aM$EEBFNv-KI0H+<4Ur$LvC#R%>kt2^$-G9M@Tv&gOZMc?=@XVfBiI_IXWw-*m2OqfFT>Guc*)'
        '<XNqu!BiyFV+fKQB$J?ftZ$p8mCanKJ72#P_Z=fyLu=OhdNt>5xQcjg6!C_db3{K|%81hOunLEReygf&`x4Y|?CY<KU+3YiuG%Jf'
        '`KXgG^se9Iy(vc7uo<=ijhjou=kD2D9g~TMDlMajWs?8)F3Y<d5Bhc3886jz&}&Pr*OVQUTHwIbo7VWZtd0XyW!UkVqktRuZI~mk'
        '8O;ER--b5CecKQ`XDa$ek;@`9YglsXu2x62y99El_Zniw6V{0WAU$TIf#l#iJ}BO9RJ@vfR23sayw)gs=7ZOmS#Y>`4q6C5Uc7^4'
        '4={p!vS0q*^u}OEwVToxB(2{!2W5cY>R4FygCcv?k99t4eo)Z5_smF)`_aky!1|aDj?ot$61KEu>wFfZB&x&j&yJ3r4xs~DwD*v;'
        'd><8lp!rotFDSOCkcdI=>GK$HFA=8RvqzxtMy>7yU*qnJd0@EFDvY9lf#HsRfjk#M92O5Y;r9&GiR1Wex!TP|iNTa*PhI{aC*w=O'
        '4E(Oj<bW;#;!%nJUYZ}TYsnj@)A?~48MvzOy3R2PUcQQEWybbWSZ;RT>|Hvg+l-BpAQwid@^U0wrpi3GXQUcDIn%lQa>Gejk1xrE'
        'FiBytdzV%-SVuZX)`&Bgj7_N6fF~nQ%eq5}bBHVDg=62b%+eJ10KLlDLv){_YbBuCY+d2iK@ey6#uj(w6W`SCY0gKz>0>L>hg$;V'
        'T?ZGnLIaiB7I}nHz=ktW)}4{pstzJfPC~5zCFOgHui8h~V+tDear22dph44dG;CKh9q1qm=;jTpk9qGBLR1(j9-8m~^bB|@$mvq~'
        'ZITR+pMA)_%_SF-w&=e+J&EW;m1pzE->Ixl?7&RUzL<TIy$8lUk#d6`%=Auh(Wd41OF5F70N<6FZqv;J=TXa<j+-`Ya2kzA$T5L|'
        'LjqS07?Ho^=qq=&`dqIIqz~=M>(oOG=Ah=O(*Z?AzQA}z76l-*#LQRZ;^B)<EZ=45d9ooNRCpS6>V_@+>gzy5<GaU|A9{?cofuB7'
        '$oH8)fXx&4aj&;7eNKD5VeKp=5S&mt=vYq}3kd#_#kCue+ZbTD_%vdrpMdo|Gn_)VjwD~FxbxVPRsKNj6N8Y@X|*QNCd}wLCmM85'
        '<$siWszcrd;;FaUW;UCQJ3VrB>4ZwMEGOAkJCq2<l~3ISUtZ?hI%mG5U^25%^jL5xX(va&VPjg*l_nna3Y<0{Zl|}Ieah&OEtBXY'
        'vQY$a9A5&bT1ILPv#nTeHiG7Ixqn6e#rU^9xcL=I5A=sOAzB9rW_fyB0NVp!8gOu~QHjK1?V=|{Me+)!vL}1YB}NnviwfP=CE5>0'
        '2C?O(HExmS+TDFe<te7tJ5bH|w{ogXG;H__eAZ@Uq)j$Ymo+N6M9+7C`PK&e<NY?Aqg~aTN0Abn3Goui2&vG22HnbnoV<A*d;@CK'
        'tg8tx?4~32E_jn86<4QEI56HlWWf%if#T%4iNbbPd=5elbUBt;<g?*N)1wK{p^YVBWIe1FLU;i)5h2U<?H#AO?4P6)|GimX&jExg'
        'TXuP)Giz$1q&P{q#_ljL_o2=Z3cCjUT5;R(BiKt;EmF+60TYv0ags*vflV#%p=~anX`Gnzj&e0?x;-)yJ5kop7049PBCjdnFTZ)<'
        'l;ZR37Cv84O8UF?3OX(@hXTf!rSn~a%&f|9RvmKJwx?4_dhk*rzLWRdPCMD>4pnP#?smNg(xZ?b;}+<B`!z@&K7F3hTj!k7A=_y?'
        'OnPECy`%Y*9vt+eU8)g%oiS`T>n0K=XFVNvok-Hvflpav^dMd=P3lro_wSE7_eIMoDzj_T+_$7HQOkgIE2XFnRHG+v^Nx-3Zj#lX'
        'p^)Vu%Z>c{e=7^o8})@PHLujx#o>Cs03n?C_rzSW?%5vji|D0rv8V-#GECS~ivkHXffO!GX(LbyCz@rVozoY>LMmevQW1jGRv2GC'
        'r4WdMG+7|d*RCq7jhn7y|8y!RuVfH=(|Qnm4Z@?Ge9D`^=?tiB^_2aQLSA)kK!Ta4m^xZVKU>!(&CFQ|XXn|RcUz8nbGA%0=R2`c'
        '6^x>GDqrtWv$FcyBCem9f58PQ=t5T77ED7#W_`JtDXk?&LF0DfC)_8Z*bApK3V%i-5vA89Dt9yJRgjb3iO-ubDHT-#0kBuu&AL{J'
        'xP8~aHg~Zn?Xdx8j9OW)x`|lE875r-KZ=O=CP!vw5zc9u_ekK*DMj#mH%YkSJ3<E10L3$3hFOB{PVIJqv-{|ix-Rr_3>;bsG{QIq'
        '+HIeJ>{v0@h$qeXw)KMaPd0cb2!)moN~yjlZcMD152SJ1RG$YTK)Z3@p3kstNDMfBn)DTo^}Ut1jwM$<q){5#w10O^n6Q8EZ9Yax'
        'XO;p86X=jO$$N2i1!n$g(sb!XvMNJkFov}lHWP(dY#u^_M)^0Jlo9NN<6H?}L}#WlN4w`~e;2AlRY!-Xrz8eN^*pD-GYB6Tu^v0!'
        '9cp$HKQ{^k>68;Qm<djEn!)4|<h+UsBLE#D>+D=R3{&Hi3hp#48S;(a49l&p&_t78AQokLM+Q3n2w0|+#Lku(RD)`wC;a6mk0YxC'
        'vF)|vR=vsmh;GxhN4d+TtzQQiRvn{y%|4_YXCj!WHcPI2*vUY;r%#{-8@<7`wN_dByiFTdaO=1q1Qj4=u>?O$vjxGoRPT;swy8o8'
        't%C5Kav}+?F7fuSl1~wbFKdL`ZK=AvZIy$X>ft{~a<r?sG@Yu9^eUj%oU6Zo1Al{2>SOsxCGnUn@?x+*em-heHXQCe5n4O}Qf`G+'
        'p8=zKVG~yh*bbQ-xv3)sK}UMGuG?!<ZankKvdD~4M#%5&6(on7Gacyrw0~PW83S=-A@cKNY{e#`)ti#HCZk6RrtOQG3XqeQ&sxKK'
        'x;?Xk1HsT{@q6o`ja$3#kS(6qLHyw+P(J3adBPj-zxgKWdF>c7iNcQ1DcB$_9sDZ*YG5#X3^hn}DI1GEHxwQ2Xy%?6OE!?%KHJ#j'
        'trcq7(tc=;AGzQ7({}JKzrDLpx$?{}ak^xOJ00b)FNw7u63Wd_Pc|QIl_1k-1kX6XWP-%8dGXQP+ZWOI>4)dGi2;MfM6xmNk{9Ac'
        'pndfM{Y~d-zSv{mI~A5d`9Ic+wWMUX%&2TYC825@;LLm}a@yQFqT9jeMYk?gvoGEjDxrO!3B#sAKFJlY%iFt$YhG_|pa((Nh`oM_'
        'feb4qbs?kAEScps=9f(?)IV<^DUw8;CUS<YPt;_N%wEtasJrbFWS#(T{$;rHnegWcaEQZJbyYs{Qa8XqR`0w)I=%&(jU}lYd%!zu'
        '>#;PBV{Me6O=O9rG?mpB%~ye(bsJf63z4I1*jW@6!;E;~l$ndC<oqTl*8_N@VpjdNBe0t{6V5`fudQKEaC#z!RTvz{wEahjjQjst'
        '@xW?&O;ke9S*eDX&W#zgByH%VeZ`8!xDQ&Wz#<bpWG~ITaRX9V48^<bfgN=8Q%d_hYUYeTISLh%Oam<Smmm8O72U1Nx?Eu_nI}eb'
        'Tf%Y+lHhI1)*<YM>)iV4_w|~k$xG1`i7aB=Rg?2U<*e>ARW++df6v*>gH;B*6h(@m`Np5`p$kryLRuNrRF5!^yL4TzHcq6O!k2cL'
        'r=Az!7VW1c5aXgF6TtuH%pP;ADv!TUJNT{cTP5bURO7Vu>;3dcEloynA|MI((#d;Nq*7UWFx>Hq)lRUJ&sk+_saKi>RWDYwVEZ*2'
        'BGLcdRnZWjH`yiQIDX57A#KIrtB{YIay~Ebi5HQ?0!>mU0N4AhHar7W3GY<Gx2W?G8%hw3%SAqo>LOj%cjamvohiPBt_0CUH_89+'
        'ur>mg&ddtTDaYYbIOt8o=G0oH56_GB5;{fiMg@;nJ}j;Xvq&GBE?x+c=3EeXk?WO8b%y(N{tn%^QlmfG&2jXK%yuw`^g5s8(PU1E'
        'ik9mv2aP_6^Wy0Z^t&3GoS3t(#4lZ!<$UDPGGW}I4j#mh03t1Ce!rHGO42xEZ5vy_Zlz^AL5`ni`7|rGJ6T^Oakpac$<5Fk)brh%'
        '{Y_f^Nx-!2wNJNpz^aLeR@@a@Nezpzp`h&0OlI?qfyjtRpGY!o=LnZ_HWAA6^tR^Os=ceJs^2e9&yN3k{8INt0l)ruUo&NV6G83C'
        '_@abQl~A)SE@Fv7mHo&{yy;1C?r{jwn~0=T`3Z0}Lq)WmLW?>Rg&AFp$(?;C$ZrJDF~xRG7FC0+tE1JRJ7C<cyJppr?L9+j>}&&R'
        'e!a_Ajzzo-^~;%pcU?PPo5^b68-`Pq^@+HL>zk(XF^mFkjQE3657bnBB`*}CZ*09{@0_i-{Z>i*sXs~K{3s1GsyI+!!l5s(nj?*D'
        'PE&ftO$72q^d_rzL3&woq&Ke~zE77gs8B@omczwK+ruffqIz9bbi1qaIEIgGL;lc{W*oh4RL!<0J?z<RJynrAz$v<3^4+(QPNpSs'
        '97;uAtLsl^uGUpx^fv>qX}o=jhu!g&ThO}#ozl^p2<24e6=eHZQrrfaRK<xs&|8&G#Ur%HKCCR3pxM81hcg6Y-cu+Go<K?P1O~82'
        'TM{43FFZBR@Hh{e?fo74`H7o8;;l)wQWShXceT&uvSx7kZmirlTX?YrH*%wI(blki%456bk+rS|tysZiD?=|s`M6{;)+oxhq*9>Z'
        'r<|B?*ou(ah8A-%1xy-)*UWmpB4K%sXY`>_UPnhI^+Bsib^1zAZw*JF2sqH)5*b9rl(2{f<00qYMVlX!AZH!$=P?2;!ufIjN3>t='
        'fAv)mNjw~Ivs_*7hfDm>XoXHScn!eBumT?<WA-V@Yvg0x4mvI^8~3bq&_)lOd}l*q(?{kF>cbmuP!gK_)z0TZfKS`}&$01aZ~BvM'
        '_$O}mCv0>`3NUI2TQpB(ih)q}8%#_@sV1?CLzOS7@HhLUIz%vtQcYe45UnZ0m-Lud(Er33iM5Q02otqr@vs9rRc#^Y>xMdOCg#Ir'
        'y?HVV0=9lA3$dQ@2%A!U(aDfL^+s-w$jZXoY@W3nk{Qr<%{d44{P<6wa!}QW1(o#;rWo(iNAOv!VKwt?m%5SJN0bfATpDn+E3Znz'
        '2!?s)Nqno620hGS&wOX}qYYg>je+M*7d8TGrLa0;A_`(7B_2K4RR0%kD%_GnI6W(O*$yQ}I%qm#Ph)4E7}AfYh83?$e=mCQU)L(B'
        'OI8UNynCISQS-Hxe8Nzj@R*u`YJL(6)%;xhqhs_zdG-B;(HEg6o;OdE0WD9DsDIIb`d6Rv^v670H!5rHR|-#e)6+(faaI-mpU55-'
        'Znyv2BlVvi9&RvquYf!dzviV48chsmk2cx%U^Z;{OH7+tEp!cGDWvBy_n>BAIR`<1fg~KQE&+r=kT?g*zi{<UV?b)ip|KPP?s$q4'
        'JV6x#WAN3meOm`FpiUpPC%BUgud-J_>Ry+tR|wZ*47v0V8Z>t^EX8aW#8HqG1WFQoV7U#oxt`66sV~@QC#t|Hqep`nBXPjQq-L2B'
        'BCv<%sc}dT5-it9?f`yd-h%(|BKH^3d0DRZ_}<u~^5|MkDq-|Z#&NCMBfX(I`7OO(=RJY{wqcq=DKJ{04gEQtEyd69{o-SNTp^gh'
        '5!mlMzF+Twd{S1i|B>8+l!msi?b7gMyP`PP9!=Edc$>I8sWXXfvz7jyx0^^SyjoEKWij|n>K#AZXtBOcgF635W;92gTT;}`lc_uz'
        'dJGo{dkhSa{15`sADsOg*Vw+0|B}w%5n<9!2TdAqCcR{eP@WQk_N}X!tccn~2_s#`JQXYnLN9$eHK>vD%EVvFJUNK5*vy#zGmeLn'
        '4!WXu)T%ory1u@|fkG|GxuE#1GWuyywXT0_WKY5&qno`6eHB!1RRiN|^!SkkUu9#t1uj*f;8+DW3+b|4V6ri28!c4UwjzoXC*{E5'
        '4$J(sYH~0cQh>Rc`9$k(*m)^!3!s+=yU(uz+=@9$2()w$a;$1Yz41$jdiUn2d?d@ELLJWFRFZ>dg0x6xLf!(-g#7JsGsbuq6d((!'
        'nR6%9wZ6~&&25gr-_qN#*>3!{^$EE>O=QPl!*(`q0k(MT7UWEl6%k3^!K&DWIc|#J9Bj37#<}aaaXkM|+&J#!F&pP=x#J6*>{1zr'
        'fJm8%M`40VpN1mQSu@myODr2a4Jw#pvKpd~irlAP<JSH3+A=Ezj~=>Cp=)6_TuMumD47v`o(&LZh6g?Hp}WsvKi^amWk>jbW*<r4'
        '8NqIn5!Mn1d~B4TgJlk66t#JiHdpcnH4!VVC9s22NZ*vMI22IdZyg!}8L{nIN2fzigU?38F?DKBh#q3<%Jr%S>>&FVE8DPx*cAxG'
        '8s_mNmMxq=B&2)s6sT8QN9<>(A|j}3Xc6assnP-S?BU$e+7J$B^8q3lcE8beU$}Jz`3}E;*0`JbEZY2*E+j3Yb-_5$r50&Mw{)4J'
        'CMU#fUUaL)J+o>Xs0_t;+;P(yw}b3{+<CJo{r~CfKf7wyQBz|%YEe|7pj}st+*j<C&2_W%sf_j_SG>rIDU3RZ*Q=Y|Kg3<vgQ_!S'
        '4nQsszuo`i*BeZx%^FcaQ>7QJo*s3zEV5NPOINA59I%fpYl#&33y3fM8360%zbRwep!DkG)mdu`yOz@4T<l`g&H|=sI=IneteL$f'
        'mK)c4>z(Sn=Qc0_ckXq^o8JfUhLrPUp5R1vhA|785b3Vik>*{1eEU&<J6gSwu!`T1%xdH5eAJoH<;1!JjryrPc6{E5gs`~^?^jAA'
        'N_~uWHogY4*|`4|>+-z+PHO$F&QUj;>>MC<ZaBw*#K^=!WhM2!Sw~=IyZV>vW4pKp2BnXLg)H_iWSdl1+Y>Mc?)Cb*hDPhvCYrS!'
        'H40+)CsCp8aJiEjKGErV99`VRQ+C+VT#ixpjPlBJwshV-rfFe!%}*t}L6Y110(=C~6}V~iw}nQGZX1{aDR(o2&AHRk;)Fe3^)Tjd'
        '`f{@0*DFW@Wv~&le!uz3pZ}CU=!~Df%alyjZ6<S7QrOOC{4m_aC?+H17uM{1Q;w<NY~gw#WPogRWuATXY+VCRN;Bwg$-X;VYa(HW'
        '&X~0ZJBGTy`R=E;Cod0Alb45YkCUV0Hy7V+##>(4=FRznqACCacsbVV1#82#!N0t@sk7A!y87Y8O_kMmddYcNIGISHE7Tw~+Cef-'
        '*vi4s_InAMqp#99BqI%N)fHk)pEC`OxAV}W4A4ka8CH6DOhO~(2R}VTg@pL66y0BL^pLQ_f!y2(oe})DTX-v}0wUSb59f#9o}8Xs'
        '^iHVYqXt`MQ^4y9kcC=}@yDh_VfcN(_C=w4dpdHDZoW+`Xz6v`m0&L&^Ow5fY}}C>rpGe)SbiBj?;@-mK)v|@KaSRP(jA%Emb9mX'
        '4n1ZqnC3w4Zw=*;B`}<o0xnrWFvCJfWgDUYPC!!A-Y}FZxk|HZUJA^EHH#1h?>3c(Ji6fS+1&7idQab^E3K#zAT6fRy>~};%wZ>s'
        '-4_@X2;|S(^XVx}Hl|7IRu7wdz6F2%I37Fb71M=z!%u?`ZlLL1?dZZbOg3aG?m4@So8z-hG64FqA5XI<pJ88m?M-hG<sM(Yz}y-?'
        'K4Yo}y^bmgE7FNc`Sktbvu|xd5}nH`bnh{}*dO-l_>;iWIYMVT9<S+;dhVbXL3Q>v=I2)UiLxZvI{Z(^xlWzmCy>p5!($r0LTxBN'
        '&57?}@Zan)*rRdRx-e^%y*48l0P&}%)m`JhlCAowDGc0tQYYL#Zp9t}m4Vq`D7Bg8uuQs9a~viK?VV@Eif7;5OPW3jsbDri=My3G'
        '$x!h_WCJvslwX)1&Q@jYDOHA1rQ0Qc+C5C#2c0CH%rckH4?NC&PwKDdi5zVkq&3i0t{RmDM4gtjTU+)CUVS><$RpkQ9_7;4;m$`q'
        'jOxq?eA^FKp>zZ0CgIF8-Np+QMoKwS0Qk0=azhwSk0=Mrmq`QuDI+I>1X~xYT$?d@-fN+cBUabsy`EU!59G9(dHkrFVv-lj^{S@S'
        'AjSa9%vS0Bs3A#{D3R-!Z$VBcB4s3n{Y8z+`SE}LaQyZn`Sz!a<F{^Js-`!y7%Fz4-=LoBF0Jq8`SrNIOTYTv*8`ZyaD112nB}+d'
        'sZotyHRkVHsf#%6vYFXK8hA9Jl9q0kkrN4y=#D~ulDkr4dy77O`8b=DOw#%?p5D*mt6?*00uPc<nocX_$Nj8J#T%Z4lR~VW8+6<3'
        'pGrw&^*f#uWp81E9T{vUJ?kC0|NGx}!9`72xkBmGk{ClvZc*0{>^!&z+GZ>Rk7X16z(|K@(%vu0mBgqQUyXAZt#*?|^*cy<EIdDN'
        '&we<6dF&pat|KHfX_BN}svfTbCg~pMi~qJ!fCutyJVK1grk<UGS0WMA&FuV;+JL539QGxSb!G8d-s{GgI=Am<6uFTIYu{=-De3&{'
        ';g!_s4NL6<(GRHcJv9R4^pFDAJu?l29+g(cgw%$-0$XN>cw}Y>4m4KP7^LjxfQi5oX@E;ExPj}rOHVIjXu<kc!8m-X@kd_ow3jTc'
        'uk%Vd{rcO>2liQz3ALBl+^|$!-MLx6h|V*Wk5$UtOa3Wf@Nctfm-08&Q{XP^adZq!03si-@Hv`w*GsJG3JjCcA8{6{b`}m<vqAb9'
        'b1l!J9J35^$~DYTl2PKuIY<MU&_ScKs=OZqc%$sYs!C-_RG_rxgt{~ILzD{dz&T~e$5LE2<zyw6qOq7ta{%jliG|U}3=vNmP{0_F'
        'Tfzb>;{f+}8DnZZRhR_`@2yJlXgr7A8=5=@cJI$oN*95dxtu30Giqb5uy_2KvDv!hZjs$5#!MtRGJkI&!pjsBkco(ACHk{4f{GX;'
        'XwW5J^S8K@=t9wSM>iS85vvqdaI6+s=^1MnQ!Z*%9GQ-fg?vuQZ3dggA-V^WlPSAQ1k%C^4amdcD0~@fS8KeM@$rL0eHA_^IJfp('
        'CE{qM!Qz&1I|DgeOBvr-GHTD_NcT-x6U(d;L*(-pfe&h|mcXdz<r=k$YUp;SSD_-xs<mC=!g|FM<&3KIS-q;fn4Epc>lI~8a2YkK'
        'Z9#kC2vcI%C1zBOcgbU21+z}5WF+>+n^{R5l-Q7-MAi2-?u~*k!OaaFD8ZGOqo4gKvY*54ILqQt+7I<_U@^a!syEF1Yro*`t^#>I'
        'JV=kEcb+aW#+C9yQMAY^mCQR>iOSd*s+|kc<!n7CI>ZUpit=942cZATs#>q^@T_ZJ1Uy7)Jog;yiqC+;%ZKqS%a-_uy<V&Sc$2XZ'
        'FCzC2i{tp)9HVvBXOwQ+tRI{$%jw+<+y&AaU|x6H%U{>p!3{2saXZ_1Fk@mU-(fQc&U`3hLuD72xG$@B9r+mh*Xb2<IiVhRJVd~s'
        'V6|UnRZ==iPr<8DmV$Lt@lONQ@u%)K(a9X`gRB>zn>mwh8oF2BhNU%N)k|wl+%w9AR}q}Wgx?tGNs2cICEYrElDon#->$N4HVI1&'
        '^zs!ewGvp$Iyv31PL^m_+|vw=7lS<o$^#!y!WDh(r8uEcEp_b|(HnIJ?Nq{R(vhJ^Wb(8HX5MXzzQ1t#LQYaS(Gj~*qrXyf1nJmw'
        '89h~!5V#>|HukJKz+Gr>v=(fL6b(OHPGe4rd5wxlU<x_@rYVT7*GSWd4qqQdOBi>Tf8M0|d|kPjopmjULy|v%n)BDho=?m5d=_0Z'
        '(c(i1=M3&Z%5#LpCY;`^{Ua)1<WpU8Ms|)rV{R_GPitL+#MuDFk7L?$5Oop<6xJE?MBf4Ls%rYYJ^C~1fPtW6j1p&wczgK$u@7{F'
        '9&Vxd*I7<iBI6Umr+}N?tc8OmjcZjYUOQ=W)yDBBAP#*<Xz1}q<kFD3lr{buugV0Ov_Z)BKwn+P^R&pA^E?;qJB26X9}iDYjt(zQ'
        '&R#S7+L5YJI$}XoOSgu2yt%C?wCPtuJs3{Ht&GQ{hi9}2*Lq`6unamdE=yYrJL#dB_4v+I35nU0ZV|k@AI&x)Azg`wIC|I#wfDRp'
        '_U>|7&hzPmwa7$UJ_4U@=v;`F+M|iWAH8QA+Kb+VF?<4iZe7k(oQ`^NTb1i&f`QVpRYVAc`{}znL9+qyVQB}G9rjYYI6r*(=i{T~'
        '?aQ+_$D6>&>bH9G3u^8T$m@{{95k9kOM0-=E{cNfqd(fdZ}Wpdz6+2v7Vl7IMQzuFG+kW@+FSZe)<$Y&maV)D`&A@2^+Pc=jM4s2'
        'MeSH+c%U2gqiEY|A1!h_4wVXNaV<{%c3&kLC9U<UTeC&wD@j8i2=(Ti?VK4O^K$!^{iJMwQEGvi8d%kGEm_ooPns%=I;Jdw`;;_f'
        'Adop-;T5{a*P|4INVx_?UWIv!yOaw&)U9jV;#oU*MDZE=7Rbo4sw3y}g)c=8qwW;zK({yC=<O+CEHbJf$I;16l)8)#YO<;(2SXao'
        'sp6xn&;nXBqH0uJqv<YPIUQ*o2Kuiov)Qf=heAH-g|5PkT&3_09;QOLu|%1p9_lebgnka%QE>*Zvqd1Bm(!5hhB*#<CldrIFkjEi'
        '2?xXGtlh-83>ht0YNOCn3iF3EV;e{#OuB_kwwPlS0)1IR#Inj4m<m#6txy^mKs;r0Ob<pnjd53%3xQOIu55_PsPdAB$d@8XO%mI#'
        'p5{g}46i-im5uED8Ag#i7A7_Oiw+&os1Y%lDQv4fe$1-;=7G_dRo-G^W-(^OoXkkdyCGoAx(7jhhas(o^x>_ShKlo7ri!zV3>z8R'
        'R5ger$?{O|X}!XYQDM54BpMLop0)_aQy0H*$M%@+KJ6w6RMptka8Z>i`d8KPYrR@EHDW(tyRgDnnxk#;XtE{Z3AxK)9oJd9a!-j@'
        'sOl$7J%JEq2tbD9;~0W2V~6qfS_l0ym?@qtTiML}$Y0?m)8#s;=Wxi3q4cwGGxkVH7S~2I{j6g&_WM;Lggb8gZMZ9yf<3uiu6dy<'
        '@VPB%vXH556K!czk!jIUG>B%X0JGwKUX=x^O2oc~dK*t&(R1!hb0+Zr#0S?e6w?Cy25@ks@nPN9Jio5+dOP}dZ<<c=zC#JYB;8&V'
        'XNwe-J_n=*QC;SU$MISSQsc6ZPu#X+k*qJie{*zl-pH-C>qER+EU8`_e75PE0RM4u{OG2CJ^EAf^6=$%$H{kR-ya7%A;8fr-~4p('
        '-P!A-v)31YIX}5LMz5BaXGh1A__=NJSX}3*_tIH#M1feMhbExeZ907*LPdpTklRr11|oKhU0^QD<v<7bDWA0C*FTPE7lyq)fBW5`'
        'uSsY1Nx$sFqg?tXbR|)MEqA(MuO4KMSCQ8x&OKG!i{+z$HYGF>;g-!zm4HjxyA=qHWXL|UMj=jqY<?Sr6Hjx;b+<J-Zr<rs&9)N>'
        'eI-sG?%kr=xQvxNH#|wqUOa?PH!z$>q)9+k6)O-&4Iq$yqSBO_C{m~_{N(g)XM6f0`g4{o3H@)gVvYATZ3O1*7w5J$kkvWqu2r5v'
        'sku(Mt4bp?>lYe=Z%&T(cnV5Ly{$6N#ZO}?op@IL8dd(t;I~ti10%eM^5qR61)N`ydFy2PFrJsU`E-1Za|D)VEPE8?i)C4@qU1C$'
        ')*p^EJT7=KhB<>5=cLPP31!W9fgUZS7>OY@xy$Q-E0(Zt+!!c1R`tPBan!rHfkvslT2&%(t?a5B5Vufq?TDa)0u$pi<Wbmi?Z;({'
        'SDJa;qL7^MtIK_Mlk3LKt?)Bgk3xeBWjb<}Wdt-Xe?R0%k_72HilZ;>UP5(z`keSDKJ|}3`P-d-R>XJ?e@G2L0E16imTo!3sI$?j'
        'mJ8?mk=<Y~@@;ez@V#$FR>ykQSPUwG>1Bg>me<p?BF_kgKnBQ|m;t72rLX={=@;~*8XW_?j2ZJN6yNyd^58f7`wl|cN(fT2tP7Ho'
        'b4<|3q*mt>Ycz(ar)Hhl47w=x>iib<7g!O~k*CdTQWJ&d!e%_;t58^9Vb$~5CMnERIbdyg!|)x&^1zg)nFZq!qXl`LmDRi0-=THu'
        'V_EpZV*3^4CyNADn6Y#a9?EGb*pw84(*42alq%~Qo!=U-Lzdg=siO)vU^i)?xYGy087e4%gs?n#rj#feX1w~Jv#!Ihsg^TU^RP81'
        '3rjl|+%4<1bt|Rl+xFDyb7xO7bo89Be5bE{0vnC}JY5%4R0zKV7O9pxlZcYn*<CIgN>aW6`dz10l~XktV3wS|kVoP|2<wW9`5Ay<'
        'O()>E%YBgnz^|_Fzt5YD9KymAA~QkwpKvk&$Hk``$wQkjce!{&3)-A4Rsq9JW*PMiF@dM0J||wV?b)nM3gqL-S-#LoqRt77;+w#_'
        'oIRy*+Pg>N(X6~xo^CI8EPs<(nbnf==6(52DWJ7+hDcoF;ELV>Xd7_cSwoCNhrfA$o?$zmb07P#mB~By5LIO*xz6S#))}JOtKw;h'
        'y_#O>63C}ukkuYF_glWlERPc*-1D_6V}y3F^=h}g+2vOT&W)QeQ>yAjg`GrSO0}jjq^)`|dB72Y8O~CX&B@aiM!+*Sj^5stMzset'
        '8_wY1>PjRqYPv*jVU}hK=E4c_R6=e#uh|FSrlx>Sgy;=ouz$T?kLfW>7@w(pzZ}lTwTh$W^0r)?OchbD+siEYZ67WB;4^#`^0H0e'
        'xXuz!GKFqgJ(%$FmzV&ARJqHS0IqlbRn;|oOMizQ0Ae!rYJ5`-F5TxH-VQMgBr*BAb@S-zV?Y{gaa6tnmVTXuhi&fW>rKXqIzyXj'
        'Q8vhB%06-^!>qcWO_yTL6Jwt&g1z0o_;zN0WW&0<{I3oQZk!>Y%_T<4pdq8Y5u{;Tzw=F3$2Kp3=oo+O5&PaPX)_-M-;DTw5K2_;'
        '#?5G`T-@Nq`)D9q|Hsi8+5lb3k<(>$@9C`}N9juXAwN<KsCj`Nbnv#h>`)3(Rp`h55)&BXHK03U6eUCSd;!j8o()_zf;hhfjL}9='
        'qJ1^C7-0iXO){y@OY7c3t0b~@^mAx`Lhe@*oAJNnM<$>)CUPlg&v){#EPbI|#Rna^sQ_duB>xxs`hdYJOF1ys(Km&UGXHRI23ycP'
        'zUtqXMS-0jjg|NA&^+NyPbNVfc7uzK&X*H^<NpS-6}V79vcTm0H0ACLCEfQ6^rM&k7=oy^rC|rs_6bj%@Y53Q#`<`R?ouD`ZhE?b'
        '8cW|o9N%RRlX<$ho~0NLc!2*=%C+r?wx!DZ=wW^4DVjPI=VK@Y-AEP2ppfE`-(I>CZ~``a=pI8I1=1Mf#|>jmik*bl+_s~PP$t1}'
        'aW?Kxely;;dF~@@-dreRIJJx>O}ynC6W6jVgcvF}ip6#t*Orc*Z5VgVbz85i_xbx0-Lx!-u#x~MyYB7H$<Z#QCdJf6n2)8(fCUz-'
        '{$jn7=z)r4uO@a$kGr;9*(@)Z8&vYap)Ii*^!sdJL5T{8=v`A%4t)YV=-2zh&%<x`HFP-^tq{*f*wV86Q<&E(pT2u&1D_>mE@+&+'
        'C(Q!~WRPe_xt(C|o$i#gmxm`AM<**WbW4Xd)m7#V^f+q)?NQiK`}pWFA-la<PUaEoG_#GkC3%JpbThUJ;4!-ECpVZUU(RIY!6g<J'
        'Yr}Uf_8xX)e9L%BN{41HiTEwLGWC|wXdtoGy5p7%A`ENg0RhJ`F;b-1vt?%_u^rC&0?5ZdvZ~xwss^Px!y4gf!K8?k=CzbH7UiVT'
        'm$GMODT>T{lINZ*jTGUIHSU49;SjeKsWUk2L)1v<qiFO7>@({23b?F9`$G|sY4z|zXt^4x2|}Xe-Z;H`prPgcc;{d2`P}XC?DbOg'
        'BAj9$9PA>azM=4La~W!#n^XbR(`D?rl95~Yg^vdB@Zn>C?46Cj8BOSy*2#bN%sWYM7an#dw%sR?H|i735>F)_3f%)qd8S~I%~T)m'
        'B=nb_?&wo}mIPHo9r0W5T6hFjCns9916Y!fVLqL6Uwq&k*U^t2Z^^AOU$!vRaH~xWb@GJUsE1IM;@i6zEGqxmwvlVzqbK1_q6^<s'
        'P&bx(fbQ7YuHEqduAHmQRp^E`Wp9g*pX}ar8N1Ob8@4${R&kNSe6&~7tCPQ8{BV8@a^ZK!-yc5R#-i`C2E4njOMZRjJJ;yF$r-p0'
        'NS1VZp!ys>1T<?9cw0)!_F)KZtQ_EcZ?zZT!<mm>pReW;u`En1nmij(;*g1WZQ5x>JzkY({9at((_6T<Z_)XP#O1y7w{Q0}m-2#p'
        'Mi(1YcA*S{w?E;e#~+^Th1h~pU0j#t9Ap4WYNE1urSufIw|4HfR`yeMZzIxTC#o-tPa=;eVHGeOB9&#CJR5e{a*n6Z%qtJw)^9Us'
        '9%x!;hjHRo++JK8y(y#k1}K+K|Bs%P?~)(xIH84E-G^UQ1`7S|(opDJJz>%(Ukaubh%t){%}MJbeGeQUT5U~#V$$+Tt|wcmW6am5'
        'zv4+?`)^#g>gZYYeE+N8%K!MLMaDj2!r?qbbliN-^*n|#k(LhYo3Kar$iwn0Mm;#<mT1B$bM-Z4W&2a5JSLJmg{@M}$E^&5-W<h&'
        '(rGHrv`^11n&q4kpJ>Hc2x3H56-deNu#}Z#wUj^sCx?;xmXa@#Z-6u+Q3|f<^>SG{nMYKzLz%ZH#kAUA$=ak+Ok3d|n!>8oPQl&v'
        '=voJ|hbk`-U}o~UB89nrMSDEdu5At&)~S=Uaykq*u39cgX?z*X@>S79_!ODyUexLKR6xgK6o#dtdK062@IQm0Tr3G^t77sUX3U5^'
        '0GW77xgL-smjut~m6NayJo)>&T&2KmCTVq@uP`DZSydS_Bic3|f81KYQyR{Ygr^CQ*)uNfAf&1x(u5X$N@k{`)QqqVZy1Oew<t-)'
        '98O|O?ZWdEfYRxw32t`k@^{qUo+~%lcuT^FS`X9_|9jr<*V*bGr3TYMxgBKV>af!(ajXqhY%=`<mk6{Dj>@xV@9yz0)29f1vZ5dL'
        '?y86_DpW8qDVe66k`Tc170L@;LR|=fl}<5xj~dOX<kRFi5pUbd14LXTzmkk;gqZYX)KtYXNxSqNaiX;yUxqa9(0%30^QkKMjq@7C'
        '!*ae}0g*7SvnJQso|Amua7qX!M00K>HFcv3Jz1@}^0x-0v-Q}a0bKERb8c7`4KSU6EdYF%)_2Hm&2x-7Rb?7vNR(J=6|2p;+tJz}'
        'btbW1+z0ahC)~1R0BYGJNzL&GT0A(K7Y+6F|2A~4jFnBZobsIcVv^?NEnc^KCh&G?+4&r8bN^KX4Qvbwl$B8iw~1e~FP`1!1{6*-'
        '>`wP;tWsH@12oJn&Sx-GUFG@um*!K!1jT@MU?_G|Go8CUlJyOvZyr%p&$7m8z(20Ko_R1ibUmDDL-GLdXOviXi#jZBQ79`lZrH0p'
        'A%g5|cX^c_g|_t^&X51(q~}G_rk)gZ#wOjR!psJq^xFo7Y-LA<OFh3yr>i&!ER`No4&x)8JDP;{R<Q+ic7b1K$@$UQ>(ig2fAX)_'
        'XRppqPtX3+{C@rI>DkLa55uV&u$;<_dNot;$JKRAhYGHYEM0WeA6B`snu49wVvGl<C<h%S`y`Ds_n;FwH$U^Dq>!CpqUViHD6wb5'
        '`V;|eC=+EopSWql!!4LvPVd%$d<PSO9u<fl7-I5<+FCrUih`xiItv)my|key8}1H#)qi(d<#u|tZ0#x51u{2vfpS7p)aJ9PJlm9('
        ')G9V))E;X3)Q@zR8&1EOV;pf!>fm@0$0<d_wzUBE(Dh;XQl;8`s#V?6VcL6nR>ewYa{(P|b+90jk<7kV$CB&S?3s?8<a#}@&*w+W'
        'xaGk^ym~G6O_%d9@6?0Mshd0;fpXwypB-VD{60I9$X9cDxOoZl{EDgPUvB9;V9H+MOpr)VF)~EH+tbWulP^enz_J$bj;JSD!5x1T'
        'QBCA*DOT|szebfX@q^;g0`sDrYNDDQ2_u;nhT^G7JWiQ#_fE5vv+dUGi!x>dwhD@EI1F9n=ezZ_5m|@hzrb*VMXJ))-#qB%7|=>F'
        'u*h3aQw-7N%DK9hg5SAiV-S}1I`-=~Wv5hhRK#m!U`zUL>Y=6F3;QJut#FM}6495-)h_1RrsP06yvQ)|kE2&U)4G{Bo{j7|fYC}w'
        '&khD_<sYDZl7J>)x@*>zB4az=&i?f2=6J`5(lW&BOfZH_<cc06S%<^kcLv&dHrUK4%ip&}P)Rsw$-s0;(O>2<9{S4oB<->z8%y?R'
        'U7}eP$9T&zd!lP3OWvqupc`Rg@@%?BT_Yc8{s?Ip_KClg@q9*Kn=7mh6_+8}i#wo|G#v|3sprIg^6Ylpt4}F}WX7Cf=J@Rorx#*$'
        '47PAqb`_{X6m0Lpq16FQN@$<{q}7?R{!0^#S3^$ozH+AAd_ZM9f|G0ZfbzE>KKpRBaZwkdZKuBznr%ics|#b&z`@?(E8h;QZ)jEX'
        'yyj)?gV;$9z54AplgL;2seq$K8PWCq<x`k=qE1!A#F)2D7Vv6khnu|V%BC;Y0s}|aQ6@FZw;TUzB8S+s6=JizW{nx;BvXwY_N=|C'
        'e@^UKvRFJ+998rm2C67!uhR#fRf4exwC;@*h-xI}rSUIpsi24(a%k&QDtVUa!@Nu_3U(mYi(PN~z4y;OG_I!;g1F=uB}$r>=F?zH'
        'Md3e*rB)s3xo@Zig{BSMCis$hO>d{#w}?$Y^d&R1Xe~irQA}#^Q%p_DRbE(=*xxZ`I$N1;F7QYjL>e=PWfqZ7o2w%u5{UaeKm-`i'
        '){7<Hf3*7}Vx<${pz8^fy&7|^rdV@tGKfdG;Rje#A|;(skrtvZ!tmw474dM)-M4wX^<qGLxU%$7Ws~wA35TU;lj#iurof$ES~PVo'
        'SZ`K)Y=$)d)IObFJ&SZDs+PZ;o2r(V=f{T^>c{b4U!J-;m{GJ}e!cIyW(U+Q_Z{jM5xl8nkp_|Pi<|kn73;NG@NbD)vg)y0zSCmk'
        'kW$#k0S^>444x=8ck@(z>_s1SDM`~APSDm6>xALX8kM~g-fKlv1!Y}BN$We~?$<H1S`%PkTMAM|6-wREQP!y|jipto$CnmLOq?z6'
        '*6rmivjl|Z&qHyZ=7DpHZE@PWMi|p6ex+Ao@E;|hnG5K=8jV7LH0q^bXs3U;-g&Lxk;F4C{mxTfxJg(V(L|>ukf8SP>sCF>o)tnh'
        'Oq^4CwIx{%)z$n=HgMOa+dAT=-%I<X+w784%E9JkdqvIY)7&e8n>Ue7D}9jPGf@uzHe~FJ=&0m8uOF65o56_yeqBfRS&HG*DB1wP'
        '^@eiP3+8Z%t{;{_$;RH~7#ig5S+t%AF{Wjbq(fsE=2eyInU{vys8P(JzeW_CkztNBCz}TO7wmCR!!D^;010PiXafvG6)`IEe`7Dv'
        'i1iu&)<F)PdAIxevh+%_vzg9rPG!}ZX8XcTkVow8E{S6*LpE+csTMWz1v=A(|L`NM0TUJE<PFQAbiXRQ#aN>~Ca?~4Mxo|%21uCX'
        '+<=r2Lrr#${%fi(4Fz@8pPshcO{vANH|9bb#O>foJz_9G%fK3Stir)~;Uq#11!$`Ry_n|Ys@2Clc))EdfiH*oMxwnH@qRoJ-<p{7'
        'EO&O21Qta()i2|=OVD{E>Y`v3@EO8aI>9Mv<?u;6_o;qmY4GB!o&N`&L@_)'
        , 19087, 86554, '4df3f7f2c6d2952550dd78153b579f4e928e9f119e697bded8a7dc001021f8d2'),
}


def _sampled_v5_finite_pair_source_data(label):
    import base64
    import zlib

    encoded, compressed_size, size, expected = _SAMPLED_V5_FINITE_PAIR_SOURCE_DATA[label]
    compressed = base64.b85decode(encoded.encode('ascii'))
    assert len(compressed) == compressed_size
    decompressor = zlib.decompressobj()
    raw = decompressor.decompress(compressed, size + 1)
    assert decompressor.eof and not decompressor.unconsumed_tail and not decompressor.unused_data
    assert len(raw) == size and _sampled_sha(raw) == expected
    return raw


def _sampled_v5_rebind_unit_pair_data(case, producer_raw, sdk_sha):
    """Bind hypothetical unit DATA consistently; assert no execution history."""
    case['producer'] = producer_raw.decode('utf-8')
    request, row, terminal, parent = case['request'], case['row'], case['terminal'], case['parent']
    lifecycle, reservation = terminal['source_custody_lifecycle'], terminal['reservation']
    request['source_sha256'][lifecycle['producer']['path']] = _sampled_sha(producer_raw)
    sdk_path = str(Path(request['cwd']) /
        'ipfs_datasets_py/optimizers/logic_theorem_optimizer/validation_run_resources.py')
    if sdk_sha is None:
        request['source_sha256'].pop(sdk_path, None)
    else:
        request['source_sha256'][sdk_path] = sdk_sha
    request_sha = _sampled_sha(_sampled_wire(request))
    row['validation_request_sha256'] = request_sha
    terminal['request_sha256'] = lifecycle['request_sha256'] = request_sha
    lifecycle['producer']['sha256'] = _sampled_sha(producer_raw)
    terminal['failure']['request_sha256'] = request_sha
    reservation['record'] = _sampled_copy(row)
    reservation['ordinary_scratch_profile']['request_sha256'] = request_sha
    parent['request_sha256'] = request_sha
    parent['actual_original_owner_argv'][6] = request_sha
    parent['original_owner_custody']['original_terminal'] = _sampled_copy(terminal)
    ledger = json.loads(case['ledger'].read_bytes())
    ledger['reservations'][case['args']['reservation_id']] = row
    case['ledger'].write_text(json.dumps(ledger))
    _sampled_seal(case)


def _sampled_source_held_v5_finite_pair_fixture(setup, monkeypatch, pair):
    case = _sampled_source_held_v5_current_producer_fixture(setup, monkeypatch)
    if pair == '280-11e':
        producer_raw = _sampled_v5_public_280_source_data()
        sdk_raw = _sampled_v5_finite_pair_source_data('sdk11e')
    elif pair == '7ce-860':
        producer_raw = _sampled_v5_finite_pair_source_data('cli7ce')
        sdk_raw = _sampled_v5_finite_pair_source_data('sdk860')
    elif pair == '86c8-4df':
        producer_raw = _sampled_v5_finite_pair_source_data('cli86c8')
        sdk_raw = _sampled_v5_finite_pair_source_data('sdk4df')
    else:
        assert pair == '269-4df'
        producer_raw = _sampled_v5_finite_pair_source_data('cli269')
        sdk_raw = _sampled_v5_finite_pair_source_data('sdk4df')
    _sampled_v5_rebind_unit_pair_data(case, producer_raw, _sampled_sha(sdk_raw))
    return case


def test_sampled_source_held_v5_finite_pair_captured_protocol_ast():
    import ast

    old_cli = ast.parse(_sampled_v5_public_280_source_data())
    new_cli = ast.parse(_sampled_v5_finite_pair_source_data('cli269'))
    old_sdk = ast.parse(_sampled_v5_finite_pair_source_data('sdk11e'))
    new_sdk = ast.parse(_sampled_v5_finite_pair_source_data('sdk4df'))

    def functions(tree):
        return {node.name: ast.dump(node, include_attributes=False)
            for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}

    before, after = functions(old_cli), functions(new_cli)
    assert set(before) - set(after) == set()
    assert set(after) - set(before) == {
        '_report_validation_watchdog_shutdown', '_validation_watchdog_shutdown_observation'}
    assert {name for name in before if before[name] != after[name]} == {'main'}
    for name in ('_source_custody_witness', 'classify_owned_validation_source_custody'):
        assert before[name] == after[name]

    def methods(tree):
        return {node.name + '.' + child.name: ast.dump(child, include_attributes=False)
            for node in tree.body if isinstance(node, ast.ClassDef)
            for child in node.body if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))}

    before, after = methods(old_sdk), methods(new_sdk)
    assert set(before) <= set(after)
    assert {name for name in before if before[name] != after[name]} == {
        'ValidationResourceReservation.__init__', 'ValidationResourceReservation._physical_inventory',
        'ValidationResourceReservation._usage_inventory', 'ValidationResourceReservation.check_limits'}
    for name in ('_validate_request', 'seal_results', 'finalize', 'to_dict'):
        key = 'ValidationResourceReservation.' + name
        assert before[key] == after[key]
    assert _sampled_sha(_sampled_v5_public_280_source_data()) == recovery._REVIEWED_SAMPLED_V5_PRODUCER_SHA256
    assert _sampled_sha(_sampled_v5_finite_pair_source_data('sdk11e')) == recovery._REVIEWED_SAMPLED_V5_SDK_SHA256
    assert _sampled_sha(_sampled_v5_finite_pair_source_data('cli269')) == recovery._REVIEWED_SAMPLED_V5_COOPERATIVE_PRODUCER_SHA256
    assert _sampled_sha(_sampled_v5_finite_pair_source_data('sdk4df')) == recovery._REVIEWED_SAMPLED_V5_COOPERATIVE_SDK_SHA256


@pytest.mark.parametrize('pair', ['280-11e', '269-4df'])
def test_sampled_source_held_v5_finite_pairs_readiness_closeout_and_disposition(setup, monkeypatch, pair):
    case = _sampled_source_held_v5_finite_pair_fixture(setup, monkeypatch, pair)
    before = case['ledger'].read_bytes()
    previous_sha = case['args']['expected_record_sha256']
    readiness = _sampled_inspect(case)
    assert readiness['ready'] is True
    assert readiness['state_written'] is readiness['recovery_performed'] is readiness['admitted'] is False
    _sampled_assert_unchanged(case, before)
    receipt = _sampled_reconcile(case, 'administrative_closeout')
    after = case['ledger'].read_bytes()
    original, current = json.loads(before), json.loads(after)
    selected = current['reservations'][case['args']['reservation_id']]
    assert selected['status'] == 'released' and selected['artifacts_durable_asserted'] is True
    assert current['reservations'][case['prior_id']] == case['prior']
    assert set(current['reservations']) == set(original['reservations'])
    assert current['roots'] == original['roots'] and current['limit_bytes'] == original['limit_bytes']
    assert selected['explicit_reconciliation'] == receipt
    for name in ('native_release_performed', 'admitted', 'outputs_deleted', 'cap_changed',
            'new_reservation_created', 'new_resource_lease_acquired'):
        assert receipt[name] is False
    for proof in (readiness['proof'], receipt['sampled_custody_proof']):
        assert proof['producer_sha256'] == case['args']['expected_producer_sha256']
        assert proof['original_failure_profile'] == 'source-held-V5-retained-command-failure/v1'
        assert proof['original_command_returncode'] == proof['original_cli_returncode'] == 1
        assert proof['original_failure_preserved'] is True
        assert proof['cryptographic_execution_attestation'] is proof['reconstructed_Popen_handle'] is False
    disposition = recovery.inspect_validation_disposition(case['ledger'], roots=case['args']['roots'],
        reservation_id=case['args']['reservation_id'],
        expected_request_sha256=case['args']['expected_request_sha256'],
        attempt_directory=case['args']['attempt_directory'],
        expected_record_sha256=recovery._digest(selected),
        expected_previous_record_sha256=previous_sha, process_scope='sampled_birth_bound_descendants')
    assert disposition['storage_release_established'] is True
    assert disposition['native_release_established'] is False
    assert disposition['state_written'] is disposition['recovery_performed'] is disposition['admitted'] is False
    assert disposition['release_evidence']['test_or_task_acceptance_asserted'] is False
    assert disposition['release_evidence']['historical_capacity_is_admission_authority'] is False
    assert case['ledger'].read_bytes() == after
    assert case['scheduler_state'] == dict(leases={}, waiters={})
    assert recovery._durable_inventory(case['args']['attempt_directory']) == case['args']['expected_artifacts']


@pytest.mark.parametrize('pair', ['280-11e', '269-4df'])
@pytest.mark.parametrize('damage,error', [
    ('cross-sdk', 'original Source-held V5 producer/SDK pair differs'),
    ('missing-sdk', 'original Source-held V5 producer or source pins differ'),
    ('changed-sdk-bytes', 'original Source-held V5 producer/SDK pair differs'),
    ('changed-producer-bytes', 'original Source-held V5 producer or source pins differ'),
    ('request-profile', 'original sampled V5 request profile differs'),
    ('source-open', 'Popen-verified parent closeout'),
    ('scratch-exception', 'V5 closed ordinary scratch receipt'),
    ('zero-body', 'original V5 retained command failure differs'),
    ('watchdog-join', 'original V5 retained command failure differs'),
    ('inventory-over-4096', 'complete nonempty sampled recovery artifact inventory required'),
])
def test_sampled_source_held_v5_finite_pairs_refuse_resealed_mismatch_before_owner(
        setup, monkeypatch, pair, damage, error):
    case = _sampled_source_held_v5_finite_pair_fixture(setup, monkeypatch, pair)
    original_artifacts = _sampled_copy(case['args']['expected_artifacts'])
    raw = case['producer'].encode('utf-8')
    if damage in {'cross-sdk', 'missing-sdk', 'changed-sdk-bytes', 'changed-producer-bytes'}:
        sdk_raw = _sampled_v5_finite_pair_source_data('sdk11e' if pair == '280-11e' else 'sdk4df')
        sdk_sha = _sampled_sha(sdk_raw)
        if damage == 'cross-sdk':
            sdk_sha = _sampled_sha(_sampled_v5_finite_pair_source_data('sdk4df' if pair == '280-11e' else 'sdk11e'))
        elif damage == 'missing-sdk':
            sdk_sha = None
        elif damage == 'changed-sdk-bytes':
            sdk_sha = _sampled_sha(sdk_raw + b'\n# counterfactual UNIT DATA mutation\n')
        else:
            raw += b'\n# counterfactual UNIT DATA mutation\n'
        _sampled_v5_rebind_unit_pair_data(case, raw, sdk_sha)
    elif damage == 'request-profile':
        case['request']['ordinary_scratch_profile'] = {}
        sdk_raw = _sampled_v5_finite_pair_source_data('sdk11e' if pair == '280-11e' else 'sdk4df')
        _sampled_v5_rebind_unit_pair_data(case, raw, _sampled_sha(sdk_raw))
    elif damage == 'source-open':
        case['parent']['source_closed'] = False
    elif damage == 'scratch-exception':
        case['terminal']['reservation']['ordinary_scratch_profile']['live_exception_active'] = True
    elif damage in {'zero-body', 'watchdog-join'}:
        case['terminal']['failure'].update(returncode=0,
            error='validation command failed with returncode 0' if damage == 'zero-body'
            else 'validation watchdog did not finish cleanly')
    else:
        assert damage == 'inventory-over-4096'
        # Complete offered DATA is retained. The finite sampled parser refuses
        # the population before any inventory or current owner is opened.
        case['args']['expected_artifacts'] = [dict(path=f'logs/control-{i}.json', bytes=0,
            sha256=_sampled_sha(b'')) for i in range(4097)]
    case['parent']['original_owner_custody']['original_terminal'] = _sampled_copy(case['terminal'])
    _sampled_seal(case)
    before = case['ledger'].read_bytes()

    def forbidden(*args, **kwargs):
        raise AssertionError('unsupported finite V5 pair reached a current resource owner')

    monkeypatch.setattr(recovery.resources, 'DaemonResourceReservation', forbidden)
    with pytest.raises(recovery.resources.DaemonResourceError, match=error):
        _sampled_reconcile(case, 'administrative_closeout')
    assert case['scheduler_calls'] == []
    assert case['ledger'].read_bytes() == before
    assert json.loads(before)['reservations'][case['prior_id']] == case['prior']
    assert recovery._durable_inventory(case['args']['attempt_directory']) == original_artifacts
    if damage == 'inventory-over-4096':
        assert len(case['args']['expected_artifacts']) == 4097


# Explicit manual private-snapshot/canonical-owner UNIT_DATA controls.
# These authored frame forks reuse the existing bounded public source witnesses
# and scripted process/scheduler doubles. They supply no historical claim,
# actual Source/Popen/Native custody, semantic review, or execution attestation.
def _manual_snapshot_unit_case(setup, monkeypatch, pair='280-11e'):
    case = _sampled_source_held_v5_finite_pair_fixture(setup, monkeypatch, pair)
    assert recovery._REVIEWED_SAMPLED_V5_PRODUCER_SHA256 == '280bf5bcb4d1cdc42ba91d5e1d71d6c867fb6e575833957eca7fc79d5e3228a4'
    canonical = Path(case['request']['cwd'])
    snapshot = case['ledger'].parent / 'authored-private-snapshot' / 'ipfs_datasets'
    snapshot.mkdir(parents=True)
    sdk = canonical / 'ipfs_datasets_py/optimizers/logic_theorem_optimizer/validation_run_resources.py'
    case['manual_unit_roots'] = (canonical, snapshot)
    case['unit_data_provenance'] = 'authored-private-snapshot-frame-fork; no actual history'
    case['request']['cwd'] = str(snapshot)
    case['request']['source_sha256'][str(snapshot / 'scripts/ops/legal_ir/run_owned_validation.py')] = case['args']['expected_producer_sha256']
    case['request']['source_sha256'][str(snapshot / 'ipfs_datasets_py/optimizers/logic_theorem_optimizer/validation_run_resources.py')] = case['request']['source_sha256'][str(sdk)]
    _manual_snapshot_reseal_unit_data(case)
    return case


def _manual_snapshot_reseal_unit_data(case):
    """Reseal authored DATA consistently, never adapt inputs inside a product call."""
    request, row, terminal, parent = (case[name] for name in ('request', 'row', 'terminal', 'parent'))
    request_sha = _sampled_sha(_sampled_wire(request))
    row['validation_request_sha256'] = request_sha
    terminal['request_sha256'] = terminal['failure']['request_sha256'] = request_sha
    terminal['source_custody_lifecycle']['request_sha256'] = request_sha
    terminal['reservation']['record'] = _sampled_copy(row)
    terminal['reservation']['ordinary_scratch_profile']['request_sha256'] = request_sha
    parent['request_sha256'] = request_sha
    parent['actual_original_owner_argv'][6] = request_sha
    parent['original_owner_custody']['original_terminal'] = _sampled_copy(terminal)
    data = json.loads(case['ledger'].read_bytes())
    data['reservations'][case['args']['reservation_id']] = row
    case['ledger'].write_text(json.dumps(data))
    _sampled_seal(case)


def _manual_snapshot_call(case, operation='inspect', **overrides):
    function = (recovery.inspect_manual_private_snapshot_validation_recovery_v1 if operation == 'inspect'
        else recovery.reconcile_manual_private_snapshot_validation_reservation_v1)
    if operation == 'reconcile' and 'capacity_policy' not in overrides:
        overrides['capacity_policy'] = 'administrative_closeout'
    native = recovery.resources.native_deadlines
    original = native.resource_operation_deadline()
    if original is not None and original.cleanup_only:
        return function(case['ledger'], **case['args'], **overrides)
    cutoff = (recovery.resources.time.monotonic() + 240 if original is None else
        min(original.work_deadline_monotonic, original.native_deadline_monotonic))
    with native.resource_cleanup_deadline(native_deadline_monotonic=cutoff):
        return function(case['ledger'], **case['args'], **overrides)


def _manual_snapshot_pure_parent(case):
    return recovery._sampled_manual_private_snapshot_v5_parent(case['parent'], case['request'],
        case['terminal'], case['terminal']['source_custody_lifecycle']['producer'],
        case['args']['expected_request_sha256'], case['ledger'])


@pytest.mark.parametrize('pair', ['280-11e', '269-4df'])
def test_manual_snapshot_explicit_readiness_and_closeout_preserve_unmodified_unit_frames(setup, monkeypatch, pair):
    case = _manual_snapshot_unit_case(setup, monkeypatch, pair)
    before = case['ledger'].read_bytes()
    raw_frames = tuple(_sampled_wire(case[name]) for name in ('request', 'terminal', 'parent'))
    _manual_snapshot_pure_parent(case)
    ready = _manual_snapshot_call(case)
    assert ready['ready'] is True and ready['capacity_not_assessed'] is True
    assert ready['state_written'] is ready['recovery_performed'] is ready['admitted'] is False
    _sampled_assert_unchanged(case, before)
    receipt = _manual_snapshot_call(case, 'reconcile')
    after = case['ledger'].read_bytes()
    prior, current = json.loads(before), json.loads(after)
    selected = current['reservations'][case['args']['reservation_id']]
    assert selected['status'] == 'released' and selected['artifacts_durable_asserted'] is True
    assert current['reservations'][case['prior_id']] == case['prior']
    assert set(current['reservations']) == set(prior['reservations'])
    assert current['roots'] == prior['roots'] and current['limit_bytes'] == prior['limit_bytes']
    assert selected['explicit_reconciliation'] == receipt
    assert receipt['capacity_policy'] == 'administrative_closeout'
    assert receipt['actual_postwrite_census_required'] is receipt['final_accounting_is_prewrite_projection'] is True
    for name in ('native_release_performed', 'admitted', 'outputs_deleted', 'cap_changed',
            'new_reservation_created', 'new_resource_lease_acquired'):
        assert receipt[name] is False
    canonical, snapshot = case['manual_unit_roots']
    for proof in (ready['proof'], receipt['sampled_custody_proof']):
        assert proof['original_failure_profile'] == 'manual-private-snapshot-source-held-V5-retained-command-failure/v1'
        assert proof['manual_private_snapshot_optin'] is True
        assert proof['canonical_source_owner_root'] == str(canonical)
        assert proof['original_working_directory'] == str(snapshot)
        assert proof['original_command_returncode'] == proof['original_cli_returncode'] == 1
        assert proof['original_failure_preserved'] is True
        assert proof['cryptographic_execution_attestation'] is proof['reconstructed_Popen_handle'] is False
    assert tuple(_sampled_wire(case[name]) for name in ('request', 'terminal', 'parent')) == raw_frames
    assert case['scheduler_state'] == dict(leases={}, waiters={})
    assert recovery._durable_inventory(case['args']['attempt_directory']) == case['args']['expected_artifacts']
    assert case['ledger'].read_bytes() == after


@pytest.mark.parametrize('pair', ['280-11e', '269-4df'])
@pytest.mark.parametrize('operation', ['inspect', 'reconcile'])
def test_manual_snapshot_does_not_expand_existing_default_entrypoints(setup, monkeypatch, pair, operation):
    case = _manual_snapshot_unit_case(setup, monkeypatch, pair)
    _manual_snapshot_pure_parent(case)
    before = case['ledger'].read_bytes()
    with pytest.raises(recovery.resources.DaemonResourceError, match='original Source-held V5 producer or source pins differ'):
        _sampled_inspect(case) if operation == 'inspect' else _sampled_reconcile(case, 'administrative_closeout')
    assert case['scheduler_calls'] == []
    _sampled_assert_unchanged(case, before)


@pytest.mark.parametrize('operation', ['inspect', 'reconcile'])
def test_manual_snapshot_requires_a_distinct_private_working_directory(setup, monkeypatch, operation):
    case = _sampled_source_held_v5_finite_pair_fixture(setup, monkeypatch, '280-11e')
    before = case['ledger'].read_bytes()
    def forbidden(*args, **kwargs):
        raise AssertionError('canonical cwd incorrectly reached manual live owner')
    monkeypatch.setattr(recovery, '_sampled_open_scheduler', forbidden)
    with pytest.raises(recovery.resources.DaemonResourceError):
        _manual_snapshot_call(case, operation)
    assert case['scheduler_calls'] == []
    _sampled_assert_unchanged(case, before)


@pytest.mark.parametrize('operation', ['inspect', 'reconcile'])
@pytest.mark.parametrize('damage', ['canonical-cli-missing', 'private-cli-missing', 'canonical-cli-changed',
    'private-cli-changed', 'canonical-sdk-missing', 'private-sdk-missing', 'canonical-sdk-changed',
    'private-sdk-changed', 'cross-sdk-pair', 'cwd-relative', 'cwd-dotdot', 'cwd-canonical',
    'cwd-accelerate', 'cwd-canonical-descendant', 'producer-relative', 'producer-dotdot'])
def test_manual_snapshot_refuses_resealed_root_or_dual_source_pin_mutation_before_owner(setup, monkeypatch, operation, damage):
    case = _manual_snapshot_unit_case(setup, monkeypatch)
    _manual_snapshot_pure_parent(case)
    canonical, snapshot = case['manual_unit_roots']
    cli = 'scripts/ops/legal_ir/run_owned_validation.py'
    sdk = 'ipfs_datasets_py/optimizers/logic_theorem_optimizer/validation_run_resources.py'
    pins = case['request']['source_sha256']
    if damage.startswith(('canonical-cli', 'private-cli', 'canonical-sdk', 'private-sdk')):
        side, kind, fault = damage.split('-')
        path = str((canonical if side == 'canonical' else snapshot) / (cli if kind == 'cli' else sdk))
        if fault == 'missing': pins.pop(path)
        else: pins[path] = 'f' * 64
    elif damage == 'cross-sdk-pair':
        wrong = _sampled_sha(_sampled_v5_finite_pair_source_data('sdk4df'))
        pins[str(canonical / sdk)] = pins[str(snapshot / sdk)] = wrong
    elif damage.startswith('cwd-'):
        target = {'cwd-relative': 'relative/private-snapshot', 'cwd-dotdot': str(snapshot) + '/../ipfs_datasets',
            'cwd-canonical': str(canonical), 'cwd-accelerate': str(canonical.parent / 'ipfs_accelerate'),
            'cwd-canonical-descendant': str(canonical / 'authored-snapshot') }[damage]
        case['request']['cwd'] = target
        for relative in (cli, sdk): pins[str(Path(target) / relative)] = pins[str(snapshot / relative)]
    else:
        original = case['terminal']['source_custody_lifecycle']['producer']['path']
        target = 'relative/scripts/ops/legal_ir/run_owned_validation.py' if damage == 'producer-relative' else str(canonical) + '/unused/../' + cli
        pins[target] = pins.pop(original)
        case['terminal']['source_custody_lifecycle']['producer']['path'] = target
        case['parent']['actual_original_owner_argv'][2] = target
    _manual_snapshot_reseal_unit_data(case)
    before = case['ledger'].read_bytes()
    def forbidden(*args, **kwargs):
        raise AssertionError('invalid manual roots/source pins reached current owner')
    monkeypatch.setattr(recovery, '_sampled_open_scheduler', forbidden)
    monkeypatch.setattr(recovery.resources, 'DaemonResourceReservation', forbidden)
    with pytest.raises(recovery.resources.DaemonResourceError):
        _manual_snapshot_call(case, operation)
    assert case['scheduler_calls'] == []
    _sampled_assert_unchanged(case, before)


@pytest.mark.parametrize('operation', ['inspect', 'reconcile'])
@pytest.mark.parametrize('damage', ['unknown-parent', 'source-open', 'source-drift', 'native-source-not-closed',
    'false-wait', 'false-child-reap', 'false-native-close', 'parent-errors', 'wrong-source-root',
    'swapped-source-order', 'wrong-source-lock', 'source-write', 'source-wait-bool', 'source-wait-negative',
    'zero-body', 'missing-body', 'bool-body', 'before-barrier', 'wrong-ledger-invocation'])
def test_manual_snapshot_refuses_resealed_custody_or_dispatch_mutation_before_owner(setup, monkeypatch, operation, damage):
    case = _manual_snapshot_unit_case(setup, monkeypatch)
    _manual_snapshot_pure_parent(case)
    parent, terminal = case['parent'], case['terminal']
    if damage == 'unknown-parent': parent['state'] = 'UNKNOWN_ORIGINAL_CUSTODY_SOURCE_READS_RETAINED_NO_REPLAY'
    elif damage == 'source-open': parent['source_closed'] = False
    elif damage == 'source-drift': parent['source_drift'] = ['/authored/changed.py']
    elif damage == 'native-source-not-closed': parent['native_and_source_exit_verified_before_parent_Source_close'] = False
    elif damage == 'false-wait': parent['original_owner_custody']['genuine_wait_completed'] = False
    elif damage == 'false-child-reap': parent['original_owner_custody']['child_reaped'] = False
    elif damage == 'false-native-close': parent['original_owner_custody']['original_native_compute_closed'] = False
    elif damage == 'parent-errors': parent['original_owner_custody']['errors'] = ['authored unresolved custody']
    elif damage == 'wrong-source-root': parent['original_source_READs'][1]['canonical_root'] = '/authored/foreign-accelerate'
    elif damage == 'swapped-source-order': parent['original_source_READs'].reverse()
    elif damage == 'wrong-source-lock': parent['original_source_READs'][0]['lock_path'] = '/authored/foreign-source.lock'
    elif damage == 'source-write': parent['original_source_READs'][0]['mode'] = 'write'
    elif damage == 'source-wait-bool': parent['original_source_READs'][0]['waited_seconds'] = True
    elif damage == 'source-wait-negative': parent['original_source_READs'][0]['waited_seconds'] = -1
    elif damage in {'zero-body', 'missing-body', 'bool-body'}:
        value = {'zero-body': 0, 'missing-body': None, 'bool-body': True}[damage]
        terminal['failure'].update(returncode=value, error='validation command failed with returncode ' + str(value))
    elif damage == 'before-barrier':
        terminal['source_custody_lifecycle']['events']['barrier_release_attempted'] = False
        terminal['source_custody_lifecycle']['events']['barrier_released'] = False
    else: parent['actual_original_owner_argv'][8] = '/authored/foreign-ledger.json'
    parent['original_owner_custody']['original_terminal'] = _sampled_copy(terminal)
    _sampled_seal(case)
    before = case['ledger'].read_bytes()
    def forbidden(*args, **kwargs):
        raise AssertionError('invalid manual custody/dispatch reached current owner')
    monkeypatch.setattr(recovery, '_sampled_open_scheduler', forbidden)
    monkeypatch.setattr(recovery.resources, 'DaemonResourceReservation', forbidden)
    with pytest.raises(recovery.resources.DaemonResourceError):
        _manual_snapshot_call(case, operation)
    assert case['scheduler_calls'] == []
    _sampled_assert_unchanged(case, before)


@pytest.mark.parametrize('operation', ['inspect', 'reconcile'])
@pytest.mark.parametrize('version', ['v1', 'v4'])
def test_manual_snapshot_never_uses_existing_legacy_parent_alternatives(setup, monkeypatch, operation, version):
    case = (_sampled_validation_fixture(setup, monkeypatch) if version == 'v1' else
        _sampled_source_held_v4_current_producer_fixture(setup, monkeypatch))
    before = case['ledger'].read_bytes()
    def forbidden(*args, **kwargs):
        raise AssertionError('legacy profile escaped explicit manual V5 gate')
    monkeypatch.setattr(recovery, '_sampled_open_scheduler', forbidden)
    monkeypatch.setattr(recovery.resources, 'DaemonResourceReservation', forbidden)
    with pytest.raises(recovery.resources.DaemonResourceError):
        _manual_snapshot_call(case, operation)
    assert case['scheduler_calls'] == []
    _sampled_assert_unchanged(case, before)


@pytest.mark.parametrize('operation', ['inspect', 'reconcile'])
@pytest.mark.parametrize('population', ['empty', 'over4096'])
def test_manual_snapshot_preserves_complete_nonempty_4096_artifact_bound(setup, monkeypatch, operation, population):
    case = _manual_snapshot_unit_case(setup, monkeypatch)
    _manual_snapshot_pure_parent(case)
    original_inventory = _sampled_copy(case['args']['expected_artifacts'])
    case['args']['expected_artifacts'] = [] if population == 'empty' else [dict(path=f'logs/control-{i}.json',
        bytes=0, sha256=_sampled_sha(b'')) for i in range(4097)]
    before = case['ledger'].read_bytes()
    def forbidden(*args, **kwargs):
        raise AssertionError('unsupported artifact population reached current owner')
    monkeypatch.setattr(recovery, '_sampled_open_scheduler', forbidden)
    monkeypatch.setattr(recovery.resources, 'DaemonResourceReservation', forbidden)
    with pytest.raises(recovery.resources.DaemonResourceError):
        _manual_snapshot_call(case, operation)
    assert case['scheduler_calls'] == [] and case['ledger'].read_bytes() == before
    assert recovery._durable_inventory(case['args']['attempt_directory']) == original_inventory


@pytest.mark.parametrize('overrides', [{}, {'capacity_policy': 'require_capacity'}], ids=['default', 'explicit-require-capacity'])
def test_manual_snapshot_reconciliation_still_requires_explicit_administrative_policy(setup, monkeypatch, overrides):
    case = _manual_snapshot_unit_case(setup, monkeypatch)
    _manual_snapshot_pure_parent(case)
    before = case['ledger'].read_bytes()
    def forbidden(*args, **kwargs):
        raise AssertionError('manual policy refusal reached live recovery')
    monkeypatch.setattr(recovery, '_sampled_open_scheduler', forbidden)
    monkeypatch.setattr(recovery, '_retained_reconciliation_engine', forbidden)
    native = recovery.resources.native_deadlines
    from contextlib import nullcontext
    scope = (nullcontext() if native.resource_operation_deadline() is not None else
        native.resource_cleanup_deadline(native_deadline_monotonic=recovery.resources.time.monotonic() + 240))
    with scope, pytest.raises(recovery.resources.DaemonResourceError):
        recovery.reconcile_manual_private_snapshot_validation_reservation_v1(case['ledger'], **case['args'], **overrides)
    assert case['scheduler_calls'] == []
    _sampled_assert_unchanged(case, before)


@pytest.mark.parametrize('operation', ['inspect', 'reconcile'])
def test_manual_snapshot_keeps_original_deadline_required_before_live_access(setup, monkeypatch, operation):
    case = _manual_snapshot_unit_case(setup, monkeypatch)
    assert recovery.resources.native_deadlines.resource_operation_deadline() is None
    before = case['ledger'].read_bytes()
    def forbidden(*args, **kwargs):
        raise AssertionError('deadline-free manual call reached current owner')
    monkeypatch.setattr(recovery.resources, 'DaemonResourceReservation', forbidden)
    function = (recovery.inspect_manual_private_snapshot_validation_recovery_v1 if operation == 'inspect' else
        recovery.reconcile_manual_private_snapshot_validation_reservation_v1)
    with pytest.raises(recovery.resources.DaemonResourceError):
        function(case['ledger'], **case['args'], **({'capacity_policy': 'administrative_closeout'} if operation == 'reconcile' else {}))
    assert case['scheduler_calls'] == []
    _sampled_assert_unchanged(case, before)


@pytest.mark.parametrize('operation', ['inspect', 'reconcile'])
@pytest.mark.parametrize('damage', ['owner-pid', 'observed-reused-pid', 'native-root', 'native-waiter', 'stale-selected-ledger', 'attempt-inode'])
def test_manual_snapshot_reuses_existing_current_process_native_ledger_and_inode_guards(setup, monkeypatch, operation, damage):
    case = _manual_snapshot_unit_case(setup, monkeypatch)
    _manual_snapshot_pure_parent(case)
    if damage in {'owner-pid', 'observed-reused-pid'}:
        pid = case['row']['owner_pid'] if damage == 'owner-pid' else case['terminal']['reservation']['process_observation']['observed_identities'][-1]['pid']
        case['process_table'][pid] = dict(pid=pid, birth='987654321', state='S', parent_pid=99999998, group_pid=99999996, rss_bytes=4096)
    elif damage == 'native-root':
        value = case['row']['native_lease_id'];case['scheduler_state']['leases'][value] = {'lease_id': value}
    elif damage == 'native-waiter':
        case['scheduler_state']['waiters']['e' * 32] = {'request_id': 'validation:' + case['args']['reservation_id']}
    elif damage == 'stale-selected-ledger':
        data = json.loads(case['ledger'].read_bytes());data['reservations'][case['args']['reservation_id']]['memory_mb'] += 1;case['ledger'].write_text(json.dumps(data))
    else:
        original = case['args']['attempt_directory'];original.rename(original.with_name(original.name + '-preserved-original'));original.mkdir()
    before = case['ledger'].read_bytes()
    with pytest.raises(recovery.resources.DaemonResourceError):
        _manual_snapshot_call(case, operation)
    assert case['ledger'].read_bytes() == before
    assert json.loads(before)['reservations'][case['args']['reservation_id']]['status'] == 'retained'
    assert json.loads(before)['reservations'][case['prior_id']] == case['prior']
    if damage != 'attempt-inode':
        assert recovery._durable_inventory(case['args']['attempt_directory']) == case['args']['expected_artifacts']


@pytest.mark.parametrize('operation', ['inspect', 'reconcile'])
def test_manual_snapshot_rechecks_late_foreign_ledger_mutation_before_commit(setup, monkeypatch, operation):
    case = _manual_snapshot_unit_case(setup, monkeypatch)
    selected_before = _sampled_copy(case['row'])
    original_inventory = recovery._durable_inventory
    mutations = []
    def mutate_after_inventory(attempt):
        result = original_inventory(attempt)
        if not mutations:
            data = json.loads(case['ledger'].read_bytes());data['reservations'][case['prior_id']]['created_at'] += 1
            case['ledger'].write_text(json.dumps(data));mutations.append(True)
        return result
    monkeypatch.setattr(recovery, '_durable_inventory', mutate_after_inventory)
    with pytest.raises(recovery.resources.DaemonResourceError):
        _manual_snapshot_call(case, operation)
    assert mutations == [True]
    data = json.loads(case['ledger'].read_bytes())
    assert data['reservations'][case['args']['reservation_id']] == selected_before
    assert data['reservations'][case['prior_id']]['created_at'] == case['prior']['created_at'] + 1
    assert original_inventory(case['args']['attempt_directory']) == case['args']['expected_artifacts']


@pytest.mark.parametrize('operation', ['inspect', 'reconcile'])
def test_manual_snapshot_rechecks_late_complete_inventory_before_commit(setup, monkeypatch, operation):
    case = _manual_snapshot_unit_case(setup, monkeypatch)
    before = case['ledger'].read_bytes()
    original_inventory = recovery._durable_inventory
    additions = []
    def add_after_inventory(attempt):
        result = original_inventory(attempt)
        if not additions:
            path = Path(attempt) / 'late-authored-data.json';path.write_bytes(b'{}\n');additions.append(path)
        return result
    monkeypatch.setattr(recovery, '_durable_inventory', add_after_inventory)
    with pytest.raises(recovery.resources.DaemonResourceError):
        _manual_snapshot_call(case, operation)
    assert len(additions) == 1 and additions[0].read_bytes() == b'{}\n'
    assert case['ledger'].read_bytes() == before
    assert json.loads(before)['reservations'][case['args']['reservation_id']]['status'] == 'retained'


# Restrict lossless relocation to closed, test-local detached proof DATA. The
# product always sees the original regular raw file during every assertion.
# These files are not qualification receipts and never describe actual 372f.
def _completed_watchdog_archive_closed_proof_data(scratch, nodeid):
    import gzip
    import hashlib
    import stat

    directories = [scratch, scratch / 'cache',
        scratch / 'cache' / 'authored-completed-watchdog-evidence']
    raw_path = directories[-1] / 'original-proof-archive.json'
    try:
        if any(not stat.S_ISDIR(path.lstat().st_mode) for path in directories):
            return
        before = raw_path.lstat()
    except FileNotFoundError:
        return  # Early-refusal controls intentionally publish no detached DATA.
    if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
        return  # Preserve unusual or aliased evidence without following it.
    identity = lambda value: (value.st_dev, value.st_ino, value.st_mode,
        value.st_nlink, value.st_size, value.st_mtime_ns, value.st_ctime_ns)
    descriptor = os.open(raw_path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        with os.fdopen(descriptor, 'rb') as stream:
            if identity(os.fstat(stream.fileno())) != identity(before):
                return
            original = stream.read()
            if identity(os.fstat(stream.fileno())) != identity(before):
                return
    except BaseException:
        # A teardown failure retains the original DATA. No product operation is
        # active here, and no failed assertion's bytes are discarded.
        raise
    if len(original) != before.st_size or identity(raw_path.lstat()) != identity(before):
        return
    original_sha = hashlib.sha256(original).hexdigest()
    compressed = gzip.compress(original, compresslevel=9, mtime=0)
    archive = raw_path.with_name('original-proof-archive.closed-unit-data.json.gz')
    locator = raw_path.with_name('original-proof-archive.closed-unit-data.relocation.json')
    if archive.exists() or locator.exists():
        return
    # Exclusive creation and complete readback precede any removal. A partial
    # archive or locator failure leaves the complete original regular file.
    with archive.open('xb') as stream:
        stream.write(compressed)
        stream.flush()
        os.fsync(stream.fileno())
    archived = archive.read_bytes()
    restored = gzip.decompress(archived)
    if restored != original or hashlib.sha256(restored).hexdigest() != original_sha:
        raise AssertionError('closed unit DATA gzip roundtrip differs; raw preserved')
    archive.chmod(stat.S_IMODE(before.st_mode))
    os.utime(archive, ns=(before.st_atime_ns, before.st_mtime_ns))
    record = dict(schema='closed-unit-proof-data-relocation/v1',
        origin='authored completed-watchdog UNIT_DATA after test assertions',
        test_nodeid=nodeid, original_path=str(raw_path),
        original_bytes=len(original), original_sha256=original_sha,
        original_mode=stat.S_IMODE(before.st_mode),
        original_atime_ns=before.st_atime_ns, original_mtime_ns=before.st_mtime_ns,
        original_device=before.st_dev, original_inode=before.st_ino,
        original_ctime_ns=before.st_ctime_ns,
        archive_path=str(archive), archive_bytes=len(archived),
        archive_sha256=hashlib.sha256(archived).hexdigest(), compression='gzip',
        roundtrip_bytes_and_sha256_verified=True,
        restore=dict(source=str(archive), destination=str(raw_path),
            method='gzip.decompress; write exact bytes; chmod original_mode; restore atime/mtime',
            historical_inode_and_ctime_restored=False),
        raw_removal_permitted_only_after_verified_archive_and_locator=True,
        product_operations_or_test_acceptance_asserted=False)
    locator_raw = json.dumps(record, sort_keys=True, indent=2).encode() + b'\n'
    with locator.open('xb') as stream:
        stream.write(locator_raw)
        stream.flush()
        os.fsync(stream.fileno())
    assert locator.read_bytes() == locator_raw
    directory_fd = os.open(directories[-1], os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(directory_fd)
        # The final raw read/stat prevents relocation of a changed generation.
        if identity(raw_path.lstat()) != identity(before) or raw_path.read_bytes() != original:
            return
        raw_path.unlink()
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


@pytest.fixture(autouse=True)
def _completed_watchdog_closed_unit_proof_storage(request):
    if not request.node.name.startswith('test_completed_watchdog_'):
        yield
        return
    scratch = request.getfixturevalue('tmp_path')
    try:
        yield
    finally:
        # This fixture starts before setup/monkeypatch fixtures and tears down
        # after them, including on failed assertions. Only this exact test's
        # fixed detached proof DATA is eligible; no root traversal is used.
        _completed_watchdog_archive_closed_proof_data(scratch, request.node.nodeid)


# Explicit completed-body watchdog-finalization UNIT_DATA controls. These
# authored fixtures use captured reviewed producer DATA, never execute it, and
# make no claim about the original 372f attempt or actual Source/Native custody.
def _completed_watchdog_unit_case(setup, monkeypatch, *, large_population=False,
        owner_pair='280-11e', subject_pair='269-4df', publish_evidence=True):
    factory, roots, ledger, scheduler = setup
    assert not ledger.exists(), 'the original modeled promise must precede selection'
    monkeypatch.setattr(recovery.resources, 'MAX_STORAGE_BYTES', 4_000_000)
    promise = 2_000_000 if large_population else 1_000_000
    def promised_factory(**kwargs):
        kwargs.setdefault('storage_bytes', promise)
        return factory(**kwargs)
    case = _manual_snapshot_unit_case((promised_factory, roots, ledger, scheduler),
        monkeypatch, owner_pair)
    canonical, snapshot = case['manual_unit_roots']
    cli = 'scripts/ops/legal_ir/run_owned_validation.py'
    sdk = 'ipfs_datasets_py/optimizers/logic_theorem_optimizer/validation_run_resources.py'
    subject_cli = (_sampled_v5_public_280_source_data() if subject_pair == '280-11e'
        else _sampled_v5_finite_pair_source_data('cli7ce') if subject_pair == '7ce-860'
        else _sampled_v5_finite_pair_source_data('cli86c8') if subject_pair == '86c8-4df'
        else _sampled_v5_finite_pair_source_data('cli269'))
    subject_sdk = _sampled_v5_finite_pair_source_data(
        'sdk11e' if subject_pair == '280-11e' else 'sdk860' if subject_pair == '7ce-860' else 'sdk4df')
    case['request']['source_sha256'][str(snapshot / cli)] = _sampled_sha(subject_cli)
    case['request']['source_sha256'][str(snapshot / sdk)] = _sampled_sha(subject_sdk)
    check = snapshot / 'tests/unit/optimizers/logic_theorem_optimizer/test_authored_completed_watchdog.py'
    check.parent.mkdir(parents=True)
    check_data = b'# Authored private owning-check DATA; never executed.\n'
    check.write_bytes(check_data)
    case['request']['selected_checks'] = [str(check)]
    case['request']['source_sha256'][str(check)] = _sampled_sha(check_data)
    case['request']['argv'].append(str(check))
    case['terminal']['failure'].update(executed_checks=[str(check)], returncode=0,
        error_type='RuntimeError', error='validation watchdog did not finish cleanly')
    case['unit_data_provenance'] = 'authored-completed-watchdog-frame-fork; no actual history'
    case['completed_owner_pair'] = owner_pair
    case['completed_subject_pair'] = subject_pair
    case['completed_publish_evidence'] = publish_evidence
    assert case['row']['storage_bytes'] == promise
    if large_population:
        population = case['args']['attempt_directory'] / 'regular-population'
        population.mkdir()
        for number in range(4096):
            (population / f'item-{number:04d}.txt').write_bytes(b'x')
    case['args']['expected_artifacts'] = recovery._durable_inventory(case['args']['attempt_directory'])
    _completed_watchdog_reseal_unit_data(case)
    return case


def _completed_watchdog_reseal_unit_data(case):
    _manual_snapshot_reseal_unit_data(case)
    evidence = case['args']['roots'][1] / 'authored-completed-watchdog-evidence'
    if case['completed_publish_evidence']:
        evidence.mkdir(exist_ok=True)
    def store(name, raw):
        path = evidence / name
        if case['completed_publish_evidence']:
            path.write_bytes(raw)
            path.chmod(0o600)
        return dict(path=str(path), bytes=len(raw), sha256=_sampled_sha(raw))
    manifest_raw = _sampled_wire(dict(schema='retained-artifact-inventory/v1',
        attempt_directory=case['row']['attempt_directory'],
        artifacts=case['args']['expected_artifacts']))
    case['completed_args'] = dict(case['args'],
        artifact_inventory_manifest=store('complete-inventory.json', manifest_raw),
        evidence_archive=store('original-proof-archive.json', case['args']['proof_raw']))
    assert sum(case['completed_args'][key]['bytes'] for key in (
        'artifact_inventory_manifest', 'evidence_archive')) <= case['row']['storage_bytes']


def _completed_watchdog_call(case, operation='inspect', **overrides):
    function = (recovery.inspect_completed_watchdog_validation_recovery_v1 if operation == 'inspect'
        else recovery.reconcile_completed_watchdog_validation_reservation_v1)
    if operation == 'reconcile' and 'capacity_policy' not in overrides:
        overrides['capacity_policy'] = 'administrative_closeout'
    arguments = dict(case['completed_args'], **overrides)
    native = recovery.resources.native_deadlines
    original = native.resource_operation_deadline()
    if original is not None and original.cleanup_only:
        return function(case['ledger'], **arguments)
    cutoff = (recovery.resources.time.monotonic() + 240 if original is None else
        min(original.work_deadline_monotonic, original.native_deadline_monotonic))
    with native.resource_cleanup_deadline(native_deadline_monotonic=cutoff):
        return function(case['ledger'], **arguments)


def _completed_watchdog_assert_preserved(case, before):
    assert case['ledger'].read_bytes() == before
    current = json.loads(before)
    assert current['reservations'][case['args']['reservation_id']]['status'] == 'retained'
    assert current['reservations'][case['prior_id']] == case['prior']


@pytest.mark.parametrize('owner_pair,subject_pair', [
    ('280-11e', '269-4df'), ('269-4df', '280-11e')])
def test_completed_watchdog_explicit_compact_closeout_preserves_original_failure(
        setup, monkeypatch, owner_pair, subject_pair):
    case = _completed_watchdog_unit_case(setup, monkeypatch,
        owner_pair=owner_pair, subject_pair=subject_pair)
    before = case['ledger'].read_bytes()
    raw_frames = tuple(_sampled_wire(case[name]) for name in ('request', 'terminal', 'parent'))
    ready = _completed_watchdog_call(case)
    assert ready['schema'] == 'completed-watchdog-validation-recovery-readiness/v1'
    assert ready['ready'] is ready['capacity_not_assessed'] is True
    assert ready['state_written'] is ready['recovery_performed'] is ready['admitted'] is False
    _completed_watchdog_assert_preserved(case, before)
    receipt = _completed_watchdog_call(case, 'reconcile')
    assert receipt['schema'] == 'explicit-completed-watchdog-validation-reconciliation/v1'
    selected = json.loads(case['ledger'].read_bytes())['reservations'][case['args']['reservation_id']]
    assert selected['status'] == 'released' and selected['artifacts_durable_asserted'] is True
    assert selected['storage_bytes'] == case['row']['storage_bytes'] == 1_000_000
    assert selected['explicit_reconciliation'] == receipt
    assert receipt['capacity_policy'] == 'administrative_closeout'
    assert receipt['actual_postwrite_census_required'] is receipt['final_accounting_is_prewrite_projection'] is True
    for result in (ready, receipt):
        assert 'artifacts' not in result
        assert result['artifact_count'] == len(case['args']['expected_artifacts'])
        assert result['artifact_bytes'] == sum(row['bytes'] for row in case['args']['expected_artifacts'])
        assert result['artifact_manifest_schema'] == 'retained-artifact-inventory/v1'
        assert result['artifact_inventory_manifest'] == case['completed_args']['artifact_inventory_manifest']
        assert result['evidence_archive'] == case['completed_args']['evidence_archive']
    for proof in (ready['proof'], receipt['sampled_custody_proof']):
        assert proof['original_failure_profile'] == 'source-held-V5-completed-command-watchdog-finalization/v1'
        assert proof['original_command_returncode'] == 0
        assert proof['original_cli_returncode'] == 1
        assert proof['original_failure_preserved'] is True
        assert proof['cryptographic_execution_attestation'] is proof['reconstructed_Popen_handle'] is False
        assert proof['completed_body_watchdog_finalization_optin'] is True
        assert proof['original_owner_completed'] is proof['retroactive_qualification_claimed'] is False
        canonical, snapshot = case['manual_unit_roots']
        sdk = 'ipfs_datasets_py/optimizers/logic_theorem_optimizer/validation_run_resources.py'
        assert proof['canonical_source_owner_root'] == str(canonical)
        assert proof['original_working_directory'] == str(snapshot)
        assert proof['owner_sdk_sha256'] == case['request']['source_sha256'][str(canonical / sdk)]
        assert proof['private_subject_sdk_sha256'] == case['request']['source_sha256'][str(snapshot / sdk)]
        assert proof['private_subject_pin_scope'] == 'original_declared_subject_pins_not_execution_attestation'
    for name in ('native_release_performed', 'admitted', 'outputs_deleted', 'cap_changed',
            'new_reservation_created', 'new_resource_lease_acquired', 'request_budget_changed',
            'source_authority_granted', 'retroactive_qualification_claimed', 'test_or_task_acceptance_asserted'):
        assert receipt[name] is False
    assert tuple(_sampled_wire(case[name]) for name in ('request', 'terminal', 'parent')) == raw_frames
    assert case['terminal']['completed'] is case['terminal']['failure']['completed'] is False
    assert case['parent']['original_owner_custody']['storage_artifacts_durable_asserted'] is False
    assert Path(case['completed_args']['evidence_archive']['path']).read_bytes() == case['args']['proof_raw']
    assert json.loads(Path(case['completed_args']['artifact_inventory_manifest']['path']).read_bytes())['artifacts'] == case['args']['expected_artifacts']
    assert json.loads(case['ledger'].read_bytes())['reservations'][case['prior_id']] == case['prior']
    assert case['scheduler_state'] == dict(leases={}, waiters={})


def test_completed_watchdog_full4097_inventory_stays_out_of_hot_ledger(setup, monkeypatch):
    case = _completed_watchdog_unit_case(setup, monkeypatch, large_population=True)
    before = case['ledger'].read_bytes()
    ceiling = len(before) + 16000
    monkeypatch.setattr(recovery.resources, 'MAX_LEDGER_BYTES', ceiling)
    assert len(case['args']['expected_artifacts']) == 4097
    assert len(_sampled_wire(case['args']['expected_artifacts'])) > ceiling
    ready = _completed_watchdog_call(case)
    _completed_watchdog_assert_preserved(case, before)
    receipt = _completed_watchdog_call(case, 'reconcile')
    assert ready['artifact_count'] == receipt['artifact_count'] == 4097
    assert len(case['ledger'].read_bytes()) < ceiling
    assert 'artifacts' not in ready and 'artifacts' not in receipt
    final = json.loads(case['ledger'].read_bytes())
    assert final['limit_bytes'] == recovery.resources.MAX_STORAGE_BYTES == 4_000_000
    assert final['reservations'][case['args']['reservation_id']]['storage_bytes'] == 2_000_000
    assert final['reservations'][case['prior_id']] == case['prior']
    assert recovery._durable_inventory(case['args']['attempt_directory']) == case['args']['expected_artifacts']


@pytest.mark.parametrize('operation', ['inspect', 'reconcile'])
@pytest.mark.parametrize('route', ['default', 'manual-private-snapshot'])
def test_completed_watchdog_keeps_existing_failure_categories_unchanged(setup, monkeypatch, operation, route):
    case = _completed_watchdog_unit_case(setup, monkeypatch, publish_evidence=False)
    before = case['ledger'].read_bytes()
    def forbidden(*args, **kwargs):
        raise AssertionError('completed body reached legacy current recovery')
    monkeypatch.setattr(recovery, '_sampled_open_scheduler', forbidden)
    with pytest.raises(recovery.resources.DaemonResourceError):
        if route == 'default':
            _sampled_inspect(case) if operation == 'inspect' else _sampled_reconcile(case, 'administrative_closeout')
        else:
            _manual_snapshot_call(case, operation)
    assert case['scheduler_calls'] == []
    _completed_watchdog_assert_preserved(case, before)


@pytest.mark.parametrize('operation', ['inspect', 'reconcile'])
@pytest.mark.parametrize('damage', ['forged-error', 'non-runtime-error', 'bool-body', 'float-body',
    'nonzero-body', 'bool-outer', 'wrong-outer', 'watchdog-errors', 'received-signal',
    'source-open', 'native-not-closed', 'false-wait', 'original-durability', 'source-drift',
    'canonical-sdk-swap', 'private-sdk-swap', 'private-cli-swap', 'missing-check-pin',
    'check-outside-snapshot', 'wrong-ledger', 'source-root-swap', 'terminal-completed',
    'failure-completed', 'admitted', 'lifecycle-open'])
def test_completed_watchdog_refuses_resealed_unknown_profile_before_current_owner(
        setup, monkeypatch, operation, damage):
    case = _completed_watchdog_unit_case(setup, monkeypatch, publish_evidence=False)
    parent, terminal, request = (case[key] for key in ('parent', 'terminal', 'request'))
    canonical, snapshot = case['manual_unit_roots']
    sdk = 'ipfs_datasets_py/optimizers/logic_theorem_optimizer/validation_run_resources.py'
    if damage == 'forged-error': terminal['failure']['error'] += ' (invented)'
    elif damage == 'non-runtime-error': terminal['failure']['error_type'] = 'OSError'
    elif damage == 'bool-body': terminal['failure']['returncode'] = False
    elif damage == 'float-body': terminal['failure']['returncode'] = 0.0
    elif damage == 'nonzero-body': terminal['failure']['returncode'] = 1
    elif damage == 'bool-outer':
        parent['owner_returncode'] = parent['original_owner_custody']['returncode'] = True
    elif damage == 'wrong-outer':
        parent['owner_returncode'] = parent['original_owner_custody']['returncode'] = 0
    elif damage == 'watchdog-errors': terminal['failure']['watchdog_errors'] = ['authored unresolved failure']
    elif damage == 'received-signal': terminal['failure']['received_signals'] = [15]
    elif damage == 'source-open': parent['source_closed'] = False
    elif damage == 'native-not-closed': parent['original_owner_custody']['original_native_compute_closed'] = False
    elif damage == 'false-wait': parent['original_owner_custody']['genuine_wait_completed'] = False
    elif damage == 'original-durability': parent['original_owner_custody']['storage_artifacts_durable_asserted'] = True
    elif damage == 'source-drift': parent['source_drift'] = ['/authored/changed.py']
    elif damage == 'canonical-sdk-swap':
        request['source_sha256'][str(canonical / sdk)] = _sampled_sha(_sampled_v5_finite_pair_source_data('sdk4df'))
    elif damage == 'private-sdk-swap':
        request['source_sha256'][str(snapshot / sdk)] = _sampled_sha(_sampled_v5_finite_pair_source_data('sdk11e'))
    elif damage == 'private-cli-swap':
        request['source_sha256'][str(snapshot / 'scripts/ops/legal_ir/run_owned_validation.py')] = _sampled_sha(_sampled_v5_public_280_source_data())
    elif damage == 'missing-check-pin': request['source_sha256'].pop(request['selected_checks'][0])
    elif damage == 'check-outside-snapshot':
        check = str(canonical / 'tests/unit/authored.py')
        request['selected_checks'] = terminal['failure']['executed_checks'] = [check]
        request['source_sha256'][check] = 'e' * 64
    elif damage == 'source-root-swap': parent['original_source_READs'][0]['canonical_root'] = str(snapshot)
    elif damage == 'terminal-completed': terminal['completed'] = True
    elif damage == 'failure-completed': terminal['failure']['completed'] = True
    elif damage == 'admitted': terminal['failure']['admitted'] = True
    elif damage == 'lifecycle-open': terminal['source_custody_lifecycle']['events']['owner_exit_handling_completed'] = False
    else: parent['actual_original_owner_argv'][8] = '/authored/foreign-ledger.json'
    _completed_watchdog_reseal_unit_data(case)
    before = case['ledger'].read_bytes()
    def forbidden(*args, **kwargs):
        raise AssertionError('invalid completed watchdog DATA reached live owner')
    monkeypatch.setattr(recovery, '_sampled_open_scheduler', forbidden)
    monkeypatch.setattr(recovery.resources, 'DaemonResourceReservation', forbidden)
    with pytest.raises(recovery.resources.DaemonResourceError):
        _completed_watchdog_call(case, operation)
    assert case['scheduler_calls'] == []
    _completed_watchdog_assert_preserved(case, before)


@pytest.mark.parametrize('operation', ['inspect', 'reconcile'])
@pytest.mark.parametrize('damage', ['owner-pid', 'observed-reused-pid', 'native-root',
    'native-waiter', 'stale-selected-ledger', 'attempt-inode', 'inventory-change',
    'manifest-drift', 'archive-drift', 'manifest-sha', 'archive-sha', 'inventory-drop'])
def test_completed_watchdog_refuses_changed_current_custody_or_saved_evidence(
        setup, monkeypatch, operation, damage):
    case = _completed_watchdog_unit_case(setup, monkeypatch)
    if damage in {'owner-pid', 'observed-reused-pid'}:
        pid = (case['row']['owner_pid'] if damage == 'owner-pid' else
            case['terminal']['reservation']['process_observation']['observed_identities'][-1]['pid'])
        case['process_table'][pid] = dict(pid=pid, birth='987654321', state='S',
            parent_pid=99999998, group_pid=99999996, rss_bytes=4096)
    elif damage == 'native-root':
        value = case['row']['native_lease_id']
        case['scheduler_state']['leases'][value] = {'lease_id': value}
    elif damage == 'native-waiter':
        case['scheduler_state']['waiters']['e' * 32] = {'request_id': 'validation:' + case['args']['reservation_id']}
    elif damage == 'stale-selected-ledger':
        data = json.loads(case['ledger'].read_bytes())
        data['reservations'][case['args']['reservation_id']]['memory_mb'] += 1
        case['ledger'].write_text(json.dumps(data))
    elif damage == 'attempt-inode':
        original = case['args']['attempt_directory']
        original.rename(original.with_name(original.name + '-preserved-original'))
        original.mkdir()
    elif damage == 'inventory-change':
        (case['args']['attempt_directory'] / 'late-authored.json').write_bytes(b'{}\n')
    elif damage in {'manifest-drift', 'archive-drift'}:
        key = 'artifact_inventory_manifest' if damage == 'manifest-drift' else 'evidence_archive'
        Path(case['completed_args'][key]['path']).write_bytes(b'{}\n')
    elif damage in {'manifest-sha', 'archive-sha'}:
        key = 'artifact_inventory_manifest' if damage == 'manifest-sha' else 'evidence_archive'
        case['completed_args'][key]['sha256'] = 'f' * 64
    else: case['completed_args']['expected_artifacts'] = []
    before = case['ledger'].read_bytes()
    with pytest.raises(recovery.resources.DaemonResourceError):
        _completed_watchdog_call(case, operation)
    _completed_watchdog_assert_preserved(case, before)


@pytest.mark.parametrize('capacity_policy', ['default', 'require_capacity', 'unknown'])
def test_completed_watchdog_requires_explicit_administrative_closeout_policy(setup, monkeypatch, capacity_policy):
    case = _completed_watchdog_unit_case(setup, monkeypatch, publish_evidence=False)
    before = case['ledger'].read_bytes()
    def forbidden(*args, **kwargs):
        raise AssertionError('nonadministrative completed closeout reached live engine')
    monkeypatch.setattr(recovery, '_retained_reconciliation_engine', forbidden)
    monkeypatch.setattr(recovery, '_sampled_open_scheduler', forbidden)
    native = recovery.resources.native_deadlines
    arguments = dict(case['completed_args'])
    if capacity_policy != 'default': arguments['capacity_policy'] = capacity_policy
    with native.resource_cleanup_deadline(native_deadline_monotonic=recovery.resources.time.monotonic() + 240):
        with pytest.raises(recovery.resources.DaemonResourceError):
            recovery.reconcile_completed_watchdog_validation_reservation_v1(case['ledger'], **arguments)
    assert case['scheduler_calls'] == []
    _completed_watchdog_assert_preserved(case, before)


@pytest.mark.parametrize('operation', ['inspect', 'reconcile'])
def test_completed_watchdog_requires_existing_cleanup_deadline_before_live_access(setup, monkeypatch, operation):
    case = _completed_watchdog_unit_case(setup, monkeypatch, publish_evidence=False)
    assert recovery.resources.native_deadlines.resource_operation_deadline() is None
    before = case['ledger'].read_bytes()
    def forbidden(*args, **kwargs):
        raise AssertionError('deadline-free completed closeout reached live owner')
    monkeypatch.setattr(recovery.resources, 'DaemonResourceReservation', forbidden)
    function = (recovery.inspect_completed_watchdog_validation_recovery_v1 if operation == 'inspect'
        else recovery.reconcile_completed_watchdog_validation_reservation_v1)
    arguments = dict(case['completed_args'])
    if operation == 'reconcile': arguments['capacity_policy'] = 'administrative_closeout'
    with pytest.raises(recovery.resources.DaemonResourceError):
        function(case['ledger'], **arguments)
    _completed_watchdog_assert_preserved(case, before)


@pytest.mark.parametrize('operation', ['inspect', 'reconcile'])
def test_completed_watchdog_refuses_fsync_failure_without_releasing_claim(setup, monkeypatch, operation):
    case = _completed_watchdog_unit_case(setup, monkeypatch)
    before = case['ledger'].read_bytes()
    real_os = recovery.os
    def failed_fsync(descriptor):
        raise OSError('authored recovery durability failure')
    monkeypatch.setattr(recovery, 'os', SimpleNamespace(**{**vars(real_os), 'fsync': failed_fsync}))
    with pytest.raises((recovery.resources.DaemonResourceError, OSError)):
        _completed_watchdog_call(case, operation)
    _completed_watchdog_assert_preserved(case, before)


@pytest.mark.parametrize('operation', ['inspect', 'reconcile'])
def test_completed_watchdog_rechecks_late_foreign_ledger_mutation(setup, monkeypatch, operation):
    case = _completed_watchdog_unit_case(setup, monkeypatch)
    selected_before = _sampled_copy(case['row'])
    original_inventory = recovery._durable_inventory
    mutations = []
    def mutate_after_inventory(attempt):
        result = original_inventory(attempt)
        if not mutations:
            data = json.loads(case['ledger'].read_bytes())
            data['reservations'][case['prior_id']]['created_at'] += 1
            case['ledger'].write_text(json.dumps(data))
            mutations.append(True)
        return result
    monkeypatch.setattr(recovery, '_durable_inventory', mutate_after_inventory)
    with pytest.raises(recovery.resources.DaemonResourceError):
        _completed_watchdog_call(case, operation)
    assert mutations == [True]
    data = json.loads(case['ledger'].read_bytes())
    assert data['reservations'][case['args']['reservation_id']] == selected_before
    assert data['reservations'][case['prior_id']]['created_at'] == case['prior']['created_at'] + 1


@pytest.mark.parametrize('operation', ['inspect', 'reconcile'])
@pytest.mark.parametrize('damage', ['late-inventory', 'late-owner', 'late-native'])
def test_completed_watchdog_rechecks_late_custody_after_inventory(setup, monkeypatch, operation, damage):
    case = _completed_watchdog_unit_case(setup, monkeypatch)
    before = case['ledger'].read_bytes()
    original_inventory = recovery._durable_inventory
    mutations = []
    def mutate_after_inventory(attempt):
        result = original_inventory(attempt)
        if not mutations:
            if damage == 'late-inventory': (Path(attempt) / 'late-authored.json').write_bytes(b'{}\n')
            elif damage == 'late-owner': case['process_table'][case['row']['owner_pid']] = {'birth': case['row']['owner_birth']}
            else:
                value = case['row']['native_lease_id']
                case['scheduler_state']['leases'][value] = {'lease_id': value}
            mutations.append(True)
        return result
    monkeypatch.setattr(recovery, '_durable_inventory', mutate_after_inventory)
    with pytest.raises(recovery.resources.DaemonResourceError):
        _completed_watchdog_call(case, operation)
    assert mutations == [True]
    _completed_watchdog_assert_preserved(case, before)


def test_completed_watchdog_cannot_commit_after_census_cleanup_deadline(setup, monkeypatch):
    case = _completed_watchdog_unit_case(setup, monkeypatch)
    before = case['ledger'].read_bytes()
    native = recovery.resources.native_deadlines
    clock, censuses = [239.0], []
    monkeypatch.setattr(native, 'time', SimpleNamespace(monotonic=lambda: clock[0]))
    original_admin = recovery._administrative_census
    def expired_after_census(helper, state):
        result = original_admin(helper, state)
        censuses.append(True)
        clock[0] = 241.0
        return result
    monkeypatch.setattr(recovery, '_administrative_census', expired_after_census)
    with pytest.raises(native.ResourceAdmissionDeadlineError):
        with native.resource_cleanup_deadline(native_deadline_monotonic=240.0):
            _completed_watchdog_call(case, 'reconcile')
    assert censuses
    _completed_watchdog_assert_preserved(case, before)


def test_completed_watchdog_refuses_hot_ledger_overflow_without_partial_release(setup, monkeypatch):
    case = _completed_watchdog_unit_case(setup, monkeypatch)
    before = case['ledger'].read_bytes()
    monkeypatch.setattr(recovery.resources, 'MAX_LEDGER_BYTES', len(before) + 128)
    with pytest.raises(recovery.resources.DaemonResourceError):
        _completed_watchdog_call(case, 'reconcile')
    _completed_watchdog_assert_preserved(case, before)


def test_completed_watchdog_record_only_disposition_authenticates_compact_receipt(setup, monkeypatch):
    case = _completed_watchdog_unit_case(setup, monkeypatch)
    previous_sha = case['args']['expected_record_sha256']
    _completed_watchdog_call(case, 'reconcile')
    data = json.loads(case['ledger'].read_bytes())
    row = data['reservations'][case['args']['reservation_id']]
    before = case['ledger'].read_bytes()
    def forbidden(*args, **kwargs):
        raise AssertionError('record-only disposition attempted live inventory or scheduler')
    monkeypatch.setattr(recovery, '_durable_inventory', forbidden)
    monkeypatch.setattr(recovery, '_sampled_open_scheduler', forbidden)
    report = recovery.inspect_validation_disposition(case['ledger'], roots=case['args']['roots'],
        reservation_id=case['args']['reservation_id'],
        expected_request_sha256=case['args']['expected_request_sha256'],
        attempt_directory=case['args']['attempt_directory'],
        expected_record_sha256=recovery._digest(row), expected_previous_record_sha256=previous_sha,
        process_scope='sampled_birth_bound_descendants')
    assert report['storage_release_established'] is True
    assert report['native_release_established'] is False
    assert report['state_written'] is report['recovery_performed'] is report['admitted'] is False
    assert case['ledger'].read_bytes() == before
    assert data['reservations'][case['prior_id']] == case['prior']


@pytest.mark.parametrize('damage', ['schema', 'attempt', 'missing-artifact', 'unknown-field',
    'archive-other-proof', 'manifest-in-attempt', 'shared-reference'])
@pytest.mark.parametrize('operation', ['inspect', 'reconcile'])
def test_completed_watchdog_refuses_self_consistently_rehashed_detached_evidence(
        setup, monkeypatch, damage, operation):
    case = _completed_watchdog_unit_case(setup, monkeypatch)
    arguments = case['completed_args']
    reference = arguments['artifact_inventory_manifest']
    manifest = json.loads(Path(reference['path']).read_bytes())
    if damage == 'schema': manifest['schema'] = 'invented-inventory/v1'
    elif damage == 'attempt': manifest['attempt_directory']['inode'] += 1
    elif damage == 'missing-artifact': manifest['artifacts'] = []
    elif damage == 'unknown-field': manifest['unreviewed_durability_authority'] = True
    elif damage == 'archive-other-proof':
        reference = arguments['evidence_archive']
        manifest = json.loads(Path(reference['path']).read_bytes())
        manifest['provenance'] = 'invented-execution-attestation/v1'
    elif damage == 'manifest-in-attempt':
        reference['path'] = str(case['args']['attempt_directory'] / 'invented-manifest.json')
    else: arguments['evidence_archive'] = _sampled_copy(reference)
    if damage != 'shared-reference':
        raw = _sampled_wire(manifest)
        Path(reference['path']).write_bytes(raw)
        reference.update(bytes=len(raw), sha256=_sampled_sha(raw))
    before = case['ledger'].read_bytes()
    with pytest.raises(recovery.resources.DaemonResourceError):
        _completed_watchdog_call(case, operation)
    _completed_watchdog_assert_preserved(case, before)


@pytest.mark.parametrize('damage', ['profile', 'previous-record', 'qualification', 'owner-sdk',
    'subject-sdk', 'inventory-count', 'inventory-bytes', 'manifest-ref', 'archive-ref'])
def test_completed_watchdog_record_only_disposition_refuses_corrupt_compact_receipt(
        setup, monkeypatch, damage):
    case = _completed_watchdog_unit_case(setup, monkeypatch)
    previous_sha = case['args']['expected_record_sha256']
    _completed_watchdog_call(case, 'reconcile')
    data = json.loads(case['ledger'].read_bytes())
    row = data['reservations'][case['args']['reservation_id']]
    receipt = row['explicit_reconciliation']
    proof = receipt['sampled_custody_proof']
    if damage == 'profile': proof['original_failure_profile'] = 'unknown/v1'
    elif damage == 'previous-record': receipt['previous_record_sha256'] = 'f' * 64
    elif damage == 'qualification': proof['retroactive_qualification_claimed'] = True
    elif damage == 'owner-sdk': proof['owner_sdk_sha256'] = 'f' * 64
    elif damage == 'subject-sdk': proof['private_subject_sdk_sha256'] = 'f' * 64
    elif damage == 'inventory-count': receipt['artifact_count'] = True
    elif damage == 'inventory-bytes': receipt['artifact_bytes'] += 1
    elif damage == 'manifest-ref': receipt['artifact_inventory_manifest']['path'] = str(case['args']['attempt_directory'] / 'not-detached.json')
    else: receipt['evidence_archive']['sha256'] = 'f' * 64
    case['ledger'].write_text(json.dumps(data))
    before = case['ledger'].read_bytes()
    with pytest.raises(recovery.resources.DaemonResourceError):
        recovery.inspect_validation_disposition(case['ledger'], roots=case['args']['roots'],
            reservation_id=case['args']['reservation_id'],
            expected_request_sha256=case['args']['expected_request_sha256'],
            attempt_directory=case['args']['attempt_directory'], expected_record_sha256=recovery._digest(row),
            expected_previous_record_sha256=previous_sha, process_scope='sampled_birth_bound_descendants')
    assert case['ledger'].read_bytes() == before
    assert data['reservations'][case['prior_id']] == case['prior']


# Production-valued cap fields in authored UNIT_DATA, using only test-local
# ledgers and scripted process/native observations. No actual 372f operation.
def _completed_watchdog_cap_unit_case(setup, monkeypatch, scenario='historical220-current250',
        publish_evidence=True):
    case = _completed_watchdog_unit_case(setup, monkeypatch,
        publish_evidence=publish_evidence)
    limits = {'same-modeled': (4_000_000, 4_000_000),
        'same-production250': (250_000_000_000, 250_000_000_000),
        'historical220-current250': (220_000_000_000, 250_000_000_000)}
    original, current = limits[scenario]
    canonical, snapshot = case['manual_unit_roots']
    suffix = 'ipfs_datasets_py/optimizers/logic_theorem_optimizer/autoencoder_daemon_resources.py'
    case['cap_unit_resource_paths'] = (str(canonical / suffix), str(snapshot / suffix))
    if scenario != 'same-modeled':
        monkeypatch.setattr(recovery.resources, 'MAX_STORAGE_BYTES', current)
        data = json.loads(case['ledger'].read_bytes())
        claims_before = _sampled_copy(data['reservations'])
        data['limit_bytes'] = current
        case['ledger'].write_text(json.dumps(data))
        assert json.loads(case['ledger'].read_bytes())['reservations'] == claims_before
        case['request']['source_sha256'][str(canonical / suffix)] = (
            '3d11147bbaa9bba35dadda391baa074fefd2ad9c851fff3a5fe2ed9542a072e3'
            if original != current else
            '3d1086df85ca33394c71f848e6bb45f954d369d2e977b9b73df92941f9ff4075')
    case['terminal']['reservation']['storage_limit_bytes'] = original
    case['cap_unit_limits'] = (original, current)
    _completed_watchdog_reseal_unit_data(case)
    return case


@pytest.mark.parametrize('scenario', ['same-modeled', 'same-production250',
    'historical220-current250'])
def test_completed_watchdog_cap_identity_survives_readiness_closeout_and_disposition(
        setup, monkeypatch, scenario):
    case = _completed_watchdog_cap_unit_case(setup, monkeypatch, scenario)
    before = json.loads(case['ledger'].read_bytes())
    previous_sha = case['args']['expected_record_sha256']
    frames = tuple(_sampled_wire(case[name]) for name in ('request', 'terminal', 'parent'))
    ready = _completed_watchdog_call(case)
    assert json.loads(case['ledger'].read_bytes()) == before
    receipt = _completed_watchdog_call(case, 'reconcile')
    original, current = case['cap_unit_limits']
    transition = original != current
    expected_pin = ('3d11147bbaa9bba35dadda391baa074fefd2ad9c851fff3a5fe2ed9542a072e3'
        if transition else None)
    for fields in (ready, ready['proof'], receipt, receipt['sampled_custody_proof']):
        assert type(fields['original_storage_limit_bytes']) is int
        assert type(fields['current_storage_limit_bytes']) is int
        assert fields['original_storage_limit_bytes'] == original
        assert fields['current_storage_limit_bytes'] == current
        assert fields['storage_limit_transition'] == (
            'historical220GB-current250GB/v1' if transition else 'unchanged/v1')
        assert fields['original_resource_owner_sha256'] == expected_pin
    after = json.loads(case['ledger'].read_bytes())
    selected = after['reservations'][case['args']['reservation_id']]
    assert after['limit_bytes'] == before['limit_bytes'] == current
    assert after['roots'] == before['roots']
    assert set(after['reservations']) == set(before['reservations'])
    assert after['reservations'][case['prior_id']] == before['reservations'][case['prior_id']] == case['prior']
    assert selected['storage_bytes'] == case['row']['storage_bytes'] == 1_000_000
    assert selected['status'] == 'released' and selected['explicit_reconciliation'] == receipt
    assert receipt['full_claim_accounting']['limit_bytes'] == current
    assert receipt['final_accounting']['limit_bytes'] == current
    assert (receipt['full_claim_accounting']['outstanding_full_reservations_bytes']
        - receipt['final_accounting']['outstanding_full_reservations_bytes']) == 1_000_000
    for key in ('cap_changed', 'request_budget_changed', 'native_release_performed',
            'retroactive_qualification_claimed', 'admitted', 'outputs_deleted',
            'new_reservation_created', 'new_resource_lease_acquired'):
        assert receipt[key] is False
    assert receipt['fresh_global_inventory_count'] == 2
    assert receipt['actual_postwrite_census_required'] is True
    assert case['terminal']['reservation']['storage_limit_bytes'] == original
    assert case['terminal']['completed'] is case['terminal']['failure']['completed'] is False
    assert tuple(_sampled_wire(case[name]) for name in ('request', 'terminal', 'parent')) == frames
    disposition = recovery.inspect_validation_disposition(case['ledger'], roots=case['args']['roots'],
        reservation_id=case['args']['reservation_id'],
        expected_request_sha256=case['args']['expected_request_sha256'],
        attempt_directory=case['args']['attempt_directory'], expected_record_sha256=recovery._digest(selected),
        expected_previous_record_sha256=previous_sha, process_scope='sampled_birth_bound_descendants')
    assert disposition['storage_release_established'] is True
    assert disposition['native_release_established'] is disposition['admitted'] is False
    assert json.loads(case['ledger'].read_bytes()) == after


@pytest.mark.parametrize('damage', ['original-bool', 'original-float', 'original-string',
    'original-unknown200', 'original-over250', 'current-bool', 'current-float',
    'current-string', 'current-unknown260', 'current-lower200', 'missing-original-pin',
    'wrong-original-pin', 'boolean-original-pin', 'private-only-original-pin'])
@pytest.mark.parametrize('operation', ['inspect', 'reconcile'])
def test_completed_watchdog_cap_transition_refuses_unknown_DATA_before_current_owner(
        setup, monkeypatch, damage, operation):
    case = _completed_watchdog_cap_unit_case(setup, monkeypatch, publish_evidence=False)
    reservation = case['terminal']['reservation']
    original_values = {'original-bool': True, 'original-float': 220_000_000_000.0,
        'original-string': '220000000000', 'original-unknown200': 200_000_000_000,
        'original-over250': 250_000_000_001}
    current_values = {'current-bool': True, 'current-float': 250_000_000_000.0,
        'current-string': '250000000000', 'current-unknown260': 260_000_000_000,
        'current-lower200': 200_000_000_000}
    canonical, private = case['cap_unit_resource_paths']
    if damage in original_values:
        reservation['storage_limit_bytes'] = original_values[damage]
    elif damage in current_values:
        monkeypatch.setattr(recovery.resources, 'MAX_STORAGE_BYTES', current_values[damage])
    elif damage == 'missing-original-pin':
        case['request']['source_sha256'].pop(canonical)
    elif damage == 'wrong-original-pin':
        case['request']['source_sha256'][canonical] = 'f' * 64
    elif damage == 'boolean-original-pin':
        case['request']['source_sha256'][canonical] = True
    else:
        assert damage == 'private-only-original-pin'
        case['request']['source_sha256'][private] = case['request']['source_sha256'].pop(canonical)
    _completed_watchdog_reseal_unit_data(case)
    before = case['ledger'].read_bytes()
    def forbidden(*args, **kwargs):
        raise AssertionError('unsupported cap DATA reached current scheduler or ledger owner')
    monkeypatch.setattr(recovery, '_sampled_open_scheduler', forbidden)
    monkeypatch.setattr(recovery.resources, 'DaemonResourceReservation', forbidden)
    with pytest.raises(recovery.resources.DaemonResourceError):
        _completed_watchdog_call(case, operation)
    _completed_watchdog_assert_preserved(case, before)


@pytest.mark.parametrize('profile', ['sampled', 'manual-private'])
def test_completed_watchdog_cap_exception_does_not_upgrade_legacy_profiles(
        setup, monkeypatch, profile):
    case = _manual_snapshot_unit_case(setup, monkeypatch)
    # The existing setup intentionally selects a100000-byte unit ledger. Model
    # the current production-valued cap explicitly for this negative DATA case;
    # preserve every already-authored claim and every legacy-profile assertion.
    modeled_original = recovery.resources.MAX_STORAGE_BYTES
    data = json.loads(case['ledger'].read_bytes())
    assert data['limit_bytes'] == modeled_original == 100_000
    claims_before = _sampled_copy(data['reservations'])
    monkeypatch.setattr(recovery.resources, 'MAX_STORAGE_BYTES', 250_000_000_000)
    data['limit_bytes'] = 250_000_000_000
    case['ledger'].write_text(json.dumps(data))
    assert json.loads(case['ledger'].read_bytes())['reservations'] == claims_before
    original = recovery.resources.MAX_STORAGE_BYTES
    assert original == 250_000_000_000
    case['terminal']['reservation']['storage_limit_bytes'] = 220_000_000_000
    canonical, _ = case['manual_unit_roots']
    suffix = 'ipfs_datasets_py/optimizers/logic_theorem_optimizer/autoencoder_daemon_resources.py'
    case['request']['source_sha256'][str(canonical / suffix)] = '3d11147bbaa9bba35dadda391baa074fefd2ad9c851fff3a5fe2ed9542a072e3'
    _manual_snapshot_reseal_unit_data(case)
    before = case['ledger'].read_bytes()
    # A positive historical cap is DATA. The complete public APIs must still
    # enforce their source interpretation and then the current policy gate.
    calls = {'scheduler': 0, 'ledger_owner': 0}
    def current_policy_gate(*args, **kwargs):
        calls['scheduler'] += 1
        if profile == 'manual-private':
            raise recovery.resources.DaemonResourceError('current policy refusal sentinel')
        raise AssertionError('default sampled source context reached current policy')
    def forbidden_ledger_owner(*args, **kwargs):
        calls['ledger_owner'] += 1
        raise AssertionError('policy refusal reached current ledger owner')
    monkeypatch.setattr(recovery, '_sampled_open_scheduler', current_policy_gate)
    monkeypatch.setattr(recovery.resources, 'DaemonResourceReservation', forbidden_ledger_owner)
    if profile == 'sampled':
        with pytest.raises(recovery.resources.DaemonResourceError,
                match='^original Source-held V5 producer or source pins differ$'):
            _sampled_inspect(case)
        assert calls == {'scheduler': 0, 'ledger_owner': 0}
    else:
        with pytest.raises(recovery.resources.DaemonResourceError,
                match='^current policy refusal sentinel$'):
            _manual_snapshot_call(case)
        assert calls == {'scheduler': 1, 'ledger_owner': 0}
    _completed_watchdog_assert_preserved(case, before)


@pytest.mark.parametrize('damage', ['receipt-original-bool', 'receipt-current-float',
    'proof-original-bool', 'proof-current-float', 'receipt-original-other',
    'receipt-current-other', 'proof-original-other', 'proof-current-other',
    'both-unsupported-original200', 'proof-resource-pin', 'receipt-resource-pin',
    'transition-marker', 'missing-proof-original', 'missing-receipt-current'])
def test_completed_watchdog_cap_disposition_authenticates_both_limits_and_transition(
        setup, monkeypatch, damage):
    case = _completed_watchdog_cap_unit_case(setup, monkeypatch)
    previous_sha = case['args']['expected_record_sha256']
    _completed_watchdog_call(case, 'reconcile')
    data = json.loads(case['ledger'].read_bytes())
    row = data['reservations'][case['args']['reservation_id']]
    receipt = row['explicit_reconciliation'];proof = receipt['sampled_custody_proof']
    if damage == 'receipt-original-bool': receipt['original_storage_limit_bytes'] = True
    elif damage == 'receipt-current-float': receipt['current_storage_limit_bytes'] = 250_000_000_000.0
    elif damage == 'proof-original-bool': proof['original_storage_limit_bytes'] = True
    elif damage == 'proof-current-float': proof['current_storage_limit_bytes'] = 250_000_000_000.0
    elif damage == 'receipt-original-other': receipt['original_storage_limit_bytes'] = 200_000_000_000
    elif damage == 'receipt-current-other': receipt['current_storage_limit_bytes'] = 260_000_000_000
    elif damage == 'proof-original-other': proof['original_storage_limit_bytes'] = 200_000_000_000
    elif damage == 'proof-current-other': proof['current_storage_limit_bytes'] = 260_000_000_000
    elif damage == 'both-unsupported-original200':
        proof['original_storage_limit_bytes'] = receipt['original_storage_limit_bytes'] = 200_000_000_000
    elif damage == 'proof-resource-pin': proof['original_resource_owner_sha256'] = 'f' * 64
    elif damage == 'receipt-resource-pin': receipt['original_resource_owner_sha256'] = 'f' * 64
    elif damage == 'transition-marker': receipt['storage_limit_transition'] = 'unreviewed-upgrade/v1'
    elif damage == 'missing-proof-original': proof.pop('original_storage_limit_bytes')
    else: receipt.pop('current_storage_limit_bytes')
    case['ledger'].write_text(json.dumps(data))
    before = case['ledger'].read_bytes()
    def forbidden(*args, **kwargs):
        raise AssertionError('record-only cap disposition attempted live artifact/scheduler inspection')
    monkeypatch.setattr(recovery, '_durable_inventory', forbidden)
    monkeypatch.setattr(recovery, '_sampled_open_scheduler', forbidden)
    with pytest.raises(recovery.resources.DaemonResourceError):
        recovery.inspect_validation_disposition(case['ledger'], roots=case['args']['roots'],
            reservation_id=case['args']['reservation_id'],
            expected_request_sha256=case['args']['expected_request_sha256'],
            attempt_directory=case['args']['attempt_directory'], expected_record_sha256=recovery._digest(row),
            expected_previous_record_sha256=previous_sha, process_scope='sampled_birth_bound_descendants')
    assert case['ledger'].read_bytes() == before
    assert data['reservations'][case['prior_id']] == case['prior']


@pytest.mark.parametrize('operation', ['inspect', 'reconcile'])
def test_completed_watchdog_cap_change_after_inventory_cannot_release_claim(
        setup, monkeypatch, operation):
    case = _completed_watchdog_cap_unit_case(setup, monkeypatch)
    before = case['ledger'].read_bytes()
    original = recovery._durable_inventory
    calls = []
    def changed_after_inventory(attempt):
        result = original(attempt)
        calls.append(True)
        monkeypatch.setattr(recovery.resources, 'MAX_STORAGE_BYTES', 260_000_000_000)
        return result
    monkeypatch.setattr(recovery, '_durable_inventory', changed_after_inventory)
    with pytest.raises(recovery.resources.DaemonResourceError):
        _completed_watchdog_call(case, operation)
    assert calls
    _completed_watchdog_assert_preserved(case, before)


@pytest.mark.parametrize('history', ['authentic250', 'unknown-current300', 'unknown-original200'])
def test_completed_watchdog_cap_record_history_is_independent_of_later_live_limit(
        setup, monkeypatch, history):
    case = _completed_watchdog_cap_unit_case(setup, monkeypatch)
    previous_sha = case['args']['expected_record_sha256']
    _completed_watchdog_call(case, 'reconcile')
    data = json.loads(case['ledger'].read_bytes())
    selected = data['reservations'][case['args']['reservation_id']]
    original_receipt = _sampled_copy(selected['explicit_reconciliation'])
    reservations = _sampled_copy(data['reservations'])
    # Model only a later test-local ledger migration. No actual cap is changed.
    monkeypatch.setattr(recovery.resources, 'MAX_STORAGE_BYTES', 300_000_000_000)
    data['limit_bytes'] = 300_000_000_000
    assert data['reservations'] == reservations
    receipt = selected['explicit_reconciliation'];proof = receipt['sampled_custody_proof']
    if history == 'unknown-current300':
        proof['current_storage_limit_bytes'] = receipt['current_storage_limit_bytes'] = 300_000_000_000
    elif history == 'unknown-original200':
        proof['original_storage_limit_bytes'] = receipt['original_storage_limit_bytes'] = 200_000_000_000
    case['ledger'].write_text(json.dumps(data))
    before = case['ledger'].read_bytes()
    def forbidden(*args, **kwargs):
        raise AssertionError('historical record-only inspection reached live artifacts or scheduler')
    monkeypatch.setattr(recovery, '_durable_inventory', forbidden)
    monkeypatch.setattr(recovery, '_sampled_open_scheduler', forbidden)
    arguments = dict(roots=case['args']['roots'], reservation_id=case['args']['reservation_id'],
        expected_request_sha256=case['args']['expected_request_sha256'],
        attempt_directory=case['args']['attempt_directory'], expected_record_sha256=recovery._digest(selected),
        expected_previous_record_sha256=previous_sha, process_scope='sampled_birth_bound_descendants')
    if history == 'authentic250':
        report = recovery.inspect_validation_disposition(case['ledger'], **arguments)
        assert report['storage_release_established'] is True
        assert report['native_release_established'] is report['admitted'] is False
        assert report['release_evidence']['historical_capacity_is_admission_authority'] is False
        assert selected['explicit_reconciliation'] == original_receipt
        assert proof['original_storage_limit_bytes'] == 220_000_000_000
        assert proof['current_storage_limit_bytes'] == 250_000_000_000
    else:
        with pytest.raises(recovery.resources.DaemonResourceError):
            recovery.inspect_validation_disposition(case['ledger'], **arguments)
    assert case['ledger'].read_bytes() == before
    assert data['reservations'][case['prior_id']] == case['prior']


@pytest.mark.parametrize('operation', ['inspect', 'reconcile'])
def test_completed_watchdog_cap_record_history_exception_does_not_admit_recovery_at300(
        setup, monkeypatch, operation):
    case = _completed_watchdog_cap_unit_case(setup, monkeypatch, publish_evidence=False)
    monkeypatch.setattr(recovery.resources, 'MAX_STORAGE_BYTES', 300_000_000_000)
    data = json.loads(case['ledger'].read_bytes())
    claims = _sampled_copy(data['reservations'])
    data['limit_bytes'] = 300_000_000_000
    case['ledger'].write_text(json.dumps(data))
    assert json.loads(case['ledger'].read_bytes())['reservations'] == claims
    before = case['ledger'].read_bytes()
    def forbidden(*args, **kwargs):
        raise AssertionError('historical receipt exception widened new recovery admission')
    monkeypatch.setattr(recovery, '_sampled_open_scheduler', forbidden)
    monkeypatch.setattr(recovery.resources, 'DaemonResourceReservation', forbidden)
    with pytest.raises(recovery.resources.DaemonResourceError,
            match='historical220GB/current250GB original resource source pin'):
        _completed_watchdog_call(case, operation)
    _completed_watchdog_assert_preserved(case, before)


# Historical proof caps are explicit unit DATA, while the live private ledger
# and accounting keep the selected present 250 GB limit. No host ledger is used.
def _historical_cap_sampled_case(setup, monkeypatch, cap):
    monkeypatch.setattr(recovery.resources, 'MAX_STORAGE_BYTES', 250_000_000_000)
    case = _sampled_validation_fixture(setup, monkeypatch)
    case['terminal']['reservation']['storage_limit_bytes'] = cap
    case['parent']['original_owner_custody']['original_terminal'] = _sampled_copy(case['terminal'])
    _sampled_seal(case)
    return case


@pytest.mark.parametrize('historical_cap', [220_000_000_000, 250_000_000_000, 300_000_000_000])
def test_sampled_historical_cap_is_data_under_current_250gb_ledger(setup, monkeypatch, historical_cap):
    case = _historical_cap_sampled_case(setup, monkeypatch, historical_cap)
    before = case['ledger'].read_bytes()
    report = _sampled_inspect(case)
    assert report['ready'] is True and report['state_written'] is False
    _sampled_assert_unchanged(case, before)
    receipt = _sampled_reconcile(case, 'administrative_closeout')
    after = json.loads(case['ledger'].read_bytes())
    assert after['limit_bytes'] == recovery.resources.MAX_STORAGE_BYTES == 250_000_000_000
    assert after['reservations'][case['args']['reservation_id']]['status'] == 'released'
    assert receipt['cap_changed'] is False and after['reservations'][case['prior_id']] == case['prior']


@pytest.mark.parametrize('historical_cap', [True, False, 220_000_000_000.0, 250_000_000_000.0, 0, -1, '220000000000'])
def test_sampled_historical_cap_refuses_non_positive_exact_int_data(setup, monkeypatch, historical_cap):
    case = _historical_cap_sampled_case(setup, monkeypatch, historical_cap)
    before = case['ledger'].read_bytes()
    with pytest.raises(recovery.resources.DaemonResourceError, match='original sampled retained custody binding differs'):
        _sampled_inspect(case)
    _sampled_assert_unchanged(case, before)


@pytest.mark.parametrize('fault', ['source', 'root', 'row', 'native', 'closure', 'current_ledger_cap'])
def test_sampled_historical_cap_does_not_relax_other_custody_guards(setup, monkeypatch, fault):
    case = _historical_cap_sampled_case(setup, monkeypatch, 220_000_000_000)
    if fault == 'source':
        case['terminal']['source_custody_lifecycle']['source_guards']['source_pins_unchanged'] = False
    elif fault == 'root':
        case['terminal']['reservation']['roots'][0]['inode'] += 1
    elif fault == 'row':
        case['terminal']['reservation']['record']['owner_pid'] += 1
    elif fault == 'native':
        case['terminal']['reservation']['resource_lease']['released'] = False
    elif fault == 'closure':
        case['parent']['original_owner_custody']['original_native_compute_closed'] = False
    elif fault == 'current_ledger_cap':
        ledger = json.loads(case['ledger'].read_bytes())
        ledger['limit_bytes'] = 220_000_000_000
        case['ledger'].write_bytes(_sampled_wire(ledger))
    case['parent']['original_owner_custody']['original_terminal'] = _sampled_copy(case['terminal'])
    _sampled_seal(case)
    before = case['ledger'].read_bytes()
    with pytest.raises(recovery.resources.DaemonResourceError):
        _sampled_inspect(case)
    _sampled_assert_unchanged(case, before)


# Exact qualified-candidate source DATA only; decoded by the existing bounded
# source-capture owner and never imported, compiled or used as an execution receipt.
_SAMPLED_V5_FINITE_PAIR_SOURCE_DATA['cli86c8'] = (
    'c-'
    'ri}X?NRJk}&*TzXC}<fQ%tpa%^{^gneGeR=WMPWBHMl^z_l_;6NlKu}uLSg0!v9_`kok+<gH+El&Dr^_ht&;G*tUw{GqA)fW%f&G'
    'O;tta?~h?~}#V>Y}c`+4}O!FAvvMQhr>_XOr0~SuNMis+=a1i*oX=Nj}V07fD@}NmZ<7@5|(UF`rH0XI&*lHBFjTy)4elr2bHq%h'
    'A@>(Z#Gun&NUX2M~*8Jt>=J`+Qli7x>rNY+feNpsH6%k>Fp=6?Ar){Li{x6-'
    'm8JCUvzcX4Pd`t&;j|t5}}SR?A{}l}yWKQdZNVS~a8O<tnMl_vJD<U*dzLDKFvQ*#sfHDhn9e^m5iTFvt<kZ|iJXUnY5ewqC85Wu'
    '7Oq%SF9}AyhCBnoF~_C7&(N7sawE<=+=Yb1|Qt%0K_v)Rp{wS*$MP@4Dem7Vr$3%O2hsO`6$xRm}BYE7eB>gHXTMr()UElPmReb+'
    'Igq>8v_e4`!F;*4E*{!BH}%&IT|`Sk^orj+SLp&)=7W;Rq%K>)9NCbF#IyH7(DQrYaWAMZFr}a5I?5$Jyoja=g3q=<(P1pDg)0ON'
    '#lt{*afKi`CWmr()ie!@aEp{x>^IR#%I1V7wp7O+BsaIk&?9EsI%GCchT*b-'
    'BM>*2_U^e3M)Po+YOx>;fQPG2xHXA$@&0t8hdxsU7Uk{H%nLB)ilKM=$4%zxmrUKmwj|GOH4LAyxpUW&9<VWvB-'
    'XUEwTnKSpo!mv3LZJRFF|b9@ME*{t%*dRiJEg=ade7VA|qoh{1=9FZ$rAVSIN9FY_bQPGrBF<U-k&FE}eFUo2Fzvy4y9Qf-'
    'XKYVfU`qe-FmwvxK`03!)tAoGGzh3|N>frg`hFOv>Pt##iz;Rdsnq2A;o|dpCC9D+oLG$1iBSe*|9t?-'
    'k6*%1g%YZ*uGsp4kN7Z~*y-'
    'U6rC%gC@zm<FU!`Nun%>Gs46M<@7t9M$jt0_>BbtP6RS(fMPd9h4*U6<wmtYK;80y2;fFhemhJSGFt*MnW%s5n~z)#zG?*%Wqs2D'
    'mm(=Edddv`Cu0L4(tnmhUtAF{^6+ffM6jmv|WSs^PyT;;*4RGtj{R#yG^aa@GYFPIf64n_8)7H0q(%Ogu7M5o!xG9kv}pUc$*mQJ'
    'urWez-uQEa-|@&t(aOvce@51OwN*Y$Uyy&d%Wv(T7-flcK0O3*tFyE{aD_p3?M37v)F(en7+L-'
    ')+MceG@Qfes)$a8!^uJ*bI6{syv$4#k8S5WcT!XbY89oX#>~UWdX+nF%-'
    '!{iZ|ADTVH3}qMwKFcT+e^@z;;qUq5bt{UmMOn|0N!7f9M+XN;>>d~R<KO)oQcsj1h?NtvIoi{*4cZ$)2=S=GQY(WB#3G~-'
    'Q4Pb{L2EfqDN&VVY5Q;jd$2Cn!AW7OOc_wJlnCej+2a8Iz^2(HD;W?<7~2aTNDi?1wkZ<&|Y(GnJ*6XC+s@n<2<%U+T`U>xT)pIu'
    '(ASH&q@xrl^fNaot}`5+9Pt}hqOKx|tBo1DKZuNoR>1`B`(dHhJup(-'
    'kI?T*T70)%%kd~llnca;)UWQUfs1zasm&D;y)`QiSvBfcT_|LgfH{`L1m{}#!To%-p{PVgeqod8OIh+Hm$f__-'
    'S&gs)<yg8e%n~Q;dOtkl^nuKYuxViPD^zE*0aqmimdwT!*(ZQiJH-@-'
    'cUhVmvGc19OGq`5vcB{#}Zc5ckQb9bK`J`ABfazEHvOHTi#e7gA&JfQ8)c3p`f63f14*yGm1;B;=2xzxmo}Cewd43KTTCpkt9gFj'
    '-Zh(3Hp1+nnZB-'
    '}p*;zTcngDq&*1)X83SW(oo%LoVPcH#b#~0QYPcK82bk7`HmVCK@u5)^no5NKHgDDN+p?Yx%%qfB#C#hurf!8dT@A<sQ<pHj4QkH'
    'Owr{*{ZG*DWx;V1_zzeI){&Sm<dC@<^ku;lYb=P<PfLp!rfG=LE>>zZ1v)*y6X1H5U?_sE>|0Cc=_VlG|i3*8uj4#YxaLtf^km=?'
    'Yhulg)!eX7@PEV@uAX1vs^Sgp!)*s!x%IiDh3hs%tbmD9XfFv{kqSF5t2t7yFf45;vS2LWh4&yBrmWHW1&X)&G7@O6QW>EZ#%3Lp'
    '@|<+=G_KD(T)!jJ?nm}^llKU<ci{#GE6K2vbc@EQq&bHUh+HHkq<0>nUbg}jawc4j_YxQNzg2pU#09s1~N?22_+hH$2+uJ|LM_14'
    'kED-fRHsWjn*U^KwOSbYM9{U&)DT*V0-Uik5~jT-R4UWrf9V_-l(mVi5tL+~Ry%Tqeb+e>knx8<sD8=oMf)ptBNy-kNh-'
    '_U4~$V~HPU9XzFuI5+nDQVp{6Dn+%9tEtm_o4nCTkN33<9?s~kUaYO>!;tC`)_aC@OtCHtu}$$TR-eWiqvVxBV#RRA1ZPZUXBO$#'
    '<UQZ6FqZ5WD<M*qIB*AdQs2}287SNAQK6RpM#xDLEpBan}p05i$NVcNP5K_SnZVW#3m}%mo|MR3>J^Nk-nXp5-'
    'ev?I$^fcTmtDY(B>mm<oHD5^T6G{KPNlGjfZQIat%AMr!nxcvEaK1m|kbil?(6!888(c`vRn*pn~ZnG1cmYc~AOp#%x561Y;aztV'
    'D~kWMM2w#)6K`YsVK_ni7s-'
    '0c+EY2Wf^^(Ox>Vft9cU%Q7#T$!sRRas?bXyh^aKwIx#YN!P2h?QhfJ5SI7x&Ua6HtS<^As}fl%*q~9fn!<!bQi}MPXsh^!NGi}|'
    '(r_y{W2M5OZxLY^tK`R`Dfj6otkB+8a7bHQuU`JN|NI}%U+w2_pZ|6L=V!<}ds{5;$~7R{^lDpi|8!C28pQsu`>&7QCddM4&OI++'
    'lpyvpLt{MWk>Fz*9FUjUe45XTbv3!LKjJqN5X!`Z(_*=t0i0zC7fDl^tr?cn!05XC2qXd|=II=7j7g0K0sQdOR(|yI=lz3Uj`E*g'
    '?!S7$)6ksEw4BUPZ=Xw+CZ#3FKLF0;s8Z990H^C!UCk!qIS*-'
    'C7TBlp8owy##RA5cH|3<Rrp(69>&ZLa&4&UoW0}ur4h>TEYNCJ&Dlgv7i>j3W=Bp(vq+Bp@C-'
    'G`=V;tKwhwD?VKU~Qq;^kHSfyVX`Iwk=Ws3CMZpIgA}XTZdq<xO!`BFU^!@1Qn=l<4^>P7Bw3u`Ge2z{t1{>)oVSHzn)^i?w;Zgn'
    'PYMUcqX>VFt9Q>YR~5PQ1A&;CN_-la^}Vz~L79`(K|VDAIn9mY#o>6QQ_*o|*)?uH@Ip2_ORUg~XC11XS3WqH--'
    'WJ*-f1^->}I-WTI`?OT-NG=O>QAxu|De>%8*p<;_dp!@Q-'
    'AfqJbuoswsgtsl=0daUwbm3E<s|GiDQOuUjfV6AgC(U|}EX{AWcpzBGEWwY6OT~}(ys^V3367H??FDD&tJtP%)EJ@;M9wY|vy)s^'
    'LU@w;w=#Fc?DUw%6<P#tWvxP0S7*SO!5xryT5wd`==f~W&{jfcaEsz0$Z6s8i@JU{rk`0t_C=tH6>`+8vFeAAmk_AOo{BR@EHZHp'
    'd_?^BqeZ=FLuvmDLzWx2Yr569UnS4binm%8$pk1_xx~ZHr+kLGUk02Bt8ESck=N?!l|e2>=6a@x<G{bY2P#;@$mNJhRV>H4$x0o^'
    'AmTjjGud_)5y<ug*_uY!3P2W6R~!mPWd3g8<K0g#Ly*%DBJ@>_)aIZJ9#OaOSh1+q_!{gA-'
    '3l;BzNhdCg9|K|ck@90P~s2Vb^1m)ggf@UBD)q+{nZ8D53^>4rcYef=^F4OZ4$UL*2Nr-<TiDah;EWo_-'
    'k^ZE(9?&z6WH_M2G1bASVPM+WHMJY7UQ~&418XHZ-'
    'w(j90v1zv%Mb7K7QAt^YqmS7AeOI2MM+bIajkzeL@#T0)*%43x=|NH}CQ$%RWm4h;aB=6vXj7&wD#A!z#V$OpvOaK{?o(?BDG>mi'
    'ZKK5%w>mnWhRUe{Huy=IuGB_g-GOcn>#Ie;L4rN0UfH`LOCZ=vIHm@#AB4C-OpK2^--i6wW08YF)nCp&GhG#AUjP|t|X=4BOY1-'
    't#tBMT-h)c`dPfW##l+>>-?_t7_xpFI83x8D_~6Ce&LF$Y$gFmw;DJzk-'
    '|g3~=iyUrQho~t3XMc<mytPz*B{ej007)q}}e|e#=tS}tLj%x@k?U6|xye>{+c<S^U*liQ3Bh0=!UhN;S1fUwDh07E%5B~mo|1f|'
    '3?C1Trq&?T<AcvEmOJdoK7FW1r#d=lqb+gP__3Jc|Vw5yJ%WFV<FYkvu+JeuQeoY4r-'
    '$~nCuEga$Y6eGf1#kp!Bysu3JEy!vZiLTDy_}sR(KamE4=p!0Ev$6g)wKiAI6*h9hv{r_*1#gIfE=!xd~x-'
    '#hP(I@uFGZfa9*Dy9$l36vb@aIi*!pWXVHQVkdD#V6m$0)X35uRTOFvrAEE+$NXG<!;W-'
    'KK^{|ICfKo)0xgO;uGR}IY4RX$!RchG7Ufu(0@wM%f*1XM^Ah6#ODa0$GQprEeRux>M0|J?uR?AFzQ;18FSa|sd8P;7bc@AUAk`k'
    'FoVCv6`*&IY+vI0kxA0~^$PJ?o?XocOzugL##iF$ls=DtVXrvT!i-'
    '7M*Tn3ju@oCOpflIx+1SR;*CqX=RtN641*i#GoY7~hRL8u<rX_WcSOgCjnNgbiDQX`ikq<g3++>(rQbz9CJL+#A$xk-'
    'r9T;dFVUR)<G`C=___+$utkCB3VH07-?4eE#vtC*{?GCoE&F23<%N+(BS~nQ$`O(@s<--'
    'VIIG4OK6h12H@;4Yi#zsvE!s8=b#~jA${EyeYaZ0yS97rUOk3EI!ZW1>&Cz$$l){igSA`^fqRCvzdVfE8$LO%hd&3<fdZYQZ#8SI'
    '>!A&fsl4^FqAx~Y8n!x@Qe^L1R+X1IT;lTJh=lR!VeOZF5#b$L&Q)x`S9%xqk*L<R&Wp$nMqx#4Ccu<IS&$VdwIK!xexIzO(}fpw'
    '1kjYGQb{=llQ`)nNpBo&+r^Q57%sL7h=ma#j8Z@AqfB`UXUlRTCWry=khyGa3VnVq!5cXl~MI3BIBQ~t9KwlRPq`TG*;+ScsgTaz'
    'G$_=XXy!?Z#1p07dcx|j7F?Mv|gJQ5v59Jhn|0xQz5R)i&uRrcFXhtX;PtOlMnU`1<b*Mt*WSoDJw!7lE3jhNKw1|u+6ur=tSOH&'
    'By>mF8m~3OV6a_#j~Sl-zPKab<dQbkt?<>CS`ajxhB}rdI6YJ4%#L+HWX-v%EQ%F8ivxgl{)b?A`Xdb`8-'
    'Dr6<)#Pz8$JBq|hVO7N$|pH3DhWWR`JkG8U%#if+R3Zz)~}Ks4kNywaH0+>5(Ns<wukr0o>>N%uv_fgR28nhO(OdU>LVYP1=@KKW'
    '$gzDYX9A$meQ8DCQR*pBs24GiRK^q9aU86$_l(2S?XZY!PxriMqj%*9Gd#$CS8jkhO`@6n<L4)rQmD=xkT&Xp8$nz704mM$Dpvg}'
    'zJ7BoNA%Xf(S_-'
    '0a6C@2E;GujyID9muV;_t^|EZz&;C!mUp^{SC=#GmG{PS>z#(Be0^Hs!qN0=DJq#X4{1^@@yVm%t+~uky=NZ8wxED%D1s%!PB-Ck'
    'v&yDQddpz^sSn@R-'
    '9M(@B!tcB_$b9OJ(oL>D?(ShWK8P9P*dH7_dtnYiib$`QD<M*h#b0hPH;Je612o_&EiXyIMwd;0qK?moJ{aA?M&n!H^z=6^Dm4v)'
    'pZB=5gD+|U1V`0Vvj{`}dSXU|_A{Ublz|LK>v&tA1zsTa$V6}CZ_1Oq5WrECU}PwzJBC}J@8U;G7x)gKRjdHv#Aun`$8*ju@Vt_<'
    'tGv3*+^+vAq)ExnGffBE^x{X=1+zYX8a8~J2*`C)z%(z5H=Y+i5!TRxV3X_@xfg!p2m^H;*H_H|aC!SZ^N1|bXqLrw{0Jy;7Z*Gm'
    '6Qe`WtS=m6Q~=D8JhBei^ldN`$aIih~r>S4S_qlI`wE>t+vt*|xu=B||{tZVv3N;|oW0ERmxwsBsg2jtFH%$HH$H7*$A7WyICF>a'
    '!e+!w))o9^N;vV?6OjJU4u66h~22SZw#VZ;Wf-LTNsXV3{?YgP9sYXz_CEklgIA@ymcJVO71ysuV+y8erQ4$huMt_#!vsV_TxCIJ'
    '(SA%jG!M`l?HBjXs4)rz7t+Xl(9uE>KE_gHK(^N5ezy%NLUclV2*;o65j>-'
    'K}>#m7$uw1G&I@X@f>C|oztv2uxxEdO>84TgQj9`7r*i@LWiKir|X`+!prss!&Al*$OHHom5&SV=a_iUd^0FdN_}3~R+R5U5d}A}'
    '<-'
    'kY=Mq_4~xm9URM|kOT&~=zCc{z(WG8Z$$6Ed_GxCLErR<@x@b@UHput$d2(J>>seLK@zY`fT>*YPfAx}WNb6;B3U6RtFnk`qn8H9'
    '=#D852`9d2yP&ZP{E|rP|C%#%<5#5(j`G|hP&oH?tm*q%K_}@gE9W#f?5&Wv&ORw9*(vIWNp(Kb?>h|mY(7ldLr5-'
    '{crE0+A*ZsKB%0zaW+c1<%`d+il1V~z<X-'
    'Ypq6tx}*oQx@kbwgiKsNZ?AS#VAGU<ElY`3h$2G5%3D<!oM@`(YON6h&hOIU=gin6dOSXpG*I-'
    'yaFsctwxLN!WMSl)1eDe)72mwFX}$`{abF*zU6>aCZ&L+Hn4JMJ&+tHkGs@=Z(wr1m4cs*I9xq3@U;IBazx!Dc90IjgXwwi&;5+C'
    '|t?6NdhRPYCIF*X4PcACOVBfDu%(~_`v<It4X;;TNe)jhzI57pwZ8!B@-'
    'mF0gq(hw>*HCHELain>YW#X35sGG|I(?QrE8ZICy|=Vyu1GWem5wGXjmr_8>+WjZ5}`cKf?h9kZ2;tt!5$3=z<tB=e=tI=ap|0*M'
    'K<*SfPG{Y4Avp26-'
    'D&x!nO$F|{d$^2nw!7lYhJP43Q8ymzy$cTVu_DXF6NF1~<9JN(QTF$WB^Lc#=3_s?iVe+CD7O56IMnZ!P5ufsWG^uID$%6C++eUT'
    '91;YY%2CF2OMq1+4I=AeF;bice(XWCD3zS>1gyEBjO_r>d#e~ixoWG&sYyb?sI4vgc@|+{hDeD9`H^{l=`c3o~TZ~qxIrT6)qw(M'
    'u=HQ6ib{mS7rNk@tnr;OwhUR+ZvBlCe9RaHu9^23`F!EZcW>xu-'
    '`3`lhj@1f91Aaw97PT)RGz!WtLX+CHHu7cWGV+rDZ9@e!E}1XjRZVL+&@?A#A7kx8y^?%E%9;VACEqPNAS*<3oDUTDTu9F)lR@Y*'
    '!L@ZH7s(aSNtO=;t@(m%KVU>Vetz~}`P-v|!)Jfl&wu>K(f-'
    '?(Eie+%#Es>0D^z3Y047)%%WRIrh#S>gjpr@HJd3$5d||mR#38i%C~WQ#A{>2`Etd^&oeFPLUyj;xlSi|U849+<LkYe%y-'
    'j0Y*q@Ajtwi&H)sC3U-rM;p^Gs-tfI4h5!3?DhhAd_<9eL8VcMMAaVgDL&{#CG<{>o%71Fvn9jeKD&Mu?D(H5H6maEMxI^_ELhP4'
    'k;HrMO?q6~IJXo|Qi^Qrln?c3ooE{;1~?z255Uwj_X=UQ1D1wQouhH`TV(hH&gdAEeiYIkAhV2Ur<@W6HkVeJJ`H3#CZVj6AkH_@'
    'o8V_RSy*o@p>N9=m%X{R9;?8Vf=)R8FSx=#6M}92zx1GJF46M7)tL#L(8f;j}&Em?6^%nxVzX%LAdh;p~c>AgVFLD}?tXW48=m(4'
    'iHRdC@epvssCm+vfEL7NRJNBFGpeYi0mqkw`l<e9K~ALp{(bKU>d}w=e#dP~_5bjoO}v6w9<6iP4qGWWA*PJ%9ix{$ulLNwSbs@F'
    '70wOlC7w$t*<_Abc=~ewL0pNE(4mgHN$Me@}+54<cZ5&TKYE6Q=si2<mBAf25_=hy}HoBG109E#DeS#OUpt;91d5Hh1H5Sd@8zo='
    '!44AxFWN@<<^)ZiLUXVG+-gu%Chfw9^*>NmDIG8i|GaWO)GhH(gyX9`kY9V*iMTErvoCweMw1ydrYb!UH-Mtk@Q)h-'
    '=mwoG1blr4OMMndnC)#v>Bjq7kh@{GYc6ueAo?PC^ia`%;_&zqN)@;}m_?ko9Kt&J07@Nq(SE6nx=__Je4HvHe@FuPC*Kfdb7#mB'
    '=7{m~xOv`rjXSc2b$z$_oP}(*_{}s@oo>oOpANNxfD&4<Md}5&dVB4rTIC1@L%x?_|`#{;#Op;c%#yK=@B>v;cDQ<kb80@m9z!7O'
    'u+nxEtMoKq>Z^vg?kunI#<SXiAmBk)L1rF?H(2*e1S_c*jrPbOZn=)UGR{(gS0T@;KJJ9X-'
    '|A8b`9*W_`7IXL;SY_l%jR5UGt?e#=GKT5YCfIM(^BS$W5zp>qJlI_fqZ#w>A2mb1lR=%5<F`*!!cM}3Zrs}`|HX=hp!k+(x#569'
    'kmoeYV>V5?}0mOT**iL0Opkm*BUJFGEl5WJCtH|emgYq~e}>EdfNaG2;tczeaGAMoU>-'
    'Lwg*wdmY_*g=Vjp%bYe@e98_>Hkm?uWNBQFu2YjsQ6;EWaJ^@`T)tLrL3HnXDbRsn4Mp&I0G<ti;pvYIMh$+Z<H_3R-'
    'R%K!&g4?J2IYB>&tS9uEAn;unl)2SKxS$zG+1avB`RW0<Mr2234487so0ZinZhJ>st5T1079Y7VTeYlT-ICkyPt6A<wX<CPF&^|0'
    'Qn44BP@a9+_0~Q(9dvh(ASHnBo~vIhc;b1LE=ObM(9n6I3yzPEPbhVY3IPHwc{W@k#7^$Musg36VoSCv`<m`Ji(n2YlLRUlg@;{E'
    'Xx!VffDc+3`~HZh+n*LRd6#%z^>W3d1Yt(W9MwXGi^i>-'
    'M?Qj2}<yeQw9r#^FfX6>EV*{pM+4e1bFT?IGPt<D_Z5HO$hCjg(4383u`#JSJ(^vF6D`7`-'
    'Mf;iEIO(qa$A)ND#2ZwvL(VF$d6gEg(jx`XUJG!iT?D8ZmyN10&R56zZlBDvtfAkLxi8|Iny^uQ(6hUImeYZxs~xBsi0Zk5UbO@4'
    't)SJr!#@k%8)LgyZC==t<?I`bq!otEd!BYi2n7*DCBIh%dNsv25%A`)FlO_0vZ%PCWUs3QdxnxE&!1f>=Q_UN))6^PIrxD4MmcD@'
    'ZhXq4TZ?DF4pjwRDQm-SA<w%-U9k_vbh8Zn**W-'
    '7&$%)=3BqS%&IE?2WN7LRr2V&(gzTz;}dJD9MC2YPFu2s^>p_0{j>0(2t_iz}}mt}7&xLSom^z48c14W$OOu8Q}7IJnV*-'
    '{OYSSERo>|2`1*|NTJNZX4adS%B*;+4Mq}(eG}L6V9TYMmF2j=v-uEX-qvsT*#3uaz%O$W#+B>sXMgEHjMSLgXzW{mat&R(jV9&W'
    'g4D-3xu=vw>x#(n>27~24mZ+&gyD8f2w08)4H18oyU8q{c*w&y%i`wmXo#C!;FtlGO-JIi;7`8D`G(mE}4o5X2jAju#ymni6u(<a'
    'LL0mq1swSL#qTHN_7X9D4;$FTq-o2t#0y9i%)Y5a2VXMT~_Zw;1}k%?~@{7yn1*6yb&@$b99-'
    '|91PN;hk~1Uc`#}*Mx{2!!2=x>mZfq<;HR}h@VD5Y)VpyFM1y8Q^n&LuYQduzTDcKPa?yg89sM#Imn56?vGs&bX*)b;JuNSi#jFa'
    't>6!rEscCV7FQR}#C)j6ad>38`{y4H3o;Q;Iz}qFOZJXdLNrB^tr9nq`8;-7SWg?TE-bdQDT_g};Uf~i4s)6o7;_-'
    '>quw`cNW)({6qJJBSw)~P9ux$aS4oV5Zkj6=OD65rh!ivYnoO|7HL(!~pn0)DzFSF2H_2{7`wp9iETGykQH{QZPX~0oCY#DG;;y6'
    'NtOL8-&QJD}J-WiMx{KbrjqC%uaPcvgYS!!|=)G4tGno99~Z&-~e+qQ`l9w8Wq34zjynO~cU%aw-'
    '3`owb?6nqTzW4kW~n+wmcVKAX#pta?|IJEM#d95X#G0|pdW@}@26vW+@U|lmE!d~?LlITFt#Qw7L7Iz>;AG+D9v)TE2DPMWM6z)|'
    '<Rt9KoWY`O)-P3W3=0oa3C6me0i+VmaWidbm5S?eu1u1(zW6-'
    'S`sV>%_E#{UMm?435HD5P)Fl0D|@FTn;cY+86y)`G&?c3bj2kFR81RD5SE#rxOJL+a_t80JMs(i1`YOSmd;t^j%n7ft{k?JZEB4S'
    '-d{(%f4|5~Gni$Big52`uIKe2wI_&^j~<iBM3MHek_bV01(7qGTCtY{?AM>kISqY6*{$c0?a>UboOS6LIAAFJ7(aEV9xjAwbGYHO'
    '+&xJKR4!(w>{-Dmbjht$51T#Jigjff`q)J+YW3@5+TtQ*cI7%SQ}J6foxJK>mCciPlg8MXY(oyP0HQk-lBZDXxqLSuN)du~SZOZH'
    '2YiAbh+ElkSUVii<yE0c_U!#Wuet5W4Gl*Kf=JUNU+`yOfr%M9H9fJMC7&y=X$Qii{OB;@Yx_vI43A*bvIMP?2(TvGi*SYQD{YgF'
    'Llq7tfEjOatQ03U{x<*dpUvLpY4shQTR+1#joIeCXxKW)}^wcV&aY0-eYrO~dTEH`baVmyH`I&-'
    'A@1maT5S03w$w&H=zSSK36Y;wA+@*HM%jE*4VvCS<UOKaUjv(M48T+E9}Ibbg>biz7Or6OVTcnQbXT7hUFZ)$cR%1mEBBCsub&+M'
    'oHBuB473uQ(?Ca3gjU`&`-K<tA4*xd=^-H7cGcy2jrOwCPPR5!J`M1!KSXz28v9x(hto=Y0hj*Xd}u=Fy0r-BPZL*BBK=-e7-'
    'nddF@^gnv_^4EQkwf^rf`)`kw6|-'
    ';A0~^ZA*QioGIQ&N|oT#gtgmrZI?D^mJUjUGUH~YOjA$%AVVs!A!;q(3c&CAzs5eg7XEhYupNWTal*ugJHZ+<zFxuD0_aX?YoEYT'
    'j98BXA1-Z_4g(H|XAyVCS2F9MBK0=yB}i=#DZgyn!9Z)Y!o1{;XL9FHx4;TG*!sNq|opzq-'
    'W+^3;8>TolLiiV_{ldE0<%<?3UtaxKNUp0`xnd1-8Rhb==TNf?{NG#jHv<HgqFapLl@QAflPM$m-'
    '`PLxA!NQ=HJFWH7^8f1gt<4foTVuo`c<pn^o+?j&6_5{tATlisk(-'
    'NvMs~mY<f~QU#X+U_so%^Qt!mx@JvgMkA9r~McYNNqjA0l~^~lgNN6JT7=w@hR_I#h|)&etLSe>=%dvV6Ob+&uSj+?bII63VB5Zt'
    '%DBwYXvAv#mcSxDi#50h)P6d$`QG3H(@xEBlV#e#dWpzEW9!xt}KKO<KD@Y&JxziuWXJV|>%d~<m4(@Ucs=y;Q=fA?a;z1VOsHhd'
    '<rAzsU~kKoWzc=0wx2UkEybms+pUrj8zV5@_-%dkE|Q<fDPEYH||y1AGw$hS<ocYV01=aQ$Bj3jVCzq1h0GVMF$<Bz-'
    '6s}G3Sg5HW4(OWujQcA>^69t7X;lKvgu|`^=h^>Tl9~^FZnL90W_#ZQCC(MAX#`jq}@3VH^M%K>hta&HgJQBhyGoqj)S*Pm;U}x@'
    '(yuDB3`FYcLHs$>6At%STGI~-B4-*vj1A;9R_F(~NfvS@!JSNYQOp=$y`joO+kXJtt3PEesDc2c2?~{1mC-Ll^#8aT4u2j~QD3d='
    'R{m+Lb#*Iu#1*DxEF`EDb^~0_H{W6Fq13BS;&%~f^hR@$V-'
    '6*|hd(KTSY0qcL1F9to7Y3ExmX69mkl7WJnE*e75HHoSF|rdg4Jf_tktGzfDnf@0jZS3GjI6DP6mcq%IYf^cC-pehT#XZmU+~nOR'
    'GMP@5fiOuw!5M2jNg((lKloPNcc>XM&E(2ZZM4nh8)?soLtzpj4sjE_58MIx)WyB*8?;Y(OeyFo<<!r>Dg&kF_X`RS;&8q!@ne*#'
    'RbXW!7x@NWpK9+mS*Hzhr`;~D$*8eVI|<S9plD6j)^wuF!R0a?B?>lS&Gs3;IqHcl~Y#mnT6CMimAn6)~V`fBA{`#svN#iM{d)j-'
    'jzlFBXjrOXUqNk*>VH1FKwA}&GUVqEccI`EZ4mO#}>KinJd?%<M(-'
    'T|Ks!I3Wsz)E^KyeiBP&MK2mumvzTBo;VXPOgGK(AS>(|Am`#W@G4(eG;7K;&lb?Y{M+sTx7V&uOg$S9^1EwQ<ggd1Ew`mb9v#pi'
    'NFOr-}XI>Ij@E(2r_0w-Ul2mQHNW)-Ih5d~zxTPNj*Td}_lWKK-Wew&;nc{-'
    'rw!6XE8?KEeA!9)ZL;pZV16{~xwrp06N(pk~uIa!~=#B1`@t;u{FXhN$c}{xafu)T{98CzjboH!kc(0QGw^PaAtEvAVQd84G%h*6'
    '6<;31f-'
    'L{sxblT@oMvG}gG|j^Na<6E<S2X`lie~1+cs3ayI`Nm*JyV;2>N%4Q=(Ct^npiQ(UWprUEKuKCMrfE0?J)=yB7GcwCsR9UdglX<Y'
    'r|8#b3piAUZsh&hMHsdN@}AQn!E&M$!K~blnapzEjUK&oeSL`G~K0o&<sB~D1N1KSE$0!>9Dm+{_NQPgw-'
    '+3X&5g+{8q4dHoh7WpE}t&P(jI10tHE7Er}PSQV7%a<)Rr#ENOtR%rTIB%o2W6E{Y|(M>gX@nxSa4mkzV`M6Yym=kxjlT$Ytk@?x'
    'gD|E|)ZtZ2}t{EJv3TJyzR$1dSWo`wYP$W>#?Ope(UZRu*Pij~Q{G+3)Fv$6zA!A-'
    '#c5iR^#VhLuOD#yEY36|C>IDmUq`Ms+A^Qg+>Nt}A9%;_}U>&*YyI`dXqZE4UqOs;8S!F}Pmdxg5GP!|>4u86prQekdG2;{>gPWf'
    'x|=8i;7@=)Ov%b#?T%`~7^$YsbDjTtw|Jy8?^7j@~BF0-'
    'n)>3}_iAHwla@GUaY_+(x;$Px*!=SrFBH4t=h#s$UusE}^ai)Bek>Kha)xKN(1dM83HxYnIGBaKQ(j-'
    '~FJ^=SimyIzUJ_Yx_jd!*Rf5sc`Hppmy^b)MmmOAPEl*DlzVqG8TOU_VecJQ9;qtYX8ClJ6>5;pBa}MAWzasO3v>!-'
    'zKHRHWc<a=8vNN>&Ul^|H$1QigN2+5{!{sfNj+S$U+XWEsY+pu5J*QMMShH`MDs1=iLT`LtF(o+LV{r4wW-'
    'L?9!K2X>r=C#&X;+2V(Bvb*!>@z?mDtt41gBXT&rz!UY=MbTVfOeVLp`Ws!8A4N$9vL(e}E1+~O!^WFs+zfbu1qj%$LPhu-'
    'k06oMJRH5aE2}DmUq5Pp{kZ-06Vu>Ch3v+jJ&kyYoAhAT-NHU>6r{x)1jEkTs(Oa@!NU4Y^J4{|P?pbLHAaom1csxq*~;_lN$cUZ'
    '0(D}!WrrQG27U6=I_L>YrE7mMvmBAafv|3p5;}I`hM}_*z1qweHIfdZEl0B^S9Mv2KCw{pMI3^ZH@IjlX)1;;^{_v2IaA?C+0oA&'
    'dB}mY4pwqP1KddX3(CrJ)(dhL<Z^m8G_-Ilh%a6qVmK>onCw~u6-'
    '5`ZZmdhGh+1__g+B!zr&l}iPZLH0#RFNkc=Z(PL>WPcnoF{f#CQ%EF)b&v%VHkF2XTo>_R8v0KSp79Cp1{^cq<16{l+QX=*Nf}DY'
    '0#aUgyV7+|=cX&Ry<gD^FtS%0t3}nY%n`NnY;GT~nA=V%wQ{ocF-Ulx;_ww%plU;mV8>6v@WY_rR%2sF%BKiHF0sk+x(ZS2-'
    'TKQjqIF3!}_{lR8CfI|A9hqe;fIUOCFmTiQ!Uu8=vHBfM9}Z~NB&Yz`4NJ&oqzPGr{Q(2>+>xK;Y?tyqq6&exo%gxrapkvj?JPS<'
    ')6k)GR!ukv*#Zo=-'
    'NKT$DBo$A;z!>d7rbz8y8I11*q&!r29*OF^5lD2BklzD~XYR@F!pV|SMdvMb4lHOS3=zfGMj%YDFTZQNEldPnxAcX}Rcb*C%<=Vw'
    'nize{!>NygVQt)bMETPeVhMp8<jo#{@hpx9(G7vECDwA$xH%#v%MfRj&$Rm3pkpg31{JTx8wgoAaP=Aw?WC7E~XvEM0E>mewFam-'
    'u5vOf3l5}V<sva=yVm1u@_$0I-'
    'lF16B@sEQ4fCA&RKF@_lvjse04u+64vvar(Rm*54F!O7Q>A4XT5w>NfUQr%$6O9z)Nr%H2=DH<96!!Xs6-'
    '*3vEtaOGcsqv1*RR!J8{wiG+-Zdi)oM6SBOF-2IhfZ+tBlukNmPB+c~QwjsVPOzh5b-3-{IDa?<Yltp-~`QZw#rUhDDr-FgX};<7'
    '{UAxeE(Wdp&mL$mlsShG(Un8e^wReJ41(6JN>;G#Ph!UtVYA5`4rH(_<H8d)m4iduICU<FJ#CH-'
    'H*Okn=ssB88Vb<`f2o*@7_NrQyHscnWYIR;yd;NI5#ZJvumi_LqI(>CkenES6s!te7p*UE;KZ6_(;c5NtmSWzP<dLofpQk-'
    '|_cQAP~*Rt%umG=#Pv&e*thxQIHnfym$XVyn@5sqq=O)XKEqDnk|9att$-'
    'RAp<fS_qvHgH?QO`x~upL$MGDd%RaFuu{P*n)bOB3f(cL_d11pox;6N;a;cEKSSERD&bz0aIZ?ZS0&u568?i!3DL|unjv#}-'
    'IEqK$lDUX?W7v_qW8V%{huXz$HOS@MQ|a4x7Qf|odoi>2$p+^{9Yozm&orW@~$i?_d@x-P<}6z-'
    'wWmULivBJP~H{s@A76bF8Cyt58&41^ias|y|{iauK$OK>j!^-4QHxNLjNi`y1-'
    'hdbiGKnS_Hb_vehv2`IX24BkS}{QT8q>6^83Te82nf{i8(QWFzVUHV1R$DXEJVx8YK+#d1D_N2+qGlgsZbnNl%JK44)Z7>vkefs~'
    'A+c_|pRzzt45;MgQ}8~KF9$|!;ftjt&+pQRdZreEl#R&dk^A=zI@{#w7_VB9s;1AjO%-'
    'lh%$>M=p|i^1JY{_i5ouHr;j5+=11=}gjlCBh#|iO?a#Q|2`Jf>~KDG0PjQEzXXPqbtzTIai`<))9;s5cvEqq5@#cu@MtHHs@s5Y'
    'z(#-'
    '%^JQEG55kC%uHf%egr&*=|B25Hi|$M$ac5_<hQ%uJ#vQZEc!`{@UA{GwxwMfG{pT|hzGnAQD5Xw9s8Vp<OCS$U#$ZmpG)b4xq_QX'
    'C#}g}B^+*a9HOUM{-C8tRw+6Z0VcXl-lURkIOwgNe!49Y<3{3yhH@`Z+zS++PoUUD@$G4tUm@@#wta{6%eSZS_8@6$Y^Y}Ys-HVY'
    '*`<r#L`xh<ldv(9(DSPBbXHMK)%AoGH*uSpA5<h5U}Tlh__1RsRoYRSEYsm!)wiYYsOD|sc6ho5I4lB5jb<~c7iGx$>gWzbQj<k3'
    '3^B^hVxZ}Zk;K4FgK|qI(%TiR`bt&9t!qm$H<4i4rI)*qR_;tx`6_u?P0K}D;e9}5o{8chk<huagyKUvEvzuF7_i==B*fN+GS9}T'
    'j2@*<1~B%l;D2yQ)~nfk%dJ_mC?@alE}=Z)#0k4z9C&zIJUe16@im-5(m-x)F}^^qe{<wMS4!9?KQ@!Ml5jGE{g#FML?fzzig-um'
    'PmfP1+fVokKE}gC#RAMR!1-Csi%B_1N4R7Ufp$B=Y>Q$EG?kZne61CVmg`7E9Z|aXo0K(ZD?t$IumKtf9oi^2I-'
    '6BfdNnW>Ai$NIK-?WO-'
    'i`Rg;c4Kc_iC;VYj$TfQ3k#v1C1hITwFC|!#kUO#A@%D&KId`mc04vKi<B4{_Iu$)64%l`sGmGD<PeuM)PB1y-'
    'rl!h0w&qIlwwb6|N=FxvWYvs;e`ZtVXdse@}Xr56oc$k2<k6D)#jeP?0#rD2?0OD5q3j0y~jko>E_nb>7VDRfre~JELMLxY<Um34'
    'xiGlX-y^HOr5ya*13$8oMxhffgyuw`fx_*(0NBV8uP?4;J-&Hn}o5wq-'
    '3w9@|e>Axu&{*3DwNE;q*AkpR(k5*r>96y_(8bXu7m?G`_blaNN)7wcxQ`W7#M4@Q`6Z7~=s4HCB!TBG)i@c2pk-ye5&QlcC%W&D'
    '^HfquXPYp4OF#vT=7AA1YMSAsF=K#P{de&QP+@8XIyo$9XTV>{WMr-'
    '5erGr>%&RAFH`D^b<dK^uG$C;YLxM&lF*veNAPo(nNdj;VePc)svsz3dQx{H3Pz#fh5GU7=pH9Ko3l)t}_BhPTj+Mh%Dm1Ke))hk'
    '$m-$WM1_da`Knal1$4TXQfSA6wr=M{QPS^H$v2JXp?v^@`VbFLu583%?ij;oAyt$ezUEWB&WZ-'
    'l07@j)dJqXSev3!1!Uv!#B1nQXAKi!Su6wFB)kGF~wtVXSpzTT+e&1hldypvzS#O=fR-'
    'y)v5B*p3*evY^HQNY{Q1NEgJHFqC7_GHbo6g(_jOfdUSk!$~xFyRgMnf?sTg+QmWpzM)gkAsXfdfo0&kg7AIr^xfT0|Z~Snau9VR'
    'u(3Da^!a`t4^z&TnJR^pZ-c}NK-'
    'pRJVgTIA`n<X7%`!wuQX}QX|&>f=+MFr1vFvGYivJ`TEJ$BWVA_WY76n<wY^X!*hIySd`SfSMoRSr(+{CHeC#jQavy_Vs-UxO9I3'
    'pYX&E${teIjhBXEz2sdJ`WIV%Wt<ujlP+)>Q+0=_Z&cO5*p&V%lNwO6UVW4FHIh7vcr~UnN{M3aZm_@d#0Ap6BSPaY>O=z?&%7?9'
    'U^217CA8QS>DT7u35S!??wEQKXq)B;~{Mw#?ZUC_p}FEjm-jTKMfB$w)Fui#;AWBc`G{(ygp{_bsIuRHG|oae&%Y%4V8lVf%C@iF'
    '5He8qXOyql+6mlUw2wIld_r?c;mJhosN~Erp;5@Xya;8e>2rJt|BL_tFg5|y?7fn0KcMlq}q2}X<<@f4_c&0y;1Tn13<Vd;|dR~q'
    'uvs-ahYtA?Zpt-I(p;pmUwLXD^OkXVzQDljSPLxv{nxDs5cQRKoE_>Y%*x1m{8G_sV)&90h^x%dv0NdQ1;>?;_lc60-'
    '`tOlPqbc`NJq{AMx)9R-|)Go3<3O*C}Rf;3RT$2N9oo8@s2dws^J`V`J1uq-'
    '#`VAu~fH99ka~%hl`*_Pfca>m{jCiv~VgMLEXL>u1r=#{y&J7OUh(Xt7T}tx7v$%%YNzs32twQq~Q^p(w>$v~ZOA8>Zh_WzFumlG'
    'NJ^)O#mqvkHqfpU$c&hy=~|NeTSDsCqAzGzn`&8*LSpj^;$VMK!5kpHMYjEKP-'
    'O;cs93ZJQjt7j?7RX6iOA3zR%c#O;fO2t)F(a#_n7UkTq}4VzV8*Qy^Zn<`ci+y1j8hcN69y?T>Xoj@x<w^;*Vxe%2!hgjvGS_>?'
    '-7gy?2SV<DZc!eb#z@nHf8&ZPXm6|aIl}a*iId?~<blvn(pyCc*FhW1ha9npLd?xNJ0^(vbx6o@;SBw~g+#I5}1gf2f8peE;8k_X'
    '~-'
    'a(334x}Z5EC{OhD_RX6?|k>vqgcYw0Q9Fp<Qkx*Hex;SzNJ3sR(nWAMv?DW03`X*AVrEt_TSMcRTWhfz~kM$lTovn&sNl})PCUHg'
    '%`p`GuI{(7}C?nTOqb+0;d;F52jkEl5}VH(KnBuJpI$R-'
    'xa45=$3=RtTqHtkIV2N4v($J(7s`hUt@|ONzq%?4Ib`1ARM}#ewFMKF<2~1ac~4Lo4j~-^bFOfKprV%1z=#kH-'
    'K560r`Rcu#)%4JjBkjnx&nQKjIf(uq8oQ^v;(x+|$b@Xd@(ru$Tm!DVMS~FKJdp2|cL@o0UN*$gtFBIrl^$&Gx{E!Ct*XtqgMupB'
    'w|8*cSVuCt%`49~+Z6iDTNanDmKfrc-Zv$r4*ZcAAC|VoB*Su~<4iT-'
    'Ls{K1W1gjtvN5F47Vm_#2PE*N<^jJGR$&+o&8>p=bT{yHZbY-jlJ5A*^$3xh)L?Iw2Q+8@h%&YW<?SN9O>95Y%l#m@00X+pSw@5V'
    'p?3g11wsaLYFmc2~=aeYAPitPKigDNB{Q*gFz-2~(HF=Q93tJw#o&u)Rhj@VlqT`sKty<rj7RZcINj_9WtH0jvV7_!0(7&H-'
    'qHxE+_4+i_*No(oGKmlfSbPuG=ATva~F+TreolE&|e;jYN5J}RcuLFyHR^nC(2IQ<5dBTcdL5`<GE6cr#WZv4|HPri9-'
    ')mdfy$Pv?s0A=uWvAP)VI2SLV(!8D!V`~9*ZfCp0Z8#!6mrflZy%C&~`_-'
    'SVN_1kGnf2GT;Z5cSju4#hjLcgZIRys_!qUNYq1r6c8634$#9`>NAc`Tx0cIn=?*$d_hX_#13uyQ0H{U+?eQfZeB+I{KU-zs%qgP'
    '_n9_$YL%v)a(YK)3a@ki7iz#=0DkiHsMy1`~g=b@~Q{U&6#QI!X`yyYa4IbB~a8bjI8)XP;4Lu*(kg2S&r<W*4#b%!ljX%FhHfWM'
    'f})@fHkKI&TmJ#{}fXSBgM^knOnl-?mYog~y{SFGDk0Kt3XWEgxEa-nL46*dzMO*W*rK}ewA=6-^=>K}OPZh_bH1iW<*K-'
    'ck)FU8hX(rsXFgQt&ME>A8}yz4NR&iExbchssIx%Rf=C9qWLlj!uEpb(n|IMejnI%weyi`<Y+9H&SU)~=vJ6T?&VSl##((uJuMK*'
    'FQ~SN-6omM8;r6bAc-CA9*EJ?Mwz(br!;{l>fy#JKDg9t?u}zngmN?{b<kyOuo||1&u>$B}cH3}TqrXCy#aW>_1T_=j)|vCTfjVR'
    'cUc*rumDJHt4xDqCyhrm|XaKoagZo53y@>?H~(o|x=Y!4<;=+Hg&db5kWDahZcLTJ6dYNUiuFAwPV?4E&K1iW}IihUVb)XQ)SfSG'
    '9;YtV3+?>uppazIg%SyRAKZmt}{$N)9_y3b+LhTDHEWfc@6B(t5Pvte3uH%Lr#R(|GjF_Fx3PD#17!t81Q<P>^pVAxSwe7H9x8R0'
    'OUsuQd<HS=TsTPTt`#n%JjD<<scmzP+@kPBxC~otUm1ARFZTuv)qc7y;)jWr&wotve1~Y+Wqu5#C8P{9X#5@phRcFEEiF?uPWyOt'
    ')IH!#J4aU%Y{fw&m-'
    's&y`2znnCejC4Vc+1=*0bVO2VMZz~hBv`tTe>7G?USST>CKokFBA#$31Wg4G}VzNn^wUgUautp>&OE{Z0bX%-'
    '+zp}THuxRmLQh9}BG{VS5&V!MOhg!-'
    '+zt80SUWhK7%nUvhd8XA038p%c$e9RqgfXc#gTssF>9qYUSScRcPlAVCsKbgfc?1J@gx!0n3d4p=*_}A4=gPMxTJB7a6yK131(77'
    'T+p>^xR@j0PwXn8tt2k>)+u9qopWM-YY;qF%<*mBQGt(xewC*VhVYj$}La*#>9!k*RV+L=cd+xGscbt#p&T^4#nKpN6HMz|^B)Wr'
    'mJ`&$oJeGxI>(&Z3+*%@%jWav?A8ed=IU3e;i}{v&<XI+m=XyajzS=()y7OtH0Gsge+moD0Pqe7(ug=)*dDHIEh5xBfw{70NEn~m'
    'CfV%6((@7+2jiOUQUy&fXTaTaXQ7r&Zl=ae~$qwywY3`PpvsSo@i-'
    '0YY9&<!cTqt!^Kq{@lmK9WN1c;dND24*oEW=HKzp&Di@)8!vaR>U}Wbj+usQjr@#g5D75C$*SMG4NmYc8}pU2B)=%?ly0(%8G_Jv'
    'gl_ys!HmT!%|&=UTdlGi+OTbH{zTTF3jM1ih%|C}e~5hPirbG;}U2kS+gbU9Sp3jhFR@EFtWTg(YU~#Vg!%SbqqdKYS=?n9I`WW2'
    'FQAe0LFjPGW8&QQL(wVWPX|IiDL*mH{pk+Zn_P43r?*7bfbqpS7P|Lpv7oTbUO~4I5Ro%L(YV2{5c<EabBzCbT<#kF1W`={4BZ&>'
    'v0s0QWkV+=DaWldcH%+dQOgLjaLv1*oIC4S9m$=YjB44LcU)>aQbXno|k}UpPo<s`Ti+hu+LB1Q4fJ=t*Rj#)0XjUJHDrr)oU*eD'
    'oNpf`ODBk(R+|N(Islpp3>=c9f*Ki|E|Qn#WS+xTH1GlIZQUd_S8IX_-'
    '~R2tecc6qX)h(0s#gYfEca9bSLnjcFJlD=h)0)*5dd#k%$RBU63ZZ{tu>dKI*kTU!^7`RoV|^<&!vBx|8t!#ump`Q6!~)y<LlVS`'
    '8ydxi#HD=d)5N_Q~wK!|?Ett=Rv_2ntB$>bqhOga1sD1@%WqgZk#!^Q)PWjFX3Ae5KuOUl60TmcODxh%^-*hH~d6hQh7wjWRv-FP'
    't|Ek9e&aU7cAwxR<xV@9*_@l8C2?T}OaUzp;oLfK!iD2&hcBGYGfKm=OtfwZAqlVgyZJMJ*rGN6#($T-'
    'pOLXIP1yu;AATDHhMu{M)=5`tuJCw(m5#P-Mb;eVi-_t>)&-'
    'MnoEp>dj67Pv11;$wh730QjfPa+88v~gnH;fQ!B>m(Gj@=xifSC_z~y%P^2ca-'
    'v#vv7s{woELMj$HnDBYH2t;juf9Ufb_#CW!L*>nI)*9c1Dpbh$!;u%sc;gKlRy$#3e*bq*g`?ba2t{8RIxse>jxS(C$OBnZin_F}'
    '~*`<dnCF9<Eu@uHfPD1kaVX-FB=_*l>XL^?b2<8IzguW+0b_g}|(anaUYZ<{X{jnrK2WJltyp1mK0WdSkPH^PQ1)aP$JVyPboBB*'
    '+7_i%WF?lc<^=lC|m(O$#plt9eZ&ZserAU@bO3?B|dduV<^&^<9HX2R&1eJ3c4Z{2Ouof{<F2`AXGp?4?S8TO8&5!y{xffdz$hH{'
    '07Ha?wJFE&Z7srwf3xKhQ(l#zn}N|`w!2bmlm@Y!ris%BoCk^jrGxtJ};#L@)ZM?PHCczc#rv&N$5<WvLfMIbO#Orp!*NsfA3wBN'
    '>odR3n-'
    'fY&Vwpoq7E)Usr8S*6$4L=}V1_ww@=&z{I$`SHtLdl%m?sqhuC$Rct}9BIcvQR{2_CDzE_@5Xa$e6Ca)Z$x4g+h+;B1G+I=CGU5Q'
    'xOPcQw_%UAc`nI05UG(&Q6X08nh8Z5Vlt)(%dT}8cdyS_uatsjtk^iRdgDF|IgY1w>xlzTet#VJafU&*a_@hAVtSsbR4B@+1hX1Y'
    '5)=@dlB!-'
    '_0+IR`XAZh6Jb3c&j|Z~~<*Jo%oiy_KN7m@~qYWCo)b=>8LgObIbq<)4TLc4VuwDYkeTMlvEV=@W1aKwEd0DLimF8CovT!m9&s+9'
    'mI^2KuLWGw#$wfJzevegG2^+J7n4*M=I#W&z7M>Hq?<e(SvR*cJ-W-XH8}2}4`L~=z=HqT6pKXk@4tm<SyD83wu%#dFW>E}?Jij)'
    'wKlwL9cFgypZbOwY2`HzH`-Q}GeF6~S1-'
    '>81bW`djpMY&d`s58!U2$M8i!00)1+6hnm5~K~Ra2KNl)_PhNf*;*l)MDeERsq6&l=YM40G%kz`s<p24n*X7s$6fJNPLpdbf;hW2'
    '59i4o;_{K<1Fm=-ccqZg?ENM->8`VmPSCrLAD4_&7daFHvw$-n@MA5H*qTpAQd(>mmtk_2eBueNBjwu+x14vVPKVvM)-'
    'z^?vt{b+(`UXPs?2+$43Q55qN1xzHwL$&HV@SeEW{ty1yPxRtT_vaaeCinjWA|Fp)658=}&&I?v1KW8u7??qxKnp`6<FDw!+j`wq'
    '{#YI?aopC<b97t?rrBnXAILu_SUe#x3!mpp8Aq@6NrSl;rsBP(iwM~lI<P@&S$pzLu2STwZm+<{1mpT`eh=5TaoP8?8mz9Jka^R`'
    'k94MNiZt`R@g&QT$Dv@yTqFAFCB?g@(Y?ha4`S6-'
    'v14UROap9ij<u1|?W|Es^!o#62gz;D>0e?^xEA*@3&2KC|pb0PnOeLOadI!q^El`mmw{lWc7>j*cQvOF#sa4V$qO)f(Y+Wc#k{mJ'
    'UWb9;qRN6wF`%z*)ou_EVNA_jhx^~9L)$(f3Pa!5wn#v;9tWU+G5n-'
    'U$pG?oud0tdzxwi0G3>AfDw%)H3bU1IA%vR~0XqAHmHlqu6vYjA78>t6_p_@DrgBk*`MeuH~p<TDYm#pJuL}v*NUQ)pR5h5A46Wp'
    '@(8ZDmuW~4q-F#u`>jA@qDw8ui3tD<@`il5o*z%YT758zj(J{Sqy5A3m#H}CH-'
    '0$gE$E)EIsGxZ)&rsNXNNODmle^OLQSuE!>Sc~!_1x%eMYy>bsVH79suMCAE93K(2;lzrH$iNy`<p%^J_@fDO9wR^h4$KQ@*N!(9'
    'n)JgFGaHpm9!et}h#PmTfDW%Ys!%d4KDCrd&=|oNm=B8{Z9EU53(M92VGXD2YCCMCy1s}n*V7X6uOaBi#?x2m-'
    '>|giog*FHYA&^qoSvc;(NjByK{>=(Tzr_p@wTKr?-'
    'scWM7Sw3T#wuKK*YFjB&AO>y~RT>sg{cwXw`!4iDl37P{CAZ^B!J1arEtoU6@H)mWBJBrF}2O^h8LlGIy&XduQTM)rpD~=KJ4F|2'
    'q2jU>jR=OLym&?#MAM7g324l_g39Ydgd?sE2tuD!_)4&O{n>O0l7P*>xFy_(r#t+s?u3F28n7RrY66XWtg93s_lm2DfF-'
    'K`KUBTVQ%G>SlFook_+q4>Q>E_2=c|nRoWc`GXiv-dF&*YmWZ*nT(Cg!~0b-'
    'HYnuYr<lA`ZLBAMr&gcCA7JsjIc1;3ew7@Ss0CJa3Y0wb_Ql_ThSOnsD2h>2;#^^Q4?vpEit`GN7)Zu=KcEt6BJ^4)Gp!ekIjW4|'
    'c4NKIw!8t)lt$NDhfwa*epM)g#V)Q}nNqov1IBa}hP6M08&IU*7=-'
    'E%Ggfmln7rR{v+xng*+_a*Iq8x805|6|)R(JR%Ym8$Ile@r3_O5zJnLrEOwiYLX~IDo$Yn|Qg4;o3smhNlS-mvlL4U^4i@X$8e&w'
    'br7R^Py8pO5SyHCH?sX;?Yn0br{l%Eb;YEO$hFyJuC&s{$xSs&X84K>}1LuGoE3mZbU9fN4JPV9ZqcSn9~xfQn-mNL7%hRd=V-'
    'OtbdD}Q@*aQN&m`}vRmINE<3?afI0DmxZQ9lNu?dPTg9{~2)Y=)1naf6oyghYk&qGD<nAb4>cFFug$x`{9U%k0&iPZ(CNu0zp@1I'
    '85>Ob{3iLE?E8oY;a-'
    'Ugzl@W#D1!{!Lho#N0h2TF{rA^V8bem8~A_<u^oqxtV94+q<IPXE(vEOrG1igeE;x(JOhGCyGLz{Y6bmN$95S=^)6^Sb>4FRvdd!'
    'm4#XK#7V^5J9B0@gMyN_1EHc2mQ6uRvTAaL`25L|f@3czY8tSsGPOm1yD~3@*tqZA_(_{Zb_NTN5N7ugI#heZ8j7@_D`dBq9p-'
    'n(08xFq0M#c=}4yg5BFwglr^d4h>O!6a;p4sKn%Ft}f7{o*nSC9UKxC#hn7-'
    'v4X#Ih)z?qxq$FXAcLgEgtdcQSA3UX<|Mg#YvBVJ2X=Dv7kyUK0t>3HFO|;+;aBqMA@ky%+{tcXp#8xp5aa258U$g4Iz4aVwza3X'
    's?htMZw$*EMSL-C12e)~{-'
    'VzZRpF+=ecKmNeAu==m#CQ%oVUoT1xhIW+}Au2&`PWb7V|(q(}oLl5d?Qh@xabed>v4yFPT>A%d}89D60@(gZgj-'
    ')}|gJ1Yj+MxRamD~zK!vy9oFs_%g0W36!`Srx~K#j#3CmTRM-'
    'r<vhM2;g>Lpl8RQb!TyrzP%4HMge^k0eNGmL9y7Z|g>aOb_9{fJ;rj5vXUSWL3@tdfLINWajHHOc4lgLCl^ZQs&|8;SbK`kaOl+J'
    '8XikU=wR(3KH*)BR9cF^e7CG=?fK0p)%lzos#L7y%-'
    '7?)QY2`5t7_om6xLROJmaXIc+|(#x41ChHd!A%K>8S*;%<H_RQ=swtB#twKWq|dv+$ki&!h>S#Z1lNn|DU2WCPwca>vU*41QQ0Fq'
    ')z8}mML*k+0#L^9DYE^#qI;)owOt7*f>rXq<0O(&SCvd5l8PF#>GiO~m-'
    'fO;3ke@=cvd8`7}^*{iS?5C9Y;F}57fjVC=9nMsTbf)ClfZ>8tgBpVF>sjGT6(MUrq+WFLwe+H%Pt6=(s!XXBHY!#~EP!+L-'
    '0V|E^4e`NpV0Z!z>LEOH|TubP%0%JW6r)F`4tw;h{MopPjF(l<b!mCEj!?-'
    '<*{!ut6|%^*`Ku?b@@5E>`2H#OgXV>wR|3~AE{n4o}vTLd%~oAR@MCDlISx2T4Ojf{y3j`0dDZL!hmpY&;TnTzQ%3MD@M<JBLDL6'
    '1xI$>xN$j)K(x4kE?XSSDN=UR9q$!RTE8McIUq%&xB1Jrhx>mSSZ!%tPTITTB{@-'
    'UHP*}ZOc0%#Zh;d19<)+>Rr+mkJz~)N?5lWAYgZ)N*<rm=v#ZrSWNX!k9LpQQ6K-'
    '1)G4D*wHj^{V42^{~k^p$qb6mi~!9Cq!eJ(@BC(5fGhc4k$$rtfr+h{BxJ=iU`p9c8%KW+rza}MPD^@%E^O>0&dwV@5iV@x2*Dh1'
    ')@t9T*d_Dr6~GYmFZpf|Pj0>(JOjPXkd)5@Y$tAL<wa@eE#xFZ3q-5*=osnC~N##)f?-'
    '$VBOD?x09p66GewU)NAUTzWXw(@>BD$YsTTG_9&s$XkGziU+UyJ00ir<z@#3V!kGeO<u(!hOAp_5}*|89UKdug@9K4eIn=qefp_e'
    'ZG$IcUJiBRp46}^=>QXtww&wHM}1<onW*^&mPRGSSI74fHlP>D!tEEKwq)`gAdR$i(tDRmJZ9Jfna+Yr#^ed;Jc_4EceH-hJWr_!'
    '2Wm93)370+2f)uVPLr`6xXXdu(7E(uOe$4e7ol6oz&a(S8(HEUtYqFV5u*s+?QLvMOS>X3qHk4eFZ9fITFr)Lbb2>g8tEKeVH}Bo'
    'E^Wj3ST~=_N?#KZ^<*Sw%2t_ds&seWMMDAu9sidD^ShLugGmBQ2%!*>P2^Vys}r8Y*0HjSo_PmV#3wIz8E{{bX)4ln5y~inlO3+L'
    '1wwUl<j0JqjBS<573J;JcApS)@s4(&ca%4b+!JG)zo?yIlFO<vz=>H<+;mRZ?{z2!7lC4qq2i4?BLaPh)^Z>wimv5UOxCOKkZo-'
    'F6m(9_s`-'
    'f%*+IkZAQVYpSkqY=PmRgl4$iP^WfGG30X9=E`y~uPC6FJ;Rb2FdnNDQC`q~h#m1S)eM5H8ZPF1=I=w8tr0jQ7fg;{Ve;dCcu4)r'
    'pvzg)CAvXpbyJ|T~HP%ZM?uNe2-e@Cj@*(IxEi>PZuWRGJo_(98^MG-CyqR&^gR@fkzS}I@?q`+>mDqrg&q2hK!Sq0|T@HrP4sFX'
    'X^=O%vv#2FF4l`;hj~Tx+ZJD;A-'
    'j<Wj4J+9BqKU3w*Im9YT)ob@rH$Hkp@J#8Vx8_sRjzXj*QvU7k+OA8)jGFWovu|EPqiAWS$F5P>a<x#R;s&Ep}M~H*1R;vcU{zut'
    'JfK2#jah>uB{%NQ4TIr4UT<R1GV7(D5c;?pB5_ww^1E9h9s-'
    'NeV!t4u^Mn~CE&vA)thk>)pj=t{_7L;r(*t8$X~CBzmS@|&xb>|j8|r*ZX4UqlfHUuGm*zHySG`nFD+^r>Fs;f`Z9Bfhcnv;3Vm6'
    '1zP$2Yh6u%FzFMn%c|x5j%Y|+#v$B`&N}PV3$zR`SsX@U5msu><B3MJv2;;~MnZvnk;)(hDmjAlLVq|`KF-vT0E3egEqRa2eTzmr'
    '>J-'
    'A5?ty?bQ6(~P+!_q|2id(*{>KD@LQ!UGeZw45drC5Ru+5kBbM+U6!@FX8@{EYPG)^4|QmpHq!SeB@j_38I2m4(;7G^KV_2@4kc3f'
    'KBF3e0i+yT~%Bw~7IlZ11O_vDf@aak_4;J@JB^<$}dPywM$tPVF-H!4@5MW4FkZACuFk{@(4E-'
    'y<Ui(?ePQEb|JY4Ruq$f?DRa=J^XLjU5e*yWG0tgZH}49z;agTQ90+qLQv6@`o#^)>iK02Gu_L2YQNHA65{hQQad_+~Xz%Q66-'
    'cL$PsF6@trbk&i1mxb^1R6w=P3g-X&1L9tcixMyex9gw{=pWMl(;f+d7iAqxzC*H5lRF5<3R2>S{m~u)>8K!2l0FP5)$|x{(3-'
    'zURK%>kO;j-'
    'r^p?W_pEYf{FstxN={m$j6I#GF(VpMlri^?rUwOI)&msS{r#itn7OQ8a0DfE0<19e(9WKO`NB9_Y*+~K{lXsS>Ep~RW-'
    ')AcH^&vFJwfUMW6Wife&uEHTl4`Xz83Ca#rbHH|Hfzoq3X<ZVhrC<F}*#`VIGM46(KN$n=u>mH0Vy(y)|6Hi2`VflP7F!)>WgCpo'
    '(l3e>o|SW8EP$<>ZVJWLR}L=lR;T`bZ%)MXxUfPI#Ta$x$=Dfa0B2o8o_=Lp38hD@`TmD-@_6UFr-Bo{A{~X2@6U`F9wYL|%9G@E'
    'd*x%Oe&b3>IWQXU8hyVn{7@^oPP{j)mMhti3x9m_*kbl+-XLH~-'
    '^>`P#Mhok@+}r5)WVd_G(7&`*lB!%X=24AYRY*a$D+B;7vl(q&c4!HXLVOgetc}L=ZVfP<%)k6c8X7p#c#RsWn*_g=o9hM*ctP&F'
    '`Yg*g~9e2=FMzsQh&qp3^R8Jbl$xSOe!Z@o7)lygb=OltrZW&o@3`u-'
    'Wqr^DyH)5;rD7}V!Qe86MG@Iu3rG~+Qt8TGiY16Kf^E|E+yAlIj%>czgsQxcjE$o*DLO)ebM?=^$WSB^(pG-Sfg%zS8i0!FPiN*8'
    's_&$DB{(>{>e+8pUPisM6t=TMoejhcd4wofu(+$<k|D1m%r{CwNJ_=CJ!Z{rNJ^Cdwww_9jTWkXS0vx)USs^;2uBPY0SbX8Kdz<N'
    '!*1SAxIU(xO5n_0U~`a3VLAB;Fj`|q%TAPBKG$kCHpd=CWUO5n6db*#yE&XrW)i5ODY8?(>UQaj41PcvaUedL*5?ox}2R?__(1GP'
    'Q~;+ih9Xux%yD5sw=E{-~h$fH5EciC>gdadWMxyD11xAx&k3=-oc&}vrD)n2+1)f@2t71CR9v;WebM*i%2|;%lA-'
    'RT@M*eMfs(N@Om4@NU1$#87R4y!ioOhsRqjC$*kLgI*n5hO<S#aQi=x-B=rq2i`{irY}wW0*fy-KvK31sCI<aOcL^0E44OZB00;9'
    'rIkGnkjJ{8x{re}-Hajy^!4uSbUSV(Y_vcNa{kijko9TrQ4-SqVrf%mCb>|Nwou^wSGS4`V&oK%z3jD*gb-_oAt8_@&`Ua6vP}dJ'
    'nK{_w1Y4cE3!+`Ic65C2u(dN>^nMaLqWSM|e&cG)xYOES5XN;5_N{U%domAkQm7IwzwoxfE#WVHR4uHO_al<lrcM1QMRl7Ki5v3r'
    '`(zdgLi;@jesWSoYQAl>eK_s<vvEl=rEf_dT|JoYJxo6$mh&@Z)7-a%Ay)4xmk?SrEXQ9*Wl-'
    '@^wVE|EvBEhnUU)oMZf!WDzLARdh@ey;2BsWd7p<C>WFp53B^fACK4W!!S9Un<&FqC`fbGjDgJ7i|_d?eDLiza^5KXyUMK_uP;vR'
    'sN+Fg!R7AZ9GZ2r_?sk@oTtta$!mS>V>>d78<`k)+eA0$ont&oG-wO>?F}o3l1rp3m!3;EZ5d;JmyqmW>$f@Y<EY$VKK_#Rl*@v('
    'kW5U4R<=K9vQKNfdQSP@sb|{^7Rsz7rpcd3%UK%ZDL0Q@vM3Qi!)_ULlR3MMw1c9POxs;fPZXkvhvvICM*y)$PRULAunPY&}~5e!'
    '@;-{Y4OU#%eh}&&(+(3@_gs<lMfkbnz-'
    'e%?>)d&lTU9dEH4|&?}ic{?Ez25y}*QOP~?jwP5v4)vjWoV(oq~7W{Dk?f&7f&yHRmyncH(Io@w;**;u*(V_>sr5?zJ1u3q3HEfW'
    '9-n*dO;y6@I#)vu)-a#r{b`RGuH90!lhbCx(`{W4Rf?18QsRJ>Lc&2;N!19RN3R6tgf-qb0|M{C)Rh84f5N9JJO5bWpjg;al!MT&'
    '(-ZRkJx^(%OcECb3FmWa9q&4h-XM1C9<O1t6sh8#IqQ-R9DB*|@APj($e=vtf5>N0*3{oq3f0_y8jjX769l6#)Vli{br&-'
    'T^QtgHTMvG@?aLj6TGGp??XuSaAOLKi%zhzm1TA;j8&d-=>ZY<1F4Uos?2C~y$tiNpRu>NrvF6-'
    '|z^ya3=X<(=HV9Q#B@+Rbw4z{878+OnInUFn55ZXzZNL1lLbR|{=J5=q`{n`_T!z1e+-8Jfl-0^6xd-wFpjvrOdN?uN8RSc*jS`z'
    '5rU7mb)4#NzF#II)}NJ}7z%#&4oAR{#0liW@;+v197l(>@p5-'
    'tj=d}gTrb)|XM95%AhG$x)bCaZNZH+7R=F<nkXgl0pws##OBUFglr7Y~i#mGTTW5F3eAONz4<=C;HN^+;7!cJ8YNZmH?48lA2&!|'
    '4buQG;E|<$Id$rp7Y)awcogj8rkCz+W$t(_*>A+S(rqmeZB1qDl&@WI+;!us2xCw$6-R#Cj(pG!PcV?O5~^J5-'
    'dFoP+;HlMg7x;Q+){3J=ngo+ClOXSD2T74CF~t0>*pK~luTK<~9Cv{;_Mr_}w*&7PlRe17nQ>iuk4S3ns>!dE=n`XG@Sk-by0gj3'
    'n=$w@Jy30F}U!M8rEeL!j+govPu)X@+}%DZQ#6egxhNBWQ8bLC<~7>PgKy)jdKSi8f^0SANdaEWCOr{CkzST|&jr3^ml(9MiZ8-'
    'eB=HP(!6H@w=)-=<n$o|a2aRZ5^nZ(si9X#eo%EYW}e?d7Xiei~R_6GJ1cow<%(XS);oS~`UT`c6HuY?K1y-'
    'p%Io#kpSTj0b9H>X;n9;Vxd)^}F?gR?k(QHah()uJJrzgnaOg<1yqm_<_E(A&a5a^Z8&HGNRsKdHf}k8J<VYyet=k(aw{h_7)qVn'
    'sOlPGd)pAdCd`YASA(KiwEpcQq0LHL4;Wvv*oF$Lysv{U@rD?7wq|%(%mUPix*3@udmG1#@rh_H9()72!QxZ5DaFkM0?66<W#Flu'
    'y81NqS9KydhpHT9#MKaB7e=sbiCb*<L6h&^J1~0B+h)-i8GVH#RNx_UA=%?MW37GRq?KTh>5=v;Q`l-'
    'e8cKUn2+_23_Mh~ZhkVt`RLBG9w9GXO$T2JsEIkP<jdrNNa%@;hrrAt6AMiAgXBwoi}wn@3^);Vlk%+%2JH+OVLO|DodMtGX7eXg'
    'M9rK&EG_@+TiGXqe$!ooNi*2iqx>Z~X_@?vKskAO$xVkc2u!)3FTYQ|9R0IK%LIYfm%8EUrSi@-'
    '7wZ+~sWUYv10ba{;4ILWsiJZZ8P_+n+`U|vgvAAC22g}TdU}(-'
    'p<Xz|<3}!5XJ$1*CC47}tCSVI$&|MiB~nM8Ro?r$QoSM|z(>dYRVY7DrV`?t#oAIDb(&Es9^%DQOzti-(AsGZezT+CFN<_9;QJ_-'
    'c3Up(wgClwAg%N@mgD1|x2R%#dt!C<mvU!vN=*Wi%nBOGhnTllxZ0+O30{?jz2u3R0)e+Xr@H~(iN7iPFFqnTvJu@$W+VJN08B_+'
    'm`6snRnLs}$`Pkn8HF4W4L)RvNbR&Iw$Mta2NIZ@Mi6=`J`Q$9JG6(%w%qce{pI8xv^+k^#2-'
    'K=*3|?B8hGqDaEZ{5J<51R7Dm`y+qO))Ijj}vCxo=XsZvzdsR-9Ex1&#{PL-oXct%qRL>QDg7=4@uRzHG;T$09wB(Pjc=kyQ=BOM'
    '59TLagLaGWGKF11Fzy*+YTYt-'
    '5&yH6c<j1pHfpwSuWbpnMuZ8(zt{^l14BA4quf@&&<K(buSi%B_1|NG<44sKF9Jl=b<`zTPbGnHy41J3_|I2?zw`{>&c97-'
    'Ivr>2H~R<%=ZU2cSIgbprS@wpo)dLq9vmtRy_flGL9`47&ysp%?g0GIayOb)FRZP&xyUkP6&FZ4~YSf9>C8FysTSe&OFu*!L;>p;'
    '0y!#e?u1$Dc+d;@b?uT)a!v`JX6ldzQ`VX8jzv0f%UzlAF_=maR-{etT^wpNk;>n>y9qziY4YGvj~7aF9l1nC)h?T&?-'
    '2Dk`#Fkd$pMt$9O?G{OKj9jG5LUn_=*JLb5iweA;-'
    '=k;C^EGCBd_!*r$XYFD1a+L}(|VHUL*q*f;m8Z|$spa{mR6%ox^eN$kRcntQQk6<kEH@zLfMuf7Z$LN{;j%TY0sW>krb#Px-'
    '%vlbBSjiIFgHUz8I_ZdHc(oH;4Og-!eFOjG~f&%B~0aj22pPm-uAFUFfYbRE+dq%sHb!Vl@+7wdIc0h2y>8>w?5MOO{Q&)xr;y10'
    'j1dk&aIVM5M#G{&T}gz?cnVSX%;b`u5@bCx$k%hw8k9^J7FmwJ6vb!F#0ya|RypYh+-'
    'gQFKaMD4i!a$sQZdE>^9JuHr!R0`sDwI+scA<+@pcJgr3g`BkzYqgg8T(1$z=4sYO(R?D(veITg^#F&%{n)H20sPU5p+<U;}jRds'
    'U!00Ynp@t=y_@(#+@rHrIc&0NBdHCzI=g%?JWd-'
    'D|;JQv?Aw4hCl%mCe+_Al=T_Q{2Do#A93;+}f>A$6bCiTGpc0nHQ6((^S>}1m0bvV3{dURx_6Iz=(QK2{07Svx=OKHnIG+o+XAs4'
    'CJ9O!H8En9eopI46yTSNzf6=MFWKs3L$)AGYE7uxpCXI(q#i<n9&9)xgPrhDJ&^hXPkPTLnPz<slpWZb@?VbJ8eGd|`7U!1uKX)T'
    '7!0PZ@jNDf=;xsi<H-Y1!rN=G)d^XoX^Rel87S|?06$y6c*`BG<AfR}zY1=TE&Xu;_><PS04AfZi{1H`z0h8qj6aj-'
    '9o3hta{#bdKBJ2;O2DyuxySajcZ9cG@c+RzWkfxBvhlZ|wR!V-B3!teyCVmT?XB%4s6E-'
    ')~dZ5D86Ra00MuJ%+?BnI12h;SMJ|5la@Tj8uY|A$=AkHk|FAAoa!o8(lenUEoya$wjft~~TOW<a2lBQtZd;efO)rH6s$N3z7)8Q'
    '-C%Z6ktARF();q0f4^?Ep)1DvyCZId8Ul#_3NS3Aw5T2))3T=CRyn3MAHIFG-'
    'UJLAMQ&G~ODGR*LozFxqAsn1yLJBC^fq7MYI*HG>yuWkxgfK5EQ_YS1-1NNFwlfr|Ghv-'
    'eo4w&0hR!#OX6`N&rJ7%#LCiByI>;H1V6eX3Wv&|syRr`i<xTnz}d$RTBRpjlSVVJvNpjML-+Cy2O;UQCR4%<%hxjZ9scC-edETM'
    '@nKek#o6+I_<P+G${URbXm}<#N4XJ+9a^lru5&IT4cqTOKn~e3({H{iW0+xi(6LE+bN&irl^B`&qrFTKC+3PZ(P5?o|K74m+*>^X'
    '2O!v4>hS9n@a~37*uXE~2et$z|MDbtrQb3;k{ar=HOG_#`u;1xbIS3gw8+lErbvpH{&fcjN6UF5`h!(?R-'
    '_<aSaDzi>;`=T_KpV<saK&7vRQw3>{bWvm2{TrgKj9F6{UPp-'
    '`7WuIBn2U=dC5sMgp<{Q6=#SRoaiP*t}rf^b#{DpH6_kgf#`4VKm$w(sO&qWn34mbhCc$ARHyt%9&qS`{~UX>pLig#=?kk`l1is5'
    'GY-'
    ';dpPWdRz7@0Zlm(C>ICIWad~zJBNwqsX5$A8kAa1p+vO2Y@U~ZG&_=bGP%)W4YI{PLFt_{Z18<AWoN4YwEcCbVIt62{J>>Jt7rRm'
    'NfF!80`j@!oR+c#oc{E2}sQq4_)6ufC5#5@4iaju9k2C%&*u$n#gP*B5?)K*F{}5<mJb1F&9FK76AtY5ALc<EOD*tOT*9Q3>Noaq'
    '*OtD2D|Nw{0yUw*MW};h0Qd**CAvkvz3Zoj20bE_9Nxa250N}ye+=MR@Q9<FiY}YD)_#OglLA0vc$Vy3)Rn-'
    'Xz%&6gv2W#JIj?|W-*}$_Z!aVk-S_*fU!%FOqQYXEv4il^W<OUvfh^d3WBW*Bak4iVztA>wPlILZPuyCid<_^f^a=l3=zq7MO@ER'
    '99`3~0D-'
    '1MR<F_E+E$2*_r#WnK6k7`n<Jy}>(0qbEXPe$T$%KB?Sr0iA(e&4@R_tcZG;#}?X~#$0PXQq0aCsS&oRW$U&Hw)GAu`?)q^sfeEJ'
    'MWi;!C6JfdHN6=v#RjcKzeMmxau6DlaLlQd(UrXxyAvpz{0M&H6BD&m9$r$||~LAbkuUsz%495p`=Q*Mh|-'
    'qidarrY~_Xls8@@e%?saj5CXQ#cE-'
    '5%44vU)V3;iM>CeJJS*dE=rj6X^9cF=tLw4yJA&(F*&~9Ip=_x*JK7E`vr@`4&&u>zG2zfXMRm}L$f}WsV^wk)ZiGECoHg`wIfTn'
    'e@wGhQ&PZF!7!ZSrxqKUwOK}6<w<SW40uOOK1|1^(|cA{@5fprAwAK_Lh5;^hr_tu{Nw1a2e02eJNoOmW?KtzGwcC(tZXfr)hXuj'
    'Lc`e_=p_CY=A>pYJZbIZ^}#Q1_YdE`JlY?pAZ7Ez7YDD8{(cD0F!1;J!3%yDg!1yuPjB-V&yJqG-'
    '9LJpzxhZ0^UK#Se}48VfBEy9gTte@^rhYC*)K;2`ODXDkDk4HHBNWh0NYK^kWWdoqr+#f-~M!P_%n<<KltgVS1(`F0EZccV2n-'
    '7diiEQ5D7!4bF9zf7!`IzNJtbCZn9&){uB9dUlz@~@lL(-'
    'r$2=RGRpKCm&hKWt4*80HY6r4+1~AU=!8lteAWzi{MPsZgU0Cemoc88SGWMGu7NcWWQ1dFsP?7Zq0~9*^qFoZP|YYX5I%>o2}B5|'
    '(20sXnxBb;PS;D6WTJETcQmR;Y@wtg?1+M(1{i8IjJ6?#^dSD8JckAw4l**fs{FVT(UHM$hn*e2`Lcw=7jD11<qNfD_(L39W8!DP'
    'S9ud87vW&01Fz&)m>cxe6;UmLIrk{Peto>XF8-!r4s^4fYM(UY$KKW^vZ`-'
    'SxhBfF0WG^5P?BqCvLZ;*u2m9h^3i$$a8PVes%u7mBi)^=>Bhv`DoS1?!4&UQCT~+y=D<Uh-OlE;zfX;Ox2vJayZhlf9IZp>VEGR'
    '9)Ds9HlOTH{W=sHAy0V~H!;F{{?G(Zp7^Uxcj)yjcMc4INwZ+~n5boUHZX(<>(`G#(*%&7pV9z%9+w6fm>SRo3Q$u0NK_T<2)ZYB'
    'gC>rDV9Df<erSYZqId6-6a!#N&77=ggc<YZ{qO&c%^&Nv0WhO@VhaNJf`eKAed@X0rE-zV7qMS_w8*nDZZFKw|d8|n}CIN!Oh0WA'
    'S17?Z^L!8;*hLkc4Jr{Hqr)KuA^3OXbMqcz{&WWGa^VRrn&3Ylzp4{xzd68NsKh;V<b7eYrkHx~#LNsIfr|Ch8lM(4j`e+UKgZAw'
    '-fM(Xp4sFk=5xx|!8uKfQn9+^M?ddPrx`9`d(YabZ#}V36vAwLR(w${S>Y6ci;n-1!!-'
    '&gmPpy^qK(O_RfR}v@aU$1D52Hz|O)%rgopHJVCMnllrPuNDK$lYKA?id0SUy46*EX&w38r#2M(tiBQQF1&el8YIZrvg6AHN@K^`'
    'CS6dXm0O-'
    'A{b!F=HaQ9XE7fQqCxWF*y{7riPb;i9^a3>&1wCmAop?iwQF4Q*`bnOOmR9JW7r(w2N=@>l1Z>vHx#<iYc}YV6#<7_0REpLc9eoL'
    'HYP9cN;>+(bi@<_Xy)*GZXDbkuE01s?BEl)dY`&nGV5<jAF^XbtJvHxeYYe?&v*g(333;o_n0E1;5oUaxKpC8jAX`J5<=L0yB`5v'
    'eR-Vi3o;pK+AHFlCdcf0fC8RIsyAJxB^gmUBQH??pWMSPPxkYQNt;HWkd}h@9pmF?6^6#-'
    '1B^kXCrD6>pC>o+`9Pog`P^mAf^N8y|aCG7iTKuG~SlbrUf+^VUZ>@q0WKcmCSP!*+<}CO!m2%3>4l?MN}h;*uK+Y1iJ+}D|8tMq'
    'F3UjTu#l526avh;?Sr*{>3=a<rRbEwx1m5%5&k|h>FEkLlN=tfyTpr@SQrQBDBeRI`nT1(%)Oxs&goN%YO0@+oFPxL<DfeSwHYxP'
    'G`#j7doU3HXBjoXfud-|2R^J`K2#XYN9w>h1rQtx+~BrClI-)B-UqnP4tc*Qu{;rKkHOT{+O_Yw>Y!Bu=D{TkqJ|-'
    'Q^@CSTnpBs^}R4-'
    'v}9AKz(gwPZg8C(1l;M_m7c;DfPb&8`$bPUc<uM|V6t5>J6VQnQ5jP%v!yWU2_%xrkx)jH<?I_R(9DC34%jG=H9FpkweFOzi-'
    'o{q9y&%Eo=VV11DtS4r&Z0t-z2gCa_h)Oth&@Tyq{67tj-'
    '?_y{(J~NtiAP2C$L2{k~5sjA&_r7nETozL8eA(19I%O5($d5)VTGW27{3?ts=WmFfTk;hp@5qE^m8T=7=L93xJq6~2m;k#RH~aWk'
    '$eBa@5P-3=WtiaJ84J6ng<z6fDOPiKcw<(?Sww!|VkLCkHiYMsDbRY&4D@F%Ta{T(z=>JTlQ7@PRfy>>RLscj#tU)?Z*Jj!?@{-'
    'nDTR&Qz2J=Q;Cfn5E4=2`-'
    '~Hl_ia27c+As$G=5lL)XrOVne!rml~#&b~t8R|&^Xh;(siiA<!nQ!2HPcAw(4B$f&}e)61c0^rJza3>n-'
    'N;v)^0g29IB1TkTj#!bTgiV0~c>CniTdyv-QsK6gH{|TN5FY#I%8GZAo$Jqis(X&go|PQG;;DUgc%--'
    'r`cVH(sD3b7a;x*s^6rQv%Ard$yqs^ROc`DoOf7z+Rk_=h`Mp<%h9`on{v%eYTWs)n3;B7+<#D4+qxG`bG&-'
    '2}wmUlb&hCiK?gr~l2#Q5Ilrs}C>S+CyF`*+YOCHn?1Vcmx1j{t<Y0$%1a;H*ji?r(InsnvVc<i^$Rz>7=yHQZm4NJJ}9btWLu4;'
    '#R)m<8YSr~o*%+}V{S7Z}gVG2-'
    '6Fu>^zuzn4&6sM(%qT+xm4(l+EiA>T!$qoP*T*@;kdTvWkIjZ@9wu9v;`4KL5(F;hy$b49WqLnOZv~_g&?B(nI!~Agn|NgT7_9*A'
    'FNr^(1v)ymERlV3|TTVk`&Tgt;{QBtnU>>E$P@cW`#|99J>6JAM44Z!W`q``AAWT_mE0<t?db$7V#oNRzRfX9qr<nbd+`=)1qnFP'
    'F{f|km$JjMl+KO<+NyLOeRAv%{ta6x8o=G$P2{sL6ClO%XfYvMtCnJI9ory&RNYxJ|v&8N}<Xf-'
    'G^pjqmgI|u`{Bp$WLn>8<k0k=|=jw7nA7T{%{IS59tnk<L)CBYV;Aa4{Z?5*NLUpZ7=~gcZ9u`NNVU31jNwp{wOsj-'
    'b#~Ny=d|Ii&*NgSsPH;l&TYQAoC>Kq>z_J?4OZAY~O+7XS_u}Q@{_~@Q!++eY>ZyYFBfxkIf4o87#_PnceL5*F7X{o0YSS@~KbM!'
    '(0AKGP{r%wZZ#}??%tf>6eLWGjpa8rV&-Q;lc%8rf>oY3d1N-;gchf(8yR-ASd^#zgo_<?=`*ing_euF^vUB>Uot^JaPfwqoJ$_P'
    'r^QYq5@1{j@I{Eh7?;aPE$B%bTAAS31n#!D!bl6}Vc75tBxrC_!rtA6uc7f`6i39ne+rdH=FcL8Bu64y%Rn`@$`%dx$r6Uz@ei$c'
    '@cfNb7ddDWZGSZN&bD~bWFa@Yk8g4OEb&o6<>1dSF41p^!;Q>}7p9sgLLI)3{416L+&#q)L?VT{O2wxuqlDirrTbsEa;-'
    'kny7>fWic>0(gVyWB-jyc`gee})aCr|(M?RT)%&{Ik*&qS36baO|SY9ulNU+=B4DhKKzIrQ0DUaOq1V0`54tcIbmlJHHKCDGf>%n'
    '~d_?w@wQ)i=Eiuy-~sHtA!&Tu!X*u-'
    '<U=i%5zLWZ{%3D{zbD5^+X9!V;4}<<DlOpSc0frti!fh7)QK4d=N@M8vVky2_lCzkP;*lPSWgXg`sz;(Z~ZqnprLsM)1!wV4i3^d'
    'W9uq<kUx(L#2?)@_B(B9k!>R<F`##vFB-EpCK~5c^|^WG_x4r^ISu9vE?BTL^(C+g=j(NQLjj5>hE*RWLYntAVP%q;O-'
    'N3Zb~7+=p`V!s@}+SdXBIx}<ig(b$5}Ygz^LWuy7*BI!mNCf@ykG|ZbZef`m@>-~|6dh<t;4mMQi5g*ZlXt2!cu#cPCRA$-'
    '46r6dHcPl0!ve)|K(CIrg)uOr@NNmScA9c-'
    'Br5~6^lHUmfbtAI$@jL3*CIPG^1duqTQ#9Ka*z#0;4^K`Bu6z>qZ$c3%<8MnMLFfg^{n5)))&KF{%tC)&A*>QMFBTMKbBQKRnHop'
    'cu6b8pWtgCScDcUfn&uYA{LP~wrr|gF=G~pg-'
    '#+=%(_xE#W)NnjlWz%_%XdH7$w9=F|8JJ>i=IyywJIU2SPT6MF;dKlxLUd=6%wTnpiLJ6@U!gE>Og;}@TiNGz2TRXOtcZznBy?)v'
    'HC4=<lpS<I5h<f4n=%{rLHdPW(92%@v(OtP`f;iB&dze9zU{4o;vLO3jP29;lnQc?DfU!5^?~cUG_7g$cVoHI84~w)6W+aP0X3B8'
    '3%yx1307!uak6G-1~SxTi1RJ59RGD#I+Ntt;po}34M>5TrlX1YP}U#m~aZuq4-'
    'QPE~!jW93GFuc61EM)I&u%D*N2(F2tx+;t;j`?;kmXmG;RsCC77@qwVyHM*gL$UQpF)U+M&L`>Fz|Zw12N+3X|M4N5;bGZ8G5YMA'
    '&_qb#wQ+15cHX4%EtTwNr3F8XS=X=PxfyWi~Y{E5k?KjtiXlzg3FCRy>1TdfpE0X>W5IL0pRK;qC1U7q<1N)Kr<rCvg*IRp*(6f7'
    '|-'
    'As(krrEW#K%$EkC4MKAX0DWt6YcdmPk4+2hnY{Kr4wX6zmD07>kG}mvv0+Tk#P3Sq?$JwH3Z+c><QG7H0(l+WiIE0|S#gnumAzhw'
    'kuwK$S~`kLgAS%{1x^cxWoi^Vn#NuN#e><OGB@@JRY_E*0Z^;|akBNpJxIlS%=l1OkBs}O4=FS31m%3%m>L>K<@LYG;J0*M7E2Tw'
    'b1E<TiLL<IF?ke_TlVnA1dK-'
    '$rcNw1k__wI1R?x3M(FCoX+b5OaHiHxG76f5&Cuu*j=+E5f;99hpH*k|2o8Dxt<^Ol7?nlc%;*xNok*;Kg{CMeE6d&2R!fFelK=L'
    '^l`oT<(N-'
    'n(m#YG`s@){D2Q7`CjpKk8*q&%xLtNHx><O!tv%hmR%Bl<R+xE}6!webikLrAW^C;nvvxkUg7}hoOH84WQXXKIhtGc*VTzuVOiK='
    '5bkRJrD;#(X<Ga#0DxaUM^qW1oib$UpI<6=0-'
    'P~%s7EocqR<xRy9k;bnVRN6<&8UN?)!E1!<T`>3s3t6u2Rjda$iL4Oi<*rZviN)e+mia|pzZ=uf%&tv>hr3x7)oMI1E>EXLvZ~*e'
    ')m}2lY1TOrjNx#!y1**dRypFja-'
    '=4lO*&Mo@2X1!b)C7OiCvtyhpI}zAiQ&me&80HwLK8=__rbRDDhp~2?)a}CG3_x^0mJq<Z2UodI}jR=e=<W0&-'
    '7pv`UNgBCx_*ccm`-5j|+Uq*r0as8O{{Y~E*ep?B4mN(8cL_Z0W21+uN~wbY-'
    '98(bqgV?!Yv&=?QfmKAx(fN=?LsG+fzju3C(o%W*6%X8?uSrk>St+6@gAE9Sbf1ba8gvP0CqmPx<EoZ`*zu!e5-'
    'o}~|q~2t%N=^i|MW9!;hd>OAWlzhJuVbqgS(>z~&PWz)BC=4!uYW>QbRx0VtiuK<nH1T9k#bw8s2y;!G+G{MNw(wq%y?a#m8+|kL'
    'ABU9v!u5Pb2tpDP6hr7?N2MRN)?UV-JrThc~Qu7u6^8F5GJe;vBz*6IcJ?{G1PpbsqD8bxg;vdIyBmkl#1r5sbERLk`92-'
    'vQ*`V1PdC@&O~XwmWuTbJv&7eFZ{8vh#7mrsQy(W*2_)dLfXdKn4{!%tqL|_>Lt|5l3rTqsu}^USQ-VL49D8pa#@mWf@Phma)oGu'
    'zF`=%VQ^h`hFMW`i2uR6alM+&>5YJFT)DnMKeW-'
    '#CCgyEd$tcc=x$ETN~kU}>IJoPdN+%5f@$Easg3Yyju#hGuemr>gET+e{Z<!%R_9YehjZC)0jOWsj|v|W$7Ppq&RXZQu8Q}?Y>u&'
    'WVoqFn%byiL=XqgQGzh&6qG!s4nRD9#{}Y@*%Z8Krgtj#6vlTL79S_&$3wQwT86wA~fk1gIo2l~n$%-'
    '3`*)&t39jL&LTGa&<UtCl##<ri6>`LZSq|RC@5u3gXIU0C~&)}mcQksAAP08fx)x+{BMtQ7<brPM5-'
    'H0XO898flg$VHnXF~iGvle)uY`cz-'
    'Z3J`Wf*%fjuY?dtnT|2&qCj?y){oF0^N8BEwHwWvqM6KQ1A9;%p8$J4yDa9yxdoki+sE?fWTy)}?uE*KNl;Z<N?bJS{jsr{C&9*U'
    'hxQ_Cl(ohCPy_5&{TZG_i1)U<6s^|I(V(x4QyT8VIX(1|N=Dl<Q~QkRV-fDfY0bg8O$`@6YPKrWWXU8H=}_kM=>>{U+GUC4Zq{5<'
    '1?*Y1CanhEx8(T;J)n=oRf92=SbqE1=E`{_>~L6BrLe95Q?jb%ugm6K{lwo?l{-'
    '9vJsSO|fC$TUN21h2zIz`^PC+K2a)et!ti=NO)EWbFxct&Uu;Q6)93;$0Z6wbQ`;bc=7-'
    '~UO%1xWn5On1Z$_zUvGsQeU)yjB6Z&l%9$9O5q8*A5vf_(IK_<?U}GioSL&~$(GJsJ;@IlU~<HUg`&lo}a1tHzv_8oXQ+cLj|~v!'
    '>F6Za%sT^E0~cc*6Kwo!a2~vWmDkZ${F!iLVOvxT<r^<?KA2f=HB8!dLPFunLW{e8@vd{tV<-'
    'Jdr~(pNUrJv7z6qj1D+zq+!Oks8Pypx2Hh5Pv^#csksV64c&f!N_P(uILXh;t7R(0QO@<=U;y#JYc-'
    '0f#f>7Uri+JHZdLHm_1PI!UeUZ{pj2<G3e28jtV)eusBv5<*-}|0u|Au8iS>GzvN1jBC9erT+@a7y8=0XExbo>Bv`-'
    'sdhINA!V*w9XhS2PwPwT7%Qz#vY_<A<xDWqd>KWFtuInr6diRv?`7{$HdZD_KOdzxuA1Q&Jr?wOpddvWe53gF(3d-'
    '`hh*vviN(odokS|buK%h7u?EU=V{%(px+$xGiNmj)pkYm%gk?Uik%8jO)pW6pV}7wg>z3_u(ImY(6%%;80sQDe(q7>9rp_liD<ky'
    '-^GBEpdJ5X9puJ)=jH4+0q-hfW#c0q>P8RIKDo(w+x;6PFlmjL>+RV(bUE-xhss(|2aJOcCC(=RkI?r84|oFc{*qIU5C*YpTtT%*'
    '_s6)aB&eqK4}^m&yyuXGmY~IFK0(5K7qdsf2L81hgqBa+Y}}e5lo&Yzt}v&}0BUyb^KwDOPXdQccD~nB-'
    '+`wEGmWlN(q%K?}w?=B=5QXu$_g>5A?0hJ<kkrJp^uA4V+luZZ@VbhAQ57^(_ws>=icw-jY;b(453I+ZtC8Y;Ek%W`3%s2CpB<3_'
    'EE^OZE!i3~=%obnsPd0Bbj9;^5pGX=FD5EtuQ7zw2Q{idA<E!LD|)e_x}7c7qG^EITFfO~UKOgBD|>@p#*%`dAXVB@}t^cH7q@3^'
    '20ssf`U5A>jpJ{fe?LDB@(mkin&q&j!vq3nO#OpBW(X0}_IFc$Gx*iel<IAQmb$DYM%y(pLOXK-bT*lQ*8m}QQ?HuO`(#TjyNMpZ'
    'L1RgRAfhU%(E^ta&bzx?vc1JobR=^Edb`|2bQB9R2M?$%3DJOE@8L=9XJ5Q#<rMi{a;FB6H&qrQ{U8Lf?cx}|e^L`#DR&J7v25Ee'
    'OKcj!kscZ6!~D@pAVzMI$J6=KZ)-'
    '`uq|w{ctHcm9g)6Ul^R<h1F94j+6`Vl}d)k?b@bMYAKDRLrqVa!ApR#?^l>&IP~$aDZLPN~d{n#NEYZvACS;_gRfP59RVj9KDvaN'
    'DP|8IfD+M{6sxLy{z&o6<ifR?d_oWZB1&$n{Kybfm2t2bLhC76XxcDqjz?|$XQ@lfxs`WIvxpxbqLxxG#B`&L{bI!DEJfiMth#4*'
    'ppG1b!7Ihw=*8Lama@iHWqI7i{+;rO|V3|gUX4)<r65eVaLw*F4B~0W#UTq3~jy^=`WHdRsM_7o*Nz79L>nEGb|Y!U`(Z3rI-'
    '`9am$UWc>~XdC6#znqZ2WDx$1kjlZa*=RD6-PG}ZZea@&lLh{z-'
    'fMCy6!bGx@OpHIs2s(xFSiC$)ORryu%)AOe?Uwv=nO}n09m6t6OtbW^up0&l?_rwx*7ReRB*HoZZ<+*X5ImN$Sc23Lx#6r^A)(!~'
    '0an$<UDMUKp7V>6$<Q5snhIQu}8K<;ScRGkhIQg&*lH|m3l-'
    'QE9F^E|Hyt@YSNF@?cK65>nyb_r(ySS0GesH8%0p2AOU3>*0@c2)g>f)}5I<<VG3$en9;FIrvb9#1GVRWRn%<qAQ`4B{ubi{Q8ly'
    'f8ZWX0r@yiFkVf)zz$0?O1F5v=BLd4^anex1<q7~X9#&VNn~PEtG#wP}GsS9^=gD7+k%Aw<h@WtUng-K7gIzHgV^oy-IQd1w%cLq'
    'KCVUrBZ`DIg6J`6zwfTmftS8xSBs_p|LpY{=#le*`flB9pAT!voN&hG+Qi)9#?!fm*UV9C|H<=_M=Tzz`=gRGcT6EPT1)(9VOQbD'
    'InaHe`4;bxpbP?DKsbGWmob(ewrI(+$ZJ3{R_{T7>Ed+Da>)d*aGLRU(RPM+zBquz?}6zy?|6=pe%eUi?tMc>OfEUp;&M{7L=u!P'
    '&vn!~OdC{?7-`_D$E!jpLUm_0j8>^{W?PHKy)XFMm2rE(T2;pX?t!J$!PO7X9V<kM*-'
    'B&tB};FOFaCPf~rDKu97YnpZDRo*$elPXls^S(UH$U!D~1=5O{x;XJ3LI~Z!7oFk$L>h=|0+v?YFPu`_Yv#BR_CX~1jN;M0c#2_V'
    'Zg*iVF^BxvTL?~)z$<gb>!y>0>B}hf9467(1_10I@O@?I@ki77=T=;`v*No1=9e6<_p95_wkE1O+LGl)*L?<4{s%~12@bIT?Sx6('
    'j&6bYCwCoLtrUq+h94irRZE6~buR}VppbB3(AAx~WDso*}VK<WzBFqM#-'
    '_LHxzIIFnD2M8})3+a{#pL*}Z5Sg6nie3_n)G~N;~WAduD2V^n!7UR-'
    'n)va6W`7jo9$+l)W?LI4h;Iu>>X5c`uYe2t>yN&caT|q1MRMs;Od_P_*`YA$xjGSJyK}-'
    'h~AN;{gVc43~T=ZA69&7DeRzcy1y>EK2?K_EbaM0OZrU&6{PTx4r1?S$cKx*NX5dCMJ{~%Zo7C-'
    'Vi8KRR`~h*qksH)h^P<t4GXOGEIAz<?-#HW1taF(cNr4;r5XH%qA7*r0#@-JcD$bq2S?dalnW0^=x+<9dut>6dO}0d&~!K=py`-'
    '_`gRb9*O30QA#J8x+JszXqqpYSn;y<CG{HO)!4z=c=r9zZK#wGCUac=bfLT4X)CX@WBLc{=o#dprck>~alhlnJqBwi!ZzA6d(R3o'
    'CHN(?%yIzwpc#mD&7LGS@zWyb9IBlu6qIgHOHQdQ~g>*jh25Hyl>!YrIxQ6Ct{dCoXi>ze-Sq(jaghLx}GNx&8rxDWXO6DKDqc$~'
    'N)^YPgl7xme=(}pv#-0A5cI48IWR49JY6oiRz#J-'
    'OX4sYg7rD0K6od@B>eD67aLD($t)SdZ$_=;^m3DFLrVle}fj~H0vn)7M30;621JJi4ogI>juR|bDT3gNrh1n3m1vi_<;>9!5IL4m'
    'eRAw$+&(WK`y~em+=<pJeY)#>hW{`>V0_(OhArDRuUON5@tkHq1B_=v9o-e-'
    'K1mh>j(d*FK+)m}7YQH9xUtv)$E!myvHa~YgPo$YYDpO>|>^b9r+YR6eFYa`X#`Zje(vX}3vp-tm0)(ZvT5d3@W@IL*n=6DC5BbU'
    'Sm088+5{iT?_$v!$kD8*LX68T#>6XxsfnkGT>><)*{bA<2Ins>b;X-'
    'M&h$niM*UvIe#6;;OA4G=8P6r^?*cwv<d(O7+NhKbH*0GHhIA9H5CA@%=scssH9%EILDv|%Gym#p!#_y33P^E4uYp=F!Q}8z3Ad>'
    'ZJimIVvSRItCsQqMxT}{iA&rLiVgcw@6AJkD3OeAIUFwUymCaFEr8_2uTFHfNsLr-'
    'rsok3ouSj^pBc1k-cpM@{UN3KOqm$6k2y>Evu-F5Eq8q~C)wS)DctsEIdBO?wy=5%0w9y*UM#~jLdLXEaiB~1-7u^iX-SR9dXZlE'
    'M&u38=fwqEHXGR*<W<2R;3kf{TF5;;PH44L0J>@|i+;zDGeV(1h85xj@XC|=@eSb!wGe{5qE#+04-{6Tx(-'
    'x!9iwRCfaE=zhonzsGGznSwVg5XlD)lYi0Lh0{>x>B?c;wi5IW7XnKy1d=vg^>@*IJchtw!OYwSB~Kv1y3Ye0RCqqEpR#w;<;FKI'
    'nyBudmTAUJf|!{Z2x*g><!Rw*eO3<Uca}!Ffzq*1!Sc*nCNN=&?QDtc%KG+1j+SZQN>?j&C!k~8RcD9`k0{~?(B=JrFjmqwypslw'
    'pY@`;epXveQ@^t;IxO(L`F}5uu!CN^|w#=e~fNZo*i9Tz`LRSLxHk%Y7u_1`L!^O0*Rbi1E9G8KeyS(*0=scb(2Fk-'
    'yMbZVM-P<H1Sg~pZRrMpFTf6I{f#4@b9DJAC3<XkN;(V9X&lfe)iK2mN;R|HdS2Va9>T^gdI3bHoU@g_R-PC;)VHQ8D7|!jUv4A0'
    'a2S4n>?A6`5tbNum$@AYqvkBW;d9&R-w+?4<f_i{kP1qr^0aDF5arcQKV>0<c{QPij|mrQintke&GU-'
    't=dzyhe6M1J7OY>TTFwP#!*!qWaM~mylu@!n>Lc#i9`wdlQ`3ZgHu!z(Ej*f)Keo6B31!z!&8?sIH)eK0A+wUBZqD}JE`K?;Q?B!'
    'M;)vRH1jRyMKLc2=OVgrD&&Ingp?acXSuxciWj5S($@Og5_SRgjFl~XPUDIq7G|5sn81WBype!^Ze(8;|8IG~Ko&Dyf^!g#XuI)v'
    'ya1QZM>S%yW=P0Kr>#4s<4Nm4c%5;{zI~LU5X?L^+T6_z3M7Z)PsJz8%$j}@CKux-'
    'i56m9hb*B~5>c4RH@zpIlIW5W3A00ZA`GD;lnO)k`Kq269nr6(cxkS*mMEPWwqh-T+*m}jFI3}mH-co2LJ11*x$qbRVH#E#)q}t8'
    'bnv*ON^2+1!Ny@JpK2z>y&$_Zei%Cuz#xn3GV8ySfd_Q<up}hUzk|pfNb@(+QIx3$=IPj2mv#kF8o2l_2_OM0X)z<D>6_OXI#_yx'
    '#KaudkYhiWDxcb3^kAV0xyUzmg4*@u{M9~vjSZQ}tvh|};d4W-'
    'wEMbbM=@7m(6imhf~+N$1DA$wPeGh)c9;WPWXVk&YzdyZzN7H#*?|S|r=}TaKOfGbab!V9{Ra-'
    'r)qDXbE@LHip<kd|L&6EO*m;L5#2kJ@$9h!V<y&)VZswM_(@Y6dN%d~Fo{g$wq~)w@B;~AYt7^lNy}Y%@@Ti@&`%e?Q2jrF;zO4='
    'jDwh~5{*0#**sQzHF?#cqcj0|vdRHY;XFjk;ycj+6Kl5)C`FdCE*?DZv$SoqagU~{_D<hT$1_571Y8+7*)@3@IeJ(sX#f@_SM7Y^'
    '*Y`);~re+@2u3B+WlqOg7!qF2>bOpD+zHO*=XEvthf&tYa#q<tsH-'
    '_TL%@BCjT2)6>D%Y0_d#=B`{O|#;m@c-c0umg-{J@2M7CC?I7F96sC_zd_0!pA9G)z_ZHg-Q2Of%!E$U~D^Od-LHtD~8UCQ~1d@;'
    'Dq~b2zv$9BTu3r`RU~qGDRt=`NYu(s5g#Q&Lwron`oSGd41dMUvJEuca8i@@#7)xmwSs{e~~?=7l|RZO{d;iE;PqbsQ?rtb2C2<h'
    'ka|_<Br>n4byKd{&QDYLJClm2jC+qK!fI=&wFAA`+GUfUIu^bqLM@@QoBcJeu;zf6|ccy#u_W@|_eYMSGq(9BWR^Oq0bk^OZkL0%'
    '~TjNAPUSD+w+TBhPx8NV&^qPEV?lk)NnStR4qWQQ3lnO%@K?>PP1syW7l)p(5wu;}?xxqc@~HykH{`lu&W`bGT{Ye*+#Q*9j^u)x'
    '1)L$vey8?q}1DG&z6=oJ||;>#;qTB`%Ut(dxZ$U-jjaU+Ob6-JkrpUqdRvS*E2$PybjL<L7ER-9Otu{rSnOgX5#K;x5J>1-'
    'Cc~c8&lqoVo3@b0<%utQvu!vRDd(YsoBzjT$GM=|v}(?<LE!0Efu3pSdPdCNJND)K4ptjC27s*In*NPsUE31UxSK=wVn5?tKu{V@'
    '9nP_Ehp(fiaqQ{h08I8B-?uyxFBmk4__+6Bo5m4mDSfLX4qe-M+1LA)j@}9no&*-'
    'fs50IouHn^&O<RZS0&X>0o~U6TtiWbcVzTFap;I)5r-78*^^dW*%|^Lju-cTzDR3akZLVuF<C!FGhP(bszQ!FW^I?d!KJNo#OVnT'
    '~6{QXzF$cx$7;5=w*&@AzW*cR|{TAK`6i=4gRJ1S}$xRns5WrSy>oE*o!5D@osDt#=Ar^<SGc%3||Y_8~`$i;aFR%DLSK3S}Scg1'
    'UpV><3^E2+`K~CaU`UOMe163_;u+F{xD*}s$_CDoFxc!O}wDFFm{eL5q=mlA*Egz(>S(WI}NO64b1t}$QzS6k#epZYdLJ`s!<N-'
    'W=kBmk(dW*Ft-bO=fE5Y`|^NsCMLScWKgz~bas>_SVS~s!|QnIyeoo_bEaW_l0)=4W_wyN^m2iWRV3<F9t$_Uts~(^!Z5Y%dYNe1'
    '$`b|N9D7{nI;q@m(Mww@wi=`+f$W2NpWE38a+P)(Y<l72B;@N=b-v8}(6-'
    'h_dz`IlH(OnUoz7OeoAvI2EO&pP)$SoJcK5W_b#!$`&0ukgv_G_!ryAyrFmb!NVz0^e-'
    '9>cUNepABK=reoU#;g$#t$}oD7AKek#}Cv7L^e7`pf>6;a8Ub*tr=cEpb3dtg0c21MIiiVmn{V5_S=G9$`MIp4GOiz0cYDPKwVbf'
    'o_=~HwYVJ^GFcK=CAokHuZA^;c_e6tgj4-SzwGC`pfdEjI!ca#c;SRQj(hzJe86;A+Cp$LQH^8#4nwl46(AEn;rfo-fYcF+(3rJ!'
    'aSi&0L~<^angC$*q|ypvohmTijx)Hq~>i5ks_IC2`J+xn<$o0=q%}SYi5U(s}CxOLM$lKTHFW-269!1wDx>OlS!36-'
    'dJ@+4dGZAL28K~`9AB@2%q#+5c<uO^dW93Hz<MCB@Bs?V<Dnq!kX`roYDNAmnPW6{%>!DqW<)YKFrilEXq2h2MdMM&S|dKmEdY5m'
    '6~DLF4i*!O%FyS&~w@=fQ)1esYgu;-'
    '$N;TT5iWU?mP!FM68F1{tx&e68sY>7vaz{H}LP#ll5;~2vI!2J3R}A5BMM5)9s=Hk2oj6Lyn*0NFzj+F!0d|Ng=AHC91~;MwioRe'
    'aUV1RJbCGO~GaXSjmW!TdbyxX5^|X*5MrNbl!E_ww+)iUB0F9gRcx>hFdUSznfjJCT`fzUZ0$t?w_4CbjSfKVNa07_g?h~0H!ahN'
    'n$g#s|X<1G3FoZBg#*>hEvl4lEalzNMDgmbB)~s%SCaV1FEeteAxpwTumofM5D&AcND4&x)s6H+n0&tsx&K<M`T81rpfGs0*)OK1'
    'f*c8X$!1K{IL5#wS-'
    'aDDKdT!QZAwUzoU2`4RbQK(TMgH5(b^P0}^K_Ck#T#Raj|-u7gdMf_Z~jr_+HpPhB$n49l375YCjvgqHcje9oKR-'
    'oO(oINk(?Y8ny3e6JPi*!_{lsM-Hn1i^h98nvO|w7q#w)?EsaJGM{#lOF2)&jT1Ve}|(0qO=1@{)$~5PG=Nc$u2ZR+cwk~k?>8=*'
    'UL|lqyAGnKYgm<;SH7(xyvkJxpZ1^3j~fC#gH-'
    'Z32EZg)prUm4vuIefUSFh&So1&l3+$GCzF2#*KZ$JXs@u(xgFCnEAdPGUm=Mj4i@HRsc^bfp1T+Zgr0hPP-eE^2b@HoS>~U6rP)3'
    'eYSQN0IX!!lBDoGKr;<BFI;W$HmK1G#QpRv?%@7kAU=XLfj!S<hJbJ>EIB98SY%(KG+M65gl&qakmHHh(U07Udi!N^ii#>L{jYDQ'
    '+e^QAipYJR*jssT;Gny0g#3W6MNA+M(sloIUpX=_CHhc)Zgm$2uRKAUWc-_u!=HhV*Wv_DK^j3w_;^~Ec<e|0|=y{UIAP{)HT~U|'
    'LJtDl>+zBP4x7dDo1B(X`uL96>U(|yB(xbv=<Pg0*ro(DI`#4{2@!jb8G2?NJq6S?T$T~-'
    'tQBLCL&klZs6re%ne;*vZ>MJ>01ghjh-FyAV{(}UrvUC?tQOQaFPBGPa=lZ&NZ3YtC&GN>4dyBdL4Yx;HBy)E_E(wB8M%-'
    'wYNjk>obO{il^}<usk3PJI(*#VPlfC8N_C)eaia%vjv^x=!kr}(9+|d?0bZC*0m@?#ZMAeuwfJq{Hjm@jQhNGO%gnnaRT2hq@Ki6'
    '0|xioy{I|-lS_pcpEO(ZPwMAcCub<M-'
    'S6^8&%&q+jz(l~tuVT$`JnG_McmE(mR_;JXY$lU`;?nur*Z!sC|028Q^v<A0gu}LPRtI<wLrSJBADX-XUD9SEg;DFG+W(zW(%NsN'
    '|nN6X4-'
    '<(Soej!@^m_%)~5D$#ta{F!h|35IQ`IY+yS>wNo2M~SAF9N}rhkw_02P@8@x@7T?lD=k_OGBpL4tYqTQY{gwfDsXUW*iL9<CM`g2'
    'e9joX&A-'
    '2cM4c^A1KiaagTTcIhdhAB_HX*81gd^>Z}$B(TVIQO9g=)zI*V^zw8T>*mthTd;lrfYV&AK7W3G(mP(NqZH6O8IoWJNY!nvbFng5'
    '*H!J(;an-sM$i*4R%I0fMG-}W&AN>B3fn{e5^0Qk2D2bUMFN5!w##+lv-3gB9KC*~t%14=uzaYfqp~6ePI1%i@crOyl*f2<N%-'
    'VvZLd~URk9ju{^(8=9Qp`zQ=PEW<c~h34Sq_HFm$2@^0)kfaNs^3@$P*unY40I8I2W5aayMbdkRvs@S=Ol1_lwA1=Gd6cKf=7itp'
    'REk%BK#}73SdIi<oq^2FJ7r*!5sAVQ{Wd5)hS2h(wa=P)~`*GwBg~B{9$x$y*bjr1dX>!hAj7+#uUHJaqnOe8K*dk0DK9;5$;Bh-'
    'j{N)q;T#d=ddGcT#B5?R!UsE8I`qP_ciNpOb?U-|BQsH|<%80eCeQuWRNqHC39oI=kJNQ)A!EwVoKRe!ufy?fy23'
    , 36164, 196956, '86c8c151e559e4f4e665c475348e3a81665f008ba69298b3829d474b4873035f')


def test_completed_watchdog_86c8_captured_protocol_preserves_original_productive_emitters():
    import ast
    before = ast.parse(_sampled_v5_finite_pair_source_data('cli269'))
    after = ast.parse(_sampled_v5_finite_pair_source_data('cli86c8'))
    functions = lambda tree: {node.name: ast.dump(node, include_attributes=False)
        for node in tree.body if isinstance(node, ast.FunctionDef)}
    old, new = functions(before), functions(after)
    for name in ('main', '_source_custody_witness', 'classify_owned_validation_source_custody',
            '_productive_native_closed_profile_v1', 'inspect_owned_validation_productive_native_closed_v1'):
        assert old[name] == new[name]
    assert set(old) <= set(new)
    assert {name for name in old if old[name] != new[name]} == {
        '_no_child_native_closed_profile_v1', 'inspect_owned_validation_no_child_native_closed_v1'}
    assert _sampled_sha(_sampled_v5_finite_pair_source_data('cli86c8')) == (
        '86c8c151e559e4f4e665c475348e3a81665f008ba69298b3829d474b4873035f')
    assert _sampled_sha(_sampled_v5_finite_pair_source_data('sdk4df')) == (
        '4df3f7f2c6d2952550dd78153b579f4e928e9f119e697bded8a7dc001021f8d2')


@pytest.mark.parametrize('role', ['ordinary', 'manual', 'completed-owner', 'completed-subject', 'completed-both'])
def test_completed_watchdog_86c8_pair_reuses_existing_full_roundtrip_assertions(setup, monkeypatch, role):
    # Preserve the original assertions, with authored original-producer DATA.
    # This is not a claim that these modeled frames were emitted by a real CLI.
    if role == 'ordinary':
        test_sampled_source_held_v5_finite_pairs_readiness_closeout_and_disposition(setup, monkeypatch, '86c8-4df')
    elif role == 'manual':
        test_manual_snapshot_explicit_readiness_and_closeout_preserve_unmodified_unit_frames(setup, monkeypatch, '86c8-4df')
    else:
        owner = '269-4df' if role == 'completed-subject' else '86c8-4df'
        subject = '269-4df' if role == 'completed-owner' else '86c8-4df'
        test_completed_watchdog_explicit_compact_closeout_preserves_original_failure(setup, monkeypatch, owner, subject)


@pytest.mark.parametrize('damage,error', [
    ('cross-sdk', 'original Source-held V5 producer/SDK pair differs'),
    ('missing-sdk', 'original Source-held V5 producer or source pins differ'),
    ('changed-sdk-bytes', 'original Source-held V5 producer/SDK pair differs'),
    ('changed-producer-bytes', 'original Source-held V5 producer or source pins differ'),
    ('request-profile', 'original sampled V5 request profile differs'),
    ('source-open', 'Popen-verified parent closeout'),
    ('scratch-exception', 'V5 closed ordinary scratch receipt'),
    ('zero-body', 'original V5 retained command failure differs'),
    ('watchdog-join', 'original V5 retained command failure differs'),
    ('inventory-over-4096', 'complete nonempty sampled recovery artifact inventory required')])
def test_completed_watchdog_86c8_pair_refuses_resealed_mismatch_before_owner(setup, monkeypatch, damage, error):
    test_sampled_source_held_v5_finite_pairs_refuse_resealed_mismatch_before_owner(
        setup, monkeypatch, '86c8-4df', damage, error)


@pytest.mark.parametrize('role', ['owner', 'subject', 'both'])
def test_completed_watchdog_86c8_record_only_disposition_uses_original_assertions(setup, monkeypatch, role):
    original = _completed_watchdog_unit_case
    def selected(*args, **kwargs):
        kwargs.update(owner_pair='269-4df' if role == 'subject' else '86c8-4df',
            subject_pair='269-4df' if role == 'owner' else '86c8-4df')
        return original(*args, **kwargs)
    with monkeypatch.context() as patch:
        patch.setitem(globals(), '_completed_watchdog_unit_case', selected)
        test_completed_watchdog_record_only_disposition_authenticates_compact_receipt(setup, patch)


@pytest.mark.parametrize('damage', ['owner-sdk', 'subject-sdk'])
def test_completed_watchdog_86c8_record_only_disposition_refuses_crossed_SDK(setup, monkeypatch, damage):
    original = _completed_watchdog_unit_case
    def selected(*args, **kwargs):
        kwargs.update(owner_pair='86c8-4df', subject_pair='86c8-4df')
        return original(*args, **kwargs)
    with monkeypatch.context() as patch:
        patch.setitem(globals(), '_completed_watchdog_unit_case', selected)
        test_completed_watchdog_record_only_disposition_refuses_corrupt_compact_receipt(setup, patch, damage)


# Fictional completed-command/ledger-finalization DATA. No original runtime
# document is adapted and no test below claims historical execution attestation.
def _completed_ledger_unit_reference(path):
    raw = path.read_bytes()
    return {'path': str(path), 'bytes': len(raw), 'sha256': _sampled_sha(raw)}


def _completed_ledger_reseal_unit_data(case):
    """Rehash only the authored fixture; product recovery never calls this."""
    _manual_snapshot_reseal_unit_data(case)
    request, terminal = case['request'], case['terminal']
    attempt = case['args']['attempt_directory']
    for directory in request['outputs'].values():
        Path(directory).mkdir(exist_ok=True)
    execution = _sampled_copy(case['ledger_execution'])
    result = _sampled_copy(case['ledger_result'])
    execution['request_sha256'] = result['request_sha256'] = terminal['request_sha256']
    paths = {name: attempt / 'logs' / filename for name, filename in (
        ('execution', 'execution.json'), ('result', 'result.json'),
        ('durability', 'validation-durability.json'))}
    (attempt / 'logs/stdout.log').write_bytes(b'Authored unit completed-body DATA; never a pytest report.\n')
    (attempt / 'logs/stderr.log').write_bytes(case.get('ledger_stderr', b''))
    paths['execution'].write_bytes(_sampled_wire(execution))
    paths['result'].write_bytes(_sampled_wire(result))
    files = []
    for path in sorted(attempt.rglob('*')):
        if not path.is_file() or path in (paths['durability'], attempt / 'logs/failure.json'):
            continue
        info = path.lstat()
        files.append({'path': str(path.relative_to(attempt)), 'bytes': info.st_size,
            'sha256': _sampled_sha(path.read_bytes()), 'device': info.st_dev, 'inode': info.st_ino})
    durability = {'schema': 'owned-validation-durability/v1',
        'request_sha256': terminal['request_sha256'], 'reservation_id': case['args']['reservation_id'],
        'result_path': 'logs/result.json', 'result_sha256': _sampled_sha(paths['result'].read_bytes()),
        'scope': 'owned_files_fsynced_after_recorded_group_observed_stopped',
        'files': files, 'admitted': False, 'arbitrary_descendant_containment': False}
    damage = case.get('ledger_durability_damage')
    if damage == 'missing-file': durability['files'] = files[1:]
    elif damage == 'duplicate-file': durability['files'] = files + [dict(files[0])]
    elif damage == 'device': durability['files'][0]['device'] += 1
    elif damage == 'inode': durability['files'][0]['inode'] += 1
    elif damage == 'result-sha': durability['result_sha256'] = '0' * 64
    elif damage == 'admitted': durability['admitted'] = True
    elif damage == 'extra-field': durability['extra'] = 'undeclared'
    elif damage is not None: raise AssertionError('unknown authored durability mutation')
    paths['durability'].write_bytes(_sampled_wire(durability))
    (attempt / 'logs/failure.json').write_bytes(_sampled_wire(terminal['failure']))
    case['args']['expected_artifacts'] = recovery._durable_inventory(attempt)
    case['sealed_artifacts'] = {name: _completed_ledger_unit_reference(path) for name, path in paths.items()}
    case['ledger_sealed_paths'] = paths
    case['ledger_args'] = dict(case['args'], sealed_artifacts=case['sealed_artifacts'])


def _completed_ledger_unit_case(setup, monkeypatch):
    case = _sampled_source_held_v5_finite_pair_fixture(setup, monkeypatch, '86c8-4df')
    canonical = Path(case['request']['cwd'])
    case['request']['source_sha256'][str(canonical / 'ipfs_datasets_py/optimizers/logic_theorem_optimizer/autoencoder_daemon_resources.py')] = '3d1086df85ca33394c71f848e6bb45f954d369d2e977b9b73df92941f9ff4075'
    check = case['ledger'].parent / 'authored-separately-pinned-checks' / 'test_completed_ledger_fixture.py'
    check.parent.mkdir()
    check.write_bytes(b'# Fictional selected-check source DATA, never executed.\n')
    assert canonical not in check.parents and canonical.parent / 'ipfs_accelerate' not in check.parents
    case['request']['selected_checks'] = [str(check) + '::test_authored_completed_body']
    case['request']['source_sha256'][str(check)] = _sampled_sha(check.read_bytes())
    case['request']['argv'].append(case['request']['selected_checks'][0])
    failure = case['terminal']['failure']
    failure.update(executed_checks=list(case['request']['selected_checks']), returncode=0,
        error_type='DaemonResourceError', error='disk ledger lock unavailable', elapsed_seconds=75.0)
    execution_keys = ('schema', 'request_sha256', 'executed_checks', 'returncode', 'completed',
        'admitted', 'Lean_admitted', 'resource_scope', 'model_weights_downloaded',
        'authority_granted', 'elapsed_seconds', 'process_observation')
    case['ledger_execution'] = {name: _sampled_copy(failure[name]) for name in execution_keys}
    case['ledger_execution'].update(completed=True, elapsed_seconds=14.5)
    case['ledger_result'] = {'schema': 'owned-validation-result/v1',
        'request_sha256': failure['request_sha256'], 'executed_checks': list(case['request']['selected_checks']),
        'returncode': 0, 'completed': True,
        'evidence_paths': [str(case['args']['attempt_directory'] / 'logs/stdout.log'),
                           str(case['args']['attempt_directory'] / 'logs/execution.json')]}
    case['unit_data_provenance'] = 'authored canonical-cwd completed-ledger-finalization frames; no actual history'
    _completed_ledger_reseal_unit_data(case)
    return case


def _completed_ledger_call(case, operation='inspect', **overrides):
    function = (recovery.inspect_completed_ledger_finalization_validation_recovery_v1
        if operation == 'inspect' else recovery.reconcile_completed_ledger_finalization_validation_reservation_v1)
    arguments = dict(case['ledger_args'], **overrides)
    if operation == 'reconcile' and 'capacity_policy' not in overrides:
        arguments['capacity_policy'] = 'administrative_closeout'
    native = recovery.resources.native_deadlines
    original = native.resource_operation_deadline()
    if original is not None and original.cleanup_only:
        return function(case['ledger'], **arguments)
    cutoff = (recovery.resources.time.monotonic() + 240 if original is None else
        min(original.work_deadline_monotonic, original.native_deadline_monotonic))
    with native.resource_cleanup_deadline(native_deadline_monotonic=cutoff):
        return function(case['ledger'], **arguments)


def test_completed_ledger_explicit_closeout_preserves_failed_owner_and_all_original_files(setup, monkeypatch):
    case = _completed_ledger_unit_case(setup, monkeypatch)
    before = case['ledger'].read_bytes()
    prior_sha = case['args']['expected_record_sha256']
    frames = tuple(_sampled_wire(case[name]) for name in ('request', 'terminal', 'parent'))
    files = {path: path.read_bytes() for path in case['args']['attempt_directory'].rglob('*') if path.is_file()}
    ready = _completed_ledger_call(case)
    assert ready['schema'] == 'sampled-validation-recovery-readiness/v1'
    assert ready['ready'] is ready['capacity_not_assessed'] is True
    assert ready['state_written'] is ready['recovery_performed'] is ready['admitted'] is False
    _sampled_assert_unchanged(case, before)
    receipt = _completed_ledger_call(case, 'reconcile')
    after = case['ledger'].read_bytes()
    selected = json.loads(after)['reservations'][case['args']['reservation_id']]
    assert selected['status'] == 'released' and selected['artifacts_durable_asserted'] is True
    assert selected['explicit_reconciliation'] == receipt and selected['storage_bytes'] == case['row']['storage_bytes']
    assert json.loads(after)['reservations'][case['prior_id']] == case['prior']
    assert receipt['capacity_policy'] == 'administrative_closeout'
    assert receipt['actual_postwrite_census_required'] is receipt['final_accounting_is_prewrite_projection'] is True
    for summary in (ready['proof'], receipt['sampled_custody_proof']):
        assert summary['original_failure_profile'] == 'source-held-V5-completed-command-ledger-finalization/v1'
        assert summary['completed_body_ledger_finalization_optin'] is True
        assert summary['original_command_returncode'] == 0 and summary['original_cli_returncode'] == 1
        assert summary['original_failure_preserved'] is True
        assert summary['original_owner_completed'] is summary['retroactive_qualification_claimed'] is False
        assert summary['cryptographic_execution_attestation'] is summary['reconstructed_Popen_handle'] is False
    for name in ('native_release_performed', 'admitted', 'outputs_deleted', 'cap_changed',
                 'new_reservation_created', 'new_resource_lease_acquired'):
        assert receipt[name] is False
    assert tuple(_sampled_wire(case[name]) for name in ('request', 'terminal', 'parent')) == frames
    assert all(path.read_bytes() == raw for path, raw in files.items())
    assert case['terminal']['completed'] is case['terminal']['failure']['completed'] is False
    assert case['parent']['owner_returncode'] == 1
    assert recovery._durable_inventory(case['args']['attempt_directory']) == case['args']['expected_artifacts']
    disposition = recovery.inspect_validation_disposition(case['ledger'], roots=case['args']['roots'],
        reservation_id=case['args']['reservation_id'], attempt_directory=case['args']['attempt_directory'],
        expected_request_sha256=case['args']['expected_request_sha256'], expected_record_sha256=recovery._digest(selected),
        expected_previous_record_sha256=prior_sha, process_scope='sampled_birth_bound_descendants')
    assert disposition['storage_release_established'] is True and disposition['native_release_established'] is False
    assert disposition['release_evidence']['test_or_task_acceptance_asserted'] is False
    assert case['scheduler_state'] == dict(leases={}, waiters={})


@pytest.mark.parametrize('operation', ['inspect', 'reconcile'])
@pytest.mark.parametrize('damage', ['wrong-error', 'wrong-error-type', 'body-bool', 'body-nonzero',
    'outer-zero', 'false-wait', 'Source-open', 'Native-open', 'source-drift',
    'watchdog-errors', 'received-signal', 'wrong-SDK'])
def test_completed_ledger_refuses_resealed_wrong_original_category_before_live_owner(setup, monkeypatch, operation, damage):
    case = _completed_ledger_unit_case(setup, monkeypatch)
    failure, parent = case['terminal']['failure'], case['parent']
    if damage == 'wrong-error': failure['error'] = 'validation watchdog did not finish cleanly'
    elif damage == 'wrong-error-type': failure['error_type'] = 'RuntimeError'
    elif damage == 'body-bool': failure['returncode'] = False
    elif damage == 'body-nonzero': failure['returncode'] = 1
    elif damage == 'outer-zero': parent['owner_returncode'] = parent['original_owner_custody']['returncode'] = 0
    elif damage == 'false-wait': parent['original_owner_custody']['genuine_wait_completed'] = False
    elif damage == 'Source-open': parent['source_closed'] = False
    elif damage == 'Native-open': parent['original_owner_custody']['original_native_compute_closed'] = False
    elif damage == 'source-drift': parent['source_drift'] = ['/authored/changed-source.py']
    elif damage == 'watchdog-errors': failure['watchdog_errors'] = ['authored original observation error']
    elif damage == 'received-signal': failure['received_signals'] = [15]
    elif damage == 'wrong-SDK':
        case['request']['source_sha256'][str(Path(case['request']['cwd'])/'ipfs_datasets_py/optimizers/logic_theorem_optimizer/validation_run_resources.py')] = 'f'*64
    _completed_ledger_reseal_unit_data(case)
    before = case['ledger'].read_bytes()
    def forbidden(*args, **kwargs): raise AssertionError('invalid original category reached current live owner')
    monkeypatch.setattr(recovery, '_sampled_open_scheduler', forbidden)
    monkeypatch.setattr(recovery.resources, 'DaemonResourceReservation', forbidden)
    with pytest.raises(recovery.resources.DaemonResourceError): _completed_ledger_call(case, operation)
    assert case['scheduler_calls'] == []
    _sampled_assert_unchanged(case, before)


@pytest.mark.parametrize('operation', ['inspect', 'reconcile'])
@pytest.mark.parametrize('damage', ['result-incomplete', 'result-body-bool', 'result-stale-checks',
    'execution-incomplete', 'execution-body-bool', 'execution-stale-checks', 'execution-stale-observation',
    'manifest-missing-file', 'manifest-duplicate-file', 'manifest-device', 'manifest-inode',
    'manifest-result-sha', 'manifest-admitted'])
def test_completed_ledger_refuses_self_consistently_rehashed_incomplete_seal(setup, monkeypatch, operation, damage):
    case = _completed_ledger_unit_case(setup, monkeypatch)
    if damage == 'result-incomplete': case['ledger_result']['completed'] = False
    elif damage == 'result-body-bool': case['ledger_result']['returncode'] = False
    elif damage == 'result-stale-checks': case['ledger_result']['executed_checks'] = ['authored-stale-check']
    elif damage == 'execution-incomplete': case['ledger_execution']['completed'] = False
    elif damage == 'execution-body-bool': case['ledger_execution']['returncode'] = False
    elif damage == 'execution-stale-checks': case['ledger_execution']['executed_checks'] = ['authored-stale-check']
    elif damage == 'execution-stale-observation': case['ledger_execution']['process_observation']['observed_identities'].pop()
    else: case['ledger_durability_damage'] = damage.removeprefix('manifest-')
    _completed_ledger_reseal_unit_data(case)
    before = case['ledger'].read_bytes()
    with pytest.raises(recovery.resources.DaemonResourceError): _completed_ledger_call(case, operation)
    _sampled_assert_unchanged(case, before)


@pytest.mark.parametrize('operation', ['inspect', 'reconcile'])
@pytest.mark.parametrize('damage', ['missing-reference', 'wrong-path', 'wrong-hash', 'missing-file', 'hardlink'])
def test_completed_ledger_refuses_aliased_missing_or_detached_sealed_artifacts(setup, monkeypatch, operation, damage):
    case = _completed_ledger_unit_case(setup, monkeypatch)
    offered_artifacts = _sampled_copy(case['args']['expected_artifacts'])
    refs = case['sealed_artifacts']
    alias = None
    if damage == 'missing-reference': refs.pop('execution')
    elif damage == 'wrong-path': refs['execution'] = dict(refs['result'])
    elif damage == 'wrong-hash': refs['execution']['sha256'] = '0'*64
    elif damage == 'missing-file': case['ledger_sealed_paths']['execution'].unlink()
    else:
        alias = case['ledger'].parent/'authored-execution-alias'
        os.link(case['ledger_sealed_paths']['execution'], alias)
    before = case['ledger'].read_bytes()
    expected_after_damage = _completed_ledger_diagnostic_owned_files(case)
    try:
        with pytest.raises((recovery.resources.DaemonResourceError, OSError)):
            _completed_ledger_call(case, operation)
        _completed_ledger_assert_rejection_preserved_authored_damage(
            case, before, offered_artifacts, expected_after_damage)
        if alias is not None:
            target = case['ledger_sealed_paths']['execution'].lstat()
            linked = alias.lstat()
            assert (target.st_dev,target.st_ino)==(linked.st_dev,linked.st_ino)
            assert target.st_nlink == linked.st_nlink == 2
            assert alias.read_bytes() == case['ledger_sealed_paths']['execution'].read_bytes()
    finally:
        if alias is not None:
            # Remove only this negative control's verified own alias after its
            # rejection assertions; keep the original execution and failures.
            target = case['ledger_sealed_paths']['execution'].lstat()
            linked = alias.lstat()
            assert (target.st_dev,target.st_ino)==(linked.st_dev,linked.st_ino)
            assert target.st_nlink == linked.st_nlink == 2
            alias.unlink()
    if alias is not None:
        assert not alias.exists()
        _sampled_assert_unchanged(case, before)


@pytest.mark.parametrize('operation', ['inspect', 'reconcile'])
@pytest.mark.parametrize('damage', ['owner-present', 'reused-child', 'Native-lease', 'Native-waiter', 'row-changed', 'cap-changed'])
def test_completed_ledger_keeps_current_process_native_record_and_cap_guards(setup, monkeypatch, operation, damage):
    case = _completed_ledger_unit_case(setup, monkeypatch)
    row = case['row']
    if damage == 'owner-present': case['process_table'][row['owner_pid']] = {'pid':row['owner_pid'],'birth':row['owner_birth'],'group_pid':row['owner_pid'],'state':'S'}
    elif damage == 'reused-child': case['process_table'][row['child']['pid']] = {'pid':row['child']['pid'],'birth':'999','group_pid':row['child']['pid'],'state':'S'}
    elif damage == 'Native-lease': case['scheduler_state']['leases'][row['native_lease_id']] = {'lease_id':row['native_lease_id']}
    elif damage == 'Native-waiter': case['scheduler_state']['waiters']['authored-waiter'] = {'request_id':'validation:'+case['args']['reservation_id'],'owner_pid':row['owner_pid']}
    elif damage == 'row-changed':
        ledger = json.loads(case['ledger'].read_bytes());ledger['reservations'][case['args']['reservation_id']]['retention_reason'] = 'authored foreign rewrite';case['ledger'].write_text(json.dumps(ledger))
    else: monkeypatch.setattr(recovery.resources, 'MAX_STORAGE_BYTES', recovery.resources.MAX_STORAGE_BYTES+1)
    before = case['ledger'].read_bytes()
    with pytest.raises(recovery.resources.DaemonResourceError): _completed_ledger_call(case, operation)
    if damage == 'row-changed': assert case['ledger'].read_bytes() == before
    else: _sampled_assert_unchanged(case, before)


@pytest.mark.parametrize('operation', ['inspect', 'reconcile'])
@pytest.mark.parametrize('damage', ['late-addition', 'same-bytes-new-inode', 'late-original-failure'])
def test_completed_ledger_rechecks_sealed_witnesses_after_inventory_before_commit(setup, monkeypatch, operation, damage):
    case = _completed_ledger_unit_case(setup, monkeypatch)
    before = case['ledger'].read_bytes()
    offered_artifacts = _sampled_copy(case['args']['expected_artifacts'])
    original = recovery._durable_inventory
    changed, expected_after_damage = [], []
    def observed(attempt):
        value = original(attempt)
        if Path(attempt) == case['args']['attempt_directory'] and not changed:
            changed.append(True)
            if damage == 'late-addition': (attempt/'logs/late-authored.txt').write_bytes(b'late file')
            elif damage == 'same-bytes-new-inode':
                path=case['ledger_sealed_paths']['execution'];replacement=case['ledger'].parent/'authored-replacement.json';replacement.write_bytes(path.read_bytes());os.replace(replacement,path)
            else: (attempt/'logs/failure.json').write_bytes(b'{"authored_changed_failure":true}')
            expected_after_damage.append(_completed_ledger_diagnostic_owned_files(case))
        return value
    with monkeypatch.context() as injection:
        injection.setattr(recovery, '_durable_inventory', observed)
        with pytest.raises(recovery.resources.DaemonResourceError): _completed_ledger_call(case, operation)
    assert changed == [True]
    assert len(expected_after_damage) == 1
    _completed_ledger_assert_rejection_preserved_authored_damage(
        case, before, offered_artifacts, expected_after_damage[0])


@pytest.mark.parametrize('policy', [None, 'require_capacity'])
def test_completed_ledger_requires_explicit_administrative_closeout_before_owner(setup, monkeypatch, policy):
    case = _completed_ledger_unit_case(setup, monkeypatch)
    before = case['ledger'].read_bytes()
    def forbidden(*args, **kwargs): raise AssertionError('missing closeout policy reached live owner')
    monkeypatch.setattr(recovery, '_sampled_open_scheduler', forbidden)
    with pytest.raises(recovery.resources.DaemonResourceError):
        _completed_ledger_call(case, 'reconcile', capacity_policy=policy)
    assert case['scheduler_calls'] == []
    _sampled_assert_unchanged(case, before)


@pytest.mark.parametrize('operation', ['inspect', 'reconcile'])
def test_completed_ledger_refuses_fsync_failure_without_claim_release(setup, monkeypatch, operation):
    case = _completed_ledger_unit_case(setup, monkeypatch)
    before = case['ledger'].read_bytes()
    def refused(*args, **kwargs): raise OSError('authored sealed artifact fsync refusal')
    with monkeypatch.context() as injection:
        injection.setattr(recovery.os, 'fsync', refused)
        with pytest.raises(OSError, match='fsync refusal'): _completed_ledger_call(case, operation)
    # The original fsync is restored before the existing assertion helper
    # independently checks the unchanged ledger and durable file inventory.
    _sampled_assert_unchanged(case, before)


@pytest.mark.parametrize('route', ['default-sampled', 'old-completed-watchdog'])
def test_completed_ledger_does_not_widen_existing_failure_categories(setup, monkeypatch, route):
    if route == 'default-sampled':
        case = _completed_ledger_unit_case(setup, monkeypatch)
        call = lambda: _sampled_inspect(case)
    else:
        case = _completed_watchdog_unit_case(setup, monkeypatch, owner_pair='86c8-4df', subject_pair='86c8-4df', publish_evidence=False)
        case['terminal']['failure'].update(error_type='DaemonResourceError', error='disk ledger lock unavailable')
        _completed_watchdog_reseal_unit_data(case)
        call = lambda: _completed_watchdog_call(case)
    before = case['ledger'].read_bytes()
    def forbidden(*args, **kwargs): raise AssertionError('new ledger-finalization category leaked to old profile')
    monkeypatch.setattr(recovery, '_sampled_open_scheduler', forbidden)
    with pytest.raises(recovery.resources.DaemonResourceError): call()
    assert case['scheduler_calls'] == []
    _sampled_assert_unchanged(case, before)


@pytest.mark.parametrize('variant', ['valid-nonempty-stderr', 'missing-nonempty-stderr', 'reversed-evidence-order'])
def test_completed_ledger_preserves_nonempty_original_stderr_in_exact_evidence_order(setup, monkeypatch, variant):
    case = _completed_ledger_unit_case(setup, monkeypatch)
    attempt = case['args']['attempt_directory']
    case['ledger_stderr'] = b'Legitimate authored original warning; no failure normalization.\n'
    expected = [str(attempt/'logs/stdout.log'), str(attempt/'logs/stderr.log'), str(attempt/'logs/execution.json')]
    case['ledger_result']['evidence_paths'] = list(expected)
    if variant == 'missing-nonempty-stderr': case['ledger_result']['evidence_paths'].pop(1)
    elif variant == 'reversed-evidence-order': case['ledger_result']['evidence_paths'].reverse()
    _completed_ledger_reseal_unit_data(case)
    before = case['ledger'].read_bytes()
    stderr = (attempt/'logs/stderr.log').read_bytes()
    if variant == 'valid-nonempty-stderr':
        ready = _completed_ledger_call(case)
        assert ready['ready'] is True and ready['state_written'] is False
        _sampled_assert_unchanged(case, before)
        receipt = _completed_ledger_call(case, 'reconcile')
        selected = json.loads(case['ledger'].read_bytes())['reservations'][case['args']['reservation_id']]
        assert selected['status'] == 'released' and selected['explicit_reconciliation'] == receipt
        assert receipt['admitted'] is receipt['native_release_performed'] is False
        assert selected['artifacts_durable_asserted'] is True
    else:
        for operation in ('inspect', 'reconcile'):
            with pytest.raises(recovery.resources.DaemonResourceError): _completed_ledger_call(case, operation)
            _sampled_assert_unchanged(case, before)
    assert (attempt/'logs/stderr.log').read_bytes() == stderr
    assert case['terminal']['failure']['error'] == 'disk ledger lock unavailable'
    assert case['terminal']['completed'] is case['terminal']['failure']['completed'] is False
    assert case['parent']['owner_returncode'] == 1


def test_completed_ledger_prewrite_status_requires_actual_locked_recheck(setup, monkeypatch):
    from contextlib import nullcontext
    case = _completed_ledger_unit_case(setup, monkeypatch)
    before = case['ledger'].read_bytes()
    native = recovery.resources.native_deadlines
    original = native.resource_operation_deadline()
    cutoff = (recovery.resources.time.monotonic() + 240 if original is None else
        min(original.work_deadline_monotonic, original.native_deadline_monotonic))
    scope = (nullcontext() if original is not None and original.cleanup_only else
        native.resource_cleanup_deadline(native_deadline_monotonic=cutoff))
    inputs = dict(case['ledger_args'])
    proof_raw = inputs.pop('proof_raw')
    sealed = inputs.pop('sealed_artifacts')
    with scope:
        profile = recovery._completed_ledger_finalization_profile_v1(
            proof_raw, sealed, ledger_path=case['ledger'], **inputs)
    assert profile['summary']['sealed_full9_prewrite_guard_required'] is True
    assert 'sealed_full9_rechecked_before_write' not in profile['summary']
    assert case['scheduler_calls'] == []
    _sampled_assert_unchanged(case, before)
    ready = _completed_ledger_call(case)
    assert ready['ready'] is True and ready['state_written'] is False
    assert ready['proof']['sealed_full9_prewrite_guard_required'] is True
    assert ready['proof']['sealed_full9_rechecked_before_write'] is True
    assert case['scheduler_calls']
    _sampled_assert_unchanged(case, before)


@pytest.mark.parametrize('variant', ['admission-inclusive-elapsed', 'elapsed-after-original-failure', 'nonfinite-execution-transport'])
def test_completed_ledger_elapsed_uses_original_cli_clock_without_replacing_productive_budget(setup, monkeypatch, variant):
    case = _completed_ledger_unit_case(setup, monkeypatch)
    timeout = case['request']['timeout_seconds']
    case['terminal']['failure']['elapsed_seconds'] = timeout + 65.0
    case['ledger_execution']['elapsed_seconds'] = timeout + 5.5
    if variant == 'elapsed-after-original-failure':
        case['ledger_execution']['elapsed_seconds'] = case['terminal']['failure']['elapsed_seconds'] + 0.25
    _completed_ledger_reseal_unit_data(case)
    attempt = case['args']['attempt_directory']
    if variant == 'nonfinite-execution-transport':
        # Authored hostile DATA is deliberately encoded outside the finite fixture
        # writer. Refresh every dependent hash so the product's closed-JSON parser,
        # rather than fixture serialization or a stale descriptor, must refuse it.
        execution_path = case['ledger_sealed_paths']['execution']
        execution = json.loads(execution_path.read_bytes())
        execution['elapsed_seconds'] = float('inf')
        execution_path.write_bytes(json.dumps(execution, sort_keys=True, separators=(',', ':'), allow_nan=True).encode())
        durability_path = case['ledger_sealed_paths']['durability']
        durability = json.loads(durability_path.read_bytes())
        stamp = execution_path.lstat()
        for row in durability['files']:
            if row['path'] == 'logs/execution.json':
                row.update(bytes=stamp.st_size, sha256=_sampled_sha(execution_path.read_bytes()),
                           device=stamp.st_dev, inode=stamp.st_ino)
                break
        else:
            raise AssertionError('authored execution must be in the original sealed manifest')
        durability_path.write_bytes(_sampled_wire(durability))
        case['args']['expected_artifacts'] = recovery._durable_inventory(attempt)
        case['sealed_artifacts'] = {name: _completed_ledger_unit_reference(path)
                                   for name, path in case['ledger_sealed_paths'].items()}
        case['ledger_args'] = dict(case['args'], sealed_artifacts=case['sealed_artifacts'])
        def forbidden(*args, **kwargs):
            raise AssertionError('nonfinite sealed transport reached the live owner')
        monkeypatch.setattr(recovery, '_sampled_open_scheduler', forbidden)
    before = case['ledger'].read_bytes()
    frames = tuple(_sampled_wire(case[name]) for name in ('request', 'terminal', 'parent'))
    files = {path: path.read_bytes() for path in attempt.rglob('*') if path.is_file()}
    if variant == 'admission-inclusive-elapsed':
        assert timeout < case['ledger_execution']['elapsed_seconds'] < case['terminal']['failure']['elapsed_seconds']
        ready = _completed_ledger_call(case)
        assert ready['ready'] is True and ready['state_written'] is False
        _sampled_assert_unchanged(case, before)
        receipt = _completed_ledger_call(case, 'reconcile')
        selected = json.loads(case['ledger'].read_bytes())['reservations'][case['args']['reservation_id']]
        assert selected['status'] == 'released' and selected['explicit_reconciliation'] == receipt
        assert receipt['admitted'] is receipt['native_release_performed'] is False
        assert receipt['sampled_custody_proof']['original_owner_completed'] is False
    else:
        for operation in ('inspect', 'reconcile'):
            with pytest.raises(recovery.resources.DaemonResourceError):
                _completed_ledger_call(case, operation)
            _sampled_assert_unchanged(case, before)
        if variant == 'nonfinite-execution-transport':
            assert case['scheduler_calls'] == []
    assert tuple(_sampled_wire(case[name]) for name in ('request', 'terminal', 'parent')) == frames
    assert all(path.read_bytes() == contents for path, contents in files.items())
    assert case['request']['timeout_seconds'] == timeout
    assert case['terminal']['completed'] is case['terminal']['failure']['completed'] is False
    assert case['parent']['owner_returncode'] == 1


def _completed_ledger_diagnostic_owned_files(case):
    """Snapshot authored negative-control files without asserting valid durability."""
    from stat import S_ISREG
    attempt = case['args']['attempt_directory']
    files = {}
    for path in sorted(attempt.rglob('*')):
        if path.is_file():
            info = path.lstat()
            assert S_ISREG(info.st_mode) and info.st_uid == os.getuid()
            files[str(path.relative_to(attempt))] = (
                path.read_bytes(), info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_nlink)
    return files


def _completed_ledger_assert_rejection_preserved_authored_damage(case, before, offered_artifacts, expected_files):
    # Deliberate file damage remains evidence. Never rewrite the original
    # expected_artifacts API input to make a rejected attempt look unchanged.
    assert case['ledger'].read_bytes() == before
    assert json.loads(before)['reservations'][case['prior_id']] == case['prior']
    assert case['args']['expected_artifacts'] == offered_artifacts
    assert case['ledger_args']['expected_artifacts'] == offered_artifacts
    assert _completed_ledger_diagnostic_owned_files(case) == expected_files


# Explicit private-cwd completed-body/ledger-finalization UNIT_DATA. These
# fixtures never execute the selected authored checks or rewrite actual history.
def _private_completed_ledger_reseal_unit_data(case):
    _completed_ledger_reseal_unit_data(case)
    # Reuse the two existing detached archive writer mechanics, retaining this
    # fixture's ledger error and sealed3 rather than a watchdog failure label.
    case['completed_publish_evidence'] = True
    _completed_watchdog_reseal_unit_data(case)
    case['private_ledger_args'] = dict(case['completed_args'], sealed_artifacts=case['sealed_artifacts'])


def _private_completed_ledger_unit_case(setup, monkeypatch, *, population=None):
    factory, roots, ledger, scheduler = setup
    assert not ledger.exists()
    # Same established large-watchdog fictional sizing, selected before either
    # original claim. The admitted qualification's real16MiB is independent.
    monkeypatch.setattr(recovery.resources, 'MAX_STORAGE_BYTES', 4_000_000)
    def promised_factory(**kwargs):
        kwargs.setdefault('storage_bytes', 2_000_000)
        return factory(**kwargs)
    case = _completed_ledger_unit_case((promised_factory, roots, ledger, scheduler), monkeypatch)
    canonical = Path(case['request']['cwd'])
    snapshot = ledger.parent / 'authored-private-completed-ledger-snapshot'
    snapshot.mkdir()
    check = snapshot / 'tests/test_authored_private_completed_ledger.py'
    check.parent.mkdir()
    check.write_bytes(b'# Fictional selected check DATA; never executed.\n')
    old_check = case['request']['selected_checks'][0]
    selected = str(check) + '::test_authored_completed_body'
    case['request']['cwd'] = str(snapshot)
    case['request']['selected_checks'] = [selected]
    case['request']['argv'] = [selected if value == old_check else value for value in case['request']['argv']]
    for relative in ('scripts/ops/legal_ir/run_owned_validation.py',
            'ipfs_datasets_py/optimizers/logic_theorem_optimizer/validation_run_resources.py',
            'ipfs_datasets_py/optimizers/logic_theorem_optimizer/autoencoder_daemon_resources.py'):
        case['request']['source_sha256'][str(snapshot / relative)] = case['request']['source_sha256'][str(canonical / relative)]
    case['request']['source_sha256'][str(check)] = _sampled_sha(check.read_bytes())
    for document in (case['terminal']['failure'], case['ledger_execution'], case['ledger_result']):
        document['executed_checks'] = [selected]
    case['private_ledger_roots'] = canonical, snapshot
    case['unit_data_provenance'] = 'authored private-cwd completed-ledger frames; no actual history or execution'
    if population is not None:
        current = len(recovery._durable_inventory(case['args']['attempt_directory']))
        assert type(population) is int and population > current
        directory = case['args']['attempt_directory'] / 'regular-population'
        directory.mkdir()
        for number in range(population - current):
            (directory / f'item-{number:04d}.txt').write_bytes(b'x')
    _private_completed_ledger_reseal_unit_data(case)
    if population is not None:
        assert len(case['args']['expected_artifacts']) == population
    assert case['row']['storage_bytes'] == 2_000_000
    assert case['terminal']['reservation']['storage_limit_bytes'] == recovery.resources.MAX_STORAGE_BYTES == 4_000_000
    assert sum(row['bytes'] for row in case['args']['expected_artifacts']) + sum(
        case['private_ledger_args'][key]['bytes'] for key in ('artifact_inventory_manifest', 'evidence_archive')) < case['row']['storage_bytes']
    return case


def _private_completed_ledger_call(case, operation='inspect', **overrides):
    function = (recovery.inspect_private_snapshot_completed_ledger_finalization_validation_recovery_v1
        if operation == 'inspect' else recovery.reconcile_private_snapshot_completed_ledger_finalization_validation_reservation_v1)
    arguments = dict(case['private_ledger_args'], **overrides)
    if operation == 'reconcile' and 'capacity_policy' not in overrides:
        arguments['capacity_policy'] = 'administrative_closeout'
    native = recovery.resources.native_deadlines
    original = native.resource_operation_deadline()
    if original is not None and original.cleanup_only:
        return function(case['ledger'], **arguments)
    cutoff = (recovery.resources.time.monotonic() + 240 if original is None else
        min(original.work_deadline_monotonic, original.native_deadline_monotonic))
    with native.resource_cleanup_deadline(native_deadline_monotonic=cutoff):
        return function(case['ledger'], **arguments)


def _private_completed_ledger_disposition(case, previous_sha, row):
    return recovery.inspect_validation_disposition(case['ledger'], roots=case['args']['roots'],
        reservation_id=case['args']['reservation_id'],
        expected_request_sha256=case['args']['expected_request_sha256'],
        attempt_directory=case['args']['attempt_directory'], expected_record_sha256=recovery._digest(row),
        expected_previous_record_sha256=previous_sha, process_scope='sampled_birth_bound_descendants')


def test_private_completed_ledger_compact_closeout_and_record_only_disposition(setup, monkeypatch):
    case = _private_completed_ledger_unit_case(setup, monkeypatch)
    before = case['ledger'].read_bytes()
    frames = tuple(_sampled_wire(case[key]) for key in ('request', 'terminal', 'parent'))
    previous_sha = case['args']['expected_record_sha256']
    ready = _private_completed_ledger_call(case)
    assert ready['schema'] == 'private-snapshot-completed-ledger-validation-recovery-readiness/v1'
    assert ready['ready'] is ready['capacity_not_assessed'] is True
    assert ready['state_written'] is ready['recovery_performed'] is ready['admitted'] is False
    _sampled_assert_unchanged(case, before)
    receipt = _private_completed_ledger_call(case, 'reconcile')
    assert receipt['schema'] == 'explicit-private-snapshot-completed-ledger-validation-reconciliation/v1'
    after = case['ledger'].read_bytes()
    data = json.loads(after)
    row = data['reservations'][case['args']['reservation_id']]
    assert row['status'] == 'released' and row['artifacts_durable_asserted'] is True
    assert row['explicit_reconciliation'] == receipt
    assert receipt['fresh_global_inventory_count'] == 2
    assert receipt['actual_postwrite_census_required'] is receipt['final_accounting_is_prewrite_projection'] is True
    assert receipt['full_claim_accounting']['outstanding_full_reservations_bytes'] - receipt['final_accounting']['outstanding_full_reservations_bytes'] == case['row']['storage_bytes']
    for result, proof_key in ((ready, 'proof'), (receipt, 'sampled_custody_proof')):
        proof = result[proof_key]
        assert 'artifacts' not in result
        assert result['artifact_count'] == len(case['args']['expected_artifacts'])
        assert result['artifact_inventory_manifest'] == case['private_ledger_args']['artifact_inventory_manifest']
        assert result['evidence_archive'] == case['private_ledger_args']['evidence_archive']
        assert proof['original_failure_profile'] == 'private-snapshot-source-held-V5-completed-command-ledger-finalization/v1'
        assert proof['original_command_returncode'] == 0 and proof['original_cli_returncode'] == 1
        assert proof['original_owner_completed'] is proof['retroactive_qualification_claimed'] is False
        assert proof['completed_body_ledger_private_snapshot_optin'] is proof['completed_body_ledger_finalization_optin'] is True
        assert proof['sealed_full9_prewrite_guard_required'] is proof['sealed_full9_rechecked_before_write'] is True
        assert proof.get('completed_body_watchdog_finalization_optin') is not True
        assert proof['original_storage_limit_bytes'] == proof['current_storage_limit_bytes'] == 4_000_000
        assert proof['storage_limit_transition'] == 'unchanged/v1'
        assert proof['sealed_completed_artifacts'] == case['sealed_artifacts']
    for key in ('native_release_performed', 'admitted', 'outputs_deleted', 'cap_changed',
            'request_budget_changed', 'new_reservation_created', 'new_resource_lease_acquired',
            'source_authority_granted', 'retroactive_qualification_claimed', 'test_or_task_acceptance_asserted'):
        assert receipt[key] is False
    assert tuple(_sampled_wire(case[key]) for key in ('request', 'terminal', 'parent')) == frames
    assert recovery._durable_inventory(case['args']['attempt_directory']) == case['args']['expected_artifacts']
    def forbidden(*args, **kwargs):
        raise AssertionError('record-only disposition attempted live inventory, archives or Native')
    with monkeypatch.context() as inspection:
        inspection.setattr(recovery, '_durable_inventory', forbidden)
        inspection.setattr(recovery, '_released_artifact_reference', forbidden)
        inspection.setattr(recovery, '_sampled_open_scheduler', forbidden)
        report = _private_completed_ledger_disposition(case, previous_sha, row)
    assert report['storage_release_established'] is True and report['native_release_established'] is False
    assert report['state_written'] is report['recovery_performed'] is report['admitted'] is False
    assert case['ledger'].read_bytes() == after
    assert data['reservations'][case['prior_id']] == case['prior']


@pytest.mark.parametrize('population', [4097, 4169])
def test_private_completed_ledger_large_population_uses_existing_compact_hot_ledger(setup, monkeypatch, population):
    case = _private_completed_ledger_unit_case(setup, monkeypatch, population=population)
    before = case['ledger'].read_bytes()
    ceiling = len(before) + 20000
    monkeypatch.setattr(recovery.resources, 'MAX_LEDGER_BYTES', ceiling)
    assert len(_sampled_wire(case['args']['expected_artifacts'])) > ceiling
    with pytest.raises(recovery.resources.DaemonResourceError):
        recovery._sampled_artifacts(case['args']['expected_artifacts'])
    ready = _private_completed_ledger_call(case)
    _sampled_assert_unchanged(case, before)
    receipt = _private_completed_ledger_call(case, 'reconcile')
    assert ready['artifact_count'] == receipt['artifact_count'] == population
    assert receipt['sampled_custody_proof']['original_sealed_artifact_count'] == population - 2
    assert 'artifacts' not in receipt and 'artifacts' not in ready
    assert len(case['ledger'].read_bytes()) < ceiling
    assert sum(case['private_ledger_args'][key]['bytes'] for key in ('artifact_inventory_manifest', 'evidence_archive')) < case['row']['storage_bytes']
    assert recovery._durable_inventory(case['args']['attempt_directory']) == case['args']['expected_artifacts']
    assert json.loads(case['ledger'].read_bytes())['limit_bytes'] == 4_000_000


@pytest.mark.parametrize('operation', ['inspect', 'reconcile'])
@pytest.mark.parametrize('damage', ['canonical-cwd', 'overlapping-cwd', 'selector-outside-private', 'private-SDK', 'private-host'])
def test_private_completed_ledger_requires_exact_distinct_private_scope_before_owner(setup, monkeypatch, operation, damage):
    case = _private_completed_ledger_unit_case(setup, monkeypatch)
    canonical, snapshot = case['private_ledger_roots']
    if damage == 'canonical-cwd': case['request']['cwd'] = str(canonical)
    elif damage == 'overlapping-cwd': case['request']['cwd'] = str(canonical / 'authored-private-child')
    elif damage == 'selector-outside-private':
        selected = str(case['ledger'].parent / 'authored-separately-pinned-checks/test_completed_ledger_fixture.py') + '::test_authored_completed_body'
        old = case['request']['selected_checks'][0]
        case['request']['selected_checks'] = [selected]
        case['request']['argv'] = [selected if value == old else value for value in case['request']['argv']]
        for doc in (case['terminal']['failure'], case['ledger_execution'], case['ledger_result']): doc['executed_checks'] = [selected]
    else:
        relative = ('validation_run_resources.py' if damage == 'private-SDK' else 'autoencoder_daemon_resources.py')
        case['request']['source_sha256'][str(snapshot / 'ipfs_datasets_py/optimizers/logic_theorem_optimizer' / relative)] = 'f' * 64
    _private_completed_ledger_reseal_unit_data(case)
    before = case['ledger'].read_bytes()
    def forbidden(*args, **kwargs): raise AssertionError('invalid private scope reached current live owner')
    monkeypatch.setattr(recovery, '_sampled_open_scheduler', forbidden)
    monkeypatch.setattr(recovery.resources, 'DaemonResourceReservation', forbidden)
    with pytest.raises(recovery.resources.DaemonResourceError): _private_completed_ledger_call(case, operation)
    _sampled_assert_unchanged(case, before)


@pytest.mark.parametrize('operation', ['inspect', 'reconcile'])
@pytest.mark.parametrize('damage', ['watchdog-category', 'failed-body', 'Source-open'])
def test_private_completed_ledger_preserves_original_failure_category_and_closed_Source(setup, monkeypatch, operation, damage):
    case = _private_completed_ledger_unit_case(setup, monkeypatch)
    if damage == 'watchdog-category': case['terminal']['failure'].update(error_type='RuntimeError', error='validation watchdog did not finish cleanly')
    elif damage == 'failed-body': case['terminal']['failure']['returncode'] = 1
    else: case['parent']['source_closed'] = False
    _private_completed_ledger_reseal_unit_data(case)
    before = case['ledger'].read_bytes()
    with pytest.raises(recovery.resources.DaemonResourceError): _private_completed_ledger_call(case, operation)
    _sampled_assert_unchanged(case, before)


@pytest.mark.parametrize('operation', ['inspect', 'reconcile'])
@pytest.mark.parametrize('damage', ['incomplete-execution', 'missing-file', 'inode', 'result-sha'])
def test_private_completed_ledger_compact_path_still_requires_complete_original_seal(setup, monkeypatch, operation, damage):
    case = _private_completed_ledger_unit_case(setup, monkeypatch)
    if damage == 'incomplete-execution': case['ledger_execution']['completed'] = False
    else: case['ledger_durability_damage'] = damage
    _private_completed_ledger_reseal_unit_data(case)
    before = case['ledger'].read_bytes()
    with pytest.raises(recovery.resources.DaemonResourceError): _private_completed_ledger_call(case, operation)
    _sampled_assert_unchanged(case, before)


@pytest.mark.parametrize('damage', ['owner-present', 'reused-child', 'Native-lease', 'Native-waiter', 'row-changed', 'cap-changed'])
def test_private_completed_ledger_keeps_current_custody_record_and_cap_guards(setup, monkeypatch, damage):
    case = _private_completed_ledger_unit_case(setup, monkeypatch)
    row = case['row']
    if damage == 'owner-present': case['process_table'][row['owner_pid']] = {'pid':row['owner_pid'],'birth':row['owner_birth'],'group_pid':row['owner_pid'],'state':'S'}
    elif damage == 'reused-child': case['process_table'][row['child']['pid']] = {'pid':row['child']['pid'],'birth':'999','group_pid':row['child']['pid'],'state':'S'}
    elif damage == 'Native-lease': case['scheduler_state']['leases'][row['native_lease_id']] = {'lease_id':row['native_lease_id']}
    elif damage == 'Native-waiter': case['scheduler_state']['waiters']['authored-waiter'] = {'request_id':'validation:'+case['args']['reservation_id'],'owner_pid':row['owner_pid']}
    elif damage == 'row-changed':
        state = json.loads(case['ledger'].read_bytes());state['reservations'][case['args']['reservation_id']]['retention_reason'] = 'authored foreign rewrite';case['ledger'].write_text(json.dumps(state))
    else: monkeypatch.setattr(recovery.resources, 'MAX_STORAGE_BYTES', recovery.resources.MAX_STORAGE_BYTES + 1)
    before = case['ledger'].read_bytes()
    with pytest.raises(recovery.resources.DaemonResourceError): _private_completed_ledger_call(case, 'reconcile')
    _sampled_assert_unchanged(case, before)


@pytest.mark.parametrize('damage', ['late-addition', 'same-bytes-new-inode', 'late-original-failure'])
def test_private_completed_ledger_rechecks_sealed_witnesses_before_compact_write(setup, monkeypatch, damage):
    case = _private_completed_ledger_unit_case(setup, monkeypatch)
    before = case['ledger'].read_bytes()
    offered = _sampled_copy(case['args']['expected_artifacts'])
    original = recovery._durable_inventory
    changed, expected = [], []
    def observed(attempt):
        value = original(attempt)
        if Path(attempt) == case['args']['attempt_directory'] and not changed:
            changed.append(True)
            if damage == 'late-addition': (attempt / 'logs/late-authored.txt').write_bytes(b'late file')
            elif damage == 'same-bytes-new-inode':
                path=case['ledger_sealed_paths']['execution'];replacement=case['ledger'].parent/'private-authored-replacement.json';replacement.write_bytes(path.read_bytes());os.replace(replacement,path)
            else: (attempt / 'logs/failure.json').write_bytes(b'{"authored_changed_failure":true}')
            expected.append(_completed_ledger_diagnostic_owned_files(case))
        return value
    with monkeypatch.context() as injection:
        injection.setattr(recovery, '_durable_inventory', observed)
        with pytest.raises(recovery.resources.DaemonResourceError): _private_completed_ledger_call(case, 'reconcile')
    assert changed == [True] and len(expected) == 1
    _completed_ledger_assert_rejection_preserved_authored_damage(case, before, offered, expected[0])
    assert case['private_ledger_args']['expected_artifacts'] == offered


@pytest.mark.parametrize('damage', ['schema', 'attempt', 'missing-artifact', 'unknown-field', 'archive-other-proof', 'manifest-in-attempt', 'shared-reference', 'bool-size'])
def test_private_completed_ledger_authenticates_detached_compact_evidence(setup, monkeypatch, damage):
    case = _private_completed_ledger_unit_case(setup, monkeypatch)
    arguments = case['private_ledger_args']
    reference = arguments['artifact_inventory_manifest']
    manifest = json.loads(Path(reference['path']).read_bytes())
    if damage == 'schema': manifest['schema'] = 'invented-inventory/v1'
    elif damage == 'attempt': manifest['attempt_directory']['inode'] += 1
    elif damage == 'missing-artifact': manifest['artifacts'] = []
    elif damage == 'unknown-field': manifest['unreviewed_durability_authority'] = True
    elif damage == 'archive-other-proof':
        reference = arguments['evidence_archive'];manifest = json.loads(Path(reference['path']).read_bytes());manifest['provenance'] = 'invented-execution-attestation/v1'
    elif damage == 'manifest-in-attempt': reference['path'] = str(case['args']['attempt_directory'] / 'invented-manifest.json')
    elif damage == 'shared-reference': arguments['evidence_archive'] = _sampled_copy(reference)
    else: reference['bytes'] = True
    if damage not in ('shared-reference', 'bool-size', 'manifest-in-attempt'):
        raw = _sampled_wire(manifest);Path(reference['path']).write_bytes(raw);reference.update(bytes=len(raw),sha256=_sampled_sha(raw))
    before = case['ledger'].read_bytes()
    with pytest.raises(recovery.resources.DaemonResourceError): _private_completed_ledger_call(case, 'reconcile')
    _sampled_assert_unchanged(case, before)


@pytest.mark.parametrize('damage', ['manifest-same-bytes-new-inode', 'caller-ref-mutation'])
def test_private_completed_ledger_rechecks_detached_evidence_generation_before_commit(setup, monkeypatch, damage):
    case = _private_completed_ledger_unit_case(setup, monkeypatch)
    before = case['ledger'].read_bytes()
    original = recovery._administrative_census
    changed = []
    def observed(helper, ledger):
        value = original(helper, ledger)
        if not changed:
            changed.append(True)
            reference = case['private_ledger_args']['artifact_inventory_manifest']
            if damage == 'caller-ref-mutation': reference['sha256'] = 'f' * 64
            else:
                path=Path(reference['path']);replacement=path.with_name('authored-new-manifest-inode.json');replacement.write_bytes(path.read_bytes());os.replace(replacement,path)
        return value
    with monkeypatch.context() as injection:
        injection.setattr(recovery, '_administrative_census', observed)
        with pytest.raises(recovery.resources.DaemonResourceError): _private_completed_ledger_call(case, 'reconcile')
    assert changed == [True]
    _sampled_assert_unchanged(case, before)


@pytest.mark.parametrize('damage', ['other-row-during-census', 'hot-ledger-bound', 'fsync-failure'])
def test_private_completed_ledger_preserves_atomic_accounting_and_durability_guards(setup, monkeypatch, damage):
    case = _private_completed_ledger_unit_case(setup, monkeypatch)
    before = case['ledger'].read_bytes()
    with monkeypatch.context() as injection:
        if damage == 'hot-ledger-bound': injection.setattr(recovery.resources, 'MAX_LEDGER_BYTES', len(before) + 32)
        elif damage == 'fsync-failure':
            def refused(*args, **kwargs): raise OSError('authored private compact durability refusal')
            injection.setattr(recovery.os, 'fsync', refused)
        else:
            original = recovery._administrative_census
            def foreign(helper, state):
                result = original(helper, state)
                state['reservations'][case['prior_id']]['retention_reason'] = 'authored foreign mutation'
                return result
            injection.setattr(recovery, '_administrative_census', foreign)
        with pytest.raises((recovery.resources.DaemonResourceError, OSError)):
            _private_completed_ledger_call(case, 'reconcile')
    _sampled_assert_unchanged(case, before)


@pytest.mark.parametrize('route', ['canonical-ledger', 'default-sampled', 'manual-private', 'watchdog'])
def test_private_completed_ledger_does_not_widen_existing_recovery_categories(setup, monkeypatch, route):
    case = _private_completed_ledger_unit_case(setup, monkeypatch)
    before = case['ledger'].read_bytes()
    with pytest.raises(recovery.resources.DaemonResourceError):
        if route == 'canonical-ledger': _completed_ledger_call(case)
        elif route == 'default-sampled': _sampled_inspect(case)
        elif route == 'manual-private': _manual_snapshot_call(case)
        else: _completed_watchdog_call(case)
    _sampled_assert_unchanged(case, before)


@pytest.mark.parametrize('damage', ['profile', 'watchdog-schema', 'subject-SDK', 'subject-host', 'qualification', 'sealed-recheck', 'sealed-population', 'sealed-descriptor', 'inventory-bytes', 'archive-reference', 'cap-transition', 'census-count'])
def test_private_completed_ledger_record_only_disposition_refuses_relabeling_or_corruption(setup, monkeypatch, damage):
    case = _private_completed_ledger_unit_case(setup, monkeypatch)
    previous_sha = case['args']['expected_record_sha256']
    _private_completed_ledger_call(case, 'reconcile')
    state = json.loads(case['ledger'].read_bytes())
    row = state['reservations'][case['args']['reservation_id']]
    receipt = row['explicit_reconciliation'];proof = receipt['sampled_custody_proof']
    if damage == 'profile': proof['original_failure_profile'] = 'source-held-V5-completed-command-watchdog-finalization/v1'
    elif damage == 'watchdog-schema': receipt['schema'] = 'explicit-completed-watchdog-validation-reconciliation/v1'
    elif damage == 'subject-SDK': proof['private_subject_sdk_sha256'] = 'f' * 64
    elif damage == 'subject-host': proof['private_subject_resource_owner_sha256'] = 'f' * 64
    elif damage == 'qualification': proof['retroactive_qualification_claimed'] = True
    elif damage == 'sealed-recheck': proof['sealed_full9_rechecked_before_write'] = False
    elif damage == 'sealed-population': proof['original_sealed_artifact_count'] -= 1
    elif damage == 'sealed-descriptor': proof['sealed_completed_artifacts']['execution']['path'] = str(case['ledger'].parent / 'not-original.json')
    elif damage == 'inventory-bytes': receipt['artifact_bytes'] += 1
    elif damage == 'archive-reference': receipt['evidence_archive']['sha256'] = 'f' * 64
    elif damage == 'cap-transition':
        proof['original_storage_limit_bytes'] = receipt['original_storage_limit_bytes'] = 220_000_000_000
        proof['current_storage_limit_bytes'] = receipt['current_storage_limit_bytes'] = 250_000_000_000
        proof['storage_limit_transition'] = receipt['storage_limit_transition'] = 'historical220GB-current250GB/v1'
    else: receipt['fresh_global_inventory_count'] = 1
    case['ledger'].write_text(json.dumps(state));before = case['ledger'].read_bytes()
    def forbidden(*args, **kwargs): raise AssertionError('corrupt record-only receipt caused live work')
    with monkeypatch.context() as inspection:
        inspection.setattr(recovery, '_durable_inventory', forbidden)
        inspection.setattr(recovery, '_released_artifact_reference', forbidden)
        inspection.setattr(recovery, '_sampled_open_scheduler', forbidden)
        with pytest.raises(recovery.resources.DaemonResourceError): _private_completed_ledger_disposition(case, previous_sha, row)
    assert case['ledger'].read_bytes() == before
    assert state['reservations'][case['prior_id']] == case['prior']


# Immutable current source captures are DATA, never imported or executed.
_SAMPLED_V5_FINITE_PAIR_SOURCE_DATA['cli7ce'] = (
    'c-'
    'ri}Yj@j5vMBnUzXC}<fQ%_ha%{&@!dX|bl^LILEFVe9>@009EQo|8Zc_v|LE6@2{NHcaqu<>CNJ&oSjIw4D5olDus;lc=UwyH?su'
    'tVlli7ALd!Nj2mRIHMo6eVCetEQ-CB?`2bTXPOljUMnEsJq7x++HRs^r6Dd6ks2BAMmO$@?OCpHC-'
    'a@n<<p^4U14mgOS9ERyoWtXK>>os+9cl~nold@4Z97v-'
    'p^s;$dKxthbTi^;S|M1xtmO!5SNRX3uu>*Rk|<uXsoMKUU9%X~7sE@sQ5yy)bM^T~3NFK&`?QH_e(IG-'
    ')6LGo&u%!>ELBDq|^gQP01#eXLwfbhD=#n8srld2Mf9KifK7mM;b$+C;pa<wS3ESX%-'
    '%Y_)iObi6)Qgu4=+2V4ZFRDWRzRIhs>EvAg{GY0v$-l4j<(2%qtf-T@cqW?59^M*Fs>$UnpXy&r)kh@;q5fW-'
    '^RlTYH|o#j)uPD9li8(uFu5)|ouk9UlVpgUb;T^jvSwLtuqdi>`o8G)24X^DJ*(4i&N{~@`$s3gyv<&`K78@_?C9YC{&H}9k{!SJ'
    '+riKK0z?Y?INs8mytOF)cU4r&?f1`8=i|3Whd;e~eIUO2J*@<`T<7VY|Gk*oV!4`cji%-3-'
    'S+$4wBJd@KdIWGtSZE&kE?WV_xVmg6_X#YMu2M0i>27Asebn4@y@4Cr!y`tl4_REtE+O^g~jiSZTUF4UR@7&cOF0a8vfN!zV0Xab'
    'XtDMitG9EX82P+t%}|r4rFqXEN|vT*LdHPD0*I&Q)&hOEb>WJB){g<RdKLbl#6a^e3M*@Q<Iz*0;j}L%188Z+QYA}Co>q4Sg9T8&'
    '-|<qBT06#6^vf)BK%F?UI>(?{YxgZ1YhueifI|Y<R<s@fJIj@3&5_yarWx?<*TDEH=e>nff>~@yDrCt@lklDli7T=OvaN%F%k#<1'
    '{MgnZ*~bsPV9DG6=R+)QH*MEF)ruDtSkP)|I+4&Ux(Sz%fmOXfBP5y{pRqe!`H75{~>?9`4Nz-'
    '*H6;LdD=^Iak!TP>96$&&kM08g;*)*1Lr|427vgpvfJxLSK#R2uU-'
    '0F%^b$BAI+wd*}LS6VX_O);aj<PKMaj#)#RTAJYiI8TD|jfH5&_hxSH`wC5z&6HO&_Ztt*@{v9xjl3CIUAL!KBM`Y!kNXjeDNFP4'
    'G^HZ8<tEOvY%aBY}O^Xv0*o>Y6?3Z^kG-uLm3$*iP5U}E&wHISBUR?)8!|LVyzBRc4cG4^1soOKZkC%fdu##ZVXj=E<x<40yIL~T'
    'aXUfm(2B^+JlvrDnCAFkkvVJgY%xhMqLpTUwc!C;!kC^?>7iXYquue(W6)SUS$7*tpJ<EPJX`h%<DBYoe+;nUxB!{xpam}q`+Q7k'
    'GR=X+=-dWSn^FfH?Og?-5G@%7-'
    'cSav13?IDH&S*W4gg5uVZ^~d$EpVYs8Dqh!JDYZMdnpLYgTw`M247P%Sr}o58zobcjd6o=^wS6LA0t=Jz-IL+nlg-L(B(P(gaR-'
    '^$M?v@zdLK5vZm?ep7;tc{>r4(+?&FshzG=Yno+?+1QITD)^2M0C<sRpgSta(J=9zLc!m{+tx}~6{x}L@pam_H9f){mbt=Kzbp{X'
    'P4-'
    '627A>*&(~NCxc&f@`_1y7ndGoD1hVraPD~V)GV0S%?K_JVD{<__JUFu$QEd=+M%dPp+?5%luq$L~yEjNaotpfyW~^UR}>Ci4T>)%'
    'j{ioQ{g!KVgZ0M4Ij%n%<>uY5rbkj5;sY=_vk$R?^%jafm>Zn=Hjj-^6cJ#FOClOPw2`!_^%hQ>92nr`PX7U*(smx>;!LC-HAA(A'
    '0oFUUkM);V&^nDG2UEESJhQlKgP@CW;P06Cd`WHNojUPu_fLeFBp%57bk~D&fEy%a&fcgcTTVv87Jc2oZ7AMII32XtOGI0M)^D!n'
    '0_P9`NgWrr`-Z@2AM!{dM}INmn5vf@V{g%5JJL_0`0bniwhJ2E-%Fmoi7W4j``)Rtb}awJ$)@jj#-'
    '&ZCl|%&W+d*Ld?jQlvBEb4kT$$o$<vDf)bSPT3#XT$N<waqt)F~37hPxgC^Ltv4hB&g#6$JsTF4FnQgHK9IuoKmv3O7CMJ|tEQ%6'
    'N1*pk#7XBP*GE7lui0?V&KUJ~areVG^6<?N`S^M>azwFZMbvq&_6fsmy%wGvcwip&A94(5B{wpsu>-'
    '8nOtF7$<N3_!cQ5d9u4^Ma=Z@Ay@l<t)$j+6}o2g<{4_y^6DCaVa+JVp2@UK-b0XjLnL1md^=gv-'
    '6u}QQ_UXS_%x90lOmP)9Exb_NtQ2tWgTlX*_|~`BYwI0<r=q2;t(=d@!9{PnKaw%-'
    'm*L63;FcMWMfC1kz_poHMva!r)vmc4JLqKr|9ky17DLM+!UpK3s7Ttu6qxSjn{Kqpz_m)@2#OnS6Fb9|>A-'
    '9Zk3b#WOgSCcF@gO7LV>pI;a<F|6W99A5Fq*EVX12lh&QiXH<4`l$rmcpQQs;aMKzS>9UkVcwFfzGZv@oMYSZ!1UG~4t|590U{%~'
    'va(!OSvi~DxTmCc+f1lpyYwi;T6-'
    'Vr@1eyGh;Z)r$q&inufKlwjk*8!w)Hj}4{Wsw)ZY4D8&afBI~*BnIonW?v+!~}vNxuNxSZ*kGm%N`^^4NEGtrBJW-'
    'uUh=9x?+C{K5H`U?7%4c#PU##jvM;6c(W=D@0_d}lUMvA(qFD`GG|YDW5cYKpL&MQMatPjeBZzd-AcRFUH|iO*ek`~H&b^wu7(Ma'
    'nhoz@Emy$HoHhB4ApbHCHZx3#3a_bm&XOih?rJsWqJ%+kyAQfA@)v$beuBgNzlo7)ln#f@Cb{(7bkhp`|LsG0er<RKsrChpT8W?b'
    '*Nzu>p%B%d633!e6-'
    'pjySwZu(8!YQuIkz%Zsh&X|E@i_sPz8&swZ62qen_SSqnWgK9Yz6Ano!{4vs2{su{^pvfrcD>y@?lfrKSVdu-'
    '_$Gj>I@K3Qqd!68rI-S?AemZ#Z+l$u+b((N_SFQxIjc>LT_m3B4ra>J1dhq7t7}esMbI)=yN+I?VLt{Lrk-'
    '%fpi<63Cny+S~EBhmQGZI1>KRC}9i-'
    '~}<D8xll6=rLK<uow5E<OqpAtdJU6mE=B3HBQJ@KYx{dG+(b;V&oIPp=MMzdTNCPG($;CZx1ymL|m|$UX?1$v{V_9|@c;m*s3S;^'
    '#D^agjrx#%uVZnC5daKBe6UAgHrZ-F(OeW-PJ^&Y=RTJ{u{ZQlUd{r}?aq|IL;Qv5<1X_)enLqQ)?`aVD-'
    '$wf^EtMiDQYl^<|yA4SI~fC_3TI-O1}VD>Y?#9U-'
    'meo+9)oPpj!Z3bEevU8XgtoeLV2#O*`MtxZCM)|5LQfc1E%7wVs^Tmx=4RM$STC~+<31RfDINWTI`1NT5BJKBJi2I*n#JV=oQ<VV'
    'MmHhf75r_bMA+jV10%bE`RIVkahZHKVUMi%p{9;(IPK<J#1~6|u*s=)pr-9pN6<ZVn-'
    'j}}z86{=o3QR!4+hTZvIJ`%?@TtvJ1Dib0CyT0!+BNT!YBdFx=672>U{<o9z(>fX!pD2w*u^F>$4QX(g0u5gY~vMZ3_%AXXP5Bol'
    '-d*VB=v7)>WJ9sA&x7w2-M12g;_bf5R93)1F}YwlxiCtpDh~NTJ^rTMd1)+xbWFkS-'
    'u<MpZx^Qzk(*tfTLaxRX>Qlh(Im&l+PHl$jCX+5%J#-'
    '=H<K&rTs4qS#DUbx>w(RmF$CAa=FNpk)UM70uDQ!@(JjE32>i{>ZSOXyjIU|4016r*E0ni7yR3MK?O@OayepD70a=%vr?xqh%it4'
    'OxB%60J1d#wx(j^hmZx-'
    '6$gS5dM8xk<K0g#Ly+MRBJ@>_)aIZJ9#OaOSh1+qcms9?Zv`<(x~Jd@6Bk$}@8+)jLy14)uG2Tdk+@?oXK1Jcs=vH~`(aWo!Ilfl'
    'I$jC<NUKC#8LNCMj^q}0lW;f5x%f4@QWpXbjqU;2Gtyza2GB=D5N-WNFlr8uq3xNXv218!`4FynX20<A-'
    'r~V*$=3g$p{uZ=I2;Q>qq$|`V!sC6vRXo#TMU%Rl1MmcHObgxBNGh-G|l<o7cp=K*MiXW@5l$p*igqB-_t-NgX=+&%06&*dzUA|5'
    '8jlsSbNPdVM{=6cbO~>s&N28{z`up9&V_m1>Zu)(=cO3x*5>J)P1U$%`;2x2sKFlGE8>rU}-LvfPtP7noWyYtd-d9ZysAP#Zq-'
    'a;~<c@01tvB-PwKo&6B6kzJ2~(em)Y!Aw}lEY7>U;!L`TB`YUm|Ct%mP5Vz;Dhi$?2X)vkyvbI0)*a1W7)om{?w3QWlz1VRLfyF&'
    'Cse{+WSqx8|egnI0B6Wn>SI4XV1Cjt#W3X_UBIe;g-W(idZ}xvaI7aQcCI^`~`I#h^)nI-DOO~&eC0#d*j8wl)6DdYX)3dw=_<MO'
    'jWYHFMzVvH6Xz)(j<}xKNXHhdah${j|;6~!hN8UNbHE<(zR?5ZX5{R~8$=<fS5Vf$<Y**JFO~VAd=(f|z{Gt+zv=roUS!MH^?NZ#'
    'u*W$WdRNK??67cA%C>O<bre35SshkB1x`1>F#-^AzUay~g4Yt*;>U$d$;5|Gh@E4qu@Lu;?I0Gm}G@9!{UP9xnXWBq-'
    'v&l>iyVuHlKrOzued3ze`4R;7TOtL&VwFnvVX~ZwYqX0X`=-'
    '^hue>Svl0+6>{y@XJt0m9GSo%o;%%ouIFY?J$h{9+EjwnA&7Kwa1<z&GMy9HmNd+Gx8_=1`H9(bQz5D)DIi}%C0m>1|QpzshqLtV'
    'rgXv7*s5KH-~)|_9k`Cp0g-KwL3f3RiWuYoZ*p>v4X&|#*1yc(hNSuL((W8C=)HA!-'
    'BK)Z$h8iEVQ%Nw*hGy*`Oz<cLbVLg^~7YhPJ6)N!gr)Qs(R|}l5K4~@ZLbBj?0|V@{*W8}=3N!JpXR>afdg(h5!_(4G>nWqU0bH='
    'r`D@6476Zwff*+=!2J^|dtBHZd=efK<{BxG<hwSy8*<-'
    '=CG1HsP49rOhcRpDxuf#=eD&{Rklg6S`*gp^maR<9S$%Cq<Awdex2qHreqQsN4K|Y6*+eIS$C;{nG{3qlP(PJkcy1m6{#M0zTaS#'
    '-lNnNQ-%#&_%8YJBI@^%|iAN(y&DSYa*gpgP=z#fc~_QIf<Qjj3WeQ<_buE^NVV#_#%tAzIu1ppH-'
    '&^1}DS1KN7@;gs(LO}MU0E^a@QS~MQ<Daf(?}P*~lh+8-Sk|Y|bcV)!!D<E1(lc?s!L+)XXJkb&8j%LkdTm-nlq#JZdj46ASzMPF'
    'ulkgC%k%)LQr5D`2YZGB=5S6{RZzneGejGdzu`PcQM>rCMYkz;B5$o~U;x4h3ly)VXHxQV|78FBWFmtih!RwC#kP1-'
    'hL@6Sf*q{p0+Whv-Q<Rb0?kl)xVlQiP+GTAXTC<nA#pXIXP}{iD|pzpL-mCedRT2?8ueTwkVZ{n8HXlgVXCk2CLI2r!gU~shI|57'
    '8u6NYaTiI|)^L-'
    'wogzQ!z7RQ}qX}GdVd9G~&lFLOHlx>PpG@30NyjimPmm|0OG+Qxq5e|?6Y@29Ou&*1fkPl@##3Xr70)5221mHacqJv{F5hRy+cU@'
    'aXkH2q^(Ip*&ff~o6%}%tvB~U~E*w;{>{%KXFh7-xcYylvW|YrBP!!b9Xk)A+o8dCW-w$~#-'
    'V4|#K^5n#WhLA2Pjgu3E3s&z#qZ+Ul=H$1*p{p3tE`%qOEjKc3m$QClU<){yP;H3sW#GN&dyn%ER?3Epy`qWvmTnmBMy6rCrNVKw'
    'MNEajQ@5JoprEc)pFQ7Mo4;UUR3%szUlDFVO&}P|7YER%G}0J<rTJPUtkVec-'
    'Q%!zW%+t53es6nz5)RZ&wZJKYf=D5Ba|+@4r1d$o_h?|K=onvHy1e#jBIwvZI5aemUNMU1z19FA7rF23-'
    ';ipzJxn20%K!TcD$e!8~~RS0Swac=*ekmm9$bWVB#+G7ViB)_r69mNK@-E!!Qvj&FYX`NxAJw$a~(Z|1FhGMoG`Ke4pzIyRdZT-T'
    'P5WnWsR-'
    '5()etaScLxYfSS$}?DAPtqU+F>SypfvhLiLd&(%f74&te+3;N>)bp$Q8!Y{N2rBUYLg@Cr%nswH5e`U4Z2XlOgmv~^6gzKO;{WHM'
    'M^ulivWf@B(!l}g9qeJC+5qj?;013aSQ#B>=-vuNbZYZ$8C497g@qO4@Ov5cM0^DmV+TKO)p}D({5N`>oe$tU~5(PAZrD$>y9DD-'
    ';(;&QXba70Pm~SpsxSoUxKqIk?RUHK<di|pGkoU#*l?Xsz+v73M1nf4%Lc+G+PJBvaZO36ZcrGG4t@p^<IhL@0<ID&tUCCpEdhI('
    '&ED>UEDyRN${xGY80*;=uo-DMwWjohz7kjV~_V0+eO`5lOJx6?>@mPuqwg31*I}Vs*N|)6f4PwSdoD0Sj<N76Na^7UkKD7PobBLV'
    'YUFrzU_Q8DpxZI?!{rsuw_A9#iLQV7^CwlB~`$g4LS&SU%F^uM7fafr_<!Jn5`zWVhW$;bJ3N+j~B0Bkqv3J$j`+au`ZC^KzuP41'
    '0@mvP08|wHgte)B%fR>6$wmyxwt{PFGKPH{n*bixhfXLKu-AIM4KHmhshEAs@_Yl+oQsc<I$lcfK%%BYyQx^j!mT=KtQExz~k5bx'
    'YEi*a++H+luP<vlguQLv;fnTegY_JJz$)SDTZ}JUs0&vd9qn>P3T|+IWGB1%-'
    'Cc6qio8>G{5x2EZ`}K#sqSJRG~7H1IVB;e2;#AC}6`CJsc)s-'
    '(6GY_6GRL=N8l&e3cxa6Q*LjFBXEkt3cKk=RZ@#0!(jXNh>nixGYP=+bQ`vOK`bCMSx%=QadZ<THL1rkdtygDaPCEO1^~>Kp|D*e'
    'Fis~jixK4)3BpF49YJcxc}8`R4l;OMMDt815>Bq=qKZX2ol<W2Qrdf9>D7ov@Y!CO+UyiS$mcS8Gk5s?MjaW2k17&+U+J|xZRx*X'
    'gstBF@R`Xv<KAN-'
    '<9f^tYl<W@l9obfc7MbFLl<@b<SZVM$lgC#(wk{HK=<bb{~08;Ab1Q4US9SA9g?3rM`%}0kUXg10RGw641WAQtJTXgBFIPwhBng1'
    '$28kEzbqR4=IC)yr_i*swEx+p@D{gPgyn?mAK+)LHdGhqdJ9zVF9}kt0b33TH@6@*X)JiWbnJuuYxHSD6?R(;S-'
    '5XKUpsF5uQbH{(6eD5n%Aec|LlVWfW<SX*8(0LC!7LZ=}D_Vz4~Vu!q3~jt9Ol2Z!9Y+mKflGs)O%+6h<;&GpJ+i=}5e5Ugf+Y(2'
    'xkNNb^*&5Do2cc^Q1s8%Q%@XHxy)V>IzktsWeCe>?g<jcOx$V>jW4i(I}WV(QtC9Yvt)107vjI;~oQt|~UX$Fjzbhqe$tPss{K2Y'
    '3qE<Kk_2BFCWSJ#nTBv(L3Sw0Z7<_ogzfFbSpdH=t%<CDXq{l6Y$KmK-da9pzmMrNJ3v0QG2YAhYVn1!*-'
    '<}i%7QN7l9UNg*#nCrq9mg_<sLcNc|`W_+d=%Z}8WPoc_c$@li(3YD#ntjYbutgq<`P%d@jd@{zGV-<J<^ii6GMBBl^Hbk5p*aF-'
    'ug(P1lQtN%n2G7gldipENCF7^*YNpQ!Djj^lerAMwoNwjg|QeRLORq`FlNC)YNgd%E=@JfZ_<?Fel1r3GK+au{=i6WgH70ViCp`m'
    'o=f<;)7EW?ftg-QQCqcdO5vMoOKL+X_Mr{ZYr`DxBIp5@#&5`|n7I$Rzac9{f@b8Q<-sQ{h_-JATJTJRq4C(=3+X4QsL_xKiPREp'
    'mhef2$$@o4h-'
    'mMhap)TwMGUpgTgu;q9vU+3qZwnIygFnZ4rRfl<W`j#XTffigyu4eLC08(rg>FOE+z%!q??u>NSeZImqOSmNJS$c=7}^&i*HH(tF'
    'Q+=?iZ_Ra{Th|35GB&R-pFT#-OIffJav(qtyZv`3Ot^JpeQx7bp}-O&=hZ&e1jj-OPf+0mTPX(a*xs3rTB`Y5B<)m+#R6_JJcer^'
    'IhlSYfIU50g>D3?xmiMo_5D9eIXsZ35R&BGzx;7Ec;?G`<_3i$$5{;PNEH6f%&2F`*O?=8B!44byl(2|FwpKpUMBfJT)((nwGgu7'
    '-*2^2I01N4ULlt0rQzF56m-'
    'fg~Q+7>a4s&Y3j<jlgcRi*ziSu`ZGk*0MHwks}wSlc5#5=!Y%FLl*186|F)1pX0+fT19X#F^a)`$<GBtwi2U;Df+x4Dc10v8K<(7'
    '{D844@WPM%7qSlo|94zxQf!ULT7k}_n{KBRMUwva$DN&2=DzacMA7zv$N>7d?UYiDP9f{pQfEGdlQ6)44bq-Wm#P4s?(UrpDzX1d'
    '?6%kIsU=_stF;zDP9D8}pFQb>{AR^nS|6CB8z3mfKVx>}p|-<>gCR|^lRf?El^=AcUJPxb90`d0<V}YGII(z5A(tK)bCjpC-tF+J'
    '#?~;B-8%CuWoXpVA3<UnSWRr;uO&YolJX>&3Aq=ZIDTmpRf$tU{Bb^lyi{swEQ!HSp&U$~?50lc`QzlZaw)yc@a&pP-J4l$od-'
    'Df0q)-OTJyR+Rc0ex{=rN{3AcsXZ_5YW+F!bhV8GK!we-kZg>+0@!co8YFlAsOx0uYkJ%>~Xc+Ypgd)$WPxq2__Ds0SK!--kc?SA'
    'U5*I5s52xt{;QL`t!kgy8s0x_LLY>z}@`GTBQkVER#b&dRxKF-7*1&%Mi2yZXH`T;1n+D-'
    'c+v=*J(_Zn_eWYjsgCw$?zM+GmaTFR1%8$?eU7b3hEEC_k<a(o2Wou!SQ78gs5G?`ppEh%R;bPJFB^suL&;%`tOTr54!GsGu-'
    'q<3f?o2{;k1^9mR>OdRnM6ST;9)44c7`(}Pe*(U)76#2AH#Cfu8}iyw_hqSjZ-'
    'I`cvyyh8wMn@97OzC>Gy%`IrzV0sApVWqrWu*nP3Itdpd;GydX91jC_6A<^_-'
    '$5QS3wBy}Sh1+VH)=Lu!;T&J;Gs$ZInQnC|IW?0d(z7cY6P;gF#|D#HxsnNfowZL=?mS~`wo@{%{4qyFN!p?NnzYtb((@&zuvu*M'
    'y!|Kpu(XGi_NcKbqip&c;oeQpO&$KgoY6}?2oP``N=7$0-'
    'CtzF=2X`J+(sEwmFgI}fASH`)5sg_9ECgxgs2&31eB|J99&RXm}PtB$j^0rVf9d^LGI7pRltowX2>lqoe=a@lKuA|JL?Z@6rJD^<'
    'fV3e*7oeitHf-b>^5>6q5tr-MQUo!&s?G-qAKwObD^)HI~6bxoMEeLkFO{%PI8UHH--E|PQ<ikA+P?#g{#dJxjJ!0Z@Nflxz3p4p'
    '*=t4}^NFdNL(&)-&p+o}~C+&kVUxz+7)L6)T2fH9WIn=r_bGMm~-'
    'xmu|2kNKDsEKtqdyqaQWHJ&>)dNdg5B3FlcuQcsi0%cH;dEgEMzj=(9QSA?QZxyURyO^phqM9C!2tvtLFrCd5Ia?9a~7GA)uNre7'
    'wy7H)@zD<zPM+8XWf-|EcF@dX{1<cl9Z$3VF<3DD#u1rbvx_h5E)+l45E$MZx~AH5zJ}Bp9T-'
    '12|IKgBUxvxFVs=BbAHH!(dHo5CAVQX&f(Wc-TDin#$bNzS=?EqIY$^;99z3Cq@~&vo1>j@e4^l!AkOMKpUNwf5dlKLd9`cE{h6j'
    '@UHM^PGit8_6BnYy+(^}8I2&|j+JER+GltPbI;tg=R-^H{ta1Bs1My-Yk3iiL15-0A3&fMhJG=?x1RA*19Y2tsUVnF|-'
    'Mb0<>f+9z9)rD1RVX?=I!*Nl+P5Mw47B?9!p=*J@<TEVJG^}F+<I*en6sKS=L;qH^1~^cf#-G-'
    'CI~O57liyI1Ao{HE??+mIpFySSw>_8qjU1alif91NuNAeNgu4Fe|9VBJs3l4Gj2XuLm#Z657y8JYv`ZO8v0;Od$6WGSkoS?X%E)4'
    '2W#4cHSNKg_Fzqu)-;GZp_#QzScIw#D@jqNVbtU(`j^U4q*M-'
    '|xeF8qvfir#L8=}M<U*i^UJ8W9+y_Z81i;IEAVbf+l(<q!b20fS@YB$pa9seY3DRXusltRH>OetR^Yg-(pwyy>J-'
    'RNIIUqFUc^2PRc6kCiXjt7F!<fIPk~C&EBhou@D0G!b>m&!ya{vKN0}4Ar1>4>LHBn@&EEdbj1&PPH(5p(7p!BW%M91TksuF_RL4'
    '+NF1$6lbWlXqLK$<JBAFXCUBw1qD$&lp{kO3VU&}x>y7l;EJ&HNTMl%e(Qqn{q~2LHdGH@G>Z@!u>T@EwIfhAyK&JbaOJ>omqB+L'
    '4*gMTUWysTa2x%DWM{BE9?@=B@jwITNHEN7yE8P&aM}91Lc7{1XT8nQ?l*2eN;*57TQ5&(pwV)F6eb>LQp{t{io&WED&^8P4e*Xn'
    '&lnt=<Y0AB)jS>tTkcXMNrUxJ7x`&WczNgG;6oC=+7o7uN!)5EBcK^u;AFmI>6>DtWYW+ES`Jafu4l7Xp{cq)k>g`P1Ul90MHWg4'
    '-%)?}fn6=C|*YJR!W=z7o6<FhEl<n`#aQXwf!v6R!>jHO464%}VFcB-'
    'g4X{b{X`_{|%XdN;0tXymHmqZjxrIjE(5l{~a^6FAC63tD#c%V-)$*`$rFCv-~d;W_JR1>MglvtU*u6Tmw)Evkov6p(d-'
    'ZFa`bcqGA}MmEDs-k?A5cFAg6C-_QI;N-2)prgAjj;?NHB9mPWMTP>qNWfV!!xiCG1Koqf<1?#a&CK3SW+16^|27hJoO-'
    '>Oem@igj~Vm{(lBYx{A=arx6)UG-'
    '&Hf*Q1ah6OuF<j^%Lu^TJ%tp3RvYwwysCB%(jJr(tx9O*fQXx$Z<scLy?=Yd?ndM(qLr7FJeR#6+$g~+Be42Pfd;jJ4JRuQz^Rd4'
    'XY6rCpK}yBLu@RAy7Io^J}xtbJ)cz<X;PX4EAGZdkHo-'
    'U1mIAxkf)9%d5(3E$NJjHa)Yr6}h7T?$+csHnYd?Mei?(4&=Q^`%Aelr~@hb;LSF>m|U(F@|EXH;a+7SN8q4muS)A`KEys$?TvnV'
    'RZhpIEG7^^h|ZJhO1a>ErX0m)VsBo9x)jB@zywK1SJPDm2Sa9`<FqR`=uQxUptt5sX2~-5_E9>p>m~-iR?B#1-;TOj-RjyO)hgd-'
    '7o}F#2JwilAt?1phzLpI-'
    'y<SslUYfB0E0+>t;h{~nO(|1W&(TO(VvwNDfk1}hiq2SuaW%apaqOBh!ylgtSt;HnmF;Jo7VZG%I5qL?W6)qJaHmb6U&!_<LuS(('
    'ZOG_(^ECuGc=*8XEaOP?_KK!tWk5aWnSKH^O?QXA+;|g*Wz;4!i7^eHEc3eD^Rm;Fq>d%-'
    'KN>$LOt6FrvUaHq<<J{qgKGVQ@;)@#aSn48><Bq8pEU3bL+W&iL!3P7_Nm;F_|xe3hro3ixv4|1h|Ov<C4W;LtSzYHG@^z?|#5F<'
    '87Cf1D!|LON?VEB{h=XPrwmpAN?82c3Zms_m5evuqB=D$;}I`IAE6r=ITn|4};JOBk^%QW6d+<cLlBo9)@iJq^W1onEnHWdREKHR'
    'Ox;NyZ#Q0n%ZjZD)T`(RHNW`IEi!vTYzaI=J5oQs+uG1**G9Saye@-'
    'g?DBBGHxVhli^*QWnyNh;O8<N+RV_YG)8WleGWKGtV>R4;A6)A$FzC0gu{(iAez=WH9J5X-)-'
    '{4*5z_FJE{a;gHxo1G6Qi7jPX_1n6TjmZ+`6Vgz;`b<`#0lUv!PR@sYf(Nhz8lJFgN!zVv{_4|L4Zh<0ks?2Lr7@jI1jHZ<gpWh0'
    '>0Fv~2fnWz8J>sP-XICQRoZa+yQP+q+Ojq%~pZ?$luo_rG4$<h9czaP95Kn~v?v~u+DVPL|^!(WbG9As}_y*UObf<9^~Fwn+Nw;_'
    'QY{&Mp6mlIhTc({pw%^h7iFq*pNP2f77ZOMly^OH2juBm#BU_$L1e)~hhMtal79}Rh_rL|h#XZoZtcq4T+49ui^R?I-'
    'WoxQCZY#_%l&0GNtx2Qi^8orh6_`Uc5HnHc8I^2w)g6;42B)C<IZiQu5Mr}D?HIM)up%1{joP5b^7cK^fm#u4ZO9~M;abmW$gq{i'
    '|@@>xv)iw1*o(Ht`(sJ2rc85mmm#ttk!biOJnUpA0aE3}bFJyOM#0Vla=ajwVG55*Wgc$?(BWfef+)&|Q0B-2Bz>wO0+~myN@Oj-'
    'bhGAHrhnG1LLu#R$p+MX7-Q43yv6t+6iDRu*-;4AAwX@wzcHFv*!O3Z-'
    'jo`lRCFxwy5TrBtl;ldf&!K!2OPilZklT9@bsj{W2T|ui)M@q6;nB-iZ}w3<IodyY@wfHFo~LOGh|E0KLX@O&i%BC&ME_}`(1Y0U'
    'AU6D=VuQz^tR*-^zrK6X!4(h^-FYs)pN%ZJpwqzHiO*NFswie)W4<7d_v&ggM|VK!k@w-'
    'MoJyWfGLnJ=`h$gtnrYu7AAj1kUTr|c7W7WUh}P19Q#2vIoFFJP2?sW?hBeX>MQkOc$7iqO)uyyO82+4fDa8!X(Em`E@}Vx}UDTx'
    '<PpWt9nUf%1nL!{8<tSax4ZAjF<n2SD%FkP<vMQz*+f@GDs#%F)S42?AbxUj+oAepb98@P`@fe+f`jWiNSLc|31OqVyp<r60PPwj'
    'G`B0|vp-'
    'g4#GL?*i!$c~0no2>^2dMw~uz*mXF{*&HUn(SkAfSGP+`nIq%%m$P{O?)%(yd|n`=?tKu&l2t>E&7aER`;`MB%~^TPHxUU#}p@<U'
    'LDFfS>e<mg>|P*_m1B5?{Bdg9&v5MTZ0pPh`uQqqT<=a4L~iGEWI7^*GgBjS~o8(A1q`k-'
    'YtYiB>b)L)4C+s40_3uAUYoc&16C?{isJka+~6#O(B2E^J#ymuTxc>svJ4i41J(wA<$Zyavx)O;?mNE{0hVf25xE`XQHBirABM78'
    'axrRZ0w=!;NLVPoG#bSh2y!aLCgmXX8){tHh-3%Q*CLjN7EWzV8@mH<#~IgQELRm-aX6eZCZ*SxC)+XEi>~9C{{E*F-'
    '?$YE@NgqrUfM5QHm>{zq1)eW(Zf`Rl<3!j<Z3!J6m$p&aa=xg4x}0}d^6)3O?@Nyi^5!T!frg5?+jIxb{(tO+W+&Oc7BSJ#xVDjr'
    'q_$r2Y6vB>`fTB5RMnIDr05htd8Q_Q4f6F&J#lXPI0Wp3fe;nE7B*o6ppi2ZNjB6uYgn(~S1WLZd^en=jF{q?hN8uE&*y-2-'
    'a9E|-9PSJW4To1Qz$b;7Sl{FZv41y1Cs~McV;o4{tG8Tj|^iO0oP#VCC$)Z{kDkZ>;yQTv}p*MI?#(zd-yp$vJ#U<*6yOuT{a5O>'
    'eLOm*IV$*)_K_&lhr;>kAQ~y7trpANTCj*6)6I&~F>slhj&!&v#X+$*5Y<_uAG(RYs{~$#(@nJNZJ{>y#rFGBPCZKxm%Le#aOgD|'
    'Jm}IZ`1{^Z#TgxaKragNMtU|<(!|!A^4o&ZTz;SJO3U`hWeit`bM8^Cyc&nlpn!E&owN-Cexe!UJ17oz_xzPPV<6Wu;P4I(*qE{;'
    '2h$LB6+N<r7K0CEPA$1IK8paDDek)is8()nGPo0D+pr9lug`eX>tR?bdSiNGrx}H~Ei6xcbD>I1wACiP$74v)n?vd57oAyC8+Dm)'
    '=`rN#Da;MYsgSaebtmK8{g#SHDd$I^co$@bYiKtESvx!~8kvt6v-jS<@m`olLVA|5v5HCD%_m!!Hemglh?pui+rQoJu2oWv(Sz-x'
    'h>ng{abP1N$DmZ`#Rr!Oe{PU>F<9WAQsLb&+J?PB;+&c4GT5W02*UX1%Vu7S{4+`}Mg*qrMx#-'
    '>v5?50y%xnmO6sE{2e{J5}k*G;k6;b|)C)v#0YK2^eY|)S;72Ojt#k(pcsC1dSZgsiEj)%;*$lUOwX;}eF#9q%cWv16az{MFB6z-'
    '#3x<$_y1=ba)K&YVFhPqH8hgwj1LOvsv${`Qc39Hq4CGd8&<XQz1DWrQOZ|y*g=mw#ox8&@y4}V-'
    'kU<bH%iCxJn;#?T}1!aRHF)DZ!D{_>4HxnzIye}4j`nDgne91Qqw;85fHKEGf5}rJ?)Jp^mOBqhDYZH_}>06USvr>O!l{qYkS<c2'
    '2N7-VOOHr@e)WloO(5H3g<4L0PkUBx8ECLx}JYvU5c(TeQnJs=8Cc8V2pL`Af@)KN;f-`(LyucIn)m2_yK};sKv-'
    '%rc6(6~ZMz5w)ww@SX%VOir%6kU9zybv9SE0Izjz<vZp$|td?#e<K;n$DrUq7jT{ZzcJOFLrdc(F3!(6hE7r*VJ%n`PEu1UC9oCF'
    '70Lc?Hhk`iWj*iDH9+^mje5mQk<jA51mds?cpP>zRK(tz^@l{vq6!4?`@$ajyYZw@s2{=fH`j(gkQj8FfqnaGkv5F&fefQHSVdZA'
    'RUpyc2CXm{gf64%7=|1(Fg|9D<afsB$stUV1J)v_ElqZFUW9=w}LCao1S~D?_FMZonRpvb>@70^J{}rlSoFZ1xJ`%U4Gbper^^cC'
    'CSO<xePH?9yJOzYSBNPX*W3svZBQ3L}By>MZX9^%RPg8DW%~@3WA^cy5-2k6fafVYK?xk3oFj2@Tde-pVCIzj5k^`cbb&UUpkV(M'
    'j49H-CPj6X-iB^OIQ4{E+x#CeTl6GU&T=*A%9f*fyrWr#&#zwcGKtHC#w1Tpm<{LTO)mQ#hqD^>WuOaj#c5(wbEGDr-ek9()}-'
    'V$`~DlEG;GO(5lbG}C>*RigaPEiQE@Z@0~M%&&kum&Kf1Rb(jRnqR5j=VPc4t_E$NIrlAR5}%CuzO<4)SY>*H->9-'
    'fNOOYiSZ}0T5*adA)vGk1h8s-(-zu5Ez0{x0amK!-'
    'qUrS$nNU4M=yZmCm07<ND<43q*b|j&Ke3bTC*iUPT3^PQ_kH*(6@TL9;_vwr<w@!+=8n6D8bnwJ8Z3IHU~Ww9TtIweXeR)D_e|Xg'
    'BkG=srJw2nntO28j`dkvGwpr^s<3FCOIy_&qYVb6umJ4NQz4{WySNJ41Rh>JN3vFi01b^KdHh$;leVqVTOG8p3Din~4CB6%WJh+x'
    '^ioq~PZ|(CvKJE6AV$jP7<jcUNTFI8>zpJDn65L$Lkqapr7giQ1YP}6+wLUk(B5_}VA^%62>R(+Xh9_F8mQ0_1^)rW@Ns#WvF5u5'
    'yucg?HL50;;?7nrqecGAuQB%PR;*dr=AC-'
    '=w$Pn8Qfn*i^<tRoR{v4h>(@*%G1#?in;r#QF*M%142x~7jc#zGwKi0S<ur}(we99$ULUoRbIT=BrIV-mOdd*2DOxV<hjQ@_ww}K'
    'q<ueGO6Ab6tkQ&O<#F+?_gW(%zJuBgTSPG+O)^>RHoL$4S($253)1|&+&hE^YodZpVO<ua2j9h|`c<g%Yf^3glcWVz`e|;Qw((xK'
    'm!w7P|XZ=V`^@cfxfk9R&$ct*kIXGe*^<lNTqmGnA%<;+L(f(f#*dwOqTv;qXAFP<o+FjzbffbhGLJ({_OLof+PD3yPd9=b%EK!C'
    'BdnbnS4Gre?hch;A9af}HZ6HFtzK(LV6mon9F10f4{K}w7Hb29hDGdagt7f4yV%UtYZF}S9T__d;;js@&1yU+_^$<U|LZLYp`9Y`'
    'fpi_9zDLm*D+Go;xP$fL55*}0u52}O*Rl<LeDj}MoNi$?FuX|SGE_+wvx1D_DLG*qQz5laB?|8V)g9y$dcx}AOA0?32MLIo5<PQ@'
    '0gGBxykvC=2c@WAUgz^WW{6Q#x5X%2!h4QA%5H4>P<ATp(c_Z#jP7j54KZxrO;`)DxxPJJLH{wjyN$6iCCs$DO7Oxk{R&%5QEL$m'
    'NKE2^wL9(9X7-a8!roy!yi0^l|-'
    '#<>|O*X(D#O6RQMJ09N;#O1=IA2UB;*qNG>*Rd=N~YfICm)~ymKY4@JON5ZQQsJ}oWlkuA7E^fx($3nVr8CzL}z9MmCsW3*3&PvQ'
    'Y$!WgplmdlE2n3I2gB~df-nd#@p0^p`IedvuMQ2X7Ya%S#}jCy5cmdols|zJ}43XTuOun86Gq2$rr@RYKd9iV0F=pcpP1U7SFj7U'
    'Hc6ojsbzs?;<Jy)*Kt2*r_=uyS8Vr#b8p=l?XXHx?yG#k~l=bLpq1Y&tszqR12+#%OIcce)rfJva{%CHNw04$k>*8Y0wb&?;y(ZU'
    'POJ)vpe)T`^X6}(ga%vKt7k!32_CtlTK=r1WP#7=rlx6wfuog53EvjC=4dLP2QxEEpgCmJN<N5BF3%62@T~zpm-'
    '1{KA%9bj^f+XFuw-iCuI8$>6h<L;q5`v)YwqXwpBkjj<QJ?y^fYRkbGioCZXk3;pwcRnySr&6*s}3nMan>HW0E(X!O`Ilq&5gPL}'
    '9!rs^PLcUT*_ayvX<2{<GINsVSTD(6MW`s(NoLsFAPEetWr%?+XHi;+vfO)hgsCephVtlCOdz0Sr`%xxr?dg<jpq?LOURlZ7I&Bn'
    '#Nn8AI3<-n2R0Flr+)mZVNoEDale@?L8Tsow)rp&W;f~d!-'
    'lPQioE9gJ4B&+3Q+Hq^!%=6JZxJxkKJaWRW7Y7`k8qbaxOT2+INE*n&&f^QzgfK_$bESxV@?$f}FA66UvEQ=5BR9fIxqx?ACinCV'
    'b0~$c;8Qp}SX9CsgE&9)X+A2t=>V2&ThMMNm~Eaf1Wl!-'
    '9&WTk(XuXSs3R;3aGUZMb)_mo9ae${iVkg*8(d6gV|>*$79hZtn?T$hGu{p8#KCEx;s|Q44r_LAwR5_@BLj{in_t~jXv4dhd=yMZ'
    'Arr>*led5S?fBJ;{nyz~um0=gm!ktOAD-4ZYBWDJ*6U2w=Lk(aoGPYaRN<NvjmxSuqq>Th$!g?_%lD{f`9K`D;891mM#a890xA-x'
    'XsK~~8)dhOYr#%r*XP*Re3ezxav35<Y-'
    'dy~1vOiXH9;`rVl>U6@@nyMSuB972V)mRFW@4D`4(*|Mtfvb4Xn5a{lUDPPDVEd$F?YW<gxv96~ZXRLwz-'
    '(>vCh<9SIO!CjsUuLLq(vNT-zn)Nb*^FbQdteX(vLR^Q?U;K2ZL*v-2=r9q-'
    'rtTn2y8~~rB|NU`iCq>F3rVJnBBH$n5fi=_sQbUglu}{5)qAS6ebf85|x<vlQ$Gf;9O(zhn`Pfb&=xLyd{)`|aFIM7MObSpnHP8m'
    '1#IZkC(`cL`QdT(z-*X{`$uZTh0nZnHtd|V}kiXP;z9>->xGR(^k|QWzr22^tYj6uqaMa@Pe-'
    'O7@`5~YkGP3@io1QEh{8@dbFaKL}FbyAD-$h4lR`Byy+}b>`oB`_<t?yp!dh-{4FY3eB32(@r#Nku=eP-{_9v(-;?w+$-'
    '^olXQ7xM6pt%}sfHDs&(tlo=8az{v<+1gnyj2)YK&$aLn6T{3Wvyk&((D>?91FBCH8+0~PIvuiMi?z)w^nb!UM(Q>N4NO%*1DJYr'
    'd~M2q*j`nR4&nZEtG80B-nB;cUeu{A%pmKTK(rPoWCFPp`-'
    'gA*aGb7`(Ie0l6Kslw7*8j&%S`J$BZiXJRuXsK$(Fx^zlVq0Pa4Mdsn?{^a+PzTJ4O{03!dp<CVEwjE9Cxq>Z&U_1q^%?erG82?3'
    'YbCHn)9Pq16mk4o>O(Xk2y@Ph;*@%kbT=!7}lJjnG8Pdp}=HO5UzTF^j9u0|eXh+pSTfujj1Vsi*m#1ITScLtJ+mU$=ecIQH(P$)'
    'k04*wQSMO589GvM{)3YWX}-@hrf$*n;7nuJqg>LWW?W1M{Bcy$of&rEBtD#4q_%!$vtC($--'
    'Ny^DKKd!W_WETHz&@StN`ACO{<I@yu8vg5$(Q_^17A%s*jm>ub7u4dd&DVQHPZ~X4U?T9hTfu4`atib-'
    'd<DwcBvvCeLZjI6DR2gdOJf)2`t`_xoQ(faKa>BYATl>?Bw^0M|E5Apo!pD^sCKdLeMS9d5C4U(J!d)3xcwim%mY|KxWRq+!hQQY'
    '08-KU>vFWdX_3QJ|Qpz+k^trFKa*&<AickTBXcX|1K_mGHi|dSa;ROlU{4CgW4KoC?7Zsa#$JS+t-'
    'k8t&Nj=T)MOpiZe@C!#p<~*#rHH*oF=GuUk=r|n_|)6jJw>(oStrKEsE<(BsLF@-4Uw>CeULAflMAumRW@ENP>q^b;-'
    'h7hWBj~+7VUg2AXaX^OnwwC4)9Maw>*!TD^78xF=LRjz7z~aDc+(5#?)^y{mLqTch42aj;}!Pom@<2P}KW;G8+q#p!z;31b?5*SL'
    'cGskV=|_G@_NZib_XwB;8zf?ANCVrAm%p{(TEwyXR%K+#<R*E^?4L3SI1W3)2P3`oAytPxb-huM#8|$v=xlDJ#S!bgxxpY<*Lz-'
    'l6C&uPe0up90;)0L{SHH(8d6XeE$vQVFnB#!MPXtm0v{<+<uhbG0eUCCOyGJ{JsNo=+APs>ba)-w>IK1-'
    '(1YjnY>daQrAxa|x~;)|wL>*U1T<@lA$6TpXtsdX35%p-VS2hv+SVYUd%0F<+(JMr(j~ydw4lX`ev5f~p)0wuC1;-'
    '#zo_7@HpiRjL5Fx?sPJ*c7~Pu@AiKwy{Jla3ga8Nq*E#fexZocrZv+^%@26ba(G;P|c^4C3Y)yA~1LMO;~H@+HfL<^z2C|#4L@(n'
    'HHx95-`k?bZ7VRH&32E`}X;F`T0n6OQB*`8w9AwW%w0`$JSzK-;f`$F-0L?;ak-'
    'W9PTV2GP<39l^h^3m@f)GILzT9xd5fAAetD+B49wZKmoJ75JXAz2X){F<{@^L)hrASTob+cg6s=y=et~#;`UxtLCYbkiFp!ayj;l'
    '2&ZuwU0*q2UHYtKofQ>0HGU^FIn(YO9Cidzb=xT_E_~e-'
    'Ncw6l2AA#|SJ~bwB7RR(xp7fb#yi;#lNf@0VlZ`_NF{=0&884kQu3x{jKA(hOP7MfQ-qI2%=o^pg*N<UTJGL)*-'
    'KZP|qGuEJyHZbY-;=S6A*^#OyfqC2nj#l|9lC})s{Nw5N9O>95Y%mgn94WJ-'
    'B!Ic2wP)W%DX9Z+3`(>&6UYwAFW@ZY>nb%%6_FT_J%ZGYyh*kU&4Q?rio=I)A!FL%GcNV6uj^`Fn}5IQQ1{lz8m77eeyD*NCK!Nt'
    '+*2ci;e?epST-'
    '$m%DLu+04DAjXR6(qNQ8QI&LhVWc_(}TTvVM)No~_RUhQzaX0l!aQglN6u5qiTAjVxkv;QAwwgnvY?q1gWCqq5*fTk{ex!()t7+J'
    '{>}hnwbVS7Az_VepXxBm_2Rb+t=Mgaa+0&=rJhO@r6XIuZgpj`W#nbunYPjR@72=GD;UeE|0d<%UyTdI(0em3@I{<RZjG_D0U#y~'
    'rJZF+@*uVi|p253`=?n7JN1I+BJ)r~Dl94XCP;CzILeP+9#7pWrM}o-G4sprfw}J}SUj(S-'
    '`n3D(o99n_$0FbZ(A`0D=X=(k;Va&>N4vc?^VT<@8l&RE{1Meh?Z|KmxIPSy#gHPR^H8SNb`vt&s3MjfZ#nTU7_YA9m7!s&%EdAh'
    'L#s#;1j8>sWV3w6Iv!hY)NbRQfRmihwQB!Jq7<Ega=x8!HyECr!`-'
    '<fO@9bZ<K5tLW7cKPK;S|=>jhth{Kjfwg>7R!lgnyt1!MGE-#PM5og(kt7jiTA$2)g>biEzvwy#|!-A2r<`|L^cO-'
    '5y}cO4emnTCYw4qo*px4>2}1y)Rb5}l<J5Mz@9XSQBj2RpoBp$oQ&>KH{sIwVl$LTHX2s~ekx8b6i(h|Njj#_!(N3TGgYLS)~lrd'
    'GhPh5e8`{`%`@-<bCTkIP=+Za2t+?WW%PyPR~)re_bv|4a_eabjI0-3Xi7Y9s=8Cs1t~*@$rbw9Q4tVKq-ca8J*6c3Mv0*&0h}UJ'
    '!o2Ak#hH>BWzTGH*xjNvj3LfB~A3<?(t>j=6%~pzLza!iKoMD=LF>Y3h6A5u*5)T2uZb)Y(2tF!TWs68`Ap$ubU=8k%#QK0{&c`z'
    'orvW<hOxU+<!v_U$Wa-)|A^`>dbcR6E<5Qos|lTeJ1iUG%WFWhRw6ob@uMbc_gMGjmGY1RF-'
    '2vC=n0!=ue}5{j#i<bWxr`5bJnhUUd}pSI@V_(vPZ%SrVdMicw=s1znmyuX)e)=7Y}*@<aNyRt@_6|1GYfDv%cQidc6)w<!(#n#2'
    'b9(D*T#or5d)329^vK(?3!fr^n*tAoVkjKF!|Gp30?=@d{K3D3R4f7CumHfRZ=9tY*Tdk#U{g$%bOLu^=VEHFAL0B*rGY7AV`JB_'
    'pePvqxkz$fBfNAvSd~gXRFc;nCOWm*RZNTP2`X%*iKt?0{W8^#-'
    '$&aw5%&ojH=l7DkaFSv8P~@3bE5y8fB9Sv;bQEJ!YbFja*#6V{vtVV_tUn1Jc7X;h%H|;q*b(xmGF6qKrL@)Wz0P_$t6J_rZI0{4'
    'yj1axX;+I%GTSu^8t23<C{Z(Z{r2*iQ_Ac%C~iy2_p>eQ9E^6E!|wA4)yYb=TZ^LL9quD5xt%=(IX-;q#GB~WyPVuTXN0-'
    '8Y%m?uzd_oj?lKdM?jW8K#`o5b<$>wkS;>q$O9iubZcYD#wKHEw1FP;Z<8_Nn*GTI&3uE$a5V7E?PiuuZg@<3CW=?wjMV+s8&UDY'
    '8c@OXZPi?xb^RKQM`~8J9ZW_@jk*qe3QH9+_!Wi#7g0V%t1~^gHONS;qw9}=z9W!e%JL_}EoJo%<CMzzZIvOFBSfXQvbsHf%W<-'
    '#o1~v<!W9YS5=}~bl7RYhE`d8BZJ#M=HRO1DJivErlxwxjG{ZoxKpG*m`F%IeR;+d4B-'
    'ny<vtz*4*i(kLk1u4fpPQrszD>L{i;_fDVNIhTFJe*$Lx|=xV3-'
    'UUq8$|YbIR&X+h>MVqsRX<3VkU&y|6P^Koaz0d{LoMEe8fUe`}GA%+>>5@2%K<u$W+p0n)Jcd!JNL^k3NYp_n)YZMp<mZdH0e|CY'
    'Rn2*Ol$mV+DUokmS=84bAA+QwKvG7xF)v=0I;NRhZ2Q+P6u(SjSjcZ$sQ~bBrb$S+xsuu&bUwn(zT`buOs~XToPqSqkp*kk$=B2t'
    '7-'
    'II;z`{UmtuP2tn4cW0B1MIufQi<$mCWgOsKY5#M|0P5ejzaax5JMP_Lnm{$6{z(;zj#$(Upl8`DGEZY!G8;qD$Al)F@X#8wL*`fQ'
    '0z>chWEG?2tS|cry-j0j+lM#}Z$&9TIIG#^o`6LF-'
    'H(=Mcw06~zCc563dI7Rh6GUvS@!FBfozEYA>`RwxhYRDYphtkUb>X<)h5%qcevu(r3tbz^+vK*;oDp2z9DP4D6zE~g@Xw7xKWVIZ'
    '2LlfT=x5x@%;2o9&jp)|p3eE0g4qOx(AAa{(@$jBcwh+y1|K5`<@M?svn*9N0*3f=Q51n7n0!9Z1?e{g3xS&8jtxPF*~MxK<IoJZ'
    '73-'
    'lHGn|c&Z~Rznhn(WS#1xezLEH`Cv%SdpnH}B&ZUTa|f#j5xv+0dH?l9UCppbveFwyTq4l+F6UT9o3TV$SCo5?&2L9(|KKjt^F{jn'
    'o59;xOn_UueIubV+=oF<k9?#qCH8X!;%OYi<!1Yw*uPCf&1L_CyrlEzs%#`M#hYr&+w;|GyDO1TDFxPty^CYDHtHGjMj&6?lv)SX'
    'AG?RRw_NO}Bq<i|({i8!&gm?a2H8sZ*wJ0sX(U7xi}@qyKDH3OD^Y(6x#+^C7GGVvJ-LNaYZz9b)ki50EEgqG-dJ{uJvfjT>BNEz'
    '7pRL}oR`gYReX5LP(aGVqOU&ncIZtJeM&6jf{HCH>K6~EQ9_e1I|AjbMe*l>mV^o>U>_2WQ1T#N1Q^={FfW&`3J-+DOOYB-'
    'G&h}qg1HAGFs2U~~Xy<TV!%`XtTC+5VABrP*61%>g>{U%nrMN*}35+xgYb3&zF>v$;EpSlXHsD3q+4~E<LbXvVwCw;2!o1?3xijO'
    'EGYHJIb9U~Jmxp+WlvnsG+eSU!sH;d|OGDjm$74TR2a8<(XS<I>x6t+h%9>HD&!hCrWO%7Ia)LYzs3kK>{_O<|STKGW`Zw0Al$>O'
    'p~tFMtN24fB6=QXZGk-hSx(VO-zzF)mHBJ4g#hE=o`Ktkk5_?@ZFR(%@KqJ7%kP}UFteX5)qGPcxmX1od4g7z<KwT-'
    'm^$V_a2peWvs5y#IHU;^sQL~F;}rK-'
    'u^@5Zy$e6Hj)Z#mVF?UE+G6I6P#Oy2JrIU(fLwI!Bvi{_GCiYs9t)4T90ZJ46RLFXa5M>Va(uz7ukdZiRJW5tG%)f={1$YDHDVoM'
    'x&`p4tIj}r(`mwW%~Q=L~RmP|+`5fXxGGAkF?;#&A8<>R_9TzLBLj|-C-NU}@zjy0-eMAqn!qYr(9ypw*-'
    'asL`V)#!6bcc(=(U<QzFD!+jIHx_LXtefBilgnbZ5|}l;Nq}jVsjZI5H|^+P|0TySSIJc|9e)qCjL~e<Pmm2wuv9wclp%FR!V*?e'
    'jz+6RW#^re$hhVXM3%qflm{3#6Z-'
    'zzIP0LNjl1jOYzSN0;ch>Q0g>k$Bm2{TGh~N+N$N&a3C9HWv~fR|n66I%AUxyy;Y=I=>v+%!*aD<a-'
    'Xam^19P3<K(;l}TJWA`ZGmNpU6L9=93?U7d|VBZSAsNiGPeI+iS@sL$`!fbVP=y`NMjPNAm8%rz^9~I?-'
    ')7!2FaluoKEEe>^M0tY*9dfx+}KLi=ucB3LJ5w#i0crc_~(nj^>Ni0@NnS+gC5QK@Tkc^<kS`Q&C(NpNk&eAd(~$W0B-'
    'ySu0AXhbipd@BX>Y`P2WbbB+fcbspeBvcZXGT~0r__0i{LX+GnM_s4N7Q~z~2E0>^H&`15J71UG-pG-bG0-'
    '=jb@}mBplceF~DtVEK!&mT8e*x9*5NoaTPG_8=){VT6%3m9XnT%G;^5TNSI1n1ZAdh1_A5wnZk{)(js1{Go#g#d_8YCw`H0H%Ze1'
    'Bcx$4r$F81_M#-'
    '1_ixCgF(z0fACCyP$50(#exa)NYXM&p4&$RlWitmIvKW$SFc5zJx1#B`CrI2o3ctFM3Y&*_WIp5h03nLX3w>B=85;i36`D+WgAm3'
    '90~7KvZI1(>}2rq6Mgt<W`RI83g{H7nos{YavTIgEaR-3|p5Xlq81-'
    'EhJz&x2n?B>g=i#`|&(QbE=ZBYG>n|s>{XAo}Z47PnyceSFO(Z(Eu^f>rdu_X*@3~OJiM-Hbe%CX13O~5p*~QpUemAooJQtMr=kC'
    '>|`qef;LbOx;-'
    '}$Da5V>U~`CgtD$XLLQhu8GlKD0f12cC{}7Rk+ezHA<qGW0^k$$wQ!yTD1&nDHvvG@sGFL_QWRw@Q*MVRPQr;DR_0<Oh#{Iw^8#y'
    'TdAw~czETHot5xh;gCn!^LEzU@CRRXV)&ypfvOebP3ijNo{cbSk0#sCFDyRg49@(po(fYgSPlqw=4)_7KY03ggOp^j+aCwmg}g4x'
    'yMjfE!daKy~)CKK`ENV|OF4i(VehNB84mZMXPSvidnd;z)T@X^}yVBJ`z{s&6IO|>63Qf)5o%k{Jb{tblw*m&A10M;yCd+$hxx0*'
    '{WB&VlnMfB7T#h@JG%oiVIL%l1>&$~tL0}*bE44ZM=9*7wC4W#sGUvF{G%i!i>2G|tE_QX=Pd8lBjw`mVIPR)KdVi)9UmxUMqV9D'
    'Q0;yz-jRpvo9<nTTpsxncb;dK9-'
    'sgwu*9&BT6p7!Qk?G5?b<svFkVrGdF!Rjfo4QgTBj|#A%)JBoUl)tX$UUp4}AiB|QMYnVCn$2$;s<l6pYWuEOU4fM)r3+kS6e464'
    'juuSsRaq_XtTV|tW?=?fzW%&?Jn_yRIe!$x$y*Bm_s!AYJ(D40tP?7-jm30jUGE<DF@5h9@wMyFs4#6AE=<lY@-a9TI!-'
    'KZN;ohU%jP|&o?lD;POUx#pNPe8=9GOB`&DvOfJV5KN@OJu9l!j$py7C!wz=FpCZT4(hXADUB)^=ABPJwcxF0}?G-'
    'ACL$V{vGd<yDgal4V;XG`9I7fPdRtwSh-'
    'a62!AU^$shYrn3!$j|&m{#;dRRoH>R?WQ8p_J`uG=DaZ7P%Uygf0U&tYeyKYlLLfzAieIKr09Mir1KeQ_EpqxSIq&PETYjU9zY}{'
    'Wi_Zq;1j(t;Q+O!62*H##KE!5ijPZK$+%C0{*0sNL@8E2^=g*StE+O^jqBrgpM9+}=7y54(-'
    ';9LJ?+)hq37E=;8;x0U4ONb{V$y$Wz!8kRI*#SIs#PNfec6MWPu3!c*&0~_w(8!b7q$txVEd&{k;EQ+40HY(f(f#vLAmtIXI5?W@'
    'JN_9dnY?=A_78K|kXk1FjvV*%tU8IpWjMp+QoHDOh#RRX;VXH;7(49I^26tfu~T%_>+R@Ny4_v)<j#f_Tsbs~5V6+Oih6q5JA8v7'
    'aiwb*Q+E0VWMmth8#<U9%$V8ot7;V1VHR(-'
    'S}yX$S)jQNkHWy#&f+ejGvI(iS3Bz2|j}5(xa6hjvL=^)6`Sb>329z3Y7OP6%G6)aG@G$@ic~@VJ!PVqn#GqvqTYZ!Fg=P>&wDyr'
    'q%m)^4lw{&5&iFG{G9|KyKP{SV3S)*c*Q`+65MatR=8>dwJ4tXi_(1H=Jw@D(-'
    '^W&n49t@ncI|KEY%8~N>`_k;A{7m(9ln4MrI0_6|ze1ug1FugeQLFLxzJHIG^dJ(Tw5UfPU-'
    '^ql!dr`u38~)Fqhgp}vsvlHOdrc$&XX!77iFXQh=5|Ca^`aMS-PnzW<i_XR8lXW35LQD))J{Ml7a*}~R_HVZm<{T4-'
    'dl}M(gbVQ1TF9@2@@O}V?N*!7u8>hnnJ3X#RQy9i?J!PQk6Ps(IYo{kb`p=8F<<!qg+VJO8W|C@nFgrPDE#Vt!H8f78l}nrid%hl'
    'K4enrM0{*P|2+TG|21k0;4KfYrq1-'
    'onJ*z57bz!VX_9~(;Ye)@37z~NC}~&l6$G6vh(w0HzYmW(}zbAq_m$N9?Q37B|)Y~;=T}<nta2kXXOf3ZV!6e!CHjo>n}_Z2yQ{h'
    'vckz5VfNw&<^0GfC9@q~gIBPLH8NF=_r{T%#7Oig43X&z6?3C9CGk$lyx?A}jSFf?(enUFZm!B-'
    'Qv0PbY5W{FpIGCXJWIVg{G;U%V(i65u|W3B>@c=^f;Fpa##DQ9!QeS2k9Zc?uKz)@lKKNPp_;o&u}-'
    'VmXqpQoh0sUhedMssR8oLs+%GI~J_6zhA2_RN!-uAv>;tD0Or6?dPa-ESNR@c>!6TsFh4G(~<X}d%Kut{{07&*zN_^s*5!8LVTrC'
    '{VREPdjqA>_7mAc*#bYCMZzEqLa=0og7rvXf_%IVn5Hm8acTj9mLLc9RZ(Q~tu8BVQRJfG0{)4+_wCvMQ`s=}08G{%g)QnDMUB@>'
    '6C*B;@-'
    'ZplaK09rP{QOjfBVphYtb+bRKJL>Xta4wRNgP3w=(`xxVTs2m`Bs>LIrT2(Q*<@DIAJ<5i;ja~hy~7`u6E6@_Je@(}0BTSPR)W8V'
    'ZOvwcp4mwL^6&*lwrPF=Ig3D60fsJHoXRO;p4}bq6--*cLXSQ{iU!BotK*}Czjm#*xGrb)UD1-9DF-'
    '0y<!Zu2r^H*J5Wl;%)LxZ(>~2O3TAzIt3u*0&L_0hDJ8B@dnun~y8j)l9MQFlxOTzQ+^KAQahJ8b0VT~jJ-'
    't=*2crdtUJEYGg$nZqPZNbnbd@O;)FSd-v4C&EsvGq*y?=m&(pDuDyD>kH4K5Frmpzwmi5`TS~$SJUo0lObp7)f-'
    '!T2kx;l<8(yL*=!>{@N#35YupxLsj?*`An;<rKaok{)>}WzaFT1_xPQ3m_|S<xx<!>u2A{9&1Vdt;vkP=vfv;SEL;iWCI`h18$yA'
    '%fp`uD;9>zqcm$@GI9MJRQU_iG*~K9FtKt1^#idY~EIVkBsc)NYKg#KaoRQdZdYhGNr5sp+E-'
    'V#zVuQkNTnN$+#AJFSPLTkAqoPs92?X{R;B5$2a@()E)&-'
    '^B{iMeAM9tOMK%>A*#|SmHu*@itscXnsjwvcvprIY{fM9+Li4K|Exr_?%5<*x{Ww5vUMi2=XD5s$dz?9^I(8K@Iu=!g}nfp$xEUV'
    '~e$e=LkYs%5>ou-ngu#=QJxwaZ=V<ptuDySP&K)q%4Q>OxGo2sYril<G${9>oA3Y`XuoEke(SL4(f&@F14Zcx{>uBK_j_yO6t&L0'
    'BxZsc&qNIeH}oSr>VgC4;M(w*JM-'
    '#mHx?Azzx<>w>OLy99DsgbLmjci35_s+O$OyZH#2?QOr?7=J{XmX_rSS9WZfkqcgas5Ko8Xur#GlO<5%wU$e3&6ItTz>W<^7m0ZU'
    'ha?KD)G6?!~5SwRjlSH&{!L7DF&9Qs+z4z#T%P?M<vDS0@66D3v&K$B#zqKwNgjz?TV`?l0Rzii6<VKY5w+hpMCr7w~u$9_5FJDd'
    '*AHre6lHIQzcI$4W@xiouH*hzBLkMI^`1$QfOChzL%=aK2EJ&w9(6h6fD{3lx=j&aOui@cHzEQ$;LpXMrX(W6RI}G7xd3wv(c>8='
    '<N8tRciDRwPl^gc1zy(YBX+IqS30*C<`?D^%?#0jDf0*W^VgH<%@r>;*4I+Ez@Y^WSqall8z1KxbzZekq(Npq@9SPQ%&VZB^Pu;-'
    'f*+}Pc0^)eV?a0b)})}Kg2$tI@WM;scYHRuU67U_B6gf{iM01dVF?zAFWF|ywhK}Y2jLKb9sHOwLRq0VlZpzBk*Gnk7>OXCRFX+w'
    'gP4i(Q2%JSy%pYt)i#5FK61i%IK|&jP7hu2k$<Mtx6@awxud%ym7x-'
    'rINftE2_?ls*hw<va{+WMJ@}M31g39ulh;HPx9Fhmq@az+4O4)BAF%uUt$QX%)d~2sB?qpw{sBrbel?6{=hzKK_y4|XJ3(R$}4#q'
    '!j2PtS_i_(KhX_(ne>~SNVLO<<0Vp8Bx$qC8*5b<@xNHRjEL`D6!c|xlmd;e?_Ncf`zasgViRKtCK}kt3(Itp)?N}o<V^RBFa@yN'
    'ui*<7(1seY6hEdoFzY37KfS;hEKit9x?9D1@yUq!ZurNzFp-`u;KMXr--'
    'pSAwNxcQnw*&2Pc4rb<a0tUW)a6V)8WkaFzeNJYCHR2ua-AaKkEEb4>#%|74v!OYlkEs@?H67-'
    'm;9YFJ|i^y3I9o!zFYb*2XBH8>*?M%jW8SRQX)Ddaf#-'
    '8>yY^l+JZ4=IVmE@oem|!nyZeFjw2;Wx3p2Rm*K#^wq0$aNm`6sf4ak+jQfax^+cqjheKPlC%`I5GY9dXQ@Yvy5U$g+O>+&5+qrQ'
    '_VZMtjTNG;t3w-Juh#5gud{Z9dYi~}6_~E#(p!b4hm2rtKJ2-'
    'bKKoX#(V;C1_^MhdFt(Eub#JDW8W%^6IyY|7PqS2rSwqAqeiJHj6R7xU75wz-e9AJPhFZ3!+@~k+nqqF~J~B&u>Mr<<>ykeD-bxK'
    'R9k{Y$!F0iL#YUW7-;iIND@9A#0qI)p<RBl9yMDdQ-Z~{<HMHAS9=*pps9t5$T1nazNl^Y-'
    'qpGOiZLCaDbJ@`tEW)ERrwGDr>Vn>JVbVZJ#aotJj8+l#MR>nBXqyV4HheP})+{d<Y)}WtiH<d3HHXsraO20lHG6rt)kv8P$pWBU'
    '|MSxyRsIwB6zSQ~Q28`iz%*RH)F_%uHGLz?q~0oyUGnLlg1#r_M~XFf>j(1-'
    'bnFfmIP*q#%AKBBZX>}K4Q?!M;Y>e%v`tOnyDuq>1}CD2vZQO@EAraYP5r8{eXljmU%RSUHO_3lCCH-KoK8gMzVkw{CMxO5Xn(pQ'
    'v2`WPZc)LkeNqChUuFgT8x_kU1<P(z<n2*&i8mWJRdL(CQ+iX$tGcAFTTvGa>IUoSQaRmvwZA12Q!y;JgF3^26BQO8M!#NlyJx6a'
    'U6`$u&OF)Pt?G4hxlT)pX;-YX1(9${H--vzI`ugX3C65q=#=R+s&w8#kxm`$FH<PFqRm;TXkrad_E6Mw&7z)va81ufR9>f|=RFtn'
    'bnAJpSI5((6$WAPDTeiumE<JBUoJ{PofZ`uV&JIoa@iHa#e1a*QE_st=9<vc)iNtDG6IKytk=s$K6(eC5+S!PV{~>M?*{*bfDO|E'
    'rRR25yChCazl5~1qWEiMEX^l>G6vjJ15EhDT4A65xlm8_A>_bMTVZJ>4UW&!uPhm!m2+S$fVG=$O5xU54ldAEr#^#WPQ-'
    'K5vEuZl54Y+(89D<E;Ov=mfb=Wd)+!?c%=bSGlP5dhJ!97U29+X8p>SaYxEf)(RuVz4+Z!K4^&3|#%LJ$KuG07W+>b++>qL7)D$R'
    'ln>f*;Ij}NDqjy0l*_00@nymakxtqxw0PzzHS)bQwoQ>XD6WP9gF6sLw^hC^<ylc_n9sI#y5)>+-'
    '<f*zk*>v^VAFS_!kg`NDVvG_GNzHIF72Y$jYjh!(c8`EinQ;><K57CuXi3S3(JiWfV13G=~6$I&VYjaxyfneOq-dcXhdk&pDN!`Q'
    '~RMS$!-'
    'uG%`yxsKs%wEXO=2et8uAuB2itB17>sv8WkGHY>Zi{NkcUmd=)>V=>tB|Z67~7Rb4*4>+sf_H{>+XD4l+|jZD!qm;#J^jeUdnoBg'
    'rM_8q<f8uN_Pw7Z5rSI=P1Ftd6_#^mNyVF{pT&vdraG`J>`!MPWE5DId}<q4rF2jo&SuY>bK$8$XI*I<;|H5-'
    'juNrd<+Q}M4D_<?ASd>4zB0oQllnN1cQn(j!Poy;(AeuV#K9YU=<~Z^M~Y=i|Gv{VuM@(mCR7V<>;Vvv>+cKQ)6^~#didiVUkrdF'
    ')0DmeF`Tf*ycievJ73Y9OQp0w)^!>WYUaC#sGCZ+*|~I{<9%N7`9}@g*qet0byhhosA=j<T9efEIkUe_r>d1X{EwCuEhdDNr*lk1'
    'C?q8jvg_@kleHyBtL_zEEPYT10|oyQ<{*Oz{;>sj(a)Qmx25w`Q#db<>z?1uO@==^3K+IahcClVh=x;hpI};1thCNFm-SO-'
    '83F{3Xkup_MvDire=(iPU*vOYkAy4xjmW+B}e&^KSN#crm}%ed3s*atPNI%t0Xa=es7fUr0SqLpN%}(Mq$;$LEAmQ>N1u9+=k&|j'
    'Z@TMBo~v9c-K)IK4n~am5Z)+^JQ{fR?8=kcPiv*;p3?|ZKE5-'
    'ctKM0a`DYGZegYWQFMqGL`Zy8i^D1_izUyg*170Fh@h8Lb(GV;Os5n$L`%h29ug*TJIksccnKGf?&qR}nC?VY8K9ETs!j-'
    '>f2MDOA^u*FlSMHF%_WS#m|V`_afLOf^YMEmMd!uxL!nB;l3`^a`3Wrcj1{|Nm3AoCipe=R&6N=Is&_=p1a2S;4|{o0-'
    'ONT<@sTvA1o0QHjs?4=ZhATdTqAm0yxtOH#QGz$Zna!X4ha5tD%84u#jUzDM@Dv|`r2A8(j0x}R7Y#(EHZPxXUJa$YA6Midd+2RZ'
    '5xB9SzEJ|Z6}rsod^9x`$DYnkCE4n06gjn>f<MA5=6^bS6PC2m~__>fG|pTy{uE}7J@;v<|bnu1<)nXOA9%ElLBtMXb%P4{!9hj%'
    '+3s_i4hp=Z=g5%_vbC)_POiQnMI?H4i8VZQ@8VN-'
    'T8K;^R#0k^MtZ9pMnNnf!|JR7kn_kNqbm>p&J<mcD;R`kKPrtakZ_gv5N1`YE$Thz169njFCr7mX(n+@ae4@t47KRAtmL2g4#7sD'
    'LSf(NB1YRQH4+VnR;tyF1s#a!-'
    'PaA7|gz^8c)fov9MG>tvf5QDE)3KjeTi9Ws?MZg{O9f9eAK?K#6PA=SaG8?)~O%gr22Q7wfy20aWS@S1?G!wFPuLWw6v=7(kRu73'
    '-SAFYS1N!0hC<fG>aa`0(5!C2P`t&n-5O7)3!G`WV2L1`4Rqjt^v<2i#fsIr0he9mqRbHsEr6+{91UH=`t;8gBx%OZb%-'
    'o;VFc+FtMo`u_ML?d2n};@O8q4qKCDX<t5$loFG##cTkD#B4?-'
    '&KU=7&e~{sIW5lx(<_!moR|0cqT<2!Hm*dE&g2^vyM*t|N|#P`OKkARRJH{EpH(%W2@q%e!(CVNLlFbAF(b#C^+FPadav|GD7F!='
    'kVep=A#L0gTmZYh0VR?~JFJ;T`i|=5+2!(rbg8+7ULW;b0=Z{m%(LZCEyw4XIVQ<~%l8(Q)b6SXpvu@`C*gRg0N7Yh&&jXXsze|B'
    '<D|_D)&ILA&;V^CSZxdNsT2sYc0U*kespkraP;f`$*aRR$M;jY@2-'
    '~Z!^VpiJ<v5(Ue_!$y6M%hMqNSgf^v&9lf<qAirJ4|<q_J0HB3#8&UXI}`i^~a1a4+lBW!9{YNw+03%P+6JJ1PJOw|H0Tk-'
    '$d+sSNJjQ@(9jm$}NtR*${=1^tpoT7!EXQAx`B0tli3V;SCu7txGdJXXGxP`TX#e639x>#P7pvM6Thok!;$A$bs93DzM!6VU4t&)'
    'sspOH7RqWn5?tqY08tPGg;Tkex;*9$OOG(&@9R;$xDCf|!zfi%7}*QfSdk|nSO$P2~vf|%yY!YtJQcx-AQJ8i}K%f=4tABW+x{ys'
    'x*ZhD*sHcAh+tc56VLLTTidR)I=16`11_JRbVo|JK#J`bWRu`1X;0{LHi!f<$G&7<3(8tgrfX4AVTRP(Uw6+LWHRj1x~)>2q=IRm'
    '%XTBUXCE(5CTNPkiFwPabP#Xb$t!J6`q_gCeSqBp=gi*iYy^GxtzkcqtW59lR|`~bD%X4vX0@&zKt;j0||9}Mf&hXq)3u^<s@NWs'
    'qmER@LvYM+djt9)weV85dKN7jC!sx6bMB-7^GS1-'
    '4XaQ5OtASyKCRZH@VCHOc9EP<L4165n@rV_XDcrqKDub@890F0^KU93cPp6;f`GWqf}X$p;mplGdG&6D$dv6zVNKI9eWDdSiomF-'
    '-~yeRZRZ(=R$Ix~9V^-'
    'g5HntbVY%>BfO2iDZ1{3V0Y2ar}_0L(Io2kBYMk${^E*qpSgdOU$ul!2^5B8IfC@3qD^UtGS&jIk>4mY(#9PQVAV_mf3A>nV37AY'
    'u9>p}LgZ$NLH8+TW9tB1B^|r;Fg7&uRye8Wt9XBt@oy50v};L@9<$)s^YnqkP~IBjHbXZ_H$f*6z@9h=YN6xF}Wv1HXr(u|jtx$}'
    'XGs+`4YK5n#4bW9^fTidI`W#LrgO=f#3*sUWDq@vFa{931`JPxSA<zk2=JukAx?Vraf~w8g0#4RdB+zvtqBzEe*uGdpA4yUBDqzt'
    'k(;r-2$8Ng{`Dsf*WT`EE7G)pM1^mCo-0Ydj5DpC5hWxb(XXe!wqn$UL-iI(4qh+b@s5M6y2FpqduNygS(8G|e;!P{(#<b@8VPDK'
    '{KJ141G^vg}O2>1B$>7bMKmA48scJoJ!zQq09Z?kt8lE=MmH;38uAPg8HG)qq=wa+y`ie<#tQYzaoaDL-'
    'n;W|gR9#bQ0^=5dcGJ{@2{Rb@uT?Zxr)tK>yKUxKe5-*tRu!2cIq7cmw?aOL0>pS;fB72A-'
    'gIpGi$_Q|mf$OHBj&^yxgP~E!u(b(vtJI#6kGQ(`#{gR<3=CqP8lSf=}1RD1Q(+<qK5EdRKU(#E+SLkKH52l%vch(rRGhl%2Z2l$'
    '#zRS&~PsV_n8Gcw;0hD*LPYC_CyCfz}U~7-^m*~Z4@;kD4oGh~ko@ST?ZA|@q`F--'
    '`;D1W6z#w>isT;14Do=QIwOT@6aZ^Lo6{K_`IEy~G$6>M3J{H3)EPqJX^<sWS$;}j@kfE5US1IQX@%Rx!TkWFbpv>6=eih4>Rej}'
    'RE2dmtaB^F6NYk|iB>@q9bj(o+Q=ax!ImaPQhHKehp}GXKiXtzbg6FX;kz;3S``u3Qb)Bbsf#4*$v|Dm%w+tu{q-'
    '15_v?7!CyhY{l?eXgBFXhf;m|anbGE31&K7_(T91E8MCU`YM_mZauEZ*)6?*{RXe`9$fc!Y3dBfOK$M({fTj72U;g{j)AXGVMFb('
    'JrTGNgb8ANmPrtKH)*G}a$}XKr$M(Nq4hyEE9qJxsRbmiO#0NAFUo5z*%#f=sMtBM@lBW5)-PW3%@#nJ-#W#pc>JbksqD51yaE-'
    'vXzSyjiEhvYt8)c+$c$c4~Ad9J)BjXi(;0^l|E1{V)rO6)lG-fn`z)fe!^?!~<b%Yv4K|hKnm>I@B8M6ZXh)t-'
    '(5x>^^hYF|4dbfCd++zp}}A0FI=;zx$=FF(z^kp_)oCAz99+`Kaio|NU`i2R13~o$fu|eS8)uk1f?{1{?@zh{M@^{5%8)^C0i3sl'
    'm@#`N`4w@<zx;;K<X7&)q=LGx?S0xrx5aQ_BT*N=?mR0t2|b7btq8_IkMgE8(l;rM?N~tMe&`kpPoM;ymtvKs3#8sOvz*K1x5^uU'
    'Jq=?zGVU++zs%kdB8Cc0$!{$(oW7RUi0RFRQZM!4(>Gc4W84;Q9@%Rm6Y0%NRK6?A9?`nkCCvgVa>7tdEZ8LsruWE<!w*uBt0+-'
    'bTBHQXC-'
    '{DziY{VD2>szYG)c0{<TDFD_S*7XK~2=>luDm>|?)mW|6%mi3G;A;vn(`IBzCwI!`%ed(@7GXsWf_*QuZMLw2_dI@Dq#zb4d8v3`'
    'Y+NUjh&N%gHj&x^;w)6tdy5LBzis^i)*5~+_w{MRQj*khPcnqQvLnRjrc!mqDxJ!64pf2>*7%E15&vWkMk62MhS8cgtb>Vnv__`n'
    '-XF;;5w_5Ola+D;GE!6R;h~=~w*MF`#2{C5F=!cFJ=vW^psD&SIqkH}F$^OyFFK@FKuMc1RJv%!1zrP$DpKu~^L($U0gaDdqBYi='
    'Qp@9xStE|V)!~*`E1PnEfPHj%56Qw5oCx+9HRjjkABJ?ze)X$*qC6au-s+L0DR-*s(CYhu0FqL}hBbo)p4$();MNyEx5Y-'
    '1fCZ(cAeIO8W_+&2bMZp9P7}^`b2ro$CmgMp!e}c8V5vUl?ctTM<f7^fY0%FCMg8Xs7A}^%pZJT1c2SE<WZdNa`rQ)hiJgH3p$P?'
    '6$O94*miv`#@hCa+7?Q3_ZFTH+yy<4eI2WA4&m8mmjy{fh(|EgL_o9>b6z5g1xOx@;CUvtM~>FRx6J+IgzJP@QX^G^k!`Nq!M+fA'
    ';-^_x$+c+@8m6;nJ4;<hZ`)oJw03z1gaCojOAlNM!IzoB8!=)*KTrIf&w>-'
    'B=tDFg00E?ExS>$%em<6by@EBU5uXlLYfz^epjvbD~5cGg#!(Bw;<8cn?P)1j$mflO&mzahVn;TkD0n;b!g?Q>#UaE*g~ozKLbQ!'
    'Qz1)@3M;<3Ed87HZ7h*Ik!=PnT`z59GjIwZhq2x<s~Ao(o}l1XQsY6;M;26|8f}>_avUac9lOVpXVIb%7BnWM@IbX#o6tQOs?Hw2'
    '}<Ap^_?#uP9y!&O+QI=d6YThHXr-kAt{!(c`EE0u_{6B|{sJkjABS(bfD)Ke2YkcPy&gh#-'
    '^IPgs@cv*vX>K$4zHL}pLUo2{O4`V&=KT$VD_UoEhunJl)50`XexC28^~=)S_$x2(}<rD+QRq;95xS(s)eB-'
    '<PYEc1U1Ax5~!Auerj02(z`9lB--Da}PcPzk%xEIyQ~FSCx8OeJGHvQ<LH3oT><l|fHHsSyO<@@2*vF2SU_s!uLiVL&K34XoLLW?'
    '89Bi?l@&PNOFv6LA%wn;7p%An;>%iMkR`=mVg)9H8ue%I0+KUg3W2G_brbAh+9Mv6_>fmp2XMP$=+(#H34>$v!GZOe?AWQtFvp8>'
    'T{+0V-FyJW26>Qm(Mh2DRT~L#*AM>c7`u$JIYyy*c4M)SBy{ep`^>QHkm#+&YqMhIK`P`;OwF-A&+BiyfYx^^K@W)bFUQA-'
    'q|#*eU<C3ZS|hZ`bY|cCF%g(&r?zv&#A9I-'
    '|bFZ0C)clmZnNt)#}ct0Agq87t{37tB>6M+4m5lPlBl+GiH^g_d`0#9{`Y`NlD1u>++eBX%;@B#v?+f59C19$>qdFG04Oj3hGtT-'
    'XH%+_OgSlA$Nt4~Mm~yP+v1Z#oF%rsc38TbjMzX{swV`k_eaSto*h_F&Ox&GT%iXRIO`j7UXrrNGz=Xx8;z!={8;@gZPNfHqxu>G'
    'iDS3Z%90lPb6p3=YHhwrc6V;P_oR5mQZ`nr1a@WfWU`3`S+~^pQaEg|@8LZL!~vMAJqT^Et$k75N5uik~&%B6(3_L&F`C?-'
    'RRWu<&~DA4FXrYN-ES$gR`GdPw#R5rfVo`?8N^xfEy_1iu#?FYV_E9U^}}rQ@DjI(`0u>_N7++G}L31!d<{qkF$If0YPB_=q{F83'
    'HT#m!Sk2L+<Ee)Qtv?Ir5M0p$Uo#BwN89tL)I|=``4lY?IC0o-${9h6O#$lO1Aig8)P8rG-'
    'OEY&N|i_ku(wy99K&0nw<Mm$M3eWXY-QidE1NaDp8WoZPh#N>%DF0b3m6iCEl!qRJ7pedOHF33>)=uLF@}46dtMuS3YlY^&tM_(t'
    'C5)LHjpHJ#Q)VcDwewE*^$td#+)?IHo1ffy<AuGK=dv&7qbzMr7-L0oT(C5w8H(TVyECv-|)EhE6lAx~yY()gBQcById&tg$-'
    'NpBw(dcp|AS2(YB_!6&KV&?T4)w~g=FG>(LL&eZ#yqcj*Fy^Ccy5#`Sv`5Nk99-'
    'QBQ6j+D65;2LZFPNQ<mitKeJnHBL?yFGPw_VB8CT(uY9)LoEk89@vS53yTzLfEERVp*AYX;&7?O53aGi?`%hCAgL76UcZHA*2ELt'
    'IRf`4_FQ2A~-#LdD?4gr}MQ9=1^rG3))JBlXh6oc2i(Kq`Oa5N#yQJ8)*o8~v-FDNs83GDlJN^QXglA7O(>9+n}w6(v-'
    's451G@>}}xT$}~55#mXozp!73C-'
    '(k??o3NmzAD6|&kKmV2Nygh?209B#Z3EA8<Y%cTB4B<t$U;_a(E$ME(~jye9_QU##O6xnIH#~7IsfTwMgm=um$$htsm2Vt)VsG=V'
    'Q1Xz^9hD)35U@sMWS;w}60e(dff?XoigRi`o03*4N264)ibZVmrdYo^O9U`P<=}xBDl58<u2=6x<B?kDe+^WZ&u(5<-'
    'Gmc_rv1{LRMJs@prO?c~kjFUJQ*$FEKfhUsqFr-v^O-<<s8NIZk|051+-'
    '(z_s(S8snh&R*`H>>nST9A|HT%YJ_K=GD*pud`P_zdbxUImR#TM*F{<9A>ZH9G~pJemzWg>HynKFMv-'
    ';`zJ^HZ;pRDJo;ITJ3IX8r`NCE-'
    '~fAl3}70XnDy%IK_HF{Pv=md$04Y*k&vLs%}(Y+zW_8wKwRh5yWvi`^X<1AxGp>fN3}Y|K#zozt=)Eqjup1yvt|Ud)JESJG)7l<i'
    '17rif^ERCBUl3_BNV9yC%_>kQX{XcL%4-5G^0R3=p4o-'
    '5FwmwG2k*0pNWKyR|}A2qH}LnO&BT(GjI}u&5WoXGh)F1nps)z`zGv)YW!=cItLJ9IAa%r27A#qXgcb~-'
    '=h!Ux`T|2Z3g9qS>y`^F7532%@>6r1mX6(9bdpU1DWC{CngF9q7K$Ma2(iay5dXTi8#}sHY2F9Fy|hX9X3Bho1UdK%nh%%Q}vT3{'
    'MhTPBRBh&&ka$|4Nco!gQ{(yy^SDAy(X0nT7%VGzyT3P8JP(AjRc*pO$usQsk|PXk(uAAqFJUY&w&SO>YerPAx>UTvFS3|fr3ebj'
    'oVevlq3AWJBqtQbg-2FEp-+w@FHYS+>I#%l-@2VVi8m5#4Uz!MvT%AA%R01!lF&R&utOBA4t&9-'
    'onX_)@ijGp_~pA4X}#qdtkS~9d$Csld+*ZrSPulO=@p`V?3O3d``a%WdHe6M~~FSFghntn{|;-'
    'b>eP@F45VNaW{_X7?bdWqf!fbSA8)6cN;D9POh&>Xu~XXT^n$p$8B`{9{9acF+^d80{_iqZ(U;0nK|#<;Ch(k5PXbu-nnY>&*CpT'
    'XGRIKobpkCZGCvZ2KbN>UT${kyhttMylSPNx$>pE$GmX35Y<rrG=0HgGMrGUjRu20sNYTlXy01dUdQ27#Y=uwnO|AN3~xkgkH5s$'
    '2{C;+K{u~VFwM}hbG3RdUbv;ay`(kMo%M}mTSM%^@py2Ouxsb}mKrqeD`e|71zxr_nR9lm76zPJ>wTYM@P_GJFiDy2D&52%>nkn`'
    'L)BKS_#Vr95Bl2DW;$MtLA`%hly;Hr0cVq8fJR6YN$-'
    'bR73mzmmZYz*?kBqRh%sSq#|;7+6%))mkFG!5)bK|#aY%Vhc+p;8C9kQ5M!6V+8$MdKKud;(b0`s|o$;Z}mAtaZQ@=cid^!fO$ue'
    'Yyph#R6wFQ@;yz!M|93tbOv!4Dx!g$!sM7@EgiAk{vp_?9X!Q)^iHnCzHNsCZBlGfbZ8d`LB^d2>6$rc9By^(2&;Mdw{HsUNdFdB'
    'p%7sDnVF#|~{8?AVfh(IuwXjybqG<+o-'
    '+M7tGlk4ONlwQrmgs`|<+@V!Dwfgb@DSl<d|DW#d?(FQiSpePhe1~TvYMpC3G#hSReEULArC<=#0kq!PHoFTmWjT$uCA4Wl4Mtd`'
    '2~DVRp!X&7+(!0c{ENvxx08XwyQzq3WD)CkI*ed<AZLXx115R}T*}4R%uP~e$RPGGQhT|oC}~ux)PzBD+fI&i<+*S+SH<G0p>Sr4'
    'K;vFJ_||QJJ)i=^eA@GG4YVZ$eaLvvTg!g(5Zj`Hk3<M?K>2&%T#hFTaVlYRaD&Z87z18)Bc4c(6k>kqi<FuuPL^SIqLJ=0I%NnV'
    'vx`C1F0YB+@k45V2nF8EQz7|d#1h)#zU2|74+x4(P$U9_x9{RwuokWDg&CtI>pH?FQb~7<>*O#H_(DN17+@s$_tLsw^n`=gemid}'
    '+gZAiW!Q+ym~xpdg-Nd@P7jGf8BUh+=+r<n4>E*GfIwF1$Vk$<W8ys$0<m~)4Lp@<69-'
    '6zHX$epO*kmB2;|l=$WQ{XZg^Zober|IGIC3n5S4`zIWy4r$qZu8YTyNBScz|_70z`C7M+s#@S?=SP{0_;iJUv2_DiKYfRq+arc*'
    'B9)#WSRD&u8Dv^Dw(TM=&!5pJ$3qc0b&xf?uQ7#|1@fVK{+ei6cop2iNN$~_+Pmc$}E)ze+DYK_2LRY&54+9b8{Hw`pU>JTlQ7@G'
    'LeymmIKscj#sznWnLd6eN={7G{sq~6k`d#L}6g<Q7x-'
    '>V71T$={08=|Ris(MlOUSc)dEK!T;nz}ya5#Q=o|0<y<Cr<nbmdHeEJEc+!X!ki>OT1LT@uL@S6#!R!%*~R!5CF@mgmgwC9#Ib2o'
    ';lqRnF0gw4$!^0#Cq)jOv)Q_c9iv+e1&ECRmsk^=RVavH%u^o86(X+wXY6j=BuC$^<RhT2jiMMjdzxJM<h`WU7F$Ld>duT@XBC(&'
    'TUrZeplv?UL71Bhe7^FtWvYs;PDpn^M=dgR+mQYWwCA?KkjXF9RI!D5$oLz)}0U(i*(R+pR-'
    'AT^;br34<^gvI;b5826Hn6%QWw4(8E}AuTpD`wCZM!b>-A}mIj-xipc49qoAZ4mT<{C!us4?)duydyEOi?5c~j`PN(w~+QgQS%ok'
    'IEP$CkjxFuMM^Fl>*QE(T9m>9=Irc=SRBm$VYlqXX3+>)MhSfvJR2a7@Sqqx|)7a;`$^I-'
    '{!R@$>c=i~^g+#fk1%ZWmki{0m2s(5*|C8wb=XE#+aeto<-n8&Fxl>L{#tpOn)-'
    '&n(d1P8C)?7wae!jz>tnFRCGtAp1sj}x=F9^{=JLmpprQHNx#Ugjb2g+{p^;^<^CKExF#Wf}lcIfMYR$~J@<W6eZG&@_-oh{3v1-'
    '2Eh+Hb^{gOaa6oRX>=P7P=QA-)dQ;pY-'
    'w^{&Mp6mlIkaRH+htDE0w=F0beKA=LALKjtu#CHyr$H^IC({8@lGFjspr19h!T&R8xG9+Y#OK)IECfz@*pNPq@YhpLaDd|Il(m-'
    'E%sPDO<4n|~CmQOv7s4uyag*Xkjyn|f>v?&YhagBK@<N59>!PP2mdqkwTNe!K<V#_Pnc);!9u=ef8K)TV=zGZn<u0N)&({NwQG?='
    '8S_j<Lz?eK}%VPypV`{ezzm-(<&s+s9&KV*kGTZv5@@ot-Devr+Nv{CWQT+3v;e)8g@H=lt89o$t=i&!1g9d76LoZT|ebah{)#o<'
    'INYNj`e=Was?x^T*><W`D)QCdPqPsnj9tC)Z+X0@HP+4<NegeNC|v`JvmvT$Nm7n0D8?MztzL4b*)n`2iCP^P3-'
    'r$&;P$o~hoUiLT|=L+jjmRZhj3U{in!>!B7sRjJK_kq!na&QNd#COm=Fz$ZebBXIB#WLknxc=Y5-'
    'CKFh)iG_WA3`p*3a9%}oJ@})@LKur6X7KC@K7``lBN%hKv-'
    '|j)Cr_V!`}{kx)uN{qS)P$9XzFHxFVsk6D$UkgW7Rs<LvrY|wY*jVa%Ozw?5u{N5SQ>x*iWLjo0;#MMed(=pX-'
    '}mCY5kDEjH;>x?Ikz?XccZBo3!H7i8faDXZWXiv{3}egs8v1(m;;n11F4IGer`Zx~K}gEXAxCJ_<FA}hgDd5!uR22Li2c;S8mU4{'
    'EXLI*dY6|32$YqgoUll$PC7bsr{ezf#vuytK&#>iyMgVm}SqcKNa7?2u4%F^~&BH4?x$SJW}m<NV$YzraaWZO$Z9;xCxUP3IMu1c'
    'Ku-TK9<FDcxZr-Bt%n59%so~<5ajr9l`S5mf%BgYm5U*jr(FB{Hh7f3hIFn;#~&@gYt`1MD1&|q>OVNU#!q=OZfriDkiAQ~*OI^^'
    'S~HkDX5o`N$k^lpVzVfI>o>^Xghrkc-gx)R$Vy-iutRPhf;_)72CKwWV@O?rp@+9ZIqgaRZ?=^V_qIkY@i--'
    '{>b2v<G{`!|7z)TeI?BthT>N&Vr=bJhRp-o!$GS|O-wIL+r6WpfQCO_{_>RiS!U-'
    '1MQ;!sL2&jij$@am?R5?m<BflW*SLdGh?}x6gVt`k8K+l}?@`FqiLsx|0bJQ~uv9I2t{lV$`bWwPG#wE5Jye6LPh9PbwrzABi?i1'
    'i(+*gsUU^1BFMKFYOJ##<af`*N>0Gu*d4RfRTT*v*T0;F*p?d0*cmMm(^0VP55K)IDmF}7)d1^n>~DFlRS0U>6Q2)0E7=a``PP@)'
    'g|Ntgm&5QBSi-'
    'M6@bHp%{~2eLE*%l$(nHh@IHV;n(#X5!};Ea``NnoV|XZUR~FY)dZ51iKEdxHs|*BvVb#X`22#VpIpohI<C4l`;^FZ)Y)8Y8Og&V'
    'Tqq5Jf?t(|Hl9;IFfB)DSth7(AFpZ_V9CfFc8~K;2dNITb*`CxX#O<4zkouNF_`8^VgbHBkCub(iLaBy{KQ+wf3^}MB^dXj=-'
    ')8C}(R0yPvrQ`lBi;RGcjsFooBo*l$>Zef1ady}f86@YViclhUXD}f(hh14-'
    'O$B_zo7UK7gOpbl$wKSz^7nQYzgs{+xukJd}$EcAT*Z%;I}5XCUf?-'
    '*tF1|$!p)^P_d&>@o#(m@Y^pG8%E@e|DNgFJ$gw?p_C|}{6f&5K#mD_VyJ;3R-'
    '6+ilh+F}a^`@}3rBHj(81KL8EoOOOw(dV)7VR(crg1@;>I3>DhVsD2-'
    'IqSoNWDY3sUhOvQLz=$Kkw>QBr2u35w~sGBq@g%IjZA_xE&K<O>iQGprQ+39kUzF?tlBTXyf(1dK)#rcNX^q73WY1R?x3M(FCoaX'
    '}@WaHiHwGIE@Q&Cuu*4#0n)(o*;;o6IiCfjH;^v{u&yGb;14n&2gfJCRre3r$f{R+76nR!fFelK=L^l`fOp(N-'
    'n(7t0*9s?8*|1uc!AjnjY@*q&%zLs-^t{{QB#w7HGr+J5J+nB)rp8-'
    'OS$@ymmPRLK%!Gm%IYX*qetu%;ja5MhA;3JYnL!vFsIZr!)HnE^#7Nu?}smhPTj?|P2^!M5l8_X3Nuts;82`ZcPs3xf79c76Wtn}'
    'Sl#p20MOw60lffngh;Vtk1CnL<9M*mgJp)3I5QcRW|&E;M4(Mv=HP2(mQ6djH_99#r9o)(Qk_cxzBGt<B?dQc;Pp$M051(&hAwzn'
    '-6-'
    'K*`Yo18<O$72008Kj@K64<Um7^25)QD@eOEUs+x+m!F3Cv+J`A!Q$R*M~m%nKDzlZ9u?c=r^#Yav`hTz5;u%ar@y^kFYnqOvG{Tk'
    'Xie}nt&Z*e&|I2eXeVkSpJu#)sfx?Mc^A<0zz}N|9+-'
    'IaTj@MjedjX)$_PloLjtqd`kR_uRZ34oB?I)lcj1Nr($hO<(n7n4>0xKPvWI;iFKi+JuC!pZv8+SB?6bXgqv~rVJlR}$O1RV#2*Z'
    'PeydyvFaLw3^l|eXRG451#E69)u=MtPy9o3hC67Qd#ey7eSA5GPp)o4*VZ)^$pBX~{h=jH7;;GF92^|JN4m9#OIx6h%FXkfJl=>{'
    '3iYP6wNDD;*^%&1{GB)4wyRj$`EUDK*#1nMRqVZ3<r>u2*Q1d(`sR^tN{Aw?=s;P`B!4vG_!!!q+E`i_@Vb$c|OZ0{=?RpICC7L8'
    'q)oleqp%JY}4Kb4bJOf)jONpp{lqL6j&V%#exOxhsgx8WkQ&T6Mc$H|G>*zb9AQB@MgC>KYH^q2NifE;v!3xKUGi^*L9)TFa1lVl'
    '2)SON|`*v~$IiP!wG@-{Pygt7J8hsZ8BHV0A<SZ@2p$<k7*0rV1BWzjCpwyF)6Hd-'
    's{H5FJpTdyamn*agZVzPy40<mF`v!SFeAMKXu!RQ}28+Y5;9Pe<+>d1{9`l*2q4p}NDI%k_q2UpFd<}?l`qw7!~$9}V#TmdAV_i2'
    '5&TEf9ayVsl-Rl8MApa0QOx!d(=OE>GXSqEUfVH_1)M2X8MV((Ud&u%fg9nI#DJICKd9C`6q(RKPRs0th5x`As(RL+u~ZPP!=52z'
    'S$bf4gmcAE@^fag(jeYt=d5UwE%Y-'
    ';nA2LfD+DJa}Hh?OVts$js*deym<SY5O?hJKurR3+GsSXl+9xQ<;Y!NG%a1}!~?SAU3I$r$O?!1Kwiyl~CB%zldh5NX0Q4Avqp7y'
    'g4#86R@qf~Y9pufw_x3s+(BolYE;kSbE3A(J5r=+~%x3H&kN;ImcF^=F&W=4v);`;Dr3#fay#o6($uTOg>nx-EY$4(p1Cv9MU2Sg'
    'M7{giiDBU#Q-'
    '^Og<b|=y$T4vc7tsdI0LRf2KboC3|~Oir&+~(!jUWDos}rtR8&H0^?SEslUeDvPjnwJWa{Do25DU!LqdgOO}98v^s+6)2Jv~X*Uz'
    't?q-'
    '`C<g%YFc4*ar^A;ojObrktale6_%8hyE!k5aaB@}SDSWMWvVuX_IQhwcRKH8t~`?6c)K45^Ye@LjXwC~82dPZmOGm#Vogep*Od9&'
    'sYh<9s9$RUc3HjCn2c{sT-'
    '!)_xoyBUX4Y+zsov5=eoPJ^Y}a8MH13Ct95d=^`E1@Br4^1yk?MCC4YVT3XIF8v_(v?(_9D{$T4zX0bU2&XqA@Qs+>S&KzRzG|bt'
    '$~Ip5B<w-'
    'O8Lf>Tc=F*{SWfY{qYsAPcGV{PmrTT?kDI=PHqlXGFE5rQ;7SKq$3`V85%3kG06_5e7JxJb=wyD!SENb$8b1XQ8}7bEbbwaF9;Sx'
    'Hwo<C?jm_5mVXn?gCsimjboKcu;U1`PVw_jRI?U=Q!SZe(fw&z#)z6s46<x6o@ra0#S%zLtr^o{1WXS~ScBKi-'
    '|HK?Klk2EqUMV@SsFJ{>C^vzligq^IPa5fK9EaOsE3`tXR^`goc50mVIt-T^*fCb-'
    '0_hM=9E|rm4`2$kBhIfUXP%vO6zv!EUcZEWmL*ZQ2CbktNS=mTd>lBTRVgm^@EvGLHas{7b_WPg$ALQ<BQbM8L;Ap^g&PK5mexmK'
    'I09N1!CP+Y?WHLlt=fo&ZcB2sn3F2n2-'
    'OmNm@w~LXMMVZ1hnDj))YQXH!s_bZng~4bI3^I5dj6a)FYqBC_^?v5SFV%M)$Aocrpe7os!{U?ps}Gw3RPuHC)j9gv2;!gqx==$o'
    '-(_dt6r!-'
    '_vNBoZc}AN)ElHlK##D2ER5Zr@$H@$;}UQ^AHc}$<?RT(j3pF7%vdd5Z^uwN~U7WMrp=;EG2wgn`tw_%vq9|;G#2gk}qhJC`}UZ%'
    '`MK$Zvm4O(MG9@<|A*G>bZx6pIpt-EAU`^1l*eO1U&dgQo1L<ywWg!1(Np2><1Z(^ebb%M%yf#2vhv++FZsPxMwIMuba$cu2fF6R'
    '*EaJk>|pjqTIaoZh=;p;4N|0F@ljJK7Xfzmu&>@h0VXw5Y%x(T&{9<5{Ui%ODj)$tPy0@Q{B}KQb*kS>fn=R?#&}LUA-XUGEQD!U'
    'baiXpZj{!dy=s~;=D6huGByuXs|oR+hAx85*Jj{ZO})MsvU`EQh!gw;&uy-'
    'b}N9fFpt@Xs>a}w!cTr5d8~G;$@+F?j!e$IwmOd{B>zg;r%;MhdT<vRJi3+|kf?nf0~7wulKpRg``c5nAI|X@@5#6Z;6bR80P5~?'
    '&Ex?_CxNK}9b#0XzA1(s*_Pn4F*ho7kA2T$U6iW_4$~t`Q^JxP2yUra6uezyA0_Mv`*dt1^~tvPXUk?aMl|X?l*<>fX$yan>NJaU'
    '1`R;@iCThsS>aSFxT^k?+urN<C8-r3TCD>CPF(@cp=Di<IM%zCh}{AsXMtT60>8Ryc_d0EV|8`BF&Fr#L{bI&DEJc(`-'
    'hHA+>ue3b!7Ihs|k18z~|=jEAuz|#qusk=&h0Npm1W7xdSEEZ`j4*Wt>u-'
    'n7EofBQ;+u=`W%xll&L`L)$yFIhvkfXIRuXKu1Hjs$x#;#;rH1`VBl6mQ=+R9Gr+DKkc6i$4P6ewNUYu6sob#&y!m+J^~_>C=jV_'
    'Z`r+#xrJh8<K)=dO!R6N<0RKB4m}T*8TG@yGwnLIS6;SE_WDf|s@Mi|-w{j5EYd50uO)$66VDCu%qi~cvU6JhPc5WW-Khg2T{&uf'
    '_7ox=a0hv_ZE}kYLc_XsjSON6tA{j*hClhR4wB^5aTM8-'
    'voVPH{zYpIM3#w2ME%Tsrg<eYVRm69arxj#5dq#N6J34<A@KO0CdGwKQDvs`jV{#+C$dq#|LpAiyuj$l9B=b~fE1ICxB~^{T+4%5'
    'FcBti69~N^qG(8l85<+K)$A`%AIrt96FMIKyEVr7&#}Qti>JOetq|x+XL0HKmxFf*(Q;78QuC#|c)^ADW!XLGOc0QVx`8+Zl!~*J'
    'W*5@}Qa6&1;^)m3u-1P70RnVCsV87&HbZ<1VoE@4S+sh`pjGwG@xR}-'
    'y2Tzem#tpUX(>!~Sr7+?I+3B^JlSQ%$n|<M4|>*Z(j(ZA-gIoMvi;fN``Bgr3D=|X2jI~4$P)}tCx=>v>L?0L5zifoX1Ay!t!ze6'
    '={2y1t+IldvdB?W`W5`}m-2`A-+A|oSMOiHEPpyaKmP8`QTh7lr{h;grfKHJ>DzbZ$@{nEk3WFbn3`L>{o9-9qF2S~yQ7ou-'
    'n=}IU;W4H@5@&&U;S`Y{&4#CXc+6m1VR!J(fs)K-RtAC#M6LWVpipkM{nO%+|A$Y_`-'
    'QkNw+Z6JURPB5!C7=IChJF`g`&|WtvSrDl?+zeNx(6*d)3!i7d?dp_=!wPy%vOGfPh1zj;&1Z(1mV(;~xgN=UusbiBzho&u5=-'
    'qs7h>+PDsIk*Q$Y2b69P31+fWk*Qf>MhlX7on;fzejlZ<ED(Lf!-'
    '!>hhbWB1EQ(H8XCq*1Y27&4aAk99avC=E1Zu&&nXqSu0+_)WP~WQ!RJqt`++MRQvs?&b?oWe@zY{*T-*}I2!f^nWQs}81vbtgP-'
    '4E@VAkB!oO{;=Qzu?c7MtCsAC<?1n-'
    '&cE!{izYIeUKsg4S~P@ftF#w@~kD39kMbfX@|1n!H1R>VATjkLVpq+J9GrjUo0Q@L`3gR)QV$L+hW5mP^%OBTI9B&?@~VfC@_Rka'
    'k1wrq9ibzQ}}yA&Xpib-'
    'i1BBC!Z1SrLBz`22r=*F)3?`NB>fOpzt0<I|%G>_o+gdH9F4HU%NsvqeHv^7{p>;%#hrC+ZH4vZE*$?iAnO=1cctBl~(tT~SlD-'
    'y@*un2!3U8-'
    '~}A{<0x$rd72G*~0o)=Gko<XBV1ao~vLAxNmeA3Q(X&qB^JR(G8f@eM`Ofr8**j9NSS&iv2bhayg9M*glH0bN)v1y%J4_I$F~|O?'
    'T@x34@Q=#pUI26X)w+vWL@_Dg}i*s+91c;}zoh$Qz`r&-W*-^x^88o71OjI=DzA`_IYH14uZOfRh1DgNGC$ZCc6vm3P#-'
    's;hO}e3wL_VKw@0GHT-'
    '?Jy3gcX$LaLh6%MjwX|yv6*Dtr<^Nu<Z8!xX!>+g+(F})tpZfyd+s530dr@gu_TBhtdd(9ECu^1kCrLsV;Kl&-'
    '?LcRTq~f^`<VkDG+MqBS0=VEN<50YKWh%$m^KD_~(tL*A?A;vWdZEEfM6xw6-<nP)&I>GCVnUvr9=z)KuV9V#TrDBdapn2q-'
    'Wy{41UY&wTASUeEL82+r1B?Nl&hBP-gKLvTaG8v%%3DvWWnq?1CQGc;0Z4u(j1M=c?Pv1IR|Ecvcv@lOK-'
    'K@U{X!rOj0{n2rVA+lV>Zlip?by30Lqd3ucd+qD(V$po4Tv=*PgY!7%m^X|leVxMucK#&Cb3)LO(NJ<I8587E?-'
    '^pX!ELu8i*AWpG0#s>DBZQqefJPEC16DzRC8or8n0X0+II1oJsNlmJX{4dFS7k6U#9T5Rl?3NOHwXjXW*R;Gy*6A2k!-'
    'QeATV+M<L@R7MuAY2$;z<yqZ{>bcM~yd;5|f8<R_!)P^^x8{-'
    'jz=E6l&1*^hM(d<W;K0+}dZSlwSF)d`T{HEpWOFL^*W69lG>z@QBZ#suisrtdG>n(Lppi;?QAEd*<h!_2_cUp^hg^(H162Q@u<q%'
    'e6gFM<kpZC<&RX!b8B;tF(wrb3pU>4X6`z>Hwcame3$W<~Q(LjUke_5SgbK+Jry6@30xgOFRuLAW0t|+Zco~WhXulXxsT4{jjx$Z'
    'cg82NzVt<w&VFXbN)mSTq;X-'
    'lRjCX_IE;AG1>?5l$U_9DtMDNZ})Uz<U=yfttTIM^U=Dn4Cg3#BGCfyKO1R*(`gXTMbPC;gDC8^Z!z(#vIMdH>kY9tK)Ye5yc^9w'
    'Nh^#@v0MRJsRR>EmjGR21cgs=(1({?{}mPd6_y<AXqr*pHl>3Z`u@(om@dt8h_y8bc-VH8CJqnu&&%WU*T-'
    'jVgeEe20)&MkjjOwTcJzI4oAT`F$^yO(?H>s!ORE;)h|T88GzuhgW(|Pm0{q-'
    '&A6wtMfoesEZoWAQ)`u}!$k4=3!F=Yg)AH=~>B*b_`xpK`IsMD&n>VL_m%mQFdvp5gZ+lqclrh^BF~#nlj+=xXSW7m1!gz9PX=Cx'
    'iY_aq&Y|KXCU%5flro|>tCS}IMb`sVge_-kI2bF9)Q%Y6ptPF?_hj(L{V^4+dxL;f)yQ7k#F_Jr?(Nrrj8d8fy;E!+xk8QH0$rgG'
    'oqwR=^EbcK4VjM<QagdSaxpB5Ni8iezwNr@_^piN#y@OK~;?e%NVAL}s5F%CqZo^}nGT1FfQ$QIY&d8pf&Q_{;_2w9@)%^o33N-'
    'T_=0!0t2j?Q%a4O`2bcB=}OJ}*9I>n1oYiVnJFN9q{JtMM(%V}Iu#KL3~7!#PVg*OuL&-'
    'LYF@n7Kq16j;83C=+{qGjW8cmXz@k4nU3O`njDPFs6Qhm+QV@LJ=Ne0`9j;LW^bw7H!d6i5!oUlN}zGiy3gm|TdPq-qFp9kPT{QA'
    'A-T-'
    '}I4yN~%eTNSHms6QK(&p_Cu8&sWol(E<HRjF)ELP9;ibx~;MlPj0M4v#%(|<!*S%92IX+c+aK781U1u{HPxM>mdyu7ZoXX;v8%oz'
    'U5NQw7BPGmxd2xBRm*nbzNuuA7tPGtvxIX$#dVJatGr4jkp(es)2brG}gsUL6io5eV+snkCn7CBcyK3%M2YXeL-Ym_DjgIpKFybS'
    'zqvAMHPCHZ)AeXdb0j%m%he^%;?rby6<7QAy?XtF4<Ac73lPAGqNCSk>$Xqq01?VlTEtW!$sEI#NL+RnClM`{Cd){ApVpz<7D`77'
    '7YRmI_f`gV6J8hIB^*(sRiu<-5L^3n8nUHTp{N086E3Eaic49YHnsi+-atSDWtfbtS9~A6lpoj5=lABQdDhNvZH%BhWpK|-'
    'M<;i9*|pZ__b+3P`$)h@n<|0&t~0vjnSKDybB)@(|b}9wdMmk;#KdNf6RY_$k&I;mR*GAjNBq(I|wa=hib%9&miE6h>ar&hIO6JC'
    'eQgNr@C<gfC$^&M)C!h+md-$TgigGS7~wu9~?YkMOSe9r?-'
    't{*_n;0{zZ>!kYaj!(u|&Za?=BzwMNAemCAgykaPWdbaMk&OcNUv0SS&^e&Cl~7CDc0gCdxBlprMo0mV}eYNo3F8rhE()6Af#<e|'
    'wdCZAx&mQhbdlPM2-'
    'dEj@kIUH;s4pJTXkg!j9M8&kO<6SbhrQ^0fqogi>I_vQ3dTeACi!`kjUW+k&_1RWSa<!g~J2fM1=Y^cO5_G|9V$k|}9fpcC>z;I%'
    'KG&=nKONJe=4XU7pVea%CFqw~m9Uvns*Y~){9Bh95r|5^Le{s1It1qc_(m!Q9!+`VKdH&~-UD7SF-'
    '{36MLEwbjy0!d#>wKD`N{(mfttzn0G^F`CBX$^<XJ}(sdw4T=}9Fr@)H$^#bd`MR5tHm(=U5<b%Jw_-EC&Y&?^`I<CnEfqc5a9JZ'
    '~dVlu+UO7jRSHe?1-~+X#AFt9exgM&GQvyOT{fO34A-;cVJyUXHX}zi}D$N~+vTJF0JA{-'
    'ZoM)BWZ5M<t{ZoM&oUw9|uyF@CnBv!nB)v!7o6czk+tUb&00N5L+R3Ok2~7tY-F*}0RaQBE3xps-'
    'L1gKN<&hK(90oN2{DF5gSP%K{uC%YNpPNSPd6fz(ecl8kg7G}lA!NRRqXp9I`5>E6Sz8r=IJsK@kL+i$7nwE|-'
    '_@A@I(6*Hy`)AMGZDjhnFs!m-@g>ocw<tW4$3QpU%Q%%Tc-'
    'El)ww{u@N`NbUW2!(nLDQ+8?Q&l>c+y4~setJ4XVgwk0ON43U1cr?{H%c=PIe{Sp>#tmR4rOt*nvB-yQwtZPoK&r+J;E#Sq0zn1x'
    '9d)Ed2XMRybhYW*+Fhw%OQH1BU}mBDaoq=ucRUrV2}p)(R{7#*Ah&)u4=4)8AI4B-}L&swpQrxDv}{vfTw1-'
    'Qo!Z_kU<Q`+E`6VGaALE(so0z<AgSD6luiGt4KQzgcP+%Z4FPqF0H{IddypuOwNY01c9!J7c>{f&ao!S4?`xT*b8GS$GS_aft9R*'
    'S)UqtV=^aF&UGV}!-'
    'lS!#Nk|TiQ_sV^B{HRZb9GdnFC>8?lR8AFl{pFR@+Gq_LL=9L^SXE*YVOtO9db2OvC&nhv;+6_PD~(%P(ZCB0;P2Sh(@+G!kwg3{'
    '%~<m64X6c%p(gM~>@UBNO)<v{K#*tp>44Ap2mt&CP5Cxk3+WY<m9VB;==yI`}g4L(@`g?Qv4lezv+AJDn7|pY`sEEO)=6)$S=Rc8'
    '|2y9i-KnWCn{>q}`#Nc&cX3C=<7xD{@WOZ!e<TPGcBb1*(&6{AxX0GJdexL#eil%e?c7wy21x*Ijm>41Z<$kFA?g(-'
    'M1x#7Q+Ia)5oDEOxWSBw`m~=Mm<UrnB1iwf9+D-@D4^qd>PzkQ;=Jv3bOcV{_MBBwKPgyl}adRO<>uVixG*n)b4Ms-vv<Q!yMai<'
    'D%i1W%=CPN?htq)-'
    '#!AmEqIPKHp~&dm<@5g&HuBeswsu`o|0CIDv=NSt)uHP$UEomrXwsfv?T&7|rjhA1JKr4mpEbv99aBSB|Lmm4!X#9Vz)KoDX<k=E'
    '*lM=+2pLZ!9m3mOiK`0?7J18NA%!U$4J_{g8KJ`Mj#M+K3-8IwMQHRU?Rv%2^pF}g2QRE%HpLzFX`-}B-'
    'Go6!I5j8N2`PNfes_7kgjEz*NP;WTrar^||PHKIaIH|!Sc34^A4J>uy(%@sgKGKSQnI)(44l)Y4L#~^Gx2Qmb#hlu_U_#qnn6Db$'
    'r&@wmhcmL)3;|@X;-{GCMfZ+rFN9%02D8M7mN$`;4XF1Xck;M;u6d}n+)fA$7te`&{kINC)*-'
    'pY02{r|r1z;s3PHtr})o4bxxXLoDgPqR1R@1s8Or+5j^&gBfgc<I@e0@EcuZFhU&)>g$cXo7sUeh28tb{E=7T-'
    'seqX3w`s3eWe)T|(YT*sJyERQHZ;Tld&3rG%E`aXR{G|f}&7WiHe$JwRQYQvWuV8e7g#8*<(7;+~;l|i=xn0on`K(30jLb*pKL}n'
    'VzK6t^hBZ7eBEw$7Ft0aEdzoQz$D5ohhe(_Q+q4~d{cpr3g)VD#8b`m5EY2pq@oS~dB2qjO#N+;+#*kq}gH;8pQ?r8JWh~Z~g#uP'
    '$0^DZW|%ob)ix9!8OBUG@w2@KWLCxrQSBh<0SBaKnD|F#H%$5zyDLcuAmc}><`3XnUMr~XP09sJt^7*hTYO94b_2ax;~x;(7TsJN'
    '1CXh>??NXCfxUwW}#-UW{OyJmj+Si{2`EGKf4S;DgEwBQ!-95V?+M%N{zsZ%$-'
    'Q}FBHh&BS)y6x#~QaO?YGh#WJ{0q2#|Dr&9g*<0>Ov|jqAMsy>B#t;(n3t7=)1~*hiGD!nnX?CFW(yABFc@Z?f9{lKdCJ$M&DdEz'
    'dl)0Rb_=VLTSPjmqpO+{+W4><!?iI(OkjXPobEDw`wz;ar%Z{%hGxb(GvcthxlyKMX??2HZV&20aH$1dUIL39cD%$PGqOLaM8nSy'
    '0*zzAmHdq6$UHHOlj2c5=oZOf`k~8pcSsv9gkD2CP);h}#ve|%lg(T`PND2YE}ULexKup7(vKX}b^>~y<S_^YUhh`aqzi`#Z#H*A'
    '$!ITjHy>c}0OFMgdhT8o&|i8~*^Dfrx5IQ;ttYp$<qp4%o*ytCM?a|0Hi4{jbQ$F&e*XOUdq@H57VhuklOH>YoGk)XvZ3zn&I>mn'
    'o~tb0g=185(!XO&b>6wYu3wv;#I{{-&Daa(`ZKPNv`FUefLsy;oea3qgh@KY=d=kBzV*UU)c0>b!D#}f&*9<ne-'
    '2ghON>7yDcT1Cl9B1VO1Yycc4$wKk(e^%b3oM?Gk|F#`V^a2a}6hPJ`?(le6*%2SAMR6a&o2cnIANKirc^TBsI~n#KWYH5~ynq{;'
    'jeL@bnx8q$su1R}rSzU(uup;H@k#WY_gW&O~k>h;m1A{&~S<lny3PC2b9E#9|XoNL!*z$wb@bdnvEjY$%Ccyn+KFHJS~`d`4R|H<'
    '?YL_1K)tB>Y0K{4t5zXdw<5!RGeM`~Q7lRI{lagRJpCi3bo2<rjhA>%+e#&B20ms4iJNq^Pag<x-'
    'RBw?`h5Dm0adRDlr@dS)yP&x@GRH3zV3k7?+|vV8_vbT^dfg}6sNfh^2Wx6qHYp%3{P2z5@r;G+}Cki~+)9^>wf`In6_iG3FdnGY'
    'ZZ8*Ltq$zopE+F~j4vPpM@C?}hZkB!1&9A>YQ;3l$PI<7h`1@h|*WF`5U!xS}WkPrTN$w1f{z5MJ307_~m=*!^yrM^yOrtSqt^cY'
    '!0Rpp{g244_j@>Jm^Uz`Z`WV{y<Wvm}0IACqTQlaM3vIo4IsPZBpEG_0luJa@|R`sT=L9;9jmwQ9pgB1u`^(RTxKPpdrpr*Zp;NV'
    '<r=E&Xn8AF!TWV<X;rSDWCf0<)rGP{L&g<AuZs+7+(NSB|3|0rV8)fybrDqz=v!T7<sMoB<aDkTzWs>5_jG@eP%*(-'
    '^Grbylz`6R`^1Pb$fw%H=vI6QRmd~nJBlv|%B(DNN7oQP<yx5a{i5PT9ID|htLu+?#n3j1;=azlmwRenx)N_Z;`$ip}!u!Uj6NJc'
    'SAY2Z7)eVzsB`HH}C9GK3LaLnI+YvjY;$MtBjeP(`;9<iCsQ3X^23j?{BZJyw9%tZMax43?cR)Z6n{p7<0Tn+oj9a>G&37%&@Eb?'
    'A)&2i|-6oTra4C)%TB|>TRdwQ{CXQDbMSC%SP7c>Zb?LI=X7cLZh^?Wv+T-'
    '}>aK{`?1t7>2uqI@bp{zu&yBnd1^F(QW%gzDSPNP}YpT4hI&F;hZpGrw3)62J_v-wYX_DN0m=RhN2?DI(Hu^36epHY@6V*c{Btre'
    '5^`Okkr50t+*7BVlk#1t51f2Ey)i1_uoq%9ks4fM%#%vf%T<A<38!H_`1Hg{3HSpuGJyj{_DP#Y0=m)8K$1E(mj%AgG7Yo_a<A>2'
    'dVQ`Rl(qGoc`Zn9*k&2@R~>wIpVs`onWyEq|EJ4w-'
    'OTx8JsEJ7QShL5|ZtL{Y;o8)mw1*rX?i`H)qb1hd5k9*E~&rjPz}lcF1e%trnlH*bETF)}m6oOyD>6`+L&oHAyC&x?1*ub-'
    '`#ch6u8G}lfjDww-wxsK+~o}HHIF&Fef^KMwbAiH}{vx6LqMmPvfrdeu$n@zWFcF;1{t$YMf;22%^h?&Y_y$j8K^pxdpsh^wn)Wm'
    'j+mASMoleAQ3C9iXe_PL$_s|W7tDD!_L55o(V$M6d`{4l{9G2EefB@u&1VDK1oijps19(^zh_ij7EJ}!(dw46?P4<(rj@R-'
    ')i@eY%%?ZMp>&8>%QGQ|fYPnu1ZNSjuZHRu|Ie#mk6SQyq}s-MiKjA75^nFhfoKauYE358VJzj-BI5sG8Kc)8#+?s{a-#L1W&-'
    'DMNF4Qe%O-'
    '7N9R8i^jTX5oF}Bd{x=_y^7ev%zU^PICOQnvbp!rjcgArpw8L2u_abgJk;hu}_duFOBfIm;qF8VY<USfuWB)lt!xudGiB>A}luB^'
    '$uo}jF{=ZscAM^;4|2e|BceNk+&$GoR?ci?9d@`U5wbiX7IeaMI$j;ZHz3O8j*h6NtFhV-'
    'C*3+W;$B{1xjtv%|ta@49z2$W5e3DUi9+Z$gFxm#Cf9ZKMjlDe{<NVWnUW6mChp%P}P+8n(nwD6BnE%9iYB)vKTk$C*3KwrmQc6$'
    '~4<~+x+S}<0?=6#1J1iV7R}V79dm0#@g(+%jE!=TQHpH+PnmY0n6he0UDg4t%?E_4u)5xPMqS%TtP1Jjoo8RA1@|%P{?G4;B%;J^'
    '_3pr<`jHg^|bM3$>AP~2J^belJqz>Y@wY;wkm~RNsAVO;R+u!?>SxC`#V?#FYW)qxBOTwCU9mvT6&lMT!olZj}@*SC15F!r?o9qI'
    '!1r>Nr#78xLb&{XZMQisvVj}1$#4}d#1rprnMwInNL3vzH~A?PU6n8yMz)rY^8tbx*_gFF!oW@&!2J5G`7g7TReu3$zw4M5!WK-'
    'E0<_(Ez1@YN{nWkNpXH}<ieYyU(DX7tjp$;{vTI?V%h'
    , 39478, 218056, '7ce92270e5a203b4bea00451997712ba5255ba3552728721d6457486157d57e3')
_SAMPLED_V5_FINITE_PAIR_SOURCE_DATA['sdk860'] = (
    'c-rlKYj@k$wcvOC3KUsuLOK*ByJ?!r;a#K1a-'
    ')f2`ATxyjH*E(5|VID0xUpUR#VS!pZz#*oCAQ8+}jW1b#E#HIIn&7*=N6Z9LFa`78U6#|ByvL?;jt%+CM)!c@y1KX|amZViu)0H&'
    'u3%uCl0Jl~sC^Mde+QRnc`>MQJoGi)od?%W7SWx3>1@^Jtb$=V_JAqPr?zrB`!kuwE_Kt2(;M=4Ejct;(o`L6=qj0lQ6Ct8B4cji'
    'dA1ypG`i>U6Q3XS1zzIxW}5DlcwEQBlHdqU(H~)%P`gAN_q@uF{C+P{TB@%8%pdZB<UQx{k`LI;)`Xyew*%;Rl%Q>NeXdtNbP}(m'
    '9M#&SB(PG`-E|Ggxc6UPf2<F!SqlJ*SyuQTA~;&!_oHPG@_T)zhq)0bI70Rf$uH(%CG>QPTPRJ_0bLc_BxK-mmg%b-'
    'R59YnVm4aUG@8s)Sh<+1*wR)1_G=q^oQRaH9o}qc>R&bFLye6abpLPm5?>s4<}1bO{Z%W@)x4i<ePaUFEAPt?sv1Ri>IPpj+tw@9'
    'VtEY6KY$1t5TF|9zd#^XnY?dY@HAHs7kJ<uZc_l+d6Ca75Qtxc~sd&MeB=n&(ol^3{3;eH~{op>(#$X(50D2l%pDPjMMA67(VW0#'
    '=M$krx0n81o;{8kQK<)7uQYt#CI1&^K8HqZ3AM-In!A_m0SMo#ylH>$G0IjDG!fl`k?tuB6UjO0)XcUn7Dx_Y07l;WR!7<UCH-'
    '1q@ZeGS=AZYL!lJ5u6GgW&oY(N?^rRcAF#m1KOw63K1l&svKr{l>zE!Td?Ql9j?(B2QfaY$I;oUT#7ACmoS-hC6El(@GLFvpG7z8'
    'w3^Xk)>Ss%LWG+_kI;RUEoh$sa7zGXjt7X&+H|!Rc*gU@u@Rv6`k+l=McD{&0e+@+wo~VD7}IJL)ysT7AHn(gxPtLUh}>nx=X+k>'
    'z?Q(7M3||wJ5TQcu;Z;bj<;z4ljM4hZIdL*7oss7N<L&;TjCj@&b|EmHmz^x`IY?nUv*i?zZdE1R{mYqJirp3!RNB~x5g&`ZSfcE'
    '#Y+8sU&}vNw*crF9s~IR5Mzt`9jp1SS7laA%UM<>d|DEKak;LhcqHlwaZNOl&l8QCqLWkc<~S{2fYZbOe0O+uo}3;0aQM@HG>KxQ'
    'jkE0!fZj6#%{CsotX}PWcph)P{o$9hql5k9WRrF;;;pUYqn{5qYV@^iboA!u!#C$Ar@yo{n*;7{19_^~HO+JD?0o<9{N3B+;P~X='
    '$BhR5CUzRXJw17SbbJV{ev1*Bi!|QzbRZ7d_H<rO-'
    '{T}kTM_(=)!CP499lpBc6SuT`q(vItpG3Q#?!A~?0(wXIyrrH^k$zRak_tg@WV#y`a|4oFP7HUzN`Q%kr>xgAh*+70yV=}A;asVz'
    'n;H4ZS7`xdtc{3AGXB-uAMIAN)F%rjO~x!zCKIfBHuqdJU>fL{_^JVRif{9`L(Zuvmf?1>jYc8_yg?v)=&F?O;mpe(CQ3&`TYy$1'
    't8<;5xsi;;#*In<kjKZ^B?f_H+a0x-W_-B58hA&4eUxz>ib{Ld5mQD>u-'
    '}k{P7!ldv@~f^x#mv{5pCTJ>PvH|Hu5~?a>?j0v1M3U%fls|NiLs==>LB{x5cu-QC@-lXvHD-'
    '<>CK_J5+MgLrulSHLPpG+Zq4e~2jKAG0g`FO%LH{{+%o$HT2ZpPs;RIXgIci^n9E*HN-$b|#^#Bi=ec-'
    '9PvdHbH$T7?XtfjD&8!#NadHt>o3wp8*{3E!;8Fasih>HmKr@-R(c6+t-'
    ')Bee?CFzx{8Rz}6N}ec(ubR)Cdc?y#!LYJik+{EA4X^<uckhcu4&H6y5Z2d~{PYi1Yg+k8p)d%nn5$ds+&ibbaG3R+|pF(6~SY~)'
    ';yOTc$Mp%cy0;pMu_W`n?N^`wZOL{9S#j~>wQnp;Nc^$IEaO3dxcT3oKtKeDRa7GRh6J+L&`pJYyP&h>hVU%<7R!5ol1l@|v5G0)'
    ')U#idTuVw%n83<|h>Zh`+?-'
    'H)la6XNYGJ{9j`yn?TZMFkcrCsrhzzOM!2glyM(kufV)=Qr@(Sgw^P2@EV;)W~2Z$)L{W*CWY|RtYX%zy|--'
    '>t$9AhGX?PU?V`>+&*J^4(Q~LMG{uPSQ6q*Ge9Rb1WaI@SQ7wLw0^7YPTKdI=ba?=yj<15g5W_*h*8CJlmN`~8g6R(0ce<lq>?aG'
    'K#$az@|l{W`WGj-`SQ$VbUqVcq=5s&NhEkL(KEQIZg7<$fYYpy)#53cASZaxdsqPduk%heg4gm-'
    '=L>sr@SS3P#?y6$(t~(42=0Sw`UcL1^N|e$|2Ga$tT~**Hok8RO(3H^qv_K=A%`{wf>N%^BA*V1NQDTRMFwXZZ*Cf56fIyX&|JVV'
    'zorwY-fQSqX%6QuM8ae*aufvbDod6nuH-{D0JLAjt`+G5{<}y&=8N@049PQE-'
    '7m#gLtvMq0kF)l$@4N@4e972OFPbM?pJ(hU>Sb08+{kii|D(F90U4@^MVdt^c#-;NgN=crR%ET5oC8_?jVk@flE)W@TQS7C-'
    'N_5jI1<(o5*%jr`NDfcw$ZpuZb#O0w&>!tjB<g#Q;AV;jfeA^wr6m<6okG@~<~1uTPGTPyV8Rzxf`SJMQZa1XX-'
    '~J)>T9*Kk^@t9XdKHITC`UFgliFA2@D9WwO;{$h-'
    '>Zc!pS$WIyk_|5n%IXXK%{PTcYkLy(e0%^wZ*Ut(d$$*t``#Udc5IGU_1S*#V#0KHZi{*MHiG9l7XDG}O+(`>zkhv<o!{f~Jr=!O'
    'r|5wp-cNMU<0en8xv+#_I+sbc2Oq)V8I4`;*Ccs^QbGIJ<!*2wYfFAJKcusu`4MaDfJIg+d4EW_mIdZ^h{$AjbPKw%stbRQeuZOr'
    'b16qa}L;a#5)Gr#LNvfOwR0}l+{YZ`LoW_BGgqno$o2Fs>=A{}BylXYU`?(j~d(mcZO;nrSro|0v>TXfRB#5|8fS4!%(vCoYgSqE'
    '$#qUK9jsOXRgJ?a6C!Zw2nq??;6Xr7sSXK81;pTx*KQIPrH>(FUT6y(f*>nZyn^$#mTbA!9jMVrYKW&55GOg+?Aw?DN!jpNrxSFL'
    '=vKI{!(xxOt#D~K%++F3}pabTiTO}^af+@bqH~p`(lQ;2DoJ2gr%T<Kj>Y7`PqIYoP0YI2tMe+zA^}Wc{ZP6Hz^>omcy5s8mVw$k'
    'BsI2ap2<$z8{=YgpJv=}qf_otho4ZML3C1<<0se~k+PVEDNc(kWeJQ5S+b6}|M2NkKP=*eKSU!r>;>5b9z<a|vfD;I;dkr^aBJRT'
    '9J^}uI;@eSZR40+><{}Oa6kqaDC`%-mYOrXBg**J;hG-tUOoQlah!@HXnR=u?b+*zkCWdkZFHIPZ1xMsVKRI+uw7QTDF0pw)nGkA'
    '9BTz%QJqGw|NQam)i=^yGE=(#7Wotnm((2}e2}1lWz_pyOZ{T#HD7(C_6Vyh+a_eMy4|oQI35Z-(!%@G<r@)M6WtA-'
    'w^<u2?IuW9@0Z<%eOjdzGyuHopfaVSmM4vm0Pm6nMev!jv{&A1~3wQJj0>eeTjj}q={L(`WkY;cbSXqTslP+`Ya2RdFO>a}$5b(4'
    'P9;HuZV&H{Jz~OAK=cyvZ<sEY3YV#N^E?qRk&j`ondCfTX9N7$FIp`JqXzFOJSxZI-s2W;i?wdG3W6MR%OeqKi-'
    '&AwbhScL>pNSt-EHTbdy!noGF3vp%-^G9XTTI*-'
    'fQMOVe)@5D*M8n$>m*Xk`FZdfD1^aa0qI#Gys5i!4Lbz5wiEkUIr@}l{Vk)|d`{2gj0Q0t<1zhbj075xh~DP~4>N2`cR5cH!Ge=T'
    'Ee`AsnvslMkj*VhjQ@BMto0tm>(%x4x5nq<ZZfZ<#%;90jpT)FM1vDsp)V-s>VIoUCw!xz0vGmRcT1i<Kw&z0fXQCef)`B!OAm>-'
    'B72gPE<juj@uvpp=`x!6aoz`P>=P+qd3PcEzw}M5AQ{C#dTL0!ENCZ4$#Ah`vxL<>@ulYkP$Pj?;+BiEk14EnUF6UY0{0(Tp{F03'
    'b^}N1^))ON<wZ8wjO*JJP9e?PMV;aJHv2fsZ(!Pk&yPp6gf{#^s+lm`A}pH7UZHx3CXZ)~v;>2AZ_fZheyu+z;1U9=&W0ezC+SsP'
    '&etHy5A8LGjg{Zp`zVY?1i$!lWZVNp--V8l%#T-'
    'aJo2KjwuaU_VRmCj?2866Bd)|aiN{`)6E6eTfqDzSziu1@c?n=g#$L$bJs5>>0CXgt4P|;fdcaRy=&9ie#t!ZgT%sp0SmosJ)nWG'
    'B#qxNI59xpt5eI<3hfA7t?{G6`EB#kOFFyH126^zE1<T{l^Y$#;(6p$_k3PQO*<21iE2IYE7!%x#i^F(RfuL2c>oGe7)B*8?c{={'
    'o>{K@63rBt+M;v;AFk2%pg8mrL23;oR>2gWtZ5JS<gZ03n9;dUJp=k(h?FDbrr9~61H+*;2_Y2hI;2vJ**JbRV_qwRpOSGu?_Kv!'
    '<X9H*79t+Ti``>GH&odXF3yiwNS)*3eoVJN$>VuGY8oxezeG+jKm}xej)ruq(>-'
    'pT7a5k^A=F~*<ChEy)4g;$(_raRB+>RDp^RE{7iUb2RaY+#=9=7y@L<j{BqIWxDEyKoLL-'
    'c9)Pu~Oq*|;zS%1G$oTG^?jxUqOVr6HJ&0n4)j70w`?%(85We+bGl^wTeHxYvzU5`kNGk1n2`JBLI<H2fV9*=07(VaY@c#ovMi@J'
    'AiALoQ3U)zrbfwFDfi6bM4io<rh$qyi2^-)Hx%2p!0swaMXF;%c%g2U>D>(A^f@FQC&)lD(&b;E(8<q?Z%?%iwH?Yy8T-'
    '<lO6#zHvn%VbvwqfihZvsOY~3@WQpP>-qvY4V)qVG8JbwMoC$J6i`uwO|Ylhfy!ryHC}7W=j;3<kV9>)-'
    '<hTbnpx6$V%qo6_&H+zeNjeNC9q+4XyeniO6u^}Uk#ZYfRkTK?&sHEk!YX`)nc(G7o?HWma~SjT(8gxiTv;Aps@4T{5}#Art1WF1'
    'lJb(6rh(9^0!y(86Y89TbWH3R#7Gkf~Q*M!i37chQfa-f+L`fmF&1BogKAT8Qs9lXs|yOIcJSw-'
    '84|bHtWGP(B{eO6v*)q*1gOs=xqV~6`4&fQ*K$z?_Uai)O-&8+-AUuUS;VD8XB&5IIwS!^J-'
    '0Fq${N&px$og<rT8U*kD=aaJa|OKAyxo^@^N$(DaP7;I^F4qV>}7_v6{J*#?c`v+@SyhdG*XSK0*)mZBZ>O0;IfYQ@@Ml4#TGv^%'
    'pSpJ2|Pjfkm54K?qx)=G|~TPd5fJhXlR=w96?iz_%g%Qc&TN9?4hTqMLp<*tP$#}yL^Pmcgpmbdix%M!qRFIe|c6he4UXDoLmz81'
    '1K$4$}GiGUW`QxoUw$v3;B2+@M2LxA!MF-`e5O@6<-'
    '>sPmQ&Ma`{BU%dAkueUuKuqb;TSJuK^D6{X(=UVtCUMSvyfxvNF_Z%nAh!(*t_x(K<@OWcPk#Rmz{(z^1+u<TtR=RzMW!|U);|@k'
    'UvAoNJ?BRK$@IeR3utZuvajw6&tD>+4(#!qwoF13K|&{Nm)>*dxI@Nr;vwh{U?5Cis84pEV#^c5oW#BX@`W*B$H46>wEPD%YWROO'
    'Ovvs$h>fxr#iFJ4NHA56){?(!GbBqym+ZZ98wxGE*jE?z<v@J0&>f`f^f`-'
    'lbUA2xGgUXF`fm=@SWEcq;sAhx*Vn)p24;_2X_)?8rw~?_h<#_x#&4forxixU_K%eHMq73~ZY$_{2?y~5^n}+*>$lQvGZAi^8-'
    'ASvGf+%vvb*iGNZD_E5)og~{%v01G;S)qta~-+>7C=WYI6^AK82}}3!-'
    'nKYE#%`(6((_vlafPCkC{_Q#qZ4UZT3g|CZd7vj9{KALX{sgo|@RF3#;3B|nuBD?Pu4B_x8N1lK7)=I{rM3wcNrM3MW@=UF-'
    'r!9enBeNhv+)x_Yfr4ym2Ycs;ekGv^TZZQGVx6yy7Q8-'
    'E(*QjVeDC;o@CChx~aaHoQ7tTba7mDKJyjXt}aa7WU5+s6bkp*;(Ur<Pr@KVh_<~2os5R;2t3;L{O9OfsX0d~!iRYqTQ5Gs!GqIu'
    'm?tPb3LLU7O_I;cLWkZHNjZ%_(OBj%LHTL%BTh{keGNjP+Z&{KV<URyq4p7#SUQ{TzM55u0WmS{q9$wWvemMAjm5=<Hb%ETwCOtj'
    'Dv?!qI@OuQ0~D;(^$blN6Vw7hHS(YF<oo<dh&;cL<<orU`rCr4uuFVn{$OI9kA9B701D9B5PU4yl`h^@DV6^7fA1|cC8NIh@~1bQ'
    'NnjYqPTirKUj_tqzbpu;v^Q&4fmYo^kNTocBqye5Bm<kx4^zvaiQ;cdwY!-lJt83Z-fS|)N?Y3i9`?+}{r4-'
    '8_gZ7+_#lHk`@K|V7&ZtP~GQ^}H=+o*{ctKn@w9CB&FMct7}$+gnrBg^3DwNEsK(Ac6Y_&|{j8cmW5e}5jTKy!8FLwqRWZv7p}P('
    'L^<Ae<tTA;Spi1XHgzl6$-HoqiGK(t3)eqm$|2WZLt2gOnN2a8C-'
    '$Bx36f%cNA|Dn})}wFh#KhnDM<9S)`sv<Uxf>7p%MPW3Zq#x&T8FUAk`^E|ws4$ByAJ#_@SZ8a#d!hZ3`Kcm5KVV}59XzkE;VUq!'
    'D`}bSym%z9`g3bngg(NiYO#%r!WOKA_{AZZjb{Q8M|0H7I<JlV+OTH!&VPONDt~}~B|K6b~&EBg~2t9jy3G+V>a*ew1WWyoa4#6<'
    '!mbJlQ4sD#rpVPl>mm#xsFAq)p?G0@m23!=(uC=#ji<wn=0$2^v{zYwaxWADtKr0*BT$`b>{;1eSK<qFyV+Bc<q=}WbEmXnYz3}w'
    'x4aE0+Mn0S0?gqvP@m<);3XE*?@UVi6)oRJIjhbp0J-'
    'REa_agWr;PTNf%=@i=Egg77{6X7M8gYy>{paf!yVmhQBHDR20#vy7;b?Kl2{|+`(vJx`F3vMz(1g;+@@($(aP~&C_d0oj(G^~H%_'
    '7vE5Y~%s4soNqO+no8qwcAs?7%C1=XLIX@aB9Rc~two(XMvH)c1j|T#vf++u+-'
    'x*zJHYl3u#b1@RTKfh!aYJ^r_~0e<Qt2x<P@cH6UDr0al>bmRJHx>^f=W{?S&gJH;hy5-83jyu{_``hP#dO>huk8Ih8-'
    '@)uUR$k@4Q1RagFrR!xSNmHVe3r*)c1U<g{_f##8jOhcdoyMuH?u`DxgfF7c48xM9_PL7OWGJ-zOqKY^Ikr#Nzfjs!ycHxM@ffK&'
    '^LV-1nM=*ZX7(Jf=B{-'
    'i_0E%C9RXFg;^;Mj@=Y?RV+)$u<79>q;yPerHvE1AP+`m*BnLC&9`YA9p^BQdNBOdHcY3S%`m*&+JNan5@ckJ7}+dPtD2~hl#BF5'
    '>za*{Y_WHoa)dLDu^+-'
    'EhxH|vHba<+ZPlr%;Se8aO{tIM7)lWFz2W)cRe{LQny*}8O_4|mUEF0qlS*%JcS5vLBZ(q`0yGje(4DS{>=J$fMDJ#(?Ev&P)baA'
    '!9qtu9j_WK-XY;(sJSJf0uzD3l_IXWw-?Xl(Q@f;>nQW?0_N>;hWk?e0F@1|vQj=gnfNz^cE1S8JcfNWl92SlAG>uuS>(!jM;T-'
    '3=QH1~JoO774Zvas`9#-OT&{JQwZC--vjeY&K@#{Ri)m768Nqp4G7kbz4@mCjaC}GDF4H`Flkk7$gUmcT)f+{Vehc5>I?Om34IUe'
    '+D@vOLz(?LH~xn5ItklMUGPjAZh*YL9#n8t&a&m2|!!0)v&@;VL}An|(*3~}E&!i7zh|0r@<1igkOXJBk}RJ%){03xsJiSYe*;-'
    '1K&p=}WyPRs|z+l`FSwU4S~M2OcKMbCWj8Z!$H7tdY;;m3>ju<QZm%$V$!e>DBi*fsaM^reMR@AW|$;I}IJU;dz62J*)`pXnczro'
    '($?L{^ViN2depV>&oSUwBB^=ANzdS&)**4u3j%b?9^m9nhk^hpgf4E%5^#PE@>>WQz(BBketX9+#C1gsJ!J5h%QI`dh)*xckCTIP'
    'CO;K~ccKa7VvDiY^d`h0m_w_YBmD<M?E`+RlX%gDK07y!=N_j;n$h_-&cH2A!aU4>|rjFh5?`BK@bz%F2ne;HtvwI>%h5`6`-'
    '~8GBB^a<e<Vcj=UFGj>k^xiCtlUpIL*$ONK0M#k8q6P2PhH^L&+_#&Me=9(?GZ_{c9>qzIw8gZ_su?ZC$@MP|7*m)^c7;&Y%aO^u'
    '4voys$K(BIkAKj(sOb)0vTUU5>5X9M`yTM)g#5cKnit~|g`dE$C;T9=DT$et%LIahWzBve`fHij@?Ytwee+`H@ISH};mz3cyzHA;'
    '{k5PEk$FVWu5H3Z>(Z!{jsn9NAH_~s|P{Vtd5Te3Js7TlF0Q3y_D~Z!3GkPT%9zXk#eV>c$Z_2ml;P@z_4`sUKpZ_59*m1}Pg*RX'
    'lVfG^$_e9DLJ(%gI<f2U@(t)zV>68X5Gi$P&`O>47GhNkf*x)p@Z`dJ$frFq|4j7TY<akqew(4B33#1Rt$*W{*4CbKbsnr!t#`?i'
    '{MHU4hw8UJ0<m}~($1dMz=!4dg0WUlaI(5Sae)V;wqw(G2$`3v66|ERftti@qKY+~>0W;qC1p1uzx?}AuBoLfXI%ru>7z+sgA{lo'
    '(A~!L>aQ4$;rJsQHJTsgLy^ciMW#QOoPgZ&cHct#fLM0NML|vHCb51nqj?8!~?x_}e7l^0YW}Dg6ImUWqCsZlq#Il_9g3aJb7*~A'
    'irZn_2-_|+vr9l)k3&qO@hZ60?(bsHD1G=J#2fYHP&4=6RO=h1mdSuHa>WFlTAdU-'
    'M;8cr|^kKFY%X%YdE*HC(6j6bH+k=~5q4Yq1cvC>OfMAxVHwCag@TCC<=Nc8Uhpb)n1m%fLs;StM9p(}vvJay|w{eN~gVE6R7Q&@'
    'zM{slP?!J?M$qnXB6V3RybR$m`Z1@X&)?{Qvn{1vgYgBTntk;Y5<6w8Z+k|tpEqn7QQera&Xd-gpO7x#Ww_-'
    's~rqC9?0X1sY)r1$e?nu51-'
    'sDKd<>?a~81EjkV0+O(a&qlNVKZkI4!aL@ITo|XXTwjXZzG^X6HCI#x?e2>;RVb@ge=!Lx18L!e_CSv_jY|X2N24l2j#WOC9H^&<'
    'Rsx5yT$Sf`zj|g>>BWE#f|1iu$Qb_q?lz0CMJ9*NE*2VHnqHiwz=?8<y6GClyYCu?U9knj`AF@K&FTmc}*eC`Sm?lhL~qJ@cDu&i'
    '`=eP&~brTV=$^Voo^FlW>tQ@YLUA(J)MH22QMY!J9*FTM7w?NP`L)@ZdZFCdK9F`xCMIOej3Tcr_YmYz&U4h$hMlU)1Ihx?`S@y2'
    'ZuST;0i=vXAC>wLdX8)tf%9y6Om?m;8PYEJqRxrovfME{kx;qeNl3X%w?^c`<ApJY8jAjBvH13YV_o7-m+2NO|tqk6tWyv-pQ~3x'
    '3UnuQD3m7=9SvGI9$&cAcPbDo|r3EJ=+6*5giCF7PUZ8hAFCQp+G`SASFnkL^&vh6U{Qw&glzbAqpH7qOcFCtuUhod!rSk$pUe{c'
    '2!wT+;k=Tr&Bq3C4<<T$cW%;5FY8|Q(gy7XFz4ErtFW6^r~wE63jfsWce!JgLQ4v%$${QKC<pg1LCObvt^<=--'
    '%jPFp8SV%e_a<%42SexPD^(1=kg#3t4JgF!36h^~KFhiF`5d18ygN!hIr&y>vRGgbzq0qV%dn<!%PO3go1B!skseDHRoS0<c%v^}'
    '3d&2YlDSCU>zX(Ypa>j9*)>+KE`kIdxqCKZuC;CP!v2CC=iT_b6GxuBQ0CTNXj`9U%j0fZ~}i!z@92r*^x**?sUyT^H&&1`e$VIm'
    'C!1+HIeJ>{v0@h$nh{+j>FzCmXyIghE3HB~{-'
    'OHw%E70ZF@U%FhEa@9ns6&u7>)BnBKmP5O$)`rgW0$C4{Pq*1hN+P^!U7{R~yHXkFUGfM%4DZ@yc<h{7sLeYOW(Or6xtjf?Bi~(+'
    'j%|s#=n}?8~QO04NB!``FoGamr=)_d!DEB<&??UAS>uCS@n8cu{p666Q4B-PK)?=r;eZ_9#=SF=um1JiIGr?(2GnhProL5m{EU-g'
    'lot<k2o-2Gp^P2IVcnqKyhG9cA@mpoNGb?7<WFOdn{+8@@{1I?aDM_IXtEht9M9u%JE(av517YfGMyGqTnGzYNTab!3h_-'
    '%}U|5rk+BW;lasZk@Ou2W01AvVU<hy$WY3OtgSH@du`13Z^p5fN%-wWzP%xW=y4rc@UZ)xHkKW$T^Ae0P(4HXBJ;Of$H|0?-'
    'VasCE{aN7;dm$$9-SCc*b2MLmP87tkXEXg4w?ajIR`#116n5JVaK9X6CCX2in?2ez0^vXO@I}b#QCqT-Lu<A2lR4;7eQYo7ulOsm'
    '8<X~yZZ`pR4btMNiZ!n9@7<JVA&R;=t*q!P{U9bJy+SzD`K?{+eC*v}@h*ob(-'
    'k6LUDVVo3(sg|&4Hq`ein=|sz5~I~<oJ85rHxy=?~n}^*g^bZ7bqWc*F52k_uqUI^}Kcr5k+E0=oEAaPka9gfEpOg4n!J>F2u&73'
    'l61?a1?b<j3pgpw$C=|uuefO8_EzR0AOaB_;EXUo8R2trCfUJw>Vw0|D6hY*cFup?h`6bLQlGnw#*Q0G=gWGU^hYHs9${Y_Vz{eQ'
    '~L3_ZE?WZF(K#}cgaiPQ=nY;0{u<rX};KDS3DV|K#76Yi?ygpVOdq#o=P&-'
    'IKY|ta)dRxbwszl&x>wtsAgZh4OBvNKNE(oK_2Cq*XI1)!&9#}H_(G1bYiccVj#nc*`CM-'
    'G)rcAjS05X3f0jaBt=w_poyGd>mxatS7tA0BUIhC2{KQBH~%u+`Aqop1USS|tg0+2IjtMuAIo>%m>u5&&Bh|DB|F4BYwNKz4r|pq'
    'Q5|R^aypCE7W%6|(#}p++(P8&3U(Gn#V{itIA!MIsXB?t$@KspX`E$$&46tEMkK6I*VeEnI6VQxGAfQk-2Nj(#{K`S@L)MT9i-'
    '56R<hxRb7KY#OC6mwuUKI~?t>OG&d5X$v6trE*nt!lL-'
    '9VlXMY{_l=6Oz^qe^jh>`z8efg;mQBmExtji^amU%)pHzh1LAPL^2Y%IcVxX`z+fN8H;n!FTEk;o#3Vd)eQGHHLGsmfVtbv~DK2$'
    'orGQxr*t<~x7-hc-A_`e|ujlRd&bZqs$W>YRw4!dG^kyPg-|2JNRM5aXgHF~I-'
    'l%pP*9N(aEl9sEZ3jT)O9s&Sh7^?v%Jh9)C85s-'
    'v?>Et~s(kdgdWH8+Fiq%f+lh1c$W2sj(3#wkM;KAl=wo9TrysM%iKzErb<2XKJ!jLvX@?`|bbvd7xcf^Z`JOes48-'
    'VLWRvV6j<bQ$%J47@Wbv|N438Hbi$fr?Vq|5rYT#cg>$+yszAT-gs`pGR8hr!yxS%JwWIeH2Qz1D0_tyKE(yjU-xQ*?He@MvVU<C'
    '0j5^j>%IQl?{~)DU=)tCfoKG<WIzJ$iMeMt`)M<LEV6@n8<=RX)d~$(&M3vAHtofz}6c!c4V+e$PXb6La>J_@%3|oR2(OCJaMVv4'
    'r>$K&0W@@7EGiO)h7wO+yXX%d~9f%klFpk27k!ll27_w=4FZ+$!Cno^RLecWLz}0ZX^nT;13Kt0*iQZC7X|H4Matg0e+3naw-nk`'
    'a*}NiuC;372x}faQ65Q*&|Y-'
    'sPm_?}Ou$!@nLLsJ<xv*B}0C*38fW)t&?}QuvgacAMfN)@YT<kgSZno*EAx{}8o_NJ^#K0GD%>MBAw}s}fU~!N!=~-'
    'gkohMgSFJY!{`HMHt&US`FIc$KAq{Rx$0~GZc-TZ6M9BclpxKh?gOMIaBbiYs+ghSq*%{aK^Ge0r+rz(^Ni%QNRruznAKPn#xb*g'
    '=F-Nt(WYbv-P$cD~Uh#qZG~$(lDcn0|h1=`r=X_X=HPB?I|}e$QRMutl9?YWyyixyn6UPUB0ABInfzMkCV2CGi*imx~k}Qm-WF6m'
    'sw5z(6MG5z0s;>+p%8fykyUmvFkM7ejBOWS|Y4Ns>o}3{i&4pstlI;X5clAH!tz9cfRxzdS9TAIyx7joGP7!Y?n(4;~<l&@M#b9R'
    ';5$nAX;P}R~Ad4_ix<d48fT96v~1pP!c?W0qnt+#E0?=Pt7wt%!6ige}{f<<EG1aV^WQb1^+Vdwa?|jW-'
    '$G3B;9u#IJE`$wbRvTV^BZkDc<k|TepSMvtTNgp_jjWSSlH76lrRb2~zM=PTMzZ#7}KPnz`r-'
    'rj)^3XFXq$>^$e%H%gZsy(*~>T1~2wTY7ra41%QRK!!`?7bTCv5*v(%f<POoen|S9b-=yH2*U_x&-'
    'owGZn^v7MG#3m46$CWDu2c$&uFwlB_g~6U}DgL50No9mB@PJ<Ky;P?l2qothDS#51g8(Bkkz}vkLWL6+3i>CcCxuc@W@noBugBe&'
    'bDlvJHRaW<O%1LqdU3Q{AF@Lc|yd%6^S$izpE#R(q-'
    'P<qBhB*hSSLf<cthSsOsoru<)`$Gn36C&oyubWDV7QHvZOcDSdkwFZ4%Q)hZ&K1^1dCuTvwRu9EOtY<tzS0XSv8KO_Mk((p3H2CV'
    'xvvxz|4fI`e&Otpr{PSZDs{F8^GUver<ZbE+K8rQ1W}a<RH)8e?<;pUb1`O`XtD!JLWuAG`;z}Jt59`=7-x>X6Lsv~>;JMQU8-'
    'X>ISUWKh`eGwt9zE!)hmIx|Zb<>2o|U_7hm<NEG##<yu`^E$_{USjdRVE>7i#e@Ynk#Ts|3@#eU+Or^|h6n!qBAfn2LeYKZ%9XKi'
    'B@)8Ff%z|8#EjMW~7A&C_H+%Tpt&Uo@cl)n`2QF%Q>{%8L7C%WVfe)pCuqs_6ej_ONif{ofvm0oCwugSmSJ<bn7#FKtk0V)%YE$+'
    'icxVZ#qFsb;lMHPuC7QIGWp6$Q&V$o*KJk&G|_gh7xv2g<*2`Hi+GX>w>R#eqAXq6AM+g}@lR7&dR~;04s`vi1ablHp|b8c5xna`'
    'hVFdWZp;{y~G*Z-'
    '%9?;stROBn1H_5sP4X5jDA<Zavi(Y{L_p!6~DMMvRg0$HbIpnGrFtgVw5XNG%d9UrXKreq`Q&|L`LB7tv{1u6Fp|*qM^MsnnW^Ab'
    'XvUTxt49jVMokL(SKEPvE~zn5IyIj7FqGe@<sZ@iTnC_*frT2<C4D?6)4?ulGPcDXZB3NNzw%L)+K%aCov^k(_IfCUSGUP28PSdB'
    '!%`N`KFrO{5WgEvbMsAbckEj-PF`SYO?s&i|1a%~9u;6t#Xb6;Fm9J4V6|1Op^Lgh2EM=LW|$HZSDAr1SSgn3NBKP7=<fmn;*~aY'
    'CSd<0>YjqOw@RNEb0r1q+7IOJBwfY9yUB@t3q#4q_}tGp7HH<Dp0vUC}#g)t)e2U0=eVLN3X<p!lt{0V+^6u77J}PdXx_o1F=L6;'
    'y9k1LJFS021lHN^QsmE>%FmF%otQ>0-ISWMfD-8mz2sMHDAa%7Mcz76EEh>|in^0dqa`iPr6~^HSOdKri;TpI-'
    '*J6?2pjXz3p0&{a*n@k@t#_vWa4B+H>fExzGYu!CoUv`EZ^oCll<`P<`WjPWigKo*iS=T4|=b)Wm2+Z=(vrMIEpZv3|K33)+H#E!'
    'v+ZFOz|ws`0k<V=z!5lP;|s@S7B)+KWGHrhGk-'
    '1XZyp8q2^jyrkC#`#)q`Qj+sRK_77Qr_ZGm|)VUp}=(347K4B%LY$_3g(!shUlXr_vzQTbw9nfn3aS_4_&9AYhgBAl%OY3G9&st8'
    'z9aM_j=$%d!NI8uBs%;j`07?K9asOg54yWtR)Wk*eE{-%N)okYVsycuH-FhB34REV8^PEzA0UCWT3j=S~LV=#HOPioenh(J{y{2Y'
    'So?)J;cP8>s1ZdLG~?HwqXbH&|8Vu=U6PZaDJbV?u8OQG<kYTO^NJht0E$(YiJPXf2q;|v+&{E(b^D>Zu0>m7=_>I$uGEd3HcT`f'
    'yTJqd=_nfLl=@3(Yjz9Xj6;m(Jfu3P?Hm4>KE;5anG!p1}Z}_9=F`I#_b?>KW@EQr2hZ-&5y2{b);*tM-'
    '7T9C}`UiBkn79(&nmK>QqKMkt<$g#S}&z#Ou}d_P24{^&qQInFEl^!`Hii`liEVs@I4Dnk>v{_4J^tWs$AYS-MJv%K^L0vX)4azk'
    'vACp8>FL{_8Tf4N9+%UY|6!ux%;L&BZRdb`~&A(ZNm!GCg}sEH|$8#yi=0&uw4=?%eB+bH5MZnw0Zop5R2aMl}mGA<|v3BhC8&`S'
    'zp!X0*DKunNB+F{{qg`JgkQijB3$9raUrZ26oM31M>??Jt!^lo%Q9Y<vx7vvL0`*5!Hsoz(gpouhU(**QS++;GYR5i%18m6g<Yw~'
    'oL}e)TWa$F^||3`!pf3t8-4$m+~jn-eex?)CbrhDPgE7tPv?8U?ZYQB-I%TyCX?PjtE-Mi;wy$`(7C%Q1>Qqpb6sOPzO*X<FD_^R'
    'Z+%NOF5$fDa(L0&WWZZJ`l^-'
    '3F#W%H7Ohb8eNiIAM=hHH`V2zMSm#^$HSkGuQ}Ozu&*`XGi4^TEnStGbvNGo5@_26t?pjKMXf93egDph3S3Q#hMDvC9W1i21u<d^'
    'X#K%>ohni>!7<OyY6hQiG&$CW7Z1n82SG8hhNT)4)%|egZ;C^<kjKZ^B=nLmKWB&IbTqa1wa5V$9lbBZMZV{m)F;Iwt7idKfJiEv'
    'iepnIWG$*PbqYT8U(E!B;$mw91Ly0m!LWNDuqL0q@k_4LX7EirlIj>9(t4?8i^{yN)3-'
    'WX@vQ~PY+QcA^cW~_Afg<B<$!QH&sGwK)>x4-'
    'pH|lNcQU8>Hhae$4BSA^DFqM!G_5d@OlDdp;lx3(Umt0zYo~HD3WhS1@h6&*R_I%Ue{d-'
    '_R=zcQFWY+JK~1vu?#+zUq#Q`2rI`^cOT$~(VAAeBWAWC?P;My4_OOlJrMV|f^x_b7*0|Fm#jcA!$L?!9ijhLKvL7*FcdX(rDoT>'
    '6qpCoix3LlP3jVPbiwVjx#kJ=p1w&}8c`!aT1=yR?~d#c#8wu&FEA(&$e+gN@fl4zv!=DHhs{0TfWLkij~(=iX~VqX<KTlEXnI#W'
    'y0DJPhAhQBXV<woKHDS%pdb73G<)(H_NCX}^afGx@#PE5P5bc~Q{C%zR7qG7otTtQ-7h}-'
    ')&?ZexvWC>9@C56VXuxK1(wzkTC?+bO^4KT3%v-cvo|q6H^NV(CBfF=KOW~=b$*W^oBxK#G<=2HP=1;d-'
    '^1YF?J?M+aof5uiIu%JBNzbjr>E6j;l7lu`l%@l+<H<c+&*r_9s!ks*<UENndPud+Nn7XlZ58Zvtq@w@9rf{pM+E}UC?<XWF8F_K'
    'SVm9p)-JCx;R^vu_IL(Mh$P5{3-'
    'V^(LU%T=_H!Dc)sUx?t4;yJx}Cl(;%&YE>qXYoFMYFr0v?WM|kzA>?03!>wAz(UyC~*@i4M8Bk*lET%*zrn45$X(X<;cWEd%>Oab'
    '8AYRZl<oE}jQmM@b6{8L6w1PQh(Ww|zE^1RnVA4jaV$$LGqydQ|uYNqw0T8l|uEZ3`=GKJVh{02rkiuE#)kt(ePyhO!GQa{8sKxm'
    'Q1L=n%<_fOB?y~X@j2R|mKhyVHR@a#M}JNV)7r+p6vi|nx}r-'
    'g4|e?)5gykRzjw&{$b=ily%|9t&oci5IQ?P=B<?9jLTSZDMMz^5_%+tZWRN5_YOasR6>i}7r|Sk{A<UPn=lxzFEc_qE7|UT1J*u<'
    'UO=8N?&hQtrh-'
    'U{fO1MOw7;wlGO!VDEe%JfuHe6t8NV^P|i$M73P5wsS1u3jd2She%lj3^7pa=7ubDRJZvmpUtdF3oPwb>D@@**^?*{{3^4F19MA-'
    'e26MXi4NcYa(;N`=5f=#nYDzm1N8=X?KZ7%=lRvRzD-'
    '~J;hO<WWH`RfKF;zR_;jFgL^kH{8mYcGO}Uu~M>O!53Pc*mSw>z~IHEfWITCM+67{|MRC#gwkQv`$H;~Aj*;AscjjHx~KOcr-'
    'T;oi~2X<|XF9op90w-'
    'Eu#M8T3d^t2o2s}tanSrgeLU*$^Gg5dGPS(O^I^s<e4ogL})$e#t++*V~+1UroJd3@vgZ%N2ZE%qjmhP4+n=Qualk4TxJv%6`fqy'
    'cVfmgqdu;O!z_rASfB0U?Q-uQBy!)UdepROM*Qez<rIy-rHdT{7cpf)NbW}@>lUdSFV0~bpV62*VpD8K`GHXb3yteKjfgjXW6H0a'
    's+A=QDVR<4H&9P84O=e)<(m^!!bXL!99SsZ+;@npgDuZLGsr`N0*90(nx9N$xxM4TQn61itaL+C-'
    'Nt4v6B<SyAT1I+`o&u}sWSpY^9{v9w8SRxH@$ptrXqXX#aMGP(2rXw&8pDO$jueX{@7Ok)HN(L7A+lvqEvmhqaT%zXU(Fx1t-'
    'oJ=WGnoQ9ovzjZIFa&hp3QEuYMXADdI}P3J&q1R&_Lw7&8i$-N7l<3aYvQWA4xB=Tptcuv(w8nmW-'
    'Z7IVLvcERUE4DWhDm^HqjEPDBTd&Z_cm4B(BjkE<#bQ=$^dHRtf2p|3Mld_pm9mZ7XnxgRJEG>I+RD?>B~u&$R`H5iT=A|4h4Fs7'
    '_#T?_^HcM)SYPFV{I2=9%|Dr-E4-'
    '5Z*08g}nbi%b`RSuBAkEoRijTp>d8XU1l$qTfY!ml!h<`Plh;3lR=d%y}r(NLFr93nQqEI)Vnnev}N2JBe;ux;whbC|7|@lLyCYf'
    'wktbiaMpgm*v^%_*lqygN2O8P9APc3Uv=8=WlnJ2&9D-I;jkYqwr;{!a49-'
    '#>e*#^_BP_;oR7Bne3;LYL8o9Ajh^^i$dbDNa8<>Bh@#Habi}9p;nUqTAus^KCSq&%0A@f8Z8%c=w_#vp)&5WwOv%ldc_mvB+m3%'
    'y{f#JoPEse6=h{{88s@WLwn&UY=rX&F{5(43m)q-nAt`qJhC_5%zWgaL`MoFsZucRje;-1?uHJO;7ZIfmS+^%&*65QWpOCAko-'
    '5WnBNQ88zvjKUvPJqf!skJq({;_PnQ@+Pr2tPB5jq5>|R*>&e#~L-aWm|X6rf8Ax_#@ly@RU3Hr#bs`cs?&${w=!b2p-bI-'
    'A=IS(kjydTf9Y>9u^>oqSfBS|V=MD86H$MN?$W(1I*QHFoBf_b(qr?)S07f3USr6g!CzpRxLEnFPqW`ToXlGad8RXqom&4k!c+4X'
    'Gh%IbYf3fTUo!3DWg#aMlPef?s0GvS#n#W+VpiJ|F=KTUMM{Lo}85j_QOR{<TY{)~Sbrw4zkZWEP*)}{>_CfEc2GWu|49_qz*_1F'
    '-0n+#@_7zjgEZ>)l917@CKCJeyfG$#DUIBaC9XsUQ0r+U%V7E})~j3fk<XxUb2kc%yb$`;u+)?sljinhMo5KwmpB2|%+>D5EJt5m'
    'vb<D~maRa^Or#U^pGca<C0uD7aS=p`miz=b}ZgzLH6OL4%^u+DuEy_Mw9P9(o3lL$(urg%|c-'
    't|h+^p{Rw$ka=pY2y59bWhdPkSH)0QI!R0fiZ<<W6!DsjGl5nZor0ah2dw*XwNy2uh8xU{5gkPDtPHN(lny|H?N{4jJwT0uhV?Ku'
    'H3x-suIvXsRH0)<*!LnnwIPNEV|<RgNYds31CMktsRyca(c7&kEo}SK6}aaI5^yx8SCgStyKjoX9J{YgheYr>P!Z{lc&;sHG-'
    '`{jF1)G&R+e9CO^1aF(j3f0-f#ubm#*ep~u+i=}ndscf$BY@F{@FGAp5BL3_-'
    'VHq9tcz3|EBn!V#kAP#*<Xy|c1=fc49`leswRhb~aJP4VZ>8p!)o)#Gk0jC1{j^WAp=l$cOSNrEjCvRAiXvxegI%1uGQZyKvite_'
    ';eo4O)>cNN!Y2>>nvn!)bxYDP{SWoJJfx)-'
    'fHibzKJA=nnvPwwfF=^L^wD+SpSR|w?5fFq9)q>i4UJrYBxh&`T^xj%zq72=E&pJ96L`&|`MB<OyvyS#cg~b>?0g<CF(U3Khx~=4'
    '<D)H(p=J&BxLT**1)Ax0PR$^d@(-'
    'wIr?38?dx_|KF;j85A;N<OL7Z_O+T2FpMCF&kIxpR3Nt;DqiIXla)&~<+DCs*m)d@qpR2!y`HdsH8w;&DPs$F}ku4b?I$hLv8?)+'
    '2}A=#uODzL*-mNB&QR2Dm~)Ql>S*Lh)JqXp!4-'
    's8CdcYjLV~v|09hRV~|~?x83`63Fbq6+5^t3YKB;E&EB?0He?jGc~ZP<ysWY06u9d9jMTh2lpu{D?v7Py22}Thp$Ib1}NnUKzSAB'
    'EpAgT?^C<ib}tUy4|kj0ZDB8kcj@;)fevK>QkSJX5YjYtC%F!~_<<Q{t_HJKpdxu39bHGM%OjyaveMalQZmI?4YeeYsS%Yi<l=s}'
    '>B{LyX`;~6ahc7wRp2bLST99DKQp9)<?!$$f{{z4QSrVW14QWOVCdfrW|KAunf5X%Vzyys#ooyTK?;1^Gjqbh0BdVEF@jHw7Oc@!'
    'C;^9A%bBqaq}L}6Q6{#SquBy|S@OrS$`_b4Sj<|U2H+j>fX*?IBx$C`ZRL>!q%w4RMpQ<{rFe)eEmGqou|2TT+(?_`^}KS$Dm&AX'
    'Q5}_qXvI0B>mM}IqBZlAP36_kS(RVkGy1aOLik#+1T<nMXe8=_B4Er4IYF(JA?Svz8jY8RqWX8HqPmax8yPxrIfx?!^H3jXy@HXW'
    'ilz-AHXs3-FKyo=RE7iRVlv>Lwbas6msskUipQ4wxce+n%4u6cO_oRMU&_g^25l5_ihF^*4c~m_p_&#kov|0s-'
    'fafUy2{d(d;YwVUOx%%2_!p1Dl^0}$540?JJNvHdh8brO_^!gsHo9LC=555F4svthvRDurJjYGvC~(wxH6ilXDy>~?1_|X+;N+4!'
    '(GWTAj!>g%?p*uH=5!vOTNl>)f9o{1t1hB8qo};YF2#6tFl1-jj+F>GRafw`jk6UJP-UoG3WJ5$qoT018gO!p;#d|&#x-'
    'HIA49gGfk&>lcLySUJ70mXNx7~Y(S(gftles;_18+<Vq{F@rm1ZEX4iupWePYI@Q9o?HUuW7E3B23ZHd-'
    '6X0yl4<Fq0udn``9PA(baG3mX^3!3k69OE~^6f9@Kb*XIb@Jx?FQ-T6hv@ZmaPsPK5<j<1VvDOBm2oN)o6u^O7$pE`c9Tx;iBM5-'
    'Gvs5WJBr}P$1X6J<#M0`%%$7s;hUdF?7iIU^RplJeN9>mBKrk09_7L}p-T~o-'
    'tbr*_Ub{*@iOvyow}!rd$D|2(B_ERe%!K|si*K*En2i1T3qEg4Wl+RKQ_M&!ilH3<%WD19qV_hT!8IlL|+M~Aop&OZCsX3JU2Xz%'
    'w9Z%Pc<-{i$s%v{w$Utjx-'
    '>UexfFqnn+S8JwPb%$j&(UMf78qEeZW^vSN+*HEjgejS<d|Yapw0QmD&Zw;aI4`4dYcJNOq0f^Uyr?eG+&<a|?QTn~oEl8XAQ`V#'
    'FBC^|IDWdMu4i1Ot%AO)OX5X9?bc|V?)H~DmYg>wWBXDs$8$`{MBT1ClmUaUX9Qt&wE#TYggUYwJ%wIS~5?*ctqNHG$I_T)CN1Fm'
    '|4o8!hn$+5B=8r7(Ga|4a)ueGd(<$7VrZa|PjZMq}e3KW<apCOOJo(+Cnws@tP$88SD3BS77WjD%p+}sF1gEf&9xKLUoe{@Db<MQ'
    '`Ij$~Aj>!UdO%I+mpORmp}f8taB@RPsU>1P#>=kSLV3<NOvl%@2B!<0N5t-'
    '8W+&N;Cg9Lcna)&sux&B*Fl%^C|5CNRBh5YO^@npWgFBN4~|851+Wl#P_=UrEh{nv~XFz{{91kJ7;ypIq$yes|YFC|kWj>YH^z@^'
    '_9&Vwu#coR(URiOO@<w#}f6VyDh;P&0x>njK-'
    '>ye1V<&=)r25nqLZ^%bmoKHJp8Aawm|w<0x^jBcI{^l0t;a3dg08|EEf0Xan;4|#gSkzuPfQbRW}og0)7Wm&y%C`;N#b9LhVZJfk'
    'cY0XGq$hDeApGeCdTsCVRJ!SxtS2VrGysHZ1U^iN1>D=%Lfz9OyroM;803JG8cy`t7(BeFyKg2boGs%6BsSYdcSsFIa?QQJ8l!Ou'
    'O_PSHct!s49)t=G3Y4p^w5gD+X1TZ8-WR1NHP}(3}m+Fu(^WUG=w_QN$=5(fN5`0bFvBY)3-Lk<)A8(<?-'
    'jwny+HX%XME;$xd^bSz7SN`wdAcs9Xzq9qY<ex~Z6iuvWw*J|zl(ziOm$V|R8<cccBe1o)43qjx}u`S1|V3E4>;~h0Av|!xSwpe&'
    't29(K^h2=nKb-QI2nNBBJKnUMN>9(B}wa=u`KJzO<C4%gZ}We<mV)hG@~!1!HoRSIom0E57jw=Q8?`|>D-'
    'Y7bLS4Ns<ZM&dgH#_vK+ByWmb#Se;>;C(!8RqmPF#T6F$1lpykVPxeqa~Eip0u`PR+iVtg#@M!q1ihp0*$;8iv+vECxppcmfI*sB'
    '>iBQ6gKgRJ%#an6{RvRttQ;hwK$IY%@QuUFgU^)|mUaBi&AZBTVfDsU+-'
    'OLT3b(0=r5*K){+zzk=p$mSFc03+a;8%JlirBU???ddZ(xT+!>jG8WyW1Xehf+ayhJXx58&TIA&IQl7|6Ct`r42}U(>oL9h3F9+a'
    '_khzH;4r9DQ4FNz^Jl6ld);30;%pu*``|NtCGxVfi*cPLo}^Ok`l4Xs@84nq5K`qfCmXol`Bzof@Gbov_Kb<i2SVYSY;fT|Z*c>P'
    'VIYy4NVV3FE<Xh{5)H0Cm^PuIH}i;Y?XsoGI8kTl5m1yGxlH+69Llh`=ob}%Wm?aXjOl%{2=-'
    '?C;@g?skqztJ*5)cXiuMwMHWwJphqkryS|ANO!8qTvb!_tjh>r269yx&8wLQ#7!8arRAA}N>{c|%rOW#j8@je=eZZYHN1TEYy<;d'
    'x>y7Tm=$x*rz{g8t-2K~K6*HU<^FFTZk;i{-'
    't<;>%8Kryr!hdQ7;ViYAqbO{5_W}XdPRhIAy3%FVsfz$TY*kFVWJT=LrJTHxV3vKSm*3r+Q{R#Ociuker9Y3%ThcS^0f%beS|IX4'
    '`i>r9AB}XTKOr|FKjlSMv@QS7E8SChq%21jhxi^C?(2p<s_hnIFr$=Muy*o5dxbDd$sKa(}(b4&8;&1%lK(+!G3P=`Mq==^6o~f<'
    '<et~|}vL8YamBv2oS=~J0i4!7Uq8djXZ=pX|$Ge@Lc2Hx{w;+!1v-`<BU0lsl3|Zd8|40SzW<=XkCx7y=KJygKZIbgbl+tcA9b-'
    '^P`OR-H+zB{A<vsM@p^gIO9Pne!Sd(%w;WamHc_WlbFr@|in@oN`-'
    'nDt|SJ+%%D8hJe8SZpU_#6}Xvn+%dDsB{u?KZA072mHJcg*=;ud5IFhZ3C-Er_s^04Tfa?d{R4ZA#IODI75`U6la~EIdmV>y-'
    '$rsYv$H@s(=awdLb!`FLHUq8SctS?9RmfdwThq^5RFN;&ii@Sxx94nGgS-'
    'PhRaSXDzj8(~Ys`-DPKSNZh)eG~XBLE{`S_>MFWtR^MVj&fYW-aFk%S4Iy{GLDW`!r4M}h=H!cA<pND2((9HNA2UI$As+mW;q$yt'
    'kcYX3Ju9KbfERvQd@0w*H3ORPrf*lkq4JpSgZ}t%-'
    'DO_jqxo5J}DjaToU1x>&ny{LPJAhqjkp(8ALFwl?MbI;KxXjV$YVXo5XfF=L;Yo|H!IxTdEqQ>I{VWMOrW^BEwBh<S3KMNuw`mQ_'
    'oTqnRi6JAF_5+7LEdwX5<A9aZ`~xgX5uu8VNmcjoyHLM%`WkmzB`|P?UCB-'
    'M<vHT#lrp^C$unr*{W5w7eT{{fk2a+Cu@nKDb_llk9_oUCIC=6y8lPL$0$+6+k^*#GWe|xpiNNd+-'
    'h)J_N|#+4!5$gnnzB{AbU+lk|4sVP|67g$H?~K4D(*R0Im5ZHSa-wX)L4KHN#DFFoDSr|K*TR0(y&Z@p{b5m=p^DAf*NNkYyc>74'
    'uG1LrtKe`;>v=9n+GFw}6PO$>GNgxjcwNMZ9(OWEAT#w_HgpKTl0MV(~@db3_LyHelgWK5)zSI`|hd^Q{2-'
    'IjB?xf0#buff~m(^Evqi|zJj@KkPc_G^P?3?A?2cM-d>V;#6A^Ox>L%DwOP(O=KsogT`>s85Dn7#^T@-(A-'
    'QzrOSl7j$FhawvNw&^kR(u{7T)FbhI?TZ;NQ!w~LT1zGs=Y%aiuxSzJ#4ceBOi{+zdBg(Ke5$?-&PIr%c@d>{dQ6}jP@D4ZVg-'
    '0^`&gt3Nj$)Nwa?faNM~xc_Ldb&9!SIBfkkJxbP)?w$vYdk;LfM~Wy2F&70t?y96WT~cFPR5KTI@vjWie~y`X~4mj5tcgvP{MiJ8'
    'ZaA&}Zfu!c%*bIrBjKKD#Us%M^F`kC=jzZ-8>?^#9;l`8W+TQH$8XK1{Q;lBjnVhF0nF3A5w*a@DOsmRe+J(^?nl2Vg_dbZk1-'
    'ld4%H#j`a_#(aHBG@b;u|IUpsh@M5ycVB!h{>L{hvN)0?0Ouj1<K~Mp;W3PfG!$vyg+miY9=StG3&9aLL=&!Gpzca5Evl@mrt$`n'
    'X-'
    't3INX6<c7!jyrE2F^s^xU9X&KdE^cZ`J~%VZT^u+v+tD=ITmvkKoy_9nljEOq3dAR3W82fV_1xh$O&O)@L2n760i$9L*#ru25Q-'
    'iH+ir6{b-ffw9ekHU8#_E08p1I$c5R~$bV6Kjr#D!%S;ewAZRX~@HHBTrk2l*X6AbchvAgin#Fb4JB-Pc3*XEYq+w)UjgJ8~$f76'
    'c<avY5kadhq*&y4?r-VQYID@3q-'
    'XIbPY<_5TE>gU9M8#|B|%2%2ybgldP&NOAG^j{Apt;Q>s}*Vx}TIX3w~^)^to$bSt2&k17z<h+p!?LkSBTrI4A!No?qTc%A~Fbo!'
    'Z#?er}3chuaTOV<Z*L&Auv7gSXLd*1F>+3F5O7t>R}8Exh&($gt%tePt7tn$Dm0<D9i^6c6BJN(OZY(mGd=x4RNGIWuuMh#3#rYN'
    'UK*I_v<<ptSkQO6_*ft7bQ`+#cIsYpD`b0Xf>n2Etf@+*;Ak`R-'
    'gjC6@oleCMzBhE;<<x3^W9lEc436W(v<#Ar4j9SjutIUc6)=43EoJv53XGAb_q;o6DsiP~fGIeJn7q|wbv-'
    'Q}a0bJp7=iIO?8ep;yTLAbWt#6Utn&%kSEo)|pAyHzfWjX{dq=P08QS=*&_kN@>7{V<}2B4NYn{<vp(Coqi^XM%=|8GO*(pcFv%P'
    'AqGFF0>r-'
    'r#k+V*+oRmYvVhK!_Rl4KE@}Un>T;iJ#sV&+c;rimMy8=fyTwDNW!38s=6?HW;e5TFL$EB+ICpVn91E6vkV#wvKot);Em4dq9O_%'
    'Ot1(|FBZW=E3Cb5aB#HBGm?eMj6OAD2nG+=(KW(hg};aB8Z)BuXWezY~j?HIz9ZelgAuMn|xBx8Jo1%Z8aNs>J%6hvXMp_F7^C6o'
    'vz{_uw))xaTp)yVWO)GS(UHQ;|6}6B&V-V-'
    'W>lD{gZ#aIeC3@e0=g3{rk=LSl4A3&W?h$?Pk=gSqCYuu3|b=aAjoaB0PDOxlUJ4rxs&8Kt(xdsh=$J-'
    'E$8r<Gucw7bV561vBDzdcwq>4eL{pT~j714KZ=+DTG@vwVd9r0r~bO0(xUgi*AU?9feMLSQ!pZowZhzrhBQQLN4wOeARz<8nq95w'
    'QTGu7HKp$b%An1Qq<<Nsd(0vzuBt%XcU6feX2*Q%Z}4;7GpqM6GaKVh~v}+WCLFSd+7Qw9J*5F!__D??lA4W+`D2av$=qdl{#1;k'
    'x})dSH~hLw%IcsJCPK7&pw}@EM>U|5Ao`?*f&*M&Ae0hx)ZB;I06|(z>Y(LW%4@?iHzrp%frn}nCF*FJ^ym+5Cc>88fSt;dWzvG;'
    '=3KiZ0eL;$_<ybfVV_F$rSH6#R%0z&gN<vH1Z{?goz&%ZZ$A3%6KSLvm?PsriGz+(iIvgW%$l<mU3G1njK=sY(<yR;hMux6&HV4U'
    'l}2$IQ~nFd03>fzQ^^wYL1cJ6bz2M^)$s;^?S+*sEW?`J#4%p;3G^t%G4noA4DWZf}vr9j?gf_236pK3<8T7ioBhok^=S6P#=cfF'
    'NRiBN-'
    '1iBaN#q~xvH#krYFNVdhPQdFl%_QFF_6)Wz_~@KZ><<gHWzlKy|S40Bd8BbsleK;d;E+fn%m=_#3EbM?>mzg`1IBha*6=#uIur*v'
    'u%+-'
    '#3L^k#N+KvgsP6zf3~mElQU(D?oJ?pi|mPvyz(emO~STHj`|HqlO7^gf$|v=^C|}OfvW*q>|Vt{*pcdGy2+GVQnbU4CR6FdbH|SV'
    'BJyqoETi5-IjZ~N|lqCF(-36JbQQSEyrlKa8`C1sHqoh@4}(c0Zd9zSM^DwGh_W1CKxY=TybONOj&<G6_tXM(|bUvlDK+Z6IZn-z'
    'PJ|b^q1mRFcSpGD`}$PVDIpyZ-?bKw5oYt^Rjk9uqD4`_4d0-<SS!Xz)_>(6zYcbsboCCwX$Ji%-'
    'bdl$ULxLQLekP>5H|%z|nQoReJe$<KIohA@*#Au!>%>PL2`_%Ek@@*j&{=C-y8^@E%H@E&2}wRirxE=>yLy!Po;@_eKf?ZxVZ?-'
    '6$JMF5<Tw+WM4gq-A<PFH?(x?FswHwzvJxhvyy|*VD~Gcpe$mqI661X|ScF@Q-'
    '5JWk+i69cB5@c!JvmUotoA?Nqr?v2lsMWOf<tG02SyqaFMd#w-~TAXt;w-'
    '!Y~*Sef2D@JN|lv?0YZyogWr)sYbi#C<mFgNogMaM4bT(*9c!569enlgC>x2E^%0TOt*iD({eRSeiUBy<x!ExYbKfC(i|I=4y{sl'
    'IEY<r_-y+5nTyo&R<SVWzNCr;r_Y&aroDRV^_;FigwFyc3ltjfI{c4MWG`^d#WC%K;--'
    '4dcJOiv~{Z%8p51d_1LY}Zn1GlDeU8b2Z|a7Pn4Xyd8$73qK~R_xaspJ(AE$f1;d?bqkvQo)RL$Qlyyxpjqi-RUxfxMU4wybDM%G'
    'nC__a{g}t_1v{uoya0-'
    '~F6YsyHBxe?xQ4&BXVAed+PGv>TVX4JEl|)?hDny6}iGbz;S}$Lt>MM<UA<jUnqrJi{rK1vAq#8P^r@YdWu)L$lT0`VP4d^$G;>A'
    '5HYAcvHbl`GB!W}B2{F&_du5Y|WL`>hECM~fUGN)LK%`Nu|KT=1vS2jj(R;orWFu!-DATOH`$}gf<C8u=$xRm-5&ZzKZ9o=Oq#-'
    '*e11OQhX%Hczp3@5s}UjnThd$WuvkT+-1cp}I>Et6y^8pALV%Z%{6G)!8Lf)xEVq9~UP6COUa-j_knTI=NPg^EtL4@F`gg=vQh1-'
    'H)>4Kiov`={sc-X;fVThf_G*;P4u{_U>#&(|-!<vo;e-'
    '98lME@ZETKqtUvxh@VUmRoXT#~9D|F8h>(SIRUQv?amePl|}S``gM90$@T_MjulRP+A^4D+1~{Vo5(L_^@d`KO#3Bla=)Y)KtTD^'
    'I#6cVBn&x00gH_$ug=)+#q-'
    'Wx1OjQ!}BK4wl^hURWOC1k(PIxRJm{+&CF;q02@``s>qv{ecmJ1o&H<LjkOl)=<Au+D{omh$JL#ovb8S9xtsTvMCol({m7CUhz(>'
    'YQP)tQGga>yKf-'
    '!*Q9*GtupFWcGGWkIU4U5eBG4IS?+~{kDXuu>FXb4LlbxeCuB?GaakBN}>wLJGGWm69dbvT|j7L`^24h|gtdYkm9N!$y%jQskrrE'
    ')ZX-'
    '*1yb>VkY8dkM=ik@_`ZyT|34`=5#X6tyC1`YHUnP^M!CM&&QJ?96pK~DNmlOVU2E_q1R)y|aUh9oDnkX(aWC^bn~Y2%N!0vwm!nK'
    'yXN6oh;qG>3kBdh+_{_;9O}%d;!K_T)f2lCz4UJ7Qs!;lZjO?ctpQRaCy~;H5eyqJ~|SD@rFEu65FuwN_oCp<JpR)1X44bG-cYj8'
    'y7i-IwX=8;(+JCd@lg1!tLTY;*J$*UEXdf4={cQxZ}}Fv-'
    'T^nz+~y9)Gyhg4K`uoY@Wl$QE~LE#oTK!9nG>E8u294N%!Eauldwq%dM+reqA_%P3HO$jChxv`tux*)}$VOchTSp(#)Mo;TFpd+>'
    'd+ll*};7RYTArEA31qE4A_0S)LGpYIuvZ)@3P^`R*pCm_eVs*zP3ML+(E<VY`!q^8g}HT}B1ZR_L=bh2h=JP%Ee=***+?jdX{*`J'
    '-aTE)X|l1kg|OA?~CuDnFf$Un%c*#P2lf=F+?yNQ{B)^=jj)^6O|P8#M$^(h<b-'
    'm+Bf#bISEYe|77WI_^BK$5Okw=kQ3XiM5BQ!VD#b@!>F)t4N5ZmW$hZUe*V&bpQKntSRh4Mv}N7ii?VmVa_eJL@8Q%USa&$DvSU%'
    'Us7A8Arkm6Lo}K$>~d-'
    '7$&b}QP0nKn_<|Xbm!tkHCOp;W|imbpApKJ|Gg`Ne)o~@rQvI2g!h?Kg1JXMEDlvYn5wdcDl5O6)7x7}ghfx42i^3vQBTojLMstX'
    'JZe`L8efj{dX`P|MLHi0jRlK(Luh*BtceD`s!WVVH=j099V&-'
    'HU2i8)G3E(ttGCunNxT_0A5=8OQw+}ny=*1ZZvKwaZuV*6)>&c5J99BoTJ|sBu9};fJIw_dm=O@LLq63(^)VYSWe9?i<TqRk-'
    'lPN4lFK)(k-3{YwhC)>7_l~-xzJ%rGgo-JPgJ&oy$(8yC^v$GxY%Zkyy#`wI!<m&_03^t0ccm&a1|tNsc7I|lEC#w)o(B2W@PE9_'
    'Gd!xnLy|%zOvO2_@r4&PQ9|+G~>&y{|7Jj8om'
    , 20662, 96211, '860d25af0ab629c48bb7a2c7356c7690c09fdfe81b53777777c0a41384f1b293')


def _current_v5_pair_select_completed_fixture(monkeypatch):
    """Select current captured source for authored frames, not actual history."""
    original = _sampled_source_held_v5_finite_pair_fixture
    def selected(setup, patch, pair):
        return original(setup, patch, '7ce-860' if pair == '86c8-4df' else pair)
    monkeypatch.setitem(globals(), '_sampled_source_held_v5_finite_pair_fixture', selected)


def test_current_v5_pair_captured_protocol_preserves_V5_emitters():
    import ast
    old = ast.parse(_sampled_v5_finite_pair_source_data('cli86c8'))
    current = ast.parse(_sampled_v5_finite_pair_source_data('cli7ce'))
    functions = lambda tree: {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}
    assert ast.dump(functions(old)['_source_custody_witness'], include_attributes=False) == ast.dump(
        functions(current)['_source_custody_witness'], include_attributes=False)
    old_sdk = ast.parse(_sampled_v5_finite_pair_source_data('sdk4df'))
    current_sdk = ast.parse(_sampled_v5_finite_pair_source_data('sdk860'))
    methods = lambda tree: {n.name: n for cls in tree.body if isinstance(cls, ast.ClassDef)
        and cls.name == 'ValidationResourceReservation' for n in cls.body if isinstance(n, ast.FunctionDef)}
    before, after = methods(old_sdk), methods(current_sdk)
    for prior, renamed in [('__exit__', '_exit_observed_resources'), ('attach_child', '_attach_child_observed')]:
        after[renamed].name = prior
        assert ast.dump(before[prior], include_attributes=False) == ast.dump(after[renamed], include_attributes=False)
    # These emitter differences are guarded solely by the V6-only non-None
    # startup profile. Removing that unreachable V5 branch restores each body.
    for name in ('to_dict', 'seal_results', 'finalize'):
        method = after[name]
        extra = [n for n in method.body if isinstance(n, ast.If) and ast.unparse(n.test) ==
                 'self._startup_original_profile is not None']
        assert len(extra) == 1 and not extra[0].orelse
        method.body.remove(extra[0])
        assert ast.dump(before[name], include_attributes=False) == ast.dump(method, include_attributes=False)
    assert _sampled_sha(_sampled_v5_finite_pair_source_data('cli7ce')) == '7ce92270e5a203b4bea00451997712ba5255ba3552728721d6457486157d57e3'
    assert _sampled_sha(_sampled_v5_finite_pair_source_data('sdk860')) == '860d25af0ab629c48bb7a2c7356c7690c09fdfe81b53777777c0a41384f1b293'


@pytest.mark.parametrize('route', ['sampled', 'manual', 'watchdog', 'ledger', 'private-ledger'])
def test_current_v5_pair_reuses_complete_readiness_closeout_disposition_assertions(setup, monkeypatch, route):
    if route == 'sampled':
        test_sampled_source_held_v5_finite_pairs_readiness_closeout_and_disposition(setup, monkeypatch, '7ce-860')
    elif route == 'manual':
        test_manual_snapshot_explicit_readiness_and_closeout_preserve_unmodified_unit_frames(setup, monkeypatch, '7ce-860')
    elif route == 'watchdog':
        test_completed_watchdog_explicit_compact_closeout_preserves_original_failure(
            setup, monkeypatch, '7ce-860', '7ce-860')
    else:
        _current_v5_pair_select_completed_fixture(monkeypatch)
        if route == 'ledger':
            test_completed_ledger_explicit_closeout_preserves_failed_owner_and_all_original_files(setup, monkeypatch)
        else:
            test_private_completed_ledger_compact_closeout_and_record_only_disposition(setup, monkeypatch)


@pytest.mark.parametrize('damage', ['cross-sdk', 'unknown-cli', 'V6-schema', 'V6-field', 'Source-open', 'UNKNOWN-parent'])
def test_current_v5_pair_rejects_crossed_or_unqualified_frames_before_current_owner(setup, monkeypatch, damage):
    case = _sampled_source_held_v5_finite_pair_fixture(setup, monkeypatch, '7ce-860')
    if damage == 'cross-sdk':
        _sampled_v5_rebind_unit_pair_data(case, _sampled_v5_finite_pair_source_data('cli7ce'),
            _sampled_sha(_sampled_v5_finite_pair_source_data('sdk4df')))
    elif damage == 'unknown-cli':
        _sampled_v5_rebind_unit_pair_data(case, _sampled_v5_finite_pair_source_data('cli7ce') + b'\n# unreviewed source\n',
            _sampled_sha(_sampled_v5_finite_pair_source_data('sdk860')))
    elif damage == 'V6-schema': case['request']['schema'] = 'owned-validation-request/v6'
    elif damage == 'V6-field': case['request']['startup_clock_profile'] = {'schema': 'unqualified'}
    elif damage == 'Source-open': case['parent']['source_closed'] = False
    else: case['parent']['schema'] = 'parent-source-closeout@2'
    _sampled_seal(case)
    before = case['ledger'].read_bytes()
    monkeypatch.setattr(recovery, '_sampled_open_scheduler', lambda *args: pytest.fail('bad tuple reached current scheduler'))
    with pytest.raises((ValueError, recovery.resources.DaemonResourceError)):
        _sampled_inspect(case)
    assert case['ledger'].read_bytes() == before


@pytest.mark.parametrize('damage', ['owner-sdk', 'subject-sdk', 'subject-producer'])
def test_current_v5_private_ledger_disposition_rejects_mixed_source_summaries(setup, monkeypatch, damage):
    _current_v5_pair_select_completed_fixture(monkeypatch)
    case = _private_completed_ledger_unit_case(setup, monkeypatch)
    previous = case['args']['expected_record_sha256']
    _private_completed_ledger_call(case, 'reconcile')
    data = json.loads(case['ledger'].read_bytes()); row = data['reservations'][case['args']['reservation_id']]
    proof = row['explicit_reconciliation']['sampled_custody_proof']
    key = {'owner-sdk': 'owner_sdk_sha256', 'subject-sdk': 'private_subject_sdk_sha256',
           'subject-producer': 'private_subject_producer_sha256'}[damage]
    proof[key] = '86c8c151e559e4f4e665c475348e3a81665f008ba69298b3829d474b4873035f' if damage == 'subject-producer' else '4df3f7f2c6d2952550dd78153b579f4e928e9f119e697bded8a7dc001021f8d2'
    case['ledger'].write_text(json.dumps(data)); before = case['ledger'].read_bytes()
    with pytest.raises(recovery.resources.DaemonResourceError):
        _private_completed_ledger_disposition(case, previous, row)
    assert case['ledger'].read_bytes() == before


# Explicit existing-ledger-cap binding: fictional private storage only.  These
# controls never acquire a native lease or infer release authority for host rows.
from contextlib import contextmanager as _ledger_limit_contextmanager
import copy as _ledger_limit_copy
import tempfile as _ledger_limit_tempfile
import unittest as _ledger_limit_unittest
from unittest.mock import patch as _ledger_limit_patch


class TestExplicitExistingLedgerLimit(_ledger_limit_unittest.TestCase):
    root_cause_observations = []

    @_ledger_limit_contextmanager
    def _fictional_case(self, limit):
        with _ledger_limit_tempfile.TemporaryDirectory(prefix='fictional-retained-cap-') as folder:
            root = Path(folder) / 'owned'
            root.mkdir()
            attempt = root / 'failed'
            attempt.mkdir()
            artifact = attempt / 'failure.json'
            artifact.write_bytes(b'{"fictional_failure":true}\n')
            ledger = root / 'ledger.json'
            selected_id, foreign_id = 'a' * 32, 'b' * 32
            row = dict(reservation_id=selected_id, status='retained', owner_pid=99999999,
                storage_bytes=4096, memory_mb=1, cpu_slots=1, child_process_slots=1,
                scheduler_lane='hammer_lean', workload='canonical_trainer', created_at=1.0,
                attempt_directory=recovery.resources._root_identity(attempt), child=None,
                prior_children=[], external_charges={}, last_usage={'fictional': True},
                artifacts_durable_asserted=False, retention_reason='context_failed')
            foreign = dict(reservation_id=foreign_id, status='retained', owner_pid=99999998,
                storage_bytes=2000, child_process_slots=1,
                external_charges={'fictional_foreign_charge': 333}, opaque_history=['preserve', 7])
            before = dict(schema=recovery.resources.SCHEMA,
                roots=[recovery.resources._root_identity(root)], limit_bytes=limit,
                reservations={selected_id: row, foreign_id: foreign})
            ledger.write_text(json.dumps(before, sort_keys=True) + '\n')
            args = dict(roots=[root], reservation_id=selected_id,
                expected_record_sha256=recovery._digest(row), attempt_directory=attempt,
                expected_artifacts=recovery._durable_inventory(attempt), artifacts_durable=True,
                capacity_policy='administrative_closeout')
            actual_process = recovery.resources._process
            def fictional_stopped(pid):
                return None if pid == row['owner_pid'] else actual_process(pid)
            def no_admission(*unused, **unused_kw):
                raise AssertionError('fictional reconciliation must never enter native admission')
            with _ledger_limit_patch.object(recovery.resources, '_process', fictional_stopped), \
                    _ledger_limit_patch.object(recovery.resources.DaemonResourceReservation, '__enter__', no_admission):
                yield dict(root=root, ledger=ledger, args=args, before=before,
                    row=row, foreign_id=foreign_id, artifact=artifact,
                    artifact_bytes=artifact.read_bytes())

    def _success(self, case, expected):
        args = dict(case['args'])
        if expected is not None:
            args['expected_ledger_limit_bytes'] = expected
        cap = recovery.resources.MAX_STORAGE_BYTES
        result = recovery.reconcile_retained_reservation(case['ledger'], **args)
        after = json.loads(case['ledger'].read_bytes())
        self.assertEqual(after['limit_bytes'], case['before']['limit_bytes'])
        self.assertEqual(after['roots'], case['before']['roots'])
        self.assertEqual(set(after['reservations']), set(case['before']['reservations']))
        self.assertEqual(after['reservations'][case['foreign_id']],
            case['before']['reservations'][case['foreign_id']])
        row = after['reservations'][case['args']['reservation_id']]
        self.assertEqual(row['status'], 'released')
        self.assertEqual(row['storage_bytes'], case['row']['storage_bytes'])
        self.assertEqual(row['external_charges'], {})
        self.assertEqual(row['last_usage'], case['row']['last_usage'])
        for key, value in case['row'].items():
            if key not in {'status', 'artifacts_durable_asserted'}:
                self.assertEqual(row[key], value)
        self.assertEqual(case['artifact'].read_bytes(), case['artifact_bytes'])
        self.assertEqual(recovery.resources.MAX_STORAGE_BYTES, cap)
        self.assertEqual(result['full_claim_accounting']['limit_bytes'], cap)
        self.assertEqual(result['full_claim_accounting']['outstanding_full_reservations_bytes'], 6096)
        self.assertEqual(result['final_accounting']['outstanding_full_reservations_bytes'], 2000)
        self.assertIs(result['cap_changed'], False)
        self.assertIs(result['admitted'], False)
        self.assertIs(result['new_resource_lease_acquired'], False)
        self.assertIs(result['actual_postwrite_census_required'], True)
        self.assertEqual(result['fresh_global_inventory_count'], 2)

    def _refusal(self, case, text, **changes):
        args = dict(case['args'], **changes)
        before = case['ledger'].read_bytes()
        with self.assertRaisesRegex(recovery.resources.DaemonResourceError, text):
            recovery.reconcile_retained_reservation(case['ledger'], **args)
        self.assertEqual(case['ledger'].read_bytes(), before)
        self.assertEqual(case['artifact'].read_bytes(), case['artifact_bytes'])

    def test_00_legacy_none_250_admin_positive(self):
        with self._fictional_case(recovery.resources.MAX_STORAGE_BYTES) as case:
            result = recovery.reconcile_retained_reservation(case['ledger'], **case['args'])
            self.assertEqual(json.loads(case['ledger'].read_bytes())['limit_bytes'],
                recovery.resources.MAX_STORAGE_BYTES)
            self.assertIs(result['cap_changed'], False)
            self.assertIs(result['admitted'], False)

    def test_01_real_default_read_rejects_current_280_before_inventory(self):
        with self._fictional_case(280_000_000_000) as case:
            actual_read = recovery.resources.DaemonResourceReservation._read
            seen = []
            def observed_read(helper):
                seen.append(helper.storage_limit_bytes)
                return actual_read(helper)
            def forbidden_inventory(*unused, **unused_kw):
                raise AssertionError('mismatched ledger reached inventory')
            before = case['ledger'].read_bytes()
            with _ledger_limit_patch.object(recovery.resources.DaemonResourceReservation,
                    '_read', observed_read), _ledger_limit_patch.object(recovery.resources,
                    '_inventory', forbidden_inventory):
                self._refusal(case, 'disk ledger storage scope differs')
            self.assertEqual(seen, [recovery.resources.MAX_STORAGE_BYTES])
            self.root_cause_observations.append(dict(configured_limit=seen[0],
                header_limit=280_000_000_000, error='disk ledger storage scope differs',
                ledger_bytes_unchanged=case['ledger'].read_bytes() == before,
                inventory_calls=0, native_admission_calls=0))

    def test_02_explicit_280_admin_positive_preserves_header_and_other_charges(self):
        with self._fictional_case(280_000_000_000) as case:
            self._success(case, 280_000_000_000)

    def test_03_wrong_exact_header_refuses(self):
        for expected in (250_000_000_000, 281_000_000_000):
            with self.subTest(expected=expected), self._fictional_case(280_000_000_000) as case:
                self._refusal(case, 'disk ledger storage scope differs',
                    expected_ledger_limit_bytes=expected)

    def test_04_invalid_limit_refuses_before_helper(self):
        class IntegerSubclass(int):
            pass
        bad = (True, False, 0, -1, 280_000_000_000.0, '280000000000', [], {},
            1 << 63, IntegerSubclass(280_000_000_000))
        def forbidden(*unused, **unused_kw):
            raise AssertionError('invalid explicit limit reached resource access')
        for expected in bad:
            with self.subTest(value=repr(expected)), _ledger_limit_patch.object(
                    recovery.resources, 'DaemonResourceReservation', forbidden):
                with self.assertRaisesRegex(recovery.resources.DaemonResourceError,
                        'invalid expected ledger limit'):
                    recovery.reconcile_retained_reservation('/not-accessed/ledger', roots=[],
                        reservation_id='not-accessed', expected_record_sha256='not-accessed',
                        attempt_directory='/not-accessed/attempt', expected_artifacts=[],
                        artifacts_durable=True, capacity_policy='administrative_closeout',
                        expected_ledger_limit_bytes=expected)

    def test_05_nonadministrative_limit_refuses_before_helper(self):
        def forbidden(*unused, **unused_kw):
            raise AssertionError('explicit limit reached nonadministrative resource access')
        with _ledger_limit_patch.object(recovery.resources, 'DaemonResourceReservation', forbidden):
            with self.assertRaisesRegex(recovery.resources.DaemonResourceError,
                    'explicit ledger limit requires administrative_closeout'):
                recovery.reconcile_retained_reservation('/not-accessed/ledger', roots=[],
                    reservation_id='not-accessed', expected_record_sha256='not-accessed',
                    attempt_directory='/not-accessed/attempt', expected_artifacts=[],
                    artifacts_durable=True, expected_ledger_limit_bytes=280_000_000_000)

    def test_06_explicit_legacy_cap_admin_positive(self):
        with self._fictional_case(recovery.resources.MAX_STORAGE_BYTES) as case:
            self._success(case, recovery.resources.MAX_STORAGE_BYTES)

    def test_07_explicit_none_keeps_280_header_refusal(self):
        with self._fictional_case(280_000_000_000) as case:
            self._refusal(case, 'disk ledger storage scope differs', expected_ledger_limit_bytes=None)

    def test_08_stale_row_refusal_is_unchanged(self):
        with self._fictional_case(280_000_000_000) as case:
            self._refusal(case, 'retained reservation identity changed',
                expected_ledger_limit_bytes=280_000_000_000, expected_record_sha256='0' * 64)

    def test_09_bad_inventory_refusal_is_unchanged(self):
        with self._fictional_case(280_000_000_000) as case:
            inventory = _ledger_limit_copy.deepcopy(case['args']['expected_artifacts'])
            inventory[0]['sha256'] = '0' * 64
            self._refusal(case, 'durable recovery inventory differs',
                expected_ledger_limit_bytes=280_000_000_000, expected_artifacts=inventory)

    def test_10_live_owner_refusal_is_unchanged(self):
        with self._fictional_case(280_000_000_000) as case:
            with _ledger_limit_patch.object(recovery.resources, '_process',
                    lambda pid: {'pid': pid, 'birth': 'fictional-reused-pid', 'state': 'S'}):
                self._refusal(case, 'original reservation owner PID still exists',
                    expected_ledger_limit_bytes=280_000_000_000)

    def test_11_selected_external_charge_refusal_is_unchanged(self):
        with self._fictional_case(280_000_000_000) as case:
            value = json.loads(case['ledger'].read_bytes())
            row = value['reservations'][case['args']['reservation_id']]
            row['external_charges'] = {'fictional_selected': 7}
            case['ledger'].write_text(json.dumps(value, sort_keys=True) + '\n')
            self._refusal(case, 'external charges require separate recovery',
                expected_ledger_limit_bytes=280_000_000_000,
                expected_record_sha256=recovery._digest(row))

    def test_12_scope_refusal_is_unchanged(self):
        with self._fictional_case(280_000_000_000) as case:
            value = json.loads(case['ledger'].read_bytes())
            row = value['reservations'][case['args']['reservation_id']]
            row['process_scope'] = 'fictional_unsupported_scope'
            case['ledger'].write_text(json.dumps(value, sort_keys=True) + '\n')
            self._refusal(case, 'process scope requires separate recovery evidence',
                expected_ledger_limit_bytes=280_000_000_000,
                expected_record_sha256=recovery._digest(row))

    def test_13_noninteger_stored_header_is_still_refused(self):
        with self._fictional_case(280_000_000_000.0) as case:
            self._refusal(case, 'disk ledger storage scope differs',
                expected_ledger_limit_bytes=280_000_000_000)


    def test_14_engine_rejects_any_explicit_nonadministrative_binding_before_helper(self):
        def forbidden(*unused, **unused_kw):
            raise AssertionError('engine explicit limit reached nonadministrative resource access')
        for expected in (250_000_000_000, 280_000_000_000):
            with self.subTest(expected=expected), _ledger_limit_patch.object(
                    recovery.resources, 'DaemonResourceReservation', forbidden):
                with self.assertRaisesRegex(recovery.resources.DaemonResourceError,
                        'explicit ledger limit requires administrative_closeout'):
                    recovery._retained_reconciliation_engine('/not-accessed/ledger', roots=[],
                        reservation_id='not-accessed', expected_record_sha256='not-accessed',
                        attempt_directory='/not-accessed/attempt', expected_artifacts=[],
                        artifacts_durable=True, capacity_policy='require_capacity',
                        expected_ledger_limit_bytes=expected)

    def test_15_explicit_historical_160_opens_without_changing_global_census(self):
        with self._fictional_case(160_000_000_000) as case:
            self._success(case, 160_000_000_000)

    def test_16_explicit_maximum_signed_integer_is_a_valid_existing_header(self):
        with self._fictional_case((1 << 63) - 1) as case:
            self._success(case, (1 << 63) - 1)

    def test_17_live_recorded_group_refusal_is_unchanged(self):
        with self._fictional_case(280_000_000_000) as case:
            value = json.loads(case['ledger'].read_bytes())
            row = value['reservations'][case['args']['reservation_id']]
            row['child'] = {'pid': 99999997, 'birth': 'fictional'}
            case['ledger'].write_text(json.dumps(value, sort_keys=True) + '\n')
            with _ledger_limit_patch.object(recovery.resources, '_group_usage',
                    lambda child: {'live_processes': 1 if child is not None else 0}):
                self._refusal(case, 'retained child group is still alive',
                    expected_ledger_limit_bytes=280_000_000_000,
                    expected_record_sha256=recovery._digest(row))

    def test_18_attempt_identity_refusal_is_unchanged(self):
        with self._fictional_case(280_000_000_000) as case:
            value = json.loads(case['ledger'].read_bytes())
            row = value['reservations'][case['args']['reservation_id']]
            row['attempt_directory']['inode'] += 1
            case['ledger'].write_text(json.dumps(value, sort_keys=True) + '\n')
            self._refusal(case, 'recovery attempt identity changed',
                expected_ledger_limit_bytes=280_000_000_000,
                expected_record_sha256=recovery._digest(row))

    def test_19_explicit_none_legacy_250_admin_positive(self):
        with self._fictional_case(recovery.resources.MAX_STORAGE_BYTES) as case:
            result = recovery.reconcile_retained_reservation(case['ledger'],
                **dict(case['args'], expected_ledger_limit_bytes=None))
            self.assertEqual(json.loads(case['ledger'].read_bytes())['limit_bytes'],
                recovery.resources.MAX_STORAGE_BYTES)
            self.assertIs(result['admitted'], False)
            self.assertIs(result['cap_changed'], False)


    def test_20_none_preserves_legacy_constructor_keyword_shape(self):
        with self._fictional_case(recovery.resources.MAX_STORAGE_BYTES) as case:
            actual_constructor = recovery.resources.DaemonResourceReservation
            observed = []
            def legacy_constructor(*args, **kwargs):
                self.assertNotIn('storage_limit_bytes', kwargs)
                observed.append(set(kwargs))
                return actual_constructor(*args, **kwargs)
            with _ledger_limit_patch.object(recovery.resources,
                    'DaemonResourceReservation', legacy_constructor):
                result = recovery.reconcile_retained_reservation(case['ledger'],
                    **dict(case['args'], expected_ledger_limit_bytes=None))
            self.assertEqual(len(observed), 1)
            self.assertIs(result['cap_changed'], False)
