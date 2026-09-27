"""Run one real concurrent smoke, then verify retained evidence without retraining."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
ROOT = Path('/home/barberb/lift_coding/external/ipfs_datasets')
sys.path.insert(0, str(HERE))
from dependency_binding import read_binding, verify_binding
DEPENDENCY = read_binding(HERE / 'frozen-config.json')
ACCELERATE = Path(DEPENDENCY['root'])
TOTAL_LIMIT = 60_000_000
TIMEOUT = 420


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def read(path):
    return json.loads(Path(path).read_bytes())


def write(path, value):
    with Path(path).open('x') as stream:
        json.dump(value, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())


def files(root):
    return sorted(path for path in root.rglob('*') if path.is_file())


def check_existing(output_directory):
    """Return the prior successful receipt; any discrepancy fails without writing."""
    dependency = verify_binding(DEPENDENCY)
    root = Path(output_directory).resolve(strict=True)
    receipt_path = root / 'smoke-receipt.json'
    if sha(receipt_path) != (root / 'smoke-receipt.sha256').read_text().strip():
        raise RuntimeError('retained smoke receipt hash changed')
    receipt = read(receipt_path)
    if receipt.get('accelerate_dependency') != dependency:
        raise RuntimeError('retained dependency binding changed')
    if not receipt['passed']:
        raise RuntimeError('previous smoke did not pass; refusal to repeat training')
    expected = set(receipt['artifact_sha256']) | {'smoke-receipt.json', 'smoke-receipt.sha256'}
    if {str(path.relative_to(root)) for path in files(root)} != expected:
        raise RuntimeError('retained artifact inventory changed')
    for name, value in receipt['artifact_sha256'].items():
        path = root / name
        if path.is_symlink() or not path.resolve().is_relative_to(root) or sha(path) != value:
            raise RuntimeError('retained artifact changed: ' + name)
    for name, value in receipt['implementation_sha256'].items():
        if sha(name) != value:
            raise RuntimeError('smoke implementation changed: ' + name)
    for name, value in receipt['source_sha256'].items():
        if sha(ROOT / name) != value:
            raise RuntimeError('canonical source changed: ' + name)
    for name, value in receipt['conversion_input_sha256'].items():
        if sha(name) != value:
            raise RuntimeError('conversion input changed: ' + name)
    checkpoint = receipt['protected_checkpoint']
    if sha(checkpoint['path']) != checkpoint['sha256']:
        raise RuntimeError('protected checkpoint changed')
    return receipt


def run_smoke(output_directory):
    """Create one new retained run; an existing directory is never reused."""
    dependency = verify_binding(DEPENDENCY)
    root = Path(output_directory).resolve()
    root.mkdir(parents=True, exist_ok=False)
    (root / 'tmp').mkdir()
    config = read(HERE / 'frozen-config.json')
    source_hashes = config['source_sha256']
    conversion_inputs = config['conversion_input_sha256']
    implementation_paths = [HERE / name for name in
        ('parent_harness.py', 'training_lane.py', 'frozen-config.json', 'conversion_lane.py', 'dependency_binding.py', 'lane_bootstrap.py')]
    implementation = {str(path): sha(path) for path in implementation_paths}
    env = dict(os.environ)
    for name in ('GIT_INDEX_FILE', 'GIT_DIR', 'GIT_WORK_TREE', 'GIT_COMMON_DIR',
                 'GIT_OBJECT_DIRECTORY', 'GIT_ALTERNATE_OBJECT_DIRECTORIES'):
        env.pop(name, None)
    env.update({'PYTHONPATH': str(ACCELERATE) + os.pathsep + str(ROOT),
        'PYTHONDONTWRITEBYTECODE': '1', 'HF_HUB_OFFLINE': '1', 'TRANSFORMERS_OFFLINE': '1',
        'IPFS_DATASETS_LEGAL_IR_METRIC_DISK_CACHE': '0', 'IPFS_DATASETS_PY_LAZY_INSTALL_ERGOAI': '0',
        'IPFS_DATASETS_MODAL_AUTOENCODER_AUTO_CUDA': '0', 'CUDA_VISIBLE_DEVICES': '',
        'OPENBLAS_NUM_THREADS': '1', 'OMP_NUM_THREADS': '1', 'MKL_NUM_THREADS': '1',
        'NUMEXPR_NUM_THREADS': '1', 'TMPDIR': str(root / 'tmp')})
    cpus = sorted(os.sched_getaffinity(0)) if hasattr(os, 'sched_getaffinity') else []
    started = time.monotonic()
    processes, logs, tokens, affinity = {}, {}, {}, {}
    error = None
    def guard():
        if time.monotonic() - started >= TIMEOUT:
            raise TimeoutError('whole concurrent smoke exceeded 420 seconds')
        if sum(path.stat().st_size for path in files(root)) > TOTAL_LIMIT:
            raise RuntimeError('combined smoke output exceeded 60 MB')
    def await_file(path, lane):
        while True:
            guard()
            if path.is_file():
                try:
                    return read(path)
                except json.JSONDecodeError:
                    pass
            if processes[lane].poll() is not None:
                raise RuntimeError(lane + ' exited before ' + path.name)
            time.sleep(0.05)
    def release(lane):
        processes[lane].stdin.write(tokens[lane] + '\n')
        processes[lane].stdin.flush()
        processes[lane].stdin.close()
    try:
        for index, lane in enumerate(('training', 'conversion')):
            tokens[lane] = secrets.token_hex(16)
            logs[lane] = (root / (lane + '.log')).open('xb')
            command = [sys.executable, '-B', str(HERE / 'lane_bootstrap.py'), '--lane', lane,
                       '--runtime-root', str(root / lane), '--start-token', tokens[lane]]
            processes[lane] = subprocess.Popen(command, cwd=ROOT, env=env,
                stdin=subprocess.PIPE, stdout=logs[lane], stderr=subprocess.STDOUT, text=True)
            if cpus:
                cpu = cpus[index % len(cpus)]
                os.sched_setaffinity(processes[lane].pid, {cpu})
                affinity[lane] = [cpu]
        for lane in processes:
            await_file(root / lane / 'ready.json', lane)
        release('training')
        await_file(root / 'training/training-started.json', 'training')
        release('conversion')
        while any(process.poll() is None for process in processes.values()):
            guard()
            time.sleep(0.1)
        guard()
    except BaseException as exc:
        error = {'type': type(exc).__name__, 'message': str(exc)}
    finally:
        for process in processes.values():
            if process.poll() is None:
                process.terminate()
        for process in processes.values():
            try:
                process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=1)
        for stream in logs.values():
            stream.close()
    checks, metrics = {}, {}
    try:
        training = read(root / 'training/summary.json')
        worker = read(root / 'training/native/receipt.json')
        evaluation_timings = read(root / 'training/evaluate-timings.json')
        conversion = read(root / 'conversion/summary.json')
        intervals = {name: read(root / path)['monotonic_ns'] for name, path in {
            'training_start': 'training/training-started.json', 'training_end': 'training/training-finished.json',
            'conversion_start': 'conversion/conversion-started.json',
            'conversion_end': 'conversion/conversion-finished.json'}.items()}
        overlap_ns = max(0, min(intervals['training_end'], intervals['conversion_end'])
                         - max(intervals['training_start'], intervals['conversion_start']))
        checks = {'training_completed': training['completed'] is True,
            'native_training': worker['execution_mode'] == 'native_training',
            'evaluate_timings_complete': evaluation_timings['incomplete_calls'] == 0,
            'optimizer_update_accepted': worker['optimizer_accepted_epochs'] > 0,
            'validation_bridge_coverage': all(worker['training_report'][key]['legal_ir_target_count'] == 2
                                              for key in ('before', 'after')),
            'conversion_gates_passed': conversion['passed'] is True,
            'actual_native_method_overlap': overlap_ns > 0,
            'all_lanes_exit_zero': all(process.returncode == 0 for process in processes.values()),
            'source_unchanged': all(sha(ROOT / name) == value for name, value in source_hashes.items()),
            'conversion_inputs_unchanged': all(sha(name) == value for name, value in conversion_inputs.items()),
            'implementation_unchanged': all(sha(name) == value for name, value in implementation.items()),
            'authority_false': worker['admitted'] is False and worker['promotion_performed'] is False
                and conversion['admitted'] is False and conversion['formalized'] is False}
        metrics = {'intervals_monotonic_ns': intervals, 'actual_native_overlap_seconds': overlap_ns / 1e9,
            'optimizer_accepted_epochs': worker['optimizer_accepted_epochs'],
            'bridge_names': worker['bridge_names'], 'metric_disk_cache': worker['metric_disk_cache'],
            'legal_ir_evaluate_provers': worker['legal_ir_evaluate_provers'],
            'legal_ir_parallel_workers': worker['legal_ir_parallel_workers'],
            'sample_count': worker['sample_count'], 'validation_sample_count': worker['validation_sample_count'],
            'training_seconds': worker['training_seconds'], 'cache_observation': worker['cache_observation']}
        metrics['acceptance_validation_metrics'] = {
            key: {'legal_ir_target_count': worker['training_report'][key]['legal_ir_target_count'],
                  'legal_ir_losses': worker['training_report'][key]['legal_ir_losses'],
                  'deontic': worker['training_report'][key].get('legal_ir_view_family_metrics', {}).get('deontic', {})}
            for key in ('before', 'after')}
        profile = worker['training_report'].get('projection_profile', {})
        target_counts = {'before_holdout_evaluation': worker['training_report']['before']['legal_ir_target_count'],
                         'line_search_evaluation': worker['training_report']['after']['legal_ir_target_count']}
        metrics['profile_evaluate_wall_times'] = [
            {'stage': item['stage'], 'wall_seconds': item['seconds'],
             'sample_count': item['metadata']['sample_count'],
             'wall_seconds_per_span': item['seconds'] / item['metadata']['sample_count'],
             'legal_ir_target_count': target_counts.get(item['stage']),
             'cache_scope': ('disk cache disabled; targets may be process-warm'
                             if item['stage'] == 'line_search_evaluation' else
                             'disk cache disabled; first evaluation of this distinct sample split')}
            for item in profile.get('events', [])
            if item['stage'] in {'before_holdout_evaluation', 'training_cache_prime', 'line_search_evaluation'}
            and item['cost_family'] in {'python_loop', 'kernel'} and item['metadata'].get('sample_count', 0) > 0]
        metrics['bridge_on_evaluate_wall_times'] = [item for item in evaluation_timings['calls'] if item['bridge_names']]
        metrics['bridge_off_evaluate_wall_times'] = [item for item in evaluation_timings['calls'] if not item['bridge_names']]
        metrics['conversion_wall_seconds_per_span'] = {
            'synthetic': sum(row['wall_seconds'] for row in conversion['gate_rows']) / len(conversion['gate_rows']),
            'retained_us_code': sum(row['wall_seconds'] for row in conversion['source_rows']) / len(conversion['source_rows'])}
        metrics['training_split_target_counts_observed'] = [item['legal_ir_target_count']
            for item in evaluation_timings['calls'] if item['bridge_names'] and item.get('sample_count') == worker['sample_count']]
    except BaseException as exc:
        error = error or {'type': type(exc).__name__, 'message': str(exc)}
    receipt = {'schema': 'concurrent-autoformal-supervisor-smoke-v1',
        'recorded_at': datetime.now(timezone.utc).isoformat(), 'passed': error is None and bool(checks) and all(checks.values()),
        'checks': checks, 'metrics': metrics, 'error': error,
        'native_executed': checks.get('native_training', False),
        'lanes_completed': checks.get('training_completed', False) and checks.get('all_lanes_exit_zero', False),
        'accepted_update': checks.get('optimizer_update_accepted', False),
        'admitted': False, 'formalized': False, 'production_promotion': False, 'heldout_canary_qualified': False,
        'lane_returncodes': {name: process.returncode for name, process in processes.items()},
        'lane_cpu_affinity': affinity, 'distinct_lane_cpus': len(cpus) >= 2,
        'elapsed_seconds': time.monotonic() - started, 'whole_deadline_seconds': TIMEOUT,
        'output_byte_limit': TOTAL_LIMIT, 'implementation_sha256': implementation, 'source_sha256': source_hashes,
        'accelerate_dependency': dependency, 'accelerate_dependency_after': verify_binding(DEPENDENCY),
        'conversion_input_sha256': conversion_inputs,
        'protected_checkpoint': {'path': str(ROOT / 'workspace/todo-queues/legal-ir-daemon-restart12-20260608T075001Z-best-8h-autoencoder.state.json'),
            'sha256': '1446cb1859ddf4ed40fb5576f6e320eece4cec268a008c5c07bffeaf959cd8dd'},
        'artifact_sha256': {str(path.relative_to(root)): sha(path) for path in files(root)}}
    write(root / 'smoke-receipt.json', receipt)
    with (root / 'smoke-receipt.sha256').open('x') as stream:
        stream.write(sha(root / 'smoke-receipt.json') + '\n')
    return receipt
