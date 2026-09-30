#!/usr/bin/env python3
"""Bounded local UI/IDL feature training and separate saved-model inference."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_LEDGER = ROOT/'workspace/test-logs/federal-corpus-audits/owned-daemon-resource-control/disk-reservations.json'
WORKER_STARTUP_PREPARATION_SECONDS = 120.0
FINAL_RECEIPT_HEADROOM_BYTES = 1_048_576
MAX_WORKER_REQUEST_BYTES = 20 * 1024 * 1024
WATCHDOG_INTERVAL_SECONDS = 0.05


def _process_birth(pid):
    """Linux birth identity fences cleanup against a reused process-group PID."""
    try:
        raw = Path(f'/proc/{pid}/stat').read_text()
    except (FileNotFoundError, ProcessLookupError):
        return None
    return raw[raw.rfind(')') + 2:].split()[19]


def _stop_owned_group(process, birth):
    def send(signum):
        current = _process_birth(process.pid)
        if current is not None and current != birth:
            raise RuntimeError('owned worker PID was reused; refusing unrelated process-group cleanup')
        try:
            os.killpg(process.pid, signum)
        except ProcessLookupError:
            pass
    send(signal.SIGTERM)
    try:
        process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        pass
    # Stop any surviving descendants even if the group leader already exited.
    send(signal.SIGKILL)
    process.wait(timeout=5)


class _WorkerWatchdog:
    """Independent fast RSS/deadline checks while the owner inventories disk.

    This samples the live owned process group; it is not a kernel peak-RSS
    counter or an OS memory cgroup. Excursions shorter than a sample may escape
    observation. Sampling never acquires the disk-ledger lock.
    """
    def __init__(self, process, birth, *, started, wall_seconds, memory_mb):
        from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_daemon_resources import _group_usage
        self.process, self.birth = process, birth
        self.started, self.wall_seconds = started, wall_seconds
        self.memory_bytes = memory_mb * 1024 * 1024
        self.group_usage = _group_usage
        self.stop_event = threading.Event()
        self.lock = threading.Lock()
        self.cleanup_lock = threading.Lock()
        self.terminated = False
        self.failure = None
        self.samples = self.peak_rss = self.peak_processes = 0
        self.thread = threading.Thread(target=self._run, name='ui-worker-resource-watchdog', daemon=True)

    def start(self):
        self.thread.start()

    def terminate(self):
        with self.cleanup_lock:
            if not self.terminated:
                _stop_owned_group(self.process, self.birth)
                self.terminated = True

    def _run(self):
        try:
            while not self.stop_event.is_set():
                group = self.group_usage({'pid': self.process.pid, 'birth': self.birth})
                with self.lock:
                    self.samples += 1
                    self.peak_rss = max(self.peak_rss, group['rss_bytes'])
                    self.peak_processes = max(self.peak_processes, group['live_processes'])
                if group['rss_bytes'] > self.memory_bytes:
                    raise MemoryError('UI worker exceeded its owned process-group RSS limit')
                if not group['live_processes']:
                    return
                if time.monotonic() - self.started >= self.wall_seconds:
                    raise TimeoutError('UI worker exceeded its bounded wall deadline')
                self.stop_event.wait(WATCHDOG_INTERVAL_SECONDS)
        except BaseException as error:
            with self.lock:
                self.failure = error
            try:
                self.terminate()
            except BaseException as cleanup:
                with self.lock:
                    self.failure = RuntimeError(f'UI watchdog cleanup failed: {cleanup}')

    def raise_if_failed(self):
        with self.lock:
            failure = self.failure
        if failure is not None:
            raise failure

    def stop(self):
        self.stop_event.set()
        self.thread.join(timeout=8)
        if self.thread.is_alive():
            raise RuntimeError('UI watchdog did not stop within its cleanup deadline')


def _supervise_owned_worker(command, *, state, reservation, log_path, wall_seconds,
                            environment, gate_fd=None, memory_mb=4096):
    """Monitor the actual isolated worker group; retain the claim on failure.

    ``gate_fd`` is a read pipe inherited by the production worker. Its owner
    closes the write end only after this function returns. Unit tests can omit
    the gate for an ordinary small subprocess. No shell commands are evaluated.
    """
    started = time.monotonic()
    peak_rss, peak_processes, checks = 0, 0, 0
    with Path(log_path).open('xb') as log:
        process = subprocess.Popen(command, cwd=ROOT, env=environment, stdin=subprocess.DEVNULL,
            stdout=log, stderr=subprocess.STDOUT, shell=False, start_new_session=True,
            pass_fds=(() if gate_fd is None else (gate_fd[0],)))
        birth = _process_birth(process.pid)
        watchdog = None
        try:
            if birth is None:
                raise RuntimeError('owned worker disappeared before resource attachment')
            watchdog = _WorkerWatchdog(process, birth, started=started,
                                       wall_seconds=wall_seconds, memory_mb=memory_mb)
            watchdog.start()
            # Attach before permitting the worker to import torch or open a DB.
            usage = reservation.check_usage(state, child_pid=process.pid)
            checks += 1
            peak_rss = usage['group_rss']['rss_bytes']
            peak_processes = usage['group_rss']['live_processes']
            watchdog.raise_if_failed()
            if gate_fd is not None:
                os.write(gate_fd[1], b'1')
            while True:
                watchdog.raise_if_failed()
                if time.monotonic() - started >= wall_seconds and process.poll() is None:
                    raise TimeoutError('UI worker exceeded its bounded wall deadline')
                usage = reservation.check_usage(state)
                checks += 1
                peak_rss = max(peak_rss, usage['group_rss']['rss_bytes'])
                peak_processes = max(peak_processes, usage['group_rss']['live_processes'])
                watchdog.raise_if_failed()
                if process.poll() is not None:
                    break
                try:
                    process.wait(timeout=min(0.5, max(0.001, wall_seconds - (time.monotonic() - started))))
                except subprocess.TimeoutExpired:
                    pass
            if process.returncode != 0:
                raise RuntimeError(f'UI worker exited {process.returncode}; inspect {log_path}')
            usage = reservation.check_usage(state)
            checks += 1
            if usage['group_rss']['live_processes']:
                raise RuntimeError('UI worker left a live descendant process group')
            watchdog.raise_if_failed()
        except BaseException:
            if watchdog is not None:
                watchdog.terminate()
            else:
                _stop_owned_group(process, birth)
            raise
        finally:
            if watchdog is not None:
                watchdog.stop()
            log.flush()
            os.fsync(log.fileno())
    watchdog.raise_if_failed()
    peak_rss = max(peak_rss, watchdog.peak_rss)
    peak_processes = max(peak_processes, watchdog.peak_processes)
    return {'schema': 'ui-feature-worker-resources/v1', 'worker_pid': process.pid,
            'worker_birth': birth, 'isolated_process_group': True,
            'resource_checks': checks, 'observed_peak_group_rss_bytes': peak_rss,
            'observed_peak_group_processes': peak_processes,
            'wall_seconds': time.monotonic() - started, 'wall_limit_seconds': wall_seconds,
            'memory_limit_bytes': watchdog.memory_bytes,
            'watchdog_samples': watchdog.samples,
            'watchdog_interval_seconds': WATCHDOG_INTERVAL_SECONDS,
            'memory_enforcement': 'independent_watchdog_owned_process_group_rss_checks',
            'memory_peak_scope': 'sampled_group_rss_not_kernel_peak_short_excursions_may_be_missed',
            'deadline_enforcement': 'independent_watchdog_terminates_owned_group',
            'registry_access': 'serialized_exclusive_owner_including_inference'}


def _owned_worker(request_path, gate_fd):
    """Internal child entry; the public CLI always owns resource admission."""
    with os.fdopen(gate_fd, 'rb', closefd=True) as gate:
        if gate.read(1) != b'1':
            raise RuntimeError('worker requires its owner resource-attachment gate')
    raw = Path(request_path).read_bytes()
    if len(raw) > MAX_WORKER_REQUEST_BYTES:
        raise ValueError('worker request exceeds byte bound')
    config = json.loads(raw)
    if config['owner_pid'] != os.getppid() or os.getpgrp() != os.getpid():
        raise RuntimeError('worker must be a direct owned process-group leader')
    sys.path.insert(0, str(ROOT))
    from ipfs_datasets_py.logic.autoformal.tree_pin import require_workspace_logic_tree
    require_workspace_logic_tree()
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import ui_feature_training as ui
    from ipfs_datasets_py.duckdb_control.autoencoder_registry import AutoencoderRegistry
    import torch
    torch.set_num_threads(1)
    state, attempt = Path(config['state']), Path(config['attempt'])
    # This registry has exactly one owner. Inference does not train/register,
    # but opening the registry advances its owner generation and takes its lock.
    with AutoencoderRegistry(state/'control.duckdb', state/'artifacts') as registry:
        if config['operation'] == 'train':
            result = ui.train_ui_feature_batch(registry, config['rows'], config['tuning'], attempt,
                parent_version_id=config['parent_version_id'], projection_ids=config['projections'],
                epochs=config['epochs'], latent_width=config['latent_width'],
                learning_rate=config['learning_rate'], max_seconds=config['max_seconds'])
        elif config['operation'] == 'infer':
            result = ui.infer_ui_feature_batch(registry, config['parent_version_id'], config['rows'], attempt)
        else:
            raise ValueError('unknown worker operation')
    ui._save(config['result_path'], {
        'operation': config['operation'], 'registration': result.get('registration'),
        'training_executed': result['training_executed'], 'transport_executed': False,
        'registry_access': 'serialized_exclusive_owner_including_inference', **ui.features.FALSE})


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('operation', choices=('train', 'infer'))
    p.add_argument('--input-jsonl', type=Path, required=True)
    p.add_argument('--tuning-jsonl', type=Path)
    p.add_argument('--state-directory', type=Path, required=True)
    p.add_argument('--attempt-id', required=True)
    p.add_argument('--parent-version-id')
    p.add_argument('--projection', action='append')
    p.add_argument('--epochs', type=int, default=3)
    p.add_argument('--latent-width', type=int, default=4)
    p.add_argument('--learning-rate', type=float, default=0.02)
    p.add_argument('--max-seconds', type=float, default=60.0)
    p.add_argument('--resource-ledger', type=Path, default=DEFAULT_LEDGER)
    p.add_argument('--storage-bytes', type=int, default=128_000_000)
    p.add_argument('--memory-mb', type=int, default=4096)
    p.add_argument('--plan', action='store_true', help='Read bounded JSONL and report configuration; no compiler, database or optimizer')
    return p


def main(argv=None):
    supplied = list(sys.argv[1:] if argv is None else argv)
    args = parser().parse_args(supplied)
    if not re.fullmatch('[A-Za-z0-9][A-Za-z0-9_.-]{0,63}', args.attempt_id):
        raise ValueError('invalid attempt ID')
    if args.operation == 'train' and args.tuning_jsonl is None:
        raise ValueError('training needs a separate tuning JSONL')
    if args.operation == 'infer' and (not args.parent_version_id or args.tuning_jsonl is not None):
        raise ValueError('inference requires a saved version and accepts no tuning/training input')
    if args.operation == 'infer' and any(value.split('=')[0] in {
            '--epochs', '--latent-width', '--learning-rate', '--max-seconds', '--projection'} for value in supplied):
        raise ValueError('inference does not accept optimizer or projection-change options')
    if not 16_000_000 <= args.storage_bytes <= 1_000_000_000 or not 1024 <= args.memory_mb <= 8192:
        raise ValueError('bounded storage and memory budgets required')
    if not (1 <= args.epochs <= 32 and 1 <= args.latent_width <= 64
            and 0 < args.learning_rate <= .1 and 0 < args.max_seconds <= 300):
        raise ValueError('invalid bounded numerical configuration')
    state = args.state_directory.resolve()
    attempt = state/'attempts'/args.attempt_id
    if attempt.exists():
        raise ValueError('use a fresh attempt ID; resume names the prior registered version')
    sys.path.insert(0, str(ROOT))
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import ui_feature_training as ui
    rows, source = ui.load_ui_training_jsonl(args.input_jsonl)
    tuning, tuning_source = ui.load_ui_training_jsonl(args.tuning_jsonl) if args.tuning_jsonl else (None, None)
    projections = args.projection or list(ui.DEFAULT_PROJECTIONS)
    plan = {'schema': 'ui-feature-cli-plan/v1', 'operation': args.operation,
            'inputs': source, 'tuning_inputs': tuning_source, 'row_count': len(rows),
            'tuning_count': len(tuning or []), 'projection_ids': projections,
            'parent_version_id': args.parent_version_id, 'state_directory': str(state),
            'attempt_directory': str(attempt), 'storage_bytes': args.storage_bytes,
            'memory_mb': args.memory_mb,
            'worker_wall_limit_seconds': args.max_seconds + WORKER_STARTUP_PREPARATION_SECONDS,
            'final_receipt_headroom_bytes': FINAL_RECEIPT_HEADROOM_BYTES,
            'registry_access': 'serialized_exclusive_owner_including_inference', 'training_executed': False,
            'compiler_executed': False, 'transport_executed': False, **ui.features.FALSE}
    if args.plan:
        print(json.dumps(plan, indent=2)); return plan
    from ipfs_datasets_py.logic.autoformal.tree_pin import require_workspace_logic_tree
    require_workspace_logic_tree()
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_daemon_resources import DaemonResourceReservation
    ledger = json.loads(args.resource_ledger.read_bytes())
    roots = [Path(row['path']).resolve() for row in ledger['roots']]
    if not any(state.is_relative_to(root) for root in roots):
        raise ValueError('state directory must be beneath an existing resource ledger root')
    if args.operation == 'infer' and not (state/'control.duckdb').is_file():
        raise ValueError('inference needs the existing local UI registry')
    # CPU choice is explicit for this bounded backend, not automatic CUDA selection.
    environment = dict(os.environ)
    environment['CUDA_VISIBLE_DEVICES'] = ''
    for name in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS'):
        environment[name] = '1'
    with DaemonResourceReservation(args.resource_ledger, roots=roots,
            storage_bytes=args.storage_bytes, memory_mb=args.memory_mb,
            cpu_slots=1, child_process_slots=1, timeout_seconds=10,
            ledger_lock_timeout_seconds=30) as reservation:
        state.mkdir(parents=True, exist_ok=True)
        reservation.check_usage(state)
        # Precharge the small post-finalization receipt before any release. The
        # complete request, output, log and inputs are included in the census.
        reservation.account_external_bytes('ui-final-resource-receipt', FINAL_RECEIPT_HEADROOM_BYTES)
        requests = state/'requests'
        requests.mkdir(exist_ok=True)
        request_path = requests/f'{args.attempt_id}.request.json'
        result_path = requests/f'{args.attempt_id}.result.json'
        log_path = requests/f'{args.attempt_id}.worker.log'
        config = {'owner_pid': os.getpid(), 'state': str(state), 'attempt': str(attempt),
                  'result_path': str(result_path), 'operation': args.operation,
                  'rows': rows, 'tuning': tuning, 'parent_version_id': args.parent_version_id,
                  'projections': projections, 'epochs': args.epochs, 'latent_width': args.latent_width,
                  'learning_rate': args.learning_rate, 'max_seconds': args.max_seconds}
        if len(ui._json(config)) > MAX_WORKER_REQUEST_BYTES:
            raise ValueError('worker request exceeds byte bound')
        ui._save(request_path, config)
        reservation.check_usage(state)
        gate = os.pipe()
        try:
            worker = _supervise_owned_worker(
                [sys.executable, str(Path(__file__).resolve()), '--_owned-worker', str(request_path), str(gate[0])],
                state=state, reservation=reservation, log_path=log_path,
                wall_seconds=args.max_seconds + WORKER_STARTUP_PREPARATION_SECONDS,
                environment=environment, gate_fd=gate, memory_mb=args.memory_mb)
        finally:
            os.close(gate[0])
            os.close(gate[1])
        result = json.loads(result_path.read_bytes())
        ui._save(attempt/'inputs.json', {'input': source, 'tuning': tuning_source})
        ui._save(attempt/'worker.json', worker)
        # Conservative: charge the complete local state including prior parents,
        # not just bytes newly written by this attempt.
        reservation.check_usage(state)
        resources = reservation.finalize(state, artifacts_durable=True)
        if len(ui._json(resources)) > FINAL_RECEIPT_HEADROOM_BYTES:
            raise RuntimeError('resource receipt exceeds its precharged headroom')
        ui._save(attempt/'resources.json', resources)
    summary = {'operation': args.operation, 'attempt_directory': str(attempt),
               'registration': result.get('registration'), 'training_executed': result['training_executed'],
               'transport_executed': False,
               'registry_access': 'serialized_exclusive_owner_including_inference', **ui.features.FALSE}
    print(json.dumps(summary, indent=2))
    return summary


if __name__ == '__main__':
    if len(sys.argv) == 4 and sys.argv[1] == '--_owned-worker':
        _owned_worker(sys.argv[2], int(sys.argv[3]))
    else:
        main()
