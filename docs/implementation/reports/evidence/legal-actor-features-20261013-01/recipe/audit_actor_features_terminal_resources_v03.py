#!/usr/bin/env python3
"""Pure saved-resource audit of one N10 actor-features claim, without tensors or live bodies.

Adapted from the exact N9 terminal observer and its pinned resource helpers. Root
must qualify this source and approve exact input descriptors before main runs.
Only approved copied endpoints and this attempt's saved wrappers are parsed.
The real post-reconciliation prelaunch opening witness keeps role=opening/cell=None; no retrospective phase sample is fabricated.
The public receipt contains aggregate prior-record hashes, never foreign rows.
"""
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import stat
import sys

N = Path(__file__).resolve().parent
OLD = N.parent / 'legal-temporal-adapter-20261013-01'
N9 = N.parent / 'legal-actor-ranking-20261013-01'
PACKAGE = Path('/home/barberb/lift_coding/external/ipfs_datasets')
RUN = PACKAGE / 'workspace/test-logs/legal-trigger-readout-pilot-20261007-01'
LEDGER = PACKAGE / 'workspace/test-logs/federal-corpus-audits/owned-daemon-resource-control/disk-reservations.json'
SCHEDULER = Path('/tmp/ipfs-datasets-resource-scheduler-1000.json')
CELL = 'actor-features-ce'
ATTEMPT_NAME = 'actor-features-20261013-actor-features-ce-02'
ATTEMPT = RUN / ATTEMPT_NAME
BASELINE = N / 'resource-baseline-v02.json'
APPROVAL = N / 'actor-features-terminal-resource-source-independent-review-v03.json'
INPUTS = N / 'actor-features-terminal-resource-inputs-v02.json'
OUTPUT = N / 'actor-features-ce-terminal-resource-audit-v02.json'
BASELINE_PIN = {'path': '/home/barberb/lift_coding/artifacts/legal-actor-features-20261013-01/resource-baseline-v02.json', 'bytes': 85505, 'sha256': '1f32831b3dc3850bc890be37aeeb6429be3389b9142bfdcc7e4a3cd88a2163c3'}
FAILED_ACTOR_CLAIM = '893d4ed80ab3497f95b1490080e3caa3'
FAILED_CLAIM = 'c3e6fbcf39d146cd85f12617d320b153'
RESOURCES = dict(storage_bytes=200000000, memory_mb=1536, cpu_slots=2, child_process_slots=1)
CONTRACT = dict(**RESOURCES, child_deadline_seconds=300, admission_timeout_seconds=120,
                ledger_lock_timeout_seconds=60)
WRAPPERS = ('child-identity.json', 'child-exit.json', 'command.json', 'guardian-exit.json',
    'pre-admission.json', 'resource-observations.json', 'resources-start.json',
    'resources-final.json', 'lease-binding.json', 'scheduler-adoption.json',
    'lease-observations.jsonl', 'owned-group-final.json', 'group-rss-observations.jsonl',
    'group-rss-summary.json')
PRIOR_SOURCE_PINS = {
    str(N9/'audit_actor_ranking_terminal_resources_v01.py'):dict(bytes=45242,sha256='c60e18fe5cd9ce6365eec89e5fa3e5dbfbf6412fc0642bac7e1e25486bc72fb3'),
    str(N9/'review_actor_ranking_resource_baseline_v03.py'):dict(bytes=25477,sha256='824af98c583d66ac378f9acc47ba6a6888ea37f91d993cdd30956dc62ea6973c'),
    str(N9/'sample_actor_ranking_private_resources_v01.py'):dict(bytes=6660,sha256='6f179fd822b4ebf2caabec4c6d07f6c06e37391406f1ccf38ef841f6bb269a2c')}
RESOURCE_PRODUCER_PINS = {'/home/barberb/lift_coding/artifacts/legal-actor-features-20261013-01/adopt_shared_scheduler_actor_ranking_v02.py': {'bytes': 15101, 'sha256': '526aa9fa55d955eb92dba37053af2dfdf01f7dd8335cd309cb36770988bab0b7'}, '/home/barberb/lift_coding/external/ipfs_datasets/workspace/test-logs/decoder-normative-wording-r2-20261006/lazy_scheduler_adoption.py': {'bytes': 1345, 'sha256': '42f31d8da1eb5b44274ca0b8c8180cd78bc083dfd0e93438e61f38223929d84a'}, '/home/barberb/lift_coding/artifacts/legal-actor-features-20261013-01/owned_lease_watchdog_actor_ranking_v02.py': {'bytes': 24435, 'sha256': '6355884b6737c5b0e5cd1a128ad70a09fcf304f27bbf32492a15d8dbe070b032'}, '/home/barberb/lift_coding/external/ipfs_datasets/workspace/test-logs/native4096-four-width-20261004/resource-cap/autoencoder_daemon_resources.py': {'bytes': 36724, 'sha256': 'b00d2752ba852fe73760bba4fbd51b0e845742c3527642606a2a77ed9f8f5e2c'}, '/home/barberb/lift_coding/external/ipfs_datasets/workspace/test-logs/ui-modal-coverage-20261002/validation-source-r2/ipfs_datasets_py/__init__.py': {'bytes': 56829, 'sha256': 'f258f8eada774251feacd8e2ee2048efe56c89a8ee88efd50e4271ea41d43dc9'}, '/home/barberb/lift_coding/external/ipfs_datasets/workspace/test-logs/ui-modal-coverage-20261002/validation-source-r2/ipfs_datasets_py/optimizers/__init__.py': {'bytes': 957, 'sha256': 'a12bab3724da07be67b447719ace42fc1f480cb5635581f320a99a372f02f450'}, '/home/barberb/lift_coding/external/ipfs_datasets/workspace/test-logs/ui-modal-coverage-20261002/validation-source-r2/ipfs_datasets_py/optimizers/logic_theorem_optimizer/__init__.py': {'bytes': 69336, 'sha256': '9d693fa576f00dc36899faad75ef3044c437e2bfec5c62306f7031236725bb0e'}, '/home/barberb/lift_coding/external/ipfs_datasets/workspace/test-logs/ui-modal-coverage-20261002/validation-source-r2/ipfs_datasets_py/optimizers/logic_theorem_optimizer/proof_resource_safety.py': {'bytes': 4534, 'sha256': '23569b40b44d9130c30c62be564d58908a509fb1f40c6377e89f2fc1e3c799c5'}, '/home/barberb/lift_coding/external/ipfs_datasets/workspace/test-logs/ui-modal-coverage-20261002/validation-source-r2/ipfs_datasets_py/optimizers/logic_theorem_optimizer/resource_scheduler.py': {'bytes': 82754, 'sha256': 'a418e84f70ed8509ba0518feea69e7a8c27865139f83b6c81349eefdfd5893a4'}, '/home/barberb/lift_coding/external/ipfs_datasets/workspace/test-logs/ui-modal-coverage-20261002/validation-source-r2/ipfs_datasets_py/optimizers/logic_theorem_optimizer/runtime_telemetry.py': {'bytes': 53075, 'sha256': '542f705867b93fcb138a117e1f5c97a144ad6635dc92c37bc5034eee5065ef63'}}

