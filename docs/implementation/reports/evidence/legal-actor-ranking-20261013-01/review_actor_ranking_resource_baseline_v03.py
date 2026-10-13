"""Qualify new private opening copies against N8's authenticated 535 records.

Reads only the two declared new private copies, never the live ledger/scheduler.
No resource API, model, checkpoint, census, subprocess, network or foreign write.
"""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import stat
import sys

F = Path(__file__).resolve().parent
N8 = F.parent / 'legal-actor-boundary-20261013-01'
RUN = Path('/home/barberb/lift_coding/external/ipfs_datasets/workspace/test-logs/legal-trigger-readout-pilot-20261007-01')
LEDGER = RUN.parent / 'federal-corpus-audits/owned-daemon-resource-control/disk-reservations.json'
SCHEDULER = Path('/tmp/ipfs-datasets-resource-scheduler-1000.json')
OUTPUT = F / 'resource-baseline-v03.json'
QUALIFICATION = F / 'resource-observer-source-independent-review-v03.json'
RESOURCES = dict(cpu_slots=2, memory_mb=1536, child_process_slots=1,
                 storage_bytes=200000000, child_deadline_seconds=300,
                 admission_timeout_seconds=120, ledger_lock_timeout_seconds=60)
GUARDIAN_SHA = 'b4811b7b24f584d5cb0f7c921451a234a3e0d84b2d7507e015426e258134c2db'
FAILED_CLAIMS = ('c3e6fbcf39d146cd85f12617d320b153', '893d4ed80ab3497f95b1490080e3caa3')
RESOURCE_PRODUCER_PINS = {'/home/barberb/lift_coding/external/ipfs_datasets/workspace/test-logs/decoder-normative-wording-r2-20261006/adopt_shared_scheduler.py': {'bytes': 11206, 'sha256': '4956baa1e41abe53fc83a2d4ae7709b3be13ebc1c775b44571a33903b8f70b1f'}, '/home/barberb/lift_coding/external/ipfs_datasets/workspace/test-logs/decoder-normative-wording-r2-20261006/lazy_scheduler_adoption.py': {'bytes': 1345, 'sha256': '42f31d8da1eb5b44274ca0b8c8180cd78bc083dfd0e93438e61f38223929d84a'}, '/home/barberb/lift_coding/external/ipfs_datasets/workspace/test-logs/decoder-normative-wording-r2-20261006/owned_lease_watchdog.py': {'bytes': 20712, 'sha256': 'f1b9f71e375cf5ed4004e023bbef2d6f7f61e1ecb588078a1094d7b1982609b3'}, '/home/barberb/lift_coding/external/ipfs_datasets/workspace/test-logs/native4096-four-width-20261004/resource-cap/autoencoder_daemon_resources.py': {'bytes': 36724, 'sha256': 'b00d2752ba852fe73760bba4fbd51b0e845742c3527642606a2a77ed9f8f5e2c'}, '/home/barberb/lift_coding/external/ipfs_datasets/workspace/test-logs/ui-modal-coverage-20261002/validation-source-r2/ipfs_datasets_py/__init__.py': {'bytes': 56829, 'sha256': 'f258f8eada774251feacd8e2ee2048efe56c89a8ee88efd50e4271ea41d43dc9'}, '/home/barberb/lift_coding/external/ipfs_datasets/workspace/test-logs/ui-modal-coverage-20261002/validation-source-r2/ipfs_datasets_py/optimizers/__init__.py': {'bytes': 957, 'sha256': 'a12bab3724da07be67b447719ace42fc1f480cb5635581f320a99a372f02f450'}, '/home/barberb/lift_coding/external/ipfs_datasets/workspace/test-logs/ui-modal-coverage-20261002/validation-source-r2/ipfs_datasets_py/optimizers/logic_theorem_optimizer/__init__.py': {'bytes': 69336, 'sha256': '9d693fa576f00dc36899faad75ef3044c437e2bfec5c62306f7031236725bb0e'}, '/home/barberb/lift_coding/external/ipfs_datasets/workspace/test-logs/ui-modal-coverage-20261002/validation-source-r2/ipfs_datasets_py/optimizers/logic_theorem_optimizer/proof_resource_safety.py': {'bytes': 4534, 'sha256': '23569b40b44d9130c30c62be564d58908a509fb1f40c6377e89f2fc1e3c799c5'}, '/home/barberb/lift_coding/external/ipfs_datasets/workspace/test-logs/ui-modal-coverage-20261002/validation-source-r2/ipfs_datasets_py/optimizers/logic_theorem_optimizer/resource_scheduler.py': {'bytes': 82754, 'sha256': 'a418e84f70ed8509ba0518feea69e7a8c27865139f83b6c81349eefdfd5893a4'}, '/home/barberb/lift_coding/external/ipfs_datasets/workspace/test-logs/ui-modal-coverage-20261002/validation-source-r2/ipfs_datasets_py/optimizers/logic_theorem_optimizer/runtime_telemetry.py': {'bytes': 53075, 'sha256': '542f705867b93fcb138a117e1f5c97a144ad6635dc92c37bc5034eee5065ef63'}}
PREVIOUS_RESOURCE_PRODUCER_PINS = dict(RESOURCE_PRODUCER_PINS)
BRIDGE_REPLACEMENTS = {
    '/home/barberb/lift_coding/external/ipfs_datasets/workspace/test-logs/decoder-normative-wording-r2-20261006/adopt_shared_scheduler.py': dict(path=str(F/'adopt_shared_scheduler_actor_ranking_v02.py'),bytes=15101,sha256='526aa9fa55d955eb92dba37053af2dfdf01f7dd8335cd309cb36770988bab0b7'),
    '/home/barberb/lift_coding/external/ipfs_datasets/workspace/test-logs/decoder-normative-wording-r2-20261006/owned_lease_watchdog.py': dict(path=str(F/'owned_lease_watchdog_actor_ranking_v02.py'),bytes=24435,sha256='6355884b6737c5b0e5cd1a128ad70a09fcf304f27bbf32492a15d8dbe070b032')}
