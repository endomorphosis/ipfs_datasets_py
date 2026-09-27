"""Prepare an immutable published dependency under a 1 GB owned reservation.

Preparation only until root explicitly invokes this wrapper. Never imports the
new dependency, trains, downloads weights, fetches Git, or initializes submodules.
"""
import argparse
import ast
import hashlib
import json
import os
from pathlib import Path
import re
import resource
import signal
import subprocess
import sys
import time

from dependency_export_common import (
    ROOT, ACCELERATE, HERE, LEDGER, GIT_ENV, Descendants, ScopedSources,
    bootstrap, durable, environment, exact, ref, require, save,
)

STORAGE = 1_000_000_000
MEMORY_MB = 2048
SECONDS = 600
MAX_SOURCE_BYTES = 180_000_000
PLANNED_ATTEMPT = ROOT / 'workspace/test-logs/federal-corpus-audits/concurrent-autoformal-dependency-20260927/capture-r2'
EXPORTER = ROOT / 'scripts/ops/legal_ir/prepare_autoformal_dependency.py'
SUFFIXES = {'.py', '.sql', '.json', '.toml', '.txt', '.typed', '.cfg'}
ROOT_PATHS = {'.gitattributes', '.gitignore', '.gitmodules', 'README.md', 'LICENSE',
              'pyproject.toml', 'setup.py', 'setup.cfg', 'requirements.txt',
              'test/__init__.py', 'test/conftest.py', 'test/api/__init__.py', 'test/api/conftest.py'}


def git(repo, *arguments, env, deadline, limit=8_000_000, input_bytes=None):
    remaining = deadline - time.monotonic()
    require(remaining > 0, 'dependency creation deadline exceeded')
    result = subprocess.run(['git', '-c', 'core.hooksPath=/dev/null', *arguments], cwd=repo,
                            env=env, input=input_bytes, capture_output=True, timeout=min(30, remaining), check=True)
    require(len(result.stdout) <= limit and len(result.stderr) <= limit, 'Git metadata exceeds bound')
    return result.stdout


def source_identity(env, deadline):
    head = git(ACCELERATE, 'rev-parse', '--verify', 'HEAD', env=env, deadline=deadline).decode().strip()
    raw = git(ACCELERATE, 'rev-parse', '--git-path', 'index', env=env, deadline=deadline).decode().strip()
    path = Path(raw)
    if not path.is_absolute():
        path = ACCELERATE / path
    return {'head': head, 'index': ref(path)}


def selected_paths(revision, env, deadline):
    raw = git(ACCELERATE, 'ls-tree', '-r', '-z', revision, env=env, deadline=deadline)
    rows = []
    for entry in raw.split(b'\0'):
        if not entry:
            continue
        metadata, name = entry.split(b'\t', 1)
        mode, kind, oid = metadata.decode().split()
        path = name.decode('utf-8')
        selected = path in ROOT_PATHS or (
            path.startswith('ipfs_accelerate_py/') and Path(path).suffix in SUFFIXES
        ) or (path.startswith('test/api/test_agent_supervisor') and path.endswith('.py'))
        if not selected:
            continue
        require(kind == 'blob' and mode in {'100644', '100755'}, 'selected dependency path is not a regular blob')
        require(not Path(path).is_absolute() and '..' not in Path(path).parts, 'unsafe committed dependency path')
        rows.append({'path': path, 'git_blob': oid, 'mode': mode})
    rows.sort(key=lambda row: row['path'])
    require(1 <= len(rows) <= 5000 and len({row['path'] for row in rows}) == len(rows), 'source inventory exceeds bound')
    require(any(row['path'] == 'ipfs_accelerate_py/__init__.py' for row in rows), 'selected package is missing')
    sizes = git(ACCELERATE, 'cat-file', '--batch-check=%(objectname) %(objecttype) %(objectsize)',
                env=env, deadline=deadline,
                input_bytes=''.join(row['git_blob'] + '\n' for row in rows).encode()).decode().splitlines()
    require(len(sizes) == len(rows), 'committed size inventory differs')
    for row, line in zip(rows, sizes):
        fields = line.split()
        require(len(fields) == 3 and fields[:2] == [row['git_blob'], 'blob'], 'committed source blob is missing')
        row['bytes'] = int(fields[2])
        require(0 <= row['bytes'] <= 8_000_000, 'selected source file exceeds 8 MB')
    total = sum(row['bytes'] for row in rows)
    require(total <= MAX_SOURCE_BYTES, 'selected source exceeds 180 MB')
    require(3 * total + 512 * 1024 * 1024 < STORAGE, 'export helper headroom exceeds 1 GB reservation')
    return rows