MAX_BYTES = 16 * 1024 * 1024
READ_PINS = {}
ALLOWED_READS = {Path(__file__).resolve(), BASELINE, APPROVAL, INPUTS,
                 *(Path(path) for path in PRIOR_SOURCE_PINS)}
sys.dont_write_bytecode = True


def require(value, message):
    if not value:
        raise ValueError(message)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True,
                      allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def descriptor(value, expected_path=None):
    require(type(value) is dict and set(value) == {'path', 'bytes', 'sha256'},
            'closed raw descriptor required')
    path = Path(value['path'])
    require(type(value['path']) is str and path.is_absolute() and '..' not in path.parts
            and (expected_path is None or path == expected_path), 'exact absolute descriptor path required')
    require(type(value['bytes']) is int and 0 < value['bytes'] <= MAX_BYTES
            and type(value['sha256']) is str and len(value['sha256']) == 64
            and all(c in '0123456789abcdef' for c in value['sha256']), 'bounded raw descriptor required')
    return path


def ordinary(path, directory=False):
    path = Path(path)
    require(path.is_absolute() and '..' not in path.parts, 'physical absolute path required')
    for part in (*reversed(path.parents), path):
        info = part.lstat()
        wanted = stat.S_ISDIR if part != path or directory else stat.S_ISREG
        require(not stat.S_ISLNK(info.st_mode) and wanted(info.st_mode), 'ordinary path required')
    return path


def pin(path):
    path = ordinary(path)
    require(path in ALLOWED_READS, 'only explicitly approved raw input may be read')
    require(path not in {LEDGER, SCHEDULER} and 'checkpoint' not in path.name
            and 'reference-packet' not in path.name, 'live/model/reference access prohibited')
    before = path.stat()
    require(before.st_size <= MAX_BYTES, 'raw input exceeds byte bound before allocation')
    raw = path.read_bytes()
    after = path.stat()
    identity = lambda v: (v.st_dev, v.st_ino, v.st_size, v.st_mtime_ns, v.st_ctime_ns)
    require(identity(before) == identity(after) and len(raw) == before.st_size,
            'raw input changed while reading')
    value = dict(path=str(path), bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())
    require(str(path) not in READ_PINS or READ_PINS[str(path)] == value,
            'previously observed input identity changed')
    READ_PINS[str(path)] = value
    return value


def bind(value, expected_path=None):
    path = descriptor(value, expected_path)
    ALLOWED_READS.add(path)
    require(pin(path) == value, 'approved raw input identity differs')
    return path


def strict_json(raw):
    require(len(raw) <= MAX_BYTES, 'bounded JSON required')
    def unique(pairs):
        value = {}
        for key, item in pairs:
            require(key not in value, 'duplicate JSON field')
            value[key] = item
        return value
    def finite(raw):
        value = float(raw)
        require(math.isfinite(value), 'nonfinite metadata number')
        return value
    return json.loads(raw, object_pairs_hook=unique, parse_float=finite,
        parse_constant=lambda value: (_ for _ in ()).throw(ValueError('nonfinite JSON constant')))


def read(path):
    path = Path(path)
    opening = pin(path)
    raw = path.read_bytes()
    require(len(raw) == opening['bytes'] and hashlib.sha256(raw).hexdigest() == opening['sha256'],
            'consumed JSON differs from approved bytes')
    value = strict_json(raw)
    require(pin(path) == opening, 'consumed JSON identity changed')
    return value


def lines(path):
    path = Path(path)
    opening = pin(path)
    raw = path.read_bytes()
    require(len(raw) == opening['bytes'] and hashlib.sha256(raw).hexdigest() == opening['sha256'],
            'consumed JSONL differs from approved bytes')
    rows = [strict_json(line) for line in raw.splitlines() if line]
    require(len(rows) <= 2048 and pin(path) == opening, 'bounded stable JSONL required')
    return rows


def root_identity(path):
    path = ordinary(path, directory=True)
    info = path.stat()
    return dict(path=str(path), device=info.st_dev, inode=info.st_ino)


def qualify_snapshot(receipt, role, directory):
    require(receipt['schema'] == 'actor-features-private-endpoints/v1'
            and role in {'opening', 'terminal'} and receipt['role'] == role
            and receipt['cell'] == (None if role == 'opening' else CELL)
            and type(receipt['index']) is int and 1 <= receipt['index'] <= 99
            and directory.name == role + ('' if role == 'opening' else '-' + CELL) + '-v' + str(receipt['index']).zfill(2),
            'exact cell/role private sample required')
    require(receipt['private_bodies'] is True and receipt['continuous_custody'] is False
            and receipt['independent_contemporaneous_copy_witness'] is False
            and type(receipt['resource_API_calls']) is int and receipt['resource_API_calls'] == 0
            and receipt['shared_state_modified'] is False, 'private sample scope differs')
    for name, source in (('ledger', LEDGER), ('scheduler', SCHEDULER)):
        descriptor(receipt[name], directory / (name + '.json'))
        origin = receipt['source_' + name]
        require(origin['path'] == str(source) and all(type(origin[key]) is int and origin[key] > 0
                for key in ('device', 'inode')) and all(receipt[name][key] == origin[key]
                for key in ('bytes', 'sha256')), 'copied/source endpoint identity differs')