for old_path,new in BRIDGE_REPLACEMENTS.items():
    del RESOURCE_PRODUCER_PINS[old_path]
    RESOURCE_PRODUCER_PINS[new['path']] = {k:new[k] for k in ('bytes','sha256')}
PUBLIC_PRIOR_PINS = {
    'prior_final': dict(path=str(N8/'final-integration-independent-review-v01.json'), bytes=287372, sha256='b478dbc9a2964b88cbaef40d36380fbad4c761ff3828dea44052be6bd5807eec'),
    'prior_HF_actual': dict(path=str(N8/'hf-publication-actual-independent-review-v01.json'), bytes=166244, sha256='7acc5d1f7cdf41cacecfeb7b833b2bb05f9fcf46975561dee7953221016a6995'),
    'prior_baseline': dict(path=str(N8/'resource-baseline-v02.json'), bytes=79833, sha256='f8fcc274170d7b46e6c659e465f0eeba059913c42d3135db6712c4dbe4714aa4'),
    'prior_terminal': dict(path=str(N8/'actor-boundary-ce-terminal-resource-audit-v04.json'), bytes=29389, sha256='e2ba92f14e57f7d5a44a56e8740814396a75f18e1eb4b9bb3bd162adbcd3511b')}
READS = {}
PRIVATE = set()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def pin(path):
    path = Path(path)
    require(path.is_absolute() and path.resolve(strict=True) == path and not path.is_symlink(), 'physical absolute ordinary file required')
    require(path not in (LEDGER, SCHEDULER), 'live global endpoint bodies forbidden')
    require('checkpoint' not in path.name and 'reference-packet' not in path.name, 'checkpoint/gold access forbidden')
    require('private-runtime-snapshots' not in path.parts or path in PRIVATE, 'only exact new opening copies allowed')
    before = path.stat()
    require(stat.S_ISREG(before.st_mode) and before.st_size <= 16777216, 'bounded ordinary source required')
    raw = path.read_bytes()
    identity = lambda v: (v.st_dev, v.st_ino, v.st_size, v.st_mtime_ns, v.st_ctime_ns)
    require(identity(before) == identity(path.stat()) and len(raw) == before.st_size, 'raw read drift')
    return dict(path=str(path), bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())


def read(descriptor):
    require(type(descriptor) is dict and set(descriptor) == {'path', 'bytes', 'sha256'}, 'closed raw descriptor required')
    path = Path(descriptor['path'])
    require(pin(path) == descriptor, 'input pin mismatch')
    raw = path.read_bytes()
    require(len(raw) == descriptor['bytes'] and hashlib.sha256(raw).hexdigest() == descriptor['sha256'] and pin(path) == descriptor, 'consumed bytes differ')
    require(str(path) not in READS or READS[str(path)] == descriptor, 'previous consumed identity drift')
    READS[str(path)] = descriptor
    def pairs(items):
        value = {}
        for key, item in items:
            require(key not in value, 'duplicate JSON key')
            value[key] = item
        return value
    def finite(value):
        number = float(value)
        require(math.isfinite(number), 'nonfinite JSON number')
        return number
    return json.loads(raw, object_pairs_hook=pairs, parse_float=finite,
                      parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))


