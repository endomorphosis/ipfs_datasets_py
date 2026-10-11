"""Copy bounded metadata from an explicitly completed, independently reviewed run.

This helper never opens a database, writer lock, scheduler or disk ledger. Only
the enumerated JSON/JSONL/log files are eligible. Completion notification is an
explicit operator prerequisite; stopped cleanup/release receipts and applicable
independent-review hashes are checked before an atomic no-replace publication.
"""
from __future__ import annotations

import argparse
import ctypes
import errno
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import sys
import uuid


FILES = (
    'command.json', 'child-identity.json', 'child-exit.json',
    'lease-binding.json', 'lease-observations.jsonl', 'resource-observations.json',
    'resources-final.json', 'child.log', 'results/manifest.json',
    'results/report.json', 'results/clone-custody.json',
)
OPTIONAL = {'resource-observations.json'}
MAX_FILE_BYTES = 8 * 1024 * 1024
MAX_TOTAL_BYTES = 32 * 1024 * 1024


def witness(info):
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns


def read_regular(path):
    path = Path(path)
    if path.resolve(strict=True) != path or path.is_symlink():
        raise ValueError('Metadata path must be canonical without symlink aliases')
    before = path.stat()
    if not stat.S_ISREG(before.st_mode) or before.st_size > MAX_FILE_BYTES:
        raise ValueError('Metadata must be a bounded regular file')
    with path.open('rb') as stream:
        if witness(os.fstat(stream.fileno())) != witness(before):
            raise ValueError('Metadata changed before read')
        data = stream.read(MAX_FILE_BYTES + 1)
        if witness(os.fstat(stream.fileno())) != witness(before):
            raise ValueError('Metadata changed while reading')
    if len(data) != before.st_size or witness(path.stat()) != witness(before):
        raise ValueError('Metadata changed after read')
    return data, {'path': str(path), 'bytes': len(data),
                  'sha256': hashlib.sha256(data).hexdigest()}, witness(before)


def noreplace(source, destination):
    if not sys.platform.startswith('linux'):
        raise ValueError('Linux renameat2 no-replace publication is required')
    libc = ctypes.CDLL(None, use_errno=True)
    rename = libc.renameat2
    rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    rename.restype = ctypes.c_int
    if rename(-100, os.fsencode(source), -100, os.fsencode(destination), 1):
        error = ctypes.get_errno()
        if error == errno.EEXIST:
            raise FileExistsError('Snapshot destination already exists')
        raise OSError(error, os.strerror(error))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--attempt', type=Path, required=True)
    parser.add_argument('--review', type=Path, required=True)
    parser.add_argument('--review-sha256', required=True)
    parser.add_argument('--destination', type=Path, required=True)
    parser.add_argument('--completion-notified', action='store_true', required=True)
    args = parser.parse_args()
    if args.destination.exists():
        raise ValueError('Completed snapshot cannot be overwritten')
    if args.attempt.resolve(strict=True) != args.attempt:
        raise ValueError('Attempt directory must be canonical')
    review_bytes, review_pin, _ = read_regular(args.review)
    if review_pin['sha256'] != args.review_sha256:
        raise ValueError('Accepted review checksum changed')
    review = json.loads(review_bytes)
    if review.get('passed') is not True or review.get('completed') is not True or review.get('findings'):
        raise ValueError('Accepted completed independent review required')
    data = {}
    pins = {}
    witnesses = {}
    review_bound = []
    for name in FILES:
        path = args.attempt / name
        if name in OPTIONAL and not path.exists():
            continue
        payload, metadata, signature = read_regular(path)
        expected = review['actual_receipt_pins'].get(name)
        if expected is not None:
            if (metadata['sha256'], metadata['bytes']) != (expected['sha256'], expected['bytes']):
                raise ValueError('Accepted metadata review pin changed: ' + name)
            review_bound.append(name)
        data[name], pins[name], witnesses[name] = payload, metadata, signature
    if sum(len(v) for v in data.values()) > MAX_TOTAL_BYTES:
        raise ValueError('Metadata snapshot exceeds its total byte bound')
    child = json.loads(data['child-exit.json'])
    resources = json.loads(data['resources-final.json'])
    identity = json.loads(data['child-identity.json'])
    if (child['returncode'] != 0 or child['cleanup']['leader_reaped'] is not True
            or child['cleanup']['live_group_processes'] != 0
            or identity != child['cleanup']['identity'] or identity != resources['record']['child']
            or resources['record']['status'] != 'released'
            or resources['resource_lease']['released'] is not True
            or resources['cleanup_error'] is not None):
        raise ValueError('Run is not successfully stopped, reaped and released')
    proc = Path('/proc') / str(identity['pid']) / 'stat'
    if proc.exists():
        fields = proc.read_text().rsplit(')', 1)[1].split()
        if fields[19] == identity['birth'] and fields[0] != 'Z':
            raise ValueError('The recorded owned child is still live')
    args.destination.parent.mkdir(parents=True, exist_ok=True)
    if args.destination.parent.resolve(strict=True) != args.destination.parent:
        raise ValueError('Snapshot parent must be canonical')
    staging = args.destination.parent / ('.metadata-snapshot-' + uuid.uuid4().hex)
    staging.mkdir()
    try:
        for name, payload in data.items():
            path = staging / name
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open('xb') as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
        receipt = {
            'schema': 'uscode-stopped-window-metadata-snapshot/v1',
            'accepted_review': review_pin, 'source_attempt': str(args.attempt),
            'destination': str(args.destination), 'completion_notified': True,
            'source_file_pins': pins, 'review_bound_files': sorted(review_bound),
            'supplemental_stopped_metadata_files': sorted(set(pins).difference(review_bound)),
            'copied_metadata_bytes': sum(len(v) for v in data.values()),
            'excluded': ['All database files and WALs', 'writer.lock'],
            'publication': 'Atomic Linux renameat2(RENAME_NOREPLACE)',
            'database_opened': False, 'models_executed': False,
            'resources_acquired_or_mutated': False,
            'snapshot_helper_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        }
        with (staging / 'snapshot-receipt.json').open('x') as stream:
            json.dump(receipt, stream, indent=2, sort_keys=True)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        for name, signature in witnesses.items():
            if witness((args.attempt / name).stat()) != signature:
                raise ValueError('Stopped metadata changed before publication')
        for directory in sorted([staging] + [p for p in staging.rglob('*') if p.is_dir()],
                                key=lambda p: len(p.parts), reverse=True):
            fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
        noreplace(staging, args.destination)
        fd = os.open(args.destination.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    print(json.dumps({'destination': str(args.destination),
                      'copied_files': len(pins), 'copied_metadata_bytes': receipt['copied_metadata_bytes'],
                      'review_bound_files': len(review_bound), 'database_opened': False}))


if __name__ == '__main__':
    main()