def snapshot(approved, role):
    path = descriptor(approved)
    require(path.name == 'snapshot-receipt-v01.json' and path.parent.parent == N / 'private-runtime-snapshots',
            'only exact owned private receipt directory allowed')
    for directory in (path.parent.parent, path.parent):
        ordinary(directory, directory=True)
        require(stat.S_IMODE(directory.stat().st_mode) == 0o700, 'private700 directory required')
    bind(approved)
    receipt = read(path)
    qualify_snapshot(receipt, role, path.parent)
    values = []
    for name in ('ledger', 'scheduler'):
        private = bind(receipt[name], path.parent / (name + '.json'))
        require(stat.S_IMODE(private.stat().st_mode) == 0o400, 'private400 copy required')
        values.append(read(private))
    require(stat.S_IMODE(path.stat().st_mode) == 0o400, 'private400 receipt required')
    return receipt, *values


def qualify_retry_baseline(baseline):
    phase = N
    ledger = baseline['baseline_ledger']
    reconciled = ledger['only_reconciled_prior_claim']
    require(baseline['schema'] == 'actor-features-resource-baseline/v2'
            and baseline['passed'] is True and baseline['findings'] == []
            and ledger['record_count'] == ledger['previous_record_count'] == 536
            and ledger['unchanged_other_record_count'] == 535
            and ledger['all_other535_record_bodies_unchanged'] is True
            and ledger['failed_N7_claim_retained_and_fully_charged'] is True
            and ledger['failed_N8_claim_explicitly_reconciled'] is True
            and ledger['record_status_counts'] == {'released': 435, 'retained': 101}
            and ledger['full_nonreleased_claim_bytes'] == 44381777216,
            'Qualified post-reconciliation536/535 resource baseline required')
    require(type(reconciled) is dict and set(reconciled) == {'reservation_id', 'previous_record_body_sha256',
                'record_body_sha256', 'status', 'storage_bytes'}
            and reconciled['reservation_id'] == '893d4ed80ab3497f95b1490080e3caa3'
            and reconciled['previous_record_body_sha256'] == '63cbb539d211fa47bf9a19d9b50c45dd4f2f4f8075d3d27b7597466c5174386c'
            and reconciled['status'] == 'released' and type(reconciled['storage_bytes']) is int
            and reconciled['storage_bytes'] == 200000000
            and type(ledger['record_body_hashes']) is dict and len(ledger['record_body_hashes']) == 536
            and all(type(key) is str and type(value) is str and len(value) == 64
                and all(c in '0123456789abcdef' for c in value) for key, value in ledger['record_body_hashes'].items())
            and ledger['record_body_hashes'][reconciled['reservation_id']] == reconciled['record_body_sha256']
            and digest(ledger['record_body_hashes']) == ledger['record_body_hash_map_sha256'],
            'Only exact proved N8 own claim may be reconciled; post-recovery full map must join')
    require(baseline['prior_baseline'] == dict(path=str(phase / 'resource-baseline-v01.json'), bytes=77873,
                sha256='0d9930ff9831f0fb135439a066f0345e2fa3e9720a8827f74366253016b4f8f2'),
            'Immutable pre-recovery baseline anchor differs')
    for key, name in (('explicit_reconciliation', 'actor-features-retained-claim-reconciliation-v01.json'),
                      ('recovery_preflight', 'actor-features-retained-claim-preflight-v01.json')):
        proof = baseline[key]
        require(type(proof) is dict and set(proof) == {'path', 'bytes', 'sha256'}
                and proof['path'] == str(phase / name) and type(proof['bytes']) is int and proof['bytes'] > 0
                and type(proof['sha256']) is str and len(proof['sha256']) == 64
                and all(c in '0123456789abcdef' for c in proof['sha256'])
                and baseline['artifacts'].get(proof['path']) == proof,
                'Exact qualified public reconciliation/preflight provenance required')
    return ledger

def qualify_phase_ledger(baseline, opening):
    prior = qualify_retry_baseline(baseline)
    original = prior['record_body_hashes']
    require(type(original) is dict and len(original) == 536
            and digest(original) == prior['record_body_hash_map_sha256'], 'authenticated536 hash map required')
    require(opening['schema'] == prior['schema'] == 'daemon-resource-reservations-v1'
            and type(opening['limit_bytes']) is int and opening['limit_bytes'] == prior['limit_bytes']
            == 145000000000 and opening['roots'] == baseline['counted_root_metadata'],
            'global schema/cap/counting roots changed')
    require(type(opening['reservations']) is dict and all(type(k) is str and type(v) is dict
            for k, v in opening['reservations'].items()), 'ordinary reservation map required')
    first = {k: digest(v) for k, v in opening['reservations'].items()}
    require(first == original, 'all536 prior bodies must remain exact before admission')
    bodies = opening['reservations']
    require(bodies[FAILED_CLAIM]['status'] == 'retained' and bodies[FAILED_CLAIM]['storage_bytes'] == 200000000
            and bodies[FAILED_ACTOR_CLAIM]['status'] == 'released' and bodies[FAILED_ACTOR_CLAIM]['storage_bytes'] == 200000000
            and digest(bodies[FAILED_ACTOR_CLAIM]) == prior['only_reconciled_prior_claim']['record_body_sha256'],
            'N7 stays retained; exact proved N8 own release remains unchanged from the new baseline')
    require(all(type(v['storage_bytes']) is int and v['storage_bytes'] >= 0
                for v in bodies.values()), 'full integer claims required')
    statuses = dict(Counter(v['status'] for v in bodies.values()))
    claims = sum(v['storage_bytes'] for v in bodies.values() if v['status'] != 'released')
    require((statuses, claims) == (prior['record_status_counts'], prior['full_nonreleased_claim_bytes'])
            == ({'released': 435, 'retained': 101}, 44381777216)
            and claims + RESOURCES['storage_bytes'] <= opening['limit_bytes'],
            'prior statuses/full nonreleased claims or own headroom differs')
    return dict(opening_record_count=536, all_previous536_record_bodies_unchanged=True,
        preserved_prior_record_count=536, failed_N7_claim_retained_and_fully_charged=True, failed_N8_claim_explicitly_reconciled=True,
        explicitly_reconciled_N8_record_body_sha256=prior['only_reconciled_prior_claim']['record_body_sha256'],
        prior_record_body_hash_map_sha256=digest(first),
        opening_record_status_counts=statuses, full_nonreleased_claim_bytes=claims)


