#!/usr/bin/env python3
"""Workspace-only native preparation measurement; --run explicitly launches it."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[4]
BASE = Path(__file__).resolve().parent
SCRIPT = ROOT / 'scripts/ops/legal_ir/prepare_shared_autoencoder_targets.py'
RUNNER = ROOT / 'scripts/ops/legal_ir/run_incremental_autoencoders.py'
PINNED = ROOT / 'workspace/todo-queues/legal-ir-daemon-restart12-20260608T075001Z-best-8h-autoencoder.state.json'
PINNED_SHA = '1446cb1859ddf4ed40fb5576f6e320eece4cec268a008c5c07bffeaf959cd8dd'
BRIDGES = ['modal_frame_logic', 'deontic_norms', 'fol_tdfol', 'cec_dcec', 'external_prover_router']

def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()

def descriptor(path):
    return {'path': str(path), 'bytes': path.stat().st_size, 'sha256': digest(path)}

def write(path, value):
    with path.open('x') as stream:
        json.dump(value, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write('\n')

def binding():
    started = time.monotonic()
    package = ROOT / 'ipfs_datasets_py'
    sources = {}
    for path in sorted(package.rglob('*.py')):
        if path.is_dir():
            continue
        if path.is_symlink():
            raise ValueError('source symlink: ' + str(path))
        sources[str(path.relative_to(package))] = digest(path)
    encoded = json.dumps(sources, sort_keys=True, separators=(',', ':')).encode()
    selected = [SCRIPT, RUNNER, BASE / 'input.jsonl', BASE / 'validation.jsonl', PINNED,
                ROOT.parents[1] / 'JevOps/jevops/statement_lock.py']
    files = {str(path): descriptor(path) for path in selected}
    assert files[str(PINNED)]['sha256'] == PINNED_SHA
    assert files[str(PINNED)]['bytes'] == 25895338
    return {'package_python_files': sources, 'package_source_mapping_sha256': hashlib.sha256(encoded).hexdigest(),
            'file_count': len(sources), 'files': files, 'audit_hash_wall_seconds': time.monotonic() - started}

def argv():
    return [sys.executable, str(SCRIPT), '--input-jsonl', str(BASE / 'input.jsonl'),
            '--validation-jsonl', str(BASE / 'validation.jsonl'), '--output-directory', str(BASE / 'shared-targets'),
            '--bridge-names', ','.join(BRIDGES), '--legal-ir-evaluate-provers', 'false',
            '--metric-disk-cache', '0', '--legal-ir-parallel-workers', '1',
            '--max-input-rows', '256', '--max-input-bytes', '67108864',
            '--max-output-bytes', '268435456', '--storage-bytes', '750000000',
            '--memory-mb', '8192', '--timeout-seconds', '600']

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', action='store_true')
    args = parser.parse_args()
    command = argv()
    env = {'PYTHONPATH': str(ROOT), 'CUDA_VISIBLE_DEVICES': '',
           'IPFS_DATASETS_LEGAL_IR_METRIC_DISK_CACHE': '0', 'HF_HUB_OFFLINE': '1',
           'TRANSFORMERS_OFFLINE': '1', 'OPENBLAS_NUM_THREADS': '1',
           'OMP_NUM_THREADS': '1', 'MKL_NUM_THREADS': '1', 'IPFS_DATASETS_PY_LAZY_INSTALL_ERGOAI': '0'}
    if not args.run:
        print(json.dumps({'argv': command, 'environment_overrides': env, 'launch_requires': '--run'}, indent=2))
        return
    for path in [BASE / 'shared-targets', BASE / 'shared-preparation-before.json', BASE / 'shared-preparation-after.json',
                 BASE / 'shared-preparation-command.json', BASE / 'shared-preparation-audit.json', BASE / 'shared-preparation.log']:
        if path.exists():
            raise FileExistsError(path)
    before = binding()
    write(BASE / 'shared-preparation-before.json', before)
    started = time.monotonic()
    with (BASE / 'shared-preparation.log').open('x') as log:
        completed = subprocess.run(command, cwd=ROOT, env={**os.environ, **env}, stdout=log, stderr=subprocess.STDOUT)
    elapsed = time.monotonic() - started
    after = binding()
    write(BASE / 'shared-preparation-after.json', after)
    unchanged = before['files'] == after['files'] and before['package_python_files'] == after['package_python_files']
    command_report = {'argv': command, 'environment_overrides': env, 'returncode': completed.returncode,
                      'wall_seconds': elapsed, 'sources_inputs_seed_unchanged': unchanged,
                      'measurement_scope': 'complete fresh preparation CLI including startup, source guards, bundle encoding, artifact verification and final resource accounting; outside audit hashing excluded',
                      'outside_audit_hash_seconds': before['audit_hash_wall_seconds'] + after['audit_hash_wall_seconds'],
                      'admitted': False}
    write(BASE / 'shared-preparation-command.json', command_report)
    assert completed.returncode == 0 and unchanged, command_report
    directory = BASE / 'shared-targets'
    handoff = json.loads((directory / 'receipt.json').read_bytes())
    producer = json.loads((directory / 'producer.json').read_bytes())
    preparation = producer['preparation']
    assert descriptor(directory / 'targets.bundle') == handoff['target_artifact'] == preparation['artifact']
    assert descriptor(directory / 'producer.json') == handoff['producer_receipt']
    assert preparation['bridge_names'] == BRIDGES
    assert preparation['legal_ir_evaluate_provers'] is False
    assert preparation['metric_disk_cache'] == 0 and preparation['legal_ir_parallel_workers'] == 1
    assert preparation['sample_count'] == preparation['legal_ir_target_count'] == 5
    for name in ['metric_process_cache_used', 'multiview_process_cache_used', 'admitted']:
        assert preparation[name] is False
    assert handoff['plan']['use_sample_memory'] is False
    assert handoff['plan']['training_record_count'] == 4 and handoff['plan']['validation_record_count'] == 1
    audit = {'command': command_report, 'producer_receipt': handoff['producer_receipt'],
             'target_artifact': handoff['target_artifact'], 'target_snapshot_id': handoff['target_snapshot_id'],
             'runner_arguments': handoff['runner_arguments'], 'sample_count': preparation['sample_count'],
             'legal_ir_target_count': preparation['legal_ir_target_count'],
             'preparation': {key: value for key, value in preparation.items() if key not in {'artifact', 'target_snapshot_id'}},
             'timings': {'full_cli_wall_seconds': elapsed,
                         'handoff_preparation_including_input_planning_seconds': handoff['preparation_including_input_planning_seconds'],
                         'handoff_target_preparation_wall_seconds': handoff['target_preparation_wall_seconds'],
                         'producer_call_wall_seconds': producer['producer_call_wall_seconds'],
                         'full_cli_wall_seconds_per_unique_span': elapsed / preparation['sample_count']},
             'supervision': handoff['supervision'], 'resources': json.loads((directory / 'resources.json').read_bytes()),
             'cache_scope': 'fresh child process; disk cache disabled; producer metric/multiview caches bypassed; operating system cache uncontrolled',
             'amortization_scope': 'Add full preparation once and full shared consumer wall for one-off comparison. Reuse break-even requires consumer savings > 0 and same source/runtime/input bindings; target preparation is invalidated by package-source changes.',
             'admitted': False}
    write(BASE / 'shared-preparation-audit.json', audit)
    print(json.dumps({'audit': str(BASE / 'shared-preparation-audit.json'), 'wall_seconds': elapsed,
                      'target_count': preparation['legal_ir_target_count'], 'admitted': False}), flush=True)

if __name__ == '__main__':
    main()
