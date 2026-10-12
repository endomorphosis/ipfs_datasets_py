"""Independent metadata review of one remaining targeted-loss cell.

Only frozen metadata predicates are extracted from the qualified runner. No
production module, resource client, model, reference packet or compiler is
imported. This helper creates one exclusive review and grants no reservation.
"""
from __future__ import annotations

import argparse
import ast
from collections import Counter
import copy
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import random
import stat
import sys

N = Path(__file__).resolve().parent
RUN = Path('/home/barberb/lift_coding/external/ipfs_datasets/workspace/test-logs/legal-trigger-readout-pilot-20261007-01')
LEDGER = Path('/home/barberb/lift_coding/external/ipfs_datasets/workspace/test-logs/federal-corpus-audits/owned-daemon-resource-control/disk-reservations.json')
SCHEDULER = Path('/tmp/ipfs-datasets-resource-scheduler-1000.json')
FIRST_PLAN = N / 'rank0-presence1-plan-v01.json'
FIRST_REVIEW = N / 'first-training-protocol-independent-review-v01.json'
FIRST_REVIEW_SHA = '45de3b7cbe86fea89ba4121321d1b58bbd5b629efb85e72b6e85a39f00ece049'
CELLS = ('rank0-presence2', 'rank1-presence1', 'rank1-presence2')
FORBIDDEN_PACKETS = {N / 'authored-reference-packet-v01.json',
    N.parent / 'legal-matched-curriculum-20261012-01/authored-reference-packet-v01.json'}
METADATA_FUNCTIONS = {'require', 'canonical', 'digest', 'schedule', 'validate_plan', 'reuse_baseline'}
LITERAL_CONSTANTS = {'PLAN_FIELDS', 'SCHEMA', 'RETAINED_FORBIDDEN', 'HELPER_SHA'}
sys.dont_write_bytecode = True


def require(value, message):
    if not value:
        raise ValueError(message)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True,
                      allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def pin(path):
    path = Path(path)
    require(path.is_absolute() and path.resolve(strict=True) == path and not path.is_symlink(),
            'canonical absolute ordinary artifact required')
    before = path.stat()
    require(stat.S_ISREG(before.st_mode) and before.st_size <= 128 * 1024 * 1024,
            'bounded regular artifact required')
    data = path.read_bytes()
    after = path.stat()
    require((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns)
            == (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns)
            and len(data) == before.st_size, 'artifact changed while reading')
    return {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}


def read(path):
    path = Path(path)
    require(path not in FORBIDDEN_PACKETS, 'deferred reference packet forbidden')
    require('checkpoint' not in path.name, 'model-state JSON parsing forbidden')
    before = pin(path)
    require(before['bytes'] <= 16 * 1024 * 1024, 'bounded metadata JSON required')
    data = path.read_bytes()
    require(hashlib.sha256(data).hexdigest() == before['sha256'] and pin(path) == before,
            'metadata changed while reading')

    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, 'duplicate metadata key')
            result[key] = value
        return result

    def finite(raw):
        value = float(raw)
        require(math.isfinite(value), 'nonfinite metadata number')
        return value

    return json.loads(data, object_pairs_hook=unique, parse_float=finite,
                      parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))


def metadata_predicates(runner, expected):
    require(pin(runner) == expected, 'qualified runner source differs')
    tree = ast.parse(runner.read_text(encoding='utf-8'))
    nodes = [copy.deepcopy(node) for node in tree.body
             if isinstance(node, ast.FunctionDef) and node.name in METADATA_FUNCTIONS]
    require({node.name for node in nodes} == METADATA_FUNCTIONS, 'missing metadata predicate')
    for node in nodes:
        require(not node.decorator_list and not any(isinstance(child, (ast.Import, ast.ImportFrom))
                for child in ast.walk(node)), 'metadata extraction refuses decorators/imports')
    constants = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            if node.targets[0].id in LITERAL_CONSTANTS:
                constants[node.targets[0].id] = ast.literal_eval(node.value)
    require(set(constants) == LITERAL_CONSTANTS, 'missing closed metadata constants')
    namespace = dict(constants, __file__=str(runner), F=N, RUN_ROOT=RUN,
        HELPER=N.parent / 'legal-temporal-binding-20261012-01/run_temporal_contrast_pilot.py',
        Path=Path, math=math, random=random, json=json, hashlib=hashlib, read=read,
        pin=lambda path: {'path': str(Path(path)), **pin(path)})
    exec(compile(ast.fix_missing_locations(ast.Module(body=nodes, type_ignores=[])),
                 str(runner), 'exec'), namespace)
    return namespace