def qualify_ledgers(baseline, opening, closing, own_id):
    result = qualify_phase_ledger(baseline, opening)
    prior = baseline['baseline_ledger']
    require(closing['schema'] == prior['schema'] and type(closing['limit_bytes']) is int
            and closing['limit_bytes'] == 145000000000
            and closing['roots'] == baseline['counted_root_metadata'],
            'closing global schema/cap/counting roots changed')
    require(type(closing['reservations']) is dict and all(type(k) is str and type(v) is dict
            for k, v in closing['reservations'].items()), 'ordinary closing reservation map required')
    first = {k: digest(v) for k, v in opening['reservations'].items()}
    last = {k: digest(v) for k, v in closing['reservations'].items()}
    require(len(last) == 537 and set(last) - set(first) == {own_id}
            and own_id not in first and all(last.get(k) == v for k, v in first.items()),
            'all536 prior bodies must survive exactly one own new claim')
    bodies = closing['reservations']
    require(all(type(v['storage_bytes']) is int and v['storage_bytes'] >= 0
                for v in bodies.values()), 'full integer closing claims required')
    statuses = dict(Counter(v['status'] for v in bodies.values()))
    claims = sum(v['storage_bytes'] for v in bodies.values() if v['status'] != 'released')
    require((statuses, claims) == ({'released': 436, 'retained': 101}, 44381777216),
            'prior statuses/full nonreleased claims or own release differs')
    return dict(**result, closing_record_count=537, closing_record_body_hash_map_sha256=digest(last),
        closing_record_status_counts=statuses), last[own_id]


def qualify_schedulers(baseline, opening, closing):
    prior = baseline['scheduler_observation']
    require(prior['resource_contract'] == CONTRACT, 'frozen resource envelope differs')
    for scheduler in (opening, closing):
        require(scheduler['schema_version'] == prior['schema_version']
                and scheduler['config'] == prior['config']
                and digest(scheduler['config']) == prior['config_sha256']
                and type(scheduler['leases']) is dict and type(scheduler['waiters']) is dict,
                'saved scheduler schema/config or typed occupancy differs')
    require(len(opening['leases']) == prior['lease_count'] and len(opening['waiters']) == prior['waiter_count'],
            'Exact baseline opening occupancy counts required')
    return prior['config_sha256']


def resource_producers(baseline):
    require(len(RESOURCE_PRODUCER_PINS) == 10, 'Closed ten resource producer names required')
    result = {}
    for path, expected in RESOURCE_PRODUCER_PINS.items():
        approved = baseline['artifacts'].get(path)
        require(type(approved) is dict and approved.get('path') == path
                and all(approved.get(key) == expected[key] for key in ('bytes', 'sha256')),
                'Exact authenticated baseline resource producer binding required')
        result[path] = approved
    return result


def qualify_check(check, baseline, phase, producers):
    require(check['schema'] == 'scope-pilot-resource-compatibility/v1'
            and check['passed'] is True and check['findings'] == []
            and check['resources'] == CONTRACT and all(type(check['resources'][k]) is int for k in CONTRACT)
            and check['physical_run_root'] == str(RUN)
            and type(check['disk_limit_bytes']) is int and check['disk_limit_bytes'] == 145000000000
            and type(check['outstanding_full_reservations_bytes']) is int
            and check['outstanding_full_reservations_bytes'] == 44381777216
            and type(check['lease_count']) is int and type(check['waiter_count']) is int
            and check['lease_count'] == baseline['scheduler_observation']['lease_count']
            and check['waiter_count'] == baseline['scheduler_observation']['waiter_count']
            and check['shared_config'] == baseline['scheduler_observation']['config'],
            'actual pre-admission metadata differs')
    require(all(check[k] is False for k in ('admission_guaranteed', 'continuous_lease_coverage_claimed',
            'reservation_acquired', 'scheduler_client_constructed', 'model_started', 'shared_state_modified')),
            'pre-admission check scope differs')
    for key, name, source in (('disk_ledger', 'ledger', LEDGER), ('shared_state', 'scheduler', SCHEDULER)):
        require(check[key]['path'] == str(source) and all(check[key][k] == phase[name][k]
                for k in ('bytes', 'sha256')), 'pre-admission check/private phase identity differs')
    require(set(check['producers']) == set(producers) and len(producers) == 10
            and all(all(check['producers'][p][k] == v[k] for k in ('bytes', 'sha256'))
                    for p, v in producers.items()), 'all ten producer pins must remain exact')


