"""Finite, fileless synthetic controls for roots-only metadata predicates."""
import ast
from collections import Counter
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

F = Path(__file__).resolve().parent
P = F.parent / 'legal-conditions-recall-20261014-01'
HELPER = F / 'balanced_execution_root_identity_v01.py'
PROTOCOL = P / 'conditions_balanced_resource_protocol_v01.py'
OUTPUT = F / 'root-identity-independent-detached-controls-v01.json'


def pin(path):
    raw = path.read_bytes()
    return dict(path=str(path), bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())


def detach(path, names, namespace):
    nodes = [n for n in ast.parse(path.read_text()).body if isinstance(n, ast.FunctionDef) and n.name in names]
    assert len(nodes) == len(names)
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(path), 'exec'), namespace)


def main():
    assert not OUTPUT.exists()
    ns = dict(json=json, hashlib=hashlib, Counter=Counter)
    detach(PROTOCOL, {'require', 'canonical', 'digest', 'qualify_ledger', 'qualify_check'}, ns)
    p = SimpleNamespace(qualify_ledger=ns['qualify_ledger'])
    ns['p'] = p
    detach(HELPER, {'qualify_ledger_roots', 'qualify_transition'}, ns)
    old_roots = [dict(path=x, device=10, inode=i) for x, i in
                 zip(('/counted/logs', '/counted/todo', '/counted/evidence', '/tmp/pytest-of-barberb'),
                     (101, 102, 103, 524352))]
    current = deepcopy(old_roots)
    current[3]['inode'] = 524344
    records = {str(i): dict(reservation_id=str(i), status='released' if i < 437 else 'retained',
                           storage_bytes=200000000 if i < 437 else 1) for i in range(538)}
    records['437']['storage_bytes'] = 44381777216 - 100
    hashes = {key: ns['digest'](value) for key, value in records.items()}
    contract = dict(counted_root_metadata=old_roots, global_cap_bytes=145000000000,
        required_preserved_claims=[dict(reservation_id='438', status='retained', storage_bytes=1)],
        prior_record_status_counts=dict(released=437, retained=101), prior_full_nonreleased_claim_bytes=44381777216)
    before = dict(schema='daemon-resource-reservations-v1', roots=old_roots, limit_bytes=145000000000,
                  reservations=records)
    after = deepcopy(before)
    after['roots'] = current
    results = []
    def check(name, action, refusal=False):
        try:
            action()
            ok = not refusal
        except ValueError:
            ok = refusal
        assert ok, name
        results.append(dict(name=name, passed=True, expected_refusal=refusal))
    check('old_root_envelope_needs_exact_rebind', lambda: ns['require'](
        ns['qualify_ledger_roots'](contract, before, hashes, current)[1] is True, 'needed'))
    check('current_envelope_is_idempotent_no_write_needed', lambda: ns['require'](
        ns['qualify_ledger_roots'](contract, after, hashes, current)[1] is False, 'no write'))
    check('only_temporary_inode_changes_all538_records_exact', lambda: ns['qualify_transition'](
        before, after, contract, hashes, current))
    for name, mutate in [
        ('cap_increase', lambda x: x.update(limit_bytes=145000000001)),
        ('cap_decrease', lambda x: x.update(limit_bytes=144999999999)),
        ('ledger_schema_change', lambda x: x.update(schema='other')),
        ('extra_top_level_field', lambda x: x.update(extra=True)),
        ('record_removed', lambda x: x['reservations'].pop('0')),
        ('record_added', lambda x: x['reservations'].update(new=dict(reservation_id='new', status='released', storage_bytes=1))),
        ('retained_claim_released', lambda x: x['reservations']['438'].update(status='released')),
        ('released_claim_retained', lambda x: x['reservations']['0'].update(status='retained')),
        ('claim_bytes_changed', lambda x: x['reservations']['438'].update(storage_bytes=2)),
        ('opaque_foreign_body_field_added', lambda x: x['reservations']['123'].update(extra='changed')),
        ('root_name_changed', lambda x: x['roots'][3].update(path='/tmp/other')),
        ('persistent_root_inode_changed', lambda x: x['roots'][0].update(inode=999)),
        ('temporary_root_device_changed', lambda x: x['roots'][3].update(device=999)),
        ('wrong_temporary_inode', lambda x: x['roots'][3].update(inode=777)),
    ]:
        bad = deepcopy(after)
        mutate(bad)
        check(name + '_refused', lambda bad=bad: ns['qualify_transition'](before, bad, contract, hashes, current), True)
    wrong = dict(hashes)
    wrong['0'] = '0'*64
    check('prior_record_hash_mismatch_refused', lambda: ns['qualify_ledger_roots'](contract, before, wrong, current), True)
    stale = deepcopy(before)
    stale['reservations']['0']['external_charges'] = dict(new=1)
    check('concurrent_prior_body_change_refused', lambda: ns['qualify_ledger_roots'](contract, stale, hashes, current), True)
    state = dict(schema_version='scheduler/v1', config=dict(cpu=4), leases={'foreign-active': {'opaque': True}},
                 waiters={'foreign-waiter': {'opaque': True}})
    contract2 = dict(contract, resources=dict(cpu_slots=2), scheduler_config=state['config'],
                     scheduler_config_sha256=ns['digest'](state['config']), resource_producer_pins={'/public/producer.py': {}})
    receipt = dict(ledger=dict(bytes=10, sha256='a'*64), scheduler=dict(bytes=20, sha256='b'*64))
    check_value = dict(schema='scope-pilot-resource-compatibility/v1', passed=True, findings=[],
        resources=contract2['resources'], disk_limit_bytes=145000000000, outstanding_full_reservations_bytes=44381777216,
        shared_config=state['config'], lease_count=1, waiter_count=1, model_started=False, reservation_acquired=False,
        scheduler_client_constructed=False, shared_state_modified=False, admission_guaranteed=False,
        disk_ledger=receipt['ledger'], shared_state=receipt['scheduler'], producers={'/public/producer.py': {}})
    check('actual_foreign_scheduler_lease_and_waiter_preserved', lambda: ns['require'](
        ns['qualify_check'](contract2, check_value, receipt, state)['lease_count'] == 1, 'not idle'))
    idle = deepcopy(check_value)
    idle.update(lease_count=0, waiter_count=0)
    check('fake_idle_counts_refused', lambda: ns['qualify_check'](contract2, idle, receipt, state), True)
    changed = deepcopy(state)
    changed['config']['cpu'] = 8
    check('scheduler_config_change_refused', lambda: ns['qualify_check'](contract2, check_value, receipt, changed), True)
    mismatch = deepcopy(receipt)
    mismatch['scheduler']['sha256'] = 'c'*64
    check('scheduler_snapshot_check_join_mismatch_refused', lambda: ns['qualify_check'](contract2, check_value, mismatch, state), True)
    # Exact source order supplies write/lock/durability custody; no I/O kernel is executed.
    executor = F / 'reconcile_balanced_execution_root_identity_v01.py'
    tree = ast.parse(executor.read_text())
    main_source = ast.get_source_segment(executor.read_text(), next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'main'))
    assert main_source.index('with owner._locked():') < main_source.index('r.read_locked_raw')
    assert main_source.index('r.durable_backup(raw)') < main_source.index('owner._write(after)') < main_source.index('verified=owner._read()')
    assert main_source.count('owner._write(after)') == 1 and '.__enter__' not in main_source
    assert "native.DaemonResourceReservation" in main_source and 'get_global_resource_scheduler(' not in main_source
    check('locked_exact_before_backup_then_single_native_write_and_strict_readafter_order', lambda: None)
    artifacts = {str(path): pin(path) for path in (Path(__file__).resolve(), HELPER, PROTOCOL, executor,
                                                 F/'review_balanced_execution_root_identity_preflight_v01.py')}
    result = dict(schema='conditions-balanced-root-identity-independent-detached-controls/v1', passed=True,
        findings=[], controls=results, control_count=len(results), synthetic_records=538,
        synthetic_foreign_active_scheduler_leases=1, synthetic_waiters=1, executed_main_or_full_module=False,
        private_or_live_endpoint_reads=0, actual_locks_or_writes=0, resource_API_calls=0, census_calls=0,
        model_or_numerical_imports=0, checkpoint_JSON_parses=0, artifacts=artifacts,
        limits='Fileless pure metadata predicates plus source-order checks; native lock/backup/atomic-write implementation is source-reviewed, never executed here.')
    with OUTPUT.open('x') as handle:
        json.dump(result, handle, indent=2, sort_keys=True)
        handle.write('\n')
    OUTPUT.chmod(0o444)
    print(json.dumps(pin(OUTPUT)))


if __name__ == '__main__':
    main()