def audit_for(output):
    def audit(event, args):
        if event == 'import' and args[0].split('.')[0] in {
                'torch', 'numpy', 'transformers', 'sentence_transformers', 'ipfs_datasets_py'}:
            raise ValueError('production/numerical import forbidden')
        if event.startswith(('subprocess.', 'socket.', 'os.exec', 'os.spawn')) or event in {
                'os.system', 'os.fork', 'os.posix_spawn', 'os.kill', 'os.killpg', 'fcntl.flock',
                'os.remove', 'os.rmdir', 'os.mkdir', 'os.rename', 'os.replace', 'os.unlink'}:
            raise ValueError('process/network/lock/mutation forbidden')
        if event == 'open':
            path, mode, flags = args
            if isinstance(path, (str, bytes, os.PathLike)):
                path = Path(os.fsdecode(path)).absolute()
                require(path not in FORBIDDEN_PACKETS, 'deferred reference packet forbidden')
            write = isinstance(mode, str) and any(char in mode for char in 'wax+')
            write |= isinstance(flags, int) and bool(flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT
                                                             | os.O_TRUNC | os.O_APPEND))
            require(not write or path == output, 'only exclusive owned review may be written')
        if event == 'os.chmod':
            require(Path(args[0]).absolute() == output, 'only owned review chmod allowed')
    return audit