def qualify_own(record, wrappers, attempt_identity):
    final = wrappers['resources-final.json']
    start = wrappers['resources-start.json']
    terminal = wrappers['guardian-exit.json']
    child_exit = wrappers['child-exit.json']
    child = wrappers['child-identity.json']
    cleanup = wrappers['owned-group-final.json']
    own_id = final['owner']['reservation_id']
    require(type(own_id) is str and record['reservation_id'] == own_id
            and digest(record) == digest(final['owner']['record'])
            and start['reservation_id'] == start['record']['reservation_id'] == own_id,
            'exact own terminal/start record identity differs')
    require(terminal['schema'] == 'scope-pilot-guardian-exit/v1'
            and all(type(v) is int and v == 0 for v in (terminal['returncode'], terminal['child_returncode'],
                                                        child_exit['returncode']))
            and child_exit['leader_reaped'] is True, 'successful guardian/child0/reap required')
    require(record['child'] == child == cleanup['identity']
            and record['attempt_directory'] == attempt_identity
            and cleanup['leader_reaped'] is True and type(cleanup['leader_returncode']) is int
            and cleanup['leader_returncode'] == 0 and type(cleanup['live_group_processes']) is int
            and cleanup['live_group_processes'] == 0, 'own attempt/child cleanup identity differs')
    require(all(type(record[k]) is int and record[k] == v for k, v in RESOURCES.items()),
            'own unchanged reserved envelope differs')
    require(record['status'] == 'released' and record['artifacts_durable_asserted'] is True
            and record['attempt_exceeded_reservation'] is False
            and type(record['final_total_charged_bytes']) is int
            and 0 <= record['final_total_charged_bytes'] <= 200000000
            and terminal['artifacts_durable'] is True and terminal['resource_reservation_released'] is True
            and final['owner']['cleanup_error'] is None, 'durable own200M successful release required')
    for accounting in (record['last_usage'], record['final_accounting']):
        require(type(accounting['limit_bytes']) is int and accounting['limit_bytes'] == 145000000000
                and type(accounting['charged_bytes']) is int
                and 0 <= accounting['charged_bytes'] <= 145000000000, 'own locked accounting exceeds145B')
    require(type(record['released_at']) in (int, float) and math.isfinite(record['released_at'])
            and record['released_at'] > 0, 'finite own release timestamp required')
    return dict(reservation_id=own_id, record_body_sha256=digest(record), status='released',
        storage_bytes=200000000, attempt_directory=attempt_identity, child=child,
        final_total_charged_bytes=record['final_total_charged_bytes'], released_at=record['released_at'])


def qualify_lease(record, wrappers, scheduler, events):
    config = scheduler['config']
    adoption = wrappers['scheduler-adoption.json']
    binding = wrappers['lease-binding.json']
    final = wrappers['resources-final.json']
    require(adoption['schema'] == 'guardian-adopt-shared-scheduler/v1' and adoption['complete'] is True
            and adoption['shared_config'] == config and adoption['shared_config_sha256'] == digest(config)
            and all(adoption[k] is False for k in ('capacity_changed', 'global_scheduler_cache_modified',
                'model_or_training_started', 'proof_guards_changed', 'reset_performed', 'stale_recovery_called_by_adoption'))
            and all(type(adoption[k]) is int and adoption[k] == 0 for k in ('leases_acquired_by_adoption',
                'leases_cancelled_by_adoption', 'leases_released_by_adoption')), 'scheduler adoption scope differs')
    own = binding['own_fields']
    lease_id = own['lease_id']
    require(type(lease_id) is str and binding['capability_persisted'] is False
            and binding['state_path'] == str(SCHEDULER) and binding['config_sha256'] == digest(config)
            and own['requires_gpu'] is False and own['gpu_memory_mb'] == own['unified_memory_mb'] == 0
            and all(type(own[k]) is int and own[k] == RESOURCES[k]
                    for k in ('cpu_slots', 'memory_mb', 'child_process_slots'))
            and own['owner_pid'] == record['owner_pid']
            and own['lane'] == record['scheduler_lane'] == 'hammer_lean', 'own lease envelope/owner differs')
    require(lease_id not in scheduler['leases'], 'Exact own scheduler lease must be absent from terminal copy')
    starts = [e for e in events if e.get('schema') == 'guardian-owned-lease-watchdog-start/v1']
    samples = [e for e in events if e.get('schema') == 'guardian-owned-lease-observation/v1']
    require(len(starts) == 1 and starts[0]['binding'] == binding and starts[0]['poll_seconds'] == 1.0
            and starts[0]['maximum_observation_gap_seconds'] == 5.0
            and starts[0]['continuous_coverage_claimed'] is False
            and samples and len(samples) + 1 == len(events), 'exact sampled lease log required')
    for event in samples:
        require(event['healthy'] is True and event['configuration_matches'] is True
                and event['continuous_coverage_claimed'] is False and event['lease_id'] == lease_id
                and event['capability_persisted'] is False and event['read_only'] is True
                and event['expected_config_sha256'] == event['observed_config_sha256'] == digest(config)
                and event['changed_known_configuration_fields'] == []
                and event['unknown_configuration_fields_present'] is False
                and (event['expected'] == 'absent' or event['owned_identity_matches'] is True
                     and event['lease_present'] is True), 'healthy exact lease sample required')
    require({'pre_spawn', 'post_spawn', 'pre_finalize'} <= {e['stage'] for e in samples}
            and samples[-1]['stage'] == 'post_finalize' and samples[-1]['expected'] == 'absent'
            and samples[-1]['lease_present'] is False and final['lease_absent'] == samples[-1]
            and final['continuous_lease_coverage_claimed'] is False, 'own sampled lease release closure differs')
    require(all(type(e['observed_at_monotonic']) in (int, float) for e in samples)
            and all(a['observed_at_monotonic'] <= b['observed_at_monotonic'] for a, b in zip(samples, samples[1:]))
            and all(0 <= e.get('observation_gap_seconds', 0) <= 5
                    for e in samples if e['stage'] in {'monitor', 'post_spawn'}), 'lease sample order/gap differs')
    return len(samples)


