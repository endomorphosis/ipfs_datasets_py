"""Explicit administrative recovery of this phase's one failed native attempt."""
from pathlib import Path
import hashlib
import json
import os
import stat
import sys
import types

PHASE = Path(__file__).resolve().parent
ROOT = Path('/home/barberb/lift_coding/artifacts/legal-ir-missing-component-import-20261016/datasets')
GUARD = ROOT / 'docs/autoencoders/evidence/legal-relational-target-contract-20261016/run_qualification.py'
LEDGER = Path('/home/barberb/lift_coding/external/ipfs_datasets/workspace/test-logs/federal-corpus-audits/owned-daemon-resource-control/disk-reservations.json')
ATTEMPT = Path('/home/barberb/lift_coding/external/ipfs_datasets/workspace/test-logs/federal-corpus-audits/owned-validation-runs/legal-source-corpus-reuse-20261016-a-02')

raw = GUARD.read_bytes()
assert hashlib.sha256(raw).hexdigest() == 'caef50be105d8280cd727ae0c14867644e223d83639454ff33f0df2df2e68854'
g = types.ModuleType('existing_checked_recovery_guard')
g.__file__ = str(GUARD)
exec(compile(raw, str(GUARD), 'exec', dont_inherit=True, optimize=0), g.__dict__)
request_raw = g.snapshot(PHASE / 'qualification-request-02.json', g.MAX_METADATA_BYTES)
request = g.decode(request_raw)
assert g.sha(request_raw) == '0b72c9bb47f84afecc2dd7e4bf8280de9a8d8694bf3d43ac1b378ef519a3686d'
# Current administrative source context is separate from the preserved failed test pins.
pins = {path: g.sha(g.snapshot(Path(path), g.MAX_SOURCE_BYTES, allow_empty=True))
    for path in request['source_sha256']}
recovery_path = ROOT / 'ipfs_datasets_py/optimizers/logic_theorem_optimizer/autoencoder_resource_recovery.py'
pins[str(recovery_path)] = g.sha(g.snapshot(recovery_path, g.MAX_SOURCE_BYTES))
g.code_guard(pins)
g.no_forbidden_modules()
os.environ.update(IPFS_DATASETS_PY_MINIMAL_IMPORTS='1', IPFS_DATASETS_AUTO_INSTALL='0', IPFS_AUTO_INSTALL='false', IPFS_DATASETS_PY_LAZY_INSTALL_ERGOAI='0')
sys.path.insert(0, str(ROOT))
finder = g.PinnedProductFinder(ROOT, pins)
sys.meta_path.insert(0, finder)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_resource_recovery as recovery

# The only permitted ledger observation here selects this exact owned failure.
ledger = g.decode(g.snapshot(LEDGER, 16 * 1024 * 1024))
selected = [(identity, row) for identity, row in ledger['reservations'].items()
    if (row.get('attempt_directory') or {}).get('path') == str(ATTEMPT)]
assert len(selected) == 1
reservation_id, row = selected[0]
assert row['status'] == 'retained' and row['retention_reason'] == 'context_failed'
assert row['validation_request_sha256'] == g.sha(request_raw)
assert row['storage_bytes'] == request['storage_bytes'] and row['external_charges'] == {}
assert row['scheduler_lane'] == 'validation' and row['workload'] == 'canonical_validation'
roots = [entry['path'] for entry in ledger['roots']]
assert roots == request['roots']
assert recovery.resources._process(row['owner_pid']) is None
assert all(not recovery.resources._group_usage(child)['live_processes'] for child in [row.get('child'), *row.get('prior_children', [])])
original_record_sha = hashlib.sha256(json.dumps(row, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()
inventory = []
for path in sorted(ATTEMPT.rglob('*')):
    if path.is_dir():
        continue
    g.physical_parents(path)
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), 'rb') as stream:
        before = os.fstat(stream.fileno())
        assert stat.S_ISREG(before.st_mode) and before.st_nlink == 1
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        os.fsync(stream.fileno())
        after = os.fstat(stream.fileno())
    assert g.identity(before) == g.identity(after) == g.identity(path.lstat())
    inventory.append({'path': str(path.relative_to(ATTEMPT)), 'bytes': before.st_size, 'sha256': digest})
for directory in [ATTEMPT, *(path for path in ATTEMPT.rglob('*') if path.is_dir())]:
    descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
result = recovery.reconcile_retained_reservation(LEDGER, roots=roots, reservation_id=reservation_id,
    expected_record_sha256=original_record_sha, attempt_directory=ATTEMPT,
    expected_artifacts=inventory, artifacts_durable=True)
g.code_guard(pins)
g.no_forbidden_modules()
origins = g.product_origins(ROOT, pins, finder)
receipt = {'schema': 'legal-source-corpus-reuse-own-failed-qualification-recovery/v1',
    'scope': 'Explicit administrative reconciliation of the exact current-phase failed attempt only. No product/test/corpus workload, new reservation/lease, foreign cleanup or authority.',
    'attempt_directory': str(ATTEMPT), 'request_sha256': g.sha(request_raw),
    'selected_previous_record_sha256': original_record_sha, 'source_sha256': pins,
    'loaded_product_source_origins': origins, 'reconciliation': result,
    'outputs_deleted': False, 'new_reservation_acquired': False, 'new_resource_lease_acquired': False,
    'successful_test_claim': False, 'scheduler_lease_state_independently_authenticated': False}
Path('/home/barberb/lift_coding/artifacts/legal-source-corpus-reuse-20261016/qualification02-own-recovery-receipt-v01.json').write_text(json.dumps(receipt, sort_keys=True, indent=2) + '\n')
print(json.dumps({'reservation_id': reservation_id, 'reconciled': True, 'artifact_files': len(inventory), 'artifact_bytes': sum(entry['bytes'] for entry in inventory), 'outputs_deleted': False}))