def main():
    started = time.monotonic()
    deadline = started + SECONDS
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--revision', required=True)
    parser.add_argument('--attempt', type=Path, required=True)
    args = parser.parse_args()
    require(re.fullmatch(r'[0-9a-f]{40}', args.revision) is not None, 'revision must be a full commit SHA')
    attempt = args.attempt.absolute()
    require(attempt == PLANNED_ATTEMPT and attempt.resolve() == attempt, 'attempt differs from explicit owned plan')
    require(not attempt.exists() and not attempt.is_symlink(), 'new capture required; failed captures are retained')
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    resource.setrlimit(resource.RLIMIT_FSIZE, (128_000_000, 128_000_000))
    clean = environment(attempt)
    clean.update(GIT_NO_LAZY_FETCH='1', GIT_LFS_SKIP_SMUDGE='1', GIT_TERMINAL_PROMPT='0')
    for name in GIT_ENV:
        clean.pop(name, None)
    os.environ.clear()
    os.environ.update(clean)
    sources = ScopedSources()
    network = bootstrap(sources)
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_daemon_resources import (
        DaemonResourceReservation, MAX_STORAGE_BYTES, _process, _group_usage,
    )
    require(MAX_STORAGE_BYTES == 75_000_000_000, 'campaign cap differs from approved 75 GB')
    descendant = Descendants(_process)
    def alarm(_signal, _frame):
        raise TimeoutError('whole dependency creation exceeded 600 seconds')
    signal.signal(signal.SIGALRM, alarm)
    signal.setitimer(signal.ITIMER_REAL, max(.01, deadline - time.monotonic()))
    require(git(ACCELERATE, 'rev-parse', 'origin/main', env=clean, deadline=deadline).decode().strip() == args.revision,
            'revision differs from locally fetched published main; root must refresh publication audit')
    identity_before = source_identity(clean, deadline)
    implementation = [ref(HERE / name) for name in (
        'create_published_dependency_reserved.py', 'dependency_export_common.py', 'dependency_binding.py')]
    exporter = ref(EXPORTER)
    ast.parse(EXPORTER.read_bytes(), filename=str(EXPORTER))
    selection = selected_paths(args.revision, clean, deadline)
    committed_bytes = sum(row['bytes'] for row in selection)
    roots = [ROOT / 'workspace/test-logs', ROOT / 'workspace/todo-queues',
             ROOT / 'docs/implementation/reports/evidence', Path('/tmp/pytest-of-barberb')]
    owner = DaemonResourceReservation(LEDGER, roots=roots, storage_bytes=STORAGE,
                                     memory_mb=MEMORY_MB, cpu_slots=1, timeout_seconds=0,
                                     ledger_lock_timeout_seconds=5)
    prior = owner._read()
    capacity = owner._account(prior, additional=2 * STORAGE + 5_000_000)
    prior_rows = prior['reservations']
    require(exact(implementation) and ref(EXPORTER) == exporter, 'export implementation changed before admission')
    child = child_identity = None
    report = {'schema': 'autoformal-published-dependency-owned-export/v1', 'passed': False,
              'source_root': str(ACCELERATE), 'source_commit': args.revision,
              'source_identity_before': identity_before, 'implementation': implementation, 'exporter': exporter,
              'bounds': {'storage_bytes': STORAGE, 'memory_mb': MEMORY_MB, 'cpu_slots': 1, 'seconds': SECONDS},
              'selected_files': len(selection), 'committed_bytes': committed_bytes,
              'capacity_plan': capacity, 'prior_ledger_rows': prior_rows, 'network_guard': network,
              'training_run': False, 'dependency_qualified': False, 'live_quack_exercised': False,
              'scope': 'committed source export only', 'admitted': False, 'formalized': False}
    destination = attempt / 'published-source'
    with owner:
        attempt.mkdir(parents=True)
        try:
            for name in ('tmp', 'hub', 'cache'):
                (attempt / name).mkdir()
            save(attempt / 'selected-committed-paths.json', {'source_commit': args.revision, 'files': selection})
            owner.check_usage(attempt)
            gate = ("import sys,runpy; "
                    "line=sys.stdin.readline(); "
                    "assert line == 'RUN\\n', 'missing owned export handshake'; "
                    "sys.argv=sys.argv[1:]; runpy.run_path(sys.argv[0],run_name='__main__')")
            command = [sys.executable, '-u', '-B', '-c', gate, str(EXPORTER), '--source', str(ACCELERATE),
                       '--revision', args.revision, '--runtime-root', str(attempt),
                       '--destination', str(destination), '--storage-limit-bytes', str(STORAGE)]
            for row in selection:
                command.extend(['--path', row['path']])
            with (attempt / 'export.log').open('x') as log:
                child = subprocess.Popen(command, cwd=ROOT, env=clean, stdin=subprocess.PIPE,
                                         stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
                process = _process(child.pid)
                require(process and process['parent_pid'] == os.getpid() and process['group_pid'] == child.pid,
                        'dependency exporter child identity differs')
                child_identity = {key: process[key] for key in ('pid', 'birth')}
                owner.check_usage(attempt, child.pid)
                descendant.observe()
                os.sched_setaffinity(child.pid, {min(os.sched_getaffinity(0))})
                require(owner.to_dict()['record']['child'] == child_identity, 'exporter registration differs')
                child.stdin.write(b'RUN\n')
                child.stdin.flush()
                child.stdin.close()
                peak_rss, last_usage = 0, 0.0
                while child.poll() is None:
                    require(time.monotonic() < deadline, 'dependency creation deadline exceeded')
                    live = descendant.living()
                    rss = sum(row['rss_bytes'] for row in live)
                    peak_rss = max(peak_rss, rss)
                    require(rss <= MEMORY_MB * 1024**2, 'dependency exporter descendant RSS exceeds 2 GiB')
                    if time.monotonic() - last_usage >= 5:
                        usage = owner.check_usage(attempt)
                        last_usage = time.monotonic()
                        print(json.dumps({'stage': 'exporting_source_only', 'elapsed_seconds': last_usage - started,
                                          'attempt_bytes': usage['attempt_bytes'], 'descendant_rss_bytes': rss}), flush=True)
                    try:
                        child.wait(timeout=.25)
                    except subprocess.TimeoutExpired:
                        pass
                log.flush()
                os.fsync(log.fileno())
            require(not descendant.living(), 'exporter left living descendants')
            descendant.reap(child)
            save(attempt / 'child-terminal.json', {'returncode': child.returncode, 'identity': child_identity})
            report.update(child_returncode=child.returncode, descendant_peak_rss_bytes=peak_rss,
                          owned_descendants_dead=True, owned_descendant_identities=descendant.known)
            require(child.returncode == 0, 'dependency source exporter failed')
            export_path = attempt / 'published-source-snapshot.json'
            exported = json.loads(export_path.read_bytes())
            require(exported.get('source_commit') == args.revision and exported.get('snapshot') == str(destination)
                    and exported.get('source_modified') is False and exported.get('monkey_patched') is False
                    and exported.get('qualified') is False and exported.get('committed_bytes') == committed_bytes
                    and exported.get('packaging_paths') == [row['path'] for row in selection], 'export receipt differs')
            snapshot_commit = git(destination, 'rev-parse', 'HEAD', env=clean, deadline=deadline).decode().strip()
            require(snapshot_commit == exported['snapshot_commit'], 'snapshot commit differs')
            files = []
            for row in selection:
                path = destination / row['path']
                observed = ref(path)
                raw = path.read_bytes()
                oid = hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()
                require(observed['bytes'] == row['bytes'] and oid == row['git_blob'], 'export differs from committed blob')
                files.append({**row, 'sha256': observed['sha256']})
            manifest = {'schema': 'autoformal-published-dependency-manifest/v1',
                        'source_root': str(ACCELERATE), 'source_commit': args.revision,
                        'snapshot_root': str(destination), 'snapshot_commit': snapshot_commit,
                        'committed_bytes': committed_bytes, 'files': files, 'export_receipt': ref(export_path),
                        'qualified': False, 'admitted': False, 'formalized': False}
            manifest_ref = save(attempt / 'dependency-manifest.json', manifest)
            binding = {'root': str(destination), 'source_commit': args.revision, 'snapshot_commit': snapshot_commit,
                       'manifest_path': manifest_ref['path'], 'manifest_sha256': manifest_ref['sha256']}
            from dependency_binding import verify_binding
            observation = verify_binding(binding)
            identity_after = source_identity(clean, deadline)
            require(identity_after == identity_before, 'source HEAD/index changed during export')
            require(exact(implementation) and ref(EXPORTER) == exporter, 'export implementation changed')
            current_rows = owner._read()['reservations']
            require(all(current_rows.get(key) == value for key, value in prior_rows.items()),
                    'prior ledger row changed during export')
            durable(attempt)
            require(time.monotonic() < deadline, 'dependency creation deadline exceeded before durable completion')
            report.update(passed=True, source_identity_after=identity_after, dependency_binding=binding,
                          dependency_observation=observation, prior_ledger_rows_unchanged=True,
                          scoped_sources=sources.verify(), final_usage=owner.check_usage(attempt))
            save(attempt / 'dependency-binding.json', binding)
        except BaseException as exc:
            report['error'] = {'type': type(exc).__name__, 'message': str(exc)[:3000]}
            # Deadline expiry must not interrupt termination and durable capture.
            signal.setitimer(signal.ITIMER_REAL, 0)
            if child is not None:
                try:
                    descendant.settle(child)
                    report.update(child_returncode=child.returncode, owned_descendants_dead=True,
                                  owned_descendant_identities=descendant.known)
                    if not (attempt / 'child-terminal.json').exists():
                        save(attempt / 'child-terminal.json', {'returncode': child.returncode,
                                                              'identity': child_identity, 'stopped_after_error': True})
                except BaseException as cleanup:
                    report['cleanup_error'] = {'type': type(cleanup).__name__, 'message': str(cleanup)[:1000]}
        signal.setitimer(signal.ITIMER_REAL, 0)
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
    print(json.dumps({'passed': report['passed'], 'audit': str(attempt / 'audit-receipt.json'),
                      'qualified': False, 'training_run': False}), flush=True)
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