def qualify_rss(wrappers, events, rss_events_pin):
    rss = wrappers['group-rss-summary.json']
    child = wrappers['child-identity.json']
    terminal = wrappers['guardian-exit.json']
    child_exit = wrappers['child-exit.json']
    require(rss['identity'] == child and rss['memory_limit_bytes'] == 1536 * 1024 * 1024
            and rss['failure'] is None and rss['events'] == rss_events_pin, 'saved RSS identity/pin differs')
    counts = dict(Counter(e['phase'] for e in events))
    require(set(counts) <= {'gated', 'model', 'post_model'} and 0 < len(events) <= 1024, 'bounded RSS phases required')
    previous = None
    for event in events:
        observed, gap = event['observed_at_monotonic'], event['observation_gap_seconds']
        require(type(observed) in (int, float) and observed >= rss['sampler_started_at_monotonic']
                and event['sample_elapsed_seconds'] >= 0 and event['scheduler_or_claim_mutation'] is False,
                'RSS timestamp/read-only scope differs')
        require((gap is None) if previous is None else (type(gap) in (int, float) and 0 <= gap <= 5
                and abs(gap - (observed - previous)) <= 1e-8), 'RSS sampled timestamp/gap differs')
        previous = observed
        require(event['schema'] == 'guardian-owned-group-rss-observation/v1' and event['identity'] == child
                and event['memory_limit_bytes'] == 1536 * 1024 * 1024
                and type(event['group_rss_bytes']) is int and 0 <= event['group_rss_bytes'] <= 1536 * 1024 * 1024
                and event['sampled_only'] is True and event['kernel_hard_cap'] is False, 'RSS observed envelope differs')
    for phase in ('gated', 'model', 'post_model'):
        samples = [e for e in events if e['phase'] == phase]
        require(counts.get(phase, 0) == rss['sample_counts_by_phase'][phase]
                and max((e['group_rss_bytes'] for e in samples), default=0) == rss['sampled_peaks_by_phase'][phase]
                and (samples[0]['observed_at_monotonic'] if samples else None) == rss['first_observation_monotonic_by_phase'][phase]
                and (samples[-1]['observed_at_monotonic'] if samples else None) == rss['last_observation_monotonic_by_phase'][phase]
                and max((e['observation_gap_seconds'] for e in samples if e['observation_gap_seconds'] is not None),
                        default=0.0) == rss['max_observation_gap_seconds_by_phase'][phase], 'RSS aggregate reconstruction differs')
    require(rss['model_phase_sample_count'] > 0 and rss['sampled_peak_only'] is True
            and rss['model_phase_sample_count'] == rss['sample_counts_by_phase']['model']
            and rss['sampled_model_phase_peak_rss_bytes'] == rss['sampled_peaks_by_phase']['model']
            and rss['absolute_peak_measured'] is False and rss['continuous_coverage_claimed'] is False
            and rss['poll_seconds'] == 1.0 and rss['kernel_hard_cap'] is False
            and rss['scheduler_or_claim_mutation'] is False
            and abs(rss['model_phase_wall_seconds'] - (rss['model_leader_reaped_at_monotonic']
                    - rss['model_gate_permitted_at_monotonic'])) <= 1e-8
            and 0 <= rss['model_phase_wall_seconds'] <= 300
            and 0 <= child_exit['launch_through_reap_wall_seconds'] <= 300
            and terminal['sampled_model_phase_peak_rss_bytes'] == rss['sampled_model_phase_peak_rss_bytes']
            and terminal['model_phase_RSS_sample_count'] == rss['model_phase_sample_count']
            and terminal['model_phase_peak_is_sampled'] is True and terminal['kernel_hard_memory_cap'] is False,
            'sampled RSS/deadline qualification differs')
    return dict(model_phase_wall_seconds=rss['model_phase_wall_seconds'],
        sampled_model_phase_peak_rss_bytes=rss['sampled_model_phase_peak_rss_bytes'],
        model_phase_RSS_sample_count=rss['model_phase_sample_count'])


def qualify_opening_inputs(inputs, baseline):
    require(inputs['opening_snapshot'] == baseline['private_sample_receipt']
            and inputs['metadata_check'] == baseline['fresh_metadata_check'],
            'Exact baseline-bound real opening sample and contemporaneous metadata check required')


def qualify_public_custody(plan, review, plan_pin, review_pin, producers, wrappers=None):
    require(plan['schema'] == 'actor-features-cell-plan/v1' and plan['cell'] == CELL
            and plan['attempt_name'] == ATTEMPT_NAME and plan['package_root'] == str(N / 'datasets')
            and plan['runner_path'] == str(N / 'run_actor_features_v02.py')
            and plan['guardian_path'] == str(N / 'run_scope_guardian_v02.py'), 'exact owned plan custody required')
    require(review['schema'] == 'actor-features-concrete-training-independent-review/v1' and review['passed'] is True
            and review['findings'] == [] and review['phase'] == 'training'
            and review['plan_sha256'] == plan_pin['sha256'] and review['package_root'] == plan['package_root']
            and review['run_root'] == str(RUN), 'exact source-bound training review required')
    for label in ('runner', 'guardian'):
        producer = producers[label]
        require(producer['path'] == plan[label + '_path'] and review[label + '_sha256'] == producer['sha256']
                and plan['artifacts'][producer['path']] == {k: producer[k] for k in ('bytes', 'sha256')},
                'qualified runtime producer identity differs')
    approved_plan = review['artifacts'].get(plan_pin['path'])
    require(approved_plan in (plan_pin, {k: plan_pin[k] for k in ('bytes', 'sha256')}), 'review must close exact plan bytes')
    if wrappers is None:
        return
    pre, command = wrappers['pre-admission.json'], wrappers['command.json']
    require(pre['plan'] == plan_pin and pre['review'] == review_pin
            and pre['runner'] == producers['runner'] and pre['guardian'] == producers['guardian'],
            'actual admission must join exact plan/review/producers')
    argv = command['argv']
    require(type(argv) is list and len(argv) == 6 and type(argv[0]) is str and Path(argv[0]).is_absolute()
            and argv[1:] == [str(N / 'run_actor_features_v02.py'), '--plan', plan_pin['path'], '--output', str(ATTEMPT / 'results')]
            and command['cwd'] == command['candidate_pythonpath'] == plan['package_root']
            and command['resources'] == CONTRACT and command['no_cuda'] is True
            and command['no_proof_workers'] is True and command['model_authority'] is False,
            'exact guarded child command and envelope required')


