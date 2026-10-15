"""Close only this campaign's retained claim with the existing recovery API."""
import hashlib
import json
import os
from pathlib import Path
import stat
import sys

ROOT = Path('/home/barberb/lift_coding/artifacts/legal-conditions-composition-diagnostic-20261015-01/datasets')
PHASE = Path(__file__).absolute().parent
LEDGER = Path('/home/barberb/lift_coding/external/ipfs_datasets/workspace/test-logs/federal-corpus-audits/owned-daemon-resource-control/disk-reservations.json')
ATTEMPT = Path('/home/barberb/lift_coding/external/ipfs_datasets/workspace/test-logs/federal-corpus-audits/owned-validation-runs/legal-primary-graph-export-20261015-01')
VALIDATION_SHA = 'f7bf6667a651fdd30e4bafde2b34c1fc0fd275d7f9072b6bb93526db5b5391fc'
REQUEST = PHASE / 'recovery-request-v01.json'
ROOTS = [str(Path('/home/barberb/lift_coding/external/ipfs_datasets') / p) for p in
    ('workspace/test-logs', 'workspace/todo-queues', 'docs/implementation/reports/evidence')] + ['/tmp/pytest-of-barberb']
SOURCES = ['ipfs_datasets_py/__init__.py', 'ipfs_datasets_py/router_deps.py',
    'ipfs_datasets_py/_router_alias.py', 'ipfs_datasets_py/optimizers/__init__.py',
    'ipfs_datasets_py/optimizers/logic_theorem_optimizer/__init__.py'] + [
    'ipfs_datasets_py/optimizers/logic_theorem_optimizer/' + name + '.py' for name in
    ('autoencoder_daemon_resources', 'autoencoder_resource_recovery', 'resource_scheduler',
     'runtime_telemetry', 'proof_resource_safety', 'existing_resource_scheduler', 'validation_run_resources')]


def need(value, message):
    if not value:
        raise RuntimeError(message)


def read(path):
    for parent in (path.parent, *path.parent.parents):
        need(stat.S_ISDIR(parent.lstat().st_mode), 'unaliased parent required')
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), 'rb') as stream:
        before = os.fstat(stream.fileno())
        need(stat.S_ISREG(before.st_mode) and before.st_nlink == 1 and 0 < before.st_size <= 4*1024*1024,
             'bounded regular administrative input required')
        raw = stream.read(4*1024*1024 + 1)
        identity = lambda item: (item.st_dev, item.st_ino, item.st_mode, item.st_size,
            item.st_mtime_ns, item.st_ctime_ns, item.st_nlink)
        need(identity(before) == identity(os.fstat(stream.fileno())) == identity(path.lstat()),
             'administrative input changed')
    return raw


def guard(pins):
    for spelling, digest in pins.items():
        need(hashlib.sha256(read(Path(spelling))).hexdigest() == digest, 'recovery source changed')


def save(path, value):
    raw = (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + '\n').encode()
    need(len(raw) <= 4*1024*1024, 'bounded recovery metadata required')
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600), 'wb') as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    os.chmod(path, 0o444)
    descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    return hashlib.sha256(raw).hexdigest()


need(len(sys.argv) in (2, 3) and sys.argv[1] in ('prepare', 'execute'), 'explicit administrative mode required')
sys.path.insert(0, str(ROOT))
if sys.argv[1] == 'prepare':
    pins = {str(p): hashlib.sha256(read(p)).hexdigest() for p in
            [*(ROOT / name for name in SOURCES), Path(__file__).absolute()]}
else:
    request_raw = read(REQUEST)
    need(len(sys.argv) == 3 and hashlib.sha256(request_raw).hexdigest() == sys.argv[2], 'frozen recovery request differs')
    frozen = json.loads(request_raw)
    pins = frozen['source_sha256']
guard(pins)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_resource_recovery as recovery
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_daemon_resources as resources
helper = resources.DaemonResourceReservation(LEDGER, roots=ROOTS, storage_bytes=1, memory_mb=1)
ledger = helper._read()
rows = [(key, value) for key, value in ledger['reservations'].items()
        if value.get('validation_request_sha256') == VALIDATION_SHA
        and value.get('attempt_directory', {}).get('path') == str(ATTEMPT)]
need(len(rows) == 1, 'exactly one owned validation reservation required')
reservation_id, record = rows[0]
need(record['status'] == 'retained' and record['storage_bytes'] == 536870912,
     'only the retained original 512 MiB claim may close')
need(record.get('external_charges') == {} and record.get('scheduler_lane') == 'validation', 'owned validation scope differs')
if sys.argv[1] == 'prepare':
    artifacts = recovery._durable_inventory(ATTEMPT)
    frozen = {'schema': 'legal-primary-export-owned-recovery-request/v1',
        'ledger_path': str(LEDGER), 'roots': ROOTS, 'reservation_id': reservation_id,
        'attempt_directory': str(ATTEMPT), 'original_record': record,
        'expected_record_sha256': recovery._digest(record), 'expected_artifacts': artifacts,
        'source_sha256': pins, 'capacity_policy': 'require_capacity', 'artifacts_durable': True,
        'validation_request_sha256': VALIDATION_SHA, 'original_validation_completed': False,
        'artifacts_deleted': False, 'native_admission_or_semantic_authority_granted': False}
    digest = save(REQUEST, frozen)
    print(json.dumps({'prepared_request_sha256': digest, 'reservation_id': reservation_id,
        'files': len(artifacts), 'bytes': sum(row['bytes'] for row in artifacts)}))
else:
    need(frozen['reservation_id'] == reservation_id and recovery._digest(record) == frozen['expected_record_sha256']
         and frozen['roots'] == ROOTS and frozen['ledger_path'] == str(LEDGER)
         and frozen['attempt_directory'] == str(ATTEMPT) and frozen['validation_request_sha256'] == VALIDATION_SHA,
         'frozen selected recovery custody differs')
    guard(pins)
    result = recovery.reconcile_retained_reservation(LEDGER, roots=ROOTS,
        reservation_id=reservation_id, expected_record_sha256=frozen['expected_record_sha256'],
        attempt_directory=ATTEMPT, expected_artifacts=frozen['expected_artifacts'],
        artifacts_durable=True, capacity_policy='require_capacity')
    current = helper._read()['reservations'][reservation_id]
    need(current['status'] == 'released' and current['explicit_reconciliation'] == result,
         'existing recovery did not record exact selected release')
    need(recovery._durable_inventory(ATTEMPT) == frozen['expected_artifacts'], 'retained artifacts changed')
    digest = save(PHASE / 'recovery-result-v01.json', result)
    print(json.dumps({'status': 'released', 'reservation_id': reservation_id,
        'retained_files': len(result['artifacts']), 'retained_bytes': current['final_attempt_bytes'],
        'result_sha256': digest, 'failed_execution_promoted': False, 'outputs_deleted': False}))
guard(pins)
for name, module in tuple(sys.modules.items()):
    if name == 'ipfs_datasets_py' or name.startswith('ipfs_datasets_py.'):
        need(module.__dict__.get('__file__') in pins, 'unqualified administrative product origin')
need(not any(name in sys.modules for name in ('torch', 'numpy', 'pyarrow', 'multiformats',
    'huggingface_hub', 'datasets', 'transformers', 'tensorflow', 'jax')), 'numerical/CID/SDK administrative import refused')