def review(cell, compatibility):
    require(cell in CELLS, 'one of three registered remaining cells required')
    compatibility = Path(compatibility)
    require(compatibility.is_absolute() and compatibility.parent == N
            and compatibility.name == cell + '-compatibility-v01.json',
            'owned exact selected-cell compatibility path required')
    output = N / (cell + '-training-protocol-independent-review-v01.json')
    require(not os.path.lexists(output), 'fresh exclusive review required')
    sys.addaudithook(audit_for(output))
    require(len(FIRST_REVIEW_SHA) == 64 and all(c in '0123456789abcdef' for c in FIRST_REVIEW_SHA),
            'helper is not frozen to the independent first phase receipt')
    require(pin(FIRST_REVIEW)['sha256'] == FIRST_REVIEW_SHA, 'qualified first review differs')
    first_review, first, plan = read(FIRST_REVIEW), read(FIRST_PLAN), read(N / (cell + '-plan-v01.json'))
    require(first_review['passed'] is True and first_review['findings'] == []
            and first_review['phase'] == 'training', 'qualified first review required')
    require(pin(FIRST_PLAN)['sha256'] == first_review['plan_sha256'], 'first plan differs')
    runner, guardian = N / 'run_targeted_loss.py', N / 'run_scope_guardian.py'
    for path in (runner, guardian):
        require(pin(path) == first_review['artifacts'][str(path)], 'qualified executable source differs')
    predicates = metadata_predicates(runner, first_review['artifacts'][str(runner)])
    predicates['validate_plan'](plan)
    require(plan['cell']['id'] == cell and plan['attempt_name'] == 'targeted-loss-20261012-' + cell + '-01',
            'exact selected cell/attempt differs')
    variable = {'artifacts', 'attempt_name', 'cell', 'baseline_results', 'baseline_plan'}
    require(set(plan) == set(first) and all(plan[key] == first[key] for key in set(first) - variable),
            'scientific/source/resource boundary changed')
    require(bool(first['artifacts']) and bool(first['source_owner_pins'])
            and plan['source_owner_pins'] == first['source_owner_pins']
            and all(first_review['artifacts'].get(path) == expected
                    and plan['artifacts'].get(path) == expected
                    for path, expected in first['artifacts'].items()),
            'all actual first-plan artifacts and producers must be preserved')
    baseline_reports = predicates['reuse_baseline'](plan)
    summary_path = Path(plan['baseline_results']['path'])
    additions = {str(FIRST_PLAN), str(summary_path), str(summary_path.parent.parent / 'guardian-exit.json'),
                 str(summary_path.parent.parent / 'pre-admission.json')}
    for panel in baseline_reports:
        additions.update(panel[key]['path'] for key in ('raw', 'joint', 'score') if panel[key] is not None)
    require(set(plan['artifacts']) == set(first['artifacts']) | additions,
            'only explicit immutable baseline additions are admitted')
    artifacts = {}
    # Keep every immutable qualification artifact from the reviewed first phase;
    # only the two live endpoints acquire fresh per-cell pins.
    for path, expected in first_review['artifacts'].items():
        if path not in {str(LEDGER), str(SCHEDULER)}:
            require(pin(path) == expected, 'immutable first-phase qualification changed: ' + path)
            artifacts[path] = expected
    for path, expected in plan['artifacts'].items():
        require(type(expected) is dict and set(expected) == {'bytes', 'sha256'}
                and pin(path) == expected, 'plan artifact differs: ' + path)
        artifacts[path] = expected
    data = read(plan['data_export']['path'])
    require(set(data['training_populations']) == {'mixed'}, 'one common mixed curriculum required')
    rows = data['training_populations']['mixed']
    require(len(rows) == 168 and digest(rows) == plan['training_manifest_sha256'], 'selected matched168 rows differ')
    require('authored_eval' not in data['diagnostic_metadata']
            and len(data['diagnostic_populations']['authored_eval']) == 72
            and all(set(row) == {'id', 'source_text', 'latent'}
                    for row in data['diagnostic_populations']['authored_eval']), 'deferred evaluation references leaked')
    schedule = predicates['schedule'](rows, seed=plan['batch_order_seed'])
    require(len(schedule['batch_indices']) == 32 and all(len(row) == 12 for row in schedule['batch_indices'])
            and schedule['final_progress'] == dict(epochs_completed=2, row_cursor=48, optimizer_steps=32),
            'exact32 completed-batch recipe required')
    compatible = read(compatibility)
    require(compatible['passed'] is True and compatible['findings'] == []
            and compatible['resources'] == first_review['resource_contract']
            and compatible['physical_run_root'] == str(RUN), 'exact fresh guardian compatibility required')
    require(all(compatible[key] is False for key in ('admission_guaranteed', 'reservation_acquired',
            'scheduler_client_constructed', 'model_started', 'shared_state_modified')), 'read-only check required')
    ledger, scheduler = read(LEDGER), read(SCHEDULER)
    ledger_pin, scheduler_pin = pin(LEDGER), pin(SCHEDULER)
    require(ledger_pin == {key: compatible['disk_ledger'][key] for key in ('bytes', 'sha256')}
            and scheduler_pin == {key: compatible['shared_state'][key] for key in ('bytes', 'sha256')},
            'live endpoint differs from fresh check')
    require(ledger['schema'] == first_review['opening_ledger']['schema']
            and ledger['limit_bytes'] == compatible['disk_limit_bytes'] == 145000000000
            and ledger['roots'] == first_review['opening_ledger']['roots'], 'cap/root/schema changed')
    record_hashes = {identifier: digest(body) for identifier, body in ledger['reservations'].items()}
    original = first_review['opening_ledger']['record_body_sha256']
    require(len(original) == 522 and all(record_hashes.get(key) == value for key, value in original.items()),
            'original522 record body changed or disappeared')
    claims = sum(body['storage_bytes'] for body in ledger['reservations'].values() if body['status'] != 'released')
    require(claims == compatible['outstanding_full_reservations_bytes'], 'claim accounting differs from fresh check')
    require(scheduler['schema_version'] == first_review['opening_scheduler']['schema_version']
            and scheduler['config'] == compatible['shared_config'] == first_review['opening_scheduler']['config']
            and not scheduler['leases'] and not scheduler['waiters']
            and compatible['lease_count'] == compatible['waiter_count'] == 0, 'scheduler configuration/occupancy changed')
    for root in ledger['roots']:
        path = Path(root['path']); observed = path.stat()
        require(path.resolve(strict=True) == path and stat.S_ISDIR(observed.st_mode)
                and (observed.st_dev, observed.st_ino) == (root['device'], root['inode']), 'counted-root identity changed')
    run_stat, shared_stat = RUN.stat(), SCHEDULER.stat()
    require((run_stat.st_dev, run_stat.st_ino) ==
            (first_review['run_root_identity']['device'], first_review['run_root_identity']['inode']), 'run-root changed')
    require((shared_stat.st_dev, shared_stat.st_ino) ==
            (compatible['shared_state']['device'], compatible['shared_state']['inode']), 'scheduler identity drift')
    attempt = RUN / plan['attempt_name']
    require(not os.path.lexists(attempt) and attempt.resolve() == attempt, 'selected attempt already exists')
    for path, expected in compatible['producers'].items():
        require(pin(path) == {key: expected[key] for key in ('bytes', 'sha256')}, 'resource producer differs')
        require(path in first_review['artifacts'] and pin(path) == first_review['artifacts'][path], 'resource source changed')
        artifacts[path] = pin(path)
    for path in (FIRST_REVIEW, FIRST_PLAN, N / (cell + '-plan-v01.json'), runner, guardian,
                 compatibility, LEDGER, SCHEDULER, Path(__file__).resolve()):
        artifacts[str(path)] = pin(path)
    for path in (N / 'root-science-source-independent-review-v01.json', N / 'corpus-source-independent-review-v01.json',
                 N / 'trainer-source-independent-review-v01.json', N / 'resource-baseline-audit-design-v01.json'):
        require(pin(path) == first_review['artifacts'][str(path)], 'source/science qualification changed')
        artifacts[str(path)] = pin(path)
    for path, expected in artifacts.items():
        require(pin(path) == expected, 'closing immutable or live fence differs')
    require(not os.path.lexists(attempt), 'attempt appeared before review seal')
    result = dict(schema='targeted-loss-cell-training-protocol-independent-review/v1', passed=True, findings=[],
        phase='training', observed_at_utc=datetime.now(timezone.utc).isoformat(), package_root=plan['package_root'],
        run_root=str(RUN), plan_sha256=pin(N / (cell + '-plan-v01.json'))['sha256'],
        runner_sha256=pin(runner)['sha256'], guardian_sha256=pin(guardian)['sha256'], artifacts=artifacts,
        selected_cell=plan['cell'], attempt_name=plan['attempt_name'], physical_output=str(attempt / 'results'),
        first_recipe_artifact_count=len(first['artifacts']), source_producer_count=len(first['source_owner_pins']),
        common_training_manifest_sha256=plan['training_manifest_sha256'], promotion_gate=plan['promotion_gate'],
        resource_contract=first_review['resource_contract'], original522_unchanged=True,
        opening_ledger=dict(path=str(LEDGER), schema=ledger['schema'], **ledger_pin, record_count=len(record_hashes),
            record_status_counts=dict(Counter(body['status'] for body in ledger['reservations'].values())),
            full_nonreleased_claim_bytes=claims, record_body_sha256=record_hashes,
            record_body_hash_map_sha256=digest(record_hashes), full_record_bodies_published=False,
            limit_bytes=ledger['limit_bytes'], roots=ledger['roots']),
        opening_scheduler=dict(path=str(SCHEDULER), **scheduler_pin, device=shared_stat.st_dev,
            inode=shared_stat.st_ino, config_sha256=digest(scheduler['config']), config=scheduler['config'],
            lease_count=0, waiter_count=0), run_root_identity=first_review['run_root_identity'],
        reused_baseline_summary=plan['baseline_results'], schedule=schedule,
        scope='Independent exact one-cell static/source and current metadata review; all fresh opening bodies bound; no admission performed',
        next_step_scope='One unchanged guardian invocation for this exact cell/attempt, subject to fresh owner capacity/proof-safety/admission/model gate. No other cell authorized.',
        reviewer_actions=dict(full_module_imports=0, numerical_imports=0, model_state_JSON_parses=0,
            evaluation_reference_packet_reads_or_scores=0, models_restores_forwards_updates=0,
            resource_API_lease_lock_calls=0, shared_tree_censuses=0, network_compiler_Git_HF_calls=0),
        limitations=first_review['limitations'][:5] + [
            'First-cell baseline reuse is checked from existing terminal/prediction metadata, not recomputed numerically.',
            'Every current opening body is bound for terminal preservation; additional records are not release or deletion authorization.',
            'Terminal observer qualification remains separate; this review does not claim actual completion or continuous resource coverage.'])
    with output.open('x') as stream:
        json.dump(result, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write('\n');stream.flush();os.fsync(stream.fileno())
    os.chmod(output, 0o444)
    print(json.dumps(dict(path=str(output), **pin(output), passed=True, phase='training'), sort_keys=True))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cell', required=True, choices=CELLS)
    parser.add_argument('--compatibility', required=True)
    args = parser.parse_args()
    review(args.cell, args.compatibility)