def audit(event, args):
    if event == 'import' and args[0].split('.')[0] in {'torch', 'numpy', 'ipfs_datasets_py',
            'transformers', 'sentence_transformers'}:
        raise ValueError('production/numerical import prohibited')
    if event.startswith(('subprocess.', 'socket.', 'os.exec', 'os.spawn')) or event in {
            'os.system', 'os.fork', 'os.posix_spawn', 'os.kill', 'os.killpg', 'fcntl.flock',
            'os.remove', 'os.mkdir', 'os.rmdir', 'os.rename', 'os.replace', 'os.unlink'}:
        raise ValueError('process/network/lock/shared mutation prohibited')
    if event == 'open':
        path, mode, flags = args
        target = Path(os.fsdecode(path)).absolute() if isinstance(path, (str, bytes, os.PathLike)) else None
        require(target not in {LEDGER, SCHEDULER} and (target is None or
                ('checkpoint' not in target.name and 'reference-packet' not in target.name)),
                'live/model/reference open prohibited')
        writing = isinstance(mode, str) and any(c in mode for c in 'wax+')
        writing |= isinstance(flags, int) and bool(flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND))
        if writing:
            require(target == OUTPUT and bool(flags & os.O_EXCL), 'only own exclusive receipt write permitted')
        else:
            require(target in ALLOWED_READS, 'only exact approved input reads permitted')
    if event in {'os.chmod', 'os.chown', 'os.truncate', 'os.utime', 'os.link', 'os.symlink'}:
        require(event == 'os.chmod' and Path(args[0]).absolute() == OUTPUT and args[1] == 0o444,
                'only own receipt freeze permitted')


