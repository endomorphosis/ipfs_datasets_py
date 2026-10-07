"""Offline custody and pinned native metadata owners for this private release."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import stat
import sys

sys.dont_write_bytecode = True
BASE = Path('/home/barberb/lift_coding')
DATASETS = BASE / '.worktrees/dual-bank-wording-adapter-datasets-20261007'
SOURCE_COMMIT = '271ad796288e17039f036af6a0d003a4628da6ed'
ACCELERATE = BASE / '.worktrees/normative-checkpoint-availability-accelerate-20261006'
ACCELERATE_COMMIT = '45803f0dca3365982b6058bf7e7c9c94a95aefcf'
OLD_REGISTRATION = BASE / 'artifacts/normative-checkpoint-availability-20261006/registration'
PREFIX = 'experiments/dual-bank-replay-20261007/run-01-protocol-5a91408e4e3a'
REPOSITORIES = ('Publicus/legal-ir-autoencoder', 'Publicus/legal-ir-autoencoder-384d')
RETAINED_PREFIX = 'experiments/retained-wording-recipes-20261007/run-01-dual-6e47fc6d5452'
RETAINED_ARMS = ('control-wording-ce', 'balanced-wording-ce', 'dual-bank-retention-ce')
ARMS = ('retained_bank_control', 'dual_bank_replay')
ROLES = ('initial', 'selected', 'last-attempt')
FITTED_ROLES = ROLES[1:]
PARENT_TENSOR_SHA = '0b3c7c3b1a5581cd393d9bb8db1d24b87fe2cb9dff0be268aa2b5ed1f88b6594'
PROTOCOL_SHA = '5a91408e4e3a'  # Full exact protocol pin is also captured and reviewed.
TRAIN_MANIFEST_SHA = 'e777af1ca8728d615695c641acb3055ad36ea89404f76c4581331a8f8d410c03'
TRAIN_PLAN_SHA = 'e5088d13ba0c3526171fd33009f2980342aed965ab8c71cf2cafa0714048724c'
FIT_DRIVER_SHA = '406df2c266b69ef80a50106b9127e50d4a8a024a3b3cf0b870e3cea9b5c9af0b'
MAX_METADATA = 8 * 1024**2
AUTHORITY = dict(runtime_ready=False, runtime_admitted=False, teacher_qualified=False,
    proof_authority=False, quality_qualified=False, checkpoint_promoted=False,
    source_semantics_verified=False, exact_legal_text_reconstruction_qualified=False,
    fresh_holdout_qualified=False, long_context_8192_qualified=False)


def load_file(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if Path(module.__file__).resolve() != Path(path).resolve():
        raise ValueError('private import origin differs')
    return module


# Reuse custody source bytes, without adding its directory to the import path.
_CUSTODY_SHA = 'c3b355c2b3e4743a839a721b61c1d2868fe25c609b8da562a6b302fbe0cb6864'
_custody_path = OLD_REGISTRATION / 'custody.py'
if hashlib.sha256(_custody_path.read_bytes()).hexdigest() != _CUSTODY_SHA:
    raise ValueError('reviewed original custody source changed')
custody = load_file('_dual_bank_publication_custody', _custody_path)
capture, read, require, source, write = (getattr(custody, name)
    for name in ('capture', 'read', 'require', 'source', 'write'))


def pin(value):
    require(type(value) is dict and {'path', 'bytes', 'sha256'} <= set(value), 'file pin required')
    answer = {key: value[key] for key in ('path', 'bytes', 'sha256')}
    require(type(answer['path']) is str and Path(answer['path']).is_absolute(), 'absolute pinned path required')
    require(type(answer['bytes']) is int and 0 < answer['bytes'] <= 128 * 1024**2, 'bounded positive pin required')
    require(type(answer['sha256']) is str and re.fullmatch('[0-9a-f]{64}', answer['sha256']), 'exact SHA256 required')
    return answer


def pairs(items):
    answer = {}
    for key, value in items:
        require(key not in answer, 'duplicate JSON key')
        answer[key] = value
    return answer


def decode(raw):
    return json.loads(raw, object_pairs_hook=pairs,
        parse_constant=lambda _: (_ for _ in ()).throw(ValueError('nonfinite JSON')))


def document(value, *, maximum=MAX_METADATA):
    value = pin(value)
    require(value['bytes'] <= maximum, 'metadata file bound exceeded')
    return decode(read(value))


def wire(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)


def digest(value):
    return hashlib.sha256(wire(value).encode()).hexdigest()


def argument_pin(value):
    path, expected = value.rsplit('=', 1)
    answer = capture(Path(path))
    require(answer['sha256'] == expected, 'explicit input SHA differs')
    return answer


def write_raw(path, raw):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('xb') as output:
        output.write(raw)
        output.flush()
        custody.os.fsync(output.fileno())
    return capture(path)


def load_native(owner):
    relative = 'ipfs_datasets_py/logic/formalization/autoencoder/' + owner + '.py'
    record = source(DATASETS, relative)
    require(record['head'] == SOURCE_COMMIT, 'current committed native owner generation differs')
    module = load_file('_dual_bank_publication_native_' + owner, record['pin']['path'])
    return module, record


def source_pins():
    names = ('publication_common.py', 'prepare_dual_bank_release.py',
        'publish_dual_bank_release.py', 'register_dual_bank_release.py', 'prepare_retained_parallel_release.py')
    return [capture(Path(__file__).resolve().with_name(name)) for name in names]


def inventory_contract(schema):
    if schema in ('dual-bank-publication-preparation/v1', 'dual-bank-model-manager-plan-preparation/v1',
            'dual-bank-release-authentication/v1'):
        return dict(prefix=PREFIX, arms=ARMS, raw_count=6, fitted_count=4, run_count=2,
            publication_schema='dual-bank-publication-preparation/v1',
            preparation_schema='dual-bank-model-manager-plan-preparation/v1',
            authentication_schema='dual-bank-release-authentication/v1')
    if schema in ('retained-wording-publication-preparation/v1', 'retained-wording-model-manager-plan-preparation/v1',
            'retained-wording-release-authentication/v1'):
        return dict(prefix=RETAINED_PREFIX, arms=RETAINED_ARMS, raw_count=9, fitted_count=6, run_count=3,
            publication_schema='retained-wording-publication-preparation/v1',
            preparation_schema='retained-wording-model-manager-plan-preparation/v1',
            authentication_schema='retained-wording-release-authentication/v1')
    raise ValueError('unknown closed experimental inventory schema')


def fence(pins):
    for value in pins:
        require(capture(value['path']) == pin(value), 'pinned input/source file changed')


def capture_historical_source(path):
    """Hash-only historical input; unlike artifacts, existing hard links are allowed.

    No input bytes are copied or deserialized. Link count and descriptor/path
    identity must stay unchanged across each bounded sequential observation.
    """
    path = Path(path)
    require(path.is_absolute() and path.resolve(strict=True) == path, 'canonical historical source path required')
    before = path.lstat()
    require(stat.S_ISREG(before.st_mode) and 1 <= before.st_nlink <= 128
        and 0 <= before.st_size <= 2 * 1024**3, 'bounded regular historical source required')
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    digestor, total = hashlib.sha256(), 0
    try:
        require(custody.witness(os.fstat(descriptor)) == custody.witness(before), 'historical descriptor changed at open')
        while True:
            raw = os.read(descriptor, 1024**2)
            if not raw:
                break
            total += len(raw)
            require(total <= before.st_size, 'historical source grew while hashing')
            digestor.update(raw)
        require(total == before.st_size and custody.witness(os.fstat(descriptor)) == custody.witness(before),
            'historical descriptor changed while hashing')
    finally:
        os.close(descriptor)
    require(path.resolve(strict=True) == path and custody.witness(path.lstat()) == custody.witness(before),
        'historical source path/link count changed while hashing')
    return dict(path=str(path), bytes=total, sha256=digestor.hexdigest())


def historical_source_fence(pins):
    for value in pins:
        require(capture_historical_source(value['path']) == value, 'historical shared/large source bytes changed')


def exact_stage_files(directory, expected):
    root = Path(directory)
    require(root.is_absolute() and root.resolve(strict=True) == root and root.is_dir(), 'canonical staged directory required')
    actual = set()
    for path in root.rglob('*'):
        require(not path.is_symlink(), 'staged symlink forbidden')
        if path.is_file():
            actual.add(path.relative_to(root).as_posix())
            capture(path)
        else:
            require(path.is_dir(), 'staged special file forbidden')
    require(actual == set(expected), 'closed staged file inventory differs')


def load_guard():
    path = OLD_REGISTRATION / 'register_normative_states.py'
    owner = capture(path)
    require(owner['sha256'] == 'ba8f50acd731ae42ba1883b1289395fdc108e0ece1045b39f8afd0b785598309',
        'reviewed genuine registration guard changed')
    prior = sys.modules.get('custody')
    sys.modules['custody'] = custody
    try:
        module = load_file('_dual_bank_reused_registration_boundary', path)
    finally:
        if prior is None:
            sys.modules.pop('custody', None)
        else:
            sys.modules['custody'] = prior
    # Private instance only: its original functions and genuine manager owner are unchanged.
    module.DATASETS, module.DATASETS_HEAD = DATASETS, SOURCE_COMMIT
    require(module.ACCELERATE == ACCELERATE and module.ACCELERATE_HEAD == ACCELERATE_COMMIT,
        'genuine accelerate source boundary differs')
    return module, owner, capture(_custody_path)
