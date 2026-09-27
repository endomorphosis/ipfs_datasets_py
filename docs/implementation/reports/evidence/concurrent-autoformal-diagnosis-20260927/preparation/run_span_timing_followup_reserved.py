"""50 MB / 2 GiB / CPU 6 / 120-second isolated span timing follow-up reservation."""
import argparse
import ast
import json
import os
from pathlib import Path
import resource
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / 'harness'))
from smoke_resource_common import (ROOT, ACCELERATE, LEDGER, DEPENDENCY, ScopedSources,
    bootstrap, durable, environment, exact, ref, require, save, verify_binding)
from run_native_smoke_reserved import Descendants
STORAGE = 50_000_000
MEMORY_MB = 2048
CPU = 6
SECONDS = 120
FILES = (HERE / 'run_span_timing_followup_reserved.py', HERE / 'span_timing_guard_child.py',
         HERE / 'span_timing_followup.py', HERE / 'harness/formal_validation.py',
         HERE / 'span-timing-inputs.json',
         HERE / 'harness/smoke_resource_common.py', HERE / 'harness/dependency_binding.py',
         HERE / 'harness/frozen-config.json', HERE / 'harness/run_native_smoke_reserved.py')


def prior_rows_preserved(before, after):
    for key, old in before.items():
        require(key in after, 'prior reservation disappeared')
        current = after[key]
        if old['status'] in {'released', 'retained'}:
            require(current == old, 'prior terminal storage claim changed')
        else:
            for field in ('reservation_id', 'storage_bytes', 'owner_pid', 'created_at', 'memory_mb', 'cpu_slots'):
                require(current.get(field) == old.get(field), 'prior active reservation identity changed')
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--attempt', type=Path, required=True)
    args = parser.parse_args()
    attempt = args.attempt.absolute()
    allowed = ROOT / 'workspace/test-logs/federal-corpus-audits'
    require(attempt.is_relative_to(allowed) and attempt != allowed and attempt.resolve() == attempt,
            'span timing attempt must be inside the canonical owned audit root')
    require(not attempt.exists() and not attempt.is_symlink(), 'span timing attempt must be fresh')
    require(CPU in os.sched_getaffinity(0), 'requested CPU 6 is not in permitted affinity')
    os.sched_setaffinity(0, {CPU})
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    mem = dict(line.split(':', 1) for line in Path('/proc/meminfo').read_text().splitlines())
    require(int(mem['MemAvailable'].split()[0]) * 1024 >= MEMORY_MB * 1024**2, '2 GiB available host memory required')
    frozen = [ref(path) for path in FILES]
    for path in FILES:
        if path.suffix == '.py': ast.parse(path.read_bytes(), filename=str(path))
    input_manifest = json.loads((HERE / 'span-timing-inputs.json').read_bytes())
    evidence_inputs = []
    for kind in ('retained_artifacts', 'validator_sources'):
        rows = input_manifest[kind]
        require(isinstance(rows, list) and rows, 'span timing input manifest is incomplete: ' + kind)
        for expected in rows:
            actual = ref(expected['path'])
            require(actual['sha256'] == expected['sha256'] and actual['bytes'] == expected['bytes'],
                    'span timing retained artifact or validator source differs')
            evidence_inputs.append(actual)
    dependency = verify_binding(DEPENDENCY)
    clean = environment(attempt)
    clean['IPFS_DATASETS_LEGAL_IR_TARGET_TIMEOUT_SECONDS'] = '60'
    os.environ.clear(); os.environ.update(clean)
    sources = ScopedSources()
    network = bootstrap(sources)
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_daemon_resources import DaemonResourceReservation, MAX_STORAGE_BYTES, _process, _group_usage
    require(MAX_STORAGE_BYTES == 75_000_000_000, 'campaign cap changed')
    roots = [ROOT / 'workspace/test-logs', ROOT / 'workspace/todo-queues', ROOT / 'docs/implementation/reports/evidence', Path('/tmp/pytest-of-barberb')]
    owner = DaemonResourceReservation(LEDGER, roots=roots, storage_bytes=STORAGE, memory_mb=MEMORY_MB,
                                     cpu_slots=1, timeout_seconds=0, ledger_lock_timeout_seconds=30)
    prior = owner._read(); capacity = owner._account(prior, additional=2 * STORAGE + 5_000_000)
    descendants = Descendants(_process)
    started = time.monotonic()
    child = identity = None
    peak_rss = 0
    report = {'schema': 'span-timing-followup-owned-resource-audit/v1', 'passed': False,
              'bounds': {'storage_bytes': STORAGE, 'memory_mb': MEMORY_MB, 'cpu_slots': 1, 'cpu_affinity': [CPU], 'seconds': SECONDS},
              'capacity_plan': capacity, 'prepared_files': frozen, 'evidence_inputs': evidence_inputs,
              'accelerate_dependency': dependency,
              'network_guard': network, 'admitted': False, 'formalized': False,
              'training_executed': False, 'provider_calls': 0, 'database_opened': False,
              'enforcement': 'cooperative polled storage/RSS; offline seccomp; Linux subreaper PID-birth descendant custody'}
    with owner:
        attempt.mkdir(parents=True)
        try:
            for name in ('tmp', 'hub', 'cache'): (attempt / name).mkdir()
            save(attempt / 'prepared-inputs.json', {'files': frozen, 'evidence_inputs': evidence_inputs, 'accelerate_dependency': DEPENDENCY})
            owner.check_usage(attempt)
            require(exact(frozen + evidence_inputs), 'span timing source changed before launch')
            with (attempt / 'span-child.log').open('x') as log:
                child = subprocess.Popen([sys.executable, '-u', '-B', str(HERE / 'span_timing_guard_child.py'),
                    '--attempt', str(attempt)], cwd=ROOT, env=environment(attempt), stdin=subprocess.PIPE,
                    stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
                row = _process(child.pid)
                require(row and row['parent_pid'] == os.getpid() and row['group_pid'] == child.pid,
                        'span timing child ownership differs')
                identity = {key: row[key] for key in ('pid', 'birth')}
                descendants.observe(); owner.check_usage(attempt, child.pid)
                require(owner.to_dict()['record']['child'] == identity, 'span timing child registration differs')
                os.sched_setaffinity(child.pid, {CPU})
                child.stdin.write(b'RUN\n'); child.stdin.flush(); child.stdin.close()
                last_usage = 0
                while child.poll() is None:
                    elapsed = time.monotonic() - started
                    require(elapsed < SECONDS, 'span timing follow-up 120-second outer deadline exceeded')
                    live = descendants.living(); rss = sum(row['rss_bytes'] for row in live)
                    peak_rss = max(peak_rss, rss)
                    require(rss <= MEMORY_MB * 1024**2, 'span timing owned descendants exceeded 2 GiB RSS')
                    if time.monotonic() - last_usage >= 10:
                        usage = owner.check_usage(attempt); last_usage = time.monotonic()
                        print(json.dumps({'elapsed_seconds': elapsed, 'attempt_bytes': usage['attempt_bytes'],
                                          'descendant_rss_bytes': rss, 'owned_live_processes': len(live)}), flush=True)
                    try: child.wait(timeout=.25)
                    except subprocess.TimeoutExpired: pass
                log.flush(); os.fsync(log.fileno())
            require(not descendants.living(), 'span timing child exited with living owned descendants')
            descendants.reap(child)
            save(attempt / 'child-terminal.json', {'returncode': child.returncode, 'identity': identity})
            report.update(child_returncode=child.returncode, owned_descendants_dead=True,
                          child_group_dead=_group_usage(identity)['live_processes'] == 0,
                          owned_descendant_identities=descendants.known, descendant_peak_rss_bytes=peak_rss)
            require(child.returncode == 0, 'span timing child failed')
            result = json.loads((attempt / 'child-source-receipt.json').read_bytes())
            require(result['passed'] is True and exact(result['scoped_sources']), 'span timing child source receipt failed')
            require(exact(frozen + evidence_inputs), 'span timing frozen source changed')
            require(time.monotonic() - started <= SECONDS, 'span timing follow-up exceeded outer deadline')
            report['accelerate_dependency_after'] = verify_binding(DEPENDENCY)
            report['scoped_sources'] = sources.verify()
            report['prior_ledger_claims_preserved'] = prior_rows_preserved(prior['reservations'], owner._read()['reservations'])
            final_usage = owner.check_usage(attempt)
            require(time.monotonic() - started <= SECONDS, 'span timing follow-up exceeded outer deadline')
            report.update(passed=True, child_receipt=ref(attempt / 'child-source-receipt.json'),
                          span_receipt=ref(attempt / 'spans/span-timing-receipt.json'), final_usage=final_usage)
        except BaseException as exc:
            report['error'] = {'type': type(exc).__name__, 'message': str(exc)[:3000]}
            if child is not None:
                try:
                    descendants.settle(child)
                    report.update(child_returncode=child.returncode, owned_descendants_dead=True,
                                  owned_descendant_identities=descendants.known, descendant_peak_rss_bytes=peak_rss)
                    if not (attempt / 'child-terminal.json').exists():
                        save(attempt / 'child-terminal.json', {'returncode': child.returncode, 'identity': identity, 'stopped_after_error': True})
                except BaseException as cleanup:
                    report['cleanup_error'] = {'type': type(cleanup).__name__, 'message': str(cleanup)[:2000]}
            try:
                report['prepared_inputs_unchanged'] = exact(frozen + evidence_inputs)
                report['scoped_sources'] = sources.verify()
                report['accelerate_dependency_after'] = verify_binding(DEPENDENCY)
                report['prior_ledger_claims_preserved'] = prior_rows_preserved(prior['reservations'], owner._read()['reservations'])
            except BaseException as drift:
                report['source_or_ledger_error'] = {'type': type(drift).__name__, 'message': str(drift)[:2000]}
        report['elapsed_seconds'] = time.monotonic() - started
        report['reservation_at_publication'] = owner.to_dict()
        save(attempt / 'audit-receipt.json', report); durable(attempt)
        if report['passed']:
            save(attempt / 'resource-release.json', owner.release(artifacts_durable=True)); durable(attempt)
    if not report['passed']:
        save(attempt / 'resource-retention.json', owner.to_dict()); durable(attempt)
    print(json.dumps({'passed': report['passed'], 'audit': str(attempt / 'audit-receipt.json')}), flush=True)
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