def main():
    global OUTPUT, INPUTS
    require(BASELINE_PIN is not None, 'Exact frozen N10 baseline pin must be set before qualification')
    require(sys.argv[1:] in ([], ['--opening']), 'only optional --opening mode is allowed')
    phase_only = sys.argv[1:] == ['--opening']
    if phase_only:
        INPUTS = N / 'actor-features-opening-resource-inputs-v02.json'
        OUTPUT = N / 'actor-features-ce-opening-resource-audit-v02.json'
        ALLOWED_READS.add(INPUTS)
    require(not os.path.lexists(OUTPUT), 'exclusive new terminal receipt required')
    sys.addaudithook(audit)
    own = pin(Path(__file__).resolve())
    approval = read(APPROVAL)
    require(approval['schema'] == 'actor-features-terminal-resource-source-independent-review/v1'
            and approval['passed'] is True and approval['findings'] == [] and approval['observer'] == own,
            'independent exact-observer source qualification required')
    inputs = read(INPUTS)
    require(inputs['schema'] == 'actor-features-terminal-resource-inputs/v1'
            and inputs['passed'] is True and inputs['findings'] == []
            and inputs['cell'] == CELL and inputs['attempt_name'] == ATTEMPT_NAME,
            'root-approved exact saved input manifest required')
    require(inputs['baseline'] == BASELINE_PIN, 'exact frozen baseline descriptor required')
    bind(BASELINE_PIN, BASELINE)
    baseline = read(BASELINE)
    qualify_retry_baseline(baseline)
    for path, expected in PRIOR_SOURCE_PINS.items():
        bind(dict(path=path, **expected), Path(path))
    for path, expected in baseline['artifacts'].items():
        require('/private-runtime-snapshots/' not in path and path not in (str(LEDGER), str(SCHEDULER)),
                'baseline public closure cannot contain private/live bodies')
        bind(expected, Path(path))
    plan_path = bind(inputs['plan'], N / (CELL + '-plan-v02.json'))
    plan = read(plan_path)
    require(plan['cell'] == CELL and plan['attempt_name'] == ATTEMPT_NAME, 'exact saved plan identity differs')
    review_path = bind(inputs['training_review'], N / (CELL + '-training-review-v02.json'))
    review = read(review_path)
    require(review['schema'] == 'actor-features-concrete-training-independent-review/v1'
            and review['passed'] is True and review['findings'] == [] and review['phase'] == 'training'
            and review['plan_sha256'] == inputs['plan']['sha256'], 'qualified saved training review differs')
    runtime_producers = {}
    for key, label in (('runner_path', 'runner'), ('guardian_path', 'guardian')):
        producer_path = Path(plan[key]); producer = dict(path=str(producer_path), **plan['artifacts'][str(producer_path)])
        bind(producer, producer_path)
        runtime_producers[label] = producer
    qualify_public_custody(plan, review, inputs['plan'], inputs['training_review'], runtime_producers)
    qualify_opening_inputs(inputs, baseline)
    phase, opening, opening_scheduler = snapshot(inputs['opening_snapshot'], 'opening')
    config_sha = qualify_schedulers(baseline, opening_scheduler, opening_scheduler)
    conservation = qualify_phase_ledger(baseline, opening)
    producers = resource_producers(baseline)
    check_path = descriptor(inputs['metadata_check'])
    require(check_path.parent == N and check_path.name == 'guardian-check-v02.json'
            and check_path.suffix == '.json', 'exact owned pre-admission metadata path required')
    bind(inputs['metadata_check'])
    qualify_check(read(check_path), baseline, phase, producers)
    for item in baseline['counted_root_metadata'] + [baseline['run_root_identity']]:
        require(root_identity(Path(item['path'])) == item, 'physical counted/run root identity differs')
    if phase_only:
        for path, expected in list(READ_PINS.items()):
            require(pin(Path(path)) == expected, 'closing full consumed phase input identity differs')
        value = dict(schema='actor-features-opening-resource-audit/v1', passed=True, findings=[],
            observed_at_utc=datetime.now(timezone.utc).isoformat(), phase='saved-opening-qualification', cell=CELL,
            reviewer='/root/runtime_protocol_n9', observer=own, input_manifest=READ_PINS[str(INPUTS)],
            source_qualification=READ_PINS[str(APPROVAL)], baseline=BASELINE_PIN, plan=inputs['plan'],
            training_review=inputs['training_review'], metadata_check=inputs['metadata_check'],
            global_cap_bytes=145000000000, counted_root_metadata=baseline['counted_root_metadata'],
            run_root_identity=baseline['run_root_identity'], scheduler_config_sha256=config_sha,
            scheduler_lease_count=len(opening_scheduler['leases']), scheduler_waiter_count=len(opening_scheduler['waiters']),
            sampled_coexistence=True, all_ten_resource_producer_pins_unchanged=True,
            private_sample_receipt=inputs['opening_snapshot'],
            private_endpoint_pin_descriptors=[phase['ledger'], phase['scheduler']],
            private_record_bodies_published=False, individual_prior_records_published=False,
            admission_guaranteed=False, resource_API_calls_by_reviewer=0,
            global_endpoint_body_reads_by_reviewer=0, model_or_encoder_calls_by_reviewer=0,
            checkpoint_JSON_parses_by_reviewer=0, reference_packet_reads_by_reviewer=0,
            shared_state_modified_by_reviewer=False, shared_tree_censuses_by_reviewer=0,
            continuous_coverage_claimed=False, prior_observer_source_pins=PRIOR_SOURCE_PINS,
            artifacts={p: v for p, v in READ_PINS.items() if '/private-runtime-snapshots/' not in p},
            **conservation)
        write_output(value)
        print(json.dumps(dict(passed=True, receipt=str(OUTPUT), preserved_prior_records=536,
                             scheduler_lease_count=len(opening_scheduler['leases']), scheduler_waiter_count=len(opening_scheduler['waiters']))))
        return
    terminal_sample, closing, closing_scheduler = snapshot(inputs['terminal_snapshot'], 'terminal')
    config_sha = qualify_schedulers(baseline, opening_scheduler, closing_scheduler)
    require(set(inputs['runtime_artifacts']) == set(WRAPPERS), 'exact fourteen own wrapper descriptors required')
    wrappers = {}
    for name in WRAPPERS:
        path = bind(inputs['runtime_artifacts'][name], ATTEMPT / name)
        if not name.endswith('.jsonl'):
            wrappers[name] = read(path)
    qualify_public_custody(plan, review, inputs['plan'], inputs['training_review'], runtime_producers, wrappers)
    lease_events = lines(ATTEMPT / 'lease-observations.jsonl')
    rss_events = lines(ATTEMPT / 'group-rss-observations.jsonl')
    final = wrappers['resources-final.json']
    own_id = final['owner']['reservation_id']
    require(own_id in closing['reservations'], 'own new terminal claim absent')
    conservation, own_hash = qualify_ledgers(baseline, opening, closing, own_id)
    own_claim = qualify_own(closing['reservations'][own_id], wrappers, root_identity(ATTEMPT))
    require(own_hash == own_claim['record_body_sha256'], 'own raw body hash differs')
    require(terminal_sample['plan'] == inputs['plan']
            and terminal_sample['terminal'] == inputs['runtime_artifacts']['guardian-exit.json'],
            'terminal copy producer plan/exit identity differs')
    lease_count = qualify_lease(closing['reservations'][own_id], wrappers, closing_scheduler, lease_events)
    require(final['lease_events'] == inputs['runtime_artifacts']['lease-observations.jsonl']
            and final['group_rss_summary'] == inputs['runtime_artifacts']['group-rss-summary.json'],
            'final sampled observation pins differ')
    rss = qualify_rss(wrappers, rss_events, inputs['runtime_artifacts']['group-rss-observations.jsonl'])
    for path, expected in list(READ_PINS.items()):
        require(pin(Path(path)) == expected, 'closing full consumed input identity differs')
    artifacts = {path: value for path, value in READ_PINS.items()
                 if '/private-runtime-snapshots/' not in path and Path(path).name not in ('resources-start.json', 'resources-final.json')}
    value = dict(schema='actor-features-terminal-resource-audit/v1', passed=True, findings=[],
        observed_at_utc=datetime.now(timezone.utc).isoformat(), phase='terminal', cell=CELL,
        reviewer='/root/runtime_protocol_n9', observer=own, input_manifest=READ_PINS[str(INPUTS)],
        source_qualification=READ_PINS[str(APPROVAL)], baseline=BASELINE_PIN, plan=inputs['plan'],
        training_review=inputs['training_review'], metadata_check=inputs['metadata_check'],
        only_new_own_claim=own_claim, global_cap_bytes=145000000000,
        counted_root_metadata=baseline['counted_root_metadata'], run_root_identity=baseline['run_root_identity'],
        scheduler_config_sha256=config_sha, scheduler_lease_count=len(closing_scheduler['leases']), scheduler_waiter_count=len(closing_scheduler['waiters']),
        opening_scheduler_lease_count=len(opening_scheduler['leases']), opening_scheduler_waiter_count=len(opening_scheduler['waiters']), sampled_coexistence=True,
        own_scheduler_lease_absent=True, all_ten_resource_producer_pins_unchanged=True,
        saved_lease_observations=lease_count, private_sample_receipts=dict(opening=inputs['opening_snapshot'], terminal=inputs['terminal_snapshot']),
        private_endpoint_pin_descriptors=[phase['ledger'], phase['scheduler'], terminal_sample['ledger'], terminal_sample['scheduler']],
        private_owned_resource_wrapper_pin_descriptors={name: inputs['runtime_artifacts'][name]
            for name in ('resources-start.json', 'resources-final.json')},
        private_record_bodies_published=False, individual_prior_records_published=False,
        sampled_coverage_only=True, continuous_coverage_claimed=False, absolute_peak_measured=False,
        kernel_hard_memory_cap=False, model_or_encoder_calls_by_reviewer=0,
        checkpoint_JSON_parses_by_reviewer=0, reference_packet_reads_by_reviewer=0,
        resource_API_calls_by_reviewer=0, global_endpoint_body_reads_by_reviewer=0,
        shared_state_modified_by_reviewer=False, shared_tree_censuses_by_reviewer=0,
        semantic_qualification=False, artifacts=artifacts, prior_observer_source_pins=PRIOR_SOURCE_PINS,
        **conservation, **rss)
    write_output(value)
    print(json.dumps(dict(passed=True, receipt=str(OUTPUT), opening=536, closing=537,
                         preserved_prior_records=536, own_claim_released=True)))


def write_output(value):
    with OUTPUT.open('xb') as stream:
        stream.write(json.dumps(value, sort_keys=True, indent=2, allow_nan=False).encode() + b'\n')
        stream.flush()
        os.fsync(stream.fileno())
    OUTPUT.chmod(0o444)


if __name__ == '__main__':
    main()
