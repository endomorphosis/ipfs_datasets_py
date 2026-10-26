"""Synthetic disposable native-format evidence, never native launch authority.

The source profile bytes are the exact inert published owner fixture. The
request/receipt and deceased-owner metadata below are explicitly test-authored;
they do not claim an actual native launch, grant, death or original receipt.
Every scheduler/ledger path belongs to tmp_path. No host scheduler is opened.
"""
import builtins
import copy
import hashlib
import importlib
import json
import os
from pathlib import Path
import uuid

import pytest


PACKAGE = os.environ.get('IPFS_RECOVERY_TEST_PACKAGE',
    'ipfs_datasets_py.optimizers.logic_theorem_optimizer')
recovery = importlib.import_module(PACKAGE + '.autoencoder_native_request_recovery')
base = importlib.import_module(PACKAGE + '.autoencoder_resource_recovery')
tree = importlib.import_module(PACKAGE + '.autoencoder_external_tree_inventory')
scheduling = importlib.import_module(PACKAGE + '.resource_scheduler')
existing = importlib.import_module(PACKAGE + '.existing_resource_scheduler')
resources = base.resources
OWNER_SHA = 'e2f66d5901f73ea99028d704703698745a16b83b4328589aa5e1b47c04d532c7'


def save_json(path, value):
    path.write_bytes(json.dumps(value, sort_keys=True, indent=2, allow_nan=False).encode() + b'\n')


