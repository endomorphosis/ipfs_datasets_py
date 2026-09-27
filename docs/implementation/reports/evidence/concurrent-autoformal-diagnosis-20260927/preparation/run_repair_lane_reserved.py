"""Reserve 75 MB / 2 GiB / one CPU for one local, unapplied source proposal."""
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
    durable, environment, exact, ref, require, save, verify_binding)
from run_native_smoke_reserved import Descendants
STORAGE = 75_000_000
MEMORY_MB = 2048
SECONDS = 600
FILES = (HERE / 'repair_lane.py', HERE / 'run_repair_lane_reserved.py', HERE / 'repair-proposal-plan.json',
         HERE / 'harness/smoke_resource_common.py', HERE / 'harness/run_native_smoke_reserved.py',
         HERE / 'harness/dependency_binding.py', HERE / 'harness/frozen-config.json')


def proposal_environment(attempt):
    env = environment(attempt)
    for name in list(env):
        upper = name.upper()
        if ('TOKEN' in upper or 'API_KEY' in upper or upper.endswith('_PROXY') or
            upper.startswith(('GROK_', 'XAI_', 'OPENAI_'))):
            env.pop(name, None)
    env.update(IPFS_ACCELERATE_LLAMA_CPP_BASE_URL='http://172.17.0.1:8080/v1',
        IPFS_ACCELERATE_LLAMA_CPP_MODEL='leanstral_local',
        IPFS_ACCELERATE_LLAMA_CPP_AUTOSTART='0', IPFS_ACCELERATE_LLAMA_CPP_AUTO_INSTALL='0',
        IPFS_ACCELERATE_LLAMA_CPP_AUTO_UPDATE='0', IPFS_ACCELERATE_LLAMA_CPP_PREFETCH_MODEL='0',
        IPFS_ACCELERATE_LLAMA_CPP_NATIVE_AUTO_INSTALL='0',
        IPFS_ACCELERATE_PY_ROUTER_RESPONSE_CACHE='0', IPFS_DATASETS_PY_ROUTER_RESPONSE_CACHE='0',
        ipfs_accelerate_py_ROUTER_RESPONSE_CACHE='0',
        IPFS_ACCELERATE_LLM_ALLOCATION_DB=str(attempt / 'llm-allocation.duckdb'),
        IPFS_ACCELERATE_AGENT_ORCHESTRATION_DIR=str(attempt), NO_PROXY='172.17.0.1',
        IPFS_ACCELERATE_PY_LLM_PROVIDER='llama_cpp')
    # The host's approved package roots remain readable; no credentials are used.
    return env


