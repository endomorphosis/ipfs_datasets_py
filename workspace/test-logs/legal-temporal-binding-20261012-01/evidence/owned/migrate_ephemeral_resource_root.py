"""One reviewed, exact root-identity migration; never admits work or releases claims.

Full ledger recovery copies are local artifacts, excluded from public evidence.
On post-write uncertainty this helper preserves endpoints and aborts. It never
automatically rolls back or overwrites another writer's bytes.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.abc
import importlib.util
import json
import os
from pathlib import Path
import stat
import sys
import time
from types import ModuleType

F = Path(__file__).resolve().parent
PROTOCOL = F / 'ephemeral-root-migration-protocol-v03.json'
OUTPUT = F / 'ephemeral-root-migration-attempt-01'
MAX_JSON_BYTES = 16 * 1024 * 1024

class DenyModels(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'torch', 'numpy', 'transformers', 'sentence_transformers'}:
            raise AssertionError('Numerical/model imports prohibited: ' + fullname)
        return None

sys.meta_path.insert(0, DenyModels())
sys.dont_write_bytecode = True

def require(condition, message):
    if not condition:
        raise ValueError(message)

def raw(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()

def digest(value):
    return hashlib.sha256(raw(value)).hexdigest()

def strict_json(content):
    require(len(content) <= MAX_JSON_BYTES, 'bounded JSON required')
    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, 'duplicate JSON field')
            result[key] = value
        return result
    def reject(value):
        raise ValueError('nonfinite JSON: ' + value)
    return json.loads(content, object_pairs_hook=unique, parse_constant=reject)

def ordinary(path, *, directory=False):
    path = Path(os.path.abspath(os.fspath(path)))
    for part in (*reversed(path.parents), path):
        info = part.lstat()
        require(not stat.S_ISLNK(info.st_mode), 'symlink path refused: ' + str(part))
        require(stat.S_ISDIR(info.st_mode) if part != path or directory else stat.S_ISREG(info.st_mode),
                'ordinary path required: ' + str(part))
    return path

def bytes_and_pin(path, *, limit=MAX_JSON_BYTES, unaliased=False):
    path = ordinary(path)
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, 'rb') as stream:
        before = os.fstat(stream.fileno())
        require(stat.S_ISREG(before.st_mode) and (not unaliased or before.st_nlink == 1) and before.st_size <= limit,
                'bounded regular artifact with required alias policy needed: ' + str(path))
        content = stream.read(limit + 1)
        require(len(content) <= limit, 'artifact grew beyond bound')
        after = os.fstat(stream.fileno())
    current = path.lstat()
    identity = lambda info: (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)
    require(identity(before) == identity(after) == identity(current), 'artifact changed during read')
    return content, dict(path=str(path), bytes=len(content), sha256=hashlib.sha256(content).hexdigest())

def pin(path):
    return bytes_and_pin(path)[1]

def fsync_directory(path):
    descriptor = os.open(ordinary(path, directory=True), os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)

def save_bytes(path, content):
    require(path.parent == OUTPUT, 'receipt outside exclusive owned attempt')
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, 'wb') as stream:
        stream.write(content); stream.flush(); os.fsync(stream.fileno())
    fsync_directory(OUTPUT)
    return pin(path)

def save(path, value):
    return save_bytes(path, json.dumps(value, sort_keys=True, indent=2, allow_nan=False).encode()+b'\n')

def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module

def roots_now(resources, protocol):
    return [resources._root_identity(Path(row['path'])) for row in protocol['new_roots']]

def validate_ledger(value, protocol, *, migrated=False):
    require(type(value) is dict and set(value) == {'schema', 'roots', 'limit_bytes', 'reservations'},
            'closed existing ledger envelope required')
    require(value['schema'] == protocol['schema_before'] and value['limit_bytes'] == 145_000_000_000,
            'ledger schema or unchanged cap differs')
    require(value['roots'] == protocol['new_roots' if migrated else 'old_roots'], 'ledger root identity differs')
    rows = value['reservations']
    require(type(rows) is dict and len(rows) == 511, 'exact 511 records required')
    require({key: digest(row) for key, row in rows.items()} == protocol['record_body_hashes'],
            'a reservation record body changed')
    require(sum(row['status'] == 'retained' for row in rows.values()) == 101
            and sum(row['status'] == 'released' for row in rows.values()) == 410
            and not any(row['status'] in {'active','reserved'} for row in rows.values()),
            'exact retained/released counts and no live reservations required')
    require(sum(row['storage_bytes'] for row in rows.values() if row['status'] != 'released')
            == 48_181_777_216, 'outstanding full claims differ')

def validate_review(path, protocol, protocol_pin):
    content, review_pin = bytes_and_pin(path)
    review = strict_json(content)
    require(review.get('passed') is True and review.get('findings') == []
            and review.get('phase') == 'storage-root-migration', 'clean concrete migration review required')
    require(review.get('helper_sha256') == pin(Path(__file__))['sha256']
            and review.get('protocol_sha256') == protocol_pin['sha256'], 'reviewed helper/protocol binding differs')
    require(review.get('output_directory') == str(OUTPUT)
            and review.get('expected_ledger_sha256') == protocol['ledger_before']['sha256'],
            'review attempt or ledger binding differs')
    artifacts = review.get('artifacts')
    require(type(artifacts) is dict and artifacts, 'complete review artifacts required')
    required = {str(Path(__file__)), str(PROTOCOL), protocol['ledger_before']['path'],
                *protocol['producers'].keys()}
    require(required <= set(artifacts), 'review must bind helper/protocol/ledger/resource closure')
    for name, expected in artifacts.items():
        require(Path(name).is_absolute() and type(expected) is dict, 'absolute review artifact required')
        actual = pin(Path(name))
        require(actual['sha256'] == expected.get('sha256') and actual['bytes'] == expected.get('bytes'),
                'reviewed artifact changed: ' + name)
    return review_pin

def authenticate(protocol):
    require(protocol.get('schema') == 'ephemeral-root-migration-protocol/v1', 'exact protocol required')
    require(protocol.get('helper') == pin(Path(__file__))
            and protocol.get('helper_sha256') == protocol['helper']['sha256'], 'helper source differs')
    require(protocol.get('output_directory') == str(OUTPUT), 'one-shot output differs')
    old_roots, new_roots = protocol['old_roots'], protocol['new_roots']
    require(len(old_roots) == len(new_roots) == 4 and old_roots[:3] == new_roots[:3],
            'exact three durable roots unchanged')
    require(old_roots[3] == dict(path='/tmp/pytest-of-barberb', device=66306, inode=533856)
            and new_roots[3] == dict(path='/tmp/pytest-of-barberb', device=66306, inode=524352),
            'exact old/new ephemeral root pins required')
    for name, expected in protocol['producers'].items():
        require(pin(Path(name)) == expected, 'resource closure changed: ' + name)
    require(pin(Path(protocol['guardian']['path'])) == protocol['guardian'], 'guardian source differs before import')
    guardian = load('root_migration_guardian', Path(protocol['guardian']['path']))
    require(pin(Path(guardian.__file__)) == protocol['guardian'], 'guardian source differs')
    require({str(path): sha for path, sha in guardian.CLOSURE.items()}
            == {name: row['sha256'] for name, row in protocol['producers'].items()}, 'exact resource closure differs')
    for name in ('ipfs_datasets_py', 'ipfs_datasets_py.optimizers', 'ipfs_datasets_py.optimizers.logic_theorem_optimizer'):
        require(name not in sys.modules, 'fresh inert namespace process required')
        module = ModuleType(name)
        module.__path__ = [str(guardian.SOURCE.joinpath(*name.split('.')))]
        module.__file__ = str(guardian.SOURCE.joinpath(*name.split('.'), '__init__.py'))
        sys.modules[name] = module
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import resource_scheduler as scheduler
    require(Path(scheduler.__file__).resolve() == guardian.SOURCE / guardian.PREFIX / 'resource_scheduler.py',
            'resource scheduler outside authenticated namespace')
    resources = load('ipfs_datasets_py.optimizers.logic_theorem_optimizer.root_migration_owner', guardian.OWNER)
    def denied(*args, **kwargs):
        raise AssertionError('Reservation entry, scheduler clients and model work prohibited')
    resources.DaemonResourceReservation.__enter__ = denied
    resources.get_global_resource_scheduler = denied
    require(resources.MAX_STORAGE_BYTES == 145_000_000_000, 'owner unchanged cap differs')
    require(roots_now(resources, protocol) == new_roots, 'current root identities changed')
    ledger_content, ledger_pin = bytes_and_pin(Path(protocol['ledger_before']['path']), unaliased=True)
    require(ledger_pin == protocol['ledger_before'], 'fresh expected ledger endpoint differs')
    ledger = strict_json(ledger_content)
    validate_ledger(ledger, protocol)
    proposed = copy.deepcopy(ledger); proposed['roots'] = copy.deepcopy(new_roots)
    proposed_content = raw(proposed)+b'\n'
    require(hashlib.sha256(proposed_content).hexdigest() == protocol['ledger_after_planned']['sha256']
            and len(proposed_content) == protocol['ledger_after_planned']['bytes'], 'exact proposed bytes differ')
    require(raw(ledger)+b'\n' == ledger_content, 'existing ledger canonical byte spelling required')
    lock_path = Path(protocol['lock']['path'])
    require(pin(lock_path) == protocol['lock']['artifact'], 'existing stable lock bytes changed')
    lock_info = lock_path.lstat()
    require(dict(device=lock_info.st_dev, inode=lock_info.st_ino, nlink=lock_info.st_nlink)
            == protocol['lock']['identity'], 'existing stable lock identity changed')
    return resources, guardian, ledger_content, ledger, proposed, proposed_content

def recheck_administrative_endpoints(protocol, protocol_pin, review_path, review_pin):
    require(pin(Path(__file__)) == protocol['helper'], 'administrative helper changed')
    require(pin(PROTOCOL) == protocol_pin, 'administrative protocol changed')
    require(pin(Path(protocol['guardian']['path'])) == protocol['guardian'], 'administrative guardian changed')
    require(review_path is not None and pin(review_path) == review_pin, 'concrete independent review changed')

def fail_receipt(resources, protocol, *, stage, exception, before, after_planned, write_started):
    result = dict(schema='ephemeral-root-migration-failure/v1', complete=False, stage=stage,
                  exception_type=type(exception).__name__, exception_message=str(exception)[:2048],
                  write_started=write_started, automatic_rollback_performed=False,
                  training_started=False, admission_performed=False, claims_released=0,
                  cap_change_requested=False, source_change_requested=False,
                  before=before, planned_after=after_planned,
                  original_failure_preserved=True, further_mutation_permitted=False)
    try:
        observed_content, observed = bytes_and_pin(Path(protocol['ledger_before']['path']), unaliased=True)
        result['observed_ledger'] = observed
        result['observed_ledger_local_backup'] = save_bytes(OUTPUT/'ledger-observed-after-failure.local.json', observed_content)
        result['observed_byte_class'] = ('exact_before' if observed['sha256'] == protocol['ledger_before']['sha256'] else
                                        'exact_planned_after' if observed['sha256'] == protocol['ledger_after_planned']['sha256'] else
                                        'different_bytes_preserved')
    except BaseException as observed_error:
        result['endpoint_observation_error'] = dict(type=type(observed_error).__name__, message=str(observed_error)[:2048])
        result['observed_byte_class'] = 'unavailable'
    try:
        result['observed_root_identities'] = roots_now(resources, protocol)
    except BaseException as root_error:
        result['root_observation_error'] = dict(type=type(root_error).__name__, message=str(root_error)[:2048])
    result['recovery'] = [
        'Do not train, retry this one-shot helper, automatically revert, or overwrite ledger bytes',
        'Preserve original failure and all local backups; exclude full ledger copies from publication',
        'If exact_before, migration did not become visible at the observed endpoint; fresh review is still required',
        'If exact_planned_after, re-audit current root/source/ledger identities independently before deciding whether completion can be qualified',
        'If different/unavailable, treat current ledger as external-state uncertainty; prepare a new independently reviewed recovery using exact current bytes and the existing lock, preserving all other claims',
    ]
    save(OUTPUT/'failure-primary.json', result)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--review', type=Path)
    args = parser.parse_args()
    protocol_content, protocol_pin = bytes_and_pin(PROTOCOL)
    protocol = strict_json(protocol_content)
    resources, guardian, original, before_value, proposed, proposed_content = authenticate(protocol)
    review_pin = validate_review(args.review, protocol, protocol_pin) if args.review else None
    require(not args.apply or review_pin is not None, 'apply requires independent concrete review')
    require(not OUTPUT.exists(), 'one-shot migration attempt already exists')
    if not args.apply:
        print(json.dumps(dict(schema='ephemeral-root-migration-preflight/v1', passed=True,
              helper=pin(Path(__file__)), protocol=protocol_pin, review=review_pin,
              ledger_before=protocol['ledger_before'], ledger_after_planned=protocol['ledger_after_planned'],
              output_directory=str(OUTPUT), mutation_performed=False, admission_performed=False), sort_keys=True))
        return
    OUTPUT.mkdir(mode=0o700)
    fsync_directory(F)
    stage, before_backup, after_planned_backup, write_started = 'attempt_started', None, None, False
    save(OUTPUT/'attempt-started.json', dict(schema='ephemeral-root-migration-attempt-started/v1',
         helper=pin(Path(__file__)), protocol=protocol_pin, review=review_pin,
         expected_before=protocol['ledger_before'], expected_after=protocol['ledger_after_planned'],
         local_ledger_copies_excluded_from_public_contribution=True, owner_pid=os.getpid(),
         training_started=False, admission_performed=False, claims_released=0))
    owner = None
    try:
        # Construction creates no ledger entry or CPU lease; __enter__ is denied.
        owner = resources.DaemonResourceReservation(protocol['ledger_before']['path'],
            roots=[row['path'] for row in protocol['new_roots']], storage_bytes=1, memory_mb=1,
            cpu_slots=1, child_process_slots=1, timeout_seconds=60, ledger_lock_timeout_seconds=60)
        require(owner._record is None and owner._lease is None and not owner._entered,
                'administrative owner must have no reservation or lease')
        require(owner.root_identities == protocol['new_roots'], 'administrative current root identities differ')
        stage = 'existing_lock_admission'
        with owner._locked():
            stage = 'locked_prewrite_validation'
            require(pin(owner.lock_path) == protocol['lock']['artifact'], 'stable lock changed under acquisition')
            lock_info = owner.lock_path.lstat()
            require(dict(device=lock_info.st_dev, inode=lock_info.st_ino, nlink=lock_info.st_nlink)
                    == protocol['lock']['identity'], 'existing lock identity changed')
            locked_content, locked_pin = bytes_and_pin(owner.ledger_path, unaliased=True)
            require(locked_content == original and locked_pin == protocol['ledger_before'], 'ledger changed before migration')
            historical = copy.copy(owner); historical.root_identities = copy.deepcopy(protocol['old_roots'])
            historical_value = historical._read()
            require(historical_value == before_value, 'historical bounded reader differs')
            validate_ledger(historical_value, protocol)
            require(roots_now(resources, protocol) == protocol['new_roots'], 'current roots drifted under lock')
            for name, expected in protocol['producers'].items():
                require(pin(Path(name)) == expected, 'resource source changed before mutation')
            before_backup = save_bytes(OUTPUT/'ledger-before.local.json', locked_content)
            after_planned_backup = save_bytes(OUTPUT/'ledger-after-planned.local.json', proposed_content)
            save(OUTPUT/'planned-mutation.json', dict(schema='ephemeral-root-planned-mutation/v1',
                before=before_backup, planned_after=after_planned_backup, old_roots=protocol['old_roots'],
                new_roots=protocol['new_roots'], record_count=511, record_body_hashes=protocol['record_body_hashes'],
                outstanding_full_reservations_bytes=48_181_777_216, cap_bytes=145_000_000_000,
                changed_root_count=1, claims_modified=0, claims_removed=0, claims_released=0,
                backup_and_plan_fsynced_before_mutation=True, local_backups_excluded_from_publication=True))
            require(bytes_and_pin(owner.ledger_path, unaliased=True)[0] == locked_content, 'ledger changed while making backups')
            owner._verify_owner_roots()
            recheck_administrative_endpoints(protocol, protocol_pin, args.review, review_pin)
            for name, expected in protocol['producers'].items():
                require(pin(Path(name)) == expected, 'resource source changed immediately before mutation')
            stage = 'atomic_owner_write'; write_started = True
            owner._write(proposed)
            stage = 'postwrite_readback'
            owner._verify_owner_roots()
            require(roots_now(resources, protocol) == protocol['new_roots'], 'current roots changed after atomic write')
            for name, expected in protocol['producers'].items():
                require(pin(Path(name)) == expected, 'resource source changed after atomic write')
            readback = owner._read()
            validate_ledger(readback, protocol, migrated=True)
            require(readback == proposed and {k:v for k,v in readback.items() if k != 'roots'}
                    == {k:v for k,v in before_value.items() if k != 'roots'}, 'nonroot fields changed')
            actual_content, actual_pin = bytes_and_pin(owner.ledger_path, unaliased=True)
            require(actual_content == proposed_content and actual_pin == protocol['ledger_after_planned'],
                    'atomic writer bytes differ from exact plan')
            actual_backup = save_bytes(OUTPUT/'ledger-after.local.json', actual_content)
            stage = 'completion_receipt'
            owner._verify_owner_roots()
            recheck_administrative_endpoints(protocol, protocol_pin, args.review, review_pin)
            for name, expected in protocol['producers'].items():
                require(pin(Path(name)) == expected, 'resource source changed before completion receipt')
            require(bytes_and_pin(owner.ledger_path, unaliased=True)[0] == actual_content, 'ledger changed before completion')
            receipt = dict(schema='reboot-ephemeral-resource-root-migration/v2', complete=True,
                helper=pin(Path(__file__)), protocol=protocol_pin, independent_review=review_pin,
                verified_at_unix=time.time(), ledger_before=protocol['ledger_before'], ledger_after=actual_pin,
                before_local_backup=before_backup, planned_after_local_backup=after_planned_backup,
                after_local_backup=actual_backup, old_root=protocol['old_roots'][3], new_root=protocol['new_roots'][3],
                changed_root_count=1, durable_roots_unchanged=True, all_record_body_hashes=protocol['record_body_hashes'],
                reservation_count_before=511, reservation_count_after=511, retained_count=101, released_count=410,
                active_or_reserved_count=0, unreleased_claim_bytes_before=48_181_777_216,
                unreleased_claim_bytes_after=48_181_777_216, limit_bytes_before=145_000_000_000,
                limit_bytes_after=145_000_000_000, claims_modified=0, claims_removed=0, claims_released=0,
                source_files_modified=False, existing_ledger_lock_used=True, atomic_durable_owner_writer_used=True,
                roots_reverified_after_write=True, sources_reverified_after_write=True,
                automatic_rollback_performed=False, local_ledger_backups_excluded_from_publication=True,
                ledger_mutated=True, training_started=False, admission_performed=False,
                admission_retry_requires_fresh_inventory=True, new_experiment_plan_and_review_required=True,
                cause_of_prior_root_replacement='Unverified; migration corrects an observed exact identity mismatch only')
            final = save(OUTPUT/'completion.json', receipt)
            print(json.dumps(final, sort_keys=True))
    except BaseException as exc:
        try:
            fail_receipt(resources, protocol, stage=stage, exception=exc, before=before_backup,
                         after_planned=after_planned_backup, write_started=write_started)
        except BaseException as receipt_error:
            note = ('Failure observation/receipt could not be made durable: '
                    + type(receipt_error).__name__ + ': ' + str(receipt_error)[:1024])
            try:
                exc.add_note(note)
            except BaseException:
                pass
        raise

if __name__ == '__main__':
    main()