def pin(path):
    raw = path.read_bytes()
    return {'path': str(path), 'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}


@pytest.fixture
def native_case(tmp_path, monkeypatch):
    roots = [tmp_path / name for name in ('attempts', 'external-a', 'external-b')]
    for root in roots:
        root.mkdir()
    scheduler = scheduling.GlobalResourceScheduler(scheduling.ResourceSchedulerConfig(
        total_cpu_slots=4, total_memory_mb=4096, total_child_process_slots=4,
        lane_reservations={}, state_path=tmp_path / 'scheduler.json', auto_renew_leases=False))
    monkeypatch.setattr(resources, 'get_global_resource_scheduler', lambda: scheduler)
    backend_cap = resources.MAX_STORAGE_BYTES
    ledger = tmp_path / 'ledger.json'
    attempt = roots[0] / 'synthetic-failed-attempt'
    attempt.mkdir()
    (attempt / 'TEST_ONLY.txt').write_text('Synthetic protocol fixture; no native launch or grant.\n')
    (roots[1] / 'metadata.duckdb').write_bytes(b'opaque database fixture')
    (roots[1] / 'latest').symlink_to('metadata.duckdb')
    (roots[2] / 'auth.json').write_bytes(b'opaque synthetic payload')
    owner_source = tmp_path / 'original-owner-source.txt'
    source = (Path(__file__).parent / 'fixtures/native_orchestration_owner_v06.py.txt').read_bytes()
    assert hashlib.sha256(source).hexdigest() == OWNER_SHA
    owner_source.write_bytes(source)  # Byte copy only: this source is never executed.

    def factory(storage_bytes=60_000):
        return resources.DaemonResourceReservation(ledger, roots=roots,
            storage_bytes=storage_bytes, cpu_slots=1, memory_mb=2048, child_process_slots=4)

    amounts = [10_000, 12_000]
    with factory() as owner:
        owner.check_usage(attempt)
        native_lease_id = owner.to_dict()['resource_lease']['lease_id']
        for root, amount in zip(roots[1:], amounts):
            owner.account_external_bytes(hashlib.sha256(str(root).encode()).hexdigest(), amount)
    # Public APIs created the real disposable ledger and released its test-local
    # scheduler lease. These edits model native deceased-owner metadata only;
    # they are not assertions about an actually launched process or grant.
    state = json.loads(ledger.read_bytes())
    selected = state['reservations'][owner.reservation_id]
    selected.update(owner_pid=99_999_999, child={'pid': 99_999_998, 'birth': '123'},
        prior_children=[], workload='canonical_parented_phase', scheduler_lane='orchestration',
        native_lease_id=native_lease_id, parent_lease_id=uuid.uuid4().hex,
        scheduler_state_path=str(tmp_path / 'scheduler.json'),
        scheduler_policy_sha256=existing.policy_sha256(scheduler.config.persisted_dict()))
    save_json(ledger, state)
    request_path = tmp_path / 'synthetic-original-request.json'
    request = {'schema': 'legal-ir-native-orchestration-request@1', 'purpose': 'supervisor_preflight',
        'name': 'synthetic-test-only-native-request', 'attempt_directory': str(attempt),
        'command': ['/not-executed/test-only'], 'cwd': str(tmp_path), 'duration_seconds': 30,
        'storage_bytes': selected['storage_bytes'],
        'external_charges': [{'path': str(root), 'bytes': amount}
                             for root, amount in zip(roots[1:], amounts)],
        'source_sha256': {str(owner_source): OWNER_SHA}}
    save_json(request_path, request)
    receipt = {'schema': 'legal-ir-native-orchestration-receipt@1', 'purpose': 'supervisor_preflight',
        'request_sha256': pin(request_path)['sha256'], 'owner_pid': selected['owner_pid'],
        'status': 'failed', 'hard_enforcement': False, 'completion_authority': False,
        'root_lease_id': uuid.uuid4().hex, 'phase_lease_id': selected['parent_lease_id'],
        'disk_reservation_id': owner.reservation_id, 'child_pid': selected['child']['pid'],
        'child_pgid': selected['child']['pid'], 'child_returncode': 1,
        'failure_type': 'SyntheticFixtureOnly', 'owned_group_quiescent': True, 'ended_at_epoch': 1.0}
    save_json(attempt / 'receipt.json', receipt)
    dispositions = [{'key': hashlib.sha256(str(root).encode()).hexdigest(), 'path': str(root),
        'bytes': amount, 'descriptor_inventory': tree.observe_external_tree(root,
            max_entries=64, max_bytes=amount, max_depth=8, max_symlink_hops=8)}
        for root, amount in zip(roots[1:], amounts)]
    case = {'ledger': ledger, 'roots': roots, 'scheduler': scheduler, 'factory': factory,
        'attempt': attempt, 'request_path': request_path, 'request': request, 'receipt': receipt,
        'owner_source': owner_source, 'reservation_id': owner.reservation_id,
        'dispositions': dispositions, 'backend_cap': backend_cap}
    refresh(case)
    return case


def refresh(case, *, reseal_request=False):
    if reseal_request:
        save_json(case['request_path'], case['request'])
        case['receipt']['request_sha256'] = pin(case['request_path'])['sha256']
        save_json(case['attempt'] / 'receipt.json', case['receipt'])
    state = json.loads(case['ledger'].read_bytes())
    row = state['reservations'][case['reservation_id']]
    case['args'] = dict(roots=case['roots'], reservation_id=case['reservation_id'],
        expected_record_sha256=base._digest(row), attempt_directory=case['attempt'],
        expected_artifacts=base._durable_inventory(case['attempt']),
        original_request_pin=pin(case['request_path']), original_owner_source_pin=pin(case['owner_source']),
        external_dispositions=copy.deepcopy(case['dispositions']), artifacts_durable=True)


def change_record(case, **changes):
    state = json.loads(case['ledger'].read_bytes())
    state['reservations'][case['reservation_id']].update(changes)
    save_json(case['ledger'], state)
    refresh(case)


def call(case):
    return recovery.reconcile_retained_native_request_reservation(case['ledger'], **case['args'])


def test_real_disposable_closeout_preserves_all_other_records_files_policy_and_charges(native_case, monkeypatch):
    case = native_case
    with case['factory'](5_000) as foreign:
        pass
    before = json.loads(case['ledger'].read_bytes())
    scheduler_before = case['scheduler'].config.state_path.read_bytes()
    artifacts_before = base._durable_inventory(case['attempt'])
    def forbidden(*args, **kwargs):
        raise AssertionError('closeout must not acquire a resource or enter an owner')
    monkeypatch.setattr(resources.DaemonResourceReservation, '__enter__', forbidden)
    monkeypatch.setattr(scheduling.GlobalResourceScheduler, 'acquire', forbidden)
    receipt = call(case)
    after = json.loads(case['ledger'].read_bytes())
    assert receipt['schema'] == 'explicit-native-request-retained-reservation-reconciliation/v1'
    assert receipt['admitted'] is receipt['cap_changed'] is receipt['outputs_deleted'] is False
    assert receipt['source_profile_is_execution_attestation'] is False
    assert receipt['new_resource_lease_acquired'] is receipt['new_reservation_created'] is False
    assert receipt['external_payloads_opened'] is receipt['external_historical_durability_asserted'] is False
    assert receipt['atomic_external_snapshot'] is receipt['continuous_external_custody_proved'] is False
    assert receipt['fresh_global_inventory_count'] == 2
    assert receipt['descriptor_inventory_count_per_external_tree'] == 3
    assert receipt['actual_postwrite_census_required'] is receipt['final_accounting_is_prewrite_projection'] is True
    assert after['reservations'][foreign.reservation_id] == before['reservations'][foreign.reservation_id]
    selected = after['reservations'][case['reservation_id']]
    old = before['reservations'][case['reservation_id']]
    assert selected['status'] == 'released' and selected['artifacts_durable_asserted'] is True
    assert selected['external_charges'] == old['external_charges']
    assert selected['child'] == old['child'] and selected['prior_children'] == old['prior_children']
    assert after['roots'] == before['roots'] and after['limit_bytes'] == before['limit_bytes'] == case['backend_cap']
    assert resources.MAX_STORAGE_BYTES == case['backend_cap']
    assert base._durable_inventory(case['attempt']) == artifacts_before
    assert case['scheduler'].config.state_path.read_bytes() == scheduler_before
    assert receipt['full_claim_accounting']['outstanding_full_reservations_bytes'] - receipt['final_accounting']['outstanding_full_reservations_bytes'] == old['storage_bytes']


@pytest.mark.parametrize('fault', ['request_hash', 'request_source_map', 'source_profile',
    'source_pin_size', 'wrong_attempt', 'wrong_owner', 'wrong_child', 'wrong_phase',
    'wrong_storage', 'bool_charge', 'duplicate_charge', 'omitted_charge',
    'noncanonical_path', 'wrong_charge_amount', 'wrong_disposition_key',
    'missing_disposition', 'descriptor_digest', 'descriptor_bool_identity',
    'attempt_inode', 'scheduler_policy', 'not_retained', 'no_durability'])
def test_wrong_original_or_current_evidence_never_changes_ledger(native_case, fault):
    case = native_case
    if fault == 'request_hash':
        case['args']['original_request_pin']['sha256'] = '0' * 64
    elif fault == 'request_source_map':
        case['request']['source_sha256'] = {str(case['owner_source']): '0' * 64}
        refresh(case, reseal_request=True)
    elif fault == 'source_profile':
        case['owner_source'].write_bytes(case['owner_source'].read_bytes() + b'\n')
        refresh(case)
    elif fault == 'source_pin_size':
        case['args']['original_owner_source_pin']['bytes'] += 1
    elif fault == 'wrong_attempt':
        case['request']['attempt_directory'] = str(case['roots'][0])
        refresh(case, reseal_request=True)
    elif fault in {'wrong_owner', 'wrong_child', 'wrong_phase'}:
        field = {'wrong_owner': 'owner_pid', 'wrong_child': 'child_pid', 'wrong_phase': 'phase_lease_id'}[fault]
        case['receipt'][field] = uuid.uuid4().hex if fault == 'wrong_phase' else 99_999_997
        save_json(case['attempt'] / 'receipt.json', case['receipt'])
        refresh(case)
    elif fault in {'wrong_storage', 'bool_charge', 'duplicate_charge', 'omitted_charge', 'noncanonical_path'}:
        if fault == 'wrong_storage': case['request']['storage_bytes'] += 1
        elif fault == 'bool_charge': case['request']['external_charges'][0]['bytes'] = True
        elif fault == 'duplicate_charge': case['request']['external_charges'].append(copy.deepcopy(case['request']['external_charges'][0]))
        elif fault == 'omitted_charge': case['request']['external_charges'].pop()
        else: case['request']['external_charges'][0]['path'] += '/.'
        refresh(case, reseal_request=True)
    elif fault in {'wrong_charge_amount', 'wrong_disposition_key', 'missing_disposition', 'descriptor_digest', 'descriptor_bool_identity'}:
        rows = case['args']['external_dispositions']
        if fault == 'wrong_charge_amount': rows[0]['bytes'] += 1
        elif fault == 'wrong_disposition_key': rows[0]['key'] = '0' * 64
        elif fault == 'missing_disposition': rows.pop()
        elif fault == 'descriptor_digest': rows[0]['descriptor_inventory']['inventory_sha256'] = '0' * 64
        else:
            value = rows[0]['descriptor_inventory']
            value['root_identity']['inode'] = True
            body = {k: v for k, v in value.items() if k != 'inventory_sha256'}
            value['inventory_sha256'] = hashlib.sha256(recovery._canonical(body)).hexdigest()
    elif fault == 'attempt_inode':
        state = json.loads(case['ledger'].read_bytes())
        state['reservations'][case['reservation_id']]['attempt_directory']['inode'] += 1
        save_json(case['ledger'], state)
        refresh(case)
    elif fault == 'scheduler_policy': change_record(case, scheduler_policy_sha256='0' * 64)
    elif fault == 'not_retained': change_record(case, status='released')
    else: case['args']['artifacts_durable'] = False
    unchanged = case['ledger'].read_bytes()
    with pytest.raises((resources.DaemonResourceError, ValueError, OSError)):
        call(case)
    assert case['ledger'].read_bytes() == unchanged


@pytest.mark.parametrize('kind', ['owner_present', 'owner_reused', 'child_live', 'prior_child_live'])
def test_current_process_presence_refuses_even_reused_original_owner(native_case, monkeypatch, kind):
    case = native_case
    if kind == 'owner_present':
        case['receipt']['owner_pid'] = os.getpid()
        save_json(case['attempt'] / 'receipt.json', case['receipt'])
        change_record(case, owner_pid=os.getpid())
    elif kind == 'owner_reused':
        original = resources._process
        monkeypatch.setattr(resources, '_process', lambda pid: {'pid': pid, 'birth': 'different'}
            if pid == 99_999_999 else original(pid))
    else:
        child = {'pid': 99_999_998, 'birth': '123'}
        if kind == 'prior_child_live':
            child = {'pid': 99_999_997, 'birth': '456'}
            change_record(case, prior_children=[child])
        original = resources._group_usage
        monkeypatch.setattr(resources, '_group_usage', lambda value: {'live_processes': 1}
            if value == child else original(value))
    unchanged = case['ledger'].read_bytes()
    with pytest.raises(resources.DaemonResourceError):
        call(case)
    assert case['ledger'].read_bytes() == unchanged


def test_actual_disposable_scheduler_lease_with_original_request_name_blocks_closeout(native_case):
    case = native_case
    with case['scheduler'].acquire(scheduling.ResourceLane.ORCHESTRATION,
            cpu_slots=1, memory_mb=1, request_id=case['request']['name'], timeout=0):
        unchanged = case['ledger'].read_bytes()
        with pytest.raises(resources.DaemonResourceError, match='lease|waiter'):
            call(case)
        assert case['ledger'].read_bytes() == unchanged


@pytest.mark.parametrize('census', [1, 2])
@pytest.mark.parametrize('fault', ['attempt_bytes', 'external_tree', 'selected_body', 'other_body'])
def test_mutation_at_either_real_administrative_census_refuses_before_write(native_case, monkeypatch, census, fault):
    case = native_case
    with case['factory'](5_000) as foreign:
        pass
    original = base._administrative_census
    count = 0
    def mutate(helper, state):
        nonlocal count
        result = original(helper, state)
        count += 1
        if count == census:
            if fault == 'attempt_bytes': (case['attempt'] / 'TEST_ONLY.txt').write_text('changed by test')
            elif fault == 'external_tree': (case['roots'][1] / 'metadata.duckdb').write_bytes(b'changed by test')
            elif fault == 'selected_body': state['reservations'][case['reservation_id']]['storage_bytes'] += 1
            else: state['reservations'][foreign.reservation_id]['retention_reason'] = 'changed by test'
        return result
    monkeypatch.setattr(base, '_administrative_census', mutate)
    unchanged = case['ledger'].read_bytes()
    with pytest.raises((resources.DaemonResourceError, ValueError, OSError)):
        call(case)
    assert case['ledger'].read_bytes() == unchanged


@pytest.mark.parametrize('write_completed', [False, True])
def test_single_atomic_write_error_requires_real_durable_readback_not_retry(native_case, monkeypatch, write_completed):
    case = native_case
    before = json.loads(case['ledger'].read_bytes())
    original = resources.DaemonResourceReservation._write
    writes = 0
    def lose_response(helper, state):
        nonlocal writes
        writes += 1
        if write_completed:
            original(helper, state)
        raise OSError('synthetic atomic-write response loss')
    with monkeypatch.context() as patch:
        patch.setattr(resources.DaemonResourceReservation, '_write', lose_response)
        with pytest.raises(OSError, match='response loss'):
            call(case)
    assert writes == 1
    after = json.loads(case['ledger'].read_bytes())
    if not write_completed:
        assert after == before
    else:
        assert after['reservations'][case['reservation_id']]['status'] == 'released'
        assert after['reservations'][case['reservation_id']]['explicit_reconciliation']['schema'] == recovery.SCHEMA
        assert after['roots'] == before['roots'] and after['limit_bytes'] == before['limit_bytes']
        with pytest.raises(resources.DaemonResourceError, match='identity changed'):
            call(case)
        assert json.loads(case['ledger'].read_bytes()) == after


def test_administrative_overage_is_reported_without_raising_cap_or_admitting_work(native_case):
    case = native_case
    # A synthetic promise at the actual backend limit makes observed tiny
    # files plus the complete retained promise exceed that unchanged limit.
    # No large payload, altered policy, or host reservation is involved.
    change_record(case, storage_bytes=case['backend_cap'])
    case['request']['storage_bytes'] = case['backend_cap']
    refresh(case, reseal_request=True)
    receipt = call(case)
    assert resources.MAX_STORAGE_BYTES == case['backend_cap']
    assert receipt['full_claim_accounting']['over_limit_bytes'] > 0
    assert receipt['final_accounting']['over_limit_bytes'] == 0
    assert receipt['admitted'] is receipt['cap_changed'] is False
    assert receipt['full_claim_accounting']['additional_requested_bytes'] == receipt['final_accounting']['additional_requested_bytes'] == 0
    unchanged = case['ledger'].read_bytes()
    with pytest.raises(resources.DaemonResourceError, match='capacity'):
        with case['factory'](case['backend_cap']):
            pytest.fail('administrative closeout must not authorize admission')
    assert case['ledger'].read_bytes() == unchanged


def test_external_payloads_are_never_opened_while_strict_attempt_evidence_is_verified(native_case, monkeypatch):
    case = native_case
    real_builtin, real_path_open = builtins.open, Path.open
    def is_external(path):
        return isinstance(path, (str, Path)) and any(Path(path).is_relative_to(root) for root in case['roots'][1:])
    def guarded_builtin(path, *args, **kwargs):
        assert not is_external(path), 'external payload opened'
        return real_builtin(path, *args, **kwargs)
    def guarded_path(path, *args, **kwargs):
        assert not is_external(path), 'external payload opened'
        return real_path_open(path, *args, **kwargs)
    with monkeypatch.context() as patch:
        patch.setattr(builtins, 'open', guarded_builtin)
        patch.setattr(Path, 'open', guarded_path)
        receipt = call(case)
    assert receipt['external_payloads_opened'] is False
    assert receipt['artifacts'] == case['args']['expected_artifacts']


def test_legacy_strict_recovery_still_rejects_external_charges(native_case):
    case = native_case
    args = {k: case['args'][k] for k in ('roots', 'reservation_id', 'expected_record_sha256',
        'attempt_directory', 'expected_artifacts', 'artifacts_durable')}
    unchanged = case['ledger'].read_bytes()
    with pytest.raises(resources.DaemonResourceError, match='external charges'):
        base.reconcile_retained_reservation(case['ledger'], **args, capacity_policy='administrative_closeout')
    assert case['ledger'].read_bytes() == unchanged


def add_opaque_external_leaf(case):
    """A test-authored opt-in, not a statement about native target custody."""
    link = case['roots'][1] / 'opaque'
    target = '/not-observed-synthetic-native-target/payload'
    link.symlink_to(target)
    manifest = [{'path': 'opaque', 'link_target': target}]
    first = case['dispositions'][0]
    first['descriptor_inventory'] = tree.observe_external_tree(case['roots'][1],
        max_entries=64, max_bytes=first['bytes'], max_depth=8, max_symlink_hops=8,
        opaque_symlinks=manifest)
    refresh(case)
    return link, manifest


def reseal_descriptor(value):
    body = {key: item for key, item in value.items() if key != 'inventory_sha256'}
    value['inventory_sha256'] = hashlib.sha256(recovery._canonical(body)).hexdigest()


def test_explicit_opaque_descriptor_is_reobserved_three_times_without_widening_other_tree(native_case, monkeypatch):
    case = native_case
    link, manifest = add_opaque_external_leaf(case)
    with case['factory'](5_000) as foreign:
        pass
    before = json.loads(case['ledger'].read_bytes())
    identity_fields = ('st_dev', 'st_ino', 'st_mode', 'st_uid', 'st_gid', 'st_nlink',
        'st_size', 'st_mtime_ns', 'st_ctime_ns')
    source_before = tuple(getattr(link.lstat(), field) for field in identity_fields)
    original = recovery.observe_external_tree
    observations = []

    def observe_actual(path, **kwargs):
        observations.append((str(path), copy.deepcopy(kwargs.get('opaque_symlinks'))))
        return original(path, **kwargs)

    monkeypatch.setattr(recovery, 'observe_external_tree', observe_actual)
    receipt = call(case)
    assert receipt['schema'] == 'explicit-native-request-retained-reservation-reconciliation/v2'
    assert len(observations) == 6
    assert [opt for path, opt in observations if path == str(case['roots'][1])] == [manifest] * 3
    assert [opt for path, opt in observations if path == str(case['roots'][2])] == [None] * 3
    summary = next(row for row in receipt['external_dispositions'] if row['path'] == str(case['roots'][1]))
    assert summary['opaque_symlinks'] == manifest
    assert summary['opaque_link_referents_observed'] is False
    assert summary['opaque_link_target_custody_asserted'] is False
    assert summary['opaque_link_target_durability_asserted'] is False
    assert receipt['external_symlink_resolution'] == 'internal_except_explicit_opaque'
    assert receipt['opaque_link_referents_observed'] is False
    assert receipt['opaque_link_target_custody_asserted'] is False
    assert receipt['opaque_link_target_durability_asserted'] is False
    assert receipt['external_historical_durability_asserted'] is False
    assert receipt['external_payloads_opened'] is receipt['admitted'] is receipt['cap_changed'] is False
    after = json.loads(case['ledger'].read_bytes())
    assert after['reservations'][foreign.reservation_id] == before['reservations'][foreign.reservation_id]
    assert after['reservations'][case['reservation_id']]['external_charges'] == before['reservations'][case['reservation_id']]['external_charges']
    assert after['limit_bytes'] == resources.MAX_STORAGE_BYTES == case['backend_cap']
    assert tuple(getattr(link.lstat(), field) for field in identity_fields) == source_before
    assert os.readlink(link) == manifest[0]['link_target']


@pytest.mark.parametrize('fault', ['missing_manifest', 'empty_manifest', 'extra_manifest_leaf',
    'wrong_literal', 'wrong_kind', 'escape_path', 'missing_scope_flag',
    'target_observed_claim', 'target_custody_claim', 'relabel_as_v1',
    'resolved_target_claim', 'extra_manifest_field'])
def test_resealed_opaque_descriptor_mismatch_refuses_without_any_ledger_write(native_case, monkeypatch, fault):
    case = native_case
    add_opaque_external_leaf(case)
    descriptor = case['args']['external_dispositions'][0]['descriptor_inventory']
    opaque = next(row for row in descriptor['entries'] if row['path'] == 'opaque')
    if fault == 'missing_manifest':
        del descriptor['opaque_symlinks']
    elif fault == 'empty_manifest':
        descriptor['opaque_symlinks'] = []
    elif fault == 'extra_manifest_leaf':
        descriptor['opaque_symlinks'].append({'path': 'unrecorded-leaf', 'link_target': '/unobserved'})
        descriptor['opaque_symlinks'].sort(key=lambda row: row['path'])
    elif fault == 'wrong_literal':
        descriptor['opaque_symlinks'][0]['link_target'] = '/different-literal'
    elif fault == 'wrong_kind':
        opaque.update(kind='regular', mode=0o100600, link_target=None, resolved_target=None)
    elif fault == 'escape_path':
        descriptor['opaque_symlinks'][0]['path'] = '../opaque'
    elif fault == 'missing_scope_flag':
        del descriptor['opaque_link_referents_observed']
    elif fault == 'target_observed_claim':
        descriptor['opaque_link_referents_observed'] = True
    elif fault == 'target_custody_claim':
        descriptor['opaque_link_target_custody_asserted'] = True
    elif fault == 'relabel_as_v1':
        descriptor['schema'] = 'autoencoder-external-tree-descriptor-inventory@1'
    elif fault == 'resolved_target_claim':
        opaque['resolved_target'] = 'metadata.duckdb'
    else:
        descriptor['opaque_symlinks'][0]['extra'] = False
    reseal_descriptor(descriptor)  # Reach the actual closed/type/manifest check.
    unchanged = case['ledger'].read_bytes()
    writes = []

    def forbidden_write(*args, **kwargs):
        writes.append(True)
        raise AssertionError('invalid opaque evidence reached a ledger write')

    monkeypatch.setattr(resources.DaemonResourceReservation, '_write', forbidden_write)
    with pytest.raises((resources.DaemonResourceError, ValueError, OSError)):
        call(case)
    assert writes == []
    assert case['ledger'].read_bytes() == unchanged


@pytest.mark.parametrize('census', [1, 2])
def test_opaque_literal_change_at_either_real_census_refuses_without_write(native_case, monkeypatch, census):
    case = native_case
    link, manifest = add_opaque_external_leaf(case)
    original = base._administrative_census
    calls = 0

    def change_literal(helper, state):
        nonlocal calls
        result = original(helper, state)
        calls += 1
        if calls == census:
            link.unlink()
            link.symlink_to(manifest[0]['link_target'] + '-changed')
        return result

    def forbidden_write(*args, **kwargs):
        raise AssertionError('changed opaque leaf reached a ledger write')

    monkeypatch.setattr(base, '_administrative_census', change_literal)
    monkeypatch.setattr(resources.DaemonResourceReservation, '_write', forbidden_write)
    unchanged = case['ledger'].read_bytes()
    with pytest.raises((resources.DaemonResourceError, ValueError, OSError)):
        call(case)
    assert calls == census
    assert case['ledger'].read_bytes() == unchanged


def test_v1_relabel_cannot_silently_inherit_an_opaque_opt_in(native_case, monkeypatch):
    case = native_case
    add_opaque_external_leaf(case)
    descriptor = case['args']['external_dispositions'][0]['descriptor_inventory']
    descriptor['schema'] = 'autoencoder-external-tree-descriptor-inventory@1'
    for key in ('symlink_resolution', 'opaque_symlinks', 'opaque_link_referents_observed',
            'opaque_link_target_custody_asserted', 'opaque_link_target_durability_asserted'):
        del descriptor[key]
    opaque = next(row for row in descriptor['entries'] if row['path'] == 'opaque')
    opaque['resolved_target'] = 'metadata.duckdb'
    reseal_descriptor(descriptor)

    def forbidden_write(*args, **kwargs):
        raise AssertionError('strict descriptor accepted an escaping real link')

    monkeypatch.setattr(resources.DaemonResourceReservation, '_write', forbidden_write)
    unchanged = case['ledger'].read_bytes()
    with pytest.raises((resources.DaemonResourceError, ValueError, OSError)):
        call(case)
    assert case['ledger'].read_bytes() == unchanged