def prior_hashes(baseline, terminal):
    require(baseline['schema'] == 'actor-boundary-resource-baseline/v1' and baseline['passed'] is True and baseline['findings'] == [], 'qualified N8 baseline required')
    require(terminal['schema'] == 'actor-boundary-terminal-resource-audit/v1' and terminal['passed'] is True and terminal['findings'] == [], 'qualified N8 terminal required')
    hashes = dict(baseline['baseline_ledger']['record_body_hashes'])
    require(len(hashes) == terminal['opening_record_count'] == terminal['preserved_prior_record_count'] == 534
            and digest(hashes) == terminal['prior_record_body_hash_map_sha256']
            and terminal['all_previous534_record_bodies_unchanged'] is True
            and terminal['failed_N7_claim_retained_and_fully_charged'] is True
            and terminal['failed_actor_claim_retained_and_fully_charged'] is True, 'authenticated prior534 map mismatch')
    claim = terminal['only_new_own_claim']
    require(claim['reservation_id'] == 'c763adb4bf214a2db186a784e76858f7' and claim['reservation_id'] not in hashes
            and claim['status'] == 'released' and claim['storage_bytes'] == 200000000, 'released N8 own claim required')
    hashes[claim['reservation_id']] = claim['record_body_sha256']
    require(len(hashes) == terminal['closing_record_count'] == 535
            and digest(hashes) == terminal['closing_record_body_hash_map_sha256'], 'authenticated terminal535 map mismatch')
    return hashes


def qualify_ledger(ledger, baseline, terminal):
    old = prior_hashes(baseline, terminal)
    require(ledger['schema'] == 'daemon-resource-reservations-v1' and type(ledger['limit_bytes']) is int
            and ledger['limit_bytes'] == terminal['global_cap_bytes'] == 145000000000, 'global ledger cap/schema changed')
    require(ledger['roots'] == terminal['counted_root_metadata'] == baseline['counted_root_metadata']
            and len(ledger['roots']) == 4, 'counted four roots changed')
    bodies = ledger['reservations']
    require(type(bodies) is dict and len(bodies) == 535 and all(type(k) is str and type(v) is dict for k, v in bodies.items()), 'exact full535 reservation map required')
    hashes = {key: digest(value) for key, value in bodies.items()}
    require(hashes == old, 'a prior535 body was modified, added or removed')
    for key, body in bodies.items():
        require(body.get('reservation_id') == key and body.get('status') in {'reserved', 'active', 'retained', 'released'}
                and type(body.get('storage_bytes')) is int and body['storage_bytes'] >= 0, 'valid full claims required')
    require(all(bodies[key]['status'] == 'retained' and bodies[key]['storage_bytes'] == 200000000 for key in FAILED_CLAIMS),
            'failed N7 and N8 claims must remain retained and charged')
    claims = sum(body['storage_bytes'] for body in bodies.values() if body['status'] != 'released')
    statuses = dict(Counter(body['status'] for body in bodies.values()))
    require((statuses, claims) == ({'released': 433, 'retained': 102}, 44581777216)
            and claims + RESOURCES['storage_bytes'] <= ledger['limit_bytes'], 'full claims/headroom or exact statuses differ')
    return hashes, claims, statuses


def audit(event, args):
    if event == 'import' and args[0].split('.')[0] in {'torch', 'numpy', 'ipfs_datasets_py', 'transformers', 'huggingface_hub'}:
        raise ValueError('production/numerical/SDK import forbidden')
    if event.startswith(('subprocess.', 'socket.', 'os.exec', 'os.spawn')) or event in {
            'os.system', 'os.fork', 'os.posix_spawn', 'os.kill', 'os.killpg', 'fcntl.flock',
            'os.mkdir', 'os.remove', 'os.rmdir', 'os.rename', 'os.replace', 'os.unlink'}:
        raise ValueError('process/network/lock/shared mutation forbidden')
    if event == 'open':
        name, mode, flags = args
        target = Path(os.fsdecode(name)).absolute() if isinstance(name, (str, bytes, os.PathLike)) else None
        require(target not in (LEDGER, SCHEDULER), 'live global endpoint bodies forbidden')
        if target is not None:
            require('checkpoint' not in target.name and 'reference-packet' not in target.name, 'checkpoint/gold access forbidden')
            require('private-runtime-snapshots' not in target.parts or target in PRIVATE, 'only declared new private copies allowed')
        writing = isinstance(mode, str) and any(c in mode for c in 'wax+')
        writing |= isinstance(flags, int) and bool(flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND))
        require(not writing or target == OUTPUT, 'only exclusive owned baseline receipt may be written')
    if event in {'os.chmod', 'os.chown', 'os.truncate', 'os.utime', 'os.link', 'os.symlink'}:
        require(event == 'os.chmod' and Path(args[0]).absolute() == OUTPUT and args[1] == 0o444, 'only owned receipt freeze allowed')



