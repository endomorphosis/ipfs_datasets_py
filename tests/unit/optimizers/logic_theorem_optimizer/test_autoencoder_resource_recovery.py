"""Explicit one-record recovery; original resource ownership is never adopted."""
import json
import os
from pathlib import Path

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
    assert recovery._durable_inventory(args['attempt_directory']) == args['expected_artifacts']
    assert row['explicit_reconciliation'] == receipt
    with pytest.raises(recovery.resources.DaemonResourceError, match='identity changed'):
        recovery.reconcile_retained_reservation(ledger, **args)


@pytest.mark.parametrize('fault', ['live_owner', 'live_group', 'prior_live_group', 'wrong_record', 'wrong_artifact',
                                   'extra_artifact', 'wrong_inode', 'not_retained', 'external_charge', 'no_assertion'])
def test_recovery_refuses_ambiguous_or_changed_evidence(setup, monkeypatch, fault):
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
        recovery.reconcile_retained_reservation(ledger, **args)
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
def test_recovery_does_not_accept_aliased_artifact_inventory(setup, monkeypatch, alias):
    ledger, args, _ = retained(setup, monkeypatch)
    source = args['attempt_directory'] / 'failure.json'
    target = args['attempt_directory'] / 'alias'
    if alias == 'hardlink': os.link(source, target)
    else: target.symlink_to(source)
    unchanged = ledger.read_bytes()
    with pytest.raises(recovery.resources.DaemonResourceError):
        recovery.reconcile_retained_reservation(ledger, **args)
    assert ledger.read_bytes() == unchanged
