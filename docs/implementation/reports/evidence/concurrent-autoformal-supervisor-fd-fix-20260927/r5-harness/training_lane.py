#!/usr/bin/env python3
"""Bounded native optimizer smoke; source fixtures and validation are not proof."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import resource
import sys
import threading
import time

ROOT = Path('/home/barberb/lift_coding/external/ipfs_datasets')
PINNED = ROOT / 'workspace/todo-queues/legal-ir-daemon-restart12-20260608T075001Z-best-8h-autoencoder.state.json'
PINNED_SHA = '1446cb1859ddf4ed40fb5576f6e320eece4cec268a008c5c07bffeaf959cd8dd'
LIMIT = 30_000_000


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def write(path, value):
    with path.open('x') as stream:
        json.dump(value, stream, sort_keys=True, allow_nan=False)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())


def event(stage, **extra):
    value = {'stage': stage, 'monotonic_ns': time.monotonic_ns(),
             'utc': datetime.now(timezone.utc).isoformat(), 'pid': os.getpid(), **extra}
    print(json.dumps(value, sort_keys=True), flush=True)
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime-root', required=True, type=Path)
    parser.add_argument('--start-token', required=True)
    args = parser.parse_args()
    runtime = args.runtime_root.resolve()
    runtime.mkdir(parents=True, exist_ok=False)
    config_path = Path(__file__).with_name('frozen-config.json')
    config = json.loads(config_path.read_bytes())
    if config['script_sha256'] != digest(__file__):
        raise RuntimeError('training lane script differs from frozen configuration')
    def source_guard():
        changed = [name for name, sha in config['source_sha256'].items() if digest(ROOT / name) != sha]
        if changed:
            raise RuntimeError('pinned source changed: ' + ', '.join(changed))
        if PINNED.stat().st_size != 25_895_338 or digest(PINNED) != PINNED_SHA:
            raise RuntimeError('protected checkpoint changed')
    source_guard()
    write(runtime / 'ready.json', event('ready', native_started=False,
          config_sha256=digest(config_path), runtime_root=str(runtime)))
    if sys.stdin.readline().rstrip('\n') != args.start_token:
        raise RuntimeError('parent start handshake did not match')
    source_guard()
    os.environ.update({'PYTHONDONTWRITEBYTECODE': '1', 'HF_HUB_OFFLINE': '1',
        'TRANSFORMERS_OFFLINE': '1', 'IPFS_DATASETS_LEGAL_IR_METRIC_DISK_CACHE': '0',
        'IPFS_DATASETS_PY_LAZY_INSTALL_ERGOAI': '0', 'CUDA_VISIBLE_DEVICES': '',
        'IPFS_DATASETS_MODAL_AUTOENCODER_AUTO_CUDA': '0', 'OPENBLAS_NUM_THREADS': '1',
        'OMP_NUM_THREADS': '1', 'MKL_NUM_THREADS': '1', 'NUMEXPR_NUM_THREADS': '1'})
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(ROOT))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    resource.setrlimit(resource.RLIMIT_FSIZE, (LIMIT, LIMIT))
    done = threading.Event()
    def storage_watch():
        while not done.wait(0.2):
            total = sum(path.stat().st_size for path in runtime.rglob('*') if path.is_file())
            if total > LIMIT:
                event('output_byte_limit_exceeded', bytes=total, limit=LIMIT)
                os._exit(75)
    threading.Thread(target=storage_watch, daemon=True).start()
    receipt, failed, entry, exit_event, monitor_id = None, None, None, None, None
    evaluations, evaluation_stack = [], []
    try:
        from ipfs_datasets_py.logic.autoformal.tree_pin import require_workspace_logic_tree
        from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_training_worker import (
            TrainingJobSpec, execute_training_job)
        from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder import AdaptiveModalAutoencoder
        paths = require_workspace_logic_tree()
        payload = dict(config['job'])
        payload.update(output_directory=str(runtime / 'native'),
            base_checkpoint={'path': str(PINNED), 'bytes': 25_895_338, 'sha256': PINNED_SHA},
            expected_source_sha256=config['worker_source_sha256'])
        spec = TrainingJobSpec.from_dict(payload)
        write(runtime / 'job.json', spec.to_dict())
        source_guard()
        monitor_code = AdaptiveModalAutoencoder.train_generalizable_projection.__code__
        evaluate_code = AdaptiveModalAutoencoder.evaluate.__code__
        monitor_id = next(tool for tool in range(6) if sys.monitoring.get_tool(tool) is None)
        sys.monitoring.use_tool_id(monitor_id, 'autoformal-smoke-native-interval')
        def training_start(code, instruction_offset):
            if code is evaluate_code:
                arguments = sys._getframe(1).f_locals
                observation = {'call_index': len(evaluations), 'start_monotonic_ns': time.monotonic_ns(),
                    'bridge_names': list(arguments['legal_ir_bridge_names']),
                    'legal_ir_evaluate_provers': arguments['legal_ir_evaluate_provers'],
                    'legal_ir_parallel_workers': arguments['legal_ir_parallel_workers'],
                    'use_sample_memory': arguments['use_sample_memory'], 'metric_disk_cache': 0}
                evaluations.append(observation)
                evaluation_stack.append(observation)
                return
            write(runtime / 'training-started.json', event('native_training_method_entry',
                timing_scope='unmodified train_generalizable_projection local PY_START event'))
        def training_return(code, instruction_offset, result):
            if code is evaluate_code:
                observation = evaluation_stack.pop()
                observation.update(end_monotonic_ns=time.monotonic_ns(),
                    sample_count=int(result.sample_count), legal_ir_target_count=int(result.legal_ir_target_count))
                observation['wall_seconds'] = (observation['end_monotonic_ns'] - observation['start_monotonic_ns']) / 1e9
                observation['wall_seconds_per_span'] = (observation['wall_seconds'] / result.sample_count
                                                        if result.sample_count else None)
                return
            write(runtime / 'training-finished.json', event('native_training_method_exit',
                accepted_epochs=result.get('accepted_epochs') if isinstance(result, dict) else None,
                timing_scope='unmodified train_generalizable_projection local PY_RETURN event'))
        sys.monitoring.register_callback(monitor_id, sys.monitoring.events.PY_START, training_start)
        sys.monitoring.register_callback(monitor_id, sys.monitoring.events.PY_RETURN, training_return)
        sys.monitoring.set_local_events(monitor_id, monitor_code,
            sys.monitoring.events.PY_START | sys.monitoring.events.PY_RETURN)
        sys.monitoring.set_local_events(monitor_id, evaluate_code,
            sys.monitoring.events.PY_START | sys.monitoring.events.PY_RETURN)
        entry = event('native_worker_entry', timing_scope='unmodified worker including state load and sample preparation',
                      tree_paths=paths, job_sha256=spec.canonical_sha256)
        receipt = execute_training_job(spec)
        exit_event = event('native_worker_exit', accepted_epochs=receipt['optimizer_accepted_epochs'])
        source_guard()
        if (receipt['execution_mode'] != 'native_training' or receipt['validation_mode'] != 'holdout'
                or receipt['admitted'] or receipt['promotion_performed']
                or receipt['overlapping_sample_ids'] or receipt['overlapping_normalized_text_sha256']):
            raise RuntimeError('native receipt identity or authority invariant failed')
        if any(receipt['training_report'][stage]['legal_ir_target_count'] != 2 for stage in ('before', 'after')):
            raise RuntimeError('five-bridge validation did not produce both legal IR targets')
        if (runtime / 'native/candidate.state.json').exists():
            raise RuntimeError('sparse smoke unexpectedly wrote a full checkpoint')
    except BaseException as exc:
        failed = {'type': type(exc).__name__, 'message': str(exc)}
        event('failed', error=failed)
    finally:
        if monitor_id is not None:
            sys.monitoring.set_local_events(monitor_id, monitor_code, 0)
            sys.monitoring.set_local_events(monitor_id, evaluate_code, 0)
            sys.monitoring.register_callback(monitor_id, sys.monitoring.events.PY_START, None)
            sys.monitoring.register_callback(monitor_id, sys.monitoring.events.PY_RETURN, None)
            sys.monitoring.free_tool_id(monitor_id)
        done.set()
    write(runtime / 'evaluate-timings.json', {'schema': 'native-evaluate-wall-times-v1',
        'calls': evaluations, 'incomplete_calls': len(evaluation_stack),
        'timing_scope': 'unmodified native evaluate local PY_START/PY_RETURN events; no injected trainer',
        'cache_policy': 'metric disk cache disabled; later calls may use warm process targets; OS cache uncontrolled'})
    checks = {'pinned_checkpoint_unchanged': digest(PINNED) == PINNED_SHA,
              'source_unchanged': all(digest(ROOT / name) == sha for name, sha in config['source_sha256'].items())}
    used = sum(path.stat().st_size for path in runtime.rglob('*') if path.is_file())
    summary = {'schema': 'concurrent-autoformal-native-training-smoke-v1', 'error': failed,
        'completed': receipt is not None and failed is None and all(checks.values()), **checks,
        'native_worker_entry': entry, 'native_worker_exit': exit_event,
        'optimizer_accepted_epochs': None if receipt is None else receipt['optimizer_accepted_epochs'],
        'training_receipt': str(runtime / 'native/receipt.json'), 'bytes_before_summary': used,
        'evaluate_timings': str(runtime / 'evaluate-timings.json'), 'evaluate_call_count': len(evaluations),
        'storage_limit_bytes': LIMIT, 'config_sha256': digest(config_path),
        'admitted': False, 'formalized': False, 'heldout_canary_qualified': False,
        'scope': 'three synthetic training gates; two distinct synthetic acceptance-validation fixtures; no corpus qualification',
        'cache_policy': 'disk metric cache disabled; process targets can warm within job; OS cache uncontrolled'}
    write(runtime / 'summary.json', summary)
    event('complete', completed=summary['completed'], optimizer_accepted_epochs=summary['optimizer_accepted_epochs'])
    return 0 if summary['completed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
