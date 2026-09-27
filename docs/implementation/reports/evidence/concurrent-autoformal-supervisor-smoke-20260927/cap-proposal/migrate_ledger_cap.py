#!/usr/bin/env python3
"""Review or explicitly apply one locked 62.0 -> 62.2 GB ledger migration."""
import argparse
import ast
import fcntl
import hashlib
import json
import os
from pathlib import Path
import stat

OLD, NEW = 62_000_000_000, 62_200_000_000
BOUND = 8 * 1024 * 1024
SOURCE = Path('/home/barberb/lift_coding/external/ipfs_datasets/ipfs_datasets_py/optimizers/logic_theorem_optimizer/autoencoder_daemon_resources.py')


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate JSON key: ' + key)
        result[key] = value
    return result


def proposal(raw):
    if len(raw) > BOUND:
        raise ValueError('ledger exceeds byte bound')
    old = json.loads(raw, object_pairs_hook=unique)
    if (set(old) != {'limit_bytes', 'reservations', 'roots', 'schema'}
            or old['schema'] != 'daemon-resource-reservations-v1'
            or old['limit_bytes'] != OLD or type(old['reservations']) is not dict):
        raise ValueError('unexpected ledger schema or old cap')
    if any(row.get('status') not in {'retained', 'released'} for row in old['reservations'].values()):
        raise ValueError('active or unknown reservations prevent cap migration')
    prefix = ('{"limit_bytes":' + str(OLD) + ',').encode()
    if not raw.startswith(prefix):
        raise ValueError('ledger is not in the expected canonical byte encoding')
    after = ('{"limit_bytes":' + str(NEW) + ',').encode() + raw[len(prefix):]
    new = json.loads(after, object_pairs_hook=unique)
    if new != {**old, 'limit_bytes': NEW} or new['reservations'] != old['reservations']:
        raise ValueError('migration changed ledger history')
    return after, old


def regular(path):
    path = Path(path).absolute()
    if path != path.resolve(strict=True):
        raise ValueError('symlink path refused: ' + str(path))
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise ValueError('file must be regular and unaliased: ' + str(path))
    return path, info


def write_new(path, raw, mode=0o600):
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, mode)
    with os.fdopen(descriptor, 'wb') as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def sync_dir(path):
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ledger', type=Path, required=True)
    parser.add_argument('--expected-ledger-sha256', required=True)
    parser.add_argument('--record-directory', type=Path, required=True)
    parser.add_argument('--mode', choices=('dry-run', 'apply'), default='dry-run')
    parser.add_argument('--authorization-file', type=Path)
    args = parser.parse_args()
    if args.mode == 'apply':
        if args.authorization_file is None:
            raise ValueError('apply requires explicit recorded user authorization')
        authorization = json.loads(args.authorization_file.read_bytes())
        if (authorization.get('schema') != 'campaign-cap-authorization-v1'
                or authorization.get('authorized') is not True
                or authorization.get('old_limit_bytes') != OLD
                or authorization.get('new_limit_bytes') != NEW
                or not authorization.get('user_message')):
            raise ValueError('authorization does not cover this exact cap change')
        constants = [ast.literal_eval(node.value) for node in ast.parse(SOURCE.read_bytes()).body
                     if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name)
                     and target.id == 'MAX_STORAGE_BYTES' for target in node.targets)]
        if constants != [NEW]:
            raise ValueError('reviewed source cap must be applied before ledger migration')
    ledger, original_info = regular(args.ledger)
    lock, lock_info = regular(ledger.with_name(ledger.name + '.lock'))
    descriptor = os.open(lock, os.O_RDWR | os.O_NOFOLLOW)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if (lock.stat().st_dev, lock.stat().st_ino) != (lock_info.st_dev, lock_info.st_ino):
            raise ValueError('lock identity changed')
        current, current_info = regular(ledger)
        if (current_info.st_dev, current_info.st_ino) != (original_info.st_dev, original_info.st_ino):
            raise ValueError('ledger changed before lock acquisition')
        if current_info.st_size > BOUND:
            raise ValueError('ledger exceeds byte bound')
        raw = current.read_bytes()
        if sha(raw) != args.expected_ledger_sha256:
            raise ValueError('ledger changed since reviewed observation')
        after, old = proposal(raw)
        records = args.record_directory.absolute()
        if records != records.resolve() or records == ledger.parent or ledger.parent in records.parents:
            raise ValueError('use a new regular private record directory outside the ledger directory')
        records.mkdir(parents=False, exist_ok=False)
        write_new(records / 'ledger.before.json', raw)
        write_new(records / 'ledger.proposed.json', after)
        receipt = {'mode': args.mode, 'applied': False, 'old_limit_bytes': OLD, 'new_limit_bytes': NEW,
            'before_sha256': sha(raw), 'after_sha256': sha(after), 'bytes': len(raw),
            'reservation_count': len(old['reservations']), 'all_records_preserved': True,
            'non_cap_bytes_identical': True, 'per_worker_limit_unchanged': 50_000_000_000}
        if args.mode == 'apply':
            write_new(records / 'authorization.json', args.authorization_file.read_bytes())
            sync_dir(records)
            temporary = ledger.with_name('.' + ledger.name + '.cap-622gb-' + str(os.getpid()))
            write_new(temporary, after, stat.S_IMODE(current_info.st_mode))
            if ledger.read_bytes() != raw:
                raise ValueError('ledger changed while locked; temporary and backup retained')
            os.replace(temporary, ledger)
            sync_dir(ledger.parent)
            if ledger.read_bytes() != after:
                raise ValueError('atomic migration readback differs; backup retained')
            receipt['applied'] = True
        write_new(records / 'receipt.json', (json.dumps(receipt, sort_keys=True, indent=2) + '\n').encode())
        sync_dir(records)
        print(json.dumps(receipt, sort_keys=True))
    finally:
        os.close(descriptor)


if __name__ == '__main__':
    main()