def prior_rows_preserved(before, after):
    for key, old in before.items():
        require(key in after, 'prior ledger record disappeared')
        current = after[key]
        if old['status'] in {'released', 'retained'}:
            require(current == old, 'prior terminal storage claim changed')
        else:
            for field in ('reservation_id', 'storage_bytes', 'owner_pid', 'created_at', 'memory_mb', 'cpu_slots'):
                require(current.get(field) == old.get(field), 'prior active claim identity or capacity changed')
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--attempt', type=Path, required=True)
    parser.add_argument('--training-marker', type=Path, required=True)
    args = parser.parse_args()
    attempt, marker = args.attempt.absolute(), args.training_marker.absolute()
    allowed = ROOT / 'workspace/test-logs/federal-corpus-audits'
    require(attempt.is_relative_to(allowed) and attempt != allowed and attempt.resolve() == attempt,
            'proposal attempt must be within canonical owned audit root')
    require(not attempt.exists() and not attempt.is_symlink(), 'proposal attempt must be new')
    require(marker.is_relative_to(allowed) and marker.resolve() == marker, 'training marker outside owned audit root')
    require(not marker.exists(), 'new proposal must start before the new training method begins')
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    affinity = sorted(os.sched_getaffinity(0))
    require(affinity, 'CPU affinity unavailable')
    mem = dict(line.split(':', 1) for line in Path('/proc/meminfo').read_text().splitlines())
    require(int(mem['MemAvailable'].split()[0]) * 1024 >= MEMORY_MB * 1024**2, '2 GiB available host memory required')
    harness = [ref(path) for path in FILES]
    for path in FILES:
        if path.suffix == '.py': ast.parse(path.read_bytes(), filename=str(path))
    plan = json.loads((HERE / 'repair-proposal-plan.json').read_bytes())
    plan_inputs = [ref(plan['source_receipt']['path']), ref(plan['parser_source']['path'])]
    for actual, expected in zip(plan_inputs, (plan['source_receipt'], plan['parser_source']), strict=True):
        require(actual['sha256'] == expected['sha256'], 'frozen proposal evidence changed')
    dependency = verify_binding(DEPENDENCY)
    environment_map = proposal_environment(attempt)
    os.environ.clear(); os.environ.update(environment_map)
    # This owner performs no networking. The fresh child installs the narrow
    # local-only connection and exact HTTP-body observer before importing routers.
    def owner_network_guard(name, args):
        if name == 'socket.connect': raise RuntimeError('proposal resource owner cannot connect to a network')
    sys.addaudithook(owner_network_guard)
    sources = ScopedSources()
    sys.path[:0] = [str(ACCELERATE), str(ROOT)]
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_daemon_resources import DaemonResourceReservation, MAX_STORAGE_BYTES, _process, _group_usage
    require(MAX_STORAGE_BYTES == 75_000_000_000, 'campaign cap changed')
    roots = [ROOT / 'workspace/test-logs', ROOT / 'workspace/todo-queues', ROOT / 'docs/implementation/reports/evidence', Path('/tmp/pytest-of-barberb')]
    owner = DaemonResourceReservation(LEDGER, roots=roots, storage_bytes=STORAGE, memory_mb=MEMORY_MB,
                                     cpu_slots=1, timeout_seconds=0, ledger_lock_timeout_seconds=30)
    prior = owner._read(); capacity = owner._account(prior, additional=2 * STORAGE + 5_000_000)
    descendants = Descendants(_process)
    child = identity = None
    peak_rss = 0
    started = time.monotonic()
    report = {'schema': 'local-proposal-owned-resource-audit/v1', 'passed': False,
              'bounds': {'storage_bytes': STORAGE, 'memory_mb': MEMORY_MB, 'cpu_slots': 1, 'seconds': SECONDS},
              'capacity_plan': capacity, 'prepared_inputs': harness + plan_inputs,
              'accelerate_dependency': dependency, 'training_marker': str(marker),
              'admitted': False, 'formalized': False, 'applied': False,
              'network_policy': 'resource owner denies connections; child permits only 172.17.0.1:8080 and one exact generation payload',
              'shared_server_resources': 'Existing llama.cpp server is outside owned descendants; its pre-existing context/capacity is unchanged.',
              'enforcement': 'cooperative polled storage/RSS; Linux subreaper and PID-birth owned descendant cleanup'}
    with owner:
        attempt.mkdir(parents=True)
        try:
            for name in ('tmp', 'hub', 'cache'): (attempt / name).mkdir()
            save(attempt / 'prepared-inputs.json', {'files': harness + plan_inputs, 'dependency': DEPENDENCY})
            owner.check_usage(attempt)
            require(exact(harness + plan_inputs), 'proposal preparation changed before admission')
            with (attempt / 'repair-lane.log').open('x') as log:
                child = subprocess.Popen([sys.executable, '-u', '-B', str(HERE / 'repair_lane.py'),
                    '--runtime-root', str(attempt), '--training-marker', str(marker)], cwd=ROOT,
                    env=proposal_environment(attempt), stdin=subprocess.PIPE, stdout=log,
                    stderr=subprocess.STDOUT, start_new_session=True)
                row = _process(child.pid)
                require(row and row['parent_pid'] == os.getpid() and row['group_pid'] == child.pid, 'proposal child ownership differs')
                identity = {key: row[key] for key in ('pid', 'birth')}
                descendants.observe(); owner.check_usage(attempt, child.pid)
                require(owner.to_dict()['record']['child'] == identity, 'proposal child registration differs')
                os.sched_setaffinity(child.pid, {affinity[-1]})
                child.stdin.write(b'RUN\n'); child.stdin.flush(); child.stdin.close()
                last_usage = 0
                while child.poll() is None:
                    elapsed = time.monotonic() - started
                    require(elapsed < SECONDS, 'proposal outer deadline exceeded')
                    live = descendants.living(); rss = sum(x['rss_bytes'] for x in live)
                    peak_rss = max(peak_rss, rss)
                    require(rss <= MEMORY_MB * 1024**2, 'proposal owned descendant RSS exceeded 2 GiB')
                    if time.monotonic() - last_usage >= 10:
                        usage = owner.check_usage(attempt); last_usage = time.monotonic()
                        print(json.dumps({'elapsed_seconds': elapsed, 'attempt_bytes': usage['attempt_bytes'],
                                          'descendant_rss_bytes': rss, 'owned_live_processes': len(live)}), flush=True)
                    try: child.wait(timeout=.25)
                    except subprocess.TimeoutExpired: pass
                log.flush(); os.fsync(log.fileno())
            require(not descendants.living(), 'proposal child left owned living descendants')
            descendants.reap(child)
            save(attempt / 'child-terminal.json', {'returncode': child.returncode, 'identity': identity})
            report.update(child_returncode=child.returncode, owned_descendants_dead=True,
                          child_group_dead=_group_usage(identity)['live_processes'] == 0,
                          owned_descendant_identities=descendants.known, descendant_peak_rss_bytes=peak_rss)
            require(child.returncode == 0, 'proposal child failed; raw evidence retained')
            result = json.loads((attempt / 'proposal-receipt.json').read_bytes())
            require(result['passed'] is True and result['provider_calls'] == 1 and
                    result['native_task_completed'] is False and result['applied'] is False, 'proposal evidence contract failed')
            require(exact(harness + plan_inputs) and exact(result['scoped_sources']), 'proposal source provenance changed')
            report['accelerate_dependency_after'] = verify_binding(DEPENDENCY)
            report['scoped_sources'] = sources.verify()
            report['prior_ledger_claims_preserved'] = prior_rows_preserved(prior['reservations'], owner._read()['reservations'])
            report.update(passed=True, proposal_receipt=ref(attempt / 'proposal-receipt.json'), final_usage=owner.check_usage(attempt))
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
                report['prior_ledger_claims_preserved'] = prior_rows_preserved(prior['reservations'], owner._read()['reservations'])
                report['accelerate_dependency_after'] = verify_binding(DEPENDENCY)
                report['scoped_sources'] = sources.verify()
                report['prepared_inputs_unchanged'] = exact(harness + plan_inputs)
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