def main(args):
    require(not os.path.lexists(OUTPUT), 'exclusive new baseline receipt required')
    sys.dont_write_bytecode = True
    sys.addaudithook(audit)
    own = pin(Path(__file__).resolve())
    qualification_pin = pin(QUALIFICATION)
    qualification = read(qualification_pin)
    require(qualification['passed'] is True and qualification['findings'] == [] and qualification['observer'] == own, 'exact independently reviewed observer required')
    input_pin = dict(path=str(Path(args.inputs)), bytes=args.inputs_bytes, sha256=args.inputs_sha256)
    inputs = read(input_pin)
    require(inputs['schema'] == 'actor-ranking-resource-baseline-inputs/v2' and set(inputs) == {'schema', 'public_pins', 'sample_receipt'}, 'closed baseline inputs required')
    expected_keys = {'prior_final', 'prior_HF_actual', 'prior_baseline', 'prior_terminal', 'guardian', 'sampler', 'sampler_qualification', 'check', 'bridge_qualification'}
    require(set(inputs['public_pins']) == expected_keys, 'closed public baseline inputs required')
    pins = inputs['public_pins']
    require(all(pins[key] == expected for key, expected in PUBLIC_PRIOR_PINS.items()), 'exact authenticated N8 public anchors required')
    require(pins['guardian']['path'] == str(F / 'run_scope_guardian_v02.py') and pins['guardian']['bytes'] == 38449
            and pins['guardian']['sha256'] == GUARDIAN_SHA and pin(Path(pins['guardian']['path'])) == pins['guardian'], 'unchanged guardian required')
    require(pins['sampler']['path'] == str(F / 'sample_actor_ranking_private_resources_v01.py')
            and pin(Path(pins['sampler']['path'])) == pins['sampler'], 'exact adapted sampler required')
    for key in ('guardian', 'sampler'):
        READS[pins[key]['path']] = pins[key]
    bridge = read(pins['bridge_qualification'])
    require(pins['bridge_qualification']['path'] == str(F/'resource-bridge-source-independent-review-v02.json')
            and bridge['schema'] == 'actor-ranking-resource-bridge-source-independent-review/v1'
            and bridge['passed'] is True and bridge['findings'] == [], 'Exact source-qualified local historical metadata bridge required')
    for descriptor in list(BRIDGE_REPLACEMENTS.values()) + [pins['guardian']]:
        require(bridge['artifacts'][descriptor['path']] in (descriptor,{k:descriptor[k] for k in ('bytes','sha256')})
                and pin(Path(descriptor['path'])) == descriptor, 'Exact qualified bridge producer raw bytes required')
        READS[descriptor['path']] = descriptor
    sampler_review = read(pins['sampler_qualification'])
    require(sampler_review['passed'] is True and sampler_review['findings'] == [] and sampler_review['sampler'] == pins['sampler'], 'qualified adapted sampler required')
    final, hub, baseline, terminal = (read(pins[key]) for key in ('prior_final', 'prior_HF_actual', 'prior_baseline', 'prior_terminal'))
    require(final['schema'] == 'actor-boundary-final-integration-independent-review/v1' and final['passed'] is True and final['findings'] == []
            and final['qualified_Hub_publication']['actual_review'] == pins['prior_HF_actual'], 'qualified N8 final/HF join required')
    require(hub['passed'] is True and hub['findings'] == [] and hub['revision'] == 'fa37360840c070f9318d6ad2baef87d785eac504', 'qualified N8 immutable HF review required')
    for key in ('prior_baseline', 'prior_terminal'):
        require(hub['artifacts'][pins[key]['path']] in (pins[key], {k:pins[key][k] for k in ('bytes','sha256')}), 'prior resource evidence absent from qualified HF inventory')
    require(terminal['baseline'] == pins['prior_baseline'], 'prior baseline/terminal join differs')
    sample_pin = inputs['sample_receipt']
    folder = Path(sample_pin['path']).parent
    require(folder.parent == F / 'private-runtime-snapshots' and folder.name.startswith('opening-v')
            and len(folder.name) == len('opening-v01') and folder.name[-2:].isdigit()
            and 1 <= int(folder.name[-2:]) <= 99 and Path(sample_pin['path']).name == 'snapshot-receipt-v01.json', 'exact new owned opening sample required')
    PRIVATE.update(folder / name for name in ('snapshot-receipt-v01.json', 'ledger.json', 'scheduler.json'))
    for directory in (folder.parent, folder):
        require(directory.resolve(strict=True) == directory and stat.S_ISDIR(directory.stat().st_mode)
                and stat.S_IMODE(directory.stat().st_mode) == 0o700, 'physical private700 directory required')
    sample = read(sample_pin)
    require(stat.S_IMODE(Path(sample_pin['path']).stat().st_mode) == 0o400, 'private receipt400 required')
    require(sample['schema'] == 'actor-ranking-private-endpoints/v1' and sample['role'] == 'opening' and sample['cell'] is None
            and sample['index'] == int(folder.name[-2:]) and sample['private_bodies'] is True
            and sample['resource_API_calls'] == 0 and sample['shared_state_modified'] is False
            and sample['continuous_custody'] is False and sample['independent_contemporaneous_copy_witness'] is False,
            'opening sample contract differs')
    for key, endpoint in (('ledger', LEDGER), ('scheduler', SCHEDULER)):
        require(sample[key]['path'] == str(folder / (key + '.json')) and pin(Path(sample[key]['path'])) == sample[key]
                and stat.S_IMODE(Path(sample[key]['path']).stat().st_mode) == 0o400
                and sample['source_' + key]['path'] == str(endpoint)
                and all(sample[key][k] == sample['source_' + key][k] for k in ('bytes', 'sha256')), 'exact private400 endpoint copy required')
    ledger, scheduler = read(sample['ledger']), read(sample['scheduler'])
    hashes, claims, statuses = qualify_ledger(ledger, baseline, terminal)
    old_scheduler = baseline['scheduler_observation']
    require(scheduler['schema_version'] == old_scheduler['schema_version'] and scheduler['config'] == old_scheduler['config']
            and digest(scheduler['config']) == terminal['scheduler_config_sha256'] == old_scheduler['config_sha256'], 'scheduler config changed')
    require(type(scheduler['leases']) is dict and type(scheduler['waiters']) is dict, 'Ordinary sampled occupancy maps required')
    check = read(pins['check'])
    require(check['schema'] == 'scope-pilot-resource-compatibility/v1' and check['passed'] is True and check['findings'] == []
            and check['resources'] == RESOURCES and check['physical_run_root'] == str(RUN)
            and check['disk_limit_bytes'] == 145000000000 and check['outstanding_full_reservations_bytes'] == claims
            and type(check['lease_count']) is int and type(check['waiter_count']) is int
            and check['lease_count'] == len(scheduler['leases']) and check['waiter_count'] == len(scheduler['waiters'])
            and check['shared_config'] == scheduler['config'], 'fresh guardian metadata check differs')
    for key in ('admission_guaranteed', 'continuous_lease_coverage_claimed', 'reservation_acquired', 'scheduler_client_constructed', 'model_started', 'shared_state_modified'):
        require(check[key] is False, 'metadata check grants no admission or mutation authority')
    for role, key in (('disk_ledger', 'ledger'), ('shared_state', 'scheduler')):
        require(all(check[role][k] == sample['source_' + key][k] for k in ('path', 'bytes', 'sha256')), 'check/private copy endpoint snapshot differs')
    require(set(check['producers']) == set(RESOURCE_PRODUCER_PINS), 'exact closed ten resource producer names required')
    for name, expected in check['producers'].items():
        replacement = next((new for new in BRIDGE_REPLACEMENTS.values() if new['path']==name),None)
        if replacement is None:
            old = baseline['artifacts'][name]
            require(all(old[k] == PREVIOUS_RESOURCE_PRODUCER_PINS[name][k] for k in ('bytes','sha256')),
                    'Exact retained eight historical resource producers required')
        else:
            prior_path = next(path for path,new in BRIDGE_REPLACEMENTS.items() if new['path']==name)
            old_prior = baseline['artifacts'][prior_path]
            require(all(old_prior[k] == PREVIOUS_RESOURCE_PRODUCER_PINS[prior_path][k] for k in ('bytes','sha256')),
                    'Replaced historical helper must retain its authenticated prior identity')
            old = replacement
        require(all(expected[k] == old[k] == RESOURCE_PRODUCER_PINS[name][k] for k in ('bytes','sha256')),
                'Only two independently qualified local producer replacements permitted')
        captured = pin(Path(name))
        require(all(captured[k] == expected[k] for k in ('bytes', 'sha256')), 'resource producer current raw bytes differ')
        READS[name] = captured
    for root in terminal['counted_root_metadata'] + [terminal['run_root_identity']]:
        directory = Path(root['path']); info = directory.stat()
        require(directory.resolve(strict=True) == directory and stat.S_ISDIR(info.st_mode)
                and (info.st_dev, info.st_ino) == (root['device'], root['inode']), 'counted/run root identity changed')
    for name, expected in READS.items():
        require(pin(Path(name)) == expected, 'closing consumed identity drift')
    require(pin(Path(__file__).resolve()) == own, 'observer source drift')
    availability = os.statvfs(RUN)
    free = availability.f_bavail * availability.f_frsize
    require(free >= RESOURCES['storage_bytes'], 'sampled physical availability insufficient')
    result = dict(schema='actor-ranking-resource-baseline/v1', passed=True, findings=[], observed_at_utc=datetime.now(timezone.utc).isoformat(),
        observer=own, source_qualification=qualification_pin, input_manifest=input_pin,
        artifacts={name: row for name, row in READS.items() if 'private-runtime-snapshots' not in Path(name).parts},
        qualified_local_guardian=pins['guardian'], resource_bridge_source_qualification=pins['bridge_qualification'],
        historical_resource_producer_pins_preserved=PREVIOUS_RESOURCE_PRODUCER_PINS,
        qualified_resource_producer_replacements=BRIDGE_REPLACEMENTS, adapted_sampler=pins['sampler'], sampler_source_qualification=pins['sampler_qualification'],
        prior_terminal=pins['prior_terminal'], private_sample_receipt=sample_pin, fresh_metadata_check=pins['check'],
        baseline_ledger=dict(path=str(LEDGER), **{k:sample['ledger'][k] for k in ('bytes','sha256')}, schema=ledger['schema'],
            limit_bytes=ledger['limit_bytes'], record_count=len(hashes), record_status_counts=statuses,
            full_nonreleased_claim_bytes=claims, record_body_hashes=hashes, record_body_hash_map_sha256=digest(hashes),
            all_previous535_record_bodies_unchanged=True, additional_current_records=0,
            full_record_bodies_published=False, failed_N7_claim_retained_and_fully_charged=True, failed_N8_claim_retained_and_fully_charged=True),
        counted_root_metadata=terminal['counted_root_metadata'], run_root_identity=terminal['run_root_identity'],
        scheduler_observation=dict(path=str(SCHEDULER), **{k:sample['scheduler'][k] for k in ('bytes','sha256')},
            schema_version=scheduler['schema_version'], config=scheduler['config'], config_sha256=digest(scheduler['config']),
            lease_count=len(scheduler['leases']), waiter_count=len(scheduler['waiters']), resource_contract=RESOURCES,
            sampled_coexistence=True, admission_guaranteed=False),
        physical_availability=dict(sampled_bytes=free, fresh_tree_accounting=False, admission_guaranteed=False),
        sampled_coexistence=True, foreign_lease_or_waiter_IDs_published=False, foreign_lease_or_waiter_bodies_published=False,
        resource_API_calls=0, live_global_body_reads=0, shared_state_modified=False, model_calls=0, checkpoint_JSON_parses=0,
        default_promotion=False, semantic_accuracy=None, continuous_coverage_claimed=False, execution_approval=False,
        limitations=['Copied occupancy and physical availability are sampled; actual capacity, pressure, fairness, admission and counted-tree census belong to the qualified unchanged guardianV02.',
            'All prior full records and any new foreign records are preserved and charged; no release, transfer, expiry or cap change occurs.'])
    with OUTPUT.open('x') as stream:
        json.dump(result, stream, indent=2, sort_keys=True, allow_nan=False); stream.write('\n'); stream.flush(); os.fsync(stream.fileno())
    OUTPUT.chmod(0o444)
    print(json.dumps({'baseline':pin(OUTPUT), 'passed':True}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--inputs', required=True)
    parser.add_argument('--inputs-bytes', required=True, type=int)
    parser.add_argument('--inputs-sha256', required=True)
    main(parser.parse_args())
