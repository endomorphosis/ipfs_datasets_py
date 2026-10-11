"""Reuse the authenticated resource owner for a bounded, source-only census phase."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

BASE = Path('/home/barberb/lift_coding')
HELPERS = BASE / 'artifacts/autoencoder-dual-bank-fit-20261007/parent-replay-guardian-source-r2'
sys.path.insert(0, str(HELPERS))
from run_reserved import resource_owner, capture_owned_child, cleanup_owned_group, SOURCE, PACKAGE
from adopt_shared_scheduler import adopt_for_owner
from lazy_scheduler_adoption import install
from owned_lease_watchdog import OwnedLeaseWatchdog, capture_lease_binding, safe_owner_snapshot


def save(path, value):
    with path.open('w') as stream:
        json.dump(value, stream, sort_keys=True, indent=2)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())


def sync_tree(path):
    for item in path.rglob('*'):
        if item.is_file() and not item.is_symlink():
            with item.open('rb') as stream:
                os.fsync(stream.fileno())
    for directory in sorted([path] + [p for p in path.rglob('*') if p.is_dir()],
                            key=lambda p: len(p.parts), reverse=True):
        fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--command-file', type=Path, required=True)
    parser.add_argument('--attempt', required=True)
    parser.add_argument('--source-root', type=Path, required=True)
    parser.add_argument('--storage-bytes', type=int, required=True)
    parser.add_argument('--memory-mb', type=int, default=1536)
    parser.add_argument('--seconds', type=int, default=900)
    args = parser.parse_args()
    if Path(args.attempt).name != args.attempt or args.attempt in ('', '.', '..'):
        raise ValueError('fresh single-component attempt required')
    if not 1 <= args.seconds <= 1800:
        raise ValueError('deadline must be between one and 1800 seconds')
    command = json.loads(args.command_file.read_bytes())
    if not isinstance(command, list) or not command or any(not isinstance(x, str) for x in command):
        raise ValueError('explicit argument array required')
    run = PACKAGE / 'workspace/test-logs/uscode-identity-recovery-20261011-01'
    run.mkdir(exist_ok=True)
    attempt = run / args.attempt
    if attempt.exists():
        raise ValueError('completed attempt may not be overwritten')
    resources = resource_owner()
    complete_adoption = install(resources, adopt_for_owner, source_root=SOURCE,
                               receipt_path=run / (args.attempt + '-scheduler-adoption.json'))
    roots = [PACKAGE / 'workspace/test-logs', PACKAGE / 'workspace/todo-queues',
             PACKAGE / 'docs/implementation/reports/evidence', Path('/tmp/pytest-of-barberb')]
    ledger = roots[0] / 'federal-corpus-audits/owned-daemon-resource-control/disk-reservations.json'
    owner = resources.DaemonResourceReservation(ledger, roots=roots,
        storage_bytes=args.storage_bytes, memory_mb=args.memory_mb,
        cpu_slots=1, child_process_slots=1, timeout_seconds=600, ledger_lock_timeout_seconds=60)
    child = identity = watchdog = None
    started = time.monotonic()
    try:
        with owner:
            try:
                attempt.mkdir()
                save(attempt / 'command.json', dict(command=command, cwd=str(args.source_root.resolve()),
                    storage_bytes=args.storage_bytes, memory_mb=args.memory_mb, cpu_slots=1,
                    command_sha256=hashlib.sha256(args.command_file.read_bytes()).hexdigest(),
                    source_only=True, models_executed=False, training_executed=False,
                    proof_authority=False, adopted_scheduler=complete_adoption()))
                binding = capture_lease_binding(owner, complete_adoption(), resources)
                watchdog = OwnedLeaseWatchdog(binding, resources=resources,
                    events_path=attempt / 'lease-observations.jsonl')
                watchdog.observe('pre_spawn')
                save(attempt / 'lease-binding.json', binding.public())
                env = dict(os.environ, PYTHONPATH=str(args.source_root.resolve()),
                    PYTHONDONTWRITEBYTECODE='1', CUDA_VISIBLE_DEVICES='', OMP_NUM_THREADS='1',
                    OPENBLAS_NUM_THREADS='1', MKL_NUM_THREADS='1',
                    IPFS_DATASETS_PY_LAZY_INSTALL_ERGOAI='0')
                with (attempt / 'child.log').open('w') as stream:
                    child = subprocess.Popen(command, cwd=args.source_root, env=env,
                        stdout=stream, stderr=subprocess.STDOUT, start_new_session=True)
                    identity = capture_owned_child(child, resources)
                    save(attempt / 'child-identity.json', identity)
                    watchdog.bind_child(identity)
                    watchdog.start()
                    observations = [owner.check_usage(attempt, child.pid)]
                    while child.poll() is None:
                        watchdog.assert_healthy()
                        if time.monotonic() - started > args.seconds:
                            raise TimeoutError('source census phase exceeded deadline')
                        time.sleep(2)
                        if child.poll() is None:
                            observations.append(owner.check_usage(attempt, child.pid))
                            save(attempt / 'resource-observations.json', observations)
                    code = child.wait()
                    stream.flush()
                    os.fsync(stream.fileno())
                watchdog.stop()
                watchdog.assert_healthy()
                cleanup = cleanup_owned_group(child, identity, resources)
                save(attempt / 'child-exit.json', dict(returncode=code, cleanup=cleanup,
                    elapsed_seconds=round(time.monotonic() - started, 3)))
                if code:
                    raise RuntimeError(f'source census child exited {code}')
                watchdog.observe('pre_finalize')
                sync_tree(attempt)
                final = owner.finalize(attempt, artifacts_durable=True)
                watchdog.observe('post_finalize', expected='absent')
                watchdog.close()
                save(attempt / 'resources-final.json', final)
                sync_tree(attempt)
                print(json.dumps(dict(status='complete', attempt=str(attempt), returncode=code,
                    reservation_id=owner.reservation_id)), flush=True)
            except BaseException as error:
                if watchdog is not None:
                    watchdog.stop()
                cleanup = cleanup_owned_group(child, identity, resources)
                save(attempt / 'failure.json', dict(error_type=type(error).__name__,
                    error=str(error), cleanup=cleanup, resources=safe_owner_snapshot(owner)))
                sync_tree(attempt)
                raise
    finally:
        if watchdog is not None:
            watchdog.close()


if __name__ == '__main__':
    main()
