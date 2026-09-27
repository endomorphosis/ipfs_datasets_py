"""Root-owned 80 MB / 8 GiB / two CPU / 600 second native smoke reservation."""
import argparse
import ast
import ctypes
import json
import os
from pathlib import Path
import resource
import signal
import subprocess
import sys
import time
from smoke_resource_common import (ROOT, ACCELERATE, HERE, LEDGER, FILES, ScopedSources, bootstrap,
                                   durable, environment, exact, ref, require, save)

STORAGE = 80_000_000
MEMORY_MB = 8192
SECONDS = 600


class Descendants:
    """PID+birth fencing includes children that create new sessions or double-fork.

    This owner is a Linux subreaper, so otherwise orphaned descendants return
    here. Existing unrelated process groups are never signaled.
    """
    def __init__(self, process):
        self.process = process
        self.known = {}
        libc = ctypes.CDLL(None, use_errno=True)
        require(libc.prctl(36, 1, 0, 0, 0) == 0, 'cannot install child subreaper')
        current = ctypes.c_int()
        require(libc.prctl(37, ctypes.byref(current), 0, 0, 0) == 0 and current.value == 1,
                'child subreaper was not established')
    def observe(self):
        rows = {}
        entries = list(Path('/proc').iterdir())
        require(len(entries) <= 100_000, 'process inventory bound exceeded')
        for path in entries:
            if path.name.isdecimal():
                row = self.process(int(path.name))
                if row:
                    rows[row['pid']] = row
        selected = {os.getpid()}
        changed = True
        while changed:
            changed = False
            for pid, row in rows.items():
                owned = self.known.get(pid) == row['birth'] or row['parent_pid'] in selected
                if owned and pid not in selected:
                    selected.add(pid)
                    self.known[pid] = row['birth']
                    changed = True
        return [rows[pid] for pid in sorted(selected) if pid != os.getpid()]
    def living(self):
        return [row for row in self.observe() if row['state'] != 'Z']
    def signal(self, sig):
        for row in reversed(self.living()):
            current = self.process(row['pid'])
            if current and current['birth'] == row['birth']:
                try:
                    os.kill(row['pid'], sig)
                except ProcessLookupError:
                    pass
    def reap(self, child):
        # Let Popen preserve the root child's true wait status before reaping
        # adopted descendants. It may still be running at this boundary.
        child.poll()
        if child.returncode is None:
            return
        while True:
            try:
                pid, _status = os.waitpid(-1, os.WNOHANG)
                if not pid:
                    return
            except ChildProcessError:
                return
    def settle(self, child):
        if self.living():
            self.signal(signal.SIGTERM)
            deadline = time.monotonic() + 2
            while self.living() and time.monotonic() < deadline:
                child.poll()
                time.sleep(.05)
        deadline = time.monotonic() + 8
        while self.living() and time.monotonic() < deadline:
            self.signal(signal.SIGKILL)
            child.poll()
            time.sleep(.05)
        child.wait(timeout=2)
        self.reap(child)
        require(not self.living(), 'owned descendant termination is unconfirmed')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--attempt', type=Path, required=True)
    args = parser.parse_args()
    attempt = args.attempt.absolute()
    allowed = ROOT / 'workspace/test-logs/federal-corpus-audits'
    require(attempt.is_relative_to(allowed) and attempt != allowed, 'attempt outside owned audit root')
    require(not attempt.exists() and not attempt.is_symlink(), 'attempt must be new')
    require(attempt.resolve() == attempt, 'attempt ancestors must be canonical')
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    affinity = sorted(os.sched_getaffinity(0))
    require(len(affinity) >= 2, 'two CPU affinity slots unavailable')
    mem = dict(line.split(':', 1) for line in Path('/proc/meminfo').read_text().splitlines())
    require(int(mem['MemAvailable'].split()[0]) * 1024 >= MEMORY_MB * 1024**2,
            '8 GiB available host memory required before reservation')
    harness = [ref(HERE / name) for name in FILES]
    for name in FILES:
        if name.endswith('.py'):
            ast.parse((HERE / name).read_bytes(), filename=str(HERE / name))
    frozen = json.loads((HERE / 'frozen-config.json').read_bytes())
    require(ref(HERE / 'training_lane.py')['sha256'] == frozen['script_sha256'], 'training script pin changed')
    for name, expected in frozen['source_sha256'].items():
        require(ref(ROOT / name)['sha256'] == expected, 'frozen canonical source changed: ' + name)
    for name, expected in frozen['conversion_input_sha256'].items():
        require(ref(name)['sha256'] == expected, 'frozen conversion input changed: ' + name)
    checkpoint = ROOT / 'workspace/todo-queues/legal-ir-daemon-restart12-20260608T075001Z-best-8h-autoencoder.state.json'
    checkpoint_ref = ref(checkpoint)
    require(checkpoint_ref['bytes'] == 25_895_338 and checkpoint_ref['sha256'] ==
            '1446cb1859ddf4ed40fb5576f6e320eece4cec268a008c5c07bffeaf959cd8dd', 'protected checkpoint changed')
    accelerate_root = ACCELERATE / 'ipfs_accelerate_py'
    accelerate_paths = sorted(accelerate_root.rglob('*.py'))
    require(len(accelerate_paths) <= 5000, 'accelerate source closure exceeds bounded file inventory')
    accelerate_sources = [ref(path) for path in accelerate_paths]
    clean = environment(attempt)
    os.environ.clear()
    os.environ.update(clean)
    sources = ScopedSources()
    network = bootstrap(sources)
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_daemon_resources import DaemonResourceReservation, MAX_STORAGE_BYTES, _process, _group_usage
    require(MAX_STORAGE_BYTES == 62_000_000_000, 'campaign cap changed')
    roots = [ROOT / 'workspace/test-logs', ROOT / 'workspace/todo-queues',
             ROOT / 'docs/implementation/reports/evidence', Path('/tmp/pytest-of-barberb')]
    owner = DaemonResourceReservation(LEDGER, roots=roots, storage_bytes=STORAGE,
                memory_mb=MEMORY_MB, cpu_slots=2, timeout_seconds=0, ledger_lock_timeout_seconds=5)
    prior = owner._read()
    capacity = owner._account(prior, additional=2 * STORAGE + 5_000_000)
    prior_rows = prior['reservations']
    descendant = Descendants(_process)
    require(exact(harness) and exact(accelerate_sources), 'harness or accelerate source changed before admission')
    child = identity = None
    report = {'schema': 'concurrent-autoformal-owned-resource-audit/v1', 'passed': False,
              'bounds': {'storage_bytes': STORAGE, 'memory_mb': MEMORY_MB, 'cpu_slots': 2, 'seconds': SECONDS},
              'capacity_plan': capacity, 'prior_ledger_rows': prior_rows, 'prepared_harness': harness,
              'accelerate_source_files': len(accelerate_sources),
              'network_guard': network, 'admitted': False, 'formalized': False,
              'enforcement': 'cooperative polled storage/RSS; Linux subreaper PID-birth descendant custody'}
    started = time.monotonic()
    with owner:
        attempt.mkdir(parents=True)
        try:
            for name in ('tmp', 'hub', 'cache'):
                (attempt / name).mkdir()
            save(attempt / 'prepared-inputs.json', {'harness': harness, 'accelerate_sources': accelerate_sources})
            owner.check_usage(attempt)
            with (attempt / 'native-child.log').open('x') as log:
                child = subprocess.Popen([sys.executable, '-u', '-B', str(HERE / 'native_guard_child.py'),
                          '--attempt', str(attempt)], cwd=ROOT, env=environment(attempt),
                          stdin=subprocess.PIPE, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
                row = _process(child.pid)
                require(row and row['parent_pid'] == os.getpid() and row['group_pid'] == child.pid,
                        'native child ownership differs')
                identity = {key: row[key] for key in ('pid', 'birth')}
                descendant.observe()
                owner.check_usage(attempt, child.pid)
                require(owner.to_dict()['record']['child'] == identity, 'native child registration differs')
                os.sched_setaffinity(child.pid, set(affinity[:2]))
                child.stdin.write(b'RUN\n')
                child.stdin.flush()
                child.stdin.close()
                last_usage = 0.0
                peak_rss = 0
                while child.poll() is None:
                    elapsed = time.monotonic() - started
                    require(elapsed < SECONDS, 'native smoke 600 second deadline exceeded')
                    live = descendant.living()
                    rss = sum(row['rss_bytes'] for row in live)
                    peak_rss = max(peak_rss, rss)
                    require(rss <= MEMORY_MB * 1024**2, 'owned descendant RSS exceeded 8 GiB')
                    if time.monotonic() - last_usage >= 5:
                        usage = owner.check_usage(attempt)
                        last_usage = time.monotonic()
                        print(json.dumps({'elapsed_seconds': elapsed, 'attempt_bytes': usage['attempt_bytes'],
                                          'descendant_rss_bytes': rss, 'owned_live_processes': len(live)}), flush=True)
                    try:
                        child.wait(timeout=.25)
                    except subprocess.TimeoutExpired:
                        pass
                log.flush()
                os.fsync(log.fileno())
            require(not descendant.living(), 'native driver exited with living descendants')
            descendant.reap(child)
            save(attempt / 'child-terminal.json', {'returncode': child.returncode, 'identity': identity,
                                                'elapsed_seconds': time.monotonic() - started})
            report.update(child_returncode=child.returncode, descendant_peak_rss_bytes=peak_rss,
                          child_group_dead=_group_usage(identity)['live_processes'] == 0,
                          owned_descendants_dead=True, owned_descendant_identities=descendant.known)
            require(child.returncode == 0, 'native supervisor child failed')
            result = json.loads((attempt / 'child-source-receipt.json').read_bytes())
            require(result['passed'] is True and exact(result['scoped_sources']), 'child source receipt failed')
            native = json.loads((attempt / 'supervisor/supervisor-receipt.json').read_bytes())
            require(native['passed'] is True and native['native_task']['status'] == 'completed', 'native completion absent')
            require(exact(harness), 'prepared harness changed during smoke')
            require(sorted(accelerate_root.rglob('*.py')) == accelerate_paths and exact(accelerate_sources),
                    'accelerate source closure changed during smoke')
            report['scoped_sources'] = sources.verify()
            current = owner._read()['reservations']
            require(all(current.get(key) == value for key, value in prior_rows.items()), 'prior reservation row changed')
            require(time.monotonic() - started <= SECONDS, 'native smoke deadline exceeded')
            report.update(passed=True, child_receipt=ref(attempt / 'child-source-receipt.json'),
                          native_receipt=ref(attempt / 'supervisor/supervisor-receipt.json'),
                          prior_ledger_rows_unchanged=True, final_usage=owner.check_usage(attempt))
        except BaseException as exc:
            report['error'] = {'type': type(exc).__name__, 'message': str(exc)[:3000]}
            if child is not None:
                try:
                    descendant.settle(child)
                    report.update(child_returncode=child.returncode, owned_descendants_dead=True,
                                  owned_descendant_identities=descendant.known)
                    if not (attempt / 'child-terminal.json').exists():
                        save(attempt / 'child-terminal.json', {'returncode': child.returncode, 'identity': identity,
                                                              'stopped_after_error': True})
                except BaseException as cleanup:
                    report['cleanup_error'] = {'type': type(cleanup).__name__, 'message': str(cleanup)}
        report['elapsed_seconds'] = time.monotonic() - started
        report['reservation_at_publication'] = owner.to_dict()
        save(attempt / 'audit-receipt.json', report)
        durable(attempt)
        if report['passed']:
            save(attempt / 'resource-release.json', owner.release(artifacts_durable=True))
            durable(attempt)
    if not report['passed']:
        save(attempt / 'resource-retention.json', owner.to_dict())
        durable(attempt)
    print(json.dumps({'passed': report['passed'], 'audit': str(attempt / 'audit-receipt.json')}), flush=True)
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
