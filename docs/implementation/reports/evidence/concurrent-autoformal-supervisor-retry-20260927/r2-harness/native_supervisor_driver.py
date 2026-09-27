#!/usr/bin/env python3
"""One real deterministic-only accelerate pass in a new private Git fixture.

Preparation file only until an admitted root-owned invocation executes main.
The native Portal bridge owns claim/effect/validation/completion. This script
never writes a task status or injects provider/validation callbacks.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import traceback

ROOT = Path('/home/barberb/lift_coding/external/ipfs_datasets')
from dependency_binding import read_binding, verify_binding
DEPENDENCY = read_binding(Path(__file__).resolve().parent / 'frozen-config.json')
ACCELERATE = Path(DEPENDENCY['root'])
GIT_ENV = ('GIT_INDEX_FILE', 'GIT_DIR', 'GIT_WORK_TREE', 'GIT_COMMON_DIR',
           'GIT_OBJECT_DIRECTORY', 'GIT_ALTERNATE_OBJECT_DIRECTORIES')
BUNDLE_FILES = ('parent_harness.py', 'training_lane.py', 'conversion_lane.py', 'frozen-config.json', 'dependency_binding.py', 'lane_bootstrap.py')

TEST_SOURCE = '''"""A real concurrent smoke, followed by immutable receipt revalidation."""
import hashlib
import importlib.util
import json
from pathlib import Path


def test_real_concurrent_autoformal_smoke():
    root = Path(__file__).resolve().parents[1]
    config = json.loads((root / 'smoke-config.json').read_bytes())
    for relative, expected in config['bundle_sha256'].items():
        assert hashlib.sha256((root / relative).read_bytes()).hexdigest() == expected
    path = root / 'harness' / 'parent_harness.py'
    spec = importlib.util.spec_from_file_location('concurrent_smoke_parent', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    output = Path(config['lane_directory'])
    report = module.check_existing(output) if output.exists() else module.run_smoke(output)
    assert report['passed'] is True
    assert report['admitted'] is False
    assert report['formalized'] is False
    assert report['production_promotion'] is False
    raw = (output / 'smoke-receipt.json').read_bytes()
    assert json.loads(raw) == report
    target = root / 'results' / 'smoke.json'
    target.parent.mkdir(exist_ok=True)
    if target.exists():
        assert target.read_bytes() == raw
    else:
        with target.open('xb') as stream:
            stream.write(raw)
    module.check_existing(output)
'''


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8') as stream:
        json.dump(value, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())


def git(repo, *args):
    env = dict(os.environ)
    for key in GIT_ENV:
        env.pop(key, None)
    return subprocess.check_output(['git', '-c', 'core.hooksPath=/dev/null', *args],
                                   cwd=repo, env=env, text=True).strip()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime-root', type=Path, required=True)
    parser.add_argument('--bundle-directory', type=Path, default=Path(__file__).parent)
    parser.add_argument('--implementation-timeout', type=int, default=480)
    args = parser.parse_args()
    dependency_observation = verify_binding(DEPENDENCY)
    if not 450 <= args.implementation_timeout <= 600:
        raise ValueError('native smoke timeout must remain within 450..600 seconds')
    runtime = args.runtime_root.absolute()
    if runtime.exists() or runtime.is_symlink():
        raise ValueError('runtime must be new; prior attempts are retained')
    for key in GIT_ENV:
        os.environ.pop(key, None)
    os.environ.update({
        'PYTHONDONTWRITEBYTECODE': '1', 'HF_HUB_OFFLINE': '1',
        'TRANSFORMERS_OFFLINE': '1', 'IPFS_DATASETS_PY_LAZY_INSTALL_ERGOAI': '0',
        'IPFS_DATASETS_LEGAL_IR_METRIC_DISK_CACHE': '0', 'CUDA_VISIBLE_DEVICES': '',
        'OMP_NUM_THREADS': '1', 'OPENBLAS_NUM_THREADS': '1', 'MKL_NUM_THREADS': '1',
        'IPFS_ACCELERATE_AGENT_WORKTREE_POOL_ENABLED': '0',
        'IPFS_ACCELERATE_AGENT_ORCHESTRATION_DIR': str(runtime),
        'PYTEST_DISABLE_PLUGIN_AUTOLOAD': '1',
    })
    sys.dont_write_bytecode = True
    runtime.mkdir(parents=True)
    tmp = runtime / 'tmp'
    tmp.mkdir()
    # The native Portal bridge seals its own attempt directory beneath this
    # existing parent and correctly refuses missing or symlinked parents.
    (runtime / 'state').mkdir()
    os.environ['TMPDIR'] = str(tmp)
    repo = runtime / 'repository'
    (repo / 'harness').mkdir(parents=True)
    (repo / 'tests').mkdir()
    bundle = args.bundle_directory.resolve(strict=True)
    hashes = {}
    for name in BUNDLE_FILES:
        source = bundle / name
        raw = source.read_bytes()
        if len(raw) > 1_000_000 or source.is_symlink():
            raise ValueError('fixture input must be bounded regular data: ' + name)
        relative = 'harness/' + name
        (repo / relative).write_bytes(raw)
        hashes[relative] = hashlib.sha256(raw).hexdigest()
        if sha(source) != hashes[relative]:
            raise RuntimeError('fixture source changed during preparation')
    (repo / 'tests/test_concurrent_smoke.py').write_text(TEST_SOURCE)
    (repo / '.gitignore').write_text('__pycache__/\n.pytest_cache/\n')
    (repo / 'pyproject.toml').write_text(
        '[project]\nname = "private-autoformal-concurrent-smoke"\nversion = "0.0.0"\n'
        'requires-python = ">=3.12"\n'
        'dependencies = ["pytest", "duckdb", "numpy", "pyarrow", "spacy"]\n'
    )
    write(repo / 'smoke-config.json', {
        'schema': 'concurrent-autoformal-native-fixture/v1',
        'lane_directory': str(runtime / 'lanes'), 'bundle_sha256': hashes,
        'scope': 'current compiler/decompiler checks and native autoencoder training; no code repair',
        'admitted': False, 'formalized': False, 'production_promotion': False,
    })
    git(repo, 'init', '--initial-branch=smoke-candidate')
    git(repo, 'config', 'user.name', 'Local Autoformal Smoke')
    git(repo, 'config', 'user.email', 'autoformal-smoke@localhost')
    paths = ['.gitignore', 'pyproject.toml', 'smoke-config.json',
             'tests/test_concurrent_smoke.py', *hashes]
    git(repo, 'add', '--', *paths)
    git(repo, '-c', 'commit.gpgsign=false', 'commit', '-m', 'Private concurrent autoformal smoke fixture')
    head = git(repo, 'rev-parse', 'HEAD')
    fixture_sha = {path: sha(repo / path) for path in paths}
    write(runtime / 'fixture-manifest.json', {'head': head, 'files': fixture_sha})
    # Both trees are explicit. Never accept an already-imported foreign package.
    sys.path.insert(0, str(ROOT / 'scripts/ops/legal_ir'))
    from run_autoformal_supervisor import pin_accelerate, require_native_transition_contract
    pin = pin_accelerate(ACCELERATE)
    from ipfs_datasets_py.logic.autoformal.tree_pin import require_workspace_logic_tree
    tree_pin = require_workspace_logic_tree()
    require_native_transition_contract()
    from ipfs_accelerate_py.agent_supervisor.task_sources.control_plane_contracts import content_identity
    from ipfs_accelerate_py.agent_supervisor.task_sources.database_task_source import DatabaseTaskSource
    from ipfs_accelerate_py.agent_supervisor.todo_daemon.implementation_daemon import parse_args
    from ipfs_accelerate_py.agent_supervisor.todo_daemon.implementation_daemon_runner import build_portal_implementation_daemon_from_args
    task_cid = content_identity({'schema': 'concurrent-autoformal-smoke-task/v1',
                                'repository_tree_id': head, 'fixture_sha256': fixture_sha})
    task_id = 'SMOKE-' + hashlib.sha256(task_cid.encode()).hexdigest()[:20]
    database = runtime / 'supervisor.duckdb'
    task = {
        'task_cid': task_cid, 'task_id': task_id, 'status': 'ready',
        'title': 'Execute and verify concurrent autoformal smoke',
        'board_namespace': 'concurrent-autoformal-smoke-v1',
        'completion': 'auto', 'priority': 'P1', 'track': 'bounded-validation',
        'provider_role': 'deterministic-only', 'context_budget_tokens': 4096,
        'is_schedulable': True, 'review_only': False,
        'outputs': [{'path': 'results/smoke.json'}],
        'validation_commands': [{'argv': ['python3', '-m', 'pytest', 'tests/test_concurrent_smoke.py', '-q']}],
        'acceptance_criteria': ['The declared test runs both real lanes concurrently and verifies all retained receipts. Completion applies only to this smoke task, never legal admission or model promotion.'],
    }
    with DatabaseTaskSource(database) as source:
        source.materialize({'repository_tree_id': head, 'tasks': [task]})
        before = source.snapshot().to_dict()
    write(runtime / 'task.json', task)
    argv = [
        '--todo-path', str(database), '--state-dir', str(runtime / 'state'),
        '--task-prefix', 'SMOKE-', '--board-namespace', 'concurrent-autoformal-smoke-v1',
        '--state-prefix', 'smoke', '--task-source-kind', 'duckdb', '--authority-mode', 'embedded',
        '--state-store-id', 'concurrent-autoformal-smoke-' + task_id,
        '--state-failover-policy', 'fail_closed', '--implementation-timeout', str(args.implementation_timeout),
        '--max-task-attempts', '1', '--implement', '--once', '--no-ephemeral-worktree',
        '--merge-target-branch', 'smoke-candidate', '--merge-queue-dir', str(runtime / 'merge-queue'),
        '--merged-worktree-cleanup-max', '0', '--retain-worktree-artifacts',
        '--validation-max-workers', '1', '--validation-resource-budget', '1',
    ]
    for path in paths:
        argv.extend(['--implementation-protected-path', path])
    write(runtime / 'native-arguments.json', argv)
    started = time.monotonic()
    daemon, result, error = None, None, None
    try:
        daemon, _context = build_portal_implementation_daemon_from_args(parse_args(argv), repo_root=repo)
        if not daemon.require_real_execution or not daemon.execution_callbacks_bound:
            raise RuntimeError('native real-execution bridge is not bound')
        result = daemon.run_once()
    except Exception as exc:
        error = {'type': type(exc).__name__, 'message': str(exc), 'traceback': traceback.format_exc()}
    finally:
        if daemon is not None:
            daemon.close_event_runtime()
            daemon.close()
    with DatabaseTaskSource(database, install_schema=False) as source:
        record = source.get(task_cid)
        after = source.snapshot().to_dict()
    summary = {
        'schema': 'concurrent-autoformal-native-supervisor-smoke/v1',
        'scope': 'deterministic-only smoke task; no compiler code repair',
        'passed': error is None and record is not None and record.status == 'completed',
        'native_result': result, 'error': error, 'native_task': None if record is None else record.to_dict(),
        'before': before, 'after': after, 'elapsed_seconds': time.monotonic() - started,
        'accelerate_pin': pin, 'logic_pin': tree_pin,
        'accelerate_dependency': dependency_observation,
        'accelerate_dependency_after': verify_binding(DEPENDENCY),
        'authority_mode': 'embedded-single-owner', 'quack_transport_exercised': False,
        'admitted': False, 'formalized': False, 'production_promotion': False,
    }
    write(runtime / 'supervisor-receipt.json', summary)
    print(json.dumps({'passed': summary['passed'], 'task_status': record.status if record else None,
                      'error': error, 'receipt': str(runtime / 'supervisor-receipt.json')}, sort_keys=True), flush=True)
    return 0 if summary['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
